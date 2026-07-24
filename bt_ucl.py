"""E4a 前置回测：欧战两回合 tie 晋级概率 hindcast + 非五大分层 + ET 污染敏感性。

任务 1（tie hindcast，docs/backtest.md 第八节）：
  数据 = eurodata（五季 1552 场、195 对 tie；agg_note 含晋级方原文）。
  as_of 时序防泄漏：每季 as_of=季初 9 月 1 日（同 bt_crossleague 口径——训练帧
    不含该季任何场次，非五大队参数只来自此前赛季的欧战账本）。
  模型 = 锚点合训 Dixon-Coles（dom 五大联赛帧 + as_of 前欧战账本，hl=365；
    拟合口径复制自 bt_crossleague.main，帧构建直接 import 复用）。
  tie 晋级概率：两回合各 90 分钟比分分布（score_matrix，各回合主场 neutral=False）
    → 净胜卷积合计 → 合计平局走加时近似（xG×ET_SCALE 独立泊松 + 点球 PEN_PRIOR
    先验，常数与口径同 simulate.advancement_paths；ET 主场=次回合主队）。
    显式不用客场进球规则（2021 已废除，本账本全部赛季适用）。
  评估：
    ① tie 晋级概率 vs 实际晋级方（agg_note 解析，pens 场次亦有晋级方原文）：
       Brier + 分箱可靠性表 + bootstrap CI；基线 = 50/50（Brier .25）与
       「仅用合计预期净胜」朴素基线（μ=两回合 xG 合计差、σ²=λ 合计的正态 CDF，
       不用逐格分布、不建模加时——隔离『全分布+ET 建模』的增量）。
    ② 单场层面（leg==0 非决赛、纯 90 分钟）分层 RPS：
       双方均五大（E3 已证跨联赛子集；此处含同联赛相遇）/ 至少一方非五大。
       基线 = 均匀 (⅓,⅓,⅓) 与训练窗欧战主平客频率常数预测；配对 bootstrap。
    ③ 严格 as_of 下参数不可得（队不在训练帧）→ 跳过并计数，报告跳过率。

任务 2（--et-sens 段）：锚点训练帧的欧战 KO 行是 ESPN 终局比分（含加时）——
  训练污染敏感性：变体 = 训练帧剔除全部 KO 行（leg∈{1,2} 及决赛），
  在 bt_crossleague 同一评测集（跨联赛五大互相交锋）上对比全帧锚点。

用法：/opt/anaconda3/bin/python3 bt_ucl.py          # 全部（任务 1 + 任务 2）
"""
from __future__ import annotations
import re
import sys
import warnings

import numpy as np
import pandas as pd
from scipy.stats import norm, poisson

import bt_crossleague as btc                  # 复用：帧构建/池/RPS（口径同 E3）
import eurodata
from model import DixonColesModel, MAX_GOALS

warnings.filterwarnings("ignore")

HL = btc.HL                                   # 365，同 E3
ET_SCALE = 30.0 / 90.0                        # 口径同 simulate.ET_SCALE
PEN_PRIOR = 0.5                               # 口径同 simulate.PEN_PRIOR
TIE_SEASONS = [2021, 2022, 2023, 2024, 2025]  # tie hindcast 全五季
EVAL_SEASONS = btc.SEASONS_EVAL               # [2022..2025]，单场分层与 ET 敏感性
BOOT_N, SEED = 4000, 42


# ---------- 模型拟合（帧口径复制自 bt_crossleague.main） ----------
def fit_model(dom, euro_train, cut):
    frame = dom if euro_train is None else (
        pd.concat([dom, euro_train], ignore_index=True).sort_values("date"))
    return DixonColesModel(half_life_days=HL).fit(frame, verbose=False, as_of=cut)


def boot_ci(x, seed=SEED, n=BOOT_N):
    x = np.asarray(x, dtype=float)
    rng = np.random.default_rng(seed)
    means = [rng.choice(x, len(x), replace=True).mean() for _ in range(n)]
    lo, hi = np.percentile(means, [2.5, 97.5])
    return float(lo), float(hi)


