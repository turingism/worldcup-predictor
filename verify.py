"""Prediction verification layer: pre-match prediction ledger (frozen before kickoff) + finished-match prediction-vs-actual stats.

预测验证层：预测留痕（开球前冻结） + 已完赛「预测 vs 实际」对比统计。

诚实性铁律（与 backtest 同口径，杜绝事后改口）：
  1) 每场预测在【开球前】写入 data/predictions.json（账本）；开球后条目永不修改。
     开球前模型若因新赛果重训，允许覆盖更新（始终是"赛前最新认知"）。
  2) 账本缺失但已完赛的场次（app 没开着的时候踢完的），用【只含该场开球前数据】
     训练的回溯模型补预测（as_of = 比赛日前一天），标 retro=True——绝不偷看结果。
     回溯模型为纯引擎 + 东道主/环境乘子，不含伤病层（无法还原当时的名单状态）。
  3) 账本存完整比分概率矩阵 → 事后可算"赋予实际比分/赛果的概率"，校准可证伪。

用法：
    python3 verify.py            # CLI：冻结未开赛预测 + 回补 + 打印对比报告
    app.py 的 /api/verify        # 网页「预测验证」tab 数据源
"""
from __future__ import annotations
import datetime as dt
import json
import os

import numpy as np

import data as datamod
import env

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "data", "predictions.json")
GROUP_END = "2026-06-28"          # 小组赛阶段截止（与 simulate.py 同口径）
_RETRO_CACHE: dict[str, object] = {}   # as_of 日期 -> 回溯模型（进程内缓存）


