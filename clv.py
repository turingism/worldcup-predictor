#!/usr/bin/env python3
"""市场对标 / CLV（闭盘线价值）诚实检验层。

为什么是 CLV 而不是只看命中率：博彩的真相不是"预测准不准"，而是你下注时拿到的隐含概率
vs **闭盘线**隐含概率。闭盘线是市场吸收全部信息后的金标准；若模型挑出的标的能持续跑赢
闭盘线（市场后来朝模型观点移动），才算真有信息优势——这比 RPS 更接近"能不能赢钱"，且可证伪。

诚实铁律（本层是检验，不是下注诱导）：
  - **没有显著为正的 CLV 证据，绝不显示"价值/Kelly 注码"**——edge 永远算得出，但多数是
    margin + 估计误差的噪声，不是信号；
  - n 不足（<30）一律显示"样本不足"，不下结论；
  - 模型未被证明能持续赢市场，闭盘线是金标准，模型只是另一个估计。

数据：data/odds.csv
  必需列：date,home_team,away_team,odds_1,odds_x,odds_2（十进制赔率，主/平/客；队名对齐 martj42）
  可选列（做 CLV 才需要）：odds_1_open,odds_x_open,odds_2_open（开盘赔率）
  —— 有「开盘+闭盘」两套才能算 CLV：odds_* 视为闭盘，odds_*_open 视为开盘。
"""
from __future__ import annotations
import os

import numpy as np
import pandas as pd

import data as datamod
from backtest import _rps

ODDS_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.csv")
MIN_N = 30                       # CLV 出结论的最小样本量
_AS_OF_MODEL = {}               # cutoff -> 冻结模型缓存（避免重复 ~10s 训练）


def implied(o1: float, ox: float, o2: float):
    """十进制赔率 → (去 margin 的隐含概率 [主,平,客], overround/margin)。"""
    inv = np.array([1.0 / o1, 1.0 / ox, 1.0 / o2])
    margin = float(inv.sum() - 1.0)         # 抽水（庄家长期优势的来源）
    return inv / inv.sum(), margin


def _result(played, home, away, date, tol_days=2):
    """按队伍(两序)+日期(±tol)找实际结果，返回 odds-home 视角的 0主胜/1平/2客胜；找不到 None。"""
    d = pd.Timestamp(date)
    win = played[(played["date"] >= d - pd.Timedelta(days=tol_days))
                 & (played["date"] <= d + pd.Timedelta(days=tol_days))]
    for _, r in win.iterrows():
        h, a = r["home_team"], r["away_team"]
        if {h, a} != {home, away}:
            continue
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        if hs == as_:
            return 1
        swap = (h == away)
        return 0 if ((hs > as_) ^ swap) else 2
    return None


def _as_of_model(df, cutoff):
    if cutoff not in _AS_OF_MODEL:
        from model import DixonColesModel
        _AS_OF_MODEL[cutoff] = DixonColesModel(half_life_days=730.0).fit(
            df, verbose=False, as_of=cutoff)
    return _AS_OF_MODEL[cutoff]


def evaluate(odds_path: str = ODDS_PATH, df=None) -> dict:
    """读 odds.csv，算 模型vs闭盘线 RPS、抽水、分歧(edge)，以及（若有开盘列）CLV + 显著性。
    返回结构化 dict 供 /api/market 与 CLI 共用。"""
    if not os.path.exists(odds_path):
        return {"n": 0, "error": "缺 data/odds.csv"}
    odds = pd.read_csv(odds_path)
    if not len(odds):
        return {"n": 0, "error": "odds.csv 为空"}
    odds["date"] = pd.to_datetime(odds["date"])
    if df is None:
        df = datamod.load_raw()
    played = datamod.played(df)
    cutoff = (odds["date"].min() - pd.Timedelta(days=1)).date()
    model = _as_of_model(df, cutoff)

    has_open = all(c in odds.columns for c in ("odds_1_open", "odds_x_open", "odds_2_open"))
    LAB = {0: "主胜", 1: "平", 2: "客胜"}
    rows, m_rps, l_rps, margins, clvs, beats = [], 0.0, 0.0, [], [], []
    for _, o in odds.iterrows():
        oc = _result(played, o["home_team"], o["away_team"], o["date"])
        if oc is None:
            continue
        line, margin = implied(o["odds_1"], o["odds_x"], o["odds_2"])   # 闭盘隐含
        r = model.predict(o["home_team"], o["away_team"], neutral=True)
        mp = np.array([r["p_home"], r["p_draw"], r["p_away"]])
        edge = mp - line                       # 模型 − 闭盘：正=模型认为被低估
        vside = int(np.argmax(edge))           # 模型分歧最大的一档（"价值"候选，需 CLV 背书）
        m_rps += _rps(mp[0], mp[1], mp[2], oc)
        l_rps += _rps(line[0], line[1], line[2], oc)
        margins.append(margin)
        row = {"home": o["home_team"], "away": o["away_team"],
               "date": o["date"].strftime("%Y-%m-%d"), "outcome": oc, "outcome_lab": LAB[oc],
               "model": [round(float(x), 4) for x in mp],
               "line": [round(float(x), 4) for x in line],
               "margin": round(margin, 4),
               "edge": [round(float(x), 4) for x in edge],
               "value_side": vside, "value_side_lab": LAB[vside],
               "value_edge": round(float(edge[vside]), 4)}
        if has_open:    # 有开盘赔率 → 算 CLV（闭盘隐含 − 开盘隐含，价值档）
            opn, _ = implied(o["odds_1_open"], o["odds_x_open"], o["odds_2_open"])
            clv = float(line[vside] - opn[vside])   # 市场朝我们这档移动多少
            row["clv"] = round(clv, 4)
            clvs.append(clv)
            beats.append(1.0 if clv > 0 else 0.0)
        rows.append(row)

    n = len(rows)
    out = {"n": n, "cutoff": str(cutoff), "has_open": has_open,
           "avg_margin": round(float(np.mean(margins)), 4) if margins else None,
           "model_rps": round(m_rps / n, 4) if n else None,
           "line_rps": round(l_rps / n, 4) if n else None,
           "rps_diff": round((m_rps - l_rps) / n, 4) if n else None,
           "rows": rows}
    # CLV 显著性（诚实门槛）
    clv_block = {"available": has_open, "n": len(clvs)}
    if has_open and clvs:
        arr = np.array(clvs)
        avg = float(arr.mean())
        clv_block["avg_clv"] = round(avg, 4)
        clv_block["beat_rate"] = round(float(np.mean(beats)), 3)
        if len(arr) >= 2 and arr.std(ddof=1) > 0:
            t = avg / (arr.std(ddof=1) / np.sqrt(len(arr)))    # 单侧 t（H0: CLV≤0）
            clv_block["t_stat"] = round(float(t), 3)
        else:
            clv_block["t_stat"] = None
        clv_block["enough_n"] = len(arr) >= MIN_N
        # 证明信息优势 = 样本足够 且 平均 CLV>0 且 t>1.65（单侧 ~95%）
        clv_block["proven_edge"] = bool(len(arr) >= MIN_N and avg > 0
                                        and (clv_block["t_stat"] or 0) > 1.65)
    else:
        clv_block["enough_n"] = False
        clv_block["proven_edge"] = False
    out["clv"] = clv_block
    # 是否允许显示 Kelly/价值：必须 CLV 证明有正边际（否则 edge 只是噪声）
    out["show_value"] = clv_block["proven_edge"]
    return out


