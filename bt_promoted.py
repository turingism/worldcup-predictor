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

实现注记（2026-08-03 二次扩展）：feeder 行的降权走 comp_weights 的**赛事名精确键**
（data.build_training_frame 查表顺序=赛事名 > tier > 1.0）。初版靠
`comp_tier("English Championship")=="major"` 的关键词撞车才把英冠分出来，那是巧合、
且只对英格兰成立；改精确名后五大联赛同一条通道，不再依赖撞车。

用法：/opt/anaconda3/bin/python3 bt_promoted.py           # 五联赛全跑
      /opt/anaconda3/bin/python3 bt_promoted.py E0 SP1    # 只跑指定联赛
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


def promoted_teams(top: pd.DataFrame, cutoff: pd.Timestamp) -> set[str]:
    """cutoff 起新赛季的顶级联赛参赛队 − 上一季参赛队 = 升班马。"""
    nxt = top[(top.date >= cutoff) & (top.date < cutoff + pd.Timedelta(days=HORIZON_DAYS))]
    prev = top[(top.date >= cutoff - pd.Timedelta(days=365)) & (top.date < cutoff)]
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


def run_league(code: str, verbose: bool = True) -> dict | None:
    """单联赛闸门。返回 {code, best_w, rps, uniform, market, n_cutoffs, n_worse, gate}。"""
    feeder = clubdata.FEEDER[code]
    top = clubdata.load(code, seasons=SEASONS)
    fdr = clubdata.load(feeder, seasons=SEASONS)
    both = pd.concat([top, fdr], ignore_index=True).sort_values("date")
    feeder_name = clubdata.LEAGUES[feeder]          # comp_weights 精确键=赛事名

    rows = []
    for cutoff in CUTOFFS:
        cut = pd.Timestamp(cutoff)
        promo = promoted_teams(top, cut)
        horizon = top[(top.date >= cut) & (top.date < cut + pd.Timedelta(days=HORIZON_DAYS))]
        test = horizon[horizon.home_team.isin(promo) | horizon.away_team.isin(promo)]
        if not len(test):
            continue
        if verbose:
            print(f"\n== {code} cutoff {cutoff} · 升班马 {sorted(promo)} · 涉升班马场次 {len(test)} ==")
        base = DixonColesModel(half_life_days=HL).fit(top, verbose=False, as_of=cut)
        eb = evaluate(base, test)
        if verbose:
            skip = f"跳过 {eb['skipped']}/{len(test)}" if eb else f"跳过 {len(test)}/{len(test)}（全部无参数）"
            print(f"  纯{code}基线（现状=拒绝出数）：可预测 {eb['n'] if eb else 0} 场，{skip}")
        for w in W_GRID:
            m = DixonColesModel(half_life_days=HL,
                                comp_weights={feeder_name: w}).fit(
                both, verbose=False, as_of=cut)
            ev = evaluate(m, test)
            if ev is None:
                continue
            if verbose:
                mk = f"{ev['market_rps']:.4f}(n={ev['market_n']})" if ev["market_rps"] else "—"
                print(f"  w={w:<5} RPS={ev['rps']:.4f}  LL={ev['ll']:.4f}  hit={ev['hit']:.3f}"
                      f"  n={ev['n']} skip={ev['skipped']}  均匀={ev['uniform_rps']:.4f}  市场={mk}")
            rows.append({"cutoff": cutoff, "w": w, **ev})

    if not rows:
        print(f"[{code}] 无样本")
        return None
    df = pd.DataFrame(rows)
    agg = df.groupby("w").agg(rps=("rps", "mean"), ll=("ll", "mean"), hit=("hit", "mean"),
                              uniform=("uniform_rps", "mean"), market=("market_rps", "mean"),
                              n=("n", "sum")).round(4)
    if verbose:
        print(f"\n---- {code} 跨 cutoff 平均 ----")
        print(agg.to_string())
    best_w = float(agg["rps"].idxmin())
    b = agg.loc[best_w]
    sub = df[df.w == best_w]
    n_worse = int((sub.rps >= sub.uniform_rps).sum())
    # 闸门三条（与 E0 首版同口径）：① 优于均匀且各 cutoff 方向一致（无一逊于均匀）；
    # ② 对市场的差距 ≤0.03（bt_club_market 常态差距 +0.010~0.012，升班马场景放宽到 3×）。
    gate = (b["rps"] < b["uniform"]) and n_worse == 0 and (b["rps"] - b["market"] <= 0.03)
    return {"code": code, "feeder": feeder, "best_w": best_w, "rps": float(b["rps"]),
            "uniform": float(b["uniform"]), "market": float(b["market"]),
            "hit": float(b["hit"]), "n": int(b["n"]), "n_cutoffs": len(sub),
            "n_worse": n_worse, "gate": bool(gate),
            "grid": {float(w): float(agg.loc[w, "rps"]) for w in agg.index}}


def main(codes=None):
    codes = codes or list(clubdata.FEEDER)
    out = [r for r in (run_league(c) for c in codes) if r]
    print("\n\n==== 五联赛升班马闸门汇总（采纳裁决口径） ====")
    print(f"{'联赛':<5} {'feeder':<7} {'最优w':>6} {'RPS':>8} {'均匀':>8} {'市场':>8} "
          f"{'优于均匀':>9} {'对市场差':>9} {'场次':>6} {'逊于均匀的cutoff':>16} {'闸门':>6}")
    for r in out:
        print(f"{r['code']:<5} {r['feeder']:<7} {r['best_w']:>6.2f} {r['rps']:>8.4f} "
              f"{r['uniform']:>8.4f} {r['market']:>8.4f} {r['uniform']-r['rps']:>+9.4f} "
              f"{r['rps']-r['market']:>+9.4f} {r['n']:>6d} "
              f"{r['n_worse']:>10d}/{r['n_cutoffs']:<5d} {'过' if r['gate'] else '不过':>6}")
    print("\n权重网格 RPS（越小越好，看单调性是否与全量并入否决同向）：")
    for r in out:
        print(f"  {r['code']:<5} " + "  ".join(f"w={w}:{v:.4f}" for w, v in sorted(r["grid"].items())))
    return out


if __name__ == "__main__":
    import sys
    main(sys.argv[1:] or None)
