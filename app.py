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
from flask import Flask, jsonify, make_response, render_template, request, send_file

import clv as clvmod
import data as datamod
import espn_odds as oddsmod
import inplay as inplaymod
import live as livemod
import manager as managermod
import narrative as narrativemod
import lineups as lineupsmod
import market
import market_research
import schedule
import teams_zh
import verify as verifymod
import wc2026
import xuanxue as xuanxuemod
import xuanxue_board as xuanxueboardmod
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
# 重训写锁：Flask 默认 threaded=True，前端多处轮询 + 手点都可能并发命中 /api/live、/api/refresh，
# 而 _refit_all 对全局 MODEL/DF/_SIM 做非原子的"重训→写 pkl→清缓存→冻结"。无锁并发会写坏
# model.pkl、产生半构造 _SIM。所有重训走这把锁串行；抢不到的请求跳过本次重训（数据已落盘，下次刷新即生效）。
_REFIT_LOCK = threading.Lock()
# /api/live 的非原子 check-then-set 节流在多客户端并发下会各自打 ESPN/各自尝试重训。
# 这把锁让同一时刻只有一个 /api/live 真正去拉取，其余直接复用上次结果（只读旁路，不影响正确性）。
_LIVE_LOCK = threading.Lock()

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
    # 单页 HTML 内联了全部 JS/CSS。禁缓存：否则浏览器留旧版，改了前端（如括号布局）也不生效——
    # 用户反复看到"点实时比分后布局崩坏"正是旧缓存页在跑旧 layoutBracket。
    resp = make_response(render_template("index.html", readonly=READONLY))
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp


@app.route("/api/config")
def api_config():
    """前端启动配置：是否只读分享模式（据此隐藏写操作按钮）。"""
    return jsonify({"readonly": READONLY, "sponsor": os.path.exists(_SPONSOR_QR)})


@app.route("/sponsor-qr")
def sponsor_qr():
    """赞赏码图片（作者把自己的收款/赞赏码放到 data/sponsor.png 即生效）。
    纯自愿打赏入口，**不解锁任何功能、不构成购买预测服务**——缺图则 404，前端优雅降级。"""
    if os.path.exists(_SPONSOR_QR):
        return send_file(_SPONSOR_QR)
    return "", 404


_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_SPONSOR_QR = os.path.join(_BASE_DIR, "data", "sponsor.png")   # 作者赞赏码（可选，自愿打赏用）


def _git(*args):
    """跑一条 git 命令（cwd=项目根），成功返回 stdout(strip)，失败/异常返回 None。"""
    try:
        r = subprocess.run(["git", *args], capture_output=True, text=True,
                           cwd=_BASE_DIR, timeout=20)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:  # noqa  git 缺失/超时/网络问题
        return None


_VERSION_CACHE = {"t": 0.0, "data": None}
_VERSION_TTL = 15 * 60   # 仓库更新检查结果缓存 15min（git ls-remote 走网络，避免频繁请求）


@app.route("/api/version")
def api_version():
    """检测 GitHub 仓库是否有新版本：本地 HEAD vs 远程 main 的 commit。
    用 git ls-remote（git 协议）而非 GitHub API——避开匿名 API 60/h 限流（见 CLAUDE.md）。
    结果缓存 15min，?fresh=1 强制重查（手动「立即检查」用）。网络/git 失败时优雅降级 ok=False。"""
    now = time.time()
    if not request.args.get("fresh") and _VERSION_CACHE["data"] and \
            now - _VERSION_CACHE["t"] < _VERSION_TTL:
        return jsonify(_VERSION_CACHE["data"])
    local = _git("rev-parse", "HEAD")
    remote_url = _git("remote", "get-url", "origin") or ""
    web = remote_url.replace("git@github.com:", "https://github.com/")
    if web.endswith(".git"):
        web = web[:-4]
    _git("fetch", "origin", "main", "--quiet")   # 更新 origin/main 远程跟踪引用（只动 refs，不动工作区）
    remote = _git("rev-parse", "origin/main")
    # 落后数＝远程有、本地没有的提交数。只有 behind>0 才算「有新版本可更新」；
    # 本地领先远程（有未推送的本地提交）不算更新，避免误报。
    behind = _git("rev-list", "--count", "HEAD..origin/main") if remote else None
    out = {"checked_at": dt.datetime.now().strftime("%m-%d %H:%M"),
           "local": (local or "")[:7], "repo_url": web or None}
    if local and remote and behind is not None:
        n = int(behind)
        out.update(ok=True, remote=remote[:7], behind=n, update_available=(n > 0),
                   compare_url=(f"{web}/compare/{local[:7]}...{remote[:7]}" if web and n > 0 else None))
    else:
        out.update(ok=False, remote=None, behind=0, update_available=False)
    _VERSION_CACHE.update(t=now, data=out)
    return jsonify(out)


