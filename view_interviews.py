"""
CLI for post-game interview prompts.

Usage:
    python view_interviews.py              -- list all pending prompts
    python view_interviews.py --all        -- list pending + completed
    python view_interviews.py --show ID    -- print the full prompt for a player interview
    python view_interviews.py --submit ID  -- paste a response for player interview ID
    python view_interviews.py --show-gm ID   -- print the full prompt for a GM interview
    python view_interviews.py --submit-gm ID -- paste a response for GM interview ID
"""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))
from league.database import get_connection, create_tables
from league.chatgpt_bridge import (
    get_pending_interviews,
    get_recent_interviews,
    save_interview_response,
    get_pending_gm_interviews,
    get_recent_gm_interviews,
    save_gm_interview_response,
)


def _separator():
    print("-" * 60)


TRIGGER_LABELS = {
    "midseason": "Midseason",
    "season_end": "End of Season",
    "playoff_series_win": "Playoff Series Win",
    "playoff_series_loss": "Playoff Series Loss",
}


def cmd_list(show_all=False):
    create_tables()
    conn = get_connection()
    state = conn.execute("SELECT season_year FROM league_state WHERE id=1").fetchone()
    if not state:
        print("League not found. Run  python seed.py  first.")
        conn.close()
        return
    season_year = state["season_year"]

    pending_players = get_pending_interviews(conn, season_year=season_year)
    pending_gms = get_pending_gm_interviews(conn, season_year=season_year)
    completed_players = get_recent_interviews(conn, season_year, limit=20) if show_all else []
    completed_gms = get_recent_gm_interviews(conn, season_year, limit=20) if show_all else []
    conn.close()

    print(f"\n{'='*60}")
    print("  POST-GAME INTERVIEWS")
    print(f"{'='*60}\n")

    # ── Pending player interviews ──────────────────────────────────────────
    if pending_players:
        print(f"  PENDING PLAYER PROMPTS ({len(pending_players)}):\n")
        for iv in pending_players:
            print(f"  [{iv['id']}]  Week {iv['week']}  |  {iv['player_name']}  ({iv['team_name']})")
            print(f"       Q: {iv['question']}")
            print(f"       Run:  python view_interviews.py --show {iv['id']}   to see full prompt")
            print(f"       Run:  python view_interviews.py --submit {iv['id']}  to paste response\n")
    else:
        print("  No pending player interview prompts.\n")

    # ── Pending GM interviews ──────────────────────────────────────────────
    if pending_gms:
        print(f"  PENDING GM PROMPTS ({len(pending_gms)}):\n")
        for iv in pending_gms:
            label = TRIGGER_LABELS.get(iv["trigger_type"], iv["trigger_type"])
            print(f"  [{iv['id']}]  Week {iv['week']}  |  {iv['gm_name']}  ({iv['team_name']})  [{label}]")
            print(f"       Q: {iv['question']}")
            print(f"       Run:  python view_interviews.py --show-gm {iv['id']}   to see full prompt")
            print(f"       Run:  python view_interviews.py --submit-gm {iv['id']}  to paste response\n")
    else:
        print("  No pending GM interview prompts.\n")

    if show_all:
        # ── Completed player interviews ────────────────────────────────────
        if completed_players:
            _separator()
            print(f"\n  COMPLETED PLAYER INTERVIEWS ({len(completed_players)}):\n")
            for iv in completed_players:
                print(f"  [{iv['id']}]  Week {iv['week']}  |  {iv['player_name']}  ({iv['team_name']})")
                label = iv.get("personality_label") or ""
                if label:
                    print(f"       [{label}]")
                print(f"       Q: {iv['question']}")
                print(f"       A: {iv['response']}\n")

        # ── Completed GM interviews ────────────────────────────────────────
        if completed_gms:
            _separator()
            print(f"\n  COMPLETED GM INTERVIEWS ({len(completed_gms)}):\n")
            for iv in completed_gms:
                label = TRIGGER_LABELS.get(iv["trigger_type"], iv["trigger_type"])
                print(f"  [{iv['id']}]  Week {iv['week']}  |  {iv['gm_name']}  ({iv['team_name']})  [{label}]")
                print(f"       Q: {iv['question']}")
                print(f"       A: {iv['response']}\n")


