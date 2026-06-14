# 营销 / 传播文案包

> ⚠️ **免责声明（请置于任何对外文案最前）**：本项目为**个人学习与技术研究的开源作品**，仅供统计建模与编程学习，**不构成任何投注/投资/决策建议**；作者不对任何人使用本项目、以及由此**直接或间接关联的任何赌球博彩行为及后果**负责。概率≠确定，博彩长期对多数人 EV 为负且多地受法律限制，风险与法律责任由使用者自负。

> 基调：**诚实、可证伪、开源、实时**。绝不出现"稳赢 / 必中 / 内幕"类暗示——这与项目核心气质（拿数字逼自己说真话）一致，也更可信。市场/CLV 层一律强调"做检验、不做下注诱导"。

---

## 1. GitHub 仓库 About（一句话描述）

**中文**
> 用 1872–2026 全量真实国际赛数据 + Dixon-Coles 双泊松引擎驱动的 2026 世界杯实时概率机器：比分预测、夺冠概率（带可信区间）、进行中实时胜平负、样本外回测校准，全部可证伪、随真实赛果自动更新。

**English**
> A falsifiable, self-calibrating World Cup 2026 probability engine — Dixon-Coles double-Poisson on 150+ years of real international results. Score predictions, title odds with credible intervals, live in-play win/draw/loss, and out-of-sample backtests. Open source, real-time, every number checkable.

## 2. Topics / Tags（GitHub topics）
`football` `soccer` `world-cup` `world-cup-2026` `dixon-coles` `poisson` `sports-analytics` `bayesian` `monte-carlo` `forecasting` `flask` `python` `probability` `calibration`

---

## 3. X / Twitter

**EN（Show-HN / dev 向）**
> I built an open-source World Cup 2026 probability engine. Not vibes — Dixon-Coles double-Poisson on 1872–2026 real international results, out-of-sample backtested (ECE ~1%).
>
> • Live in-play win/draw/loss that updates every minute
> • Title odds with 90% credible intervals (hierarchical Bayes)
> • Pre-match predictions frozen before kickoff, then scored — no hindsight
> • A market/CLV honesty layer that refuses to show "value bets" without proven edge
>
> Every number is falsifiable. ⚽ [repo link]

**ZH（中文社媒）**
> 开源了一个 2026 世界杯概率引擎，不是"AI 凭感觉吹球"：
> 📊 1872–2026 全量真实国际赛数据 + Dixon-Coles 双泊松，样本外回测校准（ECE ~1%）
> ⚡ 比赛进行中，胜平负概率随比分/剩余时间实时跳动
> 📈 夺冠概率带 90% 可信区间（分层贝叶斯）
> 🎯 赛前预测开球前冻结存证，逐场核对命中——谁也别想事后改口
> 💹 还有个"市场对标"层：没证明有信息优势，就拒绝给任何"价值投注"暗示
> 每个数字都能被回测证伪。⚽ [链接]

## 4. Hacker News（Show HN 标题 + 首段）
**标题**：Show HN: A falsifiable, self-updating World Cup 2026 probability engine
> It's a Dixon-Coles double-Poisson model fit on every international match since 1872, wrapped in a Flask app. What I cared about most was *honesty*: predictions are frozen before kickoff and scored afterward, the model is backtested out-of-sample (RPS/LogLoss/ECE), and a bunch of "fancy" additions (Elo priors, post-hoc calibration, market-value shrinkage) were tried and **rejected by backtest** rather than shipped. There's a live in-play win/draw/loss layer, Bayesian credible intervals on title odds, and a market/CLV layer that deliberately refuses to surface "value bets" unless it can prove a positive closing-line edge. Feedback welcome.

## 5. 小红书 / 朋友圈（轻量种草）
> 世界杯看球前先看概率📈 自己写了个开源预测器：
> 输两个队 → 最可能比分 + 胜平负 + 完整概率矩阵；
> 一键模拟 → 每队夺冠率（带可信区间）；
> 比赛进行中 → 实时胜平负随比分跳动⚡
> 最爽的是它"诚实"：赛前预测锁死、事后逐场打分，吹得对不对一目了然。
> 纯统计模型，不玄学，不荐彩。⚽

## 6. 一句话电梯陈述（pitch）
> 市面上的"AI 预测"给你一个拍脑袋的结论；我们给你一个**带可信区间、能被回测证伪、随真实赛果自动更新**的概率分布——并且把所有试过却无效的"高级花招"都诚实地标成了否决项。

---

## 7. 责任声明（随营销附带，尤其涉及市场/CLV）
- 本项目是**统计预测与教育工具**，不是博彩建议；市场/CLV 层用于"模型是否真有信息优势"的**可证伪检验**，默认不展示注码。
- 概率 ≠ 确定；任何博彩长期对多数人 EV 为负。如涉及投注，请只用可承受损失的资金并遵守当地法律。
