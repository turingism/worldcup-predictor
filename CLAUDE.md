# CLAUDE.md — 世界杯比分预测项目（给未来的 Claude）

> 重启 Claude Code 后读这个文件即可快速接手继续优化。先读本文件，再按需读 `README.md`。

## 📌 最新接手（2026-06-21 · 7-agent 深挖重写七法「忠实排盘」+ 保持诚实铁证）
- **需求**：用户派 7 个 agent 各认领一套术数，深挖其真实占卜方式/逻辑，**彻底优化玄学占卜算法**。
- **关键判断（沿用 B 类诚实定位）**：优化目标 = **对传统术数排盘的忠实度（fidelity）**，**不是**提高命中率。提高命中率 = 灌真实球队先验 = 把玄学变成伪装基线 = 违背诚实定位。三条红线全守：① 完全确定性可复现（禁随机）② 绝不读赛果 ③ 不灌实力先验（队名仅 hash 进取用层做主客归属+区分同时刻不同对阵）。
- **`xuanxue.py` 七法全部重写为忠实排盘**（每法带 `_前缀_` 专用表/辅助，互不冲突；共享工具 `_settle/_conf/_goals/_sign_winner/_tiyong/GUA/WX_*` 不动；**ganzhi.py 零改动**）：
  - **梅花**：时间起卦三步(年支+月+日%8 上卦／+时%8 下卦／总和%6 动爻) + 动爻定体用 + 互卦(2345爻) + 变卦 + 卦气旺衰。
  - **射覆**：梅花路线占时起卦，由卦五行**生成数 × 旺衰 × 动爻**"射"出进球数(覆物之数)，比分真由象数推导。
  - **周易**：以数起卦得本卦→动爻→变卦；综合 64 卦卦义吉凶表 `_YJ_AUSPICE` + 动爻爻位中正(程序化) + 体用生克 + 本卦→变卦升降。
  - **六爻**：京房八宫(程序生成 64 卦)定世应 + 纳甲配五行六亲(父母/兄弟/子孙/妻财/官鬼) + 六兽 + 月建日辰旺衰生克 + 旬空/月破/冲合/暗动，世(主)/应(客)+子孙官鬼取用。
  - **奇门**：定阴阳遁/三元/局数(节气近似) → 地盘三奇六仪 → 天盘九星/八门/八神 → 值符值使旬首遁仪 → 主(日干)/客(时干)落宫断旺衰+格局(青龙返首/飞鸟跌穴/三奇得使/入墓/门迫/伏吟/五不遇时)。地盘已用 KB 阳遁1局/阴遁9局样例逐宫核验。
  - **大六壬**：月将加占时排天地盘 → 起四课 → **九宗门**发三传(贼克/比用/涉害/遥克/昴星/别责/伏吟/返吟/八专) → 昼夜贵人顺逆布十二天将 → 日干(主)/日支(客)取用断课体。
  - **紫微**：节气月+时辰定命宫/身宫(五虎遁定干) → 命宫干支纳音起五行局 → 局+生日安紫微 → 紫微系(逆)/天府系(顺)排 14 主星入 12 宫 → 庙旺利陷表 `_ZW_BRIGHT` + 生年四化落宫，命(主)/迁(客)取用。农历以节气月/干支日序**近似**(已标注)。
- **修复一处边界 bug**：奇门值符遁仪落**中5宫**时 `_QM_GATE_HOME[5]` KeyError（agent 3 个 fixture 未覆盖，历史 49438 场触发）→ 加 `fu_eff=2 if fu_pal==5`（中5无门寄坤2）。
- **诚实铁证保持**：历史 49438 场回测，七法胜负命中 **31.6%–38.3%**（贴随机 33.3%），全部**低于无脑基线「永远押主胜」49.0%**；精确比分 1.9%–6.1% 低于「全押最常见比分 1-0」10.3%。**忠实度大升但仍打不过基线——正是诚实定位要的结果**（排盘更正统 ≠ 更准）。
- **实测**：`xuanxue.divine` 7 法齐全/score 0..6 与 winner 自洽/可复现；`/api/xuanxue` + `/api/xuanxue/board` 200；historical_leaderboard 49438 场 4.7s（`_num` lru_cache）；截图两排行+CI+基线+逐场卡齐显、布局正常；**test_core 26 项全绿**。
- **可继续**：① 奇门精确局数可让 ganzhi 多导出 `jie_name`(24 节气名)替掉「月建→主节气」近似；② 紫微 `_ZW_BRIGHT` 是通行精简口径，可换某流派 168 格全表；③ 各法 detail 现含大量正统术语，前端单场卡可加"起卦依据"展开显示完整 detail。

