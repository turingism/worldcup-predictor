<!-- 本文档=2026-07-25 Codex 评审轮的定稿需求：Codex 出稿 + Claude Code 三处修正后由 Codex 正式采纳。
     施工方 Claude Code；基线 HEAD=9043359 / test_core 160 passed。第 10 节为定稿修正案，与前文冲突时以第 10 节为准。 -->

# 多赛事比分预测器下一轮升级需求

版本：2026-07-25  
仓库：`~/worldcup-predictor`  
基线：`HEAD=9043359`，`test_core.py` 160 passed  
实施方：Claude Code  
评审结论：Codex 与 Claude Code 已达成一致

---

## 1. 总目标

按以下顺序完成升级：

1. **P0-A：英超 26-27 赛前冻结链路**
2. **P0-B：事件能力正向契约重构**
3. **P0-C：欧国联 26-27 最小可运行壳**
4. **P1-A：欧冠单场模型引擎与 API**
5. **P1-B：欧冠历史回顾 Tab**
6. **P2：双份 skill、内部文档及三语 README 收口**

硬期限：

- 英超首轮：2026-08-08
- 欧国联开赛：2026-09-03

---

## 2. 全局不可突破约束

### 2.1 模型裁决

- 国家队模型固定 `half_life=730`。
- 俱乐部模型固定 `half_life=365`。
- 五大联赛 Tab 继续使用各联赛独立模型。
- 欧战跨联赛预测使用“五大联赛国内帧 + 欧战锚点”合训模型。
- 国家队、单联赛俱乐部、欧战三个模型宇宙不得混路由。
- 不重做已归档负结论：
  - Elo 进入主模型；
  - 球队身价；
  - `nb_alpha`；
  - ρ 缩放；
  - 淘汰赛保守修正；
  - E1 并入英超单场模型；
  - ET 污染剔除。
- 任何新增模型或参数变体必须通过时序 as-of 回测；失败即落负结论，不得硬上线。

### 2.2 产品与合规

- 不输出投注建议、跨场组合或买入指令。
- `jc_review` 不接入欧冠 tie 推演。
- `explainer`、`jc_review` 不产生跨场聚合，不输出任何“率”类描述性聚合。
- 不使用“稳赚、必中、已校准、高可信、市场优势”等表述。
- 界面正文和数据区不新增 emoji；Tab 栏和既有功能图标位除外。
- 不实现走地、滚球、秒级概率或下注相关功能。
- 欧战没有闭盘赔率源，不得暗示市场对标“即将补齐”。

### 2.3 账本

- 账本按赛事、赛季隔离。
- 任何赛事别名只用于入口解析，不得成为账本名、缓存身份或响应中的规范 event key。
- `no_model` 不得写入伪预测数字。
- `retro=true` 与真实赛前冻结记录必须严格区分。
- 开球后的赛前预测内容不得修改。

### 2.4 空态协议

统一使用三种业务状态：

```json
{"status": "ok"}
```

```json
{
  "status": "no_model",
  "reason_code": "outside_calibrated_pool",
  "missing_teams": ["..."],
  "scope": "top5_plus_euro_anchor"
}
```

```json
{
  "status": "no_fixtures",
  "reason_code": "schedule_unpublished"
}
```

`no_model.reason_code` 仅允许：

- `outside_calibrated_pool`
- `insufficient_history`
- `unknown_team`
- `mapping_missing`

`no_fixtures` 属于赛程层，不得混入 `no_model`。

---

# 3. P0-A：英超 26-27 赛前冻结链路

## 3.1 目标

在 26-27 当季 CSV 尚不存在、当季已赛场次为 0 的情况下，仅依赖：

- 历史赛季 CSV 训练的 E0 模型；
- `football-data.co.uk/fixtures.csv` 未来赛程；

生成真实的赛前冻结账本：

```text
data/predictions_epl2627.json
```

不得等待 `E0_2627.csv` 出现后才工作。

## 3.2 文件与模块

新增：

```text
clubverify.py
scripts/club_freeze.py
```

修改：

```text
clubdata.py
verify.py
daily_update.py
events.py
test_core.py
docs/README-dev.md
docs/progress.md
```

如仓库管理 launchd 配置，新增：

```text
ops/com.melvin.worldcup-club-freeze.plist
```

### `clubverify.py`

至少提供：

```python
freeze_event(
    event_key: str,
    fixtures: pd.DataFrame | None = None,
    now_utc: datetime | None = None,
    ledger: str | None = None,
) -> dict
```

返回：

```json
{
  "status": "ok",
  "event": "epl2627",
  "fixtures_seen": 10,
  "frozen_new": 10,
  "updated_prekickoff": 0,
  "skipped_no_model": 0,
  "skipped_started": 0,
  "ledger": ".../predictions_epl2627.json"
}
```

无赛程时：

```json
{
  "status": "no_fixtures",
  "reason_code": "schedule_unpublished",
  "event": "epl2627"
}
```

### 冻结器约束

- 不得 import `schedule`。
- 不得实例化 `TournamentSimulator`。
- 不得读取世界杯小组、淘汰赛结构。
- 模型只通过 `clubpredict.get_club_model("E0")` 获取。
- 模型训练数据允许全部来自历史赛季。
- fixture 唯一身份按赛季内 `home_team + away_team` 生成；不得把比赛日期作为唯一身份，以免改期生成重复比赛。
- 改期比赛在新开球时间之前允许更新 `kickoff`，并保留 `rescheduled_from` 审计信息。
- 达到当前有效开球时间后，概率、xG、比分矩阵及 `frozen_at` 均不可修改。
- 并发读改写必须使用统一进程锁和原子替换，不得直接复用私有 `_LEDGER_LOCK`。
- 可在 `verify.py` 增加公开的 ledger transaction helper，但不得改变世界杯账本格式和行为。

建议账本条目字段：

```json
{
  "event": "epl2627",
  "stage": "league",
  "home": "Arsenal",
  "away": "Man City",
  "kickoff_utc": "2026-08-08T19:00:00Z",
  "kickoff_bj": "2026-08-09 03:00",
  "date": "2026-08-09",
  "source": "football-data",
  "model_universe": "club_E0",
  "model_half_life": 365,
  "data_through": "2026-05-24",
  "retro": false,
  "frozen_at": "...",
  "p_home": 0.0,
  "p_draw": 0.0,
  "p_away": 0.0
}
```

### 时间口径

- `fixtures.csv` 的 E0 开球时间必须按明确的源时区解析，再转换成 UTC 和北京时间。
- 禁止把 naive datetime 直接与北京时间字符串比较。
- 上线前随机选择至少 3 场英超赛程，与 ESPN `eng.1` 的开球时间交叉核对。
- 三场换算后的差值均不得超过 5 分钟。
- 无法确定源时区时，不得启动自动冻结任务。

