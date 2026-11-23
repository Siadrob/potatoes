import re

import pytest

import widgets
from app import create_app
from conftest import ME, login
from db import get_db

OTHER = "ZZZZyyyyXXXX"


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "PORTRAITS_DIR": str(tmp_path / "portraits")})
    with app.app_context():
        db = get_db()
        rows = [(ME, f"2026-11-{d:02d} 1{i}:00", "Leroy", opp, res, 1900 + d + i, 5)
                for d in range(1, 23) for i, (opp, res) in enumerate([("King", "L"), ("Jin", "W"), ("Lee", "W")])]
        rows += [(ME, "2026-11-20 20:00", "Bob", "Kuma", "W", 1400, 8)]
        db.executemany("INSERT INTO matches (player_id, played_at, my_char, opp_char, result, rating, "
                       "rating_change) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
        db.execute("INSERT INTO training_goals (player_id, category, opp_char, title, status) "
                   "VALUES (?, 'punish', 'King', 'Punir le f+2 de King', 'doing')", (ME,))
        cur = db.execute("INSERT INTO quiz_sessions (player_id, mode, day, my_char, questions, completed_at) "
                         "VALUES (?, 'libre', '2026-11-22', 'Leroy', '[]', '2026-11-22')", (ME,))
        db.executemany("INSERT INTO quiz_answers (session_id, idx, opp_char, move_id, kind, given, expected, correct) "
                       "VALUES (?, ?, 'King', 'King-1', 'bracket', 'x', 'y', ?)",
                       [(cur.lastrowid, i, i % 2) for i in range(4)])
        db.commit()
    return app


@pytest.fixture
def client(app):
    return login(app, app.test_client())


def widget_ids(html):
    return re.findall(r'class="card widget w-(\w)" data-id="(\w+)"', html)


def test_normalize():
    assert widgets.normalize("n'importe quoi") == []
    assert widgets.normalize([
        {"id": "week", "size": "l"},          # taille interdite -> taille par défaut
        {"id": "inconnu", "size": "s"},       # widget inconnu -> ignoré
        {"id": "week", "size": "s"},          # doublon -> ignoré
        "pas un dict",
        {"id": "matchup_chart", "size": "m"},
    ]) == [{"id": "week", "size": "s"}, {"id": "matchup_chart", "size": "m"}]
    assert widgets.normalize(widgets.DEFAULT_LAYOUT) == widgets.DEFAULT_LAYOUT
    for wid, w in widgets.CATALOG.items():
        assert w.default_size in w.sizes, wid


def test_default_layout(client):
    html = client.get("/").get_data(as_text=True)
    assert [wid for _, wid in widget_ids(html)] == [w["id"] for w in widgets.DEFAULT_LAYOUT]
    # Les widgets masqués sont proposés dans le catalogue.
    for wid in ("activity", "matchup_chart", "margins", "characters"):
        assert f'class="catalog-item" data-id="{wid}"' in html


def test_every_widget_renders(client):
    layout = [{"id": wid, "size": w.sizes[-1]} for wid, w in widgets.CATALOG.items()]
    r = client.post("/widgets", json={"layout": layout})
    assert r.status_code == 200 and len(r.get_json()["layout"]) == len(widgets.CATALOG)
    html = client.get("/").get_data(as_text=True)
    assert len(widget_ids(html)) == len(widgets.CATALOG)
    assert "Tous les widgets sont affichés" in html
    for text in ("Punir le f+2 de King",          # plan
                 "jours actifs".capitalize(),      # calendrier
                 "progressChart",                  # courbe
                 'class="mu-col"',                 # analyse des matchups
                 "À récupérer",                    # marges de progression
                 'class="know-row"',               # connaissance des frames
                 'class="char-row active"'):       # mes persos
        assert text in html, text


def test_save_order_sizes_and_reset(app, client):
    client.post("/widgets", json={"layout": [{"id": "plan", "size": "l"}, {"id": "week", "size": "m"},
                                             {"id": "nope", "size": "s"}]})
    html = client.get("/").get_data(as_text=True)
    assert widget_ids(html) == [("l", "plan"), ("m", "week")]
    with app.app_context():
        assert "nope" not in get_db().execute("SELECT layout FROM players").fetchone()[0]

    client.post("/widgets", json={"layout": []})
    assert "Aucun widget affiché" in client.get("/").get_data(as_text=True)

    r = client.post("/widgets/reinitialiser", follow_redirects=True)
    assert [wid for _, wid in widget_ids(r.get_data(as_text=True))] == [w["id"] for w in widgets.DEFAULT_LAYOUT]


def test_layout_is_per_player(app, client):
    client.post("/widgets", json={"layout": [{"id": "plan", "size": "s"}]})
    with app.app_context():
        db = get_db()
        db.execute("INSERT INTO matches (player_id, played_at, my_char, opp_char, result) "
                   "VALUES (?, '2026-11-20', 'King', 'Jin', 'W')", (OTHER,))
        db.commit()
    other = login(app, app.test_client(), pid=OTHER, name="Autre")
    html = other.get("/").get_data(as_text=True)
    assert [wid for _, wid in widget_ids(html)] == [w["id"] for w in widgets.DEFAULT_LAYOUT]


def test_widgets_endpoints_require_login(app):
    anon = app.test_client()
    assert anon.post("/widgets", json={"layout": []}).status_code == 302
