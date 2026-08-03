"""联赛未来赛程（ESPN 主源）——补 football-data fixtures.csv 的结构性缺口。

**为什么要第二个源**（2026-08-03 实测事实，勿凭印象改）：
football-data 的 fixtures.csv 只在**盘口开出后**才登记未来数天的场次。2026-08-03
实测该文件仅含苏格兰四级联赛 31/07–03/08 共 21 行，五大联赛 0 行，而 26-27 赛季
首轮为英超 08-21、西甲 08-15、意甲 08-22、德甲 08-28、法甲 08-21——即「未来 14 天
赛程预测」卡片在开赛前会长期空白，且开赛后也只能看到未来一轮。ESPN scoreboard
的赛程在赛季前数月即完整发布，故本模块以 ESPN 为**赛程主源**，football-data 只保留
它独有的 B365 赛前盘（见 `attach_b365`）。

口径与纪律：
- **时区**：ESPN `date` 原生 UTC ISO（`...Z`）→ 转北京时间后落 tz-naive Timestamp，
  与看板其余时间同口径。这也绕开了 fixtures.csv「英国本地时间、夏令时差 1 小时」
  那颗雷（P0-A 时区闸的成因）。
- **队名**：ESPN displayName → football-data 拼写，复用 `eurodata.ESPN_FIX`
  并叠加联赛专属补丁 `LEAGUE_FIX`（欧战账本不含的升降级队）。映射在**装载层**做，
  原始 ESPN 名落盘——缓存不因映射表演进而失效（eurodata 既有纪律）。
- **只收未完场**（state != 'post'）：本模块只服务赛程/赛前预测，赛果口径仍走
  football-data CSV（训练帧唯一来源），两者绝不混。
- **缓存**：`data/club/fixtures_espn_<code>.json`，TTL 12h，stale-while-revalidate
  与 `clubdata.load_fixtures` 同款；`load_cached()` 是**纯只读、不联网、不起线程**的
  装载器，供 home_dashboard 的只读铁律使用。
"""
from __future__ import annotations

import json
import os
import threading
import time

import pandas as pd

import eurodata

CLUB_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "club")
BJ = "Asia/Shanghai"
TTL_H = 12.0
HORIZON_DAYS = 120        # 抓取窗：今天起 120 天（覆盖 14 天窗与「下一轮」回退，约 4 次请求/联赛）
_LOCKS: dict[str, threading.Lock] = {}

# ESPN 联赛码（events 注册表同源事实，此处独立成表以免装载层反向依赖 events）
LEAGUE_SLUG = {"E0": "eng.1", "SP1": "esp.1", "I1": "ita.1",
               "D1": "ger.1", "F1": "fra.1"}

# 联赛专属队名补丁：eurodata.ESPN_FIX 覆盖的是欧战常客，升降级队与中小球会需在此补。
# 值必须是 **football-data 拼写**（clubdata 帧里的 home_team/away_team）。
LEAGUE_FIX = {
    # 英超 26-27（Coventry / Hull 为升班马，只在 E1 帧出现 → 单场模型 no_model）
    "AFC Bournemouth": "Bournemouth", "Ipswich Town": "Ipswich",
    "Leeds United": "Leeds", "Coventry City": "Coventry", "Hull City": "Hull",
    # 西甲 26-27
    "Alavés": "Alaves", "Espanyol": "Espanol", "Málaga": "Malaga",
    "Deportivo La Coruña": "La Coruna", "Racing Santander": "Santander",
    # 德甲 26-27
    "1. FC Union Berlin": "Union Berlin", "FC Augsburg": "Augsburg",
    "FC Cologne": "FC Koln", "Hamburg SV": "Hamburg",
    "SC Paderborn 07": "Paderborn", "SV Elversberg": "Elversberg",
    # 法甲 26-27
    "AJ Auxerre": "Auxerre", "Le Havre AC": "Le Havre",
}
NAME_FIX = {**eurodata.ESPN_FIX, **LEAGUE_FIX}