### 调度

`scripts/club_freeze.py` 至少支持：

```bash
/opt/anaconda3/bin/python3 scripts/club_freeze.py --event epl2627
```

生产任务每 3 小时运行一次。它可以使用缓存，但每次执行必须：

1. 检查 fixtures；
2. 获取历史模型；
3. 冻结新增赛程；
4. 输出结构化结果；
5. 以非零退出码报告硬失败。

`daily_update.py` 在刷新 fixtures 后也调用同一冻结函数，不得复制逻辑。

## 3.3 必须新增的测试

```text
test_clubverify_freezes_with_zero_current_season_results
test_clubverify_uses_historical_model_before_new_csv
test_clubverify_never_mutates_after_kickoff
test_clubverify_updates_rescheduled_fixture_before_kickoff
test_clubverify_event_ledger_isolated
test_clubverify_atomic_concurrent_freeze
test_clubverify_unknown_team_writes_no_fake_prediction
test_clubverify_empty_schedule_returns_no_fixtures
test_clubverify_bst_to_utc_and_beijing
test_daily_update_invokes_club_freeze
test_clubverify_does_not_import_worldcup_schedule
```

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_clubverify_freezes_with_zero_current_season_results \
  test_core.py::test_clubverify_uses_historical_model_before_new_csv \
  test_core.py::test_clubverify_never_mutates_after_kickoff \
  test_core.py::test_clubverify_updates_rescheduled_fixture_before_kickoff \
  test_core.py::test_clubverify_event_ledger_isolated \
  test_core.py::test_clubverify_atomic_concurrent_freeze \
  test_core.py::test_clubverify_unknown_team_writes_no_fake_prediction \
  test_core.py::test_clubverify_empty_schedule_returns_no_fixtures \
  test_core.py::test_clubverify_bst_to_utc_and_beijing \
  test_core.py::test_daily_update_invokes_club_freeze \
  test_core.py::test_clubverify_does_not_import_worldcup_schedule -q
```

## 3.4 完成判据

必须同时满足：

1. 合成 26-27 fixtures、删除或屏蔽 `E0_2627.csv` 后，冻结器退出码为 0。
2. 账本至少写入一场 `retro=false` 的比赛。
3. `data_through` 仍是 25-26 或更早历史数据日期。
4. 概率和为 `1 ± 1e-8`。
5. 同一 fixture 连续运行两次不增加重复条目。
6. 开球后再次执行，账本预测字段逐字节不变。
7. EPL、世界杯账本路径不同。
8. 3 场真实赛程与 ESPN 时间差均不超过 5 分钟。
9. 全量测试通过：

```bash
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
```

可观察产物：

```text
docs/evidence/p0a-epl-freeze-zero-season.json
docs/evidence/p0a-epl-kickoff-crosscheck.json
docs/evidence/p0a-epl-freeze.log
docs/evidence/p0a-epl2627-upcoming.png
```

截图要求：

- `1440×900`；
- 显示英超 26-27 看板的真实 upcoming；
- 日期为北京时间；
- 不得出现“使用当季已赛数据”等错误文案。

## 3.5 回滚条件

任一情况出现即停止生产调度，不得硬上：

- 必须有 `E0_2627.csv` 才能出预测；
- 开球时间源时区无法确认；
- 同一场比赛重复写入；
- 开球后预测被覆盖；
- 并发运行损坏或丢失账本；
- 冻结器进入世界杯 `schedule`/`TournamentSimulator` 分支；
- 未识别球队时仍产生概率。

回滚后保留现有联赛看板和手动单场预测，只关闭冻结调度。

## 3.6 既有裁决冲突与避让

- 可能冲突：E1 不得并入英超单场模型。  
  避让：冻结器只取 E0 单场模型。
- 可能冲突：账本按赛事隔离。  
  避让：路径只通过规范 event key 解析。
- 可能冲突：新赛季 CSV 尚未发布。  
  避让：fixtures 与训练帧解耦，不提前修改 `_CUR_END`。
- 可能冲突：世界杯行为零变化。  
  避让：新建俱乐部冻结器，不参数化改写 `verify.freeze()` 的世界杯赛制逻辑。

---

# 4. P0-B：事件能力正向契约

## 4.1 目标

删除 `tabs_off`、`isClub` 和赛事 key 特判，改成：

```python
kind
universe
tabs
capabilities
```

四个正交字段。

## 4.2 文件

修改：

```text
events.py
app.py
templates/index.html
test_core.py
docs/MULTI_EVENT_PLAN.md
docs/README-dev.md
```

## 4.3 Registry 契约

示例：

```python
"epl2627": {
    "kind": "league",
    "universe": "club_E0",
    "tabs": [
        "board",
        "matchup",
        "seasonsim",
        "champ",
        "market",
        "explain",
        "jc",
    ],
    "capabilities": {
        "single_match": True,
        "season_sim": True,
        "market": True,
        "verification": True,
        "live_polling": False,
        "tie_experimental": False,
    },
}
```

仅允许以下 capability：

```text
single_match
season_sim
market
verification
live_polling
tie_experimental
```

不得提前加入没有消费方的字段。

规则：

- `kind` 只描述赛事结构。
- `universe` 只用于后端模型池选择。
- `tabs` 决定 Tab 内容及顺序。
- `capabilities` 决定具体功能是否启用。
- 删除 `tabs_off`，不保留双轨兼容。
- `/api/events` 返回规范化后的 `tabs` 和六个完整 capability。
- 所有 capability 必须有真实消费代码及测试。
- registry 在测试期执行 schema validation：
  - 缺字段失败；
  - 未知 capability 失败；
  - 重复 Tab 失败；
  - `market=false` 却包含 `market` Tab 失败；
  - `season_sim=false` 却包含 `seasonsim` Tab 失败；
  - `tie_experimental=true` 但非淘汰赛结构失败；
  - ledger 文件名重复失败。

### 前端约束

- 删除 `LEAGUE_TABS` 的固定全量装配。
- 由 `/api/events[].tabs` 按顺序渲染。
- 不得出现 `key === 'nl2026'`、`key === 'wc2026'` 等赛事字面特判。
- 默认赛事如需识别，由后端注入 `DEFAULT_EVENT` 或 `is_default`，不得写死 key。
- 删除 `isClub`。
- 单场预测表单调用统一 `/api/predict?event=...`。
- 后端根据 `universe` 路由模型；前端不得根据 universe 决定使用哪个预测函数。
- 旧 `/api/club/predict` 暂时保留兼容，但新 UI 不再调用。
- `live_polling=false` 时不得建立 interval、WebSocket 或重复 fetch。

## 4.4 测试

新增：

```text
test_event_registry_schema_valid
test_event_registry_rejects_unknown_capability
test_event_registry_rejects_duplicate_tabs
test_event_registry_rejects_capability_tab_conflict
test_event_registry_ledgers_remain_unique
test_api_events_exposes_positive_capabilities
test_tabs_follow_registry_order
test_unified_predict_dispatches_by_universe
test_frontend_has_no_event_key_special_case
test_frontend_has_no_isclub_or_tabs_off
test_live_polling_capability_is_consumed
```

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_event_registry_schema_valid \
  test_core.py::test_event_registry_rejects_unknown_capability \
  test_core.py::test_event_registry_rejects_duplicate_tabs \
  test_core.py::test_event_registry_rejects_capability_tab_conflict \
  test_core.py::test_event_registry_ledgers_remain_unique \
  test_core.py::test_api_events_exposes_positive_capabilities \
  test_core.py::test_tabs_follow_registry_order \
  test_core.py::test_unified_predict_dispatches_by_universe \
  test_core.py::test_frontend_has_no_event_key_special_case \
  test_core.py::test_frontend_has_no_isclub_or_tabs_off \
  test_core.py::test_live_polling_capability_is_consumed -q
```

