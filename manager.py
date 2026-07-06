# Repository summary: World Cup prediction analytics module.
"""
足球经理人预测层（Football-Manager-style deep pre-match report）。

定位：与 insights.py / inplay.py / clv.py 同级的**只读组装/解读层**，
不参与训练、不碰 GLM、不写任何账本。把已有引擎的输出 + 历史数据组装成
一份「资深分析师」风格的赛前深度报告（4 大模块 + 结论汇总表）。

三段式（对应用户需求「获取过程数据 → 算法模型 → 得出结论」）：
  1) 过程数据：近期 5 场状态、历史交锋、攻防均值/零封率（来自 results.csv 真实历史）。
  2) 算法模型：Dixon-Coles 双泊松比分矩阵（model.py，即本项目核心引擎），
     λ 作为 xG 代理；矩阵卷积推导出全部盘口维度。
  3) 结论：1X2 / 大小球 / BTTS / 总进球分布 / 正确比分 / 亚盘让球 / 竞彩让球 /
     半全场 / 胜负倾向 + 置信度 + 结论汇总表。

诚实边界（遵循项目铁律）：
  - 凡引擎/历史数据**无法提供**的定性维度（具体阵型、首发名单、临场调整、
    天气草皮裁判），明确标注「定性维度·引擎不提供」，不编造。
  - 半全场为**启发式**（按经验前/后半场进球占比拆分独立泊松，未套 DC ρ），
    标注低置信度。
  - 亚盘/欧赔若该对阵无已采集赔率，仅给**模型推导盘口**，注明非市场实盘。
"""
from __future__ import annotations
import os
import numpy as np
from scipy.stats import poisson

import data as datamod
import schedule as schedmod
import teams_zh

# 经验：上半场进球数略少于下半场（约 45% 落在上半场）。半全场启发式用。
FH_SHARE = 0.45
RECENT_FORM_N = 5      # 近期状态取最近 N 场
STATS_WINDOW = 20      # 攻防均值/零封率取最近 N 场（兼顾近期性与样本量）
H2H_N = 5              # 历史交锋取最近 N 次


# ───────────────────────── 过程数据：近期状态 / 交锋 / 攻防 ─────────────────────────

def _team_matches(df, team):
    """该队全部已开赛场次（任意赛事），按日期降序。返回标准化行 dict 列表。"""
    m = ((df["home_team"] == team) | (df["away_team"] == team)) \
        & df["home_score"].notna() & df["away_score"].notna() & df["date"].notna()
    sub = df.loc[m].sort_values("date", ascending=False)
    rows = []
    for _, r in sub.iterrows():
        at_home = r["home_team"] == team
        gf = int(r["home_score"] if at_home else r["away_score"])
        ga = int(r["away_score"] if at_home else r["home_score"])
        opp = r["away_team"] if at_home else r["home_team"]
        res = "W" if gf > ga else ("D" if gf == ga else "L")
        rows.append({
            "date": r["date"].date().isoformat(),
            "opp": opp, "gf": gf, "ga": ga, "res": res,
            "home": bool(at_home), "neutral": bool(r["neutral"]),
            "tournament": r.get("tournament", ""),
        })
    return rows


def recent_form(df, team, n=RECENT_FORM_N):
    ms = _team_matches(df, team)[:n]
    gf = sum(x["gf"] for x in ms)
    ga = sum(x["ga"] for x in ms)
    w = sum(x["res"] == "W" for x in ms)
    d = sum(x["res"] == "D" for x in ms)
    l = sum(x["res"] == "L" for x in ms)
    cs = sum(x["ga"] == 0 for x in ms)            # 零封
    fts = sum(x["gf"] == 0 for x in ms)           # 哑火
    return {
        "matches": ms, "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
        "clean_sheets": cs, "failed_to_score": fts,
        "form_str": "".join(x["res"] for x in ms),  # 最近在前
        "n": len(ms),
    }


