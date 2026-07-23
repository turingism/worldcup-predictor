"""C3 赛季推演预计算：25-26 赛季回溯推演（晋级树的联赛等价物，非树状图）。

对每联赛在多个 as_of 快照跑 clubsim.simulate_retro（as_of 前=事实、后=模型抽样，
模型只用 as_of 前数据训练防泄漏），输出 争冠/前四/降级 概率随赛季演进序列，
终局用真实终表 0/1 收口。产物 data/club/seasonsim_<code>.json，联赛页直读。

26-27 季前推演仍走 club_preseason.py（升班马名单确认前有运行闸）；届时页面
同一组件换数据源即可。用法：python3 club_seasonsim.py [sims]
"""
import json
import os
import sys
from datetime import datetime

import clubdata
import clubsim

SNAPSHOTS = ["2025-08-01", "2025-10-01", "2025-12-01",
             "2026-02-01", "2026-04-01", "2026-05-01"]
SEASON_START, SEASON_END = "2025-07-01", "2026-06-30"
SEASON_LABEL = "2025-26"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "club")


def build(code: str, sims: int = 5000) -> dict:
    feeder = clubdata.FEEDER.get(code)
    df = clubdata.load(code)
    season = clubsim.season_slice(df, SEASON_START, SEASON_END)
    snaps = []
    for a in SNAPSHOTS:
        rows, nf, nr = clubsim.simulate_retro(code, SEASON_START, SEASON_END, a,
                                              sims=sims, feeder=feeder)
        snaps.append({"as_of": a, "played": nf, "remaining": nr,
                      "rows": [{k: (round(v, 4) if isinstance(v, float) else v)
                                for k, v in r.items()} for r in rows]})
    st = clubsim.standings(season)
    n = len(st)
    fin = [{"team": r["team"],
            "title": 1.0 if i == 0 else 0.0,
            "top4": 1.0 if i < 4 else 0.0,
            "bottom3": 1.0 if i >= n - 3 else 0.0,
            "exp_pts": float(r["pts"]), "exp_rank": float(i + 1)}
           for i, r in enumerate(st)]
    return {"code": code, "season": SEASON_LABEL, "sims": sims,
            "mode": "retro",
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "football-data.co.uk",
            "data_through": str(df.date.max().date()),
            "snapshots": snaps,
            "final": {"as_of": str(season.date.max().date()), "rows": fin}}


def main():
    sims = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    for code in clubdata.FEEDER:                      # 五大联赛
        out = build(code, sims=sims)
        path = os.path.join(_DIR, f"seasonsim_{code}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, path)
        top = out["snapshots"][-1]["rows"][0]
        print(f"[seasonsim] {code}: {len(out['snapshots'])} 快照 + 终局 → {path}"
              f" | {SNAPSHOTS[-1]} 争冠第一 {top['team']} {top['title']:.1%}")


if __name__ == "__main__":
    main()
