"""E2 欧战账本：ESPN 回收欧冠/欧联正赛 → 统一 match 模型（E1 裁决主源）。

- 回收：按月窗迭代 ESPN scoreboard（复用 live._fetch_json 代理回退），只收
  正赛窗（9 月—次年 6 月，资格赛 7-8 月不收——口径：账本服务跨联赛校准与
  欧冠预测，小俱乐部资格赛不进池）；原始 ESPN 队名落盘（映射在装载层做，
  缓存不因映射表演进而失效）。
- 统一 match 模型（与两宇宙同 7 核心列）：date/home_team/away_team/home_score/
  away_score/tournament/neutral + 欧战特有列：season（起始年）/leg（1|2|0=单场）
  /agg_note（ESPN 合计比分与晋级方原文）。
- 两回合关系：load() 按（赛季, 赛事, 无序队对）配对 leg1/leg2 生成 tie_id；
  决赛=每（赛季, 赛事）最后一场，neutral=True（中立场决赛）。
- 队名映射：ESPN 显示名 → football-data 拼写（五大联赛俱乐部对齐 teams_zh
  CLUB 键；非五大俱乐部保留 ESPN 原名，属独立实体）。

用法：python3 eurodata.py            # 全量回收（约 80 请求，数分钟）
      eurodata.load()               # 统一模型帧（含映射与 tie 配对）
"""
from __future__ import annotations
import json
import os
import sys

import pandas as pd

COMPS = {"uefa.champions": "UEFA Champions League",
         "uefa.europa": "UEFA Europa League"}
SEASONS = [2021, 2022, 2023, 2024, 2025]    # 起始年：21-22 至 25-26 共 5 季
EURO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "euro")
RAW_CSV = os.path.join(EURO_DIR, "euro_matches_raw.csv")

# ESPN 显示名 → football-data 拼写（五大联赛俱乐部；装载时应用，不进原始缓存）。
# 非五大俱乐部不映射（保留 ESPN 名，独立实体）。
ESPN_FIX = {
    "Internazionale": "Inter", "AC Milan": "Milan", "AS Roma": "Roma",
    "Paris Saint-Germain": "Paris SG", "Bayern Munich": "Bayern Munich",
    "Borussia Dortmund": "Dortmund", "Bayer Leverkusen": "Leverkusen",
    "RB Leipzig": "RB Leipzig", "Eintracht Frankfurt": "Ein Frankfurt",
    "Borussia Mönchengladbach": "M'gladbach", "Union Berlin": "Union Berlin",
    "VfB Stuttgart": "Stuttgart", "SC Freiburg": "Freiburg",
    "1. FC Heidenheim": "Heidenheim", "TSG Hoffenheim": "Hoffenheim",
    "Atlético Madrid": "Ath Madrid", "Athletic Club": "Ath Bilbao",
    "Real Madrid": "Real Madrid", "Barcelona": "Barcelona",
    "Real Sociedad": "Sociedad", "Real Betis": "Betis", "Sevilla": "Sevilla",
    "Villarreal": "Villarreal", "Girona": "Girona", "Celta Vigo": "Celta",
    "Rayo Vallecano": "Vallecano", "Osasuna": "Osasuna", "Getafe": "Getafe",
    "Manchester City": "Man City", "Manchester United": "Man United",
    "Newcastle United": "Newcastle", "Tottenham Hotspur": "Tottenham",
    "West Ham United": "West Ham", "Aston Villa": "Aston Villa",
    "Brighton & Hove Albion": "Brighton", "Nottingham Forest": "Nott'm Forest",
    "Arsenal": "Arsenal", "Chelsea": "Chelsea", "Liverpool": "Liverpool",
    "Olympique Marseille": "Marseille", "Marseille": "Marseille",
    "Olympique Lyonnais": "Lyon", "LOSC Lille": "Lille", "Lille": "Lille",
    "AS Monaco": "Monaco", "Monaco": "Monaco", "Stade Rennais": "Rennes",
    "Rennes": "Rennes", "RC Lens": "Lens", "Lens": "Lens",
    "OGC Nice": "Nice", "Nice": "Nice", "Stade Brestois 29": "Brest",
    "Brest": "Brest", "Toulouse": "Toulouse", "Strasbourg": "Strasbourg",
    "Napoli": "Napoli", "Juventus": "Juventus", "Atalanta": "Atalanta",
    "Lazio": "Lazio", "Fiorentina": "Fiorentina", "Bologna": "Bologna",
    "Torino": "Torino",
}


