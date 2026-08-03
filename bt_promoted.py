#!/usr/bin/env python3
"""升班马单场专项回测——E1 降权并入的采纳闸门（2026-08-03）。纯离线旁路。

背景与边界（勿与旧裁决混淆）：
  - 2026-07-08 裁决：E1 **全量并入（w=1）用于一般 E0 单场**=否决（严格可比 RPS +0.0036 变差），
    当时预留两条路：升班马对阵标「数据不足」；「后续可研究 E1 降权（w<1）并入」。
  - 本回测就是那条预留研究：**只对涉升班马场次启用** E0+E1 加权合训模型——非升班马场次
    照旧用纯 E0 模型，一般场次准度零风险；因此闸门只需回答「升班马场次上这样预测靠不靠谱」。
  - 基线不是「更准 vs 纯 E0」（纯 E0 对升班马场次=拒绝出数，无数字可比），而是：
      ① 显著优于无信息基线（均匀 1/3）；② 与 B365 闭盘的差距 ≈ bt_club_hl 里模型对市场的
      正常差距（模型略逊于市场是常态，不因升班马场景显著恶化）；③ 各 cutoff 方向一致。

实现注记：E1 行的降权走 comp_weights——`data.comp_tier("English Championship")=="major"`
（"championship" 关键词撞车，本意是欧锦赛）而 EPL→"other"，恰好可分。这是**脆弱巧合**，
test_core 有护栏测试锁死该映射；此路只适用于英格兰（西乙/意乙等与其顶级同 tier，不适用）。

用法：/opt/anaconda3/bin/python3 bt_promoted.py
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

import clubdata
from model import DixonColesModel

warnings.filterwarnings("ignore")

CUTOFFS = ["2021-08-01", "2022-08-01", "2023-08-01", "2024-08-01", "2025-08-01"]
HORIZON_DAYS = 300          # 覆盖整赛季：升班马整季都靠该路径（E0 当季样本随赛季推进自然增权）
W_GRID = [0.25, 0.5, 0.75, 1.0]
HL = 365                    # 俱乐部正式裁决超参，不动
SEASONS = 9                 # 让最早 cutoff 也有 ≥3 季历史


def rps(p, outcome):
    c = np.cumsum(p)
    o = np.zeros(3)
    o[outcome] = 1.0
    return float(np.sum((c - np.cumsum(o))[:2] ** 2) / 2)


def devig(h, d, a):
    """1/odds 归一去水；任一缺失返回 None。"""
    if any(pd.isna(x) or x <= 1.0 for x in (h, d, a)):
        return None
    inv = np.array([1 / h, 1 / d, 1 / a])
    return inv / inv.sum()


def promoted_teams(e0: pd.DataFrame, cutoff: pd.Timestamp) -> set[str]:
    """cutoff 起新赛季的 E0 参赛队 − 上一季 E0 参赛队 = 升班马。"""
    nxt = e0[(e0.date >= cutoff) & (e0.date < cutoff + pd.Timedelta(days=HORIZON_DAYS))]
    prev = e0[(e0.date >= cutoff - pd.Timedelta(days=365)) & (e0.date < cutoff)]
    t_next = set(nxt.home_team) | set(nxt.away_team)
    t_prev = set(prev.home_team) | set(prev.away_team)
    return t_next - t_prev


def evaluate(model, test: pd.DataFrame):
    rs, lls, hits, skipped = [], [], [], 0
    mk_rs, uni_rs = [], []
    for _, r in test.iterrows():
        if r.home_team not in model.attack or r.away_team not in model.attack:
            skipped += 1
            continue
        pr = model.predict(r.home_team, r.away_team, neutral=False)
        p = np.clip([pr["p_home"], pr["p_draw"], pr["p_away"]], 1e-9, 1)
        out = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
        rs.append(rps(p, out))
        lls.append(-np.log(p[out]))
        hits.append(int(np.argmax(p) == out))
        uni_rs.append(rps(np.array([1 / 3] * 3), out))
        mp = devig(r.get("B365CH"), r.get("B365CD"), r.get("B365CA"))
        if mp is None:
            mp = devig(r.get("B365H"), r.get("B365D"), r.get("B365A"))
        if mp is not None:
            mk_rs.append(rps(mp, out))
    n = len(rs)
    if n == 0:
        return None
    return {"n": n, "skipped": skipped,
            "rps": float(np.mean(rs)), "ll": float(np.mean(lls)),
            "hit": float(np.mean(hits)),
            "uniform_rps": float(np.mean(uni_rs)),
            "market_rps": float(np.mean(mk_rs)) if mk_rs else None,
            "market_n": len(mk_rs)}


def main():
    e0 = clubdata.load("E0", seasons=SEASONS)
    e1 = clubdata.load("E1", seasons=SEASONS)
    both = pd.concat([e0, e1], ignore_index=True).sort_values("date")

    rows = []
    for cutoff in CUTOFFS:
        cut = pd.Timestamp(cutoff)
        promo = promoted_teams(e0, cut)
        horizon = e0[(e0.date >= cut) & (e0.date < cut + pd.Timedelta(days=HORIZON_DAYS))]
        test = horizon[horizon.home_team.isin(promo) | horizon.away_team.isin(promo)]
        if not len(test):
            continue
        print(f"\n== cutoff {cutoff} · 升班马 {sorted(promo)} · 涉升班马场次 {len(test)} ==")

        base = DixonColesModel(half_life_days=HL).fit(e0, verbose=False, as_of=cut)
        eb = evaluate(base, test)
        skip_note = f"跳过 {eb['skipped']}/{len(test)}" if eb else f"跳过 {len(test)}/{len(test)}（全部无参数）"
        print(f"  纯E0基线（现状=拒绝出数）：可预测 {eb['n'] if eb else 0} 场，{skip_note}")

        for w in W_GRID:
            m = DixonColesModel(half_life_days=HL,
                                comp_weights={"major": w, "other": 1.0}).fit(
                both, verbose=False, as_of=cut)
            ev = evaluate(m, test)
            if ev is None:
                continue
            mk = f"{ev['market_rps']:.4f}(n={ev['market_n']})" if ev["market_rps"] else "—"
            print(f"  w={w:<5} RPS={ev['rps']:.4f}  LL={ev['ll']:.4f}  hit={ev['hit']:.3f}"
                  f"  n={ev['n']} skip={ev['skipped']}  均匀={ev['uniform_rps']:.4f}  市场={mk}")
            rows.append({"cutoff": cutoff, "w": w, **ev})

    if not rows:
        print("无样本")
        return
    df = pd.DataFrame(rows)
    print("\n==== 跨 cutoff 平均（采纳裁决口径） ====")
    agg = df.groupby("w").agg(rps=("rps", "mean"), ll=("ll", "mean"), hit=("hit", "mean"),
                              uniform=("uniform_rps", "mean"), market=("market_rps", "mean"),
                              n=("n", "sum")).round(4)
    print(agg.to_string())
    best_w = agg["rps"].idxmin()
    b = agg.loc[best_w]
    print(f"\n最优 w={best_w}: RPS {b['rps']:.4f} vs 均匀 {b['uniform']:.4f}"
          f"（优 {b['uniform']-b['rps']:+.4f}） vs 市场 {b['market']:.4f}"
          f"（差 {b['rps']-b['market']:+.4f}）")
    worse_than_uniform = df[df.w == best_w][df[df.w == best_w].rps >= df[df.w == best_w].uniform_rps]
    print(f"方向一致性：最优 w 在 {len(df[df.w == best_w])} 个 cutoff 中 "
          f"{len(worse_than_uniform)} 个逊于均匀基线")


if __name__ == "__main__":
    main()