# ---------- tie 晋级概率（两回合卷积 + ET 近似） ----------
def _margin_pmf(M, flip=False):
    """比分矩阵 → 净胜球 pmf（长度 2*MAX_GOALS+1，索引 d+MAX_GOALS）。flip=转客视角。"""
    pmf = np.zeros(2 * MAX_GOALS + 1)
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            d = (j - i) if flip else (i - j)
            pmf[d + MAX_GOALS] += M[i, j]
    return pmf


def _et_wdl(lam_h, lam_a):
    """加时 30 分钟 (主胜, 平, 客胜)：xG×ET_SCALE 独立泊松（同 simulate._et_wdl）。"""
    k = np.arange(7)
    fa = poisson.pmf(k, lam_h * ET_SCALE)
    fb = poisson.pmf(k, lam_a * ET_SCALE)
    M = np.outer(fa, fb)
    M /= M.sum()
    i, j = np.meshgrid(k, k, indexing="ij")
    return float(M[i > j].sum()), float(M[i == j].sum()), float(M[i < j].sum())


def tie_advance_prob(m, home1, away1):
    """A=首回合主队 晋级概率 + 朴素基线。次回合主队=away1（ET 主场=次回合主队）。"""
    _, _, l1h, l1a, M1 = m.score_matrix(home1, away1, neutral=False)
    _, _, l2h, l2a, M2 = m.score_matrix(away1, home1, neutral=False)   # B 主场
    d1 = _margin_pmf(M1)                      # A 视角（A 是 leg1 主队）
    d2 = _margin_pmf(M2, flip=True)           # A 视角（A 是 leg2 客队）
    agg = np.convolve(d1, d2)                 # 合计净胜（A−B），索引 d+2*MAX_GOALS
    mid = 2 * MAX_GOALS
    p_win, p_tie = float(agg[mid + 1:].sum()), float(agg[mid])
    et_b, et_d, et_a = _et_wdl(l2h, l2a)      # 次回合主队 B 的主场 ET
    p_adv = p_win + p_tie * (et_a + et_d * PEN_PRIOR)
    # 朴素基线：仅用合计预期净胜（正态近似，不用逐格分布、不建模 ET）
    mu = (l1h + l2a) - (l1a + l2h)
    sd = np.sqrt(l1h + l1a + l2h + l2a)
    p_naive = float(norm.cdf(mu / sd))
    return p_adv, p_naive


# ---------- agg_note 晋级方解析 ----------
def parse_winner(note, team_a, team_b):
    """leg2 agg_note → 晋级方（已映射队名）；解析不出返回 None。"""
    if not isinstance(note, str) or " advance" not in note:
        return None
    raw = note.split(" advance")[0]           # "2nd Leg - [Tied on aggregate - ]X"
    name = raw.split(" - ")[-1].strip()
    name = eurodata.ESPN_FIX.get(name, name)
    if name == team_a:
        return team_a
    if name == team_b:
        return team_b
    return None


