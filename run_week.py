"""
Simulates all games for the current week, updates standings, and advances
the league clock by one week. Run this once per "week" as commissioner.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection
from league.simulation import simulate_game


def run_week():
    conn = get_connection()
    c = conn.cursor()

    state = c.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return

    week        = state["current_week"]
    season_year = state["season_year"]

    print(f"\n{'='*54}")
    print(f"  WEEK {week}  —  {season_year} SEASON")
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
        else:
            print(f"No games scheduled for week {week}.")
        conn.close()
        return

    for game in games:
        home_players = [dict(p) for p in c.execute(
            "SELECT * FROM players WHERE team_id = ?", (game["home_team_id"],)
        ).fetchall()]
        away_players = [dict(p) for p in c.execute(
            "SELECT * FROM players WHERE team_id = ?", (game["away_team_id"],)
        ).fetchall()]

        h_score, a_score, h_box, a_box = simulate_game(home_players, away_players)

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
        print(f"{marker}{game['home_name']:<26} {h_score:>3}  —  {a_score:<3} {game['away_name']}")
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
    conn.close()

    print(f"Week {week} complete.  Now entering week {week + 1}.")
    print("Run  python view_league.py  to see updated standings.\n")


if __name__ == "__main__":
    run_week()