静态验收：

```bash
! rg -n "tabs_off|isClub|['\"](wc2026|nl2026|epl2627)['\"]" templates/index.html
! rg -n "_EVENT_WIRED\\.setdefault\\(['\"]" app.py
```

## 4.5 Golden 验收

施工前：

```bash
scripts/golden_diff.sh capture data/golden/p0b-before
```

施工后重启生产实例，再执行：

```bash
scripts/golden_diff.sh capture data/golden/p0b-after
scripts/golden_diff.sh diff data/golden/p0b-before data/golden/p0b-after
```

要求：

- WC 五端点逐字节一致；
- club 五端点逐字节一致；
- `/api/events` 允许因新契约变化，不纳入旧 golden。

截图：

```text
docs/evidence/p0b-epl-tabs-desktop.png
docs/evidence/p0b-nl-tabs-mobile.png
```

移动端尺寸：`390×844`。

## 4.6 回滚条件

- WC 或 club 既有十个 golden 端点出现非预期差异；
- 前端仍需依赖赛事 key 才能装配；
- `tabs_off` 与 `tabs` 被迫双轨长期存在；
- 为消除 key 特判而必须重写世界杯全部 DOM；
- capability 无消费方或同一事实仍在多个位置维护。

出现上述情况时，回滚 P0-B，保留 P0-A 的显式 `--event epl2627` 调度，不阻塞赛前冻结。

## 4.7 裁决冲突

- 可能冲突：世界杯 golden 零变化。  
  避让：保留旧 API 和默认事件兼容层。
- 可能冲突：不写 if 森林。  
  避让：Tab 和功能由正向契约驱动。
- 可能冲突：空转元数据漂移。  
  避让：只允许六个有消费方的 capability。

---

# 5. P0-C：欧国联 26-27 最小可运行壳

## 5.1 目标

在 9 月 3 日前交付：

- 欧国联赛事入口；
- 国家队单场预测；
- 共用经理人分析；
- 赛程未发布时的 `no_fixtures`；
- 赛程发布后的看板、赛前冻结和按赛事账本；
- 无赛程时零轮询。

## 5.2 文件

新增或抽取：

```text
eventmatch.py
intlverify.py
```

修改：

```text
events.py
app.py
live.py
templates/index.html
manager.py
test_core.py
daily_update.py
```

允许使用其他等价模块名，但不得把欧国联逻辑直接堆入 `app.py`。

## 5.3 功能要求

### 单场预测

统一入口：

```http
GET /api/predict?event=nl2026&home=西班牙&away=法国
```

后端：

- 根据 `universe=intl` 获取国家队模型；
- 使用 `half_life=730`；
- 调用 `manager.py` 共用的近期战绩、交手和强度函数；
- 不复制一套 `nl_manager` 算法。

### 赛程

- ESPN league code 使用 registry 的 `uefa.nations`。
- 无赛程时返回：

```json
{
  "status": "no_fixtures",
  "reason_code": "schedule_unpublished",
  "event": "nl2026",
  "poll_after_seconds": 0
}
```

- 前端收到 `poll_after_seconds=0` 后不得继续轮询。
- 赛程上线后才把 `live_polling` 激活为 `true`。
- 激活 capability 必须与实际接线在同一 commit 完成。

### 账本

```text
data/predictions_nl2026.json
```

不得与世界杯共用。

赛程发布后，需在首场开球前完成真实冻结；无赛程时不得创建伪比赛或空数字。

## 5.4 测试

```text
test_nl2026_matchup_uses_national_universe
test_nl2026_matchup_reuses_manager_payload
test_nl2026_no_fixtures_is_not_no_model
test_nl2026_no_fixtures_disables_polling
test_nl2026_ledger_isolated_from_wc
test_nl2026_freeze_never_crosses_event_ledger
test_nl2026_registry_has_no_key_specific_frontend_branch
```

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_nl2026_matchup_uses_national_universe \
  test_core.py::test_nl2026_matchup_reuses_manager_payload \
  test_core.py::test_nl2026_no_fixtures_is_not_no_model \
  test_core.py::test_nl2026_no_fixtures_disables_polling \
  test_core.py::test_nl2026_ledger_isolated_from_wc \
  test_core.py::test_nl2026_freeze_never_crosses_event_ledger \
  test_core.py::test_nl2026_registry_has_no_key_specific_frontend_branch -q
