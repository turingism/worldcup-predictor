"""In-play real-time win/draw/loss update.

比赛进行中（in-play）实时胜平负更新。

原理：赛前 Dixon-Coles 给出双方 90 分钟期望进球 λ_主/λ_客。把进球看作 90 分钟上的
齐次泊松过程——已进行 t 分钟后，剩余时间 (90−t)/90，各队剩余进球 ~ Poisson(λ·剩余比例)。
当前比分 (gh, ga) 加上各自剩余进球（独立卷积）得「从现状到终场」的终场比分分布，
聚合成胜/平/负。

铁律（与赛前可证伪性隔离）：
  - 只读调用 model.expected_goals，**绝不改 GLM、绝不写 predictions.json、绝不进 verify 统计**；
  - 这是赛前引擎在「当前比分+剩余时间」上的条件化使用，零新参数、零训练；
  - 仅用于看板「正在比赛」的实时展示，与赛前冻结预测物理分离。

简化取舍：剩余进球用纯泊松独立卷积（不加 DC ρ 低分修正）——ρ 修正是针对整场终场低分格的
相关性，对「剩余短时段进球」意义甚微；in-play 概率由当前比分+剩余时间主导。
"""
from __future__ import annotations
import re

import numpy as np
from scipy.stats import poisson

import env

MAX_REM = 10          # 每队剩余进球枚举上限（11×11 终场组合，足够覆盖）
FULL = 90.0           # 常规时间（缩放分母）


def parse_minute(clock: str | None, period: int | None = None) -> int:
    """ESPN displayClock → 整数分钟（用于剩余时间缩放）。
    "67'"→67；"90'+7'"→90（封顶）；"45'+2'"→45；"HT"→45；空/赛前→0。"""
    if clock:
        s = str(clock).strip().strip("'")
        m = re.match(r"(\d+)", s)
        if m:
            return min(95, int(m.group(1)))
        if "HT" in s.upper():
            return 45
    return 45 if period == 2 else 0


def remaining_fraction(minute: float) -> float:
    """剩余时间占比，夹紧 [0,1]。补时（>90）→0（按已无常规剩余处理）。"""
    return min(1.0, max(0.0, (FULL - minute) / FULL))


def _tail_pmf(lam: float) -> np.ndarray:
    """0..MAX_REM 的泊松分布，尾部概率并入最后一格保证归一。"""
    ks = np.arange(MAX_REM + 1)
    p = poisson.pmf(ks, lam)
    p[-1] += max(0.0, 1.0 - p.sum())
    return p


def win_draw_loss(model, home: str, away: str, gh: int, ga: int, minute: float,
                  neutral: bool = True, env_mult=None) -> dict:
    """从当前比分 (gh-ga) 与已进行 minute 分钟，估计「从现状到终场」的胜平负分布。

    返回 {p_home, p_draw, p_away, t_rem, lam_h, lam_a, exp_final_h, exp_final_a}。
    p_* 是终场（含已进球）主胜/平/客胜概率。只读模型。"""
    _h, _a, lam_h, lam_a = model.expected_goals(home, away, neutral, env_mult)
    t_rem = remaining_fraction(minute)
    lh, la = lam_h * t_rem, lam_a * t_rem
    ph, pa = _tail_pmf(lh), _tail_pmf(la)
    p_home = p_draw = p_away = 0.0
    for x in range(MAX_REM + 1):
        if ph[x] == 0.0:
            continue
        for y in range(MAX_REM + 1):
            p = ph[x] * pa[y]
            fh, fa = gh + x, ga + y
            if fh > fa:
                p_home += p
            elif fh < fa:
                p_away += p
            else:
                p_draw += p
    s = p_home + p_draw + p_away or 1.0
    return {"p_home": p_home / s, "p_draw": p_draw / s, "p_away": p_away / s,
            "t_rem": round(t_rem, 4),
            "lam_h": round(float(lam_h), 3), "lam_a": round(float(lam_a), 3),
            "exp_final_h": round(gh + lh, 2), "exp_final_a": round(ga + la, 2)}


def win_draw_loss_host(model, home: str, away: str, gh: int, ga: int, minute: float,
                       host: str | None = None, city: str | None = None) -> dict:
    """host+env 口径的 in-play 胜平负（镜像 verify.pair_predict 的朝向逻辑）。

    东道主场次接入主场优势 + 环境乘子，使 live 卡与赛前冻结概率**同口径**；
    host 语义=英文队名（与账本 e['host'] 一致）。非东道主场次退化为原 neutral 行为。"""
    mh, ma = env.match_mult(home, away, city)
    em = (mh, ma) if (mh, ma) != (1.0, 1.0) and city else None
    if host == home:
        return win_draw_loss(model, home, away, gh, ga, minute, neutral=False, env_mult=em)
    if host == away:                       # away 为主 → 反向计算后转置回 home 视角
        r = win_draw_loss(model, away, home, ga, gh, minute, neutral=False,
                          env_mult=(em[1], em[0]) if em else None)
        return {"p_home": r["p_away"], "p_draw": r["p_draw"], "p_away": r["p_home"],
                "t_rem": r["t_rem"],
                "lam_h": r["lam_a"], "lam_a": r["lam_h"],
                "exp_final_h": r["exp_final_a"], "exp_final_a": r["exp_final_h"]}
    return win_draw_loss(model, home, away, gh, ga, minute, neutral=True, env_mult=em)


if __name__ == "__main__":
    # 自测：t=0 应≈赛前 predict；领先方随时间推进概率单调上升
    from predict import get_model
    m = get_model(use_cache=True, half_life=730.0, verbose=False)
    pre = m.predict("Germany", "Curaçao", neutral=True)
    ip0 = win_draw_loss(m, "Germany", "Curaçao", 0, 0, 0, neutral=True)
    print(f"赛前 predict  : 主{pre['p_home']:.3f} 平{pre['p_draw']:.3f} 客{pre['p_away']:.3f}")
    print(f"in-play t=0   : 主{ip0['p_home']:.3f} 平{ip0['p_draw']:.3f} 客{ip0['p_away']:.3f}  (应≈赛前)")
    for mn, (gh, ga) in [(0, (0, 0)), (30, (1, 0)), (60, (1, 0)), (85, (1, 0)), (90, (1, 0))]:
        r = win_draw_loss(m, "Germany", "Curaçao", gh, ga, mn, neutral=True)
        print(f"  {mn:>2}' 比分{gh}-{ga} → 主{r['p_home']:.3f} 平{r['p_draw']:.3f} 客{r['p_away']:.3f} (剩{r['t_rem']:.2f})")