# ---------- 任务 1：tie hindcast + 单场分层 ----------
def run_hindcast():
    dom = btc._domestic_frame()
    euro_full = eurodata.load()
    euro_train_all = euro_full.drop(
        columns=["season", "leg", "agg_note", "tie_id"], errors="ignore")
    pools = btc._pools()
    team2lg = {t: lg for lg, ts in pools.items() for t in ts}

    ties = []          # dict: season, stratum, p, p_naive, y(A 晋级=1)
    skip = {"no_param": 0, "no_winner": 0, "bad_pair": 0}
    n_tie_total = 0
    sm = []            # 单场: season, stratum, rps_m1, rps_m0(或 None), rps_uni, rps_freq
    sm_skip = {"both5": 0, "nonbig5": 0}

    print("=" * 72)
    print(f"任务 1：两回合 tie 晋级概率 hindcast（hl={HL:.0f}，as_of=每季 9/1）")
    print("=" * 72)
    for sy in TIE_SEASONS:
        cut = pd.Timestamp(f"{sy}-09-01")
        m1 = fit_model(dom, euro_train_all, cut)
        m0 = fit_model(dom, None, cut) if sy in EVAL_SEASONS else None

        # --- tie 晋级 ---
        season_ties = euro_full[(euro_full.season == sy) & euro_full.tie_id.notna()]
        n_season = 0
        for tid, g in season_ties.groupby("tie_id"):
            n_tie_total += 1
            g = g.sort_values("date")
            if len(g) != 2 or list(g.leg) != [1, 2]:
                skip["bad_pair"] += 1
                continue
            leg1, leg2 = g.iloc[0], g.iloc[1]
            A, B = leg1.home_team, leg1.away_team
            if leg2.home_team != B or leg2.away_team != A:
                skip["bad_pair"] += 1
                continue
            if any(t not in m1.attack for t in (A, B)):
                skip["no_param"] += 1
                continue
            win = parse_winner(leg2.agg_note, A, B)
            if win is None:
                # 兜底：ESPN 终局比分（含 ET）合计定胜负；仍平（=点球）则放弃
                da = (leg1.home_score + leg2.away_score) - (leg1.away_score + leg2.home_score)
                if da == 0:
                    skip["no_winner"] += 1
                    continue
                win = A if da > 0 else B
            p, p_nv = tie_advance_prob(m1, A, B)
            strat = "both5" if (A in team2lg and B in team2lg) else "nonbig5"
            ties.append({"season": sy, "stratum": strat, "p": p, "p_naive": p_nv,
                         "y": int(win == A)})
            n_season += 1
        print(f"  {sy}-{(sy + 1) % 100:02d}: 可评 tie {n_season}")

        # --- 单场分层（leg0 非决赛，纯 90 分钟）---
        if m0 is None:
            continue
        test = euro_full[(euro_full.season == sy) & (euro_full.leg == 0)
                         & (~euro_full.neutral)]
        # 训练窗欧战频率基线（as_of 前 leg0 场次的主/平/客频率；空则均匀）
        hist = euro_full[(euro_full.date < cut) & (euro_full.leg == 0)]
        if len(hist):
            f_h = float((hist.home_score > hist.away_score).mean())
            f_d = float((hist.home_score == hist.away_score).mean())
            p_freq = [f_h, f_d, 1.0 - f_h - f_d]
        else:
            p_freq = [1 / 3] * 3
        for r in test.itertuples():
            strat = ("both5" if (r.home_team in team2lg and r.away_team in team2lg)
                     else "nonbig5")
            if r.home_team not in m1.attack or r.away_team not in m1.attack:
                sm_skip[strat] += 1
                continue
            out = 0 if r.home_score > r.away_score else (
                1 if r.home_score == r.away_score else 2)
            pr = m1.predict(r.home_team, r.away_team, neutral=False)
            p1 = [pr["p_home"], pr["p_draw"], pr["p_away"]]
            row = {"season": sy, "stratum": strat,
                   "rps_m1": btc.rps(p1, out),
                   "rps_uni": btc.rps([1 / 3] * 3, out),
                   "rps_freq": btc.rps(p_freq, out),
                   "hit_m1": int(int(np.argmax(p1)) == out), "rps_m0": None}
            if strat == "both5" and r.home_team in m0.attack and r.away_team in m0.attack:
                pr0 = m0.predict(r.home_team, r.away_team, neutral=False)
                row["rps_m0"] = btc.rps([pr0["p_home"], pr0["p_draw"], pr0["p_away"]], out)
            sm.append(row)

    _report_ties(pd.DataFrame(ties), skip, n_tie_total)
    _report_single(pd.DataFrame(sm), sm_skip)


