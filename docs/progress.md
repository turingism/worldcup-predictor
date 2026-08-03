# /loop 任务进度记录（世界杯预测器 → S 级联赛比分预测器）

体例：每轮记录做了什么、如何验证、证据路径、遗留问题。「未验证」按纪律如实标注。

## 2026-08-03（二十轮）联赛赛程接 ESPN 主源：看板「未来 14 天赛程预测」实数据落地

### 触发
用户报「英超赛事看板 未来 14 天赛程预测 可以更新了」。实测发现卡片仍空——
根因**不是**没更新，而是源能力缺口：`fixtures.csv` 当日仅 21 行、全是苏格兰四级联赛，
五大联赛 0 行（该文件只在盘口开出后登记未来数天）。同日 ESPN 已完整发布 26-27 赛程。

### 做了什么
1. **新模块 `clubfixtures.py`**：ESPN scoreboard 按月窗抓今天起 120 天未完场
   （state != post）→ 队名映射 football-data 拼写（`eurodata.ESPN_FIX` + 新增
   `LEAGUE_FIX` 18 条升降级队）→ UTC 转北京时间落帧、另存精确 `kickoff_utc`
   → 缓存 `data/club/fixtures_espn_<code>.json`（TTL 12h + SWR）。
   `load_cached()` 为**纯只读装载器**（不联网/不起线程/不写盘），供首页只读铁律。
   裁决落 `docs/data-sources.md` 第十节。
2. **`/api/club/overview` 的 upcoming 改接新源**：赛程走 clubfixtures，B365 赛前盘仍
   从 fixtures.csv 按（主,客）**不含日期**合并（两源时区口径不同，含日期必失配）。
   新增**下一轮回退**：14 天窗口内无场次但赛季已排期时，显示下一轮（首场起 4 天内同轮）
   并置 `mode=next_round` + `days_to_first`，标题如实写「已超出 14 天窗口」——
   不拿下一轮冒充窗内场次，也不再用一句「赛程未发布」把已公布赛程盖掉。
3. **首页只读接同一份缓存**：`_fixtures_cached()` 两源合并（同主客以 ESPN 行为准），
   帧多一列 `kickoff_utc`——非空即 ESPN 行直接用，为空才走 `clubverify._kickoff`
   的英国时区换算。**这是本轮最大的雷**：两种 naive 时间戳互喂会整偏 7-8 小时。
   指纹纳入 ESPN 缓存文件；`freshness.schedule` 双源标注 + `espn_cached_at`。
   效果：首页从「赛程未发布 / 赛季启动时间轴」变为真实「接下来 14 天」比赛流。
4. **赛历事实校正**（ESPN 实测 vs 旧估计值）：英超首轮 08-21（旧 08-08）、
   德甲 08-28（旧 08-21）、法甲 08-21（旧 08-14）；西甲 08-15、意甲 08-22 原值即准。
5. **teams_zh 补 2 条**：Hull 赫尔城、Malaga 马拉加（26-27 升班马）。

### 滚动断言改判（按 07-24 立的改判纪律登记，依据=赛历事实而非放宽断言）
- clubverify 用例里按旧赛历写死的 08-08/08-09 已落在新赛季窗外 → 整体平移到真实首轮周
  08-21/08-22（BST 断言仍成立，8 月同为 BST）；五联赛参数化冒烟的 08-25 落在德甲窗外
  → 改 09-01（五家窗内共同日）。
- `test_clubverify_scheduler_discovers_all_active_club_events` 的 as-of 07-25 → 08-05：
  德甲改 08-28 后距 07-25 已 34 天=upcoming，08-05 时五家全在 soon 的 30 天窗内。

### 验证
- `pytest test_core.py -q` **218 passed**（新增 6 个：ESPN 帧映射/时区、只读装载器离线性、
  盘口不含日期合并、中文映射全覆盖、下一轮回退、真休赛期空态；首页只读铁测追加
  禁用 `clubfixtures.harvest/load`，锁死首页只准走 `load_cached`）。
- 世界杯五端点 200 且体积正常（本轮 diff 未触碰世界杯路径）。
- 截图：`docs/evidence/upcoming-epl2627-espn.png`（下一轮回退态，10 场、2 场升班马
  no_model）、`upcoming-laliga2627-window.png`（窗内态）、`home-match-stream-espn.png`
  （首页 14 天比赛流）。页头「18 天后开赛」与卡片「距开赛 18 天」已统一基准（首场 UTC 日期）。

### 遗留
- **开球时间核验仍 0/5、五联赛冻结仍 blocked**（P0-A 闸未动，本轮只碰看板读路径）。
  ESPN 源原生 UTC 无时区歧义，是把 `--crosscheck` 换成 ESPN 对表的天然素材，
  但冻结账本写入不可回改，须单独一轮做。**英超首轮 08-21 前必须解闸**。
- `clubverify.freeze_event` 仍只吃 fixtures.csv（英国本地时间口径），未改。

## 2026-07-25（十八轮）events 更名 + P0-A 俱乐部冻结/结算链路（跨模型对谈定稿需求）

### 做了什么
1. **跨模型对谈**（用户授权 computer-use 驱动本机 Codex 桌面端）：我提供实测状态 + 硬约束 +
   方案 → Codex 读仓库核验后出评审（核对了 verify.py:127 世界杯绑定、bt_ucl.py:59 IID bootstrap、
   index.html:3051/3121 的 isClub 二分，均属实）→ 我提三处反驳 → Codex 全部采纳出定稿修正案。
   合并落 `docs/UPGRADE_REQUIREMENTS_2026-07-25.md`（六阶段，逐项完成判据/回滚条件/裁决避让；
   第 10 节为修正案，冲突以其为准）。
   - 我的三处反驳：① 「前端零 key 特判」按字面不可完成（世界杯遗留 WC_SECTIONS/wcArchived/
     evApplyIdentity 的 key 判断正是为保 golden 而存在，清除即触发同文件的「不得重写世界杯全部
     DOM」回滚条件）→ 收口为只约束新装配层 + legacy allowlist；② P0-A 只写英超，但五大联赛
     8-14~8-22 全部开赛 → 调度须参数化覆盖五个规范 key；③ 只冻结不结算 = 不可验证的半截账本
     → settle_event 必须同阶段交付。
2. **events 五联赛更名 25-26 → 26-27 + 旧 key alias**（9043359，用户拍板；实测零联赛账本→零迁移）。
3. **P0-A `clubverify.py` + `scripts/club_freeze.py`**（7171e4c）：赛前冻结 + 赛后结算 + 批量调度 +
   开球时区安全闸；daily_update 第④步接入同一实现。

### 如何验证
- 186 passed（160→186）。golden diff 十端点逐字节一致（生产实例 kickstart 后捕获）。
- 更名：旧 key epl2526 与现 key 响应逐字节一致、bundes2526→bundes2627 归一、/api/events 只列现 key；
  浏览器实测 #epl2627/board 渲染「英超 26-27」。
- P0-A 证据 docs/evidence/p0a-*.json：当季 0 场冻结（概率和误差 0.0、data_through=2026-05-24）、
  五联赛参数化、账本隔离（五文件互异 + 别名同文件）、批量隔离（德甲无赛程不影响英超）、
  **25-26 真实历史闭环**（Leeds 3-1 Burnley：赛前 p_home .582 冻结 → 结算 actual=H、
  outcome_hit=true、赛前 15 字段逐字段不变）。

### 遗留 / 未验证（如实）
- **开球时间交叉核对未做**：26-27 赛程未发布，fixtures.csv 无赛季窗内场次 → 记为未核对，
  五联赛冻结当前全部 blocked（安全默认，非故障）。8-08 前必须逐联赛 --crosscheck 通过解锁。
- 生产启用分两步：首轮开球前启用冻结；首轮赛果进当季 CSV 后确认 settled。
- P0-B~P2 未动（队列见 CLAUDE.md 十八轮条）。

## 2026-07-19（第 N 轮，决赛日）阶段 0 诊断完成 + 三份文档落地

### 做了什么
1. 阶段 0 失败归因诊断：git log/status 核查 + 链路四层逐层实测，结论写入 `docs/diagnosis.md`。
   核心结论：非故障——P0 离线层（数据/模型/模拟器/注册表/映射）全部建成且实测可用，L3 API 与 L4 前端零接线是「世界杯运行期冻结大改」纪律下的计划内未实施，施工清单 `docs/P1_WIRING_CHECKLIST.md` 已备好，解冻点=今晚决赛赛果回补后。
2. `docs/data-sources.md`：数据源选型结论整合落档（主源 football-data.co.uk + martj42，任务书候选源落选原因逐一说明）。
3. `docs/backtest.md`：hl=365 裁决、市场对标基线（闭盘全胜模型，如实不美化）、clubsim 回溯验证整合落档。

### 如何验证的
- 数据层：`ls data/club/` 十联赛各约 7 季 CSV 在位。
- 计算层：`python3 clubpredict.py "阿森纳" "曼城"` 实跑 → 39.7/26.4/33.9，Top7 比分正常。
- API 层：grep app.py 零 club/events 引用；`GET /api/dashboard?event=epl2526` 实测参数被忽略。
- 前端层：grep index.html 零联赛入口。
- 基线测试：`python3 -m pytest test_core.py -q` → **103 passed, 1 skipped**（网络依赖项自动跳过）——P1 动工前置条件②满足。
- 决赛状态：dashboard API 实测西班牙 vs 阿根廷仍在 upcoming（北京 7-20 凌晨开球），冻结生效中。

### 证据路径
- `docs/diagnosis.md`（含逐层实测表）
- 本轮 pytest 输出：103 passed, 1 skipped in 39.83s

### 遗留问题 / 下一步（07-19 晚已大部分完成，见下一条记录）
- [ ] P1 接线（决赛赛果回补后动工，照 `docs/P1_WIRING_CHECKLIST.md` 五步）：event 上下文 → live/espn 参数化 → 账本隔离 → L0 切换器 → nl2026 壳。
- [ ] 链路打通验收件：浏览器截图可见非世界杯赛事预测卡片，存 `docs/evidence/`（待 P1-④）。
- [ ] P2（8 月初英超开赛前）：英超 web 接线、每日抓取脚本、`clubdata._CUR_END` +1。
- [ ] 未验证项：每日定时抓取脚本（赛季未开，未做）；可靠性曲线出图（未做）；欧冠两回合制（P4 研究项，未做）。
- 任务书与既有裁决的冲突已在 diagnosis.md 第五节勘误（数据源不重选、DC 基线已超额完成）。

