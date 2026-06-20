"""
Rule-based player agent logic. Each player has an archetype and five trait weights
(ambition, loyalty, ego, work_ethic, volatility) that drive morale and weekly actions.

LLM swap-in points are marked with # [LLM-HOOK] comments.
"""
import json
import random
import os

ARCHETYPES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")


def load_player_archetypes():
    with open(ARCHETYPES_PATH) as f:
        return json.load(f).get("player_archetypes", {})


def get_player_personality(conn, player_id):
    row = conn.execute(
        "SELECT * FROM player_personalities WHERE player_id = ?", (player_id,)
    ).fetchone()
    return dict(row) if row else None


def get_current_morale(conn, player_id):
    row = conn.execute(
        "SELECT morale FROM player_morale WHERE player_id = ? "
        "ORDER BY season_year DESC, week DESC LIMIT 1",
        (player_id,),
    ).fetchone()
    return row["morale"] if row else 70.0


def log_player_memory(conn, player_id, week, season_year, event_type, detail=None):
    conn.execute(
        "INSERT INTO player_memory (player_id, week, season_year, event_type, detail)"
        " VALUES (?, ?, ?, ?, ?)",
        (player_id, week, season_year, event_type, detail),
    )


def get_demanding_player_ids(conn):
    """Return set of player IDs with an active trade demand."""
    rows = conn.execute(
        "SELECT player_id FROM player_events WHERE event_type = 'trade_demand' AND status = 'active'"
    ).fetchall()
    return {r["player_id"] for r in rows}


# ── Morale computation helpers ─────────────────────────────────────────────────

def _team_result_this_week(conn, team_id, week, season_year):
    """Returns (won, game_found)."""
    game = conn.execute("""
        SELECT home_team_id, home_score, away_score
        FROM   games
        WHERE  (home_team_id = ? OR away_team_id = ?)
          AND  week = ? AND season_year = ? AND played = 1
        LIMIT  1
    """, (team_id, team_id, week, season_year)).fetchone()
    if not game:
        return False, False
    if game["home_team_id"] == team_id:
        return game["home_score"] > game["away_score"], True
    return game["away_score"] > game["home_score"], True


def _pts_share_this_week(conn, player_id, team_id, week, season_year):
    """Returns (actual_share, expected_share, found)."""
    game = conn.execute("""
        SELECT g.id FROM games g
        WHERE  (g.home_team_id = ? OR g.away_team_id = ?)
          AND  g.week = ? AND g.season_year = ? AND g.played = 1
        LIMIT  1
    """, (team_id, team_id, week, season_year)).fetchone()
    if not game:
        return 0.0, 0.10, False

    gid = game["id"]

    stat = conn.execute(
        "SELECT points FROM player_game_stats WHERE player_id = ? AND game_id = ?",
        (player_id, gid),
    ).fetchone()
    actual_pts = stat["points"] if stat else 0

    team_total = conn.execute(
        "SELECT SUM(points) AS s FROM player_game_stats WHERE team_id = ? AND game_id = ?",
        (team_id, gid),
    ).fetchone()
    total_pts = team_total["s"] if team_total and team_total["s"] else 1

    actual_share = actual_pts / total_pts

    sorted_ids = [
        p["id"] for p in sorted(
            conn.execute(
                "SELECT id, skill_rating FROM players "
                "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
                (team_id,),
            ).fetchall(),
            key=lambda p: p["skill_rating"], reverse=True,
        )
    ]
    rank = sorted_ids.index(player_id) if player_id in sorted_ids else 5
    # Stars expected ~19% of points; bench ~6%
    expected_shares = [0.19, 0.15, 0.12, 0.10, 0.09, 0.08, 0.07, 0.07, 0.07, 0.06]
    expected_share = expected_shares[min(rank, 9)]

    return actual_share, expected_share, True


