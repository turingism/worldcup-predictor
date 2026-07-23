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