```

## 5.5 完成判据

- `/api/predict?event=nl2026` 返回正常三向概率，和为 `1 ± 1e-8`。
- `model_half_life=730`。
- manager 响应 schema 与世界杯同源，不存在复制实现。
- 无赛程时浏览器网络面板在首次响应后不再请求欧国联赛程。
- 赛程发布后，至少一场比赛在开球前写入 `predictions_nl2026.json`。
- 世界杯账本逐字节不变。

产物：

```text
docs/evidence/p0c-nl2026-matchup.png
docs/evidence/p0c-nl2026-no-fixtures.png
docs/evidence/p0c-nl2026-network-zero-polling.json
docs/evidence/p0c-nl2026-freeze.json
```

## 5.6 回滚条件

- 欧国联请求错误落入俱乐部模型；
- 必须复制 manager 算法才能工作；
- 无赛程时仍持续轮询；
- ESPN 队名映射冲突无法消除；
- 首场开球时间口径无法验证；
- 欧国联账本写入世界杯文件。

如赛程层失败，保留 matchup-only 壳和明确空态，不伪造赛程。

## 5.7 裁决冲突

- 国家队半衰期不得改为 365。
- 欧国联与世界杯可共用国家队模型，但不得共用赛事账本。
- 赛制不完整时不得借用世界杯括号结构。
- 不因欧国联接线修改国家队核心模型。

---

# 6. P1-A：欧冠单场模型引擎与 API

## 6.1 前置回测加固

先修改：

```text
bt_ucl.py
docs/backtest.md
```

新增：

- season-stratified bootstrap；
- leave-one-season-out；
- 每季、每覆盖层的：
  - RPS；
  - LogLoss；
  - 命中率；
  - 样本数；
  - 跳过数；
- 单场可靠性分箱。

### 统计口径

- seed 固定为 `42`；
- bootstrap 至少 `10000` 次；
- season-stratified bootstrap：先按季重抽，再在抽中的季内按场重抽；
- 保留原逐场 IID 结果，但必须明确标注为 IID；
- leave-one-season-out 指从评测汇总中依次移除一个留出季，不得重新用未来数据训练。

支持机器可读输出：

```bash
/opt/anaconda3/bin/python3 bt_ucl.py \
  --json docs/evidence/p1a-ucl-backtest.json
```

## 6.2 回测门槛

### 基线复现门槛

数据未变化时必须复现：

| 分层 | RPS | Δ vs 频率基线 | 容差 |
|---|---:|---:|---:|
| 双方均五大 | 0.1972 | −0.0360 | RPS ±0.0005，Δ ±0.0010 |
| 涉非五大可评样本 | 0.2079 | −0.0265 | RPS ±0.0005，Δ ±0.0010 |
| 涉非五大跳过率 | 55% | — | ±0.5 个百分点 |

### 新鲁棒性分级

**Green：允许进入正常研究型单场 UI**

- 两层 pooled ΔRPS 均 `< 0`；
- 两层 season-stratified 95% CI 上界均 `< 0`；
- leave-one-season-out 四次汇总 ΔRPS 均 `< 0`；
- 两层 LogLoss 均优于各自频率基线。

**Yellow：API 可落地，UI 必须标实验性**

- 两层 pooled ΔRPS 均 `< 0`；
- leave-one-season-out 至少 3/4 为负；
- 但 season-stratified CI 有一层包含 0。

**Red：不进入 UI**

任一情况成立：

- 任一层 pooled ΔRPS `>= 0`；
- leave-one-season-out 仅 2/4 或更少为负；
- LogLoss 相对频率基线反向恶化。

Red 时保留回测报告，记录负结论；不得为了上线调整参数。

## 6.3 模块与文件

新增：

```text
europredict.py
```

修改：

```text
events.py
eurodata.py
app.py
test_core.py
docs/backtest.md
docs/data-sources.md
```

缓存：

```text
data/euro/model_euro.pkl
data/euro/model_euro.meta.json
```

### 赛事注册

```text
ucl2526：归档回顾
ucl2627：新赛季
ucl → ucl2627 alias
```

账本：

```text
predictions_ucl2526.json
predictions_ucl2627.json
```

裸 `ucl` 不得成为账本名或缓存身份。

### 模型缓存指纹

指纹覆盖：

```text
data/club/E0_*.csv
data/club/SP1_*.csv
data/club/I1_*.csv
data/club/D1_*.csv
data/club/F1_*.csv
data/euro/euro_matches_raw.csv
```

并包含：

- 相对路径；
- 文件大小；
- `mtime_ns`；
- `half_life=365`；
- 模型 schema version；
- 队名映射 version；
- 数据截止时间；
- euro frame schema version。

要求：

- 路径集合排序后再计算；
- 任意一份输入变化后缓存必须失效；
- 并发首次请求只能训练一次；
- pkl 和 meta 均原子写；
- meta 记录训练场数、球队数、`data_through`、fingerprint。

## 6.4 API

统一单场入口：

```http
GET /api/predict?event=ucl2526&home=Arsenal&away=Paris%20SG
```

正常响应：

```json
{
  "status": "ok",
  "event": "ucl2526",
  "model_universe": "euro",
  "model_scope": "top5_plus_euro_anchor",
  "market_benchmark": "unavailable",
  "market_note": "欧战闭盘赔率源当前缺位",
  "p_home": 0.0,
  "p_draw": 0.0,
  "p_away": 0.0
}
```

不可评时返回 `no_model`，不得包含概率、xG、比分矩阵或默认 1/3。

UI 固定文案：

> 历史比分模型估计，未与欧冠闭盘市场完成对标。

禁用：

```text
已校准
高可信
市场优势
胜算可靠
```

## 6.5 测试

```text
test_ucl_backtest_reproduces_published_rps
test_ucl_backtest_reports_season_stratified_ci
test_ucl_backtest_reports_leave_one_season_out
test_ucl_backtest_json_schema
test_euro_model_cache_fingerprint_all_inputs
test_euro_model_cache_invalidates_on_euro_change
test_euro_model_cache_invalidates_on_domestic_change
test_euro_model_cache_atomic_and_singleflight
test_ucl_event_uses_euro_universe
test_ucl_alias_never_becomes_ledger_identity
test_ucl_predict_ok_schema
test_ucl_predict_no_model_has_no_numeric_prediction
test_ucl_no_model_reason_codes
test_ucl_market_benchmark_copy_is_honest
```

## 6.6 完成判据

- 回测达到 Green 或 Yellow。
- Red 时本阶段只能交付报告和内部 API，不得接 UI。
- 缓存输入任意修改一次后 fingerprint 必须变化。
- `ucl2526` 与 `ucl2627` 账本路径不同。
- 涉非五大请求的实际 `no_model` 占比与回测覆盖说明一致，不得宣传全覆盖。
- 全量测试通过。
- WC 和 club golden diff 干净。

产物：

```text
docs/evidence/p1a-ucl-backtest.json
docs/evidence/p1a-ucl-backtest.txt
docs/evidence/p1a-ucl-api-ok.json
docs/evidence/p1a-ucl-api-no-model.json
docs/evidence/p1a-ucl-cache-meta.json
```

## 6.7 回滚条件

- 新鲁棒性结果达到 Red；
- cache 输入变化后仍复用旧模型；
- `no_model` 被填成均匀概率；
- API 把单联赛模型用于跨联赛欧战；
- 归档比赛使用赛后数据却标成赛前预测；
- 文案暗示已完成市场对标。

回滚为“研究报告保留、UI 不接线”，不得换参数刷过闸门。

## 6.8 裁决冲突

- 欧战模型不能修改五大联赛 Tab 的独立模型。
- 不因覆盖率不足重新引入身价、Elo 或 E1。
- ET 行保持全帧训练。
- 无欧战赔率基线，不伪造市场结论。
- 历史展示必须遵守 as-of，不得用赛后全量模型伪装赛前结果。

---

# 7. P1-B：欧冠历史回顾 Tab

## 7.1 目标

- `ucl2526`：已完赛回顾模式；
- `ucl2627`：赛程未发布空态；
- 参数化复用括号渲染工厂；
- 世界杯括号及五个 golden API 零变化；
- tie 只做实验性描述，不展示精确晋级百分比。

## 7.2 文件

新增：

```text
docs/knockout-approx.md
```

修改：

```text
templates/index.html
app.py
events.py
eurodata.py
test_core.py
docs/backtest.md
```

如模板继续膨胀，可抽取：

```text
static/js/event-bracket.js
```

## 7.3 Bracket 工厂

把现有括号逻辑参数化为：

```javascript
makeBracket(container, rounds, options)
```

要求：

- 世界杯通过薄 wrapper 调用，原数据结构和视觉行为不变；
- 欧冠使用独立 round adapter；
- 不允许在 `makeBracket` 内出现 `ucl2526` 或 `wc2026`；
- 宽屏和移动端均不能溢出正文；
- 低端移动端不执行无意义的持续动画。

## 7.4 历史预测口径

`ucl2526` 已完赛比赛没有真实历史冻结账本，因此：

- 不得标为 `retro=false`；
- 不得称为“当时已冻结预测”；
- 历史模型结果必须使用比赛前的 as-of 训练窗；
- 统一标记：

```json
{
  "retro": true,
  "as_of": "早于该场开球的训练截止时间"
}
```

若无法提供无泄漏回溯结果，只展示真实赛果和当前模型的“当前实力反事实”，并明确它不是赛前预测。

## 7.5 tie 实验性展示

不进入：

- 主预测卡；
- 排序；
- 摘要；
- 正式验证账本；
- `jc_review`；
- 任何“率”类聚合。

默认折叠区允许展示：

- 两回合各自的单场胜平负；
- 合计净胜分布；
- 固定映射的描述性带宽。

带宽映射写死：

| 模型内部 p | 展示文案 |
|---:|---|
| `< 0.35` | 模型情景明显偏向 B 队 |
| `0.35 ≤ p < 0.45` | 模型情景轻微偏向 B 队 |
| `0.45 ≤ p ≤ 0.55` | 模型情景接近五五开 |
| `0.55 < p ≤ 0.65` | 模型情景轻微偏向 A 队 |
| `> 0.65` | 模型情景明显偏向 A 队 |

UI 不显示用于映射的精确 `p`。

固定说明：

> 两回合情景为实验性近似；现有回测未证明优于五五开或朴素净胜基线，不作为正式校准概率。

## 7.6 `ucl2627` 空态

赛程未发布时：

```json
{
  "status": "no_fixtures",
  "reason_code": "schedule_unpublished",
  "poll_after_seconds": 0
}
```

要求：

- 不训练轮询；
- 不启动 WebSocket；
- 不创建空账本；
- 不复制 25-26 bracket 假装新赛季；
- 页面明确显示“赛程未发布”。

## 7.7 测试

```text
test_make_bracket_accepts_wc_and_ucl_adapters
test_wc_bracket_wrapper_behavior_unchanged
test_ucl2526_archive_predictions_are_retro
test_ucl2526_archive_asof_precedes_kickoff
test_tie_band_mapping_boundaries
test_tie_ui_contains_no_exact_advancement_percentage
test_tie_is_excluded_from_verification_ledger
test_tie_is_excluded_from_jc_review
test_ucl2627_returns_no_fixtures
test_ucl2627_no_fixtures_starts_zero_polling
test_ucl_mobile_bracket_has_no_page_overflow
```

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_make_bracket_accepts_wc_and_ucl_adapters \
  test_core.py::test_wc_bracket_wrapper_behavior_unchanged \
  test_core.py::test_ucl2526_archive_predictions_are_retro \
  test_core.py::test_ucl2526_archive_asof_precedes_kickoff \
  test_core.py::test_tie_band_mapping_boundaries \
  test_core.py::test_tie_ui_contains_no_exact_advancement_percentage \
  test_core.py::test_tie_is_excluded_from_verification_ledger \
  test_core.py::test_tie_is_excluded_from_jc_review \
  test_core.py::test_ucl2627_returns_no_fixtures \
  test_core.py::test_ucl2627_no_fixtures_starts_zero_polling \
  test_core.py::test_ucl_mobile_bracket_has_no_page_overflow -q
```