def compute_morale_update(conn, player_id, week, season_year):
    """
    Compute a new morale value for the player after this week's games.
    Returns (new_morale, delta, summary_str).

    # [LLM-HOOK] Replace this function with an LLM call that reads player history,
    # recent events, and team context to produce nuanced morale reasoning.
    """
    personality = get_player_personality(conn, player_id)
    if not personality:
        return 70.0, 0.0, "no personality"

    arch_cfgs = load_player_archetypes()
    arch_cfg  = arch_cfgs.get(personality["archetype"], {})
    mw        = arch_cfg.get("morale_weights", {
        "playing_time": 0.25, "personal_stats": 0.25, "team_wins": 0.25, "contract": 0.25
    })
    traits = {k: personality[k] for k in ["ambition", "loyalty", "ego", "work_ethic", "volatility"]}

    player     = dict(conn.execute("SELECT * FROM players WHERE id = ?", (player_id,)).fetchone())
    prev_morale = get_current_morale(conn, player_id)
    parts = []

    # ── Playing time vs expectation ───────────────────────────────────────────
    actual_share, expected_share, found = _pts_share_this_week(
        conn, player_id, player["team_id"], week, season_year
    )
    if found and expected_share > 0:
        ratio     = actual_share / expected_share      # >1 means got more than expected
        pt_delta  = (ratio - 1.0) * 8.0 * traits["ego"] * mw.get("playing_time", 0.25)
        pt_delta  = max(-4.5, min(4.5, pt_delta))
        parts.append(f"usage={actual_share:.2f}/{expected_share:.2f}")
    else:
        pt_delta = 0.0

    # ── Team result ───────────────────────────────────────────────────────────
    team_won, game_found = _team_result_this_week(conn, player["team_id"], week, season_year)
    if game_found:
        win_delta = (3.5 if team_won else -3.5) * traits["loyalty"] * mw.get("team_wins", 0.25)
        parts.append(f"{'W' if team_won else 'L'}")
    else:
        win_delta = 0.0

    # ── Contract situation ────────────────────────────────────────────────────
    contract = conn.execute(
        "SELECT years_remaining, salary FROM contracts WHERE player_id = ?", (player_id,)
    ).fetchone()
    if contract:
        yrs_left    = contract["years_remaining"]
        salary      = contract["salary"]
        market_sal  = max(500_000, player["skill_rating"] * 120_000)
        underpaid   = max(0.0, (market_sal - salary) / max(1, market_sal))
        con_delta   = (-underpaid * 4 - (0 if yrs_left >= 2 else 1.5)) * traits["ambition"]
        con_delta   = max(-2.5, min(0.8, con_delta)) * mw.get("contract", 0.25)
    else:
        con_delta = 0.0

    # ── Active feud penalty ───────────────────────────────────────────────────
    feud = conn.execute(
        "SELECT id FROM player_events WHERE (player_id=? OR target_id=?) "
        "AND event_type='feud' AND status='active' LIMIT 1",
        (player_id, player_id),
    ).fetchone()
    feud_delta = -2.0 if feud else 0.0
    if feud:
        parts.append("feuding")

    # ── Archetype-specific decay ──────────────────────────────────────────────
    arch_decay = arch_cfg.get("morale_decay", 0.0)

    # ── Noise ─────────────────────────────────────────────────────────────────
    noise = random.gauss(0, 2.0 * traits["volatility"])

    # ── Memory pull (gentle regression toward recent average) ─────────────────
    recent = conn.execute("""
        SELECT AVG(m.morale) AS avg_m FROM (
            SELECT morale FROM player_morale
            WHERE  player_id = ?
            ORDER  BY season_year DESC, week DESC
            LIMIT  4
        ) m
    """, (player_id,)).fetchone()
    if recent and recent["avg_m"]:
        memory_pull = (recent["avg_m"] - prev_morale) * 0.14
    else:
        memory_pull = (70.0 - prev_morale) * 0.08

    total_delta = pt_delta + win_delta + con_delta + feud_delta + noise + memory_pull - arch_decay

    # ── ChatGPT influence: player morale modifiers ────────────────────────────
    try:
        mod_rows = conn.execute(
            "SELECT mod_type, magnitude FROM player_modifiers "
            "WHERE player_id=? AND season_year=? AND expires_week>=? "
            "AND mod_type IN ('morale_boost', 'morale_penalty')",
            (player_id, season_year, week)
        ).fetchall()
        for m in mod_rows:
            total_delta += m["magnitude"] if m["mod_type"] == "morale_boost" else -m["magnitude"]
    except Exception:
        pass

    # ── ChatGPT influence: team-wide locker room modifier ────────────────────
    try:
        team_mod = conn.execute(
            "SELECT mod_type, magnitude FROM team_modifiers "
            "WHERE team_id=? AND season_year=? AND expires_week>=? "
            "AND mod_type IN ('locker_room_boost', 'locker_room_penalty')",
            (player["team_id"], season_year, week)
        ).fetchone()
        if team_mod:
            total_delta += team_mod["magnitude"] if team_mod["mod_type"] == "locker_room_boost" else -team_mod["magnitude"]
    except Exception:
        pass

    new_morale  = max(12.0, min(98.0, prev_morale + total_delta))

    summary = (
        f"morale {prev_morale:.0f} -> {new_morale:.0f} ({total_delta:+.1f})"
        + (f" [{', '.join(parts)}]" if parts else "")
    )
    return new_morale, total_delta, summary


