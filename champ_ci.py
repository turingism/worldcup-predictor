#!/usr/bin/env python3
"""夺冠概率的『参数不确定性』可信区间（precompute → data/champ_ci.json）。

⚠️ 实验性 / 方法未通过验证，未接入 UI（2026-06-14）。
   独立按每队边际标准误扰动系数 → 统计上无效：忽略系数相关性、且被稀疏数据小国的
   巨大边际 SE 主导，每套抽样把"谁强"彻底重排，导致 90% 带不包含点估（如阿根廷点估
   19.3% 却落在带 [0–2.1%] 之外）。正确做法需 **全协方差 MVN 抽样**（glm.cov_params）
   或把 bayes.py 的同模型后验样本注入 DC 模拟器——留待专门一轮谨慎实现。
   （本文件保留作为脚手架；勿据其输出做任何展示。model.py 的 τ 截零护栏已合入并验证恒等。）


现状：夺冠榜只有点估（一次 MC 的频率）。点估隐藏了**评级本身的估计误差**——
England 11.0% 与 Portugal 6.8% 的差距，可能小于评级噪声。

做法（参数不确定性传播，非 MC 抽样误差）：
  1) 重新拟合 Poisson GLM 拿到每个 attack/defence 系数的标准误 (glm.bse)；
  2) 抽 N 套系数（各系数独立 Normal(coef, se)——忽略相关性，略偏保守）；
  3) 每套构造一个扰动模型，跑一遍（小样本）蒙特卡洛得夺冠%；
  4) 对每队的 N 个夺冠% 取 5/50/95 分位 → 可信带。

诚实定位：这是 DC 引擎的**不确定性补充视图**（与 bayes.py 同定位），预测/模拟仍由点估
引擎驱动，不改 backtest 口径。独立 Normal 忽略系数相关性会略放大区间（保守，不会假装更确定）。
与 bayes.py 一样手动运行生成缓存：`python3 champ_ci.py`。
"""
from __future__ import annotations
import copy
import json
import os

import numpy as np

import data as datamod
from model import DixonColesModel
from simulate import TournamentSimulator

OUT_PATH = os.path.join(os.path.dirname(__file__), "data", "champ_ci.json")
N_DRAWS = 24          # 后验抽样套数
DRAW_SIMS = 500       # 每套的 MC 次数（点估用更高，区间用小样本够）
BASE_SIMS = 4000
SEED = 20260614


def _perturbed(model, bse, rng, clamp=2.0):
    """复制模型，对每队 attack/defence 系数加 Normal(0, se) 扰动（独立采样，截断 ±clamp·se
    防极端 λ 把 DC 低分格修正推成负概率）。引擎不改，扰动只发生在副本上。"""
    md = copy.copy(model)
    md.attack = dict(model.attack)
    md.defence = dict(model.defence)
    for t in model.teams:
        sa = float(bse.get(f"C(attack)[T.{t}]", 0.0))
        sd = float(bse.get(f"C(defence)[T.{t}]", 0.0))
        if sa:
            md.attack[t] = model.attack[t] + float(np.clip(rng.normal(0.0, sa), -clamp * sa, clamp * sa))
        if sd:
            md.defence[t] = model.defence[t] + float(np.clip(rng.normal(0.0, sd), -clamp * sd, clamp * sd))
    return md


def main():
    df = datamod.load_raw()
    print("[champ_ci] 重新拟合 GLM 以取系数标准误…")
    m = DixonColesModel(half_life_days=730.0).fit(df, verbose=False)
    bse = m.glm.bse                      # 每个系数的标准误（Series）
    rng = np.random.default_rng(SEED)

    print(f"[champ_ci] 点估 MC（{BASE_SIMS} 次）…")
    base_rows = TournamentSimulator(m, df, sims=BASE_SIMS).run()
    point = {t: champ for (t, champ, *_rest) in base_rows}

    print(f"[champ_ci] 参数不确定性传播：{N_DRAWS} 套 × {DRAW_SIMS} MC …")
    draws: dict[str, list] = {t: [] for t in point}
    done, attempts = 0, 0
    while done < N_DRAWS and attempts < N_DRAWS * 3:
        attempts += 1
        md = _perturbed(m, bse, rng)
        try:
            rows = TournamentSimulator(md, df, sims=DRAW_SIMS).run()
        except ValueError:          # 极端扰动→负概率，跳过该套（引擎不改，宁缺毋滥）
            continue
        for (t, champ, *_r) in rows:
            if t in draws:
                draws[t].append(champ)
        done += 1
        print(f"  draw {done}/{N_DRAWS}")
    print(f"  （有效 {done} 套 / 尝试 {attempts}）")

    out = []
    for t, pt in point.items():
        arr = np.array(draws[t]) if draws[t] else np.array([pt])
        out.append({"team": t, "champ": round(pt, 5),
                    "lo": round(float(np.percentile(arr, 5)), 5),
                    "med": round(float(np.percentile(arr, 50)), 5),
                    "hi": round(float(np.percentile(arr, 95)), 5)})
    out.sort(key=lambda x: x["champ"], reverse=True)

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    tmp = OUT_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"n_draws": N_DRAWS, "draw_sims": DRAW_SIMS, "base_sims": BASE_SIMS,
                   "rows": out}, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OUT_PATH)

    print(f"\n[champ_ci] 写入 {OUT_PATH}（{len(out)} 队）。Top 8 点估 + 90% 可信带：")
    for x in out[:8]:
        print(f"  {x['team']:<16} {x['champ']*100:5.1f}%  "
              f"[{x['lo']*100:4.1f}% – {x['hi']*100:4.1f}%]")


if __name__ == "__main__":
    main()
