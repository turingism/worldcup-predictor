# 足球赛事预测器

<p align="right"><a href="./README.md">English</a> · <strong>简体中文</strong></p>

[![SkillSafe verified](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/verified)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/) [![Installs](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/installs)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/) [![Scan](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/scan)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/)

### [打开在线版](https://turingism.github.io/worldcup-predictor/) · 无需安装与 API Key

一个覆盖国家队赛事与欧洲五大联赛的足球概率分析产品。核心是 Dixon-Coles 双泊松模型，网页端提供跨赛事总览、未来赛程、比分概率、赛事推演、验证账本和数据状态。任何模型改动都必须通过时序样本外回测，未赢过基线的方案不会进入生产模型。

<p align="center">
  <img src="./docs/evidence/ui-v2-home-desktop-1440x900.png" alt="新版赛事控制台桌面端：首页展示近期赛程、数据状态、赛事导航与概率" width="900">
</p>

## 当前覆盖

| 模型宇宙 | 赛事 | 数据与模型口径 |
| --- | --- | --- |
| 国家队 | 世界杯 2026；欧国联 26-27 赛事壳与单场引擎；支持任意国家队对阵 | 1872–2026 国际比赛，257 支球队，半衰期 730 天 |
| 俱乐部 | 英超、西甲、意甲、德甲、法甲 26-27 | football-data.co.uk 各联赛独立模型，半衰期 365 天 |
| 跨联赛 | 欧战历史账本与联赛强度锚点 | 五季欧战数据用于跨联赛校准，联赛页面仍保持独立模型 |

国家队与俱乐部是两个独立模型宇宙。训练集、缓存、赛事账本和验证结果均按对应口径隔离。

## UI v2：赛事控制台

这一版对全部页面重新设计，目标是让高密度赛程和概率在桌面、平板与手机上保持同一套阅读顺序。

- 首页默认落在 `#home`，回答“近期有什么比赛、数据更新到哪里、各赛事当前处于什么阶段”。
- 桌面端使用赛事侧栏；小于 900px 时切换为单行横滚赛事导航。
- 世界杯、联赛和欧国联按赛事能力装配不同功能页，不复制一套固定 Tab。
- 宽表格保留信息密度，并放进明确的横向滚动容器；页面根节点不会被撑宽。
- 动态比赛卡、联赛赛程行和晋级树支持键盘操作；主要移动端控件保持至少 44px 触控高度。
- 赛前冻结概率、当前模型估算、数据截至时间和赛事状态在界面中分别标注。

<p align="center">
  <img src="./docs/evidence/ui-v2-wc-bracket-desktop-1440x900.png" alt="新版世界杯晋级树桌面端" width="900">
</p>

<p align="center">
  <img src="./docs/evidence/ui-v2-home-mobile-390x844.png" alt="新版赛事控制台手机端" width="360">
  &nbsp;&nbsp;
  <img src="./docs/evidence/ui-v2-epl-board-mobile-390x844.png" alt="新版英超赛事看板手机端" width="360">
</p>

详细页面说明见 [完整功能说明](./docs/FEATURES.zh-CN.md)，视觉规范见 [DESIGN.md](./DESIGN.md)。

## 核心能力

### 跨赛事首页

- 汇总未来 14 天已接线赛事，按开球时间排序。
- 同时展示各数据源的 `data_through`、赛程发布状态和开球时间核验状态。
- 赛事卡按国家队与俱乐部分组，展示赛季阶段、数据覆盖和就绪状态。
- 验证账本按赛事独立呈现，不合并为全站单一指标。

### 单场分析

- 胜 / 平 / 负概率与最可能比分。
- 完整比分概率矩阵与期望进球。
- 近期状态、主客场拆分、历史交锋和攻防强度。
- 大小球、双方进球、让球线与市场价格的结构化对照。
- 联赛升班马通过对应次级联赛样本合训，且逐场标出模型口径。

### 赛事推演

- 世界杯：官方赛制晋级树、实际赛果锁定、比赛状态与冠军路径。
- 五大联赛：积分榜、赛季剩余赛程模拟、夺冠 / 前四 / 降级分布。
- 夺冠页展示概率随赛季推进的变化、关键时间窗与实力排名。

