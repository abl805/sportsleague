"""Playoff bracket management — seeding, series tracking, bracket advancement."""

WINS_TO_ADVANCE = 2  # best of 3


def seed_playoffs(conn, start_week, season_year):
    """
    Rank top 4 teams, create Round 1 series (#1v#4, #2v#3),
    and insert Game 1 of each series into the games table.
    """
    top4 = conn.execute("""
        SELECT s.team_id, s.wins, s.losses,
               s.points_for - s.points_against AS diff,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation
        FROM   standings s
        JOIN   teams t ON s.team_id = t.id
        WHERE  s.season_year = ?
        ORDER  BY s.wins DESC, diff DESC
        LIMIT  4
    """, (season_year,)).fetchall()

    print(f"\n{'='*54}")
    print(f"  PLAYOFFS BEGIN  --  {season_year} SEASON")
    print(f"  Top 4 playoff seeds:")
    for i, t in enumerate(top4, 1):
        print(f"    #{i}  {t['team_name']}  ({t['wins']}-{t['losses']})")
    print()

    matchups = [(0, 3), (1, 2)]  # (higher_seed_idx, lower_seed_idx)
    for a_idx, b_idx in matchups:
        team_a = top4[a_idx]
        team_b = top4[b_idx]
        conn.execute("""
            INSERT INTO playoff_series
                (season_year, round, seed_a, seed_b, team_a_id, team_b_id)
            VALUES (?, 1, ?, ?, ?, ?)
        """, (season_year, a_idx + 1, b_idx + 1,
              team_a["team_id"], team_b["team_id"]))
        series_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Game 1: higher seed (team_a) at home
        conn.execute("""
            INSERT INTO games
                (home_team_id, away_team_id, week, season_year, playoff_series_id)
            VALUES (?, ?, ?, ?, ?)
        """, (team_a["team_id"], team_b["team_id"],
              start_week, season_year, series_id))

        print(f"  #{a_idx+1} {team_a['team_name']}  vs  #{b_idx+1} {team_b['team_name']}")

    print(f"\n  Semifinals start Week {start_week}.\n")
    conn.commit()


def schedule_next_playoff_game(conn, series_id, next_week, season_year):
    """Insert the next game of an active series for next_week."""
    s = conn.execute(
        "SELECT * FROM playoff_series WHERE id = ?", (series_id,)
    ).fetchone()
    game_num = s["team_a_wins"] + s["team_b_wins"] + 1  # 1-indexed

    # Home pattern for BO3: Game 1 → A, Game 2 → B, Game 3 → A
    if game_num in (1, 3):
        home_id, away_id = s["team_a_id"], s["team_b_id"]
    else:
        home_id, away_id = s["team_b_id"], s["team_a_id"]

    conn.execute("""
        INSERT INTO games
            (home_team_id, away_team_id, week, season_year, playoff_series_id)
        VALUES (?, ?, ?, ?, ?)
    """, (home_id, away_id, next_week, season_year, series_id))


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
            (series_id,)
        )
    else:
        conn.execute(
            "UPDATE playoff_series SET team_b_wins = team_b_wins + 1 WHERE id = ?",
            (series_id,)
        )

    s = conn.execute("SELECT * FROM playoff_series WHERE id = ?", (series_id,)).fetchone()
    if s["team_a_wins"] >= WINS_TO_ADVANCE or s["team_b_wins"] >= WINS_TO_ADVANCE:
        w = s["team_a_id"] if s["team_a_wins"] >= WINS_TO_ADVANCE else s["team_b_id"]
        conn.execute(
            "UPDATE playoff_series SET status='complete', winner_id=? WHERE id=?",
            (w, series_id)
        )
        return series_id, True, w

    return series_id, False, None


def get_bracket(conn, season_year):
    """Return all playoff series for display, sorted by round then seed_a."""
    return conn.execute("""
        SELECT ps.*,
               ta.city || ' ' || ta.name AS name_a, ta.abbreviation AS abbr_a,
               tb.city || ' ' || tb.name AS name_b, tb.abbreviation AS abbr_b,
               tw.city || ' ' || tw.name AS winner_name
        FROM   playoff_series ps
        JOIN   teams ta ON ps.team_a_id = ta.id
        JOIN   teams tb ON ps.team_b_id = tb.id
        LEFT   JOIN teams tw ON ps.winner_id  = tw.id
        WHERE  ps.season_year = ?
        ORDER  BY ps.round, ps.seed_a
    """, (season_year,)).fetchall()
