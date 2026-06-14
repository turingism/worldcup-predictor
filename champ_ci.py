#!/usr/bin/env python3
"""Title-probability parameter-uncertainty credible interval (precompute -> data/champ_ci.json).

夺冠概率的『参数不确定性』可信区间（precompute → data/champ_ci.json）。

方法（修正版，2026-06-14）：复用 bayes.py 的**分层贝叶斯后验抽样**驱动模拟器。
  - 为什么靠谱：bayes 是同族加权双泊松（log_mu = intercept + atk − dfc + home_adv），
    带**分层收缩**——稀疏数据小国的强度被拉向总体均值，不会像 GLM 边际 SE 那样爆炸。
    这正是早先 naive 方法（独立按每队 GLM 边际 SE 扰动）失败的根因所在。
  - 后验 draws 本身保留了联合相关结构；把每套 draws 灌进模拟器跑一遍 MC，
    得每队夺冠%的分布 → 5/50/95 分位 = 可信带。
  - 参数化对齐：DC.expected_goals = exp(intercept + home_adv + attack[h] + defence[a])，
    令 attack[t]=bayes.atk[t]、defence[t]=−bayes.dfc[t]、intercept/home_adv 取 bayes 同套，
    四者**整套替换**即逐位复现 bayes 的 log_mu（中心化差异被整套替换吸收）。

诚实定位：这是**贝叶斯后验驱动**的夺冠概率 + 区间，与看板的 DC 点估**同源不同口径**
（分层收缩更保守、区间普遍较宽且重叠——这恰恰是诚实：很多队的夺冠次序本就不确定）。
预测/模拟主引擎仍是 DC，本视图为补充（与 bayes.py「补充视图」同定位）。

先决条件：`python3 bayes.py`（生成 data/bayes_draws.npz）。然后 `python3 champ_ci.py`。
"""
from __future__ import annotations
import copy
import json
import os

import numpy as np

import data as datamod
from bayes import DRAWS_PATH

OUT_PATH = os.path.join(os.path.dirname(__file__), "data", "champ_ci.json")
DRAW_SIMS = 500       # 每套后验的 MC 次数
MAX_DRAWS = 300       # 用多少套后验（npz 里有多少用多少，封顶）


def _model_from_draw(base, teams, atk, dfc, intercept, home_adv):
    """用一套 bayes 后验抽样构造 DC 兼容模型（整套替换 intercept/home_adv/attack/defence）。"""
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


def main():
    from predict import get_model
    from simulate import TournamentSimulator
    if not os.path.exists(DRAWS_PATH):
        raise SystemExit(f"缺 {DRAWS_PATH}，请先跑 `python3 bayes.py` 生成后验抽样。")
    z = np.load(DRAWS_PATH, allow_pickle=True)
    teams = list(z["teams"])
    A, D, IC, HA = z["atk"], z["dfc"], z["intercept"], z["home_adv"]
    n_draws = min(MAX_DRAWS, A.shape[0])
    print(f"[champ_ci] 用 {n_draws} 套 bayes 后验抽样 × {DRAW_SIMS} MC（分层收缩，稳定）…")

    df = datamod.load_raw()
    base = get_model(use_cache=True, half_life=730.0, verbose=False)
    all_teams = None
    draws_champ: dict[str, list] = {}
    for d in range(n_draws):
        md = _model_from_draw(base, teams, A[d], D[d], IC[d], HA[d])
        rows = TournamentSimulator(md, df, sims=DRAW_SIMS).run()
        if all_teams is None:
            all_teams = [t for (t, *_r) in rows]
            draws_champ = {t: [] for t in all_teams}
        for (t, champ, *_r) in rows:
            draws_champ[t].append(champ)
        if (d + 1) % 25 == 0:
            print(f"  {d + 1}/{n_draws}")

    out = []
    for t in all_teams:
        arr = np.array(draws_champ[t])
        out.append({"team": t,
                    "med": round(float(np.percentile(arr, 50)), 5),
                    "lo": round(float(np.percentile(arr, 5)), 5),
                    "hi": round(float(np.percentile(arr, 95)), 5),
                    "mean": round(float(arr.mean()), 5)})
    out.sort(key=lambda x: x["med"], reverse=True)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"n_draws": n_draws, "draw_sims": DRAW_SIMS,
                   "method": "bayes-hierarchical-posterior", "rows": out}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)

    print(f"\n[champ_ci] 写入 {OUT_PATH}。Top 10 夺冠中位 + 90% 可信带：")
    for x in out[:10]:
        print(f"  {x['team']:<16} 中位 {x['med']*100:5.1f}%  90%带 [{x['lo']*100:4.1f}% – {x['hi']*100:4.1f}%]")
    # 自检：中位是否落在带内（百分位法必然，但打印以确认非退化）
    bad = [x['team'] for x in out[:16] if not (x['lo'] <= x['med'] <= x['hi'])]
    print(f"\n  中位落在带内: {'✅ 全部' if not bad else '❌ '+str(bad)}")


if __name__ == "__main__":
    main()
