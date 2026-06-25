"""让球预测命中率擂台（只读分析层）。

复用 `verify.py` 已冻结的赛前比分矩阵（`data/predictions.json`，开球前冻结、含完整 `matrix`），
对每场**已完赛**推导【当时赛前】的让球预测并用真实赛果结算，统计两个可证伪指标：

  1) 竞彩让球（强队让 1 球）argmax 命中率 —— 模型选 让胜/让平/让负 中概率最高者，是否打出；
     对照基线「永远押最常见的让球赛果」，看模型让球方向有没有信息量。
  2) 亚盘「模型公平盘」校准 —— 模型每场给一个公平让球档（赛前称≈五五开），统计强队在该档的
     **实际打出(cover)率**与模型预测打出率的差，检验"公平盘"是不是真公平（校准，非命中）。

铁律：**纯只读**——绝不写 verify 主账本、绝不碰 GLM。让球预测取自赛前冻结矩阵 = 模型赛前本就
会给的结论（matrix 已是 as_of 冻结，比 xuanxue 擂台更严格不偷看）。早期样本小，前端须标注。
"""
import numpy as np

import espn_odds
import manager
import verify


def _jc_probs(mp, fav_is_home):
    """竞彩让球（强队让 1 球）三向概率：让胜(净胜≥2)/让平(净胜=1)/让负(净胜≤0)。
    复用 manager.jc_handicap，映射成中文键供逐场结算。"""
    jc = manager.jc_handicap(mp, fav_is_home)
    return {"让胜": jc["win"], "让平": jc["draw"], "让负": jc["lose"]}


def _jc_actual(real_margin, line=1):
    """真实净胜（站强队角度）→ 竞彩让球结算桶。"""
    return "让胜" if real_margin > line else ("让平" if real_margin == line else "让负")


def _cover(real_margin, line):
    """强队在让 line 球盘的结算：'cover'(赢盘)/'push'(走水)/'lose'(输盘)。"""
    adj = real_margin - line
    return "cover" if adj > 1e-9 else ("lose" if adj < -1e-9 else "push")


def _wilson(k, n, z=1.96):
    """命中率 95% Wilson 区间（小样本稳健，与 xuanxue_board 同口径）。"""
    if n == 0:
        return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (p, max(0.0, c - h), min(1.0, c + h))


