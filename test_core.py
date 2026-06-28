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
    # played() 应恰好滤掉无比分行：用原始赛程(live=False，保留未赛 NA 行)验语义，
    # 不依赖 live 合并是否已把赛程填满——赛事推进到赛程末尾时 live 口径可能已无未赛行
    # (2026-06-28 即如此：赛程止于 6-27 且全部已赛，live 下 played==df 会误伤本断言)。
    raw = datamod.load_raw(live=False)
    raw_played = datamod.played(raw)
    assert raw_played["home_score"].notna().all()
    assert len(raw_played) < len(raw)                     # 原始赛程含未赛赛程行


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


def test_api_version_shape(client):
    """仓库更新检测端点：离线/在线都应返回结构化结果（失败优雅降级 ok=False，不抛错）。"""
    d = client.get("/api/version").get_json()
    assert "update_available" in d and "local" in d and "ok" in d
    assert isinstance(d["update_available"], bool)


def test_api_fixtures_matches_dashboard_upcoming(client):
    """回归：/api/fixtures 的未开赛小组赛集合必须与看板 /api/dashboard 的 upcoming 一致。
    曾因 fixtures 用『全历史交手过的队对』过滤，把历史踢过友谊赛的未来对阵（如英格兰vs加纳）误删，
    导致对阵分析比看板少 15 场。两接口同源同口径，集合应完全相同。"""
    fx = client.get("/api/fixtures").get_json()["fixtures"]
    up = client.get("/api/dashboard").get_json()["upcoming"]
    fx_pairs = {(r["home_en"], r["away_en"]) for r in fx}
    up_pairs = {(r["home_en"], r["away_en"]) for r in up if r.get("stage") == "group"}
    assert fx_pairs == up_pairs, f"fixtures 与看板 upcoming 不一致：仅在看板={up_pairs - fx_pairs}，仅在fixtures={fx_pairs - up_pairs}"


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


# ---------- 首发名单层（lineups / 增益记分卡 / avail_override） ----------
def test_avail_override_identity_and_effect(model):
    """avail_override=None 与不传逐位恒等（零影响现有路径）；缺阵乘子降低强队主胜。"""
    r0 = model.predict("Brazil", "Haiti", neutral=True)
    rn = model.predict("Brazil", "Haiti", neutral=True, avail_override=None)
    assert abs(r0["p_home"] - rn["p_home"]) < 1e-12
    re = model.predict("Brazil", "Haiti", neutral=True, avail_override={})  # 强制纯 DC
    assert abs(re["p_home"] + re["p_draw"] + re["p_away"] - 1.0) < 1e-9
    rm = model.predict("Brazil", "Haiti", neutral=True, avail_override={"Brazil": (0.85, 1.15)})
    assert rm["p_home"] < re["p_home"]          # 削巴西进攻 → 主胜下降


def test_lineups_norm_and_classify():
    import lineups
    assert lineups._norm("Frenkie de Jong") == "frenkiedejong"
    assert lineups._norm("Müller") == "muller"            # 去重音
    lt = {"confirmed": True, "starters": [lineups._norm("Jamal Musiala")],
          "bench": [lineups._norm("Florian Wirtz")]}
    assert lineups._classify("Musiala", lt)[0] == "started"   # 姓匹配首发
    assert lineups._classify("Wirtz", lt)[0] == "bench"
    assert lineups._classify("Rodrygo", lt)[0] == "absent"    # 不在名单 → 确认缺阵
    assert lineups._classify("X", {"confirmed": False})[0] == "unknown"  # 未公布 → 降级


def test_lineups_detect_team_overrides_prob():
    import lineups
    items = [{"player": "Rodrygo", "tier": "key", "role": "attack",
              "status": "doubtful", "prob": 0.3}]
    new, status = lineups.detect_team("Brazil", items, {"confirmed": True, "starters": [], "bench": []})
    assert new[0]["prob"] == 1.0 and new[0]["status"] == "out"   # 首发确认缺阵覆盖赛前 doubtful
    assert status[0]["lineup_status"] == "absent"


def test_lineup_ledger_rps_matches_backtest():
    import lineup_ledger, backtest
    assert lineup_ledger._rps(1.0, 0.0, 0.0, 0) == 0.0          # 完美预测主胜
    assert abs(lineup_ledger._rps(0.5, 0.3, 0.2, 1) - backtest._rps(0.5, 0.3, 0.2, 1)) < 1e-12


def test_api_fixtures_ok(client):
    d = client.get("/api/fixtures").get_json()
    assert "fixtures" in d and isinstance(d["fixtures"], list)
    for f in d["fixtures"]:
        assert {"home_en", "away_en", "home", "away", "kickoff"} <= set(f)


