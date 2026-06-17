import hashlib
import json
import re

from league.database import get_connection
from league.playoffs import get_playoff_snapshot


CHATGPT_SCHEMA = "aibl.manual_chatgpt.v1"
APP_TO_GPT_START = "=== AIBA APP TO CHATGPT ==="
APP_TO_GPT_END = "=== END AIBA APP TO CHATGPT ==="
GPT_TO_APP_START = "=== CHATGPT TO AIBA ==="
GPT_TO_APP_END = "=== END CHATGPT TO AIBA ==="


def rows_to_dicts(rows):
    return [dict(row) for row in rows]


def compact_player(row):
    player = dict(row)
    if "salary" in player and player["salary"] is not None:
        player["salary_millions"] = round(player["salary"] / 1_000_000, 2)
    return player


def hash_text(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]


def league_snapshot_context(conn, season_year):
    state = conn.execute("SELECT * FROM league_state WHERE id = 1").fetchone()
    standings = rows_to_dicts(conn.execute("""
        SELECT t.city || ' ' || t.name AS team,
               t.abbreviation,
               s.wins,
               s.losses,
               s.points_for,
               s.points_against,
               s.points_for - s.points_against AS point_diff
        FROM standings s
        JOIN teams t ON t.id = s.team_id
        WHERE s.season_year = ?
        ORDER BY s.wins DESC, point_diff DESC
    """, (season_year,)).fetchall())

    leaders = rows_to_dicts(conn.execute("""
        SELECT p.first_name || ' ' || p.last_name AS player,
               t.abbreviation AS team,
               p.position,
               ROUND(AVG(pgs.points), 1) AS ppg,
               ROUND(AVG(pgs.rebounds), 1) AS rpg,
               ROUND(AVG(pgs.assists), 1) AS apg,
               COUNT(pgs.id) AS games_played
        FROM player_game_stats pgs
        JOIN games g ON g.id = pgs.game_id
        JOIN players p ON p.id = pgs.player_id
        JOIN teams t ON t.id = p.team_id
        WHERE g.season_year = ?
        GROUP BY p.id
        ORDER BY ppg DESC
        LIMIT 15
    """, (season_year,)).fetchall())

    recent_games = rows_to_dicts(conn.execute("""
        SELECT g.week,
               ht.city || ' ' || ht.name AS home_team,
               at.city || ' ' || at.name AS away_team,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ? AND g.played = 1
        ORDER BY g.week DESC, g.id DESC
        LIMIT 12
    """, (season_year,)).fetchall())

    pending_trade_count = conn.execute(
        "SELECT COUNT(*) FROM pending_trades WHERE status = 'pending'"
    ).fetchone()[0]

    phase = state["phase"] if state and "phase" in state.keys() else "regular_season"
    playoffs = None
    if phase in ("playoffs", "complete"):
        playoffs = get_playoff_snapshot(conn, season_year)

    return {
        "standings": standings,
        "stat_leaders": leaders,
        "recent_games": recent_games,
        "pending_trade_count": pending_trade_count,
        "playoffs": playoffs,
    }


def team_report_context(conn, team_id, season_year):
    team = conn.execute("""
        SELECT id, city, name, abbreviation, mascot, colors, motto, arena,
               team_archetype, play_style, reputation, rivalry, signature_trait
        FROM teams
        WHERE id = ?
    """, (team_id,)).fetchone()

    roster = [
        compact_player(row)
        for row in conn.execute("""
            SELECT p.id,
                   p.first_name || ' ' || p.last_name AS player,
                   p.position,
                   p.age,
                   p.skill_rating,
                   p.salary,
                   c.years_remaining
            FROM players p
            LEFT JOIN contracts c ON c.player_id = p.id
            WHERE p.team_id = ? AND COALESCE(p.status, 'active') = 'active'
            ORDER BY p.skill_rating DESC
        """, (team_id,)).fetchall()
    ]

    standings = conn.execute("""
        SELECT wins, losses, points_for, points_against,
               points_for - points_against AS point_diff
        FROM standings
        WHERE team_id = ? AND season_year = ?
    """, (team_id, season_year)).fetchone()

    recent_games = rows_to_dicts(conn.execute("""
        SELECT g.week,
               ht.city || ' ' || ht.name AS home_team,
               at.city || ' ' || at.name AS away_team,
               g.home_score,
               g.away_score
        FROM games g
        JOIN teams ht ON ht.id = g.home_team_id
        JOIN teams at ON at.id = g.away_team_id
        WHERE g.season_year = ?
          AND g.played = 1
          AND (g.home_team_id = ? OR g.away_team_id = ?)
        ORDER BY g.week DESC
        LIMIT 6
    """, (season_year, team_id, team_id)).fetchall())

    gm = conn.execute("""
        SELECT name, archetype, risk_tolerance, veteran_loyalty,
               youth_preference, trade_frequency
        FROM general_managers
        WHERE team_id = ?
    """, (team_id,)).fetchone()

    return {
        "team": dict(team) if team else None,
        "record": dict(standings) if standings else None,
        "general_manager": dict(gm) if gm else None,
        "roster": roster,
        "recent_games": recent_games,
    }


