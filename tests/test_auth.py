import sqlite3
import urllib.error

import pytest

from app import create_app
from conftest import ME, login
from db import get_db
from test_app import row, wavu_page

OTHER = "ZZZZyyyyXXXX"


def page_with_title(rows, name="PLS | Sia"):
    return wavu_page(rows).replace("<html>", f"<html><head><title>{name} • Wavu Wank</title></head>")


@pytest.fixture
def make_app(tmp_path):
    def make(**cfg):
        return create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                           "PORTRAITS_DIR": str(tmp_path / "portraits"), **cfg})
    return make


def test_pages_require_identification(make_app):
    client = make_app().test_client()
    for url in ["/", "/stats", "/entrainement", "/plan", "/profil"]:
        r = client.get(url)
        assert r.status_code == 302 and r.headers["Location"].endswith("/connexion")
    page = client.get("/connexion").get_data(as_text=True)
    assert "Entre ton ID Tekken" in page and "Statistiques" not in page   # pas de menu


def test_login_fetches_everything(make_app):
    pages = {ME: page_with_title([row(1795380992, "3-1"), row(1795380900, "1-3", change="-8")])}
    app = make_app(WAVU_FETCH=lambda pid: pages[pid])
    client = app.test_client()
    r = client.post("/connexion", data={"polaris_id": f"https://www.ewgf.gg/player/{ME}"},
                    follow_redirects=True)
    text = r.get_data(as_text=True)
    assert "Bienvenue PLS | Sia" in text and "2 matchs classés lus, 2 nouveaux" in text
    assert '<h1 class="char-title">Leroy</h1>' in text
    with app.app_context():
        player = get_db().execute("SELECT * FROM players").fetchone()
    assert (player["polaris_id"], player["name"]) == (ME, "PLS | Sia")
    assert player["last_import_at"]
    with client.session_transaction() as s:
        assert s["player"] == ME and s.permanent
    assert client.get("/connexion").headers["Location"].endswith("/")   # déjà connecté


def test_login_rejects_unknown_ids(make_app):
    def not_found(pid):
        raise urllib.error.HTTPError("u", 404, "Not Found", {}, None)

    client = make_app(WAVU_FETCH=not_found).test_client()
    r = client.post("/connexion", data={"polaris_id": OTHER})
    assert r.status_code == 400 and "introuvable" in r.get_data(as_text=True)

    client = make_app(WAVU_FETCH=lambda pid: page_with_title([])).test_client()
    r = client.post("/connexion", data={"polaris_id": OTHER})
    assert r.status_code == 400 and "Aucun match classé" in r.get_data(as_text=True)

    client = make_app().test_client()          # réseau coupé, joueur inconnu
    r = client.post("/connexion", data={"polaris_id": OTHER})
    assert r.status_code == 503 and "injoignable" in r.get_data(as_text=True)


def test_known_player_can_log_in_offline(make_app):
    app = make_app()
    login(app, app.test_client())                # le joueur existe déjà
    client = app.test_client()
    r = client.post("/connexion", data={"polaris_id": ME}, follow_redirects=True)
    text = r.get_data(as_text=True)
    assert "Bienvenue Moi" in text and "pas été mis à jour" in text


def test_players_data_is_isolated(make_app):
    pages = {ME: page_with_title([row(1795380992, "3-1")], "Moi"),
             OTHER: page_with_title([row(1795380992, "0-3", left_id=OTHER, left_char="King",
                                         change="-9")], "Autre")}
    app = make_app(WAVU_FETCH=lambda pid: pages[pid])
    me, other = app.test_client(), app.test_client()
    me.post("/connexion", data={"polaris_id": ME})
    other.post("/connexion", data={"polaris_id": OTHER})

    me.post("/matchups/Kazuya", data={"notes": "note secrète"})
    me.post("/plan", data={"category": "autre", "title": "objectif à moi"})

    assert "Leroy" in me.get("/").get_data(as_text=True)
    other_home = other.get("/").get_data(as_text=True)
    assert '<h1 class="char-title">King</h1>' in other_home
    assert "note secrète" not in other.get("/matchups/Kazuya").get_data(as_text=True)
    assert "objectif à moi" not in other.get("/plan").get_data(as_text=True)
    with app.app_context():
        my_match = get_db().execute("SELECT id FROM matches WHERE player_id = ?", (ME,)).fetchone()[0]
        goal = get_db().execute("SELECT id FROM training_goals WHERE player_id = ?", (ME,)).fetchone()[0]
    # On ne peut ni voir, ni modifier, ni supprimer les données d'un autre joueur.
    assert other.get(f"/matchs/{my_match}/modifier").status_code == 404
    assert other.post(f"/matchs/{my_match}/supprimer").status_code == 404
    other.post(f"/plan/{goal}/supprimer")
    assert "objectif à moi" in me.get("/plan").get_data(as_text=True)


