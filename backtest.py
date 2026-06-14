"""Backtesting framework: quantify prediction quality on out-of-sample matches so "optimization" is evidence-based.

回测框架：用样本外比赛量化预测质量，让"优化"有据可依。

做法：选若干历史时点 cutoff，只用 cutoff 之前的数据训练，预测 cutoff 之后
      一段时间的真实比赛，比较预测胜平负概率与真实结果。

指标：
  RPS   —— Ranked Probability Score（有序三分类，越低越好；足球预测金标准）
  LogLoss—— 对数损失（越低越好）
  Acc   —— 最大概率命中率（越高越好）

效率：每个 cutoff 的 GLM 只拟合一次；身价参数用 model.reshrink() 廉价复算，
      因此可在同一次拟合上对比多组身价配置。
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

import data as datamod
from model import DixonColesModel


def _wdl(model, home, away, neutral):
    r = model.predict(home, away, neutral=neutral)
    return r["p_home"], r["p_draw"], r["p_away"]


def _rps(ph, pd_, pa, outcome):
    """有序三分类 [主胜, 平, 客胜] 的 RPS。outcome ∈ {0,1,2}。"""
    cp1, cp2 = ph, ph + pd_
    co1 = 1.0 if outcome == 0 else 0.0
    co2 = 1.0 if outcome <= 1 else 0.0
    return 0.5 * ((cp1 - co1) ** 2 + (cp2 - co2) ** 2)


def select_test(df, cutoff: dt.date, horizon_days: int):
    pl = datamod.played(df)
    lo = pd.Timestamp(cutoff)
    hi = lo + pd.Timedelta(days=horizon_days)
    m = (pl["date"] > lo) & (pl["date"] <= hi)
    return pl.loc[m]


def evaluate(model, test: pd.DataFrame):
    rps = ll = 0.0
    correct = n = 0
    gd_pred, gd_act = [], []          # 预测/实际净胜球，用于算相关系数（高盛同口径指标）
    for _, row in test.iterrows():
        h, a = row["home_team"], row["away_team"]
        try:
            r = model.predict(h, a, neutral=bool(row["neutral"]))
        except KeyError:
            continue
        ph, pdr, pa = r["p_home"], r["p_draw"], r["p_away"]
        hs, as_ = int(row["home_score"]), int(row["away_score"])
        outcome = 0 if hs > as_ else (1 if hs == as_ else 2)
        probs = [ph, pdr, pa]
        rps += _rps(ph, pdr, pa, outcome)
        ll += -np.log(max(probs[outcome], 1e-12))
        correct += (int(np.argmax(probs)) == outcome)
        gd_pred.append(r["xg_home"] - r["xg_away"])   # 预测期望净胜球
        gd_act.append(hs - as_)                        # 实际净胜球
        n += 1
    if n == 0:
        return None
    return {"n": n, "rps": rps / n, "logloss": ll / n, "acc": correct / n,
            "gd_pred": gd_pred, "gd_act": gd_act}


class _Acc:
    def __init__(self):
        self.n = self.rps = self.ll = self.cor = 0
        self.gp, self.ga = [], []          # 跨 cutoff 汇总净胜球，最后统一算相关系数
    def add(self, m):
        self.n += m["n"]; self.rps += m["rps"]*m["n"]
        self.ll += m["logloss"]*m["n"]; self.cor += m["acc"]*m["n"]
        self.gp += m.get("gd_pred", []); self.ga += m.get("gd_act", [])
    def out(self):
        gd_corr = None
        if len(self.gp) >= 2:
            c = np.corrcoef(self.gp, self.ga)[0, 1]
            gd_corr = float(c) if np.isfinite(c) else None
        return {"n": self.n, "rps": self.rps/self.n, "logloss": self.ll/self.n,
                "acc": self.cor/self.n, "gd_corr": gd_corr}


def run(df, cutoffs, horizon_days, half_life, market_variants, verbose=True):
    """
    market_variants: list of (name, market_k, min_market_weight)
    返回 {name: 聚合指标}
    """
    aggs = {name: _Acc() for name, _, _ in market_variants}
    for cutoff in cutoffs:
        if verbose:
            print(f"  [cutoff {cutoff}] half_life={half_life} 拟合中…")
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        test = select_test(df, cutoff, horizon_days)
        for name, k, wmin in market_variants:
            m.reshrink(market_k=k, min_market_weight=wmin)
            res = evaluate(m, test)
            if res:
                aggs[name].add(res)
                if verbose:
                    print(f"      {name:<16} n={res['n']:>4} "
                          f"RPS={res['rps']:.4f} LogLoss={res['logloss']:.4f} Acc={res['acc']:.3f}")
    return {name: a.out() for name, a in aggs.items()}


def _major_gd_corr(df, cutoffs, horizon, half_life):
    """只在'大赛正赛'测试样本上算净胜球相关系数，与高盛口径更接近。"""
    gp, ga = [], []
    for cutoff in cutoffs:
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        test = select_test(df, cutoff, horizon)
        test = test[test["tournament"].map(lambda t: datamod.comp_tier(t) == "major")]
        r = evaluate(m, test)
        if r:
            gp += r["gd_pred"]; ga += r["gd_act"]
    if len(gp) >= 2:
        c = np.corrcoef(gp, ga)[0, 1]
        return (float(c), len(gp)) if np.isfinite(c) else None
    return None


if __name__ == "__main__":
    df = datamod.load_raw()
    cutoffs = [dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
    horizon = 270
    half_life = 547
    variants = [
        ("无身价", None, 0.0),
        ("身价k25w.15", 25, 0.15),
    ]
    print(f"回测：cutoffs={cutoffs}, horizon={horizon}d, half_life=547")
    res = run(df, cutoffs, horizon, 547, variants)
    print("\n== 聚合结果 ==")
    print(f"  {'配置':<16}{'样本':>6}{'RPS':>9}{'LogLoss':>10}{'命中率':>8}{'净胜球相关':>11}")
    for name, m in res.items():
        gc = f"{m['gd_corr']*100:.0f}%" if m.get("gd_corr") is not None else "—"
        print(f"  {name:<16}{m['n']:>6}{m['rps']:>9.4f}{m['logloss']:>10.4f}"
              f"{m['acc']:>8.3f}{gc:>11}")
    base = res.get("无身价") or next(iter(res.values()))
    if base.get("gd_corr") is not None:
        print(f"\n  净胜球相关系数（全部国际赛）= {base['gd_corr']*100:.0f}%")
        # 仅大赛正赛子集 —— 与高盛"只在世界杯正赛上自评"更同口径
        mc = _major_gd_corr(df, cutoffs, horizon, half_life)
        if mc is not None:
            print(f"  净胜球相关系数（仅大赛正赛 n={mc[1]}）= {mc[0]*100:.0f}%")
        print("  对标：高盛官方自评（仅世界杯正赛）历届~49% / 2018届43% / 2022届45%。")
        print("  注意：全部国际赛含大量强弱悬殊场次，净胜球好预测→相关偏高，不可与高盛")
        print("        '仅世界杯正赛'直接比；大赛正赛子集才更同口径（但近年大赛样本有限）。")
