# Developer Notes · 世界杯比分预测器

This file is a compact maintainer guide. For product copy, see:

- [README.md](../README.md)
- [README.zh-CN.md](../README.zh-CN.md)
- [Codex / Claude Skill Guide](./CODEX_SKILL.md)
- [Codex / Claude Skill 使用说明](./CODEX_SKILL.zh-CN.md)

---

## Product Scope

World Cup Score Predictor is a local-first Flask product built around one falsifiable engine:

- Dixon-Coles double-Poisson model on real international results from 1872-2026;
- official 2026 World Cup groups, bracket, and best-third-place allocation;
- Monte-Carlo title odds and Bayesian title credible intervals;
- live dashboard, in-play W/D/L, scoreline matrix, match-analysis report, verification ledger, market/CLV honesty layer, lineup context, and cultural divination tab.

It is an educational analytics project only. Product and documentation copy must never turn probabilities into betting advice.

---

## Core Rules

| Rule | Why it exists |
|---|---|
| `half_life=730` is the current backtest-backed default | The old `240` result came from a time-leak artifact and must not be restored |
| Model changes require `python3 backtest.py` | No parameter or feature is adopted without RPS / LogLoss / hit-rate evidence |
| In-play / market / lineup layers are read-only side paths | They must not write the frozen verification ledger or mutate the GLM |
| Public copy must say probability, not certainty | No "guaranteed", "sure win", "follow", "stake", or purchase nudges |
| README English and Chinese stay paired | GitHub-facing product docs are bilingual by default |

---

## Runtime

```bash
cd ~/worldcup-predictor
/opt/anaconda3/bin/python app.py
# http://127.0.0.1:8000
```

Port `8000` is intentional; avoid `5000` on macOS because AirPlay can occupy it.

On the maintainer machine the UI may be kept alive with a user LaunchAgent:

```bash
launchctl print gui/$(id -u)/com.melvin.worldcup-predictor
```

Logs:

```bash
tail -f ~/Library/Logs/worldcup-predictor/app.out.log
tail -f ~/Library/Logs/worldcup-predictor/app.err.log
```

---

## Verification

```bash
/opt/anaconda3/bin/python -m pytest test_core.py -q
/opt/anaconda3/bin/python backtest.py
```

Use the tests for regression safety and `backtest.py` only when model behavior changes. Documentation, screenshot, and copy updates do not require a backtest unless they alter modeling code or output semantics.

For screenshots:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new \
  --no-proxy-server \
  --screenshot=docs/screenshot-dashboard.png \
  --window-size=1180,1450 \
  --force-device-scale-factor=2 \
  --virtual-time-budget=10000 \
  "http://127.0.0.1:8000/"
```

---

## Main Files

```text
worldcup-predictor/
├── app.py                 # Flask API + dashboard routes + background jobs
├── templates/index.html   # single-page Web UI
├── model.py               # Dixon-Coles model and score matrix
├── predict.py             # CLI single-fixture prediction
├── simulate.py            # group/bracket/title Monte-Carlo
├── wc2026.py              # official 2026 groups, bracket, best-third allocation
├── verify.py              # frozen pre-match prediction ledger
├── manager.py             # match-analysis report and derived markets
├── explainer.py           # market/handicap explanation cards with red-line guard
├── inplay.py              # live W/D/L side path
├── lineup_ledger.py       # confirmed-lineup context and scorecard
├── handicap_ledger.py     # handicap verification and model-vs-market checks
├── teams_zh.py            # Chinese labels + flags
├── data/                  # local data and runtime ledgers
├── docs/                  # screenshots, runbooks, whitepaper source, skill docs
└── test_core.py           # regression tests
```

Generated personal/runtime files such as prediction ledgers, odds snapshots, and caches should stay out of Git unless they are intentionally part of a public fixture.

---

## 文档维护口径

- 主 README 是产品说明；`docs/RUNBOOK*.md` 是比赛日操作手册；`docs/CODEX_SKILL*.md` 是 agent skill 操作说明。
- 白皮书源文件是 `docs/whitepaper-source.html`，定位为方法论，不塞 UI 小功能。
- 截图放在 `docs/`，用相对路径引用。
- 所有对外文案保留免责声明：个人学习与数据研究项目，不构成任何投注、投资或决策建议。

