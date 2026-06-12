"""
Standalone script: run GM agent decisions for the current (or specified) week.
Can also be called as a library from run_week.py.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables
from league.gm_agents import run_all_gm_agents


def main(week=None, season_year=None):
    create_tables()
    conn = get_connection()
    c    = conn.cursor()

    state = c.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return

    # GMs deliberate on the week that just finished
    if week is None:
        week = state["current_week"] - 1
    if season_year is None:
        season_year = state["season_year"]

    if week < 1:
        print("No completed weeks yet. Run  python run_week.py  first.")
        conn.close()
        return

    print(f"\n{'='*54}")
    print(f"  GM DECISIONS  —  WEEK {week}  |  {season_year} SEASON")
    print(f"{'='*54}")

    run_all_gm_agents(conn, week, season_year, verbose=True)
    conn.close()


if __name__ == "__main__":
    # Optional: python run_gm_agents.py <week> <year>
    w  = int(sys.argv[1]) if len(sys.argv) > 1 else None
    yr = int(sys.argv[2]) if len(sys.argv) > 2 else None
    main(week=w, season_year=yr)
