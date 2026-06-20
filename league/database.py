import os
import re
import random
import sqlite3

DB_PATH = os.environ.get(
    "AIBA_DB_PATH",
    os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "league.db"),
)
LEAGUE_YEAR = 2026


# ── PostgreSQL wrapper ────────────────────────────────────────────────────────

class _PGConn:
    """
    Wraps a psycopg2 connection so existing code can call conn.execute(),
    conn.executemany(), and conn.cursor() exactly as it does with sqlite3.

    The execute() method also normalises SQLite-specific SQL:
      - ? placeholders  →  %s
      - datetime('now') →  NOW()
    """

    def __init__(self, pg_conn):
        self._conn = pg_conn

    @staticmethod
    def _normalise(sql):
        sql = re.sub(r'\?', '%s', sql)
        sql = re.sub(r"datetime\('now'\)", "NOW()", sql)
        return sql

    def cursor(self):
        import psycopg2.extras
        return self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    def execute(self, sql, params=()):
        cur = self.cursor()
        cur.execute(self._normalise(sql), params)
        return cur

    def executemany(self, sql, params_list):
        cur = self.cursor()
        cur.executemany(self._normalise(sql), params_list)
        return cur

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def _is_postgres(conn):
    return isinstance(conn, _PGConn)


# ── Connection factory ────────────────────────────────────────────────────────

def get_connection():
    url = os.environ.get("DATABASE_URL")
    if url:
        import psycopg2
        try:
            pg = psycopg2.connect(url)
        except UnicodeDecodeError:
            # Python 3.12+ psycopg2 decodes percent-encoded URL bytes as UTF-8.
            # Supabase URLs sometimes contain single non-UTF8 bytes (e.g. %bb).
            # Fix: strip the password from the URL and pass raw bytes via PGPASSWORD
            # so libpq reads them as C bytes, bypassing Python string encoding.
            from urllib.parse import urlparse, unquote_to_bytes
            import re as _re
            r = urlparse(url)
            pw_bytes = unquote_to_bytes(r.password or b"")
            safe_url = _re.sub(r"(://[^:@]+):[^@]+@", r"\1@", url, count=1)
            prev = os.environb.get(b"PGPASSWORD")
            os.environb[b"PGPASSWORD"] = pw_bytes
            try:
                pg = psycopg2.connect(safe_url)
            finally:
                if prev is None:
                    os.environb.pop(b"PGPASSWORD", None)
                else:
                    os.environb[b"PGPASSWORD"] = prev
        pg.autocommit = False
        return _PGConn(pg)
    else:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn


# ── Schema helpers ────────────────────────────────────────────────────────────

def _pg_ddl(sqlite_ddl):
    """Translate SQLite CREATE TABLE DDL to PostgreSQL DDL."""
    ddl = sqlite_ddl
    ddl = ddl.replace("AUTOINCREMENT", "")
    ddl = re.sub(r'\bINTEGER\s+PRIMARY\s+KEY\b', 'SERIAL PRIMARY KEY', ddl)
    ddl = re.sub(
        r"TEXT\s+DEFAULT\s+\(datetime\('now'\)\)",
        "TIMESTAMP DEFAULT NOW()",
        ddl,
    )
    return ddl


def _get_columns(conn, table):
    if _is_postgres(conn):
        rows = conn.execute(
            "SELECT column_name AS name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = ?",
            (table,),
        ).fetchall()
    else:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {row["name"] for row in rows}


# ── Table schemas (SQLite dialect; _pg_ddl translates for PostgreSQL) ─────────

