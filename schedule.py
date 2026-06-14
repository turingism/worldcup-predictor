"""2026 世界杯赛程开球时间（已换算为北京时间 UTC+8）。
来源：维基百科 2026 FIFA World Cup（各场含 UTC 偏移），脚本统一换算。
另含 data/venues.json（每场主办城市 + 城市 UTC 偏移），可把北京时间换算成场馆当地时间。"""
import datetime as _dt
import json as _json
import os as _os

BEIJING_OFFSET = 8   # 北京 = UTC+8

_VENUES = None


def _venues() -> dict:
    """加载场馆映射 {cities:{城市:偏移}, group:{'home|away':城市}, ko:{'73':城市}}。缺失返回空。"""
    global _VENUES
    if _VENUES is None:
        path = _os.path.join(_os.path.dirname(__file__), "data", "venues.json")
        try:
            with open(path, encoding="utf-8") as f:
                _VENUES = _json.load(f)
        except (FileNotFoundError, ValueError, OSError):
            _VENUES = {"cities": {}, "group": {}, "ko": {}}
    return _VENUES


def _to_local(beijing_str: str, offset: int) -> str:
    """北京时间 'YYYY-MM-DD HH:MM' + 场馆 UTC 偏移 → 当地 'YYYY-MM-DD HH:MM'（日期会随之变化）。"""
    if not beijing_str or offset is None:
        return ""
    t = _dt.datetime.strptime(beijing_str, "%Y-%m-%d %H:%M")
    return (t + _dt.timedelta(hours=offset - BEIJING_OFFSET)).strftime("%Y-%m-%d %H:%M")


def group_venue(home: str, away: str) -> dict | None:
    """某场小组赛的场馆信息：{city, offset, local('YYYY-MM-DD HH:MM')}。
    顺序无关（fixtures 主客顺序可能与数据源相反）。无数据返回 None。"""
    v = _venues()
    city = v["group"].get(f"{home}|{away}") or v["group"].get(f"{away}|{home}")
    if not city:
        return None
    off = v["cities"].get(city)
    bj = GROUP.get((home, away)) or GROUP.get((away, home), "")
    return {"city": city, "offset": off, "local": _to_local(bj, off)}


def ko_venue(mn: int) -> dict | None:
    """某场淘汰赛（场次编号）的场馆信息。无数据返回 None。"""
    v = _venues()
    city = v["ko"].get(str(mn))
    if not city:
        return None
    off = v["cities"].get(city)
    return {"city": city, "offset": off, "local": _to_local(KO.get(mn, ""), off)}


# —— 东道主主场优势：16 主办城市 → 东道主国家队名（队名对齐 martj42）——
HOSTS = {"United States", "Mexico", "Canada"}
_CITY_COUNTRY = {
    "Atlanta": "United States", "Boston": "United States", "Dallas": "United States",
    "Houston": "United States", "Kansas City": "United States", "Los Angeles": "United States",
    "Miami": "United States", "New York/New Jersey": "United States",
    "Philadelphia": "United States", "San Francisco Bay Area": "United States",
    "Seattle": "United States",
    "Toronto": "Canada", "Vancouver": "Canada",
    "Mexico City": "Mexico", "Guadalajara": "Mexico", "Monterrey": "Mexico",
}


def host_of_city(city: str) -> str | None:
    """该城市所属东道主国家队名（非主办城市返回 None）。"""
    return _CITY_COUNTRY.get(city)


def group_match_host(home: str, away: str) -> str | None:
    """某场小组赛若由东道主在本国城市出战，返回该东道主队名；否则 None。"""
    v = group_venue(home, away)
    if v:
        hc = host_of_city(v.get("city", ""))
        if hc in (home, away):
            return hc
    return None


def ko_city_country(mn: int) -> str | None:
    """某场次编号所在城市的东道主国家（用于判断淘汰赛中谁占主场）。"""
    v = ko_venue(mn)
    return host_of_city(v.get("city", "")) if v else None

