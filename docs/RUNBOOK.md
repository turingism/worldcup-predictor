# ⚽ Match-day Runbook

<p align="right"><strong>English</strong> · <a href="./RUNBOOK.zh-CN.md">简体中文</a></p>

> A one-page operating guide for running the predictor on a match day. See the main [README](../README.md) for what the project is.

### ▶️ Start
```bash
cd ~/worldcup-predictor && python3 app.py        # http://127.0.0.1:8000
```
- Port is fixed to **8000** (avoid 5000 — taken by macOS AirPlay).
- Page blank or stuck? **Hard-refresh** with `Cmd+Shift+R` (clears the cached frontend).
- On the maintainer Mac, the app can also be supervised by `launchd`:
  ```bash
  launchctl print gui/$(id -u)/com.melvin.worldcup-predictor
  ```

### 🤖 What happens automatically while the app is open (no action needed)
| Every | It does |
|---|---|
| 60 s | Dashboard refreshes live scores; the LIVE card's in-play win/draw/loss updates with the score |
| 3 min | Silently pulls finished results from ESPN → **on a new finish, auto-retrains the model**, re-renders the dashboard, and triggers a background recompute of the title 90% interval (no manual "refresh facts" needed) |
| 30 min | A background ESPN odds snapshot (DraftKings 1X2) accrues opening/closing lines → feeds the market/CLV layer |

> Keep the **dashboard tab in the foreground** for the auto-pulls to fire. On a long-running match day you can just leave the page open — scores, finishes, the title interval, and odds all roll forward by themselves.

### 🖱️ Tabs / buttons cheat-sheet
- **📋 Dashboard** (home): 🔴 live / 🟡 upcoming / ✅ finished. "See prediction" on any match pops the score matrix. The **verification** ledger (pre-match predictions frozen before kickoff vs actuals, per-match scored) lives in the *Finished* section — early on, watch RPS/calibration, not hit-rate.
- **⚽ Match analysis** (Football Manager): pick two teams → analyst-style report (process data → Dixon-Coles matrix + heatmap → 1X2 / over-under / Asian handicap / correct score / confidence). Absorbs the old single-match view.
- **📖 Read-card / review tools**: market and handicap explanation cards plus the manual 90-minute settlement review loop for learning and calibration notes.
- **🌳 Bracket**: official 2026 projection; edit any score / knockout result as a what-if → bracket + title odds recompute live. **🔄 Refresh facts** here manually pulls ESPN finished results (retrains on new ones).
- **🏆 Title odds + power ratings**: Monte-Carlo point estimate + Bayesian 90% interval (whisker chart; "↻ recompute" to refresh) + the Bayesian net-strength power ranking.
- **💹 Market**: model vs closing line + CLV; the value/Kelly panel is **honestly locked by default**.
- **🔮 Mystical divination**: deterministic culture/algorithm easter egg; explicitly not predictive and checked against baselines.

### 🔧 Two switches (environment variables)
```bash
READONLY=1 python3 app.py        # read-only share mode: all write endpoints disabled (for public sharing)
MARKET_UNLOCK=1 python3 app.py   # force the value/Kelly panel open (demo only, loud red warning, NOT advice)
```

### 🩹 Quick troubleshooting
- **Dashboard hung on "loading…"** → hard-refresh; if it persists, restart `app.py`.
- **Port 8000 offline** → if using `launchd`, run `launchctl kickstart -k gui/$(id -u)/com.melvin.worldcup-predictor`.
- **Market tab slow/empty** → normal early on (no finished matches with captured odds yet → "insufficient sample").
- **403 on refresh** → you're in `READONLY=1` mode (writes disabled by design).
- **Stale data** → click "🔄 Refresh facts", or restart `app.py`.

### 🧪 Tests / accuracy
```bash
python3 -m pytest test_core.py -q     # core regression tests
python3 backtest.py                   # out-of-sample accuracy (RPS 0.16 / hit 59.7% / ECE 1.06%)
```
