import sqlite3
import os
import random

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "league.db")
LEAGUE_YEAR = 2026


def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def create_tables():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id          INTEGER PRIMARY KEY,
            city        TEXT NOT NULL,
            name        TEXT NOT NULL,
            abbreviation TEXT NOT NULL,
            mascot     TEXT,
            colors      TEXT,
            logo_description TEXT,
            motto       TEXT,
            arena       TEXT,
            team_archetype TEXT,
            play_style  TEXT,
            reputation  TEXT,
            rivalry     TEXT,
            signature_trait TEXT
        );

        CREATE TABLE IF NOT EXISTS players (
            id           INTEGER PRIMARY KEY,
            team_id      INTEGER NOT NULL REFERENCES teams(id),
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            age          INTEGER NOT NULL,
            position     TEXT NOT NULL,
            skill_rating INTEGER NOT NULL,
            salary       INTEGER NOT NULL,
            status       TEXT DEFAULT 'active',
            retired_season INTEGER
        );

        CREATE TABLE IF NOT EXISTS contracts (
            id             INTEGER PRIMARY KEY,
            player_id      INTEGER NOT NULL REFERENCES players(id),
            team_id        INTEGER NOT NULL REFERENCES teams(id),
            salary         INTEGER NOT NULL,
            years_remaining INTEGER NOT NULL,
            season_start   INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS games (
            id           INTEGER PRIMARY KEY,
            home_team_id INTEGER NOT NULL REFERENCES teams(id),
            away_team_id INTEGER NOT NULL REFERENCES teams(id),
            week         INTEGER NOT NULL,
            season_year  INTEGER NOT NULL,
            home_score   INTEGER,
            away_score   INTEGER,
            played       INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS player_game_stats (
            id        INTEGER PRIMARY KEY,
            game_id   INTEGER NOT NULL REFERENCES games(id),
            player_id INTEGER NOT NULL REFERENCES players(id),
            team_id   INTEGER NOT NULL REFERENCES teams(id),
            points    INTEGER DEFAULT 0,
            rebounds  INTEGER DEFAULT 0,
            assists   INTEGER DEFAULT 0,
            steals    INTEGER DEFAULT 0,
            blocks    INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS standings (
            id             INTEGER PRIMARY KEY,
            team_id        INTEGER NOT NULL REFERENCES teams(id),
            season_year    INTEGER NOT NULL,
            wins           INTEGER DEFAULT 0,
            losses         INTEGER DEFAULT 0,
            points_for     INTEGER DEFAULT 0,
            points_against INTEGER DEFAULT 0,
            UNIQUE(team_id, season_year)
        );

        CREATE TABLE IF NOT EXISTS league_state (
            id           INTEGER PRIMARY KEY,
            current_week INTEGER DEFAULT 1,
            season_year  INTEGER DEFAULT 2026,
            mode         TEXT DEFAULT 'test',
            official_started INTEGER DEFAULT 0,
            offseason_stage TEXT,
            offseason_from_season INTEGER,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS general_managers (
            id               INTEGER PRIMARY KEY,
            team_id          INTEGER NOT NULL UNIQUE REFERENCES teams(id),
            name             TEXT NOT NULL,
            archetype        TEXT NOT NULL,
            risk_tolerance   REAL NOT NULL,
            veteran_loyalty  REAL NOT NULL,
            youth_preference REAL NOT NULL,
            trade_frequency  REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS agent_memory (
            id          INTEGER PRIMARY KEY,
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            gm_id       INTEGER NOT NULL REFERENCES general_managers(id),
            event_type  TEXT NOT NULL,
            player_id   INTEGER,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS pending_trades (
            id                   INTEGER PRIMARY KEY,
            week                 INTEGER NOT NULL,
            season_year          INTEGER NOT NULL,
            proposing_gm_id      INTEGER NOT NULL REFERENCES general_managers(id),
            receiving_gm_id      INTEGER NOT NULL REFERENCES general_managers(id),
            offered_player_ids   TEXT NOT NULL,
            requested_player_ids TEXT NOT NULL,
            proposing_score      REAL,
            receiving_score      REAL,
            proposing_reasoning  TEXT,
            receiving_reasoning  TEXT,
            status               TEXT DEFAULT 'pending',
            rejection_reason     TEXT,
            created_at           TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS player_personalities (
            player_id  INTEGER PRIMARY KEY REFERENCES players(id),
            archetype  TEXT NOT NULL,
            ambition   REAL NOT NULL,
            loyalty    REAL NOT NULL,
            ego        REAL NOT NULL,
            work_ethic REAL NOT NULL,
            volatility REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS player_morale (
            id          INTEGER PRIMARY KEY,
            player_id   INTEGER NOT NULL REFERENCES players(id),
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            morale      REAL NOT NULL,
            UNIQUE(player_id, week, season_year)
        );

        CREATE TABLE IF NOT EXISTS player_events (
            id          INTEGER PRIMARY KEY,
            player_id   INTEGER NOT NULL REFERENCES players(id),
            target_id   INTEGER,
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            status      TEXT DEFAULT 'active',
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS player_memory (
            id          INTEGER PRIMARY KEY,
            player_id   INTEGER NOT NULL REFERENCES players(id),
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            event_type  TEXT NOT NULL,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS team_chemistry (
            team_id     INTEGER NOT NULL REFERENCES teams(id),
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            chemistry   REAL NOT NULL,
            PRIMARY KEY (team_id, week, season_year)
        );

        CREATE TABLE IF NOT EXISTS playoff_series (
            id           INTEGER PRIMARY KEY,
            season_year  INTEGER NOT NULL,
            round        INTEGER NOT NULL,
            series_type   TEXT DEFAULT 'semifinal',
            seed_a       INTEGER NOT NULL,
            seed_b       INTEGER NOT NULL,
            team_a_id    INTEGER NOT NULL REFERENCES teams(id),
            team_b_id    INTEGER NOT NULL REFERENCES teams(id),
            team_a_wins  INTEGER DEFAULT 0,
            team_b_wins  INTEGER DEFAULT 0,
            winner_id    INTEGER REFERENCES teams(id),
            status       TEXT DEFAULT 'active'
        );

        CREATE TABLE IF NOT EXISTS articles (
            id          INTEGER PRIMARY KEY,
            week        INTEGER NOT NULL,
            season_year INTEGER NOT NULL,
            headline    TEXT NOT NULL,
            body        TEXT NOT NULL,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS article_tags (
            id         INTEGER PRIMARY KEY,
            article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
            tag_type   TEXT NOT NULL,
            tag_id     INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS player_modifiers (
            id           INTEGER PRIMARY KEY,
            player_id    INTEGER NOT NULL REFERENCES players(id),
            week_set     INTEGER NOT NULL,
            season_year  INTEGER NOT NULL,
            expires_week INTEGER NOT NULL,
            mod_type     TEXT NOT NULL,
            magnitude    REAL NOT NULL DEFAULT 5.0,
            reason       TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS team_modifiers (
            id           INTEGER PRIMARY KEY,
            team_id      INTEGER NOT NULL REFERENCES teams(id),
            week_set     INTEGER NOT NULL,
            season_year  INTEGER NOT NULL,
            expires_week INTEGER NOT NULL,
            mod_type     TEXT NOT NULL,
            magnitude    REAL NOT NULL DEFAULT 6.0,
            reason       TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS gm_modifiers (
            id           INTEGER PRIMARY KEY,
            gm_id        INTEGER NOT NULL REFERENCES general_managers(id),
            week_set     INTEGER NOT NULL,
            season_year  INTEGER NOT NULL,
            expires_week INTEGER NOT NULL,
            mod_type     TEXT NOT NULL,
            magnitude    REAL NOT NULL DEFAULT 0.15,
            reason       TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS offseason_events (
            id          INTEGER PRIMARY KEY,
            from_season INTEGER NOT NULL,
            to_season   INTEGER NOT NULL,
            stage       TEXT NOT NULL,
            headline    TEXT NOT NULL,
            detail      TEXT,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS player_backstories (
            player_id         INTEGER PRIMARY KEY REFERENCES players(id),
            college_state     TEXT,
            hometown_state    TEXT,
            personality_label TEXT,
            backstory_blurb   TEXT
        );

        CREATE TABLE IF NOT EXISTS player_interviews (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id        INTEGER REFERENCES games(id),
            player_id      INTEGER NOT NULL REFERENCES players(id),
            week           INTEGER NOT NULL,
            season_year    INTEGER NOT NULL,
            question       TEXT NOT NULL,
            context_packet TEXT NOT NULL,
            response       TEXT,
            created_at     TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS gm_interviews (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            gm_id             INTEGER NOT NULL REFERENCES general_managers(id),
            week              INTEGER NOT NULL,
            season_year       INTEGER NOT NULL,
            trigger_type      TEXT NOT NULL,
            playoff_series_id INTEGER REFERENCES playoff_series(id),
            question          TEXT NOT NULL,
            context_packet    TEXT NOT NULL,
            response          TEXT,
            created_at        TEXT DEFAULT (datetime('now'))
        );
    """)
    _migrate_existing_schema(conn)
    conn.commit()
    conn.close()


def _migrate_existing_schema(conn):
    """Small additive migrations for databases created by earlier prototypes."""
    player_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(players)").fetchall()
    }
    if "status" not in player_columns:
        conn.execute("ALTER TABLE players ADD COLUMN status TEXT DEFAULT 'active'")
    if "retired_season" not in player_columns:
        conn.execute("ALTER TABLE players ADD COLUMN retired_season INTEGER")
    conn.execute("UPDATE players SET status = COALESCE(status, 'active')")

    team_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(teams)").fetchall()
    }
    team_migrations = {
        "mascot": "TEXT",
        "colors": "TEXT",
        "logo_description": "TEXT",
        "motto": "TEXT",
        "arena": "TEXT",
        "team_archetype": "TEXT",
        "play_style": "TEXT",
        "reputation": "TEXT",
        "rivalry": "TEXT",
        "signature_trait": "TEXT",
    }
    for column, column_type in team_migrations.items():
        if column not in team_columns:
            conn.execute(f"ALTER TABLE teams ADD COLUMN {column} {column_type}")

    games_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(games)").fetchall()
    }
    for col in ["q1_home", "q2_home", "q3_home", "q4_home",
                "q1_away", "q2_away", "q3_away", "q4_away"]:
        if col not in games_columns:
            conn.execute(f"ALTER TABLE games ADD COLUMN {col} INTEGER")

    games_columns2 = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(games)").fetchall()
    }
    if "mvp_player_id" not in games_columns2:
        conn.execute("ALTER TABLE games ADD COLUMN mvp_player_id INTEGER")

    columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(league_state)").fetchall()
    }
    if "mode" not in columns:
        conn.execute("ALTER TABLE league_state ADD COLUMN mode TEXT DEFAULT 'test'")
    if "official_started" not in columns:
        conn.execute(
            "ALTER TABLE league_state ADD COLUMN official_started INTEGER DEFAULT 0"
        )
    if "offseason_stage" not in columns:
        conn.execute("ALTER TABLE league_state ADD COLUMN offseason_stage TEXT")
    if "offseason_from_season" not in columns:
        conn.execute("ALTER TABLE league_state ADD COLUMN offseason_from_season INTEGER")
    conn.execute(
        "UPDATE league_state SET mode = COALESCE(mode, 'test'), "
        "official_started = COALESCE(official_started, 0)"
    )

    games_columns3 = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(games)").fetchall()
    }
    if "playoff_series_id" not in games_columns3:
        conn.execute("ALTER TABLE games ADD COLUMN playoff_series_id INTEGER")

    playoff_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(playoff_series)").fetchall()
    }
    if "series_type" not in playoff_columns:
        conn.execute("ALTER TABLE playoff_series ADD COLUMN series_type TEXT")
    conn.execute("""
        UPDATE playoff_series
        SET series_type = COALESCE(
            series_type,
            CASE
                WHEN round = 1 THEN 'semifinal'
                WHEN round = 2 THEN 'finals'
                ELSE 'semifinal'
            END
        )
    """)

    ls_columns = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(league_state)").fetchall()
    }
    if "phase" not in ls_columns:
        conn.execute("ALTER TABLE league_state ADD COLUMN phase TEXT DEFAULT 'regular_season'")
    conn.execute(
        "UPDATE league_state SET phase = COALESCE(phase, 'regular_season')"
    )

    # Backfill quarter scores for games played before this column was added
    stale = conn.execute(
        "SELECT id, home_score, away_score FROM games WHERE played=1 AND q1_home IS NULL"
    ).fetchall()
    for g in stale:
        hq = _split_quarters(g["home_score"] or 100)
        aq = _split_quarters(g["away_score"] or 100)
        conn.execute(
            "UPDATE games SET q1_home=?,q2_home=?,q3_home=?,q4_home=?,"
            "q1_away=?,q2_away=?,q3_away=?,q4_away=? WHERE id=?",
            (*hq, *aq, g["id"]),
        )

    # Backfill MVP for games played before this column was added
    mvp_stale = conn.execute(
        "SELECT id FROM games WHERE played=1 AND mvp_player_id IS NULL"
    ).fetchall()
    for g in mvp_stale:
        best = conn.execute("""
            SELECT player_id,
                   points + rebounds*0.75 + assists*0.5 + steals*1.5 + blocks AS score
            FROM player_game_stats
            WHERE game_id=?
            ORDER BY score DESC
            LIMIT 1
        """, (g["id"],)).fetchone()
        if best:
            conn.execute(
                "UPDATE games SET mvp_player_id=? WHERE id=?",
                (best["player_id"], g["id"]),
            )


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
