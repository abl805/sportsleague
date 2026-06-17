"""
League dashboard — run with:  streamlit run app.py
"""
import hashlib
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pandas as pd
import streamlit as st

from league.database import create_tables, get_connection

st.set_page_config(page_title="Basketball League", page_icon="🏀", layout="wide")

# ── helpers ───────────────────────────────────────────────────────────────────

def db():
    return get_connection()


def fmt_salary(n):
    return f"${n / 1_000_000:.1f}M"


def fmt_diff(n):
    return f"+{n}" if n > 0 else str(n)


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


def get_team_options():
    conn = db()
    rows = conn.execute(
        "SELECT id, city || ' ' || name AS label FROM teams ORDER BY city"
    ).fetchall()
    conn.close()
    return {row["label"]: row["id"] for row in rows}


def get_pending_trade_options():
    conn = db()
    rows = conn.execute("""
        SELECT pt.id,
               pgm.name AS proposer_gm,
               rgm.name AS receiver_gm,
               pt.week,
               pt.status,
               pt.proposing_score,
               pt.receiving_score,
               pt.offered_player_ids,
               pt.requested_player_ids,
               pteam.city || ' ' || pteam.name AS proposing_team,
               rteam.city || ' ' || rteam.name AS receiving_team
        FROM pending_trades pt
        JOIN general_managers pgm ON pgm.id = pt.proposing_gm_id
        JOIN general_managers rgm ON rgm.id = pt.receiving_gm_id
        JOIN teams pteam ON pteam.id = pgm.team_id
        JOIN teams rteam ON rteam.id = rgm.team_id
        WHERE pt.status = 'pending'
        ORDER BY pt.week, pt.id
    """).fetchall()
    conn.close()

    options = {}
    for row in rows:
        label = (
            f"Trade #{row['id']} - Week {row['week']}: "
            f"{row['proposing_team']} / {row['receiving_team']}"
        )
        options[label] = row["id"]
    return options


