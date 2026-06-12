"""
Commissioner trade review CLI.

Shows each pending trade with both GMs' reasoning.
Options per trade:  [a]pprove  [v]eto  [s]kip
"""
import sys
import os
import json

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables
from league.trade_engine import validate_trade, execute_trade, veto_trade, invalidate_trade


def _fmt_money(n):
    return f"${n / 1_000_000:.1f}M"


def _player_line(p):
    return (
        f"  • {p['first_name']} {p['last_name']:<22}"
        f"  {p['position']:>3}  age {p['age']:>2}  "
        f"skill {p['skill_rating']:>3}  {_fmt_money(p['salary'])}"
    )


def _show_trade(c, trade):
    trade = dict(trade)

    prop_gm = dict(c.execute("""
        SELECT gm.*, t.city, t.name AS tname
        FROM   general_managers gm JOIN teams t ON gm.team_id = t.id
        WHERE  gm.id = ?
    """, (trade["proposing_gm_id"],)).fetchone())

    recv_gm = dict(c.execute("""
        SELECT gm.*, t.city, t.name AS tname
        FROM   general_managers gm JOIN teams t ON gm.team_id = t.id
        WHERE  gm.id = ?
    """, (trade["receiving_gm_id"],)).fetchone())

    offered_players   = [
        dict(c.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone())
        for pid in json.loads(trade["offered_player_ids"])
    ]
    requested_players = [
        dict(c.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone())
        for pid in json.loads(trade["requested_player_ids"])
    ]

    print(f"\n{'='*62}")
    print(f"  TRADE #{trade['id']}  |  Week {trade['week']}  |  {trade['status'].upper()}")
    print(f"{'='*62}")
    print(f"\n  PROPOSED BY : {prop_gm['name']}")
    print(f"                {prop_gm['city']} {prop_gm['tname']}  [{prop_gm['archetype']}]")
    print(f"\n  RECEIVING   : {recv_gm['name']}")
    print(f"                {recv_gm['city']} {recv_gm['tname']}  [{recv_gm['archetype']}]")

    print(f"\n  {prop_gm['city']} {prop_gm['tname']} SENDS:")
    for p in offered_players:
        print(_player_line(p))

    print(f"\n  {recv_gm['city']} {recv_gm['tname']} SENDS:")
    for p in requested_players:
        print(_player_line(p))

    pscore = trade.get("proposing_score") or 0.0
    rscore = trade.get("receiving_score") or 0.0

    print(f"\n  PROPOSER'S VIEW  (score {pscore:.2f}):")
    for part in (trade.get("proposing_reasoning") or "").split(";"):
        part = part.strip()
        if part:
            print(f"    {part}")

    print(f"\n  RECEIVER'S LIKELY VIEW  (score {rscore:.2f}):")
    for part in (trade.get("receiving_reasoning") or "").split(";"):
        part = part.strip()
        if part:
            print(f"    {part}")

    if rscore < 0.35:
        print(f"\n  *** Receiver score {rscore:.2f} is low — they may not want this deal. ***")
    if trade.get("rejection_reason"):
        print(f"\n  COMMISSIONER NOTE:")
        print(f"    {trade['rejection_reason']}")


def review_trades():
    create_tables()
    conn = get_connection()
    c    = conn.cursor()

    state = c.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return

    pending = c.execute(
        "SELECT * FROM pending_trades WHERE status = 'pending' ORDER BY week, id"
    ).fetchall()

    if not pending:
        print("\nNo pending trades.\n")
        conn.close()
        return

    print(f"\nFound {len(pending)} pending trade(s).\n")

    approved = vetoed = skipped = auto_invalid = 0

    for trade in pending:
        # Validate before showing
        ok, reason = validate_trade(conn, trade["id"])
        if not ok:
            print(f"\nTrade #{trade['id']} failed validation: {reason}")
            invalidate_trade(conn, trade["id"], reason)
            auto_invalid += 1
            continue

        _show_trade(c, trade)

        print(f"\n  [a]pprove  [v]eto  [s]kip  > ", end="", flush=True)
        try:
            choice = input().strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n\nReview interrupted.")
            break

        if choice == "a":
            execute_trade(conn, trade["id"])
            print(f"  Trade #{trade['id']} APPROVED and executed.")
            approved += 1
        elif choice == "v":
            print("  Veto reason (press Enter to skip): ", end="", flush=True)
            try:
                msg = input().strip()
            except (EOFError, KeyboardInterrupt):
                msg = ""
            veto_trade(conn, trade["id"], msg or "Vetoed by commissioner.")
            print(f"  Trade #{trade['id']} VETOED.")
            vetoed += 1
        else:
            print(f"  Trade #{trade['id']} skipped (still pending).")
            skipped += 1

    conn.close()
    print(f"\n{'─'*40}")
    print(f"  Review done: {approved} approved  {vetoed} vetoed  "
          f"{skipped} skipped  {auto_invalid} invalid\n")


if __name__ == "__main__":
    review_trades()
