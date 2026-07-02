#!/usr/bin/env python3
# Repository summary: World Cup prediction analytics module.
"""竞彩让球长期复盘系统（手动录入 + 赛后三方对账）——存储 + cover 结算 + 单场对账纯函数。

╔══════════════════════════════════════════════════════════════════════╗
║ 🔴 红线（设计层+schema层+测试层三重锁，详见 CLAUDE.md「竞彩复盘系统」条目）║
║ 定位：认清「我和模型都长期打不赢市场」、看懂盘怎么动——**绝不是找 edge/优化下注**。║
║ 1. 只做：单场事实留痕 + 单场三方对账（含 void）。                       ║
║ 2. 禁止跨场聚合成行动信号（历史胜率当edge/盈亏/ROI/「下次押X」）。      ║
║ 3. ⚠️ 即便描述性聚合也绝不出现「率」（胜率/准确率/命中率）——处方种子。 ║
║ 4. schema 断壁：本模块数据/输出**不得有** ROI/盈亏/*_rate/胜率→推荐 字段。║
║    `assert_no_rate_fields()` 在写盘与对账输出上强制校验。               ║
╚══════════════════════════════════════════════════════════════════════╝

口径：竞彩按 90 分钟（含补时、不含加时点球）结算。赛后比分**手填 90 分钟**，
**不复用 results.csv**（那是含加时口径）。只让球 cover（1X2 暂不做）。
"""
from __future__ import annotations
import json
import os

import manager
import explainer

STORE = os.path.join(os.path.dirname(__file__), "data", "jc_review.json")

# schema 断壁：记录/输出里**绝不允许**出现的字段名子串（滑向买/跳的第一级台阶）。
_FORBIDDEN_KEYS = ("rate", "率", "roi", "profit", "盈亏", "盈利", "胜率", "命中率",
                   "准确率", "edge", "recommend", "推荐", "该买", "该押", "kelly", "stake")


