# P1/P2 接线施工清单（2026-07-16 冻结期预研 · 7-20 解冻后按序施工）

> 目标：解冻当天一次落地 P1。每步独立可验收、可回滚；锚点=当日代码实测行号（施工前 grep 复核）。
> 蓝图以 `docs/ia-mockup.html` + `MULTI_EVENT_PLAN.md` 为准；本文只做施工序列与锚点。

## 动工前置（P0 事实，勿跳过）
- [ ] 决赛（104 号，北京 7-20 03:00）ESPN 赛果已 ingest、账本回补完成、`/api/verify` 无 pending。
- [ ] `events.status("wc2026", today)` 返回 `archived`（window 端点 2026-07-19 为【北京日】口径，
      决赛实际结束在北京 7-20 早上——若 status 在 7-20 判 archived 而账本仍在回补，属正常时序，
      先回补后接线）。
- [ ] 全量基线：`python3 -m pytest test_core.py -q` 104 项全绿 + `#bracket`/`#champ` 截图存档。

## P1-①：后端 event 上下文（app.py，纯增量、默认向后兼容）
- [ ] 新 helper `_event()`：`request.args.get("event")` → `events.get(key)`；非法 key → 400。
- [ ] 全 API 加 `?event=` 透传（route 清单：app.py grep `^@app.route`，33 条）；**本阶段只接
      wc2026 语义**（default=wc2026 时行为逐字节不变=回归零风险），非默认 event 先返回
      `{"status": "not_wired"}` 占位，逐 API 解锁。
- [ ] 测试：`?event=wc2026` 与无参数响应一致（golden diff）；`?event=bogus` → 400。

## P1-②：live / espn_odds league code 参数化（行为保持）
- [ ] `live.py:23 ESPN_URL` 与 `espn_odds.py:31 SB_URL / :33 SUM_URL`：`fifa.world` 抽成参数，
      默认值 `events.EVENTS["wc2026"]["espn"]`——**默认调用零行为变化**。
- [ ] `_NOPROXY_OPENER` / (系统代理,直连)×2 重试模式**原样保留**（06-25 评审已验证，勿重构）。
- [ ] 测试：URL 构造单测（fifa.world / uefa.nations / eng.1 三例），不打真网。

## P1-③：验证账本按赛事隔离接线（红线级）
- [ ] `verify.py:29 LEDGER_PATH`：`load_ledger/save_ledger` 已有 path 形参；`freeze/backfill/
      evaluate/_completed` 补 path 贯穿（或改 event-scoped 前缀函数，二选一，倾向显式 path）。
      ⚠️ 已知坑：**默认参数在 def 时绑定**，monkeypatch 模块变量不影响默认值（CLAUDE.md 06-25）。
- [ ] `jc_review.py:27 STORE` 同构隔离；`handicap_ledger`/`clv` 侧确认 key 里带不带 event（现均
      从 verify 账本派生 → 账本隔离即自然隔离，确认即可）。
- [ ] 测试：两个 event 各 freeze 一场 → 断言写入不同文件、互不可见（registry ledger 文件名
      互异测试已在，补"运行时真隔离"断言）。

## P1-④：L0 切换器 + hash 双段路由（index.html，晋级树=历史 bug 高发区，最后动）
- [ ] `index.html:519 .tabs` 上方插 L0 事件条（分组+状态徽标，样式照 ia-mockup.html）。
- [ ] `:2586` hash 解析改双段 `#<event>/<tab>?qs`；**旧深链全部 301 语义回填**
      `#bracket → #wc2026/bracket`（manager?h= 分享链在外部聊天记录里，必须永续兼容）。
- [ ] L1 tab 装配由 `events.get(key)["kind"]+tabs_off` 驱动：cup=晋级树 / league=积分榜互换位；
      无盘口源 → 市场 tab 整体隐藏（P1 阶段 nl2026 无盘口）。
- [ ] 验证：CDP/截图三态（wc2026 归档、nl2026 upcoming、epl2526 not_wired 占位）+ 旧深链回填
      + `layoutBracket` 零回归（103 季军赛卡片仍在）。

## P1-⑤：nl2026 壳（第一个新赛事，同宇宙零数据成本）
- [ ] `data.py` filter `tournament == "UEFA Nations League"`（martj42 658 场已实测在库）。
- [ ] 赛程：9 月开打前无 scoreboard 数据 → 状态页「9 月开赛，当前可预测任意对阵」+ 单场预测
      入口（predict.py 同宇宙直接可用）；开打后 live 层参数化自动生效。
- [ ] wc2026 归档态：看板转「回顾模式」（账本只读展示、冻结统计定格），in-play/refresh 停轮询。

## P2（P1 验收后 → 8 月初英超开赛前）
- [ ] `clubdata._CUR_END` 2025→2026 + `--refresh` 拉新赛季（升班马映射已提前补齐 07-16）。
- [ ] `/api/predict?event=epl2526` → clubpredict 解析链；`/api/standings` 新 route →
      `clubsim.simulate_preseason`（开赛前）/ `simulate_retro` as_of=now（开赛后，feeder 必传）。
- [ ] 市场 tab：B365 开/闭盘直读（clubdata 原生列）；对标文案数字=bt_club_market 基线
      （闭盘全胜模型 +.0100，跨联赛；红线：仅描述性，无任何「率」处方）。
- [ ] 账本：predictions_epl2526.json 从零冻结；CLV 层吃自带闭盘（免快照）。
- [ ] P3 复制：四大联赛条目已在 registry（07-16），复制 P2 模式逐联赛解锁。

## 红线随身单（施工中随时对照）
1. 账本绝不跨赛事混池；2. 双宇宙 half_life 绝不互换（国 730/club 365）；3. 赛季模拟 feeder 必传；
4. explainer/narrative/jc 的 `_BANNED`+无「率」红线全赛事一体；5. DC 引擎零改动。
