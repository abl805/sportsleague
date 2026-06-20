import contextlib
import io
import json
import random
import tempfile
import unittest
from pathlib import Path

from league import database
from league.fan_experience import (
    EDITORIAL_FROM_GPT_END,
    EDITORIAL_FROM_GPT_START,
    EDITORIAL_SCHEMA,
    cast_poll_vote,
    build_quarter_recaps,
    cool_rivalries_for_week,
    determine_injury_recovery_outcome,
    injury_recovery_probabilities,
    process_injury_comebacks,
    publish_weekly_editorial,
    refresh_draft_outcomes,
    refresh_hall_of_fame,
    refresh_record_book,
    record_game_rivalry,
    record_trade_rivalry,
    register_draft_profile,
    resolve_injury_consequence,
)
from league.simulation import build_coach_rotation, simulate_game
from league.offseason import advance_full_offseason, development_chances
import seed
from run_week import run_week
from web_app import app


class FanFirstIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = str(Path(self.temp_dir.name) / "league.db")
        with contextlib.redirect_stdout(io.StringIO()):
            seed.seed()

    def tearDown(self):
        self.temp_dir.cleanup()

    def run_one_week(self):
        with contextlib.redirect_stdout(io.StringIO()):
            run_week(verbose=False, start_official=False)

    def test_foundations_are_backfilled(self):
        conn = database.get_connection()
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM head_coaches").fetchone()[0], 8
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM player_arcs").fetchone()[0], 80
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM team_rivalries").fetchone()[0], 5
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM franchise_events
                    WHERE event_type='founding' AND season_year=2026
                    """
                ).fetchone()[0],
                8,
            )
            flagstaff = conn.execute(
                "SELECT team_archetype, fan_pitch FROM teams WHERE abbreviation='FLG'"
            ).fetchone()
            self.assertEqual(flagstaff["team_archetype"], "The Empire")
            self.assertIn("dominance", flagstaff["fan_pitch"])
            traits = conn.execute(
                "SELECT leadership, clutch, durability, media_reputation FROM player_personalities LIMIT 1"
            ).fetchone()
            self.assertTrue(all(0.0 < traits[key] < 1.0 for key in traits.keys()))
        finally:
            conn.close()

    def test_draft_verdicts_and_hall_of_fame_are_automatic(self):
        conn = database.get_connection()
        try:
            player = conn.execute(
                "SELECT * FROM players ORDER BY skill_rating ASC LIMIT 1"
            ).fetchone()
            register_draft_profile(
                conn,
                player["id"],
                player["team_id"],
                2024,
                1,
                player["skill_rating"] + 5,
            )
            conn.execute(
                """
                UPDATE players SET status='retired', retired_season=2026
                WHERE id=?
                """,
                (player["id"],),
            )
            for year, award_type in (
                (2024, "mvp"),
                (2025, "all_league"),
                (2026, "finals_mvp"),
            ):
                conn.execute(
                    """
                    INSERT INTO awards
                        (season_year, week, award_type, entity_type,
                         entity_id, label, detail)
                    VALUES (?, 0, ?, 'player', ?, 'Major honor', 'Test honor')
                    """,
                    (year, award_type, player["id"]),
                )
            refresh_draft_outcomes(conn, 2026)
            refresh_hall_of_fame(conn, 2026)
            verdict = conn.execute(
                "SELECT outcome_label FROM draft_profiles WHERE player_id=?",
                (player["id"],),
            ).fetchone()
            self.assertEqual(verdict["outcome_label"], "draft_bust")
            self.assertIsNotNone(
                conn.execute(
                    "SELECT id FROM hall_of_fame WHERE player_id=?",
                    (player["id"],),
                ).fetchone()
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM history_events
                    WHERE event_type='hall_of_fame' AND player_id=?
                    """,
                    (player["id"],),
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_rivalries_escalate_cool_and_remember_playoffs_and_trades(self):
        conn = database.get_connection()
        try:
            game_row = conn.execute("""
                SELECT g.*, ht.abbreviation AS home_abbr,
                       at.abbreviation AS away_abbr,
                       ht.city || ' ' || ht.name AS home_name,
                       at.city || ' ' || at.name AS away_name
                FROM games g
                JOIN teams ht ON ht.id=g.home_team_id
                JOIN teams at ON at.id=g.away_team_id
                ORDER BY g.id LIMIT 1
            """).fetchone()
            game = dict(game_row)
            pair = tuple(sorted((game["home_team_id"], game["away_team_id"])))

            close_context = {
                "home_score": 101,
                "away_score": 99,
                "home_win_probability": 0.56,
            }
            close_heat = record_game_rivalry(conn, game, close_context)
            self.assertGreater(close_heat, 0.18)

            blowout_context = {
                "home_score": 128,
                "away_score": 92,
                "home_win_probability": 0.78,
            }
            blowout_heat = record_game_rivalry(conn, game, blowout_context)
            self.assertLess(blowout_heat, close_heat)

            conn.execute(
                """
                UPDATE team_rivalries SET last_week=1, last_season=2026
                WHERE team_a_id=? AND team_b_id=?
                """,
                pair,
            )
            before_cooling = conn.execute(
                """
                SELECT current_intensity FROM team_rivalries
                WHERE team_a_id=? AND team_b_id=?
                """,
                pair,
            ).fetchone()["current_intensity"]
            cool_rivalries_for_week(conn, 4, 2026)
            after_cooling = conn.execute(
                """
                SELECT current_intensity FROM team_rivalries
                WHERE team_a_id=? AND team_b_id=?
                """,
                pair,
            ).fetchone()["current_intensity"]
            self.assertLess(after_cooling, before_cooling)

            series = conn.execute(
                """
                INSERT INTO playoff_series
                    (season_year, round, series_type, seed_a, seed_b,
                     team_a_id, team_b_id)
                VALUES (2026, 2, 'finals', 1, 2, ?, ?)
                RETURNING id
                """,
                pair,
            ).fetchone()
            playoff_game = dict(game)
            playoff_game["id"] = conn.execute(
                """
                INSERT INTO games
                    (home_team_id, away_team_id, week, season_year,
                     playoff_series_id, home_score, away_score, played)
                VALUES (?, ?, 20, 2026, ?, 105, 103, 1)
                RETURNING id
                """,
                (game["home_team_id"], game["away_team_id"], series["id"]),
            ).fetchone()["id"]
            playoff_game["week"] = 20
            playoff_game["playoff_series_id"] = series["id"]
            before_playoff = after_cooling
            playoff_heat = record_game_rivalry(
                conn,
                playoff_game,
                {
                    "home_score": 105,
                    "away_score": 103,
                    "home_win_probability": 0.52,
                },
            )
            self.assertGreater(playoff_heat - before_playoff, 0.18)

            gm_ids = [
                row["id"] for row in conn.execute(
                    "SELECT id FROM general_managers ORDER BY id LIMIT 2"
                ).fetchall()
            ]
            trade_id = conn.execute(
                """
                INSERT INTO pending_trades
                    (week, season_year, proposing_gm_id, receiving_gm_id,
                     offered_player_ids, requested_player_ids)
                VALUES (21, 2026, ?, ?, '[]', '[]')
                RETURNING id
                """,
                gm_ids,
            ).fetchone()["id"]
            trade_heat = record_trade_rivalry(
                conn,
                pair[0],
                pair[1],
                2026,
                21,
                trade_id=trade_id,
                star_involved=True,
            )
            self.assertGreater(trade_heat, playoff_heat)
            rivalry = conn.execute(
                """
                SELECT meetings, close_games, playoff_meetings, trade_count
                FROM team_rivalries WHERE team_a_id=? AND team_b_id=?
                """,
                pair,
            ).fetchone()
            self.assertEqual(rivalry["meetings"], 3)
            self.assertEqual(rivalry["close_games"], 2)
            self.assertEqual(rivalry["playoff_meetings"], 1)
            self.assertEqual(rivalry["trade_count"], 1)
        finally:
            conn.close()

    def test_week_creates_explanations_award_poll_and_editorial(self):
        self.run_one_week()
        conn = database.get_connection()
        try:
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM game_explanations").fetchone()[0], 4
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM team_game_stats").fetchone()[0], 8
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM game_rotations").fetchone()[0], 8
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM game_broadcasts").fetchone()[0], 4
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM (
                        SELECT scope, stat_key
                        FROM record_book_entries
                        WHERE is_current=1
                        GROUP BY scope, stat_key
                    ) records
                    """
                ).fetchone()[0],
                15,
            )
            broadcasts = conn.execute(
                """
                SELECT gb.*, g.q1_home, g.q2_home, g.q3_home, g.q4_home,
                       g.q1_away, g.q2_away, g.q3_away, g.q4_away
                FROM game_broadcasts gb JOIN games g ON g.id=gb.game_id
                """
            ).fetchall()
            for row in broadcasts:
                recaps = json.loads(row["quarter_recaps_json"])
                self.assertEqual(len(recaps), 4)
                self.assertEqual(
                    sum(item["home_points"] for item in recaps),
                    sum(row[f"q{quarter}_home"] for quarter in range(1, 5)),
                )
                self.assertEqual(
                    sum(item["away_points"] for item in recaps),
                    sum(row[f"q{quarter}_away"] for quarter in range(1, 5)),
                )
                self.assertEqual(row["generated_before_tip"], 1)
            rotation_totals = conn.execute("""
                SELECT game_id, team_id, SUM(minutes) AS minutes,
                       SUM(started) AS starters
                FROM player_game_stats
                GROUP BY game_id, team_id
            """).fetchall()
            self.assertEqual(len(rotation_totals), 8)
            self.assertTrue(
                all(row["minutes"] == 240 for row in rotation_totals)
            )
            self.assertTrue(
                all(row["starters"] == 5 for row in rotation_totals)
            )
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM awards").fetchone()[0], 1)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM polls").fetchone()[0], 1)
            package = conn.execute(
                "SELECT * FROM weekly_editorial_packages"
            ).fetchone()
            self.assertEqual(package["status"], "ready")
            self.assertIn(EDITORIAL_SCHEMA, package["prompt_text"])
        finally:
            conn.close()

    def test_record_book_detects_a_new_holder_and_preserves_lineage(self):
        self.run_one_week()
        conn = database.get_connection()
        try:
            current = conn.execute(
                """
                SELECT player_id, value FROM record_book_entries
                WHERE scope='single_game' AND stat_key='points'
                  AND is_current=1
                ORDER BY value DESC LIMIT 1
                """
            ).fetchone()
            challenger = conn.execute(
                """
                SELECT pgs.id, pgs.player_id, g.season_year, g.week, g.id AS game_id
                FROM player_game_stats pgs
                JOIN games g ON g.id=pgs.game_id
                WHERE pgs.player_id<>?
                ORDER BY pgs.id LIMIT 1
                """,
                (current["player_id"],),
            ).fetchone()
            new_value = current["value"] + 7
            conn.execute(
                "UPDATE player_game_stats SET points=? WHERE id=?",
                (new_value, challenger["id"]),
            )
            changes = refresh_record_book(
                conn, challenger["season_year"], challenger["week"], announce=True
            )
            holder = conn.execute(
                """
                SELECT * FROM record_book_entries
                WHERE scope='single_game' AND stat_key='points'
                  AND is_current=1
                """
            ).fetchall()
            self.assertEqual(len(holder), 1)
            self.assertEqual(holder[0]["player_id"], challenger["player_id"])
            self.assertEqual(holder[0]["value"], new_value)
            self.assertTrue(
                any(
                    item["scope"] == "single_game"
                    and item["stat_key"] == "points"
                    for item in changes
                )
            )
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM history_events
                    WHERE event_type='record_broken'
                      AND player_id=? AND game_id=?
                    """,
                    (challenger["player_id"], challenger["game_id"]),
                ).fetchone()[0],
                1,
            )
            self.assertGreaterEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM record_book_entries
                    WHERE scope='single_game' AND stat_key='points'
                      AND is_current=0
                    """
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_major_injury_can_permanently_change_a_career(self):
        conn = database.get_connection()
        try:
            player = conn.execute(
                """
                SELECT p.*, pp.durability
                FROM players p
                JOIN player_personalities pp ON pp.player_id=p.id
                ORDER BY p.skill_rating DESC LIMIT 1
                """
            ).fetchone()
            injury_id = conn.execute(
                """
                INSERT INTO player_injuries
                    (player_id, season_year, week_start, expected_return_week,
                     severity, status, skill_penalty, description)
                VALUES (?, 2026, 1, 4, 'major', 'resolved', 100,
                        'A significant knee injury changed the season.')
                RETURNING id
                """,
                (player["id"],),
            ).fetchone()["id"]
            consequence = resolve_injury_consequence(
                conn,
                {
                    "id": injury_id,
                    "player_id": player["id"],
                    "season_year": 2026,
                    "week_start": 1,
                    "severity": "major",
                    "description": "A significant knee injury changed the season.",
                },
                2026,
                5,
                roll=0.0,
                severity_roll=0.8,
            )
            updated = conn.execute(
                """
                SELECT p.skill_rating, pp.durability, pa.arc_type
                FROM players p
                JOIN player_personalities pp ON pp.player_id=p.id
                LEFT JOIN player_arcs pa ON pa.player_id=p.id
                WHERE p.id=?
                """,
                (player["id"],),
            ).fetchone()
            self.assertEqual(consequence["outcome_type"], "career_altering")
            self.assertLess(updated["skill_rating"], player["skill_rating"])
            self.assertLess(updated["durability"], player["durability"])
            self.assertEqual(updated["arc_type"], "career_altered")
            self.assertEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM history_events
                    WHERE event_type='career_altering_injury' AND player_id=?
                    """,
                    (player["id"],),
                ).fetchone()[0],
                1,
            )
        finally:
            conn.close()

    def test_comeback_performance_can_restore_bounded_skill(self):
        self.run_one_week()
        conn = database.get_connection()
        try:
            player = conn.execute(
                """
                SELECT p.*, pp.durability, pp.work_ethic,
                       COALESCE(hc.development, 0.5) AS coach_development
                FROM players p
                JOIN player_personalities pp ON pp.player_id=p.id
                LEFT JOIN head_coaches hc
                  ON hc.team_id=p.team_id AND hc.status='active'
                WHERE p.id IN (
                    SELECT player_id FROM player_game_stats pgs
                    JOIN games g ON g.id=pgs.game_id
                    WHERE g.week=1 AND g.season_year=2026
                )
                ORDER BY p.skill_rating DESC LIMIT 1
                """
            ).fetchone()
            probabilities = injury_recovery_probabilities(
                "major", player["age"], player["durability"],
                player["work_ethic"], player["coach_development"],
            )
            comeback_roll = (
                probabilities["career_altering"]
                + probabilities["lingering_decline"]
                + probabilities["comeback_path"] * 0.5
            )
            injury_id = conn.execute(
                """
                INSERT INTO player_injuries
                    (player_id, season_year, week_start, expected_return_week,
                     severity, status, skill_penalty, description)
                VALUES (?, 2026, 1, 1, 'major', 'resolved', 100,
                        'A major injury opened a comeback chapter.')
                RETURNING id
                """,
                (player["id"],),
            ).fetchone()["id"]
            consequence = resolve_injury_consequence(
                conn,
                {
                    "id": injury_id,
                    "player_id": player["id"],
                    "season_year": 2026,
                    "week_start": 1,
                    "severity": "major",
                    "description": "A major injury opened a comeback chapter.",
                },
                2026,
                1,
                roll=comeback_roll,
                severity_roll=0.1,
            )
            self.assertEqual(consequence["outcome_type"], "comeback_path")
            conn.commit()
            app.config.update(TESTING=True)
            with app.test_client() as client:
                response = client.get(f"/players/{player['id']}")
                self.assertEqual(response.status_code, 200)
                self.assertIn(b"Active rehabilitation arc", response.data)
            reduced_skill = conn.execute(
                "SELECT skill_rating FROM players WHERE id=?",
                (player["id"],),
            ).fetchone()["skill_rating"]
            conn.execute(
                """
                UPDATE injury_consequences
                SET recovery_points=1, target_points=1
                WHERE id=?
                """,
                (consequence["id"],),
            )
            updates = process_injury_comebacks(conn, 1, 2026)
            restored_skill = conn.execute(
                "SELECT skill_rating FROM players WHERE id=?",
                (player["id"],),
            ).fetchone()["skill_rating"]
            refreshed = conn.execute(
                "SELECT * FROM injury_consequences WHERE id=?",
                (consequence["id"],),
            ).fetchone()
            self.assertEqual(restored_skill, reduced_skill + 1)
            self.assertEqual(refreshed["skill_restored"], 1)
            self.assertEqual(refreshed["comeback_status"], "complete")
            self.assertTrue(
                any(item["player_id"] == player["id"] for item in updates)
            )
        finally:
            conn.close()

    def test_editorial_import_is_validated_and_idempotent(self):
        self.run_one_week()
        conn = database.get_connection()
        try:
            package = dict(conn.execute(
                "SELECT * FROM weekly_editorial_packages"
            ).fetchone())
            source = json.loads(package["source_json"])
            game = source["games"][0]
            player = source["week_players"][0]
            response = {
                "schema": EDITORIAL_SCHEMA,
                "direction": "chatgpt_to_aiba",
                "package_id": package["id"],
                "season_year": package["season_year"],
                "week": package["week"],
                "stories": [{
                    "role": "lead",
                    "headline": "Week 1 Draws the First Battle Lines",
                    "body": game["factual_recap"],
                    "game_ids": [game["id"]],
                    "team_ids": [game["home_team_id"], game["away_team_id"]],
                    "player_ids": [player["player_id"]],
                }],
                "quotes": [{
                    "speaker_type": "player",
                    "speaker_id": player["player_id"],
                    "game_id": player["game_id"],
                    "quote": "We set a standard, but one week is not enough.",
                }],
                "game_of_week": "The next featured matchup.",
                "mvp_commentary": "The race is open.",
                "hot_team": str(player["team_id"]),
                "cold_team": "",
                "trade_or_rivalry_drama": "",
            }
            raw = (
                f"{EDITORIAL_FROM_GPT_START}\n"
                f"{json.dumps(response)}\n"
                f"{EDITORIAL_FROM_GPT_END}"
            )
            self.assertEqual(publish_weekly_editorial(conn, raw), (1, 1, False))
            self.assertEqual(publish_weekly_editorial(conn, raw), (0, 0, True))

            invalid = dict(response)
            invalid["package_id"] = 9999
            with self.assertRaises(ValueError):
                publish_weekly_editorial(conn, json.dumps(invalid))
        finally:
            conn.close()

    def test_poll_allows_one_vote_per_browser_hash(self):
        self.run_one_week()
        conn = database.get_connection()
        try:
            poll = conn.execute("SELECT id FROM polls").fetchone()
            option = conn.execute(
                "SELECT id FROM poll_options WHERE poll_id=? LIMIT 1", (poll["id"],)
            ).fetchone()
            cast_poll_vote(conn, poll["id"], option["id"], "browser-a")
            with self.assertRaises(ValueError):
                cast_poll_vote(conn, poll["id"], option["id"], "browser-a")
        finally:
            conn.close()

    def test_poll_rotation_and_permanent_fan_results(self):
        expected_types = [
            "fan_player_of_week",
            "fan_game_of_week",
            "fan_confidence",
            "rivalry_name",
            "award_name",
        ]
        observed = []
        for index, expected in enumerate(expected_types, start=1):
            self.run_one_week()
            conn = database.get_connection()
            try:
                poll = conn.execute(
                    "SELECT * FROM polls WHERE status='open' ORDER BY id DESC LIMIT 1"
                ).fetchone()
                observed.append(poll["poll_type"])
                self.assertEqual(poll["poll_type"], expected)
                option = conn.execute(
                    "SELECT id FROM poll_options WHERE poll_id=? ORDER BY sort_order LIMIT 1",
                    (poll["id"],),
                ).fetchone()
                cast_poll_vote(
                    conn, poll["id"], option["id"], f"rotation-browser-{index}"
                )
            finally:
                conn.close()

        self.run_one_week()  # Finalizes the Week 5 award-name poll.
        conn = database.get_connection()
        try:
            self.assertEqual(observed, expected_types)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM polls WHERE status='closed' AND winner_option_id IS NOT NULL"
                ).fetchone()[0],
                5,
            )
            award_types = {
                row["award_type"]
                for row in conn.execute(
                    "SELECT award_type FROM awards WHERE award_type LIKE 'fan_%'"
                ).fetchall()
            }
            self.assertIn("fan_player_of_week", award_types)
            self.assertIn("fan_game_of_week", award_types)
            self.assertIn("fan_confidence", award_types)
            self.assertIn("fan_named_effort", award_types)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM rivalry_names WHERE status='active'"
                ).fetchone()[0],
                1,
            )
            label = conn.execute(
                """
                SELECT label FROM fan_labels
                WHERE label_type='weekly_effort_award_name' AND status='active'
                """
            ).fetchone()
            self.assertIsNotNone(label)
        finally:
            conn.close()

    def test_public_pages_render_after_a_week(self):
        self.run_one_week()
        app.config.update(TESTING=True)
        with app.test_client() as client:
            for route in (
                "/",
                "/live-league",
                "/teams",
                "/teams/FLG",
                "/players/1",
                "/games/1",
                "/news",
                "/history",
            ):
                response = client.get(route)
                self.assertEqual(response.status_code, 200, route)
            game_page = client.get("/games/1")
            self.assertIn(b"rotation", game_page.data.lower())
            self.assertIn(b"<th>MIN</th>", game_page.data)
            self.assertIn(b"START", game_page.data)
            self.assertIn(b"Before tipoff", game_page.data)
            self.assertIn(b"How the game unfolded", game_page.data)
            team_page = client.get("/teams/FLG")
            self.assertIn(b"Lineup", team_page.data)
            self.assertIn(b"Development", team_page.data)
            conn = database.get_connection()
            try:
                upcoming_id = conn.execute(
                    "SELECT id FROM games WHERE played=0 ORDER BY week, id LIMIT 1"
                ).fetchone()["id"]
            finally:
                conn.close()
            upcoming_page = client.get(f"/games/{upcoming_id}")
            self.assertIn(b"Broadcast setup", upcoming_page.data)
            self.assertNotIn(b"How the game unfolded", upcoming_page.data)
            history_page = client.get("/history")
            self.assertIn(b"Record book", history_page.data)
            self.assertIn(b"Single-game records", history_page.data)
            self.assertIn(b"League lore", history_page.data)
            self.assertIn(b"Draft verdicts", history_page.data)
            self.assertIn(b"Franchise timeline", history_page.data)
            conn = database.get_connection()
            try:
                record_holder = conn.execute(
                    """
                    SELECT player_id FROM record_book_entries
                    WHERE is_current=1 ORDER BY id LIMIT 1
                    """
                ).fetchone()["player_id"]
            finally:
                conn.close()
            record_holder_page = client.get(f"/players/{record_holder}")
            self.assertIn(b"Current record", record_holder_page.data)

    def test_complete_season_rolls_into_persistent_next_year(self):
        for _ in range(30):
            conn = database.get_connection()
            phase = conn.execute(
                "SELECT phase FROM league_state WHERE id=1"
            ).fetchone()["phase"]
            conn.close()
            if phase == "complete":
                break
            self.run_one_week()
        conn = database.get_connection()
        try:
            self.assertEqual(
                conn.execute("SELECT phase FROM league_state WHERE id=1").fetchone()["phase"],
                "complete",
            )
            player = conn.execute(
                """
                SELECT p.id, p.skill_rating
                FROM players p
                WHERE COALESCE(p.status, 'active')='active'
                ORDER BY p.age, p.id LIMIT 1
                """
            ).fetchone()
            injury_id = conn.execute(
                """
                INSERT INTO player_injuries
                    (player_id, season_year, week_start, expected_return_week,
                     severity, status, skill_penalty, description)
                VALUES (?, 2026, 28, 28, 'major', 'resolved', 100,
                        'A late-season major injury created a long recovery.')
                RETURNING id
                """,
                (player["id"],),
            ).fetchone()["id"]
            consequence = resolve_injury_consequence(
                conn,
                {
                    "id": injury_id,
                    "player_id": player["id"],
                    "season_year": 2026,
                    "week_start": 28,
                    "severity": "major",
                    "description": "A late-season major injury created a long recovery.",
                },
                2026,
                29,
                roll=0.0,
                severity_roll=0.4,
            )
            with contextlib.redirect_stdout(io.StringIO()):
                summaries = advance_full_offseason(conn, verbose=False)
            state = conn.execute("SELECT * FROM league_state WHERE id=1").fetchone()
            self.assertEqual(state["season_year"], 2027)
            self.assertEqual(state["phase"], "regular_season")
            self.assertEqual(len(summaries), 7)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM games WHERE season_year=2027"
                ).fetchone()[0],
                56,
            )
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM season_snapshots").fetchone()[0],
                1,
            )
            self.assertGreaterEqual(
                conn.execute(
                    """
                    SELECT COUNT(*) FROM playoff_run_summaries
                    WHERE season_year=2026
                    """
                ).fetchone()[0],
                4,
            )
            snapshot = json.loads(
                conn.execute(
                    "SELECT snapshot_json FROM season_snapshots WHERE season_year=2026"
                ).fetchone()["snapshot_json"]
            )
            self.assertEqual(len({
                (row["scope"], row["stat_key"])
                for row in snapshot["records"]
            }), 15)
            self.assertEqual(
                conn.execute(
                    "SELECT COUNT(*) FROM record_book_entries WHERE is_current=1"
                ).fetchone()[0] >= 15,
                True,
            )
            persisted = conn.execute(
                "SELECT * FROM injury_consequences WHERE id=?",
                (consequence["id"],),
            ).fetchone()
            self.assertIsNotNone(persisted)
            self.assertEqual(persisted["outcome_type"], "career_altering")
        finally:
            conn.close()


