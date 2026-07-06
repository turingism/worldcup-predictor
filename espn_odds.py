#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
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
HC_LINES_PATH = os.path.join(os.path.dirname(__file__), "data", "handicap_lines.json")
HC_SNAP_PATH = os.path.join(os.path.dirname(__file__), "data", "handicap_snapshots.jsonl")
_CTX = ssl.create_default_context()

# 显式绕过系统代理的 opener。macOS 系统代理节点偶发 503「Tunnel connection failed」，
# 实测 ESPN 直连可达，故失败后回退直连（照抄 live._fetch_json 的已验证模式，2026-06-19 修）。
_NOPROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _urlopen_raw(req, timeout, opener=None):
    """实际网络调用的单一出口（供测试 monkeypatch）。opener=None 走默认（系统代理）。"""
    if opener is not None:
        return opener.open(req, timeout=timeout)
    return urllib.request.urlopen(req, timeout=timeout, context=_CTX)


def _get(url: str, timeout: int = 20) -> dict:
    """拉 ESPN JSON：先按默认（系统代理）再绕过代理，每种各重试 2 次。
    系统代理偶发 503 时自动重试 + 回退直连，避免一次抖动就整体失败（同 live._fetch_json）。"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    last = None
    for opener in (None, _NOPROXY_OPENER):              # None=默认(系统代理)；再试直连
        for _ in range(2):
            try:
                with _urlopen_raw(req, timeout, opener) as r:
                    return json.loads(r.read().decode("utf-8"))
            except Exception as e:  # noqa  代理 503/超时/瞬断 → 重试或换直连
                last = e
    raise last


def am2dec(ml) -> float:
    """American moneyline → decimal odds. +150→2.5, -200→1.5."""
    ml = float(ml)
    return round(1 + ml / 100, 4) if ml > 0 else round(1 + 100 / abs(ml), 4)


def _handicap_from_summary(ev: dict) -> dict | None:
    """ESPN summary pickcenter → 让球盘行（DraftKings 亚盘/spread）。
    ESPN 的 `spread` 是**主队口径**（-1.5 = 主队让 1.5），`homeTeamOdds.favorite` 标识主队是否强队，
    `spreadOdds` 是该盘水位。已完赛 summary 也保留闭盘 spread（同 1X2 回补逻辑）。
    返回站强队口径的 {fav_line, fav_is_home, ...}；无 spread 返回 None。"""
    home, away = _event_teams(ev)
    if not home or not away:
        return None
    eid = ev.get("id")
    try:
        s = _get(SUM_URL.format(eid=eid))
    except Exception:  # noqa
        return None
    pcs = s.get("pickcenter") or []
    pc = next((p for p in pcs if (p.get("provider") or {}).get("name") == "DraftKings"),
              pcs[0] if pcs else None)
    if not pc or pc.get("spread") is None:
        return None
    ho, ao = pc.get("homeTeamOdds") or {}, pc.get("awayTeamOdds") or {}
    try:
        utc = dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ")
    except (KeyError, ValueError):
        return None
    spread_home = float(pc["spread"])
    fav_is_home = bool(ho.get("favorite"))
    _od = lambda v: am2dec(v) if v not in (None, "") else None  # noqa: E731
    return {"date": str(utc.date()), "home": home, "away": away,
            "kickoff_utc": utc.strftime("%Y-%m-%d %H:%M"),
            "spread_home": spread_home,            # 主队口径原值（负=主队让）
            "fav_line": abs(spread_home),          # 站强队角度：强队让出的球数
            "fav_is_home": fav_is_home,
            "ou": pc.get("overUnder"),
            "fav_spread_odds": _od(ho.get("spreadOdds") if fav_is_home else ao.get("spreadOdds")),
            "dog_spread_odds": _od(ao.get("spreadOdds") if fav_is_home else ho.get("spreadOdds")),
            "provider": (pc.get("provider") or {}).get("name", "DraftKings")}


def fetch_handicap_current(start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    """拉本届所有可取到 spread 的场次让球盘（含未开赛实时 + 已完赛闭盘）。免费、免翻墙（ESPN）。
    注意：每场要一次 summary 调用，整窗口较慢——调用方应限定窗口或改用 fetch_handicap_pair。"""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    out = []
    for ev in sb.get("events", []):
        r = _handicap_from_summary(ev)
        if r:
            out.append(r)
    return out


def _hc_key(home: str, away: str) -> str:
    """让球线存储键：顺序无关（淘汰赛口径），与 verify._kkey 同思路。"""
    return "|".join(sorted((home, away)))


def load_handicap_lines() -> dict:
    """读 data/handicap_lines.json：{key: 让球闭盘线行}。文件缺失/损坏返回空。"""
    try:
        with open(HC_LINES_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def backfill_handicap_finished(limit: int = 24, start: dt.date | None = None,
                               end: dt.date | None = None) -> int:
    """增量回补【已完赛】场次的市场闭盘让球线（ESPN summary 保留闭盘 spread）。
    每次最多抓 `limit` 场（每场一次 summary，控时不阻塞），跳过已存场次；多次后台运行即补全。
    存到 data/handicap_lines.json（顺序无关 key）。返回本次新增条数。"""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    store = load_handicap_lines()
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    added = 0
    for ev in sb.get("events", []):
        if added >= limit:
            break
        if _event_state(ev) != "post":               # 只回补已完赛
            continue
        home, away = _event_teams(ev)
        if not home or not away:
            continue
        key = _hc_key(home, away)
        if key in store:                              # 已有 → 跳过，不再调 summary
            continue
        r = _handicap_from_summary(ev)
        if r:
            store[key] = {**r, "retro": True}
            added += 1
    if added:
        os.makedirs(os.path.dirname(HC_LINES_PATH), exist_ok=True)
        tmp = HC_LINES_PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=0)
        os.replace(tmp, HC_LINES_PATH)               # 原子写
    return added


def snapshot_handicap(now_iso: str | None = None, start: dt.date | None = None,
                      end: dt.date | None = None) -> int:
    """快照【尚未完赛】场次的当前市场让球盘（spread），追加到 handicap_snapshots.jsonl（带时间戳）。
    多次快照 → 每场积累 开盘(首见)→闭盘(临场最后一档) 时间线，供让球 CLV。每场一次 summary，故只扫
    未完赛事件、限定窗口。返回本次快照条数。"""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    stamp = now_iso or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = []
    for ev in sb.get("events", []):
        if _event_state(ev) == "post":          # 已完赛由 backfill 取闭盘，不进开盘时间线
            continue
        r = _handicap_from_summary(ev)
        if r:
            rows.append({**r, "captured_at": stamp})
    if rows:
        os.makedirs(os.path.dirname(HC_SNAP_PATH), exist_ok=True)
        with open(HC_SNAP_PATH, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def load_handicap_timeline() -> dict:
    """聚合让球盘开盘/闭盘：{key: {fav_is_home, open_line, open_at, close_line, close_at}}。
    开盘=快照里最早一条、闭盘=最晚一条（未完赛取最后快照≈临场；已完赛优先用 backfill 的留存闭盘线）。
    无快照文件则仅由 handicap_lines.json（回补闭盘）给 close_line。"""
    snaps = {}
    try:
        with open(HC_SNAP_PATH, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                s = json.loads(ln)
                k = _hc_key(s["home"], s["away"])
                snaps.setdefault(k, []).append(s)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    out = {}
    for k, lst in snaps.items():
        lst.sort(key=lambda s: s.get("captured_at", ""))
        op, cl = lst[0], lst[-1]
        out[k] = {"fav_is_home": op.get("fav_is_home"),
                  "open_line": op.get("fav_line"), "open_at": op.get("captured_at"),
                  "close_line": cl.get("fav_line"), "close_at": cl.get("captured_at")}
    # 已完赛的留存闭盘线（backfill）覆盖/补充 close_line（更接近真实闭盘）
    for k, r in load_handicap_lines().items():
        e = out.setdefault(k, {"fav_is_home": r.get("fav_is_home"),
                               "open_line": None, "open_at": None})
        e["close_line"] = r.get("fav_line")
        e["fav_is_home"] = r.get("fav_is_home")
    return out


def fetch_handicap_pair(home: str, away: str, start: dt.date | None = None,
                        end: dt.date | None = None) -> dict | None:
    """只抓【单场】让球盘（1 次 scoreboard 定位 event + 1 次 summary 取 spread，≈3s）。
    home/away 为 martj42-canon 名，顺序无关匹配。找不到该对阵/无 spread 返回 None。"""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    want = frozenset((home, away))
    for ev in sb.get("events", []):
        h, a = _event_teams(ev)
        if frozenset((h, a)) == want:
            return _handicap_from_summary(ev)
    return None


def _event_teams(ev: dict) -> tuple[str, str]:
    """Home/away (martj42-canon) from the scoreboard event's competitors. Robust for finished
    matches, whose retained pickcenter drops the team objects (only the summary moneylines remain)."""
    comp = (ev.get("competitions") or [{}])[0]
    home = away = ""
    for c in comp.get("competitors", []):
        nm = live._canon_name(((c.get("team") or {}).get("displayName")) or "")
        if c.get("homeAway") == "home":
            home = nm
        elif c.get("homeAway") == "away":
            away = nm
    return home, away


def _row_from_event(ev: dict) -> dict | None:
    """Fetch an event's summary pickcenter (DraftKings 1X2) → odds row, or None if unavailable.
    Works for finished matches too: ESPN's `summary` endpoint **retains** the last pre-match
    DraftKings line (effectively the closing line) even after the scoreboard drops live odds.
    Team names come from the event competitors (the retained pickcenter has no team objects)."""
    home, away = _event_teams(ev)
    if not home or not away:
        return None
    eid = ev.get("id")
    try:
        s = _get(SUM_URL.format(eid=eid))
    except Exception:  # noqa
        return None
    pcs = s.get("pickcenter") or []
    pc = next((p for p in pcs if (p.get("provider") or {}).get("name") == "DraftKings"), pcs[0] if pcs else None)
    if not pc:
        return None
    ho, ao, do = pc.get("homeTeamOdds") or {}, pc.get("awayTeamOdds") or {}, pc.get("drawOdds") or {}
    h_ml, a_ml, d_ml = ho.get("moneyLine"), ao.get("moneyLine"), do.get("moneyLine")
    if None in (h_ml, a_ml, d_ml):
        return None
    try:
        utc = dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ")
    except (KeyError, ValueError):
        return None
    return {"date": str(utc.date()), "home": home, "away": away,
            "kickoff_utc": utc.strftime("%Y-%m-%d %H:%M"),
            "o1": am2dec(h_ml), "ox": am2dec(d_ml), "o2": am2dec(a_ml)}


def _event_state(ev: dict) -> str:
    return ((ev.get("status") or {}).get("type") or {}).get("state", "")


def fetch_current(start: dt.date | None = None, end: dt.date | None = None) -> list[dict]:
    """Pull current DraftKings 1X2 (decimal) for World Cup matches that carry live odds.
    Returns rows: {date, home, away(=martj42 names), kickoff_utc, o1, ox, o2}.
    Only events that still expose odds on the scoreboard (i.e. not yet finished) are captured,
    so repeat snapshots build a genuine opening→closing timeline. Finished matches are handled
    separately by backfill_finished()."""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    out = []
    for ev in sb.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if not any(o for o in (comp.get("odds") or [])):
            continue
        row = _row_from_event(ev)
        if row:
            out.append(row)
    return out


def fetch_finished(start: dt.date | None = None, end: dt.date | None = None,
                   skip: set | None = None) -> list[dict]:
    """Pull the retained DraftKings line for **already-finished** matches (closing line, one-shot).
    ESPN drops live odds from the scoreboard once a match starts, but `summary.pickcenter` keeps
    the last pre-match DraftKings 1X2 — we treat that as the closing line. Used to backfill the
    early matchdays we never snapshotted live (no opening line → no CLV, but valid for model-vs-line).
    `skip` = set of (home, away, date) already captured → filtered **before** the summary call so we
    don't re-hit ESPN for matches we already have (cost stays bounded as more matches finish)."""
    start = start or live.TOURN_START
    end = end or live.TOURN_END
    skip = skip or set()
    sb = _get(SB_URL.format(d1=start.strftime("%Y%m%d"), d2=end.strftime("%Y%m%d")))
    out = []
    for ev in sb.get("events", []):
        if _event_state(ev) != "post":          # 只回补已完赛
            continue
        home, away = _event_teams(ev)            # 队名/日期来自 event（免 summary 调用）
        try:
            date = str(dt.datetime.strptime(ev["date"], "%Y-%m-%dT%H:%MZ").date())
        except (KeyError, ValueError):
            continue
        if not home or not away or (home, away, date) in skip:
            continue                             # 已有该场 → 跳过，不再调 summary
        row = _row_from_event(ev)
        if row:
            out.append({**row, "retro": True})   # 标记：赛后单次回补，非赛前快照
    return out