# ---------- 让球结论 + 上下文 + 动机层（2026-06-25 新增） ----------
def test_handicap_conclusion_shape_and_monotone(model):
    """让球结论：公平盘在档位表内、净胜率随让球档单调非增、公平盘≈净最小、上限不亏。"""
    import manager
    import numpy as np
    _, _, lam_h, lam_a, M = model.score_matrix("Brazil", "Haiti", neutral=True)
    mp = manager._margin_pmf(M)
    hc = manager.handicap_conclusion(mp, True, "Brazil", "Haiti")
    lines = hc["lines"]
    assert hc["fav"] == "Brazil" and hc["dog"] == "Haiti"
    assert any(abs(s["line"] - hc["fair_line"]) < 1e-9 for s in lines)   # 公平盘是真实档
    # 让球越多，站强队角度净胜率(net)单调非增
    nets = [s["net"] for s in lines]
    assert all(nets[i] >= nets[i + 1] - 1e-9 for i in range(len(nets) - 1))
    # 公平盘 = |net| 最小档
    fair = min(lines, key=lambda s: abs(s["net"]))
    assert abs(fair["line"] - hc["fair_line"]) < 1e-9
    # 建议上限不亏（net≥0），且每档赢/走/输归一
    mf = [s for s in lines if abs(s["line"] - hc["max_fair_line"]) < 1e-9][0]
    assert mf["net"] >= -1e-9
    for s in lines:
        assert abs(s["win"] + s["push"] + s["lose"] - 1.0) < 1e-6
        assert s["verdict"] in ("偏值", "接近公平", "偏亏")


def test_settle_line_quarter_and_whole(model):
    """分球盘(.75)无走盘、整数盘(让2)有走盘=净胜恰好2球的概率。"""
    import manager
    _, _, _, _, M = model.score_matrix("Brazil", "Haiti", neutral=True)
    mp = manager._margin_pmf(M)
    s2 = manager.settle_line(mp, True, 2.0)
    assert s2["push"] > 0 and abs(s2["push"] - mp.get(2, 0.0)) < 1e-9   # 走盘=净胜2
    sq = manager.settle_line(mp, True, 2.75)
    assert sq["push"] == 0.0                                            # 分球盘退本并入赢/输


def test_standings_gd_table_and_clinch():
    """全队净胜球榜按净胜球降序、名次连续；clinch_status 状态合法且保守。"""
    import app, standings
    sim = app._sim()
    tab = standings.tournament_gd_table(sim)
    assert tab and all(tab[i]["gd"] >= tab[i + 1]["gd"] for i in range(len(tab) - 1))
    assert [r["rank"] for r in tab] == list(range(1, len(tab) + 1))
    cs = standings.clinch_status(sim, "Argentina")
    assert cs["state"] in ("clinched_first", "clinched_qualify", "alive", "eliminated")
    assert cs["qualified"] == (cs["state"] in ("clinched_first", "clinched_qualify"))
    gt = standings.group_table(sim, "Morocco")
    assert gt["group"] == "C" and len(gt["rows"]) == 4
    keys = [(r["pts"], r["gd"], r["gf"]) for r in gt["rows"]]   # 排序键逐行非增
    assert all(keys[i] >= keys[i + 1] for i in range(len(keys) - 1))
    assert [r["rank"] for r in gt["rows"]] == [1, 2, 3, 4]


def test_motivation_adjust_shrinks_favorite_handicap(model):
    """动机降权：强队已出线时 motiv_adj 缩进攻 λ → 公平让球档下降（或持平），且预警常开。"""
    import manager
    import data as dm
    df = dm.load_raw()
    clinched = {"qualified": True, "top1": True, "label": "已锁定小组头名", "state": "clinched_first"}
    base = manager.build_report(model, df, "Argentina", "Jordan", neutral=True,
                                context={"home_clinch": clinched, "away_clinch": None,
                                         "motiv_adj": False})
    adj = manager.build_report(model, df, "Argentina", "Jordan", neutral=True,
                               context={"home_clinch": clinched, "away_clinch": None,
                                        "motiv_adj": True})
    assert base["motivation"]["warnings"]                     # 预警常开
    assert base["motivation"]["adjusted"] is False
    assert adj["motivation"]["adjusted"] is True
    # 降权后强队公平让球档不升（轮换→大盘缩水）
    assert adj["markets"]["handicap"]["fair_line"] <= base["markets"]["handicap"]["fair_line"] + 1e-9
    # 无 context 时退化为纯模型（无 motivation 块不报错）
    plain = manager.build_report(model, df, "Brazil", "Haiti", neutral=True)
    assert plain["motivation"] is None and "handicap" in plain["markets"]


# ---------- 让球命中率擂台（2026-06-25 续） ----------
def test_handicap_ledger_settle_helpers():
    """让球擂台结算原子函数：竞彩三向桶、cover 判定、Wilson 区间边界。"""
    import handicap_ledger as hl
    assert hl._jc_actual(3) == "让胜" and hl._jc_actual(1) == "让平" and hl._jc_actual(0) == "让负"
    assert hl._jc_actual(-2) == "让负"
    assert hl._cover(3, 2.0) == "cover" and hl._cover(2, 2.0) == "push" and hl._cover(1, 2.0) == "lose"
    assert hl._cover(1, 0.5) == "cover"           # 让半球无走水
    p, lo, hi = hl._wilson(5, 10)
    assert abs(p - 0.5) < 1e-9 and lo < p < hi and 0 <= lo and hi <= 1
    assert hl._wilson(0, 0) == (0.0, 0.0, 0.0)    # 空样本不崩
    # 竞彩三向概率从净胜球分布卷出且归一
    mp = {-1: 0.2, 0: 0.3, 1: 0.3, 2: 0.2}
    jp = hl._jc_probs(mp, True)
    assert abs(sum(jp.values()) - 1.0) < 1e-9
    assert abs(jp["让胜"] - 0.2) < 1e-9 and abs(jp["让平"] - 0.3) < 1e-9 and abs(jp["让负"] - 0.5) < 1e-9


