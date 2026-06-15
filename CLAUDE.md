# CLAUDE.md — 世界杯比分预测项目（给未来的 Claude）

> 重启 Claude Code 后读这个文件即可快速接手继续优化。先读本文件，再按需读 `README.md`。

## 📌 最新接手（2026-06-15 · 真实赔率 + 自动化）
- **市场层接真实赔率**：`espn_odds.py` 从 ESPN `pickcenter` 拉 DraftKings 1X2（不抓博彩站、绕地理封锁），快照到 `data/odds_snapshots.jsonl` → 拼 `data/odds.csv`（开盘/闭盘列）。app 内置每 30min 自动快照（`ODDS_SNAP_MIN`）。`clv.evaluate` 接它算 模型vs闭盘线 / CLV。**门槛不变**：无显著正 CLV 不显示价值/Kelly。
- **`MARKET_UNLOCK=1`**（env，默认关）= 手动开闸价值/Kelly 面板（含未开赛 EV/Kelly，大红标注非建议）；公开仓库默认仍诚实锁定。
- **看板每 3min 自动拉完赛**（前端 setInterval → /api/live）：有新完赛自动重训+刷新+重算区间。比赛日零点击。
- **两个已修 bug 教训**：①模板串里别再塞反引号（会杀整个 `<script>`）；②`clv.evaluate` 已加"无已完赛则短路不训练"（否则市场接口卡 ~60s）。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-14 下午 · 6 角色大改）
- **新增三块能力 + 一处护栏，引擎逻辑零改**（详见 CHANGELOG「6 角色评审驱动」节）：
  - **In-play 实时引擎** `inplay.py`：赛前 λ 按剩余时间缩放 + 当前比分泊松卷积 → 实时胜平负，并入 dashboard live 卡。只读、不碰 GLM/账本。`bt_inplay.py` 自洽校验（无分钟级数据，非样本外）。
  - **市场/CLV 诚实层** `clv.py` + `/api/market` + 「💹 市场对标」tab：模型 vs 闭盘线 + CLV 可证伪检验。**铁律：无显著正 CLV 不显示价值/Kelly**（`show_value` gating）。数据填 `data/odds.csv`，需加 `odds_*_open` 列才能算 CLV。
  - **只读分享** `READONLY=1` → 写接口 403 + 前端隐藏写按钮（`/api/config`）。
  - **看板打磨**：看预测弹窗、即将开赛按日分组、命中率去红化、小样本说明、赛果命中口径歧义说明。
  - **model.py τ 截零护栏**：`score_matrix` 加 `np.clip(M,0,None)`——标准 DC 做法，**已验证对真实预测/回测恒等**（勿误删，它护住参数扰动等异常 λ）。
- **✅ 夺冠参数不确定性区间已解决**（`champ_ci.py` + `/api/champ_ci` + 夺冠 tab whisker 图）：naive 法（独立 GLM 边际 SE 扰动）统计无效已弃；改用 **bayes 分层后验抽样**驱动模拟器——`bayes.py` 导出 `bayes_draws.npz`（300 套 atk/dfc/intercept/home_adv），`champ_ci.py` 整套替换 DC 系数逐位复现 bayes log_mu → MC → 5/50/95 分位。分层收缩根除稀疏队 SE 爆炸，中位全落带内。**改预测口径后重跑 `bayes.py`→`champ_ci.py` 刷新**。是补充视图，主引擎仍 DC。
- test_core 18 项全绿；全部端点 200。

## 📌 上一次接手（2026-06-14 上午）
- **📋 主页赛事看板已上线**（原「预测验证」tab 升级，现为默认首屏）：🔴 正在比赛 / 🟡 即将开赛 / ✅ 已结束 三态聚合。
  - 实时状态走 `live.fetch_status()`（ESPN pre/in/post 快照，**只读不进训练**，与 `fetch_and_save()` 只 ingest 完场的训练路径分离）；端点 `/api/dashboard`（`_live_status()` 缓存 30s，`?fresh=1` 绕过）。「🔄 刷新事实数据」= POST /api/live（ingest+按需重训）再拉看板；看板可见时每 60s 静默刷新比分。
  - 已结束区含**置信度分桶命中率 + 冷门/失手归因**（解释为何胜平负命中率被平局/硬币局拉低：平局是 argmax 结构性盲区，模型真实样本外命中率 ~59.7%，开赛初期小样本噪声）。阈值 `verify.CONF_HIGH/CONF_MID/UPSET_MAJOR`。
  - 前端 `loadDashboard/renderDashboard/liveCard/upRow/renderDone`；改前端必重启 app.py（debug=False）。
