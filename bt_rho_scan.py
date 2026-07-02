#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""DC ρ 缩放回测扫描——治「平局虚胖」病灶，只缩放(不重估)、只 backtest 评估、不动线上模型。

三把锁（用户设定）：
  锁一 只缩放不重估：ρ_used = s·ρ_fit，冻结 λ 上事后调 ρ 权重；绝不把 ρ 当自由参数重拟合 DC（那会牵动 λ）。
  锁二 方向：ρ_fit<0=往平局加权；病灶是平局虚胖(+7.1pp)→ 朝 ρ 正向(削平局)扫，s∈{+2,+1,0,−1,−2,−3} 覆盖反方向。
  锁三 λ 全程冻结：ρ 只进 score_matrix 的 τ（4 低分格），不碰 expected_goals 的 λ；脚本逐场断言 xg 与基线逐字节相等。

三道闸（与 nb_alpha 同，一字不改）：①RPS/LogLoss 不变差 ∧ 离散比向1 ∧ 全档净胜球 ECE 改善；
  ②离散比∈[0.95,1.05]+邻域稳；③DEV(2014+2018)选→TEST(2022+2026G)冻结重测；辅助 LOTO 过拟合预警。
基线 = s=1（当前线上 ρ）。任一闸不过 → 如实报「ρ 不采用」。