def league_snapshot_context(conn, season_year):
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

    return {
        "standings": standings,
        "stat_leaders": leaders,
        "recent_games": recent_games,
        "pending_trade_count": pending_trade_count,
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
    conn = db()
    state_row = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
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

    payload = {
        "schema": CHATGPT_SCHEMA,
        "direction": "app_to_chatgpt",
        "context_type": context_type,
        "commissioner_request": commissioner_request.strip(),
        "league_state": {
            "season_year": packet_season,
            "current_week": packet_week,
        },
        "instructions_for_chatgpt": [
            "Read the packet as source-of-truth league data.",
            "Answer the commissioner request without inventing missing stats.",
            "Return a JSON packet inside the CHATGPT TO AIBA markers.",
            "Use short, app-readable strings in summary, recommendations, suggested_actions, questions, and notes_for_commissioner.",
        ],
        "response_contract": {
            "schema": CHATGPT_SCHEMA,
            "direction": "chatgpt_to_app",
            "response_type": context_type,
            "summary": "One short paragraph.",
            "recommendations": ["Recommendation strings."],
            "suggested_actions": ["Action strings the commissioner may take manually."],
            "questions": ["Optional clarification questions."],
            "notes_for_commissioner": ["Optional caveats or narrative hooks."],
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


def render_list_items(items):
    if isinstance(items, str):
        items = [items]
    for item in items or []:
        st.markdown(f"- {item}")


# ── load league state ─────────────────────────────────────────────────────────

create_tables()

conn = db()
state = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
conn.close()

if not state:
    st.error("League not found — run `python seed.py` first.")
    st.stop()

current_week = state["current_week"]
season_year  = state["season_year"]
last_played  = current_week - 1

# ── header ────────────────────────────────────────────────────────────────────

st.title("🏀 Basketball League")
c1, c2, c3 = st.columns(3)
c1.metric("Season", season_year)
c2.metric("Current Week", current_week)
conn = db()
games_played = conn.execute(
    "SELECT COUNT(*) FROM games WHERE played=1 AND season_year=?", (season_year,)
).fetchone()[0]
conn.close()
c3.metric("Games Played", games_played)

st.divider()

# ── tabs ──────────────────────────────────────────────────────────────────────

tab_standings, tab_teams, tab_results, tab_box, tab_players, tab_chatgpt = st.tabs(
    ["📊 Standings", "Teams", "🎯 Results", "📋 Box Scores", "👤 Players", "ChatGPT"]
)

# ═══════════════════════════════════════════════════════════════════════════════
# STANDINGS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_standings:
    st.subheader(f"{season_year} Standings")

    conn = db()
    rows = conn.execute("""
        SELECT t.city || ' ' || t.name AS Team,
               t.abbreviation          AS Abbr,
               s.wins                  AS W,
               s.losses                AS L,
               s.points_for            AS PF,
               s.points_against        AS PA,
               s.points_for - s.points_against AS Diff
        FROM standings s
        JOIN teams t ON s.team_id = t.id
        WHERE s.season_year = ?
        ORDER BY s.wins DESC, (s.points_for - s.points_against) DESC
    """, (season_year,)).fetchall()
    conn.close()

    if rows:
        df = pd.DataFrame([dict(r) for r in rows])
        df.insert(0, "#", range(1, len(df) + 1))
        df["Diff"] = df["Diff"].apply(fmt_diff)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("No standings yet — simulate some weeks first.")

    if games_played > 0:
        st.subheader("🌟 Season Leaders")
        conn = db()
        leaders = conn.execute("""
            SELECT p.first_name || ' ' || p.last_name AS Player,
                   t.abbreviation                      AS Team,
                   p.position                          AS Pos,
                   ROUND(AVG(pgs.points),   1)         AS PPG,
                   ROUND(AVG(pgs.rebounds), 1)         AS RPG,
                   ROUND(AVG(pgs.assists),  1)         AS APG,
                   COUNT(pgs.id)                       AS GP
            FROM player_game_stats pgs
            JOIN games g ON pgs.game_id = g.id
            JOIN players p ON pgs.player_id = p.id
            JOIN teams   t ON p.team_id = t.id
            WHERE g.season_year = ?
            GROUP BY p.id
            HAVING GP >= 1
            ORDER BY PPG DESC
            LIMIT 15
        """, (season_year,)).fetchall()
        conn.close()

        ldf = pd.DataFrame([dict(r) for r in leaders])
        ldf.insert(0, "#", range(1, len(ldf) + 1))
        st.dataframe(ldf, use_container_width=True, hide_index=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TEAMS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_teams:
    st.subheader("Teams")

    conn = db()
    rows = conn.execute("""
        SELECT city, name, abbreviation, mascot, colors, logo_description,
               motto, arena, team_archetype, play_style, reputation, rivalry,
               signature_trait
        FROM teams
        ORDER BY city
    """).fetchall()
    conn.close()

    if rows:
        for row in rows:
            team = dict(row)
            with st.container(border=True):
                left, right = st.columns([1, 2])
                with left:
                    st.markdown(f"### {team['city']} {team['name']}")
                    st.caption(team["abbreviation"])
                    if team["motto"]:
                        st.markdown(f"**Motto:** {team['motto']}")
                    if team["arena"]:
                        st.markdown(f"**Arena:** {team['arena']}")
                    if team["colors"]:
                        st.markdown(f"**Colors:** {team['colors']}")
                with right:
                    if team["play_style"]:
                        st.markdown(f"**Play style:** {team['play_style']}")
                    if team["mascot"]:
                        st.markdown(f"**Mascot:** {team['mascot']}")
                    if team["logo_description"]:
                        st.markdown(f"**Logo:** {team['logo_description']}")

                    details = []
                    for label, key in [
                        ("Archetype", "team_archetype"),
                        ("Reputation", "reputation"),
                        ("Rivalry", "rivalry"),
                        ("Signature trait", "signature_trait"),
                    ]:
                        value = team[key]
                        if value:
                            details.append(f"**{label}:** {value}")
                    if details:
                        st.markdown("  \n".join(details))
    else:
        st.info("No teams found.")


# ═══════════════════════════════════════════════════════════════════════════════
# RESULTS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_results:
    st.subheader("Game Results")

    if last_played < 1:
        st.info("No games played yet — run `python run_week.py` to simulate Week 1.")
    else:
        selected_week = st.selectbox(
            "Select week", range(1, last_played + 1), index=last_played - 1,
            format_func=lambda w: f"Week {w}"
        )

        conn = db()
        games = conn.execute("""
            SELECT g.id,
                   ht.city || ' ' || ht.name  AS home_name,
                   at.city || ' ' || at.name  AS away_name,
                   ht.abbreviation            AS home_abbr,
                   at.abbreviation            AS away_abbr,
                   g.home_score, g.away_score
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            WHERE g.week = ? AND g.season_year = ? AND g.played = 1
        """, (selected_week, season_year)).fetchall()
        conn.close()

        if not games:
            st.warning(f"No results for Week {selected_week}.")
        else:
            for g in games:
                home_won = g["home_score"] > g["away_score"]
                with st.container(border=True):
                    col_h, col_score, col_a = st.columns([3, 2, 3])
                    with col_h:
                        st.markdown(
                            f"**{'🏆 ' if home_won else ''}{g['home_name']}**"
                        )
                        st.caption("Home")
                    with col_score:
                        st.markdown(
                            f"<h2 style='text-align:center'>{g['home_score']} — {g['away_score']}</h2>",
                            unsafe_allow_html=True,
                        )
                    with col_a:
                        st.markdown(
                            f"**{'🏆 ' if not home_won else ''}{g['away_name']}**"
                        )
                        st.caption("Away")


# ═══════════════════════════════════════════════════════════════════════════════
# BOX SCORES
# ═══════════════════════════════════════════════════════════════════════════════
with tab_box:
    st.subheader("Box Scores")

    if last_played < 1:
        st.info("No games played yet.")
    else:
        week_choice = st.selectbox(
            "Week", range(1, last_played + 1), index=last_played - 1,
            format_func=lambda w: f"Week {w}", key="box_week"
        )

        conn = db()
        game_list = conn.execute("""
            SELECT g.id,
                   ht.city || ' ' || ht.name AS home_name,
                   at.city || ' ' || at.name AS away_name,
                   g.home_score, g.away_score
            FROM games g
            JOIN teams ht ON g.home_team_id = ht.id
            JOIN teams at ON g.away_team_id = at.id
            WHERE g.week = ? AND g.season_year = ? AND g.played = 1
        """, (week_choice, season_year)).fetchall()
        conn.close()

        if not game_list:
            st.warning(f"No games played in Week {week_choice}.")
        else:
            game_options = {
                g["id"]: f"{g['home_name']} {g['home_score']} — {g['away_score']} {g['away_name']}"
                for g in game_list
            }
            selected_game_id = st.selectbox(
                "Game", options=list(game_options.keys()),
                format_func=lambda gid: game_options[gid], key="box_game"
            )

            # Pull box score for both teams
            conn = db()
            box_rows = conn.execute("""
                SELECT p.first_name || ' ' || p.last_name AS Player,
                       t.city || ' ' || t.name            AS Team,
                       p.position                         AS Pos,
                       pgs.points                         AS PTS,
                       pgs.rebounds                       AS REB,
                       pgs.assists                        AS AST,
                       pgs.steals                         AS STL,
                       pgs.blocks                         AS BLK,
                       p.skill_rating                     AS OVR
                FROM player_game_stats pgs
                JOIN players p ON pgs.player_id = p.id
                JOIN teams   t ON p.team_id = t.id
                WHERE pgs.game_id = ?
                ORDER BY t.id, pgs.points DESC
            """, (selected_game_id,)).fetchall()
            conn.close()

            if box_rows:
                df = pd.DataFrame([dict(r) for r in box_rows])
                teams_in_game = df["Team"].unique()

                for team_name in teams_in_game:
                    st.markdown(f"**{team_name}**")
                    team_df = df[df["Team"] == team_name].drop(columns="Team").reset_index(drop=True)
                    team_df.index += 1
                    st.dataframe(team_df, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# PLAYERS
# ═══════════════════════════════════════════════════════════════════════════════
with tab_players:
    st.subheader("Player Rosters")

    conn = db()
    teams = conn.execute("SELECT id, city || ' ' || name AS name FROM teams ORDER BY city").fetchall()
    conn.close()

    team_options = {"All Teams": None} | {t["name"]: t["id"] for t in teams}
    selected_team = st.selectbox("Filter by team", list(team_options.keys()))
    team_id_filter = team_options[selected_team]

    conn = db()
    if team_id_filter:
        players = conn.execute("""
            SELECT p.first_name || ' ' || p.last_name AS Player,
                   t.abbreviation                      AS Team,
                   p.position                          AS Pos,
                   p.age                               AS Age,
                   p.skill_rating                      AS OVR,
                   p.salary                            AS Salary,
                   c.years_remaining                   AS Yrs
            FROM players p
            JOIN teams     t ON p.team_id = t.id
            LEFT JOIN contracts c ON c.player_id = p.id
            WHERE p.team_id = ? AND COALESCE(p.status, 'active') = 'active'
            ORDER BY p.skill_rating DESC
        """, (team_id_filter,)).fetchall()
    else:
        players = conn.execute("""
            SELECT p.first_name || ' ' || p.last_name AS Player,
                   t.abbreviation                      AS Team,
                   p.position                          AS Pos,
                   p.age                               AS Age,
                   p.skill_rating                      AS OVR,
                   p.salary                            AS Salary,
                   c.years_remaining                   AS Yrs
            FROM players p
            JOIN teams     t ON p.team_id = t.id
            LEFT JOIN contracts c ON c.player_id = p.id
            WHERE COALESCE(p.status, 'active') = 'active'
            ORDER BY p.skill_rating DESC
        """).fetchall()
    conn.close()

    if players:
        df = pd.DataFrame([dict(r) for r in players])
        df["Salary"] = df["Salary"].apply(fmt_salary)
        df.index += 1
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No players found.")


# ═══════════════════════════════════════════════════════════════════════════════
# CHATGPT MANUAL BRIDGE
# ═══════════════════════════════════════════════════════════════════════════════
with tab_chatgpt:
    st.subheader("Manual ChatGPT Exchange")

    st.markdown(
        """
        1. Pick the league context and write the commissioner request.
        2. Copy the app packet into ChatGPT.
        3. Ask ChatGPT to return the `CHATGPT TO AIBA` block.
        4. Paste that block back here to review it in app-readable sections.
        """
    )

    col_context, col_target = st.columns([1, 1])
    with col_context:
        context_type = st.radio(
            "Context to send",
            ["League snapshot", "Team report", "Pending trade review", "Commissioner note"],
            horizontal=False,
        )

    selected_team_id = None
    selected_trade_id = None
    with col_target:
        if context_type == "Team report":
            team_options = get_team_options()
            if team_options:
                team_label = st.selectbox("Team", list(team_options.keys()))
                selected_team_id = team_options[team_label]
            else:
                st.info("No teams found.")
        elif context_type == "Pending trade review":
            trade_options = get_pending_trade_options()
            if trade_options:
                trade_label = st.selectbox("Pending trade", list(trade_options.keys()))
                selected_trade_id = trade_options[trade_label]
            else:
                st.info("No pending trades found.")
        else:
            st.caption("The packet will use the selected context.")

    default_request = {
        "League snapshot": "Summarize the league state, identify the strongest storylines, and suggest what I should watch next.",
        "Team report": "Analyze this team like a GM advisor. Identify strengths, weaknesses, and one realistic next move.",
        "Pending trade review": "Review this trade for fairness, team fit, and narrative impact. Recommend approve, veto, or ask for revisions.",
        "Commissioner note": "Help me reason through this league decision and return a structured recommendation.",
    }[context_type]

    commissioner_request = st.text_area(
        "Commissioner request",
        value=default_request,
        height=110,
    )

    can_build_packet = (
        context_type not in {"Team report", "Pending trade review"}
        or selected_team_id is not None
        or selected_trade_id is not None
    )

    if can_build_packet:
        packet = build_chatgpt_packet(
            context_type,
            commissioner_request,
            team_id=selected_team_id,
            trade_id=selected_trade_id,
        )

        st.markdown("**Copy this to ChatGPT**")
        st.text_area(
            "App to ChatGPT packet",
            value=packet,
            height=420,
            key=f"app_to_chatgpt_{hash_text(packet)}",
            label_visibility="collapsed",
        )
        st.download_button(
            "Download packet",
            data=packet,
            file_name=f"aibl_chatgpt_packet_{hash_text(packet)}.txt",
            mime="text/plain",
        )

        with st.expander("Expected ChatGPT response shape"):
            template = response_template(context_type)
            st.text_area(
                "Response template",
                value=template,
                height=260,
                key=f"chatgpt_template_{hash_text(template)}",
                label_visibility="collapsed",
            )
    else:
        st.warning("Select a target before building the ChatGPT packet.")

    st.divider()
    st.markdown("**Paste ChatGPT's response here**")
    pasted_response = st.text_area(
        "ChatGPT to app packet",
        height=260,
        placeholder=f"{GPT_TO_APP_START}\n{{ ... }}\n{GPT_TO_APP_END}",
        label_visibility="collapsed",
    )

    parsed_response, parse_warning = parse_chatgpt_response(pasted_response)
    if parse_warning:
        st.warning(parse_warning)

    if parsed_response:
        st.markdown("**Parsed response**")
        if parsed_response.get("summary"):
            st.markdown(parsed_response["summary"])

        response_cols = st.columns(2)
        with response_cols[0]:
            st.markdown("**Recommendations**")
            render_list_items(parsed_response.get("recommendations"))

            st.markdown("**Suggested actions**")
            render_list_items(parsed_response.get("suggested_actions"))

        with response_cols[1]:
            st.markdown("**Questions**")
            render_list_items(parsed_response.get("questions"))

            st.markdown("**Notes**")
            render_list_items(parsed_response.get("notes_for_commissioner"))
