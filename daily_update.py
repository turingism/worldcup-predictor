"""D2 每日抓取：football-data.co.uk 增量 + fixtures + ESPN 联赛完场检查。

- 十联赛（五大 + feeder）最新一季 CSV 强刷（clubdata.fetch 已具 D1 韧性：
  刷新失败沿用缓存、新季空窗降级）；报告每联赛数据截止日与增量场次。
- fixtures.csv 强刷（未来一轮赛程 + B365 赛前盘；休赛期可能为空，如实记录）。
- ESPN 五大联赛 scoreboard 当日完场计数（复用 live._fetch_json 的
  系统代理+直连回退；休赛期 0 场为正常状态）。
- 模型/界面联动：club 模型缓存按数据 mtime 指纹自动失效（clubpredict.
  get_club_model），overview 时间戳每请求直读帧——CSV 更新后无需重启服务。
- 日志：data/logs/daily_update.log（追加式，含 traceback）；任何硬失败
  exit 1（launchd/cron 可据此告警）。

用法：python3 daily_update.py    每日定时（如 launchd）调用同款命令。
"""
import datetime as dt
import os
import sys
import traceback

_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(_DIR, "data", "logs")
LOG = os.path.join(LOG_DIR, "daily_update.log")


def log(msg: str):
    os.makedirs(LOG_DIR, exist_ok=True)
    line = f"{dt.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main() -> int:
    import clubdata
    ok = True
    log("=== daily_update 开始 ===")

    # ① football-data 十联赛增量（只强刷最新一季）
    for code in list(clubdata.FEEDER) + list(clubdata.FEEDER.values()):
        try:
            before = clubdata.load(code)                     # 缓存态基线
            n0, d0 = len(before), str(before.date.max().date())
            after = clubdata.load(code, refresh=True)
            n1, d1 = len(after), str(after.date.max().date())
            log(f"[csv] {code}: {n0}→{n1} 场（+{n1 - n0}），数据截止 {d0}→{d1}")
        except Exception as e:  # noqa
            ok = False
            log(f"[csv][失败] {code}: {e}\n{traceback.format_exc()}")

    # ② fixtures（未来一轮赛程+盘口）
    try:
        fx = clubdata.load_fixtures(refresh=True)
        if len(fx):
            log(f"[fixtures] {len(fx)} 场，日期 {fx.date.min().date()}~{fx.date.max().date()}")
        else:
            log("[fixtures] 0 场（休赛期/发布空窗，属正常状态）")
    except Exception as e:  # noqa
        ok = False
        log(f"[fixtures][失败] {e}\n{traceback.format_exc()}")

    # ③ ESPN 五大联赛当日完场计数（赛季内为实时兜底预热；休赛期 0 场正常）
    try:
        import events as eventsmod
        import live
        today = dt.date.today().strftime("%Y%m%d")
        for key, ev in eventsmod.EVENTS.items():
            lg = ev.get("espn")
            if not lg or not ev.get("universe", "").startswith("club_"):
                continue
            try:
                payload = live._fetch_json(live.espn_scoreboard_tmpl(lg).format(d1=today, d2=today))
                done = sum(1 for e_ in payload.get("events", [])
                           if ((e_.get("competitions") or [{}])[0].get("status") or {})
                           .get("type", {}).get("completed"))
                log(f"[espn] {lg}: 今日完场 {done} 场")
            except Exception as e:  # noqa  单联赛 ESPN 失败不拖垮整跑，但要留痕
                ok = False
                log(f"[espn][失败] {lg}: {e}")
    except Exception as e:  # noqa
        ok = False
        log(f"[espn][失败] 初始化: {e}\n{traceback.format_exc()}")

    log(f"=== daily_update 结束：{'全部成功' if ok else '存在失败（见上）'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
