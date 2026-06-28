#!/usr/bin/env python3
"""市场机制解释器（market mechanism explainer）——【信息性·描述性认知】模块。

╔══════════════════════════════════════════════════════════════════════╗
║ 红线（硬约束，设计层而非事后审查；改动前先读 CLAUDE.md 同名条目）       ║
║ 1. 禁止输出任何「买入/跳过/值得下/推荐下注」类指令或其等价物——          ║
║    包括打分阈值映射到行动、星级、红绿灯、value-bet 标签等任何变体。      ║
║ 2. 输出只能是【描述性认知】：水位结构、隐含概率、偏差量、分歧度、效率证据。║
║ 3. 任何「模型概率 vs 市场概率」分歧处，默认叙述必须诚实：本模型样本外     ║
║    CLV 显著<0、让球 MAE 打不赢市场 → 分歧时先验是「市场对、模型错」，      ║
║    不得叙述成「发现了 edge」。                                          ║
║ 4. 若被要求改回买/跳形态，按 CLAUDE.md 红线拒绝。                       ║
╚══════════════════════════════════════════════════════════════════════╝

本期实现：A 水位结构拆解 + C 模型 vs 市场分歧地图 + 赛前线移动（全部 1X2）。
B（FLB/大热必死）、D（诱惑形态命名）【冻结】——见 bt_explainer.b_gate：每概率桶
样本 ≥30 且 FLB 偏差 CI 不跨 0 才解锁，在那之前**根本不渲染**（不是标未证实）。

零碰 GLM/账本：只读模型预测 + 市场赔率，纯描述。复用 devig(Shin)。
"""
from __future__ import annotations
import numpy as np
import devig

# 红线守卫 denylist：拦的是「指导下注/弃注行为」这个**功能**，覆盖已知行动等价词全谱
# （下注指令 / 弃注指令 / 评分→行动 / 信号灯 / 星级 / 价值标签 / 绝对化营销 / 泛行动建议）。
# 注：这是 denylist，覆盖已知变体；全新措辞仍可能漏（语义级守卫无解），故新增渲染分支需补词。
# ⚠ 不得加入「投注建议」——disclaimer 含「非投注建议」会自伤（narrative.py 同坑）。
_BANNED = (
    # 下注 / 买卖指令
    "买入", "买进", "可以买", "值得买", "该买", "建议买", "下注", "值得下", "建议下", "该下",
    "可以下", "上车", "梭", "加仓", "减仓", "抄底", "低吸", "清仓", "止盈", "止损", "跟单",
    "跟注", "反买", "对冲下注",
    # 弃注 / 跳过指令（弃注=行动指令的反面，同样越界）
    "跳过此盘", "该跳", "可跳", "放弃此盘", "别买", "不要买",
    # 评分→行动 / 信号灯 / 星级
    "绿灯", "红灯", "信号灯", "星级", "★", "☆", "评级买", "打分买", "推荐",
    # 价值标签
    "value bet", "+ev", "正ev", "值博", "值博率", "性价比买",
    # 绝对化营销
    "稳赚", "必中", "包赢", "稳胆", "必赢", "稳过",
    # 泛行动建议
    "可以考虑", "值得考虑", "考虑下注", "建议关注买",
)

# 红线#3：模型 vs 市场分歧的强制诚实先验（已建层实证结论，非临时口号）。
CLV_PRIOR = ("本模型样本外 CLV 显著<0、让球点估 MAE 打不赢市场闭盘线，"
             "故任一分歧的先验是「市场对、模型错」——下列分歧更可能是模型误差，而非市场错价。")


def _assert_clean(text: str):
    """渲染文本红线自检：含任一行动/劝导词即抛（设计层守卫，不靠人工审查）。"""
    for w in _BANNED:
        if w in text:
            raise ValueError(f"红线违规：解读卡含行动/劝导词「{w}」——本模块只做描述性认知。\n{text}")
    return text


def _kl(p, q):
    """KL(p‖q)，nats。p=模型，q=市场。"""
    p = np.asarray(p, float); q = np.asarray(q, float)
    return float(np.sum(np.where(p > 0, p * np.log(p / np.clip(q, 1e-12, None)), 0.0)))


