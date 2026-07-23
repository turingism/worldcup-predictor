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


def _monday_grid(start: str, end: str) -> list[str]:
    """周一序列（周粒度 as_of 网格，C4 冠军概率演进用）。"""
    import pandas as pd
    d = pd.Timestamp(start)
    d += pd.Timedelta(days=(7 - d.weekday()) % 7)
    out = []
    while d <= pd.Timestamp(end):
        out.append(str(d.date()))
        d += pd.Timedelta(days=7)
    return out


def build_title_series(code: str, season, sims: int = 3000) -> tuple[dict, list]:
    """C4 冠军维度：周粒度 title 概率序列 + 关键场次影响窗口。

    key_shifts 口径：对任一快照 title≥5% 的争冠队，取相邻周 |Δtitle| 最大的
    3 个窗口，附该队窗口内实际赛果——展示「概率跳变与同窗赛果」的对应，
    不做单场因果归因（多场同窗时如实列出全部）。"""
    import pandas as pd
    grid = _monday_grid("2025-08-04", str(season.date.max().date()))
    feeder = clubdata.FEEDER.get(code)
    series: dict[str, list] = {}
    for a in grid:
        rows, _, _ = clubsim.simulate_retro(code, SEASON_START, SEASON_END, a,
                                            sims=sims, feeder=feeder)
        for r in rows:
            series.setdefault(r["team"], []).append(round(r["title"], 4))
    contenders = [t for t, ps in series.items() if max(ps) >= 0.05]
    contenders.sort(key=lambda t: -max(series[t]))
    shifts = []
    for t in contenders:
        ps = series[t]
        deltas = sorted(((ps[i + 1] - ps[i], i) for i in range(len(ps) - 1)),
                        key=lambda x: -abs(x[0]))[:3]
        for dp, i in deltas:
            if abs(dp) < 0.03:                       # 3pp 以下不算关键
                continue
            lo, hi = pd.Timestamp(grid[i]), pd.Timestamp(grid[i + 1])
            w = season[(season.date >= lo) & (season.date < hi)
                       & ((season.home_team == t) | (season.away_team == t))]
            ms = []
            for r in w.itertuples():
                at_home = r.home_team == t
                gf, ga = (int(r.home_score), int(r.away_score)) if at_home \
                    else (int(r.away_score), int(r.home_score))
                ms.append({"date": str(r.date.date()),
                           "opp": r.away_team if at_home else r.home_team,
                           "home": at_home, "score": f"{gf}-{ga}",
                           "res": "W" if gf > ga else ("D" if gf == ga else "L")})
            shifts.append({"team": t, "from": grid[i], "to": grid[i + 1],
                           "delta": round(dp, 4), "matches": ms})
    shifts.sort(key=lambda s: -abs(s["delta"]))
    keep = {t: [round(p, 4) for p in ps] for t, ps in series.items()
            if max(ps) >= 0.01}                      # 只存 ≥1% 出现过的队，控体积
    return {"as_of": grid, "sims": sims, "teams": keep}, shifts[:8]


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
    title_series, key_shifts = build_title_series(code, season)
    return {"code": code, "season": SEASON_LABEL, "sims": sims,
            "mode": "retro",
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "football-data.co.uk",
            "data_through": str(df.date.max().date()),
            "snapshots": snaps,
            "final": {"as_of": str(season.date.max().date()), "rows": fin},
            "title_series": title_series, "key_shifts": key_shifts}


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
