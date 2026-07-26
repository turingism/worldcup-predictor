# ⚽ 顶级足球赛事预测器

<p align="right"><a href="./README.md">English</a> · <strong>简体中文</strong> · <a href="./README.zh-TW.md">繁體中文</a></p>

### **[▶ 打开在线版](https://turingism.github.io/worldcup-predictor/)** —— 不用装、不用配 API key

Dixon-Coles 双泊松引擎，用 1872–2026 全部国际比赛训练，另有欧洲五大联赛各自独立的俱乐部模型。每个数字都可证伪：任何模型改动**必须在样本外回测里赢过基线**，否则不采用。

> ## ⚠️ 免责声明 / Disclaimer
> 本项目为**个人学习与技术研究的开源作品**，仅用于统计建模、数据分析与编程学习目的，**不构成任何形式的投注、投资或决策建议**。作者不对任何人使用本项目的行为、以及由此**直接或间接关联的任何赌球、博彩等行为及其后果**承担任何责任。所有输出均为统计概率估计——**概率不等于确定结果**；博彩长期对绝大多数人期望收益为负，且在许多法域受法律限制。是否参与、以及由此产生的一切风险与法律责任**完全由使用者自行承担**。本项目按"现状"（as-is）提供，不附带任何明示或默示担保；使用即视为已阅读并同意本声明。
>
> *This is a personal, educational open-source project for statistical modeling and programming study only. It is **not** betting, investment, or any other advice. The author accepts **no liability** for anyone's use of it or for **any gambling/betting activity directly or indirectly associated with it**. All outputs are probabilistic estimates — probability is not certainty; gambling is negative-EV for most people over time and is legally restricted in many jurisdictions. You bear all risk and legal responsibility. Provided "as is" without warranty.*

<p align="center">
  <img src="./docs/screenshot-dashboard.png" alt="赛事看板：正在比赛 / 即将开赛 / 已结束三态同屏，按日分组的预测与每场深度报告入口" width="820">
</p>

---

## 两个模型宇宙，同一套引擎

| | 国家队 | 俱乐部 |
|---|---|---|
| 数据 | 1872–2026 全部国际赛，257 支球队 | football-data.co.uk，五大联赛 |
| 半衰期 | 730 天 | 365 天 |
| 覆盖 | 世界杯 2026、欧国联——引擎层面今天就能预测任意国家队对阵 | 英超 / 西甲 / 意甲 / 德甲 / 法甲 |
| 赛事视图 | 含东道主主场修正的蒙特卡洛晋级树、带贝叶斯区间带的夺冠概率 | 赛季模拟器：夺冠 / 前四 / 降级概率 |

两个半衰期都是回测裁决出来的，不是拍脑袋定的，而且**确实不同**——别把一个宇宙的超参照搬到另一个。

**每场比赛给什么**：比分概率矩阵、胜平负、大小球、双方进球、亚盘公平线、一份分析师风格的赛前深度报告（近期状态 / 历史交锋 / 攻防评级），以及一段把概率翻成人话的解读。

**怎么保证诚实**：预测在**开球前冻结**进验证账本，赛后逐场对账——按置信度分桶、标注失手归因。市场 / CLV 层拿模型对标博彩闭盘线，并如实报告：**模型打不赢市场**。

完整功能走查（含全部截图）见 **[`docs/FEATURES.zh-CN.md`](./docs/FEATURES.zh-CN.md)**。

---

## 准确度

样本外、约 1388 场国际比赛，只用截止日之前的数据训练：

| 指标 | 数值 | |
|---|---|---|
| **RPS** | **0.1624** | 越低越好，已在博彩闭盘线的量级 |
| **胜平负命中率** | **59.7%** | 三向 argmax，**全部**国际赛口径 |
| **校准误差 ECE** | **1.06%** | 对照行业基准 8–10% |
| **净胜球相关系数** | **65%** | 高盛自己用的指标 |

要引用就引用**分层数字**，别引用这个混合口径。**仅世界杯正赛**（2014/18/22/26 合并，n=295）是 RPS 0.186 / 命中 61.0% CI[55.6, 66.8]——而在 2026 年同一批比赛上，**博彩闭盘线仍然赢过模型**（0.1462 vs 0.1514）。这个差距被如实报告而不是藏起来，这也正是本项目任何地方都没有投注建议界面的原因。

那些听起来很聪明、但**被回测否决**的做法（省得你交学费）：身价先验 · 动态 Elo（替换 / 集成 / 收缩先验三种形态）· 赛事分级加权 · 负二项过离散 · Isotonic/Platt 后校准 · 平局决策规则 · 中立场倾斜 · ρ 近期性重拟 · 分洲半衰期。

> 剩下的误差是**结构性**的——所有概率模型共有的平局盲区——外加小样本噪声，不是可调参修掉的系统偏置。数字与方法见 **[`docs/backtest.md`](./docs/backtest.md)** 与 `CHANGELOG.md`。

