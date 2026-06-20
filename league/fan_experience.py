"""Fan-facing world building, continuity, editorial, and participation systems."""

import hashlib
import json
import math
import random
import re

from league.player_agents import log_player_memory


EDITORIAL_SCHEMA = "aiba.weekly_editorial.v1"
EDITORIAL_TO_GPT_START = "=== AIBA WEEKLY EDITORIAL TO CHATGPT ==="
EDITORIAL_TO_GPT_END = "=== END AIBA WEEKLY EDITORIAL TO CHATGPT ==="
EDITORIAL_FROM_GPT_START = "=== CHATGPT TO AIBA WEEKLY EDITORIAL ==="
EDITORIAL_FROM_GPT_END = "=== END CHATGPT TO AIBA WEEKLY EDITORIAL ==="


TEAM_MYTHOLOGY = {
    "FLG": {
        "team_archetype": "The Empire",
        "reputation": "The league's feared standard-bearer: prepared, clinical, and easy to root against.",
        "rivalry": "Chattanooga Rapids",
        "signature_trait": "They make every opponent play their game.",
        "fan_pitch": "Choose Flagstaff if you prefer dominance, precision, and being the team everyone wants to knock off.",
        "pressure_label": "Anything short of a title feels like failure.",
        "rivalry_intensity": 0.92,
    },
    "APL": {
        "team_archetype": "The Blue-Collar Underdog",
        "reputation": "A hard-hat team that survives on effort, second chances, and collective belief.",
        "rivalry": "Mankato Polar",
        "signature_trait": "They turn loose balls into a civic duty.",
        "fan_pitch": "Choose Appleton if you want every win to feel earned and every overlooked player to matter.",
        "pressure_label": "Can effort finally beat pedigree?",
        "rivalry_intensity": 0.66,
    },
    "SMA": {
        "team_archetype": "The Sleeping Giant",
        "reputation": "A proud, talented franchise that always looks one breakthrough away from taking over.",
        "rivalry": "Laredo Vivos",
        "signature_trait": "Late-game patience with heavyweight expectations.",
        "fan_pitch": "Choose Santa Maria if you believe the next great power is already waking up.",
        "pressure_label": "The talent is real. The wait cannot last forever.",
        "rivalry_intensity": 0.78,
    },
    "PAY": {
        "team_archetype": "The Lovable Curse",
        "reputation": "A restless rebuild whose flashes of hope keep pulling people back in.",
        "rivalry": "Flagstaff Nightfall",
        "signature_trait": "Every climb begins immediately after another fall.",
        "fan_pitch": "Choose Payson if you want to suffer honestly and someday say you were there before the miracle.",
        "pressure_label": "Is this finally the year the climb becomes real?",
        "rivalry_intensity": 0.58,
    },
    "POC": {
        "team_archetype": "The Wildfire",
        "reputation": "The league's chaotic variable: capable of a masterpiece or a crater in the same week.",
        "rivalry": "Payson Peaks",
        "signature_trait": "Variance is not a side effect. It is the plan.",
        "fan_pitch": "Choose Pocatello if you want speed, nerve, arguments, and absolutely no safe evenings.",
        "pressure_label": "Can chaos survive long enough to become greatness?",
        "rivalry_intensity": 0.61,
    },
    "CHA": {
        "team_archetype": "The Empire Breaker",
        "reputation": "A bruising challenger built to drag polished contenders into deep water.",
        "rivalry": "Flagstaff Nightfall",
        "signature_trait": "They make beautiful basketball feel physically expensive.",
        "fan_pitch": "Choose Chattanooga if your favorite sound is a dynasty beginning to crack.",
        "pressure_label": "They were built to stop Flagstaff. Now they have to prove it.",
        "rivalry_intensity": 0.94,
    },
    "LAR": {
        "team_archetype": "The Neon Contender",
        "reputation": "The league's most glamorous show, still chasing the serious respect that only winning brings.",
        "rivalry": "Santa Maria Vaqueros",
        "signature_trait": "They can turn a broken possession into the play of the night.",
        "fan_pitch": "Choose Laredo if you want flair, stars, noise, and the fight to prove entertainment can win.",
        "pressure_label": "Highlights are no longer enough.",
        "rivalry_intensity": 0.79,
    },
    "MNK": {
        "team_archetype": "The Cold Machine",
        "reputation": "An overlooked, systematic team that treats pressure like another line in the scouting report.",
        "rivalry": "Appleton Papermakers",
        "signature_trait": "No panic, no wasted motion, no warning.",
        "fan_pitch": "Choose Mankato if you like quiet competence and watching louder teams realize too late.",
        "pressure_label": "How long can the league keep overlooking them?",
        "rivalry_intensity": 0.67,
    },
}


COACH_PROFILES = {
    "SMA": ("Elena 'La Jefa' Torres", "inside_control", 0.72, 0.80, 0.84, 0.38, 0.78),
    "APL": ("Jonah Mercer", "hustle_pressure", 0.86, 0.78, 0.68, 0.64, 0.52),
    "POC": ("Dex Rainer", "pace_and_space", 0.74, 0.54, 0.61, 0.94, 0.34),
    "LAR": ("Celeste Vega", "creative_motion", 0.79, 0.67, 0.72, 0.86, 0.43),
    "CHA": ("Wallace Boone", "defensive_grind", 0.60, 0.88, 0.81, 0.24, 0.82),
    "FLG": ("Adrian Vale", "precision_balance", 0.76, 0.91, 0.93, 0.48, 0.74),
    "MNK": ("Ingrid Solberg", "late_game_control", 0.71, 0.85, 0.90, 0.42, 0.76),
    "PAY": ("Milo Hart", "development_lab", 0.94, 0.64, 0.58, 0.70, 0.40),
}

LINEUP_PREFERENCES = {
    "inside_control": "size_and_strength",
    "hustle_pressure": "energy_and_defense",
    "pace_and_space": "speed_and_shooting",
    "creative_motion": "playmaking",
    "defensive_grind": "defense_and_veterans",
    "precision_balance": "balanced_best_five",
    "late_game_control": "clutch_and_experience",
    "development_lab": "youth_and_upside",
    "adaptive_balance": "balanced_best_five",
}

POLL_ROTATION = (
    "fan_player_of_week",
    "fan_game_of_week",
    "fan_confidence",
    "rivalry_name",
    "award_name",
)

RIVALRY_NAME_OPTIONS = {
    ("CHA", "FLG"): (
        "The Empire Breaker Series",
        "Battle for the Current",
        "The Blackwater Rivalry",
        "Nightfall at Riverbend",
    ),
    ("LAR", "SMA"): (
        "The Borderlight Classic",
        "The Golden Spur",
        "The Rio-Range Rivalry",
        "The Vaquero-Vivo Feud",
    ),
    ("APL", "MNK"): (
        "The Frost & Fiber Cup",
        "The Northern Press",
        "The Mill-Ice Rivalry",
        "The Blue-Collar Classic",
    ),
    ("PAY", "POC"): (
        "The Fault Line Feud",
        "The Mountain Fire Classic",
        "The Crater Climb",
        "The High Desert Derby",
    ),
}

AWARD_NAME_OPTIONS = (
    "The Heartbeat Award",
    "The Extra Possession Trophy",
    "The Engine Room Honor",
    "The Hard Hat Award",
)

FOUNDING_RIVALRIES = {
    ("CHA", "FLG"): 0.82,
    ("LAR", "SMA"): 0.68,
    ("APL", "MNK"): 0.58,
    ("PAY", "POC"): 0.52,
    ("FLG", "PAY"): 0.42,
}

RECORD_STATS = (
    ("points", "Points"),
    ("rebounds", "Rebounds"),
    ("assists", "Assists"),
    ("steals", "Steals"),
    ("blocks", "Blocks"),
)

RECORD_SCOPE_LABELS = {
    "single_game": "Single-game",
    "season": "Single-season",
    "career": "Career",
}


def _stable_float(key, low=0.0, high=1.0):
    raw = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:12], 16)
    return low + (raw / float(0xFFFFFFFFFFFF)) * (high - low)


def _ordered_team_ids(team_a_id, team_b_id):
    return tuple(sorted((int(team_a_id), int(team_b_id))))


def backfill_fan_foundations(conn):
    """Populate new narrative fields without resetting existing league progress."""
    teams = conn.execute("SELECT id, abbreviation FROM teams").fetchall()
    team_ids_by_abbr = {team["abbreviation"]: team["id"] for team in teams}
    for team in teams:
        myth = TEAM_MYTHOLOGY.get(team["abbreviation"])
        if not myth:
            continue
        conn.execute(
            """
            UPDATE teams
            SET team_archetype = COALESCE(team_archetype, ?),
                reputation = COALESCE(reputation, ?),
                rivalry = COALESCE(rivalry, ?),
                signature_trait = COALESCE(signature_trait, ?),
                fan_pitch = COALESCE(fan_pitch, ?),
                pressure_label = COALESCE(pressure_label, ?),
                rivalry_intensity = CASE
                    WHEN team_archetype IS NULL THEN ?
                    ELSE COALESCE(rivalry_intensity, ?)
                END
            WHERE id = ?
            """,
            (
                myth["team_archetype"],
                myth["reputation"],
                myth["rivalry"],
                myth["signature_trait"],
                myth["fan_pitch"],
                myth["pressure_label"],
                myth["rivalry_intensity"],
                myth["rivalry_intensity"],
                team["id"],
            ),
        )

        coach_exists = conn.execute(
            "SELECT id FROM head_coaches WHERE team_id=? AND status='active'",
            (team["id"],),
        ).fetchone()
        profile = COACH_PROFILES.get(team["abbreviation"])
        if profile and not coach_exists:
            lineup_preference = LINEUP_PREFERENCES.get(
                profile[1], "balanced_best_five"
            )
            conn.execute(
                """
                INSERT INTO head_coaches
                    (team_id, name, strategy, development, leadership,
                     pressure_handling, pace_preference, rotation_tightness,
                     lineup_preference, job_security, hired_season)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0.76, 2026)
                """,
                (team["id"], *profile, lineup_preference),
            )
        conn.execute(
            """
            INSERT INTO franchise_events
                (team_id, season_year, event_type, title, detail, source_key)
            VALUES (?, 2026, 'founding',
                    'Founding member of the AIBA',
                    'Joined the original eight-franchise league for the inaugural 2026 season.',
                    ?)
            ON CONFLICT (source_key) DO NOTHING
            """,
            (team["id"], f"franchise-founding:{team['id']}"),
        )

    for abbreviations, base_intensity in FOUNDING_RIVALRIES.items():
        if not all(abbr in team_ids_by_abbr for abbr in abbreviations):
            continue
        team_a_id, team_b_id = _ordered_team_ids(
            team_ids_by_abbr[abbreviations[0]],
            team_ids_by_abbr[abbreviations[1]],
        )
        conn.execute(
            """
            INSERT INTO team_rivalries
                (team_a_id, team_b_id, base_intensity, current_intensity,
                 last_event)
            VALUES (?, ?, ?, ?, 'Founding league rivalry')
            ON CONFLICT (team_a_id, team_b_id) DO NOTHING
            """,
            (team_a_id, team_b_id, base_intensity, base_intensity),
        )

    personalities = conn.execute(
        """
        SELECT pp.player_id, pp.archetype, pp.leadership, pp.clutch,
               pp.durability, pp.media_reputation
        FROM player_personalities pp
        """
    ).fetchall()
    for row in personalities:
        values = [
            row["leadership"],
            row["clutch"],
            row["durability"],
            row["media_reputation"],
        ]
        if all(value is not None and abs(value - 0.5) > 0.0001 for value in values):
            continue
        pid = row["player_id"]
        archetype = row["archetype"]
        leadership_base = 0.82 if archetype == "locker_room_leader" else 0.48
        clutch_base = 0.68 if archetype in ("superstar_ego", "aging_veteran") else 0.52
        durability_base = 0.76 if archetype in ("quiet_professional", "team_player") else 0.66
        media_base = 0.72 if archetype in ("superstar_ego", "hothead") else 0.50
        conn.execute(
            """
            UPDATE player_personalities
            SET leadership=?, clutch=?, durability=?, media_reputation=?
            WHERE player_id=?
            """,
            (
                _stable_float(f"{pid}:leadership", leadership_base - 0.16, leadership_base + 0.16),
                _stable_float(f"{pid}:clutch", clutch_base - 0.18, clutch_base + 0.18),
                _stable_float(f"{pid}:durability", durability_base - 0.14, durability_base + 0.14),
                _stable_float(f"{pid}:media", media_base - 0.20, media_base + 0.20),
                pid,
            ),
        )

    state = conn.execute("SELECT season_year FROM league_state WHERE id=1").fetchone()
    season = state["season_year"] if state else 2026
    for player in conn.execute(
        "SELECT id, first_name, last_name, age, skill_rating FROM players"
    ).fetchall():
        arc = _initial_arc(dict(player))
        conn.execute(
            """
            INSERT INTO player_arcs
                (player_id, arc_type, title, summary, started_season, updated_week)
            VALUES (?, ?, ?, ?, ?, 0)
            ON CONFLICT (player_id) DO NOTHING
            """,
            (player["id"], arc[0], arc[1], arc[2], season),
        )


def _initial_arc(player):
    name = f"{player['first_name']} {player['last_name']}"
    if player["age"] <= 23 and player["skill_rating"] >= 76:
        return ("future_face", "The Future Arrives Early", f"{name} is already carrying expectations beyond his age.")
    if player["age"] >= 32 and player["skill_rating"] >= 80:
        return ("last_run", "One More Run", f"{name} is trying to turn veteran craft into one more defining season.")
    if player["skill_rating"] >= 88:
        return ("franchise_star", "Franchise Gravity", f"{name} changes every decision his team and its opponents make.")
    return ("proving_ground", "Something to Prove", f"{name} enters the season with a role still waiting to become a reputation.")