def _brier_block(df, label):
    y, p, pn = df.y.values, df.p.values, df.p_naive.values
    b = (p - y) ** 2
    bn = (pn - y) ** 2
    b50 = (0.5 - y) ** 2                       # 恒 0.25
    lo, hi = boot_ci(b)
    dlo, dhi = boot_ci(b - b50)                # vs 50/50（配对）
    nlo, nhi = boot_ci(b - bn)                 # vs 朴素（配对）
    print(f"\n  [{label}] n={len(df)}")
    print(f"    Brier 模型 {b.mean():.4f}  CI[{lo:.4f},{hi:.4f}]"
          f"   50/50 基线 0.2500   朴素净胜基线 {bn.mean():.4f}")
    print(f"    Δ vs 50/50 = {(b - b50).mean():+.4f}  CI[{dlo:+.4f},{dhi:+.4f}]"
          f"  {'显著优于' if dhi < 0 else '不显著（CI 含 0）'}")
    print(f"    Δ vs 朴素  = {(b - bn).mean():+.4f}  CI[{nlo:+.4f},{nhi:+.4f}]"
          f"  {'显著优于' if nhi < 0 else '不显著（CI 含 0）'}")


def _report_ties(df, skip, n_total):
    print(f"\n—— tie 晋级概率评估（① Brier + 可靠性）——")
    n_eval = len(df)
    n_skip = sum(skip.values())
    print(f"  总 tie {n_total}，可评 {n_eval}，跳过 {n_skip}"
          f"（参数不可得 {skip['no_param']} / 晋级方不可知 {skip['no_winner']}"
          f" / 配对异常 {skip['bad_pair']}），跳过率 {n_skip / n_total:.1%}")
    _brier_block(df, "全部可评 tie")
    for s, lbl in (("both5", "双方均五大"), ("nonbig5", "至少一方非五大")):
        sub = df[df.stratum == s]
        if len(sub):
            _brier_block(sub, lbl)
    # 可靠性分箱（对首回合主队晋级概率 p）
    print("\n  可靠性（分箱校准表，p=首回合主队晋级概率）：")
    print("    箱          n    平均预测   实际频率")
    for a, b in [(0, .2), (.2, .4), (.4, .6), (.6, .8), (.8, 1.0001)]:
        sub = df[(df.p >= a) & (df.p < b)]
        if len(sub):
            print(f"    [{a:.1f},{min(b, 1.0):.1f})  {len(sub):4d}     {sub.p.mean():.3f}"
                  f"      {sub.y.mean():.3f}")
        else:
            print(f"    [{a:.1f},{min(b, 1.0):.1f})     0        —          —")


def _report_single(df, sm_skip):
    print(f"\n—— 单场层面分层 RPS（② leg0 非决赛，{EVAL_SEASONS[0]} 起四季）——")
    for s, lbl in (("both5", "双方均五大"), ("nonbig5", "至少一方非五大")):
        sub = df[df.stratum == s]
        n_sk = sm_skip[s]
        if not len(sub):
            print(f"  [{lbl}] 无可评样本（跳过 {n_sk}）")
            continue
        r1 = sub.rps_m1.values
        lo, hi = boot_ci(r1)
        dfr = r1 - sub.rps_freq.values
        flo, fhi = boot_ci(dfr)
        print(f"  [{lbl}] n={len(sub)}（跳过 {n_sk}，跳过率 "
              f"{n_sk / (n_sk + len(sub)):.1%}）")
        print(f"    RPS 锚点 {r1.mean():.4f} CI[{lo:.4f},{hi:.4f}]"
              f"  命中 {sub.hit_m1.mean():.1%}"
              f"  | 均匀基线 {sub.rps_uni.mean():.4f}  频率基线 {sub.rps_freq.mean():.4f}")
        print(f"    Δ vs 频率基线 = {dfr.mean():+.4f} CI[{flo:+.4f},{fhi:+.4f}]"
              f"  {'显著优于' if fhi < 0 else '不显著（CI 含 0）'}")
        if s == "both5":
            has0 = sub[sub.rps_m0.notna()]
            if len(has0):
                d0 = has0.rps_m1.values - has0.rps_m0.values.astype(float)
                zlo, zhi = boot_ci(d0)
                print(f"    （对照）锚点 vs 独立联赛裸并 m0：n={len(has0)} "
                      f"Δ={d0.mean():+.4f} CI[{zlo:+.4f},{zhi:+.4f}]")


