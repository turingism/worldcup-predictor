#!/usr/bin/env python3
"""市场机制解释器的【可证伪验证 + B/D 转正闸门】（项目铁律：能验的才呈现）。

验什么
------
A/C（已实现段，可验）：
  - 线移动信息检验 + 闭盘线校准（复用 market_research.build）。
  - 模型 vs 闭盘线 评分卡 RPS/LogLoss/ECE（复用 clv.evaluate 的 calibration_compare）。

B/D 转正闸门（b_gate，机械、随样本增长自动判定）
  - B（FLB/大热必死）、D（依赖 B 数字）现【不实现】：82 场/全 2026/无历史国家队赔率源，
    任一概率桶样本不足、FLB 偏差 CI 跨 0，按铁律不得呈现。
  - 闸门：统计各隐含概率桶样本数 + FLB 偏差(实际频率−隐含概率)及 bootstrap CI。
    **某桶 n≥30 且 FLB CI 不跨 0 → 该桶 B/D 解锁**；在那之前 explainer **根本不渲染** B/D。
  - 同「2026 淘汰赛打完重跑 bt_knockout」哲学：让数据决定 B 能否转正。
  - 注：FLB 点由每场 3 结果摊平而来、非独立，CI 偏乐观——故闸门取 n≥30 且 CI 不跨 0 双条件保守。

零碰 GLM/账本。个人/教育项目，非投注建议。
"""
from __future__ import annotations
import json
import os
import numpy as np
import pandas as pd

import clv as clvmod
import data as datamod
import devig
import market_research as mr

GATE_MIN_N = 30          # 每桶最小样本
HANDI_LINES_PATH = os.path.join(os.path.dirname(__file__), "data", "handicap_lines.json")
# FLB 概率桶（隐含概率轴；favorite 高概率端 vs longshot 低概率端的系统偏差）
FLB_EDGES = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.0)


def _flb_points(odds, played, method="shin"):
    """摊平的 (隐含概率, 是否发生) 点——FLB = 实际频率 − 隐含概率。1X2 三路。"""
    pts = mr._closing_points(odds, played, method)
    preds, hits = mr._flatten(pts)
    return preds, hits


def _match_result(played, home, away, date, tol=2):
    """按 (home,away,date±tol) 查赛果，返回 v 的 (home_score, away_score) 框；查不到 None。"""
    d = pd.Timestamp(date)
    for hh, aa, swap in ((home, away, False), (away, home, True)):
        m = played[(played.home_team == hh) & (played.away_team == aa)
                   & ((played.date - d).abs() <= pd.Timedelta(days=tol))]
        if not m.empty:
            r = m.iloc[0]
            return (int(r.away_score), int(r.home_score)) if swap else (int(r.home_score), int(r.away_score))
    return None


def _handicap_flb_points(played, method="shin"):
    """让球闭盘 2 路 de-vig cover 概率 vs 实际打出，摊平成 (cover隐含, 是否cover) 点。
    每场 2 点（强队 cover / 弱队受让）；整数线打平=push 跳过。返回 (preds, hits, n场, n_push)。"""
    if not os.path.exists(HANDI_LINES_PATH):
        return np.array([]), np.array([]), 0, 0
    hl = json.load(open(HANDI_LINES_PATH))
    preds, hits, n, n_push = [], [], 0, 0
    for v in hl.values():
        ofav, odog = v.get("fav_spread_odds"), v.get("dog_spread_odds")
        if not ofav or not odog:
            continue
        res = _match_result(played, v["home"], v["away"], v["date"])
        if res is None:
            continue
        hs, as_ = res
        fav_margin = (hs - as_) if v["fav_is_home"] else (as_ - hs)
        adj = fav_margin - v["fav_line"]
        if abs(adj) < 1e-9:          # 整数线打平=退本，二元 cover 无定义 → 跳过
            n_push += 1; continue
        fav_cover = 1.0 if adj > 0 else 0.0
        p, _ = devig.implied2(ofav, odog, method)
        preds += [float(p[0]), float(p[1])]
        hits += [fav_cover, 1.0 - fav_cover]
        n += 1
    return np.array(preds), np.array(hits), n, n_push


