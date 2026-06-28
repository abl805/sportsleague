import json

from league.database import get_connection


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
        "SELECT COUNT(*) AS cnt FROM games WHERE played = 1 AND season_year = ?",
        (season_year,),
    ).fetchone()["cnt"]


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
        GROUP BY p.id, t.id
        HAVING COUNT(pgs.id) >= 1
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

    return {
        "team": team,
        "record": record,
        "roster": roster,
        "recent_games": recent_games,
        "schedule": schedule,
        "events": events,
        "chemistry": chemistry,
        "gm": gm,
        "team_leaders": team_leaders,
        "articles": articles,
        "interviews": interviews,
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

    return {
        "player": player,
        "averages": averages,
        "game_log": game_log,
        "events": events,
        "morale": morale,
        "articles": articles,
        "interviews": interviews,
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
        ORDER BY t.id, pgs.points DESC
    """, (game_id,)).fetchall())
    mvp = None
    if box:
        mvp = max(box, key=lambda r: (
            r["points"] + r["rebounds"] * 0.75 + r["assists"] * 0.5
            + r["steals"] * 1.5 + r["blocks"] * 1.0
        ))
    return {"game": game, "box": box, "mvp": mvp}


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
        SELECT id, week, season_year, headline, body, created_at
        FROM articles
        WHERE season_year = ?
        ORDER BY week DESC, id DESC
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
    combined.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
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


def save_contact_message(conn, name, email, subject, body):
    conn.execute(
        "INSERT INTO contact_messages (name, email, subject, body) VALUES (?, ?, ?, ?)",
        (name, email, subject, body),
    )
    conn.commit()


def get_contact_messages(conn, limit=50):
    return dicts(conn.execute("""
        SELECT id, name, email, subject, body, read, created_at
        FROM contact_messages
        ORDER BY id DESC
        LIMIT ?
    """, (limit,)).fetchall())
