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
import numpy as np
import pandas as pd

import clv as clvmod
import data as datamod
import market_research as mr

GATE_MIN_N = 30          # 每桶最小样本
# FLB 概率桶（隐含概率轴；favorite 高概率端 vs longshot 低概率端的系统偏差）
FLB_EDGES = (0.0, 0.10, 0.20, 0.30, 0.40, 0.50, 0.60, 0.70, 0.80, 1.0)


def _flb_points(odds, played, method="shin"):
    """摊平的 (隐含概率, 是否发生) 点——FLB = 实际频率 − 隐含概率。"""
    pts = mr._closing_points(odds, played, method)
    preds, hits = mr._flatten(pts)
    return preds, hits


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


def b_gate(odds=None, df=None, method="shin"):
    """B/D 转正闸门：逐概率桶样本数 + FLB 偏差 + CI + 是否解锁。
    返回 {buckets:[...], any_unlocked, unlocked_buckets, n_points}。"""
    if odds is None:
        odds = pd.read_csv(mr.ODDS_PATH); odds["date"] = pd.to_datetime(odds["date"])
    if df is None:
        df = datamod.load_raw()
    played = datamod.played(df)
    preds, hits = _flb_points(odds, played, method)
    resid = hits - preds                      # FLB：>0=该档实际兑现高于隐含（冷门被低估）
    buckets, unlocked = [], []
    for lo, hi in zip(FLB_EDGES[:-1], FLB_EDGES[1:]):
        m = (preds >= lo) & (preds <= hi) if hi >= 1.0 else (preds >= lo) & (preds < hi)
        b = {"lo": lo, "hi": hi, **bucket_decision(resid[m])}
        buckets.append(b)
        if b["unlocked"]:
            unlocked.append(b)
    return {"buckets": buckets, "any_unlocked": bool(unlocked),
            "unlocked_buckets": unlocked, "n_points": int(len(preds)), "min_n": GATE_MIN_N}


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

    print("\n" + "=" * 60 + "\n【B/D 转正闸门 · 各概率桶样本清单】\n" + "=" * 60)
    g = b_gate(df=df)
    print(f"  FLB 点总数={g['n_points']}（{g['n_points']//3} 场 × 3 结果，非独立 → CI 偏乐观）；"
          f"解锁门槛：每桶 n≥{g['min_n']} 且 FLB CI 不跨 0")
    print(f"    {'隐含概率桶':>14}{'n':>6}{'FLB(实际−隐含)':>16}{'95%CI':>20}{'解锁?':>8}")
    for b in g["buckets"]:
        lab = f"[{b['lo']:.0%},{b['hi']:.0%})"
        if b["n"] == 0:
            print(f"    {lab:>14}{0:>6}{'—':>16}{'—':>20}{'否':>8}")
            continue
        ci = f"[{b['ci'][0]:+.3f},{b['ci'][1]:+.3f}]" if b["ci"] else "—"
        unlocked = "✅是" if b["unlocked"] else "否"
        print(f"    {lab:>14}{b['n']:>6}{b['flb']:>+16.4f}{ci:>20}{unlocked:>8}")
    print(f"\n  → B/D 解锁状态：{'有桶已解锁' if g['any_unlocked'] else '全部锁定（样本不足，B/D 不渲染）'}")
    print(f"  缺口：各桶离 n≥{g['min_n']} 还差多少 = " +
          ", ".join(f"[{b['lo']:.0%},{b['hi']:.0%}):{max(0, g['min_n']-b['n'])}"
                    for b in g["buckets"] if b["n"] > 0))
    print("\n  注：A/C 已验、可呈现；B/D 冻结至闸门解锁。零碰 GLM，个人/教育项目非投注建议。")


if __name__ == "__main__":
    main()