def get_active_coach(conn, team_id):
    row = conn.execute(
        "SELECT * FROM head_coaches WHERE team_id=? AND status='active' ORDER BY id DESC LIMIT 1",
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


def get_active_injuries(conn, team_id, season_year, week):
    return [
        dict(row)
        for row in conn.execute(
            """
            SELECT i.*, p.first_name || ' ' || p.last_name AS player_name
            FROM player_injuries i
            JOIN players p ON p.id=i.player_id
            WHERE p.team_id=? AND i.season_year=? AND i.status='active'
              AND i.week_start <= ? AND i.expected_return_week >= ?
            ORDER BY i.skill_penalty DESC, p.skill_rating DESC
            """,
            (team_id, season_year, week, week),
        ).fetchall()
    ]


def record_history_event(
    conn,
    season_year,
    week,
    event_type,
    headline,
    detail=None,
    team_id=None,
    player_id=None,
    coach_id=None,
    game_id=None,
    source_key=None,
    importance=1,
):
    conn.execute(
        """
        INSERT INTO history_events
            (season_year, week, event_type, headline, detail, team_id,
             player_id, coach_id, game_id, source_key, importance)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source_key) DO NOTHING
        """,
        (
            season_year,
            week,
            event_type,
            headline,
            detail,
            team_id,
            player_id,
            coach_id,
            game_id,
            source_key,
            importance,
        ),
    )


def injury_recovery_probabilities(
    severity,
    age,
    durability=0.7,
    work_ethic=0.5,
    coach_development=0.5,
):
    """Return bounded rehabilitation outcome probabilities."""
    if severity != "major":
        lingering = max(
            0.02,
            min(
                0.16,
                0.08
                + (0.65 - durability) * 0.12
                + max(0, age - 30) * 0.006,
            ),
        )
        return {
            "career_altering": 0.0,
            "lingering_decline": lingering,
            "comeback_path": 0.0,
            "full_recovery": 1.0 - lingering,
        }

    resilience = (
        durability * 0.34
        + work_ethic * 0.30
        + coach_development * 0.24
        + max(0.0, min(1.0, (34 - age) / 14.0)) * 0.12
    )
    career_altering = max(
        0.08,
        min(
            0.34,
            0.27 - resilience * 0.20 + max(0, age - 30) * 0.012,
        ),
    )
    lingering = max(0.20, min(0.40, 0.37 - resilience * 0.18))
    comeback = max(
        0.14,
        min(
            0.34,
            0.13 + work_ethic * 0.12 + coach_development * 0.10,
        ),
    )
    total = career_altering + lingering + comeback
    if total > 0.88:
        scale = 0.88 / total
        career_altering *= scale
        lingering *= scale
        comeback *= scale
    return {
        "career_altering": career_altering,
        "lingering_decline": lingering,
        "comeback_path": comeback,
        "full_recovery": 1.0 - career_altering - lingering - comeback,
    }


def determine_injury_recovery_outcome(
    severity,
    age,
    durability=0.7,
    work_ethic=0.5,
    coach_development=0.5,
    roll=None,
    severity_roll=None,
):
    probabilities = injury_recovery_probabilities(
        severity, age, durability, work_ethic, coach_development
    )
    roll = random.random() if roll is None else roll
    severity_roll = random.random() if severity_roll is None else severity_roll
    threshold = probabilities["career_altering"]
    if roll < threshold:
        outcome_type = "career_altering"
        skill_loss = 3 + min(3, int(severity_roll * 4))
        durability_loss = 0.10 + severity_roll * 0.08
        recovery_ceiling = 1 if work_ethic < 0.72 else 2
    else:
        threshold += probabilities["lingering_decline"]
        if roll < threshold:
            outcome_type = "lingering_decline"
            skill_loss = 1 + min(1, int(severity_roll * 2))
            durability_loss = 0.04 + severity_roll * 0.05
            recovery_ceiling = 1
        else:
            threshold += probabilities["comeback_path"]
            if roll < threshold:
                outcome_type = "comeback_path"
                skill_loss = 1 + min(1, int(severity_roll * 2))
                durability_loss = 0.02 + severity_roll * 0.03
                recovery_ceiling = skill_loss
            else:
                outcome_type = "full_recovery"
                skill_loss = 0
                durability_loss = 0.0
                recovery_ceiling = 0
    return {
        "outcome_type": outcome_type,
        "skill_loss": skill_loss,
        "durability_loss": round(durability_loss, 3),
        "recovery_ceiling": recovery_ceiling,
        "probabilities": probabilities,
    }


def resolve_injury_consequence(
    conn,
    injury,
    season_year,
    week,
    roll=None,
    severity_roll=None,
):
    existing = conn.execute(
        "SELECT * FROM injury_consequences WHERE injury_id=?",
        (injury["id"],),
    ).fetchone()
    if existing:
        return dict(existing)
    player = conn.execute(
        """
        SELECT p.*, COALESCE(pp.durability, 0.7) AS durability,
               COALESCE(pp.work_ethic, 0.5) AS work_ethic,
               COALESCE(hc.development, 0.5) AS coach_development,
               hc.name AS coach_name
        FROM players p
        LEFT JOIN player_personalities pp ON pp.player_id=p.id
        LEFT JOIN head_coaches hc
          ON hc.team_id=p.team_id AND hc.status='active'
        WHERE p.id=?
        """,
        (injury["player_id"],),
    ).fetchone()
    if not player:
        return None
    player = dict(player)
    outcome = determine_injury_recovery_outcome(
        injury["severity"],
        player["age"],
        player["durability"],
        player["work_ethic"],
        player["coach_development"],
        roll=roll,
        severity_roll=severity_roll,
    )
    actual_skill_loss = min(
        outcome["skill_loss"],
        max(0, player["skill_rating"] - 35),
    )
    new_skill = player["skill_rating"] - actual_skill_loss
    new_durability = max(
        0.25,
        player["durability"] - outcome["durability_loss"],
    )
    conn.execute(
        "UPDATE players SET skill_rating=? WHERE id=?",
        (new_skill, player["id"]),
    )
    conn.execute(
        "UPDATE player_personalities SET durability=? WHERE player_id=?",
        (new_durability, player["id"]),
    )
    prior = conn.execute(
        """
        SELECT AVG(pgs.points) AS ppg
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        WHERE pgs.player_id=?
          AND (g.season_year<? OR (g.season_year=? AND g.week<?))
        """,
        (
            player["id"], injury["season_year"],
            injury["season_year"], injury["week_start"],
        ),
    ).fetchone()
    target_points = float(
        prior["ppg"]
        if prior and prior["ppg"] is not None
        else max(8.0, (player["skill_rating"] - 55) * 0.75)
    )
    name = f"{player['first_name']} {player['last_name']}"
    outcome_type = outcome["outcome_type"]
    if outcome_type == "career_altering":
        summary = (
            f"{name} returned from {injury['description'].lower()} with a "
            f"{actual_skill_loss}-point rating loss and reduced durability. "
            "The injury permanently changed the shape of the career."
        )
        arc = (
            "career_altered", "A Career Redrawn",
            f"{name} is rebuilding a career after an injury took away part of the old version.",
        )
        event_type, importance = "career_altering_injury", 3
    elif outcome_type == "lingering_decline":
        summary = (
            f"{name} was cleared, but lingering effects cost "
            f"{actual_skill_loss} rating point{'s' if actual_skill_loss != 1 else ''} "
            "and lowered durability."
        )
        arc = (
            "post_injury_adjustment", "Learning a Different Game",
            f"{name} is adapting after the injury left permanent physical consequences.",
        )
        event_type, importance = "injury_consequence", 2
    elif outcome_type == "comeback_path":
        summary = (
            f"{name} returned below the pre-injury level and begins a performance-driven "
            f"comeback with up to {outcome['recovery_ceiling']} rating point"
            f"{'s' if outcome['recovery_ceiling'] != 1 else ''} recoverable."
        )
        arc = (
            "comeback", "The Long Way Back",
            f"{name}'s return is only the start; real games will decide how much of the old form comes back.",
        )
        event_type, importance = "comeback_begins", 2
    else:
        summary = (
            f"{name} completed rehabilitation without a permanent rating or "
            "durability loss."
        )
        arc = None
        event_type, importance = "injury_return", 1

    comeback_status = (
        "active"
        if actual_skill_loss > 0 and outcome["recovery_ceiling"] > 0
        else "complete"
    )
    cur = conn.execute(
        """
        INSERT INTO injury_consequences
            (injury_id, player_id, outcome_type, original_skill, skill_loss,
             original_durability, durability_loss, recovery_ceiling,
             target_points, comeback_status, resolved_season, resolved_week,
             completed_season, completed_week, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            injury["id"], player["id"], outcome_type,
            player["skill_rating"], actual_skill_loss, player["durability"],
            outcome["durability_loss"], outcome["recovery_ceiling"],
            target_points, comeback_status, season_year, week,
            season_year if comeback_status == "complete" else None,
            week if comeback_status == "complete" else None,
            summary,
        ),
    )
    consequence_id = cur.fetchone()["id"]
    if arc:
        conn.execute(
            """
            INSERT INTO player_arcs
                (player_id, arc_type, title, summary, started_season, updated_week)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (player_id) DO UPDATE SET
                arc_type=EXCLUDED.arc_type, title=EXCLUDED.title,
                summary=EXCLUDED.summary,
                started_season=EXCLUDED.started_season,
                updated_week=EXCLUDED.updated_week
            """,
            (player["id"], arc[0], arc[1], arc[2], season_year, week),
        )
    record_history_event(
        conn,
        season_year,
        week,
        event_type,
        (
            f"{name}'s career is altered by injury"
            if outcome_type == "career_altering"
            else f"{name} begins the comeback"
            if outcome_type == "comeback_path"
            else f"{name} returns with lingering effects"
            if outcome_type == "lingering_decline"
            else f"{name} cleared to return"
        ),
        summary,
        team_id=player["team_id"],
        player_id=player["id"],
        source_key=f"injury-consequence:{injury['id']}",
        importance=importance,
    )
    log_player_memory(
        conn,
        player["id"],
        week,
        season_year,
        event_type,
        summary,
    )
    return dict(conn.execute(
        "SELECT * FROM injury_consequences WHERE id=?",
        (consequence_id,),
    ).fetchone())


def prepare_week_injuries(conn, week, season_year):
    """Resolve expired injuries and occasionally create new, durability-based injuries."""
    expired = conn.execute(
        """
        SELECT i.*, p.first_name || ' ' || p.last_name AS player_name
        FROM player_injuries i
        JOIN players p ON p.id=i.player_id
        WHERE i.status='active' AND
              (i.season_year < ? OR (i.season_year=? AND i.expected_return_week < ?))
        """,
        (season_year, season_year, week),
    ).fetchall()
    for injury in expired:
        conn.execute("UPDATE player_injuries SET status='resolved' WHERE id=?", (injury["id"],))
        resolve_injury_consequence(conn, dict(injury), season_year, week)

    active_ids = {
        row["player_id"]
        for row in conn.execute(
            "SELECT player_id FROM player_injuries WHERE status='active'"
        ).fetchall()
    }
    players = conn.execute(
        """
        SELECT p.id, p.team_id, p.first_name, p.last_name, p.skill_rating,
               pp.durability
        FROM players p
        JOIN player_personalities pp ON pp.player_id=p.id
        WHERE COALESCE(p.status, 'active')='active'
        """
    ).fetchall()
    created = []
    for player in players:
        if player["id"] in active_ids:
            continue
        durability = player["durability"] if player["durability"] is not None else 0.7
        probability = 0.0025 + (1.0 - durability) * 0.014
        if random.random() >= probability:
            continue
        roll = random.random()
        if roll < 0.68:
            severity, weeks, penalty, label = "minor", 1, 5.0, "ankle soreness"
        elif roll < 0.94:
            severity, weeks, penalty, label = "moderate", random.randint(2, 3), 11.0, "lower-body strain"
        else:
            severity, weeks, penalty, label = "major", random.randint(4, 7), 100.0, "significant knee injury"
        name = f"{player['first_name']} {player['last_name']}"
        description = f"{name} will miss time with {label}."
        cur = conn.execute(
            """
            INSERT INTO player_injuries
                (player_id, season_year, week_start, expected_return_week,
                 severity, skill_penalty, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (player["id"], season_year, week, week + weeks - 1, severity, penalty, description),
        )
        injury_id = cur.fetchone()["id"]
        record_history_event(
            conn,
            season_year,
            week,
            "injury",
            f"{name} sidelined",
            description,
            team_id=player["team_id"],
            player_id=player["id"],
            source_key=f"injury:{injury_id}",
            importance=2 if severity != "minor" else 1,
        )
        created.append(player["id"])
    conn.commit()
    return created


def adjusted_roster_for_game(conn, team_id, season_year, week):
    injuries = {
        row["player_id"]: dict(row)
        for row in conn.execute(
            """
            SELECT i.*
            FROM player_injuries i
            JOIN players p ON p.id=i.player_id
            WHERE p.team_id=? AND i.season_year=? AND i.status='active'
              AND i.week_start<=? AND i.expected_return_week>=?
            """,
            (team_id, season_year, week, week),
        ).fetchall()
    }
    roster = []
    total_penalty = 0.0
    for row in conn.execute(
        """
        SELECT p.*, pp.clutch, pp.durability, pp.leadership, pp.work_ethic
        FROM players p
        LEFT JOIN player_personalities pp ON pp.player_id=p.id
        WHERE p.team_id=? AND COALESCE(p.status, 'active')='active'
        """,
        (team_id,),
    ).fetchall():
        player = dict(row)
        injury = injuries.get(player["id"])
        if injury and injury["skill_penalty"] >= 90:
            total_penalty += max(3.0, (player["skill_rating"] - 55) * 0.12)
            continue
        if injury:
            player["skill_rating"] = max(35, int(player["skill_rating"] - injury["skill_penalty"]))
            total_penalty += injury["skill_penalty"] * 0.12
        roster.append(player)
    if len(roster) < 5:
        emergency = conn.execute(
            """
            SELECT p.*, pp.clutch, pp.durability, pp.leadership, pp.work_ethic
            FROM players p
            LEFT JOIN player_personalities pp ON pp.player_id=p.id
            WHERE p.team_id=? AND COALESCE(p.status, 'active')='active'
            ORDER BY p.skill_rating DESC LIMIT 5
            """,
            (team_id,),
        ).fetchall()
        roster = [dict(row) for row in emergency]
        total_penalty += 4.0
    return roster, list(injuries.values()), total_penalty


def process_injury_comebacks(conn, week, season_year):
    """Let post-injury performance restore bounded portions of lost ability."""
    active = conn.execute(
        """
        SELECT ic.*, p.team_id, p.first_name, p.last_name, p.skill_rating,
               COALESCE(pp.work_ethic, 0.5) AS work_ethic,
               COALESCE(hc.development, 0.5) AS coach_development
        FROM injury_consequences ic
        JOIN players p ON p.id=ic.player_id
        LEFT JOIN player_personalities pp ON pp.player_id=p.id
        LEFT JOIN head_coaches hc
          ON hc.team_id=p.team_id AND hc.status='active'
        WHERE ic.comeback_status='active'
        """
    ).fetchall()
    updates = []
    for row in active:
        consequence = dict(row)
        performance = conn.execute(
            """
            SELECT COUNT(*) AS games, MAX(pgs.points) AS best_points,
                   AVG(pgs.points) AS ppg,
                   MAX(
                       pgs.points + pgs.rebounds*0.75 + pgs.assists*0.65
                       + pgs.steals*1.6 + pgs.blocks*1.35
                   ) AS best_value
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            WHERE pgs.player_id=? AND g.season_year=? AND g.week=?
            """,
            (consequence["player_id"], season_year, week),
        ).fetchone()
        games = int(performance["games"] or 0)
        if not games:
            continue
        best_points = float(performance["best_points"] or 0)
        best_value = float(performance["best_value"] or 0)
        target = max(8.0, float(consequence["target_points"] or 0))
        strong_week = (
            best_points >= target * 0.85
            or best_value >= target * 1.20
        )
        recovery_points = consequence["recovery_points"]
        if strong_week:
            recovery_points += 1
            if (
                consequence["work_ethic"] >= 0.80
                or consequence["coach_development"] >= 0.85
            ):
                recovery_points += 1
        games_since_return = consequence["games_since_return"] + games
        restored = consequence["skill_restored"]
        current_skill = consequence["skill_rating"]
        restored_this_week = False
        if (
            recovery_points >= 2
            and restored < consequence["recovery_ceiling"]
            and current_skill < consequence["original_skill"]
        ):
            restored += 1
            recovery_points -= 2
            current_skill += 1
            restored_this_week = True
            conn.execute(
                "UPDATE players SET skill_rating=? WHERE id=?",
                (current_skill, consequence["player_id"]),
            )

        completed = (
            restored >= consequence["recovery_ceiling"]
            or current_skill >= consequence["original_skill"]
        )
        settled = games_since_return >= 10 and not completed
        status = "complete" if completed else "settled" if settled else "active"
        conn.execute(
            """
            UPDATE injury_consequences
            SET skill_restored=?, recovery_points=?, games_since_return=?,
                comeback_status=?, completed_season=?, completed_week=?,
                updated_at=datetime('now')
            WHERE id=?
            """,
            (
                restored, recovery_points, games_since_return, status,
                season_year if status != "active" else None,
                week if status != "active" else None,
                consequence["id"],
            ),
        )
        name = f"{consequence['first_name']} {consequence['last_name']}"
        if restored_this_week:
            detail = (
                f"{name}'s post-injury form restored one rating point after "
                f"a strong Week {week} performance. {restored} of "
                f"{consequence['recovery_ceiling']} recoverable points have returned."
            )
            record_history_event(
                conn,
                season_year,
                week,
                "comeback_progress",
                f"{name} takes another step in the comeback",
                detail,
                team_id=consequence["team_id"],
                player_id=consequence["player_id"],
                source_key=f"comeback-progress:{consequence['id']}:{restored}",
                importance=1,
            )
            log_player_memory(
                conn, consequence["player_id"], week, season_year,
                "comeback_progress", detail,
            )
        if completed:
            detail = (
                f"{name} recovered the full {restored}-point rehabilitation ceiling "
                f"over {games_since_return} games. The comeback is now part of league history."
            )
            conn.execute(
                """
                INSERT INTO player_arcs
                    (player_id, arc_type, title, summary, started_season, updated_week)
                VALUES (?, 'comeback_complete', 'The Return Is Real', ?, ?, ?)
                ON CONFLICT (player_id) DO UPDATE SET
                    arc_type=EXCLUDED.arc_type, title=EXCLUDED.title,
                    summary=EXCLUDED.summary, updated_week=EXCLUDED.updated_week
                """,
                (consequence["player_id"], detail, season_year, week),
            )
            record_history_event(
                conn,
                season_year,
                week,
                "comeback_complete",
                f"{name} completes the comeback",
                detail,
                team_id=consequence["team_id"],
                player_id=consequence["player_id"],
                source_key=f"comeback-complete:{consequence['id']}",
                importance=2,
            )
        elif settled:
            remaining_loss = max(
                0,
                consequence["skill_loss"] - restored,
            )
            detail = (
                f"{name}'s comeback settled after {games_since_return} games with "
                f"{remaining_loss} permanent rating point"
                f"{'s' if remaining_loss != 1 else ''} still lost."
            )
            conn.execute(
                """
                INSERT INTO player_arcs
                    (player_id, arc_type, title, summary, started_season, updated_week)
                VALUES (?, 'post_injury_new_normal', 'The New Normal', ?, ?, ?)
                ON CONFLICT (player_id) DO UPDATE SET
                    arc_type=EXCLUDED.arc_type, title=EXCLUDED.title,
                    summary=EXCLUDED.summary, updated_week=EXCLUDED.updated_week
                """,
                (consequence["player_id"], detail, season_year, week),
            )
            record_history_event(
                conn,
                season_year,
                week,
                "comeback_settled",
                f"{name}'s post-injury future comes into focus",
                detail,
                team_id=consequence["team_id"],
                player_id=consequence["player_id"],
                source_key=f"comeback-settled:{consequence['id']}",
                importance=2,
            )
        updates.append({
            "player_id": consequence["player_id"],
            "status": status,
            "restored": restored,
        })
    return updates


def average_team_morale(conn, team_id):
    row = conn.execute(
        """
        SELECT AVG(latest.morale) AS morale
        FROM (
            SELECT pm.player_id, pm.morale
            FROM player_morale pm
            JOIN players p ON p.id=pm.player_id
            WHERE p.team_id=? AND COALESCE(p.status, 'active')='active'
              AND pm.id=(
                  SELECT pm2.id FROM player_morale pm2
                  WHERE pm2.player_id=pm.player_id
                  ORDER BY pm2.season_year DESC, pm2.week DESC LIMIT 1
              )
        ) latest
        """,
        (team_id,),
    ).fetchone()
    return float(row["morale"]) if row and row["morale"] is not None else 70.0


def _ensure_rivalry(conn, team_a_id, team_b_id):
    team_a_id, team_b_id = _ordered_team_ids(team_a_id, team_b_id)
    row = conn.execute(
        "SELECT * FROM team_rivalries WHERE team_a_id=? AND team_b_id=?",
        (team_a_id, team_b_id),
    ).fetchone()
    if row:
        return dict(row)
    cur = conn.execute(
        """
        INSERT INTO team_rivalries
            (team_a_id, team_b_id, base_intensity, current_intensity,
             last_event)
        VALUES (?, ?, 0.12, 0.12, 'Rivalry begins to form')
        RETURNING id
        """,
        (team_a_id, team_b_id),
    )
    rivalry_id = cur.fetchone()["id"]
    return dict(conn.execute(
        "SELECT * FROM team_rivalries WHERE id=?", (rivalry_id,)
    ).fetchone())


def _rivalry_tier(intensity):
    if intensity >= 0.85:
        return "blood feud"
    if intensity >= 0.68:
        return "fierce"
    if intensity >= 0.48:
        return "heated"
    if intensity >= 0.28:
        return "building"
    return "dormant"


def _refresh_team_rivalry_intensity(conn, team_ids):
    for team_id in set(team_ids):
        row = conn.execute(
            """
            SELECT MAX(current_intensity) AS intensity
            FROM team_rivalries
            WHERE team_a_id=? OR team_b_id=?
            """,
            (team_id, team_id),
        ).fetchone()
        if row and row["intensity"] is not None:
            conn.execute(
                "UPDATE teams SET rivalry_intensity=? WHERE id=?",
                (row["intensity"], team_id),
            )


def _record_rivalry_event(
    conn,
    rivalry,
    season_year,
    week,
    event_type,
    before,
    after,
    detail,
    game_id=None,
    trade_id=None,
):
    conn.execute(
        """
        INSERT INTO rivalry_events
            (rivalry_id, season_year, week, event_type, intensity_before,
             intensity_after, detail, game_id, trade_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            rivalry["id"],
            season_year,
            week,
            event_type,
            before,
            after,
            detail,
            game_id,
            trade_id,
        ),
    )


def cool_rivalries_for_week(conn, week, season_year):
    """Cool inactive rivalries toward their founding or organically earned floor."""
    rows = conn.execute("SELECT * FROM team_rivalries").fetchall()
    changed_team_ids = []
    for raw in rows:
        rivalry = dict(raw)
        if (
            rivalry["last_season"] == season_year
            and rivalry["last_week"] is not None
            and rivalry["last_week"] >= week - 1
        ):
            continue
        before = rivalry["current_intensity"]
        after = max(rivalry["base_intensity"], before - 0.012)
        if after >= before - 0.0001:
            continue
        detail = f"Time without a meaningful meeting cools the rivalry to {_rivalry_tier(after)}."
        conn.execute(
            """
            UPDATE team_rivalries
            SET current_intensity=?, last_event=?, updated_at=datetime('now')
            WHERE id=?
            """,
            (after, detail, rivalry["id"]),
        )
        _record_rivalry_event(
            conn, rivalry, season_year, week, "cooling", before, after, detail
        )
        changed_team_ids.extend((rivalry["team_a_id"], rivalry["team_b_id"]))
    _refresh_team_rivalry_intensity(conn, changed_team_ids)


def record_game_rivalry(conn, game, simulation):
    rivalry = _ensure_rivalry(
        conn, game["home_team_id"], game["away_team_id"]
    )
    before = rivalry["current_intensity"]
    margin = abs(simulation["home_score"] - simulation["away_score"])
    home_won = simulation["home_score"] > simulation["away_score"]
    winner_probability = (
        simulation["home_win_probability"]
        if home_won
        else 1.0 - simulation["home_win_probability"]
    )
    playoff = bool(game.get("playoff_series_id"))
    delta = 0.014
    reasons = []

    if margin <= 3:
        delta += 0.075
        reasons.append("a one-possession finish")
    elif margin <= 7:
        delta += 0.045
        reasons.append("a close finish")
    elif margin >= 22 and not playoff:
        delta -= 0.035
        reasons.append("a one-sided result")
    elif margin >= 15 and not playoff:
        delta -= 0.012
        reasons.append("a comfortable result")

    if winner_probability < 0.35:
        delta += 0.055
        reasons.append("an upset")

    series_type = None
    if playoff:
        series = conn.execute(
            "SELECT series_type FROM playoff_series WHERE id=?",
            (game["playoff_series_id"],),
        ).fetchone()
        series_type = series["series_type"] if series else "playoff"
        playoff_bonus = {
            "semifinal": 0.095,
            "third_place": 0.055,
            "finals": 0.135,
        }.get(series_type, 0.08)
        delta += playoff_bonus
        reasons.append(f"a {series_type.replace('_', ' ')} meeting")

    if rivalry["meetings"] and rivalry["meetings"] % 4 == 0:
        delta += 0.012
        reasons.append("accumulated history")

    after = max(
        rivalry["base_intensity"],
        min(1.0, before + delta),
    )
    before_tier = _rivalry_tier(before)
    after_tier = _rivalry_tier(after)
    event_type = "playoff_meeting" if playoff else (
        "rivalry_cools" if after < before else "game_meeting"
    )
    detail = (
        f"The matchup moves from {before_tier} to {after_tier}"
        f" after {', '.join(reasons) if reasons else 'another meeting'}."
    )
    conn.execute(
        """
        UPDATE team_rivalries
        SET current_intensity=?, meetings=meetings+1,
            close_games=close_games+?,
            playoff_meetings=playoff_meetings+?,
            last_season=?, last_week=?, last_event=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (
            after,
            1 if margin <= 7 else 0,
            1 if playoff else 0,
            game["season_year"],
            game["week"],
            detail,
            rivalry["id"],
        ),
    )
    _record_rivalry_event(
        conn,
        rivalry,
        game["season_year"],
        game["week"],
        event_type,
        before,
        after,
        detail,
        game_id=game["id"],
    )
    _refresh_team_rivalry_intensity(
        conn, (game["home_team_id"], game["away_team_id"])
    )

    if before_tier != after_tier and after >= 0.48:
        teams = conn.execute(
            """
            SELECT id, city || ' ' || name AS name
            FROM teams WHERE id IN (?, ?)
            ORDER BY id
            """,
            (rivalry["team_a_id"], rivalry["team_b_id"]),
        ).fetchall()
        record_history_event(
            conn,
            game["season_year"],
            game["week"],
            "rivalry_escalation",
            f"{teams[0]['name']}–{teams[1]['name']} rivalry turns {after_tier}",
            detail,
            team_id=teams[0]["id"],
            game_id=game["id"],
            source_key=f"rivalry-tier:{rivalry['id']}:{after_tier}:{game['season_year']}:{game['week']}",
            importance=2 if after >= 0.68 else 1,
        )
    return after


def record_trade_rivalry(
    conn,
    team_a_id,
    team_b_id,
    season_year,
    week,
    trade_id,
    star_involved=False,
):
    rivalry = _ensure_rivalry(conn, team_a_id, team_b_id)
    before = rivalry["current_intensity"]
    delta = 0.075 + (0.045 if star_involved else 0.0)
    after = min(1.0, before + delta)
    detail = (
        f"A {'star-level ' if star_involved else ''}trade adds front-office history "
        f"and pushes the rivalry from {_rivalry_tier(before)} to {_rivalry_tier(after)}."
    )
    conn.execute(
        """
        UPDATE team_rivalries
        SET current_intensity=?, trade_count=trade_count+1,
            last_season=?, last_week=?, last_event=?,
            updated_at=datetime('now')
        WHERE id=?
        """,
        (after, season_year, week, detail, rivalry["id"]),
    )
    _record_rivalry_event(
        conn,
        rivalry,
        season_year,
        week,
        "trade",
        before,
        after,
        detail,
        trade_id=trade_id,
    )
    _refresh_team_rivalry_intensity(conn, (team_a_id, team_b_id))
    record_history_event(
        conn,
        season_year,
        week,
        "rivalry_trade",
        "A trade adds fuel to a league rivalry",
        detail,
        team_id=team_a_id,
        source_key=f"rivalry-trade:{trade_id}",
        importance=2 if star_involved else 1,
    )
    return after


def _record_before_game(conn, team_id, season_year, week, game_id):
    row = conn.execute(
        """
        SELECT
            SUM(CASE
                WHEN (g.home_team_id=? AND g.home_score>g.away_score)
                  OR (g.away_team_id=? AND g.away_score>g.home_score)
                THEN 1 ELSE 0 END) AS wins,
            SUM(CASE
                WHEN (g.home_team_id=? AND g.home_score<g.away_score)
                  OR (g.away_team_id=? AND g.away_score<g.home_score)
                THEN 1 ELSE 0 END) AS losses
        FROM games g
        WHERE g.season_year=? AND g.played=1
          AND g.playoff_series_id IS NULL
          AND (g.home_team_id=? OR g.away_team_id=?)
          AND (g.week<? OR (g.week=? AND g.id<?))
        """,
        (
            team_id, team_id, team_id, team_id, season_year,
            team_id, team_id, week, week, game_id,
        ),
    ).fetchone()
    return (int(row["wins"] or 0), int(row["losses"] or 0))


def _form_before_game(conn, team_id, season_year, week, game_id):
    rows = conn.execute(
        """
        SELECT home_team_id, away_team_id, home_score, away_score
        FROM games
        WHERE season_year=? AND played=1
          AND (home_team_id=? OR away_team_id=?)
          AND (week<? OR (week=? AND id<?))
        ORDER BY week DESC, id DESC LIMIT 3
        """,
        (season_year, team_id, team_id, week, week, game_id),
    ).fetchall()
    if not rows:
        return "opening night", 0, 0
    results = []
    for row in rows:
        won = (
            row["home_team_id"] == team_id
            and row["home_score"] > row["away_score"]
        ) or (
            row["away_team_id"] == team_id
            and row["away_score"] > row["home_score"]
        )
        results.append("W" if won else "L")
    wins = results.count("W")
    losses = results.count("L")
    if len(set(results)) == 1:
        label = f"{len(results)}-game {'winning' if results[0] == 'W' else 'losing'} streak"
    else:
        label = f"{wins}-{losses} over the last {len(results)}"
    return label, wins, losses


def _pregame_star(conn, team_id, season_year, week, game_id):
    row = conn.execute(
        """
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               ROUND(AVG(pgs.points), 1) AS ppg
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        WHERE pgs.team_id=? AND g.season_year=?
          AND (g.week<? OR (g.week=? AND g.id<?))
        GROUP BY p.id
        ORDER BY ppg DESC, p.skill_rating DESC LIMIT 1
        """,
        (team_id, season_year, week, week, game_id),
    ).fetchone()
    if row:
        return dict(row)
    row = conn.execute(
        """
        SELECT id, first_name || ' ' || last_name AS player,
               skill_rating
        FROM players
        WHERE team_id=? AND COALESCE(status, 'active')='active'
        ORDER BY skill_rating DESC LIMIT 1
        """,
        (team_id,),
    ).fetchone()
    return dict(row) if row else None


def build_pregame_broadcast(conn, game):
    """Create a factual broadcast setup from data available before tipoff."""
    home = conn.execute(
        """
        SELECT id, city || ' ' || name AS name, abbreviation,
               team_archetype, reputation, signature_trait, pressure_label
        FROM teams WHERE id=?
        """,
        (game["home_team_id"],),
    ).fetchone()
    away = conn.execute(
        """
        SELECT id, city || ' ' || name AS name, abbreviation,
               team_archetype, reputation, signature_trait, pressure_label
        FROM teams WHERE id=?
        """,
        (game["away_team_id"],),
    ).fetchone()
    home = dict(home)
    away = dict(away)
    home_record = _record_before_game(
        conn, home["id"], game["season_year"], game["week"], game["id"]
    )
    away_record = _record_before_game(
        conn, away["id"], game["season_year"], game["week"], game["id"]
    )
    home_form = _form_before_game(
        conn, home["id"], game["season_year"], game["week"], game["id"]
    )
    away_form = _form_before_game(
        conn, away["id"], game["season_year"], game["week"], game["id"]
    )
    home_coach = get_active_coach(conn, home["id"])
    away_coach = get_active_coach(conn, away["id"])
    home_star = _pregame_star(
        conn, home["id"], game["season_year"], game["week"], game["id"]
    )
    away_star = _pregame_star(
        conn, away["id"], game["season_year"], game["week"], game["id"]
    )
    rivalry = conn.execute(
        """
        SELECT tr.current_intensity, tr.meetings, tr.close_games,
               tr.playoff_meetings, tr.last_event, rn.name AS fan_name
        FROM team_rivalries tr
        LEFT JOIN rivalry_names rn
          ON rn.team_a_id=tr.team_a_id AND rn.team_b_id=tr.team_b_id
         AND rn.status='active'
        WHERE tr.team_a_id=? AND tr.team_b_id=?
        """,
        _ordered_team_ids(home["id"], away["id"]),
    ).fetchone()
    rivalry = dict(rivalry) if rivalry else None
    revenge = conn.execute(
        """
        SELECT p.first_name || ' ' || p.last_name AS player,
               old.city || ' ' || old.name AS former_team
        FROM player_relationships pr
        JOIN players p ON p.id=pr.player_id
        JOIN teams old ON old.id=pr.origin_team_id
        WHERE pr.relationship_type='former_team' AND pr.status='active'
          AND ((p.team_id=? AND pr.origin_team_id=?)
            OR (p.team_id=? AND pr.origin_team_id=?))
        ORDER BY pr.intensity DESC LIMIT 1
        """,
        (home["id"], away["id"], away["id"], home["id"]),
    ).fetchone()
    injuries = conn.execute(
        """
        SELECT t.abbreviation, p.first_name || ' ' || p.last_name AS player,
               i.severity
        FROM player_injuries i
        JOIN players p ON p.id=i.player_id
        JOIN teams t ON t.id=p.team_id
        WHERE p.team_id IN (?, ?) AND i.season_year=? AND i.status='active'
          AND i.week_start<=? AND i.expected_return_week>=?
        ORDER BY i.skill_penalty DESC LIMIT 3
        """,
        (
            home["id"], away["id"], game["season_year"],
            game["week"], game["week"],
        ),
    ).fetchall()

    rivalry_hot = rivalry and rivalry["current_intensity"] >= 0.48
    if revenge:
        headline = f"{revenge['player']} faces former team as {away['abbreviation']} visits {home['abbreviation']}"
    elif rivalry_hot:
        rivalry_name = rivalry["fan_name"] or f"{away['abbreviation']}-{home['abbreviation']}"
        headline = f"{rivalry_name} returns with the temperature rising"
    elif home_form[1] >= 2 or away_form[1] >= 2:
        hotter = home if home_form[1] >= away_form[1] else away
        headline = f"{hotter['name']} brings momentum into a clash of identities"
    else:
        headline = f"{away['team_archetype']} meets {home['team_archetype']}"

    home_strategy = (
        home_coach["strategy"].replace("_", " ")
        if home_coach else "balanced"
    )
    away_strategy = (
        away_coach["strategy"].replace("_", " ")
        if away_coach else "balanced"
    )
    storyline = (
        f"{away['name']} ({away_record[0]}-{away_record[1]}) arrives as "
        f"{away['team_archetype'].lower()}, while {home['name']} "
        f"({home_record[0]}-{home_record[1]}) carries the expectations of "
        f"{home['team_archetype'].lower()}. The tactical question is whether "
        f"{away_strategy} can disrupt {home_strategy} on the home floor."
    )
    cards = [
        {
            "label": "The stakes",
            "title": f"{away['abbreviation']} {away_record[0]}-{away_record[1]} · {home['abbreviation']} {home_record[0]}-{home_record[1]}",
            "detail": (
                f"{away['abbreviation']} enters on {away_form[0]}; "
                f"{home['abbreviation']} is on {home_form[0]}."
            ),
        },
        {
            "label": "Stars to watch",
            "title": (
                f"{away_star['player'] if away_star else away['abbreviation']} vs "
                f"{home_star['player'] if home_star else home['abbreviation']}"
            ),
            "detail": (
                f"{away_star['player']} leads {away['abbreviation']}"
                + (
                    f" at {away_star['ppg']:.1f} PPG"
                    if away_star and away_star.get("ppg") is not None else ""
                )
                + f"; {home_star['player']} leads {home['abbreviation']}"
                + (
                    f" at {home_star['ppg']:.1f} PPG"
                    if home_star and home_star.get("ppg") is not None else ""
                )
                + "."
            ) if away_star and home_star else "The primary creators will define the matchup.",
        },
        {
            "label": "Pressure point",
            "title": (
                rivalry["fan_name"] if rivalry and rivalry["fan_name"]
                else "Identity under pressure"
            ),
            "detail": (
                f"{rivalry['meetings']} prior meetings, including "
                f"{rivalry['close_games']} close finishes and "
                f"{rivalry['playoff_meetings']} playoff games."
                if rivalry_hot else
                f"{away['pressure_label']} {home['pressure_label']}"
            ),
        },
    ]
    if revenge:
        cards[2] = {
            "label": "Revenge watch",
            "title": f"{revenge['player']} vs {revenge['former_team']}",
            "detail": "A former-team relationship gives this matchup permanent personal history.",
        }
    elif injuries:
        cards[2] = {
            "label": "Availability",
            "title": f"{len(injuries)} active injury concern{'s' if len(injuries) != 1 else ''}",
            "detail": "; ".join(
                f"{row['abbreviation']} {row['player']} ({row['severity']})"
                for row in injuries
            ) + ".",
        }
    return {
        "headline": headline,
        "storyline": storyline,
        "cards": cards,
    }


def persist_pregame_broadcast(conn, game, generated_before_tip=True):
    broadcast = build_pregame_broadcast(conn, game)
    conn.execute(
        """
        INSERT INTO game_broadcasts
            (game_id, pregame_headline, pregame_storyline,
             pregame_cards_json, generated_before_tip)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (game_id) DO UPDATE SET
            pregame_headline=EXCLUDED.pregame_headline,
            pregame_storyline=EXCLUDED.pregame_storyline,
            pregame_cards_json=EXCLUDED.pregame_cards_json,
            generated_before_tip=CASE
                WHEN game_broadcasts.generated_before_tip=1
                  OR EXCLUDED.generated_before_tip=1 THEN 1
                ELSE 0
            END,
            updated_at=datetime('now')
        """,
        (
            game["id"],
            broadcast["headline"],
            broadcast["storyline"],
            json.dumps(broadcast["cards"]),
            1 if generated_before_tip else 0,
        ),
    )
    return broadcast


def build_quarter_recaps(game, home_quarters, away_quarters):
    home_name = game["home_name"]
    away_name = game["away_name"]
    recaps = []
    home_total = away_total = 0
    previous_leader = None
    for index, (home_points, away_points) in enumerate(
        zip(home_quarters, away_quarters), start=1
    ):
        prior_home, prior_away = home_total, away_total
        home_total += home_points
        away_total += away_points
        quarter_winner = (
            home_name if home_points > away_points
            else away_name if away_points > home_points
            else None
        )
        leader = (
            home_name if home_total > away_total
            else away_name if away_total > home_total
            else None
        )
        margin = abs(home_total - away_total)
        if index == 1:
            if quarter_winner:
                text = (
                    f"{quarter_winner} set the opening tone by winning the first "
                    f"quarter {max(home_points, away_points)}-{min(home_points, away_points)}"
                )
            else:
                text = f"The teams traded control through a {home_points}-{away_points} opening quarter"
            text += (
                f", leaving {leader} ahead {home_total}-{away_total}."
                if leader else f", leaving the game tied {home_total}-{away_total}."
            )
        elif index == 2:
            if previous_leader and leader and previous_leader != leader:
                action = f"{leader} flipped the game before halftime"
            elif quarter_winner:
                action = f"{quarter_winner} won the second quarter {max(home_points, away_points)}-{min(home_points, away_points)}"
            else:
                action = f"Neither side separated in a {home_points}-{away_points} second quarter"
            text = action + (
                f", sending {leader} to halftime up {margin} at {home_total}-{away_total}."
                if leader else f", sending the game to halftime tied {home_total}-{away_total}."
            )
        elif index == 3:
            prior_margin = abs(prior_home - prior_away)
            if previous_leader and leader and previous_leader != leader:
                action = f"{leader} seized the lead in the third"
            elif quarter_winner and previous_leader and quarter_winner != previous_leader and margin < prior_margin:
                action = f"{quarter_winner} cut into the deficit with a {max(home_points, away_points)}-{min(home_points, away_points)} third quarter"
            elif quarter_winner:
                action = f"{quarter_winner} controlled the third quarter {max(home_points, away_points)}-{min(home_points, away_points)}"
            else:
                action = f"The third quarter finished even at {home_points}-{away_points}"
            text = action + (
                f", and {leader} carried a {home_total}-{away_total} lead into the fourth."
                if leader else f", producing a {home_total}-{away_total} tie entering the fourth."
            )
        else:
            winner = home_name if home_total > away_total else away_name
            entering_leader = previous_leader
            if entering_leader and entering_leader != winner:
                action = f"{winner} completed the comeback in the fourth quarter"
            elif margin <= 5:
                action = f"{winner} held on through a one-possession finish"
            elif quarter_winner == winner:
                action = f"{winner} closed the game by taking the fourth quarter {max(home_points, away_points)}-{min(home_points, away_points)}"
            else:
                action = f"{winner} protected the advantage despite losing the final quarter"
            text = f"{action}, securing the {home_total}-{away_total} final."
        recaps.append({
            "quarter": index,
            "home_points": home_points,
            "away_points": away_points,
            "home_total": home_total,
            "away_total": away_total,
            "text": text,
        })
        previous_leader = leader
    return recaps


def persist_game_explanation(conn, game, simulation, home_quarters, away_quarters):
    home_won = simulation["home_score"] > simulation["away_score"]
    winner_id = game["home_team_id"] if home_won else game["away_team_id"]
    loser_id = game["away_team_id"] if home_won else game["home_team_id"]
    winner_name = game["home_name"] if home_won else game["away_name"]
    loser_name = game["away_name"] if home_won else game["home_name"]
    winner_abbr = game["home_abbr"] if home_won else game["away_abbr"]

    quarter_margins = [
        (home_quarters[i] - away_quarters[i]) * (1 if home_won else -1)
        for i in range(4)
    ]
    decisive_quarter = max(range(4), key=lambda i: quarter_margins[i]) + 1
    decisive_margin = quarter_margins[decisive_quarter - 1]
    winner_turnovers = simulation["home_turnovers"] if home_won else simulation["away_turnovers"]
    loser_turnovers = simulation["away_turnovers"] if home_won else simulation["home_turnovers"]
    turning_point = (
        f"{winner_name} created a {decisive_margin:+d} margin in the "
        f"{['first', 'second', 'third', 'fourth'][decisive_quarter - 1]} quarter"
    )
    if loser_turnovers - winner_turnovers >= 4:
        turning_point += f" while winning the turnover battle {winner_turnovers}-{loser_turnovers}."
    else:
        turning_point += "."

    standings = conn.execute(
        "SELECT wins, losses FROM standings WHERE team_id=? AND season_year=?",
        (winner_id, game["season_year"]),
    ).fetchone()
    standings_impact = (
        f"{winner_abbr} moves to {standings['wins']}-{standings['losses']}."
        if standings
        else "Postseason position changed with the result."
    )

    factors = simulation["home_factors"] if home_won else simulation["away_factors"]
    edge = max(factors, key=lambda item: abs(item["value"])) if factors else None
    cause = edge["label"].lower() if edge else "execution"
    factual_recap = (
        f"{winner_name} beat {loser_name} {max(simulation['home_score'], simulation['away_score'])}-"
        f"{min(simulation['home_score'], simulation['away_score'])}. "
        f"The result turned on {cause}, and {turning_point[0].lower() + turning_point[1:]}"
    )

    coach = get_active_coach(conn, winner_id)
    coach_quote = None
    if coach:
        coach_quote = (
            f"We trusted our {coach['strategy'].replace('_', ' ')} identity, "
            "and the group stayed connected when the game tightened."
        )

    conn.execute(
        """
        INSERT INTO game_explanations
            (game_id, expected_margin, home_win_probability, favorite_team_id,
             decisive_quarter, turning_point, strategy_matchup, key_factors_json,
             factual_recap, standings_impact, coach_quote)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (game_id) DO UPDATE SET
            expected_margin=EXCLUDED.expected_margin,
            home_win_probability=EXCLUDED.home_win_probability,
            favorite_team_id=EXCLUDED.favorite_team_id,
            decisive_quarter=EXCLUDED.decisive_quarter,
            turning_point=EXCLUDED.turning_point,
            strategy_matchup=EXCLUDED.strategy_matchup,
            key_factors_json=EXCLUDED.key_factors_json,
            factual_recap=EXCLUDED.factual_recap,
            standings_impact=EXCLUDED.standings_impact,
            coach_quote=EXCLUDED.coach_quote
        """,
        (
            game["id"],
            simulation["expected_margin"],
            simulation["home_win_probability"],
            game["home_team_id"] if simulation["expected_margin"] >= 0 else game["away_team_id"],
            decisive_quarter,
            turning_point,
            simulation["strategy_matchup"],
            json.dumps(
                {
                    "home": simulation["home_factors"],
                    "away": simulation["away_factors"],
                    "home_injuries": simulation["home_injuries"],
                    "away_injuries": simulation["away_injuries"],
                }
            ),
            factual_recap,
            standings_impact,
            coach_quote,
        ),
    )
    quarter_recaps = build_quarter_recaps(game, home_quarters, away_quarters)
    existing_broadcast = conn.execute(
        "SELECT game_id FROM game_broadcasts WHERE game_id=?",
        (game["id"],),
    ).fetchone()
    if not existing_broadcast:
        persist_pregame_broadcast(conn, game, generated_before_tip=False)
    conn.execute(
        """
        UPDATE game_broadcasts
        SET quarter_recaps_json=?, updated_at=datetime('now')
        WHERE game_id=?
        """,
        (json.dumps(quarter_recaps), game["id"]),
    )
    for team_id, prefix in (
        (game["home_team_id"], "home"),
        (game["away_team_id"], "away"),
    ):
        conn.execute(
            """
            INSERT INTO team_game_stats
                (game_id, team_id, possessions, turnovers, expected_points,
                 strength_score, chemistry_used, morale_used, coach_effect,
                 injury_effect, clutch_effect)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (game_id, team_id) DO UPDATE SET
                possessions=EXCLUDED.possessions,
                turnovers=EXCLUDED.turnovers,
                expected_points=EXCLUDED.expected_points,
                strength_score=EXCLUDED.strength_score,
                chemistry_used=EXCLUDED.chemistry_used,
                morale_used=EXCLUDED.morale_used,
                coach_effect=EXCLUDED.coach_effect,
                injury_effect=EXCLUDED.injury_effect,
                clutch_effect=EXCLUDED.clutch_effect
            """,
            (
                game["id"],
                team_id,
                simulation["possessions"],
                simulation[f"{prefix}_turnovers"],
                simulation[f"{prefix}_expected_points"],
                simulation[f"{prefix}_strength"],
                simulation[f"{prefix}_chemistry"],
                simulation[f"{prefix}_morale"],
                simulation[f"{prefix}_coach_effect"],
                simulation[f"{prefix}_injury_effect"],
                simulation[f"{prefix}_clutch_effect"],
            ),
        )

    margin = abs(simulation["home_score"] - simulation["away_score"])
    if margin <= 3:
        record_history_event(
            conn,
            game["season_year"],
            game["week"],
            "classic_game",
            f"{winner_name} survives {loser_name}",
            factual_recap,
            team_id=winner_id,
            game_id=game["id"],
            source_key=f"classic-game:{game['id']}",
            importance=2,
        )


def update_player_arcs(conn, week, season_year):
    players = conn.execute(
        """
        SELECT p.id, p.first_name, p.last_name, p.age, p.skill_rating,
               pp.loyalty,
               COALESCE(AVG(pgs.points), 0) AS ppg,
               COUNT(DISTINCT pr.origin_team_id) AS former_teams,
               MAX(CASE WHEN ic.comeback_status='active' THEN 1 ELSE 0 END)
                   AS active_comeback
        FROM players p
        LEFT JOIN player_personalities pp ON pp.player_id=p.id
        LEFT JOIN player_game_stats pgs ON pgs.player_id=p.id
        LEFT JOIN games g ON g.id=pgs.game_id AND g.season_year=?
        LEFT JOIN player_relationships pr ON pr.player_id=p.id
             AND pr.relationship_type='former_team'
        LEFT JOIN injury_consequences ic ON ic.player_id=p.id
        WHERE COALESCE(p.status, 'active')='active'
        GROUP BY p.id, pp.loyalty
        """,
        (season_year,),
    ).fetchall()
    for row in players:
        player = dict(row)
        name = f"{player['first_name']} {player['last_name']}"
        if player["active_comeback"]:
            continue
        if player["former_teams"] >= 2:
            arc = ("journeyman", "Still Searching for Home", f"{name}'s career now carries history in several locker rooms.")
        elif player["age"] <= 25 and (player["skill_rating"] >= 82 or player["ppg"] >= 21):
            arc = ("breakout_star", "The Breakout", f"{name} is becoming too important to describe as a prospect.")
        elif player["age"] >= 32 and player["skill_rating"] < 76:
            arc = ("declining_veteran", "Fighting the Clock", f"{name} is adjusting as the game asks different questions of him.")
        elif player["age"] >= 29 and (player["loyalty"] or 0) >= 0.76 and player["former_teams"] == 0:
            arc = ("franchise_icon", "The Face of the Franchise", f"{name} has become part of the team's identity, not merely its roster.")
        else:
            continue
        conn.execute(
            """
            INSERT INTO player_arcs
                (player_id, arc_type, title, summary, started_season, updated_week)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (player_id) DO UPDATE SET
                arc_type=EXCLUDED.arc_type, title=EXCLUDED.title,
                summary=EXCLUDED.summary, updated_week=EXCLUDED.updated_week
            """,
            (player["id"], arc[0], arc[1], arc[2], season_year, week),
        )


def _performance_value_sql():
    return (
        "pgs.points + pgs.rebounds*0.75 + pgs.assists*0.65 "
        "+ pgs.steals*1.6 + pgs.blocks*1.35"
    )


def create_weekly_awards(conn, week, season_year):
    winner = conn.execute(
        f"""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation, pgs.points, pgs.rebounds, pgs.assists,
               ({_performance_value_sql()}) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        JOIN teams t ON t.id=pgs.team_id
        WHERE g.season_year=? AND g.week=?
        ORDER BY value DESC LIMIT 1
        """,
        (season_year, week),
    ).fetchone()
    if winner:
        detail = (
            f"{winner['points']} points, {winner['rebounds']} rebounds, "
            f"{winner['assists']} assists for {winner['abbreviation']}."
        )
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, ?, 'player_of_week', 'player', ?, 'Player of the Week', ?)
            ON CONFLICT DO NOTHING
            """,
            (season_year, week, winner["id"], detail),
        )
        record_history_event(
            conn,
            season_year,
            week,
            "weekly_award",
            f"{winner['player']} named Player of the Week",
            detail,
            player_id=winner["id"],
            source_key=f"pow:{season_year}:{week}",
        )

    fan_named_award = conn.execute(
        """
        SELECT label FROM fan_labels
        WHERE label_type='weekly_effort_award_name' AND status='active'
        ORDER BY id DESC LIMIT 1
        """
    ).fetchone()
    if fan_named_award:
        effort = conn.execute(
            """
            SELECT p.id, p.first_name || ' ' || p.last_name AS player,
                   t.abbreviation, pgs.rebounds, pgs.steals, pgs.blocks,
                   (pgs.rebounds*1.2 + pgs.steals*2.0 + pgs.blocks*2.0) AS effort
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=pgs.team_id
            WHERE g.season_year=? AND g.week=?
            ORDER BY effort DESC, pgs.rebounds DESC, pgs.steals DESC
            LIMIT 1
            """,
            (season_year, week),
        ).fetchone()
        if effort:
            detail = (
                f"{effort['rebounds']} rebounds, {effort['steals']} steals, "
                f"and {effort['blocks']} blocks for {effort['abbreviation']}."
            )
            conn.execute(
                """
                INSERT INTO awards
                    (season_year, week, award_type, entity_type, entity_id, label, detail)
                VALUES (?, ?, 'fan_named_effort', 'player', ?, ?, ?)
                ON CONFLICT DO NOTHING
                """,
                (
                    season_year,
                    week,
                    effort["id"],
                    fan_named_award["label"],
                    detail,
                ),
            )


def record_weekly_milestones(conn, week, season_year):
    rows = conn.execute(
        """
        SELECT g.id AS game_id, p.id AS player_id,
               p.first_name || ' ' || p.last_name AS player,
               p.team_id, pgs.points, pgs.rebounds, pgs.assists
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        WHERE g.season_year=? AND g.week=?
          AND (pgs.points>=40 OR pgs.rebounds>=20 OR pgs.assists>=15)
        """,
        (season_year, week),
    ).fetchall()
    for row in rows:
        detail = f"{row['points']} PTS, {row['rebounds']} REB, {row['assists']} AST."
        record_history_event(
            conn,
            season_year,
            week,
            "career_milestone",
            f"{row['player']} delivers a landmark performance",
            detail,
            team_id=row["team_id"],
            player_id=row["player_id"],
            game_id=row["game_id"],
            source_key=f"milestone:{row['game_id']}:{row['player_id']}",
            importance=2,
        )


def _record_candidates(conn, scope, stat_key):
    if scope == "single_game":
        rows = conn.execute(
            f"""
            SELECT p.id AS player_id, p.team_id, p.first_name || ' ' ||
                   p.last_name AS player, t.abbreviation,
                   pgs.{stat_key} AS value, g.season_year, g.week,
                   g.id AS game_id
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=pgs.team_id
            WHERE g.played=1
            ORDER BY pgs.{stat_key} DESC, g.season_year, g.week, g.id
            """
        ).fetchall()
    elif scope == "season":
        rows = conn.execute(
            f"""
            SELECT p.id AS player_id, p.team_id,
                   p.first_name || ' ' || p.last_name AS player,
                   t.abbreviation, SUM(pgs.{stat_key}) AS value,
                   g.season_year, MAX(g.week) AS week, NULL AS game_id
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=p.team_id
            WHERE g.played=1
            GROUP BY p.id, p.team_id, t.abbreviation, g.season_year
            ORDER BY value DESC, g.season_year, p.id
            """
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT p.id AS player_id, p.team_id,
                   p.first_name || ' ' || p.last_name AS player,
                   t.abbreviation, SUM(pgs.{stat_key}) AS value,
                   MAX(g.season_year) AS season_year,
                   MAX(g.week) AS week, NULL AS game_id
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=p.team_id
            WHERE g.played=1
            GROUP BY p.id, p.team_id, t.abbreviation
            ORDER BY value DESC, p.id
            """
        ).fetchall()
    if not rows:
        return []
    top_value = int(rows[0]["value"] or 0)
    return [dict(row) for row in rows if int(row["value"] or 0) == top_value]