- 其余沿袭下节。

## 📌 上次接手（2026-06-13 会话末）
- **🎯 预测验证层已上线**（`verify.py` + `GET /api/verify` + 前端「预测验证」tab，#verify 深链）：
  - 账本 `data/predictions.json`：未开球场次的预测**开球前冻结**（含完整比分矩阵）；开球后条目只读。冻结时机=app 启动 / `_refit_all()` 后 / `/api/verify` 时。**改预测口径时记得账本旧条目代表当时的赛前认知，不要回填重算**。
  - 已完赛但账本缺失的场次 → `backfill()` 用 `as_of=赛日前一天` 的回溯模型补（标 `retro`），与 backtest 同口径不偷看结果；回溯模型按 as_of 进程内缓存，约 10s 一个。
  - 统计：赛果命中（=argmax 三向概率，**不是**最可能比分的胜平负——平局边界两者可不一致，UI 脚注已说明）、精确比分命中、赋实际赛果/比分平均概率、RPS。
  - key 口径：小组赛 `G|主|客`（官方赛程序）、淘汰赛 `K|sorted`（顺序无关）；小组对阵在淘汰赛重演靠日期窗（<2026-06-28）区分。
  - `python3 verify.py` = CLI 报告；test_core.py 14 项全绿。
- 其余未尽事项沿袭下节（白皮书 PDF 未更新、只读分享模式未做、bayes_ratings.json 还是旧口径）。

## 📌 上次接手遗留（2026-06-12 会话末）
- **⚠️ 重大修正（2026-06-12）：回测曾有时间泄漏**——`build_training_frame` 不剔除 as_of 之后的比赛（负年龄、权重 0.5^负数>1），历史回测数字（RPS 0.1440/0.1443）全部被未来数据美化过，**与新数字不可比**。已修（data.py 加 `age_days >= 0`）。修复后重扫 half_life：240 的"最优"是泄漏伪影（短半衰期放大未来场权重），诚实口径 **730 天最优**（4 cutoffs n=3376：240=0.1702 / 547=0.1667 / 730=0.1662 / 1095=0.1660 / 1460=0.1662，平底盆地，取最近两 cutoff 最优的 730）。全部默认值已改 730（model/predict/app/bayes）。**CLAUDE.md 下方旧结论里凡引用 RPS 0.144x 的绝对数字均已过时，但 A/B 相对结论（Elo/分级/负二项/校准被否决）泄漏程度一致，方向大概率仍立**——如要翻案需用修复后口径重跑对应 bt_*.py。
- **挪威第4/法国第11 的旧分歧已消解**：泄漏修复+hl730 后夺冠榜 阿根廷18.3%/西班牙16.9%/英格兰11.0%/葡萄牙6.8%/法国6.6%，与市场/Kimi 共识量级一致；CLAUDE.md「对标 Kimi」节的挪威叙事已过时。`data/bayes_ratings.json` 还是旧口径（hl240+泄漏），实力榜 tab 建议重跑 `python3 bayes.py`（≈15s NUTS）。
- **白皮书 PDF 仍未更新**（沿袭上次待办），且现在又多了 half_life=730、泄漏修复、实时数据层三处要改。
- **只读分享模式（未做）**：cloudflared 公网分享时建议禁写接口（/api/refresh、/api/live、POST /api/overrides）。
- 本会话全部改动见 `CHANGELOG.md`「2026-06-12」节。app 跑在 **:8000**。

## 📌 上上次接手遗留（2026-06-07 会话末）
- **白皮书 PDF 需更新**（桌面 + `docs/` 两份，源在 `docs/whitepaper-source.html`）：①第 2.4 节蒙特卡洛还写"全中立"，但已实现东道主主场优势，需改；②第 4.3 节「可借鉴」把 Elo/赛事分级/负二项当"待试"，但都已回测**否决**、净胜球相关系数+盘口对标已实现，应升级成"已验证结论"+小结表。改完用 `Google Chrome --headless=new --no-proxy-server --print-to-pdf` 重渲覆盖两份。
- **只读分享模式（未做）**：若再用 cloudflared 公网分享，建议加开关禁用写接口 `/api/refresh`、`POST /api/overrides` + 设 `MAX_CONTENT_LENGTH`，只读最安全。分享命令：`/tmp/cloudflared tunnel --url http://localhost:8000`（二进制可能因 /tmp 清理丢失，丢了重下 darwin-arm64）。
- 本会话全部改动见 `CHANGELOG.md`。app 跑在 **:8000**（不是 5000，AirPlay 占用）。