def assert_no_rate_fields(obj, path="root"):
    """递归校验 dict/list 里没有任何「率」/盈亏/推荐 类键——把红线锁进数据结构层。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            kl = str(k).lower()
            for bad in _FORBIDDEN_KEYS:
                if bad in kl:
                    raise ValueError(f"红线违规：复盘 schema 出现禁用字段「{k}」@{path}"
                                     f"——本系统不得聚合成胜率/盈亏/行动处方。")
            assert_no_rate_fields(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            assert_no_rate_fields(v, f"{path}[{i}]")
    return obj


def match_key(date: str, home_en: str, away_en: str) -> str:
    return f"{date}_{home_en}_{away_en}"


# ---------- 存储 ----------
def load_all() -> dict:
    try:
        with open(STORE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_all(d: dict):
    assert_no_rate_fields(d)                       # 写盘前断壁
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# ---------- cover 结算（90 分钟手填比分 + 竞彩整数/半球线 → 谁 cover） ----------
def cover_outcome(h90: int, a90: int, fav_is_home: bool, line: float) -> str:
    """返回 'fav' / 'dog' / 'push'（走盘=void）。站让球方(fav)角度按 settle_line 同口径。"""
    fav_margin = (h90 - a90) if fav_is_home else (a90 - h90)
    adj = fav_margin - line
    if abs(adj) < 1e-9:
        return "push"
    return "fav" if adj > 0 else "dog"


# ---------- 三方对账（单场，含 void / 跳过 N-A） ----------
def _side_pick(cover_prob_fav: float) -> str:
    """由 fav cover 概率定某方判断：>0.5 判 fav cover，否则 dog cover。"""
    return "fav" if cover_prob_fav > 0.5 else "dog"


def reconcile(rec: dict) -> dict:
    """单场三方对账：我/模型/市场 各 对/错/void。无赛后比分 → 状态 pending。
    走盘 → 三方全 void（不计对错）；我跳过 → 我这行 N/A。挂 CLV 先验注脚。"""
    jc = rec["jc"]; fav_is_home = jc["fav_is_home"]; line = float(jc["line"])
    fav_name = jc["fav_name"]; dog_name = jc["dog_name"]
    out = {"key": rec.get("key"), "fav_name": fav_name, "dog_name": dog_name,
           "line": line, "prior_note": explainer.CLV_PRIOR}
    res = rec.get("result")
    if not res or res.get("h90") is None or res.get("a90") is None:
        out["status"] = "pending"
        return out
    actual = cover_outcome(int(res["h90"]), int(res["a90"]), fav_is_home, line)
    out["status"] = "settled"
    out["score_90"] = f"{res['h90']}-{res['a90']}"
    out["actual_cover"] = actual           # fav / dog / push
    if actual == "push":
        out["void"] = True
        for who in ("me", "model", "market"):
            out[who] = {"pick": None, "verdict": "void"}     # 走盘全部不计
        return out
    out["void"] = False
    # 模型 / 市场 的判断（由各自 fav cover 概率派生）
    model_pick = _side_pick(rec["model"]["fav_cover"])
    market_pick = _side_pick(rec["market"]["fav_cover"])
    my_pick = rec["my_call"]["pick"]                          # 'fav'/'dog'/'skip'
    def verdict(pick):
        if pick == "skip" or pick is None:
            return "na"                                       # 跳过=不计分
        return "hit" if pick == actual else "miss"
    out["me"] = {"pick": my_pick, "verdict": verdict(my_pick),
                 "note": rec["my_call"].get("note", "")}
    out["model"] = {"pick": model_pick, "verdict": verdict(model_pick)}
    out["market"] = {"pick": market_pick, "verdict": verdict(market_pick)}
    return assert_no_rate_fields(out)                         # 对账输出也断壁


# ---------- 录入 / 赛后填分 ----------
def upsert_prematch(date, home_en, away_en, home_disp, away_disp, is_knockout,
                    fav_is_home, line, o_fav, o_dog,
                    model_fav_cover, model_1x2, pred_score,
                    my_pick, my_note="", frozen_at=None):
    """赛前录入（含我的判断 + 模型冻结 cover）。fav=让球方。
    frozen_at=录入那一刻的时间戳（模型在此刻冻结，复盘看「我当时看到的模型」，非赛后回填）。"""
    d = load_all()
    k = match_key(date, home_en, away_en)
    fav_name = home_disp if fav_is_home else away_disp
    dog_name = away_disp if fav_is_home else home_disp
    # 市场 fav cover 概率：竞彩让球两栏（fav cover 赔 / dog cover 赔）2 路 Shin 去水。
    import devig
    p_mkt, _ = devig.implied2(float(o_fav), float(o_dog), "shin")
    prev = d.get(k, {})
    d[k] = {
        "key": k, "date": date, "home_en": home_en, "away_en": away_en,
        "home_disp": home_disp, "away_disp": away_disp, "is_knockout": bool(is_knockout),
        "jc": {"fav_is_home": bool(fav_is_home), "line": float(line),
               "fav_name": fav_name, "dog_name": dog_name,
               "o_fav": float(o_fav), "o_dog": float(o_dog)},
        "model": {"fav_cover": float(model_fav_cover), "p1x2": model_1x2,
                  "pred_score": pred_score, "frozen_at": frozen_at},
        "market": {"fav_cover": float(p_mkt[0])},              # 竞彩 Shin 去水 fav cover 概率
        "my_call": {"pick": my_pick, "note": my_note},        # 'fav'/'dog'/'skip'
        "result": prev.get("result"),                          # 保留已填赛果
    }
    _save_all(d)
    return d[k]


def enter_result(date, home_en, away_en, h90: int, a90: int):
    """赛后手填 90 分钟比分（不复用 results.csv 含加时口径）。"""
    d = load_all()
    k = match_key(date, home_en, away_en)
    if k not in d:
        raise KeyError(f"未找到赛前记录 {k}，请先录入。")
    d[k]["result"] = {"h90": int(h90), "a90": int(a90)}
    _save_all(d)
    return reconcile(d[k])


def reading_card(rec: dict) -> dict:
    """派生读盘卡（复用 explainer，90 分钟口径）——非存储字段，每次现生成。"""
    jc = rec["jc"]
    hA = explainer.handicap_structure(jc["o_fav"], jc["o_dog"], jc["line"], jc["fav_name"])
    hC = explainer.handicap_divergence(rec["model"]["fav_cover"], hA["implied_cover_shin"]["fav"])
    return explainer.handicap_reading(hA, hC, rec["is_knockout"], jc["fav_name"], jc["dog_name"])