def canon(espn_name: str) -> str:
    """ESPN displayName → football-data 拼写；无映射原样返回（不虚构、由消费方判 no_model）。"""
    return NAME_FIX.get(espn_name, espn_name)


def cache_path(code: str) -> str:
    return os.path.join(CLUB_DIR, f"fixtures_espn_{code}.json")


def _windows(start: pd.Timestamp, days: int) -> list[tuple[str, str]]:
    """按月切窗（ESPN scoreboard 单次 limit=300，月窗远低于上限，与 eurodata 同款）。"""
    out, a = [], start
    end = start + pd.Timedelta(days=days)
    while a <= end:
        b = min(a + pd.DateOffset(months=1) - pd.Timedelta(days=1), end)
        out.append((a.strftime("%Y%m%d"), b.strftime("%Y%m%d")))
        a = b + pd.Timedelta(days=1)
    return out


def harvest(code: str, days: int = HORIZON_DAYS, today: pd.Timestamp | None = None,
            verbose: bool = False) -> dict:
    """拉 ESPN 未完场赛程并原子写缓存；返回缓存 dict。网络失败向上抛（调用方决定降级）。"""
    import live
    if code not in LEAGUE_SLUG:
        raise KeyError(f"{code} 无 ESPN 赛程源（可选：{sorted(LEAGUE_SLUG)}）")
    t0 = (today or pd.Timestamp.now()).normalize()
    rows, errs = [], []
    for d1, d2 in _windows(t0, days):
        url = live.espn_scoreboard_tmpl(LEAGUE_SLUG[code]).format(d1=d1, d2=d2)
        try:
            payload = live._fetch_json(url)
        except Exception as e:  # noqa  单窗失败记录后继续，不让一次抖动清空整份赛程
            errs.append(f"{d1}-{d2}: {e}")
            continue
        for ev in payload.get("events", []):
            comp = (ev.get("competitions") or [{}])[0]
            st = (comp.get("status") or {}).get("type") or {}
            if st.get("state") == "post":
                continue                      # 已完场：赛果口径归 football-data CSV
            side = {c.get("homeAway"): c for c in comp.get("competitors", [])}
            h, a = side.get("home"), side.get("away")
            if not h or not a:
                continue
            rows.append({"utc": str(ev.get("date")),
                         "home_espn": h["team"]["displayName"],
                         "away_espn": a["team"]["displayName"],
                         "state": st.get("state") or "pre"})
    rows.sort(key=lambda r: (r["utc"], r["home_espn"]))
    obj = {"code": code, "espn": LEAGUE_SLUG[code], "source": "ESPN scoreboard",
           "fetched_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S"),
           "horizon_days": days, "from": t0.strftime("%Y-%m-%d"),
           "errors": errs, "rows": rows}
    if errs and not rows:
        raise RuntimeError(f"{code} 赛程全窗拉取失败：{errs[0]}")   # 全失败不写空缓存
    os.makedirs(CLUB_DIR, exist_ok=True)
    tmp = cache_path(code) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
    os.replace(tmp, cache_path(code))
    if verbose:
        print(f"[clubfixtures] {code}: {len(rows)} 场未完赛 → {cache_path(code)}"
              + (f"（{len(errs)} 窗失败）" if errs else ""))
    return obj