## 2026-07-19 晚（同日第二轮）P1 五步接线全部完成：联赛 Tab 真实预测卡片上线

说明：用户明确指示解冻动工。事实核查：动工时决赛（西班牙 vs 阿根廷）尚未开球
（北京 7-20 03:00），账本 103 场、决赛未回补——前置条件①在事实层面未满足，按
用户指令视为提前解冻；因此 wc2026 归档模式做成 events.status 条件驱动（决赛回
补前恒为 live 不激活），世界杯今晚的实时链路零干扰。

### 做了什么（每步独立 commit）
1. 存量基线 commit：07-07 至 07-16 冻结期全部离线增量落库（此前从未提交）。
2. P1-①（2cfc27f）：before_request event 闸门，全 API 接受 ?event=；默认逐字节
   不变；非法 400；未接线赛事 not_wired 占位。
3. P1-②：live/espn_odds ESPN league code 参数化，默认 fifa.world 字面量逐字节
   不变，_NOPROXY_OPENER 重试模式未动。
4. P1-③：verify 账本与 jc_review 存储 path 显式贯穿（调用时解析，兼容旧测试
   monkeypatch），ledger_path/store_path 按注册表隔离，全赛事路径互异断言。
5. P1-④：L0 赛事切换器（/api/events 状态驱动排序、纯文字徽标）、hash 双段路由
   #<event>/<tab>、旧深链永续回填、未接线赛事诚实空态。
6. P1-⑤：nl2026 壳（同宇宙复用 /api/predict，658 场历史实时读库）+ 俱乐部真实
   接线（/api/club/overview 实力榜+季前概率、/api/club/predict 单场预测，复用
   clubpredict/clubsim 离线件）+ club_preseason.py 预计算五联赛季前概率 JSON +
   wc2026 归档模式条件驱动（归档后停轮询+回顾模式标注）。

### 如何验证的
- test_core 110→113 全绿（+13 项：闸门 golden diff/400/占位、URL 三例、账本隔
  离、club overview/predict 结构与归一、nl2026 解锁）。
- 重启后同时刻 golden diff：5 个确定性端点 有参=无参 逐字节一致。
- 浏览器截图（headless Chrome，全部人工 Read 核验）：
  - docs/evidence/p1-5-epl-real-cards.png：英超 Tab 真实预测卡片（曼城 vs 阿森纳
    42.3/26.2/31.5 + Top5 比分 + 季前概率表 + 实力榜 + 时间戳/来源）——链路打通
    验收件（阶段 0 第 4 条）。
  - p1-5-laliga/seriea/bundes/ligue1：其余四联赛同构渲染。
  - p1-5-nl2026-shell.png：欧国联壳 + 西班牙 vs 法国真实预测卡。
  - p1-4-legacy-bracket.png / p1-5-legacy-manager.png：旧深链 #bracket、
    #manager?h=Argentina&a=France 回填后完整可用（晋级树零回归、报告自动生成）。
  - p1-4-default-dashboard.png：世界杯默认视图零回归，决赛冻结预测在位。
- 预计算数字与 07-16 档案交叉验证一致（曼城 42.7/巴萨 48.0/国米 62.8/拜仁
  80.1/巴黎 83.2）。

### 证据路径
docs/evidence/ 全部截图；git log 9e88367..HEAD 每步 commit message 附验收证据。

### 未验证 / 遗留（如实标注）
- wc2026 归档态行为（回顾模式标注+停轮询）：代码为条件驱动，决赛回补、状态翻
  archived 后才自然激活，本轮无法实测——标注「未验证」，明日决赛回补后观测。
- 联赛「未来 7 天赛程预测」「积分榜（赛内 as_of 口径）」「jc_review 联赛入口」：
  P2 范围（25-26 开赛前），未做。每日定时抓取脚本：未做（赛季未开，无更新源）。
- 欧冠：维持 P4 研究项，跨联赛对阵仍诚实拒绝。
- power_ranking 的身价过滤在俱乐部池会滤空（既有暗坑）：app 侧已绕开（attack-
  defence 直算），clubpredict --ranking CLI 路径仍受影响，待单独修。

## 2026-07-19 晚（第三轮）状态 B：暗坑修复 B1 + 核查 B2

状态判定：18:50 实测决赛未开球（账本 103、upcoming=西班牙 vs 阿根廷）——状态 A
未到点，按序命中状态 B。

### B1 power_ranking 俱乐部池滤空修复
- 共用实现下沉：`clubpredict.net_ranking(m, top)`（attack-defence 直算，含暗坑
  成因注释）；CLI `print_ranking` 与 `/api/club/overview` 改为同源取数；
  model.py 零改动（国家队 power_ranking 行为原样，身价过滤对国家队是刻意设计）。
- 验证：修复前 `clubpredict.py --ranking E0` 输出空榜（实测复现），修复后 Top20
  正常（曼城 +0.041 居首）；新增回归测试断言非空、降序、CLI 与 API 同值；
  test_core 113→114 全绿；重启后 API 实测 ranking[0]=曼城。

### B2 evPct 改名核查（零改动审计）
- 全页仅三处相关定义：页面原有 `const pct`（752 行）、无关的局部 `pctTag`、
  新增 `function evPct`（2640 行）；新增块内 grep 无旧 `pct(` 残留；node --check
  通过。结论：无冲突无残留，B2 关闭。

### 证据
test_core 114 全绿；本条上方 CLI/API 实测输出；git commit 本轮。
决赛观测继续等待（北京 7-20 03:00 开球）。

## 2026-07-19 晚（第四轮）球队数据架构裁决落档（用户指令项）

### 裁决结论（对照六条约束逐条落位）

1. **账本层统一（match 数据模型）——现状即达标，零迁移**。两宇宙 match 帧共享
   7 个核心列（date/home_team/away_team/home_score/away_score/neutral/tournament），
   clubdata 装载时已归一到引擎 schema（这正是 DC 引擎零改动可训俱乐部的原因）。
   共用实现裁决：**manager.py 的过程数据函数（_team_matches/recent_form/
   head_to_head/team_stats）即两宇宙共用实现**——只依赖共有核心列，实测在国家队
   帧与俱乐部帧上零改动跑通（证据见下），不另造新模块、不产生第二份实现。
   注意与红线的边界：本条说的是"历史比赛事实层"统一；**验证账本
   （predictions_*.json）按赛事隔离是 registry 层锁死的不变量，不在本条范围、
   继续隔离**。
2. **实体层同库不同池——现状语义达标（teams_zh 双命名空间 + 池化查询），物理
   单表留裁决**。现状：teams_zh 一个模块（同库）内 national/CLUB 两个命名空间
   （不同池），零交集由既有测试锁死；俱乐部池经 clubpredict._league_teams 跨五
   大联赛共享；国家队名查俱乐部池实测返回 None（物理隔离）。若要字面意义的
   "单表 + universe 字段"，需把两个 dict 合并为带字段的结构并改全部消费方
   （teams_zh.disp 双表查/_R 反查/测试断言），估计 M 级半日工作量、收益主要是
   形式统一——**是否执行留待用户裁决，本轮不动**。
3. **模型层不共享——现状即达标 + 本轮补标注**。每联赛独立拟合已是硬约束；
   卡片/CLI 实力榜标注本轮改为「联赛内相对值，跨联赛不可比」（index.html 表头
   + clubpredict CLI 文案）；欧冠跨联赛校准维持独立 P4/P2 末项，本轮未处理。
4. **卡片数据维度按宇宙区分——架构已备好，具体卡片渲染属 P2 施工**：共用维度
   走 manager.py 共用函数；俱乐部特有（积分榜/主客场拆分）数据在
   clubsim.final_table 与 clubdata 帧（主客场可按 home/away 过滤共有列直算）；
   国家队特有维度（东道主/环境/晋级树）现有世界杯口径零改动。
5. **现状冲突与迁移成本评估（留用户裁决的两项）**：
   a. teams 物理单表化：见第 2 条，M 级，收益形式化，默认不迁。
   b. 常用简称别名缺口（新发现）：跨联赛查询全称均可解析（皇家马德里→SP1、
      阿森纳→E0），但「皇马/巴萨/拜仁/尤文」等简称未命中（difflib 只给建议）。
      修法=teams_zh.CLUB 补别名映射表，S 级工作量，无风险；**待用户点头随下轮
      P2 顺手做**。
6. **验收证据（同一套函数两宇宙实测 + 跨联赛池查询）**：
   - 国家队：recent_form(martj42 帧, Spain, 6) → WWWWWW 6胜0平 进13失1 零封5，
     最近一场 2026-07-14 半决赛 2-0 法国（与真实赛果一致）；head_to_head
     西 vs 阿近 5 次 → 西 3 胜 阿 2 胜，最近 2018-03-27 西 6-1 阿（真实）。
   - 俱乐部（同一套函数零改动）：recent_form(E0 帧, Arsenal, 6) → WWDLDW
     3胜2平1负，最近一场 2025-05-25 客胜南安普顿 2-1（真实季末轮）；
     head_to_head 阿森纳 vs 曼城近 5 次 → 阿 2 胜 平 2 曼城 1 胜，最近
     2025-02-02 阿森纳 5-1（真实）。
   - 跨联赛池：阿森纳→(Arsenal,E0)、皇家马德里→(Real Madrid,SP1)；
     国家队名（西班牙/Argentina/France）查俱乐部池全部 None（隔离正确）。
   - 固化为 test_core 两项新测试（test_matchfacts_shared_impl_both_universes /
     test_team_pool_cross_league_and_isolation），基线 114→116 全绿。

### 本轮改动面
clubpredict.py/index.html 标注文案两处 + test_core 两测试；零逻辑重构（裁决
的要点恰是"现状已满足，不造第二套"）。决赛观测继续等待（19:05 实测未开球）。

## 2026-07-19 晚（第五轮）数据库拓展裁决落档 + 25-26 整季回补（用户指令项）

