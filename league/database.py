import sqlite3
import os

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
            abbreviation TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS players (
            id           INTEGER PRIMARY KEY,
            team_id      INTEGER NOT NULL REFERENCES teams(id),
            first_name   TEXT NOT NULL,
            last_name    TEXT NOT NULL,
            age          INTEGER NOT NULL,
            position     TEXT NOT NULL,
            skill_rating INTEGER NOT NULL,
            salary       INTEGER NOT NULL
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
    """)
    _migrate_existing_schema(conn)
    conn.commit()
    conn.close()


def _migrate_existing_schema(conn):
    """Small additive migrations for databases created by earlier prototypes."""
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
    conn.execute(
        "UPDATE league_state SET mode = COALESCE(mode, 'test'), "
        "official_started = COALESCE(official_started, 0)"
    )
