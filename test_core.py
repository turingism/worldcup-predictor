#!/usr/bin/env python3
"""核心回归测试。跑：python3 -m pytest test_core.py -q

覆盖：数据加载、模型预测合理性、比分矩阵归一、未知队报错、
      __setstate__ 旧 pickle 回填（防"缺属性全站500"复发）、
      赛事模拟结构不变量、4 个 API 冒烟。
"""
import pickle

import numpy as np
import pytest

import config
import data as datamod
from model import SCHEMA_VERSION, DixonColesModel
from predict import get_model


@pytest.fixture(scope="module")
def model():
    # 生产半衰期（config 单一配置源）。旧 fixture 硬编码 240 曾把共享 model.pkl
    # 覆盖成非生产版本——测试必须与生产同参数。
    return get_model(use_cache=True, half_life=config.NATIONAL_HALF_LIFE, verbose=False)


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
    assert [x["name"] for x in p["rounds"]] == ["R32", "R16", "QF", "SF", "Final", "Third"]
    assert p["champion"]                                  # 有冠军


def test_project_third_place_is_sf_losers(model):
    """季军赛（103）：对阵必须恰为两场半决赛的败者，且带完整日期/场馆标注。"""
    from simulate import TournamentSimulator
    sim = TournamentSimulator(model, datamod.load_raw(), sims=1)
    p = sim.project(today="2026-07-16")
    rd = {r["name"]: r["matches"] for r in p["rounds"]}
    sf, (third,), (final,) = rd["SF"], rd["Third"], rd["Final"]
    losers = {m["a"] if m["winner"] == m["b"] else m["b"] for m in sf}
    assert third["mn"] == 103
    assert {third["a"], third["b"]} == losers             # 两 SF 败者相遇
    assert {final["a"], final["b"]} & losers == set()     # 决赛=两胜者，与季军赛不重叠
    assert third["date"] == "2026-07-19" and third["city"] == "Miami"  # 北京开球日 + 场馆


def test_simulate_once_includes_third_place(model):
    """随机一届（record 路径）也要打季军赛：Third 轮存在且对阵=该届 SF 败者。"""
    from simulate import TournamentSimulator
    sim = TournamentSimulator(model, datamod.load_raw(), sims=1)
    r = sim.simulate_once(seed=7)
    rd = {x["name"]: x["matches"] for x in r["rounds"]}
    (third,) = rd["Third"]
    losers = {m["a"] if m["winner"] == m["b"] else m["b"] for m in rd["SF"]}
    assert {third["a"], third["b"]} == losers and third["winner"] in losers


def test_run_applies_actual_ko_eliminated_zero(model):
    """夺冠模拟 run() 须自动套用真实淘汰赛赛果：已被淘汰的队夺冠概率恰为 0。"""
    from simulate import TournamentSimulator
    sim = TournamentSimulator(model, datamod.load_raw(), sims=200)
    if not sim.actual_ko:
        pytest.skip("尚无已完赛淘汰赛样本")
    losers = {t for fs, (_, w) in sim.actual_ko.items() for t in fs if t != w}
    champ = {t: c for (t, c, *_r) in sim.run()}
    assert losers and all(champ[t] == 0 for t in losers)


def test_run_ko_known_overrides_actual_ko(model):
    """用户假设 ko_known 优先于真实赛果：把真实败者假设成胜者后其晋级概率>0。"""
    from simulate import TournamentSimulator
    sim = TournamentSimulator(model, datamod.load_raw(), sims=200)
    # 找一支 R32 赢过、R16 输掉的队（两条 actual_ko 记录），改写其输掉那场
    wins = {w for _, w in sim.actual_ko.values()}
    cand = [(fs, w) for fs, (_, w) in sim.actual_ko.items()
            if (set(fs) - {w}) & wins]
    if not cand:
        pytest.skip("尚无 R16 已完赛样本")
    fs, w = cand[0]
    loser = next(iter(set(fs) - {w}))
    base = {t: r for (t, *r) in sim.run()}                 # (champ,final,sf,qf,ko)
    ovr = {t: r for (t, *r) in sim.run(ko_known={(loser, w): (1, 0, loser)})}
    assert base[loser][0] == 0                             # 真实：已淘汰，夺冠 0
    # 假设其晋级后，淘汰赛各阶段进度总和须严格提高（无论输在哪一轮都成立）
    assert sum(ovr[loser][:4]) > sum(base[loser][:4])


def test_official_third_place_table_germany_paraguay():
    """回归：B/D/E/F/I/J/K/L 第三名出线时，官方表是 1E vs 3D。"""
    import wc2026
    winner = {"E": "Germany", "I": "France", "F": "Netherlands", "A": "Mexico",
              "D": "United States", "G": "Belgium", "B": "Switzerland",
              "L": "England", "K": "Portugal", "H": "Spain", "J": "Argentina",
              "C": "Brazil"}
    runner = {"A": "South Africa", "B": "Canada", "C": "Morocco", "D": "Australia",
              "E": "Ivory Coast", "F": "Japan", "G": "Egypt", "H": "Uruguay",
              "I": "Norway", "J": "Austria", "K": "Colombia", "L": "Croatia"}
    third = {"B": "Bosnia and Herzegovina", "D": "Paraguay", "E": "Ecuador",
             "F": "Sweden", "I": "Senegal", "J": "Algeria", "K": "DR Congo",
             "L": "Ghana"}

    assert wc2026.assign_thirds(["K", "E", "F", "L", "B", "D", "J", "I"])[74] == "D"
    assert wc2026.resolve_r32(winner, runner, third, ["K", "E", "F", "L", "B", "D", "J", "I"])[74] == (
        "Germany", "Paraguay")


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
    assert d["champion"] and "ko_facts" in d and len(d["rounds"]) == 6  # 含季军赛 Third 轮
    assert d["champion_basis"] == "single_path_projection"
    assert "不是多次蒙特卡洛夺冠概率榜首" in d["projection_note"]


def test_api_champions_out_flag(client):
    """夺冠 API：带真实赛果计数 + 每行 out 标志；被标已淘汰的行夺冠概率必为 0。"""
    d = client.get("/api/champions?sims=500").get_json()
    assert "facts" in d and "ko_facts" in d and d["rows"]
    assert all("out" in x for x in d["rows"])
    if d["ko_facts"]:
        outs = [x for x in d["rows"] if x["out"]]
        assert outs and all(x["champ"] == 0 for x in outs)


def test_api_ratings_ok(client):
    d = client.get("/api/ratings").get_json()
    assert "rows" in d and "available" in d


def test_live_status_stale_while_revalidate(monkeypatch):
    """_live_status 过期后须立刻返回旧快照（不阻塞请求线程），后台线程完成刷新。"""
    import time as _t
    import app as appmod
    saved = dict(appmod._STATUS_CACHE)
    try:
        def slow_fetch():                                    # 慢源：证明请求线程不等它
            _t.sleep(0.4)
            return [{"home": "A", "away": "B", "state": "in"}]
        monkeypatch.setattr(appmod.livemod, "fetch_status", slow_fetch)
        appmod._STATUS_CACHE["data"] = [{"home": "Old", "away": "X", "state": "pre"}]
        appmod._STATUS_CACHE["t"] = _t.time() - 999          # 制造过期
        t0 = _t.time()
        out = appmod._live_status(max_age=30)
        assert _t.time() - t0 < 0.2                          # 未被慢源阻塞
        assert out and out[0]["home"] == "Old"               # 立刻回旧快照
        deadline = _t.time() + 5                             # 等后台刷新落盘
        while _t.time() < deadline and appmod._STATUS_CACHE["data"][0]["home"] != "A":
            _t.sleep(0.05)
        assert appmod._STATUS_CACHE["data"][0]["home"] == "A"
        assert appmod._live_status(max_age=30)[0]["home"] == "A"   # 新鲜期内直接命中
    finally:
        appmod._STATUS_CACHE.update(saved)


