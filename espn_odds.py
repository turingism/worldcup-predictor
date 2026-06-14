#!/usr/bin/env python3
"""ESPN odds capture layer: pull DraftKings 1X2 moneyline from ESPN's public API → CLV pipeline.

ESPN odds capture (legitimate, free): the same public ESPN API we use for live scores also exposes
bookmaker (DraftKings) 1X2 moneyline via the summary endpoint's `pickcenter`. We snapshot it over time
so each match accrues an "opening" (first-seen) and a "closing" (latest pre-kickoff) line → that's exactly
what CLV (clv.py) needs. We do NOT scrape bookmaker/odds-portal sites (ToS + anti-bot); this reuses an
API we already consume for scores.

ESPN 赔率抓取层（合法、免费）：我们抓实时比分用的同一个 ESPN 公开 API，其 summary 端点的 pickcenter
里带 DraftKings 的 1X2 美式赔率。按时间多次快照 → 每场比赛积累「开盘」（首次见到）与「闭盘」（开球前
最后一次）→ 正好喂给 CLV（clv.py）。不抓博彩/赔率门户站（ToS + 反爬），只复用已在用的比分 API。

诚实声明：
  - 这里的 "opening" 是『我们首次快照到的盘口』，不是字面意义的市场开盘；
  - 需要随赛事推进**反复快照**，开盘/闭盘才有时间跨度，CLV 才有意义；已开赛但没提前快照过的场次拿不到 CLV；
  - 即便数据齐全，CLV 显著为正才会解锁价值/Kelly 面板——模型没真打赢闭盘线就保持锁定（诚实门槛）。

用法：`python3 espn_odds.py`（快照 + 重建 odds.csv + 打印状态）。app 刷新时也会自动快照。
"""
from __future__ import annotations
import datetime as dt
import json
import os
import ssl
import urllib.request

import live   # 复用 _canon_name / NAME_FIX / ESPN 队名→martj42

SB_URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
          "scoreboard?dates={d1}-{d2}&limit=300")
SUM_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/summary?event={eid}"
SNAP_PATH = os.path.join(os.path.dirname(__file__), "data", "odds_snapshots.jsonl")
ODDS_CSV = os.path.join(os.path.dirname(__file__), "data", "odds.csv")
_CTX = ssl.create_default_context()


def _get(url: str, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
        return json.loads(r.read().decode("utf-8"))


def am2dec(ml) -> float:
    """American moneyline → decimal odds. +150→2.5, -200→1.5."""
    ml = float(ml)
    return round(1 + ml / 100, 4) if ml > 0 else round(1 + 100 / abs(ml), 4)


def fetch_current(start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    """Pull current DraftKings 1X2 (decimal) for World Cup matches that carry odds.
    Returns rows: {date, home, away(=martj42 names), kickoff_utc, o1, ox, o2}."""
    today = dt.date.today()
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    out = []
    for ev in sb.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if not any(o for o in (comp.get("odds") or [])):
            continue
        eid = ev.get("id")
        try:
            s = _get(SUM_URL.format(eid=eid))
        except Exception:  # noqa
            continue
        pcs = s.get("pickcenter") or []
        pc = next((p for p in pcs if (p.get("provider") or {}).get("name") == "DraftKings"), pcs[0] if pcs else None)
        if not pc:
            continue
        ho, ao, do = pc.get("homeTeamOdds") or {}, pc.get("awayTeamOdds") or {}, pc.get("drawOdds") or {}
        h_ml, a_ml, d_ml = ho.get("moneyLine"), ao.get("moneyLine"), do.get("moneyLine")
        if None in (h_ml, a_ml, d_ml):
            continue
        home = live._canon_name((ho.get("team") or {}).get("displayName", ""))
        away = live._canon_name((ao.get("team") or {}).get("displayName", ""))
        if not home or not away:
            continue
        try:
            utc = dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ")
        except (KeyError, ValueError):
            continue
        out.append({"date": str(utc.date()), "home": home, "away": away,
                    "kickoff_utc": utc.strftime("%Y-%m-%d %H:%M"),
                    "o1": am2dec(h_ml), "ox": am2dec(d_ml), "o2": am2dec(a_ml)})
    return out


def snapshot(now_iso: str | None = None) -> int:
    """Fetch current odds and append a timestamped snapshot to odds_snapshots.jsonl. Returns rows captured."""
    rows = fetch_current()
    if not rows:
        return 0
    stamp = now_iso or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(SNAP_PATH), exist_ok=True)
    with open(SNAP_PATH, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({**r, "captured_at": stamp}, ensure_ascii=False) + "\n")
    return len(rows)


def _load_snapshots() -> list[dict]:
    try:
        with open(SNAP_PATH, encoding="utf-8") as f:
            return [json.loads(ln) for ln in f if ln.strip()]
    except (FileNotFoundError, ValueError, OSError):
        return []


def build_odds_csv() -> dict:
    """Assemble odds.csv from snapshots: opening = earliest capture, closing = latest capture at/before
    kickoff. Only matches with ≥1 snapshot are written; open==close when only one snapshot exists.
    Returns a summary dict."""
    snaps = _load_snapshots()
    by_match: dict = {}
    for s in snaps:
        key = (s["home"], s["away"], s["date"])
        by_match.setdefault(key, []).append(s)
    rows, n_open_close = [], 0
    for (home, away, date), lst in by_match.items():
        lst.sort(key=lambda x: x["captured_at"])
        ko = lst[0]["kickoff_utc"]
        opening = lst[0]
        # closing = latest snapshot captured at/before kickoff (else latest available)
        pre = [x for x in lst if x["captured_at"][:16] <= ko] or lst
        closing = pre[-1]
        row = {"date": date, "home_team": home, "away_team": away,
               "odds_1": closing["o1"], "odds_x": closing["ox"], "odds_2": closing["o2"],
               "odds_1_open": opening["o1"], "odds_x_open": opening["ox"], "odds_2_open": opening["o2"]}
        if opening["captured_at"] != closing["captured_at"]:
            n_open_close += 1
        rows.append(row)
    if rows:
        import csv
        rows.sort(key=lambda r: (r["date"], r["home_team"]))
        cols = ["date", "home_team", "away_team", "odds_1", "odds_x", "odds_2",
                "odds_1_open", "odds_x_open", "odds_2_open"]
        tmp = ODDS_CSV + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        os.replace(tmp, ODDS_CSV)
    return {"matches": len(rows), "with_open_close": n_open_close, "snapshots": len(snaps)}


def main():
    n = snapshot()
    print(f"[espn_odds] snapshot 抓到 {n} 场当前盘口")
    s = build_odds_csv()
    print(f"[espn_odds] odds.csv 已重建：{s['matches']} 场（其中 {s['with_open_close']} 场有开盘≠闭盘）"
          f" · 累计快照 {s['snapshots']} 条")
    print("  CLV 需要『开盘+闭盘』有时间跨度且对应场次已完赛——随赛事多次快照才会累积。")
    print("  解锁价值/Kelly 仍需 CLV 显著为正（≥30 场且 t>1.65）；模型没打赢闭盘线就保持锁定。")


if __name__ == "__main__":
    main()