## 📌 上一次接手（2026-06-20 · 玄学擂台「诚实评估」B 类优化 + 修表头错位）
- **背景**：用户问"为什么命中率比之前低了，且想优化术数算法"。分析后给出诚实结论并选 **B 类(不灌真实先验，让擂台诚实可信)**：① 命中率下降纯属**小样本噪声**(n=28，std≈9.4%)+输入重置重抽；② 数据证明**无脑「永远押主胜」基线 53.6% 碾压全部七法**(最高射覆 42.9%)，奇门暴跌因真太阳时/节气把它推成 43% 押平局的坏分布；③ 任何"提高命中率"的算法优化都等于灌真实先验、把玄学变成伪装基线，故不做。
- **B 类实现**：
  - `xuanxue_board.py`：`_wilson()`(95% 置信区间)、`_baselines()`(永远押最优单一赛果/全押最常见比分/随机1/3)、`_finalize()`(给排行加 CI)、**`historical_leaderboard(df)`**(对全部 49433 场历史国际赛跑 7 法 date-only 占卜，按 `len(played)` 缓存，约 1.8s)。`build_board` 返回新增 `baselines` + `historical{n,leaderboard,baselines}`。`xuanxue._num` 加 `lru_cache` 加速历史回测。
  - **结果(诚实铁证)**：历史 49433 场，七法全挤在 **33.7%–37.1%**(贴随机 33.3%、CI±0.4%)，无脑基线 49.0%；本届 28 场领先者(射覆42.9%)在历史尺度回落到 34.8% → 小样本排名=噪声坐实。
  - 前端 `renderXuanxue` 重构：两张排行(本届实盘 + 历史回测)，每行带 [95%CI]，附三条橙色基线行 + `xxVerdict()` 结论句("没有一套术数能超过基线")。
- **修表头错位**：`.mgt th{text-align:left}` 但数据 td 居中 → 表头靠左数字居中=视觉错位。已给所有数值列的 `th` 显式 `text-align:center`(排行表 + 比赛卡小表)，表头与数据对齐。
- **实测**：board 端点 200(首call 1.8s 后缓存)；截图两张排行+基线+CI 齐显、列对齐；**test_core 26 项全绿**。

