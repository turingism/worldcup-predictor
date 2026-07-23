# /loop 任务进度记录（世界杯预测器 → S 级联赛比分预测器）

体例：每轮记录做了什么、如何验证、证据路径、遗留问题。「未验证」按纪律如实标注。

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

### P2 清单更新（重排后）
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