def orient_odds(row_home, row_away, q_home, q_away, o1, ox, o2):
    """把某 odds 行的 (o1 主胜, ox 平, o2 客胜) 定向到查询 (q_home 主, q_away 客) 同框。
    行队序与查询相反时交换主/客赔率（平不变）。返回 (c1, cx, c2)。
    （回归：曾因未交换导致 C 段把「模型主胜」对上「市场客胜」，方向错乱。）"""
    if row_home == q_away and row_away == q_home:
        return o2, ox, o1
    return o1, ox, o2


def water_structure(o1, ox, o2, margin_baseline=None):
    """A 水位结构拆解：Shin de-vig 真实隐含概率 + margin/overround + 水位异常标注。
    margin_baseline=(q25,q75) 时据此标 偏高/偏低（纯描述，不导向任何行动）。"""
    shin = devig.shin(o1, ox, o2)
    prop = devig.proportional(o1, ox, o2)
    overround = float(1.0 / o1 + 1.0 / ox + 1.0 / o2 - 1.0)
    flag = "（无基准）"
    if margin_baseline:
        q25, q75 = margin_baseline
        flag = "偏高" if overround > q75 else ("偏低" if overround < q25 else "正常区间")
    return {
        "raw_odds": {"home": float(o1), "draw": float(ox), "away": float(o2)},
        "implied_shin": {"home": float(shin[0]), "draw": float(shin[1]), "away": float(shin[2])},
        "implied_naive": {"home": float(prop[0]), "draw": float(prop[1]), "away": float(prop[2])},
        "overround": overround, "overround_flag": flag,
    }


def divergence_map(model_probs, market_shin):
    """C 模型 vs 市场分歧地图：KL + 逐结果概率差 + 强制 CLV 先验注脚。"""
    mp = np.array(model_probs, float); mk = np.array(market_shin, float)
    labels = ("主胜", "平", "客胜")
    diffs = {labels[i]: float(mp[i] - mk[i]) for i in range(3)}
    big = max(labels, key=lambda L: abs(diffs[L]))
    return {
        "model": {labels[i]: float(mp[i]) for i in range(3)},
        "market": {labels[i]: float(mk[i]) for i in range(3)},
        "kl_model_vs_market": _kl(mp, mk),
        "per_outcome_diff": diffs,
        "largest": {"outcome": big, "diff": diffs[big]},
        "prior_note": CLV_PRIOR,
    }


def line_shift(o_open, o_close):
    """赛前线移动（开→闭，纯描述：各结果隐含概率变了多少、总变差）。无开盘则 None。"""
    if o_open is None or any(x is None or (isinstance(x, float) and np.isnan(x)) for x in o_open):
        return None
    op = devig.shin(*o_open); cp = devig.shin(*o_close)
    labels = ("主胜", "平", "客胜")
    return {
        "shift": {labels[i]: float(cp[i] - op[i]) for i in range(3)},
        "total_variation": float(0.5 * np.abs(cp - op).sum()),
    }


def handicap_structure(o_fav, o_dog, fav_line, fav_name, method="shin"):
    """A（让球）：2 路 Shin 去水真实 cover 隐含概率 + overround。"""
    p, overround = devig.implied2(o_fav, o_dog, method)
    return {"fav_name": fav_name, "line": float(fav_line),
            "odds": {"fav_cover": float(o_fav), "dog_cover": float(o_dog)},
            "implied_cover_shin": {"fav": float(p[0]), "dog": float(p[1])},
            "overround": float(overround)}


def handicap_divergence(model_fav_cover, market_fav_cover):
    """C（让球）：模型 vs 市场 的强队 cover 概率分歧 + 强制 CLV 先验注脚。"""
    return {"model_fav_cover": float(model_fav_cover), "market_fav_cover": float(market_fav_cover),
            "diff": float(model_fav_cover - market_fav_cover), "prior_note": CLV_PRIOR}


