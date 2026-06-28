#!/usr/bin/env python3
"""市场研究层（只读、纯分析）——开盘→闭盘线移动的信息检验 + 分桶 + de-vig 敏感性。

定位：研究**博彩市场如何运作**，不是参与下注。全部为概率/信息分析，非投注建议。
零碰 GLM/账本；只读 data/odds.csv 的开/闭盘赔率 + 真实赛果。

三个视图：
  ① 总体线移动信息检验：闭盘是否比开盘更锐利(RPS/LogLoss) + 线移动是否朝最终结果(含信息)，
     带 bootstrap / Wilson 95% CI。
  ② 分桶：按【强弱档】(闭盘热门概率)与【移动幅度】分桶，看信息是否集中在某类场次。
     （阶段 group/knockout 分桶待淘汰赛样本积累后才有意义，现阶段几乎全是小组赛。）
  ③ de-vig 敏感性：proportional / odds_ratio / shin 三口径各跑一遍，看结论是否稳健。

sharp vs soft（皇冠/Pinnacle 锐 vs 365/威廉 软）：需多家书同场盘口才能算跨书背离，本项目
只有单一来源(ESPN/DraftKings)、无免费多书国家队源、抓皇冠/365 受 Cloudflare+ToS 限制(且涉赌
红线)——故跨书背离=数据死胡同。**单书内 开盘(较软)→闭盘(较锐) 的移动，是此处可落地的代理。**
"""
from __future__ import annotations
import math
import os

import numpy as np
import pandas as pd

import clv as clvmod
import data as datamod
import devig
from backtest import _rps
from bt_odds import _find_result

ODDS_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.csv")
_OPEN = ("odds_1_open", "odds_x_open", "odds_2_open")
_CLOSE = ("odds_1", "odds_x", "odds_2")


def _wilson(k: int, n: int, z: float = 1.96):
    """二项比例的 Wilson 95% 置信区间（小样本比正态近似稳）。"""
    if n == 0:
        return (None, None)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


_KO_START = pd.Timestamp("2026-06-28")          # 2026 WC 淘汰赛(R32)起始；之前=小组赛


def _stage(ts) -> str:
    """按日期粗分 2026 WC 阶段：<06-28=小组赛，>=06-28=淘汰赛（淘汰赛开打后自动生效）。"""
    try:
        return "knockout" if pd.Timestamp(ts) >= _KO_START else "group"
    except Exception:  # noqa
        return "group"


def _records(odds: pd.DataFrame, played: pd.DataFrame, method: str) -> list[dict]:
    """逐场提取开/闭盘隐含概率 + 赛果派生量（所有视图共用的原子记录）。"""
    dv = devig.METHODS.get(method, devig.proportional)
    recs = []
    for _, o in odds.iterrows():
        if any(pd.isna(o.get(c)) for c in _OPEN) or any(pd.isna(o.get(c)) for c in _CLOSE):
            continue
        outcome, _ = _find_result(played, o["home_team"], o["away_team"], o["date"])
        if outcome is None:
            continue
        op = dv(o["odds_1_open"], o["odds_x_open"], o["odds_2_open"])
        cp = dv(o["odds_1"], o["odds_x"], o["odds_2"])
        recs.append({
            "stage": _stage(o["date"]),
            "rps_o": _rps(op[0], op[1], op[2], outcome),
            "rps_c": _rps(cp[0], cp[1], cp[2], outcome),
            "ll_o": -math.log(max(float(op[outcome]), 1e-12)),
            "ll_c": -math.log(max(float(cp[outcome]), 1e-12)),
            "tv": 0.5 * float(np.abs(cp - op).sum()),        # 总变差=线移动幅度
            "d": float(cp[outcome] - op[outcome]),           # 朝实际结果移动多少
            "fav_close": float(np.max(cp)),                  # 闭盘热门概率=强弱档
        })
    return recs