# —— 后台任务节流参数（集中定义；节流口径＝"距上次成功完成"，失败不占窗口，见各 worker）——
_CI_MIN_INTERVAL = 20 * 60      # 夺冠区间(bayes+champ_ci 约 90s)重训触发的最短间隔；定时/手动 force 无视
_ODDS_MIN_INTERVAL = 15 * 60    # ESPN 赔率快照重训触发的最短间隔；定时器/手动 snap force 无视
ODDS_SNAP_MIN = float(os.environ.get("ODDS_SNAP_MIN", "30"))  # 运行期定时快照间隔(分钟)，0=关闭

# 夺冠区间后台重算任务：bayes.py（导出后验）→ champ_ci.py（MC 区间），约 90s，子进程异步跑。
_CI_JOB = {"running": False, "updated": None, "error": None, "last": 0.0}


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
        _CI_JOB["last"] = time.time()   # 节流窗口从"成功完成"起算：失败不占窗口，可立即重试
        print(f"[champ_ci] 后台重算完成 {_CI_JOB['updated']}")
    except Exception as e:  # noqa
        _CI_JOB["error"] = str(e)
    finally:
        _CI_JOB["running"] = False


def regen_champ_ci_async(force=False):
    """触发后台重算（只读模式或已在跑则跳过）。新赛果重训后自动调用，实现区间自动更新。
    force=False 时受 _CI_MIN_INTERVAL 节流（避免比赛日逐场完赛都跑 90s 的 bayes）；手动重算传 force=True。"""
    if READONLY or _CI_JOB["running"]:
        return
    if not force and (time.time() - _CI_JOB["last"]) < _CI_MIN_INTERVAL:
        print("[champ_ci] 距上次重算 <20min，跳过（补充视图无需逐场更新；可手动触发）")
        return
    _CI_JOB["running"] = True
    _CI_JOB["error"] = None
    threading.Thread(target=_regen_ci_worker, daemon=True).start()
    print("[champ_ci] 已在后台启动夺冠区间重算（bayes→champ_ci，约 90s）")


# ESPN 赔率快照后台任务：espn_odds.py（~64 次 summary 调用，约数分钟），子进程异步跑。
_ODDS_JOB = {"running": False, "updated": None, "last": 0.0}


def _regen_odds_worker():
    try:
        r = subprocess.run([sys.executable, os.path.join(_BASE_DIR, "espn_odds.py")],
                           capture_output=True, text=True, cwd=_BASE_DIR, timeout=600)
        _ODDS_JOB["updated"] = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        _ODDS_JOB["last"] = time.time()   # 节流窗口从"成功完成"起算（与 champ_ci 同口径）
        _MARKET_CACHE.clear()      # 新快照落盘后失效市场缓存，下次 /api/market 用新盘口重建
        _MR_CACHE.clear()          # 市场研究（线移动）缓存同步失效
        print(f"[odds] 后台快照完成 {_ODDS_JOB['updated']}：{(r.stdout or '').strip().splitlines()[:1]}")
    except Exception as e:  # noqa
        print(f"[odds] 后台快照失败：{e}")
    finally:
        _ODDS_JOB["running"] = False


