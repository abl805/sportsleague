"""
Run once to create 8 teams, 80 players, and a full season schedule.
WARNING: re-running this wipes all existing data and starts fresh.
"""
import random
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import LEAGUE_YEAR, get_connection, create_tables

# ── Team definitions ──────────────────────────────────────────────────────────

TEAMS = [
    {
        "city": "Santa Maria",
        "name": "Vaqueros",
        "abbreviation": "SMA",
        "mascot": "A stern vaquero, wide-brimmed hat casting a shadow over the eyes",
        "colors": "Deep red + black + gold",
        "logo_description": "A stern vaquero face, wide-brimmed hat casting a shadow over the eyes",
        "motto": "La Tierra Es Nuestra",
        "arena": "Rancho Arena",
        "team_archetype": None,
        "play_style": (
            "Methodical half-court, strong in the paint, deliberate. Built to "
            "win close games in the fourth quarter."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Appleton",
        "name": "Papermakers",
        "abbreviation": "APL",
        "mascot": "A fox",
        "colors": "Forest green + cream + brown",
        "logo_description": "A fox mid-sprint wearing a paper mill worker's hard hat",
        "motto": "Press On",
        "arena": "The Mill",
        "team_archetype": None,
        "play_style": (
            "Relentless hustle, second chance points, outwork everyone. Never "
            "the most talented team but always the hardest playing."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Pocatello",
        "name": "Lava",
        "abbreviation": "POC",
        "mascot": "A coyote",
        "colors": "Burnt orange + charcoal black + ash grey",
        "logo_description": "A coyote howling, silhouetted against a glowing lava flow",
        "motto": "Born From Fire",
        "arena": "The Crater",
        "team_archetype": None,
        "play_style": (
            "Run and gun, high variance, zero filter. They'll drop 130 on you "
            "or lose by 25. Nobody knows which team shows up."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Laredo",
        "name": "Vivos",
        "abbreviation": "LAR",
        "mascot": "A roadrunner",
        "colors": "Deep purple + gold + white",
        "logo_description": "A roadrunner mid-sprint, legs blurred, beak forward and aggressive",
        "motto": "Siempre Vivos",
        "arena": "Rio Grande Arena",
        "team_archetype": None,
        "play_style": (
            "Fast, flashy, improvised. Heavy on flair and individual brilliance. "
            "Sometimes too chaotic but electric when clicking."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Chattanooga",
        "name": "Rapids",
        "abbreviation": "CHA",
        "mascot": "A snapping turtle",
        "colors": "Teal + navy + white",
        "logo_description": "A snapping turtle lunging forward, mouth wide open, water spraying",
        "motto": "Don't Test the Current",
        "arena": "Riverbend Arena",
        "team_archetype": None,
        "play_style": (
            "Physical, defensive grinders. Slow the game down, make it ugly, "
            "wear you out. Nobody likes playing in Riverbend Arena."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Flagstaff",
        "name": "Nightfall",
        "abbreviation": "FLG",
        "mascot": "An elk",
        "colors": "Black + pine green + gold",
        "logo_description": "An elk head straight on, eyes glowing, stars reflected in them",
        "motto": "Chase the Sun, Own the Night",
        "arena": "The Ponderosa",
        "team_archetype": None,
        "play_style": (
            "Precision half-court offense, suffocating man defense. Every "
            "possession is calculated. They don't beat you with athleticism; "
            "they beat you with preparation."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Mankato",
        "name": "Polar",
        "abbreviation": "MNK",
        "mascot": "A bison",
        "colors": "Arctic white + charcoal + electric blue",
        "logo_description": "A massive bison head straight on, frost and ice crystals covering its fur",
        "motto": "Built for This",
        "arena": "Blue Earth Center",
        "team_archetype": None,
        "play_style": (
            "Disciplined, systematic, cold-blooded. Excellent in late game "
            "situations. Nobody panics, nobody celebrates early."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
    {
        "city": "Payson",
        "name": "Peaks",
        "abbreviation": "PAY",
        "mascot": "A mountain goat",
        "colors": "Slate grey + snow white + deep blue",
        "logo_description": "A mountain goat head straight on, horns framing a mountain peak behind it",
        "motto": "Nothing Stops the Climb",
        "arena": "Wasatch Center",
        "team_archetype": None,
        "play_style": (
            "Inconsistent, always experimenting, never quite settled on an "
            "identity. Flashes of brilliance buried in losing streaks."
        ),
        "reputation": None,
        "rivalry": None,
        "signature_trait": None,
    },
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

# ── Player personality seeding ────────────────────────────────────────────────

INITIAL_MORALE = {
    "team_player":       72,
    "quiet_professional": 70,
    "locker_room_leader": 73,
    "rising_star":        68,
    "aging_veteran":      62,
    "superstar_ego":      65,
    "hothead":            57,
    "malcontent":         43,
}

def _pick_archetype(age, archetype_counts):
    """Age-weighted archetype selection; enforces max 1 malcontent per league."""
    if archetype_counts.get("malcontent", 0) >= 1:
        exclude = {"malcontent"}
    else:
        exclude = set()

    if age < 24:
        pool = [("rising_star", 0.35), ("team_player", 0.28), ("quiet_professional", 0.20),
                ("hothead", 0.12), ("superstar_ego", 0.05)]
    elif age < 30:
        pool = [("quiet_professional", 0.22), ("team_player", 0.18), ("superstar_ego", 0.14),
                ("locker_room_leader", 0.14), ("hothead", 0.14), ("malcontent", 0.08),
                ("rising_star", 0.10)]
    else:
        pool = [("aging_veteran", 0.30), ("quiet_professional", 0.25), ("team_player", 0.22),
                ("locker_room_leader", 0.15), ("superstar_ego", 0.08)]

    filtered  = [(a, w) for a, w in pool if a not in exclude]
    total_w   = sum(w for _, w in filtered)
    r         = random.random() * total_w
    cumulative = 0
    for arch, w in filtered:
        cumulative += w
        if r < cumulative:
            return arch
    return filtered[-1][0]


def _generate_traits(base_traits):
    return {
        k: max(0.05, min(0.95, v + random.gauss(0, 0.10)))
        for k, v in base_traits.items()
    }


# ── GM definitions (one per team, matched by abbreviation) ────────────────────
GM_DATA = [
    {
        "team_abbr":      "SMA",
        "name":           "Rafael 'The Closer' Mendoza",
        "archetype":      "loyal_to_veterans",
        "risk_tolerance":  0.35,
        "veteran_loyalty": 0.78,
        "youth_preference": 0.28,
        "trade_frequency": 0.10,
    },
    {
        "team_abbr":      "APL",
        "name":           "Elliot 'Press On' Greer",
        "archetype":      "analytics_driven",
        "risk_tolerance":  0.52,
        "veteran_loyalty": 0.48,
        "youth_preference": 0.56,
        "trade_frequency": 0.13,
    },
    {
        "team_abbr":      "POC",
        "name":           "Tessa 'Fireline' Cruz",
        "archetype":      "wild_card",
        "risk_tolerance":  0.86,
        "veteran_loyalty": 0.30,
        "youth_preference": 0.64,
        "trade_frequency": 0.24,
    },
    {
        "team_abbr":      "LAR",
        "name":           "Victor 'V-Max' Castellano",
        "archetype":      "win_now",
        "risk_tolerance":  0.74,
        "veteran_loyalty": 0.44,
        "youth_preference": 0.25,
        "trade_frequency": 0.20,
    },
    {
        "team_abbr":      "CHA",
        "name":           "Frank 'Old School' Navarro",
        "archetype":      "loyal_to_veterans",
        "risk_tolerance":  0.24,
        "veteran_loyalty": 0.86,
        "youth_preference": 0.16,
        "trade_frequency": 0.08,
    },
    {
        "team_abbr":      "FLG",
        "name":           "Samira 'The Algorithm' Chen",
        "archetype":      "analytics_driven",
        "risk_tolerance":  0.50,
        "veteran_loyalty": 0.42,
        "youth_preference": 0.44,
        "trade_frequency": 0.12,
    },
    {
        "team_abbr":      "MNK",
        "name":           "Nora 'Blue Line' Halvorsen",
        "archetype":      "analytics_driven",
        "risk_tolerance":  0.38,
        "veteran_loyalty": 0.62,
        "youth_preference": 0.34,
        "trade_frequency": 0.09,
    },
    {
        "team_abbr":      "PAY",
        "name":           "Marcus 'The Builder' Reed",
        "archetype":      "aggressive_rebuilder",
        "risk_tolerance":  0.82,
        "veteran_loyalty": 0.18,
        "youth_preference": 0.88,
        "trade_frequency": 0.22,
    },
]


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
    """Build repeated round-robin seasons; weeks scale with league size."""
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
    mode = "official" if "--official" in sys.argv else "test"
    official_started = 0

    create_tables()
    conn = get_connection()
    c = conn.cursor()

    # Wipe existing data (order respects foreign-key constraints)
    c.executescript("""
        DELETE FROM player_memory;
        DELETE FROM player_events;
        DELETE FROM player_morale;
        DELETE FROM player_personalities;
        DELETE FROM team_chemistry;
        DELETE FROM agent_memory;
        DELETE FROM pending_trades;
        DELETE FROM general_managers;
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
            "INSERT INTO teams"
            " (city, name, abbreviation, mascot, colors, logo_description,"
            "  motto, arena, team_archetype, play_style, reputation, rivalry,"
            "  signature_trait)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                t["city"],
                t["name"],
                t["abbreviation"],
                t["mascot"],
                t["colors"],
                t["logo_description"],
                t["motto"],
                t["arena"],
                t["team_archetype"],
                t["play_style"],
                t["reputation"],
                t["rivalry"],
                t["signature_trait"],
            ),
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
                (player_id, team_id, salary, random.randint(1, 4), LEAGUE_YEAR),
            )

    # Insert player personalities and initial morale (week 0 = pre-season baseline)
    import json as _json
    _archetypes_path = os.path.join(os.path.dirname(__file__), "archetypes.json")
    with open(_archetypes_path) as _f:
        _arch_data = _json.load(_f)
    _player_arch_cfgs = _arch_data.get("player_archetypes", {})

    archetype_counts = {}
    all_player_ids = c.execute("SELECT id, age FROM players").fetchall()
    for row in all_player_ids:
        pid  = row["id"]
        age  = row["age"]
        arch = _pick_archetype(age, archetype_counts)
        archetype_counts[arch] = archetype_counts.get(arch, 0) + 1

        base_traits = _player_arch_cfgs.get(arch, {}).get("base_traits", {
            "ambition": 0.5, "loyalty": 0.5, "ego": 0.5, "work_ethic": 0.5, "volatility": 0.3
        })
        traits = _generate_traits(base_traits)

        c.execute(
            "INSERT INTO player_personalities"
            " (player_id, archetype, ambition, loyalty, ego, work_ethic, volatility)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pid, arch, traits["ambition"], traits["loyalty"], traits["ego"],
             traits["work_ethic"], traits["volatility"]),
        )

        base_morale = INITIAL_MORALE.get(arch, 70)
        morale      = max(20.0, min(95.0, base_morale + random.gauss(0, 5)))
        c.execute(
            "INSERT INTO player_morale (player_id, week, season_year, morale)"
            " VALUES (?, 0, ?, ?)",
            (pid, LEAGUE_YEAR, morale),
        )

    # Insert GMs
    abbr_to_id = {t["abbreviation"]: tid for t, tid in zip(TEAMS, team_ids)}
    for gm in GM_DATA:
        tid = abbr_to_id[gm["team_abbr"]]
        c.execute(
            "INSERT INTO general_managers"
            " (team_id, name, archetype, risk_tolerance, veteran_loyalty,"
            "  youth_preference, trade_frequency)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (tid, gm["name"], gm["archetype"], gm["risk_tolerance"],
             gm["veteran_loyalty"], gm["youth_preference"], gm["trade_frequency"]),
        )

    # Insert standings rows
    for team_id in team_ids:
        c.execute(
            "INSERT INTO standings (team_id, season_year) VALUES (?, ?)",
            (team_id, LEAGUE_YEAR),
        )

    # Build and insert schedule
    schedule, total_weeks = build_schedule(team_ids, num_rounds=4)
    for home, away, week in schedule:
        c.execute(
            "INSERT INTO games (home_team_id, away_team_id, week, season_year) VALUES (?, ?, ?, ?)",
            (home, away, week, LEAGUE_YEAR),
        )

    # Initialize league state
    c.execute(
        "INSERT INTO league_state (current_week, season_year, mode, official_started, last_updated)"
        " VALUES (1, ?, ?, ?, datetime('now'))",
        (LEAGUE_YEAR, mode, official_started),
    )

    conn.commit()
    conn.close()

    print("League seeded!")
    print(f"  Mode    : {mode.upper()}")
    if mode == "official":
        print("  Status  : preseason; official games have not started")
    print(f"  Teams   : {len(TEAMS)}")
    print(f"  Players : {len(TEAMS) * 10}")
    print(f"  GMs     : {len(GM_DATA)}")
    print(f"  Weeks   : {total_weeks}")
    print(f"  Games   : {len(schedule)}")
    print()
    print("  GMs:")
    for gm in GM_DATA:
        print(f"    {gm['name']:<32} {gm['archetype']}")
    print()
    print("  Player archetype distribution:")
    for arch, cnt in sorted(archetype_counts.items(), key=lambda x: -x[1]):
        print(f"    {arch:<22} {cnt}")
    if mode == "official":
        print("\nNext step: run  python run_week.py --start-official  when you are ready")
    else:
        print("\nNext step: run  python run_week.py  for test simulation")


if __name__ == "__main__":
    seed()