# ── Morale update pass ─────────────────────────────────────────────────────────

def update_all_morale(conn, week, season_year, verbose=False):
    """Compute and persist morale for every player with a personality."""
    players = conn.execute(
        "SELECT p.* FROM players p JOIN player_personalities pp ON p.id = pp.player_id "
        "WHERE COALESCE(p.status, 'active') = 'active'"
    ).fetchall()

    if not players:
        return

    if verbose:
        print(f"\n{'.'*54}")
        print(f"  PLAYER MORALE UPDATE  --  Week {week}")
        print(f"{'.'*54}")

    low_count = 0
    for player in players:
        pid = player["id"]
        new_morale, delta, summary = compute_morale_update(conn, pid, week, season_year)

        conn.execute(
            "INSERT INTO player_morale (player_id, week, season_year, morale)"
            " VALUES (?, ?, ?, ?)"
            " ON CONFLICT (player_id, week, season_year) DO UPDATE SET morale = EXCLUDED.morale",
            (pid, week, season_year, new_morale),
        )

        personality = get_player_personality(conn, pid)
        archetype   = personality["archetype"] if personality else "unknown"

        if new_morale < 40:
            low_count += 1
            if verbose:
                print(
                    f"  LOW: {player['first_name']} {player['last_name']:<18}"
                    f" [{archetype}] morale={new_morale:.0f} ({delta:+.1f})"
                )
        elif verbose and abs(delta) >= 5.0:
            print(
                f"       {player['first_name']} {player['last_name']:<18}"
                f" [{archetype}] morale={new_morale:.0f} ({delta:+.1f})"
            )

    conn.commit()

    if verbose:
        if low_count:
            print(f"\n  {low_count} player(s) with morale below 40.")
        else:
            print(f"\n  No players in the crisis zone this week.")


# ── Player action evaluation ───────────────────────────────────────────────────

def _active_event(conn, player_id, event_type):
    return conn.execute(
        "SELECT id FROM player_events WHERE player_id=? AND event_type=? AND status='active'",
        (player_id, event_type),
    ).fetchone()


def _recent_player_event(conn, player_id, event_type, week, season_year, cooldown_weeks):
    return conn.execute(
        "SELECT id FROM player_events "
        "WHERE (player_id=? OR target_id=?) AND event_type=? AND season_year=? "
        "AND week >= ? LIMIT 1",
        (player_id, player_id, event_type, season_year, week - cooldown_weeks),
    ).fetchone()


