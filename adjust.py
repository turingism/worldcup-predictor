# Repository summary: World Cup prediction analytics module.
"""
上下文调整层：关键球员可用性 → 每队 xG 乘子。

定位：与 bayes.py 同样是『补充层』，**不属于已回测验证的 DC 预测引擎**。
当 availability.json 为空时零影响，引擎数值与纯 DC 完全一致（保证 backtest 不受污染）。

原理（期望惩罚）
--------------
一名球员对球队 xG 的影响 = 其档位影响 impact ∈ {superstar .13, key .07, squad .025}。
他真正缺阵的概率 = status=out 时 1.0，doubtful 时取 prob 字段。
故**期望惩罚 e = P(缺阵) × impact**，按出场角色作用：
  role=attack  → 自家进攻 λ × (1 - e)
  role=defence → 对手进球 λ × (1 + e)   （防线松动，被进更多）
  role=all     → 进攻 ×(1 - .6e)，防守端 对手 ×(1 + .6e)   （攻防各担一部分）
多名球员的乘子连乘。

对标 Kimi 8.3.1 伤病矩阵口径，但数值为本项目自定校准（单场 xG 量级，偏保守），
非照搬。校准依据：Kimi 称『单一球星缺阵可改变夺冠概率 ±5%』——经 7 场淘汰赛复利，
单场约 6-12% 的 xG 削弱即可累积到该量级。
"""
from __future__ import annotations
import json
import os

AVAIL_PATH = os.path.join(os.path.dirname(__file__), "data", "availability.json")
_DEFAULT_TIERS = {"superstar": 0.13, "key": 0.07, "squad": 0.025}


def load_availability(path: str = AVAIL_PATH) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


def team_modifiers(avail: dict | None = None) -> dict[str, dict]:
    """
    返回 {team: {"att": att_mult, "def_pen": def_pen, "items": [...] }}。
    att_mult<1 削自家进攻；def_pen>1 抬对手进球。仅含有缺阵项的队。
    """
    if avail is None:
        avail = load_availability()
    tiers = (avail.get("_meta", {}) or {}).get("tiers", _DEFAULT_TIERS)
    out: dict[str, dict] = {}
    for team, items in avail.items():
        if team.startswith("_") or not isinstance(items, list):
            continue
        att, dfp = 1.0, 1.0
        used = []
        for it in items:
            impact = tiers.get(it.get("tier", "key"), _DEFAULT_TIERS["key"])
            p = 1.0 if it.get("status") == "out" else float(it.get("prob", 0.0))
            e = max(0.0, min(0.5, p * impact))   # 单球员封顶 50%，防极端
            if e <= 0:
                continue
            role = it.get("role", "attack")
            if role == "attack":
                att *= (1 - e)
            elif role == "defence":
                dfp *= (1 + e)
            else:  # all
                att *= (1 - 0.6 * e)
                dfp *= (1 + 0.6 * e)
            used.append({**it, "exp_penalty": round(e, 4)})
        if used:
            out[team] = {"att": round(att, 4), "def_pen": round(dfp, 4), "items": used}
    return out


def summary_lines(mods: dict[str, dict]) -> list[str]:
    """人读摘要，给 CLI / 日志用。"""
    lines = []
    for team, m in sorted(mods.items(), key=lambda kv: kv[1]["att"]):
        who = ", ".join(f"{i['player']}({i.get('reason','')})" for i in m["items"])
        lines.append(f"  {team:<14} 进攻×{m['att']:.3f} 失球×{m['def_pen']:.3f}  ← {who}")
    return lines


if __name__ == "__main__":
    mods = team_modifiers()
    if not mods:
        print("availability.json 无缺阵项（零影响）。")
    else:
        print(f"关键球员可用性调整（{len(mods)} 队受影响）：")
        print("\n".join(summary_lines(mods)))
