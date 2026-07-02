#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""模型 vs 博彩盘口 对标（借鉴高盛"与 bookmakers' odds 对照"）。

盘口是行业金标准：把博彩 1X2 十进制赔率转成隐含概率（去掉 margin/overround 归一），
和我们模型在**同一批比赛**上比 RPS。模型 RPS 越接近（或低于）盘口，说明越好。
评级冻结在这批比赛最早日期之前（无泄漏）。

数据：data/odds.csv（date,home_team,away_team,odds_1,odds_x,odds_2，队名须对齐 martj42）。
目前仅 5 场 2022 世界杯真实闭盘赔率做种子样本——统计量不足，仅演示口径与机制；
扩样本见文末说明（OddsPortal 抓取受 ToS 限制，请自行决定来源）。
"""
from __future__ import annotations
import datetime as dt
import os

import numpy as np
import pandas as pd

import data as datamod
import devig
from backtest import _rps
from model import DixonColesModel

ODDS_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.csv")


def _implied(o1, ox, o2):
    """十进制赔率 -> 去 margin 的隐含概率 [主胜,平,客胜]（Shin 口径，见 devig.py / bt_devig.py）。"""
    return devig.shin(o1, ox, o2)


def _find_result(played, home, away, date, tol_days=2):
    """在已赛数据里按队伍(两序)+日期(±tol)找这场，返回 (实际结果0/1/2, 是否需调换主客)。"""
    d = pd.Timestamp(date)
    lo, hi = d - pd.Timedelta(days=tol_days), d + pd.Timedelta(days=tol_days)
    win = played[(played["date"] >= lo) & (played["date"] <= hi)]
    for _, r in win.iterrows():
        h, a = r["home_team"], r["away_team"]
        if {h, a} != {home, away}:
            continue
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        swap = (h == away)          # results.csv 主客与 odds 相反 -> 赔率需调换
        # 以 odds 的 home 视角给结果：0 odds主胜 1平 2 odds客胜
        if hs == as_:
            return 1, swap
        odds_home_won = (hs > as_) ^ swap
        return (0 if odds_home_won else 2), swap
    return None, None


def main():
    odds = pd.read_csv(ODDS_PATH)
    odds["date"] = pd.to_datetime(odds["date"])
    df = datamod.load_raw()
    played = datamod.played(df)

    cutoff = (odds["date"].min() - pd.Timedelta(days=1)).date()
    print(f"[odds] {len(odds)} 场样本；模型评级冻结于 {cutoff} 之前（无泄漏）")
    model = DixonColesModel(half_life_days=240.0).fit(df, verbose=False, as_of=cutoff)

    rows = []
    m_rps = b_rps = 0.0
    margins = []
    for _, o in odds.iterrows():
        outcome, swap = _find_result(played, o["home_team"], o["away_team"], o["date"])
        if outcome is None:
            print(f"  ! 未匹配到结果：{o['home_team']} vs {o['away_team']} {o['date'].date()}")
            continue
        # 盘口隐含概率（按 odds 的 home 视角）
        bp = _implied(o["odds_1"], o["odds_x"], o["odds_2"])
        margins.append(1/o["odds_1"] + 1/o["odds_x"] + 1/o["odds_2"] - 1)
        # 模型概率（中立场，世界杯）；按 odds 的主客朝向取
        r = model.predict(o["home_team"], o["away_team"], neutral=True)
        mp = [r["p_home"], r["p_draw"], r["p_away"]]
        m_rps += _rps(mp[0], mp[1], mp[2], outcome)
        b_rps += _rps(bp[0], bp[1], bp[2], outcome)
        rows.append((o["home_team"], o["away_team"], outcome, mp, bp))

    n = len(rows)
    if not n:
        print("无可对标样本。"); return
    print(f"\n  {'比赛':<26}{'实际':>5}{'模型(主/平/客)':>22}{'盘口(主/平/客)':>22}")
    lab = {0: "主胜", 1: "平", 2: "客胜"}
    for h, a, oc, mp, bp in rows:
        print(f"  {h+' vs '+a:<26}{lab[oc]:>5}"
              f"{f'{mp[0]:.0%}/{mp[1]:.0%}/{mp[2]:.0%}':>22}"
              f"{f'{bp[0]:.0%}/{bp[1]:.0%}/{bp[2]:.0%}':>22}")
    print(f"\n  样本 n={n} ｜ 盘口平均抽水 margin={np.mean(margins)*100:.1f}%")
    print(f"  模型 RPS = {m_rps/n:.4f}   盘口 RPS = {b_rps/n:.4f}   "
          f"差 = {(m_rps-b_rps)/n:+.4f}（负=模型更准；盘口是金标准，接近即优秀）")
    print("\n  注：5 场样本统计量不足，仅演示对标口径。扩样本请自备赔率来源（OddsPortal 受")
    print("      ToS/反爬限制，the-odds-api 历史需付费）；填充 data/odds.csv 同格式即可复用。")


if __name__ == "__main__":
    main()
