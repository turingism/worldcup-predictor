# ⚽ 世界杯比分预测器 (World Cup Score Predictor)

用「**真实国际比赛数据 + 双泊松 / Dixon-Coles 统计模型**」自建的足球比分预测工具。
输出：**最可能比分 + 完整比分概率矩阵 + 胜平负概率 + 期望进球(xG)**。

不是套现成仓库，而是按足球建模的学术标准方法自己拼的逻辑——可读、可改、可扩展。

---

## 为什么是这套方法

| 选择 | 原因 |
|---|---|
| **国际比赛数据**（非俱乐部联赛） | 世界杯是国家队赛事，俱乐部数据无效。用 `martj42/international_results`：1872–2026 全部国家队比分。 |
| **双泊松 GLM** | 每队进球 ~ Poisson(λ)，用进攻力/防守力/主场建模 log λ。凸优化，几秒收敛。 |
| **Dixon-Coles 修正** | 独立泊松低估 0-0/1-1 等低分平局，引入相关参数 ρ 修正。 |
| **时间衰减加权** | 越近的比赛权重越高（半衰期 **240 天**，回测调出的最优值），反映当前状态。 |
| **赛事强度加权** | 友谊赛强度低，权重下调一半。 |
| **中立场处理** | 世界杯多为中立场，主场优势只给真正主队（如东道主）。 |
| **身价先验** | 接入 Transfermarkt 国家队身价（回归「身价→攻防」按权重收缩）。**回测显示对概率准度无改善，默认关闭**；身价数值仍在 UI 展示，可手动开启（`min_market_weight>0`）。 |

---

## 快速开始

```bash
# 1) 安装依赖（anaconda 通常已自带）
pip install -r requirements.txt

# 2) 下载数据（已自带 data/results.csv，更新时再跑）
python3 download_data.py

# 3) 预测（首次训练约 1 分钟，加 --cache 后续秒开）
python3 predict.py "Argentina" "France" --cache
```

## 用法

```bash
# 单场（默认中立场，符合世界杯）
python3 predict.py "Brazil" "Spain"

# 第一支为真正主队（带主场优势，如东道主美国）
python3 predict.py "United States" "Mexico" --home

# 模型实力榜（健全性检查）
python3 predict.py --ranking

# 预测 2026 世界杯全部真实赛程
python3 predict.py --fixtures

# 调时间衰减半衰期（天）
python3 predict.py "Germany" "Japan" --half-life 365
```

> 队名用**英文**（数据源为英文）。拼错会自动模糊提示，例如输入 `brasil` 会提示 `Brazil`。

## 输出示例

```
  ⚽ Argentina  vs  France   (中立场)
  ──────────────────────────────────────────────
  期望进球 (xG):   Argentina 1.17  -  0.75 France

  赛果概率
    Argentina      胜   45.4%  ███████████·············
    平局               30.9%  ███████·················
    France         胜   23.7%  ██████··················

  最可能比分 (Top 7)
    1-0    16.9%   1-1 13.0% ...

  ➜ 最可能比分: Argentina 1-0 France  (16.9%)
```

---

## 夺冠概率（蒙特卡洛模拟）

```bash
python3 simulate.py --sims 5000           # 模拟整届，输出夺冠/进决赛/四强/八强/出线概率
python3 simulate.py --sims 10000 --top 32
```
自动从赛程推断 12 个小组 → 小组赛抽比分算排名 → 出线 32 队（前2 + 最佳8个第三）
→ 单场淘汰（平局点球模拟）→ 统计每队各轮频率。5000 次约 1–2 秒。

## Web 页面

```bash
python3 app.py            # 启动后打开 http://127.0.0.1:8000
```
- **单场预测**：两队下拉 + 中立场开关 → 比分热力图 / 胜平负 / xG / Top7 比分
- **本次世界杯实时预测**（晋级树状图）：**2026 官方赛制**（12 组 + 官方括号 + 最佳第三名分配）。已踢的真实比赛=事实（蓝色锁定），其余按模型预测，投影出最可能的官方括号与冠军。**「🔄 刷新真实赛果」**拉取最新结果，预测随事实变动。**全程可编辑**：改小组赛比分、或点击括号里任意淘汰赛录入结果/做假设（平局可设点球胜者），括号+夺冠概率实时重算；「清除试算」恢复纯预测。R32 标注官方槽位（A①/3rd…）。每场标注**日期**与**状态**（已结束/进行中/未开赛、已抽签/未抽签、试算）。
- **夺冠概率**：一键跑蒙特卡洛，夺冠%带**模拟置信区间**，**点击球队展开晋级漏斗**（出线→八强→四强→决赛→夺冠）。**会条件化在已录入/假设的赛果上**（在晋级树改的比分这里同步生效），随赛况动态更新。