def build(sim, df, market_lines=None, timeline=None):
    """对已完赛逐场结算让球预测，返回 {rows, jc, asian, buckets, vs_market, n}。纯只读。
    market_lines（可选）= espn_odds.load_handicap_lines() 的市场闭盘让球线，用于「模型 vs 市场谁更准」。
    timeline（可选）= espn_odds.load_handicap_timeline() 的开盘/闭盘时间线，用于让球 CLV。"""
    preds = verify.load_ledger()
    done = verify._completed(sim, df)
    if market_lines is None:
        market_lines = espn_odds.load_handicap_lines()
    if timeline is None:
        timeline = espn_odds.load_handicap_timeline()
    rows = []
    jc_hits = 0
    jc_actuals = {"让胜": 0, "让平": 0, "让负": 0}
    buckets = {}                  # 分桶命中：key -> [n, hits]（stage 维 + 强弱维）

    def _bump(dim, key, hit):
        b = buckets.setdefault(dim, {})
        cell = b.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += int(hit)
    cover_pred_sum = 0.0      # Σ 模型预测的公平盘打出率
    cover_real = 0            # 实际打出(cover)数（不含走水）
    cover_decided = 0         # 非走水的场次数（校准分母）
    brier_sum = 0.0           # 公平盘 cover 的 Brier（仅非走水场）
    # 模型 vs 市场闭盘线：跟模型背离方下注能否打赢市场线（价值金标准）+ 双方线对实际净胜的 MAE
    vm = {"n": 0, "edge_w": 0, "edge_l": 0, "edge_push": 0, "agree": 0,
          "mae_model": 0.0, "mae_market": 0.0, "closer_model": 0, "closer_market": 0, "tie": 0,
          "mae_model_em": 0.0, "em_closer": 0, "em_worse": 0,   # 模型期望净胜(连续)对标市场
          "clv_n": 0, "clv_sum": 0.0, "clv_pos": 0}             # 让球 CLV（开盘→闭盘）
    for c in done:
        e = preds.get(c["key"])
        if not e or not e.get("matrix"):
            continue
        gh, ga = c["gh"], c["ga"]
        if (e["home"], e["away"]) != (c["home"], c["away"]):   # 真实比分对齐账本主客序
            gh, ga = ga, gh
        M = np.array(e["matrix"], dtype=float)
        mp = manager._margin_pmf(M)
        fav_is_home = e["p_home"] >= e["p_away"]
        fav_team = e["home"] if fav_is_home else e["away"]
        dog_team = e["away"] if fav_is_home else e["home"]
        real_margin = (gh - ga) if fav_is_home else (ga - gh)

        # —— 竞彩让球命中（让球线按本场期望净胜动态定，非写死让1）——
        csl = manager.csl_handicap(mp, fav_is_home)
        jc_line = csl["line"]
        jc_pick = csl["verdict"]                       # 该场让 jc_line 球下的 argmax(让胜/让平/让负)
        jc_act = _jc_actual(real_margin, jc_line)
        jc_hit = jc_pick == jc_act
        jc_hits += jc_hit
        jc_actuals[jc_act] += 1
        # 分桶：① 阶段（小组赛/淘汰赛）② 强队赛前实力档（按 fav 胜率）
        _bump("stage", "小组赛" if e["stage"] == "group" else "淘汰赛", jc_hit)
        fav_win = max(e["p_home"], e["p_away"])
        sb = "大热(≥70%)" if fav_win >= 0.70 else ("中等(55–70%)" if fav_win >= 0.55 else "接近(<55%)")
        _bump("strength", sb, jc_hit)

        # —— 亚盘公平盘校准 ——
        hc = manager.handicap_conclusion(mp, fav_is_home, fav_team, dog_team)
        fair = hc["fair_line"]
        fs = next(s for s in hc["lines"] if abs(s["line"] - fair) < 1e-9)
        # 校准须 apples-to-apples：实际打出率排除走水，故预测也条件在非走水上 = win/(win+lose)。
        denom = fs["win"] + fs["lose"]
        pred_cover = fs["win"] / denom if denom > 1e-9 else 0.5
        res = _cover(real_margin, fair)
        if res != "push":
            cover_decided += 1
            hit_cover = 1 if res == "cover" else 0
            cover_real += hit_cover
            cover_pred_sum += pred_cover
            brier_sum += (pred_cover - hit_cover) ** 2

        # —— 模型 vs 市场闭盘让球线 ——
        mkt_lean = None
        hkey = espn_odds._hc_key(e["home"], e["away"])
        ml = market_lines.get(hkey)
        # 模型期望净胜（连续，站强队角度）：Σ k·P(净胜=k)，不受让球档离散化惩罚
        em_home = float(sum(k * p for k, p in mp.items()))   # cast 防 np.float64 渗进 JSON
        exp_margin = em_home if fav_is_home else -em_home
        if ml and (ml.get("fav_is_home") == fav_is_home):   # 市场与模型强弱判断一致才比
            market_line = ml["fav_line"]
            vm["n"] += 1
            vm["mae_model"] += abs(fair - real_margin)
            vm["mae_market"] += abs(market_line - real_margin)
            vm["mae_model_em"] += abs(exp_margin - real_margin)
            if abs(exp_margin - real_margin) < abs(market_line - real_margin) - 1e-9:
                vm["em_closer"] += 1
            else:
                vm["em_worse"] += 1
            dm, dk = abs(fair - real_margin), abs(market_line - real_margin)
            if dm < dk - 1e-9: vm["closer_model"] += 1
            elif dk < dm - 1e-9: vm["closer_market"] += 1
            else: vm["tie"] += 1
            # —— 让球 CLV：模型在开盘相对市场的方向，闭盘是否朝模型移动（开盘线今起累积）——
            tl = timeline.get(hkey)
            if tl and tl.get("open_line") is not None and tl.get("close_line") is not None \
                    and tl.get("fav_is_home") == fav_is_home:
                pos = 1 if fair > tl["open_line"] + 1e-9 else (-1 if fair < tl["open_line"] - 1e-9 else 0)
                if pos:
                    clv = pos * (tl["close_line"] - tl["open_line"])   # >0：市场朝模型方向移动
                    vm["clv_n"] += 1
                    vm["clv_sum"] += clv
                    vm["clv_pos"] += int(clv > 1e-9)
            # 跟模型背离方下注 vs 市场闭盘线：背离>0.25 才算「真分歧」（避免半档噪声）
            diff = fair - market_line
            if diff > 0.25 + 1e-9:        # 模型更看好强队 → 背强队让 market_line
                adj = real_margin - market_line
                mkt_lean = "强队"
                if adj > 1e-9: vm["edge_w"] += 1
                elif adj < -1e-9: vm["edge_l"] += 1
                else: vm["edge_push"] += 1
            elif diff < -0.25 - 1e-9:     # 模型更保守 → 背弱队受让 market_line
                adj = real_margin - market_line
                mkt_lean = "弱队"
                if adj < -1e-9: vm["edge_w"] += 1
                elif adj > 1e-9: vm["edge_l"] += 1
                else: vm["edge_push"] += 1
            else:
                vm["agree"] += 1          # 模型≈市场，无可下注分歧

        rows.append({
            "date": verify.bj_date(e.get("kickoff"), e.get("date") or c.get("date")),
            "stage": e["stage"], "fav": fav_team, "dog": dog_team,
            "fav_is_home": fav_is_home,
            "score": f"{gh}-{ga}", "real_margin": int(real_margin),
            "jc_line": jc_line, "jc_pick": jc_pick, "jc_actual": jc_act, "jc_hit": jc_hit,
            "fair_line": fair, "pred_cover": round(pred_cover, 4),
            "cover_result": res,
            "market_line": ml["fav_line"] if (ml and ml.get("fav_is_home") == fav_is_home) else None,
            "mkt_lean": mkt_lean,
        })

    rows.sort(key=lambda r: r["date"], reverse=True)
    n = len(rows)
    jc_rate, jc_lo, jc_hi = _wilson(jc_hits, n)
    # 基线：永远押本届最常见的让球赛果
    base_pick, base_n = (max(jc_actuals.items(), key=lambda kv: kv[1]) if n else ("让负", 0))
    jc_base = base_n / n if n else 0.0
    asian = {
        "decided": cover_decided,
        "pred_cover_rate": round(cover_pred_sum / cover_decided, 4) if cover_decided else None,
        "real_cover_rate": round(cover_real / cover_decided, 4) if cover_decided else None,
        "calib_gap": round((cover_real - cover_pred_sum) / cover_decided, 4) if cover_decided else None,
        "brier": round(brier_sum / cover_decided, 4) if cover_decided else None,
    }
    # 分桶竞彩命中率（按预设顺序，附 Wilson CI）
    _order = {"stage": ["小组赛", "淘汰赛"],
              "strength": ["大热(≥70%)", "中等(55–70%)", "接近(<55%)"]}
    buckets_out = {}
    for dim, cells in buckets.items():
        rowsd = []
        for key in _order.get(dim, list(cells)):
            if key not in cells:
                continue
            cn, ch = cells[key]
            r, lo, hi = _wilson(ch, cn)
            rowsd.append({"key": key, "n": cn, "hits": ch, "rate": round(r, 4),
                          "ci": [round(lo, 4), round(hi, 4)]})
        buckets_out[dim] = rowsd
    return {
        "n": n, "rows": rows,
        "jc": {
            "hits": jc_hits, "rate": round(jc_rate, 4),
            "ci": [round(jc_lo, 4), round(jc_hi, 4)],
            "actuals": jc_actuals,
            "baseline_pick": base_pick, "baseline_rate": round(jc_base, 4),
            "beats_baseline": jc_rate > jc_base,
        },
        "asian": asian,
        "buckets": buckets_out,
        "vs_market": _vs_market_out(vm),
    }


