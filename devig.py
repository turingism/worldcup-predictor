#!/usr/bin/env python3
"""去 margin（de-vig）方法库——把博彩十进制赔率还原成"真实"概率的三种口径。

为什么需要它（这就是 365/皇冠/伟德/威廉 这些公司的赔率在**算法上**能给的启发）：
  庄家挂的赔率隐含概率之和 > 1，多出来的就是抽水（overround / margin）。要拿盘口当
  "金标准概率"对标模型，必须先把这层抽水剥掉。剥法不止一种，且**剥法会系统性影响结论**：

  - proportional（按比例归一，本项目原口径）：p_i = (1/o_i) / Σ(1/o_j)。
    最简单，但假设抽水按隐含概率**等比例**摊到每个选项——已知会**高估冷门、低估热门**
    （favorite–longshot bias），因为庄家对冷门加更多水。
  - odds_ratio（Cheung 赔率比法）：真实赔率与挂牌赔率成**恒定赔率比** c，解 c 使 Σp=1。
  - shin（Shin 1992/93 内幕交易模型）：把抽水建模为"有比例 z 的知情者下注"，闭式解能
    **纠正 favorite–longshot 偏差**，学界多次实证比 proportional 更贴近真实概率。

诚实边界：这是**对盘口（外部金标准）的还原口径**改良，**完全不碰 GLM/训练**——只影响
"市场层"怎么读赔率。是否采用要用 `bt_devig.py` 在真实赛果上跑 RPS/LogLoss 证明更好
（项目铁律：用数字说话，否则不采用）。本项目个人/教育定位，**仅为概率推演、非投注建议**。
"""
from __future__ import annotations

import numpy as np

try:
    from scipy.optimize import brentq
    _HAS_SCIPY = True
except Exception:  # noqa  无 scipy 时退化到自带二分
    _HAS_SCIPY = False


def _solve(f, lo, hi):
    """在 [lo,hi] 解 f=0；优先 scipy.brentq，回退手写二分（端点同号则返回 None）。"""
    try:
        if f(lo) * f(hi) > 0:
            return None
        if _HAS_SCIPY:
            return float(brentq(f, lo, hi, maxiter=200, xtol=1e-12))
        for _ in range(200):                       # 二分兜底
            mid = 0.5 * (lo + hi)
            if f(lo) * f(mid) <= 0:
                hi = mid
            else:
                lo = mid
        return 0.5 * (lo + hi)
    except Exception:  # noqa
        return None


def proportional(o1: float, ox: float, o2: float) -> np.ndarray:
    """按比例归一（原口径）：p_i = (1/o_i) / Σ(1/o_j)。"""
    inv = np.array([1.0 / o1, 1.0 / ox, 1.0 / o2])
    return inv / inv.sum()


def odds_ratio(o1: float, ox: float, o2: float) -> np.ndarray:
    """Cheung 赔率比法：p_i = b_i / (c + b_i − c·b_i)，b_i=1/o_i，解 c 使 Σp_i=1。"""
    b = np.array([1.0 / o1, 1.0 / ox, 1.0 / o2])

    def total(c):
        return float((b / (c + b - c * b)).sum()) - 1.0

    # overround>1 时需 c>1 收缩；给宽括号
    c = _solve(total, 1e-6, 1e6)
    if c is None:
        return proportional(o1, ox, o2)
    p = b / (c + b - c * b)
    return p / p.sum()                              # 数值兜底再归一


def shin(o1: float, ox: float, o2: float) -> np.ndarray:
    """Shin 内幕交易法：p_i = (√(z²+4(1−z)·a_i²/Σa) − z) / (2(1−z))，a_i=1/o_i，解 z 使 Σp=1。

    z = 估计的知情下注比例（≈庄家因防内幕而额外加的水）。能纠正 favorite–longshot 偏差。"""
    a = np.array([1.0 / o1, 1.0 / ox, 1.0 / o2])
    sa = float(a.sum())

    def probs(z):
        return (np.sqrt(z * z + 4.0 * (1.0 - z) * a * a / sa) - z) / (2.0 * (1.0 - z))

    def total(z):
        return float(probs(z).sum()) - 1.0

    # z=0 时 Σp=√(Σa)>1（有抽水必 >1）；z↑ 使 Σp↓，根在 (0, ~0.5)
    z = _solve(total, 1e-9, 0.9)
    if z is None:
        return proportional(o1, ox, o2)
    p = probs(z)
    return p / p.sum()


METHODS = {"proportional": proportional, "odds_ratio": odds_ratio, "shin": shin}


def implied(o1: float, ox: float, o2: float, method: str = "proportional"):
    """统一入口：返回 (去 margin 概率 [主,平,客], overround/margin)。method 选 de-vig 口径。"""
    fn = METHODS.get(method, proportional)
    p = fn(o1, ox, o2)
    margin = float(np.array([1.0 / o1, 1.0 / ox, 1.0 / o2]).sum() - 1.0)
    return p, margin


if __name__ == "__main__":   # 自测：三法都归一；shin/OR 相对 proportional 把热门概率抬高
    for odds in [(1.50, 4.20, 7.00), (2.30, 3.40, 3.20), (1.20, 7.0, 15.0)]:
        pp = proportional(*odds)
        po = odds_ratio(*odds)
        ps = shin(*odds)
        print(f"odds={odds}  margin={(sum(1/o for o in odds)-1)*100:.1f}%")
        for nm, p in (("proportional", pp), ("odds_ratio", po), ("shin", ps)):
            assert abs(p.sum() - 1.0) < 1e-6, (nm, p.sum())
            print(f"   {nm:<12} 主{p[0]:.3f} 平{p[1]:.3f} 客{p[2]:.3f}")
        # 热门（最低赔率那项）在 shin/OR 下应 ≥ proportional（纠正 favorite-longshot）
        fav = int(np.argmin(odds))
        print(f"   热门项[{fav}] proportional={pp[fav]:.3f} → shin={ps[fav]:.3f} "
              f"({'抬高✓' if ps[fav] >= pp[fav] - 1e-9 else '降低'})")