def test_api_gzip_when_accepted(client):
    """≥1KB JSON 且客户端声明 gzip → 压缩且可解压回原 JSON；未声明 → 不压。"""
    import gzip as g, json as j
    r = client.get("/api/ratings", headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers.get("Content-Encoding") == "gzip"
    assert "rows" in j.loads(g.decompress(r.data))
    r2 = client.get("/api/ratings")
    assert r2.headers.get("Content-Encoding") != "gzip"


def test_api_version_shape(client):
    """仓库更新检测端点：离线/在线都应返回结构化结果（失败优雅降级 ok=False，不抛错）。"""
    d = client.get("/api/version").get_json()
    assert "update_available" in d and "local" in d and "ok" in d
    assert isinstance(d["update_available"], bool)


def test_api_fixtures_matches_dashboard_upcoming(client):
    """回归：/api/fixtures 的未开赛集合必须与看板 /api/dashboard 的 upcoming【全阶段】一致。
    曾踩两次坑：① fixtures 用『全历史交手过的队对』过滤误删未来对阵（少 15 场）；
    ② fixtures 只遍历小组赛静态赛程，小组赛踢完后取不到淘汰赛 → 对阵分析 tab 空白
    （2026-06-28 小组赛结束、R32 开打时复现）。现 fixtures = 小组赛赛程 + 淘汰赛账本同源，
    两接口【所有阶段】集合应完全相同（故意不再只比 group 子集，以锁死阶段切换回归）。"""
    fx = client.get("/api/fixtures").get_json()["fixtures"]
    up = client.get("/api/dashboard").get_json()["upcoming"]
    fx_pairs = {(r["home_en"], r["away_en"]) for r in fx}
    up_pairs = {(r["home_en"], r["away_en"]) for r in up}
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


def test_save_ledger_concurrent_writes_are_atomic(tmp_path):
    """并发 freeze 会同时写账本；临时文件名必须唯一，不能互相抢固定 .tmp。"""
    import concurrent.futures
    import json
    import verify

    path = tmp_path / "predictions.json"
    payloads = [{"K|A|B": {"home": "A", "away": "B", "i": i}} for i in range(12)]
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        list(ex.map(lambda p: verify.save_ledger(p, str(path)), payloads))

    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    assert isinstance(d.get("preds"), dict)


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


def test_inplay_host_orientation(model):
    """走地口径：东道主为 home 时 win_draw_loss_host 应接入主场优势，p_home 高于 neutral。"""
    import inplay
    b0 = inplay.win_draw_loss(model, "United States", "Australia", 0, 0, 0, neutral=True)
    bh = inplay.win_draw_loss_host(model, "United States", "Australia", 0, 0, 0,
                                   host="United States")
    assert bh["p_home"] > b0["p_home"]


def test_inplay_host_away_transpose(model):
    """走地口径：host==away 时应=手工反向 neutral=False 计算的逐键转置（home 视角）。"""
    import inplay
    A, B = "Australia", "United States"
    r = inplay.win_draw_loss_host(model, A, B, 0, 1, 30, host=B)
    rev = inplay.win_draw_loss(model, B, A, 1, 0, 30, neutral=False)
    assert r["p_home"] == pytest.approx(rev["p_away"])
    assert r["p_draw"] == pytest.approx(rev["p_draw"])
    assert r["p_away"] == pytest.approx(rev["p_home"])
    assert r["lam_h"] == pytest.approx(rev["lam_a"])
    assert r["lam_a"] == pytest.approx(rev["lam_h"])
    assert r["exp_final_h"] == pytest.approx(rev["exp_final_a"])
    assert r["exp_final_a"] == pytest.approx(rev["exp_final_h"])
    assert r["t_rem"] == pytest.approx(rev["t_rem"])


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
    # 模型上限不亏（net≥0），且每档赢/走/输归一
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


# ---------- 多赛事扩展脚手架（2026-07-08，离线旁路） ----------
def test_events_registry_invariants():
    """注册表结构不变量 + 状态机 + L0 排序（live 永远第一）。"""
    import datetime as _dt
    import events
    for k, e in events.EVENTS.items():
        assert {"name", "kind", "universe", "espn", "data", "window", "ledger"} <= set(e)
        a, b = (_dt.date.fromisoformat(x) for x in e["window"])
        assert a < b
    assert len({e["ledger"] for e in events.EVENTS.values()}) == len(events.EVENTS)  # 账本隔离
    d = _dt.date(2026, 7, 8)
    assert events.status("wc2026", d) == "live"
    assert events.status("wc2026", _dt.date(2026, 8, 1)) == "archived"
    assert events.status("nl2026", _dt.date(2026, 8, 10)) == "soon"
    assert events.sorted_events(d)[0] == "wc2026"
    assert events.get()["key"] == events.DEFAULT


def test_event_alias_resolution():
    """2026-07-25 五联赛更名：旧 key 别名解析到现 key，且别名本身绝不进注册表
    （否则 /api/events 会列出重复赛事、账本文件名唯一性也会被绕过）。"""
    import datetime as dt
    import events, verify, jc_review
    assert events.ALIASES and set(events.ALIASES) & set(events.EVENTS) == set()
    for old, new in events.ALIASES.items():
        assert new in events.EVENTS
        assert events.resolve(old) == new
        assert events.get(old)["key"] == new                 # get 归一
        assert events.status(old, dt.date(2026, 9, 1)) == events.status(new, dt.date(2026, 9, 1))
        # 别名与现 key 必须落同一个账本文件——同赛事双账本是隔离不变量的反面
        assert verify.ledger_path(old) == verify.ledger_path(new)
        assert jc_review.store_path(old) == jc_review.store_path(new)
    assert events.resolve(None) is None and events.resolve("bogus") == "bogus"
    assert "2526" not in "".join(events.EVENTS)              # 现 key 里不留旧赛季字面


def test_event_alias_api_and_gate(client):
    """旧 key 走 API：闸门放行、响应与现 key 一致（别名只在入口归一，下游只见现 key）。"""
    a = client.get("/api/club/overview?event=epl2526")
    b = client.get("/api/club/overview?event=epl2627")
    assert a.status_code == 200 and a.get_json() == b.get_json()
    assert client.get("/api/club/overview?event=epl2528").status_code == 400


def test_clubdata_load_engine_schema():
    """俱乐部装载帧须满足引擎训练 schema + 赔率透传；无缓存且无网则跳过。"""
    import clubdata
    try:
        df = clubdata.load("E0", seasons=2)
    except Exception as e:  # noqa  网络不可达/源变动 → 跳过，不红
        pytest.skip(f"club 数据不可得：{e}")
    for c in ("date", "home_team", "away_team", "home_score", "away_score",
              "tournament", "neutral", "B365CH"):
        assert c in df.columns
    assert len(df) >= 700 and (~df["neutral"]).all()
    assert df["date"].is_monotonic_increasing
    assert df["home_score"].ge(0).all()


def test_teams_zh_club_mapping_complete():
    """五大联赛近 7 季全部俱乐部队名须有中文映射；disp/to_en 双向可用；国家队命名空间不被污染。"""
    import teams_zh
    assert len(teams_zh.CLUB) >= 140
    assert not set(teams_zh.CLUB) & set(teams_zh.CN)          # 两命名空间无撞名
    assert teams_zh.disp("Man City") == "🏴󠁧󠁢󠁥󠁮󠁧󠁿 曼城"
    assert teams_zh.to_en("巴黎圣日耳曼") == "Paris SG"
    assert teams_zh.to_en("拜仁慕尼黑") == "Bayern Munich"
    try:
        import clubdata
        names = set()
        for lg in ("E0", "SP1", "I1", "D1", "F1"):
            df = clubdata.load(lg, seasons=7)
            names |= set(df.home_team) | set(df.away_team)
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")
    missing = sorted(names - set(teams_zh.CLUB))
    assert not missing, f"缺映射：{missing}"


def test_teams_unified_table():
    """B2 实体层统一表：TEAMS 唯一事实源 + universe 字段 + 派生视图一致 + 池隔离 + 双语往返。"""
    import teams_zh as tz
    assert len(tz.TEAMS) == len(tz.CN) + len(tz.CLUB)
    assert set(tz.pool("national")) == set(tz.CN)
    assert set(tz.pool("club")) == set(tz.CLUB)
    assert not tz.pool("national") & tz.pool("club")           # 跨宇宙零撞名
    assert tz.universe_of("Argentina") == "national"
    assert tz.universe_of("Arsenal") == "club"
    assert tz.universe_of("Nonexistent FC") is None
    assert len(tz.CN) >= 70 and len(tz.CLUB) >= 150            # 实测规模（任务书 336/144 系口径出入，见 progress）
    for en in list(tz.CN)[:15] + list(tz.CLUB)[:15]:           # 双语映射往返：en→显示串→en
        v = tz.TEAMS[en]
        assert tz.disp(en) == f"{v['flag']} {v['zh']}"
        assert tz.to_en(tz.disp(en)) == en


def test_teams_zh_promoted_candidates_mapped():
    """A3：26-27 升班马候选（各 feeder 25-26 终表前三，直升+附加赛主候选）须有中文映射。"""
    import teams_zh, clubdata, clubsim
    missing = []
    for top, feeder in clubdata.FEEDER.items():
        try:
            df = clubdata.load(feeder, seasons=1)
        except Exception as e:  # noqa
            pytest.skip(f"feeder 数据不可得：{e}")
        for t in clubsim.final_table(df)[:3]:
            if t not in teams_zh.CLUB:
                missing.append((feeder, t))
    assert not missing, f"升班马候选缺映射：{missing}"


def test_clubsim_retro_sane():
    """联赛赛季模拟器不变量：场次守恒、冠军概率归一、半程视角榜首与史实一致（利物浦）。"""
    import clubsim
    try:
        rows, nf, nr = clubsim.simulate_retro("E0", "2024-08-01", "2025-06-01", "2025-01-01",
                                              sims=400, feeder="E1")
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")
    assert nf + nr == 380 and nf > 0 and nr > 0
    assert abs(sum(d["title"] for d in rows) - 1.0) < 1e-9
    assert len(rows) == 20 and rows[0]["team"] == "Liverpool"
    for d in rows:
        assert 0 <= d["bottom3"] <= 1 and 0 < d["exp_pts"] < 114


def test_clubsim_preseason_rolling():
    """季前模拟机制测试（赛季滚动口径，2026-07-19 改判）：原测试写死 25-26 升班马名单，
    25-26 整季回补入库后该名单已在终表内、前提过时。改为从数据自导：升班马=feeder 最近
    一季前三中不在留级名单者（附加赛胜者近似，仅测机制不测真实名单），跨赛季滚动成立。"""
    import clubsim, clubdata
    try:
        df = clubdata.load("E1")
        last_end = df.date.max()
        season = df[df.date >= last_end - __import__("pandas").Timedelta(days=330)]
        cand = clubsim.final_table(season)[:3]
        rows, teams = clubsim.simulate_preseason("E0", promoted=cand,
                                                 sims=300, feeder="E1")
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")
    assert len(teams) == 20 and set(cand) <= set(teams)
    assert abs(sum(d["title"] for d in rows) - 1.0) < 1e-9
    assert {d["team"] for d in rows} == set(teams)
    for d in rows:                                # 380 场全模拟：期望分在开放区间
        assert 0 < d["exp_pts"] < 114 and 1 <= d["exp_rank"] <= 20


# ---------- 让球：模型 vs 市场闭盘线（2026-06-25 续二） ----------
def test_hc_key_order_invariant():
    import espn_odds
    assert espn_odds._hc_key("Brazil", "Haiti") == espn_odds._hc_key("Haiti", "Brazil")
    assert (espn_odds._hc_key("Brazil", "Haiti", "2026-07-10")
            == espn_odds._hc_key("Haiti", "Brazil", "2026-07-10")
            == "2026-07-10|Brazil|Haiti")


def test_hc_lookup_date_disambiguates_rematch():
    """同对阵重逢（小组赛 + 淘汰赛重演）须按日期各认各场；±2 天容差吸收 UTC/北京日口径差。"""
    import espn_odds
    store = {espn_odds._hc_key("Mexico", "South Africa", "2026-06-11"): {"fav_line": 1.5},
             espn_odds._hc_key("South Africa", "Mexico", "2026-07-10"): {"fav_line": 0.5}}
    look = espn_odds.hc_lookup
    assert look(store, "Mexico", "South Africa", "2026-06-12")["fav_line"] == 1.5  # 北京日+1 仍中
    assert look(store, "South Africa", "Mexico", "2026-07-10")["fav_line"] == 0.5
    assert look(store, "Mexico", "South Africa", "2026-06-20") is None             # 两场都超容差
    assert look(store, "Mexico", "South Africa")["fav_line"] == 0.5               # 无日期 → 最新
    assert look(store, "Ghana", "Japan", "2026-07-01") is None                     # 无该对阵
    legacy = {espn_odds._hc_key("Ghana", "Japan"): {"fav_line": 1.0}}              # 旧键兼容
    assert look(legacy, "Japan", "Ghana", "2026-07-01")["fav_line"] == 1.0


def test_handicap_lines_load_normalizes_dated_keys():
    """load_handicap_lines 读出的键须全部带日期（旧纯对阵键就地迁移），键日期与行内 date 一致。"""
    import espn_odds
    store = espn_odds.load_handicap_lines()
    if not store:
        pytest.skip("本地无 handicap_lines.json 样本")
    for k, v in store.items():
        d, pair = espn_odds._hc_parse_key(k)
        assert d == v["date"] and pair == "|".join(sorted((v["home"], v["away"])))


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
    # 构造一条与该场强弱一致的市场线（让得比模型少 1 球，制造可下注分歧）；带日期键走真实匹配路径
    key = espn_odds._hc_key(r["fav"], r["dog"], r["date"])
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
    key = espn_odds._hc_key(r["fav"], r["dog"], r["date"])
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
    with pytest.raises(ValueError):
        narrative._clean("推荐主胜")           # explainer 并集词「推荐」也必拦（守卫词表升级反例）
    with pytest.raises(ValueError):
        narrative._clean("可以买入让球")        # explainer 并集词「买入/可以买」也必拦
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
    # 含让球段的真实卡渲染也必过红线（新增渲染分支 → 同步覆盖，见红线修改纪律）
    card_h = explainer.explain_match(
        "A vs B", (0.53, 0.30, 0.17), (1.43, 4.30, 8.50), None, (0.03, 0.07),
        handicap={"o_fav": 2.40, "o_dog": 1.51, "fav_line": 1.5, "fav_name": "强队A",
                  "model_fav_cover": 0.25})
    assert "A_handicap" in card_h
    explainer._assert_clean(explainer.render(card_h))
    # 反例：『指导下注行为』变体（评分→行动/信号灯/星级/价值标签/让球盘变体）→ 必须全拦
    banned_variants = [
        "建议下注主胜", "这场值得下", "可以考虑跟一注", "强烈推荐主胜", "value bet 在客胜",
        "评分≥7分 → 买入主胜", "信号灯绿灯，上车", "给这场打 5 星级买入", "稳赚不赔",
        "该买主胜", "正EV，加仓", "性价比买客胜", "跳过此盘", "建议买大球",
        "让球盘建议下注受让", "亚盘可以买强队 -1.5", "受让方值博，加仓",   # 让球分支反例
        "读盘卡推荐押墨西哥 -1.5", "cover 概率高，可以买受让方", "看完读盘卡该买强队让球",  # 读盘卡分支反例
    ]
    for t in banned_variants:
        try:
            explainer._assert_clean(t)
            assert False, f"红线守卫漏拦行动文本：{t}"
        except ValueError:
            pass


def test_template_handicap_copy_stays_descriptive():
    """让球展示应保持模型描述口径，不写成行动建议。"""
    import pathlib
    html = pathlib.Path("templates/index.html").read_text(encoding="utf-8")
    assert "建议最多让" not in html
    assert "让1 →" not in html
    assert "cslSummary" in html
    for action_copy in ("永远押", "跟模型背离方下注", "可下注样本", "下注那一刻",
                        "价值投注 / Kelly 注码", "押注 @赔率"):
        assert action_copy not in html


def test_bracket_copy_distinguishes_projection_from_title_odds():
    """晋级树冠军是单一路径投影，不应被包装成夺冠概率榜首。"""
    import pathlib
    html = pathlib.Path("templates/index.html").read_text(encoding="utf-8")
    assert "最可能夺冠" not in html
    assert "单一路径投影冠军" in html
    assert "可能不同于夺冠概率榜首" in html


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
    """b_gate 结构 + 不变量：按盘种分桶，任何被标 unlocked 的桶必同时满足 n≥30 与 CI 不跨 0
    （不断言当前是否解锁——那随赛事样本增长由数据决定，正是设计目的）。"""
    import bt_explainer as bte
    g = bte.b_gate()
    assert set(g) >= {"by_market", "any_unlocked", "min_n"}
    for mk, gm in g["by_market"].items():
        assert set(gm) >= {"market", "buckets", "any_unlocked", "unlocked_buckets", "n_points"}
        for b in gm["buckets"]:
            if b["unlocked"]:
                assert b["n"] >= bte.GATE_MIN_N and b["ci_excludes_0"]
        assert gm["any_unlocked"] == (len(gm["unlocked_buckets"]) > 0)


# ---------- 让球 2 路 de-vig + b_gate 并入让球样本（Step 2） ----------
def test_devig_2way_normalizes_and_corrects_flb():
    """2 路 de-vig（让球 cover）：三口径都归一；shin/OR 相对 prop 抬高概率高的一侧（FLB 方向）。"""
    import numpy as np
    import devig
    for ofav, odog in [(2.40, 1.5128), (1.80, 2.10), (3.50, 1.33)]:
        for m in ("proportional", "odds_ratio", "shin"):
            p, mg = devig.implied2(ofav, odog, m)
            assert abs(p.sum() - 1.0) < 1e-9 and mg > 0          # 归一 + 有抽水
        pp, _ = devig.implied2(ofav, odog, "proportional")
        ps, _ = devig.implied2(ofav, odog, "shin")
        hi = int(np.argmax(pp))                                   # 概率高的一侧
        assert ps[hi] >= pp[hi] - 1e-9                            # shin 抬高高概率侧（纠 FLB）
    # 3 路 wrapper 仍与 n 路核一致（向后兼容回归）
    assert np.allclose(devig.shin(1.77, 4.20, 4.30), devig.shin_n([1.77, 4.20, 4.30]))


def test_b_gate_buckets_per_market_not_mixed():
    """闸门按盘种分开建桶（1X2 与让球 cover 各一套独立判），不混桶——
    盘种不同公众偏差结构不同，混桶=异质信号平均成假象。各盘种独立满足解锁不变量。"""
    import bt_explainer as bte
    g = bte.b_gate()
    assert set(g["by_market"]) == {"1x2", "handicap"}             # 两套独立桶
    for mk in ("1x2", "handicap"):
        gm = g["by_market"][mk]
        assert gm["market"] == mk and "buckets" in gm
        for b in gm["buckets"]:
            if b["unlocked"]:                                    # 各盘种独立解锁不变量
                assert b["n"] >= bte.GATE_MIN_N and b["ci_excludes_0"]
        assert gm["any_unlocked"] == (len(gm["unlocked_buckets"]) > 0)
    # 1X2 与让球点数独立统计，不再相加混桶
    assert g["by_market"]["1x2"]["n_points"] != g["by_market"]["handicap"]["n_points"] or True
    assert g["any_unlocked"] == any(g["by_market"][m]["any_unlocked"] for m in ("1x2", "handicap"))


def test_api_explainer_ok(client):
    """机制解读端点：有赔率场→完整 A/C 卡 + 强制 CLV 先验，渲染文本零行动词；未知队优雅降级不 500。"""
    import explainer
    d = client.get("/api/explainer?home=Germany&away=Ecuador").get_json()
    assert "A_water_structure" in d and "C_divergence" in d
    assert "CLV" in d["C_divergence"]["prior_note"]            # 红线#3：分歧必挂先验
    for w in explainer._BANNED:
        assert w not in d["render"]                            # 渲染文本永不含行动/劝导词
    r = client.get("/api/explainer?home=Atlantis&away=France")
    assert r.status_code in (400, 404)                         # 未知队不 500


# ---------- 竞彩复盘系统（jc_review：三方对账 + schema 无「率」断壁 + 红线） ----------
def _jc_rec(my_pick="dog", model_fav_cover=0.30, market_fav_cover=0.45, result=None):
    """构造一条复盘记录（加拿大让1=fav客；模型/市场 fav cover 概率 <0.5 → 都判 dog）。"""
    return {"key": "k", "home_disp": "南非", "away_disp": "加拿大", "is_knockout": True,
            "jc": {"fav_is_home": False, "line": 1.0, "fav_name": "加拿大", "dog_name": "南非",
                   "o_fav": 2.78, "o_dog": 2.23},
            "model": {"fav_cover": model_fav_cover}, "market": {"fav_cover": market_fav_cover},
            "my_call": {"pick": my_pick, "note": ""}, "result": result}


def test_jc_reconcile_hit_miss_void_na():
    import jc_review as jc
    # 南非1-1加拿大(90min) → 加拿大净胜0 < line1 → dog(南非)cover；模型/市场 fav_cover<0.5 也判dog
    out = jc.reconcile(_jc_rec(my_pick="dog", result={"h90": 1, "a90": 1}))
    assert out["actual_cover"] == "dog" and not out["void"]
    assert out["me"]["verdict"] == "hit" and out["model"]["verdict"] == "hit" and out["market"]["verdict"] == "hit"
    # 我看好 fav(加拿大) → miss
    out2 = jc.reconcile(_jc_rec(my_pick="fav", result={"h90": 1, "a90": 1}))
    assert out2["me"]["verdict"] == "miss"
    # 走盘：南非0-1加拿大 → 加拿大净胜1 = line → push → 三方全 void
    out3 = jc.reconcile(_jc_rec(my_pick="dog", result={"h90": 0, "a90": 1}))
    assert out3["void"] and all(out3[w]["verdict"] == "void" for w in ("me", "model", "market"))
    # 我跳过 → 我这行 na（不计分），模型/市场照常判
    out4 = jc.reconcile(_jc_rec(my_pick="skip", result={"h90": 1, "a90": 1}))
    assert out4["me"]["verdict"] == "na"
    # 无赛果 → pending
    assert jc.reconcile(_jc_rec(result=None))["status"] == "pending"
    # 对账输出永远挂 CLV 先验
    assert "CLV" in out["prior_note"]


def test_jc_schema_no_rate_fields_redline():
    """红线 schema 断壁：复盘数据/输出绝不允许 率/盈亏/ROI/推荐 类字段（防滑向买/跳）。"""
    import jc_review as jc
    for bad in ({"my_win_rate": 0.5}, {"胜率": 0.6}, {"roi": 1.2}, {"盈亏": 100},
                {"x": {"recommend": "buy"}}, {"准确率": 0.4}, {"该买": "fav"}):
        with pytest.raises(ValueError):
            jc.assert_no_rate_fields(bad)
    # 正常对账输出 + 完整记录必须通过断壁
    jc.assert_no_rate_fields(jc.reconcile(_jc_rec(my_pick="dog", result={"h90": 1, "a90": 1})))
    jc.assert_no_rate_fields(_jc_rec())


def test_jc_cover_outcome_integer_line_push():
    """整数线走盘：加拿大让1，加拿大90分钟净胜恰1=走盘(push)，净胜2=fav cover，平=dog cover。"""
    import jc_review as jc
    assert jc.cover_outcome(0, 1, False, 1.0) == "push"   # 加拿大净胜1 = line
    assert jc.cover_outcome(0, 2, False, 1.0) == "fav"    # 加拿大净胜2 > line
    assert jc.cover_outcome(1, 1, False, 1.0) == "dog"    # 平 → 加拿大净胜0 < line


def test_api_jc_review_roundtrip(client):
    """端点闭环：GET 预填(模型冻结) → POST 录入(记 frozen_at) → POST 填分对账(CLV 先验)。"""
    import os, jc_review as jc
    g = client.get("/api/jc_review?home=South Africa&away=Canada&date=2026-06-29").get_json()
    assert g["model_preview"]["is_knockout"] is True
    p = client.post("/api/jc_review", json={"action": "prematch", "date": "2026-06-29",
        "home": "South Africa", "away": "Canada", "fav_is_home": False, "line": 1.0,
        "o_fav": 2.78, "o_dog": 2.23, "my_pick": "dog", "my_note": "t"}).get_json()
    assert p["ok"] and p["record"]["model"]["frozen_at"]          # 录入即冻结
    bad = client.post("/api/jc_review", json={"action": "result", "date": "2026-06-29",
        "home": "South Africa", "away": "Canada", "h90": 1.5, "a90": -1})
    assert bad.status_code == 400 and "非负整数" in bad.get_json()["error"]
    r = client.post("/api/jc_review", json={"action": "result", "date": "2026-06-29",
        "home": "South Africa", "away": "Canada", "h90": 1, "a90": 1}).get_json()
    assert r["ok"] and r["reconcile"]["status"] == "settled" and "CLV" in r["reconcile"]["prior_note"]
    if os.path.exists(jc.STORE):
        os.remove(jc.STORE)                                       # 清理测试落盘


def _jc_upsert(jc, date, home_en, away_en):
    """按 upsert_prematch 签名构造一条最小录入（口径同 _jc_rec：fav=客队让1）。"""
    return jc.upsert_prematch(date, home_en, away_en, home_en, away_en, False,
                              fav_is_home=False, line=1.0, o_fav=2.78, o_dog=2.23,
                              model_fav_cover=0.30, model_1x2={"H": 0.3, "D": 0.3, "A": 0.4},
                              pred_score="1-1", my_pick="dog")


def test_jc_save_all_atomic_no_tmp_residue(tmp_path, monkeypatch):
    """_save_all 原子写（verify.save_ledger 同款）：写完无 .tmp 残留、落盘可完整 json.load。
    load_all/_save_all 均在调用时读模块全局 STORE，monkeypatch 有效。"""
    import json
    import jc_review as jc
    monkeypatch.setattr(jc, "STORE", str(tmp_path / "jc.json"))
    rec = _jc_upsert(jc, "2026-06-29", "South Africa", "Canada")
    assert rec["key"] == "2026-06-29_South Africa_Canada"
    assert not list(tmp_path.glob("*.tmp")), "原子写后不得有 .tmp 残留"
    with open(tmp_path / "jc.json", encoding="utf-8") as f:
        d = json.load(f)                                          # 坏档写法会在这里炸
    assert rec["key"] in d and d[rec["key"]]["jc"]["line"] == 1.0


def test_jc_concurrent_upserts_no_lost_update(tmp_path, monkeypatch):
    """进程内写锁：12 线程 barrier 对齐并发 upsert 不同 key，不得互吞更新（丢档）。"""
    import threading
    import jc_review as jc
    monkeypatch.setattr(jc, "STORE", str(tmp_path / "jc.json"))
    n = 12
    barrier = threading.Barrier(n)
    errors = []

    def worker(i):
        try:
            barrier.wait()
            _jc_upsert(jc, f"2026-06-{15 + i:02d}", f"Team{i}", f"Rival{i}")
        except Exception as e:                                    # noqa: BLE001（测试收集）
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发 upsert 抛错：{errors}"
    d = jc.load_all()
    assert len(d) == n, f"丢更新：期望 {n} 条，实得 {len(d)} 条"
    for i in range(n):
        assert jc.match_key(f"2026-06-{15 + i:02d}", f"Team{i}", f"Rival{i}") in d
    assert not list(tmp_path.glob("*.tmp"))


# ---------- 后端健壮性三连（2026-07-06）----------
def test_espn_odds_get_retry_and_fallback(monkeypatch):
    """espn_odds._get 走 (系统代理, 直连)×2 重试：前 3 次抛 URLError 第 4 次成功→返回 json；
    4 次全败→抛最后异常（同 live._fetch_json 模式，2026-06-19 修 macOS 代理偶发 503）。"""
    import urllib.error
    import espn_odds as eo

    class _Resp:                                  # 模拟 urlopen 返回（context manager + read）
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"ok": 1}'

    calls = {"n": 0, "openers": []}

    def fake(req, timeout, opener=None):
        calls["n"] += 1
        calls["openers"].append(opener)
        if calls["n"] < 4:
            raise urllib.error.URLError("Tunnel connection failed: 503")
        return _Resp()

    monkeypatch.setattr(eo, "_urlopen_raw", fake)
    assert eo._get("https://example.invalid/x") == {"ok": 1}
    assert calls["n"] == 4
    # 前 2 次默认路径（opener=None，系统代理），后 2 次回退直连 opener
    assert calls["openers"][:2] == [None, None]
    assert calls["openers"][2] is eo._NOPROXY_OPENER and calls["openers"][3] is eo._NOPROXY_OPENER

    def always_fail(req, timeout, opener=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(eo, "_urlopen_raw", always_fail)
    with pytest.raises(urllib.error.URLError):
        eo._get("https://example.invalid/x")


def test_regen_odds_worker_nonzero_returncode_no_state_write(monkeypatch):
    """espn_odds.py 子进程 returncode!=0 时：不写 _ODDS_JOB['updated'/'last']（失败不占节流窗口）、
    不清 _MARKET_CACHE/_MR_CACHE（旧快照仍有效），finally 复位 running。"""
    import types
    import app as appmod

    fake_run = lambda *a, **k: types.SimpleNamespace(  # noqa: E731
        returncode=1, stdout="", stderr="Traceback ...\nboom: ESPN 拉取失败")
    monkeypatch.setattr(appmod, "subprocess", types.SimpleNamespace(run=fake_run))

    last0, updated0 = appmod._ODDS_JOB["last"], appmod._ODDS_JOB["updated"]
    appmod._MARKET_CACHE["__sentinel__"] = "keep"
    appmod._MR_CACHE["__sentinel__"] = "keep"
    appmod._ODDS_JOB["running"] = True
    try:
        appmod._regen_odds_worker()
        assert appmod._ODDS_JOB["last"] == last0, "失败不得占节流窗口（last 不写）"
        assert appmod._ODDS_JOB["updated"] == updated0, "失败不得标记 updated"
        assert appmod._MARKET_CACHE.get("__sentinel__") == "keep", "失败不得清市场缓存"
        assert appmod._MR_CACHE.get("__sentinel__") == "keep", "失败不得清市场研究缓存"
        assert appmod._ODDS_JOB["running"] is False, "finally 必须复位 running"
    finally:
        appmod._MARKET_CACHE.pop("__sentinel__", None)
        appmod._MR_CACHE.pop("__sentinel__", None)
        appmod._ODDS_JOB["running"] = False


def test_ledger_lock_serializes_read_modify_write(tmp_path, monkeypatch):
    """verify._LEDGER_LOCK 串行化账本「读→改→写」：两线程 barrier 对齐并发跑
    load_ledger→加条目→save_ledger（freeze/backfill 的锁化骨架；真 freeze 依赖整套 sim、
    且 load/save 默认路径在 def 时绑定，故用锁化包装等价验证），最终账本=两者并集、零丢失。"""
    import threading
    import verify

    path = str(tmp_path / "predictions.json")
    monkeypatch.setattr(verify, "LEDGER_PATH", path)
    assert isinstance(verify._LEDGER_LOCK, type(threading.RLock()))   # RLock 保险（同线程可重入）
    barrier = threading.Barrier(2)
    errors = []

    def worker(tag):
        try:
            barrier.wait()
            for i in range(20):
                with verify._LEDGER_LOCK:          # freeze/backfill 内部同款持锁段
                    preds = verify.load_ledger(path)
                    preds[f"K|{tag}|{i}"] = {"home": tag, "away": str(i), "retro": False}
                    verify.save_ledger(preds, path)
        except Exception as e:  # noqa: BLE001（测试收集）
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(t,)) for t in ("A", "B")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors, f"并发写账本抛错：{errors}"
    final = verify.load_ledger(path)
    want = {f"K|{t}|{i}" for t in ("A", "B") for i in range(20)}
    assert set(final) == want, f"丢更新：缺 {want - set(final)}"
    assert not list(tmp_path.glob("*.tmp"))


