"""
Simulates all games for the current week, updates standings, and advances
the league clock by one week. Run this once per "week" as commissioner.

Pass --verbose for a full narrative including player drama.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables
from league.simulation import simulate_game
from league.gm_agents import run_all_gm_agents, evaluate_all_gms_season_end
from league.player_agents import (
    run_all_player_agents,
    compute_all_team_chemistry,
    get_team_chemistry,
)
from league.trade_engine import autopilot_review_pending_trades
from league.playoffs import (
    create_championship_and_third_place,
    playoff_finished,
    seed_playoffs,
    schedule_next_playoff_game,
    record_game_result,
)
from league.chatgpt_bridge import build_interview_packet, build_gm_interview_packet


def _process_playoff_results(conn, playoff_game_ids, current_week, season_year):
    """
    After playoff games for a week are simulated:
      - Update series win counts
      - Schedule the next game for any series still alive
      - If a round is swept clean, advance the bracket (start Finals or crown champion)
    """
    if not playoff_game_ids:
        return

    # Determine which round these games belong to
    round_num = conn.execute("""
        SELECT ps.round FROM playoff_series ps
        WHERE  ps.id = (SELECT playoff_series_id FROM games WHERE id = ?)
    """, (playoff_game_ids[0],)).fetchone()["round"]

    round_label = "SEMIFINALS" if round_num == 1 else "FINALS"
    print(f"\n{'-'*54}")
    print(f"  PLAYOFFS  --  {round_label}  UPDATE")
    print(f"{'-'*54}")

    for game_id in playoff_game_ids:
        series_id, done, winner_id = record_game_result(conn, game_id)
        s = conn.execute("""
            SELECT ps.seed_a, ps.seed_b,
                   ps.team_a_wins, ps.team_b_wins,
                   ta.city || ' ' || ta.name AS name_a,
                   tb.city || ' ' || tb.name AS name_b
            FROM   playoff_series ps
            JOIN   teams ta ON ps.team_a_id = ta.id
            JOIN   teams tb ON ps.team_b_id = tb.id
            WHERE  ps.id = ?
        """, (series_id,)).fetchone()

        if done:
            w_name = conn.execute(
                "SELECT city || ' ' || name AS n FROM teams WHERE id = ?",
                (winner_id,)
            ).fetchone()["n"]
            print(f"\n  #{s['seed_a']} {s['name_a']}  vs  #{s['seed_b']} {s['name_b']}")
            print(f"  >> {w_name} wins the series  "
                  f"({s['team_a_wins']}-{s['team_b_wins']})")
        else:
            print(f"\n  #{s['seed_a']} {s['name_a']}  vs  #{s['seed_b']} {s['name_b']}")
            print(f"  Series: {s['name_a']} {s['team_a_wins']}  —  "
                  f"{s['team_b_wins']} {s['name_b']}")

    conn.commit()

    next_week = current_week + 1

    # Schedule next game for still-active series
    active = conn.execute("""
        SELECT id FROM playoff_series
        WHERE  season_year = ? AND round = ? AND status = 'active'
    """, (season_year, round_num)).fetchall()

    for row in active:
        schedule_next_playoff_game(conn, row["id"], next_week, season_year)

    # If all series in this round are done, advance the bracket
    if not active:
        if round_num == 1:
            r1 = conn.execute("""
                SELECT * FROM playoff_series
                WHERE  season_year = ? AND round = 1
                ORDER  BY seed_a
            """, (season_year,)).fetchall()
            w1 = r1[0]["winner_id"]
            w2 = r1[1]["winner_id"]

            conn.execute("""
                INSERT INTO playoff_series
                    (season_year, round, seed_a, seed_b, team_a_id, team_b_id)
                VALUES (?, 2, 1, 2, ?, ?)
            """, (season_year, w1, w2))
            finals_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Finals Game 1: #1-bracket winner at home
            conn.execute("""
                INSERT INTO games
                    (home_team_id, away_team_id, week, season_year, playoff_series_id)
                VALUES (?, ?, ?, ?, ?)
            """, (w1, w2, next_week, season_year, finals_id))

            n1 = conn.execute(
                "SELECT city || ' ' || name AS n FROM teams WHERE id = ?", (w1,)
            ).fetchone()["n"]
            n2 = conn.execute(
                "SELECT city || ' ' || name AS n FROM teams WHERE id = ?", (w2,)
            ).fetchone()["n"]
            print(f"\n  FINALS SET:  {n1}  vs  {n2}")
            print(f"  Finals begin Week {next_week}.\n")
        else:
            finals = conn.execute(
                "SELECT * FROM playoff_series WHERE season_year = ? AND round = 2",
                (season_year,)
            ).fetchone()
            champ_name = conn.execute(
                "SELECT city || ' ' || name AS n FROM teams WHERE id = ?",
                (finals["winner_id"],)
            ).fetchone()["n"]
            print(f"\n  {'*'*50}")
            print(f"    CHAMPION:  {champ_name}!")
            print(f"  {'*'*50}\n")
            conn.execute(
                "UPDATE league_state SET phase = 'complete' WHERE id = 1"
            )

    conn.commit()


def _process_playoff_results_v2(conn, playoff_game_ids, current_week, season_year):
    """
    Process playoff games when multiple series types can run in the same week.
    This supports semifinals, Finals, and a parallel third-place series.
    """
    if not playoff_game_ids:
        return

    print(f"\n{'-'*54}")
    print("  PLAYOFFS  --  BRACKET UPDATE")
    print(f"{'-'*54}")

    touched_series_ids = set()

    for game_id in playoff_game_ids:
        series_id, done, winner_id = record_game_result(conn, game_id)
        touched_series_ids.add(series_id)
        series = conn.execute("""
            SELECT ps.seed_a, ps.seed_b,
                   ps.team_a_wins, ps.team_b_wins,
                   COALESCE(ps.series_type,
                       CASE WHEN ps.round = 1 THEN 'semifinal' ELSE 'finals' END
                   ) AS series_type,
                   ta.city || ' ' || ta.name AS name_a,
                   tb.city || ' ' || tb.name AS name_b
            FROM playoff_series ps
            JOIN teams ta ON ps.team_a_id = ta.id
            JOIN teams tb ON ps.team_b_id = tb.id
            WHERE ps.id = ?
        """, (series_id,)).fetchone()

        label = {
            "semifinal": "Semifinals",
            "finals": "Finals",
            "third_place": "Third Place",
        }.get(series["series_type"], "Playoffs")

        print(f"\n  {label}:  #{series['seed_a']} {series['name_a']}  vs  #{series['seed_b']} {series['name_b']}")
        if done:
            winner_name = conn.execute(
                "SELECT city || ' ' || name AS name FROM teams WHERE id = ?",
                (winner_id,),
            ).fetchone()["name"]
            print(
                f"  >> {winner_name} wins the series "
                f"({series['team_a_wins']}-{series['team_b_wins']})"
            )
        else:
            print(
                f"  Series: {series['name_a']} {series['team_a_wins']} - "
                f"{series['team_b_wins']} {series['name_b']}"
            )

    conn.commit()

    next_week = current_week + 1
    if touched_series_ids:
        placeholders = ",".join("?" for _ in touched_series_ids)
        active = conn.execute(f"""
            SELECT id
            FROM playoff_series
            WHERE season_year = ?
              AND status = 'active'
              AND id IN ({placeholders})
        """, [season_year, *touched_series_ids]).fetchall()
    else:
        active = []

    for row in active:
        schedule_next_playoff_game(conn, row["id"], next_week, season_year)

    created = create_championship_and_third_place(conn, season_year, next_week)
    if created:
        finals = conn.execute("""
            SELECT ta.city || ' ' || ta.name AS name_a,
                   tb.city || ' ' || tb.name AS name_b
            FROM playoff_series ps
            JOIN teams ta ON ta.id = ps.team_a_id
            JOIN teams tb ON tb.id = ps.team_b_id
            WHERE ps.season_year = ? AND ps.series_type = 'finals'
        """, (season_year,)).fetchone()
        third = conn.execute("""
            SELECT ta.city || ' ' || ta.name AS name_a,
                   tb.city || ' ' || tb.name AS name_b
            FROM playoff_series ps
            JOIN teams ta ON ta.id = ps.team_a_id
            JOIN teams tb ON tb.id = ps.team_b_id
            WHERE ps.season_year = ? AND ps.series_type = 'third_place'
        """, (season_year,)).fetchone()
        print(f"\n  FINALS SET:  {finals['name_a']}  vs  {finals['name_b']}")
        print(f"  THIRD PLACE SET:  {third['name_a']}  vs  {third['name_b']}")
        print(f"  Both series begin Week {next_week}.\n")

    if playoff_finished(conn, season_year):
        finals = conn.execute(
            "SELECT winner_id FROM playoff_series WHERE season_year = ? AND series_type = 'finals'",
            (season_year,),
        ).fetchone()
        third = conn.execute(
            "SELECT winner_id FROM playoff_series WHERE season_year = ? AND series_type = 'third_place'",
            (season_year,),
        ).fetchone()
        champion_name = conn.execute(
            "SELECT city || ' ' || name AS name FROM teams WHERE id = ?",
            (finals["winner_id"],),
        ).fetchone()["name"]
        third_name = conn.execute(
            "SELECT city || ' ' || name AS name FROM teams WHERE id = ?",
            (third["winner_id"],),
        ).fetchone()["name"]
        print(f"\n  {'*'*50}")
        print(f"    CHAMPION:  {champion_name}!")
        print(f"    THIRD PLACE:  {third_name}")
        print(f"  {'*'*50}\n")
        conn.execute("UPDATE league_state SET phase = 'complete' WHERE id = 1")

    conn.commit()


_process_playoff_results = _process_playoff_results_v2


def _active_player_mods(conn, season_year, week):
    """Returns {player_id: net_skill_delta} for active hot/cold streak modifiers."""
    try:
        rows = conn.execute(
            "SELECT player_id, mod_type, magnitude FROM player_modifiers "
            "WHERE season_year=? AND expires_week>=? AND mod_type IN ('hot_streak', 'cold_streak')",
            (season_year, week)
        ).fetchall()
    except Exception:
        return {}
    mods = {}
    for r in rows:
        delta = r["magnitude"] if r["mod_type"] == "hot_streak" else -r["magnitude"]
        mods[r["player_id"]] = mods.get(r["player_id"], 0) + delta
    return mods


def _active_team_chemistry_mod(conn, team_id, season_year, week):
    """Returns net chemistry delta for active momentum_hot/cold modifiers."""
    try:
        rows = conn.execute(
            "SELECT mod_type, magnitude FROM team_modifiers "
            "WHERE team_id=? AND season_year=? AND expires_week>=? "
            "AND mod_type IN ('momentum_hot', 'momentum_cold')",
            (team_id, season_year, week)
        ).fetchall()
    except Exception:
        return 0.0
    return sum(r["magnitude"] if r["mod_type"] == "momentum_hot" else -r["magnitude"] for r in rows)


def run_week(verbose=None, start_official=None):
    if verbose is None:
        verbose = "--verbose" in sys.argv or "-v" in sys.argv
    if start_official is None:
        start_official = "--start-official" in sys.argv

    create_tables()   # ensures new tables exist even without re-seeding
    conn = get_connection()
    c = conn.cursor()

    state = c.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return

    week        = state["current_week"]
    season_year = state["season_year"]
    mode = state["mode"] if "mode" in state.keys() else "test"
    official_started = state["official_started"] if "official_started" in state.keys() else 0

    if mode == "official" and not official_started:
        if not start_official:
            print("\nOfficial Year 1 has not started yet.")
            print("Run  python run_week.py --start-official  when you want Week 1 to count.\n")
            conn.close()
            return
        c.execute(
            "UPDATE league_state SET official_started = 1, last_updated = datetime('now') WHERE id = 1"
        )
        conn.commit()
        official_started = 1

    phase = state["phase"] if "phase" in state.keys() else "regular_season"

    print(f"\n{'='*54}")
    if phase == "playoffs":
        print(f"  WEEK {week}  --  {season_year} PLAYOFFS")
    elif mode == "test":
        print(f"  WEEK {week}  --  {season_year} SEASON  [TEST SIM]")
    else:
        print(f"  WEEK {week}  --  {season_year} SEASON  [OFFICIAL]")
    print(f"{'='*54}\n")

    games = c.execute("""
        SELECT g.id,
               g.home_team_id, g.away_team_id,
               g.playoff_series_id,
               ht.city || ' ' || ht.name AS home_name,
               at.city || ' ' || at.name AS away_name,
               ht.abbreviation AS home_abbr,
               at.abbreviation AS away_abbr
        FROM   games g
        JOIN   teams ht ON g.home_team_id = ht.id
        JOIN   teams at ON g.away_team_id = at.id
        WHERE  g.week = ? AND g.season_year = ? AND g.played = 0
    """, (week, season_year)).fetchall()

    if not games:
        remaining = c.execute(
            "SELECT COUNT(*) FROM games WHERE season_year = ? AND played = 0",
            (season_year,),
        ).fetchone()[0]
        if remaining == 0:
            if phase == "complete":
                print("The season is complete! Run  python view_league.py  to see the champion.\n")
            else:
                print("The season is over! Run  python view_league.py  for final standings.")
                print("GM personality review already ran at end of the final week.\n")
        else:
            print(f"No games scheduled for week {week}.")
        conn.close()
        return

    # ── Team chemistry (based on prior week's morale) ─────────────────────────
    has_personalities = c.execute(
        "SELECT COUNT(*) FROM player_personalities"
    ).fetchone()[0] > 0
    if has_personalities:
        compute_all_team_chemistry(conn, week, season_year)

    all_player_mods = _active_player_mods(conn, season_year, week)

    playoff_game_ids = []

    for game in games:
        home_players = [dict(p) for p in c.execute(
            "SELECT * FROM players "
            "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
            (game["home_team_id"],),
        ).fetchall()]
        away_players = [dict(p) for p in c.execute(
            "SELECT * FROM players "
            "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
            (game["away_team_id"],),
        ).fetchall()]

        home_chem = get_team_chemistry(conn, game["home_team_id"], week, season_year)
        away_chem = get_team_chemistry(conn, game["away_team_id"], week, season_year)
        home_team_mod = _active_team_chemistry_mod(conn, game["home_team_id"], season_year, week)
        away_team_mod = _active_team_chemistry_mod(conn, game["away_team_id"], season_year, week)
        h_score, a_score, h_box, a_box, h_q, a_q = simulate_game(
            home_players, away_players, home_chem, away_chem,
            home_player_mods=all_player_mods,
            away_player_mods=all_player_mods,
            home_team_mod=home_team_mod,
            away_team_mod=away_team_mod,
        )

        all_stats = h_box + a_box
        mvp_id = max(all_stats, key=lambda s: (
            s["points"] + s["rebounds"] * 0.75 + s["assists"] * 0.5
            + s["steals"] * 1.5 + s["blocks"] * 1.0
        ))["player_id"]

        c.execute(
            "UPDATE games SET home_score=?, away_score=?, played=1, "
            "q1_home=?, q2_home=?, q3_home=?, q4_home=?, "
            "q1_away=?, q2_away=?, q3_away=?, q4_away=?, "
            "mvp_player_id=? WHERE id=?",
            (h_score, a_score,
             h_q[0], h_q[1], h_q[2], h_q[3],
             a_q[0], a_q[1], a_q[2], a_q[3],
             mvp_id, game["id"]),
        )

        for stat in h_box + a_box:
            c.execute("""
                INSERT INTO player_game_stats
                    (game_id, player_id, team_id, points, rebounds, assists, steals, blocks)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (game["id"], stat["player_id"], stat["team_id"],
                  stat["points"], stat["rebounds"], stat["assists"],
                  stat["steals"], stat["blocks"]))

        home_won = h_score > a_score

        if game["playoff_series_id"]:
            playoff_game_ids.append(game["id"])
        else:
            c.execute("""
                UPDATE standings
                SET wins = wins + ?,
                    losses = losses + ?,
                    points_for = points_for + ?,
                    points_against = points_against + ?
                WHERE team_id = ? AND season_year = ?
            """, (1 if home_won else 0, 0 if home_won else 1,
                  h_score, a_score, game["home_team_id"], season_year))
            c.execute("""
                UPDATE standings
                SET wins = wins + ?,
                    losses = losses + ?,
                    points_for = points_for + ?,
                    points_against = points_against + ?
                WHERE team_id = ? AND season_year = ?
            """, (0 if home_won else 1, 1 if home_won else 0,
                  a_score, h_score, game["away_team_id"], season_year))

        winner = game["home_name"] if home_won else game["away_name"]
        marker = "  "
        print(f"{marker}{game['home_name']:<26} {h_score:>3}  --  {a_score:<3} {game['away_name']}")
        print(f"      Winner: {winner}\n")

        # Top performers this game
        all_stats = sorted(all_stats, key=lambda s: s["points"], reverse=True)
        print(f"      {'Top performers':}")
        for s in all_stats[:3]:
            player = c.execute(
                "SELECT first_name, last_name, position FROM players WHERE id = ?",
                (s["player_id"],),
            ).fetchone()
            print(f"        {player['first_name']} {player['last_name']:<18} "
                  f"{s['points']:>2} pts  {s['rebounds']} reb  {s['assists']} ast")
        print()

    c.execute(
        "UPDATE league_state SET current_week = current_week + 1, last_updated = datetime('now') WHERE id = 1"
    )
    conn.commit()

    # ── Post-game interviews ───────────────────────────────────────────────────
    has_backstories = c.execute(
        "SELECT COUNT(*) FROM player_backstories"
    ).fetchone()[0] > 0
    interview_count = 0
    if has_backstories:
        for game in games:
            candidates = set()
            for team_id in [game["home_team_id"], game["away_team_id"]]:
                top2 = c.execute("""
                    SELECT pgs.player_id
                    FROM player_game_stats pgs
                    JOIN players p ON p.id = pgs.player_id
                    WHERE pgs.game_id = ? AND p.team_id = ?
                    ORDER BY pgs.points + pgs.rebounds*0.75 + pgs.assists*0.5
                             + pgs.steals*1.5 + pgs.blocks DESC
                    LIMIT 2
                """, (game["id"], team_id)).fetchall()
                for row in top2:
                    candidates.add(row["player_id"])

            for pid in candidates:
                try:
                    build_interview_packet(game["id"], pid, db=conn)
                    interview_count += 1
                except Exception:
                    pass

    if interview_count:
        print(f"  {interview_count} post-game interview prompt(s) generated.")
        print("  View at /interviews or run: python view_interviews.py\n")

    # ── Midseason GM interviews ────────────────────────────────────────────────
    gm_count = c.execute("SELECT COUNT(*) FROM general_managers").fetchone()[0]
    if phase == "regular_season" and gm_count > 0:
        midseason_fired = c.execute(
            "SELECT COUNT(*) FROM gm_interviews WHERE season_year = ? AND trigger_type = 'midseason'",
            (season_year,)
        ).fetchone()[0]
        if not midseason_fired:
            total_reg = c.execute(
                "SELECT COUNT(*) FROM games WHERE season_year = ? AND playoff_series_id IS NULL",
                (season_year,)
            ).fetchone()[0]
            played_reg = c.execute(
                "SELECT COUNT(*) FROM games WHERE season_year = ? AND playoff_series_id IS NULL AND played = 1",
                (season_year,)
            ).fetchone()[0]
            if total_reg > 0 and played_reg * 2 >= total_reg:
                gms = c.execute("SELECT id FROM general_managers").fetchall()
                gm_iv_count = 0
                for gm in gms:
                    try:
                        build_gm_interview_packet(gm["id"], "midseason", db=conn)
                        gm_iv_count += 1
                    except Exception:
                        pass
                if gm_iv_count:
                    print(f"  {gm_iv_count} midseason GM interview prompt(s) generated.")
                    print("  View at /interviews or run: python view_interviews.py\n")

    # ── Player morale + actions (runs in both regular season and playoffs) ─────
    if has_personalities:
        run_all_player_agents(conn, week, season_year, verbose=verbose)

    reg_games_remaining = c.execute(
        "SELECT COUNT(*) FROM games WHERE season_year = ? AND played = 0"
        " AND playoff_series_id IS NULL",
        (season_year,),
    ).fetchone()[0]

    # ── Playoff result processing ─────────────────────────────────────────────
    if playoff_game_ids:
        _process_playoff_results_v2(conn, playoff_game_ids, week, season_year)

        # Interviews for any series that just completed this week
        placeholders = ",".join("?" * len(playoff_game_ids))
        just_completed = c.execute(f"""
            SELECT DISTINCT ps.id, ps.winner_id, ps.team_a_id, ps.team_b_id
            FROM playoff_series ps
            JOIN games g ON g.playoff_series_id = ps.id
            WHERE g.id IN ({placeholders})
              AND ps.season_year = ?
              AND ps.status = 'complete'
              AND NOT EXISTS (
                  SELECT 1 FROM gm_interviews gi
                  WHERE gi.playoff_series_id = ps.id
              )
        """, [*playoff_game_ids, season_year]).fetchall()

        po_player_count = 0
        po_gm_count = 0

        for series in just_completed:
            winner_id = series["winner_id"]
            loser_id = (
                series["team_b_id"] if series["winner_id"] == series["team_a_id"]
                else series["team_a_id"]
            )

            last_game = c.execute("""
                SELECT id FROM games
                WHERE playoff_series_id = ? AND played = 1
                ORDER BY week DESC, id DESC LIMIT 1
            """, (series["id"],)).fetchone()

            if last_game and has_backstories:
                for team_id, limit in [(winner_id, 3), (loser_id, 2)]:
                    top_players = c.execute("""
                        SELECT pgs.player_id
                        FROM player_game_stats pgs
                        JOIN players p ON p.id = pgs.player_id
                        WHERE pgs.game_id = ? AND p.team_id = ?
                        ORDER BY pgs.points + pgs.rebounds*0.75 + pgs.assists*0.5
                                 + pgs.steals*1.5 + pgs.blocks DESC
                        LIMIT ?
                    """, (last_game["id"], team_id, limit)).fetchall()
                    for row in top_players:
                        try:
                            build_interview_packet(last_game["id"], row["player_id"], db=conn)
                            po_player_count += 1
                        except Exception:
                            pass

            if gm_count > 0:
                winner_gm = c.execute(
                    "SELECT id FROM general_managers WHERE team_id = ?", (winner_id,)
                ).fetchone()
                loser_gm = c.execute(
                    "SELECT id FROM general_managers WHERE team_id = ?", (loser_id,)
                ).fetchone()
                for gm_row, trigger in [(winner_gm, "playoff_series_win"),
                                        (loser_gm, "playoff_series_loss")]:
                    if gm_row:
                        try:
                            build_gm_interview_packet(
                                gm_row["id"], trigger,
                                playoff_series_id=series["id"], db=conn
                            )
                            po_gm_count += 1
                        except Exception:
                            pass

        if po_player_count or po_gm_count:
            print(f"  Playoff series: {po_player_count} player interview(s) + "
                  f"{po_gm_count} GM interview(s) generated.")
            print("  View at /interviews or run: python view_interviews.py\n")

    # ── Regular-season end: seed playoffs ─────────────────────────────────────
    if phase == "regular_season" and reg_games_remaining == 0:
        if gm_count > 0:
            season_end_fired = c.execute(
                "SELECT COUNT(*) FROM gm_interviews WHERE season_year = ? AND trigger_type = 'season_end'",
                (season_year,)
            ).fetchone()[0]
            if not season_end_fired:
                gms = c.execute("SELECT id FROM general_managers").fetchall()
                gm_iv_count = 0
                for gm in gms:
                    try:
                        build_gm_interview_packet(gm["id"], "season_end", db=conn)
                        gm_iv_count += 1
                    except Exception:
                        pass
                if gm_iv_count:
                    print(f"  {gm_iv_count} end-of-season GM interview prompt(s) generated.")
                    print("  View at /interviews or run: python view_interviews.py\n")

        seed_playoffs(conn, week + 1, season_year)
        conn.execute("UPDATE league_state SET phase = 'playoffs' WHERE id = 1")
        conn.commit()
        phase = "playoffs"

    # ── GM weekly decisions (regular season only) ─────────────────────────────
    gm_count = c.execute("SELECT COUNT(*) FROM general_managers").fetchone()[0]
    if phase == "regular_season":
        if gm_count > 0 and reg_games_remaining > 0:
            run_all_gm_agents(conn, week, season_year, verbose=True)

            print(f"\n{'-'*54}")
            print("  AUTOPILOT TRADE REVIEW")
            print(f"{'-'*54}")
            trade_summary = autopilot_review_pending_trades(conn, season_year, verbose=True)
            if not any(trade_summary.values()):
                print("  No pending trades to review.")
        elif gm_count > 0:
            print(f"\n{'-'*54}")
            print("  GM AGENTS")
            print(f"{'-'*54}")
            print("  Regular-season trade proposals are closed; playoffs begin.\n")

            print(f"\n{'-'*54}")
            print("  AUTOPILOT TRADE REVIEW")
            print(f"{'-'*54}")
            trade_summary = autopilot_review_pending_trades(conn, season_year, verbose=True)
            if not any(trade_summary.values()):
                print("  No pending trades to review.")

        # Season-end GM personality drift fires when the regular season ends
        if gm_count > 0 and reg_games_remaining == 0:
            evaluate_all_gms_season_end(conn, season_year, verbose=True)

    # ── End-of-week summary ───────────────────────────────────────────────────
    # Re-read phase: _process_playoff_results may have set it to 'complete'
    fresh_phase = c.execute(
        "SELECT phase FROM league_state WHERE id = 1"
    ).fetchone()["phase"]
    pending_review_count = c.execute(
        "SELECT COUNT(*) FROM pending_trades WHERE status = 'pending'"
    ).fetchone()[0]
    conn.close()

    if fresh_phase == "complete":
        print(f"Week {week} complete.  The season is over — champion has been crowned!")
        print("Run  python view_league.py  to see the final standings and champion.\n")
        print("Run  python run_offseason.py  when you are ready for next season.\n")
    elif fresh_phase == "playoffs":
        print(f"Week {week} complete.  Now entering week {week + 1}  (playoffs).")
        print("Run  python view_league.py  to see the playoff bracket.")
        print("Run  python run_week.py  to simulate the next playoff game.\n")
    else:
        print(f"Week {week} complete.  Now entering week {week + 1}.")
        print("Run  python view_league.py  to see updated standings.")
        if pending_review_count:
            print(f"{pending_review_count} trade(s) still need commissioner review:"
                  f"  python review_trades.py\n")
        else:
            print("No commissioner trade review needed right now.\n")


if __name__ == "__main__":
    run_week()
