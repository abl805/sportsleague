# Virtual Basketball League — Design Document

## Vision

A fictional basketball league where AI agents control players, GMs, coaches, and media.
The commissioner (you) approves major actions and advances the simulation week by week.
Emergent storylines arise from agents with personalities, memories, and conflicting goals.

## Autonomy Update

The league is moving from "commissioner approves everything" toward "commissioner
reviews exceptions." Official Year 1 is 2026 and has not started by default.
Current simulated progress is treated as test data.

- Test mode is the default for `python seed.py`.
- Official preseason is created with `python seed.py --official`.
- Official Week 1 requires `python run_week.py --start-official`.
- Weekly trade proposals now pass through conservative autopilot review.
- Autopilot can approve valid low-drama consensus trades, veto obvious non-starters,
  and escalate star/ambiguous trades to the commissioner.
- GM trade frequencies, cooldowns, team trade caps, and star protections live in
  `archetypes.json` under `trade_policy`.

---

## Current State: Phase 3 — Rule-Based Player Agents

Player personalities, morale, and weekly drama are live. The full agent loop is
deterministic and rule-based — no LLM calls. LLM hook points are marked throughout.

- `player_personalities` table: archetype + five trait weights per player
- `player_morale` table: morale history (0-100) updated weekly after games
- `player_events` table: trade demands, feuds, complaints, retirements, contract requests
- `player_memory` table: player decision log (mirrors agent_memory structure)
- `team_chemistry` table: per-team chemistry score affecting game simulation
- `league/player_agents.py`: morale update logic, action evaluation, chemistry computation
- `view_drama.py`: commissioner dashboard showing crises, demands, feuds, retirements

### Phase 2 — Rule-Based GM Agents (complete)

The agent layer. Deterministic logic with personality-driven probabilistic decisions.
No LLM, no external APIs — all reasoning is rule-based and inspectable.

- `general_managers` table stores one GM per team with archetype + numeric trait weights
- `archetypes.json` config controls salary cap, trade threshold, and per-archetype weights
- Each week: GMs roll for activity, assess needs, find targets, score trades, log reasoning
- `agent_memory` table captures every decision (proposed, rejected, inactive) with explanation
- `pending_trades` table queues proposals for commissioner review
- `review_trades.py` CLI shows both GMs' reasoning; commissioner approves, vetoes, or skips
- `run_week.py` automatically runs GMs after each week's games simulate

### Phase 1 — World Engine (complete)

The foundation layer. Pure simulation, no AI yet.

- SQLite database stores all league state
- Python game engine simulates games from player skill ratings
- CLI scripts let the commissioner advance time and observe the world

---

## League Structure

| Setting       | Value                          |
|---------------|-------------------------------|
| Teams         | 4 franchises                   |
| Roster size   | 10 players per team            |
| Positions     | PG, SG, SF, PF, C (2 per team)|
| Season length | 12 weeks (4-round robin)       |
| Games/team    | 12 games per season            |

---

## Game Engine

Games are simulated using each team's player skill ratings (1–100):

1. **Team score** = Gaussian draw centered on `75 + (avg_skill / 100) × 45`
   - Home team gets +3 point bonus
   - Clamped to realistic range: 72–145
2. **Points distribution** uses the Hamilton largest-remainder method so the
   per-player box score sums to exactly the team total
3. **Star effect**: the best player on each team gets a disproportionate share
   of points, assists, and minutes
4. **Overtime**: ties re-roll until resolved

---

## Database Schema

| Table                  | Purpose                                                          |
|------------------------|------------------------------------------------------------------|
| `teams`                | Franchise name, city, abbreviation                               |
| `players`              | Roster, attributes, skill rating                                 |
| `contracts`            | Salary, years remaining                                          |
| `games`                | Schedule; home/away scores once played                           |
| `player_game_stats`    | Per-game box score for every player                              |
| `standings`            | Season W/L/PF/PA aggregates                                      |
| `league_state`         | Current week, season year                                        |
| `general_managers`     | One GM per team: archetype, risk_tolerance, veteran_loyalty, youth_preference, trade_frequency |
| `agent_memory`         | Timestamped log of every GM decision with human-readable detail  |
| `pending_trades`       | Proposed trades awaiting commissioner approval; stores both GMs' scores and reasoning |
| `player_personalities` | Archetype + trait weights per player (ambition, loyalty, ego, work_ethic, volatility) |
| `player_morale`        | Weekly morale score (0-100) per player                          |
| `player_events`        | Active/resolved player actions: trade demands, feuds, complaints, retirements |
| `player_memory`        | Timestamped log of player decisions and mood shifts              |
| `team_chemistry`       | Weekly chemistry score per team (0-100); affects game simulation |

---

## Rule-Based Agent Architecture

### How GM decisions work

Each week after games resolve, every GM:

1. **Rolls for activity** against their `trade_frequency` weight (0–1)
2. **Assesses their team** — position ratings, age profile, cap space, recent form
3. **Scans other rosters** — scores each opposing player by `player_want_score`
4. **Scores their own players** — scores each by `player_give_score` (how willing to trade away)
5. **Constructs 1–3 proposals** — pairs most-wanted player with best salary-compatible offer
6. **Scores each trade** via `want × (0.4 + 0.6 × give)` — want is the primary driver
7. **Submits the top proposal** if it clears the threshold (default 0.48 in `archetypes.json`)
8. **Logs everything** — accepted and rejected candidates both land in `agent_memory`

### LLM swap-in points

The rule-based functions are marked `# [LLM-HOOK]` in `league/gm_agents.py`.
The most natural integration points, in order of impact:

