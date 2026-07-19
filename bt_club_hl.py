#!/usr/bin/env python3
"""俱乐部宇宙半衰期回测（P2 超参裁决，五大联赛）。纯离线旁路，零碰国家队主线。

方法（对齐主项目回测纪律：时序前向、as_of 防泄漏、多 cutoff × 多联赛防单窗过拟合）：
  - 数据：clubdata.load(<lg>, seasons=7)（football-data.co.uk）。
  - 每 (联赛, cutoff, hl)：cutoff 前数据训练，预测 cutoff 后 horizon=180 天，RPS/LogLoss/命中率。
  - 裁决口径：**跨联赛跨 cutoff 平均 RPS** 最低者胜；同时打印每联赛最优，检查方向一致性。
  - 升班马坑：升班季前无顶级数据的队不在模型 → 跳过计数（--e1 变体检验并入英冠是否修复）。

用法：
  python3 bt_club_hl.py            # 正式复扫：5 联赛 × 3 cutoff × 8 档网格
  python3 bt_club_hl.py --quick    # 首扫口径（英超 × 2 cutoff）
  python3 bt_club_hl.py --e1       # E0+E1 合训变体（hl 取正式扫最优，看跳场与 RPS）

首扫结论存档（2026-07-08，英超 7 季 × 2 cutoff）：最优 hl=120–240（RPS 0.2062/0.2065），
365 起单调劣化，730（国家队最优）=0.2149 显著差——方向与国家队完全相反。
"""
from __future__ import annotations
import sys
import warnings

import numpy as np
import pandas as pd

import clubdata
from model import DixonColesModel

warnings.filterwarnings("ignore")

HL_GRID = [60, 90, 120, 180, 240, 365, 545, 730]
CUTOFFS = ["2023-08-01", "2024-08-01", "2025-01-01"]
LEAGUES = ["E0", "SP1", "I1", "D1", "F1"]
HORIZON_DAYS = 180
SEASONS = 7


def rps(p, outcome):        # p=(ph,pd,pa), outcome=0/1/2
    c = np.cumsum(p)
    o = np.zeros(3); o[outcome] = 1.0
    return float(np.sum((c - np.cumsum(o))[:2] ** 2) / 2)


def evaluate(df, hl, cutoff, test_filter=None):
    """cutoff 前训练、后 horizon 内评测。test_filter 可限定评测子集（E1 变体只测 E0 场）。"""
    cut = pd.Timestamp(cutoff)
    m = DixonColesModel(half_life_days=float(hl)).fit(df, verbose=False, as_of=cut)
    test = df[(df.date >= cut) & (df.date < cut + pd.Timedelta(days=HORIZON_DAYS))]
    if test_filter is not None:
        test = test[test_filter(test)]
    rs, lls, hits, skipped = [], [], [], 0
    for _, r in test.iterrows():
        if r.home_team not in m.attack or r.away_team not in m.attack:
            skipped += 1
            continue
        pr = m.predict(r.home_team, r.away_team, neutral=False)
        p = np.clip([pr["p_home"], pr["p_draw"], pr["p_away"]], 1e-9, 1)
        out = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
        rs.append(rps(p, out))
        lls.append(-np.log(p[out]))
        hits.append(int(np.argmax(p) == out))
    return dict(n=len(rs), skipped=skipped,
                rps=float(np.mean(rs)) if rs else float("nan"),
                logloss=float(np.mean(lls)) if lls else float("nan"),
                hit=float(np.mean(hits)) if hits else float("nan"))


def full_scan():
    frames = {lg: clubdata.load(lg, seasons=SEASONS) for lg in LEAGUES}
    for lg, df in frames.items():
        print(f"[data] {lg} {len(df)} 场 {df.date.min().date()} → {df.date.max().date()}")
    print(f"\n网格 {HL_GRID} × cutoffs {CUTOFFS} × {len(LEAGUES)} 联赛\n")

    by_hl_all, by_lg_best = {}, {}
    for lg in LEAGUES:
        by_hl = {}
        for hl in HL_GRID:
            vals = [evaluate(frames[lg], hl, c)["rps"] for c in CUTOFFS]
            by_hl[hl] = float(np.mean(vals))
            by_hl_all.setdefault(hl, []).append(by_hl[hl])
        best = min(by_hl, key=by_hl.get)
        by_lg_best[lg] = (best, by_hl[best])
        row = "  ".join(f"{hl}:{by_hl[hl]:.4f}" for hl in HL_GRID)
        print(f"{lg:<4} 最优 hl={best:<4} | {row}")

    print("\n—— 跨联赛平均（裁决口径）——")
    agg = {hl: float(np.mean(v)) for hl, v in by_hl_all.items()}
    for hl in HL_GRID:
        mark = "  ← 最优" if hl == min(agg, key=agg.get) else ""
        print(f"  hl={hl:<5} 平均 RPS {agg[hl]:.4f}{mark}")
    best = min(agg, key=agg.get)
    spread = {lg: b for lg, (b, _) in by_lg_best.items()}
    print(f"\n裁决：half_life={best}（跨联赛平均 {agg[best]:.4f}）。各联赛最优 {spread}"
          f"\n采纳纪律：若各联赛最优同向聚在低半衰期区间（≤240），P2 每联赛统一用跨联赛最优；"
          f"若方向分裂则各用各的并在 CLAUDE.md 记录。")
    return best


def e1_variant(hl):
    """E0+E1 合训、只测 E0：升班马是否消除 + RPS 是否不劣化。"""
    e0 = clubdata.load("E0", seasons=SEASONS)
    e1 = clubdata.load("E1", seasons=SEASONS)
    both = pd.concat([e0, e1], ignore_index=True).sort_values("date").reset_index(drop=True)
    only_e0 = lambda t: t.tournament == "English Premier League"  # noqa: E731
    print(f"\n—— E1 变体（hl={hl}，只评测英超场次）——")
    print(f"{'cutoff':>12} | {'E0 单独':>30} | {'E0+E1 合训':>30}")
    for c in CUTOFFS:
        a = evaluate(e0, hl, c)
        b = evaluate(both, hl, c, test_filter=only_e0)
        print(f"{c:>12} | RPS {a['rps']:.4f} n={a['n']:>3} 跳{a['skipped']:>2} |"
              f" RPS {b['rps']:.4f} n={b['n']:>3} 跳{b['skipped']:>2}")
    print("采纳纪律：跳场归零 且 RPS 不变差（±0.001 内）才在 P2 默认并入 E1。")


def quick_scan():
    df = clubdata.load("E0", seasons=SEASONS)
    for hl in HL_GRID:
        vals = [evaluate(df, hl, c)["rps"] for c in ["2024-08-01", "2025-01-01"]]
        print(f"hl={hl:<5} 平均 RPS {np.mean(vals):.4f}")


if __name__ == "__main__":
    if "--quick" in sys.argv:
        quick_scan()
    elif "--e1" in sys.argv:
        hl = int(sys.argv[sys.argv.index("--e1") + 1]) if len(sys.argv) > sys.argv.index("--e1") + 1 else 180
        e1_variant(hl)
    else:
        best = full_scan()
        e1_variant(best)