_TABLE_SCHEMAS = [
    """CREATE TABLE IF NOT EXISTS teams (
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
    )""",

    """CREATE TABLE IF NOT EXISTS players (
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
    )""",

    """CREATE TABLE IF NOT EXISTS contracts (
        id             INTEGER PRIMARY KEY,
        player_id      INTEGER NOT NULL REFERENCES players(id),
        team_id        INTEGER NOT NULL REFERENCES teams(id),
        salary         INTEGER NOT NULL,
        years_remaining INTEGER NOT NULL,
        season_start   INTEGER NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS games (
        id           INTEGER PRIMARY KEY,
        home_team_id INTEGER NOT NULL REFERENCES teams(id),
        away_team_id INTEGER NOT NULL REFERENCES teams(id),
        week         INTEGER NOT NULL,
        season_year  INTEGER NOT NULL,
        home_score   INTEGER,
        away_score   INTEGER,
        played       INTEGER DEFAULT 0,
        q1_home      INTEGER,
        q2_home      INTEGER,
        q3_home      INTEGER,
        q4_home      INTEGER,
        q1_away      INTEGER,
        q2_away      INTEGER,
        q3_away      INTEGER,
        q4_away      INTEGER,
        mvp_player_id INTEGER,
        playoff_series_id INTEGER
    )""",

    """CREATE TABLE IF NOT EXISTS player_game_stats (
        id        INTEGER PRIMARY KEY,
        game_id   INTEGER NOT NULL REFERENCES games(id),
        player_id INTEGER NOT NULL REFERENCES players(id),
        team_id   INTEGER NOT NULL REFERENCES teams(id),
        minutes   INTEGER DEFAULT 0,
        started   INTEGER DEFAULT 0,
        rotation_role TEXT,
        points    INTEGER DEFAULT 0,
        rebounds  INTEGER DEFAULT 0,
        assists   INTEGER DEFAULT 0,
        steals    INTEGER DEFAULT 0,
        blocks    INTEGER DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS standings (
        id             INTEGER PRIMARY KEY,
        team_id        INTEGER NOT NULL REFERENCES teams(id),
        season_year    INTEGER NOT NULL,
        wins           INTEGER DEFAULT 0,
        losses         INTEGER DEFAULT 0,
        points_for     INTEGER DEFAULT 0,
        points_against INTEGER DEFAULT 0,
        UNIQUE(team_id, season_year)
    )""",

    """CREATE TABLE IF NOT EXISTS league_state (
        id           INTEGER PRIMARY KEY,
        current_week INTEGER DEFAULT 1,
        season_year  INTEGER DEFAULT 2026,
        mode         TEXT DEFAULT 'test',
        official_started INTEGER DEFAULT 0,
        offseason_stage TEXT,
        offseason_from_season INTEGER,
        phase        TEXT DEFAULT 'regular_season',
        last_updated TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS general_managers (
        id               INTEGER PRIMARY KEY,
        team_id          INTEGER NOT NULL UNIQUE REFERENCES teams(id),
        name             TEXT NOT NULL,
        archetype        TEXT NOT NULL,
        risk_tolerance   REAL NOT NULL,
        veteran_loyalty  REAL NOT NULL,
        youth_preference REAL NOT NULL,
        trade_frequency  REAL NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS agent_memory (
        id          INTEGER PRIMARY KEY,
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        gm_id       INTEGER NOT NULL REFERENCES general_managers(id),
        event_type  TEXT NOT NULL,
        player_id   INTEGER,
        detail      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS pending_trades (
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
    )""",

    """CREATE TABLE IF NOT EXISTS player_personalities (
        player_id  INTEGER PRIMARY KEY REFERENCES players(id),
        archetype  TEXT NOT NULL,
        ambition   REAL NOT NULL,
        loyalty    REAL NOT NULL,
        ego        REAL NOT NULL,
        work_ethic REAL NOT NULL,
        volatility REAL NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS player_morale (
        id          INTEGER PRIMARY KEY,
        player_id   INTEGER NOT NULL REFERENCES players(id),
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        morale      REAL NOT NULL,
        UNIQUE(player_id, week, season_year)
    )""",

    """CREATE TABLE IF NOT EXISTS player_events (
        id          INTEGER PRIMARY KEY,
        player_id   INTEGER NOT NULL REFERENCES players(id),
        target_id   INTEGER,
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        event_type  TEXT NOT NULL,
        status      TEXT DEFAULT 'active',
        detail      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS player_memory (
        id          INTEGER PRIMARY KEY,
        player_id   INTEGER NOT NULL REFERENCES players(id),
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        event_type  TEXT NOT NULL,
        detail      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS team_chemistry (
        team_id     INTEGER NOT NULL REFERENCES teams(id),
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        chemistry   REAL NOT NULL,
        PRIMARY KEY (team_id, week, season_year)
    )""",

    """CREATE TABLE IF NOT EXISTS playoff_series (
        id           INTEGER PRIMARY KEY,
        season_year  INTEGER NOT NULL,
        round        INTEGER NOT NULL,
        series_type  TEXT DEFAULT 'semifinal',
        seed_a       INTEGER NOT NULL,
        seed_b       INTEGER NOT NULL,
        team_a_id    INTEGER NOT NULL REFERENCES teams(id),
        team_b_id    INTEGER NOT NULL REFERENCES teams(id),
        team_a_wins  INTEGER DEFAULT 0,
        team_b_wins  INTEGER DEFAULT 0,
        winner_id    INTEGER REFERENCES teams(id),
        status       TEXT DEFAULT 'active'
    )""",

    """CREATE TABLE IF NOT EXISTS articles (
        id          INTEGER PRIMARY KEY,
        week        INTEGER NOT NULL,
        season_year INTEGER NOT NULL,
        headline    TEXT NOT NULL,
        body        TEXT NOT NULL,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS article_tags (
        id         INTEGER PRIMARY KEY,
        article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
        tag_type   TEXT NOT NULL,
        tag_id     INTEGER NOT NULL
    )""",

    """CREATE TABLE IF NOT EXISTS player_modifiers (
        id           INTEGER PRIMARY KEY,
        player_id    INTEGER NOT NULL REFERENCES players(id),
        week_set     INTEGER NOT NULL,
        season_year  INTEGER NOT NULL,
        expires_week INTEGER NOT NULL,
        mod_type     TEXT NOT NULL,
        magnitude    REAL NOT NULL DEFAULT 5.0,
        reason       TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS team_modifiers (
        id           INTEGER PRIMARY KEY,
        team_id      INTEGER NOT NULL REFERENCES teams(id),
        week_set     INTEGER NOT NULL,
        season_year  INTEGER NOT NULL,
        expires_week INTEGER NOT NULL,
        mod_type     TEXT NOT NULL,
        magnitude    REAL NOT NULL DEFAULT 6.0,
        reason       TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS gm_modifiers (
        id           INTEGER PRIMARY KEY,
        gm_id        INTEGER NOT NULL REFERENCES general_managers(id),
        week_set     INTEGER NOT NULL,
        season_year  INTEGER NOT NULL,
        expires_week INTEGER NOT NULL,
        mod_type     TEXT NOT NULL,
        magnitude    REAL NOT NULL DEFAULT 0.15,
        reason       TEXT,
        created_at   TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS offseason_events (
        id          INTEGER PRIMARY KEY,
        from_season INTEGER NOT NULL,
        to_season   INTEGER NOT NULL,
        stage       TEXT NOT NULL,
        headline    TEXT NOT NULL,
        detail      TEXT,
        created_at  TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS player_backstories (
        player_id         INTEGER PRIMARY KEY REFERENCES players(id),
        college_state     TEXT,
        hometown_state    TEXT,
        personality_label TEXT,
        backstory_blurb   TEXT
    )""",

    """CREATE TABLE IF NOT EXISTS player_interviews (
        id             INTEGER PRIMARY KEY,
        game_id        INTEGER REFERENCES games(id),
        player_id      INTEGER NOT NULL REFERENCES players(id),
        week           INTEGER NOT NULL,
        season_year    INTEGER NOT NULL,
        question       TEXT NOT NULL,
        context_packet TEXT NOT NULL,
        response       TEXT,
        created_at     TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS gm_interviews (
        id                INTEGER PRIMARY KEY,
        gm_id             INTEGER NOT NULL REFERENCES general_managers(id),
        week              INTEGER NOT NULL,
        season_year       INTEGER NOT NULL,
        trigger_type      TEXT NOT NULL,
        playoff_series_id INTEGER REFERENCES playoff_series(id),
        question          TEXT NOT NULL,
        context_packet    TEXT NOT NULL,
        response          TEXT,
        created_at        TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS head_coaches (
        id                  INTEGER PRIMARY KEY,
        team_id             INTEGER NOT NULL REFERENCES teams(id),
        name                TEXT NOT NULL,
        strategy            TEXT NOT NULL,
        development         REAL NOT NULL DEFAULT 0.5,
        leadership          REAL NOT NULL DEFAULT 0.5,
        pressure_handling   REAL NOT NULL DEFAULT 0.5,
        pace_preference     REAL NOT NULL DEFAULT 0.5,
        rotation_tightness  REAL NOT NULL DEFAULT 0.5,
        lineup_preference   TEXT NOT NULL DEFAULT 'balanced_best_five',
        job_security        REAL NOT NULL DEFAULT 0.7,
        hired_season        INTEGER NOT NULL,
        fired_season        INTEGER,
        status              TEXT NOT NULL DEFAULT 'active',
        created_at          TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS player_injuries (
        id                   INTEGER PRIMARY KEY,
        player_id            INTEGER NOT NULL REFERENCES players(id),
        season_year          INTEGER NOT NULL,
        week_start           INTEGER NOT NULL,
        expected_return_week INTEGER NOT NULL,
        severity             TEXT NOT NULL,
        status               TEXT NOT NULL DEFAULT 'active',
        skill_penalty        REAL NOT NULL DEFAULT 0,
        description          TEXT NOT NULL,
        created_at           TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS injury_consequences (
        id                    INTEGER PRIMARY KEY,
        injury_id             INTEGER NOT NULL UNIQUE REFERENCES player_injuries(id),
        player_id             INTEGER NOT NULL REFERENCES players(id),
        outcome_type          TEXT NOT NULL,
        original_skill        INTEGER NOT NULL,
        skill_loss            INTEGER NOT NULL DEFAULT 0,
        original_durability   REAL NOT NULL,
        durability_loss       REAL NOT NULL DEFAULT 0,
        recovery_ceiling      INTEGER NOT NULL DEFAULT 0,
        skill_restored        INTEGER NOT NULL DEFAULT 0,
        recovery_points       INTEGER NOT NULL DEFAULT 0,
        games_since_return    INTEGER NOT NULL DEFAULT 0,
        target_points         REAL NOT NULL DEFAULT 0,
        comeback_status       TEXT NOT NULL DEFAULT 'complete',
        resolved_season       INTEGER NOT NULL,
        resolved_week         INTEGER NOT NULL,
        completed_season      INTEGER,
        completed_week        INTEGER,
        summary               TEXT NOT NULL,
        created_at            TEXT DEFAULT (datetime('now')),
        updated_at            TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS player_relationships (
        id                INTEGER PRIMARY KEY,
        player_id         INTEGER NOT NULL REFERENCES players(id),
        target_player_id  INTEGER REFERENCES players(id),
        origin_team_id    INTEGER REFERENCES teams(id),
        relationship_type TEXT NOT NULL,
        intensity         REAL NOT NULL DEFAULT 0.5,
        started_season    INTEGER NOT NULL,
        started_week      INTEGER NOT NULL DEFAULT 0,
        detail            TEXT,
        status            TEXT NOT NULL DEFAULT 'active',
        UNIQUE(player_id, target_player_id, origin_team_id, relationship_type)
    )""",

    """CREATE TABLE IF NOT EXISTS player_arcs (
        player_id      INTEGER PRIMARY KEY REFERENCES players(id),
        arc_type       TEXT NOT NULL,
        title          TEXT NOT NULL,
        summary        TEXT NOT NULL,
        started_season INTEGER NOT NULL,
        updated_week   INTEGER NOT NULL DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS team_game_stats (
        game_id          INTEGER NOT NULL REFERENCES games(id),
        team_id          INTEGER NOT NULL REFERENCES teams(id),
        possessions      INTEGER NOT NULL,
        turnovers        INTEGER NOT NULL,
        expected_points  REAL NOT NULL,
        strength_score   REAL NOT NULL,
        chemistry_used   REAL NOT NULL,
        morale_used      REAL NOT NULL,
        coach_effect     REAL NOT NULL,
        injury_effect    REAL NOT NULL,
        clutch_effect    REAL NOT NULL,
        PRIMARY KEY (game_id, team_id)
    )""",

    """CREATE TABLE IF NOT EXISTS game_rotations (
        game_id             INTEGER NOT NULL REFERENCES games(id),
        team_id             INTEGER NOT NULL REFERENCES teams(id),
        coach_id            INTEGER REFERENCES head_coaches(id),
        rotation_size       INTEGER NOT NULL,
        rotation_tightness  REAL NOT NULL,
        lineup_preference   TEXT NOT NULL,
        starter_ids_json    TEXT NOT NULL,
        rotation_ids_json   TEXT NOT NULL,
        starter_minutes     INTEGER NOT NULL,
        summary             TEXT NOT NULL,
        PRIMARY KEY (game_id, team_id)
    )""",

    """CREATE TABLE IF NOT EXISTS game_explanations (
        game_id              INTEGER PRIMARY KEY REFERENCES games(id),
        expected_margin      REAL NOT NULL,
        home_win_probability REAL NOT NULL,
        favorite_team_id     INTEGER REFERENCES teams(id),
        decisive_quarter     INTEGER,
        turning_point        TEXT NOT NULL,
        strategy_matchup     TEXT NOT NULL,
        key_factors_json     TEXT NOT NULL,
        factual_recap        TEXT NOT NULL,
        standings_impact     TEXT,
        coach_quote          TEXT,
        created_at           TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS game_broadcasts (
        game_id                INTEGER PRIMARY KEY REFERENCES games(id),
        pregame_headline       TEXT NOT NULL,
        pregame_storyline      TEXT NOT NULL,
        pregame_cards_json     TEXT NOT NULL,
        quarter_recaps_json    TEXT,
        generated_before_tip   INTEGER NOT NULL DEFAULT 0,
        created_at             TEXT DEFAULT (datetime('now')),
        updated_at             TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS weekly_editorial_packages (
        id            INTEGER PRIMARY KEY,
        schema_name   TEXT NOT NULL DEFAULT 'aiba.weekly_editorial.v1',
        season_year   INTEGER NOT NULL,
        week          INTEGER NOT NULL,
        source_json   TEXT NOT NULL,
        prompt_text   TEXT NOT NULL,
        response_json TEXT,
        response_hash TEXT,
        status        TEXT NOT NULL DEFAULT 'ready',
        created_at    TEXT DEFAULT (datetime('now')),
        published_at  TEXT,
        UNIQUE(season_year, week)
    )""",

    """CREATE TABLE IF NOT EXISTS editorial_quotes (
        id            INTEGER PRIMARY KEY,
        package_id    INTEGER NOT NULL REFERENCES weekly_editorial_packages(id),
        speaker_type  TEXT NOT NULL,
        speaker_id    INTEGER NOT NULL,
        game_id       INTEGER REFERENCES games(id),
        quote_text    TEXT NOT NULL,
        created_at    TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS history_events (
        id            INTEGER PRIMARY KEY,
        season_year   INTEGER NOT NULL,
        week          INTEGER NOT NULL DEFAULT 0,
        event_type    TEXT NOT NULL,
        headline      TEXT NOT NULL,
        detail        TEXT,
        team_id       INTEGER REFERENCES teams(id),
        player_id     INTEGER REFERENCES players(id),
        coach_id      INTEGER REFERENCES head_coaches(id),
        game_id       INTEGER REFERENCES games(id),
        source_key    TEXT UNIQUE,
        importance    INTEGER NOT NULL DEFAULT 1,
        created_at    TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS record_book_entries (
        id             INTEGER PRIMARY KEY,
        scope          TEXT NOT NULL,
        stat_key       TEXT NOT NULL,
        label          TEXT NOT NULL,
        player_id      INTEGER NOT NULL REFERENCES players(id),
        team_id        INTEGER REFERENCES teams(id),
        value          INTEGER NOT NULL,
        season_year    INTEGER,
        week           INTEGER NOT NULL DEFAULT 0,
        game_id        INTEGER REFERENCES games(id),
        previous_value INTEGER,
        is_current     INTEGER NOT NULL DEFAULT 1,
        source_key     TEXT NOT NULL UNIQUE,
        created_at     TEXT DEFAULT (datetime('now')),
        updated_at     TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS season_snapshots (
        season_year   INTEGER PRIMARY KEY,
        snapshot_json TEXT NOT NULL,
        champion_id   INTEGER REFERENCES teams(id),
        created_at    TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS awards (
        id            INTEGER PRIMARY KEY,
        season_year   INTEGER NOT NULL,
        week          INTEGER NOT NULL DEFAULT 0,
        award_type    TEXT NOT NULL,
        entity_type   TEXT NOT NULL,
        entity_id     INTEGER NOT NULL,
        label         TEXT NOT NULL,
        detail        TEXT,
        UNIQUE(season_year, week, award_type, entity_type, entity_id)
    )""",

    """CREATE TABLE IF NOT EXISTS retired_jerseys (
        id            INTEGER PRIMARY KEY,
        team_id       INTEGER NOT NULL REFERENCES teams(id),
        player_id     INTEGER NOT NULL REFERENCES players(id),
        season_year   INTEGER NOT NULL,
        reason        TEXT NOT NULL,
        UNIQUE(team_id, player_id)
    )""",

    """CREATE TABLE IF NOT EXISTS draft_profiles (
        player_id       INTEGER PRIMARY KEY REFERENCES players(id),
        draft_year      INTEGER NOT NULL,
        team_id         INTEGER NOT NULL REFERENCES teams(id),
        pick_number     INTEGER NOT NULL,
        initial_skill   INTEGER NOT NULL,
        outcome_label   TEXT NOT NULL DEFAULT 'developing',
        outcome_summary TEXT NOT NULL,
        evaluated_year  INTEGER,
        updated_at      TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS playoff_run_summaries (
        id             INTEGER PRIMARY KEY,
        season_year    INTEGER NOT NULL,
        team_id        INTEGER NOT NULL REFERENCES teams(id),
        finish_label   TEXT NOT NULL,
        title          TEXT NOT NULL,
        summary        TEXT NOT NULL,
        playoff_wins   INTEGER NOT NULL DEFAULT 0,
        playoff_losses INTEGER NOT NULL DEFAULT 0,
        close_wins     INTEGER NOT NULL DEFAULT 0,
        star_player_id INTEGER REFERENCES players(id),
        legendary      INTEGER NOT NULL DEFAULT 0,
        UNIQUE(season_year, team_id)
    )""",

    """CREATE TABLE IF NOT EXISTS hall_of_fame (
        id               INTEGER PRIMARY KEY,
        player_id        INTEGER NOT NULL UNIQUE REFERENCES players(id),
        induction_year   INTEGER NOT NULL,
        primary_team_id  INTEGER REFERENCES teams(id),
        career_points    INTEGER NOT NULL DEFAULT 0,
        career_rebounds  INTEGER NOT NULL DEFAULT 0,
        career_assists   INTEGER NOT NULL DEFAULT 0,
        championships    INTEGER NOT NULL DEFAULT 0,
        major_awards     INTEGER NOT NULL DEFAULT 0,
        summary          TEXT NOT NULL,
        created_at       TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS franchise_events (
        id           INTEGER PRIMARY KEY,
        team_id      INTEGER NOT NULL REFERENCES teams(id),
        season_year  INTEGER NOT NULL,
        event_type   TEXT NOT NULL,
        title        TEXT NOT NULL,
        detail       TEXT NOT NULL,
        source_key   TEXT NOT NULL UNIQUE,
        created_at   TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS polls (
        id            INTEGER PRIMARY KEY,
        season_year   INTEGER NOT NULL,
        week          INTEGER NOT NULL,
        poll_type     TEXT NOT NULL,
        question      TEXT NOT NULL,
        status        TEXT NOT NULL DEFAULT 'open',
        closes_week   INTEGER NOT NULL,
        result_label  TEXT,
        context_json  TEXT,
        winner_option_id INTEGER,
        created_at    TEXT DEFAULT (datetime('now')),
        finalized_at  TEXT,
        UNIQUE(season_year, week, poll_type)
    )""",

    """CREATE TABLE IF NOT EXISTS poll_options (
        id            INTEGER PRIMARY KEY,
        poll_id       INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
        label         TEXT NOT NULL,
        entity_type   TEXT,
        entity_id     INTEGER,
        payload_json  TEXT,
        sort_order    INTEGER NOT NULL DEFAULT 0
    )""",

    """CREATE TABLE IF NOT EXISTS poll_votes (
        id            INTEGER PRIMARY KEY,
        poll_id       INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
        option_id     INTEGER NOT NULL REFERENCES poll_options(id) ON DELETE CASCADE,
        voter_hash    TEXT NOT NULL,
        created_at    TEXT DEFAULT (datetime('now')),
        UNIQUE(poll_id, voter_hash)
    )""",

    """CREATE TABLE IF NOT EXISTS fan_labels (
        id             INTEGER PRIMARY KEY,
        label_type     TEXT NOT NULL,
        label          TEXT NOT NULL,
        season_year    INTEGER NOT NULL,
        week           INTEGER NOT NULL,
        team_id        INTEGER REFERENCES teams(id),
        player_id      INTEGER REFERENCES players(id),
        game_id        INTEGER REFERENCES games(id),
        source_poll_id INTEGER NOT NULL UNIQUE REFERENCES polls(id),
        status         TEXT NOT NULL DEFAULT 'active',
        created_at     TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS rivalry_names (
        id             INTEGER PRIMARY KEY,
        team_a_id      INTEGER NOT NULL REFERENCES teams(id),
        team_b_id      INTEGER NOT NULL REFERENCES teams(id),
        name           TEXT NOT NULL,
        season_year    INTEGER NOT NULL,
        week           INTEGER NOT NULL,
        source_poll_id INTEGER NOT NULL UNIQUE REFERENCES polls(id),
        status         TEXT NOT NULL DEFAULT 'active',
        created_at     TEXT DEFAULT (datetime('now'))
    )""",

    """CREATE TABLE IF NOT EXISTS team_rivalries (
        id                INTEGER PRIMARY KEY,
        team_a_id         INTEGER NOT NULL REFERENCES teams(id),
        team_b_id         INTEGER NOT NULL REFERENCES teams(id),
        base_intensity    REAL NOT NULL DEFAULT 0.12,
        current_intensity REAL NOT NULL DEFAULT 0.12,
        meetings          INTEGER NOT NULL DEFAULT 0,
        close_games       INTEGER NOT NULL DEFAULT 0,
        playoff_meetings  INTEGER NOT NULL DEFAULT 0,
        trade_count       INTEGER NOT NULL DEFAULT 0,
        last_season       INTEGER,
        last_week         INTEGER,
        last_event        TEXT,
        updated_at        TEXT DEFAULT (datetime('now')),
        UNIQUE(team_a_id, team_b_id)
    )""",

    """CREATE TABLE IF NOT EXISTS rivalry_events (
        id              INTEGER PRIMARY KEY,
        rivalry_id      INTEGER NOT NULL REFERENCES team_rivalries(id) ON DELETE CASCADE,
        season_year     INTEGER NOT NULL,
        week            INTEGER NOT NULL,
        event_type      TEXT NOT NULL,
        intensity_before REAL NOT NULL,
        intensity_after REAL NOT NULL,
        detail          TEXT NOT NULL,
        game_id         INTEGER REFERENCES games(id),
        trade_id        INTEGER REFERENCES pending_trades(id),
        created_at      TEXT DEFAULT (datetime('now'))
    )""",
]


