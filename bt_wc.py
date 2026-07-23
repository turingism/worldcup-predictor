"""世界杯专项分层回测（P1-6，2026-07 新增）：把「全国际赛混合指标」拆开说清楚。

动机：主回测（backtest.py）混合大量预选赛/友谊赛/强弱悬殊场次，其 ~59% 命中率
**不能**当作世界杯正赛能力宣传。本脚本：

  1) rolling-origin / as-of，无未来泄漏（训练严格截断在评估窗之前）；
  2) 分层报告：世界杯正赛（2014/2018/2022/2026 各届独立 as-of）、其他大赛正赛、
     预选赛、友谊赛；
  3) 指标：RPS / LogLoss / 命中率 / Brier / ECE / 正确比分 LogLoss /
     净胜球离散度比（实际方差 vs 模型隐含方差，P1-7 欠离散诊断同源复现）；
  4) 分层均值给 bootstrap 95% CI（B=2000，固定种子）；
  5) 与 2026 世界杯闭盘赔率（data/odds.csv，DraftKings，Shin 去水）在**完全相同
     场次**上对标，模型按逐比赛日 as-of 重训（信息集对齐，不偷看）；
  6) `adoption_gate()`：生产参数采纳门槛的可执行版本。

用法：/opt/anaconda3/bin/python3 bt_wc.py [--fast]
"""
from __future__ import annotations
import argparse
import datetime as dt

import numpy as np
import pandas as pd

import config
import data as datamod
import devig
from model import MAX_GOALS, DixonColesModel

# 生产参数采纳门槛（项目铁律的可执行化）：候选相对基线 pooled RPS 需改善超过
# GATE_MIN_RPS_GAIN，且在最近一个 cutoff 上不回退超过 GATE_MAX_RECENT_REGRESS。
GATE_MIN_RPS_GAIN = 0.0008
GATE_MAX_RECENT_REGRESS = 0.0


def adoption_gate(base_pooled_rps: float, cand_pooled_rps: float,
                  base_recent_rps: float, cand_recent_rps: float) -> dict:
    """生产采纳判定。返回 {adopt: bool, reasons: [...]}——回测数字不过线就不进生产。"""
    reasons = []
    gain = base_pooled_rps - cand_pooled_rps
    if gain <= GATE_MIN_RPS_GAIN:
        reasons.append(f"pooled RPS 改善 {gain:+.5f} ≤ 门槛 {GATE_MIN_RPS_GAIN}")
    recent = cand_recent_rps - base_recent_rps
    if recent > GATE_MAX_RECENT_REGRESS:
        reasons.append(f"最近 cutoff 回退 {recent:+.5f} > {GATE_MAX_RECENT_REGRESS}")
    return {"adopt": not reasons, "reasons": reasons,
            "gain": gain, "recent_delta": recent}


def _margin_stats(M: np.ndarray):
    """比分矩阵 → (E[margin], Var[margin])。"""
    side = M.shape[0]
    idx = np.arange(side)
    margins = idx[:, None] - idx[None, :]
    mu = float((margins * M).sum())
    var = float(((margins - mu) ** 2 * M).sum())
    return mu, var