# 小组赛: (home_en, away_en) -> 北京时间 "YYYY-MM-DD HH:MM"
GROUP = {
    ('Mexico', 'South Africa'): '2026-06-12 03:00',
    ('South Korea', 'Czech Republic'): '2026-06-12 10:00',
    ('Czech Republic', 'South Africa'): '2026-06-19 00:00',
    ('Mexico', 'South Korea'): '2026-06-19 09:00',
    ('Czech Republic', 'Mexico'): '2026-06-25 09:00',
    ('South Africa', 'South Korea'): '2026-06-25 09:00',
    ('Canada', 'Bosnia and Herzegovina'): '2026-06-13 03:00',
    ('Qatar', 'Switzerland'): '2026-06-14 03:00',
    ('Switzerland', 'Bosnia and Herzegovina'): '2026-06-19 03:00',
    ('Canada', 'Qatar'): '2026-06-19 06:00',
    ('Switzerland', 'Canada'): '2026-06-25 03:00',
    ('Bosnia and Herzegovina', 'Qatar'): '2026-06-25 03:00',
    ('Brazil', 'Morocco'): '2026-06-14 06:00',
    ('Haiti', 'Scotland'): '2026-06-14 09:00',
    ('Scotland', 'Morocco'): '2026-06-20 06:00',
    ('Brazil', 'Haiti'): '2026-06-20 08:30',
    ('Scotland', 'Brazil'): '2026-06-25 06:00',
    ('Morocco', 'Haiti'): '2026-06-25 06:00',
    ('United States', 'Paraguay'): '2026-06-13 09:00',
    ('Australia', 'Turkey'): '2026-06-14 12:00',
    ('United States', 'Australia'): '2026-06-20 03:00',
    ('Turkey', 'Paraguay'): '2026-06-20 11:00',
    ('Turkey', 'United States'): '2026-06-26 10:00',
    ('Paraguay', 'Australia'): '2026-06-26 10:00',
    ('Germany', 'Curaçao'): '2026-06-15 01:00',
    ('Ivory Coast', 'Ecuador'): '2026-06-15 07:00',
    ('Germany', 'Ivory Coast'): '2026-06-21 04:00',
    ('Ecuador', 'Curaçao'): '2026-06-21 08:00',
    ('Curaçao', 'Ivory Coast'): '2026-06-26 04:00',
    ('Ecuador', 'Germany'): '2026-06-26 04:00',
    ('Netherlands', 'Japan'): '2026-06-15 04:00',
    ('Sweden', 'Tunisia'): '2026-06-15 10:00',
    ('Netherlands', 'Sweden'): '2026-06-21 01:00',
    ('Tunisia', 'Japan'): '2026-06-21 12:00',
    ('Japan', 'Sweden'): '2026-06-26 07:00',
    ('Tunisia', 'Netherlands'): '2026-06-26 07:00',
    ('Belgium', 'Egypt'): '2026-06-16 03:00',
    ('Iran', 'New Zealand'): '2026-06-16 09:00',
    ('Belgium', 'Iran'): '2026-06-22 03:00',
    ('New Zealand', 'Egypt'): '2026-06-22 09:00',
    ('Egypt', 'Iran'): '2026-06-27 11:00',
    ('New Zealand', 'Belgium'): '2026-06-27 11:00',
    ('Spain', 'Cape Verde'): '2026-06-16 00:00',
    ('Saudi Arabia', 'Uruguay'): '2026-06-16 06:00',
    ('Spain', 'Saudi Arabia'): '2026-06-22 00:00',
    ('Uruguay', 'Cape Verde'): '2026-06-22 06:00',
    ('Cape Verde', 'Saudi Arabia'): '2026-06-27 08:00',
    ('Uruguay', 'Spain'): '2026-06-27 08:00',
    ('France', 'Senegal'): '2026-06-17 03:00',
    ('Iraq', 'Norway'): '2026-06-17 06:00',
    ('France', 'Iraq'): '2026-06-23 05:00',
    ('Norway', 'Senegal'): '2026-06-23 08:00',
    ('Norway', 'France'): '2026-06-27 03:00',
    ('Senegal', 'Iraq'): '2026-06-27 03:00',
    ('Argentina', 'Algeria'): '2026-06-17 09:00',
    ('Austria', 'Jordan'): '2026-06-17 12:00',
    ('Argentina', 'Austria'): '2026-06-23 01:00',
    ('Jordan', 'Algeria'): '2026-06-23 11:00',
    ('Algeria', 'Austria'): '2026-06-28 10:00',
    ('Jordan', 'Argentina'): '2026-06-28 10:00',
    ('Portugal', 'DR Congo'): '2026-06-18 01:00',
    ('Uzbekistan', 'Colombia'): '2026-06-18 10:00',
    ('Portugal', 'Uzbekistan'): '2026-06-24 01:00',
    ('Colombia', 'DR Congo'): '2026-06-24 10:00',
    ('Colombia', 'Portugal'): '2026-06-28 07:30',
    ('DR Congo', 'Uzbekistan'): '2026-06-28 07:30',
    ('England', 'Croatia'): '2026-06-18 04:00',
    ('Ghana', 'Panama'): '2026-06-18 07:00',
    ('England', 'Ghana'): '2026-06-24 04:00',
    ('Panama', 'Croatia'): '2026-06-24 07:00',
    ('Panama', 'England'): '2026-06-28 05:00',
    ('Croatia', 'Ghana'): '2026-06-28 05:00',
}

# 淘汰赛: 场次编号 -> 北京时间
KO = {
    73: '2026-06-29 03:00',
    74: '2026-06-30 04:30',
    75: '2026-06-30 09:00',
    76: '2026-06-30 01:00',
    77: '2026-07-01 05:00',
    78: '2026-07-01 01:00',
    79: '2026-07-01 09:00',
    80: '2026-07-02 00:00',
    81: '2026-07-02 08:00',
    82: '2026-07-02 04:00',
    83: '2026-07-03 07:00',
    84: '2026-07-03 03:00',
    85: '2026-07-03 11:00',
    86: '2026-07-04 06:00',
    87: '2026-07-04 09:30',
    88: '2026-07-04 02:00',
    89: '2026-07-05 05:00',
    90: '2026-07-05 01:00',
    91: '2026-07-06 04:00',
    92: '2026-07-06 08:00',
    93: '2026-07-07 03:00',
    94: '2026-07-07 08:00',
    95: '2026-07-08 00:00',
    96: '2026-07-08 04:00',
    97: '2026-07-10 04:00',
    98: '2026-07-11 03:00',
    99: '2026-07-12 05:00',
    100: '2026-07-12 09:00',
    101: '2026-07-15 03:00',
    102: '2026-07-16 03:00',
    103: '2026-07-19 05:00',
    104: '2026-07-20 03:00',
}
