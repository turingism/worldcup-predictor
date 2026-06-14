"""
实验：概率校准检验 + 等温回归(Isotonic)后校准能否降低 RPS。

动机：Kimi 报告强调「校准优于准确率」——一个输出 60% 实际只发生 52% 的模型，
即便命中率高，长期 ROI 仍为负。我们检验本模型是否已校准，以及后校准是否有增益。

做法：样本外收集 (预测概率, 是否发生) 三类事件(主胜/平/客胜) 合并成二元校准样本，
  1) 可靠性分箱：每个预测概率区间，看实际发生频率，算 ECE(期望校准误差)；
  2) 用一半 cutoff 拟合 Isotonic，另一半验证后校准前后的 RPS/二元 Brier。
"""
from __future__ import annotations
import datetime as dt
import numpy as np
import pandas as pd

import data as datamod
from model import DixonColesModel
from backtest import select_test, _rps


def collect(df, cutoffs, horizon, half_life):
    """返回 DataFrame: 每场一行，含 [p_home,p_draw,p_away, outcome]。"""
    rows = []
    for cutoff in cutoffs:
        m = DixonColesModel(half_life_days=half_life).fit(df, verbose=False, as_of=cutoff)
        test = select_test(df, cutoff, horizon)
        for _, r in test.iterrows():
            try:
                pr = m.predict(r["home_team"], r["away_team"], neutral=bool(r["neutral"]))
            except KeyError:
                continue
            hs, as_ = int(r["home_score"]), int(r["away_score"])
            oc = 0 if hs > as_ else (1 if hs == as_ else 2)
            rows.append((pr["p_home"], pr["p_draw"], pr["p_away"], oc))
    return pd.DataFrame(rows, columns=["ph", "pd", "pa", "oc"])


def reliability(probs, hits, bins=10):
    """ECE + 分箱表。probs/hits 为一维二元校准样本。"""
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    out = []
    for i in range(bins):
        lo, hi = edges[i], edges[i + 1]
        msk = (probs >= lo) & (probs < hi) if i < bins - 1 else (probs >= lo) & (probs <= hi)
        if msk.sum() == 0:
            continue
        conf = probs[msk].mean(); freq = hits[msk].mean(); w = msk.sum()
        ece += w / len(probs) * abs(conf - freq)
        out.append((lo, hi, int(w), conf, freq))
    return ece, out


def to_binary(dfp):
    """三类预测 -> 二元校准样本 (预测某结果的概率, 该结果是否发生)。"""
    P = dfp[["ph", "pd", "pa"]].to_numpy()
    oc = dfp["oc"].to_numpy()
    probs = P.flatten()
    hits = np.zeros_like(probs)
    for k in range(3):
        hits[k::3] = (oc == k).astype(float)
    # 上面 flatten 是按行 [ph,pd,pa, ph,pd,pa,...]，对应 k=col
    probs = P.reshape(-1)
    hits = np.zeros(len(probs))
    idx = 0
    for row in range(len(oc)):
        for col in range(3):
            hits[idx] = 1.0 if oc[row] == col else 0.0
            idx += 1
    return probs, hits


def mean_rps(dfp):
    return np.mean([_rps(r.ph, r.pd, r.pa, int(r.oc)) for r in dfp.itertuples()])


if __name__ == "__main__":
    df = datamod.load_raw()
    half_life = 240
    horizon = 240
    train_cut = [dt.date(2024, 5, 1), dt.date(2024, 11, 1)]
    test_cut = [dt.date(2025, 5, 1), dt.date(2025, 11, 1)]

    print("收集训练集预测 …")
    tr = collect(df, train_cut, horizon, half_life)
    print("收集验证集预测 …")
    te = collect(df, test_cut, horizon, half_life)
    print(f"训练 {len(tr)} 场 / 验证 {len(te)} 场")

    # 整体校准
    pb, hb = to_binary(tr)
    ece, tbl = reliability(pb, hb)
    print(f"\n训练集 ECE = {ece*100:.2f}%（<5% 算良好；Kimi 行业基准 8-10%）")
    print(f"  {'区间':>12}{'样本':>7}{'预测均值':>9}{'实际频率':>9}")
    for lo, hi, w, conf, freq in tbl:
        print(f"  [{lo:.1f},{hi:.1f}){'':>2}{w:>7}{conf:>9.3f}{freq:>9.3f}")

    # 后校准：等温回归映射 预测概率->校准概率，验证集前后 RPS
    try:
        from sklearn.isotonic import IsotonicRegression
        iso = IsotonicRegression(out_of_bounds="clip").fit(pb, hb)
        base_rps = mean_rps(te)
        # 校准验证集三类概率后重新归一化
        cal = te.copy()
        M = cal[["ph", "pd", "pa"]].to_numpy()
        Mc = iso.predict(M.reshape(-1)).reshape(M.shape)
        Mc = Mc / Mc.sum(axis=1, keepdims=True)
        cal["ph"], cal["pd"], cal["pa"] = Mc[:, 0], Mc[:, 1], Mc[:, 2]
        cal_rps = mean_rps(cal)
        pbte, hbte = to_binary(te)
        ece_te, _ = reliability(pbte, hbte)
        pbc, hbc = to_binary(cal)
        ece_c, _ = reliability(pbc, hbc)
        print(f"\n验证集 ECE 未校准 = {ece_te*100:.2f}%  等温后 = {ece_c*100:.2f}%")
        print(f"验证集 RPS 未校准 = {base_rps:.4f}  等温后 = {cal_rps:.4f}"
              f"  ({(cal_rps-base_rps)*1e4:+.1f}e-4)")
        print("结论：RPS 下降才采用后校准；否则模型本身已足够校准。")
    except ImportError:
        print("无 sklearn，跳过等温后校准（仅看 ECE）。")
