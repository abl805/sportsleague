import random
import math


def simulate_game(home_players, away_players, home_chemistry=70.0, away_chemistry=70.0,
                  home_player_mods=None, away_player_mods=None,
                  home_team_mod=0.0, away_team_mod=0.0,
                  home_morale=70.0, away_morale=70.0,
                  home_coach=None, away_coach=None,
                  home_injury_effect=0.0, away_injury_effect=0.0,
                  home_injuries=None, away_injuries=None):
    """
    Simulate one basketball game. Returns:
        (home_score, away_score, home_box_score, away_box_score)

    home/away_player_mods: {player_id: skill_delta} from hot/cold streak modifiers.
    home/away_team_mod: flat chemistry delta from momentum modifiers.
    """
    home_players = _apply_player_mods(home_players, home_player_mods)
    away_players = _apply_player_mods(away_players, away_player_mods)

    adj_home_chem = max(25.0, min(96.0, home_chemistry + home_team_mod))
    adj_away_chem = max(25.0, min(96.0, away_chemistry + away_team_mod))
    home_pace = (home_coach or {}).get("pace_preference", 0.5)
    away_pace = (away_coach or {}).get("pace_preference", 0.5)
    pace = max(91, min(106, int(random.gauss(96 + (home_pace + away_pace) * 4.2, 1.8))))

    matchup_home, matchup_away, matchup_text = _strategy_matchup(
        (home_coach or {}).get("strategy"),
        (away_coach or {}).get("strategy"),
    )
    home_players, home_rotation = build_coach_rotation(home_players, home_coach)
    away_players, away_rotation = build_coach_rotation(away_players, away_coach)

    home_profile = _team_profile(
        home_players,
        possessions=pace,
        chemistry=adj_home_chem,
        morale=home_morale,
        coach=home_coach,
        injury_effect=home_injury_effect,
        matchup_effect=matchup_home,
        home_advantage=True,
        rotation=home_rotation,
    )
    away_profile = _team_profile(
        away_players,
        possessions=pace,
        chemistry=adj_away_chem,
        morale=away_morale,
        coach=away_coach,
        injury_effect=away_injury_effect,
        matchup_effect=matchup_away,
        home_advantage=False,
        rotation=away_rotation,
    )

    expected_margin = home_profile["expected_points"] - away_profile["expected_points"]
    home_win_probability = 1.0 / (1.0 + math.exp(-expected_margin / 6.2))
    total_expected = home_profile["expected_points"] + away_profile["expected_points"]
    actual_margin = random.gauss(expected_margin, 9.1)
    if abs(actual_margin) <= 7:
        actual_margin += (home_profile["clutch"] - away_profile["clutch"]) * 3.0
    actual_total = random.gauss(total_expected, 10.0)
    home_score = int(round((actual_total + actual_margin) / 2))
    away_score = int(round((actual_total - actual_margin) / 2))
    home_score = max(78, min(148, home_score))
    away_score = max(78, min(148, away_score))
    while home_score == away_score:
        if random.random() < home_win_probability:
            home_score += random.randint(4, 9)
            away_score += random.randint(2, 7)
        else:
            home_score += random.randint(2, 7)
            away_score += random.randint(4, 9)

    home_box = _box_score(home_players, home_score, pace)
    away_box = _box_score(away_players, away_score, pace)
    home_quarters = _split_quarters(home_score)
    away_quarters = _split_quarters(away_score)
    home_turnovers = _turnovers(home_profile, home_coach)
    away_turnovers = _turnovers(away_profile, away_coach)

    context = {
        "home_score": home_score,
        "away_score": away_score,
        "possessions": pace,
        "expected_margin": round(expected_margin, 2),
        "home_win_probability": round(home_win_probability, 4),
        "strategy_matchup": matchup_text,
        "home_turnovers": home_turnovers,
        "away_turnovers": away_turnovers,
        "home_expected_points": round(home_profile["expected_points"], 2),
        "away_expected_points": round(away_profile["expected_points"], 2),
        "home_strength": round(home_profile["strength"], 2),
        "away_strength": round(away_profile["strength"], 2),
        "home_chemistry": round(adj_home_chem, 2),
        "away_chemistry": round(adj_away_chem, 2),
        "home_morale": round(home_morale, 2),
        "away_morale": round(away_morale, 2),
        "home_coach_effect": round(home_profile["coach_effect"], 2),
        "away_coach_effect": round(away_profile["coach_effect"], 2),
        "home_injury_effect": round(-abs(home_injury_effect), 2),
        "away_injury_effect": round(-abs(away_injury_effect), 2),
        "home_clutch_effect": round((home_profile["clutch"] - 0.5) * 3.0, 2),
        "away_clutch_effect": round((away_profile["clutch"] - 0.5) * 3.0, 2),
        "home_factors": home_profile["factors"],
        "away_factors": away_profile["factors"],
        "home_injuries": home_injuries or [],
        "away_injuries": away_injuries or [],
        "home_rotation": home_rotation,
        "away_rotation": away_rotation,
    }
    return (
        home_score,
        away_score,
        home_box,
        away_box,
        home_quarters,
        away_quarters,
        context,
    )


