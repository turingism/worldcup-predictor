---
name: football-match-forecasting
description: >
  Build and — more importantly — validate a football match forecasting model: Dixon-Coles
  double-Poisson with time-decay weighting, leak-free as-of backtesting, pre-kickoff frozen
  verification ledgers, and calibration checks against bookmaker closing lines. Includes a full
  worked example with a published, auditable track record (2026 World Cup: 104 matches, every
  prediction frozen before kickoff, 67.3% result hit-rate, RPS 0.1528) and an archive of nine
  "clever" ideas that backtesting rejected. Use when building or reviewing a sports forecasting
  model, designing a leak-free backtest, deciding whether a modeling change is real or noise, or
  setting up a falsifiable prediction track record. Not betting advice.
  （构建并验证足球比赛预测模型：Dixon-Coles 双泊松 + 时间衰减加权、防泄漏 as-of 回测、
  赛前冻结验证账本、对标博彩闭盘线的校准检验。含完整实例与可公开审计的战绩，
  以及九个被回测否决的"聪明想法"档案。适用于：搭建或评审体育预测模型、设计防泄漏回测、
  判断一次改动是真实提升还是噪声、建立可证伪的预测记录。不构成投注建议。）
license: MIT
category: ai-ml
tags: football, soccer, forecasting, dixon-coles, poisson, backtesting, calibration, monte-carlo, sports-analytics, model-validation
github_repo_url: https://github.com/turingism/worldcup-predictor
metadata:
  author: melvin
  version: "1.0"
  demo: https://turingism.github.io/worldcup-predictor/
---

# Football match forecasting — build it, then prove it

> **Live demo:** https://turingism.github.io/worldcup-predictor/ ·
> **Source:** https://github.com/turingism/worldcup-predictor
>
> ⚠️ Educational and research use only. **Not betting, investment, or any other advice.**
> Probability is not certainty; gambling is negative-EV for most people over time and is legally
> restricted in many jurisdictions. See the repository README for the full disclaimer.

Most football models are easy to build and impossible to trust. This skill is about the second half:
how to know whether your model is actually any good, and how to make that claim checkable by someone
who doesn't trust you.

---

## English

### The engine, in short

Goals for each side follow a Poisson distribution; log λ is modelled by **attack + defence + home
advantage** in a GLM, then corrected by the **Dixon-Coles ρ term** for the well-known
under-counting of low scores (0-0, 1-1). Fits in seconds by convex optimization on decades of
matches.

Two things matter far more than the model family:

**① Time-decay weighting, tuned by backtest rather than assumed.** Recent matches weigh more, with
weight `0.5 ** (age_days / half_life)`. The half-life is a hyper-parameter you must *scan*, not
guess — and it differs by domain:

| Domain | Optimal half-life | Why |
|---|---|---|
| National teams | ~730 days | Squads turn over slowly; matches are sparse |
| Club leagues | ~365 days | Denser fixtures, faster squad churn |

Never copy one domain's value to the other. In the worked example a 5-league × 3-cutoff scan found
730 days optimal in *no* club league.

**② Separating neutral venue from genuine home advantage.** Tournament matches are mostly neutral;
home advantage (~+23% xG in this data) applies only when a side genuinely plays at home. Conflating
them silently biases every host-nation fixture.

### The part that actually matters: leak-free validation

**Train only on data that existed before the match you are predicting.** This sounds obvious and is
violated constantly. In this project's own history, the training frame did not exclude matches after
the as-of cutoff — giving *negative* ages, so `0.5 ** negative` produced weights above 1 and future
matches dominated the fit. Every backtest number published before the fix was inflated, and the
"optimal" half-life it reported (240 days) was an artifact: short half-lives amplify the leaked
future matches. After the fix the true optimum was 730.

Guard rails worth copying:

- Build the training frame with an explicit `age_days >= 0` filter, and assert it in a test.
- Score with **RPS** (ranked probability score — ordinal-aware, unlike log loss) plus log loss and
  hit-rate. Report all three; a change that improves one and worsens two is not an improvement.
- Use **several as-of cutoffs**, not one. A gain that appears at one cutoff and vanishes at others is
  rotation noise.
- Set the adoption bar *before* you run the experiment, and honour it.

### The verification ledger — a track record someone else can audit

A backtest is your own homework. A **frozen ledger** is a public commitment:

1. Before kickoff, write the full prediction (probabilities, score matrix, model fingerprint) to an
   append-only record with a `frozen_at` timestamp.
2. After the match, attach the real result. **Never touch the pre-match fields again.**
3. Score per match; bucket by confidence; attribute every miss.

Any entry you had to backfill after the fact should be **tagged as such** and reported separately —
an as-of retro model is leak-free but it is not a commitment made in advance, and the difference is
exactly what makes the record worth anything.

