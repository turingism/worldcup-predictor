# -*- coding: utf-8 -*-
"""玄学占卜「自动赛程 + 命中率擂台」（xuanxue_board.py）

把 7 套术数（见 xuanxue.py）接到真实赛程上，做一个可持续累计的命中率擂台：
  1) 自动抓「近三天即将开赛」的本届场次 → 每场冻结 7 法占卜（赛前留痕）。
  2) 比赛完赛后自动结算：记录真实比分，逐体系判定 胜负命中 / 精确比分命中。
  3) 逐体系累计命中率排行 → 看哪套术数最终猜得最准。

诚实性说明：
  · 占卜引擎 divine() 是【纯确定性、完全不读取赛果】的（种子只来自队名+赛期）。
    因此对【已完赛】场次补算占卜 == 它赛前本就会给出的结果，不构成"事后偷看"。
    故本模块在冻结未来场次之外，也把本届已完赛场次补进账本（立即结算），
    让擂台立刻有样本，而非干等。两条路径同一函数、同一种子，结果一致。
  · 账本 data/xuanxue_ledger.json：赛前冻结、赛后只读（result 一旦写入不改）。
  · 这仍是文化/趣味实验，术数无科学预测力；擂台只是"看它们事后撞中了多少"。

复用 verify.py 的赛程遍历 / 比赛 key / 完赛查询 / 北京时间口径，保证与「预测验证」对齐。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os

import schedule
import teams_zh
import verify
import xuanxue

LEDGER_PATH = os.path.join(os.path.dirname(__file__), "data", "xuanxue_ledger.json")
WINDOW_DAYS = 3

# 球场经度（真太阳时校正用），来自 venues.json 的 geo 段
try:
    _VENUES = json.load(open(os.path.join(os.path.dirname(__file__), "data", "venues.json"),
                             encoding="utf-8"))
    _CITY_LNG = {c: g.get("lng") for c, g in _VENUES.get("geo", {}).items()}
except (FileNotFoundError, ValueError, OSError):
    _CITY_LNG = {}


# ---------- 账本（原子写，结构同 verify）----------
def load_ledger(path: str = LEDGER_PATH) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        preds = d.get("preds", {})
        return preds if isinstance(preds, dict) else {}
    except (FileNotFoundError, ValueError, OSError):
        return {}


def save_ledger(preds: dict, path: str = LEDGER_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                   "preds": preds}, f, ensure_ascii=False)
    os.replace(tmp, path)


def _winner(gh: int, ga: int) -> str:
    return "home" if gh > ga else ("away" if ga > gh else "draw")


def _wilson(hits: int, n: int, z: float = 1.96):
    """95% Wilson 置信区间(%)。零信号系统命中率本质是抽样，小样本必须给区间。"""
    if not n:
        return (None, None)
    p = hits / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (round(max(0.0, c - half) * 100, 1), round(min(1.0, c + half) * 100, 1))


def _baselines(results: list) -> dict:
    """无脑基线：永远押最优单一赛果 / 永远押最常见比分 / 随机。results=[(gh,ga),...]"""
    n = len(results)
    if not n:
        return {}
    wc = {"home": 0, "draw": 0, "away": 0}
    sc: dict = {}
    for gh, ga in results:
        wc[_winner(gh, ga)] += 1
        sc[(gh, ga)] = sc.get((gh, ga), 0) + 1
    bw = max(wc, key=wc.get)
    ms, mc = max(sc.items(), key=lambda kv: kv[1])
    lo, hi = _wilson(wc[bw], n)
    elo, ehi = _wilson(mc, n)
    label = {"home": "永远押主胜", "draw": "永远押平局", "away": "永远押客胜"}[bw]
    return {"const_label": label, "const_pct": round(wc[bw] / n * 100, 1),
            "const_lo": lo, "const_hi": hi,
            "modal_score": f"{ms[0]}–{ms[1]}", "modal_exact_pct": round(mc / n * 100, 1),
            "modal_lo": elo, "modal_hi": ehi, "random_pct": 33.3, "n": n}


# ---------- 冻结：近三天即将开赛的场次，每场存 7 法占卜 ----------
def _upcoming(sim, now: str, horizon: str) -> list[tuple]:
    """窗口 (now, horizon] 内、尚未开球的本届场次 → (key, stage, h, a, kickoff, date)。"""
    out = []
    for ps in sim.fixtures.values():                 # 小组赛
        for (h, a) in ps:
            if (h, a) in sim.actual_results:
                continue
            ko = schedule.GROUP.get((h, a), "")
            if ko and now < ko <= horizon:
                out.append((verify._gkey(h, a), "group", h, a, ko, ko[:10]))
    proj = sim.project(today=now[:10])               # 淘汰赛：仅对阵已抽签确定
    for rd in proj["rounds"]:
        for m in rd["matches"]:
            if not m.get("drawn") or m.get("set"):
                continue
            a, b, mn = m["a"], m["b"], m.get("mn")
            ko = schedule.KO.get(mn, "")
            if ko and now < ko <= horizon:
                out.append((verify._kkey(a, b), rd["name"], a, b, ko, ko[:10]))
    return out


def _cast_args(stage: str, h: str, a: str, mn=None) -> tuple:
    """起卦时间参数：(球场当地钟表时刻, 城市, 经度, 时区偏移)。
    术数按事发地当地算时辰/日干支；有经度则下游做真太阳时校正。缺则回落北京时间。"""
    v = schedule.ko_venue(mn) if (stage != "group" and mn is not None) else schedule.group_venue(h, a)
    if v and v.get("local"):
        city = v.get("city")
        return v["local"], city, _CITY_LNG.get(city), v.get("offset")
    return schedule.GROUP.get((h, a), ""), None, None, None


def freeze_upcoming(sim, window_days: int = WINDOW_DAYS, now_bj: str | None = None) -> int:
    """对近 window_days 天内即将开赛、且账本里还没有的场次冻结 7 法占卜。返回新增条数。"""
    now = now_bj or verify._now_bj()
    horizon = (dt.datetime.strptime(now, "%Y-%m-%d %H:%M")
               + dt.timedelta(days=window_days)).strftime("%Y-%m-%d %H:%M")
    preds = load_ledger()
    n = 0
    for key, stage, h, a, ko, date in _upcoming(sim, now, horizon):
        if key in preds:                              # 已冻结（赛前），确定性不重算
            continue
        local, city, lng, off = _cast_args(stage, h, a)   # 球场当地时间 + 经度（真太阳时）
        r = xuanxue.divine(h, a, local, longitude=lng, utc_offset=off)
        preds[key] = {"stage": stage, "home": h, "away": a, "kickoff": ko, "date": date,
                      "cast_local": local, "cast_city": city,
                      "true_solar": r["pillars"].get("true_solar"),
                      "frozen_at": now, "retro": False,
                      "methods": r["methods"], "result": None}
        n += 1
    if n:
        save_ledger(preds)
    return n


# ---------- 补算：本届已完赛场次（占卜不读赛果，补算=赛前结果，合法）----------
def backfill_finished(sim, df) -> int:
    """把本届已完赛、账本缺失的场次补进账本并立即结算。返回新增条数。"""
    preds = load_ledger()
    n = 0
    for c in verify._completed(sim, df):
        if c["key"] in preds:
            continue
        # 起卦时点：球场当地时间 + 经度（真太阳时），缺则回落比赛日
        local, city, lng, off = _cast_args(c["stage"], c["home"], c["away"])
        local = local or c["date"]
        r = xuanxue.divine(c["home"], c["away"], local, longitude=lng, utc_offset=off)
        preds[c["key"]] = {"stage": c["stage"], "home": c["home"], "away": c["away"],
                           "kickoff": schedule.GROUP.get((c["home"], c["away"]), ""),
                           "cast_local": local, "cast_city": city,
                           "true_solar": r["pillars"].get("true_solar"),
                           "date": c["date"], "frozen_at": verify._now_bj(), "retro": True,
                           "methods": r["methods"],
                           "result": {"gh": int(c["gh"]), "ga": int(c["ga"])}}
        n += 1
    if n:
        save_ledger(preds)
    return n


# ---------- 结算：已完赛但账本里 result 仍为空的，写入真实比分 ----------
def settle(sim, df) -> int:
    preds = load_ledger()
    n = 0
    for c in verify._completed(sim, df):
        e = preds.get(c["key"])
        if not e or e.get("result") is not None:
            continue
        gh, ga = int(c["gh"]), int(c["ga"])
        if (e["home"], e["away"]) != (c["home"], c["away"]):   # 校正到账本主客序
            gh, ga = ga, gh
        e["result"] = {"gh": gh, "ga": ga}
        n += 1
    if n:
        save_ledger(preds)
    return n


# ---------- 统计：逐体系累计命中率排行 ----------
def leaderboard(preds: dict | None = None) -> tuple[list, int]:
    preds = preds if preds is not None else load_ledger()
    agg: dict[str, dict] = {}
    settled = [e for e in preds.values() if e.get("result")]
    for e in settled:
        gh, ga = e["result"]["gh"], e["result"]["ga"]
        wa = _winner(gh, ga)
        for m in e["methods"]:
            a = agg.setdefault(m["key"], {"key": m["key"], "name": m["name"],
                                          "icon": m["icon"], "n": 0,
                                          "outcome_hits": 0, "exact_hits": 0})
            a["n"] += 1
            if m["winner"] == wa:
                a["outcome_hits"] += 1
            if m["score"][0] == gh and m["score"][1] == ga:
                a["exact_hits"] += 1
    board = _finalize(agg)
    return board, len(settled)


def _finalize(agg: dict) -> list:
    """把累计计数整理成带命中率 + 95% Wilson 置信区间的排行，按胜负命中率降序。"""
    board = []
    for a in agg.values():
        nn = a["n"]
        olo, ohi = _wilson(a["outcome_hits"], nn)
        elo, ehi = _wilson(a["exact_hits"], nn)
        board.append({**a,
                      "outcome_pct": round(a["outcome_hits"] / nn * 100, 1) if nn else None,
                      "exact_pct": round(a["exact_hits"] / nn * 100, 1) if nn else None,
                      "outcome_lo": olo, "outcome_hi": ohi, "exact_lo": elo, "exact_hi": ehi})
    board.sort(key=lambda x: (-(x["outcome_pct"] or 0), -(x["exact_pct"] or 0), x["name"]))
    return board


# ---------- 历史回测：全部历史国际赛(1872–今)，高样本量看真实收敛 ----------
_HIST_CACHE: dict = {}


def historical_leaderboard(df) -> dict:
    """对全部已赛国际赛跑 7 法占卜(date-only，无开球时辰/场馆)，逐体系累计命中率 + 基线。
    占卜不读赛果，补算历史合法；样本大→方差小，能看出各体系是否真的收敛到基线/随机。
    按 played 场次数缓存（新赛果才重算，约 1.7s）。"""
    import data as datamod
    played = datamod.played(df)
    played = played[played["home_score"].notna()]
    key = len(played)
    if key in _HIST_CACHE:
        return _HIST_CACHE[key]
    agg: dict = {}
    results = []
    for _, r in played.iterrows():
        gh, ga = int(r["home_score"]), int(r["away_score"])
        results.append((gh, ga))
        wa = _winner(gh, ga)
        rr = xuanxue.divine(r["home_team"], r["away_team"], r["date"].strftime("%Y-%m-%d"))
        for m in rr["methods"]:
            a = agg.setdefault(m["key"], {"key": m["key"], "name": m["name"], "icon": m["icon"],
                                         "n": 0, "outcome_hits": 0, "exact_hits": 0})
            a["n"] += 1
            if m["winner"] == wa:
                a["outcome_hits"] += 1
            if m["score"][0] == gh and m["score"][1] == ga:
                a["exact_hits"] += 1
    out = {"n": len(results), "leaderboard": _finalize(agg), "baselines": _baselines(results)}
    _HIST_CACHE.clear()
    _HIST_CACHE[key] = out
    return out


# ---------- 组装看板 ----------
def build_board(sim, df, window_days: int = WINDOW_DAYS) -> dict:
    """刷新账本（冻结未来 + 补算已完赛 + 结算）后返回擂台数据。"""
    try:
        freeze_upcoming(sim, window_days)
        backfill_finished(sim, df)
        settle(sim, df)
    except Exception as e:  # noqa  写账本失败不阻塞只读展示
        print(f"[xuanxue_board] 账本刷新失败：{e}")
    preds = load_ledger()
    now = verify._now_bj()
    L = teams_zh.disp

    upcoming, settled_rows = [], []
    for e in preds.values():
        base = {"home_disp": L(e["home"]), "away_disp": L(e["away"]),
                "date": verify.bj_date(e.get("kickoff"), e.get("date")),
                "kickoff": e.get("kickoff") or "", "cast_local": e.get("cast_local") or "",
                "cast_city": e.get("cast_city") or "", "true_solar": e.get("true_solar") or "",
                "stage": e["stage"], "methods": e["methods"]}
        if e.get("result") is None:                  # 未结算
            base["started"] = bool(e.get("kickoff") and e["kickoff"] <= now)
            upcoming.append(base)
        else:
            gh, ga = e["result"]["gh"], e["result"]["ga"]
            wa = _winner(gh, ga)
            ms = [{**m, "outcome_hit": m["winner"] == wa,
                   "exact_hit": m["score"][0] == gh and m["score"][1] == ga}
                  for m in e["methods"]]
            settled_rows.append({**base, "methods": ms, "result": {"gh": gh, "ga": ga}})

    upcoming.sort(key=lambda x: x["kickoff"] or "~")          # 未排期排最后
    settled_rows.sort(key=lambda x: x["date"], reverse=True)  # 最近完赛在前
    board, settled_n = leaderboard(preds)
    results = [(e["result"]["gh"], e["result"]["ga"])
               for e in preds.values() if e.get("result")]
    try:
        hist = historical_leaderboard(df)
    except Exception as e:  # noqa  历史回测失败不阻塞本届擂台
        print(f"[xuanxue_board] 历史回测失败：{e}")
        hist = None
    return {"now": now, "window_days": window_days,
            "leaderboard": board,
            "baselines": _baselines(results),
            "historical": hist,
            "upcoming": upcoming,
            "settled": settled_rows[:30],
            "totals": {"settled": settled_n, "upcoming": len(upcoming),
                       "methods": len(xuanxue.METHODS)}}


# ---------- CLI ----------
if __name__ == "__main__":
    import data as datamod
    from predict import get_model
    from simulate import TournamentSimulator
    m = get_model(use_cache=True, half_life=730.0, verbose=False)
    df = datamod.load_raw()
    sim = TournamentSimulator(m, df, sims=1)
    b = build_board(sim, df)
    print(f"已完赛 {b['totals']['settled']} 场 · 近{WINDOW_DAYS}天待测 {b['totals']['upcoming']} 场\n")
    print(f"  {'体系':<12}{'场次':>4}{'胜负命中':>8}{'命中率':>8}{'精确比分':>8}{'精确率':>8}")
    print("  " + "─" * 52)
    for i, r in enumerate(b["leaderboard"]):
        medal = ["🥇", "🥈", "🥉"][i] if i < 3 else "  "
        print(f"  {medal}{r['name']:<10}{r['n']:>4}{r['outcome_hits']:>8}"
              f"{(str(r['outcome_pct'])+'%'):>8}{r['exact_hits']:>8}{(str(r['exact_pct'])+'%'):>8}")