def head_to_head(df, home, away, n=H2H_N):
    m = (((df["home_team"] == home) & (df["away_team"] == away))
         | ((df["home_team"] == away) & (df["away_team"] == home))) \
        & df["home_score"].notna() & df["away_score"].notna() & df["date"].notna()
    sub = df.loc[m].sort_values("date", ascending=False).head(n)
    rows, hw, aw, dr = [], 0, 0, 0
    for _, r in sub.iterrows():
        hs, as_ = int(r["home_score"]), int(r["away_score"])
        winner = r["home_team"] if hs > as_ else (r["away_team"] if as_ > hs else None)
        if winner == home:
            hw += 1
        elif winner == away:
            aw += 1
        else:
            dr += 1
        rows.append({
            "date": r["date"].date().isoformat(),
            "home": r["home_team"], "away": r["away_team"],
            "hs": hs, "as": as_, "tournament": r.get("tournament", ""),
            "neutral": bool(r["neutral"]),
            "winner": winner,
        })
    return {"rows": rows, "home_wins": hw, "away_wins": aw, "draws": dr, "n": len(rows)}


def team_stats(df, team, model, n=STATS_WINDOW):
    """攻防数据画像：近 n 场场均进/失球 + 零封率，叠加引擎评级与净实力。"""
    ms = _team_matches(df, team)[:n]
    k = max(1, len(ms))
    avg_gf = sum(x["gf"] for x in ms) / k
    avg_ga = sum(x["ga"] for x in ms) / k
    cs_rate = sum(x["ga"] == 0 for x in ms) / k
    try:
        en = model.resolve(team)
        atk = float(model.attack.get(en, 0.0))
        dfc = float(model.defence.get(en, 0.0))
        net = atk - dfc
        nmatch = int(model.n_matches.get(en, 0))
    except Exception:
        atk = dfc = net = 0.0
        nmatch = 0
    return {
        "avg_gf": round(avg_gf, 2), "avg_ga": round(avg_ga, 2),
        "clean_sheet_rate": round(cs_rate, 2), "sample": len(ms),
        "atk": round(atk, 3), "dfc": round(dfc, 3), "net": round(net, 3),
        "n_matches": nmatch,
    }


# ───────────────────────── 算法模型：比分矩阵 → 全盘口推导 ─────────────────────────

def _margin_pmf(M):
    """净胜球分布 d=主-客：返回 {k: P(d=k)}，k ∈ -N..N。"""
    n = M.shape[0]
    out = {}
    for i in range(n):
        for j in range(n):
            d = i - j
            out[d] = out.get(d, 0.0) + M[i, j]
    return out


def _handicap_back_fav(mp, fav_is_home, line):
    """以净胜球分布 mp 计算【让 line 球】结果（line>0 表强队让出的球数）。
    返回 (win, push, lose)——站在强队（favorite）让球后的角度。
    line 支持整数/半球/(为简洁)单一数值；分球(.25/.75)用半赢半输由调用方组合。"""
    # 统一成「强队净胜球 m」分布
    fav = {(k if fav_is_home else -k): p for k, p in mp.items()}
    win = push = lose = 0.0
    for m, p in fav.items():
        adj = m - line          # 让球后强队的「净胜」
        if adj > 1e-9:
            win += p
        elif adj < -1e-9:
            lose += p
        else:
            push += p
    return win, push, lose


def _asian_quarter(mp, fav_is_home, line):
    """分球盘（如 -0.75 = -0.5/-1.0 各半仓）的净结算：返回 (win_eq, lose_eq)。
    push 视作退本（计 0.5 赢面 + 0.5 输面以反映无盈亏）。"""
    lo, hi = line - 0.25, line + 0.25
    w1, p1, l1 = _handicap_back_fav(mp, fav_is_home, lo)
    w2, p2, l2 = _handicap_back_fav(mp, fav_is_home, hi)
    # 半仓加总；push 半仓退本（既非赢也非输，按 0.5/0.5 摊给 win/lose 仅用于可读展示）
    win = 0.5 * (w1 + 0.5 * p1) + 0.5 * (w2 + 0.5 * p2)
    lose = 0.5 * (l1 + 0.5 * p1) + 0.5 * (l2 + 0.5 * p2)
    return win, lose