def _vs_market_out(vm):
    """汇总「模型 vs 市场」：覆盖场数、背离下注打赢闭线胜率(+CI)、双方让球线 MAE、谁更接近。"""
    nm = vm["n"]
    if nm == 0:
        return {"n": 0, "clv": {"n": 0}}
    dec = vm["edge_w"] + vm["edge_l"]            # 非走水的「真分歧」下注数
    er, elo, ehi = _wilson(vm["edge_w"], dec)
    out = {
        "n": nm,
        "mae_model": round(vm["mae_model"] / nm, 3),
        "mae_market": round(vm["mae_market"] / nm, 3),
        "mae_model_em": round(vm["mae_model_em"] / nm, 3),
        "em_closer": vm["em_closer"], "em_worse": vm["em_worse"],
        "em_beats_market": vm["mae_model_em"] < vm["mae_market"] - 1e-9,
        "closer_model": vm["closer_model"], "closer_market": vm["closer_market"],
        "tie": vm["tie"],
        "edge_decided": dec, "edge_wins": vm["edge_w"], "edge_push": vm["edge_push"],
        "edge_rate": round(er, 4) if dec else None,
        "edge_ci": [round(elo, 4), round(ehi, 4)] if dec else None,
        "agree": vm["agree"],
        "beats_market": (er > 0.5) if dec else None,
        "model_closer": vm["closer_model"] > vm["closer_market"],
    }
    # 让球 CLV（开盘→闭盘朝模型方向移动的均值；开盘线今起累积，早期 clv_n 可能为 0）
    out["clv"] = ({"n": vm["clv_n"], "avg": round(vm["clv_sum"] / vm["clv_n"], 3),
                   "pos_rate": round(vm["clv_pos"] / vm["clv_n"], 4)} if vm["clv_n"] else {"n": 0})
    return out


