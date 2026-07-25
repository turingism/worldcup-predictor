#!/usr/bin/env python3
"""首页总览（L0）数据装配（P0-H，需求见 docs/UPGRADE_REQUIREMENTS_2026-07-25.md 第 11 节）。

定位：`/api/home` 的**唯一**数据来源，回答「这个系统现在有什么、可不可信、接下来看什么」。
放独立模块而不是堆进 app.py，是因为首页要跨全部赛事读七八种产物，塞进路由层会立刻变成第二个巨石。

四条铁律（测试逐条锁死）：
① **只读**：不训练模型（不碰 clubpredict.get_club_model）、不跑蒙特卡洛（不碰 clubsim/TournamentSimulator）、
   不冻结不回补（不碰 verify.freeze/backfill）、不联网（不碰 live._fetch_json / urlopen）、不写盘。
   连 clubdata.load_fixtures() 都不能用——它带 stale-while-revalidate 会起后台下载线程。
② **验证账本绝不跨赛事混池**：verification 只按赛事并列，响应里不存在 total/summary/overall_accuracy
   之类的跨赛事汇总字段（registry 层不变量在 API 层的延伸）。
③ **不冒充**：赛季不匹配或 mode=retro 的 seasonsim 缓存不得当作新赛季夺冠概率
   （seasonsim_E0.json 现为 season=2025-26/mode=retro，终局表里冠军是 100%——直接取就是拿上季结果冒充预测）。
   未来比赛的概率只认**已冻结账本**，不现算（现算值与冻结值并存会让同一场比赛出现两个数字）。
④ **不出投注建议**：无赔率、无 EV、无价值、无推荐；jc_review（竞彩复盘）整体不进首页。
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import threading

import pandas as pd

import clubdata
import clubverify
import events as eventsmod
import teams_zh
import verify

_DIR = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(_DIR, "data")
CLUB = clubdata.CLUB_DIR
BJ = clubverify.BJ

SCHEMA_VERSION = 1
TTL_SECONDS = 60
HORIZON_DAYS = 14

# 进程内缓存 + single-flight：首页是默认落地页，冷启动并发下不能各建各的
_CACHE: dict = {}
_LOCK = threading.Lock()


# ---------- 通用小工具 ----------
def _stat(path: str) -> tuple:
    try:
        st = os.stat(path)
        return (os.path.relpath(path, _DIR), st.st_mtime_ns, st.st_size)
    except OSError:
        return (os.path.relpath(path, _DIR), 0, 0)


def _fingerprint() -> str:
    """输入指纹：任一产物变化即失效（TTL 之外的第二道触发）。
    刻意不含 market_*.json 与 jc_review（前者首页不用，后者红线禁入）。"""
    paths = [os.path.join(_DIR, "model_meta.json"), os.path.join(DATA, "results.csv"),
             os.path.join(DATA, "live_results.json"), os.path.join(DATA, "predictions.json"),
             os.path.join(CLUB, "fixtures.csv"), clubverify.TZ_VERIFIED_PATH,
             os.path.join(DATA, "euro", "euro_matches_raw.csv")]
    paths += sorted(glob.glob(os.path.join(DATA, "predictions_*.json")))
    paths += sorted(glob.glob(os.path.join(CLUB, "seasonsim_*.json")))
    paths += sorted(glob.glob(os.path.join(CLUB, "[A-Z]*_????.csv")))
    return str(hash(tuple(_stat(p) for p in paths)))


def _now_bj() -> dt.datetime:
    return dt.datetime.now(tz=BJ)


def _season_label(ev: dict) -> str:
    """联赛赛季标签：window 起止年 → '2026-27'（与 seasonsim JSON 的 season 同格式）。"""
    a, b = (dt.date.fromisoformat(x) for x in ev["window"])
    return f"{a.year}-{str(b.year)[2:]}" if b.year != a.year else str(a.year)


def _json(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return None


# ---------- 数据新鲜度 ----------
def _csvs(code: str) -> list[str]:
    return sorted(glob.glob(os.path.join(CLUB, f"{code}_????.csv")))


def _league_facts(code: str) -> dict:
    """某联赛的本地事实：场数与数据截止日。直接读本地 CSV，不走 clubdata.load（那会联网补齐）。"""
    files, n, last = _csvs(code), 0, None
    for f in files:
        try:
            d = pd.read_csv(f, encoding="utf-8-sig", encoding_errors="replace",
                            usecols=lambda c: c in ("Date", "HomeTeam"))
        except (ValueError, OSError):
            continue
        d = d.dropna(subset=["Date"]) if "Date" in d.columns else d
        n += len(d)
        if "Date" in d.columns and len(d):
            try:
                mx = pd.to_datetime(d["Date"], dayfirst=True, format="mixed").max()
                last = mx if last is None or mx > last else last
            except (ValueError, TypeError):
                pass
    return {"matches": int(n), "seasons": len(files),
            "data_through": str(last.date()) if last is not None else None}


def _model_cache_state(code: str) -> str:
    """模型缓存是否新于其输入 CSV。只比 mtime，不加载 pkl、更不重训。"""
    pkl = os.path.join(CLUB, f"model_{code}.pkl")
    if not os.path.exists(pkl):
        return "absent"
    newest = max((os.path.getmtime(f) for f in _csvs(code)), default=0.0)
    return "fresh" if os.path.getmtime(pkl) >= newest else "stale"


def _euro_facts() -> dict:
    p = os.path.join(DATA, "euro", "euro_matches_raw.csv")
    try:
        d = pd.read_csv(p, encoding="utf-8-sig", encoding_errors="replace")
    except (FileNotFoundError, ValueError, OSError):
        return {"matches": 0, "ties": 0, "seasons": 0, "data_through": None}
    ties = int(d["tie_id"].nunique()) if "tie_id" in d.columns else 0
    seasons = int(d["season"].nunique()) if "season" in d.columns else 0
    through = None
    if "date" in d.columns and len(d):
        try:
            through = str(pd.to_datetime(d["date"]).max().date())
        except (ValueError, TypeError):
            pass
    return {"matches": int(len(d)), "ties": ties, "seasons": seasons, "data_through": through}


def _freshness(ctx: dict) -> dict:
    """分项呈现，绝不合成单一「全站数据新鲜」绿灯——不同源状态本就不同。"""
    src = []
    meta = _json(os.path.join(_DIR, "model_meta.json")) or {}
    src.append({"id": "national", "label": "国家队数据库", "source": "martj42",
                "state": "archived_current",
                "data_through": meta.get("trained_through"),
                "model_trained_through": meta.get("trained_through"),
                "matches": meta.get("n_matches"), "updated_at": meta.get("saved_at")})
    for code in ("E0", "SP1", "I1", "D1", "F1"):
        f = _league_facts(code)
        src.append({"id": f"club_{code}", "label": f"{clubdata.LEAGUES.get(code, code)}历史数据库",
                    "source": "football-data.co.uk", "state": "offseason_current",
                    "data_through": f["data_through"], "model_input_through": f["data_through"],
                    "model_cache_state": _model_cache_state(code), "matches": f["matches"]})
    e = _euro_facts()
    src.append({"id": "euro", "label": "欧战账本", "source": "ESPN", "state": "current",
                "data_through": e["data_through"], "matches": e["matches"]})

    fx_path = os.path.join(CLUB, "fixtures.csv")
    fx = _fixtures_cached()
    ver, blocked, relevant = [], [], False
    for k in eventsmod.EVENTS:
        ev = eventsmod.EVENTS[k]
        if not str(ev["universe"]).startswith("club_"):
            continue
        (ver if clubverify.tz_verified(ev["data"]) else blocked).append(k)
        # 「已发布」必须指**本赛季窗内**有场次：fixtures.csv 休赛期会留上赛季末轮残行，
        # 只看 len(fx) 会把陈旧残留报成赛程已发布（首页第一屏就在说谎）。
        if len(fx):
            a, b = (pd.Timestamp(x) for x in ev["window"])
            if len(fx[(fx["div"] == ev["data"]) & (fx["date"] >= a) & (fx["date"] <= b)]):
                relevant = True
    return {"sources": src,
            "schedule": {"state": "published" if relevant else "awaiting_schedule",
                         "source": "football-data fixtures",
                         "cached_at": (dt.datetime.fromtimestamp(os.path.getmtime(fx_path), tz=BJ)
                                       .strftime("%Y-%m-%d %H:%M") if os.path.exists(fx_path) else None),
                         "timezone_verification": {"verified_events": ver, "blocked_events": blocked}}}


# ---------- 赛程（只读缓存，绝不刷新/起线程） ----------
def _fixtures_cached() -> pd.DataFrame:
    path = os.path.join(CLUB, "fixtures.csv")
    cols = ["div", "date", "home_team", "away_team"]
    if not os.path.exists(path):
        return pd.DataFrame(columns=cols)
    try:
        raw = pd.read_csv(path, encoding="utf-8-sig", encoding_errors="replace")
        raw = raw.dropna(subset=["Div", "HomeTeam", "AwayTeam"])
        t = raw["Time"].fillna("00:00") if "Time" in raw.columns else "00:00"
        return pd.DataFrame({"div": raw["Div"],
                             "date": pd.to_datetime(raw["Date"] + " " + t, dayfirst=True,
                                                    format="mixed"),
                             "home_team": raw["HomeTeam"].str.strip(),
                             "away_team": raw["AwayTeam"].str.strip()}).sort_values("date")
    except (ValueError, OSError, KeyError):
        return pd.DataFrame(columns=cols)


def _ledger(key: str) -> dict:
    try:
        return verify.load_ledger(clubverify.ledger_path(key))
    except (KeyError, ValueError, OSError):
        return {}


def _match_stream(now: dt.datetime) -> dict:
    """未来 14 天跨赛事比赛流；概率只取**已冻结账本**，未冻结显式标注，不借现算值填空。"""
    fx = _fixtures_cached()
    rows = []
    lo, hi = pd.Timestamp(now.date()), pd.Timestamp(now.date()) + pd.Timedelta(days=HORIZON_DAYS)
    for k in eventsmod.EVENTS:
        ev = eventsmod.EVENTS[k]
        if not str(ev["universe"]).startswith("club_") or not len(fx):
            continue
        a, b = (pd.Timestamp(x) for x in ev["window"])
        sub = fx[(fx["div"] == ev["data"]) & (fx["date"] >= max(lo, a))
                 & (fx["date"] <= min(hi, b + pd.Timedelta(days=1)))]
        led = _ledger(k)
        for r in sub.itertuples():
            ko_utc, ko_bj = clubverify._kickoff(r.date)
            e = led.get(f"{r.home_team}|{r.away_team}")
            if e and e.get("p_home") is not None:
                pred = {"status": "ok", "p_home": e["p_home"], "p_draw": e["p_draw"],
                        "p_away": e["p_away"], "data_through": e.get("data_through"),
                        "frozen_at": e.get("frozen_at")}
            else:
                pred = {"status": "pending_freeze", "reason_code":
                        ("kickoff_tz_unverified" if not clubverify.tz_verified(ev["data"])
                         else "not_frozen_yet")}
            rows.append({"event": k, "event_name": ev["name"], "kickoff_utc": ko_utc,
                         "kickoff_bj": ko_bj, "home": r.home_team, "away": r.away_team,
                         "home_disp": teams_zh.disp(r.home_team),
                         "away_disp": teams_zh.disp(r.away_team),
                         "prediction": pred, "href": f"#{k}/matchup"})
    rows.sort(key=lambda x: x["kickoff_utc"])
    if rows:
        return {"status": "ok", "horizon_days": HORIZON_DAYS, "timezone": "Asia/Shanghai",
                "rows": rows}
    # 无赛程不是「暂无数据」空卡，而是同等正式的第二形态：赛季启动时间轴
    runway = []
    today = now.date()
    for k in eventsmod.sorted_events(today):
        ev, st = eventsmod.EVENTS[k], eventsmod.status(k, today)
        start = dt.date.fromisoformat(ev["window"][0])
        runway.append({"event": k, "name": ev["name"], "start_date": ev["window"][0],
                       "days_to_start": (start - today).days, "status": st,
                       "state": ("archived" if st == "archived" else
                                 ("live" if st == "live" else "schedule_unpublished")),
                       "href": f"#{k}/board"})
    return {"status": "no_fixtures", "horizon_days": HORIZON_DAYS, "timezone": "Asia/Shanghai",
            "rows": [], "fallback": {"kind": "season_runway", "events": runway}}


# ---------- 赛事卡片 ----------
def _highlight(key: str, ev: dict, st: str, now: dt.datetime, n_upcoming: int) -> dict:
    """卡面代表信息。优先级里最容易出错的一条：赛季/mode 不匹配的 seasonsim 绝不当新季夺冠概率。"""
    today = now.date()
    if str(ev["universe"]).startswith("club_"):
        d = _json(os.path.join(CLUB, f"seasonsim_{ev['data']}.json")) or {}
        if d.get("season") == _season_label(ev) and d.get("mode") in ("preseason", "live"):
            rows = (d.get("final") or {}).get("rows") or []
            if rows:
                top = max(rows, key=lambda r: r.get("title", 0))
                return {"kind": "title_favorite", "team": top["team"],
                        "team_disp": teams_zh.disp(top["team"]),
                        "probability": top.get("title"), "season": d["season"],
                        "mode": d["mode"], "as_of": d.get("data_through")}
    if n_upcoming:
        return {"kind": "upcoming", "label": f"未来 {HORIZON_DAYS} 天", "value": n_upcoming,
                "unit": "场", "as_of": str(today)}
    if st in ("soon", "upcoming"):
        start = dt.date.fromisoformat(ev["window"][0])
        return {"kind": "countdown", "label": "距离开赛", "value": (start - today).days,
                "unit": "天", "as_of": str(today)}
    if st == "archived":
        n = len(_ledger(key))
        return {"kind": "archived", "label": "冻结账本", "value": n, "unit": "条",
                "as_of": ev["window"][1]}
    return {"kind": "coverage", "label": "模型覆盖", "value": None, "unit": None,
            "as_of": str(today)}


def _event_groups(now: dt.datetime, stream: dict) -> list:
    today = now.date()
    per_event_upcoming: dict[str, int] = {}
    for r in stream.get("rows", []):
        per_event_upcoming[r["event"]] = per_event_upcoming.get(r["event"], 0) + 1
    fx = _fixtures_cached()
    groups = {"national": [], "club": []}
    for k in eventsmod.sorted_events(today):
        ev = eventsmod.EVENTS[k]
        is_club = str(ev["universe"]).startswith("club_")
        st = eventsmod.status(k, today)
        start = dt.date.fromisoformat(ev["window"][0])
        led = _ledger(k)
        readiness = {"ledger": ("empty" if not led else
                                f"frozen_{len(led)}")}
        if is_club:
            a, b = (pd.Timestamp(x) for x in ev["window"])
            has_fx = bool(len(fx) and len(fx[(fx["div"] == ev["data"]) & (fx["date"] >= a)
                                             & (fx["date"] <= b)]))
            readiness["fixtures"] = "published" if has_fx else "unpublished"
            readiness["kickoff_timezone"] = ("verified" if clubverify.tz_verified(ev["data"])
                                             else "blocked")
            data_through = _league_facts(ev["data"])["data_through"]
        else:
            readiness["fixtures"] = "n/a" if st == "archived" else "unpublished"
            readiness["kickoff_timezone"] = "n/a"
            data_through = (_json(os.path.join(_DIR, "model_meta.json")) or {}).get("trained_through")
        groups["club" if is_club else "national"].append({
            "event": k, "name": ev["name"], "kind": ev["kind"],
            "universe_group": "club" if is_club else "national", "status": st,
            "days_to_start": (start - today).days, "start_date": ev["window"][0],
            "end_date": ev["window"][1], "data_through": data_through,
            "highlight": _highlight(k, ev, st, now, per_event_upcoming.get(k, 0)),
            "readiness": readiness, "href": f"#{k}/board"})
    return [{"id": "national", "label": "国家队赛事", "events": groups["national"]},
            {"id": "club", "label": "俱乐部赛事", "events": groups["club"]}]


# ---------- 验证账本（逐赛事，绝不汇总） ----------
def _club_ledger_summary(key: str) -> dict:
    led = _ledger(key)
    settled = [e for e in led.values() if e.get("settlement_status") == "settled"]
    hits = sum(1 for e in settled if e.get("outcome_hit"))
    return {"ledger_status": ("empty" if not led else ("settled" if settled else "frozen")),
            "frozen": len(led), "evaluated": len(settled), "outcome_hits": hits,
            "pending_settlement": len(led) - len(settled)}


def _verification(ctx: dict) -> dict:
    """**逐赛事并列**。响应里绝不出现 total/summary/overall——跨赛事混池是 registry 层不变量的反面。"""
    out = []
    for k in eventsmod.sorted_events():
        ev = eventsmod.EVENTS[k]
        row = {"event": k, "name": ev["name"], "href": f"#{k}/verify"}
        if k == eventsmod.DEFAULT and ctx.get("wc_summary"):
            s = ctx["wc_summary"]
            row.update(ledger_status="archived", evaluated=s.get("evaluated"),
                       outcome_hits=s.get("outcome_hits"), score_hits=s.get("score_hits"),
                       avg_rps=s.get("avg_rps"), retro_n=s.get("retro_n"),
                       pending_frozen=s.get("pending_frozen"))
        elif str(ev["universe"]).startswith("club_"):
            row.update(_club_ledger_summary(k))
            if row["ledger_status"] == "empty":
                row["reason"] = ("赛程未发布" if not clubverify.tz_verified(ev["data"])
                                 else "冻结未启用")
        else:
            row.update(ledger_status="empty", reason="赛事未开始")
        out.append(row)
    return {"events": out}


# ---------- 覆盖事实 ----------
def _coverage(ctx: dict) -> list:
    out = []
    meta = _json(os.path.join(_DIR, "model_meta.json")) or {}
    if ctx.get("national_teams"):
        out.append({"id": "national_teams", "label": "国家队模型", "value": ctx["national_teams"],
                    "unit": "支球队", "source": "model.pkl", "as_of": meta.get("trained_through")})
    if meta.get("n_matches"):
        out.append({"id": "national_matches", "label": "国际赛训练样本", "value": meta["n_matches"],
                    "unit": "场", "source": "martj42 results.csv",
                    "as_of": meta.get("trained_through")})
    for code in ("E0", "SP1", "I1", "D1", "F1"):
        f = _league_facts(code)
        out.append({"id": f"club_{code}", "label": clubdata.LEAGUES.get(code, code),
                    "value": f["matches"], "unit": f"场 / 近 {f['seasons']} 季",
                    "source": "football-data.co.uk", "as_of": f["data_through"]})
    e = _euro_facts()
    if e["matches"]:
        out.append({"id": "euro_matches", "label": "欧战历史账本", "value": e["matches"],
                    "unit": f"场 / {e['ties']} 对两回合 / {e['seasons']} 季",
                    "source": "data/euro/euro_matches_raw.csv", "as_of": e["data_through"]})
    out.append({"id": "events", "label": "已注册赛事", "value": len(eventsmod.EVENTS),
                "unit": "项", "source": "events.py", "as_of": str(dt.date.today())})
    return out


# ---------- 组装 ----------
def build(ctx: dict | None = None) -> dict:
    ctx = ctx or {}
    now = _now_bj()
    today = now.date()
    nxt = None
    for k in eventsmod.sorted_events(today):
        if eventsmod.status(k, today) in ("live", "soon", "upcoming"):
            ev = eventsmod.EVENTS[k]
            start = dt.date.fromisoformat(ev["window"][0])
            nxt = {"event": k, "name": ev["name"], "start_date": ev["window"][0],
                   "days_to_start": (start - today).days,
                   "live": eventsmod.status(k, today) == "live"}
            break
    stream = _match_stream(now)
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "hero": {"title": "足球赛事预测器",
                 "subtitle": "国家队与五大联赛 · 历史比分模型研究与赛事数据看板",
                 "next_event": nxt},
        "freshness": _freshness(ctx),
        "match_stream": stream,
        "event_groups": _event_groups(now, stream),
        "verification": _verification(ctx),
        "coverage": _coverage(ctx),
        "warnings": [],
    }


def get(ctx: dict | None = None, fresh: bool = False) -> dict:
    """TTL 60s + 指纹失效 + single-flight；重建失败且有旧快照 → 返回旧快照并标 stale。"""
    import time
    now = time.time()
    with _LOCK:
        snap, fp = _CACHE.get("snap"), _fingerprint()
        age = now - _CACHE.get("at", 0)
        if snap and not fresh and age < TTL_SECONDS and _CACHE.get("fp") == fp:
            out = dict(snap)
            out["cache"] = {"ttl_seconds": TTL_SECONDS, "age_seconds": int(age), "hit": True,
                            "stale": False, "fingerprint": fp}
            return out
        try:
            built = build(ctx)
        except Exception as e:  # noqa  重建失败不 500：有旧快照就降级返回，首页永远打得开
            if not snap:
                raise
            out = dict(snap)
            out["cache"] = {"ttl_seconds": TTL_SECONDS, "age_seconds": int(age), "hit": True,
                            "stale": True, "fingerprint": _CACHE.get("fp")}
            out["warnings"] = list(out.get("warnings", [])) + [f"home snapshot rebuild failed: {e}"]
            return out
        _CACHE.update(snap=built, at=now, fp=fp)
        out = dict(built)
        out["cache"] = {"ttl_seconds": TTL_SECONDS, "age_seconds": 0, "hit": False,
                        "stale": False, "fingerprint": fp}
        return out
