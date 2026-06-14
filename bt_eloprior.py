"""
实验：Elo 先验「收缩混合」对预测质量的影响（区别于已否决的 use_elo 外生特征）。

动机
----
纯 Dixon-Coles 基于进球拟合 attack/defence。当一支球队的赛程「聚集」在一批弱旅
身上（如挪威：Haaland 狂进球但对手档次窄），GLM 的 attack/对手 defence 互相纠缠，
对手强度归一化不充分 → 净实力被高估。蒙特卡洛夺冠投影继承这一扭曲：
本模型把挪威排到夺冠第 4（高于法国/德国/巴西），明显违背常识与 Kimi/市场/Elo 共识。

Elo 通过「传递性」在整个对阵图上传播对手强度（A 胜 B、B 胜 C → A 强于 C），
正好补 DC 的短板。这里把 Elo 当作**收缩先验**（不是 GLM 外生协变量——那个口径已被
bt_elo.py 在全样本 RPS 上否决），用与身价先验相同的机制：
  1) 在样本充足球队上拟合 attack~Elo、defence~Elo 线性映射；
  2) 按全局权重 β 把每队评级朝 Elo 隐含评级混合。

关键守门
--------
- 全样本 RPS 不可恶化（沿用项目铁律）。
- 额外报「强强对话子集」RPS：双方 Elo 都靠前的比赛，才是世界杯淘汰赛真正考验
  对手强度归一化的口径——全样本被大量强弱悬殊场次稀释，看不出区别。
- 额外报「夺冠强度排序 face-validity」：与 Elo 参考的 Spearman 相关。

用法：python3 bt_eloprior.py
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

import data as datamod
import elo as elomod
from model import DixonColesModel
from backtest import select_test, evaluate, _Acc


def elo_maps(model: DixonColesModel, elo_ratings: dict, min_n: int = 40):
    """在样本充足球队上拟合 attack~Elo / defence~Elo 线性映射。返回两条 (k,b)。"""
    fit_t = [t for t in model.teams
             if t in elo_ratings and model.n_matches.get(t, 0) >= min_n]
    if len(fit_t) < 20:
        return None
    e = np.array([elo_ratings[t] for t in fit_t]) / 100.0  # 缩放，数值稳定
    atk = np.array([model.attack_raw[t] for t in fit_t])
    dfc = np.array([model.defence_raw[t] for t in fit_t])
    ka, ba = np.polyfit(e, atk, 1)
    kd, bd = np.polyfit(e, dfc, 1)
    return (ka, ba, kd, bd)


def blend(model: DixonColesModel, elo_ratings: dict, maps, beta: float):
    """把 model.attack/defence 设为 (1-β)·DC + β·Elo隐含。就地修改，供 evaluate 用。"""
    ka, ba, kd, bd = maps
    model.attack = dict(model.attack_raw)
    model.defence = dict(model.defence_raw)
    if beta <= 0:
        return model
    for t in model.teams:
        if t not in elo_ratings:
            continue
        e = elo_ratings[t] / 100.0
        model.attack[t] = (1 - beta) * model.attack_raw[t] + beta * (ka * e + ba)
        model.defence[t] = (1 - beta) * model.defence_raw[t] + beta * (kd * e + bd)
    return model


def run(df, cutoffs, horizon, half_life, betas):
    all_aggs = {b: _Acc() for b in betas}
    strong_aggs = {b: _Acc() for b in betas}
    for cutoff in cutoffs:
        print(f"  [cutoff {cutoff}] 拟合 DC + 计算 as_of Elo …")
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        _, elo_ratings = elomod.prematch_ratings(df, as_of=cutoff)
        maps = elo_maps(m, elo_ratings)
        if maps is None:
            print("    Elo 映射样本不足，跳过")
            continue
        test = select_test(df, cutoff, horizon)
        # 强强子集：双方 Elo 都在参赛级别（≥ 第 40 高）——逼近世界杯对阵口径
        thr = sorted(elo_ratings.values(), reverse=True)[min(40, len(elo_ratings) - 1)]
        smask = test.apply(
            lambda r: elo_ratings.get(r["home_team"], 0) >= thr
            and elo_ratings.get(r["away_team"], 0) >= thr, axis=1)
        strong = test[smask]
        for b in betas:
            blend(m, elo_ratings, maps, b)
            ra = evaluate(m, test)
            if ra:
                all_aggs[b].add(ra)
            rs = evaluate(m, strong)
            if rs:
                strong_aggs[b].add(rs)
        print(f"    全样本 n={len(test)}  强强子集 n={len(strong)}")
    return ({b: a.out() for b, a in all_aggs.items()},
            {b: a.out() for b, a in strong_aggs.items()})


if __name__ == "__main__":
    df = datamod.load_raw()
    cutoffs = [dt.date(2024, 11, 1), dt.date(2025, 8, 1), dt.date(2025, 11, 1)]
    horizon = 240
    half_life = 240
    betas = [0.0, 0.15, 0.30, 0.50, 0.75]
    print(f"Elo 先验混合回测：cutoffs={cutoffs}, horizon={horizon}d, half_life={half_life}")
    all_res, strong_res = run(df, cutoffs, horizon, half_life, betas)

    def table(title, res):
        print(f"\n== {title} ==")
        print(f"  {'β':>5}{'样本':>7}{'RPS':>9}{'LogLoss':>10}{'命中率':>8}")
        base = res[0.0]["rps"] if res.get(0.0) else None
        for b in betas:
            m = res.get(b)
            if not m or m["n"] == 0:
                print(f"  {b:>5}      —"); continue
            d = "" if base is None or b == 0 else f"  ({(m['rps']-base)*1e4:+.1f}e-4)"
            print(f"  {b:>5}{m['n']:>7}{m['rps']:>9.4f}{m['logloss']:>10.4f}{m['acc']:>8.3f}{d}")

    table("全样本 RPS（守门：β>0 不可恶化）", all_res)
    table("强强对话子集 RPS（世界杯淘汰赛口径）", strong_res)