## 📌 上一次接手（2026-06-20 · 玄学起卦升级为「干支时间起局 + 球场当地时区」C 混合方案）
- **需求**：① 多 agent 调研七法各自"起卦/起局前需要哪些输入"；结论=七法本质都**时间驱动**，旧 `sha1(队名)+日期` 是"伪起卦"。② 用户选 **C 混合**：开球时刻真正驱动起局，队名只进取用层。③ 用户追问"农历要不要考虑比赛地点时区"→ **要，且是头等大事**（时辰/日干支按事发地当地算；最严格还需经度真太阳时）。
- **新增 `ganzhi.py`**：开球 datetime → 时间柱。**年干支(立春界)、日干支(锚点2000-01-07甲子，精确——已与1949-10-01甲子交叉验证)、时辰地支+时干(五鼠遁)均精确**；月建(节)/月将(中气)用**内置近似节气表**(±1天，无农历/天文库，已标注)。`pillars(when)`/`parse(str)`。CLI 自测。
- **重写 `xuanxue.py`(C 混合)**：`divine(home,away,dt)` 先 `P=ganzhi.pillars(parse(dt))`，7 法都吃 P——梅花(时辰起动爻)、射覆(占时起卦)、周易(月建/日支配上下卦、时辰定变爻)、**六爻(月建定旺衰+日辰生克，真吃干支)**、奇门(日干/时干落宫起局)、**大六壬(月将加占时起天地盘，真)**、紫微(以开球时刻为"诞生时刻"起盘+年干四化 `_SIHUA`)。队名 `_num()` 只用于主客归属 + 区分同时段不同对阵(取用层，已标注奇门/六壬/紫微的"队名入局"属工程扩展)。detail 现显示真实 `甲午日戌时·月将未加戌时·丙午年四化` 等。返回新增 `pillars` 字段。保留 `_tiyong/_settle/_goals/_conf` 与共识自洽逻辑。
- **时区修正(关键)**：`xuanxue_board.py` 新增 `_local_kickoff()`，起卦改用 `schedule.group_venue/ko_venue` 的**球场当地时间**(venues.json 16城 UTC偏移)而非北京时间，账本存 `cast_local`。实测美国vs澳大利亚：北京 6/20 03:00 → 当地(西雅图)**6/19 12:00**，连日干支都因此不同——正是时区影响所在。前端每场卡片显示"🧭 起卦用球场当地 06-19 12:00"。真太阳时(经度级)因 venues.json 无经度未做，已标注近似。
- **实测**：ganzhi CLI 正确(20:00=戌时/芒种后=午月/夏至前=申将)；引擎自检四柱+detail 正确、可复现、45对阵自洽 0 冲突；擂台 28 完赛+12 待测，射覆暂列第一 42.9%；截图三块齐显+当地时间标注。**test_core 26 项全绿**(新增 `test_ganzhi_pillars_known`)。
- **真太阳时(已补，2026-06-20 续)**：① venues.json 的 geo 段给 16 城加 `lng`(球场经度)。② `ganzhi.py` 加 `_equation_of_time`(均时差近似式)+`true_solar(when,lng,offset)`(经度时差 `(lng−offset×15)×4分/度` + 均时差)；`pillars(when,longitude=,utc_offset=)` 给经度则先校真太阳时再起柱，返回 `true_solar`/`solar_corr_min`。③ `xuanxue.divine(...,longitude=,utc_offset=)` 透传。④ `xuanxue_board._cast_args` 返回(当地时刻,城市,经度,偏移)，freeze/backfill 传入并存 `true_solar`/`cast_city`。⑤ 前端卡片显示"🧭 起卦用 {城市}真太阳时 MM-DD HH:MM"。实测西雅图当地12:00→真太阳时10:49(校-70min)，时辰午→巳跨时辰。**test_core 26 项全绿**。
- **精确节气(已补，2026-06-20 续)**：`ganzhi.py` 加 `_julian_day`+`solar_longitude`(太阳视黄经，Meeus 简式 ≈0.01°)+`jian_from_lon`(立春315°起寅,每30°一月建)+`jiang_from_lon`(雨水330°起亥,太阳过宫每30°退一将)。`pillars` 月建/月将改由【真实物理时刻 UTC=当地−offset】的太阳黄经定,删旧近似表(`_JIE/_ZHONG/_latest`)。实测夏至(黄经90°)边界6/21正确将月将申→未、大暑(120°)→午,无交接日误差。**关键区分:时辰用"真太阳时",月建/月将用"真实UTC太阳黄经",物理意义不同分开算。** test_core 26 项仍绿。
- **可继续**：① KO 场回填用 date-only(无 mn 取当地时间/经度)，可补 mn 映射；② 真太阳时为球场级经度(看台级误差可忽略)。

## 📌 上一次接手（2026-06-20 · 玄学 tab 改造为「自动赛程 + 命中率擂台」）
- **需求**：把「🔮 玄学占卜」从"手填两队即时占卜"改成**自动抓近三天即将开赛场次 → 每场冻结 7 法占卜 → 完赛后逐体系统计命中率排行**，看哪套术数猜得最准。
- **关键方法论判断**：占卜引擎 `divine()` **纯确定性、完全不读取赛果**（种子只来自队名+赛期）。因此对【已完赛】场次补算占卜 == 它赛前本就会给的结果，**不构成事后偷看**。故擂台除冻结未来 3 天外，**也把本届已完赛场次补入账本（立即结算）**，让排行榜即刻有样本而非干等。（这与 verify.py 模型预测的回溯严格性不同——模型会偷看，必须 as_of 训练；占卜不会，可直接补算。）
- **实现（新增旁路层，零碰引擎/账本对齐 verify）**：
  - `xuanxue_board.py`：账本 `data/xuanxue_ledger.json`（赛前冻结、`result` 写入后只读，原子写）。`freeze_upcoming`(近 N 天未开球场次起 7 法占卜)、`backfill_finished`(已完赛补算+立即结算)、`settle`(已完赛但 result 空的写真实比分)、`leaderboard`(逐体系 n/胜负命中/精确命中，按胜负命中率降序)、`build_board`(刷新账本后返回 {leaderboard, upcoming, settled, totals})。**复用 `verify._completed/_gkey/_kkey/bj_date/_now_bj`** 保证 key 与赛果查询和「预测验证」一致。`schedule.GROUP/KO` 取开球时间。
  - `app.py`：`GET /api/xuanxue/board`（用全局 `_sim()`+`DF`，异常→500 不崩页）。import `xuanxue_board as xuanxueboardmod`。旧 `/api/xuanxue`（单场）保留（测试与潜在复用）。
  - `templates/index.html`：`#xuanxue` section 去掉双队输入，改成 擂台说明+🔄刷新；`loadXuanxue(force)` 拉 `/api/xuanxue/board`；`renderXuanxue(b)` 出三块——🏆命中率排行（奖牌+金色高亮榜首）、🔮近 N 天待测（每场 7 法占卜小表）、✅已完赛回顾（带 🎯比分/✓胜负/✗ 命中标记，`xxMatchCard(mt,settled)`）。`DataScheduler.register('xuanxue', 2min, …)` 完赛后自动结算并入排行。`data/xuanxue_ledger.json` 已加 .gitignore。
  - **实测**：CLI `python3 xuanxue_board.py` + 端点 200；当前 28 场已完赛、12 场待测，奇门遁甲暂列第一 57.1%（16/28）。截图三块齐显。
  - **冒烟测试**（`test_core.py` 现 **25 项**）：`test_xuanxue_board_leaderboard_counts`（合成账本验命中计数/未结算不计/排序）、`test_api_xuanxue_board_ok`（端点 + 命中数≤场次）。