def eval_matches(model, test: pd.DataFrame) -> pd.DataFrame:
    """逐场评估 → DataFrame（每行一场，含各指标分量；聚合/分层/bootstrap 在外面做）。"""
    rows = []
    for _, r in test.iterrows():
        h, a = r["home_team"], r["away_team"]
        try:
            _, _, _, _, M = model.score_matrix(h, a, neutral=bool(r["neutral"]))
        except KeyError:
            continue
        idx = np.arange(M.shape[0])
        HH, AA = np.meshgrid(idx, idx, indexing="ij")
        ph = float(M[HH > AA].sum()); pdr = float(M[HH == AA].sum()); pa = float(M[HH < AA].sum())
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        outcome = 0 if hs > as_ else (1 if hs == as_ else 2)
        probs = np.array([ph, pdr, pa])
        cp1, cp2 = ph, ph + pdr
        o1 = 1.0 if outcome == 0 else 0.0
        o2 = 1.0 if outcome <= 1 else 0.0
        rps = 0.5 * ((cp1 - o1) ** 2 + (cp2 - o2) ** 2)
        onehot = np.eye(3)[outcome]
        brier = float(((probs - onehot) ** 2).sum())
        p_score = float(M[min(hs, MAX_GOALS), min(as_, MAX_GOALS)])
        mu, var = _margin_stats(M)
        rows.append({
            "date": r["date"], "tournament": r["tournament"],
            "home": h, "away": a, "hs": hs, "as": as_,
            "rps": rps, "logloss": -np.log(max(probs[outcome], 1e-12)),
            "hit": int(np.argmax(probs) == outcome), "brier": brier,
            "conf": float(probs.max()),
            "score_logloss": -np.log(max(p_score, 1e-12)),
            "margin_err2": (hs - as_ - mu) ** 2, "margin_var": var,
            "ph": ph, "pd": pdr, "pa": pa, "outcome": outcome,
        })
    return pd.DataFrame(rows)


def ece(df: pd.DataFrame, bins: int = 10) -> float:
    """argmax 置信度 ECE。"""
    if not len(df):
        return float("nan")
    edges = np.linspace(1 / 3, 1.0, bins + 1)
    tot = 0.0
    for i in range(bins):
        m = (df["conf"] >= edges[i]) & (df["conf"] < edges[i + 1] + (1e-9 if i == bins - 1 else 0))
        if m.sum() == 0:
            continue
        tot += m.sum() / len(df) * abs(df.loc[m, "hit"].mean() - df.loc[m, "conf"].mean())
    return float(tot)


def summarize(df: pd.DataFrame, boot: int = 2000, seed: int = 20260719) -> dict:
    if not len(df):
        return {"n": 0}
    rng = np.random.default_rng(seed)
    n = len(df)
    rps = df["rps"].to_numpy()
    hit = df["hit"].to_numpy()
    bs_rps = np.array([rps[rng.integers(0, n, n)].mean() for _ in range(boot)])
    bs_hit = np.array([hit[rng.integers(0, n, n)].mean() for _ in range(boot)])
    return {
        "n": n, "rps": float(rps.mean()),
        "rps_ci": [float(np.percentile(bs_rps, 2.5)), float(np.percentile(bs_rps, 97.5))],
        "logloss": float(df["logloss"].mean()), "acc": float(hit.mean()),
        "acc_ci": [float(np.percentile(bs_hit, 2.5)), float(np.percentile(bs_hit, 97.5))],
        "brier": float(df["brier"].mean()), "ece": ece(df),
        "score_logloss": float(df["score_logloss"].mean()),
        # 净胜球离散度比 >1 = 实际比模型隐含更散（欠离散/尾部偏瘦证据）
        "margin_disp_ratio": float(df["margin_err2"].mean() / df["margin_var"].mean()),
    }


def fmt(name, s):
    if not s.get("n"):
        return f"  {name:<14} n=0"
    return (f"  {name:<14} n={s['n']:>4}  RPS={s['rps']:.4f} "
            f"[{s['rps_ci'][0]:.4f},{s['rps_ci'][1]:.4f}]  LL={s['logloss']:.4f} "
            f"Acc={s['acc']:.3f} [{s['acc_ci'][0]:.3f},{s['acc_ci'][1]:.3f}]  "
            f"Brier={s['brier']:.4f} ECE={s['ece']:.4f}  "
            f"比分LL={s['score_logloss']:.3f}  离散比={s['margin_disp_ratio']:.2f}")


