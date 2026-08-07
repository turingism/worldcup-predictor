# Developer Notes · 足球赛事预测器

This file is a compact maintainer guide. For product copy, see:

- [README.md](../README.md)
- [README.zh-CN.md](../README.zh-CN.md)
- [Codex / Claude Skill Guide](./CODEX_SKILL.md)
- [Codex / Claude Skill 使用说明](./CODEX_SKILL.zh-CN.md)

---

## Product Scope

Football Events Predictor is a local-first Flask product built around two isolated model universes:

- a Dixon-Coles double-Poisson national-team model on international results from 1872-2026;
- independent 365-day-half-life models for Europe's top five leagues;
- official 2026 World Cup groups, bracket, and best-third-place allocation;
- league tables, remaining-season simulation, and per-event verification ledgers;
- the UI v2 Competition Console, match analysis, source freshness, and responsive event navigation.

---

## Core Rules

| Rule | Why it exists |
|---|---|
| National `half_life=730`; club `half_life=365` | Both values are independently backtest-adjudicated |
| Model changes require `python3 backtest.py` | No parameter or feature is adopted without RPS / LogLoss / hit-rate evidence |
| In-play / market / lineup layers are read-only side paths | They must not write the frozen verification ledger or mutate the GLM |
| README English and Chinese stay paired | GitHub-facing product docs are bilingual by default |

---

## Runtime

```bash
cd ~/worldcup-predictor
/opt/anaconda3/bin/python3 app.py
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
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
/opt/anaconda3/bin/python3 backtest.py
```

Use the tests for regression safety and `backtest.py` only when model behavior changes. Documentation, screenshot, and copy updates do not require a backtest unless they alter modeling code or output semantics.

For screenshots, always use the repository wrapper so Chrome runs with an isolated temporary profile:

```bash
scripts/shot.sh docs/evidence/home.png 1440,900 1 'http://127.0.0.1:8000/#home'
/opt/anaconda3/bin/python3 scripts/ui_check.py --path '#home'
```

---

## Main Files

```text
worldcup-predictor/
├── app.py                 # Flask API + dashboard routes + background jobs
├── templates/index.html   # single-page Web UI
├── events.py              # event registry, aliases, and ledger identity
├── home_dashboard.py      # read-only cross-event homepage assembly
├── model.py               # Dixon-Coles model and score matrix
├── clubdata.py            # top-five league history and model frames
├── clubpredict.py         # club single-match prediction and promoted-team path
├── clubsim.py             # remaining-season simulation
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
├── DESIGN.md              # UI v2 design system and responsive rules
├── docs/evidence/         # screenshots and executable UI acceptance evidence
├── docs/                  # product guides, runbooks, whitepaper source, skill docs
└── test_core.py           # regression tests
```

Generated personal/runtime files such as prediction ledgers, odds snapshots, and caches should stay out of Git unless they are intentionally part of a public fixture.

---

## 文档维护口径

- 主 README 是产品说明；`docs/RUNBOOK*.md` 是比赛日操作手册；`docs/CODEX_SKILL*.md` 是 agent skill 操作说明。
- 白皮书源文件是 `docs/whitepaper-source.html`，定位为方法论，不塞 UI 小功能。
- 产品截图放在 `docs/evidence/`，用相对路径引用，并保留视口尺寸到文件名。
- README 与 FEATURES 的英文、简体中文版本保持相同章节、数字与截图。