- **可继续**：① 排行榜可加"数据模型"作基线行对比（被用户上一轮砍过，慎重）；② 各体系按 stage/赔率分桶看命中率；③ 擂台样本仍小，命中率排名波动大，UI 已提示。

## 📌 上一次接手（2026-06-19 晚 · 新增「🔮 玄学占卜」彩蛋，后演进为独立 tab）
- **需求/定位**：用户要把传统术数当**文化/算法素材**做成趣味彩蛋，7 套体系各出一个比分，与 DC 模型**并列对照**。明确是娱乐/文化研究，**不涉及赌博推单**；UI 全程强声明"无科学依据、与模型概率无可比性、勿用于投注"。知识库源在 `~/xuanxue-kb/`（8 篇 md：奇门/八卦易经/六爻/大六壬/梅花/紫微/射覆 + 索引）。
- **实现（纯衍生展示层，零碰 GLM/训练/账本，遵守"5 套算法隔离红线"）**：
  - `xuanxue.py`：**确定性**玄学引擎（种子=`sha1(队名)`+赛期，同场比赛每次一致，不用随机）。7 个函数 `m_meihua/m_shefu/m_yijing/m_liuyao/m_qimen/m_daliuren/m_ziwei`，各基于真实符号系统（先天卦数/五行生克/干支/九宫八门/十二天将/十四主星）做启发式映射→`{score,winner,confidence,detail}`。`divine(home,away,dt)` 汇总 + 玄学共识（胜负多数票+最高频比分）。`_tiyong` 体用生克（体=主队）、`_settle` 让比分与胜负自洽并封顶、`_goals` 偏低分映射、`_ganzhi_day` 锚点 2000-01-07 甲子（仅取数非权威历法）。**非严格传统排盘**，是 grounded 启发式，注释已如实标注。
  - `divine()` 仍算并返回 `consensus`（共识比分只在"投了共识胜方"的体系里取最高频，保证胜负↔比分自洽；45 对阵 0 冲突），但**前端已不再展示**（见下）；保留供 CLI/测试用。
  - `app.py`：`GET /api/xuanxue?home=&away=&dt=`（缺队名→400，异常→500 不崩页；`dt` 缺省用揭幕日 2026-06-11）。import `xuanxue as xuanxuemod`。
  - `templates/index.html`：**独立顶级 tab「🔮 玄学占卜」**（`data-t="xuanxue"` + `<section id="xuanxue">` 自带双队输入/⇄/起卦按钮 + `xuanxueLoaded` 懒加载 + section 切换数组加 `xuanxue`）。`loadXuanxue()` 只取 `/api/xuanxue`；`renderXuanxue(x)` 出紫色卡——**仅 7 体系表**（比分/胜负/信心/起卦依据）+ 底注。`#xuanxue` 深链自动可用。**演进史**：先做成挂在对阵分析报告末尾的卡片 → 改独立 tab → 用户嫌「玄学共识 vs 数据模型」对照没用，删掉该块（连带去掉 `/api/predict` 对照请求），现仅留 7 法表。
  - **冒烟测试**（`test_core.py`，现 **23 项**）：`test_xuanxue_seven_methods_and_valid_scores`（7 法齐全/比分 0..6 整数/单法胜负↔比分自洽/信心 0..100）、`test_xuanxue_consensus_self_consistent`（21 对阵共识自洽）、`test_xuanxue_deterministic`（同对阵+赛期逐位可复现）、`test_api_xuanxue_ok`（端点 200 + 缺参 400）。
  - **诚实边界**：每处都标娱乐/文化、无科学依据、禁投注；引擎层 docstring 同款声明。与 DC 的对照刻意说明"恰好一致=纯属巧合"。