def regen_odds_async(force=False):
    """触发后台 ESPN 赔率快照（只读/已在跑则跳过）。刷新真实赛果后调用——随赛事积累开盘/闭盘线。
    force=False 时受 _ODDS_MIN_INTERVAL 节流（避免逐场完赛都抓数分钟盘口）；定时器/手动 snap 传 force=True。"""
    if READONLY or _ODDS_JOB["running"]:
        return
    if not force and (time.time() - _ODDS_JOB["last"]) < _ODDS_MIN_INTERVAL:
        return
    _ODDS_JOB["running"] = True
    threading.Thread(target=_regen_odds_worker, daemon=True).start()
    print("[odds] 已在后台启动 ESPN 赔率快照")


def _odds_scheduler():
    """守护线程：启动后 1 分钟先快照一次，之后每 ODDS_SNAP_MIN 分钟一次（只读模式不启用）。"""
    first = True
    while True:
        time.sleep(60 if first else ODDS_SNAP_MIN * 60)
        first = False
        try:
            regen_odds_async(force=True)   # 定时快照是既定节奏，不受重训节流限制
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
    regen_champ_ci_async(force=True)   # 手动触发：无视节流
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
        regen_odds_async(force=True)
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


_MR_CACHE: dict = {}


@app.route("/api/market_research")
def api_market_research():
    """市场研究（只读、纯分析）：开盘→闭盘线移动信息检验（闭盘是否更锐利 + 移动是否含信息，
    带 bootstrap/Wilson CI）。不训练模型、不碰 GLM、不涉下注。轻量缓存。"""
    if request.args.get("fresh") or not _MR_CACHE:
        try:
            r = market_research.build(df=DF)
        except Exception as e:  # noqa
            return jsonify({"line_movement": {"n": 0}, "error": f"市场研究计算失败：{e}"}), 500
        _MR_CACHE.clear()
        _MR_CACHE.update(r)
    return jsonify(_MR_CACHE)


@app.route("/api/teams")
def api_teams():
    # 仅 2026 世界杯 48 强；中文+国旗，按官方 A–L 组序展示，便于浏览
    teams = [t for g in wc2026.GROUPS.values() for t in g]
    return jsonify([teams_zh.disp(t) for t in teams])


def _exp_total(M) -> float:
    """比分矩阵 → 期望总进球（Σ(i+j)·P(i,j)），供解读文案氛围判断。"""
    M = np.asarray(M, dtype=float)
    n = M.shape[0]
    return float(sum((i + j) * M[i, j] for i in range(n) for j in range(n)))


@app.route("/api/predict")
def api_predict():
    home = request.args.get("home", "").strip()
    away = request.args.get("away", "").strip()
    neutral = request.args.get("neutral", "1") not in ("0", "false", "False")
    # 东道主队名（看板「正在比赛/即将开赛」的「看预测」会带上它）：与看板概率同口径——
    # 含东道主主场+环境修正。给了 host 就忽略 neutral，用 verify.pair_predict 同款朝向逻辑。
    host = request.args.get("host", "").strip() or None
    city = request.args.get("city", "").strip() or None
    try:
        # 市场让球盘按英文 canon 名查（地图键是英文）；拉取失败不致命。
        try:
            _mh = _market_handicap_one(MODEL.resolve(home), MODEL.resolve(away))
        except Exception:  # noqa
            _mh = None
        if host in (home, away):
            p = verifymod.pair_predict(MODEL, home, away, host=host, city=city)
            M = np.array(p["matrix"])
            flat = sorted(((i, j, float(M[i, j])) for i in range(M.shape[0])
                           for j in range(M.shape[1])), key=lambda t: -t[2])[:5]
            dh, da = teams_zh.disp(home), teams_zh.disp(away)
            hc = managermod.handicap_summary(M, p["p_home"], p["p_away"], dh, da, market=_mh)
            return jsonify({
                "home": dh, "away": da, "neutral": False,
                "host": teams_zh.disp(host),
                "xg_home": p["xg_home"], "xg_away": p["xg_away"],
                "p_home": p["p_home"], "p_draw": p["p_draw"], "p_away": p["p_away"],
                "top_scores": [{"h": i, "a": j, "p": pr} for (i, j, pr) in flat],
                "matrix": M.tolist(), "side": int(M.shape[0]),
                "mv_home": market.value(home), "mv_away": market.value(away),
                "handicap": hc,
                "narrative": narrativemod.match_narrative(dh, da, p["p_home"], p["p_draw"],
                                                          p["p_away"], hc, _exp_total(M)),
            })
        r = MODEL.predict(home, away, neutral=neutral)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400

    M = r["matrix"]
    side = M.shape[0]
    dh, da = teams_zh.disp(r["home"]), teams_zh.disp(r["away"])
    hc = managermod.handicap_summary(M, r["p_home"], r["p_away"], dh, da, market=_mh)
    return jsonify({
        "home": dh, "away": da, "neutral": neutral,
        "xg_home": round(r["xg_home"], 3), "xg_away": round(r["xg_away"], 3),
        "p_home": r["p_home"], "p_draw": r["p_draw"], "p_away": r["p_away"],
        "top_scores": [{"h": i, "a": j, "p": p} for (i, j), p in r["top_scores"]],
        "matrix": M.tolist(), "side": side,
        "mv_home": market.value(r["home"]), "mv_away": market.value(r["away"]),
        "handicap": hc,
        "narrative": narrativemod.match_narrative(dh, da, r["p_home"], r["p_draw"],
                                                  r["p_away"], hc, _exp_total(M)),
    })