# 让球档位扫描表（站强队角度，强队让出的球数）。整/半档走 _handicap_back_fav，
# 分球（.25/.75）走 _asian_quarter（无走盘、半仓退本已并入赢/输）。
_HANDI_LINES = [0.5, 0.75, 1.0, 1.25, 1.5, 1.75, 2.0, 2.25, 2.5, 2.75, 3.0]


def settle_line(mp, fav_is_home, line):
    """任意让球线的结算（站强队角度）：返回 {win, push, lose, net}。
    net = win − lose（push 视退本，不计盈亏），>0 押强队占面、<0 让过头押弱队占面。"""
    if abs((line * 4) % 2) > 1e-9:        # .25 / .75 分球盘
        w, l = _asian_quarter(mp, fav_is_home, line)
        p = 0.0
    else:                                  # 整数 / 半球盘
        w, p, l = _handicap_back_fav(mp, fav_is_home, line)
    return {"win": w, "push": p, "lose": l, "net": w - l}


def _verdict(net):
    """让球性价比判级（站强队角度）。push 已按退本并入 net。"""
    if net >= 0.10:
        return "偏值"      # 让这么多强队仍明显占面
    if net <= -0.10:
        return "偏亏"      # 让过头，押弱队受让占面
    return "接近公平"


def jc_handicap(mp, fav_is_home, line=1):
    """竞彩让球（强队让 line 球，line 整数）：让胜(净胜>line)/让平(净胜=line)/让负(净胜<line) + argmax。
    line=0 即平手（让胜=强队胜/让平=平/让负=强队负），等同常规胜平负。默认 line=1 与旧口径恒等。"""
    fav = {(k if fav_is_home else -k): p for k, p in mp.items()}
    win = sum(p for m, p in fav.items() if m > line)
    draw = sum(p for m, p in fav.items() if m == line)
    lose = sum(p for m, p in fav.items() if m < line)
    verdict = max((("让胜", win), ("让平", draw), ("让负", lose)), key=lambda t: t[1])[0]
    return {"win": win, "draw": draw, "lose": lose, "verdict": verdict, "line": line}


def csl_line(mp, fav_is_home):
    """本场竞彩让球线 N = round(强队期望净胜球)，clamp[0,6]。N≥1 强队让 N 球；N=0 平手(常规胜平负)。"""
    favm = {(k if fav_is_home else -k): p for k, p in mp.items()}
    exp = float(sum(k * p for k, p in favm.items()))      # 强队期望净胜
    return int(max(0, min(6, round(exp)))), round(exp, 2)


def csl_handicap(mp, fav_is_home):
    """竞彩让球胜平负——**按本场期望净胜动态定让球线**（非写死让1）。
    返回 {line, is_handicap, home_line(主队口径,负=主让/正=主受让), exp_margin, win/draw/lose/verdict}。"""
    N, exp = csl_line(mp, fav_is_home)
    jc = jc_handicap(mp, fav_is_home, N)
    home_line = 0 if N == 0 else (-N if fav_is_home else N)
    return {**jc, "is_handicap": N >= 1, "home_line": home_line, "exp_margin": exp}


def handicap_summary(M, p_home, p_away, home_team, away_team, market=None):
    """紧凑让球摘要（供看板「看预测」弹窗用）：强队 / 公平盘 / 模型上限 / 竞彩让球倾向。
    纯从比分矩阵卷积，不碰引擎。M 接受 np.array 或嵌套 list。
    market（可选）= espn_odds 让球盘行 → 附市场实盘 spread 对标。"""
    M = np.asarray(M, dtype=float)
    mp = _margin_pmf(M)
    fav_is_home = p_home >= p_away
    fav_team, dog_team = (home_team, away_team) if fav_is_home else (away_team, home_team)
    hc = handicap_conclusion(mp, fav_is_home, fav_team, dog_team)
    csl = csl_handicap(mp, fav_is_home)        # 竞彩动态让球线（让N/平手）+ 胜平负
    out = {
        "fav": fav_team, "dog": dog_team, "fav_is_home": fav_is_home,
        "fair_line": hc["fair_line"], "max_fair_line": hc["max_fair_line"],
        "jc_verdict": csl["verdict"], "csl_line": csl["line"], "csl_is_handicap": csl["is_handicap"],
        "jc": {"win": csl["win"], "draw": csl["draw"], "lose": csl["lose"]},
    }
    out["market"] = _market_compare(hc, {"market_handicap": market}, fav_team, dog_team, fav_is_home)
    return out


