#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""淘汰赛「保守效应」实证检验：90 分钟口径下，淘汰赛是否真的进球更少 / 平局更多？

为什么单独写这一支
------------------
本项目主数据集 data/results.csv 记录的是**含加时、不含点球**的全场比分（已核：2014 决赛
记 1-0=加时绝杀，90 分钟其实 0-0）。淘汰赛的「保守」是 **90 分钟现象**，加时会把被压下去的
进球又加回来——所以在 results.csv 的含加时标的上，淘汰赛进球数与小组赛**无显著差异**
（场均 -0.08，p≈0.60），保守信号被洗掉。要验证保守效应，必须拿到 **90 分钟单独记分**。

数据源
------
Fjelstul World Cup Database（github.com/jfjelstul/worldcup，CC-BY-SA 4.0）：
  - matches.csv：带 knockout_stage / group_stage / extra_time / penalty_shootout 标记
  - goals.csv：每个进球带 match_period（first/second half vs "extra time ..."）+ own_goal
用「match_period 不以 'extra time' 开头」重构每场 90 分钟比分（已用 1155 场无加时比赛
自校验：90 分钟重构 == 最终分，零误差）。

结论（截至 1986-2022 现代 16 强淘汰赛制，2026 淘汰赛打完可重跑刷新）
----------------------------------------------------------------
  原始 90 分钟：淘汰赛场均进球 2.50 vs 小组赛 2.77（-0.27，Welch p≈0.04 显著），
                平局率 29% vs 22%（+7pp，z 检验 p≈0.02 显著）——保守效应在 90 分钟口径**真实**。
  但**剔除球队强度**后（带 knockout 项的 Poisson 回归，球队攻防固定效应吸收强度）：
                纯阶段乘子 exp(ko) ≈ 0.93，95%CI 跨过 1.0，**p≈0.16 不显著**。
  即原始保守里约一半是「淘汰赛球队更强、更势均力敌→自然进球少」，而引擎的攻防评级**已建模这部分**。
  纯增量保守太弱、不显著 → **不该叠进 GLM**（会重复扣减强度、过度修正，且过不了回测显著门槛）。
  对竞彩等 **90 分钟结算盘正相关**（用户实际玩竞彩 90 分钟盘）；但纯增量不显著、引擎已建模强度
  那部分，故不建模。此负结论对口径假设稳健——90 分钟与含加时口径下纯阶段保守均不显著。零碰 GLM。