def _resolve_old_feuds(conn, week, season_year):
    """Auto-resolve feuds older than 2 weeks, or earlier if both morale improve."""
    for feud in conn.execute(
        "SELECT * FROM player_events WHERE event_type='feud' AND status='active'"
    ).fetchall():
        feud      = dict(feud)
        weeks_old = week - feud["week"] if feud["season_year"] == season_year else 99
        m1        = get_current_morale(conn, feud["player_id"])
        m2        = get_current_morale(conn, feud["target_id"]) if feud["target_id"] else 70

        if weeks_old >= 2 or (m1 > 62 and m2 > 62 and random.random() < 0.45):
            conn.execute(
                "UPDATE player_events SET status='resolved' WHERE id=?", (feud["id"],)
            )


def _demand_trade_reason(morale, traits, archetype):
    parts = []
    if morale < 25:
        parts.append(f"critically unhappy (morale {morale:.0f})")
    else:
        parts.append(f"morale dropped to {morale:.0f}")
    if archetype == "malcontent":
        parts.append("perpetually disgruntled")
    elif archetype == "superstar_ego":
        parts.append("feels undervalued")
    elif 1 - traits["loyalty"] > 0.6:
        parts.append("loyalty wearing thin")
    return "; ".join(parts)


def _complaint_reason(morale, archetype):
    if archetype == "hothead":
        return f"calls out teammates publicly (morale {morale:.0f})"
    if archetype == "superstar_ego":
        return f"questions the team's direction (morale {morale:.0f})"
    if archetype == "malcontent":
        return f"voices frustration to the media (morale {morale:.0f})"
    return f"expresses unhappiness with situation (morale {morale:.0f})"