def test_handicap_ledger_build_shape():
    """擂台 build 在真实账本上返回合法结构：命中≤场次、概率归一、校准字段成对。"""
    import app, handicap_ledger as hl
    sim, df = app._sim(), app.DF
    b = hl.build(sim, df)
    assert b["n"] == len(b["rows"]) and b["n"] >= 0
    jc = b["jc"]
    assert 0 <= jc["hits"] <= b["n"]
    assert 0.0 <= jc["rate"] <= 1.0 and jc["ci"][0] <= jc["rate"] <= jc["ci"][1] + 1e-9
    assert jc["baseline_pick"] in ("让胜", "让平", "让负")
    a = b["asian"]
    if a["decided"]:
        assert 0.0 <= a["real_cover_rate"] <= 1.0 and 0.0 <= a["pred_cover_rate"] <= 1.0
        assert abs(a["calib_gap"] - (a["real_cover_rate"] - a["pred_cover_rate"])) < 1e-3
    for r in b["rows"]:
        assert r["jc_pick"] in ("让胜", "让平", "让负")
        assert r["cover_result"] in ("cover", "push", "lose")


def test_api_handicap_ledger_ok(client):
    d = client.get("/api/handicap_ledger").get_json()
    assert "jc" in d and "asian" in d and "rows" in d
    assert d["jc"]["hits"] <= d["n"]


# ---------- 让球：市场对标 + 分桶（2026-06-25 三连） ----------
def test_market_compare_divergence_and_disagree(model):
    """模型公平盘 vs 市场 spread 背离：同强队算背离/倾向；强弱判断不一致则不强比。"""
    import manager, numpy as np
    _, _, _, _, M = model.score_matrix("Brazil", "Haiti", neutral=True)
    mp = manager._margin_pmf(M)
    hc = manager.handicap_conclusion(mp, True, "Brazil", "Haiti")
    # 市场让得更少 → 模型更看好强队（divergence>0）
    mkt = {"fav_line": hc["fair_line"] - 0.5, "fav_is_home": True, "provider": "DraftKings",
           "ou": 2.5, "fav_spread_odds": 1.9, "dog_spread_odds": 1.9}
    cmp = manager._market_compare(hc, {"market_handicap": mkt}, "Brazil", "Haiti", True)
    assert cmp["agree_fav"] and cmp["divergence"] > 0 and "更看好强队" in cmp["lean"]
    # 市场强队是客队（与模型主队不一致）→ 不强行比较盘口
    mkt2 = dict(mkt, fav_is_home=False)
    cmp2 = manager._market_compare(hc, {"market_handicap": mkt2}, "Brazil", "Haiti", True)
    assert cmp2["agree_fav"] is False and "divergence" not in cmp2
    # 无市场 → None
    assert manager._market_compare(hc, {}, "Brazil", "Haiti", True) is None


def test_handicap_summary_carries_market(model):
    """handicap_summary 传入 market 时附带对标块；不传则 market=None。"""
    import manager, numpy as np
    _, _, _, _, M = model.score_matrix("Argentina", "Jordan", neutral=True)
    ph = float(np.tril(M, -1).sum()); pa = float(np.triu(M, 1).sum())
    s0 = manager.handicap_summary(M, ph, pa, "阿根廷", "约旦")
    assert s0["market"] is None and s0["fav"] == "阿根廷"
    mkt = {"fav_line": 1.5, "fav_is_home": True, "provider": "DraftKings", "ou": 2.5,
           "fav_spread_odds": 1.85, "dog_spread_odds": 1.95}
    s1 = manager.handicap_summary(M, ph, pa, "阿根廷", "约旦", market=mkt)
    assert s1["market"] and s1["market"]["market_line"] == 1.5 and "divergence" in s1["market"]


def test_handicap_ledger_buckets():
    """擂台分桶结构合法：每桶命中≤场次、率∈[0,1]、CI 包住率、阶段键合法。"""
    import app, handicap_ledger as hl
    b = hl.build(app._sim(), app.DF)
    assert "buckets" in b and "strength" in b["buckets"]
    seen = 0
    for dim, rows in b["buckets"].items():
        for r in rows:
            seen += r["n"]
            assert 0 <= r["hits"] <= r["n"] and 0.0 <= r["rate"] <= 1.0
            assert r["ci"][0] <= r["rate"] <= r["ci"][1] + 1e-9
        if dim == "stage":
            assert all(x["key"] in ("小组赛", "淘汰赛") for x in rows)
    assert seen >= b["n"]      # 每场至少进 stage+strength 两个维度