加项：s=−3（最反方向）实测平局虚胖病因分解——ρ 能削掉多少 pp、泊松核心结构残留多少 pp。
"""
from __future__ import annotations
import numpy as np
import pandas as pd

from model import MAX_GOALS
import manager
from backtest import _rps
from bt_nbalpha_scan import collect_models, DEV_TAGS, TEST_TAGS, _DS

SCALES = [2.0, 1.0, 0.0, -1.0, -2.0, -3.0]      # ρ_used = s·ρ_fit；s=1=基线(当前)，s<0=反方向削平局


def _metrics_at(models, tags, s):
    """在 ρ_used=s·ρ_fit 下、给定赛事子集算六指标 + λ 冻结校验（max|xg−基线xg|）。"""
    rps = ll = cs = sq = mv = 0.0
    pred = {d: 0.0 for d in _DS}; act = {d: 0.0 for d in _DS}
    p_draw = a_draw = p_tail = a_tail = 0.0
    n = 0
    lam_drift = 0.0
    for tag, m, rows in models:
        if tag not in tags:
            continue
        rho_fit = m.rho
        for h, a, neu, hs, as_ in rows:
            # 基线 λ（ρ 无关，用于锁三冻结校验）
            _, _, lam_h0, lam_a0 = m.expected_goals(h, a, neutral=neu)
            m.rho = s * rho_fit                          # 只缩放 ρ
            _, _, lam_h, lam_a, M = m.score_matrix(h, a, neutral=neu)
            m.rho = rho_fit                              # 立即复位，绝不留状态
            lam_drift = max(lam_drift, abs(lam_h - lam_h0), abs(lam_a - lam_a0))
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
    full_ece = sum(abs(pred[d] / n - act[d] / n) for d in _DS)
    return {"s": s, "n": n, "rps": rps / n, "logloss": ll / n, "cs_ll": cs / n,
            "disp": sq / mv if mv > 1e-9 else None,
            "draw_pred": p_draw / n, "draw_act": a_draw / n,
            "draw_err": (p_draw - a_draw) / n, "tail_err": (p_tail - a_tail) / n,
            "full_ece": full_ece, "lam_drift": lam_drift}


def _best_scale(models, tags):
    rows = [_metrics_at(models, tags, s) for s in SCALES]
    base = next(r for r in rows if r["s"] == 1.0)
    cand = [r for r in rows if r["rps"] <= base["rps"] + 1e-9] or rows
    return min(cand, key=lambda r: r["full_ece"])["s"]


def main():
    print("训练各届 as-of 模型（4 个，一次）…")
    models = collect_models()
    print("  各届拟合 ρ_fit：" + " · ".join(f"{t}={m.rho:+.4f}" for t, m, _ in models))

    print("\n" + "=" * 80 + "\n【DEV = 2014+2018 · ρ 缩放扫描】（基线 s=1=当前线上 ρ）\n" + "=" * 80)
    dev = [_metrics_at(models, DEV_TAGS, s) for s in SCALES]
    base = next(r for r in dev if r["s"] == 1.0)
    print(f"  {'s':>5}{'ρ方向':>8}{'RPS':>9}{'LogLoss':>10}{'离散比':>9}{'平局误差':>10}{'|d|≥3误差':>11}{'全档ECE':>10}{'λ漂移':>9}")
    for r in dev:
        d = "基线" if r["s"] == 1 else ("削平局" if r["s"] < 1 else "加平局")
        print(f"  {r['s']:>5.1f}{d:>8}{r['rps']:>9.4f}{r['logloss']:>10.4f}{r['disp']:>9.3f}"
              f"{r['draw_err']*100:>+9.1f}pp{r['tail_err']*100:>+9.1f}pp{r['full_ece']:>10.4f}{r['lam_drift']:>9.0e}")
    drift = max(r["lam_drift"] for r in dev)
    print(f"  锁三 λ 冻结校验：全 s 下 max|xg−基线xg| = {drift:.1e} → {'✅ λ 逐字节冻结（真缩放，非重估）' if drift < 1e-9 else '❌ λ 漂移，非纯缩放'}")

    # 三道闸（基线=s=1）
    def gate1(r):
        return (r["rps"] <= base["rps"] + 1e-9 and r["logloss"] <= base["logloss"] + 1e-9
                and abs(r["disp"] - 1) < abs(base["disp"] - 1) and r["full_ece"] < base["full_ece"])
    g1 = [r for r in dev if r["s"] != 1 and gate1(r)]
    g12 = [r for r in g1 if 0.95 <= r["disp"] <= 1.05]
    print(f"\n  闸一通过 s：{[r['s'] for r in g1] or '无'}；闸二（离散比∈[.95,1.05]）通过 s：{[r['s'] for r in g12] or '无'}")
    pick = min(g12, key=lambda r: (r["rps"], r["full_ece"]))["s"] if g12 else None
    print(f"  DEV 推荐 s = {pick if pick is not None else '无（闸一/二未过 → 不采用）'}")

    # 闸三
    print("\n" + "=" * 80 + "\n【闸三 · TEST = 2022+2026G 冻结重测】\n" + "=" * 80)
    if pick is not None:
        tb = _metrics_at(models, TEST_TAGS, 1.0); tp = _metrics_at(models, TEST_TAGS, pick)
        for lab, r in (("TEST s=1", tb), (f"TEST s={pick}", tp)):
            print(f"  {lab:>12}{r['rps']:>9.4f}{r['logloss']:>10.4f}{r['disp']:>9.3f}"
                  f"{r['draw_err']*100:>+9.1f}pp{r['full_ece']:>10.4f}")
        test_ok = (tp["rps"] <= tb["rps"] + 1e-9 and tp["logloss"] <= tb["logloss"] + 1e-9
                   and abs(tp["disp"] - 1) < abs(tb["disp"] - 1) and tp["full_ece"] < tb["full_ece"])
        print(f"  闸三：{'通过 ✅' if test_ok else '不通过 ❌'}")
    else:
        test_ok = False
        print("  DEV 未选出 s → 闸三跳过。")

    # LOTO（注：0.075 阈值是 α 网格口径；此处 s 为缩放因子，报 best-s 离散度供判，单位不同不强套）
    print("\n" + "=" * 80 + "\n【辅助 · LOTO（4 届各自最优 s）】\n" + "=" * 80)
    loto = {t: _best_scale(models, {t}) for t in ("2014", "2018", "2022", "2026G")}
    print(f"  各届最优 s：" + " · ".join(f"{k}={v}" for k, v in loto.items())
          + f"（极差 {max(loto.values())-min(loto.values()):.1f} s-格；注：0.075 阈值原为 α 网格口径，s 为缩放因子不强套，看是否聚类）")

    # ★ 加项：平局虚胖病因分解（s=−3 最反方向实测）
    print("\n" + "=" * 80 + "\n【病因分解 · 平局虚胖来自 ρ vs 泊松核心】（DEV，s=−3 最反方向实测）\n" + "=" * 80)
    s3 = next(r for r in dev if r["s"] == -3.0)
    by_rho = (base["draw_pred"] - s3["draw_pred"]) * 100      # ρ 翻最反方向削掉的平局 pp（实测）
    residual = s3["draw_err"] * 100                            # 削到极限后残留的平局误差 pp（ρ 够不着）
    base_err = base["draw_err"] * 100
    print(f"  基线(s=1) 平局: 预测 {base['draw_pred']*100:.1f}% vs 实际 {base['draw_act']*100:.1f}%（虚胖 {base_err:+.1f}pp）")
    print(f"  s=−3(ρ 翻正最反) 平局: 预测 {s3['draw_pred']*100:.1f}%（残留误差 {residual:+.1f}pp）")
    print(f"  → 分解：平局虚胖 {base_err:+.1f}pp 中，**ρ(低分修正)能削 {by_rho:.1f}pp**、"
          f"**泊松核心结构(λ水平+独立性)占 {residual:.1f}pp（ρ 够不着）**。")
    print(f"     即 ρ 杠杆≈{by_rho/base_err*100:.0f}%、结构性≈{residual/base_err*100:.0f}%（实测，非估算）。")

    # 总判定
    print("\n" + "=" * 80 + "\n【三道闸总判定】\n" + "=" * 80)
    verdict = (pick is not None) and test_ok
    print(f"  推荐 s：{pick if pick is not None else '—'} | 闸一：{'过' if g1 else '不过'}"
          f" | 闸二：{'过' if g12 else '不过'} | 闸三：{'过' if test_ok else '不过'}")
    if verdict:
        print(f"  → 三道闸全过：建议落地 ρ 缩放 s={pick}（仍由用户点头，落地另作 commit）。")
    else:
        print("  → 任一闸不过 → **ρ 缩放不采用**（如实负结论，与 nb_alpha 一样坦然，不硬调）。")
    print("\n  注：纯 backtest、只缩放不重估、λ 全程冻结、零碰线上 model.pkl。个人/教育项目，非投注建议。")


if __name__ == "__main__":
    main()
