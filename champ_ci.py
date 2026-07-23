#!/usr/bin/env python3
"""Title-probability parameter-uncertainty credible interval (precompute -> data/champ_ci.json).

夺冠概率的『参数不确定性』区间（precompute → data/champ_ci.json）。

方法（修正版，2026-06-14；2026-07-19 增补诊断/MCSE）：复用 bayes.py 的**分层贝叶斯
后验抽样**驱动模拟器。
  - 为什么靠谱：bayes 是同族加权双泊松（log_mu = intercept + atk − dfc + home_adv），
    带**分层收缩**——稀疏数据小国的强度被拉向总体均值，不会像 GLM 边际 SE 那样爆炸。
  - 后验 draws 保留联合相关结构；每套 draws 灌进模拟器跑 MC，得每队夺冠% 的分布
    → 5/50/95 分位 = 区间带。
  - 参数化对齐：DC.expected_goals = exp(intercept + home_adv + attack[h] + defence[a])，
    令 attack[t]=bayes.atk[t]、defence[t]=−bayes.dfc[t]、intercept/home_adv 取同套。

统计口径（诚实标注，2026-07-19）：
  1. **伪后验**：bayes 的时间/赛事加权似然 = power/pseudo-posterior，区间为『时间加权
     伪后验带』，频率学覆盖率未验证——UI 不得无条件称『严格 90% 可信区间』。
  2. **ρ 混用**：低分相关 ρ 沿用基线 DC 的点估（bayes 是独立双泊松，无 ρ 后验）。
     即：强度参数带不确定性、低分修正固定。ρ 对夺冠概率是二阶效应（只挪动低比分格
     内部的质量），此混用经测试锁定（test_core 断言 draw 模型 ρ== 基线 ρ）并在此声明。
  3. **参数不确定性 vs 蒙特卡洛噪声**：每套 draws 只跑有限次 MC，观测到的跨 draws
     方差 = 参数方差 + MC 二项噪声。输出对两者做方差分解：
       mc_sd   = mean_d sqrt(p_d(1-p_d)/draw_sims)   （单套 MC 噪声）
       param_sd= sqrt(max(Var_total − mean MC 方差, 0))（净参数不确定性）
     百分位带**含 MC 噪声（略偏宽=偏保守）**；draw_sims 可调（--draw-sims），
     mcse_mean = sqrt(Var_total / n_draws) 给出均值的蒙特卡洛标准误。
  4. **收敛门槛**：拒读未带 converged=True 的 bayes_draws.npz（收敛失败不发布新区间）。

先决条件：`python3 bayes.py`（生成 data/bayes_draws.npz）。然后 `python3 champ_ci.py`。
"""
from __future__ import annotations
import argparse
import copy
import json
import os

import numpy as np

import config
import data as datamod
from bayes import DRAWS_PATH

OUT_PATH = os.path.join(os.path.dirname(__file__), "data", "champ_ci.json")
DRAW_SIMS = 1000      # 每套后验的 MC 次数（500→1000，压 MC 噪声；见 --draw-sims）
MAX_DRAWS = 300       # 用多少套后验（npz 里有多少用多少，封顶）


def assert_draws_publishable(z) -> None:
    """收敛门槛：bayes_draws.npz 必须带 converged=True。旧格式/未达标一律拒绝。"""
    try:
        ok = bool(np.asarray(z["converged"]))
    except KeyError:
        raise SystemExit(
            f"{DRAWS_PATH} 缺收敛标记（旧格式或收敛未验证）。请先重跑 `python3 bayes.py`"
            "（新版会写入 R-hat/ESS/divergence 诊断；不达标不会导出）。")
    if not ok:
        raise SystemExit("bayes 后验抽样收敛不达标：拒绝发布新夺冠区间（旧缓存保留）。")


def _model_from_draw(base, teams, atk, dfc, intercept, home_adv):
    """用一套 bayes 后验抽样构造 DC 兼容模型（整套替换 intercept/home_adv/attack/defence）。
    注意：ρ 沿用 base 的 DC 点估（独立泊松后验无 ρ；口径见模块 docstring 第 2 条）。"""
    md = copy.copy(base)
    md.intercept = float(intercept)
    md.home_adv = float(home_adv)
    md.attack = dict(base.attack)
    md.defence = dict(base.defence)
    for i, t in enumerate(teams):
        if t in md.attack:                 # 仅覆盖两个模型都认识的队（含全部 48 强）
            md.attack[t] = float(atk[i])
            md.defence[t] = float(-dfc[i])   # DC defence = −bayes dfc
    md.avail_att, md.avail_def = {}, {}    # 纯引擎，无上下文层
    return md