def _agg(recs: list[dict], method: str | None = None) -> dict:
    """把一组逐场记录汇总成信息检验指标（带 CI / 显著性判读）。"""
    n = len(recs)
    if not n:
        return {"n": 0, "method": method}
    rps_o = np.array([r["rps_o"] for r in recs]); rps_c = np.array([r["rps_c"] for r in recs])
    ll_o = np.array([r["ll_o"] for r in recs]); ll_c = np.array([r["ll_c"] for r in recs])
    dmove = np.array([r["d"] for r in recs]); tv = np.array([r["tv"] for r in recs])
    rps_diff, ll_diff = rps_c - rps_o, ll_c - ll_o
    k_right = int((dmove > 0).sum())
    wlo, whi = _wilson(k_right, n)
    rps_ci, ll_ci, d_ci = clvmod.boot_ci(rps_diff), clvmod.boot_ci(ll_diff), clvmod.boot_ci(dmove)
    return {
        "n": n, "method": method,
        "rps_open": round(float(rps_o.mean()), 4), "rps_close": round(float(rps_c.mean()), 4),
        "rps_diff": round(float(rps_diff.mean()), 4),
        "rps_diff_ci": [round(x, 4) for x in rps_ci],
        "logloss_open": round(float(ll_o.mean()), 4), "logloss_close": round(float(ll_c.mean()), 4),
        "logloss_diff": round(float(ll_diff.mean()), 4),
        "logloss_diff_ci": [round(x, 4) for x in ll_ci],
        "avg_move": round(float(tv.mean()), 4),
        "move_toward_actual": round(float(dmove.mean()), 4),
        "move_toward_actual_ci": [round(x, 4) for x in d_ci],
        "right_dir_rate": round(k_right / n, 3),
        "right_dir_ci": [round(wlo, 3), round(whi, 3)],
        "closing_sharper": bool(ll_ci[1] is not None and ll_ci[1] < 0),   # 用 LogLoss CI 判（更敏感）
        "movement_informative": bool(d_ci[0] is not None and d_ci[0] > 0),
    }


def line_movement(odds, played, method: str | None = None) -> dict:
    """总体线移动信息检验。method=de-vig 口径（默认随 clv.DEVIG_METHOD）。"""
    m = method or clvmod.DEVIG_METHOD
    return _agg(_records(odds, played, m), m)


def segments(odds, played, method: str | None = None) -> dict:
    """分桶：①强弱档(闭盘热门概率) ②移动幅度(中位数切)。看信息集中在哪类场次。"""
    m = method or clvmod.DEVIG_METHOD
    recs = _records(odds, played, m)
    if not recs:
        return {"by_strength": [], "by_move": []}
    # ① 强弱档
    tiers = [("大热 ≥60%", lambda r: r["fav_close"] >= 0.60),
             ("中等 50–60%", lambda r: 0.50 <= r["fav_close"] < 0.60),
             ("接近 <50%", lambda r: r["fav_close"] < 0.50)]
    by_strength = [{"label": lab, **_agg([r for r in recs if f(r)], m)} for lab, f in tiers]
    # ② 移动幅度（按总变差中位数切大/小移动）
    med = float(np.median([r["tv"] for r in recs]))
    by_move = [
        {"label": f"大幅移动 ≥{med*100:.1f}pp", **_agg([r for r in recs if r["tv"] >= med], m)},
        {"label": f"小幅移动 <{med*100:.1f}pp", **_agg([r for r in recs if r["tv"] < med], m)},
    ]
    # ③ 阶段（小组赛/淘汰赛）——淘汰赛开打前 knockout 桶为空，开打后自动填充
    by_stage = [{"label": "小组赛", **_agg([r for r in recs if r["stage"] == "group"], m)},
                {"label": "淘汰赛", **_agg([r for r in recs if r["stage"] == "knockout"], m)}]
    return {"by_strength": by_strength, "by_move": by_move, "by_stage": by_stage,
            "move_median": round(med, 4)}


def _closing_points(odds, played, method: str):
    """逐场闭盘隐含概率 + 赛果（校准用，只需闭盘 → 样本比线移动多）。"""
    dv = devig.METHODS.get(method, devig.proportional)
    pts = []
    for _, o in odds.iterrows():
        if any(pd.isna(o.get(c)) for c in _CLOSE):
            continue
        outcome, _ = _find_result(played, o["home_team"], o["away_team"], o["date"])
        if outcome is None:
            continue
        pts.append((dv(o["odds_1"], o["odds_x"], o["odds_2"]), outcome))
    return pts


_CAL_EDGES = (0.0, 0.10, 0.20, 0.35, 0.50, 0.70, 1.0)


def _flatten(pts):
    """每场 3 个结果摊平成二元预测点：(预测概率, 是否发生)。校准/分解共用。"""
    preds, hits = [], []
    for cp, oc in pts:
        for i in range(3):
            preds.append(float(cp[i])); hits.append(1.0 if i == oc else 0.0)
    return np.array(preds), np.array(hits)


