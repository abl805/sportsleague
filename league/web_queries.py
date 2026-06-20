import json
import math

from league.database import get_connection
from league.fan_experience import (
    adjusted_roster_for_game,
    build_pregame_broadcast,
    build_quarter_recaps,
    get_active_coach,
)
from league.simulation import build_coach_rotation


def dicts(rows):
    return [dict(row) for row in rows]


def one(row):
    return dict(row) if row else None


def full_name(row):
    return f"{row['city']} {row['name']}"


def get_state(conn):
    return one(conn.execute("SELECT * FROM league_state WHERE id = 1").fetchone())


def get_site_chrome(conn):
    return {
        "state": get_state(conn),
        "teams": dicts(conn.execute(
            "SELECT id, city, name, abbreviation FROM teams ORDER BY city"
        ).fetchall()),
    }


def get_games_played(conn, season_year):
    return conn.execute(
        "SELECT COUNT(*) FROM games WHERE played = 1 AND season_year = ?",
        (season_year,),
    ).fetchone()[0]


def get_max_week(conn, season_year):
    row = conn.execute(
        "SELECT MAX(week) AS max_week FROM games WHERE season_year = ?",
        (season_year,),
    ).fetchone()
    return row["max_week"] or 0


def get_played_weeks(conn, season_year):
    return [
        row["week"]
        for row in conn.execute("""
            SELECT DISTINCT week
            FROM games
            WHERE season_year = ? AND played = 1
            ORDER BY week DESC
        """, (season_year,)).fetchall()
    ]


def standings(conn, season_year, limit=None):
    sql = """
        SELECT t.id AS team_id,
               t.city,
               t.name,
               t.abbreviation,
               t.colors,
               s.wins,
               s.losses,
               s.points_for,
               s.points_against,
               s.points_for - s.points_against AS point_diff
        FROM standings s
        JOIN teams t ON t.id = s.team_id
        WHERE s.season_year = ?
        ORDER BY s.wins DESC, point_diff DESC, s.points_for DESC
    """
    params = [season_year]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    rows = dicts(conn.execute(sql, params).fetchall())
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
        row["team_name"] = f"{row['city']} {row['name']}"
        games = row["wins"] + row["losses"]
        row["win_pct"] = row["wins"] / games if games else 0
    return rows


def stat_leaders(conn, season_year, limit=10, order_by="ppg"):
    valid_orders = {
        "ppg": "ppg DESC",
        "rpg": "rpg DESC",
        "apg": "apg DESC",
        "spg": "spg DESC",
        "bpg": "bpg DESC",
    }
    order_sql = valid_orders.get(order_by, valid_orders["ppg"])
    rows = dicts(conn.execute(f"""
        SELECT p.id,
               p.first_name || ' ' || p.last_name AS player,
               p.position,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation,
               ROUND(AVG(pgs.points), 1) AS ppg,
               ROUND(AVG(pgs.rebounds), 1) AS rpg,
               ROUND(AVG(pgs.assists), 1) AS apg,
               ROUND(AVG(pgs.steals), 1) AS spg,
               ROUND(AVG(pgs.blocks), 1) AS bpg,
               COUNT(pgs.id) AS games_played
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        JOIN players p ON p.id = pgs.player_id
        JOIN teams t ON t.id = p.team_id
        WHERE g.season_year = ?
        GROUP BY p.id
        HAVING games_played >= 1
        ORDER BY {order_sql}
        LIMIT ?
    """, (season_year, limit)).fetchall())
    for index, row in enumerate(rows, start=1):
        row["rank"] = index
    return rows


def latest_results(conn, season_year, limit=8):
    return dicts(conn.execute("""
        SELECT g.id,
               g.week,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ? AND g.played = 1
        ORDER BY g.week DESC, g.id DESC
        LIMIT ?
    """, (season_year, limit)).fetchall())


def games_for_week(conn, season_year, week=None):
    if week is None:
        week = conn.execute("""
            SELECT MAX(week) AS week
            FROM games
            WHERE season_year = ? AND played = 1
        """, (season_year,)).fetchone()["week"]
    if week is None:
        return None, []
    rows = dicts(conn.execute("""
        SELECT g.id,
               g.week,
               g.played,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ? AND g.week = ?
        ORDER BY g.id
    """, (season_year, week)).fetchall())
    return week, rows


def teams_index(conn, season_year):
    rows = dicts(conn.execute("""
        SELECT t.id,
               t.city,
               t.name,
               t.abbreviation,
               t.colors,
               t.motto,
               t.arena,
               t.play_style,
               t.team_archetype,
               t.reputation,
               t.rivalry,
               t.signature_trait,
               t.fan_pitch,
               t.pressure_label,
               t.rivalry_intensity,
               s.wins,
               s.losses,
               s.points_for - s.points_against AS point_diff,
               tc.chemistry
        FROM teams t
        LEFT JOIN standings s ON s.team_id = t.id AND s.season_year = ?
        LEFT JOIN team_chemistry tc ON tc.team_id = t.id
            AND tc.season_year = ?
            AND tc.week = (
                SELECT MAX(week)
                FROM team_chemistry
                WHERE team_id = t.id AND season_year = ?
            )
        ORDER BY t.city
    """, (season_year, season_year, season_year)).fetchall())
    for row in rows:
        row["team_name"] = f"{row['city']} {row['name']}"
    return rows


