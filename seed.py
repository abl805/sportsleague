"""
Run once to create 4 teams, 40 players, and a full 12-week season schedule.
WARNING: re-running this wipes all existing data and starts fresh.
"""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables

# ── Team definitions ──────────────────────────────────────────────────────────
TEAMS = [
    {"city": "Springfield",  "name": "Stallions", "abbreviation": "SPS"},
    {"city": "Riverside",    "name": "Rockets",   "abbreviation": "RVR"},
    {"city": "Lakewood",     "name": "Lions",     "abbreviation": "LKL"},
    {"city": "Hillcrest",    "name": "Hawks",     "abbreviation": "HCH"},
]

# ── Name pools ────────────────────────────────────────────────────────────────
FIRST_NAMES = [
    "James", "Marcus", "DeShawn", "Tyler", "Kevin", "Jordan", "Malik",
    "Andre", "Chris", "Brandon", "Isaiah", "Darius", "Anthony", "Jaylen",
    "Trevon", "Zach", "Miles", "Donovan", "Cameron", "Jalen", "Lorenzo",
    "Stephen", "Kawhi", "Paul", "Devin", "Luka", "Giannis", "Joel",
    "Nikola", "Damian", "Tyrese", "Scottie", "Franz", "Alperen", "Cade",
    "Evan", "Draymond", "Jaren", "Zion", "Paolo",
]
LAST_NAMES = [
    "Johnson", "Williams", "Davis", "Thompson", "Jackson", "Anderson",
    "White", "Harris", "Martin", "Garcia", "Martinez", "Robinson",
    "Clark", "Rodriguez", "Lewis", "Walker", "Hall", "Allen", "Young",
    "Hernandez", "King", "Wright", "Lopez", "Hill", "Scott", "Green",
    "Adams", "Baker", "Nelson", "Carter", "Mitchell", "Perez", "Roberts",
    "Turner", "Phillips", "Campbell", "Parker", "Evans", "Edwards", "Collins",
]

POSITIONS_PER_TEAM = ["PG", "PG", "SG", "SG", "SF", "SF", "PF", "PF", "C", "C"]


def salary_for(skill):
    if skill >= 80:
        return random.randint(8_000_000, 20_000_000)
    elif skill >= 65:
        return random.randint(4_000_000, 7_999_999)
    elif skill >= 50:
        return random.randint(1_500_000, 3_999_999)
    else:
        return random.randint(500_000, 1_499_999)


def round_robin_weeks(team_ids):
    """
    Circle method: generates one full round-robin (each pair plays once).
    Returns list of (home_id, away_id, week_number) starting at the given week offset.
    """
    n = len(team_ids)
    fixed = team_ids[0]
    rotating = list(team_ids[1:])
    matchups = []
    week = 1

    for slot in range(n - 1):
        round_games = [(fixed, rotating[0])]
        for i in range(1, n // 2):
            round_games.append((rotating[i], rotating[n - 1 - i]))
        matchups.append((week, round_games))
        rotating = rotating[-1:] + rotating[:-1]  # rotate right
        week += 1

    return matchups, week


def build_schedule(team_ids, num_rounds=4):
    """4 rounds of round-robin = 12 weeks, 12 games per team."""
    schedule = []
    week_offset = 1

    for round_num in range(num_rounds):
        matchups, next_week = round_robin_weeks(team_ids)
        for week_in_round, games in matchups:
            actual_week = week_offset + week_in_round - 1
            for home, away in games:
                if round_num % 2 == 1:
                    home, away = away, home  # flip home/away every other round
                schedule.append((home, away, actual_week))
        week_offset += next_week - 1

    return schedule, week_offset - 1


def seed():
    create_tables()
    conn = get_connection()
    c = conn.cursor()

    # Wipe existing data
    c.executescript("""
        DELETE FROM player_game_stats;
        DELETE FROM games;
        DELETE FROM contracts;
        DELETE FROM standings;
        DELETE FROM players;
        DELETE FROM teams;
        DELETE FROM league_state;
    """)

    # Insert teams
    team_ids = []
    for t in TEAMS:
        c.execute(
            "INSERT INTO teams (city, name, abbreviation) VALUES (?, ?, ?)",
            (t["city"], t["name"], t["abbreviation"]),
        )
        team_ids.append(c.lastrowid)

    # Insert players + contracts
    used_names = set()
    for team_id in team_ids:
        positions = POSITIONS_PER_TEAM.copy()
        random.shuffle(positions)
        for pos in positions:
            while True:
                fname = random.choice(FIRST_NAMES)
                lname = random.choice(LAST_NAMES)
                if (fname, lname) not in used_names:
                    used_names.add((fname, lname))
                    break

            age    = random.randint(19, 36)
            skill  = random.randint(42, 94)
            salary = salary_for(skill)

            c.execute(
                "INSERT INTO players (team_id, first_name, last_name, age, position, skill_rating, salary)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (team_id, fname, lname, age, pos, skill, salary),
            )
            player_id = c.lastrowid

            c.execute(
                "INSERT INTO contracts (player_id, team_id, salary, years_remaining, season_start)"
                " VALUES (?, ?, ?, ?, ?)",
                (player_id, team_id, salary, random.randint(1, 4), 2025),
            )

    # Insert standings rows
    for team_id in team_ids:
        c.execute(
            "INSERT INTO standings (team_id, season_year) VALUES (?, 2025)",
            (team_id,),
        )

    # Build and insert schedule
    schedule, total_weeks = build_schedule(team_ids, num_rounds=4)
    for home, away, week in schedule:
        c.execute(
            "INSERT INTO games (home_team_id, away_team_id, week, season_year) VALUES (?, ?, ?, 2025)",
            (home, away, week),
        )

    # Initialize league state
    c.execute(
        "INSERT INTO league_state (current_week, season_year, last_updated)"
        " VALUES (1, 2025, datetime('now'))"
    )

    conn.commit()
    conn.close()

    print("League seeded!")
    print(f"  Teams   : {len(TEAMS)}")
    print(f"  Players : {len(TEAMS) * 10}")
    print(f"  Weeks   : {total_weeks}")
    print(f"  Games   : {len(schedule)}")
    print("\nNext step: run  python run_week.py")


if __name__ == "__main__":
    seed()