---

## 自己跑

```bash
git clone https://github.com/turingism/worldcup-predictor.git
cd worldcup-predictor
pip install -r requirements.txt

python3 app.py                                    # 网页版 → http://127.0.0.1:8000
python3 predict.py "Argentina" "France" --cache   # 国家队单场
python3 clubpredict.py "阿森纳" "曼城"              # 俱乐部单场（联赛自动识别）
python3 simulate.py --sims 5000                   # 夺冠概率
python3 backtest.py                               # 证明你的改动真的更好
```

首次运行训练模型约 1 分钟并缓存，之后秒出。队名中英文都认。`READONLY=1 python3 app.py` 启动只读分享模式，全部写接口禁用。比赛日运维见 **[`docs/RUNBOOK.zh-CN.md`](./docs/RUNBOOK.zh-CN.md)**。

```python
import data
from model import DixonColesModel

m = DixonColesModel(half_life_days=730).fit(data.load_raw())
r = m.predict("Argentina", "France", neutral=True)
r["top_scores"][0]      # ((1, 0), 0.169)
r["p_home"], r["p_draw"], r["p_away"]
r["matrix"]             # 完整比分概率矩阵
```

---

## 在线版是怎么搭的

在线版是托管在 GitHub Pages 上的**冻结静态快照**，没有服务器。

这是**刻意的架构选择，不是妥协**。本应用实测：一次冷启动的回溯验证峰值内存约 **3 GB**，光 `/api/market` 一个接口就再吃 **873 MB**，预热缓存要 **262 秒**。没有任何免费托管运行时扛得住。但在冻结快照下，每个读接口都是数据的确定函数——于是把这些**全部移进构建期**，而 GitHub Actions 给公开仓库的是免费且无限量的 4 核 / 16GB runner。workflow 训练模型、烤热全部缓存、把整个 API 面预渲染成 JSON 再发布。线上运行时内存为零，首屏就是一次 CDN 文件读取。

```bash
python3 warmup.py                      # 训练 + 烤热缓存
python3 export_static.py --out dist    # 预渲染 API 面
```

前端只加了一层适配：`apiFetch()` 用规范化查询串的 FNV-1a 确定性哈希直接算出预渲染文件的路径，零索引、零预载。动态模式下 `STATIC_MODE` 为 `false`，`apiFetch` 就是 `fetch` 本身，自建部署的行为与从前完全一致。两侧的哈希契约由金标准向量测试钉死——一旦口径悄悄漂移，整站取数都会 404。

静态快照做不到的事：实时 in-play 更新，以及全部写操作（刷新、假设赛果、手动录入）。这些在你自建部署时都有，而 `READONLY=1` 本来就禁用它们，所以两种模式口径一致。

---

## 文件地图

| | |
|---|---|
| `model.py` `data.py` `predict.py` | Dixon-Coles 引擎、数据层、单场 CLI |
| `simulate.py` `wc2026.py` `schedule.py` | 蒙特卡洛赛事模拟、官方赛制、赛程 |
| `clubdata.py` `clubpredict.py` `clubsim.py` | 俱乐部数据层、各联赛模型、赛季模拟器 |
| `verify.py` `clubverify.py` | 赛前冻结与赛后结算 |
| `clv.py` `market_research.py` `explainer.py` | 市场对标、线移动研究、机制解读 |
| `home_dashboard.py` `manager.py` `narrative.py` | 跨赛事首页总览、深度报告、人话解读层 |
| `bayes.py` `champ_ci.py` `inplay.py` | 分层贝叶斯评级、夺冠区间带、实时胜平负 |
| `export_static.py` `warmup.py` | 静态快照构建 |
| `app.py` `templates/index.html` | Flask 后端、单页前端 |
| `test_core.py` | 212 项回归测试 |
| `docs/` | 功能走查、回测、数据源、方法说明、运维手册 |

给 AI 编码助手的操作手册：**[`skill/SKILL.md`](./skill/SKILL.md)**。

---

## 方法源流

Maher (1982) 泊松进球建模 · Dixon & Coles (1997) 低比分相关性修正与时间加权 · Lee (1997) 独立双泊松基线 · Shin (1992) 去抽水用于读市场价格 · Fjelstul World Cup DB 用于重构 90 分钟比分 · martj42 国际比赛结果数据集 · football-data.co.uk 俱乐部数据与赔率。

---

## ☕ 赞赏支持（纯自愿）

免费开源项目。如果它让你看球多了点乐趣，欢迎请作者喝杯咖啡。

<p align="center">
  <img src="./data/sponsor.png" alt="赞赏码（支付宝 / 微信）" width="420">
</p>

> 赞赏**不解锁任何功能**，也不构成购买任何预测服务。所有功能对所有人永久免费。自建部署时把 `data/sponsor.png` 换成你自己的收款码即可。