def team_detail(conn, abbreviation, season_year):
    team = one(conn.execute("""
        SELECT *
        FROM teams
        WHERE UPPER(abbreviation) = UPPER(?)
    """, (abbreviation,)).fetchone())
    if not team:
        return None

    team_id = team["id"]
    record = one(conn.execute("""
        SELECT wins, losses, points_for, points_against,
               points_for - points_against AS point_diff
        FROM standings
        WHERE team_id = ? AND season_year = ?
    """, (team_id, season_year)).fetchone())
    roster = dicts(conn.execute("""
        SELECT p.id,
               p.first_name || ' ' || p.last_name AS player,
               p.position,
               p.age,
               p.skill_rating,
               p.salary,
               c.years_remaining
        FROM players p
        LEFT JOIN contracts c ON c.player_id = p.id
        WHERE p.team_id = ? AND COALESCE(p.status, 'active') = 'active'
        ORDER BY p.skill_rating DESC, p.last_name
    """, (team_id,)).fetchall())
    recent_games = dicts(conn.execute("""
        SELECT g.id,
               g.week,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ?
          AND g.played = 1
          AND (g.home_team_id = ? OR g.away_team_id = ?)
        ORDER BY g.week DESC, g.id DESC
        LIMIT 8
    """, (season_year, team_id, team_id)).fetchall())
    schedule = dicts(conn.execute("""
        SELECT g.id,
               g.week,
               g.played,
               CASE WHEN g.home_team_id = ? THEN at.city || ' ' || at.name ELSE ht.city || ' ' || ht.name END AS opponent,
               CASE WHEN g.home_team_id = ? THEN 'Home' ELSE 'Away' END AS site,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ?
          AND (g.home_team_id = ? OR g.away_team_id = ?)
        ORDER BY g.week
    """, (team_id, team_id, season_year, team_id, team_id)).fetchall())
    events = dicts(conn.execute("""
        SELECT pe.week,
               pe.event_type,
               pe.status,
               pe.detail,
               p.first_name || ' ' || p.last_name AS player
        FROM player_events pe
        JOIN players p ON p.id = pe.player_id
        WHERE p.team_id = ? AND pe.season_year = ?
        ORDER BY pe.week DESC, pe.id DESC
        LIMIT 8
    """, (team_id, season_year)).fetchall())
    chemistry = one(conn.execute("""
        SELECT chemistry, week
        FROM team_chemistry
        WHERE team_id = ? AND season_year = ?
        ORDER BY week DESC
        LIMIT 1
    """, (team_id, season_year)).fetchone())

    gm = one(conn.execute("""
        SELECT name, archetype, risk_tolerance, veteran_loyalty,
               youth_preference, trade_frequency
        FROM general_managers
        WHERE team_id = ?
    """, (team_id,)).fetchone())

    coach = one(conn.execute("""
        SELECT id, name, strategy, development, leadership,
               pressure_handling, pace_preference, rotation_tightness,
               lineup_preference, job_security, hired_season
        FROM head_coaches
        WHERE team_id = ? AND status = 'active'
        ORDER BY id DESC LIMIT 1
    """, (team_id,)).fetchone())
    if coach:
        tightness = coach["rotation_tightness"]
        coach["rotation_size"] = (
            7 if tightness >= 0.75
            else 8 if tightness >= 0.55
            else 9 if tightness >= 0.35
            else 10
        )
        coach["pace_label"] = (
            "Fast" if coach["pace_preference"] >= 0.72
            else "Deliberate" if coach["pace_preference"] <= 0.38
            else "Balanced"
        )

    injuries = dicts(conn.execute("""
        SELECT i.*, p.first_name || ' ' || p.last_name AS player_name
        FROM player_injuries i
        JOIN players p ON p.id=i.player_id
        WHERE p.team_id=? AND i.status='active'
        ORDER BY i.skill_penalty DESC
    """, (team_id,)).fetchall())

    team_leaders = dicts(conn.execute("""
        SELECT p.id,
               p.first_name || ' ' || p.last_name AS player,
               p.position,
               ROUND(AVG(pgs.points), 1)   AS ppg,
               ROUND(AVG(pgs.rebounds), 1) AS rpg,
               ROUND(AVG(pgs.assists), 1)  AS apg,
               ROUND(AVG(pgs.steals), 1)   AS spg,
               ROUND(AVG(pgs.blocks), 1)   AS bpg,
               COUNT(pgs.id) AS gp
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        JOIN players p ON p.id = pgs.player_id
        WHERE p.team_id = ? AND g.season_year = ?
        GROUP BY p.id
        ORDER BY ppg DESC
    """, (team_id, season_year)).fetchall())

    articles = articles_for_team(conn, team_id, season_year)
    interviews = dicts(conn.execute("""
        SELECT pi.id, pi.week, pi.question, pi.response,
               p.id AS player_id,
               p.first_name || ' ' || p.last_name AS player_name,
               pb.personality_label
        FROM player_interviews pi
        JOIN players p ON p.id = pi.player_id
        LEFT JOIN player_backstories pb ON pb.player_id = pi.player_id
        WHERE p.team_id = ? AND pi.season_year = ? AND pi.response IS NOT NULL
        ORDER BY pi.id DESC
        LIMIT 6
    """, (team_id, season_year)).fetchall())
    editorial_quotes = dicts(conn.execute("""
        SELECT eq.quote_text, eq.speaker_type, eq.game_id, wep.week,
               CASE
                 WHEN eq.speaker_type='coach' THEN hc.name
                 WHEN eq.speaker_type='gm' THEN gm.name
                 ELSE NULL
               END AS speaker_name
        FROM editorial_quotes eq
        JOIN weekly_editorial_packages wep ON wep.id=eq.package_id
        LEFT JOIN head_coaches hc ON eq.speaker_type='coach' AND hc.id=eq.speaker_id
        LEFT JOIN general_managers gm ON eq.speaker_type='gm' AND gm.id=eq.speaker_id
        WHERE wep.season_year=? AND (
          (eq.speaker_type='coach' AND hc.team_id=?)
          OR (eq.speaker_type='gm' AND gm.team_id=?)
        )
        ORDER BY eq.id DESC LIMIT 6
    """, (season_year, team_id, team_id)).fetchall())
    named_rivalries = dicts(conn.execute("""
        SELECT rn.name, rn.season_year, rn.week,
               CASE WHEN rn.team_a_id=? THEN tb.city || ' ' || tb.name
                    ELSE ta.city || ' ' || ta.name END AS opponent
        FROM rivalry_names rn
        JOIN teams ta ON ta.id=rn.team_a_id
        JOIN teams tb ON tb.id=rn.team_b_id
        WHERE rn.status='active' AND (rn.team_a_id=? OR rn.team_b_id=?)
        ORDER BY rn.id DESC
    """, (team_id, team_id, team_id)).fetchall())
    rivalry_dynamics = dicts(conn.execute("""
        SELECT tr.id, tr.base_intensity, tr.current_intensity,
               tr.meetings, tr.close_games, tr.playoff_meetings,
               tr.trade_count, tr.last_season, tr.last_week, tr.last_event,
               CASE WHEN tr.team_a_id=? THEN tb.id ELSE ta.id END AS opponent_id,
               CASE WHEN tr.team_a_id=? THEN tb.city || ' ' || tb.name
                    ELSE ta.city || ' ' || ta.name END AS opponent,
               CASE WHEN tr.team_a_id=? THEN tb.abbreviation
                    ELSE ta.abbreviation END AS opponent_abbr,
               rn.name AS fan_name
        FROM team_rivalries tr
        JOIN teams ta ON ta.id=tr.team_a_id
        JOIN teams tb ON tb.id=tr.team_b_id
        LEFT JOIN rivalry_names rn
          ON rn.team_a_id=tr.team_a_id AND rn.team_b_id=tr.team_b_id
         AND rn.status='active'
        WHERE tr.team_a_id=? OR tr.team_b_id=?
        ORDER BY tr.current_intensity DESC, tr.meetings DESC
    """, (team_id, team_id, team_id, team_id, team_id)).fetchall())
    for rivalry in rivalry_dynamics:
        intensity = rivalry["current_intensity"]
        rivalry["tier"] = (
            "Blood Feud" if intensity >= 0.85
            else "Fierce" if intensity >= 0.68
            else "Heated" if intensity >= 0.48
            else "Building" if intensity >= 0.28
            else "Dormant"
        )

    return {
        "team": team,
        "record": record,
        "roster": roster,
        "recent_games": recent_games,
        "schedule": schedule,
        "events": events,
        "chemistry": chemistry,
        "gm": gm,
        "coach": coach,
        "injuries": injuries,
        "team_leaders": team_leaders,
        "articles": articles,
        "interviews": interviews,
        "editorial_quotes": editorial_quotes,
        "named_rivalries": named_rivalries,
        "rivalry_dynamics": rivalry_dynamics,
    }


