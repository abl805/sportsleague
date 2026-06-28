import os
import re
import random
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "db", "league.db")
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
        # PostgreSQL ROUND(x, n) requires numeric; AVG returns double precision
        sql = re.sub(r'\bROUND\((AVG\([^)]*\)), (\d+)\)', r'ROUND(\1::numeric, \2)', sql)
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
        from urllib.parse import urlparse, unquote
        url = url.strip()
        p = urlparse(url)
        pg = psycopg2.connect(
            host=p.hostname,
            port=p.port or 5432,
            dbname=p.path.lstrip("/"),
            user=p.username,
            password=unquote(p.password, encoding="latin-1") if p.password else None,
        )
        pg.autocommit = False
        return _PGConn(pg)
    else:
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
]


def create_tables():
    conn = get_connection()
    try:
        for sqlite_ddl in _TABLE_SCHEMAS:
            ddl = _pg_ddl(sqlite_ddl) if _is_postgres(conn) else sqlite_ddl
            conn.execute(ddl)
        _migrate_existing_schema(conn)
        conn.commit()
    finally:
        conn.close()


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