def _apply_player_mods(players, mods):
    if not mods:
        return [dict(player) for player in players]
    return [
        {
            **dict(player),
            "skill_rating": max(
                30,
                min(96, player["skill_rating"] + mods.get(player["id"], 0)),
            ),
        }
        for player in players
    ]


def build_coach_rotation(players, coach=None):
    """Return a coach-selected rotation with exact minutes and usage roles."""
    coach = coach or {}
    lineup_preference = coach.get("lineup_preference") or _default_lineup_preference(
        coach.get("strategy")
    )
    tightness = max(0.0, min(1.0, float(coach.get("rotation_tightness", 0.5))))
    prepared = [dict(player) for player in players]
    for player in prepared:
        player["_lineup_score"] = _lineup_score(player, lineup_preference)

    starters = []
    remaining = list(prepared)
    for position in ("PG", "SG", "SF", "PF", "C"):
        candidates = [p for p in remaining if p.get("position") == position]
        if not candidates:
            continue
        choice = max(candidates, key=lambda p: (p["_lineup_score"], p["skill_rating"]))
        starters.append(choice)
        remaining.remove(choice)
    while len(starters) < min(5, len(prepared)) and remaining:
        choice = max(remaining, key=lambda p: (p["_lineup_score"], p["skill_rating"]))
        starters.append(choice)
        remaining.remove(choice)

    if tightness >= 0.75:
        target_size = 7
    elif tightness >= 0.55:
        target_size = 8
    elif tightness >= 0.35:
        target_size = 9
    else:
        target_size = 10
    rotation_size = min(len(prepared), max(len(starters), target_size))
    bench = sorted(
        remaining,
        key=lambda p: (p["_lineup_score"], p["skill_rating"]),
        reverse=True,
    )[:max(0, rotation_size - len(starters))]
    rotation = starters + bench

    if len(rotation) == len(starters):
        starter_total = 240
    else:
        starter_share = 0.70 + tightness * 0.12
        starter_total = max(174, min(198, int(round(240 * starter_share))))
    starter_weights = [
        1.0 + max(0.0, p["_lineup_score"] - 65.0) / 85.0
        for p in starters
    ]
    starter_minutes = _allocate_total(starter_total, starter_weights)
    bench_minutes = _allocate_total(
        240 - starter_total,
        [
            1.0 + max(0.0, p["_lineup_score"] - 62.0) / 75.0
            for p in bench
        ],
    ) if bench else []

    minute_map = {
        player["id"]: minutes
        for player, minutes in zip(starters + bench, starter_minutes + bench_minutes)
    }
    starter_ids = {player["id"] for player in starters}
    rotation_ids = {player["id"] for player in rotation}
    for player in prepared:
        minutes = minute_map.get(player["id"], 0)
        player["minutes"] = minutes
        player["started"] = 1 if player["id"] in starter_ids else 0
        player["rotation_role"] = (
            "starter" if player["id"] in starter_ids
            else "reserve" if player["id"] in rotation_ids
            else "did_not_play"
        )
        player["usage_weight"] = (
            (minutes / 30.0)
            * (1.08 if player["started"] else 0.94)
        ) if minutes else 0.0

    active_fit = [
        _preference_bonus(player, lineup_preference)
        for player in rotation
    ]
    rotation_fit = min(0.75, (sum(active_fit) / max(1, len(active_fit))) * 0.12)
    coach_name = coach.get("name") or "The coaching staff"
    preference_label = lineup_preference.replace("_", " ")
    depth_label = (
        "tight" if rotation_size <= 7
        else "selective" if rotation_size == 8
        else "balanced" if rotation_size == 9
        else "deep"
    )
    starter_minute_total = sum(starter_minutes)
    summary = (
        f"{coach_name} used a {depth_label} {rotation_size}-player rotation "
        f"built around {preference_label}; starters handled "
        f"{round(starter_minute_total / 2.4)}% of the minutes."
    )
    metadata = {
        "coach_id": coach.get("id"),
        "coach_name": coach_name,
        "rotation_size": rotation_size,
        "rotation_tightness": round(tightness, 3),
        "lineup_preference": lineup_preference,
        "starter_ids": [player["id"] for player in starters],
        "rotation_ids": [player["id"] for player in rotation],
        "starter_minutes": starter_minute_total,
        "rotation_fit": round(rotation_fit, 3),
        "summary": summary,
    }
    return prepared, metadata