| Hook location             | What an LLM would add                                              |
|---------------------------|---------------------------------------------------------------------|
| `player_want_score()`     | Narrative reasoning: "he's a locker-room fit" / "we need his energy" |
| `player_give_score()`     | History-aware: read `agent_memory` to factor in prior loyalty       |
| `score_trade_for_gm()`    | Full trade narrative with prose reasoning                           |
| `find_trade_candidates()` | Story-driven targeting: GMs pursue rivals or nemesis players        |

### GM archetypes

| GM                          | Team        | Archetype             | Behaviour                                        |
|-----------------------------|-------------|-----------------------|--------------------------------------------------|
| Marcus 'The Builder' Reed   | Springfield | aggressive_rebuilder  | Sheds veterans, targets youth, trades frequently |
| Victor 'V-Max' Castellano   | Riverside   | win_now               | Chases skill, ignores age, willing to overpay    |
| Frank 'Old School' Navarro  | Lakewood    | loyal_to_veterans     | Resists change, hoards experienced players       |
| Samira 'The Algorithm' Chen | Hillcrest   | analytics_driven      | Values skill/dollar efficiency, low noise        |

### Player archetypes

| Archetype          | Description                                                            |
|--------------------|------------------------------------------------------------------------|
| superstar_ego      | Expects to be the focal point; morale craters when underused           |
| quiet_professional | Consistent, causes no drama                                            |
| locker_room_leader | Team-first; morale tied to wins; boosts team chemistry                 |
| malcontent         | Perpetually unhappy; natural morale decay each week                    |
| rising_star        | Hungry and ambitious; morale driven by playing time and development    |
| aging_veteran      | Loyal but slowing; morale erodes with reduced role; natural decay      |
| team_player        | Selfless; morale mirrors team success                                  |
| hothead            | Combustible; quick to feud, prone to outbursts                         |

### Player morale system

Each week after games, morale updates based on:
1. **Playing time** (ego-weighted) — actual pts share vs expected by skill rank
2. **Team result** (loyalty-weighted) — win/loss this week
3. **Contract situation** (ambition-weighted) — years left, salary vs. market rate
4. **Active feud** — -4 per week while feuding
5. **Archetype decay** — malcontent: -3/wk; aging_veteran: -1/wk
6. **Gaussian noise** — scaled by volatility trait
7. **Memory pull** — gentle regression toward recent average

### Player action triggers (probabilistic, most weeks = nothing)

| Action             | Trigger condition                                                  |
|--------------------|-------------------------------------------------------------------|
| demand_trade       | morale < 35, weighted by (1-loyalty) * volatility; malcontent bonus |
| feud               | volatility * ego > threshold; hothead bonus; morale < 45 amplifies |
| public_complaint   | morale < 50, weighted by ego * (1-loyalty); malcontent/hothead bonus |
| extra_training     | morale > 40, work_ethic > 0.55; gives +1-2 skill permanently      |
| retirement         | age >= 33, morale < 38; aging_veteran bonus                        |
| contract_request   | morale > 55, years_remaining <= 1; weighted by ambition            |

### GM-player interaction

- Players with active trade demands get +0.15 boost to their want-score from GM targeting
- Demanding players on a GM's own roster get +0.15 give-score boost (unless veteran_loyalty >= 0.70)

### Team chemistry and game simulation

- Chemistry (0-100) = average team morale - penalties for feuds/demands/complaints + locker_room_leader bonus
- Game score modifier: `0.93 + (chemistry / 100) * 0.14` (range: 0.93 to 1.07)
- Chemistry is computed before games each week using previous week's morale

## Planned Phases

### Phase 4 — LLM Integration
- Selective LLM calls at marked `[LLM-HOOK]` points (no full replacement needed)
- `compute_morale_update()` — richer narrative reasoning over player history
- `evaluate_player_week()` — context-aware action decisions
- `score_trade_for_gm()` — prose trade reasoning with memory of past deals
- `compute_trait_drift()` — multi-season personality reasoning

### Phase 5 — Coach and Media Agents
- Coach agents: set lineups, call timeouts, choose strategy
- Media agents: generate game narratives, rumors, hot takes
- Season narrative dashboard showing emergent storylines

---

## Design Decisions Log

| Date       | Decision                            | Reason                                           |
|------------|-------------------------------------|--------------------------------------------------|
| 2026-05-16 | Basketball as sport                 | User preference                                  |
| 2026-05-16 | SQLite for storage                  | Simple, portable, no server required             |
| 2026-05-16 | Gaussian scoring model              | Realistic variance, easy to tune per phase       |
| 2026-05-16 | 4-round robin (12 weeks)            | Enough games for meaningful standings; short enough to iterate fast |
| 2026-05-16 | Hamilton remainder for box scores   | Points always sum exactly to team total          |
| 2026-05-16 | No external Python dependencies     | Easy setup for non-programmers                   |
| 2026-05-17 | Rule-based GMs before LLM GMs       | Prove architecture works deterministically first; LLM can be swapped in at marked hook points |
| 2026-05-17 | want × (0.4 + 0.6 × give) scoring  | Want is the primary signal; give acts as a multiplier gate, not an equal factor |
| 2026-05-17 | Salary cap $100M for 10 players     | Calibrated to typical seed salaries (~$40–70M/team), leaves meaningful cap pressure |
| 2026-05-17 | Player traits drive all probabilities | No separate per-archetype action_weights table — keeps config lean and all logic in code |
| 2026-05-17 | Chemistry uses prior week's morale  | Avoids chicken-and-egg: can apply modifier before simulating games that generate new morale |
| 2026-05-17 | player_memory is separate from agent_memory | agent_memory has NOT NULL FK to general_managers; cleaner to add a parallel player table |
