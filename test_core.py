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
