#!/usr/bin/env python3
"""Web service: a Flask app wrapping score prediction + title simulation.

Web 服务：把比分预测 + 夺冠模拟做成网页。

启动：
    python3 app.py
    浏览器打开 http://127.0.0.1:5000

接口：
    GET /                     单页 UI
    GET /api/teams            可选球队列表
    GET /api/predict?home=&away=&neutral=1   单场预测(JSON)
    GET /api/champions?sims=  夺冠概率模拟(JSON, 内存缓存)
"""
from __future__ import annotations
import datetime as dt
import json
import os
import pickle
import subprocess
import sys
import threading
import time
import urllib.request

import numpy as np
from flask import Flask, jsonify, render_template, request

import clv as clvmod
import data as datamod
import espn_odds as oddsmod
import inplay as inplaymod
import live as livemod
import manager as managermod
import market
import schedule
import teams_zh
import verify as verifymod
import wc2026
from model import DixonColesModel
from predict import CACHE_PATH, get_model
from simulate import TournamentSimulator

app = Flask(__name__)

# 只读分享模式：READONLY=1 时禁用一切写接口（刷新/实时/录入假设），公网分享更安全。
READONLY = os.environ.get("READONLY", "").strip().lower() in ("1", "true", "yes", "on")
# 市场价值/Kelly 手动开闸：MARKET_UNLOCK=1 时强制显示价值/Kelly 面板（含未开赛场次的算法 EV/Kelly），
# 绕过 CLV 诚实门槛——**默认关闭**（公开默认仍诚实锁定）；开闸后前端会大字标注"未验证·非建议·不担责"。
MARKET_UNLOCK = os.environ.get("MARKET_UNLOCK", "").strip().lower() in ("1", "true", "yes", "on")


def _readonly_block():
    """只读模式下返回 403；否则返回 None（放行）。写接口开头调用。"""
    if READONLY:
        return jsonify({"ok": False, "readonly": True,
                        "error": "只读分享模式：写操作（刷新/实时/录入假设）已禁用。"}), 403
    return None


HALF_LIFE = 730.0   # 回测最优半衰期（天，修复时间泄漏后重扫定值）；refresh/live 重训同用
MODEL = get_model(use_cache=True, half_life=HALF_LIFE, verbose=True)
DF = datamod.load_raw()
_CHAMP_CACHE: dict[int, list] = {}

# 关键球员可用性『上下文层』：从 data/availability.json 现装 xG 乘子（补充层，不入缓存）。
_AVAIL_N = MODEL.set_availability()
if _AVAIL_N:
    print(f"[avail] 已装载关键球员可用性调整：{_AVAIL_N} 队受影响")

# Elo 排名缓存（解读层用，比对『模型 vs 名气』；refresh 时重算）
_ELO = {}
def _compute_elo():
    global _ELO
    try:
        import elo as elomod
        _, _ELO = elomod.prematch_ratings(DF)
    except Exception as e:  # noqa
        print(f"[elo] 解读层 Elo 计算失败（不影响主功能）：{e}"); _ELO = {}
_compute_elo()

_RAW_CHAMP: dict = {}   # 英文队名原始夺冠模拟行缓存（解读层复用，避免重复模拟）

def _champ_rows_en(sims, grp, ko_ovr):
    key = (sims, tuple(sorted(grp.items())), tuple(sorted(ko_ovr.items())))
    if key not in _RAW_CHAMP:
        _RAW_CHAMP[key] = TournamentSimulator(MODEL, DF, sims=sims).run(
            known=grp or None, ko_known=ko_ovr or None)
    return _RAW_CHAMP[key]


@app.route("/")
def index():
    return render_template("index.html", readonly=READONLY)


@app.route("/api/config")
def api_config():
    """前端启动配置：是否只读分享模式（据此隐藏写操作按钮）。"""
    return jsonify({"readonly": READONLY})


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 夺冠区间后台重算任务：bayes.py（导出后验）→ champ_ci.py（MC 区间），约 90s，子进程异步跑。
_CI_JOB = {"running": False, "updated": None, "error": None}


