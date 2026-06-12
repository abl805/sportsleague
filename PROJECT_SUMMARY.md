# AI Basketball League — Project Summary

## What This Is

An agent-based basketball league simulator built in Python with SQLite. The commissioner (you) advances the league week-by-week while AI-controlled GMs and players drive emergent storylines through personality-driven decisions, morale dynamics, and trade proposals. All agent logic is deterministic (rule-based), with clearly marked hooks for future LLM integration.

**Current status:** Phases 1–3 complete and playable.

---

## Tech Stack

- **Language:** Python 3.x
- **Database:** SQLite (`db/league.db`)
- **Web UI:** Streamlit (optional)
- **Config:** `archetypes.json` (all tunable weights/thresholds)
- **Dependencies:** Only `streamlit`

---

## Project Layout

```
aibasketballleague/
├── README.md               # Setup and command reference
├── design.md               # Full architecture + LLM integration plan
├── archetypes.json         # GM/player archetype trait configs, salary cap
├── seed.py                 # One-time league init (teams, players, GMs, schedule)
├── run_week.py             # Main sim loop: games → morale → player actions → GM decisions
├── run_gm_agents.py        # Standalone GM decision runner
├── review_trades.py        # Commissioner trade approval CLI
├── view_league.py          # CLI standings, results, stat leaders
├── view_drama.py           # CLI drama dashboard (morale, feuds, demands)
├── app.py                  # Streamlit web dashboard
├── play.bat                # Windows quick-launch
└── league/
    ├── database.py         # SQLite schema and connection manager
    ├── simulation.py       # Game engine (scoring, box scores)
    ├── gm_agents.py        # GM decision logic and personality drift
    ├── player_agents.py    # Player morale, actions, team chemistry
    └── trade_engine.py     # Trade validation, execution, veto
```

---

## Three-Layer Agent Architecture

### Layer 1 — World Engine (Phase 1, complete)
Game simulation with Gaussian scoring, home-court advantage, and chemistry modifier.

- **Scoring:** `base = 75 + (avg_skill/100) × 45`; home team gets +3; multiplied by chemistry modifier `0.93–1.07`; drawn from `N(base, σ=8)`, clamped to `[72, 145]`
- **Overtime:** Ties re-roll until resolved
- **Box scores:** Hamilton's largest-remainder method ensures points sum exactly to team total; position-aware (guards → assists, bigs → rebounds/blocks); star players get disproportionate share via exponential weighting

### Layer 2 — GM Agents (Phase 2, complete)
Trade-proposal logic driven by 4 archetypes with season-end personality drift.

**GM Archetypes:**
| Archetype | Age Pref | Trade Freq | Key Trait |
|---|---|---|---|
| Aggressive Rebuilder | 18–26 | 0.75 | Dumps veterans for youth |
| Win Now | 25–33 | default | Pure skill focus |
| Loyal to Veterans | 28–40 | low | High vet_loyalty (0.90); resists change |
| Analytics Driven | any | 0.55 | Skill-per-dollar efficiency; low noise |

**Weekly GM loop:**
1. Activity roll vs `trade_frequency`
2. Score every opponent player (`player_want_score` 0–1)
3. Score own tradeable players (`player_give_score` 0–1)
4. Build salary-compatible proposals: `want × (0.4 + 0.6 × give)`
5. Submit if score ≥ 0.48 (configurable in `archetypes.json`)
6. Log all decisions (accepted and rejected) to `agent_memory`

**Personality drift:** After each season, GMs' trait weights shift based on W/L record, roster age, and winning %. Compounding across seasons enables multi-year arcs.

### Layer 3 — Player Agents (Phase 3, complete)
Morale system, personality-driven weekly actions, team chemistry feedback loop.

**Player traits (all 0–1):**
- `ambition` — drives contract requests, training effort
- `loyalty` — dampens trade demands; weights team-result morale impact
- `ego` — amplifies playing-time sensitivity; raises feud probability
- `work_ethic` — chance of extra training (+1–2 skill, permanent)
- `volatility` — scales morale noise; raises feud/complaint probability