"""
from __future__ import annotations
import os
import urllib.request
import numpy as np
import pandas as pd

DATA = os.path.join(os.path.dirname(__file__), "data")
BASE = "https://raw.githubusercontent.com/jfjelstul/worldcup/master/data-csv/"
FILES = {"matches": "fjelstul_matches.csv", "goals": "fjelstul_goals.csv"}


def _load(name: str) -> pd.DataFrame:
    """下载并缓存 Fjelstul 表到 data/（已存在则直接读）。"""
    local = os.path.join(DATA, FILES[name])
    if not os.path.exists(local):
        url = BASE + name + ".csv"
        print(f"[fetch] {url} -> {local}")
        urllib.request.urlretrieve(url, local)
    return pd.read_csv(local)


def reconstruct_90min():
    """返回 matches 表，附 h90/a90/tot90/draw90（90 分钟重构比分）与 year。"""
    m = _load("matches"); g = _load("goals")
    m = m[m["replay"] == 0].copy()                 # 去重赛副本
    g = g[~g["match_period"].str.startswith("extra time")]   # 仅 90 分钟内进球
    hg, ag = {}, {}
    mref = m.set_index("match_id")[["home_team_id", "away_team_id"]]
    for mid, sub in g.groupby("match_id"):
        if mid not in mref.index:
            continue
        r = mref.loc[mid]
        # goals.team_id = 受益队（乌龙球已归属对方），用它判主/客
        hg[mid] = int((sub["team_id"] == r["home_team_id"]).sum())
        ag[mid] = int((sub["team_id"] == r["away_team_id"]).sum())
    m["h90"] = m["match_id"].map(hg).fillna(0).astype(int)
    m["a90"] = m["match_id"].map(ag).fillna(0).astype(int)
    m["tot90"] = m["h90"] + m["a90"]
    m["draw90"] = (m["h90"] == m["a90"]).astype(int)
    m["year"] = pd.to_datetime(m["match_date"]).dt.year
    return m


def _self_check(m: pd.DataFrame) -> int:
    """无加时无点球的比赛：90 分钟重构应 == 最终分。返回不一致场数（应为 0）。"""
    chk = m[(m["extra_time"] == 0) & (m["penalty_shootout"] == 0)]
    bad = chk[(chk["h90"] != chk["home_team_score"]) | (chk["a90"] != chk["away_team_score"])]
    return len(bad)


def pure_stage_multiplier(m: pd.DataFrame):
    """带 knockout 项的 Poisson 回归（球队 FE 吸收强度）→ 纯阶段保守乘子 exp(ko)。"""
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    rows = []
    for _, r in m.iterrows():
        rows.append(dict(goals=r.h90, attack=r.home_team_name, defence=r.away_team_name,
                         home=1, ko=int(r.knockout_stage)))
        rows.append(dict(goals=r.a90, attack=r.away_team_name, defence=r.home_team_name,
                         home=0, ko=int(r.knockout_stage)))
    L = pd.DataFrame(rows)
    cnt = L["attack"].value_counts(); keep = set(cnt[cnt >= 6].index)   # 稀疏 FE 剔除
    L = L[L.attack.isin(keep) & L.defence.isin(keep)]
    fit = smf.glm("goals ~ home + ko + C(attack) + C(defence)", data=L,
                  family=sm.families.Poisson()).fit()
    ko, se, p = fit.params["ko"], fit.bse["ko"], fit.pvalues["ko"]
    return np.exp(ko), (np.exp(ko - 1.96 * se), np.exp(ko + 1.96 * se)), p, len(L)


def evaluate(min_year=1986):
    from scipy import stats
    from statsmodels.stats.proportion import proportions_ztest
    m = reconstruct_90min()
    bad = _self_check(m)
    M = m[m.year >= min_year]
    G = M[M.group_stage == 1]; K = M[M.knockout_stage == 1]
    t, p = stats.ttest_ind(G.tot90, K.tot90, equal_var=False)
    z, pz = proportions_ztest([G.draw90.sum(), K.draw90.sum()], [len(G), len(K)])
    mult, ci, pko, nL = pure_stage_multiplier(M)
    return dict(
        self_check_mismatches=bad, min_year=min_year, n=len(M),
        group=dict(n=len(G), goals=G.tot90.mean(), draw=G.draw90.mean()),
        knock=dict(n=len(K), goals=K.tot90.mean(), draw=K.draw90.mean()),
        raw_goal_diff=G.tot90.mean() - K.tot90.mean(), raw_goal_p=p,
        raw_ratio=K.tot90.mean() / G.tot90.mean(),
        draw_diff=K.draw90.mean() - G.draw90.mean(), draw_p=pz,
        pure_mult=mult, pure_ci=ci, pure_p=pko, pure_n=nL,
    )


def main():
    r = evaluate()
    print(f"\n  淘汰赛保守效应 · 90 分钟口径 · {r['min_year']}-2022（n={r['n']} 场）")
    print(f"  90 分钟重构自校验：无加时比赛 90分≠最终分 = {r['self_check_mismatches']} 场（应为 0）\n")
    print(f"  {'阶段':<8}{'n':>5}{'90分场均进球':>14}{'90分平局率':>12}")
    print(f"  {'小组赛':<7}{r['group']['n']:>5}{r['group']['goals']:>14.3f}{r['group']['draw']:>12.1%}")
    print(f"  {'淘汰赛':<7}{r['knock']['n']:>5}{r['knock']['goals']:>14.3f}{r['knock']['draw']:>12.1%}")
    print(f"\n  原始（未控强度）：进球差 {r['raw_goal_diff']:+.3f} (p={r['raw_goal_p']:.3f})  "
          f"平局差 {r['draw_diff']:+.3f} (p={r['draw_p']:.3f})  保守乘子≈{r['raw_ratio']:.3f}")
    lo, hi = r["pure_ci"]
    sig = "显著" if r["pure_p"] < 0.05 else "不显著"
    print(f"  纯阶段（剔球队强度+主场）：保守乘子 = {r['pure_mult']:.3f} "
          f"[95%CI {lo:.3f},{hi:.3f}]  p={r['pure_p']:.3f}（{sig}）")
    print(f"\n  结论：90 分钟口径下保守效应原始真实，但约一半由球队强度驱动（引擎已建模）；")
    print(f"  纯增量保守 ~{r['pure_mult']:.2f} 不显著 → 不叠进 GLM（避免重复扣减强度）。")
    print(f"  对竞彩等 90 分钟结算盘正相关；但纯增量不显著、不建模。零碰 GLM，个人/教育项目非投注建议。")


if __name__ == "__main__":
    main()