@app.route("/api/manager")
def api_manager():
    """足球经理人深度报告：过程数据(近期/交锋/攻防) + DC 算法模型 + 全盘口结论。
    只读组装层，不训练、不碰 GLM。队名支持中文/国旗串。"""
    home = request.args.get("home", "").strip()
    away = request.args.get("away", "").strip()
    neutral = request.args.get("neutral", "1") not in ("0", "false", "False")
    # ?lineup=1：赛前 1h（或完赛后）拉真实首发做缺阵探测；拉不到则降级（available=False）。
    lineup = None
    if request.args.get("lineup") in ("1", "true", "True"):
        try:
            h_en = MODEL.resolve(home); a_en = MODEL.resolve(away)
            lineup = lineupsmod.match_availability(h_en, a_en)
        except Exception as e:  # noqa  拉取失败不让报告 500，降级到无首发
            lineup = {"available": False, "reason": f"fetch_failed:{e}"}
    # 动机/出线上下文（只读，从本届真实赛果推 clinch 状态）。任何意外都不挡报告。
    context = {"motiv_adj": request.args.get("motiv_adj") in ("1", "true", "True")}
    gd_table = group_h = group_a = None
    try:
        import standings
        sim = _sim()
        h_en = MODEL.resolve(home); a_en = MODEL.resolve(away)
        context["home_clinch"] = standings.clinch_status(sim, h_en)
        context["away_clinch"] = standings.clinch_status(sim, a_en)
        mh = _market_handicap_one(h_en, a_en)
        # 让球盘移动：从开盘→闭盘时间线取开盘线（强弱一致时），让报告显示盘口移动方向。
        if mh:
            try:
                tl = oddsmod.load_handicap_timeline().get(oddsmod._hc_key(h_en, a_en))
                if tl and tl.get("open_line") is not None and tl.get("fav_is_home") == mh.get("fav_is_home"):
                    mh = {**mh, "open_line": tl["open_line"]}
            except Exception:  # noqa
                pass
        context["market_handicap"] = mh
        gd_table = standings.tournament_gd_table(sim)
        group_h = standings.group_table(sim, h_en)
        group_a = standings.group_table(sim, a_en)
    except Exception:  # noqa  上下文层失败 → 退化为无动机层（纯模型让球）
        context = {"motiv_adj": context.get("motiv_adj", False)}

    try:
        r = managermod.build_report(MODEL, DF, home, away, neutral=neutral, elo=_ELO,
                                    lineup=lineup, context=context)
    except KeyError as e:
        return jsonify({"error": str(e)}), 400
    except Exception as e:  # noqa  组装层任何意外都不应 500 整页
        return jsonify({"error": f"报告生成失败：{e}"}), 500

    L = teams_zh.disp
    # 附上下文表（本地化队名）：全队净胜球榜 + 两队所在组实时排名。
    if gd_table:
        for row in gd_table:
            row["team_disp"] = L(row["team"])
    for gt in (group_h, group_a):
        if gt:
            for row in gt["rows"]:
                row["team_disp"] = L(row["team"])
    r["gd_table"] = gd_table
    # 同组两队（如摩洛哥 vs 海地）只展示一张组表，去重。
    seen = set(); ugt = []
    for gt in (group_h, group_a):
        if gt and gt["group"] not in seen:
            seen.add(gt["group"]); ugt.append(gt)
    r["group_tables"] = ugt
    # 动机块里的 clinch label/队名本地化
    mo = r.get("motivation")
    if mo:
        for w in mo.get("warnings", []):
            w["team_disp"] = L(w["team"])
    r["home_disp"], r["away_disp"] = L(r["home"]), L(r["away"])
    for side in ("home", "away"):
        for mt in r["form"][side]["matches"]:
            mt["opp"] = L(mt["opp"])
    for row in r["h2h"]["rows"]:
        row["home"], row["away"] = L(row["home"]), L(row["away"])
        if row.get("winner"):
            row["winner"] = L(row["winner"])
    # 比赛解读文案（球迷语言，合规守卫，置顶报告头）
    try:
        _csl = r["markets"]["handicap"].get("csl") or {}
        _hcn = {"csl_is_handicap": _csl.get("is_handicap"), "csl_line": _csl.get("line"),
                "jc_verdict": _csl.get("verdict")}
        r["narrative"] = narrativemod.match_narrative(
            r["home_disp"], r["away_disp"], r["p_home"], r["p_draw"], r["p_away"],
            _hcn, r["markets"].get("exp_total"))
    except Exception:  # noqa  解读失败不挡报告
        r["narrative"] = None
    return jsonify(r)


