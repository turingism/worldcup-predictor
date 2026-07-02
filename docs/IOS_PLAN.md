# 世界杯比分预测器 · iOS App 技术方案

> 目标：把现有 Python + Flask 预测器做成 iOS app。本文给出推荐架构、数据流、
> Swift 模块拆分、开发里程碑、上架清单、成本与风险。读完再决定动不动手。

---

## 0. 一句话结论
**推荐方案 A：原生离线 App。** 把现有 Flask 降级成「定期重训 + 发布一个小 JSON」的静态后端，
iPhone 端用 Swift 重写**预测/模拟/括号/解读**（全是初等数学，易移植）。
离线可用、原生流畅、App Store 友好、几乎零托管成本。

---

## 1. 核心约束（决定一切）
- `numpy/scipy/statsmodels` **无法在 iOS 设备原生跑**，Apple 也禁止 app 内置可下载代码的解释器。
- 但**只有「训练/拟合」需要 Python**（statsmodels GLM + scipy 优化 + PyMC 贝叶斯）。
- **「预测」全是初等数学**：泊松 PMF、Dixon-Coles 低分修正、蒙特卡洛抽样、组合括号逻辑——Swift 轻松重写。
- 训练产物（每队 attack/defence + 截距 + 主场优势 + rho + Elo/贝叶斯评级）就是**一个小 JSON**（几十 KB）。

→ 所以：**训练留服务器（离线/定时），预测搬上设备。**

---

## 2. 推荐架构（方案 A）

```
┌─────────────────── 服务器侧（只在重训时运行，可定时/手动）───────────────────┐
│  现有 Python 引擎（model.py 拟合 + elo.py + bayes.py）                        │
│   每天/每场后：拉最新赛果 → 重训 → 跑 export_ios.py                            │
│        ↓ 产出                                                                  │
│  model_bundle.json （系数 + 赛程 + 场馆geo + 伤病 + Elo/贝叶斯评级 + 赛制结构）  │
│        ↓ 发布到                                                                │
│  静态托管（GitHub Pages / S3+CloudFront / 任意 CDN）—— 无需常驻服务器          │
└───────────────────────────────────────────────────────────────────────────┘
                              ↓ HTTPS 拉取（带本地缓存 + App 内置快照兜底）
┌─────────────────────────── iOS App（SwiftUI，全离线计算）──────────────────┐
│  Engine（Swift 重写）：DixonColes 预测 · TournamentSim 蒙特卡洛 · Bracket 括号 │
│                        · Adjust 伤病 · Env 海拔高温 · Insights 解读           │
│  UI：单场预测 / 晋级树 / 夺冠概率 / 实力榜 / 模型解读                          │
│  本地存储：用户假设赛果(overrides)、时区/单位偏好                              │
└───────────────────────────────────────────────────────────────────────────┘
```

**关键洞察**：app 自己算所有东西，所谓「后端」只是个**定期发布 JSON 的静态文件**。
→ 没有 per-user 服务器成本、无连接也能用（用缓存/内置快照）、扩展性无限。

---

## 3. 数据流
1. **构建期**：`export_ios.py` 把 `model.pkl` + `elo` + `bayes` + `data/*.json` 打包成
   `model_bundle.json`，随 app 内置一份「出厂快照」。
2. **运行期**：app 启动后台拉取 CDN 上最新 `model_bundle.json`（ETag 缓存）；拉到就热更，
   拉不到/离线就用上次缓存或内置快照。
3. **预测**：用户操作 → Swift Engine 即时本地计算（毫秒级）→ 刷新 UI。
4. **假设赛果**：用户在括号里录入/试算 → 存本地 → 重算夺冠概率（同现在网页交互）。
5. **赛事期更新**：服务器侧定时重训发布新 bundle，用户开 app 自动热更，无需更新 app。

---

## 4. 模块移植表（Python → Swift）

| 现有 Python | 去向 | 说明 |
|---|---|---|
| `model.py` 拟合(`fit/_fit_rho/_apply_market_prior`) | **留服务器** | statsmodels GLM + scipy，只在重训跑 |
| `model.py` 预测(`expected_goals/score_matrix/predict/_goal_pmf/_tau`) | **→ Swift** | 初等数学，~150 行 Swift |
| `model.py` 上下文乘子(avail/env) | **→ Swift** | 直接照搬乘子逻辑 |
| `simulate.py` 全部(蒙特卡洛/小组/括号/投影) | **→ Swift** | 最大块，~400 行；需种子 RNG |
| `wc2026.py`(GROUPS/R32_SLOTS/resolve_r32/assign_thirds) | **→ Swift** | 静态数据 + 组合逻辑，注意 `sorted` 可复现 |
| `schedule.py`(开球时间/场馆/时区) | **→ Swift + JSON** | 数据进 bundle，换算逻辑进 Swift |
| `adjust.py`(伤病) | **→ Swift + JSON** | availability 进 bundle |
| `env.py`(海拔/高温) | **→ Swift + JSON** | venues geo 进 bundle |
| `insights.py`(模型vs名气) | **→ Swift** | 排名比对，~80 行 |
| `elo.py` / `bayes.py` | **留服务器** | 产出评级 JSON 进 bundle |
| `data/results.csv`(训练数据) | **不上设备** | 只上训练产物 |
| `app.py`(Flask) | **降级/退役** | 改成 `export_ios.py` + 静态发布；或保留作可选 API |
| `templates/index.html` | **重写为 SwiftUI** | 5 个界面 + 括号自绘 |