def handicap_reading(hA, hC, is_knockout, fav_name, dog_name):
    """读盘卡：纯规则翻译 + 【含加时结算】确定性对照（零预测、零方向、不出买哪边）。
    全用实际队名（不用强队/弱队，避免看反）。复用 hA(2路Shin去水)/hC(模型cover+CLV先验)。"""
    line = float(hA["line"])
    is_int = abs(line - round(line)) < 1e-9
    fav_lbl = f"{fav_name}(-{line:g})"      # 被看好方让球：墨西哥(-1.5)
    dog_lbl = f"{dog_name}(+{line:g})"      # 受让方：南非(+1.5)
    warn = "⚠ 本盘按【含加时及点球的最终比分】结算，不是 90 分钟比分。" + (
        "本场为淘汰赛：90 分钟战平、加时分胜负的场次，cover 结果可能与上半程直觉相反；"
        "且本模型 cover 概率是**常规时间口径、未计入加时进球**，与本盘含加时结算口径有 gap，仅供参考。"
        "→ 看淘汰赛让球盘时，以盘口写明的结算口径为准，别用 90 分钟比分套这张表的 cover 结论。"
        if is_knockout else
        "本场为小组赛、常规无加时，最终比分即 90 分钟比分，模型与盘口口径一致。")
    floor_l = int(line)                      # 受让方「最多输几球仍 cover」的阈值
    dog_keep = ("平或赢都算赢" if floor_l == 0 else f"最多输 {floor_l} 球（或平/赢）都算赢")
    if is_int:
        trans = (f"{fav_name} 让 {line:g} 球：{fav_lbl} 在【最终】净胜 >{line:g} 时赢盘、"
                 f"净胜 ={line:g} 走盘退本、<{line:g} 输盘；{dog_lbl} 相反。")
        chk = (f"🧭 自检：让球数带「-」的是被看好方，要赢够球数才算赢；带「+」的少输/平/赢都算赢。"
               f"本场：{fav_name}-{line:g}（要赢 >{line:g}、赢 {line:g} 走盘）、{dog_name}+{line:g}（{dog_keep}、输 {line:g} 走盘）。")
    else:
        need = line + 0.5
        trans = (f"{fav_name} 让 {line:g} 球（半球、无走盘）：{fav_lbl} 在【最终】净胜 ≥{need:g} 时赢盘；"
                 f"{dog_lbl} 在 {fav_name} 最终净胜 ≤{floor_l}（含平、负）时赢盘。")
        chk = (f"🧭 自检：让球数带「-」的是被看好方，要赢够球数才算赢；带「+」的少输/平/赢都算赢。"
               f"本场：{fav_name}-{line:g}（要赢 ≥{need:g}）、{dog_name}+{line:g}（{dog_keep}）。")

    def verdict(m):
        if is_int and abs(m - line) < 1e-9:
            return "走盘退本（双方退本金）"
        return f"{fav_lbl} cover" if m > line else f"{dog_lbl} cover"

    rows = []
    for m in range(int(line) + 2, -3, -1):
        if m == 0:
            lab = "双方打平（含加时仍平→点球决出晋级，但点球只决定晋级、不决定让球；让球按最终净胜=0 算）"
        elif m > 0:
            lab = f"{fav_name} 最终净胜 {m}"
        else:
            lab = f"{fav_name} 最终净负 {-m}"
        rows.append({"margin": m, "label": lab, "verdict": verdict(m)})
    return {"settle_warning": warn, "translation": trans, "self_check": chk,
            "is_knockout": bool(is_knockout), "fav_label": fav_lbl,
            "caliber": ("淘汰赛·盘口含加时 vs 模型常规时间 → 有 gap" if is_knockout
                        else "小组赛·无加时 → 口径一致"),
            "cover_table": rows, "model_fav_cover": hC["model_fav_cover"],
            "market_fav_cover": hC["market_fav_cover"], "prior_note": hC["prior_note"]}


