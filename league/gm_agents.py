"""
Rule-based GM agent logic. Each GM has a personality (archetype + trait weights)
that shapes probabilistic trade decisions. No LLM, no external APIs.

LLM swap-in points are marked with # [LLM-HOOK] comments.
"""
import json
import random
import os

ARCHETYPES_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "archetypes.json")


def load_archetypes():
    with open(ARCHETYPES_PATH) as f:
        return json.load(f)


def trade_policy(archetypes_data):
    return archetypes_data.get("trade_policy", {})


def _team_trade_count(conn, team_id, season_year):
    row = conn.execute("""
        SELECT COUNT(*) AS n
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        WHERE pt.season_year = ?
          AND pt.status IN ('pending', 'approved')
          AND (pgm.team_id = ? OR rgm.team_id = ?)
    """, (season_year, team_id, team_id)).fetchone()
    return row["n"] if row else 0


def _last_team_trade_week(conn, team_id, season_year):
    row = conn.execute("""
        SELECT MAX(pt.week) AS week
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        WHERE pt.season_year = ?
          AND pt.status IN ('pending', 'approved')
          AND (pgm.team_id = ? OR rgm.team_id = ?)
    """, (season_year, team_id, team_id)).fetchone()
    return row["week"] if row and row["week"] is not None else None


def _protected_star_reason(player, demanding_ids, week, policy):
    skill = player["skill_rating"]
    if player["id"] in demanding_ids:
        return None

    franchise_line = policy.get("franchise_skill_threshold", 91)
    if skill >= franchise_line:
        return "franchise player protected"

    star_line = policy.get("star_skill_threshold", 86)
    min_week = policy.get("star_trade_min_week", 7)
    if skill >= star_line and week < min_week:
        return f"star protected until week {min_week}"

    return None


# ── Need assessment ────────────────────────────────────────────────────────────

def assess_team_needs(conn, team_id, season_year):
    """
    Analyze a team's roster and return a needs profile dict.
    cap_space is NOT set here --caller sets it after loading the cap.
    """
    c = conn.cursor()

    players = [dict(p) for p in c.execute(
        "SELECT * FROM players "
        "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
        (team_id,),
    ).fetchall()]

    if not players:
        return None

    ages = [p["age"] for p in players]
    avg_age = sum(ages) / len(ages)
    young_count   = sum(1 for a in ages if a < 25)
    prime_count   = sum(1 for a in ages if 25 <= a <= 31)
    veteran_count = sum(1 for a in ages if a > 31)

    total_salary = sum(p["salary"] for p in players)

    positions = ["PG", "SG", "SF", "PF", "C"]
    pos_ratings = {}
    for pos in positions:
        pos_players = [p for p in players if p["position"] == pos]
        if pos_players:
            pos_ratings[pos] = sum(p["skill_rating"] for p in pos_players) / len(pos_players)
        else:
            pos_ratings[pos] = 0.0

    sorted_pos     = sorted(pos_ratings.items(), key=lambda x: x[1])
    weakest_pos    = sorted_pos[0][0]
    strongest_pos  = sorted_pos[-1][0]

    # Recent form: last 4 games
    recent = c.execute("""
        SELECT home_score, away_score, home_team_id, away_team_id
        FROM   games
        WHERE  (home_team_id = ? OR away_team_id = ?)
          AND  played = 1 AND season_year = ?
        ORDER  BY week DESC
        LIMIT  4
    """, (team_id, team_id, season_year)).fetchall()

    recent_wins = recent_losses = 0
    for g in recent:
        if g["home_team_id"] == team_id:
            if g["home_score"] > g["away_score"]:
                recent_wins += 1
            else:
                recent_losses += 1
        else:
            if g["away_score"] > g["home_score"]:
                recent_wins += 1
            else:
                recent_losses += 1

    if recent_wins + recent_losses == 0:
        trend = "no_games_yet"
    elif recent_wins > recent_losses:
        trend = "winning"
    elif recent_losses > recent_wins:
        trend = "losing"
    else:
        trend = "even"

    record = c.execute(
        "SELECT wins, losses FROM standings WHERE team_id = ? AND season_year = ?",
        (team_id, season_year),
    ).fetchone()
    wins   = record["wins"]   if record else 0
    losses = record["losses"] if record else 0

    return {
        "team_id":          team_id,
        "roster":           players,
        "avg_age":          avg_age,
        "young_count":      young_count,
        "prime_count":      prime_count,
        "veteran_count":    veteran_count,
        "total_salary":     total_salary,
        "cap_space":        None,       # set by caller
        "position_ratings": pos_ratings,
        "weakest_position": weakest_pos,
        "strongest_position": strongest_pos,
        "performance_trend": trend,
        "recent_record":    f"{recent_wins}-{recent_losses}",
        "season_record":    f"{wins}-{losses}",
        "wins":             wins,
        "losses":           losses,
    }