## 7.8 截图证据

```text
docs/evidence/p1b-ucl2526-bracket-desktop.png
docs/evidence/p1b-ucl2526-tie-folded.png
docs/evidence/p1b-ucl2526-tie-expanded.png
docs/evidence/p1b-ucl2627-no-fixtures.png
docs/evidence/p1b-ucl2526-mobile-390x844.png
docs/evidence/p1b-wc2026-bracket-regression.png
```

截图中不得出现精确晋级百分比。

## 7.9 回滚条件

- 世界杯括号出现布局或交互回归；
- 归档比赛发生训练泄漏；
- tie 精确百分比进入主卡；
- `ucl2627` 空态仍发起轮询；
- 移动端出现页面级横向溢出；
- 为复用工厂必须修改世界杯赛事数据结构。

回滚时保留 P1-A API，欧冠 Tab 降级为比赛列表或暂不接线。

## 7.10 裁决冲突

- tie 负结论：用确定性带宽且不显示单点概率。
- 账本真实性：历史回放统一 `retro=true`。
- 竞彩红线：tie 不进入 `jc_review`。
- WC golden：通过 wrapper 保留既有行为。

---

# 8. P2：文档、skill 与 README 收口

## 8.1 必须同步的文件

```text
~/.claude/skills/worldcup/SKILL.md
~/.agents/skills/worldcup/SKILL.md
CLAUDE.md
docs/MULTI_EVENT_PLAN.md
docs/backtest.md
docs/data-sources.md
docs/knockout-approx.md
docs/progress.md
docs/README-dev.md
README.md
README.zh-CN.md
README.zh-TW.md
```

两份 `SKILL.md` 必须同步升版，最终内容逐字节一致。

验证：

```bash
cmp -s \
  ~/.claude/skills/worldcup/SKILL.md \
  ~/.agents/skills/worldcup/SKILL.md
```

## 8.2 文档必须反映的事实