def players_index(conn, team_id=None):
    params = []
    where = "WHERE COALESCE(p.status, 'active') = 'active'"
    if team_id:
        where += " AND p.team_id = ?"
        params.append(team_id)
    return dicts(conn.execute(f"""
        SELECT p.id,
               p.first_name || ' ' || p.last_name AS player,
               p.position,
               p.age,
               p.skill_rating,
               p.salary,
               t.id AS team_id,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation,
               c.years_remaining
        FROM players p
        JOIN teams t ON t.id = p.team_id
        LEFT JOIN contracts c ON c.player_id = p.id
        {where}
        ORDER BY p.skill_rating DESC, p.last_name
    """, params).fetchall())


def player_detail(conn, player_id, season_year):
    player = one(conn.execute("""
        SELECT p.*,
               p.first_name || ' ' || p.last_name AS player,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation,
               c.years_remaining,
               pp.archetype,
               pp.ambition,
               pp.loyalty,
               pp.ego,
               pp.work_ethic,
               pp.volatility,
               pp.leadership,
               pp.clutch,
               pp.durability,
               pp.media_reputation,
               pb.college_state,
               pb.hometown_state,
               pb.personality_label,
               pb.backstory_blurb
        FROM players p
        JOIN teams t ON t.id = p.team_id
        LEFT JOIN contracts c ON c.player_id = p.id
        LEFT JOIN player_personalities pp ON pp.player_id = p.id
        LEFT JOIN player_backstories pb ON pb.player_id = p.id
        WHERE p.id = ?
    """, (player_id,)).fetchone())
    if not player:
        return None
    averages = one(conn.execute("""
        SELECT ROUND(AVG(pgs.points), 1) AS ppg,
               ROUND(AVG(pgs.rebounds), 1) AS rpg,
               ROUND(AVG(pgs.assists), 1) AS apg,
               ROUND(AVG(pgs.steals), 1) AS spg,
               ROUND(AVG(pgs.blocks), 1) AS bpg,
               COUNT(pgs.id) AS games_played
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        WHERE pgs.player_id = ? AND g.season_year = ?
    """, (player_id, season_year)).fetchone())
    game_log = dicts(conn.execute("""
        SELECT g.id AS game_id,
               g.week,
               CASE WHEN pgs.team_id = g.home_team_id THEN at.abbreviation ELSE ht.abbreviation END AS opponent,
               pgs.points,
               pgs.rebounds,
               pgs.assists,
               pgs.steals,
               pgs.blocks
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE pgs.player_id = ? AND g.season_year = ?
        ORDER BY g.week DESC, g.id DESC
    """, (player_id, season_year)).fetchall())
    events = dicts(conn.execute("""
        SELECT week, event_type, status, detail
        FROM player_events
        WHERE player_id = ? AND season_year = ?
        ORDER BY week DESC, id DESC
        LIMIT 10
    """, (player_id, season_year)).fetchall())
    morale = one(conn.execute("""
        SELECT morale, week
        FROM player_morale
        WHERE player_id = ? AND season_year = ?
        ORDER BY week DESC
        LIMIT 1
    """, (player_id, season_year)).fetchone())
    articles = articles_for_player(conn, player_id, season_year)
    interviews = dicts(conn.execute("""
        SELECT pi.id, pi.week, pi.question, pi.response, pi.created_at
        FROM player_interviews pi
        WHERE pi.player_id = ? AND pi.season_year = ?
          AND pi.response IS NOT NULL
        ORDER BY pi.id DESC
        LIMIT 10
    """, (player_id, season_year)).fetchall())
    editorial_quotes = dicts(conn.execute("""
        SELECT eq.quote_text, eq.game_id, wep.week
        FROM editorial_quotes eq
        JOIN weekly_editorial_packages wep ON wep.id=eq.package_id
        WHERE eq.speaker_type='player' AND eq.speaker_id=?
          AND wep.season_year=?
        ORDER BY eq.id DESC LIMIT 8
    """, (player_id, season_year)).fetchall())

    arc = one(conn.execute("""
        SELECT arc_type, title, summary, started_season, updated_week
        FROM player_arcs WHERE player_id=?
    """, (player_id,)).fetchone())
    injuries = dicts(conn.execute("""
        SELECT season_year, week_start, expected_return_week, severity,
               status, description, ic.outcome_type, ic.skill_loss,
               ic.durability_loss, ic.recovery_ceiling, ic.skill_restored,
               ic.games_since_return, ic.comeback_status, ic.summary,
               ic.resolved_season, ic.resolved_week
        FROM player_injuries i
        LEFT JOIN injury_consequences ic ON ic.injury_id=i.id
        WHERE i.player_id=?
        ORDER BY i.season_year DESC, i.week_start DESC
        LIMIT 8
    """, (player_id,)).fetchall())
    active_comeback = one(conn.execute("""
        SELECT ic.*, i.description,
               (ic.recovery_ceiling-ic.skill_restored) AS points_remaining
        FROM injury_consequences ic
        JOIN player_injuries i ON i.id=ic.injury_id
        WHERE ic.player_id=? AND ic.comeback_status='active'
        ORDER BY ic.id DESC LIMIT 1
    """, (player_id,)).fetchone())
    relationships = dicts(conn.execute("""
        SELECT pr.relationship_type, pr.intensity, pr.detail,
               op.first_name || ' ' || op.last_name AS other_player,
               t.city || ' ' || t.name AS former_team
        FROM player_relationships pr
        LEFT JOIN players op ON op.id=pr.target_player_id
        LEFT JOIN teams t ON t.id=pr.origin_team_id
        WHERE pr.player_id=? AND pr.status='active'
        ORDER BY pr.intensity DESC, pr.id DESC
        LIMIT 10
    """, (player_id,)).fetchall())
    awards = dicts(conn.execute("""
        SELECT season_year, week, award_type, label, detail
        FROM awards
        WHERE entity_type='player' AND entity_id=?
        ORDER BY season_year DESC, week DESC
    """, (player_id,)).fetchall())
    career = one(conn.execute("""
        SELECT COUNT(*) AS games,
               SUM(points) AS points,
               SUM(rebounds) AS rebounds,
               SUM(assists) AS assists,
               MAX(points) AS career_high
        FROM player_game_stats
        WHERE player_id=?
    """, (player_id,)).fetchone())
    records = dicts(conn.execute("""
        SELECT rbe.*, t.abbreviation,
               CASE rbe.scope
                 WHEN 'single_game' THEN 'Single-game'
                 WHEN 'season' THEN 'Single-season'
                 ELSE 'Career'
               END AS scope_label
        FROM record_book_entries rbe
        LEFT JOIN teams t ON t.id=rbe.team_id
        WHERE rbe.player_id=?
        ORDER BY rbe.is_current DESC,
                 CASE rbe.scope
                   WHEN 'single_game' THEN 1
                   WHEN 'season' THEN 2
                   ELSE 3
                 END,
                 rbe.value DESC, rbe.id DESC
    """, (player_id,)).fetchall())

    return {
        "player": player,
        "averages": averages,
        "game_log": game_log,
        "events": events,
        "morale": morale,
        "articles": articles,
        "interviews": interviews,
        "editorial_quotes": editorial_quotes,
        "arc": arc,
        "injuries": injuries,
        "active_comeback": active_comeback,
        "relationships": relationships,
        "awards": awards,
        "career": career,
        "records": records,
    }


