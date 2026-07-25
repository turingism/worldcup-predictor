#!/usr/bin/env python3
"""俱乐部赛前冻结 / 赛后结算的运维入口（P0-A，需求见 docs/UPGRADE_REQUIREMENTS_2026-07-25.md）。

用法
----
  # 批量（默认）：注册表里所有 universe=club_* 且 soon/live 的赛事，各自冻结+结算
  /opt/anaconda3/bin/python3 scripts/club_freeze.py

  # 单赛事诊断
  /opt/anaconda3/bin/python3 scripts/club_freeze.py --event epl2627

  # 只冻结 / 只结算
  /opt/anaconda3/bin/python3 scripts/club_freeze.py --no-settle
  /opt/anaconda3/bin/python3 scripts/club_freeze.py --no-freeze

  # 上线前的开球时间口径交叉核对（对该联赛 ESPN code 取 N 场比对，差值须 ≤5 分钟）
  /opt/anaconda3/bin/python3 scripts/club_freeze.py --crosscheck epl2627 --json out.json

退出码：0=无硬失败；1=存在硬失败（供 launchd/cron 告警）。单赛事 no_fixtures 属正常
（休赛期/赛程未发布），不算失败，也不拖垮其他联赛。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import clubdata          # noqa: E402
import clubverify        # noqa: E402
import events as eventsmod   # noqa: E402

TOL_MIN = 5              # 开球时间交叉核对容差（分钟），需求 §3.2 写死


def crosscheck(event_key: str, n: int = 3) -> dict:
    """把 fixtures.csv 解析出的开球时间与 ESPN 同联赛赛程比对，验证源时区假设。

    football-data 的 Time 列没有时区标注，我们按 Europe/London 解释（见 clubverify.SOURCE_TZ）。
    这个假设错了会整体偏 1 小时（夏令时），而账本一旦按错时间冻结就再也改不回来——
    所以任一联赛启用自动冻结前必须先跑通这一步。
    """
    import live
    ev = dict(eventsmod.EVENTS[eventsmod.resolve(event_key)])
    code, espn = ev["data"], ev["espn"]
    fx = clubdata.load_fixtures(code)
    lo, hi = clubverify._window(ev)
    fx = fx[(fx["date"] >= lo) & (fx["date"] < hi)] if len(fx) else fx
    if not len(fx):
        return {"status": "no_fixtures", "reason_code": "schedule_unpublished",
                "event": ev.get("key", event_key), "checked": 0}

    rows, worst = [], 0.0
    for r in list(fx.itertuples())[:n]:
        ko_utc, ko_bj = clubverify._kickoff(r.date)
        d = r.date.strftime("%Y%m%d")
        url = live.espn_scoreboard_tmpl(espn).format(d1=d, d2=d)
        espn_ko = None
        try:
            for e in live._fetch_json(url).get("events", []):
                names = e.get("name", "")
                if r.home_team.split()[0] in names or r.away_team.split()[0] in names:
                    espn_ko = e.get("date")     # ESPN 的 date 是 UTC ISO（…Z）
                    break
        except Exception as e:  # noqa  网络不可达 → 该场标记未核对，不伪造通过
            rows.append({"home": r.home_team, "away": r.away_team, "error": str(e)})
            continue
        row = {"home": r.home_team, "away": r.away_team, "source_local": str(r.date),
               "source_tz": str(clubverify.SOURCE_TZ), "utc": ko_utc, "beijing": ko_bj,
               "espn_utc": espn_ko}
        if espn_ko:
            a = dt.datetime.strptime(ko_utc, "%Y-%m-%dT%H:%M:%SZ")
            b = dt.datetime.strptime(espn_ko.replace("Z", ""), "%Y-%m-%dT%H:%M")
            row["diff_minutes"] = round(abs((a - b).total_seconds()) / 60.0, 1)
            worst = max(worst, row["diff_minutes"])
        rows.append(row)
    ok = [r for r in rows if r.get("diff_minutes") is not None]
    passed = bool(ok) and worst <= TOL_MIN
    if passed:
        clubverify.record_tz_verified(code, worst, len(ok))   # 通过即登记，解锁该联赛自动冻结
    return {"status": "ok" if passed else "unverified",
            "event": eventsmod.resolve(event_key), "checked": len(ok),
            "worst_diff_minutes": worst if ok else None, "tolerance_minutes": TOL_MIN,
            "auto_freeze_unlocked": passed, "rows": rows}


def main() -> int:
    ap = argparse.ArgumentParser(description="俱乐部赛前冻结 / 赛后结算")
    ap.add_argument("--event", help="只处理该赛事（旧 key 别名自动归一）")
    ap.add_argument("--no-freeze", action="store_true")
    ap.add_argument("--no-settle", action="store_true")
    ap.add_argument("--crosscheck", metavar="EVENT", help="开球时间口径交叉核对（不写账本）")
    ap.add_argument("--json", metavar="PATH", help="结果另存 JSON")
    a = ap.parse_args()

    if a.crosscheck:
        out = crosscheck(a.crosscheck)
        hard = out["status"] == "error"
    elif a.event:
        key = eventsmod.resolve(a.event)
        row = {}
        if not a.no_freeze:
            row["freeze"] = clubverify.freeze_event(key)
        if not a.no_settle:
            row["settle"] = clubverify.settle_event(key)
        hard = any(v.get("status") == "error" for v in row.values())
        out = {"status": "partial" if hard else "ok", "events": {key: row},
               "hard_failures": int(hard)}
    else:
        out = clubverify.run_all(freeze=not a.no_freeze, settle=not a.no_settle)
        hard = out["hard_failures"] > 0

    print(json.dumps(out, ensure_ascii=False, indent=2))
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)
    return 1 if hard else 0


if __name__ == "__main__":
    sys.exit(main())
