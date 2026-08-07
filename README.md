# Football Events Predictor

<p align="right"><strong>English</strong> · <a href="./README.zh-CN.md">简体中文</a></p>

[![SkillSafe verified](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/verified)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/) [![Installs](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/installs)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/) [![Scan](https://api.skillsafe.ai/v1/badge/@melvin/football-match-forecasting/scan)](https://skillsafe.ai/skill/@melvin/football-match-forecasting/)

### [Open the live version](https://turingism.github.io/worldcup-predictor/) · No installation or API key required

A football probability-analysis product covering national-team competitions and Europe's top five leagues. Its core is a Dixon-Coles double-Poisson model; the web application adds a cross-event overview, upcoming fixtures, score probabilities, competition simulations, verification ledgers, and source freshness. Model changes ship only when they beat the baseline in time-ordered out-of-sample backtests.

<p align="center">
  <img src="./docs/evidence/ui-v2-home-desktop-1440x900.png" alt="New desktop Competition Console with upcoming fixtures, source freshness, event navigation, and probabilities" width="900">
</p>

## Current coverage

| Model universe | Competitions | Data and modeling policy |
| --- | --- | --- |
| National teams | World Cup 2026; Nations League 2026-27 shell and single-match engine; any international fixture | 1872–2026 internationals, 257 teams, 730-day half-life |
| Clubs | Premier League, La Liga, Serie A, Bundesliga, and Ligue 1 for 2026-27 | Independent football-data.co.uk model per league, 365-day half-life |
| Cross-league | European competition history and league-strength anchors | Five European seasons calibrate cross-league strength while league pages remain independent |

National-team and club football are separate model universes. Training frames, caches, event ledgers, and verification results remain isolated by their corresponding scope.

## UI v2: the Competition Console

This release redesigns every page around one reading order that holds up across desktop, tablet, and mobile.

- The default `#home` route answers what is coming up, how fresh each source is, and where every competition stands.
- Desktop uses an event sidebar; below 900px it becomes a single horizontal event rail.
- World Cup, league, and Nations League pages assemble their tabs from competition capabilities instead of duplicating one fixed tab set.
- Wide tables retain their information density inside explicit horizontal scrollers and never widen the page root.
- Dynamic match cards, fixture rows, and bracket ties support keyboard operation; primary mobile controls meet a 44px minimum touch height.
- Pre-match frozen probabilities, current model estimates, data cutoffs, and event states are labeled independently.

<p align="center">
  <img src="./docs/evidence/ui-v2-wc-bracket-desktop-1440x900.png" alt="Redesigned World Cup tournament bracket on desktop" width="900">
</p>

<p align="center">
  <img src="./docs/evidence/ui-v2-home-mobile-390x844.png" alt="New Competition Console on mobile" width="360">
  &nbsp;&nbsp;
  <img src="./docs/evidence/ui-v2-epl-board-mobile-390x844.png" alt="New Premier League event dashboard on mobile" width="360">
</p>

See the [complete feature guide](./docs/FEATURES.md) for a page-by-page walkthrough and [DESIGN.md](./DESIGN.md) for the visual system.

## Core capabilities

### Cross-event homepage

- Combines the next 14 days across every wired competition and sorts fixtures by kickoff.
- Shows each source's `data_through`, schedule publication state, and kickoff-time verification state.
- Groups event cards by national-team and club universes, including season state, coverage, and readiness.
- Presents verification ledgers per event without collapsing them into one site-wide metric.

### Match analysis

- Win / draw / loss probabilities and the most likely scoreline.
- Full score-probability matrix and expected goals.
- Recent form, home/away splits, head-to-head history, and attack/defence strength.
- Structured views of totals, both-teams-to-score, handicap lines, and market prices.
- Promoted clubs use a co-trained feeder-league path, labeled per match to keep the modeling basis visible.

### Competition simulation

- World Cup: official-format bracket, locked real results, match states, and the projected champion path.
- Top five leagues: table, remaining-season simulation, and title / top-four / relegation distributions.
- Title pages show probability movement through the season, key windows, and power rankings.

### Verification and data updates

- Probabilities and score matrices freeze before kickoff; results are attached after the match and scored with RPS.
- The 104-match World Cup ledger is fully settled; club ledgers remain isolated by event and season.
- ESPN supplies schedules and live results; football-data.co.uk supplies club history and market-price fields.
- The homepage reads cached artifacts only. It does not train models, run Monte Carlo simulations, or fetch the network.

## Model performance

National-team evaluation must be read by competition layer rather than through one mixed headline number.

| Evaluation set | RPS | W/D/L hit |
| --- | ---: | ---: |
| Mixed international holdout, about 1,388 matches | 0.1624 | 59.7% |
| World Cup finals 2014 / 2018 / 2022 / 2026, n=295 | 0.1864 | 61.0% |
| World Cup 2026 verification ledger, 104 matches | 0.1528 | 70 / 104 |

World Cup 2026 was a strong tournament sample; it does not imply a parameter change. See the [backtest documentation](./docs/backtest.md) for the stratified results, confidence intervals, closing-price benchmark, and rejected experiments.

## Quick start

```bash
git clone https://github.com/turingism/worldcup-predictor.git
cd worldcup-predictor
pip install -r requirements.txt

python3 app.py                                    # http://127.0.0.1:8000
python3 predict.py "Argentina" "France" --cache   # national-team fixture
python3 clubpredict.py "阿森纳" "曼城"              # club fixture
python3 simulate.py --sims 5000                   # World Cup simulation
python3 backtest.py                               # national-team backtest
```

The first run trains and caches the models. Team names work in English and Chinese. Use `READONLY=1 python3 app.py` for a read-only instance.

The recommended interpreter in this project environment is:

```bash
/opt/anaconda3/bin/python3 app.py
/opt/anaconda3/bin/python3 -m pytest test_core.py -q
```

## Static live version

The GitHub Pages version is a frozen build-time snapshot. GitHub Actions trains the models, warms the caches, and exports deterministic read endpoints to JSON; the browser then reads those artifacts from the CDN.

```bash
python3 warmup.py
python3 export_static.py --out dist
```

The self-hosted Flask version retains live scores, refreshes, what-if controls, and local entry. The static build exposes only exported read behavior.

## Project map

| Files | Responsibility |
| --- | --- |
| `model.py` `data.py` `predict.py` | Dixon-Coles engine, national data, and single-match CLI |
| `clubdata.py` `clubpredict.py` `clubsim.py` | Club data, league models, and season simulation |
| `verify.py` `clubverify.py` | Pre-match freeze and post-match settlement |
| `home_dashboard.py` `events.py` | Homepage aggregation and event registry |
| `manager.py` `explainer.py` `narrative.py` | Match analysis, mechanism explanation, and language layer |
| `app.py` `templates/index.html` | Flask API and single-page web UI |
| `export_static.py` `warmup.py` | GitHub Pages snapshot build |
| `test_core.py` | Current 230-test core regression suite |

## Verification status

The UI v2 release has completed:

- `230 passed` core tests.
- 17 routes × 2 viewports: 34 successful page checks.
- Homepage, World Cup dashboard, and Premier League dashboard pass at 390 / 430 / 768 / 1440 widths.
- Ten deterministic API endpoints are byte-identical before and after the redesign.
- Impeccable UI audit: 19 / 20. The retained point is that a few legacy renderers still contain local color literals.

See [`docs/evidence/`](./docs/evidence/) and the [Impeccable audit report](./docs/evidence/ui-v2-impeccable-audit.md) for the evidence.

## Documentation

- [Complete feature guide](./docs/FEATURES.md)
- [Match-day runbook](./docs/RUNBOOK.md)
- [Data sources](./docs/data-sources.md)
- [Backtests and experiment decisions](./docs/backtest.md)
- [Design system](./DESIGN.md)
- [Developer notes](./docs/README-dev.md)

## License

MIT. See [LICENSE](./LICENSE).

## Support the project

The project is free and open source. The “Support project” control in the web application opens the contribution QR; all functionality remains publicly available.
