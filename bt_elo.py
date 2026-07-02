#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""实验回测：把 Elo 差作为外生特征加进双泊松 GLM，是否优于基线 DC？

借鉴自高盛"以 Elo 为核心协变量"的思路（区别于此前已否决的"Elo 集成"）。
严格同 cutoff、同数据、同 half_life，只差 GLM 是否含 elo_diff 项。
评级冻结在 cutoff（与基线一致，无泄漏），预测 cutoff 后 horizon 天的真实比赛。
"""
from __future__ import annotations
import datetime as dt

import backtest
import data as datamod
from model import DixonColesModel

CUTOFFS = [dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
HORIZON = 270
HALF_LIFE = 240.0
CONFIGS = [("基线 DC", False), ("DC + Elo 外生特征", True)]


def main():
    df = datamod.load_raw()
    aggs = {name: backtest._Acc() for name, _ in CONFIGS}
    for cutoff in CUTOFFS:
        test = backtest.select_test(df, cutoff, HORIZON)
        print(f"\n[cutoff {cutoff}] 测试样本 {len(test)} 场")
        for name, use_elo in CONFIGS:
            m = DixonColesModel(half_life_days=HALF_LIFE, use_elo=use_elo).fit(
                df, verbose=False, as_of=cutoff)
            res = backtest.evaluate(m, test)
            if res:
                aggs[name].add(res)
                extra = f"  (elo_coef={m.elo_coef:+.3f})" if use_elo else ""
                print(f"   {name:<18} n={res['n']:>4} RPS={res['rps']:.4f} "
                      f"LogLoss={res['logloss']:.4f} Acc={res['acc']:.3f}{extra}")

    print("\n== 聚合结果（越低越好 RPS/LogLoss，越高越好命中率）==")
    print(f"  {'配置':<20}{'样本':>6}{'RPS':>9}{'LogLoss':>10}{'命中率':>8}")
    base = aggs["基线 DC"].out()
    for name, _ in CONFIGS:
        m = aggs[name].out()
        print(f"  {name:<20}{m['n']:>6}{m['rps']:>9.4f}{m['logloss']:>10.4f}{m['acc']:>8.3f}")
    elo = aggs["DC + Elo 外生特征"].out()
    d_rps = elo["rps"] - base["rps"]
    print(f"\n  RPS 变化: {d_rps:+.4f}  ->  Elo 外生特征"
          + ("【更好，可考虑采用】" if d_rps < -0.0005 else
             "【无显著改善，按铁律不采用】" if d_rps < 0.0005 else "【更差，不采用】"))


if __name__ == "__main__":
    main()