# ---------- 让球：模型 vs 市场闭盘线（2026-06-25 续二） ----------
def test_hc_key_order_invariant():
    import espn_odds
    assert espn_odds._hc_key("Brazil", "Haiti") == espn_odds._hc_key("Haiti", "Brazil")


def test_vs_market_out_logic():
    """_vs_market_out：MAE 均值、背离下注胜率、谁更接近 的派生正确。"""
    import handicap_ledger as hl
    vm = {"n": 4, "edge_w": 3, "edge_l": 1, "edge_push": 0, "agree": 0,
          "mae_model": 4.0, "mae_market": 6.0, "closer_model": 3, "closer_market": 1, "tie": 0,
          "mae_model_em": 4.0, "em_closer": 3, "em_worse": 1,
          "clv_n": 0, "clv_sum": 0.0, "clv_pos": 0}
    o = hl._vs_market_out(vm)
    assert o["n"] == 4 and o["mae_model"] == 1.0 and o["mae_market"] == 1.5
    assert o["model_closer"] is True               # 模型 MAE 更小 + 更近场数更多
    assert o["edge_decided"] == 4 and o["edge_wins"] == 3 and o["edge_rate"] == 0.75
    assert o["beats_market"] is True
    assert hl._vs_market_out({"n": 0})["n"] == 0   # 空样本不崩


def test_handicap_ledger_vs_market_integration():
    """build 接 market_lines：构造合成市场线覆盖一场已完赛，vs_market 至少计入 1 场；
    空 market_lines 则 vs_market.n=0。纯本地、不联网。"""
    import app, handicap_ledger as hl, espn_odds
    sim, df = app._sim(), app.DF
    base = hl.build(sim, df, market_lines={})
    assert base["vs_market"]["n"] == 0
    if not base["rows"]:
        return
    r = base["rows"][0]                            # fav/dog 在 build 内是英文 canon
    # 构造一条与该场强弱一致的市场线（让得比模型少 1 球，制造可下注分歧）
    key = espn_odds._hc_key(r["fav"], r["dog"])
    mkt = {key: {"fav_line": max(0.5, r["fair_line"] - 1.0),
                 "fav_is_home": r["fav_is_home"], "ou": 2.5}}
    b = hl.build(sim, df, market_lines=mkt)
    assert b["vs_market"]["n"] >= 1
    vm = b["vs_market"]
    assert vm["mae_model"] is not None and vm["closer_model"] + vm["closer_market"] + vm["tie"] == vm["n"]


# ---------- 让球：期望净胜 MAE + CLV（2026-06-25 续三） ----------
def test_vs_market_out_em_and_clv():
    """_vs_market_out 含期望净胜 MAE 与 CLV 派生字段。"""
    import handicap_ledger as hl
    vm = {"n": 2, "edge_w": 1, "edge_l": 0, "edge_push": 0, "agree": 1,
          "mae_model": 3.0, "mae_market": 2.0, "closer_model": 0, "closer_market": 2, "tie": 0,
          "mae_model_em": 2.5, "em_closer": 1, "em_worse": 1,
          "clv_n": 2, "clv_sum": 0.5, "clv_pos": 2}
    o = hl._vs_market_out(vm)
    assert o["mae_model_em"] == 1.25 and o["em_beats_market"] is False
    assert o["clv"]["n"] == 2 and o["clv"]["avg"] == 0.25 and o["clv"]["pos_rate"] == 1.0


def test_handicap_ledger_clv_from_timeline():
    """build 接 timeline：开盘线在模型背离方、闭盘朝模型移动 → 正 CLV 计入。纯本地、不联网。"""
    import app, handicap_ledger as hl, espn_odds
    sim, df = app._sim(), app.DF
    base = hl.build(sim, df, market_lines={}, timeline={})
    assert base["vs_market"]["clv"]["n"] == 0          # 无 timeline → 无 CLV
    # 挑一场公平盘≥1.5 的（确保 open=fair−1 严格小于 fair，position≠0）
    r = next((x for x in base["rows"] if x["fair_line"] >= 1.5), None)
    if r is None:
        return
    key = espn_odds._hc_key(r["fav"], r["dog"])
    mkt = {key: {"fav_line": r["fair_line"], "fav_is_home": r["fav_is_home"], "ou": 2.5}}
    # 开盘线比模型公平盘低 1 球（模型更看好强队=position +1），闭盘升 0.5（朝模型移动→正 CLV）
    open_line = r["fair_line"] - 1.0
    tl = {key: {"fav_is_home": r["fav_is_home"], "open_line": open_line,
                "close_line": open_line + 0.5, "open_at": "x", "close_at": "y"}}
    b = hl.build(sim, df, market_lines=mkt, timeline=tl)
    clv = b["vs_market"]["clv"]
    assert clv["n"] >= 1 and clv["avg"] > 0 and clv["pos_rate"] > 0


