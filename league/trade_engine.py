"""
Trade validation and execution.
"""
import json
import os


def _load_cap():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")
    with open(path) as f:
        return json.load(f).get("salary_cap", 100_000_000)


def _load_archetypes():
    path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")
    with open(path) as f:
        return json.load(f)


def _trade_policy():
    return _load_archetypes().get("trade_policy", {})


def validate_trade(conn, trade_id):
    """
    Validates a pending trade. Returns (is_valid: bool, reason: str).

    Checks:
    - Trade exists and is still pending
    - All offered players exist and belong to the proposing team
    - All requested players exist and belong to the receiving team
    - Neither team exceeds the salary cap after the swap
    - No player involved is already in another pending trade
    """
    cap = _load_cap()

    trade = conn.execute(
        "SELECT * FROM pending_trades WHERE id = ?", (trade_id,)
    ).fetchone()
    if not trade:
        return False, "Trade not found."
    trade = dict(trade)

    if trade["status"] != "pending":
        return False, f"Trade is already '{trade['status']}'."

    prop_gm = conn.execute(
        "SELECT * FROM general_managers WHERE id = ?", (trade["proposing_gm_id"],)
    ).fetchone()
    recv_gm = conn.execute(
        "SELECT * FROM general_managers WHERE id = ?", (trade["receiving_gm_id"],)
    ).fetchone()
    if not prop_gm or not recv_gm:
        return False, "One or both GMs not found."

    prop_team = prop_gm["team_id"]
    recv_team = recv_gm["team_id"]

    offered_ids   = json.loads(trade["offered_player_ids"])
    requested_ids = json.loads(trade["requested_player_ids"])

    for pid in offered_ids:
        p = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
        if not p:
            return False, f"Offered player id={pid} does not exist."
        if (p["status"] or "active") != "active":
            return False, f"{p['first_name']} {p['last_name']} is not on an active roster."
        if p["team_id"] != prop_team:
            return False, (
                f"{p['first_name']} {p['last_name']} is no longer on the proposing team."
            )

    for pid in requested_ids:
        p = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
        if not p:
            return False, f"Requested player id={pid} does not exist."
        if (p["status"] or "active") != "active":
            return False, f"{p['first_name']} {p['last_name']} is not on an active roster."
        if p["team_id"] != recv_team:
            return False, (
                f"{p['first_name']} {p['last_name']} is no longer on the receiving team."
            )

    # Cap check: compute team totals, then swap
    def team_total(team_id):
        row = conn.execute(
            "SELECT SUM(salary) AS s FROM players "
            "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
            (team_id,),
        ).fetchone()
        return row["s"] or 0

    offered_sal   = sum(
        conn.execute("SELECT salary FROM players WHERE id = ?", (pid,)).fetchone()["salary"]
        for pid in offered_ids
    )
    requested_sal = sum(
        conn.execute("SELECT salary FROM players WHERE id = ?", (pid,)).fetchone()["salary"]
        for pid in requested_ids
    )

    prop_post = team_total(prop_team) - offered_sal + requested_sal
    recv_post = team_total(recv_team) - requested_sal + offered_sal

    if prop_post > cap:
        over = (prop_post - cap) / 1_000_000
        return False, f"Proposing team would be ${over:.1f}M over the cap."
    if recv_post > cap:
        over = (recv_post - cap) / 1_000_000
        return False, f"Receiving team would be ${over:.1f}M over the cap."

    # Conflict check: no player already in another pending trade
    # (Use Python set intersection — avoid LIKE substring false-positives)
    all_pids = set(offered_ids + requested_ids)
    other_pending = conn.execute("""
        SELECT id, offered_player_ids, requested_player_ids
        FROM   pending_trades
        WHERE  status = 'pending' AND id != ?
    """, (trade_id,)).fetchall()

    for other in other_pending:
        other_pids = set(
            json.loads(other["offered_player_ids"]) +
            json.loads(other["requested_player_ids"])
        )
        overlap = all_pids & other_pids
        if overlap:
            pid = next(iter(overlap))
            p = conn.execute(
                "SELECT first_name, last_name FROM players WHERE id = ?", (pid,)
            ).fetchone()
            name = f"{p['first_name']} {p['last_name']}" if p else f"player {pid}"
            return False, f"{name} is already in pending trade #{other['id']}."

    return True, "Valid"


def execute_trade(conn, trade_id):
    """
    Execute an approved trade: swap players between teams and mark the trade approved.
    """
    trade = dict(conn.execute(
        "SELECT * FROM pending_trades WHERE id = ?", (trade_id,)
    ).fetchone())

    prop_gm   = dict(conn.execute(
        "SELECT * FROM general_managers WHERE id = ?", (trade["proposing_gm_id"],)
    ).fetchone())
    recv_gm   = dict(conn.execute(
        "SELECT * FROM general_managers WHERE id = ?", (trade["receiving_gm_id"],)
    ).fetchone())

    prop_team = prop_gm["team_id"]
    recv_team = recv_gm["team_id"]

    for pid in json.loads(trade["offered_player_ids"]):
        conn.execute("UPDATE players   SET team_id = ? WHERE id = ?", (recv_team, pid))
        conn.execute("UPDATE contracts SET team_id = ? WHERE player_id = ?", (recv_team, pid))

    for pid in json.loads(trade["requested_player_ids"]):
        conn.execute("UPDATE players   SET team_id = ? WHERE id = ?", (prop_team, pid))
        conn.execute("UPDATE contracts SET team_id = ? WHERE player_id = ?", (prop_team, pid))

    conn.execute(
        "UPDATE pending_trades SET status = 'approved' WHERE id = ?", (trade_id,)
    )
    conn.commit()