def _market_compare(hc, context, fav_en, dog_en, model_fav_is_home):
    """模型公平盘 vs 市场实盘让球盘（ESPN/DraftKings spread）背离分析。
    context["market_handicap"] = espn_odds 行（站强队口径 fav_line/fav_is_home/...）。
    返回 None（无实盘）或 {market_line, source, agree_fav, divergence, lean}。"""
    mh = (context or {}).get("market_handicap")
    if not mh:
        return None
    # 市场强队与模型强队是否一致（极少数分歧场，如实标注不强行比较盘口数值）
    agree = (mh.get("fav_is_home") == model_fav_is_home)
    market_line = mh.get("fav_line")
    out = {
        "market_line": market_line, "source": mh.get("provider", "DraftKings"),
        "ou": mh.get("ou"), "agree_fav": agree,
        "fav_odds": mh.get("fav_spread_odds"), "dog_odds": mh.get("dog_spread_odds"),
    }
    # 盘口移动（开盘→现/闭盘，站强队角度）：>0 市场加大让球(更看好强队)、<0 收窄
    if mh.get("open_line") is not None and market_line is not None:
        mv = round(market_line - mh["open_line"], 2)
        out["open_line"] = mh["open_line"]
        out["move"] = mv
        out["move_dir"] = ("市场加大让球（更看好强队）" if mv > 0.124 else
                           "市场收窄让球（更看好弱队）" if mv < -0.124 else "盘口基本未动")
    if agree and market_line is not None:
        div = round(hc["fair_line"] - market_line, 2)   # >0：模型让得更多=更看好强队
        out["divergence"] = div
        out["lean"] = ("模型比市场更看好强队" if div > 0.124 else
                       "模型比市场更保守" if div < -0.124 else "模型与市场基本一致")
    return out


def handicap_conclusion(mp, fav_is_home, fav_team, dog_team):
    """直接给让球结论（不放选择器）：模型公平盘 + 全档位扫描 + 模型上限档。

    - fair_line：让球后强队净胜率（win−lose）绝对值最小的档 = 模型「五五开盘口」。
    - max_fair：强队能让且模型侧仍不亏（net≥0）的最大档，超过即模型侧偏亏。
    - lines：每档赢/走盘/输 + 性价比判级，供前端直接铺表。
    """
    scan = []
    for L in _HANDI_LINES:
        s = settle_line(mp, fav_is_home, L)
        s["line"] = L
        s["verdict"] = _verdict(s["net"])
        scan.append(s)
    fair = min(scan, key=lambda s: abs(s["net"]))
    fair_or = [s for s in scan if s["net"] >= -1e-9]
    max_fair = max(fair_or, key=lambda s: s["line"]) if fair_or else scan[0]
    return {
        "fav": fav_team, "dog": dog_team, "fav_is_home": fav_is_home,
        "fair_line": fair["line"], "fair": fair,
        "max_fair_line": max_fair["line"],
        "lines": scan,
    }