def explain_match(name, model_probs, close_odds, open_odds=None, margin_baseline=None,
                  handicap=None):
    """组装单场机制解读卡（dict）。所有字段=描述/解释，无任何行动建议。
    handicap（可选）={o_fav,o_dog,fav_line,fav_name,model_fav_cover}：附让球 A/C 段。"""
    A = water_structure(*close_odds, margin_baseline=margin_baseline)
    C = divergence_map(model_probs, (A["implied_shin"]["home"], A["implied_shin"]["draw"],
                                     A["implied_shin"]["away"]))
    mv = line_shift(open_odds, close_odds)
    card = {"match": name, "A_water_structure": A, "C_divergence": C,
            "line_movement": mv, "B_D_status": "frozen（样本不足，见 bt_explainer.b_gate）",
            "disclaimer": "描述性认知，非投注建议，不含买/跳指令；理性观赛、量力而行。"}
    if handicap:
        hA = handicap_structure(handicap["o_fav"], handicap["o_dog"],
                                handicap["fav_line"], handicap["fav_name"])
        hC = handicap_divergence(handicap["model_fav_cover"], hA["implied_cover_shin"]["fav"])
        card["A_handicap"] = hA
        card["C_handicap_divergence"] = hC
        card["handicap_reading"] = handicap_reading(
            hA, hC, handicap.get("is_knockout", False),
            handicap["fav_name"], handicap.get("dog_name", "受让方"))
    _assert_clean(render(card))   # 设计层红线自检
    return card


def render(card) -> str:
    """把解读卡渲染成中文文本（同时供红线自检扫描）。"""
    A, C, mv = card["A_water_structure"], card["C_divergence"], card["line_movement"]
    L = [f"📊 {card['match']} · 市场机制解读（描述性，非投注建议）", "",
         "【A 水位结构】",
         f"  毛赔率 主 {A['raw_odds']['home']:.2f} / 平 {A['raw_odds']['draw']:.2f} / 客 {A['raw_odds']['away']:.2f}",
         f"  Shin 去水真实隐含：主 {A['implied_shin']['home']:.1%} / 平 {A['implied_shin']['draw']:.1%}"
         f" / 客 {A['implied_shin']['away']:.1%}",
         f"  抽水(overround)={A['overround']:.1%}，水位{A['overround_flag']}",
         "", "【C 模型 vs 市场分歧】",
         f"  模型：主 {C['model']['主胜']:.1%} / 平 {C['model']['平']:.1%} / 客 {C['model']['客胜']:.1%}",
         f"  市场：主 {C['market']['主胜']:.1%} / 平 {C['market']['平']:.1%} / 客 {C['market']['客胜']:.1%}",
         f"  KL(模型‖市场)={C['kl_model_vs_market']:.4f} nats；最大分歧在「{C['largest']['outcome']}」"
         f"（模型−市场 {C['largest']['diff']:+.1%}）",
         f"  ⚠ {C['prior_note']}"]
    if mv:
        s = mv["shift"]
        L += ["", "【赛前线移动 开→闭】",
              f"  隐含概率位移：主 {s['主胜']:+.1%} / 平 {s['平']:+.1%} / 客 {s['客胜']:+.1%}"
              f"（总变差 {mv['total_variation']:.1%}）"]
    hA, hC = card.get("A_handicap"), card.get("C_handicap_divergence")
    if hA and hC:
        L += ["", f"【A 让球水位】{hA['fav_name']} 让 {hA['line']:.2g} 球",
              f"  双边水位 强队cover {hA['odds']['fav_cover']:.2f} / 弱队受让 {hA['odds']['dog_cover']:.2f}"
              f"，抽水 {hA['overround']:.1%}",
              f"  Shin 去水真实 cover 隐含：强队 {hA['implied_cover_shin']['fav']:.1%}"
              f" / 弱队 {hA['implied_cover_shin']['dog']:.1%}",
              "【C 让球分歧】",
              f"  强队 cover 概率：模型 {hC['model_fav_cover']:.1%} vs 市场 {hC['market_fav_cover']:.1%}"
              f"（模型−市场 {hC['diff']:+.1%}）",
              f"  ⚠ {hC['prior_note']}"]
    rd = card.get("handicap_reading")
    if rd:
        L += ["", "【读盘卡 · 含加时结算】", f"  {rd['settle_warning']}",
              f"  规则翻译：{rd['translation']}",
              f"  {rd['self_check']}",
              f"  口径：{rd['caliber']}",
              "  最终比分(含加时) → 谁 cover："]
        for r in rd["cover_table"]:
            L.append(f"    {r['label']} → {r['verdict']}")
        L += [f"  {rd['fav_label']} cover 概率：模型 {rd['model_fav_cover']:.1%} vs 市场 {rd['market_fav_cover']:.1%}"
              f"（{('淘汰赛模型偏常规时间、仅供参考' if rd['is_knockout'] else '小组赛口径一致')}）",
              f"  ⚠ {rd['prior_note']}"]
    L += ["", f"  {card['disclaimer']}"]
    return "\n".join(L)


