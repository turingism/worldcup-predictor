"""Live-results layer: pull finished 2026 World Cup match scores from ESPN's public scoreboard API.

实时赛果层：从 ESPN 公开 scoreboard API 拉取 2026 世界杯正赛已完场比分。

为什么需要它：martj42/international_results 是人工维护，开赛期间有 1~3 天滞后；
ESPN 的 site.api.espn.com 是免 key 公开接口，完场后分钟级可得，含点球大战比分。

数据流：fetch_and_save() -> data/live_results.json -> data.merge_live() 合并进 DF
（填充 results.csv 里的 NA 赛程行 / 补缺失的淘汰赛行），训练与括号锁定自动生效。

接口约束：dates=YYYYMMDD-YYYYMMDD 范围查询窗口太大时很慢（>30s），按 7 天分块拉。
"""
from __future__ import annotations
import datetime as dt
import json
import os
import urllib.request

import schedule
import wc2026

ESPN_URL = ("https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
            "scoreboard?dates={d1}-{d2}&limit=300")
LIVE_PATH = os.path.join(os.path.dirname(__file__), "data", "live_results.json")

TOURN_START = dt.date(2026, 6, 11)
TOURN_END = dt.date(2026, 7, 19)
GROUP_STAGE_END = dt.date(2026, 6, 28)   # R32 从 6-28 起（UTC 口径含界）

# ESPN displayName -> martj42 队名（其余 44 队两边完全一致，已全量 diff 核对）
NAME_FIX = {
    "Czechia": "Czech Republic",
    "Bosnia-Herzegovina": "Bosnia and Herzegovina",
    "Congo DR": "DR Congo",
    "Türkiye": "Turkey",
}
_TEAMS48 = {t for g in wc2026.GROUPS.values() for t in g}
# 小组赛对阵（顺序无关）-> schedule 的规范 (home, away)
_GROUP_CANON = {frozenset(p): p for p in schedule.GROUP}


def _canon_name(espn_name: str) -> str | None:
    """ESPN 队名 -> martj42 队名；占位名（'Group A 2nd Place' 等）返回 None。"""
    n = NAME_FIX.get(espn_name, espn_name)
    return n if n in _TEAMS48 else None


def _fetch_json(url: str, timeout: int = 60) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _parse_events(payload: dict) -> list[dict]:
    """把 ESPN events 解析成完场记录列表（未完场/占位对阵跳过）。"""
    out = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        st = (comp.get("status") or {}).get("type") or {}
        if not (st.get("completed") and st.get("state") == "post"):
            continue
        side = {}
        for c in comp.get("competitors", []):
            nm = _canon_name((c.get("team") or {}).get("displayName", ""))
            if nm is None:
                break
            try:
                score = int(c.get("score"))
            except (TypeError, ValueError):
                break
            pens = c.get("shootoutScore")
            side[c.get("homeAway")] = (nm, score, pens)
        if set(side) != {"home", "away"}:
            continue
        (h, gh, ph), (a, ga, pa) = side["home"], side["away"]
        try:
            utc = dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ")
        except (KeyError, ValueError):
            continue
        is_group = (frozenset((h, a)) in _GROUP_CANON
                    and utc.date() < GROUP_STAGE_END)
        rec = {"home": h, "away": a, "gh": gh, "ga": ga,
               "stage": "group" if is_group else "ko",
               "utc": utc.strftime("%Y-%m-%d %H:%M")}
        if is_group:
            # 日期对齐 results.csv 的赛程行：用官方赛程的比赛日（场馆当地日）
            ch, ca = _GROUP_CANON[frozenset((h, a))]
            gv = schedule.group_venue(ch, ca) or {}
            rec["date"] = (gv.get("local") or "")[:10] or str(utc.date())
        else:
            rec["date"] = str(utc.date())
            ven = (comp.get("venue") or {}).get("address") or {}
            rec["city"], rec["country"] = ven.get("city", ""), ven.get("country", "")
            if gh == ga:  # 平局 -> 点球分胜负
                if ph is not None and pa is not None and ph != pa:
                    rec["winner"] = h if int(ph) > int(pa) else a
                    rec["pens"] = [int(ph), int(pa)]
                # 点球数据缺失时不写 winner，合并层会跳过该场（宁缺毋错）
        out.append(rec)
    return out


def fetch_live(start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    """拉取 [start, end] 窗口内全部完场记录（7 天分块，避免大窗口超时）。"""
    start = start or TOURN_START
    end = end or min(dt.date.today() + dt.timedelta(days=1), TOURN_END)
    recs, cur = {}, start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=6), end)
        url = ESPN_URL.format(d1=cur.strftime("%Y%m%d"), d2=chunk_end.strftime("%Y%m%d"))
        for r in _parse_events(_fetch_json(url)):
            recs[frozenset((r["home"], r["away"])), r["stage"], r["utc"]] = r
        cur = chunk_end + dt.timedelta(days=1)
    return sorted(recs.values(), key=lambda r: (r["utc"], r["home"]))