# 各届世界杯正赛评估窗（as_of=开赛前，杜绝时间泄漏）
WC_WINDOWS = [
    ("WC2014", dt.date(2014, 6, 1), "2014-06-12", "2014-07-14"),
    ("WC2018", dt.date(2018, 6, 1), "2018-06-14", "2018-07-16"),
    ("WC2022", dt.date(2022, 11, 1), "2022-11-20", "2022-12-19"),
    ("WC2026", dt.date(2026, 6, 1), "2026-06-11", "2026-07-20"),
]


def wc_finals_eval(df, fast=False):
    """各届世界杯正赛 as-of 评估（正赛=精确 tournament == 'FIFA World Cup'）。"""
    pl = datamod.played(df)
    out = {}
    frames = []
    for name, cutoff, lo, hi in WC_WINDOWS:
        m = DixonColesModel(half_life_days=config.NATIONAL_HALF_LIFE).fit(
            df, verbose=False, as_of=cutoff)
        test = pl[(pl["tournament"] == "FIFA World Cup")
                  & (pl["date"] >= lo) & (pl["date"] <= hi)]
        ev = eval_matches(m, test)
        ev["edition"] = name
        frames.append(ev)
        out[name] = summarize(ev)
    pooled = pd.concat(frames, ignore_index=True)
    out["WC_pooled"] = summarize(pooled)
    return out, pooled


def tier_eval(df):
    """近期窗口分层：其他大赛正赛 / 预选赛 / 友谊赛（rolling-origin 三 cutoff）。"""
    pl = datamod.played(df)
    cutoffs = [dt.date(2023, 6, 1), dt.date(2024, 11, 1), dt.date(2025, 8, 1)]
    frames = []
    for cutoff in cutoffs:
        m = DixonColesModel(half_life_days=config.NATIONAL_HALF_LIFE).fit(
            df, verbose=False, as_of=cutoff)
        lo = pd.Timestamp(cutoff)
        hi = lo + pd.Timedelta(days=270)
        test = pl[(pl["date"] > lo) & (pl["date"] <= hi)]
        frames.append(eval_matches(m, test))
    allm = pd.concat(frames, ignore_index=True)
    allm["tier"] = allm["tournament"].map(datamod.comp_tier)
    is_wc = allm["tournament"] == "FIFA World Cup"
    return {
        "major_nonWC": summarize(allm[(allm["tier"] == "major") & ~is_wc]),
        "qualification": summarize(allm[allm["tier"] == "qualification"]),
        "friendly": summarize(allm[allm["tier"] == "friendly"]),
        "all_mixed": summarize(allm),
    }


