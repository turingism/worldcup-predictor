#!/usr/bin/env python3
"""P1-⑤/P2：五大联赛 25-26 季前概率预计算 → data/club/preseason_<码>.json。

网页联赛 tab 直读 JSON（毫秒级），避免请求内跑 5000 次模拟。
升班马名单 = 25-26 真实名单（football-data 拼写，07-16 已与 feeder 帧核对）；
附加赛胜者无法从终表推导，必须显式维护——新赛季更新此表后重跑本脚本。
用法：python3 club_preseason.py [E0 SP1 ...]（无参=全部五联赛）
"""
from __future__ import annotations
import datetime as dt
import json
import os
import sys

import clubdata
import clubsim

PROMOTED_2526 = {
    "E0": ["Leeds", "Burnley", "Sunderland"],
    "SP1": ["Levante", "Elche", "Oviedo"],
    "I1": ["Sassuolo", "Pisa", "Cremonese"],
    "D1": ["FC Koln", "Hamburg"],          # 直升 2 队；16 名附加赛保级不建模（诚实近似）
    "F1": ["Lorient", "Paris FC", "Metz"],
}
SEASON = "2025-26"
SIMS = 5000


def path_for(code: str) -> str:
    return os.path.join(os.path.dirname(__file__), "data", "club", f"preseason_{code}.json")


def build(code: str, sims: int = SIMS) -> dict:
    rows, teams = clubsim.simulate_preseason(
        code, PROMOTED_2526[code], sims=sims,
        feeder=clubdata.FEEDER[code], tiebreak=clubsim.LEAGUE_TIEBREAK.get(code, "gd"))
    df = clubdata.load(code)
    return {
        "league": clubdata.LEAGUES[code], "code": code, "season": SEASON,
        "sims": sims, "computed_at": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "data_through": str(df.date.max().date()),
        "source": "football-data.co.uk",
        "promoted": PROMOTED_2526[code],
        "rows": rows,
    }


def main():
    codes = sys.argv[1:] or list(PROMOTED_2526)
    for code in codes:
        print(f"[preseason] {code} 模拟 {SIMS} 次…", flush=True)
        d = build(code)
        with open(path_for(code), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=1)
        top = d["rows"][0]
        print(f"[preseason] {code} 完成：{top['team']} 夺冠 {top['title']*100:.1f}% "
              f"→ {path_for(code)}", flush=True)


if __name__ == "__main__":
    main()