def derived_markets(M, lam_h, lam_a, p_home, p_draw, p_away):
    """从比分矩阵卷积出全部盘口维度。"""
    n = M.shape[0]
    mp = _margin_pmf(M)

    # —— 大小球 / 总进球分布 ——
    tot = {}
    for i in range(n):
        for j in range(n):
            tot[i + j] = tot.get(i + j, 0.0) + M[i, j]
    over = {}
    for line in (1.5, 2.5, 3.5):
        over[line] = sum(p for t, p in tot.items() if t > line)
    # 总进球区间桶
    goals_dist = {
        "0-1": sum(p for t, p in tot.items() if t <= 1),
        "2": tot.get(2, 0.0),
        "3": tot.get(3, 0.0),
        "4+": sum(p for t, p in tot.items() if t >= 4),
    }
    exp_total = sum(t * p for t, p in tot.items())

    # —— BTTS 双方进球 ——
    btts_yes = float(M[1:, 1:].sum())

    # —— 正确比分 Top（沿用 predict 的 argsort，但这里独立算，含中文留给上层）——
    idx = np.dstack(np.unravel_index(np.argsort(M.ravel())[::-1], M.shape))[0]
    top_scores = [{"h": int(i), "a": int(j), "p": float(M[i, j])} for i, j in idx[:6]]

    # —— 亚盘：以净胜球分布推导（模型公平盘，非市场实盘）——
    fav_is_home = p_home >= p_away
    fav_win = p_home if fav_is_home else p_away
    dog_win = p_away if fav_is_home else p_home
    asian = {"fav_is_home": fav_is_home}
    # 主要让球档（站在强队角度）
    for label, line in [("-0.5", 0.5), ("-1.0", 1.0), ("-1.5", 1.5), ("-2.0", 2.0)]:
        w, p, l = _handicap_back_fav(mp, fav_is_home, line)
        asian[label] = {"win": w, "push": p, "lose": l}
    for label, line in [("-0.75", 0.75), ("-1.25", 1.25)]:
        w, l = _asian_quarter(mp, fav_is_home, line)
        asian[label] = {"win": w, "lose": l, "push": 0.0}
    # 公平盘口：让 0/0.5/1/1.5/2... 中强队让球后胜率最接近 50% 的整/半档
    fair = min([0.5, 1.0, 1.5, 2.0],
               key=lambda L: abs(_handicap_back_fav(mp, fav_is_home, L)[0] - 0.5))
    asian["fair_line"] = fair

    # —— 竞彩让球（让 1 球）：强队让 1 → 让胜=赢2+ / 让平=刚好赢1 / 让负=不胜 ——
    jc = jc_handicap(mp, fav_is_home)

    return {
        "over": over, "goals_dist": goals_dist, "exp_total": exp_total,
        "btts_yes": btts_yes, "btts_no": 1 - btts_yes,
        "top_scores": top_scores, "asian": asian, "jc_handicap": jc,
        "fav_is_home": fav_is_home, "fav_win": fav_win, "dog_win": dog_win,
    }


def half_full_time(lam_h, lam_a, max_half=6):
    """半全场启发式：按 FH_SHARE 把每队 λ 拆成上/下半场两个独立泊松，
    枚举半场比分组合 → HT(H/D/A) × FT(H/D/A) 3×3 联合分布。
    **未套 DC ρ 低分修正，属近似**——结论标低置信度。"""
    lh1, lh2 = lam_h * FH_SHARE, lam_h * (1 - FH_SHARE)
    la1, la2 = lam_a * FH_SHARE, lam_a * (1 - FH_SHARE)
    ks = np.arange(max_half + 1)
    ph1, ph2 = poisson.pmf(ks, lh1), poisson.pmf(ks, lh2)
    pa1, pa2 = poisson.pmf(ks, la1), poisson.pmf(ks, la2)

    def res(hg, ag):
        return 0 if hg > ag else (1 if hg == ag else 2)   # 0=主 1=平 2=客

    joint = np.zeros((3, 3))   # [HT][FT]
    for h1 in ks:
        for a1 in ks:
            p1 = ph1[h1] * pa1[a1]
            if p1 < 1e-12:
                continue
            ht = res(h1, a1)
            for h2 in ks:
                for a2 in ks:
                    p2 = ph2[h2] * pa2[a2]
                    if p2 < 1e-12:
                        continue
                    ft = res(h1 + h2, a1 + a2)
                    joint[ht][ft] += p1 * p2
    joint /= joint.sum()
    labels = ["主", "平", "客"]
    cells = {}
    for i in range(3):
        for j in range(3):
            cells[f"{labels[i]}/{labels[j]}"] = float(joint[i][j])
    ranked = sorted(cells.items(), key=lambda kv: -kv[1])
    return {"cells": cells, "ranked": ranked[:4]}