- **验证**：`xuanxue.py` 自检 + 可复现性 True；`/api/xuanxue` 200、缺参 400；headless `--dump-dom` 确认卡片 7 体系/共识/声明全渲染；**内联真实 API 数据的独立 HTML 截图**确认视觉正常（绕开 manager 报告超长截不全的问题）；`test_core.py` **19 项全绿**（未加新单测，纯衍生层）。
- **可继续**：① 给 `xuanxue` 加 `test_core` 冒烟（断言 7 法齐全+可复现+比分合法）；② 看板「看预测」弹窗也可挂玄学小条；③ 知识库 JSON 表（八卦/纳甲）可抽成 `data/` 数据文件供引擎直读，减少硬编码。

## 📌 上一次接手（2026-06-19 · 5-agent 评审驱动的 5 阶段大优化）
5 个角色 agent（产品/算法/美术/文案/研发）评审后落地，全程 test_core 绿（现 **19 项**，新增 bj_date 口径单测）、CDP 实测全 tab **0 JS 异常**。
- **Phase 0 正确性&事实**：① `_refit_all` 加 `_REFIT_LOCK`（acquire 不到就跳过本次重训）+ `model.pkl` 原子写——根治 Flask 多线程并发重训写坏 pkl / 半构造 `_SIM`。② 文案 `half_life 240→730`、header「中立场建模」→「含东道主主场修正」（事实硬伤）。③ 「看预测」弹窗口径修复：`/api/predict` 新增 `host`/`city` 参数走 `verify.pair_predict`，看板「正在比赛/即将开赛」行带 host→弹窗与看板概率**同口径**（US v AUS 实测 0.334=0.334）。
- **Phase 1 结构精简（6→5 tab）**：「单场预测」并入「⚽ 对阵分析」（原足球经理人）——`manager.build_report` 加 `matrix`，`renderManager` 模块四加比分矩阵热力图；删 `#match`/`predict()`/`swapTeams`/`mv`，`#match` 深链 remap→`#manager`。夺冠 tab 把「解读/伤停/环境」收进 `<details>` 折叠降密度。晋级树↔夺冠加交叉链接（点明 投影路径 vs 概率分布）。
- **Phase 2 数据更新统一调度**：前端 `DataScheduler`（单心跳 15s，只在「该任务 tab 当前可见」时触发，切走自停）取代 4 个散 `setInterval`；`postLive()` 在途去重。后端：`/api/live` 加 15s 节流缓存；`regen_champ_ci_async(force)` 20min 节流、`regen_odds_async(force)` 15min 节流（定时器/手动 snap/手动 regen 传 force=True 无视节流）。**只读端点绝不触发重训**（铁律守住）。
- **Phase 3 UI&文案**：`:root` 增设计 token（--mut2/--dim/--blue/--chip/--line2/--gold + 胜平负三色 --wdl-h/d/a）；`.tab.on` 从实心绿改描边+底部强调线（不抢 .go 主按钮权重）；live 卡胜平负三色统一到全站 token。文案：「全量同步数据库」→「更新历史数据」（去 martj42 黑话）、晋级树长说明拆 3 句、北京/当地+RPS+CLV+可信区间+蒙特卡洛加人话 tooltip、「运行蒙特卡洛」→「开始模拟」。
- **Phase 4 工程卫生**：比分矩阵渲染去重为单一 `scoreMatrixHTML(m,hi,hj)`（单场/弹窗/对阵分析共用）；抽 `verify.bj_date(kickoff,fallback)` 统一北京日口径 + 单测（守反复修过的 off-by-one）；删单场预测遗留死代码（mv/.grid/.tops）。**前端 tab-对象级模块化按架构师建议判为"渐进、不大爆改"暂缓**（高风险低即时收益；散 setInterval/重复渲染等真痛点已在 P2/P4 解决）。
- **5 套算法隔离红线（产品/UI 合并时务必守）**：DC 预测引擎(唯一进训练) / bayes 后验(补充视图只读) / in-play 实时(赛中条件,不进账本) / 市场CLV(外部审计) / 经理人(衍生展示) ——数据层单向不回灌，UI 可同屏但禁合并成一个数字。

