# Codex / Claude Skill 使用说明

<p align="right"><a href="./CODEX_SKILL.md">English</a> · <strong>简体中文</strong> · <a href="./CODEX_SKILL.zh-TW.md">繁體中文</a></p>

这个仓库现在按「**本地产品 + agent skill**」来维护：

- 代码固定在 `~/worldcup-predictor`;
- Web UI 固定跑在 `http://127.0.0.1:8000`;
- Codex / Claude skill 负责启动网页、刷新事实、核对数据、生成截图、更新文档，但不会无意改动预测引擎。

> 这仍然是个人学习与数据研究项目。skill 必须遵守和产品相同的红线：只讲概率，不构成投注建议，不做购买引导，不把概率包装成确定结果。

## Skill 能做什么

| 意图 | Skill 行为 |
|---|---|
| 启动产品 | 从 `~/worldcup-predictor` 启动 `app.py`；系统 Python 缺科学包时使用 Anaconda Python |
| 保持网页在线 | 固定使用 `8000` 端口；macOS 上可用用户级 `launchd` 常驻 |
| 核对比赛事实 | 优先读本地看板/API，再按项目数据核对赛程或赛果异常 |
| 生成社媒卡片 | 复用已验收参考文件夹，用本地 HTML + headless Chrome 渲染 3:4 PNG，并控制合规措辞 |
| 更新产品文档 | 中英文同步更新，在必要位置补当前功能截图，避免旧口径 |
| 保护模型 | 改模型或参数必须用 `python3 backtest.py` 证明更好；展示层和文档层不得污染引擎 |

## 产品截图

skill 打开的就是用户看到的本地 Web UI：

<p align="center">
  <img src="./screenshot-dashboard.png" alt="skill 打开的世界杯比分预测器赛事看板" width="820">
  <br><sub><em>Skill 操作的 Web UI：正在比赛 / 即将开赛 / 已结束、预测弹窗、深度报告入口、右上角更新检测。</em></sub>
</p>

## 常用命令

```bash
# 启动本地 Web UI
cd ~/worldcup-predictor && /opt/anaconda3/bin/python app.py

# 检查赛事看板 API
curl -s http://127.0.0.1:8000/api/dashboard

# 跑回归测试
/opt/anaconda3/bin/python -m pytest test_core.py -q

# 从源 HTML 重建方法论 PDF
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --print-to-pdf=docs/世界杯预测器-测算逻辑白皮书.pdf \
  docs/whitepaper-source.html
```

## macOS 常驻在线

本机长期使用时，可用用户级 LaunchAgent 守住 Web UI：

```bash
launchctl print gui/$(id -u)/com.melvin.worldcup-predictor
```

服务使用：

- 程序：`/opt/anaconda3/bin/python app.py`
- 工作目录：`/Users/melvin/worldcup-predictor`
- 日志：`/Users/melvin/Library/Logs/worldcup-predictor/`

Mac 睡眠或关机时端口不可用；只要用户会话处于唤醒状态，`launchd` 会在进程退出后自动拉起。

## Skill 更新文档时的规则

- `README.md` 和 `README.zh-CN.md` 必须同步更新。
- 截图统一放在 `docs/` 下，用相对路径引用。
- 白皮书保持方法论定位；战术性的 UI/运营说明放 README 或 runbook。
- 不写「保证」「稳赢」「必中」「购买」「跟单」等行动诱导语言。
- 明确解释不确定性：概率不是确定，小样本会波动，市场层是可证伪检验而不是行动建议。