def _regen_ci_worker():
    """后台串行跑 bayes.py + champ_ci.py（子进程，避免 PyMC 多进程在 Flask 线程里出问题）。"""
    try:
        for script in ("bayes.py", "champ_ci.py"):
            r = subprocess.run([sys.executable, os.path.join(_BASE_DIR, script)],
                               capture_output=True, text=True, cwd=_BASE_DIR, timeout=600)
            if r.returncode != 0:
                _CI_JOB["error"] = f"{script} 失败：{(r.stderr or '')[-300:]}"
                print(f"[champ_ci] 后台重算 {_CI_JOB['error']}")
                return
        _CI_JOB["error"] = None
        _CI_JOB["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[champ_ci] 后台重算完成 {_CI_JOB['updated']}")
    except Exception as e:  # noqa
        _CI_JOB["error"] = str(e)
    finally:
        _CI_JOB["running"] = False


def regen_champ_ci_async():
    """触发后台重算（只读模式或已在跑则跳过）。新赛果重训后自动调用，实现区间自动更新。"""
    if READONLY or _CI_JOB["running"]:
        return
    _CI_JOB["running"] = True
    _CI_JOB["error"] = None
    threading.Thread(target=_regen_ci_worker, daemon=True).start()
    print("[champ_ci] 已在后台启动夺冠区间重算（bayes→champ_ci，约 90s）")


# ESPN 赔率快照后台任务：espn_odds.py（~64 次 summary 调用，约数分钟），子进程异步跑。
_ODDS_JOB = {"running": False, "updated": None}


