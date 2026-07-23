"""C5 市场对标预计算：25-26 赛季 模型 vs B365 开盘/闭盘（Shin 去水）。

口径沿用 bt_club_market.py（hl=365、as-of 防泄漏训练、三方同场对比、Shin 去水、
只计模型可预测且开闭盘俱全场次、跳过数如实记录）；与该脚本的差异仅为覆盖窗：
分两段 cutoff 无重叠覆盖整季（bt 脚本为 3 cutoff × 180d 抽样窗），便于市场 Tab
展示整季对标。先验（红线）：预期市场全胜，本数据是「认清打不赢市场」的展示层，
禁止衍生投注建议。产物 data/club/market_<code>.json。用法：python3 club_market.py
"""
import json
import os
from datetime import datetime

import numpy as np
import pandas as pd

import clubdata
import devig
from bt_club_market import rps
from model import DixonColesModel

HL = 365.0
SEGMENTS = [("2025-08-01", "2026-01-01"), ("2026-01-01", "2026-07-01")]
SEASON_LABEL = "2025-26"
_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "club")


def build(code: str) -> dict:
    df = clubdata.load(code)
    acc = {k: {"rps": [], "hit": []} for k in ("model", "open", "close")}
    sk_model = sk_odds = 0
    sample_rows = []
    last_day = None
    for cut_s, end_s in SEGMENTS:
        cut, end = pd.Timestamp(cut_s), pd.Timestamp(end_s)
        m = DixonColesModel(half_life_days=HL).fit(df, verbose=False, as_of=cut)
        test = df[(df.date >= cut) & (df.date < end)]
        for r in test.itertuples():
            if r.home_team not in m.attack or r.away_team not in m.attack:
                sk_model += 1
                continue
            oc = [r.B365H, r.B365D, r.B365A, r.B365CH, r.B365CD, r.B365CA]
            if any(pd.isna(x) for x in oc):
                sk_odds += 1
                continue
            out = 0 if r.home_score > r.away_score else (1 if r.home_score == r.away_score else 2)
            pr = m.predict(r.home_team, r.away_team, neutral=False)
            probs = {"model": np.array([pr["p_home"], pr["p_draw"], pr["p_away"]]),
                     "open": devig.shin(*oc[:3]), "close": devig.shin(*oc[3:])}
            for k, p in probs.items():
                p = np.clip(p, 1e-9, 1)
                acc[k]["rps"].append(rps(p, out))
                acc[k]["hit"].append(int(np.argmax(p) == out))
            sample_rows.append({"date": str(r.date.date()),
                                "home": r.home_team, "away": r.away_team,
                                "score": f"{int(r.home_score)}-{int(r.away_score)}",
                                "out": out,
                                **{k: [round(float(x), 4) for x in probs[k]] for k in probs}})
            last_day = max(last_day or r.date, r.date)
    n = len(acc["model"]["rps"])
    summary = {k: {"rps": round(float(np.mean(v["rps"])), 4),
                   "hit": round(float(np.mean(v["hit"])), 4)} for k, v in acc.items()}
    # 展示样本 = 赛季末 7 天场次（末轮可能跨多日，单日过滤会漏场）
    last_str = str(last_day.date()) if last_day is not None else None
    if last_day is not None:
        lo = str((last_day - pd.Timedelta(days=6)).date())
        sample = [x for x in sample_rows if x["date"] >= lo]
        sample.sort(key=lambda x: (x["date"], x["home"]), reverse=True)
    else:
        sample = []
    return {"code": code, "season": SEASON_LABEL, "hl": HL, "devig": "shin",
            "segments": SEGMENTS, "n": n,
            "skipped_model": sk_model, "skipped_odds": sk_odds,
            "summary": summary,
            "sample": {"date": last_str, "rows": sample},
            "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "source": "football-data.co.uk（B365 开/闭盘）",
            "data_through": str(df.date.max().date())}


def main():
    for code in clubdata.FEEDER:
        out = build(code)
        path = os.path.join(_DIR, f"market_{code}.json")
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False)
        os.replace(tmp, path)
        s = out["summary"]
        print(f"[market] {code}: n={out['n']} (跳过 模型{out['skipped_model']}/"
              f"赔率{out['skipped_odds']}) RPS 模型{s['model']['rps']:.4f} "
              f"开盘{s['open']['rps']:.4f} 闭盘{s['close']['rps']:.4f} → {path}")


if __name__ == "__main__":
    main()