def game_detail(conn, game_id):
    game = one(conn.execute("""
        SELECT g.*,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.id = ?
    """, (game_id,)).fetchone())
    if not game:
        return None
    box = dicts(conn.execute("""
        SELECT p.first_name || ' ' || p.last_name AS player,
               p.id AS player_id,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation,
               p.position,
               pgs.minutes,
               pgs.started,
               pgs.rotation_role,
               pgs.points,
               pgs.rebounds,
               pgs.assists,
               pgs.steals,
               pgs.blocks,
               p.skill_rating
        FROM player_game_stats pgs
        JOIN players p ON p.id = pgs.player_id
        JOIN teams t ON t.id = pgs.team_id
        WHERE pgs.game_id = ?
        ORDER BY t.id, pgs.started DESC, pgs.minutes DESC, pgs.points DESC
    """, (game_id,)).fetchall())
    mvp = None
    if box:
        mvp = max(box, key=lambda r: (
            r["points"] + r["rebounds"] * 0.75 + r["assists"] * 0.5
            + r["steals"] * 1.5 + r["blocks"] * 1.0
        ))
    explanation = one(conn.execute("""
        SELECT * FROM game_explanations WHERE game_id=?
    """, (game_id,)).fetchone())
    if explanation and explanation.get("key_factors_json"):
        try:
            explanation["key_factors"] = json.loads(explanation["key_factors_json"])
        except (TypeError, json.JSONDecodeError):
            explanation["key_factors"] = {}
    broadcast = one(conn.execute(
        "SELECT * FROM game_broadcasts WHERE game_id=?",
        (game_id,),
    ).fetchone())
    if broadcast:
        try:
            broadcast["cards"] = json.loads(
                broadcast.get("pregame_cards_json") or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            broadcast["cards"] = []
        try:
            broadcast["quarter_recaps"] = json.loads(
                broadcast.get("quarter_recaps_json") or "[]"
            )
        except (TypeError, json.JSONDecodeError):
            broadcast["quarter_recaps"] = []
    else:
        generated = build_pregame_broadcast(conn, game)
        broadcast = {
            "pregame_headline": generated["headline"],
            "pregame_storyline": generated["storyline"],
            "cards": generated["cards"],
            "quarter_recaps": [],
            "generated_before_tip": 0,
        }
    if game["played"] and not broadcast["quarter_recaps"]:
        broadcast["quarter_recaps"] = build_quarter_recaps(
            game,
            [game[f"q{quarter}_home"] for quarter in range(1, 5)],
            [game[f"q{quarter}_away"] for quarter in range(1, 5)],
        )
    team_stats = dicts(conn.execute("""
        SELECT tgs.*, t.abbreviation, t.city || ' ' || t.name AS team_name
        FROM team_game_stats tgs
        JOIN teams t ON t.id=tgs.team_id
        WHERE tgs.game_id=?
        ORDER BY tgs.team_id
    """, (game_id,)).fetchall())
    projected_starters = []
    rotation_plans = []
    preview_lineups = {}
    if game["played"]:
        rotation_plans = dicts(conn.execute("""
            SELECT gr.*, hc.name AS coach_name,
                   t.abbreviation,
                   t.city || ' ' || t.name AS team_name
            FROM game_rotations gr
            JOIN teams t ON t.id=gr.team_id
            LEFT JOIN head_coaches hc ON hc.id=gr.coach_id
            WHERE gr.game_id=?
            ORDER BY CASE WHEN gr.team_id=? THEN 0 ELSE 1 END
        """, (game_id, game["away_team_id"])).fetchall())
        for plan in rotation_plans:
            try:
                starter_ids = set(json.loads(plan["starter_ids_json"]))
                rotation_ids = set(json.loads(plan["rotation_ids_json"]))
            except (TypeError, json.JSONDecodeError):
                starter_ids, rotation_ids = set(), set()
            plan["starters"] = [
                row for row in box if row["player_id"] in starter_ids
            ]
            plan["reserves"] = [
                row for row in box
                if row["player_id"] in rotation_ids
                and row["player_id"] not in starter_ids
            ]
    else:
        for team_id, abbreviation, team_name in (
            (game["away_team_id"], game["away_abbr"], game["away_name"]),
            (game["home_team_id"], game["home_abbr"], game["home_name"]),
        ):
            roster, _, _ = adjusted_roster_for_game(
                conn, team_id, game["season_year"], game["week"]
            )
            coach = get_active_coach(conn, team_id)
            selected, metadata = build_coach_rotation(roster, coach)
            preview_lineups[team_id] = (selected, coach, metadata)
            starters = [
                {
                    "id": player["id"],
                    "player_id": player["id"],
                    "player": f"{player['first_name']} {player['last_name']}",
                    "position": player["position"],
                    "skill_rating": player["skill_rating"],
                    "abbreviation": abbreviation,
                    "minutes": player["minutes"],
                }
                for player in selected if player["started"]
            ]
            projected_starters.extend(starters)
            rotation_plans.append({
                **metadata,
                "team_id": team_id,
                "abbreviation": abbreviation,
                "team_name": team_name,
                "coach_name": metadata["coach_name"],
                "starters": starters,
                "reserves": [
                    {
                        "id": player["id"],
                        "player_id": player["id"],
                        "player": f"{player['first_name']} {player['last_name']}",
                        "position": player["position"],
                        "minutes": player["minutes"],
                    }
                    for player in selected if player["rotation_role"] == "reserve"
                ],
            })
    injuries = dicts(conn.execute("""
        SELECT i.*, p.first_name || ' ' || p.last_name AS player_name,
               t.abbreviation
        FROM player_injuries i
        JOIN players p ON p.id=i.player_id
        JOIN teams t ON t.id=p.team_id
        WHERE p.team_id IN (?, ?) AND i.season_year=? AND i.status='active'
          AND i.week_start<=? AND i.expected_return_week>=?
        ORDER BY i.skill_penalty DESC
    """, (
        game["home_team_id"], game["away_team_id"], game["season_year"],
        game["week"], game["week"],
    )).fetchall())
    next_matchups = dicts(conn.execute("""
        SELECT g.id, g.week,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               g.played, g.home_score, g.away_score
        FROM games g
        JOIN teams ht ON ht.id=g.home_team_id
        JOIN teams at ON at.id=g.away_team_id
        WHERE g.season_year=? AND g.week>?
          AND (g.home_team_id IN (?, ?) OR g.away_team_id IN (?, ?))
        ORDER BY g.week, g.id LIMIT 2
    """, (
        game["season_year"], game["week"], game["home_team_id"],
        game["away_team_id"], game["home_team_id"], game["away_team_id"],
    )).fetchall())
    quotes = editorial_quotes_for_game(conn, game_id)
    rivalry = one(conn.execute("""
        SELECT tr.*,
               rn.name AS fan_name
        FROM team_rivalries tr
        LEFT JOIN rivalry_names rn
          ON rn.team_a_id=tr.team_a_id AND rn.team_b_id=tr.team_b_id
         AND rn.status='active'
        WHERE tr.team_a_id=? AND tr.team_b_id=?
    """, tuple(sorted((game["home_team_id"], game["away_team_id"])))).fetchone())
    if rivalry:
        intensity = rivalry["current_intensity"]
        rivalry["tier"] = (
            "Blood Feud" if intensity >= 0.85
            else "Fierce" if intensity >= 0.68
            else "Heated" if intensity >= 0.48
            else "Building" if intensity >= 0.28
            else "Dormant"
        )
        rivalry["events"] = dicts(conn.execute("""
            SELECT season_year, week, event_type, intensity_before,
                   intensity_after, detail, game_id, trade_id
            FROM rivalry_events
            WHERE rivalry_id=?
            ORDER BY id DESC LIMIT 5
        """, (rivalry["id"],)).fetchall())
    preview = None
    if not game["played"]:
        def power(team_id):
            roster, coach, rotation = preview_lineups[team_id]
            active = [player for player in roster if player["minutes"] > 0]
            skills = sorted(
                [player["skill_rating"] for player in active], reverse=True
            ) or [60]
            avg = sum(
                player["skill_rating"] * player["minutes"]
                for player in active
            ) / max(1, sum(player["minutes"] for player in active))
            top = sum(skills[:3]) / min(3, len(skills))
            coach_edge = 0.0
            if coach:
                coach_edge = (
                    (coach["leadership"] - 0.5) * 2.2
                    + (coach["pressure_handling"] - 0.5) * 1.6
                    + rotation["rotation_fit"]
                )
            return avg * 0.67 + top * 0.25 + coach_edge, coach
        home_power, home_coach = power(game["home_team_id"])
        away_power, away_coach = power(game["away_team_id"])
        margin = (home_power - away_power) * 0.62 + 2.25
        preview = {
            "home_win_probability": 1.0 / (1.0 + math.exp(-margin / 6.2)),
            "expected_margin": margin,
            "strategy_matchup": (
                f"{(away_coach or {}).get('strategy', 'balanced').replace('_', ' ')} "
                f"against {(home_coach or {}).get('strategy', 'balanced').replace('_', ' ')}"
            ),
        }
    return {
        "game": game,
        "box": box,
        "mvp": mvp,
        "explanation": explanation,
        "broadcast": broadcast,
        "team_stats": team_stats,
        "projected_starters": projected_starters,
        "rotation_plans": rotation_plans,
        "injuries": injuries,
        "next_matchups": next_matchups,
        "quotes": quotes,
        "preview": preview,
        "rivalry": rivalry,
    }


def articles_for_team(conn, team_id, season_year, limit=8):
    return dicts(conn.execute("""
        SELECT a.id, a.week, a.season_year, a.headline, a.body, a.created_at
        FROM articles a
        JOIN article_tags tag ON tag.article_id = a.id
        WHERE tag.tag_type = 'team' AND tag.tag_id = ? AND a.season_year = ?
        ORDER BY a.week DESC, a.id DESC
        LIMIT ?
    """, (team_id, season_year, limit)).fetchall())


def articles_for_player(conn, player_id, season_year, limit=8):
    return dicts(conn.execute("""
        SELECT a.id, a.week, a.season_year, a.headline, a.body, a.created_at
        FROM articles a
        JOIN article_tags tag ON tag.article_id = a.id
        WHERE tag.tag_type = 'player' AND tag.tag_id = ? AND a.season_year = ?
        ORDER BY a.week DESC, a.id DESC
        LIMIT ?
    """, (player_id, season_year, limit)).fetchall())


def recent_articles(conn, season_year, limit=20):
    return dicts(conn.execute("""
        SELECT id, week, season_year, headline, body, story_role,
               editorial_package_id, created_at
        FROM articles
        WHERE season_year = ?
        ORDER BY week DESC,
                 CASE story_role WHEN 'lead' THEN 0 WHEN 'support' THEN 1 ELSE 2 END,
                 id DESC
        LIMIT ?
    """, (season_year, limit)).fetchall())


def public_storylines(conn, season_year, limit=20):
    events = dicts(conn.execute("""
        SELECT 'event' AS source,
               pe.id,
               pe.week,
               pe.event_type AS type,
               pe.status,
               pe.detail,
               p.first_name || ' ' || p.last_name AS primary_name,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation,
               pe.created_at
        FROM player_events pe
        JOIN players p ON p.id = pe.player_id
        JOIN teams t ON t.id = p.team_id
        WHERE pe.season_year = ?
        ORDER BY pe.week DESC, pe.id DESC
        LIMIT ?
    """, (season_year, limit)).fetchall())

    trades = dicts(conn.execute("""
        SELECT 'trade' AS source,
               pt.id,
               pt.week,
               pt.status AS type,
               pt.status,
               pteam.city || ' ' || pteam.name || ' and ' ||
               rteam.city || ' ' || rteam.name || ' completed a trade.' AS detail,
               'Trade #' || pt.id AS primary_name,
               pteam.city || ' ' || pteam.name AS team_name,
               pteam.abbreviation,
               pt.created_at
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        JOIN teams pteam ON pteam.id = pgm.team_id
        JOIN teams rteam ON rteam.id = rgm.team_id
        WHERE pt.season_year = ? AND pt.status = 'approved'
        ORDER BY pt.week DESC, pt.id DESC
        LIMIT ?
    """, (season_year, limit)).fetchall())

    combined = events + trades
    combined.sort(key=lambda item: (item.get("week") or 0, item.get("id") or 0), reverse=True)
    return combined[:limit]


def pending_trades(conn):
    rows = dicts(conn.execute("""
        SELECT pt.*,
               pteam.city || ' ' || pteam.name AS proposing_team,
               rteam.city || ' ' || rteam.name AS receiving_team,
               pgm.name AS proposing_gm,
               rgm.name AS receiving_gm
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        JOIN teams pteam ON pteam.id = pgm.team_id
        JOIN teams rteam ON rteam.id = rgm.team_id
        WHERE pt.status = 'pending'
        ORDER BY pt.week, pt.id
    """).fetchall())
    for row in rows:
        row["offered_players"] = players_for_ids(conn, json.loads(row["offered_player_ids"]))
        row["requested_players"] = players_for_ids(conn, json.loads(row["requested_player_ids"]))
    return rows


def trade_options(conn):
    return dicts(conn.execute("""
        SELECT pt.id,
               pt.week,
               pteam.city || ' ' || pteam.name AS proposing_team,
               rteam.city || ' ' || rteam.name AS receiving_team
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        JOIN teams pteam ON pteam.id = pgm.team_id
        JOIN teams rteam ON rteam.id = rgm.team_id
        WHERE pt.status = 'pending'
        ORDER BY pt.week, pt.id
    """).fetchall())


def players_for_ids(conn, ids):
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return dicts(conn.execute(f"""
        SELECT p.id,
               p.first_name || ' ' || p.last_name AS player,
               p.position,
               p.age,
               p.skill_rating,
               p.salary,
               t.abbreviation
        FROM players p
        JOIN teams t ON t.id = p.team_id
        WHERE p.id IN ({placeholders})
        ORDER BY p.skill_rating DESC
    """, ids).fetchall())


def commissioner_logs(conn, limit=24):
    gm_logs = dicts(conn.execute("""
        SELECT 'GM' AS source,
               am.week,
               am.season_year,
               am.event_type,
               am.detail,
               gm.name AS actor,
               t.abbreviation,
               am.created_at
        FROM agent_memory am
        JOIN general_managers gm ON gm.id = am.gm_id
        JOIN teams t ON t.id = gm.team_id
        ORDER BY am.id DESC
        LIMIT ?
    """, (limit,)).fetchall())
    player_logs = dicts(conn.execute("""
        SELECT 'Player' AS source,
               pm.week,
               pm.season_year,
               pm.event_type,
               pm.detail,
               p.first_name || ' ' || p.last_name AS actor,
               t.abbreviation,
               pm.created_at
        FROM player_memory pm
        JOIN players p ON p.id = pm.player_id
        JOIN teams t ON t.id = p.team_id
        ORDER BY pm.id DESC
        LIMIT ?
    """, (limit,)).fetchall())
    combined = gm_logs + player_logs
    combined.sort(key=lambda row: row.get("created_at") or "", reverse=True)
    return combined[:limit]


def offseason_events(conn, limit=12):
    return dicts(conn.execute("""
        SELECT id,
               from_season,
               to_season,
               stage,
               headline,
               detail,
               created_at
        FROM offseason_events
        ORDER BY id DESC
        LIMIT ?
    """, (limit,)).fetchall())


def team_by_id(conn, team_id):
    if not team_id:
        return None
    return one(conn.execute(
        """
        SELECT id, city, name, city || ' ' || name AS team_name,
               abbreviation, team_archetype, fan_pitch, pressure_label
        FROM teams WHERE id=?
        """,
        (team_id,),
    ).fetchone())


def mvp_ladder(conn, season_year, limit=5):
    return dicts(conn.execute("""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               p.position, t.id AS team_id, t.abbreviation,
               t.city || ' ' || t.name AS team_name,
               ROUND(AVG(pgs.points),1) AS ppg,
               ROUND(AVG(pgs.rebounds),1) AS rpg,
               ROUND(AVG(pgs.assists),1) AS apg,
               ROUND(AVG(
                   pgs.points + pgs.rebounds*0.75 + pgs.assists*0.65
                   + pgs.steals*1.6 + pgs.blocks*1.35
               ),1) AS value
        FROM player_game_stats pgs
        JOIN games g ON g.id=pgs.game_id
        JOIN players p ON p.id=pgs.player_id
        JOIN teams t ON t.id=pgs.team_id
        WHERE g.season_year=?
        GROUP BY p.id, t.id
        ORDER BY value DESC
        LIMIT ?
    """, (season_year, limit)).fetchall())


def team_form(conn, season_year):
    teams = {
        row["id"]: {
            "team_id": row["id"],
            "team_name": f"{row['city']} {row['name']}",
            "abbreviation": row["abbreviation"],
            "results": [],
        }
        for row in conn.execute(
            "SELECT id, city, name, abbreviation FROM teams"
        ).fetchall()
    }
    games = conn.execute("""
        SELECT * FROM games
        WHERE season_year=? AND played=1
        ORDER BY week DESC, id DESC
    """, (season_year,)).fetchall()
    for game in games:
        for team_id, is_home in (
            (game["home_team_id"], True),
            (game["away_team_id"], False),
        ):
            results = teams[team_id]["results"]
            if len(results) >= 4:
                continue
            won = (
                game["home_score"] > game["away_score"]
                if is_home
                else game["away_score"] > game["home_score"]
            )
            margin = (
                game["home_score"] - game["away_score"]
                if is_home
                else game["away_score"] - game["home_score"]
            )
            results.append({"won": won, "margin": margin})
    rows = []
    for team in teams.values():
        wins = sum(1 for result in team["results"] if result["won"])
        margin = sum(result["margin"] for result in team["results"])
        team["form_score"] = wins * 10 + margin * 0.3
        team["form_text"] = "".join("W" if result["won"] else "L" for result in team["results"]) or "—"
        rows.append(team)
    rows.sort(key=lambda item: item["form_score"], reverse=True)
    return rows


def next_featured_game(conn, season_year, current_week):
    return one(conn.execute("""
        SELECT g.id, g.week, g.home_team_id, g.away_team_id,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               ht.rivalry AS home_rivalry,
               at.rivalry AS away_rivalry,
               COALESCE(hs.wins,0) AS home_wins,
               COALESCE(asd.wins,0) AS away_wins,
               COALESCE(tr.current_intensity,0.12) AS rivalry_heat,
               rn.name AS rivalry_name,
               (COALESCE(hs.wins,0)+COALESCE(asd.wins,0)
                + COALESCE(tr.current_intensity,0.12)*5) AS feature_score
        FROM games g
        JOIN teams ht ON ht.id=g.home_team_id
        JOIN teams at ON at.id=g.away_team_id
        LEFT JOIN standings hs ON hs.team_id=g.home_team_id AND hs.season_year=g.season_year
        LEFT JOIN standings asd ON asd.team_id=g.away_team_id AND asd.season_year=g.season_year
        LEFT JOIN team_rivalries tr
          ON (tr.team_a_id=g.home_team_id AND tr.team_b_id=g.away_team_id)
          OR (tr.team_a_id=g.away_team_id AND tr.team_b_id=g.home_team_id)
        LEFT JOIN rivalry_names rn
          ON rn.team_a_id=tr.team_a_id AND rn.team_b_id=tr.team_b_id
         AND rn.status='active'
        WHERE g.season_year=? AND g.played=0 AND g.week>=?
        ORDER BY g.week, feature_score DESC, g.id
        LIMIT 1
    """, (season_year, current_week)).fetchone())


def trade_pressure(conn, season_year):
    return {
        "pending": conn.execute(
            "SELECT COUNT(*) FROM pending_trades WHERE season_year=? AND status='pending'",
            (season_year,),
        ).fetchone()[0],
        "demands": dicts(conn.execute("""
            SELECT p.id, p.first_name || ' ' || p.last_name AS player,
                   t.id AS team_id, t.abbreviation, pe.detail
            FROM player_events pe
            JOIN players p ON p.id=pe.player_id
            JOIN teams t ON t.id=p.team_id
            WHERE pe.season_year=? AND pe.event_type='trade_demand'
              AND pe.status='active'
            ORDER BY pe.week DESC, pe.id DESC
            LIMIT 5
        """, (season_year,)).fetchall()),
    }


def active_poll(conn, season_year):
    poll = one(conn.execute("""
        SELECT * FROM polls
        WHERE season_year=? AND status='open'
        ORDER BY week DESC, id DESC LIMIT 1
    """, (season_year,)).fetchone())
    if not poll:
        return None
    poll["options"] = dicts(conn.execute("""
        SELECT po.id, po.label, po.entity_type, po.entity_id,
               COUNT(pv.id) AS votes
        FROM poll_options po
        LEFT JOIN poll_votes pv ON pv.option_id=po.id
        WHERE po.poll_id=?
        GROUP BY po.id
        ORDER BY po.sort_order, po.id
    """, (poll["id"],)).fetchall())
    poll["total_votes"] = sum(option["votes"] for option in poll["options"])
    poll["type_label"] = {
        "fan_player_of_week": "Player of the Week",
        "fan_game_of_week": "Game of the Week",
        "fan_confidence": "Fan Confidence",
        "rivalry_name": "Name the Rivalry",
        "award_name": "Name the Award",
    }.get(poll["poll_type"], "Fan Poll")
    return poll


def recent_poll_results(conn, season_year=None, limit=12):
    where = "WHERE p.status='closed' AND p.winner_option_id IS NOT NULL"
    params = []
    if season_year is not None:
        where += " AND p.season_year=?"
        params.append(season_year)
    params.append(limit)
    rows = dicts(conn.execute(f"""
        SELECT p.id, p.season_year, p.week, p.poll_type, p.question,
               p.result_label, po.entity_type, po.entity_id,
               COUNT(pv.id) AS votes
        FROM polls p
        JOIN poll_options po ON po.id=p.winner_option_id
        LEFT JOIN poll_votes pv ON pv.option_id=po.id
        {where}
        GROUP BY p.id, po.id
        ORDER BY p.season_year DESC, p.week DESC, p.id DESC
        LIMIT ?
    """, params).fetchall())
    labels = {
        "fan_player_of_week": "Player of the Week",
        "fan_game_of_week": "Game of the Week",
        "fan_confidence": "Fan Confidence",
        "rivalry_name": "Rivalry Name",
        "award_name": "Award Name",
    }
    for row in rows:
        row["type_label"] = labels.get(row["poll_type"], "Fan Poll")
    return rows


def followed_team_feed(conn, team_id, season_year):
    team = team_by_id(conn, team_id)
    if not team:
        return None
    team["next_game"] = one(conn.execute("""
        SELECT g.id, g.week,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr
        FROM games g
        JOIN teams ht ON ht.id=g.home_team_id
        JOIN teams at ON at.id=g.away_team_id
        WHERE g.season_year=? AND g.played=0
          AND (g.home_team_id=? OR g.away_team_id=?)
        ORDER BY g.week, g.id LIMIT 1
    """, (season_year, team_id, team_id)).fetchone())
    team["articles"] = articles_for_team(conn, team_id, season_year, limit=3)
    team["events"] = dicts(conn.execute("""
        SELECT pe.week, pe.event_type, pe.detail,
               p.first_name || ' ' || p.last_name AS player
        FROM player_events pe
        JOIN players p ON p.id=pe.player_id
        WHERE p.team_id=? AND pe.season_year=?
        ORDER BY pe.week DESC, pe.id DESC LIMIT 4
    """, (team_id, season_year)).fetchall())
    return team


def current_editorial_package(conn, season_year):
    return one(conn.execute("""
        SELECT id, schema_name, season_year, week, prompt_text, status,
               published_at
        FROM weekly_editorial_packages
        WHERE season_year=?
        ORDER BY week DESC, id DESC LIMIT 1
    """, (season_year,)).fetchone())


def editorial_quotes_for_game(conn, game_id):
    rows = dicts(conn.execute("""
        SELECT eq.*, wep.week, wep.season_year
        FROM editorial_quotes eq
        JOIN weekly_editorial_packages wep ON wep.id=eq.package_id
        WHERE eq.game_id=?
        ORDER BY eq.id
    """, (game_id,)).fetchall())
    for row in rows:
        if row["speaker_type"] == "player":
            speaker = conn.execute(
                "SELECT first_name || ' ' || last_name AS name FROM players WHERE id=?",
                (row["speaker_id"],),
            ).fetchone()
        elif row["speaker_type"] == "coach":
            speaker = conn.execute(
                "SELECT name FROM head_coaches WHERE id=?", (row["speaker_id"],)
            ).fetchone()
        else:
            speaker = conn.execute(
                "SELECT name FROM general_managers WHERE id=?", (row["speaker_id"],)
            ).fetchone()
        row["speaker_name"] = speaker["name"] if speaker else "AIBA source"
    return rows


def recent_editorial_quotes(conn, season_year, limit=20):
    rows = dicts(conn.execute("""
        SELECT eq.*, wep.week, wep.season_year
        FROM editorial_quotes eq
        JOIN weekly_editorial_packages wep ON wep.id=eq.package_id
        WHERE wep.season_year=?
        ORDER BY eq.id DESC LIMIT ?
    """, (season_year, limit)).fetchall())
    for row in rows:
        if row["speaker_type"] == "player":
            speaker = conn.execute("""
                SELECT p.first_name || ' ' || p.last_name AS name,
                       t.city || ' ' || t.name AS team_name
                FROM players p JOIN teams t ON t.id=p.team_id
                WHERE p.id=?
            """, (row["speaker_id"],)).fetchone()
        elif row["speaker_type"] == "coach":
            speaker = conn.execute("""
                SELECT hc.name, t.city || ' ' || t.name AS team_name
                FROM head_coaches hc JOIN teams t ON t.id=hc.team_id
                WHERE hc.id=?
            """, (row["speaker_id"],)).fetchone()
        else:
            speaker = conn.execute("""
                SELECT gm.name, t.city || ' ' || t.name AS team_name
                FROM general_managers gm JOIN teams t ON t.id=gm.team_id
                WHERE gm.id=?
            """, (row["speaker_id"],)).fetchone()
        row["speaker_name"] = speaker["name"] if speaker else "AIBA source"
        row["team_name"] = speaker["team_name"] if speaker else "AIBA"
    return rows


def history_overview(conn):
    champions = dicts(conn.execute("""
        SELECT ss.season_year, t.city || ' ' || t.name AS champion,
               t.abbreviation
        FROM season_snapshots ss
        LEFT JOIN teams t ON t.id=ss.champion_id
        ORDER BY ss.season_year DESC
    """).fetchall())
    career_leaders = dicts(conn.execute("""
        SELECT p.id, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation, SUM(pgs.points) AS points,
               SUM(pgs.rebounds) AS rebounds, SUM(pgs.assists) AS assists,
               COUNT(*) AS games
        FROM player_game_stats pgs
        JOIN players p ON p.id=pgs.player_id
        JOIN teams t ON t.id=p.team_id
        GROUP BY p.id, t.abbreviation
        ORDER BY points DESC LIMIT 12
    """).fetchall())
    record_book = dicts(conn.execute("""
        SELECT rbe.*, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation,
               CASE rbe.scope
                 WHEN 'single_game' THEN 'Single-game'
                 WHEN 'season' THEN 'Single-season'
                 ELSE 'Career'
               END AS scope_label
        FROM record_book_entries rbe
        JOIN players p ON p.id=rbe.player_id
        LEFT JOIN teams t ON t.id=rbe.team_id
        WHERE rbe.is_current=1
        ORDER BY CASE rbe.scope
                   WHEN 'single_game' THEN 1
                   WHEN 'season' THEN 2
                   ELSE 3
                 END,
                 CASE rbe.stat_key
                   WHEN 'points' THEN 1
                   WHEN 'rebounds' THEN 2
                   WHEN 'assists' THEN 3
                   WHEN 'steals' THEN 4
                   ELSE 5
                 END,
                 rbe.player_id
    """).fetchall())
    record_history = dicts(conn.execute("""
        SELECT rbe.*, p.first_name || ' ' || p.last_name AS player,
               t.abbreviation,
               CASE rbe.scope
                 WHEN 'single_game' THEN 'Single-game'
                 WHEN 'season' THEN 'Single-season'
                 ELSE 'Career'
               END AS scope_label
        FROM record_book_entries rbe
        JOIN players p ON p.id=rbe.player_id
        LEFT JOIN teams t ON t.id=rbe.team_id
        ORDER BY rbe.created_at DESC, rbe.id DESC
        LIMIT 40
    """).fetchall())
    awards = dicts(conn.execute("""
        SELECT a.*, p.first_name || ' ' || p.last_name AS player,
               t.city || ' ' || t.name AS team,
               CASE WHEN a.entity_type='game'
                    THEN at.abbreviation || ' at ' || ht.abbreviation
                    ELSE NULL END AS game_label
        FROM awards a
        LEFT JOIN players p ON a.entity_type='player' AND p.id=a.entity_id
        LEFT JOIN teams t ON a.entity_type='team' AND t.id=a.entity_id
        LEFT JOIN games g ON a.entity_type='game' AND g.id=a.entity_id
        LEFT JOIN teams ht ON ht.id=g.home_team_id
        LEFT JOIN teams at ON at.id=g.away_team_id
        ORDER BY a.season_year DESC, a.week DESC, a.id DESC
        LIMIT 60
    """).fetchall())
    events = dicts(conn.execute("""
        SELECT he.*, t.abbreviation,
               p.first_name || ' ' || p.last_name AS player,
               hc.name AS coach
        FROM history_events he
        LEFT JOIN teams t ON t.id=he.team_id
        LEFT JOIN players p ON p.id=he.player_id
        LEFT JOIN head_coaches hc ON hc.id=he.coach_id
        ORDER BY he.season_year DESC, he.week DESC, he.importance DESC, he.id DESC
        LIMIT 80
    """).fetchall())
    retired = dicts(conn.execute("""
        SELECT rj.*, p.first_name || ' ' || p.last_name AS player,
               t.city || ' ' || t.name AS team, t.abbreviation
        FROM retired_jerseys rj
        JOIN players p ON p.id=rj.player_id
        JOIN teams t ON t.id=rj.team_id
        ORDER BY rj.season_year DESC
    """).fetchall())
    coaches = dicts(conn.execute("""
        SELECT hc.*, t.city || ' ' || t.name AS team, t.abbreviation
        FROM head_coaches hc JOIN teams t ON t.id=hc.team_id
        ORDER BY hc.team_id, hc.hired_season DESC
    """).fetchall())
    fan_labels = dicts(conn.execute("""
        SELECT fl.*, t.city || ' ' || t.name AS team,
               p.first_name || ' ' || p.last_name AS player
        FROM fan_labels fl
        LEFT JOIN teams t ON t.id=fl.team_id
        LEFT JOIN players p ON p.id=fl.player_id
        ORDER BY fl.season_year DESC, fl.week DESC, fl.id DESC
    """).fetchall())
    rivalry_names = dicts(conn.execute("""
        SELECT rn.*, ta.city || ' ' || ta.name AS team_a,
               tb.city || ' ' || tb.name AS team_b
        FROM rivalry_names rn
        JOIN teams ta ON ta.id=rn.team_a_id
        JOIN teams tb ON tb.id=rn.team_b_id
        ORDER BY rn.season_year DESC, rn.week DESC, rn.id DESC
    """).fetchall())
    draft_classes = dicts(conn.execute("""
        SELECT dp.*, p.first_name || ' ' || p.last_name AS player,
               p.skill_rating, p.status,
               t.city || ' ' || t.name AS team, t.abbreviation
        FROM draft_profiles dp
        JOIN players p ON p.id=dp.player_id
        JOIN teams t ON t.id=dp.team_id
        ORDER BY dp.draft_year DESC, dp.pick_number
        LIMIT 40
    """).fetchall())
    playoff_runs = dicts(conn.execute("""
        SELECT prs.*, t.city || ' ' || t.name AS team, t.abbreviation,
               p.first_name || ' ' || p.last_name AS star_player
        FROM playoff_run_summaries prs
        JOIN teams t ON t.id=prs.team_id
        LEFT JOIN players p ON p.id=prs.star_player_id
        ORDER BY prs.season_year DESC, prs.legendary DESC,
                 prs.playoff_wins DESC, prs.team_id
        LIMIT 32
    """).fetchall())
    hall_of_fame = dicts(conn.execute("""
        SELECT hof.*, p.first_name || ' ' || p.last_name AS player,
               t.city || ' ' || t.name AS team, t.abbreviation
        FROM hall_of_fame hof
        JOIN players p ON p.id=hof.player_id
        LEFT JOIN teams t ON t.id=hof.primary_team_id
        ORDER BY hof.induction_year DESC, hof.id DESC
    """).fetchall())
    franchise_timeline = dicts(conn.execute("""
        SELECT fe.*, t.city || ' ' || t.name AS team, t.abbreviation
        FROM franchise_events fe
        JOIN teams t ON t.id=fe.team_id
        ORDER BY fe.season_year, fe.event_type, t.city
    """).fetchall())
    return {
        "champions": champions,
        "career_leaders": career_leaders,
        "record_book": record_book,
        "record_history": record_history,
        "awards": awards,
        "events": events,
        "retired_jerseys": retired,
        "coaches": coaches,
        "fan_labels": fan_labels,
        "rivalry_names": rivalry_names,
        "draft_classes": draft_classes,
        "playoff_runs": playoff_runs,
        "hall_of_fame": hall_of_fame,
        "franchise_timeline": franchise_timeline,
        "poll_results": recent_poll_results(conn, limit=30),
    }