def _brier_decomp(pts, edges=_CAL_EDGES):
    """Brier 分数的 Murphy 分解：Brier = reliability − resolution + uncertainty。
    reliability↓=校准误差（越低越好）；resolution↑=分辨力/敢给极端概率（越高越好）；
    uncertainty=基率方差（模型/市场相同，因赛果相同）。"""
    preds, hits = _flatten(pts)
    N = len(preds)
    if not N:
        return {"brier": None, "reliability": None, "resolution": None, "uncertainty": None}
    obar = float(hits.mean())
    rel = res = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (preds >= lo) & (preds <= hi) if hi >= 1.0 else (preds >= lo) & (preds < hi)
        nb = int(m.sum())
        if not nb:
            continue
        pk, ok = float(preds[m].mean()), float(hits[m].mean())
        rel += nb / N * (pk - ok) ** 2
        res += nb / N * (ok - obar) ** 2
    brier = float(((preds - hits) ** 2).mean())
    return {"brier": round(brier, 4), "reliability": round(rel, 4),
            "resolution": round(res, 4), "uncertainty": round(obar * (1 - obar), 4)}


def _ece(pts, edges=_CAL_EDGES):
    """把每场 3 个结果的(预测概率, 是否发生)摊平 → 分箱 reliability + ECE。"""
    preds, hits = _flatten(pts)
    N = len(preds)
    bins, ece = [], 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (preds >= lo) & (preds <= hi) if hi >= 1.0 else (preds >= lo) & (preds < hi)
        nb = int(m.sum())
        if not nb:
            bins.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": 0}); continue
        pm, om, k = float(preds[m].mean()), float(hits[m].mean()), int(hits[m].sum())
        wlo, whi = _wilson(k, nb)
        ece += nb / N * abs(om - pm)
        bins.append({"lo": round(lo, 2), "hi": round(hi, 2), "n": nb,
                     "pred": round(pm, 3), "obs": round(om, 3),
                     "obs_ci": [round(wlo, 3), round(whi, 3)]})
    return bins, round(ece, 4), N


def calibration(odds, played, method: str | None = None) -> dict:
    """闭盘线作为概率源的校准（reliability + ECE）+ 各 de-vig 口径 ECE 对比。
    ECE 越低=市场概率越可信；favorite–longshot 偏差会让冷门档系统性高估。"""
    m = method or clvmod.DEVIG_METHOD
    pts = _closing_points(odds, played, m)
    bins, ece, N = _ece(pts)
    by_method = {}
    for mm in ("proportional", "odds_ratio", "shin"):
        _, e, _ = _ece(_closing_points(odds, played, mm))
        by_method[mm] = e
    return {"method": m, "n_points": N, "bins": bins, "ece": ece,
            "ece_by_method": by_method, "decomp": _brier_decomp(pts)}


def devig_sensitivity(odds, played) -> list[dict]:
    """同一批比赛、三种 de-vig 口径各跑总体检验，看结论是否稳健（不随口径翻转）。"""
    out = []
    for m in ("proportional", "odds_ratio", "shin"):
        a = _agg(_records(odds, played, m), m)
        out.append(a)
    return out


def _summary(d) -> dict:
    """从真实数字自动生成一句话研究判语（不硬编码，随数据更新；非投注建议）。"""
    lm, cal = d.get("line_movement", {}), d.get("calibration", {})
    if not lm.get("n"):
        return {"text": "暂无开/闭盘 + 赛果可匹配的样本，研究待数据积累。", "flags": {}}
    em = cal.get("ece_by_method", {})
    best = min(em, key=em.get) if em else None
    parts = [f"基于 {lm['n']} 场开/闭盘 + 赛果"]
    parts.append("线移动**含信息**" if lm.get("movement_informative")
                 else "线移动信息**不显著**")
    parts.append("闭盘比开盘**更锐利**" if lm.get("closing_sharper") else "闭盘锐利化不显著")
    if cal.get("ece") is not None:
        parts.append(f"闭盘线校准 ECE={cal['ece']*100:.1f}%（{'良好' if cal['ece'] < 0.05 else '一般'}）")
    if best:
        parts.append(f"de-vig 以 **{best}** 读盘最准（ECE 最低）")
    return {"text": "；".join(parts) + "。结论一致指向：市场高效、研究只为理解市场，非投注建议。",
            "flags": {"movement_informative": lm.get("movement_informative"),
                      "closing_sharper": lm.get("closing_sharper"),
                      "best_devig": best, "ece": cal.get("ece")}}


