import random


def simulate_game(home_players, away_players, home_chemistry=70.0, away_chemistry=70.0,
                  home_player_mods=None, away_player_mods=None,
                  home_team_mod=0.0, away_team_mod=0.0):
    """
    Simulate one basketball game. Returns:
        (home_score, away_score, home_box_score, away_box_score)

    home/away_player_mods: {player_id: skill_delta} from hot/cold streak modifiers.
    home/away_team_mod: flat chemistry delta from momentum modifiers.
    """
    pace = max(90, min(106, int(random.gauss(99, 3))))

    adj_home_chem = max(25.0, min(96.0, home_chemistry + home_team_mod))
    adj_away_chem = max(25.0, min(96.0, away_chemistry + away_team_mod))

    home_score = _team_score(
        home_players, possessions=pace, home_advantage=True, chemistry=adj_home_chem
    )
    away_score = _team_score(
        away_players, possessions=pace, home_advantage=False, chemistry=adj_away_chem
    )

    while home_score == away_score:
        home_score += random.randint(4, 14)
        away_score += random.randint(4, 14)

    home_box = _box_score(home_players, home_score, pace, player_mods=home_player_mods)
    away_box = _box_score(away_players, away_score, pace, player_mods=away_player_mods)
    home_quarters = _split_quarters(home_score)
    away_quarters = _split_quarters(away_score)

    return home_score, away_score, home_box, away_box, home_quarters, away_quarters


def _team_score(players, possessions, home_advantage=False, chemistry=70.0):
    avg_skill = sum(p["skill_rating"] for p in players) / len(players)
    top_skill = sum(
        p["skill_rating"] for p in sorted(players, key=lambda p: p["skill_rating"], reverse=True)[:3]
    ) / min(3, len(players))

    # Skill 68 lands near a modern pro baseline of ~113 points per 100 possessions.
    offensive_rating = 94 + avg_skill * 0.23 + top_skill * 0.05
    if home_advantage:
        offensive_rating += 2.2

    # Chemistry is still meaningful, but less swingy than a pure score multiplier.
    offensive_rating += (chemistry - 70.0) * 0.08

    expected = possessions * offensive_rating / 100.0
    score = int(random.gauss(expected, 7.0))
    return max(78, min(148, score))


def _box_score(players, team_score, possessions, player_mods=None):
    if player_mods:
        players = [
            {**p, "skill_rating": max(30, min(96, p["skill_rating"] + player_mods.get(p["id"], 0)))}
            for p in players
        ]
    sorted_players = sorted(players, key=lambda p: p["skill_rating"], reverse=True)
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
        max(
            1.0,
            p["skill_rating"]
            * rank_multipliers[min(i, len(rank_multipliers) - 1)]
            * pos_multipliers.get(p["position"], 1.0)
            * random.uniform(0.84, 1.18),
        )
        for i, p in enumerate(players)
    ]


def _rebound_weights(players):
    pos_multipliers = {"PG": 0.40, "SG": 0.55, "SF": 0.90, "PF": 2.15, "C": 2.70}
    return [
        max(1.0, (p["skill_rating"] * 0.55 + 35) * pos_multipliers.get(p["position"], 1.0)
            * random.uniform(0.82, 1.22))
        for p in players
    ]


def _assist_weights(players):
    pos_multipliers = {"PG": 4.80, "SG": 1.75, "SF": 1.20, "PF": 0.65, "C": 0.55}
    return [
        max(1.0, (p["skill_rating"] * 0.75 + 20) * pos_multipliers.get(p["position"], 1.0)
            * random.uniform(0.80, 1.25))
        for p in players
    ]


def _defense_weights(players, kind):
    if kind == "block":
        pos_multipliers = {"PG": 0.25, "SG": 0.35, "SF": 0.70, "PF": 1.45, "C": 1.80}
    else:
        pos_multipliers = {"PG": 1.25, "SG": 1.20, "SF": 1.05, "PF": 0.75, "C": 0.65}
    return [
        max(1.0, p["skill_rating"] * pos_multipliers.get(p["position"], 1.0)
            * random.uniform(0.70, 1.35))
        for p in players
    ]
