# Repository summary: World Cup prediction analytics module.
"""
首发增益记分卡（lineup_ledger）：对已完赛比赛补算「纯 DC 基线」与「首发确认版」两套预测，
和真实赛果对比，累积统计——加入球员首发数据，到底有没有让预测更准？

定位：独立旁路账本（类比 xuanxue_board / clv），**绝不回写 verify 主验证账本**、不碰 GLM。

诚实口径（关键）：
  - 用的是赛前 1 小时公布的首发事实（完赛后 ESPN 仍保留 rosters），**不含赛果** → 与
    verify 的 retro 回溯同口径，不构成偷看。
  - pre / post 用**同一生产模型**，只差 avail_override → 两者差异纯来自首发输入，是「首发层的
    内部 A/B 增量」，不是样本外绝对精度声明（已标注）。
  - 只有「登记关键人确有缺阵」的场次（mods 非空）才贡献信息；其余 pre==post，跳过。
  - 早期有效样本极小（取决于 availability.json 登记了多少队），结论不可靠，UI / CLI 须标注。
"""
from __future__ import annotations
import datetime as dt

import numpy as np

import adjust
import lineups
import teams_zh


def _rps(ph, pd_, pa, outcome):
    """有序三分类 [主胜, 平, 客胜] 的 RPS（与 backtest._rps 同口径）。outcome ∈ {0,1,2}。"""
    cp1, cp2 = ph, ph + pd_
    co1 = 1.0 if outcome == 0 else 0.0
    co2 = 1.0 if outcome <= 1 else 0.0
    return 0.5 * ((cp1 - co1) ** 2 + (cp2 - co2) ** 2)


def _wdl(r):
    return r["p_home"], r["p_draw"], r["p_away"]


def build_scorecard(model, days_back: int = 12, avail: dict | None = None) -> dict:
    """扫描最近 days_back 天 ESPN 已完赛场次；对登记关键人有缺阵的场次补算 pre/post 对比。

    返回 {n, pre, post, rows, scanned, skipped_no_mods, ...}。
      pre / post = {"rps":, "hit":}（hit=胜平负 argmax 命中率）。
    """
    if avail is None:
        avail = adjust.load_availability()
    today = dt.date.today()
    lo = (today - dt.timedelta(days=days_back)).strftime("%Y%m%d")
    hi = (today + dt.timedelta(days=1)).strftime("%Y%m%d")
    sb = lineups._fetch_json(f"{lineups.ESPN_BASE}/scoreboard?dates={lo}-{hi}")

    rows = []
    pre_rps = post_rps = 0.0
    pre_hit = post_hit = 0
    scanned = skipped = 0

    for e in sb.get("events", []):
        st = e.get("status", {}).get("type", {}).get("state")
        if st != "post":
            continue
        comp = e.get("competitions", [{}])[0]
        cs = comp.get("competitors", [])
        if len(cs) != 2:
            continue
        # ESPN：competitor.homeAway 标主客；score 为比分
        try:
            by_side = {c.get("homeAway"): c for c in cs}
            ch, ca = by_side["home"], by_side["away"]
            home = lineups._espn_to_team(ch.get("team", {}).get("displayName", ""))
            away = lineups._espn_to_team(ca.get("team", {}).get("displayName", ""))
            hs, as_ = int(ch.get("score")), int(ca.get("score"))
        except (KeyError, TypeError, ValueError):
            continue
        try:
            h_en = model.resolve(home); a_en = model.resolve(away)
        except KeyError:
            continue
        scanned += 1

        lm = lineups.match_availability(h_en, a_en, event_id=e["id"], avail=avail)
        mods = lm.get("mods") or {}
        if not mods:                       # 无登记关键人缺阵 → pre==post，无信息
            skipped += 1
            continue

        try:
            r_pre = model.predict(h_en, a_en, neutral=True, avail_override={})
            r_post = model.predict(h_en, a_en, neutral=True, avail_override=mods)
        except KeyError:
            continue
        outcome = 0 if hs > as_ else (1 if hs == as_ else 2)
        rp_pre = _rps(*_wdl(r_pre), outcome)
        rp_post = _rps(*_wdl(r_post), outcome)
        hit_pre = int(np.argmax(_wdl(r_pre)) == outcome)
        hit_post = int(np.argmax(_wdl(r_post)) == outcome)
        pre_rps += rp_pre; post_rps += rp_post
        pre_hit += hit_pre; post_hit += hit_post

        absentees = [p["player"] for t in lm["teams"].values() for p in t["players"]
                     if p["lineup_status"] == "absent"]
        rows.append({
            "home": teams_zh.disp(h_en), "away": teams_zh.disp(a_en),
            "actual": f"{hs}-{as_}",
            "pre_home": round(r_pre["p_home"], 3), "post_home": round(r_post["p_home"], 3),
            "rps_pre": round(rp_pre, 4), "rps_post": round(rp_post, 4),
            "rps_delta": round(rp_post - rp_pre, 4),
            "absentees": absentees,
        })

    n = len(rows)
    out = {
        "n": n, "scanned": scanned, "skipped_no_mods": skipped,
        "days_back": days_back,
        "pre": {"rps": round(pre_rps / n, 4) if n else None,
                "hit": round(pre_hit / n, 3) if n else None},
        "post": {"rps": round(post_rps / n, 4) if n else None,
                 "hit": round(post_hit / n, 3) if n else None},
        "rps_improve": round((pre_rps - post_rps) / n, 4) if n else None,  # >0 = 首发版更准
        "rows": rows,
    }
    return out


if __name__ == "__main__":
    from predict import get_model
    m = get_model(use_cache=True, half_life=730, verbose=False)
    sc = build_scorecard(m, days_back=12)
    print(f"扫描完赛 {sc['scanned']} 场，有缺阵信息 {sc['n']} 场（{sc['skipped_no_mods']} 场无登记缺阵跳过）")
    if sc["n"]:
        print(f"  纯DC基线   : RPS {sc['pre']['rps']}  命中 {sc['pre']['hit']*100:.0f}%")
        print(f"  首发确认版 : RPS {sc['post']['rps']}  命中 {sc['post']['hit']*100:.0f}%")
        print(f"  RPS 改善   : {sc['rps_improve']:+.4f}（>0=首发版更准；小样本仅供参考）")
        for r in sc["rows"]:
            print(f"    {r['home']} {r['actual']} {r['away']} | 主胜 {r['pre_home']:.0%}→{r['post_home']:.0%} "
                  f"| RPSΔ {r['rps_delta']:+.4f} | 缺阵 {','.join(r['absentees']) or '—'}")