# ── Scoring helpers ────────────────────────────────────────────────────────────

def _age_fit(age, archetype_cfg):
    """0-1: how well does this age fit the archetype's preferred range?"""
    lo = archetype_cfg.get("preferred_age_min", 18)
    hi = archetype_cfg.get("preferred_age_max", 40)
    if lo <= age <= hi:
        return 1.0
    if age < lo:
        return max(0.0, 1.0 - (lo - age) * 0.12)
    return max(0.0, 1.0 - (age - hi) * 0.12)


def player_want_score(player, needs, archetype_cfg):
    """
    How much does this GM want to acquire this player? (0-1)

    # [LLM-HOOK] Replace this function with an LLM call for richer evaluation:
    # prompt the model with player stats, team needs, and archetype description
    # to get a more nuanced want score and explanation.
    """
    pos       = player["position"]
    my_rating = needs["position_ratings"].get(pos, 50.0)
    skill     = player["skill_rating"]

    # Does this player upgrade my weakest spot?
    delta        = (skill - my_rating) / 100.0          # -1 → +1 range
    position_fit = max(0.0, min(1.0, 0.5 + delta))

    age_fit     = _age_fit(player["age"], archetype_cfg)
    skill_score = skill / 100.0

    cap_space = needs.get("cap_space") or 0
    if cap_space >= player["salary"]:
        cap_fit = 1.0
    elif cap_space > 0:
        cap_fit = max(0.1, cap_space / player["salary"])
    else:
        cap_fit = 0.0

    nw = archetype_cfg["need_weights"]
    score = (
        nw["skill"]         * skill_score  +
        nw["youth"]         * age_fit      +
        nw["position_need"] * position_fit +
        nw["cap_relief"]    * cap_fit
    )
    return max(0.0, min(1.0, score))


def player_give_score(player, needs, gm_traits, archetype_cfg):
    """
    How willing is this GM to trade away this player? (0-1, higher = more willing)

    # [LLM-HOOK] Replace this function with an LLM call that reasons about player
    # history, locker-room value, and narrative context to produce nuanced willingness.
    """
    age  = player["age"]
    lo   = archetype_cfg.get("preferred_age_min", 18)
    hi   = archetype_cfg.get("preferred_age_max", 40)

    # Age mismatch drives willingness: player outside archetype's sweet spot = tradeable
    if age < lo:
        # Younger than preferred --win-now GMs want to move young players
        age_mismatch = (lo - age) / 15.0 * (1.0 - gm_traits["youth_preference"])
    elif age > hi:
        # Older than preferred --rebuilders want to shed veterans
        age_mismatch = (age - hi) / 10.0 * (1.0 - gm_traits["veteran_loyalty"])
    else:
        age_mismatch = 0.0
    age_mismatch = min(1.0, age_mismatch)

    # Position surplus: if there's a good backup at this position, I can spare someone
    pos       = player["position"]
    pos_peers = [p for p in needs["roster"]
                 if p["position"] == pos and p["id"] != player["id"]]
    if pos_peers:
        best_peer = max(p["skill_rating"] for p in pos_peers)
        surplus   = min(1.0, best_peer / 100.0 * 1.2)
    else:
        surplus = 0.0   # only player at this position --very reluctant to trade

    # Low skill → slightly more willing, unless they're a young asset for a rebuilder
    skill_give = max(0.0, 1.0 - player["skill_rating"] / 100.0) * 0.5

    score = 0.40 * age_mismatch + 0.40 * surplus + 0.20 * skill_give

    # Loyal GM gets a hard penalty for trading away veteran players
    if age >= 30 and gm_traits["veteran_loyalty"] > 0.6:
        score *= (1.0 - gm_traits["veteran_loyalty"] * 0.5)

    # Rebuilder gets a bonus for shedding veterans
    if age >= 30 and gm_traits["youth_preference"] > 0.7:
        score = min(1.0, score + 0.30)

    # If team is over cap, more willing to trade expensive players
    cap_space = needs.get("cap_space") or 0
    if cap_space < 0 and player["salary"] > 0:
        cap_pressure = min(0.25, abs(cap_space) / player["salary"] * 0.25)
        score = min(1.0, score + cap_pressure)

    return max(0.0, min(1.0, score))