def test_logout(make_app):
    app = make_app()
    client = login(app, app.test_client())
    assert client.get("/").status_code == 200
    r = client.post("/deconnexion")
    assert r.headers["Location"].endswith("/connexion")
    assert client.get("/").status_code == 302


def test_home_refreshes_when_stale(make_app):
    calls = []
    app = make_app(WAVU_FETCH=lambda pid: calls.append(pid) or page_with_title([row(1795380992, "3-1")]))
    client = app.test_client()
    client.post("/connexion", data={"polaris_id": ME})
    client.get("/")
    assert calls == [ME]                         # import récent : pas de nouvel appel
    with app.app_context():
        get_db().execute("UPDATE players SET last_import_at = '2020-01-01 00:00:00'")
        get_db().commit()
    client.get("/")
    assert calls == [ME, ME]                     # plus de 6 h : mise à jour automatique


def test_single_player_database_is_migrated(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""
            CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1), name TEXT NOT NULL DEFAULT 'Joueur',
                polaris_id TEXT, main_char TEXT, mains TEXT, goal_rank TEXT, goal_rating INTEGER);
            INSERT INTO profile (id, name, polaris_id, mains, goal_rating) VALUES (1, 'Sia', 'AAAAbbbbCCCC', 'Leroy', 2000);
            CREATE TABLE matches (id INTEGER PRIMARY KEY AUTOINCREMENT, played_at TEXT NOT NULL,
                my_char TEXT NOT NULL, opp_char TEXT NOT NULL, opp_name TEXT, result TEXT NOT NULL,
                rounds_won INTEGER, rounds_lost INTEGER, rank TEXT, opp_rank TEXT, rating INTEGER,
                rating_change INTEGER, notes TEXT, source TEXT NOT NULL DEFAULT 'manuel',
                external_id TEXT UNIQUE, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO matches (played_at, my_char, opp_char, result) VALUES ('2026-11-20', 'Leroy', 'Jin', 'W');
            CREATE TABLE matchup_notes (opp_char TEXT PRIMARY KEY, notes TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
            INSERT INTO matchup_notes (opp_char, notes) VALUES ('Jin', 'attention au df+1');
            CREATE TABLE quiz_sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, mode TEXT NOT NULL, day TEXT NOT NULL,
                my_char TEXT, questions TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, completed_at TEXT);
            CREATE UNIQUE INDEX idx_quiz_daily ON quiz_sessions (day) WHERE mode = 'daily';
            PRAGMA user_version = 1;
        """)
    app = create_app({"TESTING": True, "DATABASE": str(path)})
    with app.app_context():
        db = get_db()
        player = db.execute("SELECT * FROM players").fetchone()
        assert (player["polaris_id"], player["name"], player["mains"], player["goal_rating"]) == \
            (ME, "Sia", "Leroy", 2000)
        assert db.execute("SELECT player_id FROM matches").fetchone()[0] == ME
        assert tuple(db.execute("SELECT player_id, notes FROM matchup_notes").fetchone()) == (ME, "attention au df+1")
    client = login(app, app.test_client())
    assert "attention au df+1" in client.get("/matchups/Jin").get_data(as_text=True)
    create_app({"TESTING": True, "DATABASE": str(path)})      # la migration est rejouable sans erreur


def test_orphan_data_adopted_by_first_player(tmp_path, make_app):
    app = make_app(WAVU_FETCH=lambda pid: page_with_title([row(1795380992, "3-1")]))
    with app.app_context():
        get_db().execute("INSERT INTO matches (played_at, my_char, opp_char, result) "
                         "VALUES ('2026-01-01', 'Bob', 'Jin', 'L')")
        get_db().commit()
    app.test_client().post("/connexion", data={"polaris_id": ME})
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM matches WHERE player_id IS NULL").fetchone()[0] == 0


def test_steam_and_profile_links(make_app):
    html = page_with_title([row(1795380992, "3-1")]).replace(
        "<body>", '<body><a href="https://steamcommunity.com/profiles/76561198018579450">7656…</a>')
    app = make_app(WAVU_FETCH=lambda pid: html)
    client = app.test_client()
    page = client.post("/connexion", data={"polaris_id": ME}, follow_redirects=True).get_data(as_text=True)
    assert "https://steamcommunity.com/profiles/76561198018579450" in page
    assert f"https://www.ewgf.gg/player/{ME}" in page and f"https://wank.wavu.wiki/player/{ME}" in page
    import wavu
    assert wavu.parse_steam_id("rien ici") is None
