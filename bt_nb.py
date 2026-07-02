#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""实验回测：进球分布用负二项(NB2, var=μ+α·μ²)替代 Poisson，是否改善 RPS/LogLoss？

动机：训练数据进球 方差/均值≈1.6 (>1)，提示过离散，Poisson 尾部偏窄。
保持 Poisson GLM 估的均值 λ 不变（排名/xG 不动），只把比分矩阵的每队进球分布换成 NB。
nb_alpha 只影响 score_matrix，故每个 cutoff 只 fit 一次、改 α 复评（高效）。
"""
from __future__ import annotations
import datetime as dt

import backtest
import data as datamod
from model import DixonColesModel

CUTOFFS = [dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
HORIZON = 270
HALF_LIFE = 240.0
ALPHAS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.30]   # 0=Poisson 基线


def main():
    df = datamod.load_raw()
    aggs = {a: backtest._Acc() for a in ALPHAS}
    for cutoff in CUTOFFS:
        m = DixonColesModel(half_life_days=HALF_LIFE).fit(df, verbose=False, as_of=cutoff)
        test = backtest.select_test(df, cutoff, HORIZON)
        for a in ALPHAS:
            m.nb_alpha = a                 # 只改分布形状，无需重训
            res = backtest.evaluate(m, test)
            if res:
                aggs[a].add(res)

    print("\n== 负二项过离散扫描（RPS/LogLoss 越低越好）==")
    print(f"  {'α(过离散)':<12}{'样本':>6}{'RPS':>9}{'LogLoss':>10}{'命中率':>8}{'ΔRPS':>9}")
    base = aggs[0.0].out()
    best = None
    for a in ALPHAS:
        m = aggs[a].out()
        d = m["rps"] - base["rps"]
        tag = "  (Poisson基线)" if a == 0 else ""
        print(f"  {a:<12.2f}{m['n']:>6}{m['rps']:>9.4f}{m['logloss']:>10.4f}"
              f"{m['acc']:>8.3f}{d:>+9.4f}{tag}")
        if a != 0 and (best is None or m["rps"] < best[1]):
            best = (a, m["rps"], d, m["logloss"])
    if best:
        dll = best[3] - base["logloss"]
        verdict = ("【更好，可考虑采用】" if best[2] < -0.0005 else
                   "【无显著改善，按铁律不采用】" if best[2] < 0.0005 else "【更差，不采用】")
        print(f"\n  最佳 α={best[0]}  ΔRPS={best[2]:+.4f}  ΔLogLoss={dll:+.4f} {verdict}")


if __name__ == "__main__":
    main()