# ---------- ESPN 让球盘解析器（2026-06-25 续四，mock 不联网）----------
def _fake_event(home="Morocco", away="Haiti", eid="1"):
    return {"id": eid, "date": "2026-06-25T18:00Z",
            "competitions": [{"competitors": [
                {"homeAway": "home", "team": {"displayName": home}},
                {"homeAway": "away", "team": {"displayName": away}}]}]}


def test_handicap_summary_parser_home_fav(monkeypatch):
    """主队是强队：spread=-1.5 → fav_line=1.5、fav_is_home=True、水位/OU 正确解析。"""
    import espn_odds as eo
    monkeypatch.setattr(eo, "_get", lambda url: {"pickcenter": [
        {"provider": {"name": "DraftKings"}, "spread": -1.5, "overUnder": 2.5,
         "homeTeamOdds": {"favorite": True, "spreadOdds": -115},
         "awayTeamOdds": {"favorite": False, "spreadOdds": -105}}]})
    r = eo._handicap_from_summary(_fake_event("Morocco", "Haiti"))
    assert r["fav_line"] == 1.5 and r["fav_is_home"] is True
    assert r["home"] == "Morocco" and r["away"] == "Haiti" and r["ou"] == 2.5
    assert r["fav_spread_odds"] == eo.am2dec(-115) and r["provider"] == "DraftKings"


def test_handicap_summary_parser_away_fav(monkeypatch):
    """客队是强队：spread=+1.5（主队受让）、favorite=False → fav_line=1.5、fav_is_home=False。"""
    import espn_odds as eo
    monkeypatch.setattr(eo, "_get", lambda url: {"pickcenter": [
        {"provider": {"name": "DraftKings"}, "spread": 1.5, "overUnder": 2.5,
         "homeTeamOdds": {"favorite": False, "spreadOdds": 120},
         "awayTeamOdds": {"favorite": True, "spreadOdds": -140}}]})
    r = eo._handicap_from_summary(_fake_event("Scotland", "Brazil"))
    assert r["fav_line"] == 1.5 and r["fav_is_home"] is False
    assert r["fav_spread_odds"] == eo.am2dec(-140)        # 强队=客队的水位


def test_handicap_summary_parser_no_spread(monkeypatch):
    """无 spread 字段 → None（不伪造盘口）。"""
    import espn_odds as eo
    monkeypatch.setattr(eo, "_get", lambda url: {"pickcenter": [
        {"provider": {"name": "DraftKings"}, "homeTeamOdds": {}, "awayTeamOdds": {}}]})
    assert eo._handicap_from_summary(_fake_event()) is None
    monkeypatch.setattr(eo, "_get", lambda url: {"pickcenter": []})
    assert eo._handicap_from_summary(_fake_event()) is None


# ---------- 竞彩动态让球线（2026-06-25 续五）----------
def test_jc_handicap_line_param():
    """jc_handicap(line) 按任意整数线结算：让胜=净胜>line/让平=net==line/让负=net<line；默认1与旧口径等。"""
    import manager
    mp = {-1: 0.1, 0: 0.2, 1: 0.2, 2: 0.25, 3: 0.25}     # 强队=主
    j1 = manager.jc_handicap(mp, True, 1)                  # 让1：net>1=P(2)+P(3)=0.5, ==1=0.2, <1=P(0)+P(-1)=0.3
    assert abs(j1["win"] - 0.5) < 1e-9 and abs(j1["draw"] - 0.2) < 1e-9 and abs(j1["lose"] - 0.3) < 1e-9
    j2 = manager.jc_handicap(mp, True, 2)                  # 让2：净胜>2=P(3)=0.25, ==2=0.25, <2=0.5
    assert abs(j2["win"] - 0.25) < 1e-9 and abs(j2["draw"] - 0.25) < 1e-9 and abs(j2["lose"] - 0.5) < 1e-9
    j0 = manager.jc_handicap(mp, True, 0)                  # 平手=常规：胜=P(>0)=0.7, 平=0.2, 负=0.1
    assert abs(j0["win"] - 0.7) < 1e-9 and abs(j0["lose"] - 0.1) < 1e-9


def test_csl_dynamic_line_strong_vs_even(model):
    """csl_handicap 动态定线：强打弱(摩洛哥vs海地)→让≥2、势均力敌(德国vs厄瓜多尔)→平手(0)。
    且让球线下 让胜/让平/让负 归一、与本场期望净胜自洽（line=round(exp)）。"""
    import manager, numpy as np
    def csl(h, a):
        _, _, _, _, M = model.score_matrix(h, a, neutral=True)
        mp = manager._margin_pmf(M)
        ph = float(np.tril(M, -1).sum()); pa = float(np.triu(M, 1).sum())
        return manager.csl_handicap(mp, ph >= pa)
    mor = csl("Morocco", "Haiti")
    assert mor["line"] >= 2 and mor["is_handicap"] and mor["home_line"] == -mor["line"]  # 摩主让N→主队口径负
    assert abs(mor["win"] + mor["draw"] + mor["lose"] - 1.0) < 1e-6
    assert mor["line"] == int(round(mor["exp_margin"]))    # 线=round(期望净胜)
    ge = csl("Germany", "Ecuador")
    assert ge["line"] == 0 and ge["is_handicap"] is False and ge["home_line"] == 0   # 势均力敌→平手


