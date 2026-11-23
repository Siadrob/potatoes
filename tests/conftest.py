from db import get_db

ME = "AAAAbbbbCCCC"


def login(app, client, pid=ME, name="Moi"):
    """Connecte un joueur sans passer par wavu (aucun accès réseau)."""
    with app.app_context():
        db = get_db()
        db.execute("INSERT OR IGNORE INTO players (polaris_id, name, last_import_at) "
                   "VALUES (?, ?, datetime('now'))", (pid, name))
        db.commit()
    with client.session_transaction() as s:
        s["player"] = pid
    return client