### 最高优先：俱乐部账本赛季完整性核实与回补（已完成）
- **核实**：ls data/club 实测十联赛全部止于 2425；25-26 赛季（2025-08 至
  2026-05，现实已踢完）整季缺库。此前「25-26 季 8 月才开」是赛季口径错误
  （8 月开的是 26-27），今晚早些时候生成的"25-26 季前模拟"实为对已发生赛季
  的模拟——属实质数据新鲜度事故，本轮修正。
- **回补**：clubdata._CUR_END 2025→2026，五大联赛 + 五个次级 feeder 各 +1 季
  实拉成功（E0/SP1/I1 各 +380 场、D1/F1 +306、E1 +552 等，数据至 2026-05-24）。
- **重训与影响证据**（同口径 before/after）：E0 队数 29→28（7 季窗滚动）；
  净实力榜曼城(+0.041)领跑 → **阿森纳登顶、曼城 -0.053 落第二**；
  Arsenal-ManCity（默认口径）35.0/27.5/37.5 → 36.7/29.6/33.7；重启后 API 实测
  data_through=2026-05-24、阿森纳主场 vs 曼城 42.9/27.7/29.4。五联赛重训后
  Top3：E0 阿森纳/曼城/利物浦；SP1 巴萨/皇马/马竞；I1 国米/科莫/罗马；
  D1 拜仁/多特/勒沃库森；F1 巴黎/朗斯/里尔。
- **25-26 真实终局（数据直读）**：英超降级 West Ham/Burnley/Wolves（英冠前三
  Coventry/Ipswich/Millwall）；西甲降 Levante/Girona/Oviedo；意甲降
  Cremonese/Verona/Pisa；德甲末三 Wolfsburg/Heidenheim/St Pauli；法甲降
  Nice/Nantes/Metz。
- **映射**：test_core 俱乐部全覆盖断言绿——25-26 新队映射 07-16 已提前补齐，
  本轮零缺口；26-27 升班马已随 feeder 数据入库（直升队可从终表得）。
- **过时产物处置**：季前 preseason_*.json 五份删除（误标赛季+旧模型产物），
  联赛页自动转为明确空态；club_preseason.py 加运行闸（26-27 名单未确认前拒跑）。
  **26-27 季前模拟为阻塞项**：直升队已知（如 E0←Coventry/Ipswich），附加赛
  胜者需外部信息（football-data CSV 不含附加赛），标注「未验证/待确认」。

### 测试改判记录（红线 5）
test_clubsim_preseason_25_26 → test_clubsim_preseason_rolling：原测试写死 25-26
升班马名单，回补后该名单已在终表内、名单构造不守恒（skip 理由"数据不可得"系
误标，真实原因=前提过时）。改为从 feeder 终表自导升班马（前三近似，仅测机制
不测真实名单），跨赛季滚动成立。影响面：仅该测试；机制断言全保留。
基线 116 全绿（数量不变：+0）。

### 裁决落档（据用户指令）
- 欧战数据集接入列入 P2、排跨联赛校准前（选型实测留后续轮）；实体层 teams
  统一表提前至欧战接入前（成本评估沿用第四轮：M 级半日、迁移与否用户已定为
  "做"，作欧战地基——本轮未动工，下轮状态 C 首位）。
- 裁决不做三项落 data-sources.md 第七节（球员名册/xG/球员层现状）。
- **留用户裁决（新）**：events 注册表五联赛条目 key/显示名「25-26」实为 26-27
  赛季窗口——建议在账本写入前更名（key epl2526→epl2627 等 + 显示名），现在
  改成本最低（账本未创建、深链外部分享少）；等拍板。

### P2 清单更新（重排后）【已废止，2026-07-23 被用户指令替换，见 07-23 第二轮条】
1. teams 实体层统一表（欧战地基，提前）→ 2. 欧战数据集选型实测 + 接入 →
3. 每日抓取脚本 → 4. fixtures 未来赛程预测（26-27）→ 5. 赛内积分榜 →
6. 市场 tab → 7. jc_review 联赛入口 → 8. 跨联赛校准（欧冠，末位）。
注：原清单第 1 项 _CUR_END+1 本轮已随回补完成。

## 2026-07-23（收官任务书第一轮）基线修复：freeze 测试前提过时改判

### 本轮内容（红了只修基线规则命中）
开轮全量 test_core：140 passed / 1 failed——
`test_freeze_ledger_records_adjustments` 断言 `freeze(now_bj="2026-07-19 12:00") >= 1`
失败（n=0）。

### 根因（实测非推测）
决赛赛果已入库（load_raw 实测：2026-07-19 Spain 1-0 Argentina、07-18 季军赛
France 4-6 England），`verify.freeze` 对已有真实赛果的场次永不再写（KO 分支
`m.get("set")` 跳过、小组分支 `actual_results` 跳过）——这是冻结账本的正确
不变量。测试写于决赛赛前，靠回拨 now_bj 依赖「决赛无赛果」这一已失效前提。

### 测试改判记录（红线 4）
- 改法：构造 sim 时剔除 `df.date >= "2026-07-19"` 的赛果行，复现「决赛赛前」
  场景；断言全保留（n>=1、每条账本记录 adjustments/availability=={}/env）。
- 理由：测试目的=验证账本记录 adjustments 机制，n>=1 只是需要至少一场可冻结；
  前提过时属数据自然演进，非机制回归。freeze 生产行为零改动。
- 影响面：仅该测试；机制断言不放宽。

### 验证
`python3 -m pytest test_core.py -q` → **141 passed** 全绿（数量不变）。

### 遗留问题（下轮起点）
- 阶段 A 核查：A1/A2 已完成（第五轮）；A4 的 CLAUDE.md 赛季口径勘误段已在位
  （L28「赛季口径勘误」章节），A3（26-27 升班马入 feeder + teams_zh 映射）第五
  轮称已覆盖但需按 A 阶段口径逐项实测确认后才可宣告 A 收口。
- 决赛已回补 → wc2026 归档模式（`wcArchived()`）是否已自然激活未实测；
  「决赛回补后重启生产实例」是否已执行未核实，下轮顺手观测。
- 上一深夜轮（116→141 一致性大修）无 progress.md 条目（记录在 CLAUDE.md 接手段
  与 CHANGELOG），此为记录缺口，不回补重写、以 CHANGELOG 为准。

## 2026-07-23（第二轮）P2 清单替换落档（用户指令）+ A3 升班马映射缺口修复，阶段 A 收口

### P2 清单（权威版，替换第五轮旧清单——用户指令「功能同步清单写入 P2」）
世界杯 → 联赛功能对等同步，一轮一项，按此序施工：
1. 赛事看板补齐：本轮比赛、积分榜、数据更新时间戳；已接线部分只补缺不重构
2. 对阵分析：比分概率分布、胜平负、球队数据展开区（账本层共用实现：
   近 6 轮/交锋/主客场拆分/攻防强度，强度标注「联赛内相对值」）
3. 赛季推演（晋级树的联赛等价物，不做树状图）：clubsim preseason JSON
   渲染争冠/前四/降级概率，概率条+推演说明；树状图形态留给欧冠复用
4. 夺冠概率：冠军维度深入（概率演进、关键场次影响），与赛季推演分工
5. 市场对标：B365 开闭盘 1X2 vs 模型概率（数据池 H/D/A 六列，闭盘 100%），
   沿用 bt_club_market 口径
6. 机制解读：共用世界杯正文 + 联赛差异章节（独立拟合/联赛内相对值/
   neutral=False/hl=365）
7. 竞彩复盘联赛入口：扩展方式接入，不改世界杯逻辑
施工纪律：每 Tab 完成验收=任选一联赛浏览器实测截图存 docs/evidence/ 且
wc2026 对应 Tab golden diff 不变；组件参数化复用，禁止按联赛复制代码；
数据不足显式空态+原因。
注：原清单中 teams 统一表/欧战/每日抓取/fixtures 等项不消失，归位任务书
阶段 B/D/E 推进序。

### 红线勘误落档（用户裁决）
「界面与文案禁 emoji」修订为：**正文与数据区文案禁 emoji，Tab 栏及功能
图标位除外**（现状 Tab 图标合法化）。

### A3 实测冲突与修复（红线 5）
- 第五轮称「25-26 新队映射零缺口」——实测仅对五大联赛帧成立
  （test_teams_zh_club_mapping_complete 只扫 E0/SP1/I1/D1/F1）。
  feeder 25-26 终表前三（26-27 升班马候选=直升+附加赛主候选）中六队无映射：
  E1 Coventry/Millwall、SP2 Santander/La Coruna、D2 Elversberg、F2 Le Mans。
- 修复：teams_zh.CLUB +6（考文垂/米尔沃尔/桑坦德竞技/拉科鲁尼亚/
  埃弗斯贝格/勒芒），disp/to_en 双向实测通过。
- 锁定：新增 test_teams_zh_promoted_candidates_mapped（各 feeder 最近一季
  终表前三必须有映射），基线 141→142 全绿。

### 阶段 A 收口核对
- A1 ✓（第五轮：十联赛 25-26 整季回补，数据至 2026-05-24）
- A2 ✓（第五轮：五联赛重训 before/after 证据，E0 阿森纳登顶等）
- A3 ✓（本轮：升班马候选在 feeder 库实测在位 + 映射补齐 + 测试锁定；
  附加赛胜者仍属外部信息，名单确认前 club_preseason 运行闸维持）
- A4 ✓（CLAUDE.md L28「赛季口径勘误」章节已覆盖旧表述，本轮复核在位）
**阶段 A 宣告完成，下轮进入阶段 B（B1 评估已有第四/五轮档案，届时按
保险丝规则处理）。**

### 验证
python3 -m pytest test_core.py -q → **142 passed** 全绿。
六队映射 CLI 实测输出见上；feeder 前三核查脚本输出（E0←E1
Coventry/Ipswich/Millwall 等五组）本轮实跑。

### 遗留问题
- wc2026 归档模式与生产实例重启仍未观测（上轮遗留，非阶段推进序项，
  择轮顺手核）。
- 附加赛升班马名单待外部确认（8 月前后官方赛程可证），确认前 26-27
  preseason 不跑（运行闸在位）。

