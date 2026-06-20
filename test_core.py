#!/usr/bin/env python3
"""核心回归测试。跑：python3 -m pytest test_core.py -q

覆盖：数据加载、模型预测合理性、比分矩阵归一、未知队报错、
      __setstate__ 旧 pickle 回填（防"缺属性全站500"复发）、
      赛事模拟结构不变量、4 个 API 冒烟。
"""
import pickle

import numpy as np
import pytest

import data as datamod
from model import SCHEMA_VERSION, DixonColesModel
from predict import get_model


@pytest.fixture(scope="module")
def model():
    return get_model(use_cache=True, half_life=240.0, verbose=False)


# ---------- 数据层 ----------
def test_load_raw_columns():
    df = datamod.load_raw()
    for c in ("date", "home_team", "away_team", "home_score", "away_score", "tournament"):
        assert c in df.columns
    assert len(df) > 40000
    played = datamod.played(df)
    assert played["home_score"].notna().all()           # 已赛全部有比分
    assert len(played) < len(df)                          # 含未赛赛程


# ---------- 模型预测 ----------
def test_predict_probabilities_sane(model):
    r = model.predict("Argentina", "France", neutral=True)
    assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 1e-6
    for k in ("p_home", "p_draw", "p_away"):
        assert 0.0 <= r[k] <= 1.0
    assert r["xg_home"] > 0 and r["xg_away"] > 0
    assert len(r["top_scores"]) == 7


def test_score_matrix_normalized(model):
    *_, M = model.score_matrix("Brazil", "Germany", neutral=True)
    assert abs(M.sum() - 1.0) < 1e-9
    assert (M >= 0).all()


def test_unknown_team_raises(model):
    with pytest.raises(KeyError):
        model.predict("Atlantis", "France")


def test_home_advantage_increases_home_xg(model):
    neu = model.predict("Mexico", "Canada", neutral=True)
    home = model.predict("Mexico", "Canada", neutral=False)
    assert home["xg_home"] > neu["xg_home"]              # 主场应抬高主队 xG


# ---------- 缓存健壮性（回归：曾因旧 pickle 缺 use_elo 全站 500）----------
def test_cached_model_has_schema_version(model):
    assert getattr(model, "schema_version", 0) == SCHEMA_VERSION


def test_setstate_backfills_missing_attrs(model):
    """模拟"旧 pickle 缺新属性"，__setstate__ 应回填，predict 不再 AttributeError。"""
    state = model.__getstate__()
    for k in ("use_elo", "elo_coef", "elo_ratings", "comp_weights", "schema_version"):
        state.pop(k, None)                               # 制造旧版缺失
    m2 = DixonColesModel.__new__(DixonColesModel)
    m2.__setstate__(state)
    assert m2.use_elo is False and m2.elo_coef == 0.0    # 已回填
    r = m2.predict("Argentina", "France", neutral=True)  # 关键：不崩
    assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 1e-6


# ---------- 赛事模拟结构不变量 ----------
def test_project_structure(model):
    from simulate import TournamentSimulator
    sim = TournamentSimulator(model, datamod.load_raw(), sims=1)
    p = sim.project(today="2026-06-07")
    assert len(p["groups"]) == 12                         # 12 个小组
    r32 = [x for x in p["rounds"] if x["name"] == "R32"][0]
    assert len(r32["matches"]) == 16                      # R32 16 场
    assert [x["name"] for x in p["rounds"]] == ["R32", "R16", "QF", "SF", "Final"]
    assert p["champion"]                                  # 有冠军


# ---------- API 冒烟 ----------
@pytest.fixture(scope="module")
def client():
    import app as appmod
    return appmod.app.test_client()


def test_api_teams_48(client):
    r = client.get("/api/teams")
    assert r.status_code == 200 and len(r.get_json()) == 48


def test_api_predict_ok(client):
    d = client.get("/api/predict?home=Argentina&away=France&neutral=1").get_json()
    assert abs(d["p_home"] + d["p_draw"] + d["p_away"] - 1.0) < 0.02


def test_api_project_ok(client):
    d = client.post("/api/project", json={}).get_json()
    assert d["champion"] and "ko_facts" in d and len(d["rounds"]) == 5


def test_api_ratings_ok(client):
    d = client.get("/api/ratings").get_json()
    assert "rows" in d and "available" in d


