# Codex / Claude Skill Guide

<p align="right"><strong>English</strong> · <a href="./CODEX_SKILL.zh-CN.md">简体中文</a></p>

This repository is designed to be operated as a **local product plus an agent skill**:

- the codebase stays in `~/worldcup-predictor`;
- the web UI runs at `http://127.0.0.1:8000`;
- the Codex / Claude skill knows how to start the app, refresh facts, inspect data, generate screenshots, and update docs without changing the model by accident.

> This is still a personal educational analytics project. The skill must keep the same guardrails as the app: probability only, no betting advice, no purchase nudges, and no claim that a result is certain.

## What The Skill Does

| Intent | Skill behavior |
|---|---|
| Start the product | Launches `app.py` from `~/worldcup-predictor`, using Anaconda Python when the system Python lacks scientific packages |
| Keep the UI available | Uses port `8000`; on macOS it can be supervised by a user `launchd` agent |
| Check match facts | Reads the local dashboard/API first, then verifies schedule or result mismatches against project data |
| Generate social cards | Reuses accepted reference folders, renders 3:4 PNG cards via local HTML + headless Chrome, and keeps copy compliance-aware |
| Update product docs | Keeps English and Chinese docs in sync, refreshes screenshots where they explain a current feature, and avoids stale claims |
| Protect the model | Any model/parameter change must prove itself with `python3 backtest.py`; display or documentation edits do not touch the engine |

## Product Screenshot

The skill opens and verifies the same local web UI users see:

<p align="center">
  <img src="./screenshot-dashboard.png" alt="World Cup predictor dashboard opened by the skill" width="820">
  <br><sub><em>Skill-operated web UI: live / upcoming / finished matches, prediction pop-ups, deep-report links, and update detection.</em></sub>
</p>

## Common Commands

```bash
# Start the local web UI
cd ~/worldcup-predictor && /opt/anaconda3/bin/python app.py

# Check the dashboard API
curl -s http://127.0.0.1:8000/api/dashboard

# Run regression tests
/opt/anaconda3/bin/python -m pytest test_core.py -q

# Rebuild the methodology PDF from source HTML
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --headless=new --print-to-pdf=docs/世界杯预测器-测算逻辑白皮书.pdf \
  docs/whitepaper-source.html
```

## macOS Always-On Setup

For a local workstation, the UI can be kept online with a user LaunchAgent:

```bash
launchctl print gui/$(id -u)/com.melvin.worldcup-predictor
```

The service uses:

- program: `/opt/anaconda3/bin/python app.py`
- working directory: `/Users/melvin/worldcup-predictor`
- logs: `/Users/melvin/Library/Logs/worldcup-predictor/`

If the machine sleeps or shuts down, the port is unavailable; when the user session is awake, `launchd` restarts the app if it exits.

## Documentation Rules For The Skill

- Update `README.md` and `README.zh-CN.md` together.
- Keep screenshots under `docs/` and reference them with relative paths.
- Keep the whitepaper methodology-focused; tactical UI features belong in README or runbooks.
- Do not say "guaranteed", "sure win", "buy", "stake", "follow", or similar action language.
- Explain uncertainty explicitly: probability is not certainty, small samples are noisy, and market layers are for falsification rather than advice.