## 2026-07-23（第三轮）阶段 C 开工（用户指令直启功能同步）：C1 赛事看板补齐 + 生产实例重启

说明：用户明确指令「将世界杯板块全部功能同步到已拓展联赛」，据此直接进入
阶段 C（功能同步七项）；阶段 B（teams 统一表）顺延，非放弃——欧战接入（阶段
E）前仍须完成。

### C1 做了什么（只补缺不重构）
- clubsim 新增 `standings(season_df)`（一季积分榜数据化：场/胜/平/负/进/失/
  净/积分，名次口径 积分>净胜>进球 与原 final_table 完全一致）；`final_table`
  改为其名次投影（行为不变，测试锁定在位）。
- `/api/club/overview` 补两字段：`standings`（本季积分榜，赛季窗=7 月 1 日界，
  含 season 标签与 complete 完结判定）、`latest_matchday`（最近完赛轮场次+比分）。
- 前端联赛视图补两张参数化卡片：「最近完赛轮」（90 分钟口径+来源+数据截至）、
  「赛季积分榜」（冠军/降级区着色，名次口径注明"联赛通用近似，未含各联赛
  特例细则"）；数据缺失时显式空态。五联赛同一套组件，零复制。

### 验证
- test_core：`test_club_overview_api` 扩展断言（20 行/38 场/积分守恒/降序/
  降级三队=真实终局 West Ham/Burnley/Wolves/末轮日=数据截止日），全量
  **142 passed**。
- golden diff：五个确定性端点（ratings/teams/verify/config/champ_ci，
  ?event=wc2026）在 HEAD（改动前）与工作区（改动后）逐字节一致
  （git stash 前后双捕获 diff -r 零差异）。
- 浏览器实测（headless Chrome，8010 独立实例）：
  - `docs/evidence/c1-epl-dashboard.png`：英超看板全貌——最近完赛轮 10 场、
    2025-26 终表（阿森纳 85 分冠军、降级区红色着色与真实终局一致）、季前
    模拟显式空态、净实力榜、单场预测卡（含来源与数据截至）。
  - `docs/evidence/c1-wc2026-dashboard-regression.png`：wc2026 看板零回归。

### 顺手完成（上轮遗留清零）：wc2026 归档模式观测 + 生产实例重启
- 归档模式（07-19 P1-⑤ 标注「未验证」项）本轮实测激活：看板显示「赛事已
  结束 · 回顾模式（账本定格，自动轮询已停）」，账本终局 104/104 场、胜平负
  命中 70/104=67.3%、精确比分 15/104、平均 RPS 0.1528；决赛（07-20 西班牙
  1-0 阿根廷）预测 1-0 比分+赛果全中，全部赛前冻结留痕在位。
- 生产实例（launchd com.melvin.worldcup-predictor，端口 8000）按既定计划
  （「决赛回补后重启即生效全部修复」）kickstart 重启：重启后实测
  wc2026 status=archived、联赛 overview 新字段在位（Arsenal 85/末轮 10 场）——
  07-19 深夜大修 + 本轮 C1 全部在生产生效。

### 遗留问题
- C2 对阵分析为下轮项（manager.py 共用函数已裁决可直用）。
- events 注册表「25-26」命名实为 26-27 窗口（页面显示「英超 25-26 · 16 天后
  开赛」），更名仍待用户拍板（第五轮留档）。
- 季前模拟空态待 26-27 附加赛升班马名单确认（运行闸维持）。

## 2026-07-23（第四轮）C2 对阵分析：展开区 + 比分概率矩阵（共用实现口径）

### 做了什么
- `/api/club/predict` 增量参数 `detail=1`（默认响应逐键不变，测试锁定）：
  - `facts`：双方 近 6 轮（逐场明细+胜平负/进失/零封）、主客场拆分
    （近 6 主/近 6 客，共有列直算）、攻防强度（team_stats：atk/dfc/net +
    近 20 场场均进失，标注「联赛内相对值，跨联赛不可比」）、历史交锋
    （head_to_head，无交手时结构完整 n=0）——**全部走 manager.py 两宇宙
    共用函数（第四轮裁决），零第二套实现**。
  - `matrix`：6×6 比分概率矩阵 + p_other 余量。
- 前端 `evMatchupDetail()` 参数化组件（任何联赛同一套）：比分概率热力格、
  双队数据展开（两栏自适应）、历史交锋（含战绩摘要），交锋覆盖不到显示
  「暂无数据（数据池近 7 季内无交手记录）」，footer 带数据截至+来源+90 分钟
  口径。三个区块默认展开（对齐世界杯对阵分析全展开形态）。

### 验证
- test_core 新增 `test_club_matchup_detail_api`（近 6 轮守恒/form_str 一致/
  拆分 n=6/net=atk-dfc/h2h 计数守恒/矩阵+余量归一<0.01/强度标注在位/默认
  响应无新增键），全量 **143 passed**。
- golden diff：五确定性端点 HEAD vs 工作区 逐字节一致（stash 双捕获）。
  manager.py 与 /api/manager 零改动（git status 佐证）。
- 浏览器实测（8010 独立实例）：
  - `docs/evidence/c2-seriea-matchup.png`：意甲 国米 vs 科莫——矩阵热力格
    （峰值 1-1 11.4%）、近 6 轮明细、主客场拆分、攻防强度（国米 净+0.399）、
    交锋近 4 次国米全胜（与真实一致）、数据截至 2026-05-24。
  - `docs/evidence/c2-wc2026-manager-regression.png`：世界杯对阵分析旧深链
    `#manager?h=Spain&a=Argentina` 自动出报告零回归，交锋表已含 07-19 决赛
    （西班牙 1-0 阿根廷）。

### 遗留问题
- C3 赛季推演为下轮项：需先解决 preseason JSON 空态（26-27 附加赛名单未
  确认，运行闸在位）——C3 可先以 25-26 已完结赛季做回溯推演形态
  （simulate_retro as_of 数据同源），或等名单；下轮按实测定。
- events「25-26」命名更名仍待用户拍板。

## 2026-07-23（第五轮）C3 赛季推演 + 联赛视图七 Tab 化 + 左侧纵向菜单（用户轮中指令并入）

用户轮中明确两点并入本轮：① 世界杯七 Tab 功能在各联赛都要能找到，但按联赛
赛制合理优化（晋级树状图在联赛=赛季推演，与任务书 C3 裁决一致）；② 赛事切换
改为左侧纵向菜单。

### 做了什么
- **C3 数据层**：`club_seasonsim.py` 预计算——五联赛 × 6 个 as_of 快照
  （25-08 季前 → 26-05-01）各 5000 次 simulate_retro（as_of 前=事实且模型只用
  as_of 前数据训练防泄漏），终局用真实终表 0/1 收口；产物
  `data/club/seasonsim_<code>.json`（原子写）。实测五联赛跑通（约 20 秒）。
- **API**：`/api/club/seasonsim` 直读 JSON + disp 映射，缺文件显式
  `{empty, reason}`；`_EVENT_WIRED` 注册。
- **前端联赛视图 Tab 化（参数化一套组件）**：`LEAGUE_TABS` 七项（看板/对阵
  分析/赛季推演/夺冠概率/市场对标/机制解读/竞彩复盘），`evShowTab` 按需
  fetch+缓存（EV_DATA）；既有 C1/C2 卡片重组为 evBoardCards（看板）与
  matchup Tab；夺冠概率 Tab=实力榜+季前空态+「C4 深入推进中」；C5/C6/C7
  Tab=显式空态+原因；nl2026 仅对阵分析有内容、其余 Tab 空态说明开赛前接线。
  hash 双段 `#<event>/<tab>` 全兼容。
- **赛季推演 Tab（禁树状图达成）**：争冠/前四/降级三组概率条（末快照时点）
  + 争冠概率 SVG 演进曲线（六队、终局收口，无外部库）+ 回溯口径说明 +
  计算时间/来源/数据截至。
- **左侧纵向菜单**：CSS grid 实现（DOM 零改动）——evbar 变 172px 粘性左栏，
  ≤760px 回退横向滚动条形态（移动端不悬空）。

### 验证
- test_core 新增 `test_club_seasonsim_api`（快照 title 归一/top4≈4/bottom3≈3、
  played 单调且季前=0、终局=真实终表（冠军阿森纳、降级西汉姆/伯恩利/狼队）、
  disp 在位），全量 **144 passed**。
- golden diff：五确定性端点 HEAD vs 工作区逐字节一致。
- 数据交叉验证：五联赛终局冠军=库中真实终表（E0 阿森纳/SP1 巴萨/I1 国米/
  D1 拜仁/F1 巴黎）；E0 季前热门曼城 41.8% vs 终局冠军阿森纳——演进曲线
  呈现完整反超叙事。
- 浏览器实测（8010）：
  - `docs/evidence/c3-epl-seasonsim.png`：英超赛季推演 Tab 全貌（侧栏+七
    Tab+三组概率条+演进曲线；保级悬念热刺 51.7% vs 西汉姆 44.3% 真实呈现）。
  - `docs/evidence/c3-sidebar-board.png`：德甲看板同构（拜仁 89 分终表、
    末三与档案一致）。
  - `docs/evidence/c3-wc2026-sidebar-regression.png`：世界杯在新侧栏布局下
    全功能零回归（Tab 栏/看板/账本统计原样）。

### 遗留问题
- C4 夺冠概率页下轮项（冠军维度深入：概率演进细化、关键场次影响；
  seasonsim 数据可复用）。
- 演进曲线末端 x 轴「终局」标签在窄容器轻微贴边（纯外观，后续顺手调）。
- events「25-26」命名更名待用户拍板；26-27 季前模拟待附加赛名单。

## 2026-07-23（第六轮）C4 夺冠概率页：周粒度冠军演进 + 关键场次影响

### 做了什么（与 C3 分工：C3=三维概览+月粒度，C4=冠军维度深入）
- **数据层**：club_seasonsim.py 增 `build_title_series`——周一网格（25-08-04 至
  赛季末，42 点）× 每点 3000 次 simulate_retro（防泄漏口径同 C3），输出
  `title_series`（任一时点夺冠概率≥1% 的队的周序列）+ `key_shifts`（争冠队
  相邻周 |Δtitle| 最大窗口 Top，≥3pp 才收录，附该队同窗实际赛果；明示
  「概率变动亦受对手赛果影响，不作单场因果归因」）。五联赛全量重算约 3.5 分钟，
  JSON 单联赛 19KB。