- 产品已从世界杯预测器扩展为多赛事预测器。
- 五联赛规范 key 已是 26-27。
- 旧 25-26 key 仅为 alias。
- 国家队与俱乐部 half-life 分离。
- 欧战使用锚点合训模型。
- 欧冠单场覆盖边界及 `no_model`。
- tie 未通过正式概率闸门。
- 欧战闭盘市场基线缺位。
- EPL 和欧国联硬期限及运维入口。
- `_CUR_END` 的默认参数在函数定义时绑定。

## 8.3 `_CUR_END` 滚季操作

只有确认 `E0_2627.csv` 已发布且包含至少一场有效完赛记录后，才执行：

```python
_CUR_END = 2027
```

必须同一 commit 完成：

- 修改源码常量；
- 调整 26-27 滚动测试断言；
- 刷新数据；
- 验证模型 fingerprint 变化；
- 重启服务；
- 记录数据截止日期。

不得只 monkeypatch `_CUR_END` 验收。

## 8.4 三语 README

三份 README 结构和事实一致，至少包含：

- 支持赛事；
- 模型宇宙；
- 数据源；
- 已验证能力；
- `no_model` 与 `no_fixtures`；
- 欧冠 tie 限制；
- 合规边界；
- 本地运行与测试命令。

不要求逐句直译，但数字、事件 key、限制和命令必须一致。

## 8.5 完成判据

```bash
cmp -s ~/.claude/skills/worldcup/SKILL.md ~/.agents/skills/worldcup/SKILL.md
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
scripts/golden_diff.sh capture data/golden/final-after
scripts/golden_diff.sh diff data/golden/upgrade-before data/golden/final-after
```

静态检查：

```bash
! rg -n "epl2526|laliga2526|seriea2526|bundes2526|ligue12526" \
  README.md README.zh-CN.md README.zh-TW.md docs \
  ~/.claude/skills/worldcup/SKILL.md \
  ~/.agents/skills/worldcup/SKILL.md
```

上述命令允许在专门的 alias/迁移说明段命中；其他位置不得继续使用旧 key。

最终证据：

```text
docs/evidence/final-pytest.txt
docs/evidence/final-golden-diff.txt
docs/evidence/final-skill-cmp.txt
docs/evidence/final-production-events.json
docs/evidence/final-desktop.png
docs/evidence/final-mobile-390x844.png
```

## 8.6 回滚条件

- 两份 skill 内容不一致；
- README 与实际 `/api/events` 不一致；
- 文档宣称未通过的模型能力已上线；
- 文档把 tie 描述为正式晋级概率；
- 三语版本中的数字、事件 key 或限制互相矛盾。

文档不一致时不得宣布本轮完成。

---

# 9. 全局最终验收

## 9.1 自动测试

```bash
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
```

要求：全部通过，无 xfail 掩盖本轮功能，无网络偶发失败被静默当通过。

## 9.2 Golden

施工前必须先留：

```bash
scripts/golden_diff.sh capture data/golden/upgrade-before
```

最终：

```bash
scripts/golden_diff.sh capture data/golden/upgrade-after
scripts/golden_diff.sh diff data/golden/upgrade-before data/golden/upgrade-after
```

要求现有 WC 和 club 十个确定性端点逐字节一致。若某个端点因已批准的 event 字段规范化产生差异，必须：

1. 单独列出；
2. 做 JSON 结构 diff；
3. 证明唯一差异是规范 event 回显；
4. 不得直接重录 baseline 掩盖回归。

## 9.3 浏览器矩阵

至少实测：

| 视口 | 赛事 |
|---|---|
| 1440×900 | wc2026 |
| 1440×900 | epl2627 |
| 1440×900 | nl2026 |
| 1440×900 | ucl2526 |
| 1440×900 | ucl2627 |
| 390×844 | epl2627 |
| 390×844 | nl2026 |
| 390×844 | ucl2526 |

检查：

- 深链回填；
- alias 归一；
- Tab 顺序；
- 空态；
- 零轮询；
- 无正文 emoji 新增；
- 无页面级横向溢出；
- 切换事件后迟到请求不会覆盖当前页面；
- `no_model` 与 `no_fixtures` 文案不串。

## 9.4 完成定义

只有以下全部满足才可宣布完成：

- EPL 冻结器能在当季 0 场状态下工作；
- EPL 首轮前已生成真实 `retro=false` 账本；
- 事件能力契约无 key 特判；
- 欧国联至少 matchup 可用，赛程空态诚实；
- 欧冠单场回测达到 Green 或 Yellow；
- tie 不显示精确晋级百分比；
- `ucl2526`、`ucl2627` 按季隔离；
- 两份 skill 逐字节一致；
- 全量测试全绿；
- golden diff 无未解释变化；
- 规定截图与 JSON 证据齐全。

任一项缺失，不得以“核心功能已完成”替代整轮完成。

---

# 10. 定稿修正案（Claude Code 提出、Codex 采纳；与前文冲突以本节为准）

裁定：三条全部成立，均纳入定稿。你的修正比原文更可执行，也没有撞上既有裁决。以下文字作为对上一版 MD 的正式增补与替换；其余章节保持不变。

# 定稿修正案

## 修正一：限定“赛事 key 特判”的清理边界

### 裁定

接受你的收口。

原 §4.3 的“前端不得出现任何赛事 key 特判”过宽，确实会同时要求：

- 保留世界杯遗留 DOM 以维持 golden；
- 又清除这些 DOM 所依赖的世界杯身份判断。

两条要求冲突。P0-B 不重写世界杯旧页面结构，只清理和约束新的多赛事装配层。

### 替换 §4.3 前端约束

#### 新装配层约束

以下职责属于本轮“事件装配层”：

- 非默认赛事的 Tab 渲染和排序；
- capability 开关；
- 通用 API 路由；
- `no_model`、`no_fixtures`、`not_wired` 空态；
- 新赛事轮询启停；
- 通用单场预测表单；
- 新赛事 header identity。

事件装配层不得：

- 出现 `wc2026`、`nl2026`、`epl2627`、`ucl2526` 等赛事 key 字面分支；
- 通过 `isClub` 决定 Tab 或 API；
- 通过 `universe` 在前端决定调用哪个预测函数；
- 使用 `tabs_off`；
- 为新赛事新增 `key === ...` 或 `key !== ...` 分支。

默认赛事身份由 `/api/events` 返回：

```json
{
  "key": "wc2026",
  "is_default": true
}
```

`evApplyIdentity()` 改为读取 `meta.is_default`，不得比较 `meta.key === 'wc2026'`。

#### 本轮允许保留的世界杯遗留边界

以下既有世界杯专属逻辑不在 P0-B 重构范围：