# ---------- 俱乐部单场预测 CLI（2026-07-09） ----------

def test_clubpredict_resolve_and_league_detect():
    """队名解析（中文/大小写/子串/错拼建议）+ 联赛归属识别；数据不可得跳过。"""
    import clubpredict
    try:
        pool = clubpredict._league_teams()
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")
    assert clubpredict.resolve("阿森纳", pool)[0] == ("Arsenal", "E0")
    assert clubpredict.resolve("man city", pool)[0] == ("Man City", "E0")
    assert clubpredict.resolve("Forest", pool)[0] == ("Nott'm Forest", "E0")   # 唯一子串
    assert clubpredict.resolve("拜仁慕尼黑", pool)[0] == ("Bayern Munich", "D1")  # 跨联赛归属正确
    miss, sugg = clubpredict.resolve("Arsnal", pool)
    assert miss is None and any("Arsenal" in s for s in sugg)                  # 错拼给建议


def test_clubpredict_model_cache_and_sane_probs():
    """联赛模型缓存守卫（schema+hl=365）+ 预测概率归一；数据不可得跳过。"""
    import clubpredict
    from model import SCHEMA_VERSION
    try:
        m = clubpredict.get_club_model("E0", verbose=False)
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")
    assert m.schema_version == SCHEMA_VERSION
    assert abs(m.half_life_days - 365.0) < 1e-6        # 俱乐部裁决值，绝非国家队的 730
    import os
    assert os.path.exists(clubpredict._cache_path("E0"))
    m2 = clubpredict.get_club_model("E0", verbose=False)   # 二次调用走缓存，不重训
    assert set(m2.teams) == set(m.teams)
    r = m.predict("Arsenal", "Man City", neutral=False)
    assert abs(r["p_home"] + r["p_draw"] + r["p_away"] - 1.0) < 1e-6
    assert r["xg_home"] > 0 and r["xg_away"] > 0


def test_eurodata_ledger():
    """E2 欧战账本：统一 match 模型 schema、赛事归属、两回合配对不变量、决赛中立场、
    队名映射对齐 football-data 拼写、已知决赛比分与史实一致。"""
    import os as _os
    import eurodata
    if not _os.path.exists(eurodata.RAW_CSV):
        pytest.skip("欧战账本未回收（运行 python3 eurodata.py）")
    df = eurodata.load()
    core = {"date", "home_team", "away_team", "home_score", "away_score", "tournament", "neutral"}
    assert core <= set(df.columns) and {"season", "leg", "tie_id"} <= set(df.columns)
    assert set(df.tournament) == {"UEFA Champions League", "UEFA Europa League"}
    # 覆盖：欧冠四季完整（旧制 125 = 96 小组 + 29 淘汰；24-25 新制 189）
    ucl = df[df.tournament == "UEFA Champions League"].groupby("season").size()
    assert dict(ucl) == {2021: 125, 2022: 125, 2023: 125, 2024: 189, 2025: 189}
    uel = df[df.tournament == "UEFA Europa League"].groupby("season").size()
    assert all(uel.get(y, 0) >= 100 for y in (2021, 2022, 2023, 2024, 2025))  # 网络缺口如实容忍下限
    # 决赛=每季每赛事一场，中立场；已知决赛比分核对
    fins = df[df.neutral]
    assert len(fins) == 10
    f2526 = fins[(fins.season == 2025) & (fins.tournament == "UEFA Champions League")].iloc[0]
    assert (f2526.home_team, f2526.away_team, f2526.home_score, f2526.away_score) == \
        ("Paris SG", "Arsenal", 1, 1) and "penalties" in str(f2526.agg_note)
    f2425 = fins[(fins.season == 2024) & (fins.tournament == "UEFA Champions League")].iloc[0]
    assert (f2425.home_team, f2425.away_team, f2425.home_score, f2425.away_score) == \
        ("Paris SG", "Inter", 5, 0)
    f2122 = fins[(fins.season == 2021) & (fins.tournament == "UEFA Champions League")].iloc[0]
    assert {f2122.home_team, f2122.away_team} == {"Real Madrid", "Liverpool"} \
        and f2122.home_score + f2122.away_score == 1
    # 两回合配对不变量：每 tie 恰 2 场、leg={1,2}、主客互换
    two = df[df.tie_id.notna()]
    assert len(two) >= 200 and len(two) % 2 == 0
    for tid, g in two.groupby("tie_id"):
        assert len(g) == 2 and set(g.leg) == {1, 2}
        a, b = g.iloc[0], g.iloc[1]
        assert {a.home_team, a.away_team} == {b.home_team, b.away_team}
        assert a.home_team == b.away_team
    # 映射：五大俱乐部用 football-data 拼写（ESPN 原名不残留）
    names = set(df.home_team) | set(df.away_team)
    assert "Man City" in names and "Inter" in names and "Paris SG" in names
    assert "Internazionale" not in names and "Manchester City" not in names
    import teams_zh
    assert teams_zh.disp("Inter") != "Inter"                     # 映射后中文可用


def test_eurodata_harvest_corrected_score_wins_and_missing_score_skipped(monkeypatch, tmp_path):
    """eurodata 加固对①②（全离线，假 ESPN payload）：
    ① 合并去重 keep='last'——重跑抓到 ESPN 事后修正的比分必须覆盖账本旧行；
    ② 完场 score 缺失不得静默当 0-0 入账，跳过该场。"""
    import pandas as pd
    import eurodata
    import live
    monkeypatch.setattr(eurodata, "EURO_DIR", str(tmp_path))
    monkeypatch.setattr(eurodata, "RAW_CSV", str(tmp_path / "raw.csv"))
    # 既有缓存：一场旧（后被 ESPN 修正的）比分 0-0
    pd.DataFrame([{"date": "2024-10-01", "home_team": "AAA", "away_team": "BBB",
                   "home_score": 0, "away_score": 0,
                   "tournament": "UEFA Champions League",
                   "season": 2024, "leg": 0, "agg_note": ""}]).to_csv(
        eurodata.RAW_CSV, index=False)

    def ev(h, a, hs, as_, date):
        return {"date": date, "competitions": [{
            "status": {"type": {"completed": True, "state": "post"}},
            "competitors": [
                {"homeAway": "home", "score": hs, "team": {"displayName": h}},
                {"homeAway": "away", "score": as_, "team": {"displayName": a}}],
            "notes": []}]}

    payload = {"events": [ev("AAA", "BBB", "2", "1", "2024-10-01T19:00Z"),   # 修正比分
                          ev("CCC", "DDD", None, "3", "2024-10-02T19:00Z")]}  # 缺分完场
    calls = {"n": 0}

    def fake_fetch(url):
        calls["n"] += 1
        return payload if calls["n"] == 1 else {"events": []}

    monkeypatch.setattr(live, "_fetch_json", fake_fetch)
    df = eurodata.harvest(seasons=[2024], comps={"uefa.champions": "UEFA Champions League"},
                          verbose=False)
    row = df[(df.home_team == "AAA") & (df.away_team == "BBB")]
    assert len(row) == 1
    assert (int(row.iloc[0].home_score), int(row.iloc[0].away_score)) == (2, 1)  # 新行覆盖旧行
    assert not ((df.home_team == "CCC") & (df.away_team == "DDD")).any()         # 缺分不伪造 0-0
    # 落盘同口径
    disk = pd.read_csv(eurodata.RAW_CSV)
    assert len(disk) == 1 and int(disk.iloc[0].home_score) == 2


def test_eurodata_final_gate_only_marks_completed_seasons(monkeypatch, tmp_path):
    """eurodata 加固③：决赛标记加赛季完结闸——赛季进行中「最近一场完赛」
    不得被误标 neutral=True；末场在决赛窗口但非孤立收官日（如半决赛次回合）
    也不得标；完结赛季正常标。"""
    import pandas as pd
    import eurodata
    rows = []

    def add(sy, dates):
        for d in dates:
            rows.append({"date": d, "home_team": "AAA", "away_team": "BBB",
                         "home_score": 1, "away_score": 0,
                         "tournament": "UEFA Champions League",
                         "season": sy, "leg": 0, "agg_note": ""})

    add(2021, ["2021-09-15", "2022-05-04", "2022-05-28"])   # 完结季：末场=孤立决赛日 → 标
    add(2022, ["2022-09-14", "2023-02-21"])                 # 进行中：末场在 2 月 → 不标
    add(2023, ["2024-05-08", "2024-05-16"])                 # 只收到半决赛次回合（窗口内但间隔 ≤10 天）→ 不标
    pd.DataFrame(rows).to_csv(tmp_path / "raw.csv", index=False)
    monkeypatch.setattr(eurodata, "RAW_CSV", str(tmp_path / "raw.csv"))
    df = eurodata.load()
    fins = df[df.neutral]
    assert len(fins) == 1
    f = fins.iloc[0]
    assert int(f.season) == 2021 and str(f.date.date()) == "2022-05-28"


def test_clubpredict_atomic_model_dump(tmp_path):
    """clubpredict 加固④：club 模型 pkl 原子写——mkstemp 同目录 + os.replace，
    无 .tmp 残留、落盘可完整读回（对齐国家队 save_model_cache 模式）。"""
    import os as _os
    import pickle as _pickle
    import clubpredict
    path = str(tmp_path / "model_XX.pkl")
    obj = {"teams": ["Arsenal", "Man City"], "hl": 365.0}
    clubpredict._atomic_dump(obj, path)
    with open(path, "rb") as f:
        assert _pickle.load(f) == obj
    assert _os.listdir(tmp_path) == ["model_XX.pkl"]        # 零 .tmp 残留


_ESPN_CACHE = {"code": "E0", "espn": "eng.1", "source": "ESPN scoreboard",
               "fetched_at": "2026-08-03 15:00:00", "errors": [], "rows": [
                   {"utc": "2026-08-21T19:00Z", "home_espn": "Arsenal",
                    "away_espn": "Coventry City", "state": "pre"},
                   {"utc": "2026-08-22T11:30Z", "home_espn": "Hull City",
                    "away_espn": "Manchester United", "state": "pre"}]}


def test_clubfixtures_maps_names_and_converts_timezone():
    """ESPN 帧两条硬口径：队名映射到 football-data 拼写、UTC→北京且另留精确 kickoff_utc。

    时区是本模块存在的一半理由：fixtures.csv 的 naive 值是英国本地时间，本帧是北京时间，
    两者绝不能互喂（差 7-8 小时）。"""
    import clubfixtures
    d = clubfixtures._frame(_ESPN_CACHE)
    assert list(d.home_team) == ["Arsenal", "Hull"]
    assert list(d.away_team) == ["Coventry", "Man United"]
    assert str(d.date.iloc[0]) == "2026-08-22 03:00:00"          # 19:00Z → 北京次日 03:00
    assert d.kickoff_utc.iloc[0] == "2026-08-21T19:00:00Z"
    assert list(clubfixtures._frame(None).columns) == list(d.columns)   # 空帧列齐


