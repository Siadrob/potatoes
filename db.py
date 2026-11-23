import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA.read_text(encoding="utf-8"))
        _migrate(conn)


def _migrate(conn):
    """Met à jour les bases créées avec une version précédente du schéma."""
    cols = {row[1] for row in conn.execute("PRAGMA table_info(profile)")}
    if "mains" not in cols:
        conn.execute("ALTER TABLE profile ADD COLUMN mains TEXT")
        conn.execute("UPDATE profile SET mains = main_char WHERE main_char IS NOT NULL")
    match_cols = {row[1] for row in conn.execute("PRAGMA table_info(matches)")}
    if "opp_rank" not in match_cols:
        conn.execute("ALTER TABLE matches ADD COLUMN opp_rank TEXT")
    # Ancien format d'identifiant (wavu:...) -> format commun à toutes les sources.
    conn.execute("UPDATE matches SET external_id = 'battle:' || substr(external_id, 6) "
                 "WHERE external_id LIKE 'wavu:%'")
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version < 1:
        # Les premiers imports wavu stockaient le rating d'avant le match.
        conn.execute("UPDATE matches SET rating = rating + rating_change "
                     "WHERE source = 'wavu' AND rating IS NOT NULL AND rating_change IS NOT NULL")
        conn.execute("PRAGMA user_version = 1")
    _migrate_players(conn)


def _columns(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _migrate_players(conn):
    """Passage au multi-joueur : chaque donnée appartient à un ID Tekken (player_id).

    Les données d'une base mono-joueur sont rattachées à l'ID enregistré dans l'ancien
    profil ; sans ID connu, elles restent orphelines et sont adoptées par le premier
    joueur qui se connecte (voir adopt_orphans).
    """
    for table in ("matches", "quiz_sessions", "training_goals"):
        if "player_id" not in _columns(conn, table):
            conn.execute(f"ALTER TABLE {table} ADD COLUMN player_id TEXT")
    if "layout" not in _columns(conn, "players"):
        conn.execute("ALTER TABLE players ADD COLUMN layout TEXT")
    if "steam_id" not in _columns(conn, "players"):
        conn.execute("ALTER TABLE players ADD COLUMN steam_id TEXT")

    if "player_id" not in _columns(conn, "matchup_notes"):
        conn.executescript("""
            ALTER TABLE matchup_notes RENAME TO matchup_notes_old;
            CREATE TABLE matchup_notes (
                player_id TEXT NOT NULL,
                opp_char TEXT NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (player_id, opp_char)
            );
            INSERT INTO matchup_notes (player_id, opp_char, notes, updated_at)
                SELECT '', opp_char, notes, updated_at FROM matchup_notes_old;
            DROP TABLE matchup_notes_old;
        """)

    old = conn.execute("SELECT * FROM profile WHERE id = 1 AND polaris_id IS NOT NULL").fetchone()
    if old:
        cols = [c[0] for c in conn.execute("SELECT * FROM profile LIMIT 0").description]
        old = dict(zip(cols, old))
        conn.execute(
            "INSERT OR IGNORE INTO players (polaris_id, name, mains, goal_rank, goal_rating) "
            "VALUES (?, ?, ?, ?, ?)",
            (old["polaris_id"], old["name"] or old["polaris_id"], old.get("mains"),
             old["goal_rank"], old["goal_rating"]))
        adopt_orphans(conn, old["polaris_id"])
        conn.execute("UPDATE profile SET polaris_id = NULL WHERE id = 1")

    _scope_external_ids(conn)
    conn.executescript("""
        DROP INDEX IF EXISTS idx_quiz_daily;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_quiz_daily_player
            ON quiz_sessions (player_id, day) WHERE mode = 'daily';
        CREATE INDEX IF NOT EXISTS idx_matches_player ON matches (player_id, played_at);
        CREATE INDEX IF NOT EXISTS idx_goals_player ON training_goals (player_id);
    """)


def adopt_orphans(conn, player_id):
    """Rattache à `player_id` les données sans propriétaire (ancienne base mono-joueur)."""
    for table in ("matches", "quiz_sessions", "training_goals"):
        conn.execute(f"UPDATE {table} SET player_id = ? WHERE player_id IS NULL", (player_id,))
    conn.execute("UPDATE OR IGNORE matchup_notes SET player_id = ? WHERE player_id = ''", (player_id,))
    _scope_external_ids(conn)


def _scope_external_ids(conn):
    """'battle:…' -> '<joueur>|battle:…' : un identifiant de match est unique par joueur."""
    conn.execute("UPDATE matches SET external_id = player_id || '|' || external_id "
                 "WHERE player_id IS NOT NULL AND external_id LIKE 'battle:%'")


def scoped_id(player_id, external_id):
    return f"{player_id}|{external_id}" if external_id else None


IMPORT_FIELDS = ("player_id", "played_at", "my_char", "opp_char", "opp_name", "result", "rounds_won",
                 "rounds_lost", "rating", "rating_change", "rank", "opp_rank", "source",
                 "external_id")


def save_imported(db, matches, player_id):
    """Insère les matchs importés ; complète ceux déjà connus (rating, rang…).

    wavu apporte le rating, ewgf le rang Dan : un même match peut venir des deux.
    Retourne le nombre de nouveaux matchs.
    """
    count = lambda: db.execute("SELECT COUNT(*) FROM matches").fetchone()[0]
    before = count()
    cols = ", ".join(IMPORT_FIELDS)
    values = ", ".join(f":{f}" for f in IMPORT_FIELDS)
    fill = ", ".join(f"{f} = COALESCE(matches.{f}, excluded.{f})"
                     for f in ("opp_name", "rating", "rating_change", "rank", "opp_rank"))
    rows = [{**{f: m.get(f) for f in IMPORT_FIELDS}, "player_id": player_id,
             "external_id": scoped_id(player_id, m.get("external_id"))} for m in matches]
    db.executemany(
        f"INSERT INTO matches ({cols}) VALUES ({values}) "
        f"ON CONFLICT(external_id) DO UPDATE SET {fill}", rows)
    db.commit()
    return count() - before