@app.route("/api/lineup_ledger")
def api_lineup_ledger():
    """首发增益记分卡：完赛场「纯 DC 基线 vs 首发确认版」的 RPS / 命中对比。
    独立旁路账本，绝不回写 verify 主验证账本、不碰 GLM。早期样本极小，前端须标注。"""
    try:
        import lineup_ledger
        days = int(request.args.get("days", "12"))
        sc = lineup_ledger.build_scorecard(MODEL, days_back=days)
        return jsonify(sc)
    except Exception as e:  # noqa
        return jsonify({"error": f"记分卡生成失败：{e}"}), 500


@app.route("/api/fixtures")
def api_fixtures():
    """近期未开赛对阵（对阵分析「明日对战看板」点击填表用）。纯赛程、不拉 live，秒回。"""
    now = verifymod._now_bj()
    # 已赛过滤只看【本届世界杯】结果，与看板 /api/dashboard 同口径。
    # 不能用「全历史交手过的队对」过滤——否则历史踢过友谊赛的对阵（如英格兰vs加纳）会被误删，
    # 曾导致本接口比看板少 15 场未来比赛。开球时间 ko<=now 已排除已开球场次，这里再排除本届已赛。
    wc_done = set(_sim().actual_results)
    fx = []
    for (h, a), ko in schedule.GROUP.items():
        if not ko or ko <= now or (h, a) in wc_done:
            continue
        gv = schedule.group_venue(h, a)
        host = schedule.group_match_host(h, a)
        fx.append({"home_en": h, "away_en": a,
                   "home": teams_zh.disp(h), "away": teams_zh.disp(a),
                   "kickoff": ko, "date": ko[:10],
                   "city": gv.get("city") if gv else None,
                   "local": gv.get("local") if gv else None,
                   "host": teams_zh.disp(host) if host else None})
    fx.sort(key=lambda x: x["kickoff"])
    return jsonify({"fixtures": fx, "now": now})


