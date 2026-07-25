#!/usr/bin/env python3
"""俱乐部（五大联赛）赛前冻结 + 赛后结算链路（P0-A，docs/UPGRADE_REQUIREMENTS_2026-07-25.md 第 3/10 节）。

为什么不复用 verify.freeze()：那个函数 import schedule、走 TournamentSimulator 与世界杯小组/
淘汰赛结构，是世界杯专属赛制冻结器。联赛没有小组与括号，赛程来自 football-data fixtures.csv，
模型是每联赛独立的 club_<code>（hl=365）。本模块只借用 verify 的账本读写（公开、原子），
不碰它的世界杯逻辑，也不使用它的私有 _LEDGER_LOCK。

两个硬约束（本模块存在的理由）：
① **新赛季 0 场已赛也必须能冻结**——football-data 的当季 CSV 通常开赛后才出现，
   8-08 首轮前 E0_2627.csv 不存在。因此赛程（fixtures.csv）与训练帧（历史季 CSV）
   彻底解耦：模型允许全部由历史赛季训练，冻结不得等待当季 CSV。
② **只冻结不结算等于半截账本**——settle_event() 与 freeze_event() 同阶段交付；
   结算只写赛后字段，赛前字段（概率/xG/矩阵/frozen_at…）逐字段不可变。

时间口径：fixtures.csv 的 Date+Time 是**英国当地时间**（源站为英国站点），本模块统一
Europe/London → UTC → 北京时间。上线某联赛自动冻结前必须与该联赛 ESPN code 交叉核对
至少 3 场开球时间（差值 ≤5 分钟），核对脚本见 scripts/club_freeze.py --crosscheck。
"""
from __future__ import annotations

import datetime as dt
import os
import threading
from zoneinfo import ZoneInfo

import pandas as pd

import clubdata
import clubpredict
import events as eventsmod
import verify

# fixtures.csv 的源时区（football-data.co.uk 为英国站点，Time 列是英国当地时间）。
# 夏令时切换由 ZoneInfo 处理——8 月的英超是 BST(UTC+1)，1 月是 GMT(UTC+0)，
# 直接把 naive 时间当 UTC 会在 8 月整整偏 1 小时。
SOURCE_TZ = ZoneInfo("Europe/London")
UTC = ZoneInfo("UTC")
BJ = ZoneInfo("Asia/Shanghai")

# 开球时间口径核对台账：{联赛码: {verified_at, worst_diff_minutes, n}}。
# 账本一旦按错误时区冻结就永远改不回来（赛前预测不可重写），所以**定时调度**只对
# 已核对的联赛自动冻结；未核对的联赛返回 blocked，由运维先跑
# `scripts/club_freeze.py --crosscheck <event>` 通过后自动登记。
# 手工调用 freeze_event 不受此闸限制（诊断与测试用），闸在批量调度层。
TZ_VERIFIED_PATH = os.path.join(os.path.dirname(__file__), "data", "club",
                                "kickoff_tz_verified.json")


def tz_verified(code: str) -> bool:
    import json
    try:
        with open(TZ_VERIFIED_PATH, encoding="utf-8") as f:
            return code in json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        return False