def trade_report_context(conn, trade_id):
    trade = conn.execute("""
        SELECT pt.*,
               pgm.name AS proposing_gm_name,
               pgm.archetype AS proposing_gm_archetype,
               rgm.name AS receiving_gm_name,
               rgm.archetype AS receiving_gm_archetype,
               pteam.city || ' ' || pteam.name AS proposing_team,
               rteam.city || ' ' || rteam.name AS receiving_team
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        JOIN teams pteam ON pteam.id = pgm.team_id
        JOIN teams rteam ON rteam.id = rgm.team_id
        WHERE pt.id = ?
    """, (trade_id,)).fetchone()

    if not trade:
        return {"trade": None}

    trade_dict = dict(trade)
    offered_ids = json.loads(trade_dict["offered_player_ids"])
    requested_ids = json.loads(trade_dict["requested_player_ids"])

    def players_for(ids):
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        return [
            compact_player(row)
            for row in conn.execute(f"""
                SELECT p.id,
                       p.first_name || ' ' || p.last_name AS player,
                       t.city || ' ' || t.name AS team,
                       p.position,
                       p.age,
                       p.skill_rating,
                       p.salary
                FROM players p
                JOIN teams t ON t.id = p.team_id
                WHERE p.id IN ({placeholders})
            """, ids).fetchall()
        ]

    return {
        "trade": {
            "id": trade_dict["id"],
            "week": trade_dict["week"],
            "season_year": trade_dict["season_year"],
            "status": trade_dict["status"],
            "proposing_team": trade_dict["proposing_team"],
            "receiving_team": trade_dict["receiving_team"],
            "proposing_gm": trade_dict["proposing_gm_name"],
            "receiving_gm": trade_dict["receiving_gm_name"],
            "proposing_gm_archetype": trade_dict["proposing_gm_archetype"],
            "receiving_gm_archetype": trade_dict["receiving_gm_archetype"],
            "proposing_score": trade_dict["proposing_score"],
            "receiving_score": trade_dict["receiving_score"],
            "proposing_reasoning": trade_dict["proposing_reasoning"],
            "receiving_reasoning": trade_dict["receiving_reasoning"],
            "rejection_reason": trade_dict["rejection_reason"],
        },
        "offered_players": players_for(offered_ids),
        "requested_players": players_for(requested_ids),
    }