```text
WC_SECTIONS
selectEvent() 内既有默认 DOM 切换
wcArchived()
wcTabActive()
世界杯 DataScheduler 双保险
旧单段世界杯深链兼容
```

约束：

- 允许保留既有世界杯 key 判断；
- 不得在这些遗留函数之外增加新的赛事 key 特判；
- 不得借“遗留兼容”之名把欧国联、欧冠或联赛逻辑放进去；
- 本轮不得重写世界杯八个 section 到通用装配层；
- 世界杯轮询双保险必须保留。

### 替换测试

删除原测试名：

```text
test_frontend_has_no_event_key_special_case
```

新增：

```text
test_event_assembly_has_no_event_key_literal
test_frontend_event_key_literals_confined_to_legacy_allowlist
test_ev_apply_identity_uses_is_default
test_frontend_adds_no_new_legacy_event_branch
```

测试口径：

- 提取事件装配函数体检查，而不是对整个 `index.html` 无差别 grep；
- 允许赛事 key 字面仅存在于明确的 legacy allowlist；
- allowlist 至少限定到具体函数，不得按整段文件或行号范围放行；
- `renderEventView()`、`evShowTab()`、capability/polling 决策函数、统一预测表单不得包含赛事 key；
- `evApplyIdentity()` 必须使用 `is_default`。

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_event_assembly_has_no_event_key_literal \
  test_core.py::test_frontend_event_key_literals_confined_to_legacy_allowlist \
  test_core.py::test_ev_apply_identity_uses_is_default \
  test_core.py::test_frontend_adds_no_new_legacy_event_branch -q
```

原全局 grep 改为：

```bash
! rg -n "tabs_off|isClub" templates/index.html
```

另由测试保证新装配层没有赛事 key，不再要求整个模板零命中。

### 回滚条件修正

保留原条件：

> 为消除赛事 key 特判而必须重写世界杯全部 DOM 时，回滚 P0-B。

补充：

> 若新装配层仍依赖具体赛事 key 才能工作，则 P0-B 未完成；但世界杯 legacy allowlist 内的既有判断不构成失败。

---

## 修正二：P0-A 扩展为五大联赛统一冻结链路

### 标题替换

原：

> P0-A：英超 26-27 赛前冻结链路

改为：

> P0-A：五大联赛 26-27 冻结与结算链路（EPL 8-08 为第一硬期限）

英超仍是最早的上线闸门，但代码、调度和测试必须参数化覆盖：

```text
epl2627
laliga2627
seriea2627
bundes2627
ligue12627
```

### 调度选择规则

P0-A 阶段初始选择：

```python
event["universe"].startswith("club_")
and events.status(key) in {"soon", "live"}
```

P0-B capability 契约完成后，选择规则收口为：

```python
event["universe"].startswith("club_")
and event["capabilities"]["verification"] is True
and events.status(key) in {"soon", "live"}
```

不得在最终调度脚本中维护五个 key 的手工列表。

### 批量执行结果

`scripts/club_freeze.py` 默认批量执行所有符合条件的赛事，并支持单赛事诊断：

```bash
/opt/anaconda3/bin/python3 scripts/club_freeze.py
/opt/anaconda3/bin/python3 scripts/club_freeze.py --event epl2627
```

批量响应示例：

```json
{
  "status": "ok",
  "events": {
    "epl2627": {"status": "ok", "frozen_new": 10},
    "laliga2627": {"status": "no_fixtures"},
    "seriea2627": {"status": "no_fixtures"},
    "bundes2627": {"status": "ok", "frozen_new": 9},
    "ligue12627": {"status": "no_fixtures"}
  },
  "hard_failures": 0
}
```

要求：

- 某个联赛 `no_fixtures` 不得拖垮其他联赛；
- 某联赛模型、映射、账本写入硬失败时，批量命令非零退出；
- 日志逐赛事输出，不能只有一个总成功；
- feeder 联赛不得被调度；
- 每个联赛仍使用自己的 `club_<code>` 模型；
- 五个账本互不相同。

### 时间验证扩展

每个实际启用自动冻结的联赛，都要与其 registry 中的 ESPN code 交叉核对至少 3 场开球时间。

验收标准：

```text
每联赛 3 场；
换算后时间差均 ≤5 分钟；
证据记录源时间、解析时区、UTC、北京时间和 ESPN 时间。
```

若某联赛尚无可核对赛程，可以保持 `no_fixtures`，但不得在未核对时间口径前启动该联赛自动冻结。

### 新增测试

```text
test_clubverify_scheduler_discovers_all_active_club_events
test_clubverify_scheduler_excludes_feeder_leagues
test_clubverify_parameterized_for_all_top5
test_clubverify_batch_failure_isolated_per_event
test_clubverify_ledgers_distinct_across_top5
test_clubverify_freezes_epl_and_second_league
```

### 完成判据替换

P0-A 代码完成必须满足：

1. 五个赛事均通过同一 `freeze_event(event_key)` 路径。
2. 合成 fixtures 测试覆盖五个模型路由。
3. 至少对 `epl2627` 和另一联赛真实或合成写出两个不同账本。
4. 两个账本均含 `retro=false` 的赛前预测。
5. 两个账本的模型 universe、联赛 code 和球队池正确。
6. 一个联赛 `no_fixtures` 不影响另一个联赛冻结。
7. 每个启用生产调度的联赛完成 3 场 ESPN 时间交叉核对。
8. 各联赛上线前分别检查其真实 fixtures；没有赛程时诚实保持 `no_fixtures`。
9. 英超必须在 8 月 8 日首场开球前产生真实冻结记录。
10. 其他四联赛必须在各自首场开球前产生真实冻结记录。

证据：

```text
docs/evidence/p0a-top5-freeze-batch.json
docs/evidence/p0a-top5-ledger-isolation.json
docs/evidence/p0a-epl-second-league-freeze.json
docs/evidence/p0a-top5-kickoff-crosscheck.json
```

### 回滚方式

回滚按赛事隔离：

- 某一联赛时区或映射未验证，只关闭该联赛冻结；
- 其他已验证联赛继续运行；
- 不允许因为法甲或意甲失败而回滚英超已通过的冻结器；
- 公共冻结核心出现账本覆盖、并发损坏或开球后改写时，五联赛全部停用。

---

## 修正三：P0-A 同阶段交付赛后结算闭环

### 裁定

接受。

只冻结不结算会留下不可验证账本，因此结算代码必须与冻结器同阶段交付。生产启用允许晚于冻结，因为首次结算必须等待 26-27 当季 CSV 出现。

### 新增接口

在 `clubverify.py` 增加：

```python
settle_event(
    event_key: str,
    results: pd.DataFrame | None = None,
    now_utc: datetime | None = None,
    ledger: str | None = None,
) -> dict
```

返回示例：

```json
{
  "status": "ok",
  "event": "epl2627",
  "frozen_entries": 10,
  "settled_new": 8,
  "already_settled": 1,
  "unsettled": 1,
  "result_corrections": 0
}
```

### 结算匹配

- 只读取 registry 对应联赛 code 的赛果。
- 结果必须先按 event window 限定赛季，防止近七季中相同主客对阵误匹配。
- 在同一赛事赛季内按 `home_team + away_team` 匹配冻结条目。
- 不得只按球队集合匹配，主客顺序必须一致。
- 结果源必须是已完赛且比分完整的当季 football-data CSV。
- 联赛结算口径固定为常规 90 分钟含补时，不存在加时和点球。
- 该结算函数不得直接复用于欧冠 KO；以后如复用，必须由独立 score-basis adapter 明确授权。

### 账本状态机

冻结时即写：

```json
{
  "settlement_status": "unsettled"
}
```

成功结算后只新增或更新赛后字段：

```json
{
  "settlement_status": "settled",
  "home_score_90": 2,
  "away_score_90": 1,
  "actual": "H",
  "outcome_hit": true,
  "score_hit": false,
  "result_source": "football-data",
  "result_date": "2026-08-08",
  "settled_at": "..."
}
```

以下赛前字段在结算前后必须逐字段完全相同：

```text
home
away
event
kickoff_utc
kickoff_bj
frozen_at
retro
model_universe
model_half_life
data_through
p_home
p_draw
p_away
xg_home
xg_away
matrix
adjustments
```

### 缺失赛果

满足以下任一情况时保持：

```json
{
  "settlement_status": "unsettled"
}
```

- 当季 CSV 尚未发布；
- CSV 尚未包含该场比赛；
- 比赛延期；
- 比分字段不完整；
- 队名映射无法确认。

不得：

- 删除条目；
- 静默跳过且不计数；
- 写 0:0；
- 用 ESPN 临时比分代替 CSV 结算；
- 以当前时间推断比赛已经完成。

### 幂等与赛果修正

- 同一账本重复结算必须幂等。
- 已结算且源比分相同时，不更新 `settled_at`。
- 上游赛果后来发生正式修正时，可以修改赛后字段，但必须追加：

```json
{
  "result_revised_from": {
    "home_score_90": 2,
    "away_score_90": 1,
    "actual": "H"
  },
  "result_revised_at": "..."
}
```

任何赛果修正仍不得触碰赛前字段。

### 调度顺序

`daily_update.py` 对每个 live 俱乐部赛事执行：

1. 刷新或读取 fixtures；
2. `freeze_event()`；
3. 刷新当季 CSV；
4. `settle_event()`；
5. 输出 frozen、settled、unsettled 数量。

冻结不得因当季 CSV 不存在而失败；结算可以正常返回：

```json
{
  "status": "ok",
  "settled_new": 0,
  "unsettled": 10,
  "reason": "current_season_results_unavailable"
}
```

### 新增测试

按你提出的三项写死，并补充赛季隔离和幂等：

```text
test_clubverify_settle_writes_result_only
test_clubverify_settle_never_touches_frozen_probs
test_clubverify_settle_missing_result_stays_unsettled
test_clubverify_settle_filters_results_to_event_window
test_clubverify_settle_is_idempotent
test_clubverify_settle_preserves_home_away_identity
test_clubverify_settle_result_correction_is_audited
test_clubverify_freeze_to_settle_historical_roundtrip
```

执行：

```bash
/opt/anaconda3/bin/python3 -m pytest \
  test_core.py::test_clubverify_settle_writes_result_only \
  test_core.py::test_clubverify_settle_never_touches_frozen_probs \
  test_core.py::test_clubverify_settle_missing_result_stays_unsettled \
  test_core.py::test_clubverify_settle_filters_results_to_event_window \
  test_core.py::test_clubverify_settle_is_idempotent \
  test_core.py::test_clubverify_settle_preserves_home_away_identity \
  test_core.py::test_clubverify_settle_result_correction_is_audited \
  test_core.py::test_clubverify_freeze_to_settle_historical_roundtrip -q