# ── Trade scoring ──────────────────────────────────────────────────────────────

def score_trade_for_gm(offering_players, requesting_players, my_needs,
                        gm_traits, archetype_cfg):
    """
    Score a trade from one GM's perspective.
    Returns (score: float, reasoning_parts: list[str])

    Formula: want drives the score; give acts as a gate.
    avg_want * (0.4 + 0.6 * avg_give)  --both must be non-trivial for a good score.

    # [LLM-HOOK] This scoring function is an ideal LLM integration point.
    # Give the model the full trade context and have it return a score + narrative.
    """
    if not offering_players or not requesting_players:
        return 0.0, ["Empty trade."]

    want_scores = []
    give_scores = []
    parts       = []

    for p in requesting_players:
        ws = player_want_score(p, my_needs, archetype_cfg)
        want_scores.append(ws)
        parts.append(
            f"want {p['first_name']} {p['last_name']} "
            f"(age {p['age']}, skill {p['skill_rating']}, {p['position']}): {ws:.2f}"
        )

    for p in offering_players:
        gs = player_give_score(p, my_needs, gm_traits, archetype_cfg)
        give_scores.append(gs)
        parts.append(
            f"give {p['first_name']} {p['last_name']} "
            f"(age {p['age']}, skill {p['skill_rating']}, {p['position']}): willing={gs:.2f}"
        )

    avg_want = sum(want_scores) / len(want_scores)
    avg_give = sum(give_scores) / len(give_scores)

    # Hard minimums: must actually want the player and be willing to part with the offer
    if avg_want < 0.35:
        return 0.0, parts + ["Incoming player not desirable enough."]
    if avg_give < 0.15:
        return 0.0, parts + ["Not willing to part with offered player."]

    base = avg_want * (0.40 + 0.60 * avg_give)

    noise_scale = archetype_cfg.get("noise_scale", 0.10)
    noise = random.gauss(0, noise_scale)
    score = max(0.0, min(1.0, base + noise))

    parts.append(
        f"base={base:.2f} noise={noise:+.2f} final={score:.2f} "
        f"(want={avg_want:.2f}, give={avg_give:.2f})"
    )
    return score, parts


# ── Trade candidate generation ─────────────────────────────────────────────────