Worked example — 2026 World Cup, all 104 matches, ledger published in the repository:

| | |
|---|---|
| Result hit-rate | 70 / 104 = **67.3%** |
| Mean RPS | **0.1528** |
| Exact scoreline | 15 / 104 = 14.4% |
| Mean probability on what actually happened | 0.479 |
| Genuinely pre-frozen | 101 entries (3 tagged `retro`) |

Long-run out-of-sample baseline over ~1,388 internationals: 59.7% / RPS 0.1624. The tournament beat
it — which is a good tournament, not a better model. Say so.

### Read the structure, not just the headline

Of 24 draws, the model called exactly **1**. Being held to a draw accounts for **23** of the 34
misses. On high-confidence fixtures (≥60%) it hit 78.4%.

This is not a defect to fix. `argmax` over three outcomes almost never selects "draw", because a
draw rarely holds the largest share — it is the shared ceiling of every probability model. Report
hit-rate *with* the draw structure beside it, or the number misleads.

### Ideas that sound clever and were rejected by backtest

Archived so you don't pay the tuition twice. Each was implemented, measured, and dropped:

| Idea | Verdict |
|---|---|
| Market-value / transfer-value prior | No accuracy gain |
| Dynamic Elo (as replacement, ensemble, or shrinkage prior) | Dominated by goal-level information |
| Tournament-strength tier weighting | Cuts effective sample, raises variance |
| Negative-binomial over-dispersion | Residuals near-Poisson after the GLM |
| Isotonic / Platt post-calibration | Already calibrated; post-hoc fitting overfits |
| Draw-aware decision rules | `argmax` is already hit-rate optimal |
| Neutral-venue tilt | Real bias found (+2.24pp) but a quarter of the adoption bar |
| ρ recency refit | Inert (+0.000008 RPS) |
| Per-confederation half-life | Noise on a flat basin |

The pattern: goal-level data already encodes most of what these proxies add, and the remaining error
is structural rather than a fixable bias.

### Benchmark against the closing line, and publish the answer

The bookmaker closing line is the strongest public forecast available. Score your model and the
de-vigged closing line on the *same* fixtures.

Use **Shin (1992)** de-vigging rather than proportional normalization — it corrects the
favourite-longshot bias. In this project's data, Shin was the best-calibrated of three methods
(ECE 2.54% vs 3.17% proportional).

Result worth stating plainly: on identical 2026 matches, **the closing line beat the model**
(RPS 0.1462 vs 0.1514). A model that reports this is more trustworthy than one that hides it — and
it is the reason this project has no betting-advice surface anywhere.

### Red lines

Baked into the source, and worth adopting:

- **No buy/skip/stake output.** Not a value rating, not a confidence star, not "the model likes X".
  A denylist plus a render-time self-check guard every generated string; violations throw.
- **No cross-match aggregation into action signals** — no ROI, no profit/loss, no hit-rate-derived
  recommendation. Enforced at the schema level: those fields do not exist.
- **Divergence from the market carries the market-is-right prior by default**, because that is what
  the CLV evidence shows.

### Where to start in the reference implementation

| Concern | File |
|---|---|
| Data layer, time-decay weighting | `data.py` |
| Dixon-Coles engine, score matrix | `model.py` |
| Out-of-sample backtest | `backtest.py` (`bt_*.py` = per-idea A/B studies) |
| Frozen ledger, per-match scoring | `verify.py` |
| Market / closing-line benchmarking | `clv.py`, `market_research.py` |
| Monte-Carlo tournament simulation | `simulate.py` |

Method notes and the full numbers live in `docs/backtest.md`.

---

## 中文

### 引擎本身很短

双方进球服从泊松分布，log λ 由**攻击力 + 防守力 + 主场优势**在 GLM 里建模，再用 **Dixon-Coles 的
ρ 项**修正低比分（0-0、1-1）被系统性低估的老问题。凸优化，几秒收敛。

有两件事比选哪个模型族重要得多：

**① 时间衰减的半衰期要回测扫出来，不能拍脑袋。** 权重 `0.5 ** (age_days / half_life)`，而最优值
分领域：国家队约 **730 天**（换血慢、比赛稀疏），俱乐部约 **365 天**（赛程密、阵容流动快）。
**绝不能把一个领域的超参照搬到另一个**——实例里 5 联赛 × 3 个时间切点的复扫显示，730 天在**任何一个**
俱乐部联赛都不是最优。

**② 中立场和真主场必须分开。** 大赛多数是中立场，主场优势（本数据约 +23% xG）只应给真正的主场方。
混为一谈会让每一场东道主比赛都带上系统偏差。

### 真正决定成败的是防泄漏验证