# ---------- 比赛解读文案层（2026-06-25 续六，文案/QA）----------
def test_narrative_compliance_no_banned_words(model):
    """QA 合规铁测：遍历多类对阵（强打弱/均势/弱打强/host）生成解读，断言**永不**含违规词，
    且每条都带『非投注建议』尾注。这是把守『严禁涉赌』红线的自动化护栏。"""
    import narrative, manager, teams_zh
    import numpy as np
    pairs = [("Brazil", "Haiti"), ("Germany", "Ecuador"), ("Argentina", "France"),
             ("Haiti", "Brazil"), ("Norway", "France"), ("Mexico", "Canada"),
             ("Saudi Arabia", "Spain"), ("Morocco", "Haiti")]
    for h, a in pairs:
        r = model.predict(h, a, neutral=True)
        _, _, _, _, M2 = model.score_matrix(h, a, neutral=True)
        mp = manager._margin_pmf(M2)
        csl = manager.csl_handicap(mp, r["p_home"] >= r["p_away"])
        hc = {"csl_is_handicap": csl["is_handicap"], "csl_line": csl["line"], "jc_verdict": csl["verdict"]}
        M = r["matrix"]
        tot = float(sum((i + j) * M[i, j] for i in range(M.shape[0]) for j in range(M.shape[1])))
        s = narrative.match_narrative(teams_zh.disp(h), teams_zh.disp(a),
                                      r["p_home"], r["p_draw"], r["p_away"], hc, tot)
        for w in narrative._BANNED:
            assert w not in s, f"{h} vs {a} 解读含违规词 {w}：{s}"
        assert "非投注建议" in s and "理性观赛" in s          # 合规尾注必带


def test_narrative_compact_mode(model):
    """看板逐行解读用 compact 模式：仍**永不**含违规词，但省去每行重复的尾注
    （免责由解读区统一展示一次）。守住红线 + 不冗余。"""
    import narrative, manager, teams_zh
    for h, a in [("Brazil", "Haiti"), ("Germany", "Ecuador"), ("Argentina", "France")]:
        r = model.predict(h, a, neutral=True)
        _, _, _, _, M2 = model.score_matrix(h, a, neutral=True)
        csl = manager.csl_handicap(manager._margin_pmf(M2), r["p_home"] >= r["p_away"])
        hc = {"csl_is_handicap": csl["is_handicap"], "csl_line": csl["line"], "jc_verdict": csl["verdict"]}
        M = r["matrix"]
        tot = float(sum((i + j) * M[i, j] for i in range(M.shape[0]) for j in range(M.shape[1])))
        full = narrative.match_narrative(teams_zh.disp(h), teams_zh.disp(a),
                                         r["p_home"], r["p_draw"], r["p_away"], hc, tot)
        comp = narrative.match_narrative(teams_zh.disp(h), teams_zh.disp(a),
                                         r["p_home"], r["p_draw"], r["p_away"], hc, tot, compact=True)
        for w in narrative._BANNED:
            assert w not in comp, f"{h} vs {a} compact 解读含违规词 {w}：{comp}"
        assert narrative.TAIL not in comp           # compact 不带尾注（统一展示一次）
        assert narrative.TAIL in full               # 默认仍带尾注，旧调用方不受影响
        assert comp and full.startswith(comp)       # compact 是 full 去尾的前缀


def test_devig_methods_normalize_and_correct_bias():
    """de-vig 三法都归一到 1；shin/odds_ratio 相对 proportional 抬高热门概率
    （纠正 favorite–longshot 偏差）；clv.implied 走配置口径、签名不变。"""
    import numpy as np
    import devig, clv
    for o1, ox, o2 in [(1.50, 4.20, 7.00), (2.30, 3.40, 3.20), (1.20, 7.0, 15.0)]:
        pp = devig.proportional(o1, ox, o2)
        po = devig.odds_ratio(o1, ox, o2)
        ps = devig.shin(o1, ox, o2)
        for p in (pp, po, ps):
            assert abs(float(p.sum()) - 1.0) < 1e-6
        fav = int(np.argmin([o1, ox, o2]))            # 最低赔率=热门
        assert ps[fav] >= pp[fav] - 1e-9              # shin 不低于 proportional 的热门概率
        assert po[fav] >= pp[fav] - 1e-9
    p, margin = clv.implied(2.30, 3.40, 3.20)         # 统一入口签名不变
    assert abs(float(np.sum(p)) - 1.0) < 1e-6 and margin > 0