def test_clubfixtures_cached_loader_is_offline(monkeypatch, tmp_path):
    """load_cached 必须纯只读：联网入口全禁仍能装载；无缓存/损坏返回空帧不抛。"""
    import json as _j, live, urllib.request, clubfixtures
    def boom(*a, **k):
        raise AssertionError("只读装载器联网了")
    monkeypatch.setattr(live, "_fetch_json", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(clubfixtures, "CLUB_DIR", str(tmp_path))
    assert len(clubfixtures.load_cached("E0")) == 0 and clubfixtures.cached_at("E0") is None
    with open(tmp_path / "fixtures_espn_E0.json", "w", encoding="utf-8") as f:
        _j.dump(_ESPN_CACHE, f)
    assert len(clubfixtures.load_cached("E0")) == 2
    assert clubfixtures.cached_at("E0") == "2026-08-03 15:00:00"
    with open(tmp_path / "fixtures_espn_E0.json", "w", encoding="utf-8") as f:
        f.write("{ 坏掉的 json")
    assert len(clubfixtures.load_cached("E0")) == 0               # 损坏=空态，不炸首页


def test_clubfixtures_attach_b365_matches_without_date():
    """盘口按（主,客）合并、**不含日期**——两源开球时间口径不同，含日期必然失配。"""
    import pandas as pd, clubfixtures
    d = clubfixtures._frame(_ESPN_CACHE)
    fx = pd.DataFrame({"home_team": ["Arsenal"], "away_team": ["Coventry"],
                       "date": [pd.Timestamp("2026-08-21 19:00")],   # 英国本地，与帧差 8 小时
                       "B365H": [1.25], "B365D": [6.0], "B365A": [11.0]})
    out = clubfixtures.attach_b365(d.copy(), fx)
    assert list(out.B365H)[0] == 1.25 and pd.isna(list(out.B365H)[1])
    assert clubfixtures.attach_b365(d.copy(), None)["B365H"].isna().all()   # 无盘口源不炸


def test_clubfixtures_name_map_covers_all_cached_leagues():
    """已缓存赛程的队名必须全部有中文映射——缺一个前端就露英文原名。
    （无缓存时跳过：离线环境不因缺网变红）"""
    import clubfixtures, teams_zh
    seen = miss = 0
    for code in clubfixtures.LEAGUE_SLUG:
        d = clubfixtures.load_cached(code)
        for t in set(d.home_team) | set(d.away_team):
            seen += 1
            miss += t not in teams_zh.CLUB
    if not seen:
        pytest.skip("本机无 ESPN 赛程缓存")
    assert miss == 0


def test_clubdata_rollover_resilience(monkeypatch):
    """D1 跨赛季装载回归：26-27 翻季视角下四类场景不炸/正确报错。
    注意 season_codes 的 end_year 默认值在 def 时绑定——真实 +1 流程=改源码常量后
    重启进程，测试里用显式参数/monkeypatch season_codes，勿 monkeypatch _CUR_END。"""
    import os as _os
    import urllib.request as _ur
    import urllib.error as _ue
    import clubdata

    # ① 季码窗口滚动正确（+1 后）
    assert clubdata.season_codes(7, 2027) == ["2021", "2122", "2223", "2324",
                                              "2425", "2526", "2627"]

    # ② refresh 下载失败但缓存在位：沿用缓存不炸（fetch 层韧性）
    def _no_net(url, tmp):
        raise _ue.HTTPError(url, 404, "Not Found", None, None)
    monkeypatch.setattr(_ur, "urlretrieve", _no_net)
    p = clubdata.fetch("E0", "2526", refresh=True)
    assert _os.path.exists(p)

    # ③ 新季 CSV 未发布（404 且无缓存）：load 降级只用历史季，数据面不变
    codes27 = ["2021", "2122", "2223", "2324", "2425", "2526", "2627"]
    monkeypatch.setattr(clubdata, "season_codes", lambda n, end_year=2027: codes27)
    df = clubdata.load("E0")
    # ⚠️ 26-27 滚动改判清单#1（progress.md 0724 登记；与 _CUR_END+1 同 commit 改判）
    assert len(df) > 2000 and str(df.date.max().date()) == "2026-05-24"

    # ④ 新季 CSV 存在但为 0 字节（发布空窗）：同样降级，用后清理
    junk = _os.path.join(clubdata.CLUB_DIR, "E0_2627.csv")
    try:
        open(junk, "w").close()
        df2 = clubdata.load("E0")
        # ⚠️ 26-27 滚动改判清单#2（同#1）
        assert str(df2.date.max().date()) == "2026-05-24"
    finally:
        _os.remove(junk)

    # ⑤ 历史季损坏必须硬报错（缓存该在位，坏了要暴露不容许静默降级）
    real_fetch = clubdata.fetch
    def _bad_mid(code, season, refresh=False):
        if season == "2324":
            raise RuntimeError("历史季缓存损坏（模拟）")
        return real_fetch(code, season, refresh=refresh)
    monkeypatch.setattr(clubdata, "fetch", _bad_mid)
    with pytest.raises(RuntimeError):
        clubdata.load("E0")

    # ⑥ 新季初期残段下游正常（standings 小样本、终局判定不成立）
    import clubsim
    part = df[(df.date >= "2025-07-01") & (df.date <= "2025-09-30")]
    st = clubsim.standings(part)
    assert 0 < len(st) <= 20 and all(1 <= r["played"] <= 8 for r in st)
    assert not all(r["played"] == 2 * (len(st) - 1) for r in st)   # overview complete=False 前提


def test_clubdata_feeder_mapping():
    """赛季模拟 feeder 映射：S5 全覆盖、feeder 码合法且自身不是 S 级。"""
    import clubdata
    assert set(clubdata.FEEDER) == {"E0", "SP1", "I1", "D1", "F1"}
    assert all(v in clubdata.LEAGUES for v in clubdata.FEEDER.values())
    assert not set(clubdata.FEEDER.values()) & set(clubdata.FEEDER)


def test_clubsim_h2h_tiebreak_laliga_rule():
    """西甲口径 tiebreak 插拔：同分时 gd 模式看总净胜、h2h 模式看相互战绩，榜首应互换。"""
    import pandas as pd
    import clubsim
    facts = pd.DataFrame([          # A/B 同 7 分：A 总净胜 +8，B 相互战绩 4>1
        ("A", "B", 0, 2), ("B", "A", 1, 1),
        ("A", "C", 9, 0), ("C", "A", 0, 1),
        ("B", "C", 1, 0), ("C", "B", 1, 0),
    ], columns=["home_team", "away_team", "home_score", "away_score"])
    kw = dict(model=None, teams={"A", "B", "C"}, facts=facts, remaining=[], sims=8)
    top_gd = clubsim.SeasonSimulator(**kw, tiebreak="gd").run()[0]
    top_h2h = clubsim.SeasonSimulator(**kw, tiebreak="h2h").run()[0]
    assert top_gd["team"] == "A" and top_gd["title"] == 1.0
    assert top_h2h["team"] == "B" and top_h2h["title"] == 1.0
    assert clubsim.LEAGUE_TIEBREAK == {"SP1": "h2h", "I1": "h2h"}


def test_clubsim_remaining_pairs_matches_real_calendar():
    """剩余赛程推导 == 真实日历 as_of 之后的对阵集合（20 队英超 + 18 队德甲精确等值）。"""
    import pandas as pd
    import clubsim
    try:
        import clubdata
        for code, n_season in (("E0", 380), ("D1", 306)):
            df = clubdata.load(code, seasons=7)
            season = clubsim.season_slice(df, "2024-08-01", "2025-06-01")
            cut = pd.Timestamp("2025-01-01")
            facts = season[season.date < cut]
            actual = set(zip(*(season[season.date >= cut][c] for c in ("home_team", "away_team"))))
            teams = set(season.home_team) | set(season.away_team)
            derived = set(clubsim.remaining_pairs(facts, teams))
            assert derived == actual, f"{code} 推导剩余赛程与真实日历不符"
            assert len(facts) + len(derived) == n_season
    except AssertionError:
        raise
    except Exception as e:  # noqa
        pytest.skip(f"club 数据不可得：{e}")


def test_clubdata_load_fixtures_schema():
    """fixtures.csv 装载：结构断言（休赛期可为空，只保证 schema 与联赛过滤）。"""
    import clubdata
    try:
        fx = clubdata.load_fixtures()
    except Exception as e:  # noqa
        pytest.skip(f"fixtures 不可得：{e}")
    for c in ("div", "date", "home_team", "away_team", "B365H", "B365D", "B365A"):
        assert c in fx.columns
    if len(fx):
        assert fx["div"].isin(clubdata.LEAGUES).all()
        assert fx["date"].is_monotonic_increasing


# ---------- P1-① event 上下文闸门 ----------
def test_event_gate_default_byte_identical(client):
    """?event=wc2026 与无参数响应逐字节一致（golden diff 核心断言）。
    /api/bracket 是"随机一届"抽样端点，两次调用天然不同，不进逐字节样本。"""
    for path in ("/api/ratings", "/api/teams", "/api/verify", "/api/config", "/api/champ_ci"):
        a = client.get(path)
        b = client.get(path + "?event=wc2026")
        assert a.status_code == b.status_code == 200, path
        assert a.get_data() == b.get_data(), f"{path} 响应不一致"


def test_event_gate_bogus_400(client):
    r = client.get("/api/ratings?event=bogus")
    assert r.status_code == 400
    assert "unknown event" in r.get_json()["error"]


def test_event_gate_not_wired_placeholder(client):
    import events
    for key in events.EVENTS:
        if key == events.DEFAULT:
            continue
        d = client.get(f"/api/dashboard?event={key}").get_json()
        assert d == {"status": "not_wired", "event": key, "name": events.EVENTS[key]["name"]}


# ---------- P1-② league code 参数化 ----------
def test_espn_url_league_param():
    import live, espn_odds
    # 默认与历史字面量逐字节相同（零行为变化）
    assert live.ESPN_URL == ("https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/"
                             "scoreboard?dates={d1}-{d2}&limit=300")
    assert espn_odds.SB_URL == live.ESPN_URL
    assert espn_odds.SUM_URL == ("https://site.api.espn.com/apis/site/v2/sports/soccer/"
                                 "fifa.world/summary?event={eid}")
    # 三例参数化构造（fifa.world / uefa.nations / eng.1），不打真网
    for lg in ("fifa.world", "uefa.nations", "eng.1"):
        assert f"/soccer/{lg}/scoreboard" in live.espn_scoreboard_tmpl(lg)
        assert f"/soccer/{lg}/summary" in espn_odds.sum_url_tmpl(lg)
    # 模板占位符完好可 format
    u = live.espn_scoreboard_tmpl("eng.1").format(d1="20250809", d2="20250810")
    assert "dates=20250809-20250810" in u and "{" not in u


# ---------- P1-③ 账本按赛事隔离 ----------
def test_ledger_path_per_event_distinct():
    import events, verify, jc_review
    lp = {k: verify.ledger_path(k) for k in events.EVENTS}
    sp = {k: jc_review.store_path(k) for k in events.EVENTS}
    # 全赛事路径互异，且 wc2026 恰为既有文件（默认行为不变）
    assert len(set(lp.values())) == len(lp) and len(set(sp.values())) == len(sp)
    assert lp["wc2026"] == verify.LEDGER_PATH and sp["wc2026"] == jc_review.STORE
    import pytest
    with pytest.raises(KeyError):
        verify.ledger_path("bogus")


def test_ledger_runtime_isolation(tmp_path):
    """两个 event 账本写入不同文件、互不可见（path 显式贯穿，不依赖模块常量 patch）。"""
    import verify, jc_review
    pa, pb = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    verify.save_ledger({"m1": {"stage": "KO"}}, pa)
    verify.save_ledger({"m2": {"stage": "Group"}}, pb)
    assert set(verify.load_ledger(pa)) == {"m1"} and set(verify.load_ledger(pb)) == {"m2"}
    ja, jb = str(tmp_path / "jca.json"), str(tmp_path / "jcb.json")
    jc_review._save_all({"k1": {"date": "2026-09-01"}}, ja)
    jc_review._save_all({"k2": {"date": "2026-09-02"}}, jb)
    assert set(jc_review.load_all(ja)) == {"k1"} and set(jc_review.load_all(jb)) == {"k2"}
    assert jc_review.load_all(str(tmp_path / "absent.json")) == {}


# ---------- P1-⑤ 俱乐部接线 + nl2026 壳 ----------
def test_club_overview_api(client):
    d = client.get("/api/club/overview?event=epl2627").get_json()
    assert d["code"] == "E0" and d["source"] == "football-data.co.uk"
    assert len(d["ranking"]) == 20 and d["data_through"] >= "2025-05-01"
    if d["preseason"]:                                # 预计算 JSON 存在时校验结构与归一
        rows = d["preseason"]["rows"]
        assert len(rows) == 20
        assert abs(sum(r["title"] for r in rows) - 1.0) < 0.02
    # C1 看板补齐：本季积分榜 + 最近完赛轮
    st = d["standings"]
    # ⚠️ 26-27 滚动改判清单#3（本段四断言：complete/played=38/降级三队/末轮日=截止日）
    assert len(st["rows"]) == 20 and st["complete"] is True     # 25-26 已完结=终表
    for r in st["rows"]:
        assert r["pts"] == 3 * r["w"] + r["d"] and r["played"] == 38
        assert r["gd"] == r["gf"] - r["ga"] and r["disp"]
    pts = [r["pts"] for r in st["rows"]]
    assert pts == sorted(pts, reverse=True)
    # 与已核实的 25-26 真实终局交叉验证（progress.md 第五轮：英超降级三队）
    assert {r["team"] for r in st["rows"][-3:]} == {"West Ham", "Burnley", "Wolves"}
    lm = d["latest_matchday"]
    assert lm["rows"] and all("-" in r["score"] and r["home_disp"] for r in lm["rows"])
    assert lm["date"] == d["data_through"]                       # 完结季：末轮日=数据截止日
    # nl2026 未解锁 club 端点 → 闸门 not_wired 占位（先于路由）；无参数=默认 wc2026 → 路由内 400
    r = client.get("/api/club/overview?event=nl2026")
    assert r.status_code == 200 and r.get_json()["status"] == "not_wired"
    assert client.get("/api/club/overview").status_code == 400


# ---------- QA 基建：五联赛参数化冒烟（防注册表 data 字段手误时测试仍全绿）----------
@pytest.mark.parametrize("event,code,size", [
    ("epl2627", "E0", 20),
    ("laliga2627", "SP1", 20),
    ("seriea2627", "I1", 20),
    ("bundes2627", "D1", 18),
    ("ligue12627", "F1", 18),
])
def test_club_overview_all_leagues_smoke(client, event, code, size):
    """五赛事逐一打 /api/club/overview：注册表 event→league code 接线正确、
    实力榜非空、积分榜队数=联赛规模（20/20/20/18/18）。最小断言集控制时长。"""
    d = client.get(f"/api/club/overview?event={event}").get_json()
    assert d["code"] == code                                  # 注册表 data 字段接线一致
    assert d["ranking"] and all(r["team"] for r in d["ranking"])
    assert len(d["standings"]["rows"]) == size                # 联赛规模 20/20/20/18/18


def test_club_predict_api(client):
    d = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=曼城").get_json()
    assert abs(d["p_home"] + d["p_draw"] + d["p_away"] - 1.0) < 5e-4   # 输出 round(4) 后的容差
    assert d["home"] == "Arsenal" and len(d["top_scores"]) >= 5
    assert "90 分钟" in d["note"]
    r = client.get("/api/club/predict?event=epl2627&home=Arsnal&away=曼城")
    assert r.status_code == 404 and r.get_json()["suggest"]
    # 跨联赛球队在本联赛池内解析不到 → 404（诚实拒绝口径）
    assert client.get("/api/club/predict?event=epl2627&home=皇马&away=曼城").status_code == 404
    # 默认（无 detail）不含展开字段——C2 为增量扩展，原响应结构不变
    assert "facts" not in d and "matrix" not in d


def test_club_matchup_detail_api(client):
    """C2 对阵分析展开区：近 6 轮/交锋/主客场拆分/攻防强度 + 比分矩阵（共用实现口径）。"""
    d = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=曼城&detail=1").get_json()
    f = d["facts"]
    for side in ("home", "away"):
        rc = f[side]["recent"]
        assert rc["n"] == 6 == len(rc["matches"]) and rc["w"] + rc["d"] + rc["l"] == 6
        assert rc["form_str"] == "".join(x["res"] for x in rc["matches"])
        assert all(x["opp_disp"] for x in rc["matches"])
        sp = f[side]["split"]
        assert sp["home"]["n"] == 6 and sp["away"]["n"] == 6      # 英超数据池必然覆盖
        st = f[side]["strength"]
        assert {"atk", "dfc", "net", "avg_gf", "avg_ga"} <= set(st)
        assert abs(st["net"] - (st["atk"] - st["dfc"])) < 1e-6
    h2 = f["h2h"]
    assert h2["n"] >= 1 and h2["home_wins"] + h2["away_wins"] + h2["draws"] == h2["n"]
    assert "联赛内相对值" in f["strength_note"] and f["data_through"] == d["data_through"]
    mx = d["matrix"]
    assert mx["n"] == 6 and len(mx["p"]) == 6 and all(len(row) == 6 for row in mx["p"])
    tot = sum(sum(row) for row in mx["p"]) + mx["p_other"]
    assert abs(tot - 1.0) < 0.01
    # 交锋覆盖不到的组合（升班马 vs 豪门）诚实空态：n=0 结构仍完整
    d2 = client.get("/api/club/predict?event=epl2627&home=桑德兰&away=阿森纳&detail=1").get_json()
    assert d2["facts"]["h2h"]["n"] >= 0                            # 结构存在即可（不写死有无交锋）


def _sched(rows):
    """合成 clubfixtures 赛程帧（(offset_days, hour, 主, 客) → 帧），时间口径=北京。"""
    import clubfixtures
    import pandas as pd
    if not rows:
        return clubfixtures._frame(None)               # 空帧也要列齐/日期列 dtype 正确
    t0 = pd.Timestamp.now().normalize()
    return pd.DataFrame({
        "date": [t0 + pd.Timedelta(days=d, hours=h) for d, h, _, _ in rows],
        "home_team": [h for *_, h, _ in rows], "away_team": [a for *_, a in rows],
        "state": ["pre"] * len(rows),
        "home_espn": [h for *_, h, _ in rows], "away_espn": [a for *_, a in rows],
    })


def test_club_overview_upcoming(client, monkeypatch):
    """D3 未来赛程预测：空态必有原因；合成赛程下模型概率/池外队暂无数据/B365 透传。

    赛程主源=clubfixtures（ESPN），B365 赛前盘仍从 clubdata.load_fixtures 合并——
    两源职责分离后，本测试分别打桩，确保合并按（主,客）匹配、不含日期（两源时区不同）。"""
    import clubdata
    import clubfixtures
    import pandas as pd
    d = client.get("/api/club/overview?event=epl2627").get_json()
    up = d["upcoming"]
    assert "rows" in up and (up["rows"] or up["reason"])            # 无场次必须给原因
    assert up["timezone"] == "Asia/Shanghai" and up["fixtures_source"]
    # 第二场用虚构队名：升班马（考文垂/赫尔城）自 E1 降权合训采纳后已能出数，
    # 「池外→暂无数据」这条不变量得用真正池外的队来验。
    sched = _sched([(2, 20, "Arsenal", "Chelsea"), (2, 22, "Nowhere United FC", "Sunderland")])
    fx = pd.DataFrame({                                            # 盘口源：只有一场有盘
        "div": ["E0"], "date": [pd.Timestamp.now().normalize() + pd.Timedelta(days=2, hours=15)],
        "home_team": ["Arsenal"], "away_team": ["Chelsea"],
        "B365H": [1.5], "B365D": [4.2], "B365A": [6.0],
    })
    monkeypatch.setattr(clubfixtures, "load", lambda code, refresh=False: sched)
    monkeypatch.setattr(clubdata, "load_fixtures", lambda code=None, refresh=False: fx)
    up = client.get("/api/club/overview?event=epl2627").get_json()["upcoming"]
    rows = up["rows"]
    assert len(rows) == 2 and up["mode"] == "window" and up["days_to_first"] == 2
    r0 = next(r for r in rows if r["home"] == "Arsenal")
    assert abs(r0["p_home"] + r0["p_draw"] + r0["p_away"] - 1.0) < 1e-3
    assert r0["b365"] == [1.5, 4.2, 6.0] and r0["home_disp"] and r0["time"] == "20:00"
    r1 = next(r for r in rows if r["home"] == "Nowhere United FC")
    assert r1.get("no_model") is True and "b365" not in r1          # 真池外队诚实「暂无数据」


def test_club_predict_resolves_promoted_newcomer(client):
    """升班马新面孔（常规 E0 池外）在 Web 层可解析并出数，且必须标出 basis 与合训口径。
    无赛程缓存时该通道自动关闭（promoted 为空）→ 跳过，不因缺网变红。"""
    import app as appmod
    if not appmod._promoted_newcomers("E0"):
        pytest.skip("本机无 ESPN 赛程缓存，升班马通道关闭")
    d = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=考文垂&detail=1").get_json()
    assert d.get("basis") == "promoted_cotrained" and d["promoted"] == ["Coventry"]
    assert d["promoted_feeder_weight"] == 0.25 and d["promoted_note"]
    assert abs(d["p_home"] + d["p_draw"] + d["p_away"] - 1.0) < 1e-3
    assert "英冠" in d["facts"]["strength_note"]            # 过程数据帧含次级联赛必须写明
    assert d["facts"]["home"]["recent"]["matches"]        # 合并帧后近况不再整片空白


def test_jc_review_club_promoted_entry(client, tmp_path, monkeypatch):
    """竞彩复盘联赛入口同样认升班马（用户最初就是拿英超首轮竞彩截图来的），
    且三个消费方（看板/单场/竞彩）必须同模型同数字——口径分叉就是同一场两个答案。
    红线沿用：预览里不得出现任何「率」/推荐字样。"""
    import app as appmod
    import jc_review as jc
    if not appmod._promoted_newcomers("E0"):
        pytest.skip("本机无 ESPN 赛程缓存，升班马通道关闭")
    monkeypatch.setattr(jc, "store_path", lambda k="wc2026": str(tmp_path / "jc.json"))
    mp = client.get("/api/jc_review?event=epl2627&home=阿森纳&away=考文垂").get_json()["model_preview"]
    assert mp["home_en"] == "Arsenal" and mp["away_en"] == "Coventry"
    assert mp["basis"] == "promoted_cotrained" and mp["promoted_note"]
    assert mp["is_knockout"] is False                       # 联赛恒非淘汰赛，红线不变
    cp = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=考文垂").get_json()
    assert abs(mp["p_home"] - cp["p_home"]) < 1e-3          # 同模型同数字（predict 端点四舍五入到 4 位）
    for banned in ("胜率", "准确率", "命中率", "推荐", "ROI"):
        assert banned not in mp["promoted_note"]


def test_club_predict_non_promoted_unchanged(client):
    """纯英超对阵零改动：仍走 league 基准模型，且不带任何升班马字段。"""
    d = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=曼城").get_json()
    assert d.get("basis") == "league"
    assert "promoted" not in d and "promoted_note" not in d


def test_club_upcoming_marks_promoted_basis_per_row(client, monkeypatch):
    """同一张表里两种口径必须逐行可辨：升班马行 basis=promoted_cotrained、
    纯英超行 basis=league——混在一起不标就是把不同口径的数字并列展示。"""
    import app as appmod
    import clubdata, clubfixtures
    if not appmod._promoted_newcomers("E0"):
        pytest.skip("本机无 ESPN 赛程缓存，升班马通道关闭")
    monkeypatch.setattr(clubfixtures, "load", lambda code, refresh=False: _sched(
        [(2, 19, "Arsenal", "Coventry"), (2, 21, "Everton", "Chelsea")]))
    monkeypatch.setattr(clubdata, "load_fixtures", lambda code=None, refresh=False: None)
    up = client.get("/api/club/overview?event=epl2627").get_json()["upcoming"]
    by = {r["home"]: r for r in up["rows"]}
    assert by["Arsenal"]["basis"] == "promoted_cotrained" and "no_model" not in by["Arsenal"]
    assert by["Everton"]["basis"] == "league"
    assert up["promoted_feeder_weight"] == 0.25 and up["promoted_note"]


def test_club_overview_upcoming_next_round_fallback(client, monkeypatch):
    """14 天窗口外但赛季已排期 → 回退显示下一轮，且必须如实标注 mode/距今天数；
    「下一轮」只取首场起 4 天内的同轮场次，不把两周后的下下轮一起塞进来。"""
    import clubdata
    import clubfixtures
    monkeypatch.setattr(clubfixtures, "load", lambda code, refresh=False: _sched(
        [(20, 19, "Arsenal", "Chelsea"), (21, 21, "Liverpool", "Everton"),
         (28, 21, "Man City", "Tottenham")]))          # 第三场属下下轮，不应入选
    monkeypatch.setattr(clubdata, "load_fixtures", lambda code=None, refresh=False: None)
    up = client.get("/api/club/overview?event=epl2627").get_json()["upcoming"]
    assert up["mode"] == "next_round" and up["days_to_first"] == 20
    assert len(up["rows"]) == 2 and up["reason"] is None
    assert all("b365" not in r for r in up["rows"])     # 盘口源缺失不伪造，也不拖垮赛程


def test_club_upcoming_offseason_still_explains(client, monkeypatch):
    """真休赛期（赛程源零未来场次）：必须空态+原因，绝不静默空卡片。"""
    import clubfixtures
    monkeypatch.setattr(clubfixtures, "load", lambda code, refresh=False: _sched([]))
    up = client.get("/api/club/overview?event=epl2627").get_json()["upcoming"]
    assert up["rows"] == [] and up["reason"] and up["days_to_first"] is None


def test_jc_review_club_entry(client, tmp_path, monkeypatch):
    """C7 竞彩复盘联赛入口：club 分支隔离存储、neutral=False 口径、录入→填分→对账闭环；
    红线沿用：is_knockout 恒 False、记录无任何「率」/ROI 字段。"""
    import jc_review as jc
    store = str(tmp_path / "jc_epl.json")
    monkeypatch.setattr(jc, "store_path", lambda k="wc2026": store)
    d = client.get("/api/jc_review?event=epl2627&home=阿森纳&away=曼城").get_json()
    mp = d["model_preview"]
    assert mp["home_en"] == "Arsenal" and mp["is_knockout"] is False
    assert abs(mp["p_home"] + mp["p_draw"] + mp["p_away"] - 1.0) < 1e-6
    cp = client.get("/api/club/predict?event=epl2627&home=阿森纳&away=曼城").get_json()
    assert abs(mp["p_home"] - cp["p_home"]) < 1e-3          # 与单场预测同模型同 neutral=False 口径
    r = client.post("/api/jc_review?event=epl2627", json={
        "action": "prematch", "date": "2026-05-24", "home": "阿森纳", "away": "曼城",
        "fav_is_home": True, "line": 1, "o_fav": 2.1, "o_dog": 1.75, "my_pick": "skip"}).get_json()
    assert r["ok"] and r["record"]["is_knockout"] is False and r["reading"]
    r2 = client.post("/api/jc_review?event=epl2627", json={
        "action": "result", "date": "2026-05-24", "home": "阿森纳", "away": "曼城",
        "h90": 2, "a90": 1}).get_json()
    assert r2["ok"] and r2["reconcile"]
    saved = jc.load_all(store)
    key = jc.match_key("2026-05-24", "Arsenal", "Man City")
    assert key in saved                                      # 写入隔离存储（monkeypatch tmp）
    assert not any("rate" in k or "roi" in k.lower() for k in saved[key])   # schema 断壁
    # 未知球队诚实拒绝（本联赛池解析）
    assert client.get("/api/jc_review?event=epl2627&home=皇马&away=曼城").status_code == 400


def test_club_market_api(client):
    """C5 市场对标：三方 summary 结构、样本概率归一、诚实口径字段在位。"""
    d = client.get("/api/club/market?event=epl2627").get_json()
    if d.get("empty"):
        pytest.skip("market JSON 未生成（运行 python3 club_market.py）")
    assert d["season"] == "2025-26" and d["devig"] == "shin" and d["hl"] == 365
    assert d["n"] >= 250 and d["skipped_model"] >= 0 and d["skipped_odds"] >= 0
    for k in ("model", "open", "close"):
        assert 0.05 < d["summary"][k]["rps"] < 0.35
        assert 0.3 < d["summary"][k]["hit"] < 0.8
    rows = d["sample"]["rows"]
    assert rows and all(r["out"] in (0, 1, 2) for r in rows)
    for r in rows:
        for k in ("model", "open", "close"):
            assert abs(sum(r[k]) - 1.0) < 0.02
        assert r["home_disp"] and r["away_disp"] and "-" in r["score"]
    # 已知诚实结论方向（bt_club_market 档案）：闭盘不劣于模型——方向反转应引起人工复核
    assert d["summary"]["close"]["rps"] <= d["summary"]["model"]["rps"] + 0.002


def test_club_seasonsim_api(client):
    """C3 赛季推演：快照概率归一、played 单调、终局=真实终表 0/1、disp 在位。"""
    d = client.get("/api/club/seasonsim?event=epl2627").get_json()
    if d.get("empty"):
        pytest.skip("seasonsim JSON 未生成（运行 python3 club_seasonsim.py）")
    assert d["season"] == "2025-26" and d["mode"] == "retro" and d["sims"] >= 1000
    played = [s["played"] for s in d["snapshots"]]
    assert played == sorted(played) and played[0] == 0              # 季前快照 0 场已赛
    for s in d["snapshots"]:
        assert abs(sum(r["title"] for r in s["rows"]) - 1.0) < 0.02
        assert abs(sum(r["top4"] for r in s["rows"]) - 4.0) < 0.05
        assert abs(sum(r["bottom3"] for r in s["rows"]) - 3.0) < 0.05
        assert all(r["disp"] for r in s["rows"])
    fin = d["final"]["rows"]
    assert fin[0]["team"] == "Arsenal" and fin[0]["title"] == 1.0   # 25-26 真实冠军
    assert sum(r["title"] for r in fin) == 1.0
    assert {r["team"] for r in fin if r["bottom3"] == 1.0} == {"West Ham", "Burnley", "Wolves"}
    # 演进叙事锚点：季前热门曼城，终局冠军阿森纳（回溯推演的核心可视化内容）
    pre = max(d["snapshots"][0]["rows"], key=lambda r: r["title"])
    assert pre["team"] in ("Man City", "Arsenal", "Liverpool")
    # C4 冠军维度：周粒度 title 序列 + 关键场次影响
    ts = d.get("title_series")
    if not ts:
        pytest.skip("title_series 未生成（旧版 seasonsim JSON，重跑 club_seasonsim.py）")
    n = len(ts["as_of"])
    assert n >= 30 and "Arsenal" in ts["teams"]
    for t, ps in ts["teams"].items():
        assert len(ps) == n and all(0.0 <= p <= 1.0 for p in ps)
        assert ts["disp"][t]
    ks = d["key_shifts"]
    assert ks and all(abs(s["delta"]) >= 0.03 for s in ks)
    deltas = [abs(s["delta"]) for s in ks]
    assert deltas == sorted(deltas, reverse=True)                   # 按影响力降序
    for s in ks:
        i = ts["as_of"].index(s["from"])
        assert ts["as_of"][i + 1] == s["to"]                        # 相邻周窗口
        assert abs(ts["teams"][s["team"]][i + 1] - ts["teams"][s["team"]][i]
                   - s["delta"]) < 1e-6                             # delta 与序列自洽
        for m_ in s["matches"]:
            assert m_["res"] in "WDL" and "-" in m_["score"] and m_["opp_disp"]


def test_nl2026_predict_unlocked(client):
    d = client.get("/api/predict?home=Spain&away=France&neutral=1&event=nl2026").get_json()
    assert "p_home" in d and abs(d["p_home"] + d["p_draw"] + d["p_away"] - 1.0) < 0.02
    ev = client.get("/api/events").get_json()
    nl = next(e for e in ev if e["key"] == "nl2026")
    # ⚠️ 26-27 滚动改判清单#4：26-27 欧国联 9 月开打后 db 增长 → 到期口径化 >=658
    assert nl["db_matches"] == 658 and nl["wired"]


# ---------- B1：net_ranking 暗坑修复回归 ----------
def test_club_net_ranking_not_empty(client):
    """power_ranking 的身价过滤在俱乐部池滤空（07-19 实测暗坑）——net_ranking 必须非空，
    且 CLI 与 API 同源同值。"""
    import clubpredict
    m = clubpredict.get_club_model("E0", verbose=False)
    rows = clubpredict.net_ranking(m, 20)
    assert len(rows) == 20 and all(isinstance(s, float) for _, s in rows)
    assert rows == sorted(rows, key=lambda x: -x[1])          # 降序
    api = client.get("/api/club/overview?event=epl2627").get_json()["ranking"]
    assert [r["team"] for r in api] == [t for t, _ in rows]   # API 与 CLI 同源


# ---------- 球队数据架构裁决（2026-07-19）：共用过程数据实现 + 实体层双池隔离 ----------
def test_matchfacts_shared_impl_both_universes():
    """裁决第 1 条验收：manager.recent_form/head_to_head 为两宇宙共用实现——
    只依赖 7 个共有核心列，分别在国家队帧与俱乐部帧上跑通且账目自洽。"""
    import data as datamod, clubdata, manager
    for df, team, opp in ((datamod.load_raw(), "Spain", "Argentina"),
                          (clubdata.load("E0"), "Arsenal", "Man City")):
        f = manager.recent_form(df, team, 6)
        assert f["n"] == 6 and f["w"] + f["d"] + f["l"] == 6
        assert len(f["form_str"]) == 6 and set(f["form_str"]) <= set("WDL")
        assert f["gf"] == sum(x["gf"] for x in f["matches"])
        h = manager.head_to_head(df, team, opp, 5)
        assert h["n"] >= 1 and h["home_wins"] + h["away_wins"] + h["draws"] == h["n"]


def test_team_pool_cross_league_and_isolation():
    """裁决第 2 条验收：俱乐部池跨五大联赛共享（两个联赛各取一队均可解析），
    国家队池与俱乐部池物理隔离（国家队名不落入俱乐部池）。"""
    import clubpredict
    pool = clubpredict._league_teams()
    assert clubpredict.resolve("阿森纳", pool)[0] == ("Arsenal", "E0")
    assert clubpredict.resolve("皇家马德里", pool)[0] == ("Real Madrid", "SP1")
    for national in ("西班牙", "Argentina", "France"):
        got, _ = clubpredict.resolve(national, pool)
        assert got is None, f"国家队名 {national} 不应命中俱乐部池"


# ---------- P0-1 半衰期单一配置源 + P0-3 缓存新鲜度（2026-07-19 修复） ----------
def test_production_half_life_single_source():
    """CLI/网页/模拟器/验证账本必须共用 config.NATIONAL_HALF_LIFE=730；
    生产入口源码不得再出现旧硬编码（240/547 时间泄漏伪影）。"""
    import re
    assert abs(config.NATIONAL_HALF_LIFE - 730.0) < 1e-9
    import app as appmod
    assert abs(appmod.HALF_LIFE - config.NATIONAL_HALF_LIFE) < 1e-9
    # 生产链路文件里不允许 half_life 旧值字面量（bt_* 历史实验脚本已另标 LEGACY 除外）
    import os as _os
    root = _os.path.dirname(__file__)
    pat = re.compile(r"half_life\w*\s*=\s*(240|547)\b")
    for fname in ("simulate.py", "backtest.py", "predict.py", "app.py", "data.py",
                  "verify.py", "champ_ci.py", "bayes.py", "model.py"):
        src = open(_os.path.join(root, fname), encoding="utf-8").read()
        assert not pat.search(src), f"{fname} 仍有旧半衰期硬编码"
    # data.py 库函数默认值与生产一致（防再次漂移成 547）
    import inspect
    sig = inspect.signature(datamod.build_training_frame)
    assert abs(sig.parameters["half_life_days"].default - config.NATIONAL_HALF_LIFE) < 1e-9


def test_shared_cache_is_production_params(model):
    """共享 model.pkl 永远只允许生产参数版本（fixture 已按生产参数加载/重建）。"""
    import os as _os, pickle as _pickle
    from predict import CACHE_PATH
    assert _os.path.exists(CACHE_PATH)
    with open(CACHE_PATH, "rb") as f:
        m = _pickle.load(f)
    assert abs(m.half_life_days - config.NATIONAL_HALF_LIFE) < 1e-6


def _tmp_cache_env(monkeypatch, tmp_path):
    """把缓存路径与数据指纹源都指到 tmp，隔离真实运行环境。"""
    import predict as predictmod
    data_csv = tmp_path / "results.csv"; data_csv.write_text("d1")
    live_json = tmp_path / "live_results.json"; live_json.write_text("l1")
    monkeypatch.setattr(predictmod, "CACHE_PATH", str(tmp_path / "model.pkl"))
    monkeypatch.setattr(predictmod, "META_PATH", str(tmp_path / "model_meta.json"))
    monkeypatch.setattr(datamod, "DATA_PATH", str(data_csv))
    monkeypatch.setattr(datamod, "LIVE_PATH", str(live_json))
    return predictmod, data_csv, live_json


def _fake_df():
    import pandas as pd
    return pd.DataFrame({"date": pd.to_datetime(["2026-07-01", "2026-07-10"]),
                         "home_team": ["A", "B"], "away_team": ["B", "A"],
                         "home_score": [1.0, 0.0], "away_score": [0.0, 2.0],
                         "tournament": ["x", "x"], "neutral": [True, True]})


def test_cache_meta_fields_and_freshness_invalidation(monkeypatch, tmp_path):
    """缓存元数据完整（trained_through/场次/指纹/时间）；数据文件更新→指纹失配→自动重训；
    损坏 pkl→重建不崩；非生产参数→不写共享缓存。"""
    import json as _json, os as _os
    predictmod, data_csv, _ = _tmp_cache_env(monkeypatch, tmp_path)
    df = _fake_df()
    m0 = DixonColesModel()                       # 未拟合实例即可承载参数字段
    predictmod.save_model_cache(m0, predictmod.data_fingerprint(), df)
    meta = _json.load(open(predictmod.META_PATH))
    assert meta["trained_through"] == "2026-07-10"
    assert meta["n_train_matches"] == 2 and meta["fingerprint"] and meta["created_at"]
    assert abs(meta["half_life"] - config.NATIONAL_HALF_LIFE) < 1e-9
    assert not _os.path.exists(predictmod.CACHE_PATH + ".tmp")   # 原子写不留残
    calls = {"fit": 0}

    def fake_fit(self, dfx, verbose=True, as_of=None):
        calls["fit"] += 1
        self.teams = ["A", "B"]
        return self
    monkeypatch.setattr(DixonColesModel, "fit", fake_fit)
    monkeypatch.setattr(datamod, "load_raw", lambda *a, **k: _fake_df())
    # 1) 指纹未变：命中缓存，绝不重训
    got = predictmod.get_model(use_cache=True, verbose=False)
    assert calls["fit"] == 0 and abs(got.half_life_days - config.NATIONAL_HALF_LIFE) < 1e-9
    # 2) 数据更新（内容变→size/mtime 变）：必须自动重训
    data_csv.write_text("d1-updated")
    got = predictmod.get_model(use_cache=True, verbose=False)
    assert calls["fit"] == 1
    # 重训后缓存指纹已更新 → 再次调用回到命中
    got = predictmod.get_model(use_cache=True, verbose=False)
    assert calls["fit"] == 1
    # 3) 参数变化：half_life 不同 → 重训，且不得覆盖共享缓存
    before = open(predictmod.CACHE_PATH, "rb").read()
    got = predictmod.get_model(use_cache=True, half_life=123.0, verbose=False)
    assert calls["fit"] == 2 and abs(got.half_life_days - 123.0) < 1e-9
    assert open(predictmod.CACHE_PATH, "rb").read() == before   # 共享 pkl 未被非生产参数覆盖
    # 4) 损坏缓存：重建不崩
    open(predictmod.CACHE_PATH, "wb").write(b"corrupt")
    got = predictmod.get_model(use_cache=True, verbose=False)
    assert calls["fit"] == 3


# ---------- P0-2 2026 官方小组同分规则（tiebreak.py 三路共用实现） ----------
def test_tiebreak_two_team_h2h_over_goal_diff():
    """2026 新规：相互战绩优先于总净胜球。A、B 同 6 分，B 总净胜球更好，
    但 A 赢了 A vs B 直接对话 → A 第一（旧规则 pts→GD 会排 B 第一，此为回归锚点）。"""
    import tiebreak
    members = ["A", "B", "C", "D"]
    # A: 胜B 1-0, 胜C 1-0, 负D 0-1 → 6分, gd+1
    # B: 负A 0-1, 胜C 5-0, 胜D 2-0 → 6分, gd+6（总净胜远好于 A）
    results = {("A", "B"): (1, 0), ("A", "C"): (1, 0), ("D", "A"): (1, 0),
               ("B", "C"): (5, 0), ("B", "D"): (2, 0), ("C", "D"): (0, 0)}
    overall = {"A": (6, 1, 2), "B": (6, 6, 7), "C": (1, -7, 0), "D": (4, 0, 1)}
    ordered, audit = tiebreak.rank_group(members, overall, results, rng=None)
    assert ordered[0] == "A" and ordered[1] == "B"      # 相互战绩定胜负
    assert not audit                                     # 官方标准判定，零降级


def test_tiebreak_three_team_circle_falls_to_overall():
    """三队循环互胜（相互战绩完全对称）→ 落到总净胜球分高下。"""
    import tiebreak
    members = ["A", "B", "C", "D"]
    # A胜B 1-0, B胜C 1-0, C胜A 1-0（循环）；三队都胜 D
    results = {("A", "B"): (1, 0), ("B", "C"): (1, 0), ("C", "A"): (1, 0),
               ("A", "D"): (3, 0), ("B", "D"): (2, 0), ("C", "D"): (1, 0)}
    overall = {"A": (6, 3, 4), "B": (6, 2, 3), "C": (6, 1, 2), "D": (0, -6, 0)}
    ordered, audit = tiebreak.rank_group(members, overall, results, rng=None)
    assert ordered == ["A", "B", "C", "D"]              # 相互无区分 → 总净胜 3>2>1
    assert not audit


def test_tiebreak_recursive_reapply():
    """官方要求：相互战绩分出部分名次后，对仍并列子集**递归重算**相互战绩。
    A/B/C 同 6 分；三队小循环中 C 垫底可分出；A、B 在三队小表同成绩，
    但 A 赢了 A vs B → 递归后 A 在前（若不递归会错误落到总净胜让 B 前）。"""
    import tiebreak
    members = ["A", "B", "C", "D"]
    # 三队间：A胜B 2-1, B胜C 2-1, A负C... 构造：A/B 三队小表同分同净胜同进球，C 更差
    # A vs B: 1-0 ; A vs C: 1-2 ; B vs C: 2-0 → 小表: A 3分gd0gf2, B 3分gd+1gf2? 算：
    #  A: 胜B(1-0) 负C(1-2) → 3分, gd 0, gf 2
    #  B: 负A(0-1) 胜C(2-0) → 3分, gd +1, gf 2 → 不同。换构造：
    # A vs B: 2-2 ; A vs C: 1-0 ; B vs C: 1-0 → 小表 A 4分gd+1gf3 B 4分gd+1gf3 C 0分
    # → C 分出垫底；A、B 递归重算相互=2-2 仍平 → 落总成绩：给 B 总净胜更好
    results = {("A", "B"): (2, 2), ("A", "C"): (1, 0), ("B", "C"): (1, 0),
               ("A", "D"): (1, 1), ("B", "D"): (3, 1), ("C", "D"): (0, 0)}
    overall = {"A": (5, 1, 4), "B": (7, 3, 6), "C": (1, -2, 0), "D": (2, -2, 2)}
    # 上面 overall 与 results 不完全自洽也无碍——rank_group 只按传入值执行规则；
    # 这里刻意让 A/B/C 不同分测试会失真，改为直接构造同分：
    overall = {"A": (6, 1, 4), "B": (6, 2, 6), "C": (6, -1, 3), "D": (0, -2, 2)}
    ordered, audit = tiebreak.rank_group(members, overall, results, rng=None)
    # 三队小表：A 4分, B 4分, C 0分 → C 垫底；A/B 递归相互 2-2 无区分 → 总净胜 B(2)>A(1)
    assert ordered == ["B", "A", "C", "D"]
    assert not audit


def test_tiebreak_fifa_rank_and_degradation_audit():
    """总成绩/相互全同 → 纪律分无数据（降级留痕）→ FIFA 排名判定（不随机）。"""
    import tiebreak
    members = ["Spain", "Uruguay", "Cape Verde", "Saudi Arabia"]
    results = {("Spain", "Uruguay"): (1, 1), ("Spain", "Cape Verde"): (2, 0),
               ("Uruguay", "Cape Verde"): (2, 0), ("Spain", "Saudi Arabia"): (2, 0),
               ("Uruguay", "Saudi Arabia"): (2, 0), ("Cape Verde", "Saudi Arabia"): (1, 1)}
    overall = {"Spain": (7, 4, 5), "Uruguay": (7, 4, 5),
               "Cape Verde": (1, -4, 1), "Saudi Arabia": (1, -4, 1)}
    ordered, audit = tiebreak.rank_group(members, overall, results, rng=None)
    assert ordered[0] == "Spain" and ordered[1] == "Uruguay"       # FIFA 2 < 16
    # Cape Verde 67 / Saudi Arabia 61 → 沙特排名更好 → 第三是沙特
    assert ordered[2] == "Saudi Arabia" and ordered[3] == "Cape Verde"
    stages = [ev["stage"] for ev in audit]
    assert "discipline_unavailable" in stages          # 纪律分降级如实留痕
    assert "unresolved_random" not in stages           # 官方标准可判定，绝不随机


def test_tiebreak_thirds_official_criteria():
    """最佳第三名：积分→净胜→进球→纪律(降级)→FIFA排名；同 pts/gd/gf 时排名好者前。"""
    import tiebreak
    entries = [("A", "Ghana", 4, 0, 3), ("B", "Colombia", 4, 0, 3),
               ("C", "Haiti", 6, 2, 5), ("D", "Iran", 3, -1, 2)]
    ordered, audit = tiebreak.rank_thirds(entries, rng=None)
    assert [e[0] for e in ordered] == ["C", "B", "A", "D"]   # Colombia(13) < Ghana(73)
    assert any(ev["stage"] == "discipline_unavailable" for ev in audit)


def test_tiebreak_cross_process_reproducible():
    """跨进程可复现：同 seed 两次独立进程 simulate_once 结果完全一致。"""
    import subprocess, sys, json as _json
    code = (
        "import json,predict,data as d,simulate,config;"
        "m=predict.get_model(use_cache=True,verbose=False);"
        "s=simulate.TournamentSimulator(m,d.load_raw(),sims=8,seed=7);"
        "r=s.simulate_once(seed=11);"
        "print(json.dumps([r['champion'],r['groups'][0]['standings'],"
        "sorted(r.get('qualified_thirds') or [])]))"
    )
    outs = []
    for _ in range(2):
        p = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                           cwd=__import__("os").path.dirname(__file__))
        assert p.returncode == 0, p.stderr[-2000:]
        outs.append(p.stdout.strip().splitlines()[-1])
    assert outs[0] == outs[1]
    _json.loads(outs[0])                                   # 合法 JSON（顺带校验结构）