```

### 历史闭环验收

使用 25-26 真实历史数据执行合成闭环：

1. 从 25-26 联赛数据选择一轮真实比赛；
2. 测试中将 event window 注入或 monkeypatch 为对应 25-26 时间窗；
3. 在比赛开球前时点调用 `freeze_event()`；
4. 保存赛前字段快照；
5. 注入该轮真实赛果；
6. 调用 `settle_event()`；
7. 比较赛前字段逐字段不变；
8. 确认赛后字段完整。

不得用 `epl2526` alias 直接完成该测试，因为 alias 会规范化成 `epl2627`，容易掩盖 event-window 错配。测试必须显式构造临时 registry/event window 或依赖注入。

可观察产物：

```text
docs/evidence/p0a-club-freeze-settle-roundtrip.json
```

其中至少包含一条：

```json
{
  "retro": false,
  "settlement_status": "settled",
  "p_home": 0.0,
  "p_draw": 0.0,
  "p_away": 0.0,
  "home_score_90": 0,
  "away_score_90": 0,
  "actual": "H"
}
```

示例里的比分和 `actual` 必须互相一致，不得使用占位值。

### 新增完成判据

P0-A 只有同时满足以下两项才算代码完成：

- 新赛季 0 场状态下可执行“赛程→赛前冻结”；
- 历史合成数据可执行“冻结→赛果结算→对账”完整闭环。

生产启用分两次：

- 首轮开球前：冻结调度必须启用；
- 首轮赛果进入当季 CSV 后：结算调度必须启用并产生首批 `settled`。

### 回滚条件

- `settle_event()` 修改任一赛前字段；
- 跨赛季匹配到同一主客对阵；
- 缺失赛果被写成默认比分；
- 延期场次被错误结算；
- 重复结算导致账本持续变化；
- 结算依赖导致赛前冻结必须等待当季 CSV；
- 英超结算写入其他联赛账本。

出现结算问题时，仅停用 `settle_event()`；经验证的赛前冻结继续运行。

---

# 最终定稿结论

三项修改均正式采纳：

1. **赛事 key 零特判只约束新装配层，世界杯遗留兼容进入明确 allowlist。**
2. **P0-A 一次交付五大联赛参数化冻结，英超作为最早硬期限。**
3. **P0-A 同阶段交付 `settle_event()`，形成冻结—结算闭环；生产启用允许随当季 CSV 分两步发生。**

加上本修正案后，上一版 MD 即为最终施工基线，可以直接进入 P0-A。