def test_boot_ci_and_wilson():
    """bootstrap CI 与 Wilson CI 行为正确（市场研究层的统计基件）。"""
    import numpy as np
    import clv, market_research as mr
    lo, hi = clv.boot_ci(np.full(50, 0.2))        # 常数样本 → CI 收敛到该值
    assert abs(lo - 0.2) < 1e-6 and abs(hi - 0.2) < 1e-6
    lo, hi = clv.boot_ci([1.0, 2.0, 3.0, 4.0, 5.0])
    assert lo <= 3.0 <= hi and lo < hi
    assert clv.boot_ci([]) == (None, None)
    wlo, whi = mr._wilson(13, 20)                  # 65%，CI 含点估、在 [0,1]
    assert 0 <= wlo < 0.65 < whi <= 1
    assert mr._wilson(0, 0) == (None, None)


def test_market_research_line_movement():
    """线移动信息检验：真实开/闭盘样本能跑出结构正确的报告（CI 为二元区间、比率合法）。"""
    import market_research as mr
    r = mr.build()
    lm = r["line_movement"]
    assert lm["n"] > 0
    for k in ("rps_diff_ci", "logloss_diff_ci", "move_toward_actual_ci", "right_dir_ci"):
        assert isinstance(lm[k], list) and len(lm[k]) == 2 and lm[k][0] <= lm[k][1]
    assert 0.0 <= lm["right_dir_rate"] <= 1.0
    assert isinstance(lm["closing_sharper"], bool) and isinstance(lm["movement_informative"], bool)
    # 分桶：强弱档 3 桶 + 移动幅度 2 桶 + 阶段 2 桶，各自子桶样本数之和 = 总数（不重不漏）
    seg = r["segments"]
    assert len(seg["by_strength"]) == 3 and len(seg["by_move"]) == 2 and len(seg["by_stage"]) == 2
    assert sum(s["n"] for s in seg["by_strength"]) == lm["n"]
    assert sum(s["n"] for s in seg["by_move"]) == lm["n"]
    assert sum(s["n"] for s in seg["by_stage"]) == lm["n"]   # 小组赛+淘汰赛=全部
    # 校准 Brier 分解：reliability/resolution/uncertainty 均非负，且 ≈ Brier 恒等
    dc = r["calibration"]["decomp"]
    for k in ("brier", "reliability", "resolution", "uncertainty"):
        assert dc[k] is not None and dc[k] >= -1e-9
    assert abs(dc["brier"] - (dc["reliability"] - dc["resolution"] + dc["uncertainty"])) < 0.01
    # 自动判语
    assert r["summary"]["text"] and isinstance(r["summary"]["flags"], dict)
    # de-vig 敏感性：三口径都跑出同样本量的结论（口径不改样本，只改概率还原）
    sens = r["devig_sensitivity"]
    assert {a["method"] for a in sens} == {"proportional", "odds_ratio", "shin"}
    assert all(a["n"] == lm["n"] for a in sens)
    # 校准：ECE 合法、分箱样本数之和=预测点数(3×闭盘场次)、三口径都给出 ECE
    cal = r["calibration"]
    assert 0.0 <= cal["ece"] <= 1.0 and cal["n_points"] > 0
    assert sum(b.get("n", 0) for b in cal["bins"]) == cal["n_points"]
    assert set(cal["ece_by_method"]) == {"proportional", "odds_ratio", "shin"}
    for b in cal["bins"]:                              # 每个非空箱 实际频率 CI 合法
        if b.get("n"):
            assert b["obs_ci"][0] <= b["obs"] <= b["obs_ci"][1] + 1e-9


def test_narrative_clean_guard_raises():
    """守卫函数 _clean 对含违规词的串必抛（防未来改文案漏词）。"""
    import narrative
    import pytest
    with pytest.raises(ValueError):
        narrative._clean("本场稳赚不赔")
    assert narrative._clean("非投注建议，理性观赛") == "非投注建议，理性观赛"   # 合规串放行


def test_narrative_nick_and_frame(model):
    """解读内容自洽：强队带昵称、势均力敌走『平手/均势』叙事。"""
    import narrative, teams_zh
    s = narrative.match_narrative(teams_zh.disp("Brazil"), teams_zh.disp("Haiti"),
                                  0.80, 0.13, 0.07,
                                  {"csl_is_handicap": True, "csl_line": 2, "jc_verdict": "让负"}, 2.6)
    assert "桑巴军团" in s and "让 2 球" in s
    s2 = narrative.match_narrative(teams_zh.disp("Argentina"), teams_zh.disp("France"),
                                   0.36, 0.30, 0.34,
                                   {"csl_is_handicap": False, "csl_line": 0, "jc_verdict": "让胜"}, 1.9)
    assert "平手" in s2 or "五五" in s2 or "难题" in s2


def test_api_predict_has_narrative(client):
    d = client.get("/api/predict?home=Brazil&away=Scotland&neutral=1").get_json()
    assert "narrative" in d and "非投注建议" in d["narrative"]