@app.route("/api/xuanxue")
def api_xuanxue():
    """玄学占卜对照（趣味/文化彩蛋）：7 套传统术数各出一个比分 + 玄学共识。
    确定性、可复现，与 DC 模型比分并列对照。⚠️ 无科学依据，禁用于赌博/决策。
    队名支持中文/国旗串/英文；dt 为可选比赛时间（YYYY-MM-DD HH:MM，缺省用揭幕日）。"""
    home = request.args.get("home", "").strip()
    away = request.args.get("away", "").strip()
    dt = request.args.get("dt", "").strip() or None
    if not home or not away:
        return jsonify({"error": "需要 home 与 away 两支球队"}), 400
    try:
        r = xuanxuemod.divine(home, away, dt)
    except Exception as e:  # noqa  彩蛋层任何意外都不应 500 整页
        return jsonify({"error": f"占卜失败：{e}"}), 500
    # 本地化展示名（引擎内部仍用原始串做稳定种子，不影响结果）
    r["home_disp"], r["away_disp"] = teams_zh.disp(home), teams_zh.disp(away)
    return jsonify(r)


@app.route("/api/xuanxue/board")
def api_xuanxue_board():
    """玄学占卜擂台：自动抓近三天即将开赛场次冻结 7 法占卜，已完赛自动结算，
    逐体系累计命中率排行。账本 data/xuanxue_ledger.json 赛前冻结、赛后只读。
    ⚠️ 趣味/文化实验，术数无科学预测力。"""
    s = _sim()
    try:
        r = xuanxueboardmod.build_board(s, DF)
    except Exception as e:  # noqa  擂台层任何意外都不应 500 整页
        return jsonify({"error": f"擂台生成失败：{e}"}), 500
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


def _localize_bracket(d, keep_en=False):
    """把一届投影/模拟结果的队名就地中文化（小组排名/小组赛/淘汰赛/冠军）。
    keep_en=True 时顺带保留各对阵的英文原名（*_en），供前端北京/当地切换或深链回填用。
    api_bracket 与 api_project 共用，避免两处本地化逻辑漂移。"""
    L = teams_zh.disp
    for g in d["groups"]:
        for s in g["standings"]:
            s["team"] = L(s["team"])
        for mt in g["matches"]:
            if keep_en:
                mt["home_en"], mt["away_en"] = mt["home"], mt["away"]
            mt["home"], mt["away"] = L(mt["home"]), L(mt["away"])
    for rd in d["rounds"]:
        for mt in rd["matches"]:
            if keep_en:
                mt["a_en"], mt["b_en"], mt["winner_en"] = mt["a"], mt["b"], mt["winner"]
            mt["a"], mt["b"], mt["winner"] = L(mt["a"]), L(mt["b"]), L(mt["winner"])
    d["champion"] = L(d["champion"])
    return d


