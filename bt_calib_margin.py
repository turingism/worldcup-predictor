#!/usr/bin/env python3
"""净胜球/比分校准 现状测量基线（只量不改，给改法定位偏差来源）。

测什么（样本外 as-of，世界杯正赛）
--------------------------------
1) 净胜球(margin=主-客)分布校准：模型预测 P(d) vs 实际频率（逐档 + 尾部），
   + 标准化残差 z=(实际-E)/SD 的均值/方差（var(z)>1=欠离散/过度自信，<1=过离散）。
2) 让球 RPS：按现有让球档位（_HANDI_LINES 整/半档）模型 cover 概率 vs 实际打出。
3) correct-score LogLoss：-log P(精确比分)。
+ 平局格(margin=0) 与 大比分尾部(|d|>=3) 单独标定，定位偏得最狠的区间。

双口径
------
- 含加时：results.csv 记分（我们买的就是这个，主口径）。
- 90 分钟：Fjelstul 90 分钟重构（bt_knockout）联结同场，仅 ≤2022 留个底参照。

零碰 GLM：用 model.predict 的现成矩阵，纯测量。
"""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd

import data as datamod
from model import DixonColesModel, MAX_GOALS
import manager
from backtest import _rps

# 各届世界杯：cutoff（赛前冻结）+ 窗口。含加时口径用全部；90 分钟仅 ≤2022。
WC_WINDOWS = [
    ("2014", dt.date(2014, 6, 11), dt.date(2014, 7, 14)),
    ("2018", dt.date(2018, 6, 13), dt.date(2018, 7, 16)),
    ("2022", dt.date(2022, 11, 19), dt.date(2022, 12, 19)),
    ("2026G", dt.date(2026, 6, 10), dt.date(2026, 7, 1)),   # 2026 已踢小组赛（仅含加时）
]
HANDI_LINES = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0]   # 整/半档（actual 干净 win/push/lose）


def collect(half_life=730.0):
    """as-of 训练、预测各届 WC 正赛，收集每场 (M, 实际含加时比分, 元信息)。"""
    df = datamod.load_raw()
    recs = []
    for tag, cutoff, end in WC_WINDOWS:
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        pl = datamod.played(df)
        sel = pl[(pl.date > pd.Timestamp(cutoff)) & (pl.date <= pd.Timestamp(end))
                 & (pl.tournament == "FIFA World Cup")]
        for _, r in sel.iterrows():
            try:
                pr = m.predict(r.home_team, r.away_team, neutral=bool(r.neutral))
            except KeyError:
                continue
            recs.append({"tag": tag, "date": pd.Timestamp(r.date).date(),
                         "home": r.home_team, "away": r.away_team,
                         "M": pr["matrix"], "p_home": pr["p_home"], "p_away": pr["p_away"],
                         "hs": int(r.home_score), "as": int(r.away_score)})
    return recs


def _margin_metrics(recs, hs_key, as_key, label):
    """对给定真实比分口径(hs_key/as_key)算 margin/比分/平局/尾部 校准。"""
    n = len(recs)
    # 1) margin 分布校准：预测均概 vs 实际频率
    ds = range(-6, 7)
    pred = {d: 0.0 for d in ds}; act = {d: 0.0 for d in ds}
    cs_ll = 0.0
    zs = []                          # 标准化残差
    p_draw_pred = a_draw = 0.0
    p_tail_pred = a_tail = 0.0       # |d|>=3
    for r in recs:
        mp = manager._margin_pmf(r["M"])
        for d in ds:
            pred[d] += mp.get(d, 0.0)
        # 实际
        hs, as_ = r[hs_key], r[as_key]
        d_act = hs - as_
        for d in ds:
            if d == max(-6, min(6, d_act)):
                act[d] += 1.0
        # correct-score LL（截断到矩阵范围）
        i, j = min(hs, MAX_GOALS), min(as_, MAX_GOALS)
        cs_ll += -np.log(max(float(r["M"][i, j]), 1e-12))
        # 标准化残差
        em = sum(k * p for k, p in mp.items())
        ev = sum((k - em) ** 2 * p for k, p in mp.items())
        if ev > 1e-9:
            zs.append((d_act - em) / np.sqrt(ev))
        # 平局格 / 尾部
        p_draw_pred += mp.get(0, 0.0); a_draw += (d_act == 0)
        p_tail_pred += sum(p for k, p in mp.items() if abs(k) >= 3); a_tail += (abs(d_act) >= 3)
    pred = {d: v / n for d, v in pred.items()}; act = {d: v / n for d, v in act.items()}
    zs = np.array(zs)
    return {
        "label": label, "n": n,
        "cs_logloss": cs_ll / n,
        "z_mean": float(zs.mean()), "z_var": float(zs.var()),
        "draw_pred": p_draw_pred / n, "draw_act": a_draw / n,
        "tail_pred": p_tail_pred / n, "tail_act": a_tail / n,
        "margin_pred": pred, "margin_act": act,
    }