- **API**：seasonsim 响应为 title_series/key_shifts 补 disp 映射。
- **前端**：抽公用 `evLineChart`（SVG 折线，C3/C4 共用，消除图表代码重复；
  点数>14 自动省略数据点圆点、x 轴标签防重叠）；夺冠概率 Tab=周粒度演进曲线
  + 关键场次影响表 + 实力榜 + 26-27 季前空态；C3 曲线改用公用组件并标注
  「月粒度概览；周粒度详版见夺冠概率 Tab」。

### 验证
- test_core 扩展 seasonsim 测试（序列长度/概率域/disp、key_shifts 按影响力
  降序、窗口相邻性、**delta 与序列逐项自洽 <1e-6**、赛果行结构），全量
  **144 passed**。
- golden diff 五端点逐字节一致。
- 数据叙事实测（E0）：新年窗口阿森纳双胜 +23.4pp 与曼城双平 -22.2pp 同窗
  对应；8 月曼城 0-2 热刺 -20.4pp；4 月阿森纳客负曼城 -17.3pp——全部与库中
  真实赛果核对一致。
- 截图：`docs/evidence/c4-epl-champ.png`（英超夺冠概率 Tab 全貌）、
  `c4-wc2026-champ-regression.png`（世界杯夺冠概率 Tab 零回归：归档态
  西班牙 100% + 贝叶斯区间带原样）。
- 教训记录：debug=False 下 Flask 不自动重载模板，改前端后须重启实例再截图
  （本轮曾截到旧模板，字节数相同暴露）。

### 遗留问题
- C5 市场对标下轮项（B365 开闭盘六列已在帧，bt_club_market 口径）。
- events「25-26」命名待拍板；26-27 季前待附加赛名单（运行闸在位）。

## 2026-07-23（第七轮）C5 市场对标：B365 开/闭盘 vs 模型（bt_club_market 口径）

### 做了什么
- `club_market.py` 预计算：25-26 整季分两段 cutoff（25-08-01/26-01-01）as-of
  训练防泄漏，B365 开/闭盘 Shin 去水，三方同场对比（口径沿用 bt_club_market，
  差异仅覆盖窗改整季分段，脚本头注明）；只计模型可预测且开闭盘俱全场次，
  跳过数如实入 JSON；展示样本=赛季末 7 天（末轮跨多日，单日过滤会漏场——
  首版曾只出 1 场，已修）。产物 data/club/market_<code>.json。
- `/api/club/market` 直读 + disp，缺文件显式空态；_EVENT_WIRED 注册。
- 前端 `evMarketCards`：三方 RPS/命中率对比条（最优标绿）+ 诚实层结论文案
  （闭盘聚合临场信息流，模型结构上不可能稳定胜出，禁止衍生投注建议）+
  赛季末周逐场对照表（实际赛果列绿粗、argmax 星标）+ 全口径说明与时间戳。

### 验证
- 五联赛实跑：n=290-363/联赛，闭盘 RPS 全部 ≤ 模型（E0 .2028 vs .2090 等），
  与 bt_club_market 三窗档案方向一致；D1/F1 开盘微好于闭盘，如实展示
  「最优」标注按实际数值。
- test_core 新增 `test_club_market_api`（结构/概率归一/跳过计数/诚实方向
  哨兵断言：闭盘劣于模型超 0.2pp 时报警人工复核），全量 **145 passed**。
- golden diff 五确定性端点逐字节一致。
- 截图：`docs/evidence/c5-laliga-market.png`（西甲市场对标 Tab 全貌，含
  瓦伦西亚 3-1 巴萨爆冷场三方全错、贝蒂斯场模型 69.2% 优于市场等真实细节）。
- **wc2026 市场 Tab 回归证据（如实说明）**：该 Tab 首载会经后端拉 ESPN 实时
  盘口，本机无代理 headless 环境下外网 SSL 握手失败导致截图挂起（既有环境
  限制，非本轮引入）。以两项静态证据替代：① git diff 证明 wc 市场前端函数
  （loadMarket/loadMarketDemo/#marketres）零改动（grep 命中为空）；② API
  golden diff 干净。浏览器回归截图待有网环境补做，标注「未验证（截图）」。

### 遗留问题
- C6 机制解读下轮项（共用世界杯正文 + 联赛差异章节：独立拟合/联赛内相对值/
  neutral=False/hl=365）。
- macOS 无 timeout 命令、headless Chrome 偶发挂起——已固化「后台起 Chrome+
  watchdog kill」截图模式。

## 2026-07-23（第八轮）C6 机制解读：共用引擎正文 + 联赛差异章节

### 落地方式说明（对照任务书「共用世界杯正文」）
实测世界杯「机制解读」Tab 是赔率机制交互工具（水位结构/分歧地图，读 odds.csv），
非静态方法论正文，且验收要求 wc 对应 Tab golden diff 不变——故「共用正文」落地为：
联赛侧新建一份方法论正文组件（内容与白皮书/回测档案口径一致：双泊松 GLM/
攻防参数/时间衰减/DC ρ 低比分修正/比分矩阵派生盘口/90 分钟口径/市场诚实层
结论），**一份实现五联赛共用**；世界杯侧 Tab 零改动。冲突与落地口径记录于此
（红线 5）。