def veto_trade(conn, trade_id, reason="Vetoed by commissioner."):
    conn.execute(
        "UPDATE pending_trades SET status = 'vetoed', rejection_reason = ? WHERE id = ?",
        (reason, trade_id),
    )
    conn.commit()


def invalidate_trade(conn, trade_id, reason):
    conn.execute(
        "UPDATE pending_trades SET status = 'invalid', rejection_reason = ? WHERE id = ?",
        (reason, trade_id),
    )
    conn.commit()


def expire_trade(conn, trade_id, reason):
    conn.execute(
        "UPDATE pending_trades SET status = 'expired', rejection_reason = ? WHERE id = ?",
        (reason, trade_id),
    )
    conn.commit()


def _trade_players(conn, trade):
    ids = json.loads(trade["offered_player_ids"]) + json.loads(trade["requested_player_ids"])
    if not ids:
        return []
    placeholders = ",".join("?" for _ in ids)
    return [
        dict(row)
        for row in conn.execute(
            f"SELECT * FROM players WHERE id IN ({placeholders})", ids
        ).fetchall()
    ]


def _mark_needs_commissioner(conn, trade_id, reason):
    conn.execute(
        "UPDATE pending_trades SET rejection_reason = ? WHERE id = ?",
        (f"Needs commissioner: {reason}", trade_id),
    )
    conn.commit()


def autopilot_review_pending_trades(conn, season_year=None, verbose=True):
    """
    Conservative autonomous trade review.

    Approves clear, valid consensus trades; vetoes one-sided low-receiver-score
    offers; leaves star or ambiguous deals pending for commissioner review.
    """
    policy = _trade_policy()
    min_prop = policy.get("autopilot_min_proposer_score", 0.74)
    min_recv = policy.get("autopilot_min_receiver_score", 0.64)
    veto_recv_below = policy.get("autopilot_veto_receiver_below", 0.38)
    star_line = policy.get("autopilot_escalate_star_skill", 84)
    expire_weeks = policy.get("pending_trade_expire_weeks", 3)
    expire_at_season_end = policy.get("expire_pending_at_season_end", True)

    state = conn.execute("SELECT current_week FROM league_state WHERE id = 1").fetchone()
    current_week = state["current_week"] if state else None
    season_finished = False
    if season_year is not None:
        remaining = conn.execute(
            "SELECT COUNT(*) FROM games WHERE season_year = ? AND played = 0",
            (season_year,),
        ).fetchone()[0]
        season_finished = remaining == 0

    if season_year is None:
        rows = conn.execute(
            "SELECT * FROM pending_trades WHERE status = 'pending' ORDER BY week, id"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pending_trades WHERE status = 'pending' "
            "AND season_year = ? ORDER BY week, id",
            (season_year,),
        ).fetchall()

    summary = {
        "approved": 0,
        "vetoed": 0,
        "invalid": 0,
        "expired": 0,
        "needs_commissioner": 0,
    }

    for row in rows:
        trade = dict(row)
        if expire_at_season_end and season_finished:
            reason = (
                "Expired at season end; GM must resubmit or build a new "
                "offseason counteroffer."
            )
            expire_trade(conn, trade["id"], reason)
            summary["expired"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} expired: season ended")
            continue

        if current_week is not None and current_week - trade["week"] > expire_weeks:
            reason = (
                f"Expired after {expire_weeks} weeks pending; "
                "GM must resubmit or build a new counteroffer."
            )
            expire_trade(conn, trade["id"], reason)
            summary["expired"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} expired: pending too long")
            continue

        ok, reason = validate_trade(conn, trade["id"])
        if not ok:
            invalidate_trade(conn, trade["id"], reason)
            summary["invalid"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} invalidated: {reason}")
            continue

        players = _trade_players(conn, trade)
        max_skill = max((p["skill_rating"] for p in players), default=0)
        prop_score = trade.get("proposing_score") or 0.0
        recv_score = trade.get("receiving_score") or 0.0

        if max_skill >= star_line:
            _mark_needs_commissioner(
                conn, trade["id"], f"involves star-level player (skill {max_skill})"
            )
            summary["needs_commissioner"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} held for commissioner: star-level player")
            continue

        if recv_score < veto_recv_below:
            reason = f"Autopilot veto: receiving GM score too low ({recv_score:.2f})"
            veto_trade(conn, trade["id"], reason)
            summary["vetoed"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} auto-vetoed: receiver score {recv_score:.2f}")
            continue

        if prop_score >= min_prop and recv_score >= min_recv:
            execute_trade(conn, trade["id"])
            summary["approved"] += 1
            if verbose:
                print(f"  Trade #{trade['id']} auto-approved.")
            continue

        _mark_needs_commissioner(
            conn, trade["id"],
            f"scores not decisive (proposer {prop_score:.2f}, receiver {recv_score:.2f})",
        )
        summary["needs_commissioner"] += 1
        if verbose:
            print(f"  Trade #{trade['id']} held for commissioner: scores not decisive")

    return summary
