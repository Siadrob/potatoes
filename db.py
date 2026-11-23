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


IMPORT_FIELDS = ("played_at", "my_char", "opp_char", "opp_name", "result", "rounds_won",
                 "rounds_lost", "rating", "rating_change", "rank", "opp_rank", "source",
                 "external_id")


def save_imported(db, matches):
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
    rows = [{f: m.get(f) for f in IMPORT_FIELDS} for m in matches]
    db.executemany(
        f"INSERT INTO matches ({cols}) VALUES ({values}) "
        f"ON CONFLICT(external_id) DO UPDATE SET {fill}", rows)
    db.commit()
    return count() - before