def evaluate_player_week(conn, player, week, season_year, verbose=False):
    """
    Probabilistically decide whether a player takes an action this week.
    Returns the event_type string if an action fires, else None.

    # [LLM-HOOK] Replace action selection with an LLM call that reads player history,
    # team dynamics, and recent events to generate narrative-driven decisions.
    """
    pid         = player["id"]
    personality = get_player_personality(conn, pid)
    if not personality:
        return None

    arch_cfgs = load_player_archetypes()
    arch_cfg  = arch_cfgs.get(personality["archetype"], {})
    traits    = {k: personality[k] for k in ["ambition", "loyalty", "ego", "work_ethic", "volatility"]}
    morale    = get_current_morale(conn, pid)
    archetype = personality["archetype"]
    name      = f"{player['first_name']} {player['last_name']}"

    # ── ChatGPT personality nudges (temporary, non-destructive local copy) ────
    try:
        nudge_rows = conn.execute(
            "SELECT mod_type, magnitude FROM player_modifiers "
            "WHERE player_id=? AND season_year=? AND expires_week>=? "
            "AND mod_type IN ('work_ethic_boost', 'loyalty_drop')",
            (pid, season_year, week)
        ).fetchall()
        if nudge_rows:
            traits = dict(traits)
            for n in nudge_rows:
                if n["mod_type"] == "work_ethic_boost":
                    traits["work_ethic"] = min(1.0, traits["work_ethic"] + n["magnitude"])
                elif n["mod_type"] == "loyalty_drop":
                    traits["loyalty"] = max(0.0, traits["loyalty"] - n["magnitude"])
    except Exception:
        pass

    # ── Trade demand ──────────────────────────────────────────────────────────
    if not _active_event(conn, pid, "trade_demand"):
        p_demand = 0.0
        if morale < 28:
            p_demand = (28 - morale) / 80 * (1 - traits["loyalty"]) * traits["volatility"]
        if archetype == "malcontent":
            p_demand += 0.03
        elif archetype == "superstar_ego" and morale < 38:
            p_demand += 0.02

        if random.random() < p_demand:
            reason = _demand_trade_reason(morale, traits, archetype)
            conn.execute(
                "INSERT INTO player_events "
                "(player_id, week, season_year, event_type, status, detail)"
                " VALUES (?, ?, ?, 'trade_demand', 'active', ?)",
                (pid, week, season_year, reason),
            )
            log_player_memory(conn, pid, week, season_year, "trade_demand", reason)
            if verbose:
                print(f"  DEMAND: {name} [{archetype}] demands a trade -- {reason}")
            return "trade_demand"

    # ── Feud ──────────────────────────────────────────────────────────────────
    in_feud = conn.execute(
        "SELECT id FROM player_events WHERE (player_id=? OR target_id=?) "
        "AND event_type='feud' AND status='active' LIMIT 1",
        (pid, pid),
    ).fetchone()
    recent_feud = _recent_player_event(conn, pid, "feud", week, season_year, cooldown_weeks=4)
    if not in_feud and not recent_feud:
        p_feud = traits["volatility"] * traits["ego"] * 0.035
        if archetype == "hothead":
            p_feud += 0.05
        if morale < 38:
            p_feud *= 1.25

        if random.random() < p_feud:
            teammates = conn.execute(
                "SELECT id, first_name, last_name FROM players "
                "WHERE team_id=? AND id!=? AND COALESCE(status, 'active') = 'active'",
                (player["team_id"], pid),
            ).fetchall()
            scored = []
            for tm in teammates:
                tm_pers = get_player_personality(conn, tm["id"])
                score   = (tm_pers["ego"] + tm_pers["volatility"]) if tm_pers else 0.5
                scored.append((score, dict(tm)))

            if scored:
                scored.sort(key=lambda x: x[0], reverse=True)
                top = scored[:max(1, len(scored) // 2)]
                _, target = random.choice(top)

                detail = f"{name} and {target['first_name']} {target['last_name']} are feuding"
                conn.execute(
                    "INSERT INTO player_events "
                    "(player_id, target_id, week, season_year, event_type, status, detail)"
                    " VALUES (?, ?, ?, ?, 'feud', 'active', ?)",
                    (pid, target["id"], week, season_year, detail),
                )
                for source_id, target_id in ((pid, target["id"]), (target["id"], pid)):
                    conn.execute(
                        """
                        INSERT INTO player_relationships
                            (player_id, target_player_id, relationship_type,
                             intensity, started_season, started_week, detail)
                        VALUES (?, ?, 'rival', 0.68, ?, ?, ?)
                        ON CONFLICT DO NOTHING
                        """,
                        (source_id, target_id, season_year, week, detail),
                    )
                log_player_memory(conn, pid, week, season_year, "feud_started", detail)
                log_player_memory(conn, target["id"], week, season_year, "feud_started", detail)
                if verbose:
                    print(
                        f"  FEUD:   {name} [{archetype}] clashes with "
                        f"{target['first_name']} {target['last_name']}"
                    )
                return "feud"

    # ── Public complaint ──────────────────────────────────────────────────────
    if morale < 42 and not _active_event(conn, pid, "public_complaint"):
        p_complaint = traits["ego"] * (1 - traits["loyalty"]) * 0.05
        if archetype in ("malcontent", "hothead"):
            p_complaint += 0.035
        if morale < 32:
            p_complaint *= 1.4

        if random.random() < p_complaint:
            reason = _complaint_reason(morale, archetype)
            conn.execute(
                "INSERT INTO player_events "
                "(player_id, week, season_year, event_type, status, detail)"
                " VALUES (?, ?, ?, 'public_complaint', 'active', ?)",
                (pid, week, season_year, reason),
            )
            log_player_memory(conn, pid, week, season_year, "public_complaint", reason)
            if verbose:
                print(f"  GRIPE:  {name} [{archetype}] -- {reason}")
            return "public_complaint"

    # ── Extra training ────────────────────────────────────────────────────────
    if morale > 40 and traits["work_ethic"] > 0.55:
        p_train = traits["work_ethic"] * 0.18
        if archetype in ("rising_star", "quiet_professional"):
            p_train += 0.05

        if random.random() < p_train:
            old_skill = player["skill_rating"]
            new_skill = min(96, old_skill + random.randint(1, 2))
            if new_skill > old_skill:
                conn.execute(
                    "UPDATE players SET skill_rating=? WHERE id=?", (new_skill, pid)
                )
                detail = f"Extra sessions: skill {old_skill} -> {new_skill}"
                log_player_memory(conn, pid, week, season_year, "extra_training", detail)
                if verbose:
                    print(
                        f"  TRAIN:  {name} [{archetype}] puts in extra work "
                        f"-- skill {old_skill} -> {new_skill}"
                    )
            return "extra_training"

    # ── Retirement ────────────────────────────────────────────────────────────
    if player["age"] >= 33 and morale < 38:
        contract   = conn.execute(
            "SELECT years_remaining FROM contracts WHERE player_id=?", (pid,)
        ).fetchone()
        yrs_left   = contract["years_remaining"] if contract else 0
        p_retire   = ((player["age"] - 31) / 10) * ((38 - morale) / 38) * 0.35
        if yrs_left <= 1:
            p_retire += 0.10
        if archetype == "aging_veteran":
            p_retire += 0.08

        already    = conn.execute(
            "SELECT id FROM player_events WHERE player_id=? AND event_type='retirement'", (pid,)
        ).fetchone()
        if not already and random.random() < p_retire:
            detail = f"Age {player['age']}, morale {morale:.0f} -- mulling retirement"
            conn.execute(
                "INSERT INTO player_events "
                "(player_id, week, season_year, event_type, status, detail)"
                " VALUES (?, ?, ?, 'retirement', 'active', ?)",
                (pid, week, season_year, detail),
            )
            log_player_memory(conn, pid, week, season_year, "retirement", detail)
            if verbose:
                print(f"  RETIRE: {name} [{archetype}] age {player['age']} -- {detail}")
            return "retirement"

    # ── Contract extension request ────────────────────────────────────────────
    contract = conn.execute(
        "SELECT years_remaining FROM contracts WHERE player_id=?", (pid,)
    ).fetchone()
    if (
        contract
        and contract["years_remaining"] <= 1
        and morale > 55
        and traits["ambition"] > 0.45
    ):
        already = conn.execute(
            "SELECT id FROM player_events WHERE player_id=? AND event_type='contract_request' "
            "AND season_year=? AND status='active'",
            (pid, season_year),
        ).fetchone()
        if not already and random.random() < traits["ambition"] * 0.14:
            detail = "Happy and motivated -- wants a contract extension"
            conn.execute(
                "INSERT INTO player_events "
                "(player_id, week, season_year, event_type, status, detail)"
                " VALUES (?, ?, ?, 'contract_request', 'active', ?)",
                (pid, week, season_year, detail),
            )
            log_player_memory(conn, pid, week, season_year, "contract_request", detail)
            if verbose:
                print(f"  EXTEND: {name} [{archetype}] requesting contract extension")
            return "contract_request"

    return None


# ── Team chemistry ─────────────────────────────────────────────────────────────

def compute_team_chemistry(conn, team_id, week, season_year):
    """
    Compute team chemistry (0-100) from current morale + active events.
    Stores result in team_chemistry table.

    # [LLM-HOOK] Could generate a narrative "locker room report" from chemistry
    # score and active events to surface to the commissioner.
    """
    players = conn.execute(
        "SELECT id FROM players "
        "WHERE team_id=? AND COALESCE(status, 'active') = 'active'",
        (team_id,),
    ).fetchall()
    if not players:
        return 70.0

    morales   = [get_current_morale(conn, p["id"]) for p in players]
    chemistry = sum(morales) / len(morales)

    # Active-event penalties
    feuds = conn.execute("""
        SELECT COUNT(*) AS n FROM player_events pe
        JOIN   players p ON (pe.player_id = p.id OR pe.target_id = p.id)
        WHERE  p.team_id=? AND COALESCE(p.status, 'active') = 'active'
          AND  pe.event_type='feud' AND pe.status='active'
    """, (team_id,)).fetchone()["n"]

    demands = conn.execute("""
        SELECT COUNT(*) AS n FROM player_events pe
        JOIN   players p ON pe.player_id = p.id
        WHERE  p.team_id=? AND COALESCE(p.status, 'active') = 'active'
          AND  pe.event_type='trade_demand' AND pe.status='active'
    """, (team_id,)).fetchone()["n"]

    complaints = conn.execute("""
        SELECT COUNT(*) AS n FROM player_events pe
        JOIN   players p ON pe.player_id = p.id
        WHERE  p.team_id=? AND COALESCE(p.status, 'active') = 'active'
          AND  pe.event_type='public_complaint' AND pe.status='active'
    """, (team_id,)).fetchone()["n"]

    leader_row = conn.execute("""
        SELECT COUNT(*) AS n, AVG(pp.leadership) AS leadership FROM player_personalities pp
        JOIN   players p ON pp.player_id = p.id
        WHERE  p.team_id=? AND COALESCE(p.status, 'active') = 'active'
          AND  pp.archetype='locker_room_leader'
    """, (team_id,)).fetchone()
    leaders = leader_row["n"]
    leadership = leader_row["leadership"] if leader_row["leadership"] is not None else 0.5

    chemistry -= feuds * 3 + demands * 4 + complaints * 1.5
    chemistry += leaders * 2.5
    chemistry += max(0.0, leadership - 0.5) * 2.0
    chemistry  = max(25.0, min(96.0, chemistry))

    conn.execute(
        "INSERT INTO team_chemistry (team_id, week, season_year, chemistry)"
        " VALUES (?, ?, ?, ?)"
        " ON CONFLICT (team_id, week, season_year) DO UPDATE SET chemistry = EXCLUDED.chemistry",
        (team_id, week, season_year, chemistry),
    )
    return chemistry


def compute_all_team_chemistry(conn, week, season_year):
    """Compute and store chemistry for all teams. Call before simulating games."""
    teams   = conn.execute("SELECT id FROM teams").fetchall()
    results = {}
    for team in teams:
        results[team["id"]] = compute_team_chemistry(conn, team["id"], week, season_year)
    conn.commit()
    return results


def get_team_chemistry(conn, team_id, week, season_year):
    """Return stored chemistry for a team this week; fall back to 70."""
    row = conn.execute(
        "SELECT chemistry FROM team_chemistry WHERE team_id=? AND week=? AND season_year=?",
        (team_id, week, season_year),
    ).fetchone()
    if row:
        return row["chemistry"]
    row = conn.execute(
        "SELECT chemistry FROM team_chemistry WHERE team_id=? AND season_year=? "
        "ORDER BY week DESC LIMIT 1",
        (team_id, season_year),
    ).fetchone()
    return row["chemistry"] if row else 70.0


# ── Main weekly runner ─────────────────────────────────────────────────────────

def run_all_player_agents(conn, week, season_year, verbose=False):
    """
    Full player-agent pass for one week:
    1. Resolve old feuds
    2. Update morale for all players
    3. Evaluate actions for all players
    Call this AFTER games are simulated and standings updated.
    """
    _resolve_old_feuds(conn, week, season_year)
    update_all_morale(conn, week, season_year, verbose=verbose)

    players = conn.execute(
        "SELECT p.* FROM players p JOIN player_personalities pp ON p.id = pp.player_id "
        "WHERE COALESCE(p.status, 'active') = 'active'"
    ).fetchall()

    if verbose:
        print(f"\n{'.'*54}")
        print(f"  PLAYER ACTIONS  --  Week {week}")
        print(f"{'.'*54}")

    action_count = 0
    for player in players:
        action = evaluate_player_week(conn, dict(player), week, season_year, verbose=verbose)
        if action:
            action_count += 1

    conn.commit()

    if verbose:
        if action_count == 0:
            print("  No notable player actions this week.")
        else:
            print(f"\n  {action_count} player action(s) logged this week.")

    return action_count