def _record_source_key(scope, stat_key, candidate):
    if scope == "single_game":
        suffix = candidate["game_id"]
    elif scope == "season":
        suffix = candidate["season_year"]
    else:
        suffix = "all"
    return (
        f"record:{scope}:{stat_key}:{candidate['player_id']}:{suffix}"
    )


def _record_achievement_detail(scope, stat_label, candidate, previous_value):
    context = (
        f"in Week {candidate['week']} of the {candidate['season_year']} season"
        if scope == "single_game"
        else f"during the {candidate['season_year']} season"
        if scope == "season"
        else f"through the {candidate['season_year']} season"
    )
    previous = (
        f", surpassing the previous mark of {previous_value}"
        if previous_value is not None else ""
    )
    return (
        f"{candidate['player']} set the {RECORD_SCOPE_LABELS[scope].lower()} "
        f"{stat_label.lower()} record at {candidate['value']} {context}"
        f"{previous}."
    )


def refresh_record_book(conn, season_year=None, week=0, announce=True):
    """Recalculate formal player records and preserve holder changes."""
    changes = []
    for scope in ("single_game", "season", "career"):
        for stat_key, stat_label in RECORD_STATS:
            candidates = _record_candidates(conn, scope, stat_key)
            if not candidates:
                continue
            candidate_value = int(candidates[0]["value"])
            current = [
                dict(row) for row in conn.execute(
                    """
                    SELECT rbe.*, p.first_name || ' ' || p.last_name AS player
                    FROM record_book_entries rbe
                    JOIN players p ON p.id=rbe.player_id
                    WHERE rbe.scope=? AND rbe.stat_key=? AND rbe.is_current=1
                    """,
                    (scope, stat_key),
                ).fetchall()
            ]
            previous_value = max(
                (int(row["value"]) for row in current),
                default=None,
            )
            current_players = {row["player_id"] for row in current}
            candidate_players = {row["player_id"] for row in candidates}
            value_increased = (
                previous_value is None or candidate_value > previous_value
            )

            if value_increased:
                if previous_value is not None and candidate_players <= current_players:
                    conn.execute(
                        """
                        UPDATE record_book_entries
                        SET is_current=0, updated_at=datetime('now')
                        WHERE scope=? AND stat_key=? AND is_current=1
                          AND player_id NOT IN (
                        """
                        + ",".join("?" for _ in candidate_players)
                        + ")",
                        (scope, stat_key, *sorted(candidate_players)),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE record_book_entries
                        SET is_current=0, updated_at=datetime('now')
                        WHERE scope=? AND stat_key=? AND is_current=1
                        """,
                        (scope, stat_key),
                    )

            for candidate in candidates:
                source_key = _record_source_key(scope, stat_key, candidate)
                existing = conn.execute(
                    "SELECT id, is_current FROM record_book_entries WHERE source_key=?",
                    (source_key,),
                ).fetchone()
                is_new_holder = candidate["player_id"] not in current_players
                if existing:
                    conn.execute(
                        """
                        UPDATE record_book_entries
                        SET team_id=?, value=?, season_year=?, week=?, game_id=?,
                            is_current=1, updated_at=datetime('now')
                        WHERE id=?
                        """,
                        (
                            candidate["team_id"], candidate_value,
                            candidate["season_year"], candidate["week"],
                            candidate["game_id"], existing["id"],
                        ),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO record_book_entries
                            (scope, stat_key, label, player_id, team_id, value,
                             season_year, week, game_id, previous_value,
                             is_current, source_key)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                        """,
                        (
                            scope, stat_key,
                            f"{RECORD_SCOPE_LABELS[scope]} {stat_label}",
                            candidate["player_id"], candidate["team_id"],
                            candidate_value, candidate["season_year"],
                            candidate["week"], candidate["game_id"],
                            previous_value, source_key,
                        ),
                    )

                should_announce = (
                    announce
                    and previous_value is not None
                    and (
                        (value_increased and is_new_holder)
                        or (candidate_value == previous_value and is_new_holder)
                    )
                )
                if should_announce:
                    tied = candidate_value == previous_value
                    event_type = "record_tied" if tied else "record_broken"
                    verb = "ties" if tied else "breaks"
                    detail = (
                        f"{candidate['player']} tied the "
                        f"{RECORD_SCOPE_LABELS[scope].lower()} {stat_label.lower()} "
                        f"record at {candidate_value}."
                        if tied else
                        _record_achievement_detail(
                            scope, stat_label, candidate, previous_value
                        )
                    )
                    record_history_event(
                        conn,
                        candidate["season_year"] or season_year or 0,
                        candidate["week"] or week,
                        event_type,
                        (
                            f"{candidate['player']} {verb} the "
                            f"{RECORD_SCOPE_LABELS[scope].lower()} "
                            f"{stat_label.lower()} record"
                        ),
                        detail,
                        team_id=candidate["team_id"],
                        player_id=candidate["player_id"],
                        game_id=candidate["game_id"],
                        source_key=(
                            f"record-event:{scope}:{stat_key}:"
                            f"{candidate['player_id']}:{candidate_value}:"
                            f"{candidate['season_year']}:{candidate['game_id'] or 0}"
                        ),
                        importance=2,
                    )
                    changes.append({
                        "scope": scope,
                        "stat_key": stat_key,
                        "player_id": candidate["player_id"],
                        "value": candidate_value,
                        "tied": tied,
                    })

            conn.execute(
                """
                UPDATE record_book_entries
                SET is_current=0, updated_at=datetime('now')
                WHERE scope=? AND stat_key=? AND is_current=1
                  AND value<?
                """,
                (scope, stat_key, candidate_value),
            )
    return changes


