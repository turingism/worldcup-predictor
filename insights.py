"""
解读层：把『模型 vs 名气(Elo) 偏差』+ 伤病暴露(#1) + 环境暴露(#2) 合成每队诚实叙事。

定位：纯展示/解释层，**不参与任何概率计算**。灵感来自 Kimi 报告的『被低估/高估』与
黑天鹅叙事，但我们没有赔率源，故改用**本项目自有的两套排序之差**做锚：
  - 我方 DC 蒙特卡洛夺冠排名（信近期场上证据）
  - Elo 排名（信传递性声誉/历史）
二者背离最大的队，正是本届最『叙事复杂』、预测分歧最大的队——这恰是对标 Kimi 时
发现的核心洞察（挪威被名气低估、法国被高估）的产品化。
"""
from __future__ import annotations
import env as envmod
import teams_zh


def _elo_rank(elo_ratings: dict, participants) -> dict:
    """只在参赛 48 队内部排 Elo —— 与我方夺冠排名同口径（都是 48 队内），可比。"""
    pool = [t for t in participants if t in elo_ratings]
    order = sorted(pool, key=lambda t: elo_ratings.get(t, 0), reverse=True)
    return {t: i + 1 for i, t in enumerate(order)}


def _group_env(team: str, sim) -> dict:
    """该队小组赛途经的高温/高原场馆，及其适应身份。"""
    cfg = envmod._cfg()
    cities = {c for (h, a), c in sim.group_city.items() if team in (h, a) and c}
    hot = sorted(c for c in cities if (cfg["geo"].get(c, {}) or {}).get("heat") in ("extreme", "high"))
    alt = sorted(c for c in cities if (cfg["geo"].get(c, {}) or {}).get("alt", 0) >= 1200)
    return {"hot": hot, "alt": alt,
            "adapted": team in cfg["alt_adapted"], "cool": team in cfg["cool"]}


def build(champ_rows_en, model, sim, elo_ratings, topn=12):
    """champ_rows_en: [(team_en, champ, final, sf, qf, ko), ...] 已按夺冠降序。
    返回 topn 支队的解读 dict 列表。"""
    er = _elo_rank(elo_ratings, [row[0] for row in champ_rows_en])
    out = []
    for rank, row in enumerate(champ_rows_en[:topn], 1):
        t, ch = row[0], row[1]
        elo_r = er.get(t)
        div = (elo_r - rank) if elo_r else None   # >0：我方排名比 Elo 高（模型更看好）
        ia = model.avail_att.get(t, 1.0)
        idf = model.avail_def.get(t, 1.0)
        ev = _group_env(t, sim)
        tags, notes = [], []

        # 1) 模型 vs 名气
        if div is not None and div >= 3:
            tags.append("模型超配")
            notes.append(f"模型比名气更看好（Elo 第 {elo_r}、我方第 {rank}）：近期进攻数据强于其声誉，"
                         f"但更依赖近期状态，方差偏高。")
        elif div is not None and div <= -3:
            tags.append("模型低配")
            notes.append(f"模型比名气更看衰（Elo 第 {elo_r}、我方第 {rank}）：Elo 声誉靠前，"
                         f"但近期场上数据未兑现。")
        else:
            notes.append("模型与 Elo 共识基本一致。")

        # 2) 伤病暴露（#1）
        if ia < 0.97 or idf > 1.03:
            who = ", ".join(i["player"] for i in _avail_items(t))
            tags.append("伤病拖累")
            notes.append(f"关键球员缺阵已下调其 xG（进攻×{ia:.3f}{'、失球×'+format(idf,'.3f') if idf>1 else ''}：{who}）。")

        # 3) 环境暴露（#2）
        if ev["cool"] and ev["hot"]:
            tags.append("热环境税")
            notes.append(f"小组赛途经 {('、'.join(ev['hot']))} 等高温场馆，欧洲球队体能折损更大。")
        if ev["alt"] and not ev["adapted"]:
            tags.append("高原折损")
            notes.append(f"需在 {('、'.join(ev['alt']))} 高原作战，非适应球队下半场冲刺衰减。")
        if ev["alt"] and ev["adapted"]:
            tags.append("高原加成")
            notes.append(f"高原适应是其在 {('、'.join(ev['alt']))} 的潜在加成。")

        out.append({
            "rank": rank, "team": teams_zh.disp(t), "champ": ch,
            "elo_rank": elo_r, "divergence": div, "tags": tags,
            "note": " ".join(notes),
        })
    return out


# availability 明细按队取（避免 build 里反复读盘）
_AVAIL_ITEMS = None


def _avail_items(team_en):
    global _AVAIL_ITEMS
    if _AVAIL_ITEMS is None:
        import adjust
        _AVAIL_ITEMS = adjust.team_modifiers()
    m = _AVAIL_ITEMS.get(team_en)
    return m["items"] if m else []