@app.route("/api/bracket")
def api_bracket():
    """模拟完整一届，返回小组排名 + 晋级树 + 冠军（队名本地化）。"""
    seed = request.args.get("seed")
    seed = int(seed) if seed not in (None, "") else None
    d = _localize_bracket(_sim().simulate_once(seed=seed))
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
    /api/refresh 与 /api/live 共用。**全程持 _REFIT_LOCK 串行**：抢不到锁说明已有重训在跑，
    直接跳过本次（数据已落盘，正在跑的那次会用上）。model.pkl 用原子写避免并发写坏。"""
    global MODEL, DF, _SIM
    if not _REFIT_LOCK.acquire(blocking=False):
        print("[refit] 已有重训在进行，跳过本次（数据已落盘）")
        return
    try:
        DF = datamod.load_raw()
        MODEL = DixonColesModel(half_life_days=HALF_LIFE).fit(DF, verbose=False)
        tmp = CACHE_PATH + ".tmp"          # 原子写：先写 .tmp 再 replace，并发也不会写坏 pkl
        with open(tmp, "wb") as f:
            pickle.dump(MODEL, f)
        os.replace(tmp, CACHE_PATH)
        MODEL.set_availability()   # 重训后重装可用性上下文层（pickle 不含它）
        _SIM = None
        _CHAMP_CACHE.clear()
        _RAW_CHAMP.clear()
        _compute_elo()             # 解读层 Elo 随新数据重算
        import insights; insights._AVAIL_ITEMS = None
    finally:
        _REFIT_LOCK.release()      # A6：全局 MODEL/DF/_SIM 与 pkl 已原子切换完毕即释放，缩短锁占用
    try:                           # 账本冻结挪到锁外：verify 账本自身原子写、与全局 MODEL 解耦
        verifymod.freeze(_sim())
    except Exception as e:  # noqa
        print(f"[verify] 重训后冻结预测失败（不影响主功能）：{e}")
    regen_champ_ci_async()     # 新赛果重训后，后台异步重算夺冠区间（bayes→champ_ci，不阻塞）
    # 注：A2——ESPN 赔率快照不再随重训联动（与"市场 CLV 为外部审计层、不随训练联动"红线一致），
    # 改由 _odds_scheduler（30min）+ 手动 snap + /api/market?fresh 负责，避免分钟级子进程与定时快照口径重叠。


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


_LIVE_CACHE = {"t": 0.0, "summary": {}}
_LIVE_TTL = 15.0   # 完赛数据秒级不变：窗口内复用上次结果，挡住多客户端/多定时器的并发拉取与重训


@app.route("/api/live", methods=["POST"])
def api_live():
    """轻量实时刷新：只查 ESPN 完场赛果（秒级，增量窗口），有新完场才重训+重建。
    供前端比赛日自动轮询；无变化时几乎零开销。15s 内的重复调用直接复用上次结果（节流）。"""
    if (blocked := _readonly_block()):
        return blocked
    # A4：原子节流。并发多客户端同时 POST 时，只有抢到锁的那个去拉 ESPN/重训，其余直接复用上次结果，
    # 避免各自打 ESPN、各自尝试重训（check-then-set 竞态）。锁只护"判窗口→拉取→回填"这一段。
    if not _LIVE_LOCK.acquire(blocking=False):
        summary = _LIVE_CACHE["summary"]
        s = _sim()
        return jsonify({"ok": True, "changed": False, "coalesced": True,
                        "wc_played": len(s.actual_results), "ko_played": len(s.actual_ko),
                        "live_total": summary.get("total", 0),
                        "updated": dt.datetime.now().strftime("%H:%M:%S")})
    try:
        now = time.time()
        if now - _LIVE_CACHE["t"] < _LIVE_TTL:   # 节流窗口内：复用上次结果，视为无变化（真有变化上次已 ingest+重训）
            changed, summary = False, _LIVE_CACHE["summary"]
        else:
            try:
                changed, summary = livemod.fetch_and_save()
            except Exception as e:  # noqa
                return jsonify({"ok": False, "error": f"ESPN 实时源拉取失败：{e}"}), 502
            _LIVE_CACHE.update(t=now, summary=summary)
            if changed:
                try:
                    _refit_all()
                except Exception as e:  # noqa
                    return jsonify({"ok": False, "error": f"实时数据已更新但重训失败：{e}"}), 500
    finally:
        _LIVE_LOCK.release()
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
                       today=verifymod._now_bj()[:10])  # 北京今天，与赛程/看板北京口径一致（勿用服务器本地日）
    _localize_bracket(p, keep_en=True)           # 投影需保留英文原名供前端北京/当地切换与深链回填
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


@app.route("/api/handicap_ledger")
def api_handicap_ledger():
    """让球预测命中率擂台：从 verify 已冻结的赛前矩阵推导让球预测，用真实赛果结算命中率+校准。
    纯只读分析层，复用 verify 账本，绝不回写、不碰 GLM。"""
    s = _sim()
    try:
        verifymod.freeze(s)        # 轻量冻结未开球场次（backfill 由 verify tab/调度器维护，此处不重复训练）
    except Exception as e:  # noqa
        print(f"[handicap] freeze 失败：{e}")
    _hc_lines_backfill_async()     # 后台增量补市场闭盘让球线（不阻塞本次请求；build 读已存的）
    try:
        import handicap_ledger
        b = handicap_ledger.build(s, DF)
    except Exception as e:  # noqa  分析层任何意外都不应 500
        return jsonify({"error": f"让球擂台生成失败：{e}"}), 500
    for x in b["rows"]:
        x["fav"], x["dog"] = teams_zh.disp(x["fav"]), teams_zh.disp(x["dog"])
    return jsonify(b)


# —— 市场让球盘（ESPN DraftKings spread）：**按需单场**抓取（每场 1 summary），后台跑、请求只读缓存 ——
# 用户看哪场只抓哪场，永不阻塞请求；首次拿到 None，后台 ~3s 抓完，下次请求即带市场盘。缓存 10min。
_HC_LINES_LOCK = threading.Lock()
_HC_LINES_LAST = {"t": 0.0}


def _hc_lines_worker():
    try:
        added = oddsmod.backfill_handicap_finished(limit=24)   # 每次最多补 24 场，多次后台补全
        if added:
            print(f"[handicap] 市场闭盘让球线后台补 {added} 场")
    except Exception as e:  # noqa
        print(f"[handicap] 市场闭盘让球线回补失败：{e}")
    finally:
        if _HC_LINES_LOCK.locked():
            _HC_LINES_LOCK.release()


def _hc_lines_backfill_async(min_gap: float = 120.0):
    """后台增量回补已完赛市场闭盘让球线（每场一次 summary，故限量 + 节流，永不阻塞请求）。"""
    if time.time() - _HC_LINES_LAST["t"] < min_gap:
        return
    if _HC_LINES_LOCK.acquire(blocking=False):
        _HC_LINES_LAST["t"] = time.time()
        threading.Thread(target=_hc_lines_worker, daemon=True).start()


_HC_MKT = {}                      # pairkey(tuple sorted) -> {"t": ts, "row": row|None}
_HC_MKT_INFLIGHT = set()
_HC_MKT_LOCK = threading.Lock()


def _hc_fetch_pair(h_en, a_en, key):
    try:
        row = oddsmod.fetch_handicap_pair(h_en, a_en)
        with _HC_MKT_LOCK:
            _HC_MKT[key] = {"t": time.time(), "row": row}
    except Exception as e:  # noqa
        print(f"[handicap] 单场市场让球盘抓取失败 {key}：{e}")
    finally:
        with _HC_MKT_LOCK:
            _HC_MKT_INFLIGHT.discard(key)


def _market_handicap_one(h_en: str, a_en: str, max_age: float = 600.0):
    """返回该对阵当前缓存的市场让球盘行（顺序无关）；缺失/过期则**后台**单场抓取，不阻塞本次请求。"""
    key = tuple(sorted((h_en, a_en)))
    ent = _HC_MKT.get(key)
    if not ent or time.time() - ent["t"] > max_age:
        with _HC_MKT_LOCK:
            if key not in _HC_MKT_INFLIGHT:
                _HC_MKT_INFLIGHT.add(key)
                threading.Thread(target=_hc_fetch_pair, args=(h_en, a_en, key), daemon=True).start()
    return ent["row"] if ent else None


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
               "detail": r.get("detail", ""), "stage": e["stage"] if e else "group",
               "host": e.get("host") if e else None, "city": e.get("city") if e else None}
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
        ko = e.get("kickoff") or ""
        row = {"stage": e.get("stage"), "home": teams_zh.disp(e["home"]),
               "away": teams_zh.disp(e["away"]), "home_en": e["home"], "away_en": e["away"],
               "kickoff": ko,
               # 看板按日分组的日期要与展示的【北京】开球时间同一时区口径（bj_date 统一口径）。
               "date": verifymod.bj_date(ko, e.get("date")),
               "city": e.get("city"), "host": e.get("host"), "local": loc, "retro": False}
        row.update(_probs(e))
        # 紧凑让球（公平盘 + 竞彩倾向，看板速览用；不带市场盘，避免每行触发 ESPN 抓取）
        if e.get("matrix"):
            try:
                row["handicap"] = managermod.handicap_summary(
                    e["matrix"], e["p_home"], e["p_away"],
                    teams_zh.disp(e["home"]), teams_zh.disp(e["away"]))
            except Exception:  # noqa  让球摘要失败不影响看板
                pass
        # 球迷解读（文案层，只读、合规；compact 省尾注，前端解读区统一展示一次免责）
        try:
            row["narrative"] = narrativemod.match_narrative(
                row["home"], row["away"], e["p_home"], e["p_draw"], e["p_away"],
                row.get("handicap"),
                _exp_total(e["matrix"]) if e.get("matrix") else None, compact=True)
        except Exception:  # noqa  解读失败不影响看板
            row["narrative"] = None
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
