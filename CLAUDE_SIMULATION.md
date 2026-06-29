# AIBA Simulation Guide — Claude Code

## Overview

Simulation runs **locally through Claude Code**, writing directly to the Supabase
database. The website (aibasketballassociation.com) reads from the same database
and updates automatically after each simulation step.

---

## Setup (already done)

- `DATABASE_URL` is set in `.env` pointing to Supabase session pooler
- `psycopg[binary]` is installed locally for the connection
- `.env` is gitignored — never commit it

---

## Simulating the Season

### Run a regular-season week
```
python run_week.py
```
Simulates all games for the current week, updates standings, runs GM trade
agents, updates player morale, and generates post-game interview prompts.

### Run a playoff week
Same command — the engine detects the phase automatically:
```
python run_week.py
```

### Run an offseason stage
There are 7 stages that must run in order:
1. Retirements
2. Player Development
3. Contracts
4. Rookie Draft
5. Free Agency
6. Roster Finalization
7. Schedule Release

Run one stage at a time:
```
python run_offseason.py
```

After all 7 stages, `league_state` advances to the next season at Week 1.

---

## Generating ChatGPT Packets

After simulating a week, generate the league snapshot packet:

```python
from league.chatgpt_bridge import build_chatgpt_packet
from league.database import get_connection

conn = get_connection()
state = conn.execute("SELECT season_year, current_week FROM league_state WHERE id=1").fetchone()
conn.close()

season = state["season_year"]
week = state["current_week"]

packet = build_chatgpt_packet(
    "League snapshot",
    f"Season {season}, Week {week - 1} just completed. Summarize standings, "
    f"top performers, biggest upsets, and early storylines. "
    f"Include 2-3 articles and influences."
)
print(packet)
```

### Other packet types

**Team report** (deep dive on one team):
```python
# Get team_id from the teams table first
packet = build_chatgpt_packet(
    "Team report",
    "Write a narrative team report on the [Team Name]: recent results, "
    "standout players, GM tendencies, and what the commissioner should watch.",
    team_id=5   # replace with actual team id
)
```

**Trade review** (when pending trades exist):
```python
packet = build_chatgpt_packet(
    "Pending trade review",
    "Analyze this trade. Is it fair? Who benefits? Should the commissioner approve or veto?",
    trade_id=12   # replace with actual trade id
)
```

---

## Applying ChatGPT Responses

Paste the full ChatGPT response (including the `=== CHATGPT TO AIBA ===` markers)
into the commissioner dashboard at `/commissioner`:
- **Publish Articles** form → publishes news to the website
- **Apply Influences** form → sets player/team/GM modifiers for future weeks

Or apply directly from Claude Code:

```python
from league.chatgpt_bridge import parse_chatgpt_response
from web_app import app

response_text = """[paste full ChatGPT response here]"""

with app.app_context():
    # articles and influences are extracted and saved automatically
    from web_app import _apply_articles, _apply_influences
    # (use the commissioner_articles_add / commissioner_influences_add routes instead)
```

The easiest method is the `/commissioner` dashboard paste forms.

---

## Checking League State

```python
from league.database import get_connection
conn = get_connection()
state = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
print(dict(state))
conn.close()
```

---

## Season Workflow Summary

```
Week 1  →  run_week.py  →  generate packet  →  ChatGPT  →  paste articles/influences
Week 2  →  run_week.py  →  generate packet  →  ChatGPT  →  paste articles/influences
...
Week 14 →  run_week.py  →  playoffs seeded automatically
Playoff Week 1-5  →  run_week.py  →  champion crowned
Offseason ×7  →  run_offseason.py  →  season resets to Week 1
```

---

## Pending Trades

The GM agents propose trades automatically after each week. Check for pending trades:

```python
from league.database import get_connection
from league import web_queries as q
conn = get_connection()
trades = q.pending_trades(conn)
for t in trades:
    print(f"Trade #{t['id']}: {t['proposing_team']} ↔ {t['receiving_team']}")
conn.close()
```

Review and approve/veto from the `/commissioner` dashboard on the website.

---

## Resetting a Season (emergency only)

If a season needs to be wiped and replayed:

```python
from league.database import get_connection

conn = get_connection()
season = 2026

# Reset all game data for the season (keeps schedule, wipes results)
conn.execute("UPDATE games SET played=0, home_score=NULL, away_score=NULL, q1_home=NULL, q2_home=NULL, q3_home=NULL, q4_home=NULL, q1_away=NULL, q2_away=NULL, q3_away=NULL, q4_away=NULL, mvp_player_id=NULL WHERE season_year=?", (season,))
conn.execute("DELETE FROM player_game_stats WHERE game_id IN (SELECT id FROM games WHERE season_year=?)", (season,))
conn.execute("UPDATE standings SET wins=0, losses=0, points_for=0, points_against=0 WHERE season_year=?", (season,))
conn.execute("DELETE FROM player_morale WHERE season_year=?", (season,))
conn.execute("DELETE FROM agent_memory WHERE season_year=?", (season,))
conn.execute("DELETE FROM player_memory WHERE season_year=?", (season,))
conn.execute("DELETE FROM player_events WHERE season_year=?", (season,))
conn.execute("DELETE FROM pending_trades WHERE season_year=?", (season,))
conn.execute("DELETE FROM articles WHERE season_year=?", (season,))
conn.execute("DELETE FROM player_interviews WHERE season_year=?", (season,))
conn.execute("DELETE FROM gm_interviews WHERE season_year=?", (season,))
conn.execute("UPDATE league_state SET current_week=1, phase='regular_season', offseason_stage=NULL WHERE id=1")
conn.commit()
conn.close()
print("Reset complete.")
```