if __name__ == "__main__":   # CLI 自测
    import app
    sim, df = app._sim(), app.DF
    verify.freeze(sim); verify.backfill(sim, df)   # 先确保账本有冻结/回补
    espn_odds.backfill_handicap_finished(limit=200)  # CLI 下一次补全市场闭盘线
    b = build(sim, df)
    print(f"已结算让球场次：{b['n']}")
    jc = b["jc"]
    print(f"竞彩让球命中：{jc['hits']}/{b['n']} = {jc['rate']:.1%}  "
          f"[95%CI {jc['ci'][0]:.1%}–{jc['ci'][1]:.1%}]")
    print(f"  赛果分布：{jc['actuals']}  基线「永远押{jc['baseline_pick']}」={jc['baseline_rate']:.1%}  "
          f"{'✓超基线' if jc['beats_baseline'] else '✗未超基线'}")
    a = b["asian"]
    if a["decided"]:
        print(f"亚盘公平盘校准（{a['decided']} 场非走水）：模型预测打出 {a['pred_cover_rate']:.1%} "
              f"vs 实际打出 {a['real_cover_rate']:.1%}  校准差 {a['calib_gap']:+.1%}  Brier {a['brier']:.3f}")
    vm = b["vs_market"]
    if vm["n"]:
        print(f"\n模型 vs 市场闭盘线（{vm['n']} 场有市场盘）：")
        print(f"  让球线 MAE：模型 {vm['mae_model']} vs 市场 {vm['mae_market']} "
              f"→ {'模型更接近实际净胜' if vm['model_closer'] else '市场更接近实际净胜'}"
              f"（更近场数 模型{vm['closer_model']}/市场{vm['closer_market']}/平{vm['tie']}）")
        print(f"  模型期望净胜 MAE（连续）：{vm['mae_model_em']} vs 市场 {vm['mae_market']} "
              f"→ {'模型期望净胜更准' if vm['em_beats_market'] else '市场仍更准'}（更近 {vm['em_closer']}/{vm['n']}）")
        clv = vm["clv"]
        if clv["n"]:
            print(f"  让球 CLV：{clv['n']} 场有开盘线，闭盘朝模型移动均值 {clv['avg']:+.3f} 球、正 CLV 占 {clv['pos_rate']:.0%}")
        else:
            print("  让球 CLV：暂无开盘线样本（今起多次快照 + 完赛后累积；淘汰赛阶段起有数据）")
        if vm["edge_decided"]:
            print(f"  跟模型背离方下注 vs 市场闭线：{vm['edge_wins']}/{vm['edge_decided']} = "
                  f"{vm['edge_rate']:.1%} [CI {vm['edge_ci'][0]:.1%}–{vm['edge_ci'][1]:.1%}] "
                  f"{'✓打赢闭线(有价值)' if vm['beats_market'] else '✗未打赢闭线'}（另 {vm['agree']} 场模型≈市场无分歧）")
        else:
            print(f"  暂无与市场的「真分歧」可下注样本（{vm['agree']} 场模型≈市场）")

    print("\n近 5 场：")
    for r in b["rows"][:5]:
        ml = f" · 市场让{r['market_line']}" if r.get("market_line") is not None else ""
        print(f"  {r['date']} {r['fav']}(强) {r['score']} → 竞彩 模型{r['jc_pick']}/实际{r['jc_actual']} "
              f"{'✓' if r['jc_hit'] else '✗'} · 公平盘让{r['fair_line']}{ml} {r['cover_result']}")
