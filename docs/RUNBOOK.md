# ⚽ Match-day Runbook

<p align="right"><strong>English</strong> · <a href="./RUNBOOK.zh-CN.md">简体中文</a></p>

> A one-page operating guide for running the predictor on a match day. See the main [README](../README.md) for what the project is.

### ▶️ Start
```bash
cd ~/worldcup-predictor && python3 app.py        # http://127.0.0.1:8000
```
- Port is fixed to **8000** (avoid 5000 — taken by macOS AirPlay).
- Page blank or stuck? **Hard-refresh** with `Cmd+Shift+R` (clears the cached frontend).

### 🤖 What happens automatically while the app is open (no action needed)
| Every | It does |
|---|---|
| 60 s | Dashboard refreshes live scores; the LIVE card's in-play win/draw/loss updates with the score |
| 30 min | A background ESPN odds snapshot accrues opening/closing lines (feeds CLV) |
| On a new finished match | Auto-retrain the model → background recompute of the title 90% interval |

### 🖱️ Tabs / buttons cheat-sheet
- **📋 Dashboard** (home): 🔴 live / 🟡 upcoming / ✅ finished. "See prediction" on any match pops the score matrix.
- **🔄 Refresh facts**: manually pull ESPN finished results in seconds (retrains on new ones).
- **🏆 Title odds**: Monte-Carlo point estimate + Bayesian 90% interval (whisker chart; "↻ recompute" to refresh).
- **🎯 Verification**: pre-match predictions frozen before kickoff vs actuals, scored per match (early on, watch RPS/calibration, not hit-rate).
- **💹 Market**: model vs closing line + CLV; the value/Kelly panel is **honestly locked by default**.

### 🔧 Two switches (environment variables)
```bash
READONLY=1 python3 app.py        # read-only share mode: all write endpoints disabled (for public sharing)
MARKET_UNLOCK=1 python3 app.py   # force the value/Kelly panel open (demo only, loud red warning, NOT advice)
```

### 🩹 Quick troubleshooting
- **Dashboard hung on "loading…"** → hard-refresh; if it persists, restart `app.py`.
- **Market tab slow/empty** → normal early on (no finished matches with captured odds yet → "insufficient sample").
- **403 on refresh** → you're in `READONLY=1` mode (writes disabled by design).
- **Stale data** → click "🔄 Refresh facts", or restart `app.py`.

### 🧪 Tests / accuracy
```bash
python3 -m pytest test_core.py -q     # 18 regression tests
python3 backtest.py                   # out-of-sample accuracy (RPS 0.16 / hit 59.7% / ECE 1.06%)
```