# ───────────────────────── 结论：置信度 / 胜负倾向 ─────────────────────────

def confidence(p_home, p_draw, p_away):
    """胜负倾向 + 置信度（高/中/低）。平局为 argmax 或两强相近 → 降级。"""
    picks = [("主胜", p_home), ("平局", p_draw), ("客胜", p_away)]
    picks.sort(key=lambda t: -t[1])
    (lab, p), (_, p2) = picks[0], picks[1]
    gap = p - p2
    if lab == "平局":                      # 平局是 argmax 的结构盲区，谨慎
        level = "低"
    elif p >= 0.55 and gap >= 0.20:
        level = "高"
    elif p >= 0.42 and gap >= 0.10:
        level = "中"
    else:
        level = "低"
    return {"pick": lab, "p": p, "gap": gap, "level": level}


# ───────────────────────── 上下文：伤停 / 赛程 ─────────────────────────

def availability_for(home_en, away_en):
    import adjust
    mods = adjust.team_modifiers()
    out = {}
    for side, t in (("home", home_en), ("away", away_en)):
        m = mods.get(t)
        out[side] = {
            "att": m["att"] if m else 1.0,
            "def_pen": m["def_pen"] if m else 1.0,
            "items": [{"player": i["player"], "reason": i.get("reason", ""),
                       "status": i.get("status"), "tier": i.get("tier"),
                       "role": i.get("role")} for i in m["items"]] if m else [],
        } if m else None
    return out


def schedule_ctx(home_en, away_en):
    """本届世界杯小组赛对阵的场馆/北京&当地时间/东道主主场（非 WC 对阵返回 None）。"""
    gv = schedmod.group_venue(home_en, away_en)
    if not gv:
        return None
    bj = schedmod.GROUP.get((home_en, away_en)) or schedmod.GROUP.get((away_en, home_en))
    host = schedmod.group_match_host(home_en, away_en)
    return {"city": gv.get("city"), "kickoff_bj": bj, "kickoff_local": gv.get("local"),
            "host": teams_zh.disp(host) if host else None}


# ───────────────────────── 赔率对标（若已采集） ─────────────────────────

ODDS_PATH = os.path.join(os.path.dirname(__file__), "data", "odds.csv")


def market_odds(home_en, away_en):
    """从 data/odds.csv 取该对阵闭盘 1X2（顺序无关）；无则 None。返回去抽水隐含概率。"""
    if not os.path.exists(ODDS_PATH):
        return None
    try:
        import pandas as pd
        o = pd.read_csv(ODDS_PATH)
    except Exception:
        return None
    fwd = o[(o["home_team"] == home_en) & (o["away_team"] == away_en)]
    rev = o[(o["home_team"] == away_en) & (o["away_team"] == home_en)]
    flip = False
    row = None
    if not fwd.empty:
        row = fwd.iloc[-1]
    elif not rev.empty:
        row = rev.iloc[-1]
        flip = True
    if row is None:
        return None
    try:
        o1, ox, o2 = float(row["odds_1"]), float(row["odds_x"]), float(row["odds_2"])
    except (ValueError, TypeError):
        return None
    if min(o1, ox, o2) <= 0:
        return None
    inv = np.array([1 / o1, 1 / ox, 1 / o2])
    imp = inv / inv.sum()                # 去抽水
    if flip:
        imp = np.array([imp[2], imp[1], imp[0]])
    return {"odds_1": o1, "odds_x": ox, "odds_2": o2,
            "imp_home": float(imp[0]), "imp_draw": float(imp[1]), "imp_away": float(imp[2]),
            "margin": float(inv.sum() - 1)}


