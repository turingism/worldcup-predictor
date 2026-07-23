"""精确比分欠离散修复尝试（P1-7，2026-07-19）：NB2 过离散 α 网格，严格 DEV/TEST。

诊断背景：实际净胜球方差 ≈ 模型隐含方差 ×1.2（bt_wc.py margin_disp_ratio 复现），
大比分尾部被低估。候选修复 = model.nb_alpha（NB2: var=μ+α·μ²，同一 GLM 拟合上
仅改比分分布，无需重训）。

纪律：
  - DEV cutoffs 选 α（2023-06-01, 2024-11-01），TEST cutoff（2025-08-01）只评一次；
  - 采纳门槛（预定义，全部满足才采纳）：TEST 上
      ① RPS 不劣化超过 0.0005；② 比分 LogLoss 改善 > 0.01；
      ③ 尾部校准比 |P̂(|gd|≥3)/P(|gd|≥3) − 1| 缩小；④ 离散比向 1 靠近。
  - 未过线 → 保留纯 DC（历史结论：NB 单调更差；本脚本在 hl=730 新数据上复核）。
"""
from __future__ import annotations
import datetime as dt

import numpy as np
import pandas as pd

import config
import data as datamod
from bt_wc import eval_matches, summarize
from model import DixonColesModel

ALPHAS = [0.0, 0.03, 0.06, 0.10, 0.15]
DEV_CUTOFFS = [dt.date(2023, 6, 1), dt.date(2024, 11, 1)]
TEST_CUTOFF = dt.date(2025, 8, 1)
HORIZON = 270


def tail_ratio(model, test):
    """实际 vs 模型 P(|净胜球|≥3)。返回 (实际频率, 模型平均概率)。"""
    n = 0; act = 0; pred = 0.0
    for _, r in test.iterrows():
        try:
            _, _, _, _, M = model.score_matrix(r["home_team"], r["away_team"],
                                               neutral=bool(r["neutral"]))
        except KeyError:
            continue
        idx = np.arange(M.shape[0])
        H, A = np.meshgrid(idx, idx, indexing="ij")
        pred += float(M[np.abs(H - A) >= 3].sum())
        act += int(abs(int(r["home_score"]) - int(r["away_score"])) >= 3)
        n += 1
    return (act / n, pred / n) if n else (np.nan, np.nan)


def eval_alpha(df, cutoffs, alphas):
    pl = datamod.played(df)
    out = {a: [] for a in alphas}
    tails = {a: [0, 0.0, 0] for a in alphas}   # act_sum, pred_sum, n
    for cutoff in cutoffs:
        m = DixonColesModel(half_life_days=config.NATIONAL_HALF_LIFE).fit(
            df, verbose=False, as_of=cutoff)
        lo = pd.Timestamp(cutoff); hi = lo + pd.Timedelta(days=HORIZON)
        test = pl[(pl["date"] > lo) & (pl["date"] <= hi)]
        for a in alphas:
            m.nb_alpha = a                     # 同一 GLM，仅改比分分布层
            ev = eval_matches(m, test)
            out[a].append(ev)
            ar, pr = tail_ratio(m, test)
            tails[a][0] += ar * len(ev); tails[a][1] += pr * len(ev); tails[a][2] += len(ev)
        m.nb_alpha = 0.0
    res = {}
    for a in alphas:
        allm = pd.concat(out[a], ignore_index=True)
        s = summarize(allm, boot=500)
        n = tails[a][2]
        s["tail_act"] = tails[a][0] / n
        s["tail_pred"] = tails[a][1] / n
        s["tail_miss"] = abs(s["tail_pred"] / s["tail_act"] - 1) if s["tail_act"] else np.nan
        res[a] = s
    return res


def main():
    df = datamod.load_raw()
    print("== DEV（选 α）==")
    dev = eval_alpha(df, DEV_CUTOFFS, ALPHAS)
    for a, s in dev.items():
        print(f"  α={a:<5} RPS={s['rps']:.4f} 比分LL={s['score_logloss']:.4f} "
              f"离散比={s['margin_disp_ratio']:.3f} 尾部(实/模)={s['tail_act']:.3f}/{s['tail_pred']:.3f}")
    # DEV 选择：比分 LL 最优且 RPS 不劣化>0.0005 的 α
    base = dev[0.0]
    cand = min(ALPHAS, key=lambda a: dev[a]["score_logloss"]
               if dev[a]["rps"] <= base["rps"] + 0.0005 else np.inf)
    print(f"\n  DEV 选择 α={cand}")
    if cand == 0.0:
        print("  → DEV 阶段即无净收益，保留纯 DC（不进入 TEST 消耗）。")
        return
    print("\n== TEST（只评一次）==")
    test = eval_alpha(df, [TEST_CUTOFF], [0.0, cand])
    b, c = test[0.0], test[cand]
    print(f"  α=0    RPS={b['rps']:.4f} 比分LL={b['score_logloss']:.4f} "
          f"离散比={b['margin_disp_ratio']:.3f} 尾差={b['tail_miss']:.3f}")
    print(f"  α={cand} RPS={c['rps']:.4f} 比分LL={c['score_logloss']:.4f} "
          f"离散比={c['margin_disp_ratio']:.3f} 尾差={c['tail_miss']:.3f}")
    gates = {
        "RPS 不劣化≤0.0005": c["rps"] <= b["rps"] + 0.0005,
        "比分LL 改善>0.01": b["score_logloss"] - c["score_logloss"] > 0.01,
        "尾部校准改善": c["tail_miss"] < b["tail_miss"],
        "离散比向1靠近": abs(c["margin_disp_ratio"] - 1) < abs(b["margin_disp_ratio"] - 1),
    }
    for k, v in gates.items():
        print(f"    {'✅' if v else '❌'} {k}")
    print(f"\n  结论：{'采纳 α=' + str(cand) if all(gates.values()) else '未全过线 → 保留纯 DC，文档记为已知限制'}")


if __name__ == "__main__":
    main()