def _regen_odds_worker():
    try:
        r = subprocess.run([sys.executable, os.path.join(_BASE_DIR, "espn_odds.py")],
                           capture_output=True, text=True, cwd=_BASE_DIR, timeout=600)
        _ODDS_JOB["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _MARKET_CACHE.clear()      # 新快照落盘后失效市场缓存，下次 /api/market 用新盘口重建
        print(f"[odds] 后台快照完成 {_ODDS_JOB['updated']}：{(r.stdout or '').strip().splitlines()[:1]}")
    except Exception as e:  # noqa
        print(f"[odds] 后台快照失败：{e}")
    finally:
        _ODDS_JOB["running"] = False


def regen_odds_async():
    """触发后台 ESPN 赔率快照（只读/已在跑则跳过）。刷新真实赛果后调用——随赛事积累开盘/闭盘线。"""
    if READONLY or _ODDS_JOB["running"]:
        return
    _ODDS_JOB["running"] = True
    threading.Thread(target=_regen_odds_worker, daemon=True).start()
    print("[odds] 已在后台启动 ESPN 赔率快照")


# app 运行期间的盘口定时快照间隔（分钟，0=关闭）；比赛日开着网页即自动积累开盘/闭盘线。
ODDS_SNAP_MIN = float(os.environ.get("ODDS_SNAP_MIN", "30"))


def _odds_scheduler():
    """守护线程：启动后 1 分钟先快照一次，之后每 ODDS_SNAP_MIN 分钟一次（只读模式不启用）。"""
    first = True
    while True:
        time.sleep(60 if first else ODDS_SNAP_MIN * 60)
        first = False
        try:
            regen_odds_async()
        except Exception as e:  # noqa
            print(f"[odds] 定时快照触发失败：{e}")


@app.route("/api/champ_ci")
def api_champ_ci():
    """夺冠概率参数不确定性区间（bayes 分层后验驱动）。含后台重算状态（computing/updated/error），
    前端据此显示"更新中…"并轮询。缺缓存文件且未在算时 available=False。"""
    path = os.path.join(_BASE_DIR, "data", "champ_ci.json")
    job = {"computing": _CI_JOB["running"], "ci_updated": _CI_JOB["updated"],
           "ci_error": _CI_JOB["error"]}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return jsonify({"available": False, **job})
    rows = [r for r in d.get("rows", []) if r["med"] > 0 or r["hi"] > 0][:24]
    for r in rows:
        r["team"] = teams_zh.disp(r["team"])
    return jsonify({"available": True, "n_draws": d.get("n_draws"),
                    "draw_sims": d.get("draw_sims"), "rows": rows, **job})


@app.route("/api/champ_ci/regen", methods=["POST"])
def api_champ_ci_regen():
    """手动触发夺冠区间后台重算。"""
    if (blocked := _readonly_block()):
        return blocked
    regen_champ_ci_async()
    return jsonify({"ok": True, "running": _CI_JOB["running"]})


_MARKET_CACHE: dict = {}


@app.route("/api/market")
def api_market():
    """市场对标 / CLV 诚实检验：模型 vs 闭盘线 RPS、抽水、分歧；有开盘赔率才算 CLV + 显著性。
    无显著正 CLV 时 show_value=False（前端据此禁止显示价值/注码）。结果缓存（含 ~10s as_of 训练）。
    ?demo=1 返回**合成演示数据**（CLV 已证明，解锁价值/Kelly 面板）——纯展示能力，非真实赔率。"""
    if request.args.get("demo"):
        return jsonify(clvmod.demo_result())
    if request.args.get("snap"):   # 手动触发一次后台 ESPN 盘口快照（积累开盘/闭盘线；完成后失效缓存）
        regen_odds_async()
    if request.args.get("fresh") or request.args.get("snap") or not _MARKET_CACHE:
        try:                       # 从最新 ESPN 快照重建 odds.csv（快、无网络；无快照则不动已有文件）
            oddsmod.build_odds_csv()
        except Exception as e:  # noqa
            print(f"[market] 重建 odds.csv 失败：{e}")
        try:
            r = clvmod.evaluate(df=DF, include_upcoming=MARKET_UNLOCK)
        except Exception as e:  # noqa
            return jsonify({"n": 0, "error": f"市场对标计算失败：{e}"}), 500
        for x in r.get("rows", []):
            x["home"], x["away"] = teams_zh.disp(x["home"]), teams_zh.disp(x["away"])
        r["odds_source"] = "ESPN · DraftKings 1X2"
        r["odds_updated"] = _ODDS_JOB.get("updated")
        r["odds_capturing"] = _ODDS_JOB["running"]
        if MARKET_UNLOCK:          # 手动开闸：强制显示面板（绕过 CLV 门槛），前端据 unlock_override 大字标注
            r["show_value"] = True
            r["unlock_override"] = True
        _MARKET_CACHE.clear()
        _MARKET_CACHE.update(r)
    return jsonify(_MARKET_CACHE)


@app.route("/api/teams")
def api_teams():
    # 仅 2026 世界杯 48 强；中文+国旗，按官方 A–L 组序展示，便于浏览
    teams = [t for g in wc2026.GROUPS.values() for t in g]
    return jsonify([teams_zh.disp(t) for t in teams])


@app.route("/api/predict")
def api_predict():
    home = request.args.get("home", "").strip()
    away = request.args.get("away", "").strip()
    neutral = request.args.get("neutral", "1") not in ("0", "false", "False")
    try:
        r = MODEL.predict(home, away, neutral=neutral)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400

    M = r["matrix"]
    side = M.shape[0]
    return jsonify({
        "home": teams_zh.disp(r["home"]), "away": teams_zh.disp(r["away"]), "neutral": neutral,
        "xg_home": round(r["xg_home"], 3), "xg_away": round(r["xg_away"], 3),
        "p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"],
        "top_scores": [{"h": i, "a": j, "p": p} for (i, j), p in r["top_scores"]],
        "matrix": M.tolist(), "side": side,
        "mv_home": market.value(r["home"]), "mv_away": market.value(r["away"]),
    })


@app.route("/api/manager")
def api_manager():
    """足球经理人深度报告：过程数据(近期/交锋/攻防) + DC 算法模型 + 全盘口结论。
    只读组装层，不训练、不碰 GLM。队名支持中文/国旗串。"""
    home = request.args.get("home", "").strip()
    away = request.args.get("away", "").strip()
    neutral = request.args.get("neutral", "1") not in ("0", "false", "False")
    try:
        r = managermod.build_report(MODEL, DF, home, away, neutral=neutral, elo=_ELO)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa  组装层任何意外都不应 500 整页
        return jsonify({"error": f"报告生成失败：{e}"}), 500

    L = teams_zh.disp
    r["home_disp"], r["away_disp"] = L(r["home"]), L(r["away"])
    for side in ("home", "away"):
        for mt in r["form"][side]["matches"]:
            mt["opp"] = L(mt["opp"])
    for row in r["h2h"]["rows"]:
        row["home"], row["away"] = L(row["home"]), L(row["away"])
        if row.get("winner"):
            row["winner"] = L(row["winner"])
    return jsonify(r)


_RATINGS = None