## 📌 上一次接手（2026-06-19 · 修实时比分 ESPN 拉取 503）
- **症状**：点「⚡ 实时比分」弹错 `ESPN 实时源拉取失败：<urlopen error Tunnel connection failed: 503 Service Unavailable>`。
- **根因**：macOS **系统代理节点偶发 503**（Tunnel failed）。`live._fetch_json` 原是单 URL、无重试、`urllib.urlopen` 默认走系统代理，代理一抖就整体失败。实测 ESPN **直连可达**（系统代理/直连当时都能成，是瞬时抖动）。
- **已修（`live.py`）**：`_fetch_json` 改为 **先系统代理后直连各重试 2 次**——加 `_NOPROXY_OPENER = build_opener(ProxyHandler({}))`，循环 `(None, _NOPROXY_OPENER)` × retries，任一成功即返回，全败才抛。瞬时 503 自动重试/回退直连恢复。（与 app.py martj42 的 `_fetch` 多镜像+重试同思路；headless 截图历来用 `--no-proxy-server` 也是绕这个代理。）
- 验证：`live._fetch_json` 直接调通；重启后 POST `/api/live` 返回 ok=True、live_total=28、error=None；test_core 18 项全绿。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-19 · 晋级树说明文案移到按钮下方）
- **需求**：晋级树 tab 顶部那段长说明（「本次世界杯实时预测…」）原本作为 `.row` 里最后一个 `flex:1` 项挤在按钮右侧，渲染成右侧一长条竖排、左边留大片空白。改为**放到按钮行下方**整宽一段。
- **改动（`templates/index.html`）**：把说明 `<div class="muted">` 从按钮 `.row` 里移出，作为 `.card` 内按钮行的兄弟、`margin-top:12px;line-height:1.6` 整宽显示。`#livestat`(flex:1) + 北京/当地 toggle 仍留在按钮行。intro 卡片高度大幅缩短、括号上移。
- 验证：headless 截图确认按钮成行、说明在下方整宽、卡片紧凑；test_core 18 项全绿。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-19 · 修晋级树点实时比分后布局崩坏）
- **症状**：晋级树 tab 点「⚡ 实时比分」后括号变全尺寸溢出（框超大、列铺满整宽、无缩放）。
- **根因**：`layoutBracket` 算缩放 `scale=avail/natW` 时未防边界——当括号在**隐藏态**被重渲（5min 自动轮询 `liveFacts` 不判当前 tab，只看 visibility+bracketLoaded）→ `clientWidth=0`、`natW=0` → `0/0=NaN` → `scale(NaN)` 被浏览器判为非法 → **不缩放=全尺寸**；可见态下若在回流前测到 `natW=0` 则 `avail/0=Infinity→scale(1)` 同样全尺寸。两条都恰好复现用户截图。
- **已修（`templates/index.html`）**：`layoutBracket` 加双护栏——①`if(!fit.clientWidth)return`（隐藏/未布局不乱算，留待切回 tab 的 layout 重拟合）②`if(!natW){setTimeout(layoutBracket,200);return}`（宽度没回流出来先不缩，稍后重试）；整段包 try/catch，异常也不停在 `transform:none`。`loadProjection` 重排时机从写死 `setTimeout 80/320` 升级为 `rAF×2 +（120/360 兜底）+ fonts.ready`，可见 tab 拿最准回流时机、后台 tab 兜底、字体回流后再拟合一次（重复调用安全）。
- **注意**：跑中的 app 服务的是**正确**模板（含 `.wrap{max-width:1180px}` 与新布局）；用户截图里内容铺满整窗（未受 1180 限制）说明其浏览器是**旧缓存页**——让用户 Cmd+Shift+R 硬刷新。代码侧已加固，避免该类"重渲后没缩放"复发。
- 验证：CDP 实测 点实时比分 前后 scale 一致(0.728/0.968)、隐藏态重渲不再产生 NaN/全尺寸、切回 tab 自动重拟合（svg 连线齐）；test_core 18 项全绿。
- **关键后续（同日）：根因其实是浏览器缓存旧 HTML**——用户截图内容铺满整窗（未受 `.wrap{max-width:1180px}` 限制），而服务端模板早已正确；说明跑的是旧缓存页里的旧 `layoutBracket`。单页 HTML 内联全部 JS/CSS，浏览器缓存文档 → 改了前端也不生效。**已给 `app.py` 的 `/` 路由加 `Cache-Control: no-cache, no-store, must-revalidate` + Pragma + Expires**（`make_response`），从此每次加载都是新版。CDP 在用户同环境（retina 908px）实测：新代码 点实时比分 前后均 `scale(0.728)`、布局正常。
- **再后续：用户精确指出是 `#livestat`「实时源已同步…」文案撑宽**。CDP 在 1817px 窗口对当前代码注入该文案，布局**完全稳定**（wrapClientW=1180、fitClientW=1098、scale 不变）——当前代码无此 bug；用户页面内容铺满整窗坐实仍跑**旧缓存 JS**（旧版无 max-width/行不 wrap，长文案横向溢出撑宽 body→`bfit.clientWidth` 虚高→`avail≥natW`→`scale(1)` 全尺寸）。已加三重防御彻底免疫：① `layoutBracket` 的 `avail=Math.min(fit.clientWidth, documentElement.clientWidth)`（视口宽钳住缩放分母，兄弟元素溢出再撑不大括号）② `body{overflow-x:hidden}` ③ `#livestat{flex:1 1 180px;min-width:0}`。**终极办法：开 `http://localhost:8000/?v=3`（新 URL 不命中缓存必加载新代码）或关掉久开的旧标签重开**——光按刷新可能被 bfcache 挡。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-19 · 实力榜并入「夺冠概率」tab）
- **判断**：实力榜 与 夺冠概率 **不是严格重复**，而是**同一套贝叶斯后验的上下游两视图**——`bayes.py` 同时产出 `bayes_ratings.json`（实力榜：每队净实力 atk+dfc + 94% CI）和 `bayes_draws.npz`（夺冠 90% CI：把同一后验整套灌进模拟器跑 MC）。即夺冠 CI = 实力榜后验**经括号传播**的结果。故合并，不丢算法。
- **算法没有"淘汰"**：DC 仍是回测最优的**点预测**引擎（夺冠%漏斗 `/api/champions` 用 DC MC）；bayes 是**唯一带 CI** 的评级/不确定性层，且是夺冠 CI 的来源。两者各司其层，删任一都丢信息。
- **改动（纯前端，后端 `/api/ratings` 原样保留）**：删掉「实力榜」顶级 tab；把 `#ratingsres` 移进 `#champ` section（顺序：夺冠CI whisker → 夺冠漏斗 → 实力榜评级 → insights/avail/env）；champ tab 打开时懒加载 `loadRatings()`；`#ratings` 旧深链 remap 到 `#champ`；实力榜卡片文案点明"是上方夺冠 CI 的上游"。
- 验证：`/api/ratings` 48 队正常、headless 截图夺冠 tab 内两段（夺冠CI + 实力榜）齐显、tab 栏已无实力榜、test_core 18 项全绿。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-19 · 修看板时区错位 off-by-one）
- **症状**：看板「即将开赛」按日分组的日期表头与每行展示的【北京】开球时间对不上——凌晨开球的场次（北京日 > 场馆当地日）被归到前一天；「已结束」同样错位。
- **根因**：日期口径混用。`schedule.py` 全是北京时间，但分组/显示日期用了**场馆当地日**：①`app.py` 看板 upcoming 行的 `date` 取自账本 `fixture_date`（当地日）；②账本 `date` 本身不一致——`verify.freeze` 小组赛存当地日(`fixture_date`)、淘汰赛存北京日(`kickoff[:10]`)；③`api_project` 的 `today` 用服务器本地 `dt.date.today()`（非北京）。
- **已修（全部统一到北京口径，纯展示层，不回填重算预测）**：
  - `app.py` 看板 upcoming：`date` 改用 `kickoff[:10]`（北京日），无 kickoff 才回落账本 date。
  - `verify.evaluate`（已结束行）：`date` 改从存的北京 `kickoff[:10]` 推导（立即修正全部已冻结旧条目），retro 无 kickoff 才回落。
  - `verify.freeze`：小组赛 `date` 也存 `kickoff[:10]`（与淘汰赛一致，账本不再混用当地/北京）。
  - `app.py api_project`：`today=verifymod._now_bj()[:10]`（北京今天，服务器换时区也不错判 进行中/已结束）。
  - **未动**：晋级树 tab 本就正确（每场带 `date`+`time`(北京) 与 `date_local`+`time_local`(当地) 两套配对，北京/当地切换各自自洽）；足球经理人 `schedule_ctx` 北京/当地都明确标注；单场/夺冠/实力榜/市场对标不展示单场开球时间，无此问题。
