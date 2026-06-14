# AI Basketball League

An autonomous fictional basketball league. You are the commissioner, but the
goal is for the league to mostly run itself while you check in a couple times a
week.

## League Status

- Official Year 1 is 2026.
- Existing simulated progress is test data.
- `python seed.py` creates a fresh test league.
- `python seed.py --official` creates the clean 2026 preseason state.
- Official games do not start accidentally. After seeding official mode, run:

```bat
python run_week.py --start-official
```

After that first official start, normal weekly advances use:

```bat
python run_week.py
```

## First-Time Setup

1. Install Python from python.org.
2. Open a terminal in this folder.
3. Create and activate a virtual environment:

```bat
python -m venv venv
venv\Scripts\activate
```

4. Install dependencies:

```bat
pip install -r requirements.txt
```

5. Seed a league:

```bat
python seed.py
```

## Operating The League

| Command | What it does |
| --- | --- |
| `python seed.py` | Reset and create a test league |
| `python seed.py --official` | Reset and create the 2026 official preseason |
| `python run_week.py` | Advance one test week, or one official week after official start |
| `python run_week.py --start-official` | Start official Year 1 and play Week 1 |
| `python review_trades.py` | Review only trades autopilot escalated |
| `python run_offseason.py` | Advance a finished season into the next year |
| `python view_league.py` | View standings, results, and stat leaders |
| `python view_drama.py` | View morale, chemistry, and player events |
| `python web_app.py` | Open the primary public league site and commissioner console |
| `streamlit run app.py` | Open the legacy optional dashboard |

The Flask web app runs locally at:

```bat
python web_app.py
```

Then visit:

```text
http://127.0.0.1:5000
```

Viewer pages are public-style read-only league pages. Commissioner tools live at
`/commissioner` and are intentionally unprotected in this first local version.

## Autonomy Model

The game engine owns scores and stats. Agents can create pressure, propose
trades, affect morale, and shape chemistry, but they do not directly write
outcomes by narration.

GM trade behavior is intentionally conservative:

- GMs do not roll for trades every week at high rates.
- Teams have a trade cooldown.
- Teams have a season trade cap.
- Stars are protected from early-season churn unless they demand out.
- Autopilot approves only valid, low-drama consensus trades.
- Star trades, ambiguous deals, and edge cases stay pending for commissioner review.

This keeps the league surprising without making it feel random or silly.

## Offseason

After the final week, run:

```bat
python run_offseason.py
```

The offseason resolves retirement notices, ages players, applies development
and veteran regression, decrements contracts, handles extension requests,
moves unsigned players into free agency, fills rosters with free agents and
rookies, creates new standings/schedule rows, and advances the league year.

## Project Layout

```text
aibasketballleague/
  seed.py              Create test or official league state
  run_week.py          Advance the league and run autopilot review
  review_trades.py     Manual review for escalated trades
  view_league.py       CLI standings/results/stats
  view_drama.py        CLI morale and drama dashboard
  web_app.py           Flask public site + commissioner console
  app.py               Legacy Streamlit dashboard
  archetypes.json      Tunable GM/player/trade policy
  league/
    database.py        SQLite schema and migrations
    simulation.py      Game engine
    gm_agents.py       GM decision logic
    player_agents.py   Player morale/actions/chemistry
    trade_engine.py    Trade validation, execution, autopilot review
  db/
    league.db          Local league database
```