## 这是什么
2026 世界杯比分/赛果预测器。核心：**Dixon-Coles 双泊松模型**（基于 1872–2026 真实国际比赛数据）+ 蒙特卡洛赛事模拟 + Flask 网页。
不是 Claude skill，就是一个普通 Python 项目。

## 怎么跑
```bash
cd ~/worldcup-predictor
python3 app.py                 # 启动网页 http://127.0.0.1:8000（避开 AirPlay 占用的 5000）
python3 predict.py "Argentina" "France" --cache   # CLI 单场
python3 simulate.py --sims 5000                     # CLI 夺冠概率
python3 backtest.py                                 # 回测（改模型后必跑，验证是否真的更好）
```
依赖：anaconda 自带 numpy/pandas/scipy/statsmodels/flask（已验证可用）。
环境无 `timeout`、无 `gh` CLI；GitHub API 匿名限流 60/h。

## 文件地图
- `data.py` 数据层（清洗+时间衰减加权+长表）
- `model.py` DixonColesModel：Poisson GLM + ρ 修正 + 身价先验(默认关) + 比分矩阵
- `predict.py` CLI + `get_model()` 缓存
- `simulate.py` TournamentSimulator：`run()`夺冠概率 / `simulate_once()`随机一届 / `project()`确定性投影（含淘汰赛）
- `wc2026.py` 官方赛制：12 组 + R32 官方槽位 + 第三名约束匹配 + 晋级树 + 淘汰赛日期
- `schedule.py` 全 104 场开球时间（北京时间）+ 场馆/当地时间换算（`group_venue`/`ko_venue`，读 venues.json）
- `teams_zh.py` 英文→中文+国旗 映射
- `market.py` + `data/market_values.json` Transfermarkt 身价（先验，默认关）
- `elo.py` 动态 Elo（已回测：不如 DC，留作对照，未启用）
- `bayes.py` PyMC 分层贝叶斯评级（净实力+94%可信区间），**补充视图非预测引擎**；`python3 bayes.py` 生成 `data/bayes_ratings.json`
- `backtest.py` 样本外回测（RPS/LogLoss/命中率/净胜球相关）；`bt_elo.py` Elo 外生特征、`bt_tiers.py` 赛事分级权重、`bt_nb.py` 负二项过离散 对比回测（结论均：不采用）；`bt_odds.py` 模型 vs 博彩盘口对标（读 `data/odds.csv`）
- `docs/` 测算逻辑白皮书 PDF（对比高盛方法论）；`CHANGELOG.md` 全部改动归档
- `app.py` Flask 后端；`templates/index.html` 单页前端
- `test_core.py` pytest 回归测试（`python3 -m pytest test_core.py -q`，12 项：预测合理性/矩阵归一/旧pickle回填/模拟结构/API冒烟）
- `data/results.csv` 比赛数据（martj42）；`data/shootouts.csv` 点球胜者；`model.pkl` 训练缓存（带 `schema_version`）
- `data/overrides.json` 用户录入/假设赛果的持久化文件（存盘，刷新/重启不丢）
- `live.py` ESPN 实时完场抓取层 + `data/live_results.json` 持久化（`python3 live.py` 全量回拉自测）；app `/api/live` 增量轮询端点
- `verify.py` 预测验证层：赛前冻结留痕（`data/predictions.json`）+ 回溯补缺 + 预测vs实际统计；`python3 verify.py` CLI 报告；app `/api/verify`
- `data/venues.json` 104 场主办城市 + 16 城 UTC 偏移（维基核对）；`data/bayes_ratings.json` 贝叶斯评级缓存

