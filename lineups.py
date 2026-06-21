"""
首发名单层（lineups）：从 ESPN 公开 API 拉真实首发 11 人，对照 availability.json 的
登记关键人做「在场 / 替补 / 缺阵」布尔核对，输出这一场的 per-match xG 乘子。

定位：与 manager / inplay / clv 同级的**只读旁路层**。绝不写训练数据、绝不碰 GLM、
绝不回写 verify 冻结账本。默认不参与任何预测——只有显式调用才生效（主动权在用户）。

核心设计：不需要球员级 xG / 实力数据（那是数据死胡同）。只对 availability.json 里
**已登记的关键人**做一次布尔核对——首发名单只决定那个人的「档位惩罚触不触发」，
不决定它多大（档位仍取自 adjust.py 的人工校准）。这就是它能落地而全量球员实力做不到的原因。

诚实边界：
  - 只追踪已登记关键人；未登记球员意外缺阵探测不到（如实标注 coverage）。
  - 首发约赛前 1 小时公布；未公布时 available=False，调用方降级到赛前估计。
  - 完赛后 ESPN 仍保留首发，可用于「完赛后补算对比」——用的是赛前 1h 的首发事实，
    不含赛果，与 verify 的 retro 回溯同口径，不构成偷看。
"""
from __future__ import annotations
import json
import unicodedata
import urllib.request

import adjust

ESPN_BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world"

# ESPN 队名 → 本项目英文队名（与 live.NAME_FIX 同思路；多数一致，仅个别需映射）。
TEAM_FIX = {
    "Czechia": "Czech Republic",
    "Türkiye": "Turkey", "Turkiye": "Turkey",
    "Congo DR": "DR Congo", "DR Congo": "DR Congo",
    "Bosnia & Herzegovina": "Bosnia and Herzegovina",
    "Côte d'Ivoire": "Ivory Coast", "Cote d'Ivoire": "Ivory Coast",
}

# 替补席的关键人有多大概率最终不影响比赛（不首发但可能替补登场）。
_BENCH_ABSENT_PROB = 0.7