# ───────────────────────── 总装 ─────────────────────────

MOTIV_MULT = 0.90   # 动机降权乘子：已出线队进攻 λ × 此值（启发式、非回测结论，默认不启用）


def _motivation(context, h_en, a_en, fav_is_home):
    """动机层：综合「已晋级球队心态」。从 context（app 注入的 clinch 状态）出发——
    预警常开；降权乘子仅在 motiv_adj 显式开启且强队已出线时应用。返回 motivation 块 +
    供 score_matrix 用的 avail_override（None=不调整）。**不碰 GLM，只走上下文乘子通道。**"""
    if not context:
        return None, None
    hc, ac = context.get("home_clinch"), context.get("away_clinch")
    fav_en = h_en if fav_is_home else a_en
    fav_clinch = hc if fav_is_home else ac
    # 预警：任一方已锁定出线/头名 → 可能轮换，让球盘性价比下调（尤其强队已出线时大盘易翻）。
    warn = []
    for en, c, who in ((h_en, hc, "home"), (a_en, ac, "away")):
        if c and c.get("qualified"):
            warn.append({"team": en, "side": who, "label": c["label"],
                         "top1": c.get("top1", False)})
    applies = bool(fav_clinch and fav_clinch.get("qualified"))   # 强队已出线=降权才有意义
    block = {
        "home_clinch": hc, "away_clinch": ac,
        "warnings": warn, "applies_to_fav": applies,
        "fav_clinched": applies, "mult": MOTIV_MULT,
        "adjusted": False,
    }
    override = None
    if context.get("motiv_adj") and applies:
        # 强队已出线 → 进攻 λ × MOTIV_MULT（防守不动）。avail_override=(att_mult, def_pen_mult)。
        override = {fav_en: (MOTIV_MULT, 1.0)}
        block["adjusted"] = True
    return block, override