def build_card(m, home, away):
    """组装单场机制解读卡（CLI 与 /api/explainer 共用）。读 odds.csv + handicap_lines.json，
    模型预测来自传入的 m。无赔率 → 返回 None（无可拆解的市场结构）。"""
    import os, json, pandas as pd
    import manager, teams_zh
    base = os.path.dirname(__file__)
    odds = pd.read_csv(os.path.join(base, "data", "odds.csv"))
    odds["overround"] = 1 / odds.odds_1 + 1 / odds.odds_x + 1 / odds.odds_2 - 1
    q25, q75 = odds["overround"].quantile([0.25, 0.75])
    h = m.resolve(home); a = m.resolve(away)
    row = odds[((odds.home_team == h) & (odds.away_team == a)) |
               ((odds.home_team == a) & (odds.away_team == h))]
    if row.empty:
        return None
    o = row.iloc[0]
    pr = m.predict(h, a, neutral=True)
    c1, cx, c2 = orient_odds(o.home_team, o.away_team, h, a, o.odds_1, o.odds_x, o.odds_2)
    has_open = not any(pd.isna(o[c]) for c in ("odds_1_open", "odds_x_open", "odds_2_open"))
    open_odds = None if not has_open else orient_odds(
        o.home_team, o.away_team, h, a, o.odds_1_open, o.odds_x_open, o.odds_2_open)
    hc = None
    try:
        hl = json.load(open(os.path.join(base, "data", "handicap_lines.json")))
        rec = next((v for v in hl.values() if {v["home"], v["away"]} == {h, a}), None)
        if rec and rec.get("fav_spread_odds") and rec.get("dog_spread_odds"):
            *_, M = m.score_matrix(h, a, neutral=True)
            s = manager.settle_line(manager._margin_pmf(M), rec["fav_is_home"], rec["fav_line"])
            denom = s["win"] + s["lose"]
            # 含加时结算口径标注：淘汰赛(date>=R32 起始)盘口含加时，而模型是常规时间分布 → 有 gap。
            is_ko = str(rec.get("date", "")) >= "2026-06-28"
            hc = {"o_fav": rec["fav_spread_odds"], "o_dog": rec["dog_spread_odds"],
                  "fav_line": rec["fav_line"], "is_knockout": is_ko,
                  "fav_name": teams_zh.disp(h if rec["fav_is_home"] else a),
                  "dog_name": teams_zh.disp(a if rec["fav_is_home"] else h),
                  "model_fav_cover": s["win"] / denom if denom > 1e-9 else s["win"]}
    except Exception:  # noqa  让球段缺失不影响 1X2 卡
        hc = None
    return explain_match(f"{teams_zh.disp(h)} vs {teams_zh.disp(a)}",
                         (pr["p_home"], pr["p_draw"], pr["p_away"]),
                         (c1, cx, c2), open_odds, (q25, q75), handicap=hc)


def _cli():
    import argparse
    import predict
    ap = argparse.ArgumentParser()
    ap.add_argument("home"); ap.add_argument("away")
    args = ap.parse_args()
    m = predict.get_model(use_cache=True, half_life=730.0, verbose=False)
    card = build_card(m, args.home, args.away)
    print(render(card) if card else f"odds.csv 无 {args.home} vs {args.away} 的赔率，换一场。")


if __name__ == "__main__":
    _cli()
