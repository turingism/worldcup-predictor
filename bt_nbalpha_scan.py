#!/usr/bin/env python3
"""nb_alpha（负二项过离散）回测扫描——治净胜球欠离散，但只在 backtest 评估、不动线上模型。

三道硬闸（采用标准，缺一不采用）：
  闸一 三指标 AND 同向改善：RPS/LogLoss 不变差 AND 离散比回归 AND 全档净胜球校准误差缩小
       （校准看**全分布** Σ_d|预测P(d)−实际freq(d)|，不只 d=0/|d|≥3 两点，防零和搬运的伪改善）。
  闸二 防过冲：取「三指标联合改善 AND 离散比∈[0.95,1.05]」的 α，且最优点邻域稳定（给整条曲线）。
  闸三 out-of-sample：时序前向切分 DEV(2014+2018) 选 α → TEST(2022+2026G) 冻结重测，不回调。
  辅助 LOTO：4 届各自最优 α 极差>0.075(3 格)→ 标黄过拟合预警（不作采用依据）。

nb_alpha 是预测时 pmf 加宽（NB2：均值仍是 GLM 的 λ、方差 λ+α·λ²），不改 GLM 拟合 →
每个 cutoff 只训练一次，整条 α 网格在冻结 λ 上廉价重算。零碰线上 model.pkl / 默认 nb_alpha=0。
"""
from __future__ import annotations
import numpy as np
import pandas as pd

import data as datamod
from model import DixonColesModel, MAX_GOALS
import manager
from backtest import _rps
from bt_calib_margin import WC_WINDOWS

ALPHAS = [round(a, 3) for a in np.arange(0.0, 0.2501, 0.025)]
DEV_TAGS = {"2014", "2018"}
TEST_TAGS = {"2022", "2026G"}
_DS = range(-8, 9)            # 全档净胜球 ECE 的覆盖范围（涵盖 ~全部概率）


def collect_models(half_life=730.0):
    """as-of 训练各届模型（一次），返回 [(tag, model, [(h,a,neutral,hs,as)...])]。"""
    df = datamod.load_raw()
    pl = datamod.played(df)
    out = []
    for tag, cutoff, end in WC_WINDOWS:
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        sel = pl[(pl.date > pd.Timestamp(cutoff)) & (pl.date <= pd.Timestamp(end))
                 & (pl.tournament == "FIFA World Cup")]
        rows = []
        for _, r in sel.iterrows():
            try:
                m.resolve(r.home_team); m.resolve(r.away_team)
            except KeyError:
                continue
            rows.append((r.home_team, r.away_team, bool(r.neutral),
                         int(r.home_score), int(r.away_score)))
        out.append((tag, m, rows))
    return out


def _metrics_at(models, tags, alpha):
    """在给定 α 下、给定赛事子集上算六指标。"""
    rps = ll = cs = sq = mv = 0.0
    pred = {d: 0.0 for d in _DS}; act = {d: 0.0 for d in _DS}
    p_draw = a_draw = p_tail = a_tail = 0.0
    n = 0
    for tag, m, rows in models:
        if tag not in tags:
            continue
        m.nb_alpha = alpha                       # 仅改 pmf，不重训
        for h, a, neu, hs, as_ in rows:
            *_, M = m.score_matrix(h, a, neutral=neu)
            ph = float(np.tril(M, -1).sum()); pdd = float(np.trace(M)); pa = float(np.triu(M, 1).sum())
            oc = 0 if hs > as_ else (1 if hs == as_ else 2)
            rps += _rps(ph, pdd, pa, oc)
            ll += -np.log(max([ph, pdd, pa][oc], 1e-12))
            i, j = min(hs, MAX_GOALS), min(as_, MAX_GOALS)
            cs += -np.log(max(float(M[i, j]), 1e-12))
            mp = manager._margin_pmf(M)
            em = sum(k * p for k, p in mp.items())
            ev = sum((k - em) ** 2 * p for k, p in mp.items())
            sq += (((hs - as_) - em) ** 2); mv += ev
            d_act = max(-8, min(8, hs - as_))
            for d in _DS:
                pred[d] += mp.get(d, 0.0)
            act[d_act] += 1.0
            p_draw += mp.get(0, 0.0); a_draw += (hs - as_ == 0)
            p_tail += sum(p for k, p in mp.items() if abs(k) >= 3); a_tail += (abs(hs - as_) >= 3)
            n += 1
    m.nb_alpha = 0.0                             # 复位，绝不留状态
    full_ece = sum(abs(pred[d] / n - act[d] / n) for d in _DS)    # 全档净胜球校准总误差
    return {"alpha": alpha, "n": n, "rps": rps / n, "logloss": ll / n, "cs_ll": cs / n,
            "disp": sq / mv if mv > 1e-9 else None,
            "draw_err": (p_draw - a_draw) / n, "tail_err": (p_tail - a_tail) / n,
            "full_ece": full_ece}


def _best_alpha(models, tags):
    """某子集上『最优 α』= 在 RPS 不差于 α=0 的前提下、全档净胜球 ECE 最小者（校准目标）。"""
    rows = [_metrics_at(models, tags, a) for a in ALPHAS]
    base_rps = rows[0]["rps"]
    cand = [r for r in rows if r["rps"] <= base_rps + 1e-9] or rows
    return min(cand, key=lambda r: r["full_ece"])["alpha"], rows