## 已验证的关键结论（别重复踩坑）
- **东道主主场优势已建模**：模拟器(`simulate.py`)曾全程 `neutral=True`，漏了美/墨/加在本国比赛的主场优势(home_adv=+23%xG)。已修：`schedule.py` 16城→东道主国映射 + `group_match_host`/`ko_city_country`；simulate 概率函数(`_pmf/_match_full/_padv/_pen/_match_score/_modal_score/_project_match`)统一支持 `host` 朝向，东道主在本国城市才给主场。实测出线率 美40→51% / 墨90→95% / 加90→94%。仅改 simulate/schedule，**不影响 GLM/回测**。`group_venue` 已改顺序无关（fixtures 主客顺序可能与 venues.json 相反，否则漏 3 场）。
- **half_life=730 天**是修复时间泄漏后的回测最优（见顶部 2026-06-12 重大修正）。旧结论"240 最优(RPS 0.1440)"是泄漏伪影，**别再改回 240**。改这个仍要用（已修复的）backtest 验证。
- **实时数据层（2026-06-12 起，开赛期间的事实来源）**：`live.py` 从 ESPN 公开 API（site.api.espn.com fifa.world scoreboard，免 key、分钟级、含点球 shootoutScore）拉正赛完场 → `data/live_results.json` → `data.merge_live()` 在 `load_raw(live=True)` 里填充 NA 赛程行（顺序无关、反序翻转比分）/补缺失淘汰赛行（东道主放主位 neutral=False）；`load_shootouts()` 合并实时点球胜者。martj42 滞后 1~3 天，ESPN 兜底；同场两边都有时以先填入的 csv 行为准。ESPN 队名仅 4 个需映射（Czechia/Bosnia-Herzegovina/Congo DR/Türkiye，live.NAME_FIX），其余 44 队与 martj42 一致（已全量 diff）。**大日期窗口查询会超时，live.py 已按 7 天分块+增量窗口**。
- **simulator 小组赛程已改官方静态构建（重要）**：旧版从「NA 比分行」并查集推断小组（derive_groups），开赛后比分逐场填入、NA 行消失会让小组推断逐场退化（一组踢完整组消失）。现 `TournamentSimulator.__init__` 直接用 `wc2026.GROUPS + schedule.GROUP`（排序构建保证跨进程确定），actual_results 顺序无关匹配+小组赛阶段日期窗（<2026-06-28，防淘汰赛重演小组对阵被误判）。`derive_groups` 仅留作历史参考勿再用。
- **身价收缩对 RPS 无改善**，默认 `min_market_weight=0` 关闭；身价数值仍在 UI 展示。
- **Elo 不如 Dixon-Coles**，集成无增益，未启用。借鉴高盛"Elo 为核心协变量"又试了**Elo 作为 GLM 外生特征**（`DixonColesModel(use_elo=True)`，`bt_elo.py` 回测）：RPS 0.1440→0.1446（+0.0006 更差）、elo_coef 为负——全套攻防 dummy 下 Elo 差冗余，**默认关闭**。
- **赛事强度分级加权无改善**：抬高世界杯/洲际杯正赛权重（`DixonColesModel(comp_weights={...})`，`bt_tiers.py`）回测全部更差（温和 +0.0003 ~ 强 +0.0013）——上调稀有大赛=砍有效样本、升方差，时间衰减已处理近期性。默认沿用 友谊0.5/其余1.0（`comp_weights=None`）。"等价基线"=0.1440 印证新路径不改变默认行为。
- **负二项(过离散)无改善**：进球原始 方差/均值≈1.6 像过离散，但那是强弱队均值差的水分；GLM 扣实力+DC ρ 修正后残差近 Poisson。`DixonColesModel(nb_alpha=α)` + `bt_nb.py` 扫描：α>0 单调更差（α=0.05 RPS +0.0005、LogLoss +0.0029）。默认 `nb_alpha=0`(Poisson)。
- 数据集 tournament 字段里 "FIFA World Cup qualification" ≠ 正赛，过滤正赛要用**精确等于** "FIFA World Cup"。
- 改模型类（加/删属性）→ **把 model.py 的 `SCHEMA_VERSION` +1**，`get_model` 会自动重建旧 `model.pkl`（不再需手删；`__setstate__` 也会给旧 pickle 回填默认值兜底）。改 `templates/`/后端仍要**重启 app.py**（debug=False）。改完跑 `python3 -m pytest test_core.py -q` 确认没回归。

