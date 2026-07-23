#!/usr/bin/env python3
"""Hierarchical Bayesian double-Poisson model (PyMC): team ratings with credible intervals.

贝叶斯分层双泊松模型（PyMC）—— 给球队评级加可信区间。

定位：这是 DC 预测引擎的**补充视图**，不替换它。
  - DC 模型（model.py）：加权 Poisson GLM 的点估计，经回测调优，仍是预测/模拟的引擎。
  - 本模型：同样的加权双泊松似然，但对 attack/defence 用分层正态先验（部分汇合 partial
    pooling），输出每队净实力的**后验分布**，从而得到 94% 可信区间。
    由于分层收缩 + 时间衰减后有效样本有限，估计比 DC 点估计更保守（更靠近均值、区间更宽），
    这是对“我们到底多确定”的诚实量化。

参数化：log E[goals] = intercept + atk[攻方] - dfc[守方] + home_adv * is_home
  - atk 高 = 进攻强；dfc 高 = 防守强（压制对手进球）
  - 球队净实力 net = atk + dfc（越高越强）
  - 采用非中心化参数化（non-centered）改善采样几何。
  - 时间衰减/赛事权重通过加权对数似然（pm.Potential）施加，与 DC 完全一致。

统计口径（诚实标注）：
  - 加权对数似然（权重∈(0,1]）意味着这是 **power/pseudo-posterior**（每条观测的
    似然被升到 w 次幂），不是严格贝叶斯后验——区间应解读为『时间加权伪后验的
    可信带』，其频率学覆盖率未经验证。meta.posterior_type 记录此口径。
  - 收敛诊断（R-hat / ESS / divergences）随拟合计算并写入 meta；
    **收敛不达标（convergence_ok=False）时不发布新评级/后验抽样**（main 退出码 2，
    旧缓存保持不动）。

用法：
  python3 bayes.py                 # 拟合并缓存 data/bayes_ratings.json
  python3 bayes.py --draws 1500    # 更多采样
缓存生成后，网页 /api/ratings 直接读 JSON（app 启动不重训，太慢且应确定性）。
"""
from __future__ import annotations
import config
import argparse
import json
import os
import sys
import time

import numpy as np

import data as datamod

sys.setrecursionlimit(100000)   # Potential 大图克隆需要更高递归上限

RATINGS_PATH = os.path.join(os.path.dirname(__file__), "data", "bayes_ratings.json")
DRAWS_PATH = os.path.join(os.path.dirname(__file__), "data", "bayes_draws.npz")
N_EXPORT_DRAWS = 300      # 导出的后验抽样套数（供 champ_ci 夺冠区间用，分层收缩→稳定）

# 收敛门槛（不达标不发布）：R-hat ≤ 1.05、min bulk-ESS ≥ 200、零 divergence。
RHAT_MAX = 1.05
ESS_MIN = 200.0
MAX_DIVERGENCES = 0


def convergence_ok(diag: dict) -> bool:
    """收敛判定（可测试的纯函数）。diag 需含 rhat_max / ess_min / divergences。"""
    return (diag.get("rhat_max", float("inf")) <= RHAT_MAX
            and diag.get("ess_min", 0.0) >= ESS_MIN
            and diag.get("divergences", 10 ** 9) <= MAX_DIVERGENCES)


def _diagnostics(idata) -> dict:
    """R-hat / bulk-ESS / divergences（对全部关键参数取最差值）。"""
    import arviz as az
    var_names = ["intercept", "home_adv", "sigma_a", "sigma_d", "atk", "dfc"]
    rh = az.rhat(idata, var_names=var_names)
    es = az.ess(idata, var_names=var_names)
    rhat_max = float(max(np.nanmax(np.asarray(rh[v])) for v in rh.data_vars))
    ess_min = float(min(np.nanmin(np.asarray(es[v])) for v in es.data_vars))
    ss = getattr(idata, "sample_stats", None)
    div = int(np.asarray(ss["diverging"]).sum()) if ss is not None and "diverging" in ss else 0
    return {"rhat_max": round(rhat_max, 4), "ess_min": round(ess_min, 1),
            "divergences": div}