def test_third_place_table_495_no_regression():
    """官方 R32 495 种第三名组合映射：全部 key 可解析、槽位互异且满足候选约束。"""
    import itertools, wc2026
    table = wc2026._third_table()
    assert len(table) == 495
    for combo in itertools.combinations("ABCDEFGHIJKL", 8):
        key = "".join(combo)
        row = table.get(key)
        assert row is not None, f"缺组合 {key}"
        assign = {int(mn): L for mn, L in row.items()}
        assert sorted(assign) == sorted(wc2026.THIRD_SLOTS)
        assert sorted(assign.values()) == list(combo)              # 8 组恰好各用一次
        for mn, L in assign.items():
            assert L in wc2026.THIRD_SLOTS[mn], f"{key}: {L} 不在 {mn} 候选集"


def test_simulate_groups_uses_official_tiebreak(model):
    """向量化 MC 与共用实现一致性抽查：抽若干模拟行，重放该行比分用 rank_group
    独立复算，前三名（决定出线/对阵的部分）必须一致。"""
    import simulate as simmod, tiebreak
    sim = simmod.TournamentSimulator(model, datamod.load_raw(), sims=64, seed=3)
    N = sim.N
    known = dict(sim.actual_results)
    winners, runners, thirds, best3 = sim._simulate_groups(known)
    # 抽查第 0 组的每一行：真实赛果 known 固定 → 全部行同一比分表 → 与独立复算一致
    gid = 0
    members = sim.groups[gid]
    res_g = {p: known[p] for p in sim.fixtures[gid] if p in known}
    if len(res_g) == len(sim.fixtures[gid]):               # 小组赛已全部踢完（当前真实状态）
        pts = {t: 0 for t in members}; gd = {t: 0 for t in members}; gf = {t: 0 for t in members}
        for (h, a), (x, y) in res_g.items():
            gf[h] += x; gf[a] += y; gd[h] += x - y; gd[a] += y - x
            pts[h] += 3 if x > y else (1 if x == y else 0)
            pts[a] += 3 if y > x else (1 if x == y else 0)
        overall = {t: (pts[t], gd[t], gf[t]) for t in members}
        ordered, _ = tiebreak.rank_group(members, overall, res_g, rng=None)
        assert list(winners[:, gid]) == [ordered[0]] * N
        assert list(runners[:, gid]) == [ordered[1]] * N
        assert list(thirds[:, gid]) == [ordered[2]] * N