def _ratings():
    global _RATINGS
    if _RATINGS is None:
        path = os.path.join(os.path.dirname(__file__), "data", "bayes_ratings.json")
        try:
            with open(path, encoding="utf-8") as f:
                _RATINGS = json.load(f)
        except (FileNotFoundError, ValueError, OSError):
            _RATINGS = {"ratings": {}, "meta": {}}
    return _RATINGS


@app.route("/api/ratings")
def api_ratings():
    """贝叶斯分层评级（净实力 + 94% 可信区间），仅本届 48 强，附 DC 点估值参照。"""
    data = _ratings()
    R = data.get("ratings", {})
    rows = []
    for t in (x for g in wc2026.GROUPS.values() for x in g):
        r = R.get(t)
        if not r:
            continue
        dc = MODEL.attack.get(t, 0.0) - MODEL.defence.get(t, 0.0)
        rows.append({"team": teams_zh.disp(t), "net": r["net"], "lo": r["net_lo"],
                     "hi": r["net_hi"], "atk": r["atk"], "dfc": r["dfc"],
                     "dc_net": round(dc, 2)})
    rows.sort(key=lambda x: -x["net"])
    return jsonify({"rows": rows, "meta": data.get("meta", {}), "available": bool(rows)})


@app.route("/api/availability")
def api_availability():
    """关键球员可用性『上下文层』当前生效的 xG 调整（供前端展示，非引擎核心）。"""
    import adjust
    mods = adjust.team_modifiers()
    rows = []
    for t, m in sorted(mods.items(), key=lambda kv: kv[1]["att"]):
        rows.append({"team": teams_zh.disp(t), "att": m["att"], "def_pen": m["def_pen"],
                     "items": [{"player": i["player"], "reason": i.get("reason", ""),
                                "status": i.get("status"), "prob": i.get("prob"),
                                "role": i.get("role"), "exp_penalty": i.get("exp_penalty")}
                               for i in m["items"]]})
    return jsonify({"rows": rows, "active": bool(rows)})


@app.route("/api/environment")
def api_environment():
    """环境上下文层：高海拔/高温场馆 + 适应/受影响球队（供前端展示，非引擎核心）。"""
    import env as envmod
    cfg = envmod._cfg()
    geo = cfg["geo"]
    venues = []
    for city, g in sorted(geo.items(), key=lambda kv: -(kv[1].get("alt") or 0)):
        if (g.get("alt") or 0) >= 1200 or g.get("heat") in ("extreme", "high"):
            venues.append({"city": city, "alt": g.get("alt"), "heat": g.get("heat")})
    return jsonify({"venues": venues,
                    "alt_adapted": [teams_zh.disp(t) for t in sorted(cfg["alt_adapted"])],
                    "cool_climate": [teams_zh.disp(t) for t in sorted(cfg["cool"])]})


@app.route("/api/champions", methods=["GET", "POST"])
def api_champions():
    sims = int(request.args.get("sims", 5000))
    sims = max(500, min(sims, 20000))
    grp, ko_ovr = ({}, {})
    if request.method == "POST":
        grp, ko_ovr = _parse_overrides(request.get_json(silent=True) or {})
    key = (sims, tuple(sorted(grp.items())), tuple(sorted(ko_ovr.items())))
    if key not in _CHAMP_CACHE:
        rows = _champ_rows_en(sims, grp, ko_ovr)
        _CHAMP_CACHE[key] = [
            {"team": teams_zh.disp(t), "champ": ch, "final": fi, "sf": sf, "qf": qf, "ko": ko}
            for (t, ch, fi, sf, qf, ko) in rows
        ]
    return jsonify({"sims": sims, "conditioned": len(grp) + len(ko_ovr),
                    "rows": _CHAMP_CACHE[key]})


@app.route("/api/insights", methods=["GET", "POST"])
def api_insights():
    """解读层：模型 vs 名气(Elo) 偏差 + 伤病/环境暴露 合成每队叙事（纯展示，不算概率）。"""
    import insights
    sims = max(500, min(int(request.args.get("sims", 4000)), 20000))
    grp, ko_ovr = ({}, {})
    if request.method == "POST":
        grp, ko_ovr = _parse_overrides(request.get_json(silent=True) or {})
    rows = _champ_rows_en(sims, grp, ko_ovr)
    sim = _sim()
    cards = insights.build(rows, MODEL, sim, _ELO, topn=12)
    return jsonify({"cards": cards, "has_elo": bool(_ELO)})