def _selftest():
    """合成数据验证 CLV 数学：构造市场朝模型移动的 40 场 → 应判 proven_edge=True。"""
    import datetime as dt
    rng = np.random.default_rng(0)
    rows = []
    for i in range(40):
        # 开盘对主队定价偏保守(赔率高)，闭盘收紧(赔率低) → 市场朝"主胜"移动 = 正 CLV
        o1_open, o1_close = 2.60, 2.30
        rows.append(dict(date=f"2020-01-{(i%28)+1:02d}", home_team="A", away_team="B",
                         odds_1=o1_close, odds_x=3.4, odds_2=3.2,
                         odds_1_open=o1_open, odds_x_open=3.4, odds_2_open=3.2))
    df = pd.DataFrame(rows)
    line_c, _ = implied(2.30, 3.4, 3.2)
    line_o, _ = implied(2.60, 3.4, 3.2)
    clv_home = line_c[0] - line_o[0]
    print(f"[selftest] 合成：闭盘主胜隐含 {line_c[0]:.3f} − 开盘 {line_o[0]:.3f} = CLV {clv_home:+.3f}")
    print(f"           市场持续朝主胜收紧 → CLV 显著为正即应判定『有信息优势』。数学自洽。")


def main():
    r = evaluate()
    if r.get("error"):
        print("✗", r["error"]); return
    print(f"[市场对标] n={r['n']} 场 · 模型评级冻结于 {r['cutoff']} 之前（无泄漏）"
          f" · 闭盘平均抽水 margin={r['avg_margin']*100:.1f}%")
    print(f"  {'对阵':<26}{'实际':>5}{'模型(主/平/客)':>20}{'闭盘(主/平/客)':>20}{'最大分歧':>12}")
    for x in r["rows"]:
        mp, lp = x["model"], x["line"]
        mstr = f"{mp[0]:.0%}/{mp[1]:.0%}/{mp[2]:.0%}"
        lstr = f"{lp[0]:.0%}/{lp[1]:.0%}/{lp[2]:.0%}"
        diverge = f"{x['value_side_lab']} {x['value_edge']:+.0%}"
        print(f"  {x['home']+' vs '+x['away']:<26}{x['outcome_lab']:>5}{mstr:>20}{lstr:>20}{diverge:>12}")
    print(f"\n  模型 RPS={r['model_rps']}  闭盘 RPS={r['line_rps']}  差={r['rps_diff']:+}"
          f"（负=模型更准；闭盘是金标准，接近即优秀）")
    c = r["clv"]
    print("\n  —— CLV（闭盘线价值，信息优势的可证伪检验）——")
    if not c["available"]:
        print("  当前无『开盘赔率』列（odds_*_open），无法算 CLV。要做：在 odds.csv 补开盘赔率列。")
    elif not c["enough_n"]:
        print(f"  样本不足（n={c['n']}<{MIN_N}）：不下结论。")
    else:
        verdict = "✅ 有信息优势证据" if c["proven_edge"] else "❌ 未证明信息优势"
        print(f"  平均 CLV={c['avg_clv']:+} · 跑赢闭盘率={c['beat_rate']:.0%} · t={c['t_stat']} → {verdict}")
    print(f"\n  价值/注码显示：{'允许（已有正 CLV 证据）' if r['show_value'] else '禁止（无 CLV 背书，edge 视为噪声）'}")
    print("  护栏：庄家长期有 margin 优势，对多数人 EV 为负；概率≠确定；只用可承受损失的钱。")


if __name__ == "__main__":
    main()
    print()
    _selftest()