---

## 5. Swift 工程结构（SwiftUI）
```
WorldCupPredictor/
├─ Models/            Codable 结构：TeamCoef, Fixture, Venue, Availability, Bundle…
├─ Engine/
│  ├─ DixonColes.swift     预测：expected_goals + score_matrix + DC 修正
│  ├─ Tournament.swift     蒙特卡洛 + 小组积分 + 出线
│  ├─ Bracket.swift        2026 官方括号 + resolve_r32 + 最佳第三名
│  ├─ Adjust.swift / Env.swift   上下文乘子
│  ├─ Insights.swift       模型 vs Elo 偏差解读
│  └─ SeededRNG.swift      可复现随机数（xoshiro/GK MersenneTwister）
├─ Networking/        BundleFetcher：拉取+ETag缓存+内置快照兜底
├─ Store/             Overrides 本地持久化（FileManager/UserDefaults）
├─ Views/             MatchPredict / Bracket / Champions / Ratings / Insights
└─ Resources/         model_bundle.json（出厂快照）、App 图标、Flag 资源
```

**数值/性能**：泊松 PMF 用 `Foundation` 数学；蒙特卡洛在 iPhone 上比 Python 更快
（现 Python 5000 次≈0.4s，Swift 原生预计更快，甚至可调高迭代）。括号用 SwiftUI `Canvas`/自定义布局重画连线。

---

## 6. 开发里程碑

| 阶段 | 内容 | 产出 | 估时* |
|---|---|---|---|
| P0 | `export_ios.py` + bundle schema 定稿 | 可发布的 model_bundle.json | 1-2 天 |
| P1 | Swift Engine 移植 + **对拍测试** | 预测/模拟/括号与 Python 数值一致 | 1-2 周 |
| P2 | SwiftUI 五屏 + 括号自绘 | 可交互 app | 1-2 周 |
| P3 | 网络拉取/缓存/离线 + 假设赛果持久化 | 热更 + 离线可用 | 3-5 天 |
| P4 | 打磨/图标/截图/TestFlight 内测 | 可提审版本 | ~1 周 |

\* 单人、熟悉 Swift 的节奏；**我能生成绝大部分代码**，可显著压缩 P1-P3。
**对拍测试是关键**：确定性部分（预测概率/期望进球/括号分配）逐位对齐 Python；
蒙特卡洛部分按统计区间对齐（跨语言 RNG 无法逐位相同）。

---

## 7. 上架清单（App Store）
- **Apple 开发者账号** $99/年（个人或公司）——必须。
- Xcode（你的 Mac 装）、Bundle ID、签名证书 + Provisioning（Xcode 自动管理可）。
- App 图标(1024)、各尺寸截图、隐私政策 URL、App 隐私问卷（本 app 几乎不收数据，填「不收集」最省事）。
- TestFlight 内测 → 提审 → 审核（通常 1-3 天）。

## 8. 成本
- **Apple 开发者**：$99/年（硬性）。
- **托管**：用 GitHub Pages / GitHub Actions 定时重训发布 JSON ≈ **$0**；若要按需重训可加个 ~$5/mo 小 VPS。
- **无 per-user 后端成本**（算力在设备）。

## 9. 合规风险（务必注意）
- **商标**：「FIFA」「World Cup」「世界杯」及官方会徽是注册商标。**不能用官方 logo/会徽、不得暗示官方授权**。
  → app 名用中性名（如「2026 足球大赛预测」），自绘图标，球队用 emoji 国旗（一般安全）。
- **博彩红线**：Apple 对真钱博彩管控严。本 app 定位**数据分析/娱乐**，**不得**导流博彩、不显示可下注赔率、无博彩联盟链接。
  → 保留项目现有「不含投注引导」立场，加免责声明。否则易被拒或下架。
- **「仅网站」拒审**：方案 A 是真原生 app + 本地计算，天然规避；方案 C（WebView 套壳）才有此风险。

## 10. 三方案对比（再次）
| | A 原生离线 | B 瘦客户端+API | C WebView 套壳 |
|---|---|---|---|
| 体验 | 原生、离线、流畅 | 原生界面、需联网 | ≈网页套壳 |
| 工作量 | 中-大（Swift 重写预测层）| 小-中 | 最小 |
| 托管成本 | ≈$0（静态 JSON）| 需常驻服务器 | 需常驻服务器 |
| App Store 风险 | 低 | 低 | **高（仅网站拒审）** |
| 离线 | ✅ | ❌ | ❌ |
| 推荐度 | ⭐⭐⭐ | ⭐⭐ | ⭐ |

## 11. 建议的第一步（若决定做）
1. 我先写 `export_ios.py`，把当前 `model.pkl`/elo/bayes/数据导出成 `model_bundle.json`（不碰现有功能）。
2. 定 bundle 的 JSON schema（Swift `Codable` 对应）。
3. 写 Swift `DixonColes.swift` + 对拍脚本，证明**同输入 Swift 与 Python 预测逐位一致**。
   —— 这一步打通即证明整条路可行，再继续 P2 UI。
<!-- Repository summary: World Cup prediction analytics planning notes. -->