def fit(half_life: float = config.NATIONAL_HALF_LIFE, draws: int = 1000, tune: int = 1000,
        chains: int = 2, seed: int = 42, verbose: bool = True,
        progressbar: bool = False) -> dict:
    """拟合分层贝叶斯模型，返回 {team: {net, net_lo, net_hi, atk, dfc}} 及元信息。"""
    import pymc as pm
    import pytensor.tensor as pt

    long = datamod.build_training_frame(df=datamod.load_raw(), half_life_days=half_life)
    teams = list(long["attack"].cat.categories)
    n = len(teams)
    ai = long["attack"].cat.codes.to_numpy()
    di = long["defence"].cat.codes.to_numpy()
    g = long["goals"].to_numpy().astype("float64")
    h = long["home"].to_numpy().astype("float64")
    w = long["weight"].to_numpy().astype("float64")
    if verbose:
        print(f"[bayes] 长表 {len(long)} 行, {n} 队, 有效权重和 {w.sum():.0f}")

    t0 = time.time()
    with pm.Model() as model:
        intercept = pm.Normal("intercept", 0.0, 2.0)
        home_adv = pm.Normal("home_adv", 0.0, 0.5)
        sigma_a = pm.HalfNormal("sigma_a", 2.0)
        sigma_d = pm.HalfNormal("sigma_d", 2.0)
        # 非中心化：z ~ N(0,1)，真实系数 = z * sigma
        z_a = pm.Normal("z_a", 0.0, 1.0, shape=n)
        z_d = pm.Normal("z_d", 0.0, 1.0, shape=n)
        atk = pm.Deterministic("atk", z_a * sigma_a)
        dfc = pm.Deterministic("dfc", z_d * sigma_d)
        log_mu = intercept + atk[ai] - dfc[di] + home_adv * h
        # 加权泊松对数似然（分数权重 -> 用 Potential）
        pm.Potential("wll", (w * (g * log_mu - pt.exp(log_mu) - pt.gammaln(g + 1.0))).sum())
        idata = pm.sample(draws=draws, tune=tune, chains=chains, cores=chains,
                          random_seed=seed, target_accept=0.9, progressbar=progressbar,
                          compute_convergence_checks=False)
    diag = _diagnostics(idata)
    converged = convergence_ok(diag)
    if verbose:
        print(f"[bayes] 采样耗时 {time.time() - t0:.1f}s；收敛诊断 "
              f"R-hat_max={diag['rhat_max']} ESS_min={diag['ess_min']} "
              f"divergences={diag['divergences']} → {'✅ 达标' if converged else '❌ 不达标'}")

    A = idata.posterior["atk"].values.reshape(-1, n)
    D = idata.posterior["dfc"].values.reshape(-1, n)
    icpt = idata.posterior["intercept"].values.reshape(-1)
    hadv = idata.posterior["home_adv"].values.reshape(-1)
    net = A + D                                   # 净实力（攻+守）
    mean = net.mean(0)
    lo = np.percentile(net, 3, 0)                 # 94% 可信区间
    hi = np.percentile(net, 97, 0)
    out = {}
    for i, t in enumerate(teams):
        out[t] = {"net": round(float(mean[i]), 3),
                  "net_lo": round(float(lo[i]), 3),
                  "net_hi": round(float(hi[i]), 3),
                  "atk": round(float(A[:, i].mean()), 3),
                  "dfc": round(float(D[:, i].mean()), 3)}

    # 导出后验抽样（供 champ_ci 夺冠概率区间用）：均匀子采样 N_EXPORT_DRAWS 套，
    # 含每队 atk/dfc + 全局 intercept/home_adv。分层收缩已驯服稀疏队 → 注入模拟器稳定。
    # 收敛不达标时**不导出**（champ_ci 也会拒读未达标 npz）——旧缓存原样保留。
    if converged:
        tot = A.shape[0]
        sel = np.linspace(0, tot - 1, min(N_EXPORT_DRAWS, tot)).astype(int)
        np.savez_compressed(DRAWS_PATH, teams=np.array(teams, dtype=object),
                            atk=A[sel].astype(np.float32), dfc=D[sel].astype(np.float32),
                            intercept=icpt[sel].astype(np.float32),
                            home_adv=hadv[sel].astype(np.float32),
                            half_life=half_life, converged=True,
                            rhat_max=diag["rhat_max"], ess_min=diag["ess_min"],
                            divergences=diag["divergences"])
        if verbose:
            print(f"[bayes] 导出 {len(sel)} 套后验抽样 → {DRAWS_PATH}")
    elif verbose:
        print("[bayes] ⚠ 收敛不达标：不导出后验抽样，不更新夺冠区间（旧缓存保留）")
    return {"ratings": out,
            "meta": {"half_life": half_life, "draws": draws, "tune": tune,
                     "chains": chains, "n_teams": n, "weight_sum": round(float(w.sum()), 1),
                     "posterior_type": "power/pseudo-posterior (time+competition weighted likelihood)",
                     "diagnostics": diag, "converged": bool(converged)}}


def main():
    ap = argparse.ArgumentParser(description="贝叶斯分层评级（PyMC）—— 拟合并缓存")
    ap.add_argument("--draws", type=int, default=1000)
    ap.add_argument("--tune", type=int, default=1000)
    ap.add_argument("--half-life", type=float, default=config.NATIONAL_HALF_LIFE)
    ap.add_argument("--progress", action="store_true",
                    help="显示 PyMC 采样进度条；默认关闭，避免无 matplotlib 环境崩溃")
    args = ap.parse_args()

    res = fit(half_life=args.half_life, draws=args.draws, tune=args.tune,
              progressbar=args.progress)
    if not res["meta"]["converged"]:
        print(f"[bayes] ❌ 收敛不达标 {res['meta']['diagnostics']}：不发布新评级"
              "（旧 bayes_ratings.json / bayes_draws.npz 保持不动）")
        sys.exit(2)
    tmp = RATINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False)
    os.replace(tmp, RATINGS_PATH)
    print(f"[bayes] 已写入 {RATINGS_PATH}（{res['meta']['n_teams']} 队）")

    # 打印 Top 15 健全性检查
    rows = sorted(res["ratings"].items(), key=lambda kv: -kv[1]["net"])[:15]
    print("\n  贝叶斯净实力 Top 15（94% 可信区间）")
    print("  " + "─" * 48)
    for i, (t, r) in enumerate(rows, 1):
        print(f"  {i:>2}. {t:<18} {r['net']:+.2f}  [{r['net_lo']:+.2f}, {r['net_hi']:+.2f}]")


if __name__ == "__main__":
    main()