### 做了什么
- 前端 `evExplainCards(o)` 参数化组件：① 预测机制正文（同一引擎四段：核心
  引擎/时间衰减/结算口径/市场诚实层）；② 联赛版 vs 世界杯版差异表七维
  （**每联赛独立拟合**（注入该联赛场数与数据截至）/**联赛内相对值**（含跨联赛
  待欧战锚点校准的诚实说明）/**neutral=False** 主场口径/**hl=365 vs 730**
  （注明回测裁决依据）/数据源/升降级 feeder/赛制推演形态）；footer 注明
  「同一份组件五联赛共用」与 backtest.md 依据。纯前端静态+overview 参数注入，
  零新 API。

### 验证
- test_core 全量 **145 passed**（本轮零 API 改动，无新增测试面）。
- golden diff 五确定性端点逐字节一致；世界杯机制解读 Tab 代码零触碰
  （改动仅联赛侧 explain 分支与新增函数）。
- 截图：`docs/evidence/c6-ligue1-explain.png`（法甲机制解读 Tab 全貌：正文
  四段 + 七维差异表，French Ligue 1 参数正确注入 2337 场/截至 2026-05-17）。

### 遗留问题
- C7 竞彩复盘联赛入口为下轮项（阶段 C 最后一项）：扩展方式接入
  jc_review（store_path 已按 event 隔离，P1-③ 就绪），不改世界杯逻辑（红线 2）。

## 2026-07-23（第九轮）C7 竞彩复盘联赛入口——阶段 C 七项全清

### 做了什么（红线 2 合规：jc_review.py 与 wc 端点逻辑零改动）
- **后端扩展分支** `_api_jc_review_club`：/api/jc_review 顶部按 event universe
  分流，club 事件走新分支——俱乐部模型按本联赛池解析（错拼给建议、跨联赛
  诚实拒绝）、neutral=False（联赛主客场）、is_knockout 恒 False（联赛无加时，
  竞彩 90 分钟口径天然一致）、存储 jc.store_path(event)（jc_review_<key>.json
  按赛事隔离，P1-③ 通道首次实装）。jc_review.py 纯函数经既有 path 参数调用，
  文件零改动；wc 分支代码原样。红线最严区全部沿用（无率/无跨场聚合/手填
  90 分钟/schema 断壁）。
- **前端组件搬移复用（零复制零重复 ID）**：联赛 jc Tab 把世界杯 #jcreview
  节点 appendChild 搬入联赛容器（移动非复制），`_jcEvent` 参数化三个 fetch
  站点（wc 不带 ?event=，请求与既往逐字节一致）；`jcRestoreHome()` 在一切
  会覆写容器的渲染路径（evShowTab/renderEventView/selectEvent-isWC）先归位
  组件，防节点随 innerHTML 覆写被销毁；club 模式摘除国家队 datalist、清空
  预填，回 wc 时恢复。

### 验证
- test_core 新增 `test_jc_review_club_entry`（monkeypatch 隔离存储：GET 预览
  neutral=False 且与 /api/club/predict 同口径 <1e-3、录入→填分→对账闭环、
  is_knockout=False、记录无「率」/ROI 字段（schema 断壁）、未知球队 400），
  全量 **146 passed**（wc jc 旧测试全绿=世界杯逻辑零回归）。
- golden diff 五确定性端点逐字节一致。
- 截图：`docs/evidence/c7-seriea-jc.png`（意甲 jc Tab：组件搬入 + 独立账本
  提示 + 俱乐部输入模式）、`c7-wc2026-jc-regression.png`（世界杯 jc Tab：
  组件归位，南非/加拿大默认值与文案原样零回归）。

### 阶段 C 收口清单
C1 看板（c1-epl-dashboard）/ C2 对阵分析（c2-seriea-matchup）/ C3 赛季推演
（c3-epl-seasonsim）/ C4 夺冠概率（c4-epl-champ）/ C5 市场对标
（c5-laliga-market）/ C6 机制解读（c6-ligue1-explain）/ C7 竞彩复盘
（c7-seriea-jc）——七项全部有 evidence 截图与 wc 回归证据（C5 的 wc 截图
以静态证据替代，见第七轮）。**阶段 C 宣告完成。**

### 遗留问题 / 下轮起点
- 下一阶段按推进序=阶段 D 运维自动化（8 月初英超开赛前硬期限）：D1 _CUR_END
  口径核查（26-27 开赛后才 +1，当前 2026 正确，先做跨赛季装载回归测试）→
  D2 每日抓取脚本 → D3 fixtures 未来赛程。阶段 B 仍顺延欧战前。
- events「25-26」命名待拍板；26-27 季前待附加赛名单（运行闸在位）。

## 2026-07-23（第十轮）阶段 D 开工：D1 跨赛季装载韧性 + 回归测试

### 做了什么（+1 动作本身按任务书注记留待 26-27 首轮 CSV 落地后执行）
- **实测找到三个翻季断点并修复（装载层韧性，红线 5：以实测为准）**：
  ① 新季 CSV 未发布（404 且无缓存）时 `clubdata.load` 整体崩 → 改为**最新一季
  装载失败降级告警、只用历史季**（历史季失败仍硬报错——缓存该在位，坏了必须
  暴露，不容许静默降级）；② 新季 CSV 为 0 字节（发布空窗）同路径降级；
  ③ `fetch(refresh=True)` 下载失败会异常中断（尽管本地缓存在位）→ 改为
  **刷新失败沿用缓存**并清理 .tmp 残件。
- **回归测试** `test_clubdata_rollover_resilience` 六断言：季码窗口滚动
  （season_codes(7,2027) 末码 2627）/ refresh 失败沿用缓存 / 404 降级数据面
  不变 / 0 字节降级 / 历史季损坏硬报错 / 新季初期残段下游 standings 正常
  （overview complete=False 前提成立）。全部离线（monkeypatch urlretrieve），
  不依赖网络。
- **翻季操作暗坑落档**：`season_codes` 的 `end_year=_CUR_END` 默认值在 def 时
  绑定——真实 +1 流程=改源码常量后**重启进程**；测试/脚本里 monkeypatch
  `_CUR_END` 不会生效，勿踩。

### 验证
python3 -m pytest test_core.py -q → **147 passed**；golden diff 五端点一致；
新韧性路径的三种降级输出均在测试中实际触发（非预期式断言）。

### 遗留问题
- D1 的「_CUR_END +1」动作：26-27 首轮 CSV 落地（8 月上旬）后执行改源码
  +重启+`--refresh`，本轮韧性保证空窗期页面不崩。
- D2 每日抓取脚本为下轮项（football-data 增量 + ESPN，失败写日志，界面时间
  戳联动，连续实跑 2 次无报错才算完成——注意验收需真实运行两次）。

## 2026-07-23（第十一轮）D2 每日抓取脚本：两次实跑验收通过 + launchd 注册

### 做了什么
- **`daily_update.py`**：① 十联赛（五大+feeder）最新一季 CSV 强刷并报告
  before/after 场次与数据截止日；② fixtures.csv 强刷（休赛期 0 场/残留旧行
  如实记录）；③ ESPN 五大联赛当日完场计数（复用 live._fetch_json 代理回退；
  休赛期 0 场为正常态）；④ 全程写 `data/logs/daily_update.log`（追加式含
  traceback），任一硬失败 exit 1。
- **实测暴露并修复网络断点（红线 5）**：首跑发现 football-data 下载走系统
  代理 SSL 断流（Clash 节点抖动）——CSV 刷新被 D1 韧性兜住但 fixtures 硬失败；
  ESPN 因 live 层「代理失败回退直连」成功。修复=clubdata 新增 `_download`
  同款回退策略（默认代理→直连），fetch 与 load_fixtures 两站点切换，且
  fixtures 刷新失败时沿用缓存（与 fetch 同口径）。
- **界面时间戳联动（架构自动保证，实测确认）**：overview 每请求直读帧
  data_through；club 模型缓存按数据 mtime 指纹自动失效（get_club_model）——
  CSV 更新后接口与模型自动跟新，无需重启。
- **launchd 注册**：`com.melvin.worldcup-daily`（每日 09:00，stdout/err 落
  data/logs/daily_launchd.*），launchctl list 确认已加载（与生产实例
  com.melvin.worldcup-predictor 并存）。

### 验证（验收口径：连续实际运行 2 次无报错）
- 修复后连跑两次：**14:02:44 与 14:04:29 两轮均 exit=0 全部成功**——十联赛
  CSV 真实下载（直连回退生效）、fixtures 11 场（05-30~05-31 季末残留行，
  消费方按日期过滤的既档口径）、ESPN 五联赛全部响应（今日完场 0 场=休赛期
  正常）。日志留痕 data/logs/daily_update.log（含首跑失败记录，如实保留）。
- test_core **147 passed**；golden diff 五端点一致。
- launchd 定时触发（明日 09:00）属未来事件，**标注未验证**；脚本本体两次
  实跑已达验收标准。

### 遗留问题
- D3 未来赛程预测为下轮项：fixtures 数据已可拉（当前为季末残留行），休赛期
  显式空态+原因；26-27 赛程发布后自动出卡片。
- 首跑的系统代理 SSL 断流已绕过，但代理节点健康度属环境问题（Clash 侧），
  与项目无关，不再跟进。

## 2026-07-23（第十二轮）D3 未来赛程预测卡片——阶段 D 三项全清

### 做了什么
- `/api/club/overview` 增 `upcoming`：load_fixtures(code) 过滤未来 14 天，
  逐场附模型赛前概率（neutral=False）+ 期望进球 + B365 赛前盘透传；模型池外
  球队（如升班马早期）标 `no_model`；无场次时 `reason` 给显式原因（休赛期/
  赛程未发布，26-27 发布后自动出卡片）；赛程源异常不拖垮看板（reason 兜底）。
- 看板 Tab 新增「未来 14 天赛程预测」卡片（参数化五联赛共用）：开球时间/
  对阵/胜平负%/期望进球/概率条/B365 盘，池外队显示「暂无数据（该队当前模型
  样本不足）」，footer 全口径（来源+90 分钟+数据截至+非投注建议）。

### 验证
- test_core 新增 `test_club_overview_upcoming`（空态必有原因；monkeypatch
  合成 fixtures：概率归一/B365 透传/开球时间/池外队 no_model 且无盘口字段），
  全量 **148 passed**；golden diff 五端点一致。
- 截图两态：
  - `docs/evidence/d3-epl-upcoming-empty.png`：**真实现状**（休赛期空态+
    原因文案）——这是当前生产形态。
  - `docs/evidence/d3-epl-upcoming-demo.png`：**合成 fixtures 演示**（临时替换
    fixtures.csv 后截图，已还原原文件）——阿森纳 vs 切尔西 62/22/15%+盘口、
    考文垂场「暂无数据」、曼城 vs 利物浦 56/22/22%，验证有数据时的渲染路径。
    按红线 3 明示：此图为合成数据演示渲染，真实赛程渲染待 26-27 fixtures
    发布后自然验证（每日抓取已自动刷新该源）。

### 阶段 D 收口
D1 ✓（韧性+回归测试；_CUR_END+1 待 8 月新季 CSV）/ D2 ✓（两次实跑验收+
launchd 每日 09:00，定时触发标未验证）/ D3 ✓（本轮）。**阶段 D 宣告完成**
（两项 8 月后自然到期动作已在遗留清单跟踪）。

### 遗留问题 / 下轮起点
- 按推进序下一阶段=**阶段 B 实体层统一表**（欧战接入前必须完成）：B1 评估
  已有第四/五轮档案（物理单表 M 级、用户已裁决「做」），注意保险丝——若需
  动世界杯账本结构（predictions_*.json 等）必须暂停等拍板；B3 共用实现已
  裁决=manager.py 函数（勿造第二套），B3 主要是验证与测试锁定。
- 长期跟踪：_CUR_END+1（8 月）/ launchd 定时触发观测（明日 09:00 后查
  data/logs/daily_launchd.out）/ events「25-26」更名待拍板 / 26-27 preseason
  待附加赛名单。

## 2026-07-23（第十三轮）阶段 B 实体层统一表——B1/B2/B3 全清

### B1 现状与迁移成本评估（保险丝核查）
- 沿用第四/五轮档案：teams_zh 双命名空间语义达标，物理单表化为形式统一诉求，
  用户已裁决「做」。本轮实施方案将成本从 M 级压到 S 级：**TEAMS 统一表为
  唯一运行时事实源，CN/CLUB 降为派生兼容视图**——全部消费方（disp/to_en/
  测试直引 CN/CLUB）零改动。
- **保险丝核查：未触发**。改造只涉及 teams_zh.py 单文件，predictions_*.json
  验证账本、jc_review_*.json 复盘账本的结构与路径零接触（git diff 佐证），
  无需暂停等拍板。
- **任务书数字冲突（红线 5）**：任务书「336 国家队 + 144 俱乐部」，实测
  _NATIONAL_SRC=78（模型 257 队中有中文映射者；未映射回退英文为既有设计）、
  _CLUB_SRC=155（五大+feeder 全覆盖，A3 后含升班马候选）。统一表按实际
  规模构建，不虚构映射；测试断言按实测规模（≥70/≥150）。

### B2 teams 统一表
- teams_zh 重构：数据源段 `_NATIONAL_SRC`/`_CLUB_SRC`（authoring 用）→
  构建 `TEAMS = {en: {zh, flag, universe}}`（构建期 assert 跨宇宙零撞名）→
  派生视图 CN/CLUB + 新helpers `universe_of(en)` / `pool(universe)`；
  disp/_R 反查改读 TEAMS（注册序 national 先于 club，与旧 (CN,CLUB) 序等价，
  反查优先级不变）。双语映射双向保持；俱乐部池跨联赛共享/国家队池隔离语义
  由既有测试 + 新测试双锁。

### B3 账本层共用实现（任务书口径逐字验证）
- 共用实现=manager.py 过程数据函数（第四轮裁决，一份两宇宙）。本轮按任务书
  口径「分别用一场世界杯与一场联赛比赛验证输出正确性」重新实测（数据已含
  决赛与 25-26 全季）：
  - 世界杯场：Spain 近 6 轮 WWWWWW，最近一场 2026-07-19 决赛 1-0 Argentina
    （真实）；西 vs 阿 h2h 近 5 次 西 4 胜 阿 1 胜（决赛入账后更新，真实）。
  - 联赛场：Arsenal 近 6 轮 WWWWWL，最近一场 2026-05-24 客胜水晶宫 2-1
    （与积分榜卡片末轮 水晶宫 1-2 阿森纳 一致）；阿 vs 曼城 1 胜 3 平 1 负。
  - 既有锁定测试 test_matchfacts_shared_impl_both_universes /
    test_team_pool_cross_league_and_isolation 全绿。

### 验证
test_core 新增 `test_teams_unified_table`（表源一致/池隔离/universe 判定/
实测规模/双语往返 30 队抽验），全量 **149 passed**；golden diff 五端点
逐字节一致（disp 输出与旧实现完全相同）。**阶段 B 宣告完成。**

### 遗留问题 / 下轮起点
- 下一阶段=阶段 E 欧战接入：E1 选型实测（ESPN API vs openfootball，欧冠+
  欧联近 3-5 季，结论落 data-sources.md）——涉及外网实测，注意用代理回退
  策略；若两源均不可达则做阶段内离线项并如实记录。
- 长期跟踪不变：_CUR_END+1（8 月）/ launchd 观测 / events 更名 / 26-27 名单。

## 2026-07-23（第十四轮）E1 欧战数据源选型实测：ESPN 主源 + openfootball 备源

### 做了什么（全部真实拉取实测，非文档推断）
- ESPN uefa.champions / uefa.europa scoreboard 六个探针：欧冠 18-19/20-21/
  21-22/24-25 决赛、24-25 联赛阶段日与 1/4 决赛日、欧联 22-23/24-25 决赛——
  全部命中且比分与史实一致；**两回合标注原生**（leg 字段 + notes 合计比分
  与晋级方）；26-27 资格赛窗实测 0 场（新鲜度留观测，标未验证）。
- openfootball champions-league repo：2024-25 cl.txt/el.txt 实测可读（271/
  236 行文本），2023-24 遇代理 SSL 断流（可重试类）、目录 API 限流；纯文本
  需自建解析器、队名带 FC/国别后缀对齐成本高、无结构化 leg 字段。
- **裁决落 docs/data-sources.md 第八节**：ESPN 为 E2 主源（日期窗迭代回收，
  复用 live._fetch_json 代理回退），openfootball 备用/交叉验证；队名映射表
  （ESPN 显示名→football-data 拼写→中文）E2 建。

### 验证
探针输出见本条上方记录（决赛比分逐一与史实核对：利物浦 2-0 热刺/切尔西 1-0
曼城/巴黎 5-0 国米/塞维利亚 1-1 罗马等）；test_core **149 passed**（本轮零
代码改动，仅文档+实测）；docs/data-sources.md 新增第八节。

### 遗留问题 / 下轮起点
- E2 欧战账本：ESPN 日期窗迭代回收近 3-5 季欧冠+欧联 → 统一 match 模型
  （7 核心列 + competition 归属 + leg/tie 关系列）→ 队名映射表。回收脚本
  注意按比赛日窗口分块（欧战每季约 15-17 个比赛周，非逐日扫）。
- 长期跟踪不变。

## 2026-07-23（第十五轮）E2 欧战账本：五季欧冠+欧联落统一 match 模型

### 做了什么
- **`eurodata.py`**：ESPN 月窗回收（复用 live._fetch_json 代理回退）21-22 至
  25-26 共五季欧冠+欧联正赛（资格赛不收，口径注明）；**合并式落盘**（并集
  去重，网络抖动单窗缺口可重跑增量补齐——首版全量覆盖曾在第二跑丢场次，
  实测暴露后改）；原始 ESPN 名落缓存、映射在装载层（缓存不因映射演进失效）。
- **统一 match 模型**：7 核心列 + season/leg/agg_note；load() 生成 **tie_id
  两回合配对**（同季同赛事无序队对 + leg1/2，主客互换断言）、**决赛
  neutral=True**（每季每赛事末场）；**队名映射 ESPN_FIX**（约 70 条：五大
  俱乐部对齐 football-data 拼写复用 CLUB 中文映射，非五大保留 ESPN 原名）。
- 最终账本：**1552 场 / 195 对两回合 tie / 10 场决赛**——欧冠 125/125/125/
  189/189（旧制 96+29 与新制联赛阶段口径吻合），欧联 139/141/141/189/189。

### 验证
- test_core 新增 `test_eurodata_ledger`（schema/赛事归属/欧冠五季覆盖精确值/
  决赛数=10 且中立场/**已知决赛比分核对**：24-25 巴黎 5-0 国米、21-22 皇马
  1-0 利物浦、25-26 巴黎 1-1 阿森纳点球胜（agg_note 含 penalties）/两回合
  配对不变量逐 tie 断言/映射后 ESPN 原名零残留），全量 **150 passed**。
- golden diff 五端点一致（欧战账本独立成库，未触碰任何既有链路）。
- 25-26 决赛真实性即史实核对（阿斯顿维拉 3-0 弗赖堡夺欧联、巴黎点球胜
  阿森纳卫冕欧冠）。

### 口径与已知限制（如实）
- **ET 场次比分含加时**：ESPN scoreboard 比分为终局口径（如 25-26 决赛 1-1
  为加时后），与 90 分钟红线冲突面仅限淘汰赛次回合与决赛少数场——**E3 跨联赛
  校准将只用联赛阶段/小组赛场次（无加时可能，纯 90 分钟）规避**，落档待办。
- 欧战账本独立成库（data/euro/，入 git——历史静态数据+回收成本高），不进
  五联赛模型训练帧（E3 仅作锚点）。

### 遗留问题 / 下轮起点
- E3 跨联赛强度校准：以欧战小组/联赛阶段跨联赛交锋为锚，方法+回测证据落
  backtest.md；不显著则如实报告采保守方案。

## 2026-07-23（第十六轮）E3 跨联赛强度校准：欧战锚点显著有效（回测证据落 backtest.md 第七节）

### 做了什么
- `bt_crossleague.py`：基线（五联赛帧裸并=无校准）vs 锚点（+欧战账本连边
  合训）两模型，每季 as_of=9 月 1 日防泄漏，评测该季欧战小组/联赛阶段跨联赛
  交锋（leg=0 非决赛：纯 90 分钟，规避 ET 口径）；逐场 RPS 差 bootstrap 显著性。

### 结果（预设「可能不显著」被数据推翻——如实报告显著）
- 四留出季 194 场：RPS 0.2629→0.1972（**Δ−0.0657，95% CI [−0.0945,−0.0385]
  不含 0**），命中率 47.4%→61.3%，**四季逐季全部改善**（−0.0287~−0.0850）。
- 联赛刻度位移（E0 基准）：SP1 −0.387 / F1 −0.534 / D1 −0.554 / I1 −0.666。
- 裁决：E4 欧冠预测用**锚点合训模型**；联赛 Tab 维持每联赛独立模型零变化
  （分场景取舍，同 feeder 先例）。未验证维度如实记录（欧战无赔率源，缺
  市场对标；m0 为裸并对照非市场基线）。

### 验证
bt_crossleague.py 实跑输出见上（全部数字为实测）；方法+表格落
docs/backtest.md 第七节；test_core **150 passed**（研究脚本旁路，主链零改动）。

### 遗留问题 / 下轮起点
- E4 欧冠预测接线（阶段 E 收官项）：锚点合训模型 + 两回合制（tie 合计晋级：
  两回合 90 分钟比分卷积 + 平局加时/点球近似——可复用国家队 advancement_paths
  的 加时 xG×⅓ 泊松 + 点球 50% 先验口径）+ 晋级树状图形态复用；界面欧冠 Tab
  （events 注册表加 ucl 条目）；验收同 C 通用标准。25-26 欧冠已完赛：可做
  回溯模式（同联赛 Tab 口径），26-27 待赛程。

## 2026-07-24 · A1 前端正确性修复包（渲染世代护栏 + fixtures SWR + 七项评审缺陷）

### 做了什么（templates/index.html + clubdata.py，含沿用上一会话中断前的半成品并补齐验证）
- **P0 渲染世代护栏**：`_evEpoch` 计数器 + `evSetContent(ep,html)` 作为异步写
  `#ev_content` 的唯一出口——迟到响应按世代丢弃，覆写前先 `jcRestoreHome()`
  归位竞彩复盘单例（防 appendChild 搬移的 #jcreview 被 innerHTML 销毁导致两侧
  jc 永久失效）；jc 分支 `jc_home/jc_away` 加空值护栏。
- **P0 overview 请求去阻塞**：clubdata.load_fixtures 超龄改 stale-while-revalidate
  （旧缓存立即返回，后台线程单飞 `_FX_REFRESH_LOCK` 重拉；显式 refresh/冷启动仍
  同步）；前端 evGet 改缓存 in-flight Promise（并发共享同一请求，失败/not_wired
  不留缓存），另存 `_<kind>` 同步副本供 jc 默认日期等轻量消费。
- **P1**：loadEvents 失败清 `_evLoadP` 可重试（selectEvent/renderEventView 入口
  重拉）；evGet 识别后端 not_wired 占位（抛 notWired 错，渲染「接线尚未完成」
  卡，不当正常数据缓存）。
- **P2**：DataScheduler wc 侧任务加 `CUR_EVENT==='wc2026'` 闸（防联赛 Tab
  data-t='market' 与调度任务名撞名误触发）；matchup 自动预填加 defaultValue
  未动护栏（慢响应不覆盖用户手输）；联赛 jc 默认日期改取 overview.data_through
  （去硬编码 '2026-05-24'）；无 hash 默认落地 /api/events 状态排序第一位赛事
  （wc2026 已归档不再恒为默认）。

### 验收证据
- pytest 150 passed（基线不减）；node --check 内联 JS 语法通过。
- golden：/api/ratings /teams /verify /config /champ_ci ?event=wc2026 重启前后
  五端点逐字节一致（cmp 实测 IDENTICAL×5）。
- kickstart 重启后 curl 冒烟：/api/events 0.03s、/api/club/overview?event=epl2526
  0.12s；SWR 实测——touch 把 fixtures.csv 拨老 4 天后请求仍 0.109s 即返，
  后台线程 20s 内完成刷新（mtime 更新为当前时刻）。
- 截图（Read 实看确认）：docs/evidence/a1-epl-board.png（看板：空态赛程卡+
  最近完赛轮+终表）、a1-epl-matchup.png（对阵分析自动预填阿森纳 vs 曼城
  42.9/27.7/29.4 + 矩阵 + 过程数据）、a1-epl-board-375.png（375px 无崩坏）、
  a1-wc2026-verify-regression.png（wc 看板 104 场账本回顾模式零回归）；
  另实测无 hash 落地=英超看板（状态排序第一位）。
- 残留不动：bt_ucl.py（344 行未跟踪，属 E4 欧冠任务）未提交，留给对应 Agent。

## 2026-07-24 A2 视觉/身份/移动端修复包（templates/index.html 单文件）
- P1 赛事身份化页头：新增 evApplyIdentity()——切赛事时同步 document.title 与
  header h1/副标题；wc2026 恢复开局从 DOM 捕获的静态默认值（逐字节不变），联赛显示
  事实行（如「英超 25-26 · football-data.co.uk · 每联赛独立模型 hl=365」），nl2026
  为国家队口径（martj42 · hl=730）。挂点：selectEvent(isWC 分支) + renderEventView
  （meta 就绪后）。
- P1 375px 积分榜：≤430px 隐藏 胜/平/负 三列（.ev-standings nth-child(4-6)，参考
  .vrow 列裁剪模式），「积分」列默认可见（实测 pts_visible=true，全表无需横滚）；
  新增 .hscroll 共用类（右缘渐隐提示，local 盖布+scroll 光晕），联赛侧全部 8 处
  overflow-x:auto 表格/图容器统一换用。
- P2 视觉一致性：evWdlBar 三色改 var(--wdl-h/d/a) token；evPredForm 出预测按钮加
  class="go"；中立场 label 套既有 .chk 类+nowrap——顺带修出一个实缺陷：原 label 未用
  .chk，checkbox 吃全局 input{width:100%;padding:11px} 被撑到 59px、「中立场」文字被
  挤出 label 盒盖在按钮下不可见（CDP Range rect 实证），套 .chk 后 input 13×13、文字
  与按钮同排正常显示。renderEvbar 渲染后对 .ev.on 执行 scrollIntoView(nearest)。
- P3 evLineChart：容器加 .evchart 类，evSetContent 写入后统一 scrollLeft=scrollWidth，
  手机默认看到赛季末端（390px 实测 atEnd=true，05/18 末端可见）。
- P2 跨联赛旧文案：机制解读差异表「待欧战锚点校准/未完成前诚实拒绝」改为事实表述
  （E3 校准回测已完成 RPS 0.2629→0.1972 见 backtest.md 第七节；欧冠待 E4 接线开放；
  联赛 Tab 数字仍联赛内相对值、接线前跨联赛对阵仍拒绝——拒绝行为不变仅更新状态）。
- 验收：150 测试全绿×2；golden 五端点 ?event=wc2026 重启前后逐字节一致（两次重启均
  diff 干净）；kickstart 重启后 CDP 截图五张入库并 Read 实读确认——a2-epl-board-desktop
  （身份化页头+十列积分榜）、a2-epl-board-375（积分列可见）、a2-epl-matchup-375
  （按钮深色/中立场同排）、a2-epl-champ-390（曲线默认最右端）、
  a2-wc2026-desktop-regression（title/h1/副标题与静态默认逐字一致）；node --check
  内联 JS 通过。残留不动：bt_ucl.py 留给 E4 Agent。

## 2026-07-24 施工 Agent B：eurodata 加固 + clubpredict 小修包（150→153 全绿）
- 评审六项逐一实证后落地：① eurodata.harvest 去重改 keep='last'（ESPN 事后修正
  比分可覆盖账本旧行）；② 完场 score 缺失改跳过+告警（不再静默 0-0 入账）；
  ③ 决赛标记加赛季完结闸（末场 ≥ 次年 5-15 决赛窗口 ∧ 距前一比赛日 >10 天的
  孤立收官场才标 neutral=True——口径依据五季账本实测：决赛 5-18~6-10 且距半决赛
  次回合 ≥13 天，赛中相邻比赛日 ≤8 天，赛季进行中不再误标）；④ club 模型 pkl
  改 mkstemp 同目录 + os.replace 原子写（clubpredict._atomic_dump，对齐国家队
  save_model_cache 模式）；⑤ clubpredict 两处「强度刻度未校准（P4）」旧文案改
  E3 完成后口径（锚点校准见 backtest.md 第七节、E4 待接线、本 CLI 仍拒跨联赛，
  行为零变化）；⑥ data-sources.md 第九节落档「欧战赔率源缺位」（欧冠市场 Tab
  按 MULTI_EVENT_PLAN §二整体隐藏，禁找未验证野源）。
- 验收：新增 3 测试（修正比分覆盖+缺分跳过 / 决赛闸三场景 / 原子写零残留）,
  153 全绿；真实账本 load() 前后一致（1552 场/390 tie/10 决赛）；跨联赛拒绝 CLI
  实测新文案；kickstart 重启后 wc2026 五端点 golden diff 逐字节一致。残留不动：
  bt_ucl.py 留给 E4 Agent。

## 2026-07-24 施工 Agent C：QA 基建包（golden diff 脚本化 + 五联赛参数化冒烟 + 滚动断言改判清单，153→158 全绿）
- 【P1】golden diff 脚本化：新增 scripts/golden_diff.sh（capture/diff 两模式，用法见
  脚本头注释）。覆盖确定性端点十个——wc2026 五端点 /api/ratings /api/teams /api/verify
  /api/config /api/champ_ci + club 五端点 /api/club/overview /api/club/predict
  /api/club/seasonsim /api/club/market /api/jc_review（GET 模型预览），各 event=epl2526；
  随机/实时端点明确排除并在脚本内注释原因（/api/bracket /api/champions=蒙特卡洛抽样、
  /api/dashboard /api/live=ESPN 实时、/api/market*=外部盘口+as_of 训练、
  /api/xuanxue/board=账本滚动、/api/version=元信息）。已知限制已注明：club/overview
  的 upcoming 按「今天+14 天」窗口计算，before/after 快照须同日抓取。
  快照目录 data/golden/ 入 .gitignore（本地验收产物），脚本入库。
  验收：对生产实例（127.0.0.1:8000）实跑 capture 两次十端点全 200 且非空合法 JSON，
  diff 两份快照逐字节一致（同时验证了端点确定性），exit code 语义正确（干净=0）。
- 【P2】五联赛参数化冒烟：test_core.py 新增 test_club_overview_all_leagues_smoke
  （@parametrize 五赛事）——此前 club API 测试仅打 epl2526，注册表 laliga2526/
  seriea2526/bundes2526/ligue12526 的 data 字段若手误接错联赛码，150 测试仍全绿。
  现每联赛断言 /api/club/overview 的 code 与注册表一致、ranking 非空、standings
  队数=联赛规模（E0/SP1/I1=20，D1/F1=18）。最小断言集，五参数化用例合计 <10s。
- 【P1】26-27 赛季滚动断言改判清单（评审行号漂移约 +85，已逐条 Read 核实实际位置；
  本轮只登记+行内注释锚点「⚠️ 26-27 滚动改判清单#N」，不改断言；到期改判须与
  clubdata._CUR_END+1 同 commit、按红线 4 有据改判并在本文件登记理由）：
  | # | 位置（本轮 commit 后行号） | 断言内容 | 到期改判方向 |
  |---|---|---|---|
  | 1 | test_core.py:1710（test_clubdata_rollover_resilience ③） | df.date.max()=="2026-05-24" | 26-27 CSV 落地后缓存在位，monkeypatch 掉的下载失败不再挡住 2627 缓存读取 → 打红。改判方向=把「已完结季末日」抽成与 _CUR_END 配套维护的测试常量，或断言 max>=该常量（口径化） |
  | 2 | test_core.py:1718（同测试 ④ 0 字节分支） | df2.date.max()=="2026-05-24" | 同 #1，两处同 commit 改 |
  | 3 | test_core.py:1884-1894（test_club_overview_api 四断言） | standings complete is True / played==38 / 末三名={West Ham,Burnley,Wolves} / latest_matchday.date==data_through | 26-27 开赛后 overview 的 standings 切到当季进行中 → complete=False、played<38、降级三队与末轮日语义全变。改判方向=参数化：终表类断言固定用 25-26 季切片（或 complete 为 True 时才断言终局），进行中季只断言结构（rows=20、pts 降序） |
  | 4 | test_core.py:2078（test_nl2026_predict_unlocked） | nl2026 db_matches==658 | 26-27 欧国联 9 月开打、ESPN 新完场入库后 658 增长 → 改判方向=口径化 db_matches>=658 |
  - 另核实无需登记：test_core.py:1695 season_codes(7, 2027) 显式传 end_year 参数、
    与 _CUR_END 解耦，滚动后仍成立；:1877 data_through>="2025-05-01" 为下界口径天然免疫。
- 验收：/opt/anaconda3/bin/python3 -m pytest test_core.py -q → **158 passed**
  （基线 153 + 本轮参数化 5）；golden 脚本实跑产出 data/golden/c-run1 与 c-run2
  两份快照且 diff 干净。残留不动：bt_ucl.py 未跟踪文件留给 E4 Agent。

## 2026-07-24 主控收口（7-Agent 评审轮完结）
- 本轮全貌：7 角色评审 + 3 透镜交叉裁决 → 四个修复包顺序施工（A1 前端正确性
  8a2a0d8 / A2 视觉身份移动端 40a76e3 / B eurodata 加固 0601298 / C QA 基建
  776071c）+ bt_ucl E4a 前置回测（a8c46fc，backtest.md 第八节）。
- 最终验收：pytest 158 passed（主控独立复跑确认）；golden 快照 diff 干净（Agent C）。
- E4a 闸门结论（第八节）：单场欧战胜平负两层显著可上 UI；tie 晋级概率无背书、
  只能实验性标注或带宽提示；锚点训练帧维持全量。
- 裁决延后 4 项：跨赛季归档浏览 / 26-27 upcoming 文案预检 / _odds_scheduler
  归档感知 / nl2026 赛制测试占位（各自到期条件见评审档）。
- ⚠️ 待用户拍板：events 五联赛条目更名（25-26→26-27）。三透镜一致 P0、
  8-08 英超开赛前为零迁移成本窗口；建议改 key（如 epl2627）+ 旧 key alias。
  未拍板前任何 Agent 不得擅改。
- 队列（下轮接手顺序）：E4a 引擎+API（tie 概率按第八节降级）→ E4b 前置
  Tab 装配 kind+tabs_off 配置驱动重构 → E4b 欧冠 Tab（makeBracket 工厂化、
  wc 树零触碰）→ README 三语文案包（等更名拍板）→ nl2026 开赛前补全（9-03）。
