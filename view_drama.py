"""
Commissioner drama dashboard. Shows morale crises, active trade demands,
ongoing feuds, retirement notices, and team chemistry scores.

Usage:  python view_drama.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables
from league.player_agents import get_current_morale


def view_drama():
    create_tables()
    conn = get_connection()
    c    = conn.cursor()

    state = c.execute("SELECT current_week, season_year FROM league_state WHERE id=1").fetchone()
    if not state:
        print("No league found. Run  python seed.py  first.")
        conn.close()
        return

    week        = state["current_week"] - 1   # last completed week
    season_year = state["season_year"]

    print(f"\n{'='*60}")
    print(f"  DRAMA REPORT  --  After Week {week}  |  {season_year} Season")
    print(f"{'='*60}")

    # ── Team chemistry ────────────────────────────────────────────────────────
    print(f"\n  TEAM CHEMISTRY")
    print(f"  {'-'*56}")
    teams = c.execute("SELECT id, city, name, abbreviation FROM teams").fetchall()
    for team in teams:
        tid  = team["id"]
        chem = conn.execute(
            "SELECT chemistry FROM team_chemistry WHERE team_id=? AND season_year=? "
            "ORDER BY week DESC LIMIT 1",
            (tid, season_year),
        ).fetchone()
        chem_val = chem["chemistry"] if chem else 70.0
        bar_len  = int(chem_val / 100 * 20)
        bar      = "#" * bar_len + "-" * (20 - bar_len)
        label    = (
            "CRISIS" if chem_val < 45 else
            "low"    if chem_val < 58 else
            "ok"     if chem_val < 72 else
            "good"   if chem_val < 85 else
            "great"
        )
        print(f"  {team['abbreviation']}  [{bar}] {chem_val:5.1f}  {label}")

    # ── Low morale players ────────────────────────────────────────────────────
    low_players = []
    for row in c.execute(
        "SELECT p.id, p.first_name, p.last_name, p.age, p.team_id, t.abbreviation AS abbr,"
        "       pp.archetype"
        " FROM players p"
        " JOIN player_personalities pp ON p.id = pp.player_id"
        " JOIN teams t ON p.team_id = t.id"
        " WHERE COALESCE(p.status, 'active') = 'active'"
    ).fetchall():
        m = get_current_morale(conn, row["id"])
        if m < 45:
            low_players.append((m, dict(row)))

    low_players.sort(key=lambda x: x[0])

    if low_players:
        print(f"\n  LOW MORALE  (below 45)")
        print(f"  {'-'*56}")
        for morale, p in low_players:
            bar_len = int(morale / 100 * 20)
            bar     = "#" * bar_len + "-" * (20 - bar_len)
            print(
                f"  [{bar}] {morale:4.0f}  "
                f"{p['first_name']} {p['last_name']:<20} "
                f"[{p['archetype']}]  {p['abbr']}"
            )

    # ── Active trade demands ──────────────────────────────────────────────────
    demands = c.execute("""
        SELECT pe.detail, pe.week, p.first_name, p.last_name, t.abbreviation AS abbr,
               pp.archetype
        FROM   player_events pe
        JOIN   players p  ON pe.player_id = p.id
        JOIN   teams   t  ON p.team_id = t.id
        JOIN   player_personalities pp ON p.id = pp.player_id
        WHERE  pe.event_type = 'trade_demand' AND pe.status = 'active'
        ORDER  BY pe.week DESC
    """).fetchall()

    if demands:
        print(f"\n  ACTIVE TRADE DEMANDS")
        print(f"  {'-'*56}")
        for d in demands:
            print(
                f"  Wk{d['week']:>2}  {d['first_name']} {d['last_name']:<20} "
                f"[{d['archetype']}]  {d['abbr']}"
            )
            print(f"         {d['detail']}")

    # ── Active feuds ──────────────────────────────────────────────────────────
    feuds = c.execute("""
        SELECT pe.detail, pe.week, t.abbreviation AS abbr
        FROM   player_events pe
        JOIN   players p ON pe.player_id = p.id
        JOIN   teams   t ON p.team_id = t.id
        WHERE  pe.event_type = 'feud' AND pe.status = 'active'
        ORDER  BY pe.week DESC
    """).fetchall()

    if feuds:
        print(f"\n  ACTIVE FEUDS")
        print(f"  {'-'*56}")
        for f in feuds:
            print(f"  Wk{f['week']:>2}  [{f['abbr']}]  {f['detail']}")

    # ── Recent public complaints ──────────────────────────────────────────────
    complaints = c.execute("""
        SELECT pe.detail, pe.week, p.first_name, p.last_name, t.abbreviation AS abbr,
               pp.archetype
        FROM   player_events pe
        JOIN   players p  ON pe.player_id = p.id
        JOIN   teams   t  ON p.team_id = t.id
        JOIN   player_personalities pp ON p.id = pp.player_id
        WHERE  pe.event_type = 'public_complaint' AND pe.status = 'active'
        ORDER  BY pe.week DESC
        LIMIT  8
    """).fetchall()

    if complaints:
        print(f"\n  PUBLIC COMPLAINTS")
        print(f"  {'-'*56}")
        for comp in complaints:
            print(
                f"  Wk{comp['week']:>2}  {comp['first_name']} {comp['last_name']:<20} "
                f"[{comp['archetype']}]  {comp['abbr']}"
            )
            print(f"         {comp['detail']}")

    # ── Retirement notices ────────────────────────────────────────────────────
    retirements = c.execute("""
        SELECT pe.detail, pe.week, p.first_name, p.last_name, p.age,
               t.abbreviation AS abbr, pp.archetype
        FROM   player_events pe
        JOIN   players p  ON pe.player_id = p.id
        JOIN   teams   t  ON p.team_id = t.id
        JOIN   player_personalities pp ON p.id = pp.player_id
        WHERE  pe.event_type = 'retirement' AND pe.status = 'active'
        ORDER  BY pe.week DESC
    """).fetchall()

    if retirements:
        print(f"\n  RETIREMENT NOTICES")
        print(f"  {'-'*56}")
        for r in retirements:
            print(
                f"  Wk{r['week']:>2}  {r['first_name']} {r['last_name']:<20} "
                f"age {r['age']}  [{r['archetype']}]  {r['abbr']}"
            )
            print(f"         {r['detail']}")

    # ── Contract extension requests ───────────────────────────────────────────
    ext_reqs = c.execute("""
        SELECT pe.week, p.first_name, p.last_name, t.abbreviation AS abbr, pp.archetype
        FROM   player_events pe
        JOIN   players p  ON pe.player_id = p.id
        JOIN   teams   t  ON p.team_id = t.id
        JOIN   player_personalities pp ON p.id = pp.player_id
        WHERE  pe.event_type = 'contract_request' AND pe.status = 'active'
        ORDER  BY pe.week DESC
    """).fetchall()

    if ext_reqs:
        print(f"\n  CONTRACT EXTENSION REQUESTS")
        print(f"  {'-'*56}")
        for req in ext_reqs:
            print(
                f"  Wk{req['week']:>2}  {req['first_name']} {req['last_name']:<20} "
                f"[{req['archetype']}]  {req['abbr']}"
            )

    # ── Quiet week ────────────────────────────────────────────────────────────
    nothing = not low_players and not demands and not feuds and not complaints and not retirements
    if nothing:
        print(f"\n  No drama to report. League is stable.")

    print(f"\n{'='*60}\n")
    conn.close()


if __name__ == "__main__":
    view_drama()