## 文件结构

```
worldcup-predictor/
├── data/results.csv          # 国际比赛历史数据（martj42）
├── data/market_values.json   # 国家队身价（Transfermarkt，150 队）
├── download_data.py     # 下载/更新数据
├── data.py              # 数据层：清洗 + 时间/赛事加权 + 长表构建
├── market.py            # 身价数据 + 实力先验工具
├── elo.py               # 动态 Elo 评级（已回测：不如 DC，留作对照）
├── backtest.py          # 样本外回测（RPS/LogLoss/命中率）
├── wc2026.py            # 2026 官方赛制：分组 + 官方括号 + 第三名分配
├── teams_zh.py          # 中文名 + 国旗映射
├── model.py             # 模型层：DixonColesModel（GLM + ρ + 身价先验 + 比分矩阵）
├── predict.py           # CLI：单场 / 实力榜 / 赛程批量
├── simulate.py          # 蒙特卡洛：整届模拟 -> 夺冠概率
├── app.py               # Flask web 服务
├── templates/index.html # 单页 UI（热力图 + 夺冠榜）
├── model.pkl            # 训练缓存（--cache 生成）
└── requirements.txt
```

## 核心 API（可在自己代码里调用）

```python
import data
from model import DixonColesModel

m = DixonColesModel(half_life_days=547).fit(data.load_raw())
r = m.predict("Argentina", "France", neutral=True)
print(r["top_scores"][0])     # ((1, 0), 0.169)
print(r["p_home"], r["p_draw"], r["p_away"])
print(r["matrix"])            # 11x11 完整比分概率矩阵
```

---

## 可扩展的逻辑（你自己加料的方向）

1. **Elo 评分融合**：把 World Football Elo 作为额外特征，与攻防力混合，对样本少的球队更稳。
2. **xG 增强**：用 `probberechts/soccerdata` 拉 understat 的预期进球，代替原始进球做拟合，降低运气噪声。
3. **近期状态**：在时间衰减外，额外给"最近 5–10 场"加 buff（捕捉状态/伤病）。
4. **淘汰赛模拟**：用比分矩阵做蒙特卡洛，模拟整届赛程，算每队夺冠概率。
5. **主队细分**：把主场优势拆成"东道主 / 大洲 / 旅行距离"等更细的因子。
6. **校准评估**：留出近两年比赛做回测，用 RPS / log-loss 评估，调 `half_life`。

## 回测与调参（backtest.py）

样本外回测：只用 cutoff 之前的数据训练，预测之后真实比赛，用 **RPS / LogLoss / 命中率** 评估。

```bash
python3 backtest.py
```

**实测调参结论**（cutoffs=2024-11 & 2025-08，各 270 天，n≈1399）：

| 改动 | RPS ↓ | 命中率 ↑ | 结论 |
|---|---|---|---|
| half_life 547→**240** | 0.1474→**0.1440** | 0.630→**0.652** | ✅ 采用（最大收益） |
| 身价收缩 wmin>0 | 0.1474→0.1481 | +0.6pp | ❌ 不改善概率准度，默认关闭 |
| 友谊赛权重 | 0.5 最优 | — | 维持 0.5 |
| 动态 Elo（`elo.py`）替代/集成 | 纯 Elo 0.1669 / 集成单调趋向纯 DC | — | ❌ Elo 被 DC 的进球级信息支配，不整合 |

> 短半衰期=更看重近期状态，所以法国/巴西等若近期不够统治会排名下滑——这恰是回测更准的原因。

## 方法出处
- Maher (1982) — 泊松建模足球进球
- Dixon & Coles (1997) — 低分相关修正 + 时间加权
- Lee (1997) — 双泊松独立模型