def _handicap_rps(recs, hs_key, as_key):
    """按让球档位：模型 cover(win/push/lose) 概率 vs 实际，出 per-line RPS + 校准。"""
    out = []
    for line in HANDI_LINES:
        rps = 0.0; n = 0; cover_pred = cover_act = 0.0
        for r in recs:
            fav_is_home = r["p_home"] >= r["p_away"]
            mp = manager._margin_pmf(r["M"])
            s = manager.settle_line(mp, fav_is_home, line)   # 模型 win/push/lose
            # 实际：强队让 line 后净胜
            m_fav = (r[hs_key] - r[as_key]) if fav_is_home else (r[as_key] - r[hs_key])
            adj = m_fav - line
            oc = 0 if adj > 1e-9 else (1 if abs(adj) < 1e-9 else 2)   # win/push/lose 有序
            rps += _rps(s["win"], s["push"], s["lose"], oc)
            cover_pred += s["win"]; cover_act += (oc == 0)
            n += 1
        out.append({"line": line, "rps": rps / n, "cover_pred": cover_pred / n,
                    "cover_act": cover_act / n})
    return out


def _attach_90min(recs):
    """联结 Fjelstul 90 分钟重构比分（仅 ≤2022 有），写 h90/a90；返回匹配数。"""
    import bt_knockout
    m90 = bt_knockout.reconstruct_90min()
    # 别名归一（两边变体都映到同一规范名）后按 (date, frozenset{home,away}) 建索引
    canon = {"south korea": "korea", "korea republic": "korea",
             "iran": "iran", "ir iran": "iran",
             "ivory coast": "ivorycoast", "côte d'ivoire": "ivorycoast", "cote d'ivoire": "ivorycoast",
             "united states": "usa", "usa": "usa",
             "czech republic": "czech", "czechia": "czech",
             "china": "china", "china pr": "china"}
    def norm(s):
        s = str(s).strip().lower()
        return canon.get(s, s)
    idx = {}
    for _, r in m90.iterrows():
        key = (pd.Timestamp(r.match_date).date(),
               frozenset({norm(r.home_team_name), norm(r.away_team_name)}))
        idx[key] = (int(r.h90), int(r.a90), r.home_team_name)
    matched = 0
    for r in recs:
        key = (r["date"], frozenset({norm(r["home"]), norm(r["away"])}))
        if key in idx:
            h90, a90, fj_home = idx[key]
            # 对齐主客方向（Fjelstul 主队可能与 results 相反）
            if norm(fj_home) == norm(r["home"]):
                r["h90"], r["a90"] = h90, a90
            else:
                r["h90"], r["a90"] = a90, h90
            matched += 1
    return matched


def _fmt_margin(mm):
    line = "    d:   "
    pr = "    预测:"
    ac = "    实际:"
    df = "    差 :"
    for d in range(-4, 5):
        line += f"{d:>7}"
        pr += f"{mm['margin_pred'][d]*100:>7.1f}"
        ac += f"{mm['margin_act'][d]*100:>7.1f}"
        df += f"{(mm['margin_pred'][d]-mm['margin_act'][d])*100:>+7.1f}"
    return "\n".join([line, pr + "  (%)", ac + "  (%)", df + "  (pp)"])