def find_trade_candidates(conn, gm, my_team_id, my_needs, week, season_year, archetypes_data):
    """
    Generate up to 3 candidate trade proposals for a GM.
    Returns list of dicts with scoring and reasoning from both sides.

    # [LLM-HOOK] The candidate-selection loop is a good place for LLM-guided targeting:
    # let the model rank other teams' rosters by narrative fit, not just by score.
    """
    c = conn.cursor()
    cap       = archetypes_data["salary_cap"]
    my_arch   = archetypes_data["archetypes"][gm["archetype"]]
    policy    = trade_policy(archetypes_data)
    gm_traits = dict(gm)

    # Collect all player IDs already locked in a pending trade this season
    pending_rows = c.execute("""
        SELECT offered_player_ids, requested_player_ids
        FROM   pending_trades
        WHERE  status = 'pending' AND season_year = ?
    """, (season_year,)).fetchall()
    locked_player_ids = set()
    for row in pending_rows:
        locked_player_ids.update(json.loads(row["offered_player_ids"]))
        locked_player_ids.update(json.loads(row["requested_player_ids"]))

    # Player trade demands boost availability scores
    try:
        from league.player_agents import get_demanding_player_ids
        demanding_ids = get_demanding_player_ids(conn)
    except Exception:
        demanding_ids = set()

    other_teams = c.execute(
        "SELECT * FROM teams WHERE id != ?", (my_team_id,)
    ).fetchall()

    candidates = []

    for other_team in other_teams:
        other_id = other_team["id"]
        other_gm = c.execute(
            "SELECT * FROM general_managers WHERE team_id = ?", (other_id,)
        ).fetchone()
        if not other_gm:
            continue
        other_gm = dict(other_gm)

        other_needs = assess_team_needs(conn, other_id, season_year)
        if not other_needs:
            continue
        other_needs["cap_space"] = cap - other_needs["total_salary"]
        other_arch = archetypes_data["archetypes"][other_gm["archetype"]]

        # Score every player on the other team from my want perspective.
        # Players with active trade demands get a +0.15 availability bonus.
        # (skip players already locked in a pending trade)
        their_scored = sorted(
            [
                (
                    min(1.0, player_want_score(p, my_needs, my_arch) +
                        (0.15 if p["id"] in demanding_ids else 0.0)),
                    p,
                )
                for p in other_needs["roster"]
                if p["id"] not in locked_player_ids
                and not _protected_star_reason(p, demanding_ids, week, policy)
            ],
            key=lambda x: x[0],
            reverse=True,
        )
        targets = [(ws, p) for ws, p in their_scored if ws > 0.30][:3]

        if not targets:
            continue

        # Score my players by willingness to give.
        # A demanding player on my own roster is easier to move (unless very loyal GM).
        my_scored = sorted(
            [
                (
                    min(1.0, player_give_score(p, my_needs, gm_traits, my_arch) +
                        (0.15 if p["id"] in demanding_ids
                         and gm_traits.get("veteran_loyalty", 0.5) < 0.70
                         else 0.0)),
                    p,
                )
                for p in my_needs["roster"]
                if p["id"] not in locked_player_ids
                and not _protected_star_reason(p, demanding_ids, week, policy)
            ],
            key=lambda x: x[0],
            reverse=True,
        )
        giveable = [(gs, p) for gs, p in my_scored if gs > 0.15]

        if not giveable:
            continue

        for target_ws, target_p in targets:
            # Find best salary-compatible offer
            best_offer, best_gs = None, -1.0
            for gs, my_p in giveable:
                ratio = my_p["salary"] / max(1, target_p["salary"])
                if 0.40 <= ratio <= 2.5:
                    if gs > best_gs:
                        best_gs, best_offer = gs, my_p
            if best_offer is None and giveable:
                best_gs, best_offer = giveable[0]

            if best_offer is None:
                continue

            my_score, my_parts = score_trade_for_gm(
                [best_offer], [target_p], my_needs, gm_traits, my_arch
            )
            their_score, their_parts = score_trade_for_gm(
                [target_p], [best_offer], other_needs, other_gm, other_arch
            )

            candidates.append({
                "offering_player":  best_offer,
                "requesting_player": target_p,
                "target_team_id":   other_id,
                "target_gm":        other_gm,
                "my_score":         my_score,
                "their_score":      their_score,
                "my_reasoning":     "; ".join(my_parts),
                "their_reasoning":  "; ".join(their_parts),
            })

    candidates.sort(key=lambda x: x["my_score"], reverse=True)
    return candidates[:3]


# ── Memory logging ─────────────────────────────────────────────────────────────

def log_memory(conn, gm_id, week, season_year, event_type, player_id=None, detail=None):
    conn.execute(
        "INSERT INTO agent_memory (week, season_year, gm_id, event_type, player_id, detail)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (week, season_year, gm_id, event_type, player_id, detail),
    )


# ── Per-GM weekly decision loop ────────────────────────────────────────────────

