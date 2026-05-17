# Virtual Basketball League

An AI-powered virtual basketball league simulation. You are the commissioner.

## First-time setup

**1. Install Python** (if you haven't already)
   - Go to python.org/downloads and download the latest version for Windows
   - Run the installer — **check "Add Python to PATH"** before clicking Install

**2. Open a terminal in this folder**
   - In File Explorer, navigate to this folder
   - Click the address bar, type `cmd`, and press Enter

**3. Create a virtual environment** (a private Python sandbox for this project)
   ```
   python -m venv venv
   ```

**4. Activate it**
   ```
   venv\Scripts\activate
   ```
   You'll see `(venv)` appear at the start of your prompt.

**5. Seed the league** (creates teams, players, and schedule)
   ```
   python seed.py
   ```

---

## Playing the league

| Command                    | What it does                                    |
|----------------------------|-------------------------------------------------|
| `python run_week.py`       | Simulate this week's games, update standings    |
| `python view_league.py`    | Print standings, last week's scores, top stats  |
| `python seed.py`           | Reset everything and start a fresh season       |

---

## Project layout

```
sportsleague/
├── seed.py            ← Run once to set up the league
├── run_week.py        ← Run each week to simulate games
├── view_league.py     ← View standings and stats
├── design.md          ← Vision, rules, and design decisions
├── league/
│   ├── database.py    ← SQLite setup and connection
│   └── simulation.py  ← Game engine
└── db/
    └── league.db      ← Created automatically (not in git)
```
