"""
动态 Elo 评级（World Football Elo 风格）+ 评级差 -> 胜平负 概率映射。

与 Dixon-Coles 的区别：Elo 按时间顺序逐场滚动更新，近期自动占更大权重、
评级随状态演化——不需要时间衰减这种"外挂"。含两项足球专属改造：
  - 进球差加成 G：大比分赢球评级涨得更多
  - 赛事重要性 K：世界杯 > 预选赛 > 友谊赛

评级差 -> 胜平负：用有序 Logit（OrderedModel）在历史上拟合 diff→[客胜,平,主胜]。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from statsmodels.miscmodels.ordinal_model import OrderedModel

import data as datamod

BASE = 1500.0
HFA = 65.0   # 主场优势（Elo 分），中立场为 0


def _k_importance(tournament: str) -> float:
    t = (tournament or "").lower()
    if "friendly" in t:
        return 15.0
    if "qualification" in t or "qualifier" in t:
        return 32.0
    if any(s in t for s in ["world cup", "euro", "copa am", "african cup",
                            "asian cup", "nations league", "confederations",
                            "gold cup", "uefa euro"]):
        return 55.0
    return 30.0


def _gd_mult(gd: int) -> float:
    """进球差加成（World Football Elo）。"""
    agd = abs(gd)
    if agd <= 1:
        return 1.0
    if agd == 2:
        return 1.5
    return (11.0 + agd) / 8.0


def prematch_ratings(df: pd.DataFrame, as_of=None):
    """按时间顺序滚动 Elo，返回 (每场赛前评级 {df_index:(home_elo,away_elo)}, 截至最后的最终评级 dict)。
    供把 Elo 差作为外生特征喂进双泊松 GLM 用。"""
    pl = datamod.played(df).sort_values("date")
    if as_of is not None:
        pl = pl[pl["date"] <= pd.Timestamp(as_of)]
    R: dict[str, float] = {}
    pre: dict[int, tuple] = {}
    for idx, m in pl.iterrows():
        h, a = m["home_team"], m["away_team"]
        rh, ra = R.get(h, BASE), R.get(a, BASE)
        pre[idx] = (rh, ra)                       # 赛前评级（无泄漏）
        adv = 0.0 if m["neutral"] else HFA
        diff = rh + adv - ra
        hs, as_s = int(m["home_score"]), int(m["away_score"])
        E = 1.0 / (1.0 + 10 ** (-diff / 400.0))
        W = 1.0 if hs > as_s else (0.5 if hs == as_s else 0.0)
        k = _k_importance(m["tournament"]) * _gd_mult(hs - as_s)
        delta = k * (W - E)
        R[h] = rh + delta
        R[a] = ra - delta
    return pre, R


class EloModel:
    def __init__(self, hfa=HFA):
        self.hfa = hfa
        self.ratings: dict[str, float] = {}
        self.ord = None  # 有序 Logit: diff -> 概率

    def fit(self, df: pd.DataFrame, as_of=None, verbose=False):
        pl = datamod.played(df).sort_values("date")
        if as_of is not None:
            pl = pl[pl["date"] <= pd.Timestamp(as_of)]
        R: dict[str, float] = {}
        diffs, outs = [], []
        for _, m in pl.iterrows():
            h, a = m["home_team"], m["away_team"]
            rh, ra = R.get(h, BASE), R.get(a, BASE)
            adv = 0.0 if m["neutral"] else self.hfa
            diff = rh + adv - ra
            hs, as_s = int(m["home_score"]), int(m["away_score"])
            outcome = 2 if hs > as_s else (1 if hs == as_s else 0)  # 0客胜 1平 2主胜
            diffs.append(diff); outs.append(outcome)
            # 更新评级
            E = 1.0 / (1.0 + 10 ** (-diff / 400.0))   # 主队期望得分率
            W = 1.0 if outcome == 2 else (0.5 if outcome == 1 else 0.0)
            k = _k_importance(m["tournament"]) * _gd_mult(hs - as_s)
            delta = k * (W - E)
            R[h] = rh + delta
            R[a] = ra - delta
        self.ratings = R

        # diff -> [客胜,平,主胜] 有序 Logit
        dfo = pd.DataFrame({
            "y": pd.Categorical(outs, categories=[0, 1, 2], ordered=True),
            "diff": np.array(diffs, dtype=float) / 100.0,  # 缩放便于收敛
        })
        self.ord = OrderedModel(dfo["y"], dfo[["diff"]], distr="logit").fit(
            method="bfgs", disp=False)
        if verbose:
            top = sorted(R.items(), key=lambda x: x[1], reverse=True)[:8]
            print("[elo] 评级 Top8:", ", ".join(f"{t}:{r:.0f}" for t, r in top))
        return self

    def rating(self, team: str) -> float:
        return self.ratings.get(team, BASE)

    def predict_wdl(self, home: str, away: str, neutral=True):
        adv = 0.0 if neutral else self.hfa
        diff = (self.rating(home) + adv - self.rating(away)) / 100.0
        p = self.ord.model.predict(self.ord.params, np.array([[diff]]))[0]
        # p 顺序对应 categories [0客胜,1平,2主胜]
        return float(p[2]), float(p[1]), float(p[0])  # (p_home, p_draw, p_away)


if __name__ == "__main__":
    m = EloModel().fit(datamod.load_raw(), verbose=True)
    for h, a in [("Argentina", "France"), ("Spain", "Brazil"), ("Germany", "Japan")]:
        ph, pd_, pa = m.predict_wdl(h, a)
        print(f"  {h} vs {a}: 主胜{ph:.0%} 平{pd_:.0%} 客胜{pa:.0%}  "
              f"(Elo {m.rating(h):.0f} vs {m.rating(a):.0f})")