class SimulationCalibrationTests(unittest.TestCase):
    @staticmethod
    def roster(skill, team_id):
        positions = ["PG", "SG", "SF", "PF", "C"]
        return [
            {
                "id": team_id * 100 + index,
                "team_id": team_id,
                "position": positions[index % 5],
                "skill_rating": skill,
                "clutch": 0.6,
            }
            for index in range(10)
        ]

    def sample_win_rate(self, favorite_skill, underdog_skill, games=600):
        random.seed(1337)
        wins = 0
        for _ in range(games):
            result = simulate_game(
                self.roster(favorite_skill, 1),
                self.roster(underdog_skill, 2),
                70,
                70,
                home_morale=70,
                away_morale=70,
            )
            wins += result[0] > result[1]
        return wins / games

    def test_favorite_bands_remain_bounded(self):
        toss_up = self.sample_win_rate(70, 70)
        moderate = self.sample_win_rate(78, 70)
        large = self.sample_win_rate(85, 70)
        self.assertGreaterEqual(toss_up, 0.52)
        self.assertLessEqual(toss_up, 0.65)
        self.assertGreaterEqual(moderate, 0.60)
        self.assertLessEqual(moderate, 0.76)
        self.assertGreaterEqual(large, 0.75)
        self.assertLessEqual(large, 0.86)

    def test_rotation_tightness_controls_depth_and_minutes(self):
        roster = self.roster(74, 1)
        for index, player in enumerate(roster):
            player["age"] = 23 + index
            player["work_ethic"] = 0.55
            player["leadership"] = 0.5
        tight, tight_plan = build_coach_rotation(
            roster,
            {
                "name": "Tight Coach",
                "strategy": "precision_balance",
                "lineup_preference": "balanced_best_five",
                "rotation_tightness": 0.85,
            },
        )
        deep, deep_plan = build_coach_rotation(
            roster,
            {
                "name": "Deep Coach",
                "strategy": "precision_balance",
                "lineup_preference": "balanced_best_five",
                "rotation_tightness": 0.20,
            },
        )
        self.assertEqual(tight_plan["rotation_size"], 7)
        self.assertEqual(deep_plan["rotation_size"], 10)
        self.assertEqual(sum(player["minutes"] for player in tight), 240)
        self.assertEqual(sum(player["minutes"] for player in deep), 240)
        self.assertEqual(sum(player["started"] for player in tight), 5)
        self.assertEqual(sum(player["started"] for player in deep), 5)
        self.assertGreater(
            sum(player["minutes"] for player in tight if player["started"]),
            sum(player["minutes"] for player in deep if player["started"]),
        )

    def test_lineup_preferences_can_change_a_close_selection(self):
        roster = self.roster(72, 1)
        for index, player in enumerate(roster):
            player["age"] = 28
            player["work_ethic"] = 0.5
            player["leadership"] = 0.5
        roster[0].update(skill_rating=80, age=34, work_ethic=0.5)
        roster[5].update(skill_rating=78, age=21, work_ethic=0.9)
        balanced, _ = build_coach_rotation(
            roster,
            {
                "lineup_preference": "balanced_best_five",
                "rotation_tightness": 0.5,
            },
        )
        youth, _ = build_coach_rotation(
            roster,
            {
                "lineup_preference": "youth_and_upside",
                "rotation_tightness": 0.5,
            },
        )
        balanced_pg = next(
            player for player in balanced
            if player["position"] == "PG" and player["started"]
        )
        youth_pg = next(
            player for player in youth
            if player["position"] == "PG" and player["started"]
        )
        self.assertEqual(balanced_pg["id"], roster[0]["id"])
        self.assertEqual(youth_pg["id"], roster[5]["id"])

    def test_development_coaching_is_bounded_and_age_sensitive(self):
        young_low = development_chances(22, 70, 0.65, 0.25, 0.45)
        young_high = development_chances(22, 70, 0.65, 0.92, 0.82)
        veteran_low = development_chances(35, 60, 0.60, 0.25, 0.40)
        veteran_high = development_chances(35, 60, 0.60, 0.92, 0.88)
        self.assertGreater(young_high[0], young_low[0])
        self.assertLess(veteran_high[1], veteran_low[1])
        for chance in (*young_low, *young_high, *veteran_low, *veteran_high):
            self.assertGreaterEqual(chance, 0.01)
            self.assertLessEqual(chance, 0.82)

    def test_quarter_recaps_match_scores_and_detect_a_comeback(self):
        game = {
            "home_name": "Home Club",
            "away_name": "Away Club",
        }
        recaps = build_quarter_recaps(
            game,
            [18, 22, 30, 31],
            [29, 24, 20, 22],
        )
        self.assertEqual(len(recaps), 4)
        self.assertEqual(recaps[-1]["home_total"], 101)
        self.assertEqual(recaps[-1]["away_total"], 95)
        self.assertIn("completed the comeback", recaps[-1]["text"])

    def test_injury_recovery_odds_reward_resilience_but_remain_bounded(self):
        low = injury_recovery_probabilities(
            "major", age=34, durability=0.38,
            work_ethic=0.35, coach_development=0.35,
        )
        high = injury_recovery_probabilities(
            "major", age=24, durability=0.90,
            work_ethic=0.92, coach_development=0.92,
        )
        self.assertGreater(
            low["career_altering"],
            high["career_altering"],
        )
        self.assertGreater(
            high["comeback_path"] + high["full_recovery"],
            low["comeback_path"] + low["full_recovery"],
        )
        self.assertAlmostEqual(sum(low.values()), 1.0)
        self.assertAlmostEqual(sum(high.values()), 1.0)


if __name__ == "__main__":
    unittest.main()