## 网页功能现状（晋级树状图 tab = 核心）
单场预测 tab：球队下拉只收录**本届 48 强**（`/api/teams` 取自 `wc2026.GROUPS`，按 A–L 组序），输入框点进去自动清空以弹出完整候选（datalist 会按文字过滤，预填值会挡住其它队）。模型本身仍含 257 队，predict.py CLI 可预测任意队。
本届官方赛制实时预测：官方括号投影最可能走势 + 冠军；真实赛果蓝色锁定、其余预测；
小组赛改比分 / 点击淘汰赛录结果或假设（黄=试算）→ 括号+夺冠概率实时重算；
每场标 日期 + 北京时间 + 状态（已结束/进行中/未开赛/已抽签/未抽签/试算）；
「🔄 刷新真实赛果」全量拉 martj42+重训；「⚡ 实时比分」秒级查 ESPN 完场（增量窗口），有新完场才重训，开页后每 5 分钟自动轮询（页面可见时），`#livestat` 显示同步状态。另有 单场预测、夺冠概率(带置信区间+晋级漏斗)、预测验证(命中统计+逐场对比)、实力榜 四个 tab。

## 可继续的方向（按价值）
1. ~~赛果持久化~~ ✅ 已完成：`OV` 经 `GET/POST /api/overrides` 存盘到 `data/overrides.json`（原子写），前端每次改动后 `persistOV()` 同步、首次进括号 tab 前 `loadSavedOV()` 回填，刷新/重启不丢；「清除试算」同步清空磁盘。
2. ~~淘汰赛真实赛果自动抓取~~ ✅ 已完成：simulator `__init__` 构建 `actual_ko`（本届正赛、两队都是参赛队、不在小组赛对阵里的已踢场次），`_project_match` 顺序无关地自动套入并标 `real=True`（显示「已结束」非「试算」）；平局点球胜者查 `data/shootouts.csv`（refresh 同步下载）。`/api/project` 出 `ko_facts`。
3. ~~贝叶斯分层评级~~ ✅ 已完成：`bayes.py` PyMC 分层双泊松（非中心化，加权似然=DC 同款，NUTS≈15s），输出净实力+94%可信区间到 `data/bayes_ratings.json`；`/api/ratings` + 前端「实力榜」tab（CI 横条）。**注意：这是补充视图，预测/模拟仍由 DC 引擎驱动，未违反 backtest 铁律**；分层收缩使其比 DC 点估更保守、区间普遍重叠（有效权重和仅 ~1519）。
4. ~~刷新后自动 refit~~ ✅ 已完成：`/api/refresh` 拉新数据后用 `HALF_LIFE=240` 重训 `MODEL` 并重写 `model.pkl`、重建 `_SIM`；整次 refresh≈15s；前端按钮显示「拉取+重训评级中…」。**下载用多源+重试+原子写**（`_fetch`/`_mirror_urls`：raw.githubusercontent → jsdelivr → ghproxy，一个 503/被墙自动换下一个；曾因系统代理节点 503 报"Tunnel connection failed"）。refresh **不**重训贝叶斯（慢），实力榜需手动 `python3 bayes.py`。
5. ~~开球时间当地/北京切换~~ ✅ 已完成：`data/venues.json`（104 场城市+16城偏移，维基核对 72/72 一致）；schedule `group_venue`/`ko_venue` 算当地时间，project 输出 `city/date_local/time_local`；前端括号 tab 有「北京/当地」切换（`TZMODE`+`whenStr`）。