# ---------- 预测验证层 ----------
def test_verify_outcome_and_rps():
    import verify
    assert verify._outcome(2, 0) == "H" and verify._outcome(0, 1) == "A"
    assert verify._outcome(1, 1) == "D"
    assert verify._rps(1.0, 0.0, 0.0, "H") == 0.0          # 完美预测
    assert abs(verify._rps(0.0, 0.0, 1.0, "H") - 1.0) < 1e-9  # 完全错
    # 顺序无关 key：淘汰赛同对阵两种顺序应同 key；小组赛保留主客序
    assert verify._kkey("France", "Brazil") == verify._kkey("Brazil", "France")
    assert verify._gkey("Mexico", "South Africa") != verify._gkey("South Africa", "Mexico")


def test_api_verify_ok(client):
    d = client.get("/api/verify").get_json()
    s = d["summary"]
    assert s["evaluated"] <= s["done"] and isinstance(d["rows"], list)
    assert s["outcome_hits"] <= s["evaluated"] and s["score_hits"] <= s["evaluated"]
    for r in d["rows"]:
        assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 0.02
        assert r["pick"] in ("H", "D", "A") and r["actual"] in ("H", "D", "A")


# ---------- In-play 实时层 ----------
def test_inplay_probabilities_sane(model):
    import inplay
    w = inplay.win_draw_loss(model, "Brazil", "Haiti", 1, 0, 60, neutral=True)
    assert abs(w["p_home"] + w["p_draw"] + w["p_away"] - 1.0) < 1e-9
    assert 0.0 <= w["p_home"] <= 1.0 and 0.0 <= w["t_rem"] <= 1.0


def test_inplay_t0_matches_prematch(model):
    """in-play 0 分钟应≈赛前 predict（缩放+卷积数学自洽）。"""
    import inplay
    pre = model.predict("Argentina", "Algeria", neutral=True)
    ip0 = inplay.win_draw_loss(model, "Argentina", "Algeria", 0, 0, 0, neutral=True)
    assert abs(ip0["p_home"] - pre["p_home"]) < 0.03


def test_inplay_endgame_collapses(model):
    """终场（90′）领先方应≈必胜（剩余时间归零）。"""
    import inplay
    w = inplay.win_draw_loss(model, "Germany", "Curaçao", 2, 0, 90, neutral=True)
    assert w["p_home"] > 0.99 and w["t_rem"] == 0.0


def test_inplay_isolation_no_ledger_write():
    """铁律：调用 in-play 绝不触碰 verify 账本 / 评估口径（赛前可证伪性零污染）。"""
    import os
    import inplay
    import verify
    led = verify.LEDGER_PATH
    before = os.path.getmtime(led) if os.path.exists(led) else None
    m = get_model(use_cache=True, half_life=730.0, verbose=False)
    for _ in range(20):
        inplay.win_draw_loss(m, "Brazil", "Morocco", 1, 1, 70, neutral=True)
    after = os.path.getmtime(led) if os.path.exists(led) else None
    assert before == after                                  # 账本文件未被 in-play 改动


def test_bj_date_beijing_kickoff_groups_by_beijing_day():
    """时区口径回归：展示日期必须按【北京】开球日，不按场馆当地日。
    反复修过的 off-by-one——凌晨开球场次（北京日 > 当地日）不能落到前一天。"""
    import verify
    # 北京 2026-06-19 00:00 开球（场馆当地是 6/18 晚）→ 必须归 6/19
    assert verify.bj_date("2026-06-19 00:00", "2026-06-18") == "2026-06-19"
    # 北京 2026-06-20 06:00（当地 6/19 下午）→ 6/20
    assert verify.bj_date("2026-06-20 06:00", "2026-06-19") == "2026-06-20"
    # 无 kickoff（retro 回补场）→ 回落到 fallback
    assert verify.bj_date("", "2026-06-11") == "2026-06-11"
    assert verify.bj_date(None, "2026-06-11") == "2026-06-11"


# ---------- 玄学占卜（趣味彩蛋层，确定性引擎）----------
METHOD_KEYS = {"meihua", "shefu", "yijing", "liuyao", "qimen", "daliuren", "ziwei"}


def test_xuanxue_seven_methods_and_valid_scores():
    """7 套术数齐全；每个比分合法（0..6 整数）、胜负与比分自洽、信心在区间内。"""
    import xuanxue
    r = xuanxue.divine("Argentina", "France")
    assert {m["key"] for m in r["methods"]} == METHOD_KEYS
    assert len(r["methods"]) == 7
    for m in r["methods"]:
        h, a = m["score"]
        assert isinstance(h, int) and isinstance(a, int)
        assert 0 <= h <= 6 and 0 <= a <= 6
        assert m["winner"] in ("home", "away", "draw")
        # 单法胜负与其比分自洽
        assert (m["winner"] == "home") == (h > a)
        assert (m["winner"] == "away") == (a > h)
        assert (m["winner"] == "draw") == (h == a)
        assert 0 <= m["confidence"] <= 100


