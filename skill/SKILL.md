---
name: worldcup
description: >
  Top-tier football prediction tool (formerly "World Cup predictor", now expanding to ALL S-tier
  events). Two model universes on one Dixon-Coles double-Poisson engine: ① national teams (World Cup
  2026 / Euro / Copa América / Nations League — 257 teams, any international fixture predictable
  today) with Monte-Carlo bracket, in-play W/D/L, frozen verification ledger, market/CLV honesty
  layer, Bayesian championship CI; ② clubs (Premier League + top-5 leagues via football-data.co.uk,
  per-league models, season simulator for title/top-4/relegation odds). Flask web app. Triggers on:
  World Cup / worldcup / Euro / Copa América / Champions League / Premier League / La Liga / any
  top-5 league, score prediction, title odds, bracket, league table simulation, match forecast,
  continue improving this project, or launch the web app.
  （顶级足球赛事预测工具，前身"世界杯预测器"、正扩展到全部 S 级赛事。同一 Dixon-Coles 双泊松引擎、
  两个模型宇宙：① 国家队——2026 世界杯/欧洲杯/美洲杯/欧国联，257 队、今天即可预测任意国家队对阵，
  含蒙特卡洛晋级树、in-play 实时胜平负、赛前冻结验证、市场/CLV 诚实层、贝叶斯夺冠可信区间；
  ② 俱乐部——英超及五大联赛（football-data.co.uk），每联赛独立模型，赛季模拟器出夺冠/前四/降级概率。
  触发词：世界杯 / 欧洲杯 / 美洲杯 / 欧冠 / 英超 / 西甲 / 五大联赛 / 比分预测 / 夺冠概率 / 积分榜模拟 /
  晋级树 / 比赛预测 / 启动这个预测网页 / 继续优化这个项目。）
metadata:
  author: melvin
  version: "3.2"
  repo: https://github.com/turingism/worldcup-predictor
---

# Top-tier Football Events Predictor — skill