def _parse_state(payload: dict) -> list[dict]:
    """解析 ESPN events 的实时状态（pre 未开 / in 进行中 / post 已完），含当前比分与分钟。
    与 _parse_events 不同：不过滤未完场，用于看板的『正在比赛/即将开赛』展示，不写入训练数据。"""
    out = []
    for ev in payload.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        stt = comp.get("status") or {}
        typ = stt.get("type") or {}
        state = typ.get("state")                    # pre / in / post
        if state not in ("pre", "in", "post"):
            continue
        side, ok = {}, True
        for c in comp.get("competitors", []):
            nm = _canon_name((c.get("team") or {}).get("displayName", ""))
            if nm is None:                          # 占位对阵（小组名次未定）跳过
                ok = False
                break
            try:
                score = int(c.get("score")) if str(c.get("score", "")).strip() != "" else 0
            except (TypeError, ValueError):
                score = 0
            side[c.get("homeAway")] = (nm, score)
        if not ok or set(side) != {"home", "away"}:
            continue
        (h, gh), (a, ga) = side["home"], side["away"]
        try:
            utc = dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").strftime("%Y-%m-%d %H:%M")
        except (KeyError, ValueError):
            utc = ""
        out.append({"home": h, "away": a, "gh": gh, "ga": ga, "state": state,
                    "clock": stt.get("displayClock", ""), "period": stt.get("period"),
                    "detail": typ.get("shortDetail") or typ.get("detail") or "",
                    "utc": utc})
    return out


def fetch_status(start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    """拉取 [today-1, today+1] 窗口内全部场次的实时状态快照（pre/in/post）。
    只读、不写盘、不进训练——供看板展示『正在比赛/即将开赛』。单源失败返回已得部分。"""
    today = dt.date.today()
    start = start or max(TOURN_START, today - dt.timedelta(days=1))
    end = end or min(TOURN_END, today + dt.timedelta(days=1))
    out, cur = {}, start
    while cur <= end:
        chunk_end = min(cur + dt.timedelta(days=6), end)
        url = ESPN_URL.format(d1=cur.strftime("%Y%m%d"), d2=chunk_end.strftime("%Y%m%d"))
        try:
            for r in _parse_state(_fetch_json(url, timeout=15)):
                out[frozenset((r["home"], r["away"])), r["utc"]] = r
        except Exception:  # noqa  单块失败不致命，返回已拿到的
            pass
        cur = chunk_end + dt.timedelta(days=1)
    return list(out.values())


def load_saved() -> list[dict]:
    try:
        with open(LIVE_PATH, encoding="utf-8") as f:
            d = json.load(f)
        return d.get("results", []) if isinstance(d, dict) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _save(results: list[dict]) -> None:
    os.makedirs(os.path.dirname(LIVE_PATH), exist_ok=True)
    tmp = LIVE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "results": results}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, LIVE_PATH)


def fetch_and_save(incremental: bool = True) -> tuple[bool, dict]:
    """拉取并持久化。返回 (是否有新完场, 摘要)。

    incremental=True 时只查「已存最晚完场日 - 1 天」之后的窗口（完场记录不可变，
    日常轮询秒级返回）；False 或无存档时全量回拉整届窗口。
    """
    saved = load_saved()
    start = None
    if incremental and saved:
        last = max(r["utc"][:10] for r in saved)
        start = max(TOURN_START,
                    dt.datetime.strptime(last, "%Y-%m-%d").date() - dt.timedelta(days=1))
    fresh = fetch_live(start=start)
    by_key = {(frozenset((r["home"], r["away"])), r["stage"], r["utc"]): r for r in saved}
    n_before = len(by_key)
    for r in fresh:
        by_key[frozenset((r["home"], r["away"])), r["stage"], r["utc"]] = r
    merged = sorted(by_key.values(), key=lambda r: (r["utc"], r["home"]))
    changed = len(merged) != n_before
    if changed or not os.path.exists(LIVE_PATH):
        _save(merged)
    n_group = sum(1 for r in merged if r["stage"] == "group")
    return changed, {"total": len(merged), "group": n_group,
                     "ko": len(merged) - n_group}


if __name__ == "__main__":
    chg, s = fetch_and_save(incremental=False)
    print(f"changed={chg} {s}")
    for r in load_saved():
        extra = f" 点球 {r['pens'][0]}-{r['pens'][1]} {r.get('winner','')}胜" if r.get("pens") else ""
        print(f"  [{r['stage']}] {r['date']} {r['home']} {r['gh']}-{r['ga']} {r['away']}{extra}")
