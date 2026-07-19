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