def _season_windows(start_year: int) -> list[tuple[str, str]]:
    """正赛月窗：9 月 1 日 — 次年 6 月 30 日，逐月。"""
    out = []
    for i in range(10):
        a = pd.Timestamp(year=start_year, month=9, day=1) + pd.DateOffset(months=i)
        b = a + pd.DateOffset(months=1) - pd.Timedelta(days=1)
        out.append((a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
    return out


def harvest(seasons=SEASONS, comps=COMPS, verbose=True) -> pd.DataFrame:
    """按月窗回收完场，原始名落盘 RAW_CSV（原子写）。"""
    import live
    rows = []
    for lg, tourn in comps.items():
        for sy in seasons:
            n0 = len(rows)
            for d1, d2 in _season_windows(sy):
                url = live.espn_scoreboard_tmpl(lg).format(d1=d1, d2=d2)
                try:
                    payload = live._fetch_json(url)
                except Exception as e:  # noqa  单窗失败：记录后继续（终检覆盖率兜底）
                    print(f"[euro][warn] {lg} {d1}-{d2} 拉取失败：{e}")
                    continue
                for ev in payload.get("events", []):
                    comp = (ev.get("competitions") or [{}])[0]
                    st = (comp.get("status") or {}).get("type") or {}
                    if not (st.get("completed") and st.get("state") == "post"):
                        continue
                    side = {c.get("homeAway"): c for c in comp.get("competitors", [])}
                    h, a = side.get("home"), side.get("away")
                    if not h or not a:
                        continue
                    hs, as_ = h.get("score"), a.get("score")
                    if hs in (None, "") or as_ in (None, ""):
                        # 完场但 score 缺失：跳过并告警——绝不当真实 0-0 入账
                        print(f"[euro][warn] 完场缺比分，跳过：{str(ev.get('date', '?'))[:10]} "
                              f"{h['team']['displayName']} vs {a['team']['displayName']}")
                        continue
                    leg = (comp.get("leg") or {}).get("value") or 0
                    notes = "; ".join(n.get("headline", "") for n in comp.get("notes", []))
                    rows.append({
                        "date": str(pd.Timestamp(ev["date"]).date()),
                        "home_team": h["team"]["displayName"],
                        "away_team": a["team"]["displayName"],
                        "home_score": int(hs),
                        "away_score": int(as_),
                        "tournament": tourn, "season": sy,
                        "leg": int(leg), "agg_note": notes,
                    })
            if verbose:
                print(f"[euro] {tourn} {sy}-{(sy + 1) % 100:02d}: {len(rows) - n0} 场")
    df = pd.DataFrame(rows)
    # 合并式落盘：与既有缓存取并集去重——网络抖动导致的单窗缺口可多次重跑增量补齐，
    # 绝不因一次失败覆盖掉已收场次。
    if os.path.exists(RAW_CSV):
        old = pd.read_csv(RAW_CSV)
        df = pd.concat([old, df], ignore_index=True)
    # keep='last'：新抓在 concat 尾部——ESPN 事后修正的比分（改判/勘误）要能覆盖旧行
    df = (df.drop_duplicates(subset=["date", "home_team", "away_team"], keep="last")
            .sort_values("date"))
    os.makedirs(EURO_DIR, exist_ok=True)
    tmp = RAW_CSV + ".tmp"
    df.to_csv(tmp, index=False)
    os.replace(tmp, RAW_CSV)
    if verbose:
        print(f"[euro] 缓存共 {len(df)} 场 → {RAW_CSV}")
    return df


def load() -> pd.DataFrame:
    """统一 match 模型帧：应用队名映射、决赛 neutral=True、两回合 tie_id 配对。"""
    df = pd.read_csv(RAW_CSV)
    df["date"] = pd.to_datetime(df["date"])
    for c in ("home_team", "away_team"):
        df[c] = df[c].map(lambda x: ESPN_FIX.get(x, x))
    df["neutral"] = False
    # 决赛=每（赛季, 赛事）最后一场完赛 → 中立场。加赛季完结闸防赛中误标：
    # 赛季进行中重跑 load() 时「最近一场完赛」不是决赛，不得进锚点训练帧。
    # 口径（五季账本实测）：决赛落次年 5-18~6-10 且距半决赛次回合 ≥13 天；
    # 赛中相邻比赛日间隔 ≤8 天（半决赛两回合最远 05-09→05-17）。故仅当
    # ① 末场日期 ≥ 次年 5 月 15 日（决赛窗口）且 ② 末场距该组前一比赛日
    # >10 天（孤立收官场）时才标 neutral=True，两条都过不了=赛季未完结。
    for (sy, tn), g in df.groupby(["season", "tournament"]):
        days = sorted(g["date"].unique())
        if len(days) < 2:
            continue
        last, prev = pd.Timestamp(days[-1]), pd.Timestamp(days[-2])
        in_final_window = last >= pd.Timestamp(year=int(sy) + 1, month=5, day=15)
        lone_closing_day = (last - prev).days > 10
        if in_final_window and lone_closing_day:
            df.loc[g["date"].idxmax(), "neutral"] = True
    # 两回合配对：同赛季同赛事、无序队对、leg 1/2 → tie_id
    df["pair"] = [frozenset((h, a)) for h, a in zip(df.home_team, df.away_team)]
    df["tie_id"] = None
    two = df[df.leg.isin([1, 2])]
    for (sy, tn, pr), g in two.groupby(["season", "tournament", "pair"]):
        if len(g) == 2 and set(g.leg) == {1, 2}:
            tid = f"{tn.split()[1]}_{sy}_{'_'.join(sorted(pr))}"
            df.loc[g.index, "tie_id"] = tid
    return df.drop(columns=["pair"]).sort_values("date").reset_index(drop=True)


if __name__ == "__main__":
    seasons = [int(x) for x in sys.argv[1:]] or SEASONS
    harvest(seasons)
    d = load()
    print(f"[euro] load: {len(d)} 场 | tie 配对 {d.tie_id.notna().sum()} 场 "
          f"| 决赛 {int(d.neutral.sum())} 场")
