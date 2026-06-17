"""Playoff bracket management: seeding, series tracking, and display data."""

WINS_TO_ADVANCE = 2  # best of 3

SERIES_LABELS = {
    "semifinal": "Semifinals",
    "finals": "Finals",
    "third_place": "Third Place",
}


def _team_name(conn, team_id):
    row = conn.execute(
        "SELECT city || ' ' || name AS name FROM teams WHERE id = ?",
        (team_id,),
    ).fetchone()
    return row["name"] if row else "Unknown Team"


def _insert_series(conn, season_year, round_num, series_type, seed_a, seed_b, team_a_id, team_b_id):
    cur = conn.execute("""
        INSERT INTO playoff_series
            (season_year, round, series_type, seed_a, seed_b, team_a_id, team_b_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (season_year, round_num, series_type, seed_a, seed_b, team_a_id, team_b_id))
    return cur.lastrowid


def _next_game_for_series(conn, series_id):
    return conn.execute("""
        SELECT g.id,
               g.week,
               g.played,
               g.home_team_id,
               g.away_team_id,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.playoff_series_id = ? AND g.played = 0
        ORDER BY g.week, g.id
        LIMIT 1
    """, (series_id,)).fetchone()


def _recent_game_for_series(conn, series_id):
    return conn.execute("""
        SELECT g.id,
               g.week,
               g.home_score,
               g.away_score,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.playoff_series_id = ? AND g.played = 1
        ORDER BY g.week DESC, g.id DESC
        LIMIT 1
    """, (series_id,)).fetchone()


def seed_playoffs(conn, start_week, season_year):
    """
    Rank top 4 teams, create semifinal series (#1 vs #4, #2 vs #3),
    and insert Game 1 of each series into the games table.
    """
    top4 = conn.execute("""
        SELECT s.team_id, s.wins, s.losses,
               s.points_for - s.points_against AS diff,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation
        FROM standings s
        JOIN teams t ON s.team_id = t.id
        WHERE s.season_year = ?
        ORDER BY s.wins DESC, diff DESC, s.points_for DESC
        LIMIT 4
    """, (season_year,)).fetchall()

    print(f"\n{'='*54}")
    print(f"  PLAYOFFS BEGIN  --  {season_year} SEASON")
    print("  Top 4 playoff seeds:")
    for index, team in enumerate(top4, 1):
        print(f"    #{index}  {team['team_name']}  ({team['wins']}-{team['losses']})")
    print()

    matchups = [(0, 3), (1, 2)]
    for a_idx, b_idx in matchups:
        team_a = top4[a_idx]
        team_b = top4[b_idx]
        series_id = _insert_series(
            conn,
            season_year,
            1,
            "semifinal",
            a_idx + 1,
            b_idx + 1,
            team_a["team_id"],
            team_b["team_id"],
        )

        conn.execute("""
            INSERT INTO games
                (home_team_id, away_team_id, week, season_year, playoff_series_id)
            VALUES (?, ?, ?, ?, ?)
        """, (team_a["team_id"], team_b["team_id"], start_week, season_year, series_id))

        print(f"  #{a_idx + 1} {team_a['team_name']}  vs  #{b_idx + 1} {team_b['team_name']}")

    print(f"\n  Semifinals start Week {start_week}.\n")
    conn.commit()


def schedule_next_playoff_game(conn, series_id, next_week, season_year):
    """Insert the next game of an active series for next_week."""
    s = conn.execute(
        "SELECT * FROM playoff_series WHERE id = ?",
        (series_id,),
    ).fetchone()
    if not s or s["status"] != "active":
        return None

    existing = _next_game_for_series(conn, series_id)
    if existing:
        return existing["id"]

    game_num = s["team_a_wins"] + s["team_b_wins"] + 1
    if game_num > 3:
        return None

    # Home pattern for BO3: Game 1 -> A, Game 2 -> B, Game 3 -> A.
    if game_num in (1, 3):
        home_id, away_id = s["team_a_id"], s["team_b_id"]
    else:
        home_id, away_id = s["team_b_id"], s["team_a_id"]

    cur = conn.execute("""
        INSERT INTO games
            (home_team_id, away_team_id, week, season_year, playoff_series_id)
        VALUES (?, ?, ?, ?, ?)
    """, (home_id, away_id, next_week, season_year, series_id))
    return cur.lastrowid


def record_game_result(conn, game_id):
    """
    Update series wins after a playoff game is played.
    Returns (series_id, series_over, winner_id_or_none).
    """
    game = conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()
    series_id = game["playoff_series_id"]
    if not series_id:
        return None, False, None

    winner_id = (
        game["home_team_id"] if game["home_score"] > game["away_score"]
        else game["away_team_id"]
    )

    s = conn.execute("SELECT * FROM playoff_series WHERE id = ?", (series_id,)).fetchone()
    if winner_id == s["team_a_id"]:
        conn.execute(
            "UPDATE playoff_series SET team_a_wins = team_a_wins + 1 WHERE id = ?",
            (series_id,),
        )
    else:
        conn.execute(
            "UPDATE playoff_series SET team_b_wins = team_b_wins + 1 WHERE id = ?",
            (series_id,),
        )

    s = conn.execute("SELECT * FROM playoff_series WHERE id = ?", (series_id,)).fetchone()
    if s["team_a_wins"] >= WINS_TO_ADVANCE or s["team_b_wins"] >= WINS_TO_ADVANCE:
        winner = s["team_a_id"] if s["team_a_wins"] >= WINS_TO_ADVANCE else s["team_b_id"]
        conn.execute(
            "UPDATE playoff_series SET status='complete', winner_id=? WHERE id=?",
            (winner, series_id),
        )
        return series_id, True, winner

    return series_id, False, None


def team_seed_for_series(series, team_id):
    if team_id == series["team_a_id"]:
        return series["seed_a"]
    if team_id == series["team_b_id"]:
        return series["seed_b"]
    return None


def series_loser_id(series):
    if not series["winner_id"]:
        return None
    if series["winner_id"] == series["team_a_id"]:
        return series["team_b_id"]
    return series["team_a_id"]


def create_championship_and_third_place(conn, season_year, start_week):
    """Create Finals and third-place series once both semifinals are complete."""
    existing = conn.execute("""
        SELECT COUNT(*) AS count
        FROM playoff_series
        WHERE season_year = ? AND COALESCE(series_type, '') IN ('finals', 'third_place')
    """, (season_year,)).fetchone()["count"]
    if existing:
        return []

    semis = conn.execute("""
        SELECT *
        FROM playoff_series
        WHERE season_year = ? AND COALESCE(series_type, 'semifinal') = 'semifinal'
        ORDER BY seed_a
    """, (season_year,)).fetchall()
    if len(semis) != 2 or any(row["status"] != "complete" for row in semis):
        return []

    first, second = semis
    finals_a = first["winner_id"]
    finals_b = second["winner_id"]
    third_a = series_loser_id(first)
    third_b = series_loser_id(second)

    finals_id = _insert_series(
        conn,
        season_year,
        2,
        "finals",
        team_seed_for_series(first, finals_a),
        team_seed_for_series(second, finals_b),
        finals_a,
        finals_b,
    )
    third_id = _insert_series(
        conn,
        season_year,
        2,
        "third_place",
        team_seed_for_series(first, third_a),
        team_seed_for_series(second, third_b),
        third_a,
        third_b,
    )

    schedule_next_playoff_game(conn, finals_id, start_week, season_year)
    schedule_next_playoff_game(conn, third_id, start_week, season_year)
    return [finals_id, third_id]


def playoff_finished(conn, season_year):
    finals = conn.execute("""
        SELECT status FROM playoff_series
        WHERE season_year = ? AND series_type = 'finals'
    """, (season_year,)).fetchone()
    third = conn.execute("""
        SELECT status FROM playoff_series
        WHERE season_year = ? AND series_type = 'third_place'
    """, (season_year,)).fetchone()
    return bool(finals and third and finals["status"] == "complete" and third["status"] == "complete")


def get_bracket(conn, season_year):
    """Return all playoff series for display, sorted by bracket position."""
    return conn.execute("""
        SELECT ps.*,
               COALESCE(ps.series_type,
                   CASE WHEN ps.round = 1 THEN 'semifinal' ELSE 'finals' END
               ) AS series_type,
               ta.city || ' ' || ta.name AS name_a, ta.abbreviation AS abbr_a,
               tb.city || ' ' || tb.name AS name_b, tb.abbreviation AS abbr_b,
               tw.city || ' ' || tw.name AS winner_name,
               tw.abbreviation AS winner_abbr
        FROM playoff_series ps
        JOIN teams ta ON ps.team_a_id = ta.id
        JOIN teams tb ON ps.team_b_id = tb.id
        LEFT JOIN teams tw ON ps.winner_id = tw.id
        WHERE ps.season_year = ?
        ORDER BY ps.round,
                 CASE COALESCE(ps.series_type, 'semifinal')
                    WHEN 'semifinal' THEN 1
                    WHEN 'finals' THEN 2
                    WHEN 'third_place' THEN 3
                    ELSE 4
                 END,
                 ps.seed_a
    """, (season_year,)).fetchall()


def _decorate_series(conn, row):
    series = dict(row)
    next_game = _next_game_for_series(conn, series["id"])
    last_game = _recent_game_for_series(conn, series["id"])
    played_count = series["team_a_wins"] + series["team_b_wins"]

    series["label"] = SERIES_LABELS.get(series["series_type"], "Playoffs")
    series["next_game"] = dict(next_game) if next_game else None
    series["last_game"] = dict(last_game) if last_game else None
    series["game_number"] = min(played_count + 1, 3)

    if series["status"] == "complete":
        series["status_text"] = (
            f"{series['winner_name']} wins "
            f"{series['team_a_wins']}-{series['team_b_wins']}"
        )
    elif next_game:
        series["status_text"] = f"Game {played_count + 1} scheduled Week {next_game['week']}"
    elif played_count == 0:
        series["status_text"] = "Best of 3"
    elif series["team_a_wins"] == series["team_b_wins"]:
        series["status_text"] = f"Series tied {series['team_a_wins']}-{series['team_b_wins']}"
    else:
        leader = series["name_a"] if series["team_a_wins"] > series["team_b_wins"] else series["name_b"]
        series["status_text"] = (
            f"{leader} leads {series['team_a_wins']}-{series['team_b_wins']}"
        )
    return series


def playoff_games(conn, season_year, played, limit=None):
    sql = """
        SELECT g.id,
               g.week,
               g.played,
               g.home_score,
               g.away_score,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr,
               ps.series_type,
               ps.seed_a,
               ps.seed_b
        FROM games g
        JOIN playoff_series ps ON ps.id = g.playoff_series_id
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ? AND g.played = ?
        ORDER BY g.week {direction}, g.id {direction}
    """
    direction = "DESC" if played else "ASC"
    params = [season_year, 1 if played else 0]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return [dict(row) for row in conn.execute(sql.format(direction=direction), params).fetchall()]


def get_playoff_snapshot(conn, season_year):
    """Return grouped bracket, recent results, and upcoming games for UI/media."""
    rows = [_decorate_series(conn, row) for row in get_bracket(conn, season_year)]
    semis = [row for row in rows if row["series_type"] == "semifinal"]
    finals = [row for row in rows if row["series_type"] == "finals"]
    third_place = [row for row in rows if row["series_type"] == "third_place"]

    champion = finals[0] if finals and finals[0]["status"] == "complete" else None
    third_place_winner = (
        third_place[0]
        if third_place and third_place[0]["status"] == "complete"
        else None
    )

    upcoming_games = playoff_games(conn, season_year, played=False, limit=6)
    recent_results = playoff_games(conn, season_year, played=True, limit=6)

    active = [row for row in rows if row["status"] == "active"]
    phase_label = "Playoffs"
    if champion and third_place_winner:
        phase_label = "Season Complete"
    elif finals or third_place:
        phase_label = "Finals Week"
    elif semis:
        phase_label = "Semifinals"

    return {
        "series": rows,
        "semifinals": semis,
        "finals": finals,
        "third_place": third_place,
        "champion": champion,
        "third_place_winner": third_place_winner,
        "upcoming_games": upcoming_games,
        "recent_results": recent_results,
        "active_series": active,
        "phase_label": phase_label,
    }