def register_draft_profile(
    conn,
    player_id,
    team_id,
    draft_year,
    pick_number,
    initial_skill,
):
    summary = (
        f"Selected No. {pick_number} in the {draft_year} rookie intake "
        f"with an initial rating of {initial_skill}. Evaluation is still developing."
    )
    conn.execute(
        """
        INSERT INTO draft_profiles
            (player_id, draft_year, team_id, pick_number, initial_skill,
             outcome_label, outcome_summary)
        VALUES (?, ?, ?, ?, ?, 'developing', ?)
        ON CONFLICT (player_id) DO NOTHING
        """,
        (
            player_id, draft_year, team_id, pick_number,
            initial_skill, summary,
        ),
    )


def refresh_draft_outcomes(conn, current_year):
    profiles = conn.execute(
        """
        SELECT dp.*, p.first_name || ' ' || p.last_name AS player,
               p.skill_rating, p.status,
               COUNT(DISTINCT g.season_year) AS seasons,
               COUNT(pgs.id) AS games,
               COALESCE(AVG(pgs.points), 0) AS ppg,
               COALESCE(SUM(pgs.points), 0) AS points
        FROM draft_profiles dp
        JOIN players p ON p.id=dp.player_id
        LEFT JOIN player_game_stats pgs ON pgs.player_id=p.id
        LEFT JOIN games g ON g.id=pgs.game_id
        GROUP BY dp.player_id, dp.draft_year, dp.team_id, dp.pick_number,
                 dp.initial_skill, dp.outcome_label, dp.outcome_summary,
                 dp.evaluated_year, dp.updated_at, p.first_name, p.last_name,
                 p.skill_rating, p.status
        """
    ).fetchall()
    for row in profiles:
        profile = dict(row)
        eligible = (
            current_year - profile["draft_year"] >= 1
            or profile["status"] == "retired"
        )
        if not eligible:
            label = "developing"
            summary = (
                f"{profile['player']} remains early in the evaluation window "
                f"after being selected No. {profile['pick_number']} in "
                f"{profile['draft_year']}."
            )
        else:
            growth = profile["skill_rating"] - profile["initial_skill"]
            if growth >= 8 or profile["ppg"] >= 18:
                label = "draft_steal"
                summary = (
                    f"{profile['player']} has outgrown the No. "
                    f"{profile['pick_number']} slot, improving {growth:+d} rating "
                    f"points and averaging {profile['ppg']:.1f} points."
                )
            elif profile["skill_rating"] >= 80 or profile["ppg"] >= 15:
                label = "franchise_piece"
                summary = (
                    f"{profile['player']} has become a franchise-level return "
                    f"from the {profile['draft_year']} class."
                )
            elif (
                profile["status"] == "retired"
                or profile["games"] < max(8, int(profile["seasons"] or 1) * 5)
                or (growth <= -2 and profile["ppg"] < 8)
            ):
                label = "draft_bust"
                summary = (
                    f"The No. {profile['pick_number']} selection has not met "
                    f"expectations: {profile['games']} games, "
                    f"{profile['ppg']:.1f} points per game, and {growth:+d} "
                    "rating growth."
                )
            else:
                label = "rotation_player"
                summary = (
                    f"{profile['player']} has settled into a useful rotation role "
                    f"from the {profile['draft_year']} class."
                )
        conn.execute(
            """
            UPDATE draft_profiles
            SET outcome_label=?, outcome_summary=?, evaluated_year=?,
                updated_at=datetime('now')
            WHERE player_id=?
            """,
            (
                label, summary,
                current_year if label != "developing" else None,
                profile["player_id"],
            ),
        )


