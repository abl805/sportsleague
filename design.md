# Virtual Basketball League — Design Document

## Vision

A fictional basketball league where AI agents control players, GMs, coaches, and media.
The commissioner (you) approves major actions and advances the simulation week by week.
Emergent storylines arise from agents with personalities, memories, and conflicting goals.

---

## Current State: Phase 1 — World Engine

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

| Table               | Purpose                                    |
|---------------------|--------------------------------------------|
| `teams`             | Franchise name, city, abbreviation         |
| `players`           | Roster, attributes, skill rating           |
| `contracts`         | Salary, years remaining                    |
| `games`             | Schedule; home/away scores once played     |
| `player_game_stats` | Per-game box score for every player        |
| `standings`         | Season W/L/PF/PA aggregates                |
| `league_state`      | Current week, season year                  |

---

## Planned Phases

### Phase 2 — AI Agents
- Player agents with personality traits (confidence, loyalty, ambition, ego)
- GM agents: negotiate contracts, propose trades, scout free agents
- Coach agents: set lineups, call timeouts, choose strategy
- Media agents: generate game narratives, rumors, hot takes

### Phase 3 — Commissioner Interface
- Approve or veto agent-proposed trades and signings
- Trigger special events: injuries, rivalries, breakout games
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