def _frame(obj: dict | None) -> pd.DataFrame:
    """缓存 dict → 装载帧（应用队名映射 + UTC→北京时间）。空缓存返回空帧但列齐。

    ⚠ `date` 是**北京时间**的 naive 时间戳，与 fixtures.csv 的英国本地 naive 时间**不同口径**。
    绝不要把本帧的 date 喂给 `clubverify._kickoff`（它按 Europe/London 解释 naive 值，
    会整整偏 7-8 小时）——需要 UTC/北京开球串时直接用本帧的 `kickoff_utc` / date。"""
    cols = ["date", "home_team", "away_team", "state", "kickoff_utc", "home_espn", "away_espn"]
    rows = (obj or {}).get("rows") or []
    if not rows:
        return pd.DataFrame({c: pd.Series(dtype="datetime64[ns]" if c == "date" else "object")
                             for c in cols})
    df = pd.DataFrame(rows)
    utc = pd.to_datetime(df["utc"], utc=True, format="ISO8601")
    df["kickoff_utc"] = utc.dt.strftime("%Y-%m-%dT%H:%M:%SZ")     # clubverify 同格式
    df["date"] = utc.dt.tz_convert(BJ).dt.tz_localize(None)
    df["home_team"] = df["home_espn"].map(canon)
    df["away_team"] = df["away_espn"].map(canon)
    return df[cols].sort_values("date").reset_index(drop=True)


def load_cached(code: str) -> pd.DataFrame:
    """**纯只读**装载：只读本地缓存，不联网、不起后台线程、不写盘（首页只读铁律用）。

    无缓存/缓存损坏 → 返回空帧（列齐），由消费方走显式空态。"""
    try:
        with open(cache_path(code), encoding="utf-8") as f:
            return _frame(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError, KeyError, ValueError):
        return _frame(None)


def cached_at(code: str) -> str | None:
    try:
        with open(cache_path(code), encoding="utf-8") as f:
            return json.load(f).get("fetched_at")
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def load(code: str, refresh: bool = False) -> pd.DataFrame:
    """赛程帧（stale-while-revalidate）：有缓存先返回旧数据、后台单飞重拉；
    冷启动/显式 refresh 同步拉取。与 clubdata.load_fixtures 同款语义。"""
    path = cache_path(code)
    fresh = os.path.exists(path) and time.time() - os.path.getmtime(path) <= TTL_H * 3600
    if refresh or not os.path.exists(path):
        harvest(code)                                    # 失败向上抛（冷启动无可降级对象）
    elif not fresh:
        lock = _LOCKS.setdefault(code, threading.Lock())
        if lock.acquire(blocking=False):
            def _worker():
                try:
                    harvest(code)
                except Exception as e:  # noqa  后台失败沿用旧缓存，下次超龄再试
                    print(f"[clubfixtures] {code} 后台刷新失败（沿用旧缓存）：{e}")
                finally:
                    lock.release()
            threading.Thread(target=_worker, daemon=True).start()
    return load_cached(code)


def attach_b365(df: pd.DataFrame, fx: pd.DataFrame) -> pd.DataFrame:
    """把 football-data fixtures.csv 的 B365 赛前盘并到赛程帧上（ESPN 无赔率）。

    按（主队, 客队）匹配、**不含日期**——两源开球时间口径不同（英国本地 vs 北京），
    含日期必然失配；同赛季同主客对阵在未来一轮窗口内唯一，够用。fx 为空则原样返回。"""
    for c in ("B365H", "B365D", "B365A"):
        if c not in df.columns:
            df[c] = float("nan")
    if fx is None or not len(fx):
        return df
    ix = {(r.home_team, r.away_team): r for r in fx.itertuples()}
    for i, r in enumerate(df.itertuples()):
        m = ix.get((r.home_team, r.away_team))
        if m is not None:
            df.loc[df.index[i], ["B365H", "B365D", "B365A"]] = [m.B365H, m.B365D, m.B365A]
    return df


if __name__ == "__main__":
    import sys
    for lg in (sys.argv[1:] or list(LEAGUE_SLUG)):
        o = harvest(lg, verbose=True)
        d = load_cached(lg)
        nxt = d.head(3)[["date", "home_team", "away_team"]].to_string(index=False) if len(d) else "(空)"
        print(f"{lg}: 未完赛 {len(d)} 场，最近三场：\n{nxt}\n")