_SIM = None


def _sim():
    global _SIM
    if _SIM is None:
        _SIM = TournamentSimulator(MODEL, DF, sims=1)
    return _SIM


@app.route("/api/bracket")
def api_bracket():
    """模拟完整一届，返回小组排名 + 晋级树 + 冠军（队名本地化）。"""
    seed = request.args.get("seed")
    seed = int(seed) if seed not in (None, "") else None
    d = _sim().simulate_once(seed=seed)
    L = teams_zh.disp
    for g in d["groups"]:
        for s in g["standings"]:
            s["team"] = L(s["team"])
        for mt in g["matches"]:
            mt["home"], mt["away"] = L(mt["home"]), L(mt["away"])
    for rd in d["rounds"]:
        for mt in rd["matches"]:
            mt["a"], mt["b"], mt["winner"] = L(mt["a"]), L(mt["b"]), L(mt["winner"])
    d["champion"] = L(d["champion"])
    return jsonify(d)


# martj42 数据的多个镜像源——一个 503/被墙就换下一个（urllib 默认走系统代理）
def _mirror_urls(repo_path: str) -> list[str]:
    user_repo, rest = repo_path.split("/master/")     # martj42/international_results , results.csv
    return [
        f"https://raw.githubusercontent.com/{repo_path}",
        f"https://cdn.jsdelivr.net/gh/{user_repo}@master/{rest}",
        f"https://ghproxy.net/https://raw.githubusercontent.com/{repo_path}",
    ]


def _fetch(repo_path: str, dest: str, retries: int = 2) -> str:
    """多源+重试下载到 dest（原子写：先 .tmp 再 replace，坏档不覆盖好档）。返回成功的源。"""
    last = None
    for url in _mirror_urls(repo_path):
        for _ in range(retries):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=20) as r:
                    data = r.read()
                if len(data) < 1000:                  # 太小=异常（错误页等）
                    raise ValueError(f"返回内容过小({len(data)}B)")
                tmp = dest + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, dest)
                return url
            except Exception as e:  # noqa
                last = e
    raise RuntimeError(f"所有镜像源均失败：{last}")


def _refit_all():
    """用磁盘最新数据（results.csv + live_results.json）重训模型并重建全部缓存。
    /api/refresh 与 /api/live 共用。"""
    global MODEL, DF, _SIM
    DF = datamod.load_raw()
    MODEL = DixonColesModel(half_life_days=HALF_LIFE).fit(DF, verbose=False)
    with open(CACHE_PATH, "wb") as f:
        pickle.dump(MODEL, f)
    MODEL.set_availability()   # 重训后重装可用性上下文层（pickle 不含它）
    _SIM = None
    _CHAMP_CACHE.clear()
    _RAW_CHAMP.clear()
    _compute_elo()             # 解读层 Elo 随新数据重算
    import insights; insights._AVAIL_ITEMS = None
    try:                       # 重训后用最新模型冻结未开球场次的赛前预测（验证账本）
        verifymod.freeze(_sim())
    except Exception as e:  # noqa
        print(f"[verify] 重训后冻结预测失败（不影响主功能）：{e}")
    regen_champ_ci_async()     # 新赛果重训后，后台异步重算夺冠区间（bayes→champ_ci，不阻塞）
    regen_odds_async()         # 同时后台快照 ESPN 赔率（积累开盘/闭盘线供 CLV，不阻塞）


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    """拉取最新国际比赛结果（含已踢世界杯赛果）→ 用新数据重训评级 → 刷新预测。"""
    if (blocked := _readonly_block()):
        return blocked
    ddir = os.path.join(os.path.dirname(__file__), "data")
    try:
        src = _fetch("martj42/international_results/master/results.csv",
                     os.path.join(ddir, "results.csv"))
    except Exception as e:  # noqa  下载失败：保留旧数据，给清晰提示
        return jsonify({"ok": False, "error": f"赛果数据下载失败（已试 3 个镜像源）：{e}。"
                        "多为网络/代理临时问题，稍后重试。"}), 502
    try:    # 点球数据用于淘汰赛平局判胜，缺失不致命
        _fetch("martj42/international_results/master/shootouts.csv",
               os.path.join(ddir, "shootouts.csv"))
    except Exception:  # noqa
        pass
    try:    # ESPN 实时完场顺带拉一把（martj42 滞后期兜底），失败不致命
        livemod.fetch_and_save()
    except Exception:  # noqa
        pass
    try:
        _refit_all()
        played = len(_sim().actual_results)
        return jsonify({"ok": True, "wc_played": played, "refit": True,
                        "teams": len(MODEL.teams), "source": src})
    except Exception as e:  # noqa
        return jsonify({"ok": False, "error": f"数据已下载但重训失败：{e}"}), 500