# ---------- 账本 ----------
def load_ledger(path: str = LEDGER_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        preds = d.get("preds", {})
        return preds if isinstance(preds, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_ledger(preds: dict, path: str = LEDGER_PATH):
    """原子写（先 .tmp 再 replace），坏档不覆盖好档。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "preds": preds}, f, ensure_ascii=False)
    os.replace(tmp, path)


def _gkey(h: str, a: str) -> str:
    return f"G|{h}|{a}"               # 小组赛：官方赛程主客序，唯一


def _kkey(a: str, b: str) -> str:
    return "K|" + "|".join(sorted((a, b)))   # 淘汰赛：顺序无关（单淘汰同对阵只遇一次）


def _now_bj() -> str:
    """北京时间 'YYYY-MM-DD HH:MM'（schedule 全部为北京时间口径）。"""
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(hours=8)).strftime("%Y-%m-%d %H:%M")


def bj_date(kickoff: str | None, fallback: str | None = "") -> str:
    """展示用比赛日（**北京日**）：kickoff 存的是北京时间 'YYYY-MM-DD HH:MM'，取其日期部分。
    全站日期分组/显示统一走它，避免凌晨开球的场次（北京日 > 场馆当地日）按当地日落到前一天
    ——这个 off-by-one 反复修过多次，集中到此函数 + 单测守住口径。无 kickoff 时回落 fallback。"""
    return kickoff[:10] if kickoff else (fallback or "")


# ---------- 单场预测（a 视角，含东道主主场 + 环境乘子；与 simulate._pmf 同口径） ----------
def pair_predict(model, a: str, b: str, host=None, city=None, use_env=True) -> dict:
    em = None
    if use_env and city:
        ma, mb = env.match_mult(a, b, city)
        em = (ma, mb) if (ma != 1.0 or mb != 1.0) else None
    if host == a:
        r = model.predict(a, b, neutral=False, env_mult=em)
        M = r["matrix"]
        pa_, pd_, pb_ = r["p_home"], r["p_draw"], r["p_away"]
        xa, xb = r["xg_home"], r["xg_away"]
    elif host == b:                    # b 为主 → 反向预测后转置回 a 视角
        emb = (em[1], em[0]) if em else None
        r = model.predict(b, a, neutral=False, env_mult=emb)
        M = r["matrix"].T
        pa_, pd_, pb_ = r["p_away"], r["p_draw"], r["p_home"]
        xa, xb = r["xg_away"], r["xg_home"]
    else:
        r = model.predict(a, b, neutral=True, env_mult=em)
        M = r["matrix"]
        pa_, pd_, pb_ = r["p_home"], r["p_draw"], r["p_away"]
        xa, xb = r["xg_home"], r["xg_away"]
    i, j = np.unravel_index(int(M.argmax()), M.shape)
    return {"gh": int(i), "ga": int(j),
            "p_home": round(float(pa_), 5), "p_draw": round(float(pd_), 5),
            "p_away": round(float(pb_), 5),
            "xg_home": round(float(xa), 3), "xg_away": round(float(xb), 3),
            "matrix": [[round(float(x), 5) for x in row] for row in M]}


# ---------- 冻结：把所有未开球场次的当前预测写入账本 ----------
def freeze(sim, now_bj: str | None = None, verbose=False) -> int:
    """对所有【尚未开球】的本届场次写入/更新预测（开球后永不触碰）。
    小组赛 72 场始终可冻结；淘汰赛仅在对阵真实确定（drawn）后冻结。
    返回本次写入/更新的条目数。"""
    import schedule
    now = now_bj or _now_bj()
    preds = load_ledger()
    n = 0

    def upsert(key, stage, h, a, kickoff, date, host, city):
        nonlocal n
        if kickoff and kickoff <= now:          # 已开球：冻结，永不再写
            return
        try:
            p = pair_predict(sim.m, h, a, host, city, use_env=getattr(sim, "use_env", True))
        except KeyError:                         # 队不在模型（样本不足），跳过
            return
        old = preds.get(key)
        ent = {"stage": stage, "home": h, "away": a, "kickoff": kickoff, "date": date,
               "host": host, "city": city, "retro": False,
               "frozen_at": now, **p}
        # 预测内容没变就不动（避免无谓的磁盘写与 frozen_at 抖动）
        if old and all(old.get(k) == ent[k] for k in
                       ("gh", "ga", "p_home", "p_draw", "p_away", "home", "away")):
            return
        preds[key] = ent
        n += 1

    # 小组赛：官方赛程全量
    for ps in sim.fixtures.values():
        for (h, a) in ps:
            if (h, a) in sim.actual_results:     # 已完赛（账本里该有赛前条目，没有走回补）
                continue
            kickoff = schedule.GROUP.get((h, a), "")
            upsert(_gkey(h, a), "group", h, a, kickoff,
                   kickoff[:10] or sim.fixture_date.get((h, a), ""),  # 北京开球日（与 KO 一致，不用场馆当地日）
                   sim.group_host.get((h, a)), sim.group_city.get((h, a)))

    # 淘汰赛：仅对阵已真实确定（drawn=True 且非投影假设）的场次
    proj = sim.project(today=now[:10])
    for rd in proj["rounds"]:
        for m in rd["matches"]:
            if not m.get("drawn") or m.get("set"):   # 未抽签 / 已有结果
                continue
            mn = m.get("mn")
            a, b = m["a"], m["b"]
            kickoff = schedule.KO.get(mn, "")
            upsert(_kkey(a, b), rd["name"], a, b, kickoff, kickoff[:10],
                   sim._ko_host(mn, a, b), sim.ko_city.get(mn))

    if n:
        save_ledger(preds)
        if verbose:
            print(f"[verify] 冻结/更新 {n} 场赛前预测（账本共 {len(preds)} 条）")
    return n


# ---------- 回补：已完赛但账本缺失的场次，用"只含开球前数据"的回溯模型补 ----------
def _retro_model(df, as_of: str, half_life: float, verbose=True):
    if as_of not in _RETRO_CACHE:
        from model import DixonColesModel
        if verbose:
            print(f"[verify] 训练回溯模型 as_of={as_of}（只含该日及之前数据，约 10s）...")
        _RETRO_CACHE[as_of] = DixonColesModel(half_life_days=half_life).fit(
            df, verbose=False, as_of=dt.date.fromisoformat(as_of))
    return _RETRO_CACHE[as_of]


def _completed(sim, df) -> list[dict]:
    """本届已完赛场次（含账本 key、实际比分、日期）。小组赛用官方主客序。"""
    out = []
    wp = datamod.played(df)
    wp = wp[(wp["tournament"] == "FIFA World Cup") & (wp["date"].dt.year >= 2026)]
    canon = {frozenset(p): p for ps in sim.fixtures.values() for p in ps}
    teams48 = set(sim.all_teams)
    for _, r in wp.iterrows():
        h, a = r["home_team"], r["away_team"]
        gh, ga = int(r["home_score"]), int(r["away_score"])
        date = r["date"].strftime("%Y-%m-%d")
        cp = canon.get(frozenset((h, a)))
        if cp and date < GROUP_END:              # 小组赛（淘汰赛可能重演小组对阵，按日期区分）
            if cp != (h, a):
                h, a, gh, ga = a, h, ga, gh
            out.append({"key": _gkey(h, a), "stage": "group", "home": h, "away": a,
                        "gh": gh, "ga": ga, "date": date,
                        "host": sim.group_host.get((h, a)), "city": sim.group_city.get((h, a))})
        elif h in teams48 and a in teams48:      # 淘汰赛
            host = None if r.get("neutral", True) else h
            out.append({"key": _kkey(h, a), "stage": "KO", "home": h, "away": a,
                        "gh": gh, "ga": ga, "date": date,
                        "host": host, "city": r.get("city") or None})
    out.sort(key=lambda x: x["date"])
    return out


def backfill(sim, df, verbose=True) -> int:
    """给账本缺失的已完赛场次补回溯预测（retro=True）。返回补的条数。"""
    preds = load_ledger()
    done = _completed(sim, df)
    half_life = getattr(sim.m, "half_life_days", 730.0)
    n = 0
    for c in done:
        if c["key"] in preds:
            continue
        as_of = (dt.date.fromisoformat(c["date"]) - dt.timedelta(days=1)).isoformat()
        m = _retro_model(df, as_of, half_life, verbose=verbose)
        try:
            p = pair_predict(m, c["home"], c["away"], c["host"], c["city"],
                             use_env=getattr(sim, "use_env", True))
        except KeyError:
            continue
        preds[c["key"]] = {"stage": c["stage"], "home": c["home"], "away": c["away"],
                           "kickoff": "", "date": c["date"], "host": c["host"],
                           "city": c["city"], "retro": True, "as_of": as_of,
                           "frozen_at": _now_bj(), **p}
        n += 1
    if n:
        save_ledger(preds)
        if verbose:
            print(f"[verify] 回补 {n} 场已完赛的回溯预测")
    return n


# ---------- 评估：预测 vs 实际 ----------
# 置信度分桶 + 冷门口径（纯展示，不影响预测引擎）
CONF_HIGH = 0.60      # 模型对头号选项 ≥60% → 高把握
CONF_MID = 0.45       # 45–60% → 中等；<45% → 硬币局（三向接近均势）
UPSET_MAJOR = 0.70    # 头号热门 ≥70% 却没踢出 → 大冷门
UPSET_MINOR = CONF_HIGH  # 60–70% 却没踢出 → 冷门


def _outcome(gh: int, ga: int) -> str:
    return "H" if gh > ga else ("A" if ga > gh else "D")


def _conf_band(conf: float) -> str:
    return "high" if conf >= CONF_HIGH else ("mid" if conf >= CONF_MID else "coin")


def _miss_type(pick: str, actual: str) -> str | None:
    """失手归因：被逼平 / 选错胜方 / 押了平局却分胜负。命中返回 None。"""
    if pick == actual:
        return None
    if actual == "D":
        return "draw"            # 模型选了某队胜，实际打平（argmax 几乎永不出平局，结构性丢分）
    if pick == "D":
        return "picked_draw"     # 模型押平，实际分出胜负
    return "wrong_winner"        # 模型押了一方，另一方赢了（真·看走眼）


def _rps(ph, pd_, pa, o: str) -> float:
    """Ranked Probability Score（3 档：胜/平/负，越小越好）。"""
    oh, od = (o == "H") * 1.0, (o == "D") * 1.0
    c1, a1 = ph, oh
    c2, a2 = ph + pd_, oh + od
    return 0.5 * ((c1 - a1) ** 2 + (c2 - a2) ** 2)


def evaluate(sim, df) -> dict:
    """已完赛逐场对比 + 汇总统计。不做任何训练/写盘（freeze/backfill 先行）。"""
    preds = load_ledger()
    done = _completed(sim, df)
    rows, miss = [], 0
    for c in done:
        e = preds.get(c["key"])
        if not e:
            miss += 1
            continue
        # 实际比分换到账本条目的主客序（KO 的 key 顺序无关，条目序可能与数据行相反）
        gh, ga = c["gh"], c["ga"]
        if (e["home"], e["away"]) != (c["home"], c["away"]):
            gh, ga = ga, gh
        act = _outcome(gh, ga)
        # 赛果判定用三向概率最大者（与"预测比分"的胜平负方向几乎总一致，平局边界除外）
        probs = {"H": e["p_home"], "D": e["p_draw"], "A": e["p_away"]}
        pick = max(probs, key=probs.get)
        conf = probs[pick]                      # 模型对头号选项的置信度
        hit = pick == act
        M = e.get("matrix") or []
        p_act_score = (M[gh][ga] if gh < len(M) and ga < len(M) else 0.0) if M else None
        miss_type = _miss_type(pick, act)
        upset = (not hit) and conf >= CONF_HIGH  # 头号热门没踢出 → 冷门
        rows.append({
            # 显示日期统一走 bj_date（北京开球日），与看板/赛程口径一致；retro 无 kickoff 才回落账本/数据集日。
            "date": bj_date(e.get("kickoff"), e.get("date") or c["date"]),
            "stage": e["stage"],
            "home": e["home"], "away": e["away"],
            "pred_gh": e["gh"], "pred_ga": e["ga"], "act_gh": gh, "act_ga": ga,
            "p_home": e["p_home"], "p_draw": e["p_draw"], "p_away": e["p_away"],
            "pick": pick, "actual": act,
            "outcome_hit": hit,
            "score_hit": (e["gh"], e["ga"]) == (gh, ga),
            "p_actual_outcome": probs[act],
            "p_actual_score": p_act_score,
            "conf": round(conf, 5),             # 头号选项置信度
            "conf_band": _conf_band(conf),      # high/mid/coin
            "miss_type": miss_type,             # draw/wrong_winner/picked_draw/None
            "upset": upset,
            "upset_level": ("major" if conf >= UPSET_MAJOR else "minor") if upset else None,
            "rps": round(_rps(e["p_home"], e["p_draw"], e["p_away"], act), 4),
            "retro": bool(e.get("retro")),
        })
    n = len(rows)
    oh = sum(r["outcome_hit"] for r in rows)
    sh = sum(r["score_hit"] for r in rows)
    done_keys = {c["key"] for c in done}
    pending = sum(1 for k in preds if k not in done_keys)

    # 置信度分桶命中率：高把握 vs 硬币局分开看（模型在有把握的场次是否真的更准）
    def _bin(band):
        b = [r for r in rows if r["conf_band"] == band]
        h = sum(r["outcome_hit"] for r in b)
        return {"n": len(b), "hits": h, "pct": round(h / len(b) * 100, 1) if b else None}
    bins = {"high": _bin("high"), "mid": _bin("mid"), "coin": _bin("coin")}

    # 失手归因 + 冷门
    draws_actual = sum(1 for r in rows if r["actual"] == "D")
    draws_called = sum(1 for r in rows if r["actual"] == "D" and r["outcome_hit"])
    miss_draw = sum(1 for r in rows if r["miss_type"] == "draw")
    wrong_winner = sum(1 for r in rows if r["miss_type"] == "wrong_winner")
    upsets = sum(1 for r in rows if r["upset"])
    upsets_major = sum(1 for r in rows if r["upset_level"] == "major")

    summary = {
        "done": len(done), "evaluated": n, "missing": miss,
        "outcome_hits": oh, "outcome_pct": round(oh / n * 100, 1) if n else None,
        "score_hits": sh, "score_pct": round(sh / n * 100, 1) if n else None,
        "bins": bins,
        "draws_actual": draws_actual, "draws_called": draws_called,
        "miss_draw": miss_draw, "wrong_winner": wrong_winner,
        "upsets": upsets, "upsets_major": upsets_major,
        "avg_p_actual_outcome": round(float(np.mean([r["p_actual_outcome"] for r in rows])), 4) if n else None,
        "avg_p_actual_score": round(float(np.mean([r["p_actual_score"] for r in rows
                                                   if r["p_actual_score"] is not None])), 4) if n else None,
        "avg_rps": round(float(np.mean([r["rps"] for r in rows])), 4) if n else None,
        "retro_n": sum(1 for r in rows if r["retro"]),
        "pending_frozen": pending,
    }
    return {"summary": summary, "rows": rows}


# ---------- CLI ----------
def main():
    from predict import get_model
    from simulate import TournamentSimulator
    m = get_model(use_cache=True, half_life=730.0, verbose=False)
    m.set_availability()   # 与 app 同口径：含关键球员可用性层，否则冻结条目会两边互相覆盖
    df = datamod.load_raw()
    sim = TournamentSimulator(m, df, sims=1)
    freeze(sim, verbose=True)
    backfill(sim, df, verbose=True)
    r = evaluate(sim, df)
    s, rows = r["summary"], r["rows"]
    print(f"\n  🎯 预测验证（已完赛 {s['done']} 场，账本另有 {s['pending_frozen']} 场赛前锁定待开赛）")
    print("  " + "─" * 78)
    print(f"  {'日期':<11}{'对阵':<34}{'预测':>5} {'实际':>5}  {'胜/平/负%':<16}{'判定':<10}")
    print("  " + "─" * 78)
    for x in rows:
        vs = f"{x['home']} vs {x['away']}"
        pr = f"{x['pred_gh']}-{x['pred_ga']}"
        ac = f"{x['act_gh']}-{x['act_ga']}"
        ps = f"{x['p_home']*100:.0f}/{x['p_draw']*100:.0f}/{x['p_away']*100:.0f}"
        tag = ("🎯比分+赛果" if x["score_hit"] else ("✓赛果" if x["outcome_hit"] else "✗未中"))
        if x["upset"]:
            tag += " 🚨大冷门" if x["upset_level"] == "major" else " ⚠️冷门"
        elif x["miss_type"] == "draw":
            tag += "（被逼平）"
        elif x["miss_type"] == "wrong_winner":
            tag += "（选错胜方）"
        tag += " ⏪" if x["retro"] else ""
        print(f"  {x['date']:<11}{vs:<34}{pr:>5} {ac:>5}  {ps:<16}{tag}")
    print("  " + "─" * 78)
    if s["evaluated"]:
        print(f"  赛果命中 {s['outcome_hits']}/{s['evaluated']}（{s['outcome_pct']}%）"
              f" · 比分命中 {s['score_hits']}/{s['evaluated']}（{s['score_pct']}%）")
        b = s["bins"]
        fb = lambda x: f"{x['hits']}/{x['n']}（{x['pct']}%）" if x["n"] else "—"
        print(f"  按把握分桶：高把握≥60% {fb(b['high'])} · 中等45–60% {fb(b['mid'])} · 硬币局<45% {fb(b['coin'])}")
        print(f"  失手归因：被逼平 {s['miss_draw']} 场（共 {s['draws_actual']} 场平局，平局 argmax 几乎必丢）"
              f" · 选错胜方 {s['wrong_winner']} 场 · 冷门 {s['upsets']} 场（其中大冷门 {s['upsets_major']}）")
        print(f"  赋予实际赛果平均概率 {s['avg_p_actual_outcome']*100:.1f}%"
              f" · 实际比分平均概率 {s['avg_p_actual_score']*100:.1f}%"
              f" · 平均 RPS {s['avg_rps']}")
        print("  （⏪=回溯预测：用只含开球前数据训练的模型生成，与赛前冻结同口径）\n")


if __name__ == "__main__":
    main()