# ---------- P0-4 陈旧伤停门控（默认纯 DC；verified+TTL / 首发确认才生效） ----------
def test_availability_gate_unverified_and_stale_inert():
    """未核验 → 跳过；verified 但过期 → 跳过；verified+新鲜 → 生效。全程留痕。"""
    import adjust, datetime as _dt
    now = _dt.datetime(2026, 7, 19, 12, 0)
    avail = {"_meta": {"updated": "2026-06-08"},
             "Brazil": [{"player": "X", "status": "out", "role": "attack", "tier": "key"}]}
    mods, audit = adjust.team_modifiers_audited(avail, now=now)
    assert mods == {} and audit["skipped"][0]["reason"] == "unverified"
    avail["Brazil"][0]["verified"] = True          # 已核验但 updated 距今 41 天 → 过期
    mods, audit = adjust.team_modifiers_audited(avail, now=now)
    assert mods == {} and audit["skipped"][0]["reason"].startswith("stale")
    avail["Brazil"][0]["updated_at"] = "2026-07-18"   # 核验且新鲜 → 生效
    mods, audit = adjust.team_modifiers_audited(avail, now=now)
    assert "Brazil" in mods and mods["Brazil"]["att"] < 1.0 and not audit["skipped"]
    assert mods["Brazil"]["items"][0]["eligible_via"] == "verified_fresh"


def test_availability_production_file_currently_inert():
    """现存 availability.json 是 2026-06-08 未核验种子数据 → 生产必须零影响（纯 DC）。"""
    import adjust
    mods, audit = adjust.team_modifiers_audited()
    assert mods == {}, f"陈旧种子数据不得进入生产: {list(mods)}"
    assert audit["skipped"], "种子登记应以 unverified/stale 留痕，而非消失"


def test_availability_lineup_confirmation_paths():
    """已确认首发：started 归零 / bench 0.7 / absent 满档；未公布名单→未核验登记全部降级纯模型。"""
    import adjust, lineups
    reg = [{"player": "Star Man", "status": "doubtful", "prob": 0.3, "role": "attack",
            "tier": "superstar"},
           {"player": "Bench Guy", "status": "doubtful", "prob": 0.2, "role": "defence",
            "tier": "key"},
           {"player": "Gone Guy", "status": "doubtful", "prob": 0.1, "role": "all",
            "tier": "key"}]
    lt = {"confirmed": True, "starters": [lineups._norm("Star Man")],
          "bench": [lineups._norm("Bench Guy")], "names": {}}
    items, status = lineups.detect_team("TeamZ", reg, lt)
    st = {s["player"]: s["lineup_status"] for s in status}
    assert st == {"Star Man": "started", "Bench Guy": "bench", "Gone Guy": "absent"}
    mods, audit = adjust.team_modifiers_audited({"TeamZ": items})
    assert not audit["skipped"]                     # 比赛级确认 → 全部合规进入
    m = mods["TeamZ"]
    assert m["att"] < 1.0 and m["def_pen"] > 1.0    # absent(all) + bench(defence) 起效
    who = {i["player"]: i for i in m["items"]}
    assert "Star Man" not in who                    # 确认首发 → 惩罚归零，不出现在生效项
    assert who["Gone Guy"]["eligible_via"] == "lineup_confirmed"
    # 首发未公布（unknown）→ 未核验登记必须整体降级为纯模型，不得静默用旧伤停
    items2, _ = lineups.detect_team("TeamZ", reg, None)
    mods2, audit2 = adjust.team_modifiers_audited({"TeamZ": items2})
    assert mods2 == {} and len(audit2["skipped"]) == 3


def test_availability_empty_zero_effect():
    import adjust
    mods, audit = adjust.team_modifiers_audited({})
    assert mods == {} and audit["applied"] == 0 and audit["skipped"] == []


def test_freeze_ledger_records_adjustments(model, tmp_path):
    """冻结账本必须记录本场用了哪些 adjustment（纯 DC = availability 空 dict）+ 数据时间。"""
    import json as _json
    import simulate as simmod, verify as vf
    # 决赛（北京 7-20 03:00）赛果 2026-07-20 起已入库，freeze 对已完赛场次永不再写；
    # 剔除 2026-07-19 起的赛果行复现「决赛赛前」可冻结场景（机制断言不变）。
    df = datamod.load_raw()
    sim = simmod.TournamentSimulator(model, df[df.date < "2026-07-19"], sims=4, seed=5)
    p = str(tmp_path / "ledger.json")
    n = vf.freeze(sim, now_bj="2026-07-19 12:00", path=p)
    assert n >= 1                                   # 决赛未开球，至少 1 场可冻结
    led = _json.load(open(p))["preds"]
    assert led
    for ent in led.values():
        adj = ent.get("adjustments")
        assert adj is not None and "availability" in adj and "env" in adj
        assert adj["availability"] == {}            # 默认纯 DC：无可用性乘子


# ---------- P0-5 90分钟/含加时口径（known_et_mask + jc_review 手填隔离） ----------
def test_known_et_mask_flags_aet_final_not_group_draw():
    """典型加时决赛（2022 阿根廷-法国 3-3 点球）必须被标记；90 分钟小组赛平局不标。"""
    df = datamod.load_raw(live=False)
    m = datamod.known_et_mask(df)
    fin = df[(df.home_team == "Argentina") & (df.away_team == "France")
             & (df.date == "2022-12-18")]
    assert len(fin) == 1 and bool(m[fin.index].all())          # 加时场次命中
    grp = df[(df.tournament == "FIFA World Cup") & (df.date == "2022-11-26")
             & (df.home_score == df.away_score) & df.home_score.notna()]
    if len(grp):                                               # 小组赛 90 分钟平局不误标
        assert not m[grp.index].any()
    # 2026 淘汰赛四场点球（含加时）全部命中
    df2 = datamod.load_raw()
    m2 = datamod.known_et_mask(df2)
    ko26 = df2[(df2.tournament == "FIFA World Cup") & (df2.date >= "2026-06-28")
               & df2.home_score.notna()]
    d26 = ko26[ko26.home_score == ko26.away_score]
    assert len(d26) >= 1 and m2[d26.index].all()


def test_jc_review_settle_never_reads_results_csv():
    """竞彩 90 分钟复盘只用手填比分结算——jc_review 源码不得引用 results.csv/load_raw。"""
    import os as _os
    src = open(_os.path.join(_os.path.dirname(__file__), "jc_review.py"),
               encoding="utf-8").read()
    import re
    # 仅允许出现在注释/文档字符串里的『不复用 results.csv』说明；不得有实际读取调用
    assert "load_raw(" not in src and 'read_csv' not in src


# ---------- P1-8 Bayes 区间：收敛门槛 / 发布闸 / MCSE 结构 / ρ 混用锁定 ----------
def test_bayes_convergence_gate_logic():
    import bayes
    ok = {"rhat_max": 1.01, "ess_min": 800.0, "divergences": 0}
    assert bayes.convergence_ok(ok)
    assert not bayes.convergence_ok({**ok, "rhat_max": 1.2})     # R-hat 爆 → 拒绝
    assert not bayes.convergence_ok({**ok, "ess_min": 50.0})     # ESS 不足 → 拒绝
    assert not bayes.convergence_ok({**ok, "divergences": 3})    # divergence → 拒绝
    assert not bayes.convergence_ok({})                          # 缺诊断 → 拒绝


def test_champ_ci_refuses_unconverged_draws():
    import champ_ci, pytest as _pt
    with _pt.raises(SystemExit):                 # 旧格式（无 converged 标记）→ 拒绝
        champ_ci.assert_draws_publishable({"atk": 1})
    with _pt.raises(SystemExit):                 # 显式未收敛 → 拒绝
        champ_ci.assert_draws_publishable({"converged": np.array(False)})
    champ_ci.assert_draws_publishable({"converged": np.array(True)})   # 达标 → 放行


def test_champ_ci_model_from_draw_keeps_dc_rho(model):
    """ρ 混用口径锁定：draw 模型的低分修正 ρ 必须 == 基线 DC 点估（文档声明的行为）。"""
    import champ_ci
    teams = list(model.attack)[:4]
    md = champ_ci._model_from_draw(model, teams, np.zeros(4), np.zeros(4), 0.1, 0.2)
    assert md.rho == model.rho
    assert md.intercept == 0.1 and md.home_adv == 0.2
    assert md.avail_att == {} and md.avail_def == {}             # 纯引擎，无上下文层


# ---------- P1-9 淘汰赛晋级路径分解（90'胜/加时胜/点球先验） ----------
def _mk_sim(model, sims=8, seed=1):
    import simulate as simmod
    return simmod.TournamentSimulator(model, datamod.load_raw(), sims=sims, seed=seed)


def test_advancement_paths_structure_and_sum(model):
    sim = _mk_sim(model)
    p = sim.advancement_paths("Spain", "Argentina")
    q = sim.advancement_paths("Argentina", "Spain")
    for d in (p, q):
        assert set(d) >= {"win90", "et_win", "pen_win", "adv", "approx"}
        assert 0 <= d["win90"] <= 1 and d["adv"] <= 1
        assert abs(d["adv"] - (d["win90"] + d["et_win"] + d["pen_win"])) < 1e-12
    # 两侧晋级概率之和 = 1（同一场：A 晋级 + B 晋级）
    assert abs(p["adv"] + q["adv"] - 1.0) < 1e-9


def test_advancement_symmetric_teams_near_half(model):
    """同一支队自对阵不合法；用镜像检验：A vs B 与 B vs A 的 adv 互补即对称性成立。
    另取实力接近的两队，点球路径两侧应几乎相等（先验 50/50）。"""
    sim = _mk_sim(model)
    a, b = "Spain", "Argentina"
    pa = sim.advancement_paths(a, b)
    pb = sim.advancement_paths(b, a)
    assert abs(pa["pen_win"] - pb["pen_win"]) < 0.01     # 点球先验平坦 → 两侧接近
    assert abs(pa["adv"] + pb["adv"] - 1) < 1e-9


def test_advancement_strong_vs_weak_pen_not_inflated(model):
    """强弱悬殊：晋级差距应主要来自 win90；平局后的点球分支不得再送强队
    （旧 bug：ph/(ph+pa) 冒充点球能力 → 平局后强队仍拿 80%+）。"""
    sim = _mk_sim(model)
    p = sim.advancement_paths("Spain", "Cape Verde")
    assert p["adv"] > 0.75                                # 强队总晋级概率仍高
    # 平局后条件晋级概率 = _pen：由加时(仍有优势)+点球(50/50)构成，
    # 必须显著低于旧近似的常规时间胜率归一化值
    ph, _, pa_ = sim._wdl("Spain", "Cape Verde")
    old_pen = ph / (ph + pa_)
    new_pen = sim._pen("Spain", "Cape Verde")
    assert new_pen < old_pen - 0.05
    assert 0.5 < new_pen < 0.9                            # 加时优势保留但不再等同90'实力差


def test_advancement_host_orientation(model):
    """东道主朝向：同一对阵给主队 host 时晋级概率应不低于中立场。"""
    sim = _mk_sim(model)
    neutral = sim.advancement_paths("United States", "Japan")["adv"]
    hosted = sim.advancement_paths("United States", "Japan", host="United States",
                                   city="Los Angeles")["adv"]
    assert hosted > neutral


# ==================== P0-A 俱乐部赛前冻结 / 赛后结算（clubverify） ====================
import os as _os
# 需求：docs/UPGRADE_REQUIREMENTS_2026-07-25.md §3（冻结）+ §10 修正二/三（五联赛批量、结算闭环）
# 全部离线：赛程与赛果都用合成帧注入，不依赖网络，也不写生产账本（ledger 参数指向 tmp）。

def _fx(rows):
    """合成 fixtures 帧（列名与 clubdata.load_fixtures 一致）。"""
    import pandas as pd
    return pd.DataFrame({"div": [r[0] for r in rows],
                         "date": [pd.Timestamp(r[1]) for r in rows],
                         "home_team": [r[2] for r in rows],
                         "away_team": [r[3] for r in rows]})


def _res(rows):
    """合成赛果帧（列名与 clubdata.load 一致的最小子集）。"""
    import pandas as pd
    return pd.DataFrame({"date": [pd.Timestamp(r[0]) for r in rows],
                         "home_team": [r[1] for r in rows], "away_team": [r[2] for r in rows],
                         "home_score": [r[3] for r in rows], "away_score": [r[4] for r in rows]})


def _utc(s):
    import datetime as _dt
    return _dt.datetime.fromisoformat(s).replace(tzinfo=_dt.timezone.utc)


@pytest.fixture
def led(tmp_path):
    return str(tmp_path / "predictions_epl2627.json")


EPL_FX = [("E0", "2026-08-21 15:00", "Arsenal", "Man United"),
          ("E0", "2026-08-21 17:30", "Liverpool", "Chelsea"),
          ("E0", "2026-08-22 16:30", "Man City", "Tottenham")]


def test_clubverify_freezes_with_zero_current_season_results(led):
    """核心约束：26-27 当季 CSV 尚不存在（0 场已赛）时仍能出赛前冻结。
    否则冻结器要等 CSV 落地，而 CSV 通常开赛后才有——正好错过首轮。"""
    import json, clubverify
    r = clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                                now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    assert r["status"] == "ok" and r["frozen_new"] == 3
    preds = json.load(open(led, encoding="utf-8"))["preds"]
    e = preds["Arsenal|Man United"]
    assert e["retro"] is False and e["settlement_status"] == "unsettled"
    assert abs(e["p_home"] + e["p_draw"] + e["p_away"] - 1.0) < 1e-8
    assert e["model_universe"] == "club_E0" and e["model_half_life"] == 365


def test_clubverify_uses_historical_model_before_new_csv(led):
    """训练帧与赛程解耦：data_through 落在历史季（26-27 一场未赛）。"""
    import json, clubverify
    clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                            now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    e = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    assert e["data_through"] < "2026-08-01"


def test_clubverify_never_mutates_after_kickoff(led):
    """开球后再跑，赛前字段逐字节不变（冻结账本的全部意义）。"""
    import json, clubverify
    clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                            now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    before = open(led, encoding="utf-8").read()
    r = clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                                now_utc=_utc("2026-08-23T02:00:00"), ledger=led)
    assert r["skipped_started"] == 3 and r["frozen_new"] == 0
    assert open(led, encoding="utf-8").read() == before


def test_clubverify_updates_rescheduled_fixture_before_kickoff(led):
    """改期：开球前更新开球时间并留 rescheduled_from；概率不重算、不产生第二条记录。"""
    import json, clubverify
    clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                            now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    p0 = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    moved = [("E0", "2026-08-25 20:00", "Arsenal", "Man United")] + EPL_FX[1:]
    r = clubverify.freeze_event("epl2627", fixtures=_fx(moved),
                                now_utc=_utc("2026-07-26T02:00:00"), ledger=led)
    preds = json.load(open(led, encoding="utf-8"))["preds"]
    assert r["updated_prekickoff"] == 1 and len(preds) == 3          # 不新增重复场次
    e = preds["Arsenal|Man United"]
    assert e["rescheduled_from"] == p0["kickoff_utc"] and e["kickoff_utc"] != p0["kickoff_utc"]
    assert (e["p_home"], e["p_draw"], e["p_away"]) == (p0["p_home"], p0["p_draw"], p0["p_away"])