def _ece_points(preds, hits, edges=mr._CAL_EDGES):
    """二元 (预测概率, 是否发生) 点的 ECE（让球 cover 校准用）。"""
    preds, hits = np.asarray(preds, float), np.asarray(hits, float)
    N = len(preds)
    if not N:
        return None, 0
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (preds >= lo) & (preds <= hi) if hi >= 1.0 else (preds >= lo) & (preds < hi)
        nb = int(m.sum())
        if nb:
            ece += nb / N * abs(float(hits[m].mean()) - float(preds[m].mean()))
    return round(ece, 4), N


def handicap_devig_ece(played=None, df=None):
    """让球 cover 2 路 de-vig 三口径 ECE 对比——确认 Shin 在 2 路上是否仍最准。"""
    if played is None:
        played = datamod.played(df if df is not None else datamod.load_raw())
    out = {}
    for m in ("proportional", "odds_ratio", "shin"):
        preds, hits, n, _ = _handicap_flb_points(played, m)
        ece, N = _ece_points(preds, hits)
        out[m] = {"ece": ece, "n_points": N, "n_matches": n}
    return out


def bucket_decision(resid):
    """单桶转正判定（纯函数，可单测）：解锁 ⇔ n≥GATE_MIN_N 且 FLB 偏差 CI 不跨 0（AND）。
    resid = 该桶内 (实际−隐含) 残差数组。任一条件不满足都不解锁。"""
    resid = np.asarray(resid, float)
    nb = int(resid.size)
    if nb == 0:
        return {"n": 0, "flb": None, "ci": None, "ci_excludes_0": False, "unlocked": False}
    flb = float(resid.mean())
    ci_lo, ci_hi = clvmod.boot_ci(resid)
    ci_excl0 = ci_lo is not None and (ci_lo > 0 or ci_hi < 0)
    return {"n": nb, "flb": round(flb, 4),
            "ci": [round(ci_lo, 4), round(ci_hi, 4)] if ci_lo is not None else None,
            "ci_excludes_0": ci_excl0, "unlocked": bool(nb >= GATE_MIN_N and ci_excl0)}


def b_gate(odds=None, df=None, method="shin", include_handicap=False):
    """B/D 转正闸门：逐概率桶样本数 + FLB 偏差 + CI + 是否解锁。
    include_handicap=True 时把让球闭盘 cover 隐含概率点并入（看让球样本能否帮某些桶达 n≥30）。
    返回 {buckets:[...], any_unlocked, unlocked_buckets, n_points, n_1x2, n_handicap}。"""
    if odds is None:
        odds = pd.read_csv(mr.ODDS_PATH); odds["date"] = pd.to_datetime(odds["date"])
    if df is None:
        df = datamod.load_raw()
    played = datamod.played(df)
    preds, hits = _flb_points(odds, played, method)
    n_1x2 = int(len(preds)); n_handi = 0
    if include_handicap:
        hp, hh, _, _ = _handicap_flb_points(played, method)
        n_handi = int(len(hp))
        preds = np.concatenate([preds, hp]) if n_handi else preds
        hits = np.concatenate([hits, hh]) if n_handi else hits
    resid = hits - preds                      # FLB：>0=该档实际兑现高于隐含（冷门被低估）
    buckets, unlocked = [], []
    for lo, hi in zip(FLB_EDGES[:-1], FLB_EDGES[1:]):
        m = (preds >= lo) & (preds <= hi) if hi >= 1.0 else (preds >= lo) & (preds < hi)
        b = {"lo": lo, "hi": hi, **bucket_decision(resid[m])}
        buckets.append(b)
        if b["unlocked"]:
            unlocked.append(b)
    return {"buckets": buckets, "any_unlocked": bool(unlocked),
            "unlocked_buckets": unlocked, "n_points": int(len(preds)),
            "n_1x2": n_1x2, "n_handicap": n_handi, "min_n": GATE_MIN_N}


def validate_ac(df=None):
    """A/C 可验部分：线移动信息检验 + 闭盘校准 + 模型 vs 闭盘评分卡。"""
    out = {"market_research": mr.build(df=df)}
    try:
        out["model_vs_market"] = clvmod.evaluate(df=df).get("calibration_compare")
    except Exception as e:  # noqa
        out["model_vs_market"] = {"error": str(e)}
    return out