def cmd_show(interview_id):
    create_tables()
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM player_interviews WHERE id = ?", (interview_id,)
    ).fetchone()
    conn.close()
    if not row:
        print(f"Player interview {interview_id} not found.")
        return
    print(f"\n{'='*60}")
    print(f"  PLAYER INTERVIEW {interview_id} — FULL PROMPT")
    print(f"{'='*60}\n")
    print(row["context_packet"])
    print(f"\n{'='*60}")
    print(f"  Copy the prompt above into ChatGPT, then run:")
    print(f"  python view_interviews.py --submit {interview_id}")
    print(f"{'='*60}\n")


def cmd_show_gm(interview_id):
    create_tables()
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM gm_interviews WHERE id = ?", (interview_id,)
    ).fetchone()
    conn.close()
    if not row:
        print(f"GM interview {interview_id} not found.")
        return
    print(f"\n{'='*60}")
    print(f"  GM INTERVIEW {interview_id} — FULL PROMPT")
    print(f"{'='*60}\n")
    print(row["context_packet"])
    print(f"\n{'='*60}")
    print(f"  Copy the prompt above into ChatGPT, then run:")
    print(f"  python view_interviews.py --submit-gm {interview_id}")
    print(f"{'='*60}\n")


def cmd_submit(interview_id):
    create_tables()
    conn = get_connection()
    row = conn.execute(
        "SELECT id, player_id, question FROM player_interviews WHERE id = ?",
        (interview_id,)
    ).fetchone()
    if not row:
        conn.close()
        print(f"Player interview {interview_id} not found.")
        return
    player = conn.execute(
        "SELECT first_name, last_name FROM players WHERE id = ?",
        (row["player_id"],)
    ).fetchone()
    conn.close()

    full_name = f"{player['first_name']} {player['last_name']}" if player else "Player"
    print(f"\nPasting response for player interview #{interview_id} — {full_name}")
    print(f"Q: {row['question']}\n")
    print("Paste ChatGPT's response below, then press Enter twice (blank line) to save:\n")

    lines = []
    while True:
        line = input()
        if line == "" and lines:
            break
        lines.append(line)

    response_text = "\n".join(lines).strip()
    if not response_text:
        print("No response entered — nothing saved.")
        return

    save_interview_response(interview_id, response_text)
    print(f"\nSaved! Player interview #{interview_id} is now complete.")
    print("It will appear on the player's profile page in the web app.\n")


def cmd_submit_gm(interview_id):
    create_tables()
    conn = get_connection()
    row = conn.execute(
        "SELECT gi.id, gi.gm_id, gi.question, gm.name AS gm_name "
        "FROM gm_interviews gi JOIN general_managers gm ON gm.id = gi.gm_id "
        "WHERE gi.id = ?",
        (interview_id,)
    ).fetchone()
    conn.close()
    if not row:
        print(f"GM interview {interview_id} not found.")
        return

    print(f"\nPasting response for GM interview #{interview_id} — {row['gm_name']}")
    print(f"Q: {row['question']}\n")
    print("Paste ChatGPT's response below, then press Enter twice (blank line) to save:\n")

    lines = []
    while True:
        line = input()
        if line == "" and lines:
            break
        lines.append(line)

    response_text = "\n".join(lines).strip()
    if not response_text:
        print("No response entered — nothing saved.")
        return

    save_gm_interview_response(interview_id, response_text)
    print(f"\nSaved! GM interview #{interview_id} is now complete.")
    print("It will appear on the GM's team page in the web app.\n")


if __name__ == "__main__":
    args = sys.argv[1:]

    if not args:
        cmd_list(show_all=False)
    elif args[0] == "--all":
        cmd_list(show_all=True)
    elif args[0] == "--show" and len(args) == 2:
        cmd_show(int(args[1]))
    elif args[0] == "--submit" and len(args) == 2:
        cmd_submit(int(args[1]))
    elif args[0] == "--show-gm" and len(args) == 2:
        cmd_show_gm(int(args[1]))
    elif args[0] == "--submit-gm" and len(args) == 2:
        cmd_submit_gm(int(args[1]))
    else:
        print(__doc__)
