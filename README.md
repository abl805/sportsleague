# AI Basketball League

An autonomous fictional basketball universe with persistent teams, players,
coaches, rivalries, injuries, awards, polls, and history. The commissioner
advances time, publishes one weekly ChatGPT editorial package, and reviews only
exceptional trades.

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
| `python run_offseason.py` | Advance one offseason stage after a finished season |
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

## Normal Commissioner Week

1. Simulate the week from `/commissioner`.
2. Copy the automatically generated `aiba.weekly_editorial.v1` prompt.
3. Paste ChatGPT's single structured response back into the same page.
4. Review a trade only when conservative autopilot escalates it.

The editorial importer validates season, week, game, team, player, coach, and GM
identifiers. ChatGPT can narrate recorded events, but it cannot alter simulation
outcomes.

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

Game outcomes now expose their logic: roster talent, star strength, coaching
matchup, chemistry, morale, injuries, home court, clutch ability, pace, and
bounded execution variance are stored with each completed game.

## Fan Experience

- `/live-league` answers what happened, why it matters, and what comes next.
- `/teams` is a choose-your-team experience; following a club uses a signed
  browser cookie and requires no account.
- `/history` preserves champions, awards, career leaders, coaching changes,
  retired jerseys, landmark games, injuries, and other permanent events.
- One fan poll is generated automatically after each completed week. The
  five-week rotation covers Player of the Week, Game of the Week, fan
  confidence, rivalry names, and the permanent name of the league's weekly
  effort award. Closed ballots become awards, labels, rivalry history, or
  named traditions; they never change scores or roster decisions.
- Rivalries use a persistent pairwise heat ledger. Close finishes, upsets,
  repeated meetings, playoff games, and trades raise the temperature; blowouts
  and inactive weeks cool it toward the rivalry's historical floor. Team and
  game pages show current heat, meeting history, and fan-given rivalry names.

## Offseason

After the final week, run:

```bat
python run_offseason.py
```

Each run advances one stage: retirements, player development/regression,
contracts, rookie draft, free agency, roster finalization, then schedule
release. The final stage creates new standings/schedule rows and advances the
league year.

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
