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


def run_week():
    verbose = "--verbose" in sys.argv or "-v" in sys.argv

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
        if "--start-official" not in sys.argv:
            print("\nOfficial Year 1 has not started yet.")
            print("Run  python run_week.py --start-official  when you want Week 1 to count.\n")
            conn.close()
            return
        c.execute(
            "UPDATE league_state SET official_started = 1, last_updated = datetime('now') WHERE id = 1"
        )
        conn.commit()
        official_started = 1

    print(f"\n{'='*54}")
    label = "TEST SIM" if mode == "test" else "OFFICIAL"
    print(f"  WEEK {week}  --  {season_year} SEASON  [{label}]")
    print(f"{'='*54}\n")

    games = c.execute("""
        SELECT g.id,
               g.home_team_id, g.away_team_id,
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

    for game in games:
        home_players = [dict(p) for p in c.execute(
            "SELECT * FROM players WHERE team_id = ?", (game["home_team_id"],)
        ).fetchall()]
        away_players = [dict(p) for p in c.execute(
            "SELECT * FROM players WHERE team_id = ?", (game["away_team_id"],)
        ).fetchall()]

        home_chem = get_team_chemistry(conn, game["home_team_id"], week, season_year)
        away_chem = get_team_chemistry(conn, game["away_team_id"], week, season_year)
        h_score, a_score, h_box, a_box = simulate_game(
            home_players, away_players, home_chem, away_chem
        )

        c.execute(
            "UPDATE games SET home_score=?, away_score=?, played=1 WHERE id=?",
            (h_score, a_score, game["id"]),
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
        all_stats = sorted(h_box + a_box, key=lambda s: s["points"], reverse=True)
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

    # ── Player morale + actions ───────────────────────────────────────────────
    if has_personalities:
        run_all_player_agents(conn, week, season_year, verbose=verbose)

    # ── GM weekly decisions ───────────────────────────────────────────────────
    gm_count = c.execute("SELECT COUNT(*) FROM general_managers").fetchone()[0]
    if gm_count > 0:
        run_all_gm_agents(conn, week, season_year, verbose=True)

        print(f"\n{'-'*54}")
        print("  AUTOPILOT TRADE REVIEW")
        print(f"{'-'*54}")
        trade_summary = autopilot_review_pending_trades(conn, season_year, verbose=True)
        if not any(trade_summary.values()):
            print("  No pending trades to review.")

    # ── Season-end personality drift (fires only on the final week) ───────────
    games_remaining = c.execute(
        "SELECT COUNT(*) FROM games WHERE season_year = ? AND played = 0",
        (season_year,),
    ).fetchone()[0]
    if games_remaining == 0 and gm_count > 0:
        evaluate_all_gms_season_end(conn, season_year, verbose=True)
    # ─────────────────────────────────────────────────────────────────────────

    pending_review_count = c.execute(
        "SELECT COUNT(*) FROM pending_trades WHERE status = 'pending'"
    ).fetchone()[0]
    conn.close()

    if games_remaining == 0:
        print(f"Week {week} complete.  Season {season_year} is finished.")
        print("Run  python view_league.py  for final standings.\n")
    else:
        print(f"Week {week} complete.  Now entering week {week + 1}.")
        print("Run  python view_league.py  to see updated standings.")
        if pending_review_count:
            print(f"{pending_review_count} trade(s) still need commissioner review: python review_trades.py\n")
        else:
            print("No commissioner trade review needed right now.\n")


if __name__ == "__main__":
    run_week()
