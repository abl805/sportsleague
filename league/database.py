import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "league.db")


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
            team_id        INTEGER NOT NULL UNIQUE REFERENCES teams(id),
            season_year    INTEGER NOT NULL,
            wins           INTEGER DEFAULT 0,
            losses         INTEGER DEFAULT 0,
            points_for     INTEGER DEFAULT 0,
            points_against INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS league_state (
            id           INTEGER PRIMARY KEY,
            current_week INTEGER DEFAULT 1,
            season_year  INTEGER DEFAULT 2025,
            last_updated TEXT
        );
    """)
    conn.commit()
    conn.close()
