"""90分钟口径 A/B 回测：训练集剔除『已知加时场次』(data.known_et_mask) 是否改善。

背景（docs/score-basis.md）：results.csv 淘汰赛比分含加时。可识别的加时场次
（点球场次 + fjelstul 世界杯 ET 标记）约占近16年训练窗 1.8%，其中『加时分胜负』
场次的 90 分钟 W/D/L 标签错误（记胜实平）。本脚本量化剔除它们对样本外
RPS/LogLoss/命中率的影响——采纳与否以此为据（无证据不改生产核心）。

口径：as-of 截断防泄漏；两组共用完全相同的测试集（只动训练集）。
"""
from __future__ import annotations
import datetime as dt

import config
import data as datamod
from backtest import evaluate, select_test
from model import DixonColesModel


def main():
    df = datamod.load_raw()
    mask = datamod.known_et_mask(df)
    df_ex = df.loc[~mask]
    print(f"全量 {len(df)} 行，剔除已知加时 {int(mask.sum())} 行")
    cutoffs = [dt.date(2023, 6, 1), dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
    horizon = 270
    agg = {"base": [0, 0.0, 0.0, 0.0], "ex_et": [0, 0.0, 0.0, 0.0]}
    for cutoff in cutoffs:
        test = select_test(df, cutoff, horizon)
        m_base = DixonColesModel(half_life_days=config.NATIONAL_HALF_LIFE).fit(
            df, verbose=False, as_of=cutoff)
        m_ex = DixonColesModel(half_life_days=config.NATIONAL_HALF_LIFE).fit(
            df_ex, verbose=False, as_of=cutoff)
        for name, m in (("base", m_base), ("ex_et", m_ex)):
            r = evaluate(m, test)
            if r:
                a = agg[name]
                a[0] += r["n"]; a[1] += r["rps"] * r["n"]
                a[2] += r["logloss"] * r["n"]; a[3] += r["acc"] * r["n"]
                print(f"  [{cutoff}] {name:<6} n={r['n']:>4} RPS={r['rps']:.4f} "
                      f"LogLoss={r['logloss']:.4f} Acc={r['acc']:.3f}")
    print("\n== 聚合 ==")
    for name, a in agg.items():
        if a[0]:
            print(f"  {name:<6} n={a[0]} RPS={a[1]/a[0]:.4f} "
                  f"LogLoss={a[2]/a[0]:.4f} Acc={a[3]/a[0]:.3f}")
    d = agg["ex_et"][1]/agg["ex_et"][0] - agg["base"][1]/agg["base"][0]
    print(f"\n  ΔRPS(ex_et − base) = {d:+.5f}  （负=剔除更好；采纳门槛见项目铁律）")


if __name__ == "__main__":
    main()