def _append_snapshots(rows: list[dict], now_iso: str | None = None) -> int:
    if not rows:
        return 0
    stamp = now_iso or dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    os.makedirs(os.path.dirname(SNAP_PATH), exist_ok=True)
    with open(SNAP_PATH, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({**r, "captured_at": stamp}, ensure_ascii=False) + "\n")
    return len(rows)


def snapshot(now_iso: str | None = None) -> int:
    """Fetch current odds and append a timestamped snapshot to odds_snapshots.jsonl. Returns rows captured."""
    return _append_snapshots(fetch_current(), now_iso)


def backfill_finished(start: dt.date | None = None, end: dt.date | None = None) -> int:
    """One-shot: capture the retained closing line for finished matches we never snapshotted live
    (e.g. opening matchdays). Skips matches that already have ANY snapshot (won't clobber a real
    opening→closing timeline). Returns rows newly appended. Idempotent."""
    have = {(s["home"], s["away"], s["date"]) for s in _load_snapshots()}
    return _append_snapshots(fetch_finished(start, end, skip=have))


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
    rows, n_open_close, n_retro = [], 0, 0
    for (home, away, date), lst in by_match.items():
        lst.sort(key=lambda x: x["captured_at"])
        # live = 赛前/赛中实时快照（fetch_current，ESPN 开赛即撤盘口，故最后一条≈闭盘）；
        # retro = 赛后单次回补（fetch_finished，summary 留存线）。用显式标记区分，不靠时区比较。
        live_snaps = [x for x in lst if not x.get("retro")]
        row = {"date": date, "home_team": home, "away_team": away}
        if live_snaps:
            opening, closing = live_snaps[0], live_snaps[-1]   # 首见=开盘，末见=闭盘
            row.update({"odds_1": closing["o1"], "odds_x": closing["ox"], "odds_2": closing["o2"],
                        "odds_1_open": opening["o1"], "odds_x_open": opening["ox"], "odds_2_open": opening["o2"]})
            if opening["captured_at"] != closing["captured_at"]:
                n_open_close += 1
        else:
            # 只有赛后回补：把留存线当闭盘，无开盘 → 开盘列留空（不参与 CLV，仅供模型 vs 闭盘线对标）
            closing = lst[0]
            row.update({"odds_1": closing["o1"], "odds_x": closing["ox"], "odds_2": closing["o2"],
                        "odds_1_open": "", "odds_x_open": "", "odds_2_open": ""})
            n_retro += 1
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
    return {"matches": len(rows), "with_open_close": n_open_close,
            "retro_closing_only": n_retro, "snapshots": len(snaps)}