- 验证：看板 44 场 upcoming 全部 `date==kickoff[:10]`、已结束行北京日修正（墨西哥vs韩国 6/18→6/19）、`/api/project` 正常、test_core 18 项全绿。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-18 · 新增「⚽ 足球经理人」深度报告页）
- **需求**：在比分预测器里加一个新页面「足球经理人预测」，按资深分析师 4 大模块维度出报告：获取过程数据 → 算法模型 → 得出结论。
- **实现（纯只读组装层，零改引擎，遵循"上下文/补充层"铁律）**：
  - `manager.py`：与 insights/inplay/clv 同级的旁路层。三段式——①**过程数据**：`recent_form`(近5场战绩/进失/零封)、`head_to_head`(近5次交锋)、`team_stats`(近20场场均进失球+零封率+DC攻防评级)，全来自 results.csv 真实历史；②**算法模型**：直接调 `model.score_matrix`（DC 双泊松，λ 作 xG）；③**结论**：`derived_markets` 从比分矩阵卷积出 1X2 / 大小球(1.5/2.5/3.5) / BTTS / 总进球分布 / 正确比分Top / **亚盘让球**(净胜球分布推导公平盘) / **竞彩让球**(让1球→让胜/让平/让负) ；`half_full_time`(半全场，按 FH_SHARE=0.45 拆前后半场独立泊松的**启发式**，未套 DC ρ，标低置信)；`confidence`(胜负倾向+高/中/低，平局判 argmax 时降级)。叠加 `availability_for`(伤停)、`schedule_ctx`(场馆/北京&当地时间/东道主主场)、`market_odds`(读 odds.csv 闭盘 1X2 去抽水隐含概率，无则标"纯模型推导非实盘")、Elo 名气对照。
  - `app.py`：`GET /api/manager?home=&away=&neutral=`（队名支持中文/国旗串，KeyError→400，其余异常→500 不崩页），本地化 form.opp / h2h 队名。
  - `templates/index.html`：新增「⚽ 足球经理人」tab + section（双队输入+中立场勾选+生成报告）、`loadManager/renderManager`（4 模块表格 + 结论汇总表 + 胜负倾向框）、`.mg*` CSS、`managerLoaded` 懒加载、`#manager` 深链。
  - **诚实边界**：定性维度（阵型/首发/临场/天气/裁判）明确标注"引擎不提供"，不编造；半全场标低置信；无赔率标非实盘；汇总表带"非投注建议"声明。
  - 验证：test_core 18 项全绿；`/api/manager` 各路径(中立/主场/host赛程/有赔率对阵/错误队名)实测 200/400 正确；headless 截图 4 模块+汇总表渲染正常。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-17 · 修市场对标不能自动刷新）
