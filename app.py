"""
League dashboard — run with:  streamlit run app.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import pandas as pd
import streamlit as st

from league.database import get_connection

st.set_page_config(page_title="Basketball League", page_icon="🏀", layout="wide")

# ── helpers ───────────────────────────────────────────────────────────────────

def db():
    return get_connection()


def fmt_salary(n):
    return f"${n / 1_000_000:.1f}M"


def fmt_diff(n):
    return f"+{n}" if n > 0 else str(n)


# ── load league state ─────────────────────────────────────────────────────────

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

tab_standings, tab_results, tab_box, tab_players = st.tabs(
    ["📊 Standings", "🎯 Results", "📋 Box Scores", "👤 Players"]
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
            JOIN players p ON pgs.player_id = p.id
            JOIN teams   t ON p.team_id = t.id
            GROUP BY p.id
            HAVING GP >= 1
            ORDER BY PPG DESC
            LIMIT 15
        """).fetchall()
        conn.close()

        ldf = pd.DataFrame([dict(r) for r in leaders])
        ldf.insert(0, "#", range(1, len(ldf) + 1))
        st.dataframe(ldf, use_container_width=True, hide_index=True)


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
            WHERE p.team_id = ?
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