def main():
    print("训练各届 as-of 模型（4 个，一次）…")
    models = collect_models()
    for tag, _, rows in models:
        print(f"  {tag}: {len(rows)} 场")

    print("\n" + "=" * 78 + "\n【DEV = 2014+2018 · α 扫描曲线】（看过冲与邻域稳定）\n" + "=" * 78)
    dev = [_metrics_at(models, DEV_TAGS, a) for a in ALPHAS]
    base = dev[0]
    hdr = f"  {'α':>6}{'RPS':>9}{'LogLoss':>10}{'离散比':>9}{'平局误差':>10}{'|d|≥3误差':>11}{'全档ECE':>10}"
    print(hdr)
    for r in dev:
        flag = " ←基线" if r["alpha"] == 0 else ""
        print(f"  {r['alpha']:>6.3f}{r['rps']:>9.4f}{r['logloss']:>10.4f}{r['disp']:>9.3f}"
              f"{r['draw_err']*100:>+9.1f}pp{r['tail_err']*100:>+9.1f}pp{r['full_ece']:>10.4f}{flag}")

    # 三道闸在 DEV 上筛 α
    def passes_gate1(r):     # RPS/LogLoss 不变差 + 离散比向 1 收 + 全档 ECE 改善
        return (r["rps"] <= base["rps"] + 1e-9 and r["logloss"] <= base["logloss"] + 1e-9
                and abs(r["disp"] - 1) < abs(base["disp"] - 1) and r["full_ece"] < base["full_ece"])
    g1 = [r for r in dev if r["alpha"] > 0 and passes_gate1(r)]
    g12 = [r for r in g1 if 0.95 <= r["disp"] <= 1.05]      # 闸二：离散比落带内
    print(f"\n  闸一（RPS/LogLoss 不变差 ∧ 离散比向1 ∧ 全档ECE改善）通过的 α："
          f"{[r['alpha'] for r in g1] or '无'}")
    print(f"  闸二（且离散比∈[0.95,1.05]）通过的 α：{[r['alpha'] for r in g12] or '无'}")

    pick = None
    if g12:
        pick = min(g12, key=lambda r: (r["rps"], r["full_ece"]))["alpha"]   # 联合最优
    print(f"  DEV 推荐 α = {pick if pick is not None else '无（闸一/二未通过 → 不采用）'}")

    # 闸三：选定 α 在 TEST 冻结重测
    print("\n" + "=" * 78 + "\n【闸三 · TEST = 2022+2026G 冻结重测】（DEV vs TEST，看过拟合）\n" + "=" * 78)
    if pick is not None:
        d_pick = next(r for r in dev if r["alpha"] == pick)
        d_base = base
        t_pick = _metrics_at(models, TEST_TAGS, pick)
        t_base = _metrics_at(models, TEST_TAGS, 0.0)
        print(f"  {'':>14}{'RPS':>9}{'LogLoss':>10}{'离散比':>9}{'平局误差':>10}{'|d|≥3误差':>11}{'全档ECE':>10}")
        for lab, r in (("DEV α=0", d_base), (f"DEV α={pick}", d_pick),
                       ("TEST α=0", t_base), (f"TEST α={pick}", t_pick)):
            print(f"  {lab:>14}{r['rps']:>9.4f}{r['logloss']:>10.4f}{r['disp']:>9.3f}"
                  f"{r['draw_err']*100:>+9.1f}pp{r['tail_err']*100:>+9.1f}pp{r['full_ece']:>10.4f}")
        test_ok = (t_pick["rps"] <= t_base["rps"] + 1e-9 and t_pick["logloss"] <= t_base["logloss"] + 1e-9
                   and abs(t_pick["disp"] - 1) < abs(t_base["disp"] - 1) and t_pick["full_ece"] < t_base["full_ece"])
        print(f"  闸三判定（TEST 上三指标仍同向改善）：{'通过 ✅' if test_ok else '不通过 ❌'}")
    else:
        test_ok = False
        print("  DEV 未选出 α → 闸三跳过。")

    # 辅助：LOTO 4 届各自最优 α 极差
    print("\n" + "=" * 78 + "\n【辅助 · LOTO 过拟合预警】（4 届各自最优 α，极差>0.075 标黄）\n" + "=" * 78)
    loto = {}
    for tag in ("2014", "2018", "2022", "2026G"):
        ba, _ = _best_alpha(models, {tag})
        loto[tag] = ba
    spread = max(loto.values()) - min(loto.values())
    print(f"  各届最优 α：" + " · ".join(f"{k}={v}" for k, v in loto.items()))
    print(f"  极差 = {spread:.3f} → {'⚠ 标黄：α 在各届间不稳，过拟合预警' if spread > 0.075 else '稳定（≤0.075）'}")

    # 总判定
    print("\n" + "=" * 78 + "\n【三道闸总判定】\n" + "=" * 78)
    verdict = (pick is not None) and test_ok
    print(f"  推荐 α：{pick if pick is not None else '—'}")
    print(f"  闸一(DEV 三指标同向)：{'过' if g1 else '不过'} | 闸二(离散比∈带内)：{'过' if g12 else '不过'}"
          f" | 闸三(TEST 冻结同向)：{'过' if test_ok else '不过'} | LOTO：{'稳' if spread <= 0.075 else '标黄'}")
    if verdict and spread <= 0.075:
        print(f"  → 三道闸全过、LOTO 稳：建议落地 nb_alpha={pick}（仍由用户点头，落地另作 commit + 重训）。")
    elif verdict:
        print(f"  → 三道闸全过但 LOTO 标黄：建议落地 nb_alpha={pick} 但附过拟合警示，由用户定夺。")
    else:
        print("  → 任一闸不过 → **nb_alpha 不采用**（如实负结论，像淘汰赛保守效应一样接受，不硬调）。")
    print("\n  注：纯 backtest 评估，零碰线上 model.pkl / 默认 nb_alpha=0。个人/教育项目，非投注建议。")


if __name__ == "__main__":
    main()