def record_tz_verified(code: str, worst_diff_minutes: float, n: int) -> None:
    """交叉核对通过后登记（由 scripts/club_freeze.py --crosscheck 调用）。"""
    import json
    os.makedirs(os.path.dirname(TZ_VERIFIED_PATH), exist_ok=True)
    try:
        with open(TZ_VERIFIED_PATH, encoding="utf-8") as f:
            d = json.load(f)
    except (FileNotFoundError, ValueError, OSError):
        d = {}
    d[code] = {"verified_at": dt.datetime.now(tz=BJ).strftime("%Y-%m-%d %H:%M:%S"),
               "worst_diff_minutes": worst_diff_minutes, "n": n,
               "source_tz": str(SOURCE_TZ)}
    with open(TZ_VERIFIED_PATH, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


# 账本「读→改→写」串行锁：freeze/settle 都是 load→改→save，多进程调度 + app 并发下
# 不串行化整个事务会丢更新。与 verify 的世界杯账本锁彼此独立（不同文件、不同事务）。
_LOCK = threading.RLock()

# 结算口径：联赛常规时间 90 分钟（含补时），无加时点球。写死是为了防止以后欧冠复用时串口径
# ——欧战 KO 的 ESPN 比分是含加时终局口径（docs/data-sources.md 第八节），
# 若要复用本函数必须先过独立的 score-basis adapter 授权。
SCORE_BASIS = "90min_regulation"


# ---------- 内部工具 ----------
def _event(event_key: str) -> dict:
    """取规范化后的注册表条目（别名在此归一），并校验它是俱乐部宇宙。"""
    key = eventsmod.resolve(event_key)
    if key not in eventsmod.EVENTS:
        raise KeyError(f"unknown event: {event_key}")
    ev = dict(eventsmod.EVENTS[key], key=key)
    if not str(ev.get("universe", "")).startswith("club_"):
        raise ValueError(f"{key} 不是俱乐部赛事（universe={ev.get('universe')}）；"
                         "国家队赛事走各自的冻结器，绝不共用账本")
    return ev


def _mkey(home: str, away: str) -> str:
    """账本内的比赛唯一身份 = 赛季内「主队|客队」。

    刻意**不含日期**：联赛改期极常见，把日期编进 key 会让同一场比赛在改期后生成
    第二条记录（账本里凭空多一场、对账全错）。同一赛季内主客有序对唯一（双循环
    各主场一次），所以这是安全的身份；跨赛季由账本按赛事隔离天然区分。
    """
    return f"{home}|{away}"


def _kickoff(ts: pd.Timestamp) -> tuple[str, str]:
    """fixtures 的 naive 英国时间 → (UTC ISO, 北京时间 'YYYY-MM-DD HH:MM')。"""
    local = ts.to_pydatetime().replace(tzinfo=SOURCE_TZ)
    return (local.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            local.astimezone(BJ).strftime("%Y-%m-%d %H:%M"))


def _now(now_utc: dt.datetime | None = None) -> dt.datetime:
    n = now_utc or dt.datetime.now(tz=UTC)
    return n if n.tzinfo else n.replace(tzinfo=UTC)


def _started(entry: dict, now: dt.datetime) -> bool:
    """该条目当前有效开球时间是否已到（到点后赛前字段永久冻结）。"""
    try:
        return dt.datetime.strptime(entry["kickoff_utc"], "%Y-%m-%dT%H:%M:%SZ") \
            .replace(tzinfo=UTC) <= now
    except (KeyError, ValueError):
        return False


def ledger_path(event_key: str) -> str:
    """账本路径（按赛事隔离，文件名来自注册表；别名归一后再解析）。"""
    return verify.ledger_path(eventsmod.resolve(event_key))


def _window(ev: dict) -> tuple[pd.Timestamp, pd.Timestamp]:
    a, b = ev["window"]
    return pd.Timestamp(a), pd.Timestamp(b) + pd.Timedelta(days=1)


# ---------- 赛前冻结 ----------
def freeze_event(event_key: str, fixtures: pd.DataFrame | None = None,
                 now_utc: dt.datetime | None = None, ledger: str | None = None,
                 verbose: bool = False) -> dict:
    """把该赛事所有【尚未开球】的已知赛程写入账本（开球后永不触碰）。

    fixtures=None 时从 clubdata.load_fixtures(code) 取（只含未来一轮左右，故本函数
    需被定时调度反复调用）。返回结构化统计；无赛程返回 no_fixtures（赛程层空态，
    **不是** no_model——前者是「比赛还不存在」，后者是「模型覆盖不到这两支队」）。
    """
    ev = _event(event_key)
    key, code = ev["key"], ev["data"]
    path = ledger or ledger_path(key)
    now = _now(now_utc)

    if fixtures is None:
        try:
            fixtures = clubdata.load_fixtures(code)
        except Exception as e:  # noqa  赛程源不可用不等于赛程未发布，如实分开报
            return {"status": "error", "event": key, "reason_code": "fixtures_source_unavailable",
                    "error": str(e)}

    lo, hi = _window(ev)
    fx = fixtures
    if len(fx):
        fx = fx[(fx["date"] >= lo) & (fx["date"] < hi)]      # 赛季窗过滤：防跨季误入账本
    if not len(fx):
        return {"status": "no_fixtures", "reason_code": "schedule_unpublished", "event": key,
                "fixtures_seen": 0, "poll_after_seconds": 0}

    m = clubpredict.get_club_model(code, verbose=verbose)
    data_through = str(clubdata.load(code, seasons=clubpredict.SEASONS).date.max().date())

    with _LOCK:
        preds = verify.load_ledger(path)
        n_new = n_upd = n_started = n_nomodel = 0
        for r in fx.itertuples():
            mk = _mkey(r.home_team, r.away_team)
            ko_utc, ko_bj = _kickoff(r.date)
            old = preds.get(mk)
            if old and _started(old, now):
                n_started += 1                              # 已开球：赛前字段永久冻结
                continue
            if dt.datetime.strptime(ko_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) <= now:
                n_started += 1                              # 首见即已开球：不补冻结（那是事后诸葛）
                continue
            try:
                p = m.predict(r.home_team, r.away_team, neutral=False)
            except KeyError:
                n_nomodel += 1                              # 池外队（升班马等）：不写任何数字
                continue
            entry = {
                "event": key, "stage": "league", "home": r.home_team, "away": r.away_team,
                "kickoff_utc": ko_utc, "kickoff_bj": ko_bj, "date": ko_bj[:10],
                "source": "football-data", "model_universe": ev["universe"],
                "model_half_life": clubpredict.HL_CLUB, "data_through": data_through,
                "score_basis": SCORE_BASIS, "retro": False,
                "frozen_at": now.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S"),
                # 概率不做 5 位截断：验收要求三向和 = 1 ± 1e-8，round(…,5) 会带来 1e-5
                # 量级的和误差（世界杯账本沿用旧的 5 位口径，两者互不影响）。
                "p_home": float(p["p_home"]), "p_draw": float(p["p_draw"]),
                "p_away": float(p["p_away"]),
                "xg_home": round(float(p["xg_home"]), 3), "xg_away": round(float(p["xg_away"]), 3),
                "settlement_status": "unsettled",
            }
            if old:
                # 改期：开球前允许更新开球时间并留审计；概率不重算——赛前预测的价值
                # 在于「当时的判断」，跟着数据滚动重算会把冻结账本变成事后账本。
                if old.get("kickoff_utc") != ko_utc:
                    keep = {k: old[k] for k in old if k not in ("kickoff_utc", "kickoff_bj", "date")}
                    keep["rescheduled_from"] = old.get("kickoff_utc")
                    keep["rescheduled_at"] = entry["frozen_at"]
                    keep.update(kickoff_utc=ko_utc, kickoff_bj=ko_bj, date=ko_bj[:10])
                    preds[mk] = keep
                    n_upd += 1
                continue                                     # 未改期：已冻结即不动（幂等）
            preds[mk] = entry
            n_new += 1
        if n_new or n_upd:
            verify.save_ledger(preds, path)

    return {"status": "ok", "event": key, "fixtures_seen": int(len(fx)),
            "frozen_new": n_new, "updated_prekickoff": n_upd,
            "skipped_no_model": n_nomodel, "skipped_started": n_started, "ledger": path}


# ---------- 赛后结算 ----------
def _outcome(h: int, a: int) -> str:
    return "H" if h > a else ("A" if a > h else "D")


def settle_event(event_key: str, results: pd.DataFrame | None = None,
                 now_utc: dt.datetime | None = None, ledger: str | None = None) -> dict:
    """用当季真实赛果结算已冻结条目：只写赛后字段，赛前字段逐字段不可变。

    赛果源必须是**当季** football-data CSV 的完赛行（比分完整）；缺赛果的条目保持
    unsettled 并计数，绝不删除、不写 0:0、不用 ESPN 临时比分顶替、不靠当前时间推断已完赛。
    """
    ev = _event(event_key)
    key, code = ev["key"], ev["data"]
    path = ledger or ledger_path(key)
    now = _now(now_utc)

    if results is None:
        try:
            results = clubdata.load(code, seasons=clubpredict.SEASONS)
        except Exception as e:  # noqa
            return {"status": "error", "event": key, "reason_code": "results_source_unavailable",
                    "error": str(e)}

    lo, hi = _window(ev)
    res = results
    if len(res):
        # 赛季窗限定：近 7 季里同一主客对阵会出现 7 次，不限定必然张冠李戴
        res = res[(res["date"] >= lo) & (res["date"] < hi)]
        res = res.dropna(subset=["home_score", "away_score"])
    by_pair = {_mkey(r.home_team, r.away_team): r for r in res.itertuples()} if len(res) else {}

    with _LOCK:
        preds = verify.load_ledger(path)
        n_frozen = len(preds)
        n_new = n_same = n_unsettled = n_rev = 0
        dirty = False
        for mk, e in preds.items():
            r = by_pair.get(mk)
            if r is None:
                if e.get("settlement_status") != "settled":
                    e["settlement_status"] = "unsettled"
                    n_unsettled += 1
                continue
            hs, as_ = int(r.home_score), int(r.away_score)
            act = _outcome(hs, as_)
            if e.get("settlement_status") == "settled":
                if (e.get("home_score_90"), e.get("away_score_90")) == (hs, as_):
                    n_same += 1                              # 幂等：同源同比分不动 settled_at
                    continue
                e["result_revised_from"] = {"home_score_90": e.get("home_score_90"),
                                            "away_score_90": e.get("away_score_90"),
                                            "actual": e.get("actual")}
                e["result_revised_at"] = now.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S")
                n_rev += 1
            else:
                n_new += 1
            probs = {"H": e.get("p_home"), "D": e.get("p_draw"), "A": e.get("p_away")}
            e.update(settlement_status="settled", home_score_90=hs, away_score_90=as_,
                     actual=act, score_basis=e.get("score_basis", SCORE_BASIS),
                     outcome_hit=bool(probs[act] is not None
                                      and probs[act] == max(v for v in probs.values() if v is not None)),
                     result_source="football-data", result_date=str(pd.Timestamp(r.date).date()),
                     settled_at=now.astimezone(BJ).strftime("%Y-%m-%d %H:%M:%S"))
            dirty = True
        if dirty:
            verify.save_ledger(preds, path)

    out = {"status": "ok", "event": key, "frozen_entries": n_frozen, "settled_new": n_new,
           "already_settled": n_same, "unsettled": n_unsettled, "result_corrections": n_rev,
           "ledger": path}
    if not len(res):
        out["reason"] = "current_season_results_unavailable"
    return out


# ---------- 批量调度 ----------
def active_club_events(today: dt.date | None = None) -> list[str]:
    """需要冻结/结算的俱乐部赛事：universe=club_* 且状态 soon/live。

    刻意从注册表推导而非维护 key 手工列表——五大联赛 8-08~8-22 陆续开赛，
    手工列表必然漏。P0-B 的 capability 契约落地后，这里再加 verification=True 收口。
    """
    out = []
    for k in eventsmod.EVENTS:
        ev = eventsmod.EVENTS[k]
        if not str(ev.get("universe", "")).startswith("club_"):
            continue
        # FEEDER 是 {顶级联赛码: feeder 码}，要排除的是**值**（E1/SP2/…）：
        # feeder 只作赛季模拟的升班马评级来源，从不出预测、更不该进冻结调度。
        if ev["data"] in set(getattr(clubdata, "FEEDER", {}).values()):
            continue
        if eventsmod.status(k, today) in ("soon", "live"):
            out.append(k)
    return out


def run_all(freeze: bool = True, settle: bool = True, today: dt.date | None = None,
            now_utc: dt.datetime | None = None) -> dict:
    """批量执行：单赛事失败被隔离，不拖垮其他联赛；有硬失败则 hard_failures>0。"""
    res: dict[str, dict] = {}
    hard = 0
    for k in active_club_events(today):
        row: dict = {}
        code = eventsmod.EVENTS[k]["data"]
        for name, fn in (("freeze", freeze_event if freeze else None),
                         ("settle", settle_event if settle else None)):
            if fn is None:
                continue
            if name == "freeze" and not tz_verified(code):
                # 未核对时区口径 → 不自动冻结（blocked 不是错误：赛程未发布时本就无从核对）
                row["freeze"] = {"status": "blocked", "event": k,
                                 "reason_code": "kickoff_tz_unverified",
                                 "hint": f"先跑 scripts/club_freeze.py --crosscheck {k}"}
                continue
            try:
                r = fn(k, now_utc=now_utc)
            except Exception as e:  # noqa  单赛事异常隔离（映射/模型/账本问题不应连坐）
                r = {"status": "error", "event": k, "error": f"{type(e).__name__}: {e}"}
            row[name] = r
            if r.get("status") == "error":
                hard += 1
        res[k] = row
    return {"status": "ok" if not hard else "partial", "events": res, "hard_failures": hard}
