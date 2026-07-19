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

### 遗留问题 / 下一步
- [ ] P1 接线（决赛赛果回补后动工，照 `docs/P1_WIRING_CHECKLIST.md` 五步）：event 上下文 → live/espn 参数化 → 账本隔离 → L0 切换器 → nl2026 壳。
- [ ] 链路打通验收件：浏览器截图可见非世界杯赛事预测卡片，存 `docs/evidence/`（待 P1-④）。
- [ ] P2（8 月初英超开赛前）：英超 web 接线、每日抓取脚本、`clubdata._CUR_END` +1。
- [ ] 未验证项：每日定时抓取脚本（赛季未开，未做）；可靠性曲线出图（未做）；欧冠两回合制（P4 研究项，未做）。
- 任务书与既有裁决的冲突已在 diagnosis.md 第五节勘误（数据源不重选、DC 基线已超额完成）。
