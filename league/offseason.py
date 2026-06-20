"""
Offseason engine.

Advances a completed season into the next one in commissioner-controlled
stages: retirements, development/regression, contracts, free-agent signings,
rookie creation, standings, schedule, and league clock.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from league.database import create_tables, get_connection
from league.player_agents import get_current_morale, log_player_memory
from seed import (
    FIRST_NAMES,
    LAST_NAMES,
    POSITIONS_PER_TEAM,
    INITIAL_MORALE,
    _generate_traits,
    _pick_archetype,
    build_schedule,
    salary_for,
)


ROSTER_SIZE = len(POSITIONS_PER_TEAM)

OFFSEASON_STAGES = [
    "retirements",
    "development",
    "contracts",
    "draft",
    "free_agency",
    "roster_finalization",
    "finalize",
]

OFFSEASON_STAGE_LABELS = {
    "retirements": "Retirements",
    "development": "Player Development",
    "contracts": "Contracts",
    "draft": "Rookie Draft",
    "free_agency": "Free Agency",
    "roster_finalization": "Roster Finalization",
    "finalize": "Schedule Release",
}


def _market_salary(skill):
    return max(500_000, int(skill * 120_000))


def _team_salary(conn, team_id):
    row = conn.execute(
        "SELECT SUM(salary) AS s FROM players "
        "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
        (team_id,),
    ).fetchone()
    return row["s"] if row and row["s"] else 0


def _load_player_archetypes():
    import json

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")
    with open(path) as f:
        return json.load(f).get("player_archetypes", {})


def _load_salary_cap():
    import json

    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")
    with open(path) as f:
        return json.load(f).get("salary_cap", 100_000_000)


def _player_label(player):
    return f"{player['first_name']} {player['last_name']}"


def _retire_player(conn, player, season_year, reason):
    pid = player["id"]
    conn.execute(
        "UPDATE players SET status = 'retired', retired_season = ? WHERE id = ?",
        (season_year, pid),
    )
    conn.execute("DELETE FROM contracts WHERE player_id = ?", (pid,))
    conn.execute(
        "UPDATE player_events SET status = 'resolved' WHERE player_id = ?",
        (pid,),
    )
    log_player_memory(conn, pid, 0, season_year, "retired", reason)


def _resolve_retirements(conn, season_year):
    retired = []
    players = conn.execute(
        "SELECT * FROM players WHERE COALESCE(status, 'active') = 'active'"
    ).fetchall()

    for row in players:
        player = dict(row)
        morale = get_current_morale(conn, player["id"])
        notice = conn.execute(
            "SELECT id FROM player_events "
            "WHERE player_id = ? AND event_type = 'retirement' AND status = 'active'",
            (player["id"],),
        ).fetchone()

        reason = None
        if notice:
            reason = "followed through on retirement notice"
        elif player["age"] >= 38:
            reason = "retired due to age"
        elif player["age"] >= 35 and morale < 36 and random.random() < 0.35:
            reason = f"retired after difficult season (morale {morale:.0f})"

        if reason:
            _retire_player(conn, player, season_year, reason)
            retired.append(_player_label(player))

    return retired


def _age_and_develop_players(conn):
    improved = regressed = 0
    rows = conn.execute(
        "SELECT * FROM players WHERE COALESCE(status, 'active') = 'active'"
    ).fetchall()

    for row in rows:
        player = dict(row)
        age = player["age"] + 1
        skill = player["skill_rating"]
        morale = get_current_morale(conn, player["id"])

        delta = 0
        if age <= 24 and random.random() < 0.55:
            delta += random.randint(1, 3)
        elif age <= 28 and random.random() < 0.25:
            delta += 1
        elif age >= 34 and random.random() < 0.65:
            delta -= random.randint(1, 3)
        elif age >= 31 and random.random() < 0.35:
            delta -= 1

        if morale >= 75 and age <= 27 and random.random() < 0.20:
            delta += 1
        if morale < 35 and age >= 30 and random.random() < 0.20:
            delta -= 1

        new_skill = max(35, min(96, skill + delta))
        conn.execute(
            "UPDATE players SET age = ?, skill_rating = ? WHERE id = ?",
            (age, new_skill, player["id"]),
        )
        if delta > 0:
            improved += 1
        elif delta < 0:
            regressed += 1

    return improved, regressed


def _extend_contract(conn, player, contract, next_year, salary_cap):
    pid = player["id"]
    current_salary = contract["salary"]
    market = _market_salary(player["skill_rating"])
    new_salary = max(current_salary, int(market * random.uniform(0.95, 1.18)))
    new_years = random.randint(2, 4)

    current_total = _team_salary(conn, player["team_id"])
    projected_total = current_total - current_salary + new_salary
    if projected_total > salary_cap and player["skill_rating"] < 82:
        return False

    conn.execute(
        "UPDATE players SET salary = ?, status = 'active' WHERE id = ?",
        (new_salary, pid),
    )
    conn.execute(
        "UPDATE contracts SET salary = ?, years_remaining = ?, season_start = ? "
        "WHERE id = ?",
        (new_salary, new_years, next_year, contract["id"]),
    )
    conn.execute(
        "UPDATE player_events SET status = 'resolved' "
        "WHERE player_id = ? AND event_type = 'contract_request' AND status = 'active'",
        (pid,),
    )
    log_player_memory(
        conn,
        pid,
        0,
        next_year,
        "contract_extension",
        f"Extended for {new_years} years at ${new_salary / 1_000_000:.1f}M",
    )
    return True


def _process_contracts(conn, season_year, next_year, salary_cap):
    extended = []
    free_agents = []

    conn.execute(
        "UPDATE contracts SET years_remaining = years_remaining - 1 "
        "WHERE player_id IN ("
        "SELECT id FROM players WHERE COALESCE(status, 'active') = 'active'"
        ")"
    )

    expiring = conn.execute(
        "SELECT p.*, c.id AS contract_id, c.salary AS contract_salary, "
        "       c.years_remaining, c.season_start "
        "FROM contracts c "
        "JOIN players p ON c.player_id = p.id "
        "WHERE c.years_remaining <= 0 AND COALESCE(p.status, 'active') = 'active'"
    ).fetchall()

    for row in expiring:
        player = dict(row)
        contract = {
            "id": player["contract_id"],
            "salary": player["contract_salary"],
        }
        request = conn.execute(
            "SELECT id FROM player_events "
            "WHERE player_id = ? AND event_type = 'contract_request' AND status = 'active'",
            (player["id"],),
        ).fetchone()
        morale = get_current_morale(conn, player["id"])
        keeper = player["skill_rating"] >= 78 or (request and morale >= 55)

        if keeper and _extend_contract(conn, player, contract, next_year, salary_cap):
            extended.append(_player_label(player))
            continue

        conn.execute("DELETE FROM contracts WHERE id = ?", (contract["id"],))
        conn.execute(
            "UPDATE players SET status = 'free_agent' WHERE id = ?",
            (player["id"],),
        )
        conn.execute(
            "UPDATE player_events SET status = 'resolved' WHERE player_id = ?",
            (player["id"],),
        )
        log_player_memory(
            conn,
            player["id"],
            0,
            season_year,
            "entered_free_agency",
            "Contract expired without extension",
        )
        free_agents.append(_player_label(player))

    return extended, free_agents


def _desired_position(team_players):
    counts = {pos: 0 for pos in set(POSITIONS_PER_TEAM)}
    for player in team_players:
        counts[player["position"]] = counts.get(player["position"], 0) + 1

    desired = {pos: POSITIONS_PER_TEAM.count(pos) for pos in counts}
    for pos in POSITIONS_PER_TEAM:
        if counts.get(pos, 0) < desired.get(pos, 0):
            return pos
    return min(counts, key=lambda pos: counts[pos])


def _create_rookie(conn, team_id, position, next_year, archetype_counts):
    player_arch_cfgs = _load_player_archetypes()
    age = random.randint(19, 22)
    skill = random.randint(45, 74)
    salary = salary_for(skill)
    fname = random.choice(FIRST_NAMES)
    lname = random.choice(LAST_NAMES)

    _cur = conn.execute(
        "INSERT INTO players "
        "(team_id, first_name, last_name, age, position, skill_rating, salary, status) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 'active')"
        " RETURNING id",
        (team_id, fname, lname, age, position, skill, salary),
    )
    pid = _cur.fetchone()["id"]
    conn.execute(
        "INSERT INTO contracts (player_id, team_id, salary, years_remaining, season_start) "
        "VALUES (?, ?, ?, ?, ?)",
        (pid, team_id, salary, random.randint(2, 4), next_year),
    )

    arch = _pick_archetype(age, archetype_counts)
    archetype_counts[arch] = archetype_counts.get(arch, 0) + 1
    base_traits = player_arch_cfgs.get(arch, {}).get(
        "base_traits",
        {
            "ambition": 0.5,
            "loyalty": 0.5,
            "ego": 0.5,
            "work_ethic": 0.5,
            "volatility": 0.3,
        },
    )
    traits = _generate_traits(base_traits)
    conn.execute(
        "INSERT INTO player_personalities "
        "(player_id, archetype, ambition, loyalty, ego, work_ethic, volatility) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            pid,
            arch,
            traits["ambition"],
            traits["loyalty"],
            traits["ego"],
            traits["work_ethic"],
            traits["volatility"],
        ),
    )
    morale = max(20.0, min(95.0, INITIAL_MORALE.get(arch, 68) + random.gauss(0, 5)))
    conn.execute(
        "INSERT INTO player_morale (player_id, week, season_year, morale) "
        "VALUES (?, 0, ?, ?)",
        (pid, next_year, morale),
    )
    log_player_memory(
        conn,
        pid,
        0,
        next_year,
        "rookie_signed",
        f"Joined as rookie {position}, skill {skill}",
    )
    return f"{fname} {lname}"


def _sign_player(conn, player, team_id, next_year):
    salary = max(player["salary"], _market_salary(player["skill_rating"]))
    years = random.randint(1, 3)
    conn.execute(
        "UPDATE players SET team_id = ?, salary = ?, status = 'active' WHERE id = ?",
        (team_id, salary, player["id"]),
    )
    conn.execute(
        "INSERT INTO contracts (player_id, team_id, salary, years_remaining, season_start) "
        "VALUES (?, ?, ?, ?, ?)",
        (player["id"], team_id, salary, years, next_year),
    )
    conn.execute(
        "INSERT INTO player_morale (player_id, week, season_year, morale) "
        "VALUES (?, 0, ?, ?) "
        "ON CONFLICT (player_id, week, season_year) DO UPDATE SET morale = EXCLUDED.morale",
        (player["id"], next_year, max(50.0, get_current_morale(conn, player["id"]) + 6)),
    )
    log_player_memory(
        conn,
        player["id"],
        0,
        next_year,
        "free_agent_signed",
        f"Signed for {years} years at ${salary / 1_000_000:.1f}M",
    )
    return _player_label(player)


def _sign_free_agents_to_roster_holes(conn, next_year, salary_cap):
    signed = []
    teams = conn.execute("SELECT id FROM teams ORDER BY id").fetchall()
    for team in teams:
        team_id = team["id"]
        while True:
            roster = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM players "
                    "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
                    (team_id,),
                ).fetchall()
            ]
            if len(roster) >= ROSTER_SIZE:
                break

            position = _desired_position(roster)
            cap_space = salary_cap - _team_salary(conn, team_id)
            candidate = conn.execute(
                "SELECT * FROM players "
                "WHERE status = 'free_agent' AND position = ? "
                "ORDER BY skill_rating DESC LIMIT 1",
                (position,),
            ).fetchone()
            if candidate and _market_salary(candidate["skill_rating"]) <= max(cap_space, 1_500_000):
                signed.append(_sign_player(conn, dict(candidate), team_id, next_year))
            else:
                break

    return signed


def _draft_rookies_to_fill_rosters(conn, next_year, max_per_team=None):
    rookies = []
    archetype_counts = {
        row["archetype"]: row["n"]
        for row in conn.execute(
            "SELECT archetype, COUNT(*) AS n FROM player_personalities GROUP BY archetype"
        ).fetchall()
    }

    teams = conn.execute("SELECT id FROM teams ORDER BY id").fetchall()
    for team in teams:
        team_id = team["id"]
        team_rookies = 0
        while True:
            roster = [
                dict(row)
                for row in conn.execute(
                    "SELECT * FROM players "
                    "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
                    (team_id,),
                ).fetchall()
            ]
            if len(roster) >= ROSTER_SIZE:
                break
            if max_per_team is not None and team_rookies >= max_per_team:
                break

            position = _desired_position(roster)
            rookies.append(_create_rookie(conn, team_id, position, next_year, archetype_counts))
            team_rookies += 1

    return rookies


def _fill_rosters(conn, next_year, salary_cap):
    signed = _sign_free_agents_to_roster_holes(conn, next_year, salary_cap)
    rookies = _draft_rookies_to_fill_rosters(conn, next_year)
    return signed, rookies


def _create_next_season(conn, next_year):
    team_ids = [row["id"] for row in conn.execute("SELECT id FROM teams ORDER BY id").fetchall()]
    for team_id in team_ids:
        conn.execute(
            "INSERT OR IGNORE INTO standings (team_id, season_year) VALUES (?, ?)",
            (team_id, next_year),
        )

    schedule, total_weeks = build_schedule(team_ids, num_rounds=4)
    for home, away, week in schedule:
        conn.execute(
            "INSERT INTO games (home_team_id, away_team_id, week, season_year) "
            "VALUES (?, ?, ?, ?)",
            (home, away, week, next_year),
        )

    return total_weeks, len(schedule)


def _next_stage(stage):
    idx = OFFSEASON_STAGES.index(stage)
    if idx + 1 >= len(OFFSEASON_STAGES):
        return None
    return OFFSEASON_STAGES[idx + 1]


def _stage_label(stage):
    return OFFSEASON_STAGE_LABELS.get(stage, stage.replace("_", " ").title())


def _names_preview(names, limit=8):
    if not names:
        return "None."
    preview = ", ".join(names[:limit])
    remaining = len(names) - limit
    if remaining > 0:
        preview += f", and {remaining} more"
    return preview + "."


def _record_offseason_event(conn, from_season, to_season, stage, headline, detail):
    conn.execute(
        "INSERT INTO offseason_events (from_season, to_season, stage, headline, detail) "
        "VALUES (?, ?, ?, ?, ?)",
        (from_season, to_season, stage, headline, detail),
    )


def _format_stage_summary(summary):
    stage = summary["stage"]
    if stage == "retirements":
        return f"{len(summary['retired'])} retired: {_names_preview(summary['retired'])}"
    if stage == "development":
        return (
            f"{summary['improved']} player(s) improved; "
            f"{summary['regressed']} player(s) regressed."
        )
    if stage == "contracts":
        return (
            f"{len(summary['extended'])} extension(s); "
            f"{len(summary['free_agents'])} player(s) entered free agency. "
            f"Extensions: {_names_preview(summary['extended'])} "
            f"Free agents: {_names_preview(summary['free_agents'])}"
        )
    if stage == "free_agency":
        return f"{len(summary['signed'])} free agent(s) signed: {_names_preview(summary['signed'])}"
    if stage == "draft":
        return f"{len(summary['rookies'])} rookie(s) added: {_names_preview(summary['rookies'])}"
    if stage == "finalize":
        return (
            f"Season {summary['to_season']} schedule created: "
            f"{summary['weeks']} weeks, {summary['games']} games."
        )
    if stage == "roster_finalization":
        return (
            f"Lineups finalized with {len(summary['rookies'])} late rookie addition(s). "
            f"{_names_preview(summary['rookies'])}"
        )
    return "Offseason stage completed."


def _ensure_offseason_started(conn, state):
    season_year = state["season_year"]
    phase = state["phase"] if "phase" in state.keys() else "regular_season"
    stage = state["offseason_stage"] if "offseason_stage" in state.keys() else None
    from_season = (
        state["offseason_from_season"]
        if "offseason_from_season" in state.keys() and state["offseason_from_season"]
        else season_year
    )

    if phase == "offseason":
        return from_season, stage or OFFSEASON_STAGES[0]

    if phase != "complete":
        raise RuntimeError("The offseason can only begin after the season is complete.")

    remaining = conn.execute(
        "SELECT COUNT(*) AS cnt FROM games WHERE season_year = ? AND played = 0",
        (season_year,),
    ).fetchone()["cnt"]
    if remaining:
        raise RuntimeError(
            f"Season {season_year} is not complete yet; {remaining} game(s) remain."
        )

    conn.execute(
        "UPDATE league_state "
        "SET phase = 'offseason', offseason_stage = ?, offseason_from_season = ?, "
        "last_updated = datetime('now') WHERE id = 1",
        (OFFSEASON_STAGES[0], season_year),
    )
    return season_year, OFFSEASON_STAGES[0]


def advance_offseason_step(conn, verbose=True):
    state = conn.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        raise RuntimeError("League not found. Run seed.py first.")

    season_year, stage = _ensure_offseason_started(conn, state)
    next_year = season_year + 1
    existing = conn.execute(
        "SELECT COUNT(*) AS cnt FROM games WHERE season_year = ?",
        (next_year,),
    ).fetchone()["cnt"]
    if existing:
        raise RuntimeError(f"Season {next_year} already exists.")

    salary_cap = _load_salary_cap()
    summary = {
        "from_season": season_year,
        "to_season": next_year,
        "stage": stage,
        "stage_label": _stage_label(stage),
    }

    if stage == "retirements":
        summary["retired"] = _resolve_retirements(conn, season_year)
    elif stage == "development":
        improved, regressed = _age_and_develop_players(conn)
        summary["improved"] = improved
        summary["regressed"] = regressed
    elif stage == "contracts":
        extended, free_agents = _process_contracts(conn, season_year, next_year, salary_cap)
        summary["extended"] = extended
        summary["free_agents"] = free_agents
    elif stage == "draft":
        summary["rookies"] = _draft_rookies_to_fill_rosters(conn, next_year, max_per_team=1)
    elif stage == "free_agency":
        summary["signed"] = _sign_free_agents_to_roster_holes(conn, next_year, salary_cap)
    elif stage == "roster_finalization":
        summary["rookies"] = _draft_rookies_to_fill_rosters(conn, next_year)
    elif stage == "finalize":
        conn.execute(
            "UPDATE pending_trades SET status = 'expired', "
            "rejection_reason = 'Expired before offseason rollover.' "
            "WHERE season_year = ? AND status = 'pending'",
            (season_year,),
        )
        conn.execute(
            "UPDATE player_events SET status = 'resolved' "
            "WHERE season_year <= ? AND status = 'active'",
            (season_year,),
        )
        total_weeks, games = _create_next_season(conn, next_year)
        summary["weeks"] = total_weeks
        summary["games"] = games
    else:
        raise RuntimeError(f"Unknown offseason stage: {stage}")

    detail = _format_stage_summary(summary)
    summary["detail"] = detail
    next_stage = _next_stage(stage)
    summary["next_stage"] = next_stage
    summary["next_stage_label"] = _stage_label(next_stage) if next_stage else None

    _record_offseason_event(
        conn,
        season_year,
        next_year,
        stage,
        f"{_stage_label(stage)} complete",
        detail,
    )

    if next_stage:
        conn.execute(
            "UPDATE league_state "
            "SET phase = 'offseason', offseason_stage = ?, offseason_from_season = ?, "
            "last_updated = datetime('now') WHERE id = 1",
            (next_stage, season_year),
        )
    else:
        conn.execute(
            "UPDATE league_state "
            "SET current_week = 1, season_year = ?, phase = 'regular_season', "
            "offseason_stage = NULL, offseason_from_season = NULL, "
            "last_updated = datetime('now') WHERE id = 1",
            (next_year,),
        )
    conn.commit()

    if verbose:
        print_offseason_step_summary(summary)
    return summary


def advance_offseason(conn, verbose=True):
    return advance_offseason_step(conn, verbose=verbose)


def print_offseason_step_summary(summary):
    print(f"\n{'=' * 58}")
    print(
        f"  OFFSEASON: {summary['from_season']} -> {summary['to_season']}  "
        f"--  {summary['stage_label']}"
    )
    print(f"{'=' * 58}\n")
    print(f"  {summary['detail']}\n")
    if summary["next_stage"]:
        print(f"Next offseason stage: {summary['next_stage_label']}")
        print("Run  python run_offseason.py  to advance one more stage.\n")
    else:
        print(f"Season {summary['to_season']} is ready. Run  python run_week.py  for Week 1.\n")


def print_offseason_summary(summary):
    print_offseason_step_summary(summary)


def advance_offseason_from_default_db(verbose=True):
    create_tables()
    conn = get_connection()
    try:
        return advance_offseason(conn, verbose=verbose)
    finally:
        conn.close()