def refresh_playoff_run_summaries(conn, season_year):
    teams = conn.execute(
        """
        SELECT DISTINCT team_id FROM (
            SELECT team_a_id AS team_id FROM playoff_series WHERE season_year=?
            UNION
            SELECT team_b_id AS team_id FROM playoff_series WHERE season_year=?
        ) playoff_teams
        """,
        (season_year, season_year),
    ).fetchall()
    if not teams:
        return
    finals = conn.execute(
        """
        SELECT * FROM playoff_series
        WHERE season_year=? AND series_type='finals'
        ORDER BY id DESC LIMIT 1
        """,
        (season_year,),
    ).fetchone()
    champion_id = finals["winner_id"] if finals and finals["status"] == "complete" else None
    finalists = (
        {finals["team_a_id"], finals["team_b_id"]} if finals else set()
    )
    for item in teams:
        team_id = item["team_id"]
        team = conn.execute(
            "SELECT city || ' ' || name AS name, abbreviation FROM teams WHERE id=?",
            (team_id,),
        ).fetchone()
        games = conn.execute(
            """
            SELECT g.* FROM games g
            WHERE g.season_year=? AND g.played=1
              AND g.playoff_series_id IS NOT NULL
              AND (g.home_team_id=? OR g.away_team_id=?)
            ORDER BY g.week, g.id
            """,
            (season_year, team_id, team_id),
        ).fetchall()
        wins = losses = close_wins = 0
        for game in games:
            won = (
                game["home_team_id"] == team_id
                and game["home_score"] > game["away_score"]
            ) or (
                game["away_team_id"] == team_id
                and game["away_score"] > game["home_score"]
            )
            if won:
                wins += 1
                if abs(game["home_score"] - game["away_score"]) <= 5:
                    close_wins += 1
            else:
                losses += 1
        star = conn.execute(
            f"""
            SELECT p.id, p.first_name || ' ' || p.last_name AS player,
                   SUM({_performance_value_sql()}) AS value
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            WHERE g.season_year=? AND g.playoff_series_id IS NOT NULL
              AND pgs.team_id=?
            GROUP BY p.id
            ORDER BY value DESC LIMIT 1
            """,
            (season_year, team_id),
        ).fetchone()
        seed = conn.execute(
            """
            SELECT MIN(
                CASE WHEN team_a_id=? THEN seed_a ELSE seed_b END
            ) AS seed
            FROM playoff_series
            WHERE season_year=? AND (team_a_id=? OR team_b_id=?)
            """,
            (team_id, season_year, team_id, team_id),
        ).fetchone()["seed"]
        if team_id == champion_id:
            finish = "Champion"
            legendary = 1
            if losses == 0:
                title = "Perfect Through Pressure"
            elif seed and seed >= 3:
                title = "The Cinderella Crown"
            elif close_wins >= 2:
                title = "The Survival Run"
            else:
                title = "The Championship Run"
        elif team_id in finalists:
            finish = "Finalist"
            legendary = 0
            title = "One Step Short"
        else:
            finish = "Semifinalist"
            legendary = 0
            title = "The Run to the Final Four"
        star_text = (
            f" {star['player']} was the postseason engine."
            if star else ""
        )
        summary = (
            f"{team['name']} finished the {season_year} postseason as "
            f"{finish.lower()} with a {wins}-{losses} playoff record and "
            f"{close_wins} close win{'s' if close_wins != 1 else ''}."
            f"{star_text}"
        )
        conn.execute(
            """
            INSERT INTO playoff_run_summaries
                (season_year, team_id, finish_label, title, summary,
                 playoff_wins, playoff_losses, close_wins,
                 star_player_id, legendary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (season_year, team_id) DO UPDATE SET
                finish_label=EXCLUDED.finish_label,
                title=EXCLUDED.title,
                summary=EXCLUDED.summary,
                playoff_wins=EXCLUDED.playoff_wins,
                playoff_losses=EXCLUDED.playoff_losses,
                close_wins=EXCLUDED.close_wins,
                star_player_id=EXCLUDED.star_player_id,
                legendary=EXCLUDED.legendary
            """,
            (
                season_year, team_id, finish, title, summary,
                wins, losses, close_wins,
                star["id"] if star else None, legendary,
            ),
        )