def build_report(model, df, home, away, neutral=True, elo=None, lineup=None, context=None):
    """组装完整报告 dict（英文队名内部用，最外层由 app 本地化）。
    context（可选，app 注入）：{home_clinch, away_clinch, motiv_adj} 驱动动机层让球微调。"""
    h_en = model.resolve(home)
    a_en = model.resolve(away)
    # 首发名单层：available 时主报告改用首发确认版乘子；否则 None=维持现状（全局口径）。
    _ov = lineup["mods"] if (lineup and lineup.get("available")) else None

    # 先用基线口径定强弱（动机降权只对「强队已出线」生效，故强弱判定不受降权影响）。
    _, _, _l0h, _l0a, M0 = model.score_matrix(h_en, a_en, neutral=neutral, avail_override=_ov)
    fav_is_home = float(np.tril(M0, -1).sum()) >= float(np.triu(M0, 1).sum())
    motiv, motiv_ov = _motivation(context, h_en, a_en, fav_is_home)

    # 动机降权：把降权乘子叠到现有 override 上（首发层若在则合并，互不覆盖）。
    av_override = _ov
    if motiv_ov:
        av_override = dict(_ov or {}); av_override.update(motiv_ov)
    h, a, lam_h, lam_a, M = model.score_matrix(h_en, a_en, neutral=neutral,
                                               avail_override=av_override)
    p_home = float(np.tril(M, -1).sum())
    p_draw = float(np.trace(M))
    p_away = float(np.triu(M, 1).sum())

    mk = derived_markets(M, lam_h, lam_a, p_home, p_draw, p_away)
    # 让球结论（直接给：公平盘 + 全档扫描 + 模型上限），队名按强弱归属。
    fav_en, dog_en = (h_en, a_en) if fav_is_home else (a_en, h_en)
    _mp = _margin_pmf(M)
    mk["handicap"] = handicap_conclusion(_mp, fav_is_home, fav_en, dog_en)
    # 竞彩让球胜平负：按本场期望净胜动态定让球线（如摩洛哥让2、势均力敌平手），非写死让1。
    mk["handicap"]["csl"] = csl_handicap(_mp, fav_is_home)
    # 市场让球盘对标（context 注入的 ESPN/DraftKings 实盘 spread）：模型公平盘 vs 市场盘口背离。
    mk["handicap"]["market"] = _market_compare(mk["handicap"], context, fav_en, dog_en, fav_is_home)
    conf = confidence(p_home, p_draw, p_away)
    hft = half_full_time(lam_h, lam_a)

    # Elo 排名（48 强内，与解读层同口径），用于「模型 vs 名气」一句
    elo_note = None
    if elo:
        import wc2026
        participants = [t for g in wc2026.GROUPS.values() for t in g]
        pool = sorted((t for t in participants if t in elo), key=lambda t: -elo[t])
        rank = {t: i + 1 for i, t in enumerate(pool)}
        if h_en in rank and a_en in rank:
            elo_note = {"home_rank": rank[h_en], "away_rank": rank[a_en]}

    avail = availability_for(h_en, a_en)
    sched = schedule_ctx(h_en, a_en)
    odds = market_odds(h_en, a_en)

    sh = team_stats(df, h_en, model)
    sa = team_stats(df, a_en, model)
    fh = recent_form(df, h_en)
    fa = recent_form(df, a_en)
    h2h = head_to_head(df, h_en, a_en)

    # 关键对位：双方进攻 λ 贡献 vs 对方防守
    matchup = {
        "home_att_vs_away_def": "主队进攻占优" if (sh["atk"] - sa["dfc"]) > (sa["atk"] - sh["dfc"]) else "客队进攻占优",
        "home_lambda": round(float(lam_h), 2), "away_lambda": round(float(lam_a), 2),
    }

    # 弱点：失球评级更松（dfc 更大）的一方防线是突破口
    weak = {
        "home": "防守偏松（易被针对）" if sh["dfc"] > sa["dfc"] else "防守相对稳固",
        "away": "防守偏松（易被针对）" if sa["dfc"] > sh["dfc"] else "防守相对稳固",
    }

    # 首发名单对比块（lineups 传入则附；不传零影响）。available 时主报告已是首发版，
    # 这里额外算「纯 DC 基线 pre」与之对照，让用户看到球员数据的净影响。
    lineup_block = None
    if lineup:
        if lineup.get("available"):
            _, _, _, _, M0 = model.score_matrix(h_en, a_en, neutral=neutral, avail_override={})
            pre = {"p_home": float(np.tril(M0, -1).sum()),
                   "p_draw": float(np.trace(M0)),
                   "p_away": float(np.triu(M0, 1).sum())}
            lineup_block = {
                "available": True, "state": lineup.get("state"),
                "teams": lineup.get("teams"), "mods": lineup.get("mods"),
                "coverage": lineup.get("coverage"),
                "compare": {"pre": pre,
                            "post": {"p_home": p_home, "p_draw": p_draw, "p_away": p_away}},
            }
        else:
            lineup_block = {"available": False,
                            "reason": lineup.get("reason", "lineup_not_published"),
                            "coverage": lineup.get("coverage")}

    return {
        "home": h_en, "away": a_en, "neutral": neutral,
        "xg_home": round(float(lam_h), 3), "xg_away": round(float(lam_a), 3),
        "p_home": p_home, "p_draw": p_draw, "p_away": p_away,
        # 完整比分概率矩阵（原「单场预测」tab 的热力图，已并入本报告算法模型模块）
        "matrix": [[round(float(x), 5) for x in row] for row in M],
        "stats": {"home": sh, "away": sa},
        "form": {"home": fh, "away": fa},
        "h2h": h2h,
        "matchup": matchup, "weak": weak,
        "markets": mk, "confidence": conf, "half_full": hft,
        "availability": avail, "schedule": sched, "odds": odds, "lineup": lineup_block,
        "motivation": motiv,
        "elo": elo_note,
        "meta": {
            "fh_share": FH_SHARE, "stats_window": STATS_WINDOW,
            "engine": "Dixon-Coles 双泊松（half_life=730，真实国际赛数据）",
        },
    }