def main():
    import sys
    if "--no-backfill" not in sys.argv:    # 默认回补已完赛闭盘线（赛前没快照过的比赛日，跳已有→很省）
        nb = backfill_finished()
        print(f"[espn_odds] backfill 回补 {nb} 场已完赛闭盘线（赛后留存线，无开盘→不计 CLV）")
    n = snapshot()
    print(f"[espn_odds] snapshot 抓到 {n} 场当前盘口")
    try:
        nh = snapshot_handicap()
        nhb = backfill_handicap_finished(limit=200)
        print(f"[espn_odds] 让球盘：开盘快照 {nh} 场 + 回补已完赛闭盘线 {nhb} 场")
    except Exception as e:  # noqa  让球盘抓取失败不影响 1X2 主流程
        print(f"[espn_odds] 让球盘快照失败：{e}")
    s = build_odds_csv()
    print(f"[espn_odds] odds.csv 已重建：{s['matches']} 场（其中 {s['with_open_close']} 场有开盘≠闭盘"
          f"，{s['retro_closing_only']} 场仅闭盘回补）· 累计快照 {s['snapshots']} 条")
    print("  CLV 需要『开盘+闭盘』有时间跨度且对应场次已完赛——随赛事多次快照才会累积。")
    print("  解锁价值/Kelly 仍需 CLV 显著为正（≥30 场且 t>1.65）；模型没打赢闭盘线就保持锁定。")


if __name__ == "__main__":
    main()