def _default_lineup_preference(strategy):
    return {
        "inside_control": "size_and_strength",
        "hustle_pressure": "energy_and_defense",
        "pace_and_space": "speed_and_shooting",
        "creative_motion": "playmaking",
        "defensive_grind": "defense_and_veterans",
        "late_game_control": "clutch_and_experience",
        "development_lab": "youth_and_upside",
    }.get(strategy, "balanced_best_five")


def _lineup_score(player, preference):
    return float(player["skill_rating"]) + _preference_bonus(player, preference)


def _preference_bonus(player, preference):
    position = player.get("position")
    age = int(player.get("age") or 27)
    work_ethic = float(player.get("work_ethic") or 0.5)
    leadership = float(player.get("leadership") or 0.5)
    clutch = float(player.get("clutch") or 0.5)
    if preference == "size_and_strength":
        return {"C": 3.2, "PF": 2.4, "SF": 0.8}.get(position, 0.0)
    if preference == "energy_and_defense":
        return work_ethic * 2.4 + leadership * 1.2
    if preference == "speed_and_shooting":
        return {"PG": 2.8, "SG": 2.5, "SF": 1.5}.get(position, 0.0)
    if preference == "playmaking":
        return {"PG": 3.2, "SG": 1.7, "SF": 0.8}.get(position, 0.0)
    if preference == "defense_and_veterans":
        position_bonus = {"C": 1.8, "PF": 1.4, "SF": 0.8}.get(position, 0.0)
        veteran_bonus = 0.9 if 27 <= age <= 33 else 0.0
        return position_bonus + leadership * 1.6 + veteran_bonus
    if preference == "clutch_and_experience":
        return clutch * 3.0 + (1.0 if 27 <= age <= 34 else 0.0)
    if preference == "youth_and_upside":
        return max(0, 26 - age) * 0.38 + work_ethic * 2.0
    return leadership * 0.4 + clutch * 0.4