def refresh_hall_of_fame(conn, induction_year):
    retirees = conn.execute(
        """
        SELECT p.id, p.team_id, p.first_name || ' ' || p.last_name AS player,
               p.retired_season,
               COALESCE(stats.points, 0) AS points,
               COALESCE(stats.rebounds, 0) AS rebounds,
               COALESCE(stats.assists, 0) AS assists,
               COALESCE(honors.major_awards, 0) AS major_awards
        FROM players p
        LEFT JOIN (
            SELECT player_id, SUM(points) AS points,
                   SUM(rebounds) AS rebounds, SUM(assists) AS assists
            FROM player_game_stats GROUP BY player_id
        ) stats ON stats.player_id=p.id
        LEFT JOIN (
            SELECT entity_id AS player_id, COUNT(*) AS major_awards
            FROM awards
            WHERE entity_type='player'
              AND award_type IN ('mvp', 'finals_mvp', 'all_league')
            GROUP BY entity_id
        ) honors ON honors.player_id=p.id
        LEFT JOIN hall_of_fame hof ON hof.player_id=p.id
        WHERE p.status='retired' AND hof.id IS NULL
        """
    ).fetchall()
    for row in retirees:
        player = dict(row)
        championships = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM season_snapshots
            WHERE champion_id=?
            """,
            (player["team_id"],),
        ).fetchone()["count"]
        retired_jersey = conn.execute(
            "SELECT id FROM retired_jerseys WHERE player_id=?",
            (player["id"],),
        ).fetchone()
        qualifies = (
            player["points"] >= 2500
            or player["major_awards"] >= 3
            or (
                player["points"] >= 1500
                and player["major_awards"] >= 1
            )
            or (
                retired_jersey
                and player["points"] >= 1200
            )
        )
        if not qualifies:
            continue
        summary = (
            f"Inducted with {player['points']} points, "
            f"{player['rebounds']} rebounds, {player['assists']} assists, "
            f"{player['major_awards']} major honor"
            f"{'s' if player['major_awards'] != 1 else ''}, and "
            f"{championships} championship"
            f"{'s' if championships != 1 else ''} tied to the primary franchise."
        )
        conn.execute(
            """
            INSERT INTO hall_of_fame
                (player_id, induction_year, primary_team_id, career_points,
                 career_rebounds, career_assists, championships,
                 major_awards, summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (player_id) DO NOTHING
            """,
            (
                player["id"], induction_year, player["team_id"],
                player["points"], player["rebounds"], player["assists"],
                championships, player["major_awards"], summary,
            ),
        )
        record_history_event(
            conn,
            induction_year,
            0,
            "hall_of_fame",
            f"{player['player']} enters the AIBA Hall of Fame",
            summary,
            team_id=player["team_id"],
            player_id=player["id"],
            source_key=f"hall-of-fame:{player['id']}",
            importance=3,
        )


def refresh_franchise_history(conn, current_year):
    teams = conn.execute("SELECT id, city, name FROM teams ORDER BY id").fetchall()
    for team in teams:
        existing = conn.execute(
            """
            SELECT id FROM franchise_events
            WHERE team_id=? AND event_type IN ('founding', 'expansion')
            LIMIT 1
            """,
            (team["id"],),
        ).fetchone()
        if existing:
            continue
        first = conn.execute(
            """
            SELECT MIN(season_year) AS season_year FROM (
                SELECT season_year FROM standings WHERE team_id=?
                UNION ALL
                SELECT season_year FROM games
                WHERE home_team_id=? OR away_team_id=?
            ) seasons
            """,
            (team["id"], team["id"], team["id"]),
        ).fetchone()
        first_year = (
            first["season_year"]
            if first and first["season_year"] is not None
            else current_year
        )
        event_type = "founding" if first_year <= 2026 else "expansion"
        title = (
            "Founding member of the AIBA"
            if event_type == "founding"
            else f"Joined the AIBA in the {first_year} expansion"
        )
        detail = (
            "Part of the original eight-franchise league."
            if event_type == "founding"
            else f"{team['city']} {team['name']} became an AIBA expansion franchise."
        )
        conn.execute(
            """
            INSERT INTO franchise_events
                (team_id, season_year, event_type, title, detail, source_key)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (source_key) DO NOTHING
            """,
            (
                team["id"], first_year, event_type, title, detail,
                f"franchise-entry:{team['id']}",
            ),
        )


def refresh_league_lore(conn, current_year):
    refresh_draft_outcomes(conn, current_year)
    refresh_hall_of_fame(conn, current_year)
    refresh_franchise_history(conn, current_year)
    completed_playoffs = conn.execute(
        """
        SELECT DISTINCT season_year
        FROM playoff_series
        WHERE series_type='finals' AND status='complete'
        """
    ).fetchall()
    for row in completed_playoffs:
        refresh_playoff_run_summaries(conn, row["season_year"])


def _legacy_create_weekly_poll(conn, week, season_year):
    conn.execute(
        "UPDATE polls SET status='closed' WHERE status='open' AND (season_year<? OR (season_year=? AND closes_week<?))",
        (season_year, season_year, week),
    )
    existing = conn.execute(
        "SELECT id FROM polls WHERE season_year=? AND week=? AND poll_type='fan_player_of_week'",
        (season_year, week),
    ).fetchone()
    if existing:
        return existing["id"]
    candidates = conn.execute(
        f"""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation, pgs.points, pgs.rebounds, pgs.assists,
               ({_performance_value_sql()}) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        JOIN teams t ON t.id=pgs.team_id
        WHERE g.season_year=? AND g.week=?
        ORDER BY value DESC LIMIT 4
        """,
        (season_year, week),
    ).fetchall()
    if len(candidates) < 2:
        return None
    cur = conn.execute(
        """
        INSERT INTO polls
            (season_year, week, poll_type, question, closes_week)
        VALUES (?, ?, 'fan_player_of_week', 'Who owned this week?', ?)
        RETURNING id
        """,
        (season_year, week, week + 1),
    )
    poll_id = cur.fetchone()["id"]
    for index, candidate in enumerate(candidates):
        label = (
            f"{candidate['player']} ({candidate['abbreviation']}) — "
            f"{candidate['points']} PTS, {candidate['rebounds']} REB, {candidate['assists']} AST"
        )
        conn.execute(
            """
            INSERT INTO poll_options
                (poll_id, label, entity_type, entity_id, sort_order)
            VALUES (?, ?, 'player', ?, ?)
            """,
            (poll_id, label, candidate["id"], index),
        )
    return poll_id


def cast_poll_vote(conn, poll_id, option_id, voter_hash):
    poll = conn.execute(
        "SELECT * FROM polls WHERE id=? AND status='open'", (poll_id,)
    ).fetchone()
    if not poll:
        raise ValueError("This poll is closed.")
    option = conn.execute(
        "SELECT id FROM poll_options WHERE id=? AND poll_id=?", (option_id, poll_id)
    ).fetchone()
    if not option:
        raise ValueError("That option does not belong to this poll.")
    try:
        conn.execute(
            "INSERT INTO poll_votes (poll_id, option_id, voter_hash) VALUES (?, ?, ?)",
            (poll_id, option_id, voter_hash),
        )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper() or "duplicate" in str(exc).lower():
            raise ValueError("This browser has already voted in the poll.") from exc
        raise
    conn.commit()


def _insert_rotating_poll(conn, season_year, week, poll_type, question, options, context=None):
    cur = conn.execute(
        """
        INSERT INTO polls
            (season_year, week, poll_type, question, closes_week, context_json)
        VALUES (?, ?, ?, ?, ?, ?)
        RETURNING id
        """,
        (
            season_year,
            week,
            poll_type,
            question,
            week + 1,
            json.dumps(context or {}, separators=(",", ":")),
        ),
    )
    poll_id = cur.fetchone()["id"]
    for index, option in enumerate(options):
        conn.execute(
            """
            INSERT INTO poll_options
                (poll_id, label, entity_type, entity_id, payload_json, sort_order)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                poll_id,
                option["label"],
                option.get("entity_type"),
                option.get("entity_id"),
                json.dumps(option.get("payload") or {}, separators=(",", ":")),
                index,
            ),
        )
    return poll_id


def _player_poll_options(conn, week, season_year):
    candidates = conn.execute(
        f"""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation, pgs.points, pgs.rebounds, pgs.assists,
               ({_performance_value_sql()}) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        JOIN teams t ON t.id=pgs.team_id
        WHERE g.season_year=? AND g.week=?
        ORDER BY value DESC LIMIT 4
        """,
        (season_year, week),
    ).fetchall()
    return [
        {
            "label": (
                f"{row['player']} ({row['abbreviation']}) — "
                f"{row['points']} PTS, {row['rebounds']} REB, {row['assists']} AST"
            ),
            "entity_type": "player",
            "entity_id": row["id"],
        }
        for row in candidates
    ]


def _game_poll_options(conn, week, season_year):
    games = conn.execute(
        """
        SELECT g.id, g.home_score, g.away_score,
               ht.abbreviation AS home_abbr, at.abbreviation AS away_abbr,
               ge.turning_point
        FROM games g
        JOIN teams ht ON ht.id=g.home_team_id
        JOIN teams at ON at.id=g.away_team_id
        LEFT JOIN game_explanations ge ON ge.game_id=g.id
        WHERE g.season_year=? AND g.week=? AND g.played=1
        ORDER BY ABS(g.home_score-g.away_score), g.id
        LIMIT 4
        """,
        (season_year, week),
    ).fetchall()
    return [
        {
            "label": (
                f"{row['away_abbr']} {row['away_score']} at "
                f"{row['home_abbr']} {row['home_score']}"
            ),
            "entity_type": "game",
            "entity_id": row["id"],
            "payload": {"turning_point": row["turning_point"]},
        }
        for row in games
    ]


def _confidence_poll_options(conn, season_year):
    teams = conn.execute(
        """
        SELECT t.id, t.city || ' ' || t.name AS team,
               s.wins, s.losses, s.points_for-s.points_against AS point_diff
        FROM teams t
        LEFT JOIN standings s ON s.team_id=t.id AND s.season_year=?
        ORDER BY COALESCE(s.wins,0) DESC, point_diff DESC, t.id
        """,
        (season_year,),
    ).fetchall()
    return [
        {
            "label": (
                f"{row['team']} — {row['wins'] or 0}-{row['losses'] or 0}, "
                f"{(row['point_diff'] or 0):+d} differential"
            ),
            "entity_type": "team",
            "entity_id": row["id"],
        }
        for row in teams
    ]