def run_gm_week(conn, gm, week, season_year, archetypes_data):
    """
    Run one GM's decision process for the week.
    Returns True if a trade proposal was submitted, False otherwise.

    # [LLM-HOOK] The narrative reasoning strings logged to agent_memory are ideal
    # prompts for an LLM in a later phase: feed them back to the model so it can
    # build on prior-week context when making decisions.
    """
    gm        = dict(gm)
    cap       = archetypes_data["salary_cap"]
    threshold = archetypes_data["trade_threshold"]
    policy    = trade_policy(archetypes_data)
    c         = conn.cursor()

    max_trades = policy.get("max_team_trades_per_season", 2)
    trade_count = _team_trade_count(conn, gm["team_id"], season_year)
    if trade_count >= max_trades:
        log_memory(conn, gm["id"], week, season_year, "inactive",
                   detail=f"Sat out: team trade limit reached ({trade_count}/{max_trades})")
        conn.commit()
        return False

    cooldown = policy.get("team_trade_cooldown_weeks", 4)
    last_trade_week = _last_team_trade_week(conn, gm["team_id"], season_year)
    if last_trade_week is not None and week - last_trade_week < cooldown:
        log_memory(conn, gm["id"], week, season_year, "inactive",
                   detail=f"Sat out: trade cooldown after week {last_trade_week}")
        conn.commit()
        return False

    # Roll for activity this week
    if random.random() > gm["trade_frequency"]:
        log_memory(conn, gm["id"], week, season_year, "inactive",
                   detail=f"Sat out (trade_frequency={gm['trade_frequency']:.2f})")
        conn.commit()
        return False

    needs = assess_team_needs(conn, gm["team_id"], season_year)
    if not needs:
        return False
    needs["cap_space"] = cap - needs["total_salary"]

    context = (
        f"record={needs['season_record']} trend={needs['performance_trend']} "
        f"weakest={needs['weakest_position']} "
        f"avg_age={needs['avg_age']:.1f} "
        f"cap_space=${needs['cap_space']/1e6:.1f}M"
    )

    candidates = find_trade_candidates(
        conn, gm, gm["team_id"], needs, week, season_year, archetypes_data
    )

    if not candidates:
        log_memory(conn, gm["id"], week, season_year, "no_candidates",
                   detail=f"No viable targets found. {context}")
        conn.commit()
        return False

    # Log all candidates (including rejected ones below threshold)
    for cand in candidates:
        req = cand["requesting_player"]
        off = cand["offering_player"]
        if cand["my_score"] < threshold:
            log_memory(
                conn, gm["id"], week, season_year, "trade_considered",
                player_id=req["id"],
                detail=(
                    f"Below threshold ({cand['my_score']:.2f} < {threshold:.2f}): "
                    f"offer {off['first_name']} {off['last_name']} "
                    f"for {req['first_name']} {req['last_name']} "
                    f"(age {req['age']}, skill {req['skill_rating']}, {req['position']}). "
                    f"{cand['my_reasoning']}"
                ),
            )

    best = candidates[0]
    if best["my_score"] < threshold:
        conn.commit()
        return False

    req = best["requesting_player"]
    off = best["offering_player"]

    c.execute("""
        INSERT INTO pending_trades
            (week, season_year, proposing_gm_id, receiving_gm_id,
             offered_player_ids, requested_player_ids,
             proposing_score, receiving_score,
             proposing_reasoning, receiving_reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        week, season_year,
        gm["id"], best["target_gm"]["id"],
        json.dumps([off["id"]]),
        json.dumps([req["id"]]),
        best["my_score"],
        best["their_score"],
        best["my_reasoning"],
        best["their_reasoning"],
    ))

    log_memory(
        conn, gm["id"], week, season_year, "trade_proposed",
        player_id=req["id"],
        detail=(
            f"PROPOSED: offer {off['first_name']} {off['last_name']} "
            f"(age {off['age']}, skill {off['skill_rating']}, {off['position']}, "
            f"${off['salary']/1e6:.1f}M) "
            f"for {req['first_name']} {req['last_name']} "
            f"(age {req['age']}, skill {req['skill_rating']}, {req['position']}, "
            f"${req['salary']/1e6:.1f}M). "
            f"Score: {best['my_score']:.2f}. {best['my_reasoning']}"
        ),
    )

    conn.commit()
    return True


# ── Run all GMs for a week ─────────────────────────────────────────────────────

def run_all_gm_agents(conn, week, season_year, verbose=True):
    """Run every GM's weekly decision. Prints a summary if verbose."""
    from league.database import create_tables
    create_tables()

    archetypes_data = load_archetypes()
    c               = conn.cursor()

    gms = c.execute("SELECT * FROM general_managers").fetchall()
    if not gms:
        if verbose:
            print("  No GMs found --run  python seed.py  first.")
        return 0

    if verbose:
        print(f"\n{'-'*54}")
        print(f"  GM AGENTS  --  reviewing week {week} results")
        print(f"{'-'*54}")

    proposed_total = 0
    for gm in gms:
        gm_d  = dict(gm)
        team  = c.execute(
            "SELECT city, name FROM teams WHERE id = ?", (gm_d["team_id"],)
        ).fetchone()
        label = f"{team['city']} {team['name']}"

        proposed = run_gm_week(conn, gm_d, week, season_year, archetypes_data)

        if verbose:
            status = "submitted a trade proposal" if proposed else "no proposal this week"
            print(f"  {gm_d['name']:<30} {label:<26} {status}")
            if proposed:
                # Show the last memory entry (the proposal detail)
                mem = c.execute(
                    "SELECT detail FROM agent_memory"
                    " WHERE gm_id = ? AND week = ? AND event_type = 'trade_proposed'"
                    " ORDER BY id DESC LIMIT 1",
                    (gm_d["id"], week),
                ).fetchone()
                if mem:
                    snippet = mem["detail"][:100] + "..." if len(mem["detail"]) > 100 else mem["detail"]
                    print(f"    >> {snippet}")

        if proposed:
            proposed_total += 1

    if verbose:
        print()
        if proposed_total:
            print(f"  {proposed_total} trade proposal(s) pending.")
            print(f"  Autopilot will review routine deals; exceptions stay pending.\n")
        else:
            print(f"  No proposals this week.\n")

    return proposed_total


# ── Season-end personality drift ──────────────────────────────────────────────

def compute_performance_signals(conn, team_id, season_year):
    """
    Collect end-of-season stats for a team: win rate, roster age profile, cap situation.
    Returns a flat dict of signals, or None if no data.
    """
    c = conn.cursor()

    players = c.execute(
        "SELECT age, skill_rating, salary FROM players "
        "WHERE team_id = ? AND COALESCE(status, 'active') = 'active'",
        (team_id,),
    ).fetchall()
    if not players:
        return None

    ages         = [p["age"] for p in players]
    avg_age      = sum(ages) / len(ages)
    # Calibrated for 19-36 age range: >29 = experienced/veteran, <23 = young asset
    veteran_count = sum(1 for a in ages if a > 29)
    young_count   = sum(1 for a in ages if a < 23)
    avg_skill     = sum(p["skill_rating"] for p in players) / len(players)
    total_salary  = sum(p["salary"] for p in players)

    record = c.execute(
        "SELECT wins, losses FROM standings WHERE team_id = ? AND season_year = ?",
        (team_id, season_year),
    ).fetchone()
    wins   = record["wins"]   if record else 0
    losses = record["losses"] if record else 0
    winning_pct = wins / max(1, wins + losses)

    return {
        "wins":           wins,
        "losses":         losses,
        "winning_pct":    winning_pct,
        "avg_age":        avg_age,
        "avg_skill":      avg_skill,
        "veteran_count":  veteran_count,
        "young_count":    young_count,
        "veteran_ratio":  veteran_count / len(players),
        "young_ratio":    young_count   / len(players),
        "total_salary":   total_salary,
        "roster_size":    len(players),
    }


def compute_trait_drift(signals, gm_traits, archetype_cfg):
    """
    Given season performance signals and the GM's current traits, return
    (deltas: dict, reasons: list[str]).

    Drift is small per season by design --it compounds meaningfully over 2-3
    losing years without becoming extreme in a single season.

    # [LLM-HOOK] An LLM could generate richer narrative and context-aware drift
    # by reading agent_memory entries from prior seasons before computing changes.
    """
    resistance  = archetype_cfg.get("change_resistance", 0.30)
    wp          = signals["winning_pct"]
    avg_age     = signals["avg_age"]
    vet_ratio   = signals["veteran_ratio"]   # fraction of players age > 29

    deltas = {
        "risk_tolerance":  0.0,
        "veteran_loyalty": 0.0,
        "youth_preference": 0.0,
        "trade_frequency": 0.0,
    }
    reasons = []

    # ── Signal A: losing + above-average age → rebuild pressure ──────────────
    # Primary driver: old(ish) team not winning pushes toward youth/rebuild traits.
    # Threshold is avg_age >= 26 because our league's age range is 19-36 (median ~27).
    if wp < 0.45 and avg_age >= 26:
        severity   = (0.45 - wp) * 3.0            # 0 → 1.35 at extreme losing
        age_factor = min(1.0, (avg_age - 24) / 8) # 0.25 at age 26, 1.0 at 32+
        factor     = min(1.0, severity * age_factor) * (1.0 - resistance)

        deltas["youth_preference"] += 0.12 * factor
        deltas["veteran_loyalty"]  -= 0.09 * factor
        deltas["trade_frequency"]  += 0.06 * factor
        deltas["risk_tolerance"]   += 0.04 * factor

        reasons.append(
            f"losing ({signals['wins']}-{signals['losses']}, {wp:.0%}) "
            f"with aging roster (avg {avg_age:.1f} yrs) --rebuild pressure "
            f"[factor={factor:.2f}, resistance={resistance:.2f}]"
        )

    # ── Signal B: meaningful veteran presence + losing ────────────────────────
    # Veteran-heavy (>29 yrs) losing team gets an extra push toward rebuilding.
    if wp < 0.45 and vet_ratio >= 0.20:
        extra = min(1.0, (0.45 - wp) * 4.0 * vet_ratio) * (1.0 - resistance)

        deltas["youth_preference"] += 0.10 * extra
        deltas["veteran_loyalty"]  -= 0.07 * extra
        deltas["trade_frequency"]  += 0.04 * extra

        reasons.append(
            f"{vet_ratio:.0%} of roster aged 30+ and team is losing --"
            f"veteran burden signal [extra={extra:.2f}]"
        )

    # ── Signal C: pure bad record (any roster) ────────────────────────────────
    # Regardless of age, a truly poor record increases urgency to act.
    if wp < 0.35:
        urgency = (0.35 - wp) * 3.0 * (1.0 - resistance) * 0.5

        deltas["trade_frequency"] += 0.05 * urgency
        deltas["risk_tolerance"]  += 0.04 * urgency

        reasons.append(
            f"poor record ({signals['wins']}-{signals['losses']}, {wp:.0%}) --"
            f"urgency to act regardless of roster profile [urgency={urgency:.2f}]"
        )

    # ── Signal D: young roster still losing → impatience to add veterans ──────
    # A rebuilder's youth core that isn't winning may need proven pieces sooner.
    if wp < 0.42 and avg_age < 25 and gm_traits.get("youth_preference", 0.5) > 0.55:
        factor = (0.42 - wp) * 2.0 * (1.0 - resistance) * 0.4

        deltas["trade_frequency"] += 0.06 * factor
        deltas["risk_tolerance"]  += 0.07 * factor

        reasons.append(
            f"young roster (avg {avg_age:.1f} yrs) still underperforming --"
            f"rising impatience to supplement youth core [factor={factor:.2f}]"
        )

    # ── Signal E: winning → stabilise current approach ────────────────────────
    # When it's working, gently dampen any prior drift. Competes with losing
    # signals if conditions flip across seasons.
    if wp >= 0.62:
        dampen = (wp - 0.60) * 0.20 * (1.0 - resistance)
        for trait in deltas:
            current = gm_traits.get(trait, 0.5)
            # Small pull toward the neutral midpoint (0.5)
            deltas[trait] += (0.5 - current) * dampen * 0.20
        reasons.append(
            f"strong winning season ({signals['wins']}-{signals['losses']}, {wp:.0%}) --"
            f"traits stabilising [dampen={dampen:.3f}]"
        )

    return deltas, reasons


def _describe_drift_tendency(traits, current_archetype):
    """
    Return a short label when traits are drifting toward a DIFFERENT archetype.
    Only flags cross-archetype tension — same-archetype reinforcement is expected.
    """
    yp  = traits.get("youth_preference", 0.5)
    vl  = traits.get("veteran_loyalty",  0.5)
    tf  = traits.get("trade_frequency",  0.5)
    rt  = traits.get("risk_tolerance",   0.5)

    if yp >= 0.72 and vl <= 0.28 and current_archetype != "aggressive_rebuilder":
        return "drifting toward REBUILD mentality"
    if yp <= 0.22 and tf >= 0.58 and rt >= 0.55 and current_archetype != "win_now":
        return "drifting toward WIN-NOW mentality"
    if vl >= 0.75 and yp <= 0.22 and current_archetype != "loyal_to_veterans":
        return "drifting toward deep VETERAN LOYALTY"
    if current_archetype == "aggressive_rebuilder" and yp < 0.55:
        return "rebuild conviction weakening"
    if current_archetype == "loyal_to_veterans" and vl < 0.80:
        return "loyalty eroding -- considering youth infusion"
    if current_archetype == "win_now" and yp > 0.55:
        return "win-now conviction wavering -- patience growing"
    return None


def evaluate_season_end(conn, gm, season_year, verbose=True):
    """
    End-of-season GM personality evaluation.

    Reads this season's performance, computes drift deltas, applies them to the
    GM's stored traits (clamped to [0.05, 0.95]), and logs to agent_memory.

    Compounding across seasons: each call shifts from wherever traits currently
    sit, so a team that loses three years running will drift substantially.
    """
    gm             = dict(gm)
    archetypes_data = load_archetypes()
    archetype_cfg  = archetypes_data["archetypes"][gm["archetype"]]

    signals = compute_performance_signals(conn, gm["team_id"], season_year)
    if not signals:
        return None

    gm_traits = {
        "risk_tolerance":  gm["risk_tolerance"],
        "veteran_loyalty": gm["veteran_loyalty"],
        "youth_preference": gm["youth_preference"],
        "trade_frequency": gm["trade_frequency"],
    }

    deltas, reasons = compute_trait_drift(signals, gm_traits, archetype_cfg)

    # Apply deltas, clamp each trait to [0.05, 0.95]
    new_traits   = {}
    change_lines = []
    for trait, delta in deltas.items():
        old_val = gm_traits[trait]
        new_val = max(0.05, min(0.95, old_val + delta))
        new_traits[trait] = new_val
        if abs(new_val - old_val) >= 0.003:
            direction = "+" if new_val > old_val else ""
            change_lines.append(
                f"{trait}: {old_val:.3f} -> {new_val:.3f} "
                f"({direction}{new_val - old_val:.3f})"
            )

    tendency = _describe_drift_tendency(new_traits, gm["archetype"])

    if not change_lines:
        log_memory(
            conn, gm["id"], 0, season_year, "season_review",
            detail=(
                f"Season {season_year} complete. No significant drift. "
                f"Record: {signals['wins']}-{signals['losses']} "
                f"({signals['winning_pct']:.0%}), avg age {signals['avg_age']:.1f}."
            ),
        )
        if verbose:
            print(
                f"  {gm['name']:<32} no trait change "
                f"({signals['wins']}-{signals['losses']}, avg age {signals['avg_age']:.1f})"
            )
        conn.commit()
        return new_traits

    # Persist updated traits
    conn.execute(
        """UPDATE general_managers
           SET risk_tolerance  = ?,
               veteran_loyalty = ?,
               youth_preference = ?,
               trade_frequency = ?
           WHERE id = ?""",
        (
            new_traits["risk_tolerance"],
            new_traits["veteran_loyalty"],
            new_traits["youth_preference"],
            new_traits["trade_frequency"],
            gm["id"],
        ),
    )

    detail_parts = [
        f"Season {season_year} review: "
        f"{signals['wins']}-{signals['losses']} ({signals['winning_pct']:.0%}), "
        f"avg age {signals['avg_age']:.1f}, "
        f"{signals['veteran_ratio']:.0%} veterans.",
        "Changes: " + "; ".join(change_lines) + ".",
        "Drivers: " + "; ".join(reasons) + ".",
    ]
    if tendency:
        detail_parts.append(f"Tendency note: {tendency}.")

    log_memory(
        conn, gm["id"], 0, season_year, "personality_drift",
        detail=" ".join(detail_parts),
    )
    conn.commit()

    if verbose:
        team = conn.execute(
            "SELECT city, name FROM teams WHERE id = ?", (gm["team_id"],)
        ).fetchone()
        label = f"{team['city']} {team['name']}" if team else "?"
        record_str = f"{signals['wins']}-{signals['losses']}"
        print(f"\n  {gm['name']} ({gm['archetype']}) --{label}")
        print(f"    Season: {record_str}  avg age {signals['avg_age']:.1f}  "
              f"{signals['veteran_ratio']:.0%} vets")
        for line in change_lines:
            print(f"    {line}")
        for reason in reasons:
            print(f"    >> {reason}")
        if tendency:
            print(f"    *** {tendency} ***")

    return new_traits


def evaluate_all_gms_season_end(conn, season_year, verbose=True):
    """
    Run end-of-season personality evaluation for every GM.
    Called automatically from run_week.py when the last week is complete.
    """
    from league.database import create_tables
    create_tables()

    c   = conn.cursor()
    gms = c.execute("SELECT * FROM general_managers").fetchall()
    if not gms:
        return

    if verbose:
        print(f"\n{'='*54}")
        print(f"  END-OF-SEASON GM REVIEW  --  {season_year}")
        print(f"{'='*54}")

    for gm in gms:
        evaluate_season_end(conn, dict(gm), season_year, verbose=verbose)

    if verbose:
        print(f"\n  Trait updates saved to database.")
        print(f"  Run  python view_league.py  for final standings.\n")