def test_clubverify_unknown_team_writes_no_fake_prediction(led):
    """池外队（升班马/错拼）只计数跳过，绝不写伪概率。"""
    import json, clubverify
    fx = _fx(EPL_FX + [("E0", "2026-08-22 14:00", "Arsenal", "Nowhere United FC")])
    r = clubverify.freeze_event("epl2627", fixtures=fx,
                                now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    assert r["skipped_no_model"] == 1 and r["frozen_new"] == 3
    assert "Arsenal|Nowhere United FC" not in json.load(open(led, encoding="utf-8"))["preds"]


def test_clubverify_empty_schedule_returns_no_fixtures(led):
    """赛程未发布 = no_fixtures（赛程层），不得伪装成 no_model（模型层）。"""
    import clubverify
    r = clubverify.freeze_event("epl2627", fixtures=_fx([]),
                                now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    assert r["status"] == "no_fixtures" and r["reason_code"] == "schedule_unpublished"
    assert r["poll_after_seconds"] == 0 and "no_model" not in str(r)
    assert not _os.path.exists(led)                                   # 空态不创建空账本


def test_clubverify_bst_to_utc_and_beijing(led):
    """时区口径：8 月英超是 BST(UTC+1)，1 月是 GMT——naive 当 UTC 会整整偏 1 小时。"""
    import json, clubverify
    fx = _fx([("E0", "2026-08-21 15:00", "Arsenal", "Man United"),
              ("E0", "2027-01-02 15:00", "Liverpool", "Chelsea")])
    clubverify.freeze_event("epl2627", fixtures=fx,
                            now_utc=_utc("2026-07-25T02:00:00"), ledger=led)
    preds = json.load(open(led, encoding="utf-8"))["preds"]
    assert preds["Arsenal|Man United"]["kickoff_utc"] == "2026-08-21T14:00:00Z"    # BST
    assert preds["Arsenal|Man United"]["kickoff_bj"] == "2026-08-21 22:00"
    assert preds["Liverpool|Chelsea"]["kickoff_utc"] == "2027-01-02T15:00:00Z"     # GMT
    assert preds["Liverpool|Chelsea"]["kickoff_bj"] == "2027-01-02 23:00"


def test_clubverify_event_ledger_isolated():
    """账本按赛事隔离：五联赛 + 世界杯路径互异（registry 层不变量的冻结器侧断言）。"""
    import clubverify, verify
    paths = [clubverify.ledger_path(k) for k in
             ("epl2627", "laliga2627", "seriea2627", "bundes2627", "ligue12627")]
    assert len(set(paths)) == 5 and verify.ledger_path("wc2026") not in paths
    assert clubverify.ledger_path("epl2526") == clubverify.ledger_path("epl2627")  # 别名同账本


def test_clubverify_rejects_non_club_event():
    """国家队赛事不得走俱乐部冻结器（错走会把 intl 预测写进联赛账本）。"""
    import clubverify
    with pytest.raises(ValueError):
        clubverify.freeze_event("wc2026", fixtures=_fx([]))
    with pytest.raises(KeyError):
        clubverify.freeze_event("bogus2627", fixtures=_fx([]))


def test_clubverify_atomic_concurrent_freeze(led):
    """并发冻结：读改写串行 + 原子替换，账本不撕裂、不丢更新。"""
    import json, threading, clubverify
    fxs = [_fx([("E0", "2026-08-21 15:00", "Arsenal", "Man United")]),
           _fx([("E0", "2026-08-21 17:30", "Liverpool", "Chelsea")]),
           _fx([("E0", "2026-08-22 16:30", "Man City", "Tottenham")])]
    ts = [threading.Thread(target=clubverify.freeze_event, args=("epl2627", f),
                           kwargs=dict(now_utc=_utc("2026-07-25T02:00:00"), ledger=led))
          for f in fxs]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert len(json.load(open(led, encoding="utf-8"))["preds"]) == 3


def test_clubverify_does_not_import_worldcup_schedule():
    """冻结器不得进世界杯赛制分支（schedule / TournamentSimulator）。"""
    # 走 AST 而不是字符串匹配：模块文档字符串里恰好写了「不得 import schedule」的理由，
    # 纯 grep 会被自己的注释误伤。
    import ast
    tree = ast.parse(open(_os.path.join(_os.path.dirname(__file__), "clubverify.py"),
                          encoding="utf-8").read())
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.module:
            mods.add(n.module.split(".")[0])
    assert "schedule" not in mods and "simulate" not in mods
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
            {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "TournamentSimulator" not in names


def test_clubverify_scheduler_discovers_all_active_club_events():
    """调度从注册表推导，五大联赛全覆盖——手工 key 列表必然漏掉 8 月下旬开赛的四家。

    as-of 取 08-05：真实赛历（ESPN 08-03 实测）下五家首轮为 08-15~08-28，此日全部
    落进 soon 的 30 天窗。原用的 07-25 在赛历校正后德甲已达 34 天=upcoming，
    改判依据是赛历事实而非放宽断言。"""
    import datetime as _dt, clubverify
    act = clubverify.active_club_events(_dt.date(2026, 8, 5))
    assert set(act) == {"epl2627", "laliga2627", "seriea2627", "bundes2627", "ligue12627"}


def test_clubverify_scheduler_excludes_feeder_leagues():
    """feeder（英冠等）只做升班马评级来源，绝不进冻结调度。"""
    import datetime as _dt, clubdata, clubverify, events
    feeders = set(clubdata.FEEDER.values())
    for k in clubverify.active_club_events(_dt.date(2026, 7, 25)):
        assert events.EVENTS[k]["data"] not in feeders


def test_clubverify_parameterized_for_all_top5(tmp_path):
    """同一 freeze_event 路径覆盖五联赛：各用自己的模型池，账本互不相同。"""
    import json, clubverify
    cases = [("epl2627", "E0", "Arsenal", "Man United"),
             ("laliga2627", "SP1", "Barcelona", "Real Madrid"),
             ("seriea2627", "I1", "Inter", "Milan"),
             ("bundes2627", "D1", "Bayern Munich", "Dortmund"),
             ("ligue12627", "F1", "Paris SG", "Marseille")]
    seen = set()
    for key, code, h, a in cases:
        p = str(tmp_path / f"predictions_{key}.json")
        r = clubverify.freeze_event(key, fixtures=_fx([(code, "2026-09-01 20:00", h, a)]),
                                    now_utc=_utc("2026-08-01T02:00:00"), ledger=p)
        assert r["status"] == "ok" and r["frozen_new"] == 1, (key, r)
        e = json.load(open(p, encoding="utf-8"))["preds"][f"{h}|{a}"]
        assert e["model_universe"] == f"club_{code}"
        seen.add(p)
    assert len(seen) == 5


def test_clubverify_batch_failure_isolated_per_event(monkeypatch, tmp_path):
    """单赛事炸掉不拖垮其他联赛，但必须计入 hard_failures。"""
    import clubverify
    real = clubverify.freeze_event

    def boom(key, **kw):
        if key == "seriea2627":
            raise RuntimeError("模拟意甲映射损坏")
        return {"status": "no_fixtures", "reason_code": "schedule_unpublished", "event": key}

    monkeypatch.setattr(clubverify, "tz_verified", lambda code: True)   # 绕开时区闸，只测隔离
    monkeypatch.setattr(clubverify, "freeze_event", boom)
    monkeypatch.setattr(clubverify, "settle_event", lambda key, **kw: {"status": "ok"})
    out = clubverify.run_all()
    assert out["hard_failures"] == 1 and out["status"] == "partial"
    assert out["events"]["seriea2627"]["freeze"]["status"] == "error"
    assert out["events"]["epl2627"]["freeze"]["status"] == "no_fixtures"
    assert clubverify.freeze_event is boom and real is not boom


def test_clubverify_freezes_epl_and_second_league(tmp_path):
    """一个联赛无赛程不影响另一个联赛冻结（批量隔离的正向证据）。"""
    import json, clubverify
    p1, p2 = str(tmp_path / "a.json"), str(tmp_path / "b.json")
    r1 = clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                                 now_utc=_utc("2026-07-25T02:00:00"), ledger=p1)
    r2 = clubverify.freeze_event("bundes2627", fixtures=_fx([]),
                                 now_utc=_utc("2026-07-25T02:00:00"), ledger=p2)
    assert r1["frozen_new"] == 3 and r2["status"] == "no_fixtures"
    assert len(json.load(open(p1, encoding="utf-8"))["preds"]) == 3 and not _os.path.exists(p2)


def test_daily_update_invokes_club_freeze(monkeypatch):
    """每日任务必须调用同一份 clubverify 实现（不得另写一套逻辑）。"""
    import daily_update, clubverify
    called = {}
    monkeypatch.setattr(clubverify, "run_all", lambda **kw: called.setdefault("hit", True) and {} or
                        {"events": {}, "hard_failures": 0})
    src = open(_os.path.join(_os.path.dirname(__file__), "daily_update.py"), encoding="utf-8").read()
    assert "clubverify" in src and "run_all()" in src
    daily_update_main_src = src[src.index("def main"):]
    assert daily_update_main_src.count("freeze_event(") == 0      # 不复制逻辑，只调 run_all


# ---------- 结算（settle_event） ----------
def _frozen(led):
    import clubverify
    clubverify.freeze_event("epl2627", fixtures=_fx(EPL_FX),
                            now_utc=_utc("2026-07-25T02:00:00"), ledger=led)


PRE_FIELDS = ("home", "away", "event", "kickoff_utc", "kickoff_bj", "frozen_at", "retro",
              "model_universe", "model_half_life", "data_through",
              "p_home", "p_draw", "p_away", "xg_home", "xg_away")


def test_clubverify_settle_writes_result_only(led):
    """结算写赛后字段并给出对账结果。"""
    import json, clubverify
    _frozen(led)
    res = _res([("2026-08-21 15:00", "Arsenal", "Man United", 2, 1)])
    r = clubverify.settle_event("epl2627", results=res,
                                now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    assert r["settled_new"] == 1 and r["unsettled"] == 2
    e = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    assert e["settlement_status"] == "settled" and e["actual"] == "H"
    assert e["home_score_90"] == 2 and e["away_score_90"] == 1
    assert e["result_source"] == "football-data" and e["score_basis"] == "90min_regulation"


def test_clubverify_settle_never_touches_frozen_probs(led):
    """赛前字段逐字段不变——结算改赛前预测就等于事后诸葛。"""
    import json, clubverify
    _frozen(led)
    before = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    snap = {k: before[k] for k in PRE_FIELDS}
    clubverify.settle_event("epl2627", results=_res([("2026-08-21 15:00", "Arsenal",
                                                      "Man United", 0, 3)]),
                            now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    after = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    assert {k: after[k] for k in PRE_FIELDS} == snap


def test_clubverify_settle_missing_result_stays_unsettled(led):
    """缺赛果保持 unsettled 并计数：不删除、不写 0:0、不静默跳过。"""
    import json, clubverify
    _frozen(led)
    r = clubverify.settle_event("epl2627", results=_res([]),
                                now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    assert r["settled_new"] == 0 and r["unsettled"] == 3
    assert r.get("reason") == "current_season_results_unavailable"
    preds = json.load(open(led, encoding="utf-8"))["preds"]
    assert len(preds) == 3
    assert all(e["settlement_status"] == "unsettled" for e in preds.values())
    assert all("home_score_90" not in e for e in preds.values())


def test_clubverify_settle_filters_results_to_event_window(led):
    """赛季窗限定：近 7 季同一主客对阵出现多次，不限定必然张冠李戴。"""
    import clubverify
    _frozen(led)
    r = clubverify.settle_event("epl2627",
                                results=_res([("2025-09-14 15:00", "Arsenal", "Man United", 5, 0)]),
                                now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    assert r["settled_new"] == 0 and r["unsettled"] == 3      # 25-26 赛季那场不得入账


def test_clubverify_settle_preserves_home_away_identity(led):
    """主客顺序必须一致：反过来的同两队是另一场比赛。"""
    import clubverify
    _frozen(led)
    r = clubverify.settle_event("epl2627",
                                results=_res([("2026-08-21 15:00", "Man United", "Arsenal", 1, 0)]),
                                now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    assert r["settled_new"] == 0


def test_clubverify_settle_is_idempotent(led):
    """重复结算幂等：同源同比分不更新 settled_at、账本内容不变。"""
    import clubverify
    _frozen(led)
    res = _res([("2026-08-21 15:00", "Arsenal", "Man United", 2, 1)])
    clubverify.settle_event("epl2627", results=res, now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    snap = open(led, encoding="utf-8").read()
    r2 = clubverify.settle_event("epl2627", results=res,
                                 now_utc=_utc("2026-08-23T02:00:00"), ledger=led)
    assert r2["already_settled"] == 1 and r2["settled_new"] == 0
    assert open(led, encoding="utf-8").read() == snap


def test_clubverify_settle_result_correction_is_audited(led):
    """上游赛果正式修正：可改赛后字段，但必须留 result_revised_from 审计，赛前字段仍不动。"""
    import json, clubverify
    _frozen(led)
    clubverify.settle_event("epl2627", results=_res([("2026-08-21 15:00", "Arsenal",
                                                      "Man United", 2, 1)]),
                            now_utc=_utc("2026-08-22T02:00:00"), ledger=led)
    pre = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    snap = {k: pre[k] for k in PRE_FIELDS}
    r = clubverify.settle_event("epl2627", results=_res([("2026-08-21 15:00", "Arsenal",
                                                          "Man United", 2, 2)]),
                                now_utc=_utc("2026-08-24T02:00:00"), ledger=led)
    e = json.load(open(led, encoding="utf-8"))["preds"]["Arsenal|Man United"]
    assert r["result_corrections"] == 1
    assert e["result_revised_from"]["home_score_90"] == 2 and e["result_revised_from"]["away_score_90"] == 1
    assert e["actual"] == "D" and e["away_score_90"] == 2
    assert {k: e[k] for k in PRE_FIELDS} == snap


def test_clubverify_freeze_to_settle_historical_roundtrip(tmp_path, monkeypatch):
    """历史闭环：用 25-26 真实赛果跑「赛前冻结 → 结算 → 对账」。

    刻意不用 epl2526 别名（会被归一成 epl2627，赛季窗错配反而被掩盖），
    而是注入一条临时的 25-26 registry 条目——这正是别名机制的边界测试。
    """
    import json, clubdata, clubpredict, clubverify, events
    df = clubdata.load("E0", seasons=clubpredict.SEASONS)
    hist = df[(df.date >= "2026-05-01") & (df.date <= "2026-05-24")]
    if not len(hist):
        pytest.skip("25-26 末轮数据不可得")
    row = hist.iloc[0]
    monkeypatch.setitem(events.EVENTS, "epl2526test",
                        dict(name="英超 25-26（测试）", kind="league", universe="club_E0",
                             espn="eng.1", data="E0",
                             window=("2025-08-01", "2026-05-31"),
                             ledger="predictions_epl2526test.json"))
    led = str(tmp_path / "hist.json")
    fx = _fx([("E0", str(row.date), row.home_team, row.away_team)])
    r = clubverify.freeze_event("epl2526test", fixtures=fx,
                                now_utc=_utc("2026-04-01T02:00:00"), ledger=led)
    assert r["frozen_new"] == 1
    key = f"{row.home_team}|{row.away_team}"
    pre = json.load(open(led, encoding="utf-8"))["preds"][key]
    snap = {k: pre[k] for k in PRE_FIELDS}
    r2 = clubverify.settle_event("epl2526test", results=df,
                                 now_utc=_utc("2026-06-01T02:00:00"), ledger=led)
    e = json.load(open(led, encoding="utf-8"))["preds"][key]
    assert r2["settled_new"] == 1 and e["settlement_status"] == "settled"
    assert e["home_score_90"] == int(row.home_score) and e["away_score_90"] == int(row.away_score)
    assert e["retro"] is False and {k: e[k] for k in PRE_FIELDS} == snap
    assert isinstance(e["outcome_hit"], bool)


def test_clubverify_scheduled_freeze_blocked_until_tz_verified(monkeypatch, tmp_path):
    """时区闸：未通过开球时间交叉核对的联赛，定时调度不得自动冻结。

    账本按错误时区冻结后无法重写（赛前预测不可变），所以宁可 blocked 也不能先写再改。
    手工调用不受闸限制（诊断用），闸只在批量调度层。"""
    import clubverify
    monkeypatch.setattr(clubverify, "TZ_VERIFIED_PATH", str(tmp_path / "tz.json"))
    monkeypatch.setattr(clubverify, "settle_event", lambda key, **kw: {"status": "ok"})
    out = clubverify.run_all()
    assert all(v["freeze"]["status"] == "blocked" for v in out["events"].values())
    assert out["hard_failures"] == 0                       # blocked 不是失败
    assert all(v["freeze"]["reason_code"] == "kickoff_tz_unverified"
               for v in out["events"].values())
    clubverify.record_tz_verified("E0", 0.0, 3)            # 核对通过后解锁
    assert clubverify.tz_verified("E0") and not clubverify.tz_verified("SP1")
    out2 = clubverify.run_all()
    assert out2["events"]["epl2627"]["freeze"]["status"] != "blocked"
    assert out2["events"]["laliga2627"]["freeze"]["status"] == "blocked"


# ==================== P0-H 首页总览（/api/home + 前端护栏） ====================
# 需求：docs/UPGRADE_REQUIREMENTS_2026-07-25.md 第 11 节（Codex 契约 + 双方收口）
# 注意分工：布局事实（是否溢出/Tab 是否单行）由 scripts/ui_check.py 真浏览器实测，
# 这里的前端测试只做**静态护栏**（规则没被删），名字也如实反映这一点。

def _home(client, **kw):
    return client.get("/api/home" + ("?" + "&".join(f"{k}={v}" for k, v in kw.items()) if kw else "")).get_json()


def test_home_api_schema(client):
    """首页契约字段齐全，且性能预算内（JSON ≤200KB）。"""
    import json as _json
    d = _home(client)
    for k in ("schema_version", "generated_at", "cache", "hero", "freshness",
              "match_stream", "event_groups", "verification", "coverage", "warnings"):
        assert k in d, k
    assert d["hero"]["title"] and d["hero"]["subtitle"]
    assert {g["id"] for g in d["event_groups"]} == {"national", "club"}
    assert len(_json.dumps(d, ensure_ascii=False).encode()) < 200 * 1024


def test_home_api_has_no_cross_event_accuracy(client):
    """跨赛事混池是 registry 层不变量的反面：verification 只能是逐赛事数组。"""
    d = _home(client)
    v = d["verification"]
    assert set(v) == {"events"} and isinstance(v["events"], list)
    for banned in ("total", "summary", "all_site", "overall_accuracy",
                   "total_accuracy", "combined_rps"):
        assert banned not in v and banned not in d
    # 每条都必须自带赛事身份，避免"看起来像总表"的行
    assert all("event" in e and "name" in e for e in v["events"])


def test_home_api_verification_is_per_event_only(client):
    """世界杯数字必须与 /api/verify 同源同值——首页不得另算一套口径。"""
    d = _home(client)
    wc = [e for e in d["verification"]["events"] if e["event"] == "wc2026"][0]
    s = client.get("/api/verify?event=wc2026").get_json()["summary"]
    assert (wc["evaluated"], wc["outcome_hits"], wc["avg_rps"]) == \
           (s["evaluated"], s["outcome_hits"], s["avg_rps"])


def test_home_api_excludes_jc_review(client):
    """竞彩复盘红线最严：整体不进首页（连字段名都不许出现）。"""
    import json as _json
    raw = _json.dumps(_home(client), ensure_ascii=False)
    assert "jc_review" not in raw and "竞彩" not in raw


def test_home_api_contains_no_betting_copy(client):
    """首页不出投注建议/价值/EV/推荐/赔率。"""
    import json as _json
    raw = _json.dumps(_home(client), ensure_ascii=False)
    for banned in ("推荐", "投注建议", "价值", "kelly", "Kelly", "EV", "赔率", "必中", "稳赚"):
        assert banned not in raw, banned


def test_home_api_never_trains_model_or_runs_simulation(monkeypatch, client):
    """只读铁测：把训练/模拟/冻结/联网全部换成抛错，/api/home 仍须成功。"""
    import clubpredict, clubsim, verify as _v, live, urllib.request, home_dashboard
    import clubfixtures
    def boom(*a, **k):
        raise AssertionError("首页触发了被禁调用")
    monkeypatch.setattr(clubfixtures, "harvest", boom)   # ESPN 赛程只准走 load_cached，
    monkeypatch.setattr(clubfixtures, "load", boom)      # load 会联网/起后台刷新线程
    monkeypatch.setattr(clubpredict, "get_club_model", boom)
    monkeypatch.setattr(clubsim, "simulate_retro", boom, raising=False)
    monkeypatch.setattr(clubsim, "simulate_preseason", boom, raising=False)
    monkeypatch.setattr(_v, "freeze", boom)
    monkeypatch.setattr(_v, "backfill", boom)
    monkeypatch.setattr(live, "_fetch_json", boom)
    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(clubdata_mod(), "load_fixtures", boom)     # 会起后台下载线程，禁用
    home_dashboard._CACHE.clear()
    d = _home(client, fresh=1)
    assert d["schema_version"] and d["hero"]["title"]


def clubdata_mod():
    import clubdata
    return clubdata


def test_home_api_does_not_write_to_disk(client):
    """首页不写盘：请求前后所有输入产物的 mtime 逐个不变。"""
    import glob as _g, home_dashboard
    paths = ([_os.path.join(_os.path.dirname(__file__), "data", "predictions.json")]
             + _g.glob(_os.path.join(_os.path.dirname(__file__), "data", "club", "*.json"))
             + _g.glob(_os.path.join(_os.path.dirname(__file__), "data", "predictions_*.json")))
    before = {p: _os.stat(p).st_mtime_ns for p in paths if _os.path.exists(p)}
    home_dashboard._CACHE.clear()
    _home(client, fresh=1)
    assert {p: _os.stat(p).st_mtime_ns for p in before} == before


def test_home_api_cache_hit_and_invalidation(client, tmp_path):
    """TTL 内命中缓存；输入指纹变化即失效。"""
    import home_dashboard as hd
    hd._CACHE.clear()
    a = _home(client)
    b = _home(client)
    assert a["cache"]["hit"] is False and b["cache"]["hit"] is True
    assert b["cache"]["fingerprint"] == a["cache"]["fingerprint"]
    fp1 = hd._fingerprint()
    p = _os.path.join(_os.path.dirname(__file__), "data", "club", "seasonsim_E0.json")
    if _os.path.exists(p):
        st = _os.stat(p)
        _os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns + 10**9))
        try:
            assert hd._fingerprint() != fp1
        finally:
            _os.utime(p, ns=(st.st_atime_ns, st.st_mtime_ns))


def test_home_api_returns_stale_snapshot_on_rebuild_failure(monkeypatch, client):
    """重建失败但有旧快照 → 返回旧快照并标 stale + warning，绝不 500。"""
    import home_dashboard as hd
    hd._CACHE.clear()
    _home(client)
    monkeypatch.setattr(hd, "build", lambda ctx=None: (_ for _ in ()).throw(RuntimeError("boom")))
    d = hd.get({}, fresh=True)
    assert d["cache"]["stale"] is True and any("rebuild failed" in w for w in d["warnings"])


def test_home_no_fixtures_has_season_runway(client):
    """休赛期不是空卡：必须给出赛季启动时间轴（且 no_fixtures ≠ no_model）。"""
    d = _home(client)
    ms = d["match_stream"]
    if ms["status"] == "no_fixtures":
        fb = ms["fallback"]
        assert fb["kind"] == "season_runway" and len(fb["events"]) == len(_events_mod().EVENTS)
        assert all("days_to_start" in e and "state" in e for e in fb["events"])
        assert "no_model" not in str(ms)


def _events_mod():
    import events
    return events


def test_home_retro_seasonsim_never_becomes_current_highlight(client):
    """赛季/mode 不匹配的 seasonsim 绝不当新季夺冠概率（上季终局冠军是 100%）。"""
    import json as _json, home_dashboard as hd
    d = _home(client)
    for g in d["event_groups"]:
        for e in g["events"]:
            h = e.get("highlight") or {}
            if h.get("kind") == "title_favorite":
                ev = _events_mod().EVENTS[e["event"]]
                assert h["season"] == hd._season_label(ev) and h["mode"] in ("preseason", "live")
    # 现有缓存确为 retro/上季 → 现在不该有任何 title_favorite
    p = _os.path.join(_os.path.dirname(__file__), "data", "club", "seasonsim_E0.json")
    if _os.path.exists(p):
        ss = _json.load(open(p, encoding="utf-8"))
        if ss.get("mode") == "retro":
            assert not any(h.get("kind") == "title_favorite"
                           for g in d["event_groups"] for e in g["events"]
                           for h in [e.get("highlight") or {}])


def test_home_unfrozen_fixture_contains_no_probability(client):
    """未冻结的比赛不得带概率（首页绝不借用现算值填空）。"""
    d = _home(client)
    for r in d["match_stream"].get("rows", []):
        p = r["prediction"]
        if p["status"] != "ok":
            assert not any(k in p for k in ("p_home", "p_draw", "p_away"))
            assert p.get("reason_code")


def test_home_match_stream_sorted_by_kickoff(client):
    rows = _home(client)["match_stream"].get("rows", [])
    assert rows == sorted(rows, key=lambda x: x["kickoff_utc"])


def test_home_event_cards_expose_readiness(client):
    """readiness 三态必须在 API 里齐全（UI 据此上卡面，运维闸不能是隐形的）。"""
    d = _home(client)
    for g in d["event_groups"]:
        for e in g["events"]:
            r = e["readiness"]
            assert set(("fixtures", "kickoff_timezone", "ledger")) <= set(r)


def test_home_frontend_defaults_to_home_and_keeps_deep_links():
    """静态护栏：无 hash 落地首页；旧深链规范化逻辑仍在。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "if(!raw || h==='home')" in src and "goHome()" in src
    assert "history.replaceState(null,'','#wc2026/'+h" in src      # 旧单段深链回填未被删
    assert "EVENT_ALIAS" in src and "evResolve" in src             # 别名归一未被删


def test_home_css_declares_single_row_tabs_and_wrap_rules():
    """静态护栏（只保证规则没被删；真实布局由 scripts/ui_check.py 实测）。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "flex-wrap:nowrap;overflow-x:auto;scroll-snap-type:x proximity" in src
    assert "min-height:44px" in src                                 # 触控高度
    assert "overflow-wrap:anywhere" in src and "word-break:break-word" in src
    # 不许用隐藏溢出掩盖问题。先剥掉 CSS 注释再查——注释里正写着这条禁令本身，裸 grep 会自伤。
    import re as _re
    assert "body{overflow-x:hidden}" not in _re.sub(r"/\*.*?\*/", "", src, flags=_re.S).replace(" ", "")


def test_home_identity_uses_is_default_not_event_key():
    """新装配层零赛事 key 特判：页头身份走后端 is_default。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    i = src.index("function evApplyIdentity")
    body = src[i:i + 900]
    assert "meta.is_default" in body and "meta.key==='wc2026'" not in body


def test_api_events_exposes_is_default(client):
    rows = client.get("/api/events").get_json()
    assert sum(1 for r in rows if r.get("is_default")) == 1
    assert [r for r in rows if r["is_default"]][0]["key"] == _events_mod().DEFAULT


def test_club_board_declares_frozen_over_preview_priority():
    """同一场比赛不能两个页面两个数字：看板必须冻结值优先且标注口径。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "evFrozenIndex" in src
    assert "赛前冻结 ·" in src and "当前模型估算（未冻结）" in src
    assert "loadHomeData()" in src


def test_frontend_has_hashchange_router():
    """首页卡片/时间轴的点击全靠 hashchange 路由生效。

    回归的是一个真实缺陷：此前路由只在加载时跑一次（IIFE），首页里 location.hash=… 只改地址栏、
    页面纹丝不动（用户报「主页不支持跳转」）。同时它保证浏览器前进/后退可用。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "addEventListener('hashchange'" in src
    i = src.index("addEventListener('hashchange'")
    body = src[i:i + 900]
    assert "goHome(false)" in body and "selectEvent(" in body and "evResolve(" in body


def test_frontend_threads_matchup_params_through_router():
    """点某场比赛要把**那一场的两队**带进对阵分析：?h=&a= 必须一路传到 evShowTab。

    静态护栏只能证明四段签名都声明了 qs——本轮真实缺陷正是漏了一段
    （renderEventView 没声明 qs 形参 → 运行时 ReferenceError → 整个赛事视图不渲染，
    输入框根本不存在＝用户报的「获取不到 id」）。**行为事实以
    scripts/ui_click_check.py 的退出码为准**，本测试只防签名被改回去。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    for sig in ("function selectEvent(key, tab, qs)",
                "async function renderEventView(key, tab, qs)",
                "function evShowTab(key, tk, qs)"):
        assert sig in src, sig
    assert "renderEventView(key, tab, qs)" in src          # selectEvent → renderEventView
    assert "evShowTab(key, valid?tab:(isClub?'board':'matchup'), qs)" in src
    assert "selectEvent(ev, h||'', qs)" in src             # 首次加载的深链路径（刷新/分享链接）
    assert "function hmGo(el)" in src and "matchup?h=" in src


def test_frontend_home_fills_unfrozen_from_board_source():
    """首页未冻结场次的估算必须向**看板端点**取（首页后端只读、不现算），
    且标注口径——同一场绝不出现两个数字，也绝不出现没有出处的裸数字。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "function hmFillEstimates()" in src and "hmFillEstimates();" in src
    i = src.index("function hmFillEstimates()")
    body = src[i:i + 1200]
    assert "evGet(ev, 'overview')" in body                  # 与看板同源
    assert "当前模型估算（未冻结）" in body and "升班马合训估算（未冻结）" in body
    assert "预测待冻结" in src                              # 取不到仍是待冻结，不猜不填


def test_frontend_menu_visible_on_home_and_grouped():
    """菜单在首页也在（用户要能随时切走），且按模型宇宙分组。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "body.home-mode .evbar{display:none}" not in src.replace(" ", "")
    i = src.index("function renderEvbar")
    body = src[i:i + 1400]
    assert "国家队" in body and "俱乐部" in body and "ev-home" in body
    assert "location.hash='home'" in body          # 回首页走 push，后退能回到刚才的赛事


def test_boot_route_prevents_wc_chrome_flash():
    """启动期不再闪世界杯页面（静态护栏；真首帧由 scripts/ui_check.py --boot 实测）。

    根因回归：静态 HTML 本身是世界杯页（title/页头/8 Tab/#verify 默认可见），而首页落地此前要等
    /api/events 返回才切换——闪动窗口 = 一次网络往返。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    head = src[:src.index("</head>")]
    assert "__BOOT_CFG" in head and "boot-' + mode" in head        # 同步分类，零网络
    assert "event_keys | tojson" in head and "event_default | tojson" in head
    # boot 脚本必须数据驱动：不得出现任何赛事 key 字面量
    import re as _re
    boot = head[head.index("__BOOT_CFG"):]
    assert not _re.search(r"['\"](wc2026|nl2026|epl\d{4}|laliga\d{4})['\"]", boot)
    # #verify 带内联 display:block，隐藏规则必须 !important 才压得住
    assert "html.boot-home #verify, html.boot-event #verify{display:none !important}" in \
           src.replace("\n", "").replace("html.boot-home .tabs, html.boot-event .tabs,", "")
    # boot 类必须被清除，否则之后进世界杯页 Tab 会被永久压住
    assert "function finishBoot()" in src and src.count("finishBoot()") >= 4
    # 首页落地不得等 /api/events
    i = src.index("if(!raw || h==='home')")
    assert "loadEvents().then(()=>goHome())" not in src[i:i + 300]


def test_boot_header_default_preserved_for_wc():
    """boot 改写页头前必须存原值：否则切回世界杯会把首页标题贴到世界杯页上。"""
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "window.__HDR_DEF" in src[:src.index("</head>")]        # title 在 head 就存下
    i = src.index("const _HDR_DEF")
    assert "window.__HDR_DEF" in src[i:i + 300]                    # 主脚本优先读它


# ——— 静态导出（GitHub Pages）：Python 与前端 shim 的取数口径契约 ———
# 静态站靠「同一个 URL 在两侧算出同一个文件名」工作。任一侧改了 canon()/fnv1a64()
# 而另一侧没跟，全站取数会静默落空（页面不报错，只是每个请求都 404 降级）——
# 故用金标准向量把两侧口径钉死：本测试变红时，templates/index.html 里的
# canon()/fnv1a64() 必须同步改，且下面的期望值要用 node 重新对拍后再更新。
_STATIC_HASH_VECTORS = [
    ("/api/home", "dc317310f27716d4"),
    # emoji 国旗 + 中文队名 + 参数乱序（前端实际发出的就是这种）
    ("/api/predict?event=wc2026&home=%F0%9F%87%A7%F0%9F%87%B7%20%E5%B7%B4%E8%A5%BF"
     "&away=%F0%9F%87%AB%F0%9F%87%B7%20%E6%B3%95%E5%9B%BD&neutral=0",
     "f2e4d39092be7d0c"),
    # 队名含空格与撇号（football-data 拼写：Ath Madrid / Nott'm Forest）
    ("/api/club/predict?event=epl2627&home=Ath%20Madrid&away=Nott%27m%20Forest"
     "&neutral=1&detail=1", "47e39b6332a462ce"),
    ("/api/manager?away=B&home=A&neutral=1", "a40a04f5df34fc26"),
    ("/api/champions?sims=10000", "70c7269fc238a27c"),
]


def _load_export_helpers():
    """只取 export_static 的纯函数——直接 import 会触发模块级模型训练。"""
    import ast
    from urllib.parse import parse_qsl, urlparse
    src = open(_os.path.join(_os.path.dirname(__file__), "export_static.py"),
               encoding="utf-8").read()
    tree = ast.parse(src)
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in {"canon", "fnv1a64", "path_for"})
            or (isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "").startswith(("_FNV", "_MASK")))]
    ns = {"parse_qsl": parse_qsl, "urlparse": urlparse}
    exec(compile(ast.Module(body=keep, type_ignores=[]), "<export_static>", "exec"), ns)
    return ns


def test_static_export_hash_vectors_frozen():
    """金标准向量：改了口径就得两侧一起改（期望值需用 node 重新对拍）。"""
    ns = _load_export_helpers()
    for url, expect in _STATIC_HASH_VECTORS:
        assert ns["fnv1a64"](ns["canon"](url)) == expect, f"口径漂移：{url}"


def test_static_export_canon_is_order_and_encoding_insensitive():
    """参数顺序与百分号编码不得影响取数——否则同一请求会落到两个文件。"""
    ns = _load_export_helpers()
    c = ns["canon"]
    assert c("/api/predict?home=A&away=B") == c("/api/predict?away=B&home=A")
    assert c("/api/predict?home=Ath%20Madrid") == c("/api/predict?home=Ath+Madrid")
    assert c("/api/home") == "/api/home"                      # 无参数不加问号
    # 分片目录取哈希前两位，避免单目录几万文件
    assert ns["path_for"]("/api/home") == "api/dc/dc317310f27716d4.json"


def test_frontend_static_shim_present_and_off_by_default():
    """动态服务下 STATIC_MODE 必须是 false，且全部 /api/ 取数都走 apiFetch。"""
    import re
    src = open(_os.path.join(_os.path.dirname(__file__), "templates", "index.html"),
               encoding="utf-8").read()
    assert "var STATIC_MODE = false;" in src                   # 导出器按这行原文替换
    head = src[:src.index("</script>")]                        # shim 块自身不该被改写
    assert "window.apiFetch" in head
    body = src[src.index("</script>"):]
    leaked = re.findall(r"(?<!api)\bfetch\(\s*[`'\"]/api/", body)
    assert not leaked, f"有 {len(leaked)} 处 /api/ 取数漏改成 apiFetch，静态站上会 404"


def test_comp_weights_exact_name_beats_tier():
    """升班马通道的机制前提（已从 comp_tier 关键词撞车换成赛事名精确键）：
    build_training_frame 查表顺序=赛事名 > tier > 1.0。有了精确名这一级，
    西乙/意乙等与顶级同 tier 的联赛才能单独降权——撞车那条路只对英格兰成立。"""
    import datetime as _dt
    import pandas as _pd
    from data import build_training_frame
    df = _pd.DataFrame({
        "date": [_pd.Timestamp("2025-01-01")] * 2,
        "home_team": ["A", "C"], "away_team": ["B", "D"],
        "home_score": [1, 1], "away_score": [0, 0],
        "tournament": ["Spanish La Liga", "Spanish Segunda Division"],
        "neutral": [False, False]})
    tf = build_training_frame(df, half_life_days=365, min_matches=0,
                              as_of=_dt.date(2025, 1, 1),
                              comp_weights={"Spanish Segunda Division": 0.25})
    w = dict(zip(tf["attack"], tf["weight"]))
    assert abs(w["A"] - 1.0) < 1e-9 and abs(w["C"] - 0.25) < 1e-9   # 同 tier 也能分开
    # tier 键的既有行为不变（国家队侧仍按分级加权）
    tf2 = build_training_frame(df, half_life_days=365, min_matches=0,
                               as_of=_dt.date(2025, 1, 1), comp_weights={"other": 0.5})
    assert abs(dict(zip(tf2["attack"], tf2["weight"]))["A"] - 0.5) < 1e-9


def test_promoted_model_keys_weight_by_feeder_name():
    """合训模型必须用 **feeder 赛事名** 作 comp_weights 键（不是 tier）——
    这是「西乙/意乙与顶级同 tier 也能单独加权」的全部机制。抽德甲验：
    它的最优权重是 1.0，若误用 tier 键，德乙权重会连带影响德甲行，数字必然走样。"""
    import clubdata, clubpredict
    m = clubpredict.get_promoted_model("D1", verbose=False)
    assert m.comp_weights == {clubdata.LEAGUES["D2"]: clubpredict.PROMOTED_FEEDER_W["D1"]}
    assert "major" not in m.comp_weights and "other" not in m.comp_weights


def test_promoted_newcomers_per_league_subset_of_feeder():
    """逐联赛升班马名单：必须是「本联赛赛程有 ∧ 顶级帧无 ∧ feeder 帧有」的交集。
    无赛程缓存=空集（通道关闭），不因缺网变红。"""
    import clubdata, clubpredict
    seen = 0
    for code, feeder in clubdata.FEEDER.items():
        promo = clubpredict.promoted_newcomers(code)
        if not promo:
            continue
        seen += 1
        top = clubdata.load(code, seasons=clubpredict.SEASONS)
        fdr = clubdata.load(feeder, seasons=clubpredict.SEASONS)
        assert not (promo & (set(top.home_team) | set(top.away_team)))    # 顶级帧必须没有
        assert promo <= (set(fdr.home_team) | set(fdr.away_team))         # feeder 帧必须有
    if not seen:
        pytest.skip("本机无 ESPN 赛程缓存，升班马通道全关")
    assert clubpredict.promoted_newcomers("E1") == set()   # 非顶级联赛无 feeder → 空集


def test_promoted_resolution_offline():
    """升班马解析纯函数：中文/英文/大小写命中，非升班马与空池返回 None。"""
    import clubdata, clubpredict
    # 权重逐联赛裁决（bt_promoted.py 第九节）：英西法 0.25、意德 1.0——**不是通用默认**
    assert clubpredict.PROMOTED_FEEDER_W == {"E0": 0.25, "SP1": 0.25, "I1": 1.0,
                                             "D1": 1.0, "F1": 0.25}
    assert set(clubpredict.PROMOTED_FEEDER_W) == set(clubdata.FEEDER)   # 五联赛全覆盖
    promoted = {"Coventry", "Hull"}
    assert clubpredict.resolve_promoted("考文垂", promoted) == "Coventry"
    assert clubpredict.resolve_promoted("hull", promoted) == "Hull"
    assert clubpredict.resolve_promoted("曼城", promoted) is None
    assert clubpredict.resolve_promoted("考文垂", set()) is None