def _rivalry_poll(conn, week, season_year):
    matchup = conn.execute(
        """
        SELECT g.id, g.home_team_id, g.away_team_id,
               ht.city AS home_city, ht.name AS home_name,
               ht.abbreviation AS home_abbr,
               at.city AS away_city, at.name AS away_name,
               at.abbreviation AS away_abbr,
               COALESCE(tr.current_intensity,0.12) AS rivalry_heat
        FROM games g
        JOIN teams ht ON ht.id=g.home_team_id
        JOIN teams at ON at.id=g.away_team_id
        LEFT JOIN team_rivalries tr
          ON (tr.team_a_id=g.home_team_id AND tr.team_b_id=g.away_team_id)
          OR (tr.team_a_id=g.away_team_id AND tr.team_b_id=g.home_team_id)
        WHERE g.season_year=? AND g.week=? AND g.played=1
        ORDER BY rivalry_heat DESC, ABS(g.home_score-g.away_score), g.id
        LIMIT 1
        """,
        (season_year, week),
    ).fetchone()
    if not matchup:
        return None, []
    key = tuple(sorted((matchup["home_abbr"], matchup["away_abbr"])))
    names = RIVALRY_NAME_OPTIONS.get(key)
    if not names:
        names = (
            f"The {matchup['away_city']}-{matchup['home_city']} Classic",
            f"The {matchup['away_name']}-{matchup['home_name']} Feud",
            "The Two-City Collision",
            "The Weeknight War",
        )
    context = {
        "game_id": matchup["id"],
        "team_a_id": min(matchup["home_team_id"], matchup["away_team_id"]),
        "team_b_id": max(matchup["home_team_id"], matchup["away_team_id"]),
        "matchup": f"{matchup['away_city']} {matchup['away_name']} vs {matchup['home_city']} {matchup['home_name']}",
    }
    return context, [
        {"label": name, "payload": {"rivalry_name": name}}
        for name in names
    ]


def create_weekly_poll(conn, week, season_year):
    """Create exactly one poll, rotating through five fan participation formats."""
    existing = conn.execute(
        "SELECT id FROM polls WHERE season_year=? AND week=?",
        (season_year, week),
    ).fetchone()
    if existing:
        return existing["id"]

    poll_type = POLL_ROTATION[(week - 1) % len(POLL_ROTATION)]
    if poll_type == "fan_player_of_week":
        question = "Who owned this week?"
        context = {"result_kind": "player_award"}
        options = _player_poll_options(conn, week, season_year)
    elif poll_type == "fan_game_of_week":
        question = "Which game deserves the fan spotlight?"
        context = {"result_kind": "game_award"}
        options = _game_poll_options(conn, week, season_year)
    elif poll_type == "fan_confidence":
        question = "Which team do you trust most right now?"
        context = {"result_kind": "team_confidence"}
        options = _confidence_poll_options(conn, season_year)
    elif poll_type == "rivalry_name":
        context, options = _rivalry_poll(conn, week, season_year)
        if not context:
            return None
        question = f"What should fans call {context['matchup']}?"
    else:
        question = "What should the league call its weekly effort-and-heart award?"
        context = {
            "result_kind": "league_label",
            "label_type": "weekly_effort_award_name",
        }
        options = [
            {"label": name, "payload": {"award_name": name}}
            for name in AWARD_NAME_OPTIONS
        ]

    if len(options) < 2:
        return None
    return _insert_rotating_poll(
        conn, season_year, week, poll_type, question, options, context
    )


def _poll_winner(conn, poll_id):
    rows = conn.execute(
        """
        SELECT po.*, COUNT(pv.id) AS votes
        FROM poll_options po
        LEFT JOIN poll_votes pv ON pv.option_id=po.id
        WHERE po.poll_id=?
        GROUP BY po.id
        ORDER BY votes DESC, po.sort_order ASC, po.id ASC
        """,
        (poll_id,),
    ).fetchall()
    if not rows or rows[0]["votes"] <= 0:
        return None
    return dict(rows[0])