def test_xuanxue_consensus_self_consistent():
    """共识胜负与共识比分必须自洽（防『主胜配平局比分』复发）；多对阵抽查。"""
    import itertools
    import xuanxue
    teams = ["Argentina", "France", "Brazil", "Spain", "England", "Japan", "Morocco"]
    for a, b in itertools.combinations(teams, 2):
        c = xuanxue.divine(a, b)["consensus"]
        h, aa = c["score"]
        w = c["winner"]
        assert (w == "home") == (h > aa)
        assert (w == "away") == (aa > h)
        assert (w == "draw") == (h == aa)


def test_ganzhi_pillars_known():
    """干支推算：日/时/年柱精确（锚点 2000-01-07甲子，已与 1949-10-01甲子交叉验证）。"""
    import datetime as _dt

    import ganzhi
    p = ganzhi.pillars(_dt.datetime(2026, 6, 11, 20, 0))
    assert p["day_gz"] == "丙辰"        # 2026-06-11 = 丙辰日
    assert p["hour_zhi"] == "戌"        # 20:00 = 戌时
    assert p["year_gz"] == "丙午"       # 2026 立春后 = 丙午年
    # 子时含 23 点（跨日边界）
    assert ganzhi.pillars(_dt.datetime(2026, 6, 11, 23, 30))["hour_zhi"] == "子"
    # 月将/月建为近似节气，至少应是合法地支
    assert p["month_jian"] in ganzhi.ZHI and p["month_jiang"] in ganzhi.ZHI


def test_xuanxue_deterministic():
    """同一对阵 + 同赛期 → 结果逐位可复现（种子来自队名+日期，不用随机）。"""
    import xuanxue
    a = xuanxue.divine("Brazil", "Spain", "2026-07-19 19:00")
    b = xuanxue.divine("Brazil", "Spain", "2026-07-19 19:00")
    assert a == b
    # 不同赛期应可能不同（至少不报错）
    xuanxue.divine("Brazil", "Spain", "2026-06-11 20:00")


def test_api_xuanxue_ok(client):
    d = client.get("/api/xuanxue?home=Argentina&away=France").get_json()
    assert len(d["methods"]) == 7 and "consensus" in d
    # 缺参数 → 400
    assert client.get("/api/xuanxue?home=Argentina").status_code == 400


def test_xuanxue_board_leaderboard_counts():
    """擂台统计逻辑：胜负命中/精确命中计数正确（合成账本，不依赖实时数据）。"""
    import xuanxue_board as xb
    preds = {
        "m1": {"home": "A", "away": "B", "result": {"gh": 2, "ga": 1}, "methods": [
            {"key": "k1", "name": "甲", "icon": "i", "score": [2, 1], "winner": "home"},  # 比分+胜负全中
            {"key": "k2", "name": "乙", "icon": "i", "score": [0, 0], "winner": "draw"},  # 全错
            {"key": "k3", "name": "丙", "icon": "i", "score": [3, 0], "winner": "home"}]},  # 仅胜负中
        "m2": {"home": "C", "away": "D", "result": None, "methods": [                       # 未结算→不计
            {"key": "k1", "name": "甲", "icon": "i", "score": [1, 1], "winner": "draw"}]},
    }
    board, settled_n = xb.leaderboard(preds)
    assert settled_n == 1                       # 只有 m1 已结算
    by = {r["key"]: r for r in board}
    assert by["k1"]["n"] == 1 and by["k1"]["outcome_hits"] == 1 and by["k1"]["exact_hits"] == 1
    assert by["k2"]["outcome_hits"] == 0 and by["k2"]["exact_hits"] == 0
    assert by["k3"]["outcome_hits"] == 1 and by["k3"]["exact_hits"] == 0
    # 排行按胜负命中率降序
    assert [r["key"] for r in board][0] in ("k1", "k3")


def test_api_xuanxue_board_ok(client):
    d = client.get("/api/xuanxue/board").get_json()
    assert "leaderboard" in d and "upcoming" in d and "settled" in d
    for r in d["leaderboard"]:                  # 命中数不可超过场次
        assert 0 <= r["outcome_hits"] <= r["n"]
        assert 0 <= r["exact_hits"] <= r["n"]
