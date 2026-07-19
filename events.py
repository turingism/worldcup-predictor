#!/usr/bin/env python3
"""赛事注册表（多赛事扩展 L0/L1 的驱动配置，见 docs/MULTI_EVENT_PLAN.md）。

纯配置模块：零依赖、零副作用，app 尚未接线（P1 世界杯结束后接）。
每个赛事一条注册；页面 L0 切换器排序、L1 tab 装配、数据/实时/账本路径全部由此驱动。

字段约定：
  name        中文显示名
  kind        赛制：cup(小组+括号) / league(双循环) / league_cup(联赛制+决赛圈) / swiss_cup(瑞士轮+括号)
  universe    模型宇宙：intl(国家队,共用现有 model.pkl) / club_<lg>(俱乐部,每联赛独立模型)
  espn        ESPN league code（live/odds 层参数化用；2026-07-08 已实测全部有响应）
  data        国家队=results.csv 的 tournament 精确值；俱乐部=clubdata league code
  window      (开赛日, 结束日) ISO 日期；联赛=赛季窗
  ledger      验证账本文件名（按赛事隔离，绝不混池）
  tabs_off    该赛事关闭的 L1 tab（默认全开；kind 决定 bracket/standings 二选一，不在此列）
"""
from __future__ import annotations
import datetime as dt

EVENTS: dict[str, dict] = {
    "wc2026": dict(
        name="世界杯 2026", kind="cup", universe="intl",
        espn="fifa.world", data="FIFA World Cup",
        window=("2026-06-11", "2026-07-19"),
        ledger="predictions.json",          # 现状文件名，保持向后兼容
    ),
    "nl2026": dict(
        name="欧国联 26-27", kind="league_cup", universe="intl",
        espn="uefa.nations", data="UEFA Nations League",
        window=("2026-09-03", "2027-06-06"),
        ledger="predictions_nl2026.json",
    ),
    "epl2526": dict(
        name="英超 25-26", kind="league", universe="club_E0",
        espn="eng.1", data="E0",
        window=("2026-08-08", "2027-05-23"),
        ledger="predictions_epl2526.json",
        tabs_off=("xuanxue",),
    ),
    # —— 其余四大联赛（P3；espn code 2026-07-08 已实测有响应，窗口=官方赛历近似）——
    "laliga2526": dict(
        name="西甲 25-26", kind="league", universe="club_SP1",
        espn="esp.1", data="SP1",
        window=("2026-08-15", "2027-05-23"),
        ledger="predictions_laliga2526.json",
        tabs_off=("xuanxue",),
    ),
    "seriea2526": dict(
        name="意甲 25-26", kind="league", universe="club_I1",
        espn="ita.1", data="I1",
        window=("2026-08-22", "2027-05-30"),
        ledger="predictions_seriea2526.json",
        tabs_off=("xuanxue",),
    ),
    "bundes2526": dict(
        name="德甲 25-26", kind="league", universe="club_D1",
        espn="ger.1", data="D1",
        window=("2026-08-21", "2027-05-15"),
        ledger="predictions_bundes2526.json",
        tabs_off=("xuanxue",),
    ),
    "ligue12526": dict(
        name="法甲 25-26", kind="league", universe="club_F1",
        espn="fra.1", data="F1",
        window=("2026-08-14", "2027-05-22"),
        ledger="predictions_ligue12526.json",
        tabs_off=("xuanxue",),
    ),
    # P3 同构追加：euro2028 / copa2028 / afcon2027 / asian2027 / ucl(P4)
}

DEFAULT = "wc2026"


def status(key: str, today: dt.date | None = None) -> str:
    """live(窗内) / soon(30 天内开赛) / upcoming(未来) / archived(已结束)。L0 排序依据。"""
    today = today or dt.date.today()
    a, b = (dt.date.fromisoformat(x) for x in EVENTS[key]["window"])
    if a <= today <= b:
        return "live"
    if today < a:
        return "soon" if (a - today).days <= 30 else "upcoming"
    return "archived"


_ORDER = {"live": 0, "soon": 1, "upcoming": 2, "archived": 3}


def sorted_events(today: dt.date | None = None) -> list[str]:
    """L0 切换器顺序：进行中 > 30 天内开赛 > 未来 > 归档；同级按开赛日。"""
    return sorted(EVENTS, key=lambda k: (_ORDER[status(k, today)], EVENTS[k]["window"][0]))


def get(key: str | None = None) -> dict:
    return {**EVENTS[key or DEFAULT], "key": key or DEFAULT}
