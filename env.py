"""
环境上下文层：海拔 + 高温 → 每场每队 xG 乘子。

定位：和 adjust.py（伤病）、bayes.py 同样是『补充层』，**不属于已回测验证的 DC 引擎**。
仅在『知道场馆』的路径生效（蒙特卡洛模拟 / 括号投影）；单场预测 UI 不指定场馆故不受影响。
近年高原/高温国际赛样本太少，**无法 backtest 证伪**，故标注为实验性，效应刻意保守。

两类效应（均作用于该队自身进攻 λ，越低越弱）
------------------------------------------------
1) 海拔：墨城 2240m 使非适应球队 VO₂max≈−15%、下半场冲刺更快衰减（Kimi 6.5）。
   高原适应国（本土常年高海拔，alt_adapted）免罚；其余 1200m 起线性、2240m≈−5%。
   注：东道主主场优势是另一套机制（simulate 已建模），与此正交：墨西哥既适应又有主场。
2) 高温：达拉斯/休斯顿等 WBGT 32°C+ 使高强度跑动−26%（Mohr 2012，Kimi 6.4）。
   凉爽气候国（cool_climate，以 UEFA 为主）受『热环境税』更重——这是 Kimi 强调的不对称。

数值为本项目自校准（单场量级、偏保守），非照搬 Kimi。
"""
from __future__ import annotations
import json
import os

_VEN = os.path.join(os.path.dirname(__file__), "data", "venues.json")
_CACHE = {}


def _cfg():
    if not _CACHE:
        try:
            with open(_VEN, encoding="utf-8") as f:
                v = json.load(f)
            _CACHE["geo"] = v.get("geo", {})
            _CACHE["alt_adapted"] = set(v.get("alt_adapted", []))
            _CACHE["cool"] = set(v.get("cool_climate", []))
        except (OSError, json.JSONDecodeError):
            _CACHE["geo"] = {}; _CACHE["alt_adapted"] = set(); _CACHE["cool"] = set()
    return _CACHE


def _alt_mult(team: str, alt) -> float:
    if not alt or alt < 1200:
        return 1.0
    if team in _cfg()["alt_adapted"]:
        return 1.0
    pen = min(0.08, (alt - 1200) / 1000.0 * 0.04)   # 2240m → ~4.2%，封顶 8%
    return 1.0 - pen


def _heat_mult(team: str, heat) -> float:
    if not heat:
        return 1.0
    cool = team in _cfg()["cool"]
    table = ({"extreme": 0.05, "high": 0.03} if cool       # 凉爽气候国热环境税更重
             else {"extreme": 0.02, "high": 0.01})         # 其余相对耐热
    return 1.0 - table.get(heat, 0.0)


def match_mult(a: str, b: str, city: str | None) -> tuple[float, float]:
    """返回 (mult_a, mult_b)：该场 city 对两队各自进攻 λ 的环境乘子。city=None → (1,1)。"""
    if not city:
        return 1.0, 1.0
    g = _cfg()["geo"].get(city)
    if not g:
        return 1.0, 1.0
    alt, heat = g.get("alt"), g.get("heat")
    ma = _alt_mult(a, alt) * _heat_mult(a, heat)
    mb = _alt_mult(b, alt) * _heat_mult(b, heat)
    return round(ma, 4), round(mb, 4)


def explain(city: str | None) -> dict | None:
    """城市环境信息，给前端/调试。"""
    if not city:
        return None
    g = _cfg()["geo"].get(city)
    return {"city": city, "alt": g.get("alt"), "heat": g.get("heat")} if g else None


if __name__ == "__main__":
    for c in ["Mexico City", "Dallas", "Boston", "Guadalajara"]:
        print(f"=== {c} {explain(c)} ===")
        for a, b in [("France", "Ecuador"), ("Mexico", "Germany"), ("Brazil", "England")]:
            ma, mb = match_mult(a, b, c)
            print(f"  {a} ×{ma}  |  {b} ×{mb}")