### 验证与数据更新

- 比赛开始前冻结概率和比分矩阵，赛后写入实际比分并计算 RPS。
- 世界杯 104 场已完成整届验证；俱乐部账本按赛事和赛季独立存储。
- ESPN 提供赛程与即时赛果，football-data.co.uk 提供俱乐部历史赛果与赔率字段。
- 首页只读取缓存产物，不触发模型训练、蒙特卡洛模拟或网络抓取。

## 模型表现

国家队样本外回测必须按赛事层级阅读，不能只看混合数据集的单一数字。

| 评估集 | RPS | 胜平负命中 |
| --- | ---: | ---: |
| 全部国际赛混合留出集，约 1,388 场 | 0.1624 | 59.7% |
| 世界杯正赛 2014 / 2018 / 2022 / 2026，n=295 | 0.1864 | 61.0% |
| 2026 世界杯验证账本，104 场 | 0.1528 | 70 / 104 |

2026 世界杯是一次表现较好的赛事样本，不代表模型参数发生了改变。详细分层、置信区间、闭盘基准和已否决实验见 [回测文档](./docs/backtest.md)。

## 快速开始

```bash
git clone https://github.com/turingism/worldcup-predictor.git
cd worldcup-predictor
pip install -r requirements.txt

python3 app.py                                    # http://127.0.0.1:8000
python3 predict.py "Argentina" "France" --cache   # 国家队单场
python3 clubpredict.py "阿森纳" "曼城"              # 俱乐部单场
python3 simulate.py --sims 5000                   # 世界杯赛事模拟
python3 backtest.py                               # 国家队样本外回测
```

首次运行会训练并缓存模型。队名支持中文与英文。`READONLY=1 python3 app.py` 可启动只读实例。

在本机项目环境中建议使用：

```bash
/opt/anaconda3/bin/python3 app.py
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
```

## 静态在线版

GitHub Pages 版本是构建期生成的冻结快照。GitHub Actions 会训练模型、预热缓存，并把确定性的只读 API 导出为 JSON；浏览器端直接从 CDN 读取这些产物。

```bash
python3 warmup.py
python3 export_static.py --out dist
```

自建 Flask 版本保留实时比分、刷新、试算与本地录入；静态版只提供已导出的读取能力。

## 工程结构

| 文件 | 职责 |
| --- | --- |
| `model.py` `data.py` `predict.py` | Dixon-Coles 引擎、国家队数据和单场 CLI |
| `clubdata.py` `clubpredict.py` `clubsim.py` | 俱乐部数据、联赛模型和赛季模拟 |
| `verify.py` `clubverify.py` | 赛前冻结与赛后结算 |
| `home_dashboard.py` `events.py` | 首页聚合与赛事注册表 |
| `manager.py` `explainer.py` `narrative.py` | 对阵分析、机制解释和文本表达层 |
| `app.py` `templates/index.html` | Flask API 与单页 Web UI |
| `export_static.py` `warmup.py` | GitHub Pages 静态快照构建 |
| `test_core.py` | 当前 230 项核心回归测试 |

## 验证状态

本次 UI v2 发布已完成：

- `230 passed` 核心测试。
- 17 条路由 × 2 个视口，共 34 条页面检查全部通过。
- 首页、世界杯看板和英超看板在 390 / 430 / 768 / 1440 四档视口全部通过。
- 10 个确定性 API 端点在升级前后逐字节一致。
- Impeccable UI 审计 19 / 20；剩余项是部分旧渲染器仍保留局部颜色字面量。

验收证据见 [`docs/evidence/`](./docs/evidence/) 与 [Impeccable 审计报告](./docs/evidence/ui-v2-impeccable-audit.md)。

## 文档

- [完整功能说明](./docs/FEATURES.zh-CN.md)
- [比赛日运行手册](./docs/RUNBOOK.zh-CN.md)
- [数据源](./docs/data-sources.md)
- [回测与实验裁决](./docs/backtest.md)
- [设计规范](./DESIGN.md)
- [开发说明](./docs/README-dev.md)

## License

MIT，见 [LICENSE](./LICENSE)。

## 支持项目

项目免费开源。网页右上角“支持项目”可打开赞赏码；所有功能保持公开可用。