def run(max_draws: int = MAX_DRAWS, draw_sims: int = DRAW_SIMS,
        out_path: str | None = OUT_PATH, verbose: bool = True) -> dict:
    """跑完整区间计算并（out_path 非 None 时）原子写 JSON。返回结果 dict。"""
    from predict import get_model
    from simulate import TournamentSimulator
    if not os.path.exists(DRAWS_PATH):
        raise SystemExit(f"缺 {DRAWS_PATH}，请先跑 `python3 bayes.py` 生成后验抽样。")
    z = np.load(DRAWS_PATH, allow_pickle=True)
    assert_draws_publishable(z)
    teams = list(z["teams"])
    A, D, IC, HA = z["atk"], z["dfc"], z["intercept"], z["home_adv"]
    n_draws = min(max_draws, A.shape[0])
    if verbose:
        print(f"[champ_ci] 用 {n_draws} 套 bayes 伪后验抽样 × {draw_sims} MC …")

    df = datamod.load_raw()
    base = get_model(use_cache=True, half_life=config.NATIONAL_HALF_LIFE, verbose=False)
    all_teams = None
    draws_champ: dict[str, list] = {}
    for d in range(n_draws):
        md = _model_from_draw(base, teams, A[d], D[d], IC[d], HA[d])
        rows = TournamentSimulator(md, df, sims=draw_sims).run()
        if all_teams is None:
            all_teams = [t for (t, *_r) in rows]
            draws_champ = {t: [] for t in all_teams}
        for (t, champ, *_r) in rows:
            draws_champ[t].append(champ)
        if verbose and (d + 1) % 25 == 0:
            print(f"  {d + 1}/{n_draws}")

    out = []
    for t in all_teams:
        arr = np.array(draws_champ[t])
        var_total = float(arr.var(ddof=1)) if len(arr) > 1 else 0.0
        mc_var = float(np.mean(arr * (1 - arr)) / draw_sims)     # 单套 MC 二项方差均值
        param_sd = float(np.sqrt(max(var_total - mc_var, 0.0)))
        out.append({"team": t,
                    "med": round(float(np.percentile(arr, 50)), 5),
                    "lo": round(float(np.percentile(arr, 5)), 5),
                    "hi": round(float(np.percentile(arr, 95)), 5),
                    "mean": round(float(arr.mean()), 5),
                    "mc_sd": round(float(np.sqrt(mc_var)), 5),
                    "param_sd": round(param_sd, 5),
                    "mcse_mean": round(float(np.sqrt(var_total / max(len(arr), 1))), 6)})
    out.sort(key=lambda x: x["med"], reverse=True)

    res = {"n_draws": n_draws, "draw_sims": draw_sims,
           "method": "bayes-hierarchical-pseudo-posterior",
           "interval_note": ("90% 区间带 = 时间加权伪后验 5–95 分位，含蒙特卡洛噪声"
                             "（mc_sd），覆盖率未经频率学验证；param_sd 为方差分解后的"
                             "净参数不确定性估计。"),
           "diagnostics": {"rhat_max": float(np.asarray(z["rhat_max"])) if "rhat_max" in z else None,
                           "ess_min": float(np.asarray(z["ess_min"])) if "ess_min" in z else None,
                           "divergences": int(np.asarray(z["divergences"])) if "divergences" in z else None},
           "rows": out}
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        tmp = out_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
        os.replace(tmp, out_path)
    return res


def main():
    ap = argparse.ArgumentParser(description="夺冠概率伪后验区间（bayes 抽样驱动）")
    ap.add_argument("--draw-sims", type=int, default=DRAW_SIMS,
                    help=f"每套后验的 MC 次数（默认 {DRAW_SIMS}；越大 MC 噪声越小）")
    ap.add_argument("--max-draws", type=int, default=MAX_DRAWS)
    args = ap.parse_args()
    res = run(max_draws=args.max_draws, draw_sims=args.draw_sims)
    out = res["rows"]
    print(f"\n[champ_ci] 写入 {OUT_PATH}。Top 10 夺冠中位 + 90% 区间带（伪后验+MC噪声）：")
    for x in out[:10]:
        print(f"  {x['team']:<16} 中位 {x['med']*100:5.1f}%  带 [{x['lo']*100:4.1f}% – {x['hi']*100:4.1f}%]"
              f"  参数σ {x['param_sd']*100:.1f}pp / MCσ {x['mc_sd']*100:.1f}pp")
    bad = [x['team'] for x in out[:16] if not (x['lo'] <= x['med'] <= x['hi'])]
    print(f"\n  中位落在带内: {'✅ 全部' if not bad else '❌ '+str(bad)}")


if __name__ == "__main__":
    main()