**Player archetypes (8):**
Superstar Ego, Quiet Professional, Locker Room Leader, Malcontent, Rising Star, Aging Veteran, Team Player, Hothead

**Weekly morale update factors:**
- Playing time vs skill-rank expectation (weighted by `ego`)
- Win/loss: ±5 (weighted by `loyalty`)
- Contract fairness (weighted by `ambition`)
- Active feud: −4
- Archetype decay (Malcontent −3/wk, Aging Veteran −1/wk)
- Gaussian noise scaled by `volatility`
- Soft pull toward 4-week morale average
- Clamped to `[5, 98]`

**Weekly player actions (probabilistic, most weeks = nothing):**
- **Trade demand:** ∝ `(35−morale)/50 × (1−loyalty) × volatility`
- **Feud:** `volatility × ego × 0.10`; morale < 45 amplifies
- **Public complaint:** `ego × (1−loyalty) × 0.12`; morale < 40 amplifies 1.8×
- **Extra training:** `work_ethic × 0.18` if morale > 40 → permanent skill gain
- **Retirement:** Age ≥ 33, morale < 38
- **Contract request:** Contract ending, morale > 55, high ambition

**Team chemistry:** Average team morale − feud penalties (−5 ea) − demand penalties (−3 ea) − complaint penalties (−2 ea) + locker-room-leader bonuses (+3 ea). Clamped to `[10, 98]`. Directly modifies game scores.

---

## Database Schema

**Core:** `teams`, `players`, `contracts`, `games`, `player_game_stats`, `standings`, `league_state`

**Agent:** `general_managers`, `agent_memory`, `pending_trades`

**Player:** `player_personalities`, `player_morale`, `player_events`, `player_memory`, `team_chemistry`

Key design: `agent_memory` and `player_memory` log human-readable detail strings for every decision — this is the narrative context layer for Phase 4 LLM integration.

---

## League Configuration

- **4 teams, 10 players each** (40 total players)
- **12-week season** (4-round round-robin, home/away balanced)
- **Salary cap:** $100M hard cap per team
- **Trade threshold:** 0.48 (configurable in `archetypes.json`)
- **Skill range:** 42–94 (generated at seed time)

---

## Commissioner Workflow

```
# First time
python seed.py

# Each week
python run_week.py           # simulate games, morale, player actions, GM proposals
python review_trades.py      # approve / veto pending trade proposals

# Monitoring
python view_league.py        # standings, last week's results, stat leaders
python view_drama.py         # morale crises, feuds, trade demands, chemistry
streamlit run app.py         # web dashboard (optional)
```

---

## Phase Roadmap

| Phase | Status | Description |
|---|---|---|
| 1 — World Engine | Complete | Deterministic game sim, box scores, standings |
| 2 — GM Agents | Complete | 4-archetype trade proposals, personality drift |
| 3 — Player Agents | Complete | Morale, 8-archetype actions, team chemistry |
| 4 — LLM Integration | Planned | Swap rule-based scoring for Claude API calls at marked `[LLM-HOOK]` points |
| 5 — Coach & Media | Planned | Coach lineups/strategy agents; media narrative/rumor agents |

**LLM hook locations (marked `# [LLM-HOOK]` in code):**
- `player_want_score()` / `player_give_score()` / `score_trade_for_gm()` in `gm_agents.py`
- `compute_morale_update()` / `evaluate_player_week()` in `player_agents.py`
- `compute_trait_drift()` for multi-season personality evolution

---

## Key Design Decisions

1. **Rule-based first:** All logic is inspectable before LLM swap-in. No black boxes in current phases.
2. **Memory as narrative:** Every agent decision is logged in human-readable form — ready to become LLM context.
3. **Chemistry bridge:** Player morale → team chemistry → game score creates a closed feedback loop.
4. **Config-driven:** All thresholds and archetype weights live in `archetypes.json` — no code changes needed to tune behavior.
5. **No external deps:** SQLite + Python stdlib keeps setup frictionless.