**只用被预测比赛之前就存在的数据训练。** 这话听着是废话，却反复被违反。本项目自己就踩过：训练帧没有
排除 as-of 截止日之后的比赛，导致出现**负的年龄**，`0.5 ** 负数` 算出大于 1 的权重，未来比赛反而
主导了拟合。修复前发布的每个回测数字都被美化过，而它报出的"最优半衰期 240 天"是伪影——短半衰期
恰好放大了泄漏进来的未来比赛。修复后真实最优是 730。

值得照搬的护栏：

- 构建训练帧时显式加 `age_days >= 0` 过滤，并写进测试断言
- 用 **RPS**（考虑结果有序性，log loss 不考虑）加 log loss 加命中率，三个一起报；一个变好两个变差
  不叫提升
- 用**多个 as-of 切点**，不要只用一个。只在某一个切点出现、换个切点就消失的增益是轮换噪声
- 采纳门槛在跑实验**之前**定好，然后遵守它

### 验证账本：让外人能审计的战绩

回测是自己批自己的作业，**冻结账本**是公开承诺：

1. 开球前把完整预测（概率、比分矩阵、模型指纹）写进只追加的记录，带 `frozen_at` 时间戳
2. 赛后附上真实结果，**赛前字段永不再动**
3. 逐场评分、按置信度分桶、每次失手都归因

事后回溯补录的条目必须**明确标注**并单独统计——as-of 回溯模型虽然不泄漏，但它不是事先做出的承诺，
而这个区别正是整份记录价值的来源。

实例：2026 世界杯全部 104 场，账本随仓库公开。

| | |
|---|---|
| 赛果命中 | 70 / 104 = **67.3%** |
| 平均 RPS | **0.1528** |
| 精确比分 | 15 / 104 = 14.4% |
| 赋予实际赛果的平均概率 | 0.479 |
| 真正赛前冻结 | 101 条（3 条标注 `retro`）|

长期样本外基线（约 1,388 场国际赛）是 59.7% / RPS 0.1624。这届赢了基线——但这是**赛事顺，不是模型
变强**，要如实这么说。

### 看结构，别只看那个总数

24 场平局，模型只叫中 **1** 场；"被逼平"占了 34 次失手中的 **23** 次。而高把握场次（≥60%）命中 78.4%。

这不是待修的缺陷。三向 `argmax` 几乎永远不会选平局，因为平局很少是三者中最大的一项——这是所有概率
模型共同的天花板。报命中率时必须把平局结构放在旁边，否则那个数字会误导人。

### 九个听起来聪明、被回测否决的想法

存档在此，省得你再交一次学费。每一个都实现过、量化过、然后放弃：

身价先验（无增益）· 动态 Elo（三种形态都被进球层信息碾压）· 赛事分级加权（砍有效样本、升方差）·
负二项过离散（GLM 后残差已近泊松）· Isotonic/Platt 后校准（本就校准良好，后校准只会过拟合）·
平局决策规则（`argmax` 已是命中率最优）· 中立场倾斜（偏差真实存在 +2.24pp，但只有门槛的四分之一）·
ρ 近期性重拟（+0.000008 RPS，惰性杠杆）· 分洲半衰期（平底盆地上的噪声）。

共同规律：进球层数据已经编码了这些代理变量想补的大部分信息，剩下的误差是结构性的，不是可调参修掉的偏置。

### 拿闭盘线当基准，并且把结果公布出来

博彩闭盘线是公开可得的最强预测。把你的模型和去抽水后的闭盘线放在**同一批比赛**上评分。

去抽水用 **Shin (1992)** 而不是按比例归一——它修正了冷门-热门偏差。本项目数据里 Shin 是三种方法中
校准最好的（ECE 2.54%，按比例归一是 3.17%）。

值得直说的结果：在 2026 年同一批比赛上，**闭盘线赢过模型**（RPS 0.1462 vs 0.1514）。
一个把这件事报出来的模型，比藏起来的可信——这也正是本项目任何地方都不做投注建议界面的原因。

### 红线

已经写进源码，也建议你照搬：

- **不输出买/跳过/注码**。不给价值评级、不给信心星级、不说"模型看好 X"。违禁词表加渲染期自检守卫，
  违反即抛异常
- **禁止跨场聚合成行动信号**——无 ROI、无盈亏、无由命中率导出的推荐。在 schema 层就断掉：这些字段
  根本不存在
- **与市场分歧时默认挂"市场对、模型错"的先验**，因为 CLV 证据就是这么显示的

### 参考实现从哪读起

数据层与时间衰减 `data.py` · 引擎与比分矩阵 `model.py` · 样本外回测 `backtest.py`
（`bt_*.py` 是各个想法的 A/B 研究）· 冻结账本与逐场评分 `verify.py` ·
市场与闭盘线对标 `clv.py`/`market_research.py` · 蒙特卡洛赛事模拟 `simulate.py`。

方法说明与完整数字在 `docs/backtest.md`。