def _apply_poll_result(conn, poll, winner):
    poll_type = poll["poll_type"]
    context = json.loads(poll["context_json"] or "{}")
    payload = json.loads(winner["payload_json"] or "{}")
    detail = f"Won the fan vote with {winner['votes']} vote{'s' if winner['votes'] != 1 else ''}."

    if poll_type == "fan_player_of_week":
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, ?, 'fan_player_of_week', 'player', ?, 'Fan Player of the Week', ?)
            ON CONFLICT DO NOTHING
            """,
            (poll["season_year"], poll["week"], winner["entity_id"], detail),
        )
        player = conn.execute(
            "SELECT first_name || ' ' || last_name AS name, team_id FROM players WHERE id=?",
            (winner["entity_id"],),
        ).fetchone()
        record_history_event(
            conn, poll["season_year"], poll["week"], "fan_award",
            f"Fans choose {player['name']} as Player of the Week", detail,
            team_id=player["team_id"], player_id=winner["entity_id"],
            source_key=f"fan-poll:{poll['id']}",
        )
    elif poll_type == "fan_game_of_week":
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, ?, 'fan_game_of_week', 'game', ?, 'Fan Game of the Week', ?)
            ON CONFLICT DO NOTHING
            """,
            (poll["season_year"], poll["week"], winner["entity_id"], detail),
        )
        record_history_event(
            conn, poll["season_year"], poll["week"], "fan_award",
            f"Fans select {winner['label']} as Game of the Week", detail,
            game_id=winner["entity_id"], source_key=f"fan-poll:{poll['id']}",
        )
    elif poll_type == "fan_confidence":
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, ?, 'fan_confidence', 'team', ?, 'Fan Confidence Leader', ?)
            ON CONFLICT DO NOTHING
            """,
            (poll["season_year"], poll["week"], winner["entity_id"], detail),
        )
        conn.execute(
            """
            INSERT INTO fan_labels
                (label_type, label, season_year, week, team_id, source_poll_id)
            VALUES ('fan_confidence', 'Fan Confidence Leader', ?, ?, ?, ?)
            ON CONFLICT (source_poll_id) DO NOTHING
            """,
            (poll["season_year"], poll["week"], winner["entity_id"], poll["id"]),
        )
        team = conn.execute(
            "SELECT city || ' ' || name AS name FROM teams WHERE id=?",
            (winner["entity_id"],),
        ).fetchone()
        record_history_event(
            conn, poll["season_year"], poll["week"], "fan_confidence",
            f"Fans put their confidence in {team['name']}", detail,
            team_id=winner["entity_id"], source_key=f"fan-poll:{poll['id']}",
        )
    elif poll_type == "rivalry_name":
        team_a_id = int(context["team_a_id"])
        team_b_id = int(context["team_b_id"])
        name = payload.get("rivalry_name") or winner["label"]
        conn.execute(
            """
            UPDATE rivalry_names SET status='retired'
            WHERE team_a_id=? AND team_b_id=? AND status='active'
            """,
            (team_a_id, team_b_id),
        )
        conn.execute(
            """
            INSERT INTO rivalry_names
                (team_a_id, team_b_id, name, season_year, week, source_poll_id)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (team_a_id, team_b_id, name, poll["season_year"], poll["week"], poll["id"]),
        )
        record_history_event(
            conn, poll["season_year"], poll["week"], "rivalry_named",
            f"Fans name the rivalry: {name}",
            f"{context.get('matchup', 'A league rivalry')} now has a permanent fan-given name.",
            team_id=team_a_id, game_id=context.get("game_id"),
            source_key=f"fan-poll:{poll['id']}", importance=2,
        )
    elif poll_type == "award_name":
        label_type = context.get("label_type", "weekly_effort_award_name")
        name = payload.get("award_name") or winner["label"]
        conn.execute(
            "UPDATE fan_labels SET status='retired' WHERE label_type=? AND status='active'",
            (label_type,),
        )
        conn.execute(
            """
            INSERT INTO fan_labels
                (label_type, label, season_year, week, source_poll_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (label_type, name, poll["season_year"], poll["week"], poll["id"]),
        )
        record_history_event(
            conn, poll["season_year"], poll["week"], "award_named",
            f"Fans establish {name}",
            "The winning name becomes the league's weekly effort-and-heart honor.",
            source_key=f"fan-poll:{poll['id']}", importance=2,
        )


def finalize_due_polls(conn, week, season_year):
    due = conn.execute(
        """
        SELECT * FROM polls
        WHERE status='open'
          AND (season_year<? OR (season_year=? AND closes_week<=?))
        ORDER BY season_year, week, id
        """,
        (season_year, season_year, week),
    ).fetchall()
    finalized = []
    for row in due:
        poll = dict(row)
        winner = _poll_winner(conn, poll["id"])
        if winner:
            _apply_poll_result(conn, poll, winner)
            result_label = winner["label"]
            winner_option_id = winner["id"]
        else:
            result_label = "No fan verdict"
            winner_option_id = None
        conn.execute(
            """
            UPDATE polls
            SET status='closed', result_label=?, winner_option_id=?,
                finalized_at=datetime('now')
            WHERE id=?
            """,
            (result_label, winner_option_id, poll["id"]),
        )
        finalized.append(poll["id"])
    return finalized


def _rows(rows):
    return [dict(row) for row in rows]


def build_weekly_editorial_package(conn, week, season_year):
    existing = conn.execute(
        "SELECT * FROM weekly_editorial_packages WHERE season_year=? AND week=?",
        (season_year, week),
    ).fetchone()
    if existing:
        return dict(existing)

    source = {
        "schema": EDITORIAL_SCHEMA,
        "season_year": season_year,
        "week": week,
        "teams": _rows(conn.execute(
            "SELECT id, city || ' ' || name AS name, abbreviation, team_archetype, reputation, rivalry FROM teams ORDER BY id"
        ).fetchall()),
        "games": _rows(conn.execute(
            """
            SELECT g.id, g.week, g.home_team_id, g.away_team_id,
                   ht.city || ' ' || ht.name AS home_team,
                   at.city || ' ' || at.name AS away_team,
                   g.home_score, g.away_score, g.mvp_player_id,
                   ge.factual_recap, ge.turning_point, ge.standings_impact,
                   ge.home_win_probability
            FROM games g
            JOIN teams ht ON ht.id=g.home_team_id
            JOIN teams at ON at.id=g.away_team_id
            LEFT JOIN game_explanations ge ON ge.game_id=g.id
            WHERE g.season_year=? AND g.week=? AND g.played=1
            ORDER BY ABS(g.home_score-g.away_score), g.id
            """,
            (season_year, week),
        ).fetchall()),
        "standings": _rows(conn.execute(
            """
            SELECT t.id AS team_id, t.abbreviation,
                   t.city || ' ' || t.name AS team,
                   s.wins, s.losses, s.points_for-s.points_against AS point_diff
            FROM standings s JOIN teams t ON t.id=s.team_id
            WHERE s.season_year=?
            ORDER BY s.wins DESC, point_diff DESC
            """,
            (season_year,),
        ).fetchall()),
        "mvp_race": _rows(conn.execute(
            f"""
            SELECT p.id AS player_id, p.first_name || ' ' || p.last_name AS player,
                   t.id AS team_id, t.abbreviation,
                   ROUND(AVG(pgs.points),1) AS ppg,
                   ROUND(AVG(pgs.rebounds),1) AS rpg,
                   ROUND(AVG(pgs.assists),1) AS apg,
                   ROUND(AVG({_performance_value_sql()}),1) AS value
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=pgs.team_id
            WHERE g.season_year=?
            GROUP BY p.id, t.id
            ORDER BY value DESC LIMIT 8
            """,
            (season_year,),
        ).fetchall()),
        "week_players": _rows(conn.execute(
            f"""
            SELECT p.id AS player_id, p.first_name || ' ' || p.last_name AS player,
                   t.id AS team_id, t.abbreviation, g.id AS game_id,
                   pgs.points, pgs.rebounds, pgs.assists, pgs.steals, pgs.blocks,
                   pp.archetype, pp.loyalty, pp.ego, pp.leadership,
                   pa.arc_type, pa.title AS arc_title,
                   ({_performance_value_sql()}) AS value
            FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            JOIN teams t ON t.id=pgs.team_id
            LEFT JOIN player_personalities pp ON pp.player_id=p.id
            LEFT JOIN player_arcs pa ON pa.player_id=p.id
            WHERE g.season_year=? AND g.week=?
            ORDER BY value DESC LIMIT 16
            """,
            (season_year, week),
        ).fetchall()),
        "events": _rows(conn.execute(
            """
            SELECT pe.id, pe.player_id, pe.target_id, pe.event_type, pe.detail,
                   p.team_id, p.first_name || ' ' || p.last_name AS player
            FROM player_events pe JOIN players p ON p.id=pe.player_id
            WHERE pe.season_year=? AND pe.week=?
            ORDER BY pe.id DESC
            """,
            (season_year, week),
        ).fetchall()),
        "injuries": _rows(conn.execute(
            """
            SELECT i.id, i.player_id, p.team_id,
                   p.first_name || ' ' || p.last_name AS player,
                   i.severity, i.description, i.expected_return_week
            FROM player_injuries i JOIN players p ON p.id=i.player_id
            WHERE i.season_year=? AND i.week_start=?
            """,
            (season_year, week),
        ).fetchall()),
        "coaches": _rows(conn.execute(
            """
            SELECT hc.id AS coach_id, hc.team_id, hc.name, hc.strategy
            FROM head_coaches hc WHERE hc.status='active'
            ORDER BY hc.team_id
            """
        ).fetchall()),
        "gms": _rows(conn.execute(
            "SELECT id AS gm_id, team_id, name, archetype FROM general_managers ORDER BY team_id"
        ).fetchall()),
        "rivalries": _rows(conn.execute(
            """
            SELECT tr.id, tr.team_a_id, tr.team_b_id, tr.current_intensity,
                   tr.meetings, tr.close_games, tr.playoff_meetings,
                   tr.trade_count, tr.last_event, rn.name AS fan_name
            FROM team_rivalries tr
            LEFT JOIN rivalry_names rn
              ON rn.team_a_id=tr.team_a_id AND rn.team_b_id=tr.team_b_id
             AND rn.status='active'
            WHERE tr.current_intensity>=0.28
            ORDER BY tr.current_intensity DESC
            LIMIT 10
            """
        ).fetchall()),
        "next_games": _rows(conn.execute(
            """
            SELECT g.id, g.home_team_id, g.away_team_id,
                   ht.city || ' ' || ht.name AS home_team,
                   at.city || ' ' || at.name AS away_team
            FROM games g
            JOIN teams ht ON ht.id=g.home_team_id
            JOIN teams at ON at.id=g.away_team_id
            WHERE g.season_year=? AND g.week=? AND g.played=0
            ORDER BY g.id
            """,
            (season_year, week + 1),
        ).fetchall()),
    }
    cur = conn.execute(
        """
        INSERT INTO weekly_editorial_packages
            (season_year, week, source_json, prompt_text)
        VALUES (?, ?, ?, '')
        RETURNING id
        """,
        (season_year, week, json.dumps(source, separators=(",", ":"))),
    )
    package_id = cur.fetchone()["id"]
    contract = {
        "schema": EDITORIAL_SCHEMA,
        "direction": "chatgpt_to_aiba",
        "package_id": package_id,
        "season_year": season_year,
        "week": week,
        "stories": [
            {
                "role": "lead",
                "headline": "Required",
                "body": "2-4 factual sentences",
                "game_ids": [],
                "team_ids": [],
                "player_ids": [],
            },
            {
                "role": "support",
                "headline": "Required",
                "body": "2-4 factual sentences",
                "game_ids": [],
                "team_ids": [],
                "player_ids": [],
            },
        ],
        "quotes": [
            {
                "speaker_type": "player, coach, or gm",
                "speaker_id": 0,
                "game_id": None,
                "quote": "One or two in-character sentences",
            }
        ],
        "game_of_week": "Short preview using a real next_games game ID.",
        "mvp_commentary": "One paragraph based on mvp_race.",
        "hot_team": "Team ID plus concise reason.",
        "cold_team": "Team ID plus concise reason.",
        "trade_or_rivalry_drama": "One concise factual hook, or an empty string.",
    }
    payload = {
        "schema": EDITORIAL_SCHEMA,
        "direction": "aiba_to_chatgpt",
        "package_id": package_id,
        "instructions": [
            "The source data is authoritative. Do not invent scores, IDs, injuries, transactions, or relationships.",
            "Lead with story and consequence, not a stat dump.",
            "Return exactly one lead story and up to two support stories.",
            "Return no more than four quotes. Use only listed player, coach, or GM IDs.",
            "Quotes add voice but cannot alter simulation state.",
            f"Return JSON inside {EDITORIAL_FROM_GPT_START} and {EDITORIAL_FROM_GPT_END}.",
        ],
        "response_contract": contract,
        "source": source,
    }
    prompt = (
        f"{EDITORIAL_TO_GPT_START}\n"
        f"{json.dumps(payload, indent=2)}\n"
        f"{EDITORIAL_TO_GPT_END}"
    )
    conn.execute(
        "UPDATE weekly_editorial_packages SET prompt_text=? WHERE id=?",
        (prompt, package_id),
    )
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM weekly_editorial_packages WHERE id=?", (package_id,)
    ).fetchone())


def _extract_editorial_json(raw):
    marker = re.search(
        rf"{re.escape(EDITORIAL_FROM_GPT_START)}\s*(.*?)\s*{re.escape(EDITORIAL_FROM_GPT_END)}",
        raw,
        re.DOTALL,
    )
    candidate = marker.group(1) if marker else raw
    fenced = re.search(r"```(?:json)?\s*(.*?)```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1)
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("No editorial JSON object was found.")
    try:
        return json.loads(candidate[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"The editorial JSON is invalid: {exc}") from exc


def publish_weekly_editorial(conn, raw):
    data = _extract_editorial_json(raw)
    if data.get("schema") != EDITORIAL_SCHEMA:
        raise ValueError(f"Expected schema {EDITORIAL_SCHEMA}.")
    if data.get("direction") != "chatgpt_to_aiba":
        raise ValueError("Editorial direction must be chatgpt_to_aiba.")
    package = conn.execute(
        "SELECT * FROM weekly_editorial_packages WHERE id=?",
        (data.get("package_id"),),
    ).fetchone()
    if not package:
        raise ValueError("This editorial package does not exist.")
    if data.get("season_year") != package["season_year"] or data.get("week") != package["week"]:
        raise ValueError("The response season or week does not match its package.")

    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
    response_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if package["status"] == "published":
        if package["response_hash"] == response_hash:
            return 0, 0, True
        raise ValueError("This week already has a different published editorial package.")

    source = json.loads(package["source_json"])
    allowed_games = {item["id"] for item in source["games"] + source["next_games"]}
    allowed_teams = {item["id"] for item in source["teams"]}
    allowed_players = {item["player_id"] for item in source["mvp_race"]}
    allowed_players.update(item["player_id"] for item in source["week_players"])
    allowed_players.update(item["player_id"] for item in source["events"])
    allowed_players.update(item["player_id"] for item in source["injuries"])
    for game in source["games"]:
        if game.get("mvp_player_id"):
            allowed_players.add(game["mvp_player_id"])
    allowed_coaches = {item["coach_id"] for item in source["coaches"]}
    allowed_gms = {item["gm_id"] for item in source["gms"]}

    stories = data.get("stories") or []
    if not 1 <= len(stories) <= 3:
        raise ValueError("Return one lead story and no more than two support stories.")
    if sum(1 for story in stories if story.get("role") == "lead") != 1:
        raise ValueError("Exactly one story must have role 'lead'.")

    article_count = 0
    for story in stories:
        if story.get("role") not in ("lead", "support"):
            raise ValueError("Story roles must be lead or support.")
        headline = (story.get("headline") or "").strip()
        body = (story.get("body") or "").strip()
        if not headline or not body:
            raise ValueError("Every story needs a headline and body.")
        game_ids = {int(value) for value in story.get("game_ids") or []}
        team_ids = {int(value) for value in story.get("team_ids") or []}
        player_ids = {int(value) for value in story.get("player_ids") or []}
        if not game_ids <= allowed_games or not team_ids <= allowed_teams or not player_ids <= allowed_players:
            raise ValueError("A story references an entity that was not in the source package.")
        cur = conn.execute(
            """
            INSERT INTO articles
                (week, season_year, headline, body, editorial_package_id, story_role)
            VALUES (?, ?, ?, ?, ?, ?)
            RETURNING id
            """,
            (
                package["week"],
                package["season_year"],
                headline,
                body,
                package["id"],
                story["role"],
            ),
        )
        article_id = cur.fetchone()["id"]
        for team_id in team_ids:
            conn.execute(
                "INSERT INTO article_tags (article_id, tag_type, tag_id) VALUES (?, 'team', ?)",
                (article_id, team_id),
            )
        for player_id in player_ids:
            conn.execute(
                "INSERT INTO article_tags (article_id, tag_type, tag_id) VALUES (?, 'player', ?)",
                (article_id, player_id),
            )
        for game_id in game_ids:
            conn.execute(
                "INSERT INTO article_tags (article_id, tag_type, tag_id) VALUES (?, 'game', ?)",
                (article_id, game_id),
            )
        article_count += 1

    quotes = data.get("quotes") or []
    if len(quotes) > 4:
        raise ValueError("The weekly package can publish at most four quotes.")
    quote_count = 0
    for quote in quotes:
        speaker_type = quote.get("speaker_type")
        speaker_id = int(quote.get("speaker_id") or 0)
        quote_text = (quote.get("quote") or "").strip()
        game_id = quote.get("game_id")
        if game_id is not None and int(game_id) not in allowed_games:
            raise ValueError("A quote references a game outside the source package.")
        valid = (
            (speaker_type == "player" and speaker_id in allowed_players)
            or (speaker_type == "coach" and speaker_id in allowed_coaches)
            or (speaker_type == "gm" and speaker_id in allowed_gms)
        )
        if not valid or not quote_text:
            raise ValueError("A quote has an invalid speaker or empty text.")
        conn.execute(
            """
            INSERT INTO editorial_quotes
                (package_id, speaker_type, speaker_id, game_id, quote_text)
            VALUES (?, ?, ?, ?, ?)
            """,
            (package["id"], speaker_type, speaker_id, game_id, quote_text),
        )
        quote_count += 1

    conn.execute(
        """
        UPDATE weekly_editorial_packages
        SET response_json=?, response_hash=?, status='published',
            published_at=datetime('now')
        WHERE id=?
        """,
        (canonical, response_hash, package["id"]),
    )
    conn.commit()
    return article_count, quote_count, False


def record_team_change(conn, player_id, old_team_id, new_team_id, season_year, week, reason):
    if old_team_id == new_team_id:
        return
    conn.execute(
        """
        INSERT INTO player_relationships
            (player_id, origin_team_id, relationship_type, intensity,
             started_season, started_week, detail)
        VALUES (?, ?, 'former_team', 0.72, ?, ?, ?)
        ON CONFLICT DO NOTHING
        """,
        (player_id, old_team_id, season_year, week, reason),
    )
    player = conn.execute(
        "SELECT first_name || ' ' || last_name AS name FROM players WHERE id=?",
        (player_id,),
    ).fetchone()
    old_team = conn.execute(
        "SELECT city || ' ' || name AS name FROM teams WHERE id=?", (old_team_id,)
    ).fetchone()
    new_team = conn.execute(
        "SELECT city || ' ' || name AS name FROM teams WHERE id=?", (new_team_id,)
    ).fetchone()
    if player and old_team and new_team:
        record_history_event(
            conn,
            season_year,
            week,
            "team_change",
            f"{player['name']} leaves {old_team['name']}",
            f"{player['name']} joined {new_team['name']} via {reason}. A future meeting now carries revenge-game history.",
            team_id=new_team_id,
            player_id=player_id,
            source_key=f"team-change:{player_id}:{season_year}:{week}:{old_team_id}:{new_team_id}",
            importance=2,
        )


def finalize_season(conn, season_year):
    refresh_record_book(conn, season_year, week=0, announce=True)
    refresh_playoff_run_summaries(conn, season_year)
    champion = conn.execute(
        """
        SELECT winner_id FROM playoff_series
        WHERE season_year=? AND series_type='finals' AND status='complete'
        ORDER BY id DESC LIMIT 1
        """,
        (season_year,),
    ).fetchone()
    champion_id = champion["winner_id"] if champion else None

    mvp = conn.execute(
        f"""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               ROUND(AVG({_performance_value_sql()}),1) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        WHERE g.season_year=?
        GROUP BY p.id ORDER BY value DESC LIMIT 1
        """,
        (season_year,),
    ).fetchone()
    if mvp:
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, 0, 'mvp', 'player', ?, 'Most Valuable Player', ?)
            ON CONFLICT DO NOTHING
            """,
            (season_year, mvp["id"], f"Season performance value: {mvp['value']}."),
        )

    finals_mvp = conn.execute(
        f"""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               SUM({_performance_value_sql()}) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN playoff_series ps ON ps.id=g.playoff_series_id
        JOIN players p ON p.id=pgs.player_id
        WHERE g.season_year=? AND ps.series_type='finals'
        GROUP BY p.id ORDER BY value DESC LIMIT 1
        """,
        (season_year,),
    ).fetchone()
    if finals_mvp:
        conn.execute(
            """
            INSERT INTO awards
                (season_year, week, award_type, entity_type, entity_id, label, detail)
            VALUES (?, 0, 'finals_mvp', 'player', ?, 'Finals MVP', 'Best performance across the championship series.')
            ON CONFLICT DO NOTHING
            """,
            (season_year, finals_mvp["id"]),
        )

    for position in ("PG", "SG", "SF", "PF", "C"):
        player = conn.execute(
            f"""
            SELECT p.id FROM player_game_stats pgs
            JOIN games g ON g.id=pgs.game_id
            JOIN players p ON p.id=pgs.player_id
            WHERE g.season_year=? AND p.position=?
            GROUP BY p.id ORDER BY AVG({_performance_value_sql()}) DESC LIMIT 1
            """,
            (season_year, position),
        ).fetchone()
        if player:
            conn.execute(
                """
                INSERT INTO awards
                    (season_year, week, award_type, entity_type, entity_id, label, detail)
                VALUES (?, 0, 'all_league', 'player', ?, 'All-League Team', ?)
                ON CONFLICT DO NOTHING
                """,
                (season_year, player["id"], f"Selected at {position}."),
            )

    standings = _rows(conn.execute(
        """
        SELECT t.id AS team_id, t.abbreviation, s.wins, s.losses,
               s.points_for, s.points_against
        FROM standings s JOIN teams t ON t.id=s.team_id
        WHERE s.season_year=? ORDER BY s.wins DESC, (s.points_for-s.points_against) DESC
        """,
        (season_year,),
    ).fetchall())
    awards = _rows(conn.execute(
        "SELECT award_type, entity_type, entity_id, label, detail FROM awards WHERE season_year=?",
        (season_year,),
    ).fetchall())
    records = _rows(conn.execute(
        """
        SELECT scope, stat_key, label, player_id, team_id, value,
               season_year, week, game_id
        FROM record_book_entries
        WHERE is_current=1
        ORDER BY scope, stat_key, player_id
        """
    ).fetchall())
    snapshot = {"standings": standings, "awards": awards, "records": records}
    conn.execute(
        """
        INSERT INTO season_snapshots (season_year, snapshot_json, champion_id)
        VALUES (?, ?, ?)
        ON CONFLICT (season_year) DO UPDATE SET
            snapshot_json=EXCLUDED.snapshot_json, champion_id=EXCLUDED.champion_id
        """,
        (season_year, json.dumps(snapshot), champion_id),
    )
    if champion_id:
        team = conn.execute(
            "SELECT city || ' ' || name AS name FROM teams WHERE id=?", (champion_id,)
        ).fetchone()
        record_history_event(
            conn,
            season_year,
            0,
            "championship",
            f"{team['name']} wins the {season_year} championship",
            "The result is preserved permanently in league history.",
            team_id=champion_id,
            source_key=f"champion:{season_year}",
            importance=3,
        )
    refresh_league_lore(conn, season_year)


def process_coach_offseason(conn, season_year):
    coaches = conn.execute(
        """
        SELECT hc.*, s.wins, s.losses, t.abbreviation
        FROM head_coaches hc
        JOIN teams t ON t.id=hc.team_id
        LEFT JOIN standings s ON s.team_id=hc.team_id AND s.season_year=?
        WHERE hc.status='active'
        """,
        (season_year,),
    ).fetchall()
    replacements = [
        "Nadia Price", "Theo March", "Renee Holloway", "Cal Dorsey",
        "Mara Quinn", "Isaiah North", "Sloane Keller", "Andre Rios",
    ]
    changes = []
    for coach in coaches:
        games = (coach["wins"] or 0) + (coach["losses"] or 0)
        pct = (coach["wins"] or 0) / games if games else 0.5
        new_security = max(0.12, min(0.96, coach["job_security"] + (pct - 0.5) * 0.55))
        should_fire = pct < 0.30 and new_security < 0.58
        if not should_fire:
            conn.execute(
                "UPDATE head_coaches SET job_security=? WHERE id=?",
                (new_security, coach["id"]),
            )
            continue
        conn.execute(
            "UPDATE head_coaches SET status='fired', fired_season=? WHERE id=?",
            (season_year, coach["id"]),
        )
        name = replacements[(coach["team_id"] + season_year) % len(replacements)]
        cur = conn.execute(
            """
            INSERT INTO head_coaches
                (team_id, name, strategy, development, leadership,
                 pressure_handling, pace_preference, rotation_tightness,
                 lineup_preference, job_security, hired_season)
            VALUES (?, ?, 'adaptive_balance', 0.72, 0.70, 0.67, 0.55, 0.58,
                    'balanced_best_five', 0.78, ?)
            RETURNING id
            """,
            (coach["team_id"], name, season_year + 1),
        )
        new_id = cur.fetchone()["id"]
        record_history_event(
            conn,
            season_year,
            0,
            "coach_change",
            f"{coach['abbreviation']} fires {coach['name']}",
            f"{name} takes over after a {coach['wins'] or 0}-{coach['losses'] or 0} season.",
            team_id=coach["team_id"],
            coach_id=new_id,
            source_key=f"coach-change:{season_year}:{coach['team_id']}",
            importance=2,
        )
        changes.append(name)
    return changes


def after_week(conn, week, season_year):
    finalize_due_polls(conn, week, season_year)
    update_player_arcs(conn, week, season_year)
    create_weekly_awards(conn, week, season_year)
    record_weekly_milestones(conn, week, season_year)
    refresh_record_book(conn, season_year, week, announce=True)
    process_injury_comebacks(conn, week, season_year)
    refresh_league_lore(conn, season_year)
    create_weekly_poll(conn, week, season_year)
    package = build_weekly_editorial_package(conn, week, season_year)
    state = conn.execute("SELECT phase FROM league_state WHERE id=1").fetchone()
    if state and state["phase"] == "complete":
        finalize_season(conn, season_year)
    conn.commit()
    return package


def win_probability_from_margin(expected_margin):
    return 1.0 / (1.0 + math.exp(-expected_margin / 6.2))
