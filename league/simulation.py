import random


def simulate_game(home_players, away_players):
    """
    Simulate one basketball game. Returns:
        (home_score, away_score, home_box_score, away_box_score)
    Each box score is a list of per-player stat dicts.
    """
    home_score = _team_score(home_players, home_advantage=True)
    away_score = _team_score(away_players, home_advantage=False)

    # Overtime until someone wins
    while home_score == away_score:
        home_score += random.randint(4, 14)
        away_score += random.randint(4, 14)

    home_box = _box_score(home_players, home_score)
    away_box = _box_score(away_players, away_score)

    return home_score, away_score, home_box, away_box


def _team_score(players, home_advantage=False):
    avg_skill = sum(p["skill_rating"] for p in players) / len(players)
    # avg skill 60 → ~100 pts; skill 40 → ~86; skill 85 → ~113
    base = 75 + (avg_skill / 100) * 45
    if home_advantage:
        base += 3
    score = int(random.gauss(base, 8))
    return max(72, min(145, score))


def _box_score(players, team_score):
    sorted_players = sorted(players, key=lambda p: p["skill_rating"], reverse=True)

    # Weighted share: stars get a bigger slice, with per-game noise
    multipliers = [1.9, 1.4, 1.1, 0.8, 0.7, 0.6, 0.5, 0.5, 0.4, 0.4]
    weights = [
        max(1.0, p["skill_rating"] * multipliers[i] * random.uniform(0.75, 1.25))
        for i, p in enumerate(sorted_players)
    ]
    total_w = sum(weights)

    # Hamilton's largest-remainder method so points sum exactly to team_score
    exact = [team_score * w / total_w for w in weights]
    floored = [int(e) for e in exact]
    remainder = team_score - sum(floored)
    fracs = sorted(range(len(exact)), key=lambda i: exact[i] - floored[i], reverse=True)
    for i in range(remainder):
        floored[fracs[i]] += 1

    box = []
    for player, pts in zip(sorted_players, floored):
        pos = player["position"]
        box.append({
            "player_id": player["id"],
            "team_id":   player["team_id"],
            "points":    pts,
            "rebounds":  max(0, int(random.gauss(5.5 if pos in ("PF", "C") else 3.0, 2.0))),
            "assists":   max(0, int(random.gauss(5.0 if pos == "PG" else (2.5 if pos == "SG" else 1.2), 1.8))),
            "steals":    max(0, int(random.gauss(0.9, 0.7))),
            "blocks":    max(0, int(random.gauss(1.2 if pos in ("PF", "C") else 0.25, 0.6))),
        })
    return box
