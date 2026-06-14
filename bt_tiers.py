#!/usr/bin/env python3
"""实验回测：赛事强度分级加权是否优于现有"友谊0.5/其余1.0"？

借鉴高盛/Elo 的赛事重要性分级思路：世界杯/洲际杯正赛 > 预选赛 > 友谊赛。
严格同 cutoff、同数据、同 half_life，只差训练样本的赛事权重方案。
"""
from __future__ import annotations
import datetime as dt

import backtest
import data as datamod
from model import DixonColesModel

CUTOFFS = [dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
HORIZON = 270
HALF_LIFE = 240.0

# tier: friendly / qualification / major / other
SCHEMES = [
    ("基线(友0.5/其余1)", None),
    ("等价基线", {"friendly": 0.5, "qualification": 1.0, "major": 1.0, "other": 1.0}),
    ("温和抬大赛", {"friendly": 0.5, "qualification": 0.85, "major": 1.2, "other": 1.0}),
    ("中度抬大赛", {"friendly": 0.4, "qualification": 0.8, "major": 1.3, "other": 1.0}),
    ("强抬大赛", {"friendly": 0.3, "qualification": 0.7, "major": 1.5, "other": 1.0}),
    ("只压预选/友谊", {"friendly": 0.4, "qualification": 0.7, "major": 1.0, "other": 1.0}),
]


def main():
    df = datamod.load_raw()
    aggs = {name: backtest._Acc() for name, _ in SCHEMES}
    for cutoff in CUTOFFS:
        test = backtest.select_test(df, cutoff, HORIZON)
        for name, cw in SCHEMES:
            m = DixonColesModel(half_life_days=HALF_LIFE, comp_weights=cw).fit(
                df, verbose=False, as_of=cutoff)
            res = backtest.evaluate(m, test)
            if res:
                aggs[name].add(res)

    print("\n== 聚合结果（n=合计样本；RPS/LogLoss 越低越好，命中率越高越好）==")
    print(f"  {'方案':<18}{'样本':>6}{'RPS':>9}{'LogLoss':>10}{'命中率':>8}{'ΔRPS':>9}")
    base = aggs["基线(友0.5/其余1)"].out()
    best = None
    for name, _ in SCHEMES:
        m = aggs[name].out()
        d = m["rps"] - base["rps"]
        print(f"  {name:<18}{m['n']:>6}{m['rps']:>9.4f}{m['logloss']:>10.4f}"
              f"{m['acc']:>8.3f}{d:>+9.4f}")
        if name not in ("基线(友0.5/其余1)", "等价基线") and (best is None or m["rps"] < best[1]):
            best = (name, m["rps"], d)
    if best:
        verdict = ("【更好，可考虑采用】" if best[2] < -0.0005 else
                   "【无显著改善，按铁律不采用】" if best[2] < 0.0005 else "【更差，不采用】")
        print(f"\n  最佳实验方案: {best[0]}  ΔRPS={best[2]:+.4f} {verdict}")


if __name__ == "__main__":
    main()
