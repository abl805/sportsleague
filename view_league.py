"""
Prints the current standings, last week's results, and top season performers.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection
from league.playoffs import get_bracket


def view_league():
    conn = get_connection()
    c = conn.cursor()

    state = c.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return

    week        = state["current_week"]
    season_year = state["season_year"]
    last_week   = week - 1
    phase = state["phase"] if "phase" in state.keys() else "regular_season"

    if phase == "complete":
        header = f"  BASKETBALL LEAGUE  |  {season_year} SEASON  |  COMPLETE"
    elif phase == "playoffs":
        header = f"  BASKETBALL LEAGUE  |  {season_year} SEASON  |  PLAYOFFS — WEEK {week}"
    else:
        header = f"  BASKETBALL LEAGUE  |  {season_year} SEASON  |  ENTERING WEEK {week}"

    print(f"\n{'='*58}")
    print(header)
    print(f"{'='*58}\n")

    # ── Standings ─────────────────────────────────────────────
    print("STANDINGS")
    print(f"  {'#':<3} {'Team':<28} {'W':>3} {'L':>3} {'PF':>6} {'PA':>6} {'DIFF':>6}")
    print(f"  {'-'*57}")

    rows = c.execute("""
        SELECT t.city || ' ' || t.name AS team_name,
               s.wins, s.losses, s.points_for, s.points_against,
               s.points_for - s.points_against AS diff
        FROM   standings s
        JOIN   teams t ON s.team_id = t.id
        WHERE  s.season_year = ?
        ORDER  BY s.wins DESC, (s.points_for - s.points_against) DESC
    """, (season_year,)).fetchall()

    for i, row in enumerate(rows, 1):
        diff_str = f"+{row['diff']}" if row['diff'] >= 0 else str(row['diff'])
        playoff_marker = " *" if i <= 4 and phase == "regular_season" else "  "
        print(f"  {i:<3} {row['team_name']:<28} {row['wins']:>3} {row['losses']:>3}"
              f" {row['points_for']:>6} {row['points_against']:>6} {diff_str:>6}"
              f"{playoff_marker}")

    if phase == "regular_season":
        print(f"  {'':3} * = playoff position")

    # ── Last week's results ────────────────────────────────────
    if last_week >= 1:
        print(f"\nWEEK {last_week} RESULTS")
        print(f"  {'-'*50}")

        games = c.execute("""
            SELECT ht.city || ' ' || ht.name AS home_name,
                   at.city || ' ' || at.name AS away_name,
                   g.home_score, g.away_score
            FROM   games g
            JOIN   teams ht ON g.home_team_id = ht.id
            JOIN   teams at ON g.away_team_id = at.id
            WHERE  g.week = ? AND g.season_year = ? AND g.played = 1
        """, (last_week, season_year)).fetchall()

        if not games:
            print("  No results recorded yet.")
        else:
            for g in games:
                home_w = g["home_score"] > g["away_score"]
                h = ("* " if home_w else "  ") + g["home_name"]
                a = ("* " if not home_w else "  ") + g["away_name"]
                print(f"  {h:<30}  {g['home_score']:>3} — {g['away_score']:<3}  {a}")
    else:
        print("\n  (No games played yet — run  python run_week.py  to start!)")

    # ── Season top performers ──────────────────────────────────
    print(f"\nTOP SCORERS  (season averages, min. 1 game)")
    print(f"  {'Player':<24} {'Team':>4} {'POS':>3} {'PPG':>6} {'RPG':>6} {'APG':>6} {'GP':>4}")
    print(f"  {'-'*57}")

    stars = c.execute("""
        SELECT p.first_name || ' ' || p.last_name AS name,
               t.abbreviation,
               p.position,
               ROUND(AVG(pgs.points),  1) AS ppg,
               ROUND(AVG(pgs.rebounds),1) AS rpg,
               ROUND(AVG(pgs.assists), 1) AS apg,
               COUNT(pgs.id)              AS gp
        FROM   player_game_stats pgs
        JOIN   games g ON pgs.game_id = g.id
        JOIN   players p ON pgs.player_id = p.id
        JOIN   teams   t ON p.team_id = t.id
        WHERE  g.season_year = ?
        GROUP  BY p.id
        HAVING gp >= 1
        ORDER  BY ppg DESC
        LIMIT  10
    """, (season_year,)).fetchall()

    if not stars:
        print("  No stats yet.")
    else:
        for row in stars:
            print(f"  {row['name']:<24} {row['abbreviation']:>4} {row['position']:>3}"
                  f" {row['ppg']:>6} {row['rpg']:>6} {row['apg']:>6} {row['gp']:>4}")

    # ── Playoff bracket ────────────────────────────────────────
    if phase in ("playoffs", "complete"):
        series_list = get_bracket(conn, season_year)
        if series_list:
            print("\nPLAYOFF BRACKET")
            current_round = None
            for s in series_list:
                if s["round"] != current_round:
                    current_round = s["round"]
                    round_label = "SEMIFINALS" if current_round == 1 else "FINALS"
                    print(f"\n  {round_label}")
                    print(f"  {'-'*50}")

                if s["status"] == "complete":
                    record = f"{s['team_a_wins']}-{s['team_b_wins']}"
                    result = f">> {s['winner_name']} wins  ({record})"
                    print(f"  #{s['seed_a']} {s['name_a']}  vs  #{s['seed_b']} {s['name_b']}")
                    print(f"     {result}")
                else:
                    print(f"  #{s['seed_a']} {s['name_a']}  vs  #{s['seed_b']} {s['name_b']}")
                    print(f"     {s['name_a']} {s['team_a_wins']}  —  "
                          f"{s['team_b_wins']} {s['name_b']}  (best of 3)")

        if phase == "complete":
            champ = conn.execute("""
                SELECT t.city || ' ' || t.name AS n
                FROM   playoff_series ps
                JOIN   teams t ON ps.winner_id = t.id
                WHERE  ps.season_year = ? AND ps.round = 2
            """, (season_year,)).fetchone()
            if champ:
                print(f"\n  {'*'*50}")
                print(f"    {season_year} CHAMPION:  {champ['n']}")
                print(f"  {'*'*50}")

    print()
    conn.close()


if __name__ == "__main__":
    view_league()