def main():
    print("收集 A/C 验证 + B/D 转正闸门（1X2，data/odds.csv）…")
    df = datamod.load_raw()
    ac = validate_ac(df=df)
    lm = ac["market_research"]["line_movement"]
    cal = ac["market_research"]["calibration"]
    print("\n" + "=" * 60 + "\n【A/C 验证 · 可证伪】\n" + "=" * 60)
    if lm.get("n"):
        print(f"  线移动信息检验 n={lm['n']}：朝实际 {lm['move_toward_actual']:+.4f} "
              f"CI{lm['move_toward_actual_ci']} 含信息={'是' if lm['movement_informative'] else '不显著'}；"
              f"闭盘更锐利={'是' if lm['closing_sharper'] else '不显著'}（LogLossΔ{lm['logloss_diff']:+.4f}）")
    print(f"  闭盘线校准 ECE={cal.get('ece')}（{cal.get('n_points')} 预测点）；"
          f"各 de-vig 口径 ECE：" + " · ".join(f"{k}={v}" for k, v in cal.get("ece_by_method", {}).items()))
    cc = ac.get("model_vs_market")
    if cc and cc.get("scorecard"):
        sc = cc["scorecard"]
        print(f"  模型 vs 闭盘线 评分卡（越低越好，{cc.get('n_points')} 预测点）：")
        print(f"    {'':<8}{'RPS':>9}{'LogLoss':>10}{'ECE':>9}")
        for who in ("model", "market"):
            s = sc[who]
            print(f"    {who:<8}{s['rps']:>9.4f}{s['logloss']:>10.4f}{s['ece']:>9.4f}")
        print(f"    逐项胜者：RPS={sc['winner']['rps']} LogLoss={sc['winner']['logloss']} ECE={sc['winner']['ece']}"
              f"  → 整体更准：{cc.get('better')}（印证红线#3 先验：分歧时市场对、模型错）")

    # 让球 cover 2 路 de-vig 口径 ECE（确认 Shin 在 2 路上是否仍最准）
    he = handicap_devig_ece(df=df)
    nh = he.get("shin", {}).get("n_points", 0)
    print(f"  让球 cover 2 路 de-vig ECE（{nh} 个 cover 预测点）："
          + " · ".join(f"{k}={v['ece']}" for k, v in he.items())
          + f"  → {'shin 最准' if he['shin']['ece'] is not None and he['shin']['ece'] <= min(x['ece'] for x in he.values() if x['ece'] is not None) else '见上'}")

    print("\n" + "=" * 60 + "\n【B/D 转正闸门 · 各概率桶样本清单（1X2 vs +让球）】\n" + "=" * 60)
    g0 = b_gate(df=df)
    g1 = b_gate(df=df, include_handicap=True)
    by_lo = {b["lo"]: b for b in g0["buckets"]}
    print(f"  1X2 点={g1['n_1x2']}，+让球 cover 点={g1['n_handicap']} → 合计 {g1['n_points']}；"
          f"解锁门槛：每桶 n≥{g1['min_n']} 且 FLB CI 不跨 0")
    print(f"    {'隐含概率桶':>14}{'n(1X2)':>8}{'n(+让球)':>10}{'Δ让球':>8}{'达n≥30?':>10}{'FLB+让球':>12}{'解锁?':>7}")
    for b in g1["buckets"]:
        lab = f"[{b['lo']:.0%},{b['hi']:.0%})"
        n0 = by_lo.get(b["lo"], {}).get("n", 0)
        reach = "✅达标" if b["n"] >= g1["min_n"] else f"差{g1['min_n']-b['n']}"
        flb = f"{b['flb']:+.4f}" if b["flb"] is not None else "—"
        unlocked = "✅" if b["unlocked"] else "否"
        print(f"    {lab:>14}{n0:>8}{b['n']:>10}{b['n']-n0:>+8}{reach:>10}{flb:>12}{unlocked:>7}")
    print(f"\n  → B/D 解锁状态：{'有桶已解锁' if g1['any_unlocked'] else '全部锁定（样本仍不足，B/D 不渲染）'}")
    reached = [f"[{b['lo']:.0%},{b['hi']:.0%})" for b in g1["buckets"] if b["n"] >= g1["min_n"]]
    print(f"  加让球后达 n≥{g1['min_n']} 的桶：{reached or '（仍无）'}"
          f"（达标只是样本够，解锁仍需 FLB CI 不跨 0）")
    print("\n  注：A/C 已验、可呈现；B/D 冻结至闸门解锁。零碰 GLM，个人/教育项目非投注建议。")


if __name__ == "__main__":
    main()