def _team_profile(players, possessions, chemistry, morale, coach, injury_effect,
                  matchup_effect, home_advantage=False, rotation=None):
    active_players = [p for p in players if p.get("minutes", 0) > 0] or players
    total_minutes = sum(p.get("minutes", 0) for p in active_players)
    if total_minutes:
        avg_skill = sum(
            p["skill_rating"] * p.get("minutes", 0) for p in active_players
        ) / total_minutes
    else:
        avg_skill = sum(p["skill_rating"] for p in active_players) / len(active_players)
    sorted_players = sorted(
        active_players, key=lambda p: p["skill_rating"], reverse=True
    )
    top_skill = sum(p["skill_rating"] for p in sorted_players[:3]) / min(3, len(players))
    clutch_values = [
        p.get("clutch") if p.get("clutch") is not None else 0.5
        for p in sorted(
            active_players,
            key=lambda p: (p.get("started", 0), p.get("minutes", 0)),
            reverse=True,
        )[:5]
    ]
    clutch = sum(clutch_values) / len(clutch_values)

    talent_effect = (avg_skill - 68.0) * 0.31
    star_effect = (top_skill - 72.0) * 0.12
    chemistry_effect = (chemistry - 70.0) * 0.07
    morale_effect = (morale - 70.0) * 0.045
    rotation_effect = float((rotation or {}).get("rotation_fit", 0.0))
    tactical_coach_effect = _coach_effect(coach) + matchup_effect
    coach_effect = tactical_coach_effect + rotation_effect
    home_effect = 2.25 if home_advantage else 0.0
    health_effect = -abs(injury_effect)

    offensive_rating = (
        108.5
        + talent_effect
        + star_effect
        + chemistry_effect
        + morale_effect
        + coach_effect
        + home_effect
        + health_effect
    )
    expected = possessions * offensive_rating / 100.0
    strength = (
        avg_skill * 0.64
        + top_skill * 0.24
        + chemistry * 0.05
        + morale * 0.03
        + coach_effect * 1.4
        + home_effect
        + health_effect
    )
    factors = [
        {"label": "roster talent", "value": round(talent_effect, 2)},
        {"label": "star power", "value": round(star_effect, 2)},
        {"label": "team chemistry", "value": round(chemistry_effect, 2)},
        {"label": "morale", "value": round(morale_effect, 2)},
        {"label": "coaching and matchup", "value": round(tactical_coach_effect, 2)},
        {"label": "rotation plan", "value": round(rotation_effect, 2)},
        {"label": "availability", "value": round(health_effect, 2)},
    ]
    if home_advantage:
        factors.append({"label": "home court", "value": round(home_effect, 2)})
    return {
        "expected_points": expected,
        "strength": strength,
        "clutch": clutch,
        "coach_effect": coach_effect,
        "factors": factors,
        "morale": morale,
    }


def _coach_effect(coach):
    if not coach:
        return 0.0
    return (
        (coach.get("leadership", 0.5) - 0.5) * 2.2
        + (coach.get("pressure_handling", 0.5) - 0.5) * 1.6
    )


def _strategy_matchup(home_strategy, away_strategy):
    counters = {
        ("defensive_grind", "pace_and_space"): 1.25,
        ("pace_and_space", "inside_control"): 1.05,
        ("inside_control", "defensive_grind"): 0.80,
        ("precision_balance", "creative_motion"): 0.75,
        ("hustle_pressure", "precision_balance"): 0.55,
        ("creative_motion", "defensive_grind"): 0.45,
        ("late_game_control", "hustle_pressure"): 0.60,
        ("development_lab", "late_game_control"): -0.35,
    }
    home_edge = counters.get((home_strategy, away_strategy), 0.0)
    away_edge = counters.get((away_strategy, home_strategy), 0.0)
    net = home_edge - away_edge
    if abs(net) < 0.15:
        text = (
            f"{(home_strategy or 'balanced').replace('_', ' ')} against "
            f"{(away_strategy or 'balanced').replace('_', ' ')} projects as an even tactical matchup."
        )
    elif net > 0:
        text = f"The home side's {(home_strategy or 'balanced').replace('_', ' ')} approach owns the tactical edge."
    else:
        text = f"The visitors' {(away_strategy or 'balanced').replace('_', ' ')} approach owns the tactical edge."
    return net, -net, text


def _turnovers(profile, coach):
    control = (coach or {}).get("pressure_handling", 0.5)
    base = 13.5 - (profile["morale"] - 70.0) * 0.035 - (control - 0.5) * 2.0
    return max(7, min(22, int(round(random.gauss(base, 2.2)))))