@app.route("/api/live", methods=["POST"])
def api_live():
    """轻量实时刷新：只查 ESPN 完场赛果（秒级，增量窗口），有新完场才重训+重建。
    供前端比赛日自动轮询；无变化时几乎零开销。"""
    if (blocked := _readonly_block()):
        return blocked
    try:
        changed, summary = livemod.fetch_and_save()
    except Exception as e:  # noqa
        return jsonify({"ok": False, "error": f"ESPN 实时源拉取失败：{e}"}), 502
    if changed:
        try:
            _refit_all()
        except Exception as e:  # noqa
            return jsonify({"ok": False, "error": f"实时数据已更新但重训失败：{e}"}), 500
    s = _sim()
    return jsonify({"ok": True, "changed": changed,
                    "wc_played": len(s.actual_results), "ko_played": len(s.actual_ko),
                    "live_total": summary.get("total", 0),
                    "updated": dt.datetime.now().strftime("%H:%M:%S")})


OVERRIDES_PATH = os.path.join(os.path.dirname(__file__), "data", "overrides.json")


def _load_overrides_file():
    """读出磁盘上保存的赛果录入/假设（list）；无文件或损坏则空。"""
    try:
        with open(OVERRIDES_PATH, encoding="utf-8") as f:
            ov = json.load(f).get("overrides", [])
        return ov if isinstance(ov, list) else []
    except (FileNotFoundError, ValueError, OSError):
        return []


def _save_overrides_file(ov):
    """原子写入（先写 .tmp 再 rename），避免并发/中断写坏文件。"""
    os.makedirs(os.path.dirname(OVERRIDES_PATH), exist_ok=True)
    tmp = OVERRIDES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"overrides": ov}, f, ensure_ascii=False)
    os.replace(tmp, OVERRIDES_PATH)


@app.route("/api/overrides", methods=["GET", "POST"])
def api_overrides():
    """赛果录入/假设的持久化：GET 取回已存盘列表，POST 覆盖保存。"""
    if request.method == "POST":
        if (blocked := _readonly_block()):
            return blocked
        ov = (request.get_json(silent=True) or {}).get("overrides", [])
        if not isinstance(ov, list):
            return jsonify({"ok": False, "error": "overrides must be a list"}), 400
        try:
            _save_overrides_file(ov)
        except OSError as e:
            return jsonify({"ok": False, "error": str(e)}), 500
        return jsonify({"ok": True, "count": len(ov)})
    return jsonify({"overrides": _load_overrides_file()})


def _parse_overrides(body):
    """把前端 overrides 列表拆成 小组赛(known) + 淘汰赛(ko_known，含胜者)。
    小组赛对阵顺序无关匹配（兼容旧存档里与官方赛程相反的主客序），反序翻转比分。"""
    sim = _sim()
    canon = {frozenset(p): p for ps in sim.fixtures.values() for p in ps}
    known, ko = {}, {}
    for o in (body or {}).get("overrides", []):
        h = teams_zh.to_en(o.get("home", "")) or o.get("home")
        a = teams_zh.to_en(o.get("away", "")) or o.get("away")
        try:
            gh, ga = int(o["gh"]), int(o["ga"])
        except (KeyError, ValueError, TypeError):
            continue
        cp = canon.get(frozenset((h, a)))
        if cp:
            known[cp] = (gh, ga) if cp == (h, a) else (ga, gh)
        else:  # 淘汰赛：平局需胜者（点球），缺省给主位
            if gh > ga: w = h
            elif ga > gh: w = a
            else: w = teams_zh.to_en(o.get("win", "")) or h
            ko[(h, a)] = (gh, ga, w)
    return known, ko