- **症状**：「💹 市场对标」tab 不能自动刷新拿到新盘口。**数据抓取层没问题**（`espn_odds.fetch_current` 实测 51 场实时盘口、odds.csv 持续更新、30min 后台快照在跑）——是 UI/缓存层冻结。
- **根因**：`/api/market` 的 `_MARKET_CACHE` 只有 `?fresh` 才重建，但前端 `loadMarket()` 从不带 `?fresh`；`marketLoaded` 标志使切回 tab 不重载；无刷新按钮、无自动轮询；后台快照完成也不失效缓存。
- **已修**：后端 `_regen_odds_worker` 快照后 `_MARKET_CACHE.clear()` + `/api/market?snap=1` 触发后台快照；前端 `loadMarket(mode)`（fresh/snap）+ 市场 tab 可见时每 60s 静默 `loadMarket('fresh')` + 切回 tab 重取 + intro 卡「🔄 刷新盘口」按钮。详见 CHANGELOG「2026-06-17」节。
- **回补早期闭盘线**：盘口快照 6.14 才开，6.11-6.13 场次缺对标。ESPN scoreboard 开赛后撤盘口，但 **`summary.pickcenter` 留存最后一档 DraftKings 线（≈闭盘）**可回补。`espn_odds.backfill_finished()`（队名从 event competitors 取，因已完赛 pickcenter 丢 team 对象；summary 调用前按已有跳过）；`build_odds_csv` 按 `retro` 标记区分——**别再用 `captured_at<=kickoff_utc` 比较**（captured_at 是本地 GMT+8、ko 是 UTC，差 8h，曾误判 6.14 实时场为 retro）；retro 场只写闭盘、开盘列空，`clv.py` 逐行守卫使其**不计 CLV**（诚实门槛不破）。`main()` 默认先 backfill 再 snapshot，app 每次刷盘口自动补漏。
- 其余沿袭下节。

## 📌 上一次接手（2026-06-15 · 真实赔率 + 自动化）
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
- `manager.py` 「⚽ 足球经理人」深度报告组装层（只读旁路，不碰引擎）：近期状态/交锋/攻防(过程数据) + DC 比分矩阵(算法模型) + 全盘口推导(结论)；`/api/manager`
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
