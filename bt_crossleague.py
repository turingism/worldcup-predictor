"""E3 跨联赛强度校准回测：欧战交锋锚点是否让跨联赛预测更准？纯离线旁路。

方法（时序前向、as_of 防泄漏，与项目回测纪律一致）：
  每季（22-23 起，as_of=9 月 1 日）拟合两个合训 Dixon-Coles：
    m0 基线   = 五大联赛国内赛事合并帧（无跨联赛信息——联赛间刻度「裸并」，
               等价于假设各联赛同刻度，即「无校准」）
    m1 锚点   = 同上 + as_of 前全部欧战账本场次（欧战交锋提供联赛间连边，
               GLM 联合估计自动完成刻度校准——与国家队模型靠洲际交锋连边同理）
  评测集 = 该季欧战**小组/联赛阶段**中双方均属五大联赛池的场次
    （只用 leg==0 且非决赛：无加时可能，纯 90 分钟口径，规避 ESPN 终局比分含 ET）；
  指标 = RPS / 命中率（bt_club_hl 同口径）；显著性 = 逐场 RPS 差配对 bootstrap。
  另输出 m1 的联赛平均净实力表（联赛间刻度位移的可解释呈现）。

先验：样本或不足以显著（每季五大互相交锋仅数十场）——不显著则如实报告，
E4 采保守方案。训练含 KO 场次（多连边），评测不含（口径干净），docstring 即口径档案。

用法：python3 bt_crossleague.py [sims 无关，纯拟合]
"""
from __future__ import annotations
import warnings

import numpy as np
import pandas as pd

import clubdata
import clubpredict
import eurodata
from model import DixonColesModel

warnings.filterwarnings("ignore")

HL = 365.0
SEASONS_EVAL = [2022, 2023, 2024, 2025]     # 评测季（首季 21-22 留作最早训练数据）
S5 = ["E0", "SP1", "I1", "D1", "F1"]


def rps(p, out):
    c = np.cumsum(p)
    o = np.zeros(3); o[out] = 1.0
    return float(np.sum((c - np.cumsum(o))[:2] ** 2) / 2)


def _domestic_frame():
    return (pd.concat([clubdata.load(c) for c in S5], ignore_index=True)
            .sort_values("date").reset_index(drop=True))


def _pools():
    return clubpredict._league_teams(tuple(S5))


def main():
    dom = _domestic_frame()
    euro = eurodata.load().drop(columns=["season", "leg", "agg_note", "tie_id"], errors="ignore")
    euro_full = eurodata.load()
    pools = _pools()
    team2lg = {t: lg for lg, ts in pools.items() for t in ts}

    grand = {"m0": [], "m1": [], "hit0": [], "hit1": []}
    print(f"跨联赛校准回测：hl={HL:.0f}，评测=欧战小组/联赛阶段五大互相交锋（纯 90 分钟）\n")
    for sy in SEASONS_EVAL:
        cut = pd.Timestamp(f"{sy}-09-01")
        m0 = DixonColesModel(half_life_days=HL).fit(dom, verbose=False, as_of=cut)
        m1 = DixonColesModel(half_life_days=HL).fit(
            pd.concat([dom, euro], ignore_index=True).sort_values("date"),
            verbose=False, as_of=cut)
        test = euro_full[(euro_full.season == sy) & (euro_full.leg == 0)
                         & (~euro_full.neutral)
                         & euro_full.home_team.isin(team2lg)
                         & euro_full.away_team.isin(team2lg)]
        cross = test[[team2lg[h] != team2lg[a]
                      for h, a in zip(test.home_team, test.away_team)]]
        n, acc = 0, {"m0": [], "m1": [], "hit0": [], "hit1": []}
        for r in cross.itertuples():
            if any(t not in m.attack for m in (m0, m1) for t in (r.home_team, r.away_team)):
                continue
            out = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
            for key, m in (("m0", m0), ("m1", m1)):
                pr = m.predict(r.home_team, r.away_team, neutral=False)
                p = [pr["p_home"], pr["p_draw"], pr["p_away"]]
                acc[key].append(rps(p, out))
                acc["hit" + key[-1]].append(int(int(np.argmax(p)) == out))
            n += 1
        for k in grand:
            grand[k].extend(acc[k])
        if n:
            print(f"  {sy}-{(sy + 1) % 100:02d}: n={n:3d}  RPS 基线 {np.mean(acc['m0']):.4f} "
                  f"vs 锚点 {np.mean(acc['m1']):.4f}  (Δ={np.mean(acc['m1']) - np.mean(acc['m0']):+.4f})"
                  f"  命中 {np.mean(acc['hit0']):.1%} vs {np.mean(acc['hit1']):.1%}")

    d = np.array(grand["m1"]) - np.array(grand["m0"])
    n = len(d)
    rng = np.random.default_rng(42)
    boots = [rng.choice(d, n, replace=True).mean() for _ in range(4000)]
    lo, hi = np.percentile(boots, [2.5, 97.5])
    print(f"\n合并 n={n}: RPS 基线 {np.mean(grand['m0']):.4f} vs 锚点 {np.mean(grand['m1']):.4f}")
    print(f"ΔRPS={d.mean():+.4f}  bootstrap 95% CI [{lo:+.4f}, {hi:+.4f}]"
          f"  {'显著' if hi < 0 or lo > 0 else '不显著（CI 含 0）'}")
    print(f"命中率 基线 {np.mean(grand['hit0']):.1%} vs 锚点 {np.mean(grand['hit1']):.1%}")

    # 联赛刻度位移的可解释呈现：全数据锚点模型下各联赛平均净实力
    m_all = DixonColesModel(half_life_days=HL).fit(
        pd.concat([dom, euro], ignore_index=True).sort_values("date"), verbose=False)
    print("\n锚点模型联赛平均净实力（全数据，E0 基准差值）：")
    means = {}
    for lg in S5:
        ts = [t for t in pools[lg] if t in m_all.attack]
        means[lg] = float(np.mean([m_all.attack[t] - m_all.defence[t] for t in ts]))
    base = means["E0"]
    for lg in S5:
        print(f"  {lg}: {means[lg] - base:+.3f}")


if __name__ == "__main__":
    main()