def build_chatgpt_packet(context_type, commissioner_request, team_id=None, trade_id=None):
    conn = get_connection()
    state_row = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
    if not state_row:
        conn.close()
        raise RuntimeError("League not found. Run seed.py first.")

    packet_season = state_row["season_year"]
    packet_week = state_row["current_week"]

    if context_type == "Team report" and team_id:
        context = team_report_context(conn, team_id, packet_season)
    elif context_type == "Pending trade review" and trade_id:
        context = trade_report_context(conn, trade_id)
    elif context_type == "Commissioner note":
        context = {
            "note": "No league tables were attached. Use the commissioner request only."
        }
    else:
        context = league_snapshot_context(conn, packet_season)

    conn.close()

    instructions = [
        "Read the packet as source-of-truth league data.",
        "Answer the commissioner request without inventing missing stats.",
        "Return a JSON packet inside the CHATGPT TO AIBA markers.",
        "Use short, app-readable strings in summary, recommendations, suggested_actions, questions, and notes_for_commissioner.",
        "REQUIRED: populate 'articles' with 1-3 news stories drawn from the data. Use real team abbreviations and player full names exactly as they appear in the context.",
        "REQUIRED: populate 'influences' with suggested modifiers for standout performers, struggling players, hot/cold teams, and trade-hungry GMs. Use real abbreviations and full names.",
    ]
    if isinstance(context, dict) and context.get("playoffs"):
        instructions.extend([
            "For playoff requests, lead with bracket stakes: series score, elimination pressure, next scheduled game, and who can advance or clinch.",
            "When writing playoff articles, include the series name (Semifinals, Finals, or Third Place) and current best-of-3 status.",
            "Third-place series is a real postseason result, not an exhibition.",
        ])

    payload = {
        "schema": CHATGPT_SCHEMA,
        "direction": "app_to_chatgpt",
        "context_type": context_type,
        "commissioner_request": commissioner_request.strip(),
        "league_state": {
            "season_year": packet_season,
            "current_week": packet_week,
        },
        "instructions_for_chatgpt": instructions,
        "response_contract": {
            "schema": CHATGPT_SCHEMA,
            "direction": "chatgpt_to_app",
            "response_type": context_type,
            "summary": "One short paragraph.",
            "recommendations": ["Recommendation strings."],
            "suggested_actions": ["Action strings the commissioner may take manually."],
            "questions": ["Optional clarification questions."],
            "notes_for_commissioner": ["Optional caveats or narrative hooks."],
            "articles": [
                {
                    "headline": "FILL IN — real headline based on the data",
                    "body": "FILL IN — 2 to 4 sentences of narrative using real names and scores.",
                    "week": packet_week,
                    "team_tags": ["USE REAL ABBREVIATIONS FROM CONTEXT"],
                    "player_tags": ["Use Real Full Name From Context"]
                }
            ],
            "influences": [
                {
                    "player": "Full Name of a standout or struggling player",
                    "streak": "hot or cold",
                    "morale": 6,
                    "work_ethic_boost": 0.10,
                    "duration_weeks": 2,
                    "reason": "FILL IN — one sentence explaining why"
                },
                {
                    "team": "REAL ABBR",
                    "momentum": "hot or cold",
                    "locker_room_boost": 5,
                    "duration_weeks": 2,
                    "reason": "FILL IN — one sentence explaining why"
                },
                {
                    "gm": "REAL ABBR",
                    "trade_urgency": "high or low",
                    "duration_weeks": 2,
                    "reason": "FILL IN — one sentence explaining why"
                }
            ],
        },
        "context": context,
    }

    return (
        f"{APP_TO_GPT_START}\n"
        f"{json.dumps(payload, indent=2)}\n"
        f"{APP_TO_GPT_END}"
    )


def response_template(context_type):
    payload = {
        "schema": CHATGPT_SCHEMA,
        "direction": "chatgpt_to_app",
        "response_type": context_type,
        "summary": "",
        "recommendations": [],
        "suggested_actions": [],
        "questions": [],
        "notes_for_commissioner": [],
    }
    return (
        f"{GPT_TO_APP_START}\n"
        f"{json.dumps(payload, indent=2)}\n"
        f"{GPT_TO_APP_END}"
    )


