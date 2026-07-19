#!/usr/bin/env python3
"""俱乐部宇宙市场对标（P2 市场 tab 的诚实基线，五大联赛）。纯离线旁路，零碰 app/GLM。

问题：国家队侧已有「模型 vs 闭盘，市场三项全胜」的诚实结论（bt_explainer，
RPS .1544 vs .1426）；俱乐部侧 B365 开盘+闭盘原生齐全，但从未量化过各联赛
模型（hl=365，正式裁决超参）与市场的差距。P2 接英超市场层之前必须先有这个基线。

方法（对齐主项目回测纪律：时序前向、as_of 防泄漏、多 cutoff × 多联赛防单窗过拟合）：
  - 每 (联赛, cutoff)：cutoff 前数据训练（hl=365），预测 cutoff 后 180 天场次；
  - 同一批场次上对比三方：模型 / B365 开盘（Shin 去水）/ B365 闭盘（Shin 去水）；
  - 只计模型可预测【且】开闭盘俱全的场次（公平对比，跳过数如实打印，无沉默截断）；
  - 指标：RPS / LogLoss / 命中率（与 bt_club_hl 同口径）。

先验（红线口径）：预期市场全胜——本脚本是「认清打不赢市场」的俱乐部版实证，
不是找 edge；结果只作 P2 市场 tab 的描述性对标文案依据。

用法：python3 bt_club_market.py
"""
from __future__ import annotations
import warnings

import numpy as np
import pandas as pd

import clubdata
import devig
from model import DixonColesModel

warnings.filterwarnings("ignore")

HL = 365.0                                   # 正式裁决超参（bt_club_hl full_scan）
CUTOFFS = ["2023-08-01", "2024-08-01", "2025-01-01"]
LEAGUES = ["E0", "SP1", "I1", "D1", "F1"]
HORIZON_DAYS = 180
SEASONS = 7


def rps(p, outcome):
    c = np.cumsum(p)
    o = np.zeros(3); o[outcome] = 1.0
    return float(np.sum((c - np.cumsum(o))[:2] ** 2) / 2)


def _score(p, out, acc):
    p = np.clip(p, 1e-9, 1)
    acc["rps"].append(rps(p, out))
    acc["ll"].append(-np.log(p[out]))
    acc["hit"].append(int(np.argmax(p) == out))


def evaluate(df, cutoff):
    """cutoff 前训练、后 180 天评测；返回 (模型, 开盘, 闭盘) 三方指标 + 覆盖计数。"""
    cut = pd.Timestamp(cutoff)
    m = DixonColesModel(half_life_days=HL).fit(df, verbose=False, as_of=cut)
    test = df[(df.date >= cut) & (df.date < cut + pd.Timedelta(days=HORIZON_DAYS))]
    accs = {k: {"rps": [], "ll": [], "hit": []} for k in ("model", "open", "close")}
    n_model_skip = n_odds_skip = 0
    for _, r in test.iterrows():
        if r.home_team not in m.attack or r.away_team not in m.attack:
            n_model_skip += 1
            continue
        oc = [r.get("B365H"), r.get("B365D"), r.get("B365A"),
              r.get("B365CH"), r.get("B365CD"), r.get("B365CA")]
        if any(pd.isna(x) for x in oc):
            n_odds_skip += 1
            continue
        out = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
        pr = m.predict(r.home_team, r.away_team, neutral=False)
        _score([pr["p_home"], pr["p_draw"], pr["p_away"]], out, accs["model"])
        _score(devig.shin(*oc[:3]), out, accs["open"])
        _score(devig.shin(*oc[3:]), out, accs["close"])
    n = len(accs["model"]["rps"])
    means = {k: {j: float(np.mean(v[j])) if n else float("nan") for j in v}
             for k, v in accs.items()}
    return means, n, n_model_skip, n_odds_skip


def main():
    print(f"俱乐部市场对标：hl={HL:.0f}，{len(LEAGUES)} 联赛 × {len(CUTOFFS)} cutoff，"
          f"horizon={HORIZON_DAYS}d，去水=Shin\n")
    grand = {k: {"rps": [], "ll": [], "hit": []} for k in ("model", "open", "close")}
    rows = []
    for lg in LEAGUES:
        df = clubdata.load(lg, seasons=SEASONS)
        agg = {k: {"rps": [], "ll": [], "hit": []} for k in ("model", "open", "close")}
        n_all = sk_m = sk_o = 0
        for cut in CUTOFFS:
            means, n, skm, sko = evaluate(df, cut)
            n_all += n; sk_m += skm; sk_o += sko
            for k in agg:
                for j in agg[k]:
                    # 按场回灌均值×n，等价于全场次合并均值
                    agg[k][j].extend([means[k][j]] * n)
                    grand[k][j].extend([means[k][j]] * n)
        row = {k: {j: float(np.mean(agg[k][j])) for j in agg[k]} for k in agg}
        rows.append((lg, row, n_all, sk_m, sk_o))
        print(f"—— {lg}（n={n_all}，跳过：模型缺队 {sk_m} / 缺盘口 {sk_o}）")
        for k, lab in (("model", "模型  "), ("open", "开盘  "), ("close", "闭盘  ")):
            r = row[k]
            print(f"   {lab} RPS {r['rps']:.4f}  LogLoss {r['ll']:.4f}  命中 {r['hit']:.1%}")
        gap = row["model"]["rps"] - row["close"]["rps"]
        print(f"   模型−闭盘 RPS gap = {gap:+.4f}（正=市场更准）\n")

    print("══ 跨联赛汇总（等权按场）══")
    for k, lab in (("model", "模型  "), ("open", "开盘  "), ("close", "闭盘  ")):
        r = {j: float(np.mean(grand[k][j])) for j in grand[k]}
        print(f"   {lab} RPS {r['rps']:.4f}  LogLoss {r['ll']:.4f}  命中 {r['hit']:.1%}")
    g_open = float(np.mean(grand["open"]["rps"]))
    g_close = float(np.mean(grand["close"]["rps"]))
    g_model = float(np.mean(grand["model"]["rps"]))
    print(f"\n   闭盘−开盘 RPS = {g_close - g_open:+.4f}（负=闭盘更锐利，与国家队结论同向则印证）")
    print(f"   模型−闭盘 RPS = {g_model - g_close:+.4f}"
          f"（对照国家队 gap +.0118；正=市场更准=诚实先验成立）")


if __name__ == "__main__":
    main()
