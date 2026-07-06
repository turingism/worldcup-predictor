# Codex / Claude Skill 使用說明

<p align="right"><a href="./CODEX_SKILL.md">English</a> · <a href="./CODEX_SKILL.zh-CN.md">简体中文</a> · <strong>繁體中文</strong></p>

這個儲存庫現在按「**本地產品 + agent skill**」來維護：

- 程式碼固定在 `~/worldcup-predictor`;
- Web UI 固定跑在 `http://127.0.0.1:8000`;
- Codex / Claude skill 負責啟動網頁、刷新事實、核對資料、產生截圖、更新文件，但不會無意改動預測引擎。

> 這仍然是個人學習與資料研究專案。skill 必須遵守和產品相同的紅線：只講機率，不構成投注建議，不做購買引導，不把機率包裝成確定結果。

## Skill 能做什麼

| 意圖 | Skill 行為 |
|---|---|
| 啟動產品 | 從 `~/worldcup-predictor` 啟動 `app.py`；系統 Python 缺科學套件時使用 Anaconda Python |
| 保持網頁上線 | 固定使用 `8000` 連接埠；macOS 上可用使用者層級 `launchd` 常駐 |
| 核對比賽事實 | 優先讀本地看板/API，再按專案資料核對賽程或賽果異常 |
| 產生社群媒體卡片 | 沿用已驗收參考資料夾，用本地 HTML + headless Chrome 渲染 3:4 PNG，並控制合規措辭 |
| 更新產品文件 | 中英文同步更新，在必要位置補當前功能截圖，避免舊口徑 |
| 保護模型 | 改模型或參數必須用 `python3 backtest.py` 證明更好；展示層和文件層不得污染引擎 |

## 產品截圖

skill 打開的就是使用者看到的本地 Web UI：

<p align="center">
  <img src="./screenshot-dashboard.png" alt="skill 打開的世界盃比分預測器賽事看板" width="820">
  <br><sub><em>Skill 操作的 Web UI：正在比賽 / 即將開賽 / 已結束、預測彈窗、深度報告入口、右上角更新偵測。</em></sub>
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

## macOS 常駐上線

本機長期使用時，可用使用者層級 LaunchAgent 守住 Web UI：

```bash
launchctl print gui/$(id -u)/com.melvin.worldcup-predictor
```

服務使用：

- 程式：`/opt/anaconda3/bin/python app.py`
- 工作目錄：`/Users/melvin/worldcup-predictor`
- 日誌：`/Users/melvin/Library/Logs/worldcup-predictor/`

Mac 睡眠或關機時連接埠不可用；只要使用者工作階段處於喚醒狀態，`launchd` 會在行程退出後自動重新拉起。

## Skill 更新文件時的規則

- `README.md` 和 `README.zh-CN.md` 必須同步更新。
- 截圖統一放在 `docs/` 下，用相對路徑引用。
- 白皮書保持方法論定位；戰術性的 UI/營運說明放 README 或 runbook。
- 不寫「保證」「穩贏」「必中」「購買」「跟單」等行動誘導語言。
- 明確解釋不確定性：機率不是確定，小樣本會波動，市場層是可證偽檢驗而不是行動建議。