> This is an **operations manual**. The real code lives in `~/worldcup-predictor/` (public repo:
> https://github.com/turingism/worldcup-predictor). Disclaimer: personal/educational project, **not**
> betting advice — see the repo README.

---

## English

### Step 1 — Load project context (mandatory)
Read `~/worldcup-predictor/CLAUDE.md` first (current state, verified conclusions, TODO, pitfalls);
for multi-event work also read `docs/MULTI_EVENT_PLAN.md` (event tiers, 3-layer IA, roadmap) and open
`docs/ia-mockup.html` (the agreed UI blueprint for the event switcher). **Do not redesign existing
features** — most decisions are made and backtest-verified. Two examples that keep tempting people:
national `half_life=730` and club `half_life=365` are both formally adjudicated optima; market-value
/ Elo are proven useless.

### Two model universes (hard constraint)
- **National teams** — one `model.pkl`, trained on all internationals (257 teams), `half_life=730`.
  Covers WC 2026 **and, engine-wise, any S-tier national event today** (Euro / Copa América / AFCON /
  Asian Cup / Nations League — data all present in martj42); what's missing is only the event shell
  (bracket, dashboard wiring).
- **Clubs** — per-league models on football-data.co.uk data (`clubdata.py`, E0/SP1/I1/D1/F1, ~3
  seasons each, B365 open+close odds native), `half_life=365` (adjudicated across 5 leagues × 3
  cutoffs; 730 is optimal in NO league — never copy national hyper-params to clubs). E1 (Championship)
  is loaded **only as a feeder** for season sims (promoted-team history), never merged into
  single-match models (accuracy gate failed).
- Cross-league (Champions League) = P4: research report first, may honestly end at "negative EV, not
  built".

### Step 2 — Act on intent
- **Web app / live prediction** (currently WC-only; multi-event UI lands in P1):
  port 8000 is managed by the launchd agent `com.melvin.worldcup-predictor` — **restart with
  `launchctl kickstart -k gui/$(id -u)/com.melvin.worldcup-predictor`, never nohup** (it auto-respawns;
  manual start ⇒ Address already in use). Logs: `~/Library/Logs/worldcup-predictor/`.
  Editing `templates/` or the backend requires a restart (debug=False, no hot reload).
  Read-only share mode: `READONLY=1 python3 app.py`.
  **`#home` is the default landing view** (cross-event overview, P0-H). Data assembly lives entirely
  in `home_dashboard.py` — never move it into the route layer, and keep its four invariants
  (read-only / per-event ledgers / no impersonation / no betting advice) intact.
- **Single fixture, national teams**: `/opt/anaconda3/bin/python3 predict.py "Argentina" "France" --cache` (Chinese
  team names supported — works for Euro/Copa fixtures too, it's the same universe).
- **Single fixture, clubs**: `python3 clubpredict.py "阿森纳" "曼城"` (league auto-detected from the
  two names, Chinese/English both fine; first team = home, `--neutral` for cup-final venue;
  `--ranking E0` for a league power table; `--refresh` re-pulls the running season). Per-league
  models (hl=365) cache to `data/club/model_<code>.pkl` and auto-refit when data updates.
  **Cross-league fixtures (UCL) are honestly refused** — strength scales are uncalibrated until P4.
- **League season simulation** (title / top-4 / relegation odds): `clubsim.SeasonSimulator` — facts
  before `as_of` counted as played, remaining fixtures sampled from DC score distributions; season
  sims **must** pass `feeder="E1"` (skipping promoted teams' 38 matches distorts the whole table).
  Retro-validation: `simulate_retro("E0", ...)` (24-25 EPL: half-season view gave Liverpool 86.5%
  title, real relegation trio = top-3 relegation probs).
- **WC title odds**: `/opt/anaconda3/bin/python3 simulate.py --sims 5000` (production half-life 730 via
  `config.NATIONAL_HALF_LIFE`; injuries layer is **opt-in** `--injuries`, default pure DC).
  **Championship interval band**: `/opt/anaconda3/bin/python3 bayes.py` then `champ_ci.py` — a
  time-weighted **pseudo-posterior band with MC-noise decomposition** (not a strictly validated
  90% credible interval); convergence-gated (R-hat/ESS/divergences), fails ⇒ old cache kept.
- **Improve the model/params**: any change **must** beat the baseline in backtests (`backtest.py`
  for national, `bt_club_hl.py` pattern for clubs) by RPS/LogLoss/hit-rate, else don't adopt. Bump
  `model.py SCHEMA_VERSION` when adding/removing model attributes (old `model.pkl` auto-rebuilds).

### Multi-event roadmap (the current mainline)
- **P0 DONE (offline, zero wiring)**: `events.py` registry (wc2026/nl2026/epl2627; per-event ledger
  isolation locked at registry level) · `clubdata.py` · club hl=365 adjudication · `clubsim.py` ·
  144-club Chinese name map (`teams_zh.CLUB`, separate namespace from national names) ·
  `docs/MULTI_EVENT_PLAN.md` + `docs/ia-mockup.html` (L0 event switcher → L1 format-driven tabs:
  cup=bracket / league=table; no odds source ⇒ market tab hidden; **verification ledgers never
  pooled across events**; L2 per-match layer unchanged).
- **P1/P2/P3 SHIPPED**: L0 event switcher + `?event=` on every API + per-event ledger isolation +
  all five top leagues wired with seven tabs each (board / matchup / season-sim / title odds /
  market / mechanism / JC review). E1–E3 done too: Euro-competition ledger (5 seasons, 1552
  matches) and cross-league calibration (anchor co-training beats naive pooling, ΔRPS −0.0657,
  bootstrap CI excludes 0).
- **Event keys renamed 2026-07-25**: the five leagues are `epl2627` / `laliga2627` / `seriea2627` /
  `bundes2627` / `ligue12627` (their windows always were the 26-27 season). Old `*2526` keys live
  on as entry-point-only aliases (`events.ALIASES`/`resolve()`) — never as ledger names or canonical keys.
- **Current mainline = `docs/UPGRADE_REQUIREMENTS_2026-07-25.md`** (cross-model adjudicated spec;
  §10 amendment wins on conflict). Order: P0-A club freeze+settle **[DONE]** → P0-B event
  capability contract → P0-C Nations League shell (hard deadline 2026-09-03) → P1-A UCL single-match
  engine → P1-B UCL archive tab → P2 docs. `clubdata._CUR_END` +1 only after `E0_2627.csv` exists.
- **P0-A ops gate (live now)**: `scripts/club_freeze.py` freezes pre-match predictions from
  fixtures.csv **without waiting for the new season's CSV**, and `settle_event()` closes the loop
  after results land. Scheduled freezing stays **blocked** for a league until
  `--crosscheck <event>` verifies its kickoff timezone (3 matches, ≤5 min). Must be unlocked
  before the EPL opener on 2026-08-08.
- **P0-H home overview DONE (2026-07-25)**: `home_dashboard.py` + `/api/home` + `#home` as the
  default landing view — answers "what does this system have, is it trustworthy, what next". Four
  invariants, each locked by a test: **① read-only** (no training, no Monte Carlo, no freeze/backfill,
  no network, no disk writes — not even `clubdata.load_fixtures`, whose stale-while-revalidate spawns
  a background download thread; use the cached-only loader) · **② ledgers stay side-by-side per
  event** (no `total`/`summary`/`overall_accuracy` at the response root — the registry invariant
  extended to the API layer; `jc_review` stays out of the home view entirely) · **③ no
  impersonation** (a `seasonsim` cache only counts when both season and mode match — the current
  `seasonsim_E0.json` is `season=2025-26/mode=retro` whose final table shows a 100% champion, so
  taking it naively passes last season's result off as a new-season forecast; future-match
  probabilities come **only** from frozen ledgers, never recomputed live) · **④ no betting advice**
  (no odds, no EV, no value, no recommendations). WC numbers reuse `verify.evaluate` — same formula
  as `/api/verify`, the home view never computes a second version. Measured: 181 ms cold build,
  1 ms warm, 9.4 KB JSON.
- **P3**: replicate to the other top-4 leagues + Euro/Copa 2028 shells. **P4**: UCL cross-league
  calibration study.

### Step 3 — Verify
- UI change → **`scripts/shot.sh <out.png> <w,h> <scale> <url>`**, then Read the image.
  ⚠ **Never hand-roll the Chrome command.** Without `--user-data-dir` a headless run seizes the
  user's *real* Chrome profile and holds its singleton lock — clicking the Chrome icon then just
  hands off to that invisible instance, i.e. **"Chrome won't open"** (really happened 2026-07-25).
  `shot.sh` always uses a throwaway profile and cleans up. For layout facts (overflow / tab rows /
  first-frame boot state) use **`scripts/ui_check.py`** (CDP, isolated profiles, real box model).
- Model change → backtest numbers vs baseline (time-ordered, as-of cutoffs, no leakage).
- Run `/opt/anaconda3/bin/python3 -m pytest test_core.py -q` — the **full test_core suite** (count grows every iteration; trust the pytest output, do not hardcode a number). Network-dependent club tests auto-skip offline.

### Current capabilities (already shipped)
Dashboard (live / upcoming / finished) · in-play live W/D/L with host/env parity (`inplay.py`) ·
frozen pre-match verification ledger + confidence bins/upset tagging (`verify.py`) · market/CLV
honesty layer (`clv.py`) · Bayesian championship 90% CI with background auto-update (`champ_ci.py`) ·
official bracket + host-advantage Monte Carlo, champions conditioned on actual KO results · ESPN
minute-level live results · Football-Manager deep pre-match report (`manager.py`) · market-mechanics
explainer with hard no-betting-advice redlines (`explainer.py`) · China-lottery review loop
(`jc_review.py`, manual entry, strict no-rate redlines) · club data layer + season simulator
(`clubdata.py`/`clubsim.py`, offline) · cross-event home overview as the default landing view
(`home_dashboard.py`/`/api/home`, read-only, per-event ledgers never pooled).

### 2026-07-19 consistency-fix wave (read before touching these areas)
- `config.py` is now the **single source** for national production params (`NATIONAL_HALF_LIFE=730`).
  The old `simulate.py` 240 hardcode and `data.py`/`backtest.py` 547 defaults were real drift bugs — fixed;
  a test bans the literals from production files. `get_model` writes the shared `model.pkl` **only** for
  production params and validates a **data fingerprint** (`model_meta.json`: results.csv/live_results.json
  mtime+size, trained_through, n matches) — data updates auto-retrain the cache.
- Group tiebreaks now implement the **official FIFA 2026 rules** (head-to-head first, recursive re-apply,
  overall GD/GF, discipline degraded-with-audit, FIFA ranking 2026-06-11 from `data/fifa_rankings_2026_06.json`)
  in **one shared module `tiebreak.py`** used by vectorized MC / `simulate_once` / deterministic projection.
- Injuries/availability: **default pure DC**. Entries need `verified` + fresh `updated_at` (TTL 7d) or a
  match-level ESPN confirmed-XI check to affect production (`WC_INJURIES=1` to enable in app). Frozen ledger
  entries record the adjustments used.
- Score basis: results.csv knockout scores **include extra time** — see `docs/score-basis.md`
  (known-ET audit `data.known_et_mask`, A/B backtest kept full training). Don't claim "strict 90 minutes".
- Knockout draws: advancement = win90 + ET(xG×1/3 Poisson) + pens at a **flat 50% prior**
  (empirics: stronger side wins only 53.5%±4.1% of 572 shootouts) — see `docs/knockout-approx.md`.
- WC-specific tiered backtest: `bt_wc.py` (per-edition as-of, WC finals vs qualifiers vs friendlies,
  bootstrap CIs, closing-odds benchmark, executable adoption gate). The mixed ~59% hit-rate is NOT
  a World-Cup-finals number — always cite the stratified figures.
- National `data/odds.csv` now has **opening columns** (~96/104 filled) alongside closing — CLV computable.

### Core pitfalls (full list in CLAUDE.md)
- **half_life: national=730, club=365** — both adjudicated; never swap or "unify" them.
- `model.py score_matrix` has a `np.clip(M,0,None)` guard (standard DC; identity for real fits — keep).
- Dataset `"FIFA World Cup qualification"` ≠ the finals; filter finals with exact `== "FIFA World Cup"`.
- In-play / market / explainer / jc_review layers are read-only side-paths — they must **never**
  write the verify ledger or touch the GLM; explainer/narrative/jc_review carry hard redlines
  (no betting recommendations, no cross-match rate aggregation) — refuse even if asked.
- Per-event ledger isolation is a registry-level invariant — never pool verification across events.
- `teams_zh` has two namespaces (national vs CLUB, keys = football-data spellings like `Ath Madrid`);
  tests assert zero overlap and full club coverage — a new club needs its mapping or tests go red.
- **Front-end traps found on 2026-07-25 (P0-H)** — the static HTML *is* the WC page (title, header,
  8 tabs, `#verify` visible by default), so landing on home used to flash the WC page for one network
  round-trip while waiting on `/api/events`. Fix: an inline sync boot script in `<head>` stamps
  `boot-home/event/wc` from the hash (keys/aliases injected server-side — **zero event-key literals in
  the front-end**), CSS suppresses `.tabs`/`#verify` on the first frame (`#verify` has an inline
  `display:block`, so the rule **needs `!important`**), and `finishBoot()` **must clear the boot
  classes** afterwards or WC tabs stay suppressed forever. Stash the original header in
  `window.__HDR_DEF` before rewriting it, else `_HDR_DEF` captures the home copy and the WC title
  comes back wrong. Also: the page had **no `hashchange` listener at all** — routing ran once on load,
  so in-page links only changed the address bar. And appending new CSS at the end of the long
  stylesheet overrides earlier media queries (it really did wipe the mobile pill background) — scope
  layout rules with `@media(min-width:761px)` or insert them before the media queries.
- For web scraping use the web-access skill (real-browser CDP), not bare curl on anti-bot sites.
- Before proposing any optimization, read CLAUDE.md's latest handover — years of negative results
  (nb_alpha, ρ scaling, knockout conservatism, Elo, market value, E1 merge) are archived there.

### TODO directions (when user says "keep improving")
1. **Now → 2026-07-19**: app is frozen for the WC run; only offline side-path work is safe.
2. **P1 wiring** (after 7-19) per `MULTI_EVENT_PLAN.md` + `ia-mockup.html` — see roadmap above.
3. Champ CI full-covariance MVN alternative (low priority); xG for national teams = dead end (no free source).

### Environment
**Python: use `/opt/anaconda3/bin/python3`** — the Homebrew `python3` on this machine lacks pandas
(quick check: `python3 -c "import pandas"`; on failure switch to the anaconda path).
anaconda (numpy/pandas/scipy/statsmodels/flask/pymc installed) · `gh` CLI at `~/.local/bin/gh`
(logged in as `turingism`) · no `timeout` cmd · GitHub anonymous API rate-limited 60/h (use release
redirects, not the API).

---

## 中文

### 第一步：加载项目上下文（必做）
先读 `~/worldcup-predictor/CLAUDE.md`（项目现状、已验证结论、待办、避坑）；做多赛事相关工作再读
`docs/MULTI_EVENT_PLAN.md`（赛事分级、三层 IA、路线图）并打开 `docs/ia-mockup.html`（切换器 UI 蓝图）。
**不要重新设计已有功能**——大量决策已做且经回测验证。两个最常被"想改"的：国家队 `half_life=730`、
俱乐部 `half_life=365` 均为正式裁决最优；身价/Elo 已验证无用。

### 两个模型宇宙（硬约束）
- **国家队**：一个 `model.pkl`，全国际赛训练（257 队），`half_life=730`。覆盖 2026 世界杯，**引擎层
  面今天就能预测任意 S 级国家队赛事对阵**（欧洲杯/美洲杯/非洲杯/亚洲杯/欧国联——数据全在 martj42），
  缺的只是赛事外壳（晋级树、看板接线）。
- **俱乐部**：每联赛独立模型，数据 football-data.co.uk（`clubdata.py`，E0/SP1/I1/D1/F1 各约 3 季，
  B365 开盘+闭盘原生齐全），`half_life=365`（5 联赛 × 3 cutoff 正式复扫裁决；**730 在任何联赛都不是
  最优——国家队超参绝不照搬俱乐部**）。英冠 E1 **只作赛季模拟的 feeder**（升班马历史），单场模型
  并入已否决（准度闸门不过）。
- 跨联赛（欧冠）= P4：先研报告再裁决，可能诚实止步于"负 EV 不做"。

### 第二步：按用户意图行动
- **网页 / 实时预测**（当前仅世界杯；多赛事 UI 在 P1 落地）：
  8000 端口由 launchd agent `com.melvin.worldcup-predictor` 守护——**重启用
  `launchctl kickstart -k gui/$(id -u)/com.melvin.worldcup-predictor`，勿 nohup 手起**（守护进程
  自动重拉，手起必 Address already in use）。日志在 `~/Library/Logs/worldcup-predictor/`。
  改 `templates/` 或后端必须重启（debug=False 不热重载）。只读分享：`READONLY=1 python3 app.py`。
  **`#home` 是默认落地页**（跨赛事总览，P0-H）。数据装配全在 `home_dashboard.py`——别挪回路由层，
  四条铁律（只读 / 账本按赛事并列 / 不冒充 / 不出投注建议）不得破。
- **国家队单场**：`/opt/anaconda3/bin/python3 predict.py "Argentina" "France" --cache`（支持中文队名；欧洲杯/美洲杯
  对阵同样可用——同一宇宙）。
- **俱乐部单场**：`python3 clubpredict.py "阿森纳" "曼城"`（联赛从两队名自动识别，中英文皆可；
  第一支=主队，`--neutral` 为中立场杯赛口径；`--ranking E0` 出联赛实力榜；`--refresh` 强拉进行中
  赛季）。每联赛模型（hl=365）缓存在 `data/club/model_<码>.pkl`，数据更新自动重训。
  **跨联赛对阵（欧冠）诚实拒绝**——强度刻度未校准，待 P4。
- **联赛赛季模拟**（夺冠/前四/降级概率）：`clubsim.SeasonSimulator`——as_of 前已赛入账、剩余赛程按
  DC 比分分布抽样；赛季模拟**必须传 `feeder="E1"`**（跳过升班马整队 38 场会扭曲全表）。回溯验证：
  `simulate_retro("E0", ...)`（24-25 英超半程视角利物浦 86.5% 夺冠、降级概率前三=真实降级三队）。
- **世界杯夺冠概率**：`/opt/anaconda3/bin/python3 simulate.py --sims 5000`（生产半衰期 730 走
  `config.NATIONAL_HALF_LIFE` 单一配置源；伤停层 **opt-in** `--injuries`，默认纯 DC）。
  **夺冠区间带**：`/opt/anaconda3/bin/python3 bayes.py` 再 `champ_ci.py`——时间加权**伪后验分位带
  + MC 噪声分解**（非严格验证的 90% 可信区间）；带收敛门槛（R-hat/ESS/divergence），不达标不发布、旧缓存保留。
- **优化模型/参数**：改完**必须回测赢基线**（国家队 `backtest.py`；俱乐部照 `bt_club_hl.py` 的时序
  as-of 纪律），用 RPS/LogLoss/命中率数字说话，否则不采用。增删模型属性给 `model.py SCHEMA_VERSION` +1。

### 多赛事路线图（当前主线）
- **P0 已完成（纯离线、零接线）**：`events.py` 注册表（wc2026/nl2026/epl2627；账本按赛事隔离在
  registry 层锁死）· `clubdata.py` · 俱乐部 hl=365 裁决 · `clubsim.py` · 144 俱乐部中文映射
  （`teams_zh.CLUB`，与国家队命名空间隔离）· `docs/MULTI_EVENT_PLAN.md` + `docs/ia-mockup.html`
  （L0 赛事切换器 → L1 赛制驱动 tab：杯赛=晋级树/联赛=积分榜；无盘口源→市场 tab 隐藏；
  **验证账本绝不跨赛事混池**；L2 单场层零改动）。
- **P1/P2/P3 已交付**：L0 赛事切换器 + 全 API `?event=` + 账本按赛事隔离 + 五大联赛各七 Tab
  （看板/对阵分析/赛季推演/夺冠概率/市场对标/机制解读/竞彩复盘）。E1–E3 亦已完成：欧战账本
  （五季 1552 场）+ 跨联赛校准（锚点合训显著优于裸并，ΔRPS −0.0657，bootstrap CI 不含 0）。
- **赛事 key 已于 2026-07-25 更名**：五联赛为 `epl2627`/`laliga2627`/`seriea2627`/`bundes2627`/
  `ligue12627`（其 window 本就是 26-27 赛季窗）。旧 `*2526` 仅作**入口别名**
  （`events.ALIASES`/`resolve()`），绝不作账本名或规范 key。
- **当前主线 = `docs/UPGRADE_REQUIREMENTS_2026-07-25.md`**（跨模型评审定稿；第 10 节修正案
  与前文冲突时以其为准）。顺序：P0-A 俱乐部冻结+结算 **[已完成]** → P0-B 事件能力正向契约 →
  P0-C 欧国联壳（硬期限 2026-09-03）→ P1-A 欧冠单场引擎 → P1-B 欧冠回顾 Tab → P2 文档收口。
  `clubdata._CUR_END` +1 只在 `E0_2627.csv` 落地后做。
- **P0-A 运维闸（现已生效）**：`scripts/club_freeze.py` 从 fixtures.csv 出赛前冻结，
  **不等当季 CSV**；`settle_event()` 在赛果落地后收口对账。某联赛未通过
  `--crosscheck <event>`（3 场、开球时间差 ≤5 分钟）前，定时冻结对它保持 **blocked**。
  英超 2026-08-08 首轮开球前必须解锁。
- **P0-H 首页总览已完成（2026-07-25）**：`home_dashboard.py` + `/api/home` + `#home` 默认落地，
  回答「这个系统现在有什么、可不可信、接下来看什么」。四条铁律，测试逐条锁死：**① 只读**
  （不训练、不跑蒙特卡洛、不冻结回补、不联网、不写盘——连 `clubdata.load_fixtures` 都不能用，
  它带 stale-while-revalidate 会起后台下载线程，改用本地 cached-only loader）· **② 账本按赛事并列**
  （响应根节点禁止 `total`/`summary`/`overall_accuracy` 之类跨赛事汇总，是 registry 层不变量在 API
  层的延伸；`jc_review` 整体不进首页）· **③ 不冒充**（`seasonsim` 缓存只有赛季与 mode 都匹配才认——
  现有 `seasonsim_E0.json` 是 `season=2025-26/mode=retro`，终局表里冠军 100%，直接取就是拿上季结果
  冒充新季预测；未来比赛概率**只认已冻结账本**，绝不现算，现算值与冻结值并存会让同一场出现两个数字）·
  **④ 不出投注建议**（无赔率、无 EV、无价值、无推荐）。世界杯数字复用 `verify.evaluate`，与
  `/api/verify` 同一套公式——首页绝不另算一份口径。实测冷构建 181ms / 热缓存 1ms / JSON 9.4KB。
- **P3**：复制到其余四大联赛 + 2028 欧洲杯/美洲杯壳。**P4**：欧冠跨联赛校准研究。

### 第三步：验证
- UI 改动 → **`scripts/shot.sh <out.png> <宽,高> <缩放> <url>`** 后 Read 看图。
  ⚠ **不要手敲 Chrome 命令**：不带 `--user-data-dir` 的 headless 会占用**用户真实 Chrome 配置**
  并持有 singleton 锁，用户点图标只会转交给这个无窗口实例——表现就是「Chrome 打不开」
  （2026-07-25 真实发生过）。`shot.sh` 固定用一次性 profile 并自动清理。
  布局事实（溢出/Tab 行数/首帧启动态）用 **`scripts/ui_check.py`**（CDP、独立 profile、真实盒模型）。
- 模型改动 → 回测数字对比基线（时序 as-of 切分，防泄漏）。
- 跑 `/opt/anaconda3/bin/python3 -m pytest test_core.py -q`——**完整 test_core**（数量随迭代增长，以 pytest 输出为准，勿硬编码）；依赖网络的俱乐部测试离线自动 skip。

### 当前已有能力
赛事看板（正在比赛/即将开赛/已结束）· in-play 实时胜平负含东道主/环境口径（`inplay.py`）· 赛前冻结
验证账本 + 置信度分桶/冷门标注（`verify.py`）· 市场/CLV 诚实层（`clv.py`）· 贝叶斯夺冠 90% 可信区间
后台自动更新（`champ_ci.py`）· 官方括号 + 东道主蒙特卡洛、夺冠对真实淘汰赛果实时条件化 · ESPN 分钟级
实时赛果 · 足球经理人深度报告（`manager.py`）· 市场机制解读（`explainer.py`，硬性无投注建议红线）·
竞彩复盘闭环（`jc_review.py`，手动录入、严格无「率」红线）· 俱乐部数据层 + 赛季模拟器
（`clubdata.py`/`clubsim.py`，离线）· 跨赛事首页总览作默认落地页（`home_dashboard.py`/`/api/home`，
只读、账本绝不跨赛事混池）。

### 2026-07-19 一致性修复档案（动这些区域前必读）
- `config.py` 成为国家队生产参数**单一配置源**（`NATIONAL_HALF_LIFE=730`）。旧 `simulate.py` 硬编码 240、
  `data.py`/`backtest.py` 默认 547 是真实漂移 bug——已修；测试禁止生产文件再出现旧字面量。`get_model`
  只为生产参数写共享 `model.pkl`，并校验**数据指纹**（`model_meta.json`：results.csv/live_results.json
  的 mtime+size、trained_through、场次数）——数据更新自动重训。
- 小组同分改为**FIFA 2026 官方规则**（相互战绩优先、递归重算、总净胜/总进球、纪律分降级留痕、FIFA 排名
  2026-06-11 版 `data/fifa_rankings_2026_06.json`），**单一共用模块 `tiebreak.py`**，向量化 MC /
  `simulate_once` / 确定性投影三路共用。
- 伤停层：**默认纯 DC**。登记需 `verified` + 新鲜 `updated_at`（TTL 7 天）或 ESPN 首发比赛级确认才进
  生产（app 用 `WC_INJURIES=1` 显式启用）；冻结账本记录本场所用 adjustment。
- 比分口径：results.csv 淘汰赛比分**含加时**——见 `docs/score-basis.md`（known_et 审计 +
  A/B 回测后维持全量训练）。不得再写『严格 90 分钟』。
- 淘汰赛平局：晋级 = 90'胜 + 加时(xG×1/3 泊松) + 点球**平坦 50% 先验**（实证：572 场点球强队仅赢
  53.5%±4.1%）——见 `docs/knockout-approx.md`。
- 世界杯专项分层回测：`bt_wc.py`（各届 as-of、正赛/预选/友谊分层、bootstrap CI、闭盘对标、可执行采纳
  门槛）。混合口径 ~59% 命中**不是**世界杯正赛数字——引用必须分层。
- 国家队 `data/odds.csv` 已有**开盘列**（约 96/104 非空）+ 闭盘——CLV 可算。

### 核心避坑（完整见 CLAUDE.md）
- **half_life：国家队=730、俱乐部=365**——均已正式裁决，别互换、别"统一"。
- `model.py score_matrix` 的 `np.clip(M,0,None)` 护栏（标准 DC，真实拟合下恒等）别删。
- 数据集 `"FIFA World Cup qualification"` ≠ 正赛，过滤正赛用精确等于 `== "FIFA World Cup"`。
- in-play / 市场 / 解读 / 竞彩复盘全是只读旁路——**绝不**写验证账本、**绝不**碰 GLM；
  explainer/narrative/jc_review 带硬红线（禁投注推荐、禁跨场聚合出「率」），用户要求也按红线拒绝。
- 账本按赛事隔离是 registry 层不变量——绝不跨赛事混池。
- `teams_zh` 双命名空间（国家队 vs CLUB，键=football-data 拼写如 `Ath Madrid`）；测试断言零交集 +
  俱乐部全覆盖——新增俱乐部必须补映射，否则测试红。
- **2026-07-25（P0-H）踩到的前端三坑**——静态 HTML 本身就是世界杯页（title/页头/8 Tab、`#verify`
  默认可见），而首页落地要等 `/api/events` 返回，闪动窗口=一次网络往返。修法：`<head>` 内联同步 boot
  脚本按 hash 打 `boot-home/event/wc` 类（key/别名由服务端注入，**前端零赛事 key 字面量**）→ CSS 首帧
  压住 `.tabs`/`#verify`（`#verify` 有内联 `display:block`，规则**必须带 `!important`**）→ 切换完成后
  `finishBoot()` **必须清除 boot 类**，不清之后进世界杯页 Tab 会被永久压住。页头原值要在改写前存进
  `window.__HDR_DEF`，否则 `_HDR_DEF` 捕获到首页文案、切回世界杯串标题。另两坑：页面**从来没有
  `hashchange` 监听**，路由只在加载时跑一次，站内改 hash 只动地址栏；新样式追加在长样式表末尾会覆盖
  更靠前的媒体查询（实测把移动端胶囊背景冲成透明），布局类规则要限定 `@media(min-width:761px)`
  或插到媒体查询之前。
- 联网抓数据用 web-access（真实浏览器 CDP），别裸 curl 抓反爬站。
- 提任何优化前先读 CLAUDE.md 最新接手——负结论档案（nb_alpha、ρ 缩放、淘汰赛保守、Elo、身价、
  E1 并入）都在，勿重做。

### 待办方向（用户说"继续优化"时可选）
1. **现在 → 2026-07-19**：世界杯运行期 app 冻结大改，只做纯离线旁路增量。
2. **P1 接线**（7-19 后）按 `MULTI_EVENT_PLAN.md` + `ia-mockup.html` 施工——见上方路线图。
3. 夺冠区间全协方差 MVN 备选（低优先级）；国家队 xG=死胡同（无免费源）。

### 环境提示
**Python 一律用 `/opt/anaconda3/bin/python3`**——本机 Homebrew `python3` 缺 pandas（检测：`python3 -c "import pandas"`，失败即切 anaconda 路径）。
anaconda（numpy/pandas/scipy/statsmodels/flask/pymc 已装）· `gh` CLI 在 `~/.local/bin/gh`（已登录
`turingism`）· 无 `timeout` 命令 · GitHub 匿名 API 限流 60/h（用 release 重定向，别走 API）。