def market_eval(df):
    """与 2026 世界杯闭盘（Shin 去水）在完全相同场次对标；模型按比赛日 as-of 重训。"""
    odds = pd.read_csv(datamod.DATA_PATH.replace("results.csv", "odds.csv"))
    odds["date"] = pd.to_datetime(odds["date"])
    pl = datamod.played(df)
    wc = pl[(pl["tournament"] == "FIFA World Cup") & (pl["date"].dt.year == 2026)]
    model_cache = {}
    rows_m, rows_k = [], []
    for _, o in odds.iterrows():
        if not (o[["odds_1", "odds_x", "odds_2"]].notna().all()):
            continue
        hit = wc[(wc["date"] - o["date"]).abs() <= pd.Timedelta(days=1)]
        hit = hit[((hit["home_team"] == o["home_team"]) & (hit["away_team"] == o["away_team"])) |
                  ((hit["home_team"] == o["away_team"]) & (hit["away_team"] == o["home_team"]))]
        if not len(hit):
            continue
        r = hit.iloc[0]
        as_of = r["date"].date()                      # 比赛日 as-of：训练含当日之前全部数据
        if as_of not in model_cache:
            model_cache[as_of] = DixonColesModel(
                half_life_days=config.NATIONAL_HALF_LIFE).fit(
                df, verbose=False, as_of=as_of - dt.timedelta(days=1))
        ev = eval_matches(model_cache[as_of], hit.iloc[[0]])
        if not len(ev):
            continue
        rows_m.append(ev.iloc[0])
        # 闭盘 Shin 去水（odds 行主客序与 odds.csv 一致；若与 results 反序需翻转）
        p = devig.shin_n(np.array([o["odds_1"], o["odds_x"], o["odds_2"]], dtype=float))
        if r["home_team"] != o["home_team"]:
            p = p[::-1]
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        outcome = 0 if hs > as_ else (1 if hs == as_ else 2)
        cp1, cp2 = p[0], p[0] + p[1]
        o1 = 1.0 if outcome == 0 else 0.0
        o2 = 1.0 if outcome <= 1 else 0.0
        rows_k.append({"rps": 0.5 * ((cp1 - o1) ** 2 + (cp2 - o2) ** 2),
                       "logloss": -np.log(max(p[outcome], 1e-12)),
                       "hit": int(np.argmax(p) == outcome), "brier": float(((p - np.eye(3)[outcome]) ** 2).sum()),
                       "conf": float(p.max()), "score_logloss": np.nan,
                       "margin_err2": np.nan, "margin_var": np.nan})
    dm = pd.DataFrame(rows_m); dk = pd.DataFrame(rows_k)
    res = {"n": len(dm)}
    if len(dm):
        res["model"] = {"rps": float(dm["rps"].mean()), "logloss": float(dm["logloss"].mean()),
                        "acc": float(dm["hit"].mean())}
        res["market_close"] = {"rps": float(dk["rps"].mean()), "logloss": float(dk["logloss"].mean()),
                               "acc": float(dk["hit"].mean())}
        d = dm["rps"].to_numpy() - dk["rps"].to_numpy()
        rng = np.random.default_rng(20260719)
        bs = np.array([d[rng.integers(0, len(d), len(d))].mean() for _ in range(2000)])
        res["delta_rps_model_minus_market"] = float(d.mean())
        res["delta_ci"] = [float(np.percentile(bs, 2.5)), float(np.percentile(bs, 97.5))]
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fast", action="store_true", help="跳过市场对标（省逐日重训）")
    args = ap.parse_args()
    df = datamod.load_raw()

    print("== 世界杯正赛（各届 as-of，无泄漏） ==")
    wc, _ = wc_finals_eval(df)
    for k in ("WC2014", "WC2018", "WC2022", "WC2026", "WC_pooled"):
        print(fmt(k, wc[k]))

    print("\n== 其他分层（cutoffs 2023-06/2024-11/2025-08，horizon 270d） ==")
    tiers = tier_eval(df)
    for k in ("major_nonWC", "qualification", "friendly", "all_mixed"):
        print(fmt(k, tiers[k]))
    print("\n  ⚠ 口径提醒：『全国际赛 ~59-60% 命中』来自 all_mixed（含预选赛/友谊赛/强弱悬殊），")
    print("    不代表世界杯正赛能力——引用命中率必须注明分层（WC_pooled 才是世界杯口径）。")

    if not args.fast:
        print("\n== 2026 世界杯：模型 vs 闭盘（同场次，比赛日 as-of） ==")
        mk = market_eval(df)
        if mk.get("n"):
            print(f"  n={mk['n']}  模型 RPS={mk['model']['rps']:.4f} Acc={mk['model']['acc']:.3f}"
                  f"  闭盘 RPS={mk['market_close']['rps']:.4f} Acc={mk['market_close']['acc']:.3f}")
            print(f"  ΔRPS(模型−闭盘)={mk['delta_rps_model_minus_market']:+.4f} "
                  f"95%CI[{mk['delta_ci'][0]:+.4f},{mk['delta_ci'][1]:+.4f}]"
                  f"  （正=模型更差；诚实先验：模型不敌闭盘）")
        else:
            print("  无可对标场次（odds.csv 无数据）")


if __name__ == "__main__":
    main()