# ---------- 市场机制解释器（explainer，A/C 信息性层；红线 = 只描述不指导下注） ----------
def test_explainer_redline_guard_is_functional():
    """红线守卫拦的是『指导下注/弃注行为』这个功能，覆盖行动等价词全谱（非单关键词字面）。"""
    import explainer
    # 正例：纯描述性机制文本 + 真实渲染卡 → 必须放行
    ok_texts = [
        "市场 Shin 去水真实隐含主胜 55%，模型 41%，KL 0.04，最大分歧在主胜，更可能是模型误差",
        "抽水 3.6%，水位偏低；赛前线移动客胜 +2.5%",
        "非投注建议，不含买/跳指令；理性观赛、量力而行",
    ]
    for t in ok_texts:
        assert explainer._assert_clean(t) == t
    card = explainer.explain_match("A vs B", (0.41, 0.31, 0.28), (1.77, 4.20, 4.30),
                                   (1.80, 4.10, 4.20), (0.03, 0.07))
    explainer._assert_clean(explainer.render(card))      # 真实卡渲染必过红线
    # 反例：一批『指导下注行为』的变体（含评分→行动、信号灯、星级、价值标签）→ 必须全拦
    banned_variants = [
        "建议下注主胜", "这场值得下", "可以考虑跟一注", "强烈推荐主胜", "value bet 在客胜",
        "评分≥7分 → 买入主胜", "信号灯绿灯，上车", "给这场打 5 星级买入", "稳赚不赔",
        "该买主胜", "正EV，加仓", "性价比买客胜", "跳过此盘", "建议买大球",
    ]
    for t in banned_variants:
        try:
            explainer._assert_clean(t)
            assert False, f"红线守卫漏拦行动文本：{t}"
        except ValueError:
            pass


def test_explainer_orientation_regression():
    """定向回归：odds 行队序与查询相反时，主/客赔率必须交换（平不变），防 C 段方向错乱复发。"""
    import explainer
    # 行 = (Ecuador 主, Germany 客)，o1=4.30(Ecuador) ox=4.20 o2=1.77(Germany)
    # 查询 = (Germany 主, Ecuador 客) → 应得 (1.77, 4.20, 4.30)
    c1, cx, c2 = explainer.orient_odds("Ecuador", "Germany", "Germany", "Ecuador", 4.30, 4.20, 1.77)
    assert (c1, cx, c2) == (1.77, 4.20, 4.30)
    # 同序不交换
    s1, sx, s2 = explainer.orient_odds("Germany", "Ecuador", "Germany", "Ecuador", 1.77, 4.20, 4.30)
    assert (s1, sx, s2) == (1.77, 4.20, 4.30)


def test_explainer_divergence_attaches_clv_prior():
    """红线#3：任何模型 vs 市场分歧地图都必须挂『市场对、模型错』先验注脚。"""
    import explainer
    d = explainer.divergence_map((0.41, 0.31, 0.28), (0.55, 0.23, 0.22))
    assert "CLV" in d["prior_note"] and "模型误差" in d["prior_note"]
    assert d["largest"]["outcome"] == "主胜"        # |0.41-0.55| 最大


# ---------- 解释器 B/D 转正闸门（bt_explainer.b_gate；解锁 = n≥30 AND CI不跨0） ----------
def test_b_gate_and_logic_boundary():
    """闸门是 AND：n≥30 且 FLB CI 不跨 0 才解锁；任一不满足都【仍锁】（B/D 不渲染）。
    boot_ci 固定种子=可复现：同值数组 CI 退化在均值（不跨 0）；正负对半 CI 跨 0。"""
    import numpy as np
    import bt_explainer as bte
    assert bte.GATE_MIN_N == 30
    # ① n=30 且 CI 不跨 0 → 解锁
    d1 = bte.bucket_decision(np.full(30, 0.5))
    assert d1["n"] == 30 and d1["ci_excludes_0"] and d1["unlocked"]
    # ② n=30 但 CI 跨 0（正负对半，均值≈0）→ 仍锁
    d2 = bte.bucket_decision(np.array([0.5] * 15 + [-0.5] * 15))
    assert d2["n"] == 30 and not d2["ci_excludes_0"] and not d2["unlocked"]
    # ③ n<30 但 CI 不跨 0 → 仍锁（证明 n 这一边是必要条件）
    d3 = bte.bucket_decision(np.full(29, 0.5))
    assert d3["n"] == 29 and d3["ci_excludes_0"] and not d3["unlocked"]
    # ④ 空桶 → 锁
    d4 = bte.bucket_decision(np.array([]))
    assert d4["n"] == 0 and not d4["unlocked"]


def test_b_gate_structure_and_invariant():
    """b_gate 结构 + 不变量：任何被标 unlocked 的桶必同时满足 n≥30 与 CI 不跨 0
    （不断言当前是否解锁——那随赛事样本增长由数据决定，正是设计目的）。"""
    import bt_explainer as bte
    g = bte.b_gate()
    assert set(g) >= {"buckets", "any_unlocked", "unlocked_buckets", "n_points", "min_n"}
    for b in g["buckets"]:
        if b["unlocked"]:
            assert b["n"] >= bte.GATE_MIN_N and b["ci_excludes_0"]
    assert g["any_unlocked"] == (len(g["unlocked_buckets"]) > 0)