## 对标 Kimi 2026 世界杯报告的结论（2026-06-08 会话）
> 桌面 `世界杯比分预测器/Kimi_2026_World_Cup_Report.pdf`（224 页、300+ agent、20 维度）。完整读后做了两组回测对标，**结论：Kimi 的核心方法论照搬过来会让我们更差，我方引擎已是同口径最优**。脚本 `bt_eloprior.py` / `bt_calib.py`。
- **Kimi 用什么**：八源等权集成（ELO+FIFA SUM+Dixon-Coles+XGBoost+高盛动态+Opta MC+Polymarket/Kalshi 预测市场+博彩共识）→ 100k 次 MC → 贝叶斯更新 → Platt/Isotonic 后校准。数据七层（L1 结果…L7 环境，2.3 亿条），输入优先级 P0 近期国家队赛(30%)>P1 俱乐部 xG/xT(25%)>P2 Elo(15%)>P3 赔率(15%)>P4 历史大赛(10%)>P5 身价(5%)。Kimi 自报冠军：西16.5%/法15%/阿12%/英11%/德11%/巴9%。
- **我方 vs Kimi 最大分歧**：我们把**挪威排夺冠第 4（6.2%）、法国第 11（3.4%）**；Kimi 法国第 2、挪威第 23。根因：纯 DC 按进球拟合，挪威赛程「聚集」在弱旅（Haaland 狂进球）→ 对手强度归一化不充分 → 净实力 +3.02 略高于法国 +2.88。Elo 用传递性正确把法国(2105)>>挪威(1955)。
- **【已验证否决】Elo 当收缩先验混合**（`bt_eloprior.py`，区别于已否决的 `use_elo` 外生特征）：评级朝 Elo 隐含值混合 β∈{.15,.3,.5,.75}，**全样本 RPS 单调恶化**（β.15 即 +16e-4），且**连"强强对话子集"（双方 Elo 都进前 40，世界杯淘汰赛口径）也单调恶化**（β.15 +18e-4）。即在最该靠 Elo 归一化的强强场次，DC 自己的对手调整评级仍预测得更准。→ **挪威第 4 不是预测错误**：近期真实强强战绩确实支持「挪威被名气低估、法国被高估」。Kimi 锚定的是声誉/历史，我们信的是近期场上证据。
- **【已验证否决】Isotonic/Platt 后校准**（`bt_calib.py`）：本模型**训练集 ECE=1.06%**（Kimi 自述行业基准 8-10%、<5% 算良好），可靠性对角线近乎完美（预测 .95→实际 .944）；等温后校验集 RPS +3.5e-4、ECE 反升。→ 我方天生已比 Kimi 行业基准更校准，后校准只会过拟合。
- **真正值得学、但受数据可得性限制的一维**：**xG/xT 过程指标**（Kimi 取 0.7·xG+0.3·实际进球去噪终结方差）——唯一可能赢过纯进球 DC 的方向，但**无免费国家队 xG 源**（StatsBomb 开源仅部分大赛），与赔率源同困境。其次**阵容可用性/伤病**（我们零名单感知）与**海拔/高温**（venues.json 已有海拔；墨城 2240m VO₂max−15%，但近年高原/高温国际赛样本太少难回测）。均属「上下文/补充层」，不应混进已验证最优的预测引擎（与 bayes.py「补充视图」同定位）。
- **结论性判断**：Kimi 强在**广度与叙事**（地缘/伤病/天气/海拔/战术相克/黑天鹅、置信区间、负责任声明），弱在**可证伪性**（多为定性，冠军概率上限自承 ≤25%）。我方强在**单一可回测引擎 + 真实场上证据 + 校准**，弱在**上下文盲**。两者非同类：Kimi 像研报，我方像可交互的实时概率引擎。
- **已补的『上下文层』（均不污染引擎、backtest 仍 0.1443、12 项 pytest 全绿）**：
  - **#1 关键球员可用性**（`adjust.py`+`data/availability.json`+`model.set_availability()`+`/api/availability`+🩹面板）：期望惩罚 P(缺阵)×档位 乘到 xG。
  - **#2 海拔/高温环境**（`env.py`+`venues.json` geo段+`expected_goals(env_mult=)`+simulate 串 city+`/api/environment`+🏔️面板）：高原削非适应队、高温课欧洲热税；仅模拟/括号生效。`use_env` 开关。
  - **#3 xG 过程指标**：⚠️数据卡死——无免费深历史国家队 xG 源（Understat 仅俱乐部、StatsBomb 国家队覆盖浅），Kimi 自己也是用 ELO 差回归插补 xG（对我们循环，且 Elo 已证无益）。只能做近期 xG 微调覆盖层，无法当训练输入。**别再花时间找免费全量源**。
  - **#4 模型解读层**✅（`insights.py`+`/api/insights`+🔎面板）：模型 DC 夺冠排名 vs Elo 排名之差，背离≥3「📈模型超配」/≤−3「📉模型低配」，叠加伤病/环境暴露合成叙事。**纯展示不算概率**。无赔率源故用自有 Elo 锚而非市场。挪威+12 超配、法国−7 低配——对标 Kimi 核心洞察的产品化。