def build(df=None) -> dict:
    odds = pd.read_csv(ODDS_PATH)
    odds["date"] = pd.to_datetime(odds["date"])
    if df is None:
        df = datamod.load_raw()
    played = datamod.played(df)
    out = {
        "line_movement": line_movement(odds, played),
        "segments": segments(odds, played),
        "calibration": calibration(odds, played),
        "devig_sensitivity": devig_sensitivity(odds, played),
        "source_note": "单一来源 ESPN/DraftKings 闭盘；开盘→闭盘=单书内 soft→sharp 代理。"
                       "跨书 sharp/soft 背离需多书同场盘口，无免费源=数据死胡同。仅为研究、非投注建议。",
    }
    out["summary"] = _summary(out)
    return out


def _fmt_seg(s):
    if not s.get("n"):
        return f"    {s.get('label',''):<16} n=0（暂无样本）"
    return (f"    {s['label']:<16} n={s['n']:<3} 朝实际 {s['move_toward_actual']:+.3f}"
            f"{'✓' if s['movement_informative'] else '✗'} | 闭盘 LogLossΔ {s['logloss_diff']:+.4f}"
            f"{'✓更锐' if s['closing_sharper'] else '✗'} | 方向 {s['right_dir_rate']:.0%}")


def main():
    r = build()
    lm = r["line_movement"]
    if not lm.get("n"):
        print("无开/闭盘 + 赛果可匹配的样本。"); return
    print(f"\n  ① 总体 · 开盘→闭盘 信息检验 · n={lm['n']}（de-vig={lm['method']}）")
    print(f"     LogLoss 闭−开={lm['logloss_diff']:+.4f} CI{lm['logloss_diff_ci']} "
          f"闭盘更锐利={'是' if lm['closing_sharper'] else '不显著'}")
    print(f"     朝实际 mean={lm['move_toward_actual']:+.4f} CI{lm['move_toward_actual_ci']} "
          f"方向正确 {lm['right_dir_rate']:.1%} CI[{lm['right_dir_ci'][0]:.1%},{lm['right_dir_ci'][1]:.1%}] "
          f"含信息={'是' if lm['movement_informative'] else '不显著'}")
    seg = r["segments"]
    print(f"\n  ② 分桶 · 强弱档（信息集中在哪类场次）")
    for s in seg["by_strength"]:
        print(_fmt_seg(s))
    print(f"  ② 分桶 · 移动幅度（中位 {seg.get('move_median')}）")
    for s in seg["by_move"]:
        print(_fmt_seg(s))
    print(f"  ② 分桶 · 阶段（淘汰赛开打后自动生效）")
    for s in seg.get("by_stage", []):
        print(_fmt_seg(s))
    cal = r["calibration"]
    dc = cal.get("decomp", {})
    print(f"\n  ③ 闭盘线校准（作为概率源是否可信）· {cal['n_points']} 个预测点 · ECE={cal['ece']}")
    print(f"     Brier 分解：reliability={dc.get('reliability')}(↓) "
          f"resolution={dc.get('resolution')}(↑) uncertainty={dc.get('uncertainty')}")
    for b in cal["bins"]:
        if not b.get("n"):
            continue
        print(f"     预测[{b['lo']:.0%}-{b['hi']:.0%}) n={b['n']:<3} 预测均 {b['pred']:.0%} "
              f"实际 {b['obs']:.0%} CI[{b['obs_ci'][0]:.0%},{b['obs_ci'][1]:.0%}]")
    print(f"     各 de-vig 口径 ECE：" + " · ".join(f"{k}={v}" for k, v in cal["ece_by_method"].items()))
    print(f"\n  ④ de-vig 敏感性（结论是否随口径翻转）")
    print(f"    {'口径':<14}{'朝实际mean':>12}{'CI下界':>9}{'方向正确':>9}{'含信息':>8}")
    for a in r["devig_sensitivity"]:
        print(f"    {a['method']:<14}{a['move_toward_actual']:>+12.4f}"
              f"{a['move_toward_actual_ci'][0]:>9.4f}{a['right_dir_rate']:>9.0%}"
              f"{'✓' if a['movement_informative'] else '✗':>8}")
    print(f"\n  📋 判语：{r['summary']['text']}")
    print(f"  {r['source_note']}")


if __name__ == "__main__":
    main()