def main():
    print("收集 as-of 预测（2014/2018/2022/2026G 世界杯正赛，half_life=730）…")
    recs = collect()
    print(f"样本：{len(recs)} 场。分布：" +
          ", ".join(f"{t}={sum(1 for r in recs if r['tag']==t)}" for t in ("2014","2018","2022","2026G")))

    print("\n" + "=" * 64 + "\n【含加时口径】（results.csv，主口径=我们买的盘）\n" + "=" * 64)
    inc = _margin_metrics(recs, "hs", "as", "含加时")
    print(f"  correct-score LogLoss = {inc['cs_logloss']:.4f}")
    print(f"  标准化残差 z: mean={inc['z_mean']:+.3f}  var={inc['z_var']:.3f}  "
          f"({'欠离散/过度自信' if inc['z_var']>1.1 else ('过离散' if inc['z_var']<0.9 else '离散合理')})")
    print(f"  平局格(d=0): 预测 {inc['draw_pred']*100:.1f}% vs 实际 {inc['draw_act']*100:.1f}%  "
          f"({(inc['draw_pred']-inc['draw_act'])*100:+.1f}pp)")
    print(f"  大比分尾部(|d|>=3): 预测 {inc['tail_pred']*100:.1f}% vs 实际 {inc['tail_act']*100:.1f}%  "
          f"({(inc['tail_pred']-inc['tail_act'])*100:+.1f}pp)")
    print("  净胜球分布校准（主-客）:")
    print(_fmt_margin(inc))
    # 偏得最狠的档
    worst = max(range(-6, 7), key=lambda d: abs(inc['margin_pred'][d]-inc['margin_act'][d]))
    print(f"  → 偏差最大档 d={worst}: 预测 {inc['margin_pred'][worst]*100:.1f}% vs 实际 "
          f"{inc['margin_act'][worst]*100:.1f}% ({(inc['margin_pred'][worst]-inc['margin_act'][worst])*100:+.1f}pp)")

    print("\n  让球 RPS（按档位，站模型判定的强队角度）:")
    print(f"    {'让球线':>7}{'RPS↓':>9}{'模型cover':>11}{'实际cover':>11}{'校准差':>9}")
    for h in _handicap_rps(recs, "hs", "as"):
        print(f"    {h['line']:>7.1f}{h['rps']:>9.4f}{h['cover_pred']*100:>10.1f}%"
              f"{h['cover_act']*100:>10.1f}%{(h['cover_pred']-h['cover_act'])*100:>+8.1f}pp")

    print("\n" + "=" * 64 + "\n【90 分钟口径】（Fjelstul 重构，仅 ≤2022，留个底）\n" + "=" * 64)
    matched = _attach_90min(recs)
    r90 = [r for r in recs if "h90" in r]
    print(f"  匹配到 90 分钟比分的场次：{len(r90)}/{len(recs)}（2026 无 Fjelstul 数据，正常）")
    if r90:
        n90 = _margin_metrics(r90, "h90", "a90", "90分钟")
        inc90 = _margin_metrics(r90, "hs", "as", "含加时(同子集)")
        print(f"  [90分钟]   CS-LogLoss={n90['cs_logloss']:.4f}  z_var={n90['z_var']:.3f}  "
              f"平局 预测{n90['draw_pred']*100:.1f}% vs 实际{n90['draw_act']*100:.1f}%  "
              f"尾部 预测{n90['tail_pred']*100:.1f}% vs 实际{n90['tail_act']*100:.1f}%")
        print(f"  [含加时同子集] CS-LogLoss={inc90['cs_logloss']:.4f}  z_var={inc90['z_var']:.3f}  "
              f"平局 预测{inc90['draw_pred']*100:.1f}% vs 实际{inc90['draw_act']*100:.1f}%  "
              f"尾部 预测{inc90['tail_pred']*100:.1f}% vs 实际{inc90['tail_act']*100:.1f}%")
    print("\n  注：纯测量基线、零碰 GLM；先定位偏差来源再谈改法。个人/教育项目，非投注建议。")


if __name__ == "__main__":
    main()