- **上下文层架构铁律**：所有上下文调整只走 `model.expected_goals` 的乘子（avail_att/avail_def/env_mult），**默认空=零影响**，`__getstate__` 剥离不入 pkl，fresh 模型(backtest)永远纯引擎。新增上下文层照此模式，别动 GLM。
- **可复现性铁律**：蒙特卡洛/括号投影要"同种子+同输入→逐位相同"。**别在喂给 rng 顺序或影响对阵分配的路径上裸迭代 set/dict**（PYTHONHASHSEED 会让跨进程顺序变）——曾因 `wc2026.assign_thirds` 迭代 `set(qual_letters)` 导致夺冠概率跨进程漂移 0.5pp、括号每次重启不同。已改 `sorted(qual)`。新增涉及随机或分配的逻辑，集合一律 `sorted()` 后再迭代。
- **解读层口径**：`insights._elo_rank` 只在 48 支参赛队内排 Elo（与夺冠排名同口径），别在全 ~250 队里排。

## 晋级树布局（重要实现细节）
- 官方淘汰赛槽位是**非顺序**的（如 R16#89←R32#74/#77，不相邻）。前端 `KO_TREE` 存父→子映射，`KO_Y` 按中序遍历给每场算纵向序值（叶子 0–15、父场=子均值），据此**绝对定位**每个 tie（`top=(KO_Y+0.5)×72px`）→ 完美二叉树、零交叉。**不要**用 flex `space-around`（条目数不同+高度不等时不会居中）。
- 连线用 SVG 叠加层（`drawConnectors`）按 DOM 实测坐标画正交线，缩放/重排都准。
- **自适应缩放**：`layoutBracket()` 先 `transform:none` 1:1 测量 →①按**实测最高框** `offsetHeight` 动态定 `SLOT_H`(=maxH+10) 并 `positionTies()` 重排（防 R32 框重叠，点球行/当地时间换行都自适应，**别写死 SLOT_H**）→②`drawConnectors()` →③按 `.bfit` 宽等比 `scale()`（含 SVG 一起缩）。下限 0.5、过窄才横向滚。窗口 resize 重排。缩放不影响点击编辑。
- 注意：**后台 tab 里 `requestAnimationFrame` 被挂起不触发**，画连线要用 `setTimeout`（已用 80/320ms 两段 + resize 重画）。
- `#bracket/#champ/#ratings` 支持 hash 深链直达 tab。

## 工作方式约定
- 改模型/参数 → 必须用 `backtest.py` 用数字证明更好，别凭感觉。`backtest.py` 现额外报「净胜球相关系数」（高盛同口径指标，全部国际赛~74% / 仅大赛正赛~72%；高盛仅世界杯正赛~45-49%，因测试样本群体不同**不可直接比**，仅作稳健度量+跨年横比）。
- **博彩盘口对标**：`bt_odds.py` 读 `data/odds.csv`（date,home,away,odds_1/x/2，队名对齐 martj42），赔率去 margin→隐含概率，与模型在同批比赛比 RPS（盘口=金标准）。现仅 5 场 2022WC 真实闭盘赔率种子样本（演示用，n 太小）。**无免费国家队历史赔率源**：football-data/Kaggle 全是俱乐部、martj42 无赔率、the-odds-api 历史付费($99/mo)、OddsPortal 免费但受 Cloudflare+ToS 禁抓。扩样本需自备来源，填 odds.csv 同格式即可（OddsPortal 队名→martj42 需映射表）。
- 联网抓数据 → 用 web-access skill（CDP 真实浏览器），别用裸 curl 抓反爬站点。
- **端口必须避开 5000**：macOS 的 AirPlay 接收器(ControlCenter/AirTunes)占用 `*:5000`（IPv4+IPv6）。浏览器开 `localhost:5000` 会优先解析到 IPv6 `::1` 命中 AirPlay 返回 **403「未获授权」(Server: AirTunes)**，而 `curl 127.0.0.1:5000` 走 IPv4 命中 Flask 是 200——极具迷惑性，曾误判为代理问题。**本项目已固定用 8000**。换端口时别用 5000/7000(AirPlay 也可能用)。
- **验证 UI 截图**：可用独立 `Google Chrome --headless=new --no-proxy-server --screenshot --virtual-time-budget=6000 "http://127.0.0.1:8000/#bracket"` 直接渲染截图（含连线，setTimeout 会在 virtual-time 内触发）。
- 验证 UI → 用 CDP 截图（proxy 在 localhost:3456）后用 Read 看图。