_tables_created = False


def create_tables():
    global _tables_created
    if _tables_created:
        return
    conn = get_connection()
    try:
        for sqlite_ddl in _TABLE_SCHEMAS:
            ddl = _pg_ddl(sqlite_ddl) if _is_postgres(conn) else sqlite_ddl
            conn.execute(ddl)
        _migrate_existing_schema(conn)
        conn.commit()
    finally:
        conn.close()
    _tables_created = True


def _migrate_existing_schema(conn):
    """Additive migrations for databases created by earlier versions."""

    # ── players ──────────────────────────────────────────────────────────────
    player_cols = _get_columns(conn, "players")
    if "status" not in player_cols:
        conn.execute("ALTER TABLE players ADD COLUMN status TEXT DEFAULT 'active'")
    if "retired_season" not in player_cols:
        conn.execute("ALTER TABLE players ADD COLUMN retired_season INTEGER")
    conn.execute("UPDATE players SET status = COALESCE(status, 'active')")

    # ── teams ─────────────────────────────────────────────────────────────────
    team_cols = _get_columns(conn, "teams")
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
        "fan_pitch": "TEXT",
        "pressure_label": "TEXT",
        "rivalry_intensity": "REAL DEFAULT 0.5",
    }
    for col, col_type in team_migrations.items():
        if col not in team_cols:
            conn.execute(f"ALTER TABLE teams ADD COLUMN {col} {col_type}")

    # ── games ─────────────────────────────────────────────────────────────────
    game_cols = _get_columns(conn, "games")
    for col in ["q1_home", "q2_home", "q3_home", "q4_home",
                "q1_away", "q2_away", "q3_away", "q4_away"]:
        if col not in game_cols:
            conn.execute(f"ALTER TABLE games ADD COLUMN {col} INTEGER")

    game_cols2 = _get_columns(conn, "games")
    if "mvp_player_id" not in game_cols2:
        conn.execute("ALTER TABLE games ADD COLUMN mvp_player_id INTEGER")
    if "playoff_series_id" not in game_cols2:
        conn.execute("ALTER TABLE games ADD COLUMN playoff_series_id INTEGER")
    if "possessions" not in game_cols2:
        conn.execute("ALTER TABLE games ADD COLUMN possessions INTEGER")

    stat_cols = _get_columns(conn, "player_game_stats")
    stat_migrations = {
        "minutes": "INTEGER DEFAULT 0",
        "started": "INTEGER DEFAULT 0",
        "rotation_role": "TEXT",
    }
    for col, col_type in stat_migrations.items():
        if col not in stat_cols:
            conn.execute(
                f"ALTER TABLE player_game_stats ADD COLUMN {col} {col_type}"
            )

    # ── league_state ──────────────────────────────────────────────────────────
    ls_cols = _get_columns(conn, "league_state")
    if "mode" not in ls_cols:
        conn.execute("ALTER TABLE league_state ADD COLUMN mode TEXT DEFAULT 'test'")
    if "official_started" not in ls_cols:
        conn.execute(
            "ALTER TABLE league_state ADD COLUMN official_started INTEGER DEFAULT 0"
        )
    if "offseason_stage" not in ls_cols:
        conn.execute("ALTER TABLE league_state ADD COLUMN offseason_stage TEXT")
    if "offseason_from_season" not in ls_cols:
        conn.execute("ALTER TABLE league_state ADD COLUMN offseason_from_season INTEGER")
    if "phase" not in ls_cols:
        conn.execute(
            "ALTER TABLE league_state ADD COLUMN phase TEXT DEFAULT 'regular_season'"
        )
    conn.execute(
        "UPDATE league_state SET "
        "mode = COALESCE(mode, 'test'), "
        "official_started = COALESCE(official_started, 0), "
        "phase = COALESCE(phase, 'regular_season')"
    )

    # ── playoff_series ────────────────────────────────────────────────────────
    ps_cols = _get_columns(conn, "playoff_series")
    if "series_type" not in ps_cols:
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

    # Player character traits.
    personality_cols = _get_columns(conn, "player_personalities")
    personality_migrations = {
        "leadership": "REAL DEFAULT 0.5",
        "clutch": "REAL DEFAULT 0.5",
        "durability": "REAL DEFAULT 0.7",
        "media_reputation": "REAL DEFAULT 0.5",
    }
    for col, col_type in personality_migrations.items():
        if col not in personality_cols:
            conn.execute(
                f"ALTER TABLE player_personalities ADD COLUMN {col} {col_type}"
            )

    coach_cols = _get_columns(conn, "head_coaches")
    if "lineup_preference" not in coach_cols:
        conn.execute(
            "ALTER TABLE head_coaches ADD COLUMN lineup_preference "
            "TEXT DEFAULT 'balanced_best_five'"
        )
    conn.execute(
        """
        UPDATE head_coaches
        SET lineup_preference = CASE strategy
            WHEN 'inside_control' THEN 'size_and_strength'
            WHEN 'hustle_pressure' THEN 'energy_and_defense'
            WHEN 'pace_and_space' THEN 'speed_and_shooting'
            WHEN 'creative_motion' THEN 'playmaking'
            WHEN 'defensive_grind' THEN 'defense_and_veterans'
            WHEN 'late_game_control' THEN 'clutch_and_experience'
            WHEN 'development_lab' THEN 'youth_and_upside'
            ELSE COALESCE(lineup_preference, 'balanced_best_five')
        END
        WHERE lineup_preference IS NULL
           OR lineup_preference = 'balanced_best_five'
        """
    )

    article_cols = _get_columns(conn, "articles")
    if "editorial_package_id" not in article_cols:
        conn.execute("ALTER TABLE articles ADD COLUMN editorial_package_id INTEGER")
    if "story_role" not in article_cols:
        conn.execute("ALTER TABLE articles ADD COLUMN story_role TEXT")

    poll_cols = _get_columns(conn, "polls")
    if "context_json" not in poll_cols:
        conn.execute("ALTER TABLE polls ADD COLUMN context_json TEXT")
    if "winner_option_id" not in poll_cols:
        conn.execute("ALTER TABLE polls ADD COLUMN winner_option_id INTEGER")
    if "finalized_at" not in poll_cols:
        conn.execute("ALTER TABLE polls ADD COLUMN finalized_at TEXT")

    poll_option_cols = _get_columns(conn, "poll_options")
    if "payload_json" not in poll_option_cols:
        conn.execute("ALTER TABLE poll_options ADD COLUMN payload_json TEXT")

    # ── Backfill quarter scores for pre-migration games ───────────────────────
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

    # ── Backfill MVP for pre-migration games ──────────────────────────────────
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

    from league.fan_experience import (
        backfill_fan_foundations,
        refresh_league_lore,
        refresh_record_book,
    )
    backfill_fan_foundations(conn)
    refresh_record_book(conn, announce=False)
    state = conn.execute(
        "SELECT season_year FROM league_state WHERE id=1"
    ).fetchone()
    refresh_league_lore(conn, state["season_year"] if state else 2026)


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