# ---------- 任务 2：ET 污染敏感性 ----------
def run_et_sensitivity():
    print("\n" + "=" * 72)
    print("任务 2：ET 污染敏感性——训练帧剔除欧战 KO 行（含加时终局比分）")
    print("=" * 72)
    dom = btc._domestic_frame()
    euro_full = eurodata.load()
    cols = ["season", "leg", "agg_note", "tie_id"]
    euro_all = euro_full.drop(columns=cols, errors="ignore")
    euro_grp = euro_full[(euro_full.leg == 0) & (~euro_full.neutral)].drop(
        columns=cols, errors="ignore")
    n_ko = len(euro_all) - len(euro_grp)
    print(f"  欧战训练行：全帧 {len(euro_all)} → 剔除 KO/决赛后 {len(euro_grp)}"
          f"（剔除 {n_ko} 行）")
    pools = btc._pools()
    team2lg = {t: lg for lg, ts in pools.items() for t in ts}

    acc = {"full": [], "grp": [], "hit_full": [], "hit_grp": []}
    for sy in EVAL_SEASONS:
        cut = pd.Timestamp(f"{sy}-09-01")
        m_full = fit_model(dom, euro_all, cut)
        m_grp = fit_model(dom, euro_grp, cut)
        test = euro_full[(euro_full.season == sy) & (euro_full.leg == 0)
                         & (~euro_full.neutral)
                         & euro_full.home_team.isin(team2lg)
                         & euro_full.away_team.isin(team2lg)]
        cross = test[[team2lg[h] != team2lg[a]
                      for h, a in zip(test.home_team, test.away_team)]]
        n = 0
        srow = {k: [] for k in acc}
        for r in cross.itertuples():
            if any(t not in m.attack for m in (m_full, m_grp)
                   for t in (r.home_team, r.away_team)):
                continue
            out = 0 if r.home_score > r.away_score else (
                1 if r.home_score == r.away_score else 2)
            for key, m in (("full", m_full), ("grp", m_grp)):
                pr = m.predict(r.home_team, r.away_team, neutral=False)
                p = [pr["p_home"], pr["p_draw"], pr["p_away"]]
                srow[key].append(btc.rps(p, out))
                srow["hit_" + key].append(int(int(np.argmax(p)) == out))
            n += 1
        for k in acc:
            acc[k].extend(srow[k])
        print(f"  {sy}-{(sy + 1) % 100:02d}: n={n:3d}  RPS 全帧 "
              f"{np.mean(srow['full']):.4f} vs 剔 KO {np.mean(srow['grp']):.4f}"
              f"  (Δ={np.mean(srow['grp']) - np.mean(srow['full']):+.4f})")
    d = np.array(acc["grp"]) - np.array(acc["full"])
    lo, hi = boot_ci(d)
    print(f"\n  合并 n={len(d)}: RPS 全帧锚点 {np.mean(acc['full']):.4f}"
          f" vs 剔 KO 锚点 {np.mean(acc['grp']):.4f}")
    print(f"  Δ(剔−全)={d.mean():+.4f}  bootstrap 95% CI [{lo:+.4f},{hi:+.4f}]"
          f"  {'剔除显著更优' if hi < 0 else ('剔除显著更差' if lo > 0 else '不显著（CI 含 0）')}")
    print(f"  命中率 全帧 {np.mean(acc['hit_full']):.1%} vs 剔 KO {np.mean(acc['hit_grp']):.1%}")


if __name__ == "__main__":
    args = set(sys.argv[1:])
    if not args or "--hindcast" in args or "--all" in args:
        run_hindcast()
    if not args or "--et-sens" in args or "--all" in args:
        run_et_sensitivity()