@app.route("/api/project", methods=["GET", "POST"])
def api_project():
    """官方赛制「最可能走势」投影；POST overrides 可做赛果假设/录入（小组赛+淘汰赛）。"""
    known, ko = ({}, {})
    if request.method == "POST":
        known, ko = _parse_overrides(request.get_json(silent=True) or {})
    p = _sim().project(known=known or None, ko_known=ko or None,
                       today=dt.date.today().isoformat())
    L = teams_zh.disp
    for g in p["groups"]:
        for s in g["standings"]:
            s["team"] = L(s["team"])
        for mt in g["matches"]:
            mt["home_en"], mt["away_en"] = mt["home"], mt["away"]
            mt["home"], mt["away"] = L(mt["home"]), L(mt["away"])
    for rd in p["rounds"]:
        for mt in rd["matches"]:
            mt["a_en"], mt["b_en"], mt["winner_en"] = mt["a"], mt["b"], mt["winner"]
            mt["a"], mt["b"], mt["winner"] = L(mt["a"]), L(mt["b"]), L(mt["winner"])
    p["champion"] = L(p["champion"])
    p["facts"] = len(_sim().actual_results)      # 已采用的小组赛真实赛果场数
    p["ko_facts"] = len(_sim().actual_ko)        # 已自动套入的淘汰赛真实赛果场数
    return jsonify(p)


@app.route("/api/verify")
def api_verify():
    """预测验证：已完赛场次的「预测 vs 实际」对比 + 命中统计。
    账本（data/predictions.json）开球前冻结、开球后只读；缺失场次用回溯模型补（不偷看结果）。"""
    s = _sim()
    try:
        verifymod.freeze(s)
        verifymod.backfill(s, DF)     # 首次遇到账本缺失的已完赛场次会训回溯模型（~10s/截止日）
    except Exception as e:  # noqa  账本写失败不阻塞只读评估
        print(f"[verify] freeze/backfill 失败：{e}")
    r = verifymod.evaluate(s, DF)
    for x in r["rows"]:
        x["home"], x["away"] = teams_zh.disp(x["home"]), teams_zh.disp(x["away"])
    return jsonify(r)


# —— 主页看板：正在比赛 / 即将开赛 / 已结束 三态聚合 ——
_STATUS_CACHE = {"t": 0.0, "data": []}


def _live_status(max_age: float = 30.0) -> list[dict]:
    """ESPN 实时状态快照（pre/in/post），进程内缓存 max_age 秒，避免每次看板加载都打 ESPN。"""
    now = time.time()
    if not _STATUS_CACHE["data"] or now - _STATUS_CACHE["t"] > max_age:
        try:
            _STATUS_CACHE["data"] = livemod.fetch_status()
            _STATUS_CACHE["t"] = now
        except Exception as e:  # noqa  实时源失败不致命：看板退化为只有账本数据
            print(f"[dashboard] ESPN 状态拉取失败：{e}")
    return _STATUS_CACHE["data"]


