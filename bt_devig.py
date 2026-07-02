#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""de-vig 口径回测：proportional vs odds_ratio vs shin，谁还原的盘口概率最贴真实赛果。

只评估**盘口本身**（不掺模型）：用 data/odds.csv 的闭盘 1X2 赔率，三种 de-vig 各算隐含概率，
在真实赛果上比 RPS（越低越好）+ LogLoss（越低越好）+ 赋实际结果平均概率（越高越好）。
项目铁律：哪种更好用数字说话；样本小则如实标注、只看趋势。零碰 GLM。
"""
from __future__ import annotations
import os
import numpy as np
import pandas as pd

import data as datamod
import devig
from backtest import _rps
from bt_odds import _find_result

ODDS_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.csv")


def _logloss(p, outcome):
    return -np.log(max(p[outcome], 1e-12))


def evaluate():
    odds = pd.read_csv(ODDS_PATH)
    odds["date"] = pd.to_datetime(odds["date"])
    played = datamod.played(datamod.load_raw())

    acc = {m: {"rps": 0.0, "ll": 0.0, "pact": 0.0} for m in devig.METHODS}
    n = 0
    for _, o in odds.iterrows():
        if pd.isna(o["odds_1"]) or pd.isna(o["odds_x"]) or pd.isna(o["odds_2"]):
            continue
        outcome, _ = _find_result(played, o["home_team"], o["away_team"], o["date"])
        if outcome is None:
            continue
        n += 1
        for m, fn in devig.METHODS.items():
            p = fn(o["odds_1"], o["odds_x"], o["odds_2"])
            acc[m]["rps"] += _rps(p[0], p[1], p[2], outcome)
            acc[m]["ll"] += _logloss(p, outcome)
            acc[m]["pact"] += p[outcome]
    return acc, n


def main():
    acc, n = evaluate()
    if not n:
        print("无可对标样本（odds.csv 未匹配到赛果）。"); return
    print(f"\n  de-vig 口径对标 · n={n} 场真实闭盘赔率 vs 真实赛果\n")
    print(f"  {'方法':<14}{'RPS↓':>10}{'LogLoss↓':>12}{'赋实际结果均概↑':>18}")
    base = acc["proportional"]
    rows = []
    for m in ("proportional", "odds_ratio", "shin"):
        a = acc[m]
        rps, ll, pact = a["rps"] / n, a["ll"] / n, a["pact"] / n
        rows.append((m, rps, ll, pact))
        print(f"  {m:<14}{rps:>10.4f}{ll:>12.4f}{pact:>17.1%}")
    print(f"\n  相对 proportional 改善（负=更好）：")
    for m, rps, ll, pact in rows[1:]:
        d_rps = rps - base["rps"] / n
        d_ll = ll - base["ll"] / n
        print(f"    {m:<12} ΔRPS={d_rps:+.4f}  ΔLogLoss={d_ll:+.4f}")
    best = min(rows, key=lambda r: r[1])[0]
    print(f"\n  RPS 最优：{best}")
    print(f"  注：n={n} 小样本，差异多在噪声量级；采用与否以 RPS/LogLoss 一致变好为准，否则保留原 proportional。")
    print("  这是对**盘口还原口径**的改良，不碰 GLM；个人/教育项目，非投注建议。")


if __name__ == "__main__":
    main()