def extract_marked_json(text, start_marker, end_marker):
    match = re.search(
        rf"{re.escape(start_marker)}\s*(.*?)\s*{re.escape(end_marker)}",
        text,
        flags=re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    first = text.find("{")
    last = text.rfind("}")
    if first >= 0 and last > first:
        return text[first:last + 1]
    return None


def build_interview_packet(game_id, player_id, db=None):
    """
    Build a formatted ChatGPT prompt for a post-game player interview.
    Returns (interview_id, prompt_text) after inserting a pending row.
    Pass db=conn to reuse an existing connection, or None to open one.
    """
    close_conn = db is None
    conn = db if db else get_connection()

    try:
        state = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
        if not state:
            raise RuntimeError("League not found.")
        week = state["current_week"] - 1  # interviews are for the week just completed
        season_year = state["season_year"]

        game = conn.execute("""
            SELECT g.*,
                   ht.city || ' ' || ht.name AS home_name,
                   at.city || ' ' || at.name AS away_name,
                   ht.abbreviation AS home_abbr,
                   at.abbreviation AS away_abbr
            FROM games g
            JOIN teams ht ON ht.id = g.home_team_id
            JOIN teams at ON at.id = g.away_team_id
            WHERE g.id = ?
        """, (game_id,)).fetchone()
        if not game:
            raise ValueError(f"Game {game_id} not found.")

        player = conn.execute("""
            SELECT p.id, p.first_name, p.last_name, p.age, p.position,
                   p.skill_rating, p.team_id,
                   t.city || ' ' || t.name AS team_name,
                   pp.archetype, pp.ego, pp.loyalty, pp.volatility,
                   pb.college_state, pb.hometown_state,
                   pb.personality_label, pb.backstory_blurb
            FROM players p
            JOIN teams t ON t.id = p.team_id
            LEFT JOIN player_personalities pp ON pp.player_id = p.id
            LEFT JOIN player_backstories pb ON pb.player_id = p.id
            WHERE p.id = ?
        """, (player_id,)).fetchone()
        if not player:
            raise ValueError(f"Player {player_id} not found.")

        stats = conn.execute("""
            SELECT points, rebounds, assists, steals, blocks
            FROM player_game_stats
            WHERE game_id = ? AND player_id = ?
        """, (game_id, player_id)).fetchone()

        morale_now = conn.execute("""
            SELECT morale FROM player_morale
            WHERE player_id = ? AND season_year = ?
            ORDER BY week DESC LIMIT 1
        """, (player_id, season_year)).fetchone()
        morale_prev = conn.execute("""
            SELECT morale FROM player_morale
            WHERE player_id = ? AND season_year = ?
            ORDER BY week DESC LIMIT 1 OFFSET 1
        """, (player_id, season_year)).fetchone()

        full_name = f"{player['first_name']} {player['last_name']}"
        is_home = player["team_id"] == game["home_team_id"]
        player_score = game["home_score"] if is_home else game["away_score"]
        opp_score = game["away_score"] if is_home else game["home_score"]
        player_team_name = game["home_name"] if is_home else game["away_name"]
        opp_name = game["away_name"] if is_home else game["home_name"]
        won = player_score > opp_score
        margin = abs(player_score - opp_score)

        morale_val = round(morale_now["morale"]) if morale_now else "?"
        morale_delta = ""
        if morale_now and morale_prev:
            delta = round(morale_now["morale"] - morale_prev["morale"])
            morale_delta = f" (was {round(morale_prev['morale'])} last week)"

        def _trait_word(val):
            if val is None:
                return "moderate"
            if val >= 0.70:
                return "high"
            if val <= 0.35:
                return "low"
            return "moderate"

        ego_word = _trait_word(player["ego"])
        volatility_word = _trait_word(player["volatility"])
        loyalty_word = _trait_word(player["loyalty"])

        personality_label = player["personality_label"] or "Pro"
        college_str = player["college_state"] or "college"
        if college_str == "International":
            college_str = "overseas"
        hometown_str = player["hometown_state"] or "his hometown"
        backstory = player["backstory_blurb"] or ""

        result_str = f"WIN by {margin}" if won else f"LOSS by {margin}"
        if stats:
            stat_line = (f"{stats['points']} pts, {stats['rebounds']} reb, "
                         f"{stats['assists']} ast, {stats['steals']} stl, "
                         f"{stats['blocks']} blk")
        else:
            stat_line = "stats not available"

        question = (
            f"{'Nice win out there tonight' if won else 'Tough one tonight'}, "
            f"{player['first_name']} — what's going through your head right now?"
        )

        packet = f"""=== POST-GAME INTERVIEW PROMPT ===

PLAYER: {full_name}, Age {player['age']}, {player['position']}
TEAM: {player_team_name}
BACKGROUND: Grew up in {hometown_str}. Played college ball in {college_str}.
PERSONALITY TYPE: {personality_label}
TRAITS: {ego_word} ego, {volatility_word} volatility, {loyalty_word} loyalty
BACKSTORY: {backstory}

GAME RESULT: {player_team_name} {player_score} — {opp_score} {opp_name} ({result_str})
{full_name.upper()}'S STAT LINE: {stat_line}
MORALE: {morale_val}/100{morale_delta}

INTERVIEW QUESTION:
"{question}"

INSTRUCTIONS FOR CHATGPT:
Write {player['first_name']}'s answer in 2-4 sentences. Stay in character as a {personality_label}. Sound like a real athlete in a real postgame press conference — not a press release. If they lost badly or underperformed, let that show. If they won big, let them be proud but not generic. Reference the game or the opponent naturally if it fits. Do NOT mention the score directly (players don't usually quote the scoreboard). Use first person.

=== END PROMPT ==="""

        row = conn.execute("""
            INSERT INTO player_interviews
                (game_id, player_id, week, season_year, question, context_packet)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (game_id, player_id, week, season_year, question, packet))
        interview_id = row.lastrowid
        conn.commit()
        return interview_id, packet
    finally:
        if close_conn:
            conn.close()


def save_interview_response(interview_id, response_text, db=None):
    """Store a ChatGPT-generated quote for an interview row."""
    close_conn = db is None
    conn = db if db else get_connection()
    try:
        conn.execute(
            "UPDATE player_interviews SET response = ? WHERE id = ?",
            (response_text.strip(), interview_id),
        )
        conn.commit()
    finally:
        if close_conn:
            conn.close()


def get_pending_interviews(conn, season_year=None, week=None):
    """Return interview rows with no response yet."""
    params = []
    where = "WHERE pi.response IS NULL"
    if season_year:
        where += " AND pi.season_year = ?"
        params.append(season_year)
    if week:
        where += " AND pi.week = ?"
        params.append(week)
    return [dict(r) for r in conn.execute(f"""
        SELECT pi.id, pi.game_id, pi.player_id, pi.week, pi.season_year,
               pi.question, pi.context_packet, pi.created_at,
               p.first_name || ' ' || p.last_name AS player_name,
               t.city || ' ' || t.name AS team_name
        FROM player_interviews pi
        JOIN players p ON p.id = pi.player_id
        JOIN teams t ON t.id = p.team_id
        {where}
        ORDER BY pi.id DESC
    """, params).fetchall()]


def get_recent_interviews(conn, season_year, limit=20):
    """Return filled-in interview quotes, newest first."""
    return [dict(r) for r in conn.execute("""
        SELECT pi.id, pi.game_id, pi.player_id, pi.week, pi.season_year,
               pi.question, pi.response, pi.created_at,
               p.first_name || ' ' || p.last_name AS player_name,
               pb.personality_label,
               t.city || ' ' || t.name AS team_name,
               t.abbreviation
        FROM player_interviews pi
        JOIN players p ON p.id = pi.player_id
        JOIN teams t ON t.id = p.team_id
        LEFT JOIN player_backstories pb ON pb.player_id = pi.player_id
        WHERE pi.response IS NOT NULL AND pi.season_year = ?
        ORDER BY pi.id DESC
        LIMIT ?
    """, (season_year, limit)).fetchall()]


def interviews_for_player(conn, player_id, season_year, limit=10):
    """Return filled-in interview quotes for a specific player."""
    return [dict(r) for r in conn.execute("""
        SELECT pi.id, pi.game_id, pi.week, pi.question, pi.response,
               pi.created_at
        FROM player_interviews pi
        WHERE pi.player_id = ? AND pi.season_year = ?
          AND pi.response IS NOT NULL
        ORDER BY pi.id DESC
        LIMIT ?
    """, (player_id, season_year, limit)).fetchall()]


def parse_chatgpt_response(text):
    if not text.strip():
        return None, None

    raw_json = extract_marked_json(text, GPT_TO_APP_START, GPT_TO_APP_END)
    if not raw_json:
        return None, "No JSON block found. Paste the CHATGPT TO AIBA block or a raw JSON object."

    try:
        parsed = json.loads(raw_json)
    except json.JSONDecodeError as exc:
        return None, f"Could not parse JSON: {exc}"

    if parsed.get("schema") != CHATGPT_SCHEMA:
        return parsed, "Parsed, but the schema marker does not match this app."
    if parsed.get("direction") != "chatgpt_to_app":
        return parsed, "Parsed, but direction should be chatgpt_to_app."
    return parsed, None
