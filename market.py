# Repository summary: World Cup prediction analytics module.
"""
国家队身价数据（Transfermarkt）+ 作为实力先验的工具。

来源：transfermarkt.com「最有价值国家队」榜（data/market_values.json）。
用途：对样本不足的球队，把其攻防评级向「身价隐含评级」收缩，
      解决新军/小国（如卡塔尔、库拉索）历史样本少、评级不稳的问题。
"""
from __future__ import annotations
import json
import os

import numpy as np

_PATH = os.path.join(os.path.dirname(__file__), "data", "market_values.json")
_VALUES: dict[str, float] = {}
if os.path.exists(_PATH):
    _VALUES = json.load(open(_PATH, encoding="utf-8"))


def value(team: str):
    """球队身价（百万欧元），无则 None。"""
    return _VALUES.get(team)


def log_value(team: str):
    v = _VALUES.get(team)
    return float(np.log(v)) if v else None


def has_data() -> bool:
    return bool(_VALUES)