def _norm(name: str) -> str:
    """归一化球员名：去重音、去标点、小写、去空格。用于模糊匹配登记名 vs ESPN 全名。"""
    s = unicodedata.normalize("NFKD", name or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return "".join(c for c in s.lower() if c.isalnum())


def _fetch_json(url: str):
    """复用 live 的「系统代理 → 直连」重试；live 不可用时退回直连。"""
    try:
        import live
        return live._fetch_json(url)
    except Exception:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        return json.load(urllib.request.urlopen(req, timeout=20))


def _espn_to_team(name: str) -> str:
    return TEAM_FIX.get(name, name)


def find_event(home_en: str, away_en: str, dates: str | None = None):
    """在 ESPN scoreboard 里按队名找 event id（顺序无关）。dates=YYYYMMDD 限定日期窗。"""
    url = f"{ESPN_BASE}/scoreboard" + (f"?dates={dates}" if dates else "")
    sb = _fetch_json(url)
    want = {home_en, away_en}
    for e in sb.get("events", []):
        comps = e.get("competitions", [{}])[0].get("competitors", [])
        teams = {_espn_to_team(c.get("team", {}).get("displayName", "")) for c in comps}
        if want <= teams:
            st = e.get("status", {}).get("type", {}).get("state")
            return {"event": e["id"], "state": st, "name": e.get("name")}
    return None


def fetch_lineup(event_id: str) -> dict:
    """拉一场的 rosters，返回 {team_en: {starters:[norm名], names:{norm:显示名}, bench:[norm], formation, confirmed}}。
    confirmed=True 表示首发已公布（starters 非空）。"""
    s = _fetch_json(f"{ESPN_BASE}/summary?event={event_id}")
    out = {}
    for t in (s.get("rosters") or []):
        team_en = _espn_to_team(t.get("team", {}).get("displayName", ""))
        starters, bench, disp = [], [], {}
        for a in t.get("roster", []):
            ath = a.get("athlete", {})
            nm = ath.get("displayName") or ath.get("fullName") or ""
            n = _norm(nm)
            if not n:
                continue
            disp[n] = nm
            (starters if a.get("starter") else bench).append(n)
        out[team_en] = {
            "starters": starters, "bench": bench, "names": disp,
            "formation": t.get("formation"), "confirmed": len(starters) > 0,
        }
    return out


def _classify(reg_name: str, lt: dict) -> tuple[str, float]:
    """一名登记关键人 vs 该队首发/替补 → (lineup_status, P(缺阵))。"""
    key = _norm(reg_name)
    if not lt or not lt.get("confirmed"):
        return "unknown", -1.0                      # 名单未公布 → 保留赛前估计
    def _hit(pool):
        return any(key and (key in cand or cand in key) for cand in pool)
    if _hit(lt["starters"]):
        return "started", 0.0                       # 确认首发 → 惩罚归零
    if _hit(lt["bench"]):
        return "bench", _BENCH_ABSENT_PROB          # 替补席 → 大概率不首发
    return "absent", 1.0                            # 名单里没有 → 确认缺阵（满档）


def detect_team(team_en: str, reg_items: list, lineup_team: dict | None):
    """对一队的 availability 登记 items 做实时核对，返回 (覆盖后的 items, 逐人状态列表)。"""
    new_items, status = [], []
    for it in reg_items or []:
        ls, p = _classify(it.get("player", ""), lineup_team or {})
        item = dict(it)
        if p >= 0:                                  # 名单已确认 → 用实时事实覆盖赛前 prob
            item["prob"] = p
            item["status"] = "out" if p >= 0.999 else "doubtful"
        item["lineup_status"] = ls                  # started / bench / absent / unknown
        new_items.append(item)
        status.append({"player": it.get("player"), "tier": it.get("tier"),
                       "role": it.get("role"), "lineup_status": ls,
                       "reason": it.get("reason", "")})
    return new_items, status


def match_availability(home_en: str, away_en: str, event_id: str | None = None,
                       dates: str | None = None, avail: dict | None = None) -> dict:
    """端到端：找 event → 拉首发 → 对两队登记关键人核对 → 组装 per-match 乘子。

    返回 {available, event, state, teams:{home/away:{confirmed,formation,players[]}},
          mods:{team_en:(att,def_pen)}, coverage}。available=False 时调用方应降级到赛前估计。
    """
    if avail is None:
        avail = adjust.load_availability()
    if event_id is None:
        ev = find_event(home_en, away_en, dates=dates)
        if not ev:
            return {"available": False, "reason": "event_not_found"}
        event_id, state = ev["event"], ev.get("state")
    else:
        state = None
    lineup = fetch_lineup(event_id)

    per_match = {}
    teams_out = {}
    any_confirmed = False
    for side, t in (("home", home_en), ("away", away_en)):
        lt = lineup.get(t)
        confirmed = bool(lt and lt.get("confirmed"))
        any_confirmed = any_confirmed or confirmed
        items, status = detect_team(t, avail.get(t, []), lt)
        if items:
            per_match[t] = items
        teams_out[side] = {
            "team": t, "confirmed": confirmed,
            "formation": (lt or {}).get("formation"),
            "players": status,                       # 登记关键人的逐人首发状态
            "starters_n": len((lt or {}).get("starters", [])),
        }

    mods = adjust.team_modifiers(per_match) if per_match else {}
    mod_pairs = {t: (m["att"], m["def_pen"]) for t, m in mods.items()}
    return {
        "available": any_confirmed,
        "event": event_id, "state": state,
        "teams": teams_out,
        "mods": mod_pairs,                           # {team_en:(att_mult,def_pen_mult)} 传 model.avail_override
        "mods_detail": mods,
        "coverage": {t: len(avail.get(t, [])) for t in (home_en, away_en)},
    }


if __name__ == "__main__":
    import sys
    h, a = (sys.argv[1], sys.argv[2]) if len(sys.argv) >= 3 else ("Germany", "Ivory Coast")
    dates = sys.argv[3] if len(sys.argv) >= 4 else None
    r = match_availability(h, a, dates=dates)
    print(json.dumps(r, ensure_ascii=False, indent=2))