def _box_score(players, team_score, possessions, player_mods=None):
    sorted_players = sorted(
        players,
        key=lambda p: (
            p.get("started", 0),
            p.get("minutes", 0),
            p["skill_rating"],
        ),
        reverse=True,
    )
    points = _allocate_total(team_score, _scoring_weights(sorted_players))

    rebounds = _allocate_total(
        max(30, min(58, int(random.gauss(42 + (possessions - 99) * 0.18, 4.0)))),
        _rebound_weights(sorted_players),
    )
    assists = _allocate_total(
        max(14, min(36, int(random.gauss(team_score * 0.235, 3.0)))),
        _assist_weights(sorted_players),
    )
    steals = _allocate_total(
        max(3, min(13, int(random.gauss(7.4, 1.7)))),
        _defense_weights(sorted_players, kind="steal"),
    )
    blocks = _allocate_total(
        max(1, min(10, int(random.gauss(4.5, 1.5)))),
        _defense_weights(sorted_players, kind="block"),
    )

    box = []
    for i, player in enumerate(sorted_players):
        box.append({
            "player_id": player["id"],
            "team_id": player["team_id"],
            "minutes": player.get("minutes", 0),
            "started": player.get("started", 0),
            "rotation_role": player.get("rotation_role", "did_not_play"),
            "points": points[i],
            "rebounds": rebounds[i],
            "assists": assists[i],
            "steals": steals[i],
            "blocks": blocks[i],
        })
    return box


def _split_quarters(total):
    weights = [random.gauss(1.0, 0.12) for _ in range(4)]
    weights = [max(0.4, w) for w in weights]
    total_w = sum(weights)
    raw = [total * w / total_w for w in weights]
    floored = [int(r) for r in raw]
    remainder = total - sum(floored)
    fracs = sorted(range(4), key=lambda i: raw[i] - floored[i], reverse=True)
    for i in range(remainder):
        floored[fracs[i % 4]] += 1
    return floored


def _allocate_total(total, weights):
    total_weight = sum(weights) or 1.0
    exact = [total * w / total_weight for w in weights]
    floored = [int(e) for e in exact]
    remainder = total - sum(floored)
    fracs = sorted(range(len(exact)), key=lambda i: exact[i] - floored[i], reverse=True)
    for i in range(remainder):
        floored[fracs[i % len(fracs)]] += 1
    return floored


def _scoring_weights(players):
    rank_multipliers = [1.75, 1.45, 1.20, 1.00, 0.86, 0.70, 0.60, 0.52, 0.45, 0.40]
    pos_multipliers = {"PG": 1.08, "SG": 1.10, "SF": 1.06, "PF": 0.98, "C": 0.95}
    return [
        0.0 if p.get("minutes", 0) <= 0 else max(
            1.0,
            p["skill_rating"]
            * rank_multipliers[min(i, len(rank_multipliers) - 1)]
            * pos_multipliers.get(p["position"], 1.0)
            * p.get("usage_weight", 1.0)
            * random.uniform(0.84, 1.18),
        )
        for i, p in enumerate(players)
    ]


def _rebound_weights(players):
    pos_multipliers = {"PG": 0.40, "SG": 0.55, "SF": 0.90, "PF": 2.15, "C": 2.70}
    return [
        0.0 if p.get("minutes", 0) <= 0 else max(
            1.0,
            (p["skill_rating"] * 0.55 + 35)
            * pos_multipliers.get(p["position"], 1.0)
            * (p.get("minutes", 30) / 30.0)
            * random.uniform(0.82, 1.22),
        )
        for p in players
    ]


def _assist_weights(players):
    pos_multipliers = {"PG": 4.80, "SG": 1.75, "SF": 1.20, "PF": 0.65, "C": 0.55}
    return [
        0.0 if p.get("minutes", 0) <= 0 else max(
            1.0,
            (p["skill_rating"] * 0.75 + 20)
            * pos_multipliers.get(p["position"], 1.0)
            * (p.get("minutes", 30) / 30.0)
            * random.uniform(0.80, 1.25),
        )
        for p in players
    ]


def _defense_weights(players, kind):
    if kind == "block":
        pos_multipliers = {"PG": 0.25, "SG": 0.35, "SF": 0.70, "PF": 1.45, "C": 1.80}
    else:
        pos_multipliers = {"PG": 1.25, "SG": 1.20, "SF": 1.05, "PF": 0.75, "C": 0.65}
    return [
        0.0 if p.get("minutes", 0) <= 0 else max(
            1.0,
            p["skill_rating"]
            * pos_multipliers.get(p["position"], 1.0)
            * (p.get("minutes", 30) / 30.0)
            * random.uniform(0.70, 1.35),
        )
        for p in players
    ]