@app.route("/api/dashboard")
def api_dashboard():
    """主页看板数据：把全部场次按 正在比赛 / 即将开赛 / 已结束 三态聚合。
    已结束沿用预测验证（预测 vs 实际 + 分桶/冷门统计）；即将开赛带模型赛前预测；
    正在比赛叠加 ESPN 实时比分+分钟。实时状态只读、不进训练。"""
    s = _sim()
    try:                                  # 账本对齐：冻结未开球预测 + 回补已完赛
        verifymod.freeze(s)
        verifymod.backfill(s, DF)
    except Exception as e:  # noqa
        print(f"[dashboard] freeze/backfill 失败：{e}")
    ev = verifymod.evaluate(s, DF)        # 已结束：rows + summary（含 bins/冷门）
    for x in ev["rows"]:
        x["home"], x["away"] = teams_zh.disp(x["home"]), teams_zh.disp(x["away"])
    ev["rows"].sort(key=lambda x: (x.get("date") or "", x["home"]), reverse=True)  # 最新在前

    completed = verifymod._completed(s, DF)
    done_keys = {c["key"] for c in completed}
    done_pairs = {frozenset((c["home"], c["away"])) for c in completed}

    preds = verifymod.load_ledger()
    pred_by_pair = {frozenset((e["home"], e["away"])): e for e in preds.values()}
    status = _live_status()
    busy_pairs = {frozenset((r["home"], r["away"])) for r in status if r["state"] in ("in", "post")}

    def _probs(e):
        return {"p_home": e["p_home"], "p_draw": e["p_draw"], "p_away": e["p_away"],
                "pred_gh": e["gh"], "pred_ga": e["ga"],
                "pick": max((("H", e["p_home"]), ("D", e["p_draw"]), ("A", e["p_away"])),
                            key=lambda t: t[1])[0]}

    # 正在比赛（ESPN state=in）：叠加赛前预测
    live = []
    for r in status:
        if r["state"] != "in":
            continue
        e = pred_by_pair.get(frozenset((r["home"], r["away"])))
        row = {"home": teams_zh.disp(r["home"]), "away": teams_zh.disp(r["away"]),
               "home_en": r["home"], "away_en": r["away"],
               "gh": r["gh"], "ga": r["ga"], "clock": r.get("clock", ""),
               "detail": r.get("detail", ""), "stage": e["stage"] if e else "group"}
        if e:
            row.update(_probs(e))
        try:    # 实时胜平负：赛前 λ 按剩余时间缩放 + 当前比分卷积（只读引擎，不入账本/统计）
            minute = inplaymod.parse_minute(r.get("clock"), r.get("period"))
            row["wdl"] = inplaymod.win_draw_loss(MODEL, r["home"], r["away"],
                                                 r["gh"], r["ga"], minute, neutral=True)
            row["minute"] = minute
        except Exception as ex:  # noqa  in-play 失败不致命，live 卡退化为只显示比分
            print(f"[inplay] {r['home']} vs {r['away']} 计算失败：{ex}")
        live.append(row)

    # 即将开赛（账本里未完赛、未在进行/刚完场，按北京开球时间升序）
    now_bj = verifymod._now_bj()
    upcoming = []
    for k, e in preds.items():
        if k in done_keys or frozenset((e["home"], e["away"])) in busy_pairs:
            continue
        loc = None
        if e.get("stage") == "group":
            gv = schedule.group_venue(e["home"], e["away"])
            loc = gv.get("local") if gv else None
        row = {"stage": e.get("stage"), "home": teams_zh.disp(e["home"]),
               "away": teams_zh.disp(e["away"]), "home_en": e["home"], "away_en": e["away"],
               "kickoff": e.get("kickoff") or "",
               "date": e.get("date"), "city": e.get("city"), "local": loc,
               "retro": False}
        row.update(_probs(e))
        upcoming.append(row)
    upcoming.sort(key=lambda x: (x["kickoff"] or "9999-99-99 99:99"))

    post_pairs = {frozenset((r["home"], r["away"])) for r in status if r["state"] == "post"}
    return jsonify({
        "live": live, "upcoming": upcoming, "done": ev, "now": now_bj,
        "stale_finished": len(post_pairs - done_pairs),   # ESPN 已完场但本地未 ingest → 提示刷新
        "counts": {"live": len(live), "upcoming": len(upcoming), "done": len(completed)},
        "status_updated": (dt.datetime.fromtimestamp(_STATUS_CACHE["t"]).strftime("%H:%M:%S")
                           if _STATUS_CACHE["t"] else ""),
    })


# 启动即冻结所有未开球场次的赛前预测（开球后账本条目不可再写，保证可验证性）
try:
    verifymod.freeze(_sim())
except Exception as e:  # noqa
    print(f"[verify] 启动冻结失败（不影响主功能）：{e}")


if __name__ == "__main__":
    # 端口避开 5000：macOS 的 AirPlay 接收器(ControlCenter/AirTunes)占用 *:5000，
    # 浏览器开 localhost:5000 会被解析到 IPv6 ::1 命中 AirPlay 返回 403「未获授权」。
    print("\n  ➜  http://127.0.0.1:8000   （也可用 http://localhost:8000）\n")
    if not READONLY and ODDS_SNAP_MIN > 0:   # 比赛日定时快照盘口（仅在 app 运行期间）
        threading.Thread(target=_odds_scheduler, daemon=True).start()
        print(f"  ⏱ 盘口定时快照已开启：每 {ODDS_SNAP_MIN:.0f} 分钟自动抓一次 ESPN 盘口（积累 CLV 数据）\n")
    app.run(host="127.0.0.1", port=8000, debug=False)
