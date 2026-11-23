import pytest

import stats
import wavu
from app import create_app
from conftest import ME, login
from db import get_db

WAVU_ROW = """
<tr>
  <td class="battle-at"><time><noscript>x</noscript><script>printDateTime({ts})</script></time></td>
  <td class="left">
    <span class="player"><a href="/player/{left_id}">{left_name}</a></span>
    <span class="char">{left_char}</span>
    <span class="rating">{left_rating}<span class="{left_cls}">{left_change}</span></span>
  </td>
  <td class="result">{score}</td>
  <td class="right">
    <span class="rating">1800<span class="lose">-9</span></span>
    <span class="char">{right_char}</span>
    <span class="player"><a href="/player/{right_id}">Rival</a></span>
  </td>
  <td class="h2h"><a href="/h2h/x/y">h2h</a></td>
</tr>"""


def wavu_page(rows):
    body = "".join(WAVU_ROW.format(**r) for r in rows)
    return f"<html><body><div class='game-list'><table>{body}</table></div></body></html>"


def row(ts, score, left_char="Leroy", right_char="Kazuya", left_id=ME, right_id="OPPxxxxx0001",
        rating=1900, change="+10"):
    return {"ts": ts, "score": score, "left_char": left_char, "right_char": right_char,
            "left_id": left_id, "right_id": right_id, "left_name": "Moi",
            "left_rating": rating, "left_cls": "win" if change.startswith("+") else "lose",
            "left_change": change}


@pytest.fixture
def app(tmp_path):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "test.db")})


@pytest.fixture
def client(app):
    return login(app, app.test_client())


# ---------- stats ----------

def M(result, **kw):
    return {"result": result, "played_at": "2026-01-01", "rank": None, "rating": None,
            "rating_change": None, "my_char": "Leroy", "opp_char": "Jin", **kw}


def test_summary_and_streaks():
    ms = [M("W"), M("W"), M("W"), M("L"), M("D"), M("W"), M("W")]
    s = stats.summary(ms)
    assert (s["total"], s["wins"], s["losses"], s["draws"]) == (7, 5, 1, 1)
    assert s["winrate"] == 71.4
    assert stats.current_streak(ms) == ("W", 2)
    assert stats.best_streak(ms) == 3
    assert stats.current_streak([]) == (None, 0)


def test_worst_matchups_needs_minimum_games():
    ms = [M("L", opp_char="King")] * 5 + [M("W", opp_char="King")] + [M("L", opp_char="Lee")]
    worst = stats.worst_matchups(ms, min_games=5)
    assert [r["name"] for r in worst] == ["King"]
    assert worst[0]["winrate"] == 16.7


def test_rolling_winrate():
    ms = [M("W"), M("L"), M("W"), M("W")]
    assert stats.rolling_winrate(ms, window=2) == [100.0, 50.0, 50.0, 100.0]


def test_rating_history_is_per_character():
    ms = [M("W", rating=1500), M("W", rating=1200, my_char="Bob"), M("L", rating=1490)]
    assert [p["rating"] for p in stats.rating_history(ms, "Leroy")] == [1500, 1490]


# ---------- wavu ----------

def test_extract_polaris_id():
    assert wavu.extract_polaris_id("https://www.ewgf.gg/player/4qLJmf7THeE2") == "4qLJmf7THeE2"
    assert wavu.extract_polaris_id("https://wank.wavu.wiki/player/4qLJmf7THeE2/") == "4qLJmf7THeE2"
    assert wavu.extract_polaris_id(" 4qLJmf7THeE2 ") == "4qLJmf7THeE2"
    assert wavu.extract_polaris_id("pas un id !") is None
    assert wavu.extract_polaris_id("") is None


def test_parse_matches():
    html = wavu_page([
        row(1795380992, "3-1"),
        row(1795380820, "2-3", change="-11", rating=1889),
        row(1795380500, "2-2", change="+0"),
        # Le joueur apparaît à droite : on doit inverser le point de vue.
        row(1795380400, "3-0", left_id="OPPxxxxx0002", right_id=ME,
            left_char="King", right_char="Bob"),
    ])
    ms = wavu.parse_matches(html, ME)
    assert len(ms) == 4
    first = ms[0]
    assert first["played_at"] == "2026-11-22 20:56"
    assert (first["my_char"], first["opp_char"], first["opp_name"]) == ("Leroy", "Kazuya", "Rival")
    assert (first["result"], first["rounds_won"], first["rounds_lost"]) == ("W", 3, 1)
    assert (first["rating"], first["rating_change"]) == (1910, 10)  # rating après le match
    assert ms[1]["result"] == "L" and ms[1]["rating_change"] == -11
    assert ms[2]["result"] == "D"
    swapped = ms[3]
    assert (swapped["my_char"], swapped["opp_char"], swapped["result"]) == ("Bob", "King", "L")
    assert (swapped["rounds_won"], swapped["rounds_lost"]) == (0, 3)


def test_import_route_is_idempotent(tmp_path):
    html = wavu_page([row(1795380992, "3-1"), row(1795380820, "1-3", change="-9"),
                      row(1795380600, "3-2", right_char="Nouveau Perso")])
    calls = []

    def fake_fetch(pid):
        calls.append(pid)
        return html

    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "WAVU_FETCH": fake_fetch})
    client = app.test_client()

    r = client.post("/connexion", data={"polaris_id": f"https://www.ewgf.gg/player/{ME}"},
                    follow_redirects=True)
    assert "wavu : 3 matchs classés lus, 3 nouveaux" in r.get_data(as_text=True)
    r = client.post("/import", follow_redirects=True)
    assert "wavu : 3 matchs classés lus, 0 nouveaux" in r.get_data(as_text=True)
    assert calls == [ME, ME]

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM matches WHERE player_id = ?", (ME,)).fetchone()[0] == 3

    # Un perso inconnu du roster apparaît quand même dans l'app.
    assert client.get("/matchups/Nouveau Perso").status_code == 200
    page = client.get("/").get_data(as_text=True)
    assert "μ 1910" in page


def test_login_rejects_bad_id(app):
    r = app.test_client().post("/connexion", data={"polaris_id": "n'importe quoi"})
    assert r.status_code == 400 and "ID invalide" in r.get_data(as_text=True)


# ---------- pages ----------

def test_empty_pages(client):
    assert "Importe tes matchs" in client.get("/").get_data(as_text=True)
    r = client.get("/stats")
    assert r.status_code == 200
    assert "Aucun match" in r.get_data(as_text=True)


def test_add_edit_delete_match(client, app):
    r = client.post("/matchs/nouveau", data={
        "played_at": "2026-11-20", "my_char": "Leroy", "opp_char": "Jin",
        "result": "W", "rounds_won": "3", "rounds_lost": "1", "rank": "Garyu",
        "notes": "bien punir le 1+2"}, follow_redirects=True)
    assert "Match enregistré" in r.get_data(as_text=True)

    with app.app_context():
        match_id = get_db().execute("SELECT id FROM matches").fetchone()[0]

    page = client.get("/").get_data(as_text=True)
    assert "Garyu" in page and "100.0 %" in page and "LEROY" not in page

    # Le formulaire suivant reprend le perso et le rang.
    form = client.get("/matchs/nouveau").get_data(as_text=True)
    assert "<option selected>Leroy</option>" in form
    assert "<option selected>Garyu</option>" in form

    r = client.post(f"/matchs/{match_id}/modifier", data={
        "played_at": "2026-11-20", "my_char": "Leroy", "opp_char": "Jin", "result": "L"},
        follow_redirects=True)
    assert "Match modifié" in r.get_data(as_text=True)

    client.post(f"/matchs/{match_id}/supprimer")
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_invalid_match_is_rejected(client, app):
    r = client.post("/matchs/nouveau", data={
        "played_at": "pas une date", "my_char": "Inconnu", "opp_char": "Jin", "result": "X",
        "rounds_won": "9"})
    text = r.get_data(as_text=True)
    assert "Date invalide" in text and "Choisis ton personnage" in text
    assert "victoire, défaite ou nul" in text and "entre 0 et 5" in text
    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 0


def test_matchup_notes(client):
    client.post("/matchups/King", data={"notes": "Attention aux chain throws"})
    assert "Attention aux chain throws" in client.get("/matchups/King").get_data(as_text=True)
    assert client.get("/matchups/PasUnPerso").status_code == 404


def test_profile(client):
    r = client.post("/profil", data={"name": "Sia", "mains": ["Bob", "Leroy"], "goal_rank": "Tekken King",
                                     "goal_rating": "2000"},
                    follow_redirects=True)
    assert "Bienvenue Sia" in r.get_data(as_text=True)
    assert client.post("/profil", data={"goal_rating": "beaucoup"}).status_code == 400


@pytest.mark.parametrize("url", ["/", "/stats", "/matchs", "/matchups", "/import", "/profil",
                                 "/matchs/nouveau", "/matchs?perso=Leroy&adversaire=Jin&page=2"])
def test_pages_render(client, url):
    assert client.get(url).status_code == 200


# ---------- tableau de bord ----------

def test_activity_calendar():
    from datetime import date
    ms = [M("W", played_at="2026-11-20 10:00"), M("L", played_at="2026-11-20 11:00"),
          M("W", played_at="2026-11-18"), M("W", played_at="2026-01-01")]
    act = stats.activity(ms, date(2026, 11, 23), weeks=13)
    assert len(act["columns"]) == 13
    assert all(len(c["cells"]) == 7 for c in act["columns"])
    assert act["columns"][-1]["cells"][0]["day"] == "2026-11-23"  # lundi de la dernière semaine
    cells = {c["day"]: c for col in act["columns"] for c in col["cells"]}
    assert cells["2026-11-20"]["total"] == 2 and cells["2026-11-20"]["cls"] == "h4"
    assert cells["2026-11-24"]["future"]
    # Le match de janvier est hors de la fenêtre.
    assert (act["total"], act["active_days"], act["per_day"]) == (3, 2, 1.5)


def test_matchup_chart_sorted_and_colored():
    ms = ([M("W", opp_char="King")] * 3 + [M("L", opp_char="Jin")] * 3
          + [M("W", opp_char="Lee"), M("L", opp_char="Lee")] + [M("W", opp_char="Kuma")])
    rows, hidden = stats.matchup_chart(ms, min_games=2)
    assert [(r["name"], r["cls"]) for r in rows] == [("King", "hi"), ("Lee", "mid"), ("Jin", "lo")]
    assert hidden == 1


def test_dashboard_focuses_on_mains(tmp_path):
    html = wavu_page([row(1795380992, "3-1"), row(1795380900, "3-0"),
                      row(1795380800, "1-3", left_char="Bob", rating=1430, change="-8")])
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "WAVU_FETCH": lambda pid: html})
    client = app.test_client()
    client.post("/connexion", data={"polaris_id": ME})
    client.post("/profil", data={"name": "Sia", "mains": ["Bob", "Leroy"]})

    page = client.get("/stats").get_data(as_text=True)
    # Leroy (le plus joué) est sélectionné par défaut, puis Bob.
    assert '<h1 class="section-title">Leroy</h1>' in page
    assert page.index('class="chip-name">Leroy') < page.index('class="chip-name">Bob')
    assert "μ 1422" in page

    bob = client.get("/stats?perso=Bob").get_data(as_text=True)
    assert '<h1 class="section-title">Bob</h1>' in bob
    assert "Tous les persos</h1>" in client.get("/stats?perso=tous").get_data(as_text=True)

    day = client.get("/matchs?jour=2026-11-22&perso=Leroy").get_data(as_text=True)
    assert "2 matchs" in day


def test_old_database_is_migrated(tmp_path):
    import sqlite3
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as conn:
        conn.executescript("""CREATE TABLE profile (id INTEGER PRIMARY KEY CHECK (id = 1),
            name TEXT NOT NULL DEFAULT 'Joueur', polaris_id TEXT, main_char TEXT,
            goal_rank TEXT, goal_rating INTEGER);
            INSERT INTO profile (id, main_char) VALUES (1, 'Leroy');""")
    app = create_app({"TESTING": True, "DATABASE": str(path)})
    with app.app_context():
        assert get_db().execute("SELECT mains FROM profile").fetchone()[0] == "Leroy"


# ---------- ewgf ----------

def battle(ts_iso, p1_id, p2_id, winner, battle_type="RANKED_BATTLE", p1_char="Leroy", p2_char="Kazuya"):
    return {"battle_at": ts_iso, "battle_type": battle_type, "winner": winner,
            "p1_tekken_id": p1_id, "p1_name": "A", "p1_char": p1_char, "p1_dan_rank": "God of Destruction IV",
            "p1_rounds_won": 3 if winner == 1 else 1,
            "p2_tekken_id": p2_id, "p2_name": "B", "p2_char": p2_char, "p2_dan_rank": "Tekken God",
            "p2_rounds_won": 3 if winner == 2 else 1}


def test_parse_ewgf_battles_keeps_ranked_only():
    import ewgf
    ms = ewgf.parse_battles([
        battle("2026-11-22T20:56:32Z", ME, "OPPxxxxx0001", 1),
        battle("2026-11-22T20:50:00Z", "OPPxxxxx0002", ME, 1, p1_char="King", p2_char="Bob"),
        battle("2026-11-22T20:40:00Z", ME, "OPPxxxxx0003", 1, battle_type="QUICK_BATTLE"),
    ], ME)
    assert len(ms) == 2
    assert (ms[0]["result"], ms[0]["rank"], ms[0]["opp_rank"]) == ("W", "God of Destruction IV", "Tekken God")
    assert ms[0]["external_id"] == "battle:1795380992:OPPxxxxx0001"
    assert (ms[1]["my_char"], ms[1]["opp_char"], ms[1]["result"]) == ("Bob", "King", "L")
    assert ms[1]["rank"] == "Tekken God"


def test_import_merges_wavu_and_ewgf(tmp_path):
    html = wavu_page([row(1795380992, "3-1")])
    battles = [battle("2026-11-22T20:56:32Z", ME, "OPPxxxxx0001", 1),      # même match que wavu
               battle("2026-11-21T10:00:00Z", ME, "OPPxxxxx0009", 2)]     # absent de wavu
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "WAVU_FETCH": lambda pid: html,
                      "EWGF_FETCH": lambda pid, key: battles, "EWGF_API_KEY": "ewgf_test"})
    client = app.test_client()
    text = client.post("/connexion", data={"polaris_id": ME}, follow_redirects=True).get_data(as_text=True)
    assert "ewgf : 2 matchs classés lus (rangs Dan), 1 nouveaux" in text
    with app.app_context():
        rows = get_db().execute("SELECT rating, rank, opp_rank FROM matches ORDER BY played_at DESC").fetchall()
    assert [tuple(r) for r in rows] == [(1910, "God of Destruction IV", "Tekken God"),
                                         (None, "God of Destruction IV", "Tekken God")]
    assert "God of Destruction IV" in client.get("/").get_data(as_text=True)


def test_ewgf_error_is_reported(tmp_path):
    import ewgf

    def failing(pid, key):
        raise ewgf.EwgfError("invalid_api_key", "Invalid API key")

    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "WAVU_FETCH": lambda pid: wavu_page([]),
                      "EWGF_FETCH": failing, "EWGF_API_KEY": "ewgf_bad"})
    client = login(app, app.test_client())
    text = client.post("/import", follow_redirects=True).get_data(as_text=True)
    assert "invalid_api_key" in text


# ---------- accueil / progression ----------

def test_rating_delta_and_weekly():
    pts = [{"date": "2026-11-01 10:00", "rating": 1500, "change": 10},
           {"date": "2026-11-10 10:00", "rating": 1540, "change": 8},
           {"date": "2026-11-20 10:00", "rating": 1520, "change": -9}]
    assert stats.rating_delta(pts, "2026-11-15") == -20
    assert stats.rating_delta(pts, "2026-10-01") == 30   # 1520 - (1500 - 10)
    assert stats.daily_rating(pts + [{"date": "2026-11-20 22:00", "rating": 1530}])[-1] == \
        {"date": "2026-11-20", "rating": 1530}
    ms = [M("W", played_at="2026-11-16 10:00", rating=1500, rating_change=10),   # lundi
          M("L", played_at="2026-11-22 10:00", rating=1490, rating_change=-10),  # dimanche
          M("W", played_at="2026-11-23 10:00", rating=1501, rating_change=11)]   # lundi suivant
    weeks = stats.weekly(ms)
    assert [(w["start"], w["total"], w["rating_delta"], w["rating_end"]) for w in weeks] == \
        [("2026-11-23", 1, 11, 1501), ("2026-11-16", 2, 0, 1490)]


def test_home_shows_most_played_character(tmp_path):
    html = wavu_page([row(1795380992, "3-1"), row(1795380900, "3-0", rating=1890),
                      row(1795380800, "1-3", left_char="Bob", rating=1430, change="-8")])
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "PORTRAITS_DIR": str(tmp_path / "portraits"),
                      "WAVU_FETCH": lambda pid: html})
    client = app.test_client()
    client.post("/connexion", data={"polaris_id": ME})
    page = client.get("/").get_data(as_text=True)
    assert '<h1 class="char-title">Leroy</h1>' in page
    assert "μ 1910" in page and 'class="hero-ghost"' in page
    bob = client.get("/?perso=Bob").get_data(as_text=True)
    assert '<h1 class="char-title">Bob</h1>' in bob
    assert client.get("/?perso=Kuma").status_code == 404


def test_portrait_upload(tmp_path):
    import io
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "PORTRAITS_DIR": str(tmp_path / "portraits")})
    client = login(app, app.test_client())
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 100

    r = client.post("/portrait/Armor King", data={"image": (io.BytesIO(b"<script>"), "x.png")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert "Format non reconnu" in r.get_data(as_text=True)
    assert client.get("/portrait/Armor King").status_code == 404

    client.post("/portrait/Armor King", data={"image": (io.BytesIO(png), "ak.png")},
                content_type="multipart/form-data")
    assert (tmp_path / "portraits" / "armor-king.png").exists()
    r = client.get("/portrait/Armor King")
    assert r.status_code == 200 and r.data == png

    client.post("/portrait/Armor King/supprimer")
    assert client.get("/portrait/Armor King").status_code == 404
    assert client.post("/portrait/PasUnPerso", data={}).status_code == 404


def test_portrait_from_url(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\1" * 50
    seen = []
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "PORTRAITS_DIR": str(tmp_path / "portraits"),
                      "PORTRAIT_DOWNLOAD": lambda url: seen.append(url) or png})
    client = login(app, app.test_client())
    client.post("/portrait/Leroy", data={"url": "https://exemple.org/leroy.png"})
    assert seen == ["https://exemple.org/leroy.png"]
    assert client.get("/portrait/Leroy").data == png
    r = client.post("/portrait/Leroy", data={}, follow_redirects=True)
    assert "Choisis une image" in r.get_data(as_text=True)


def test_portrait_download_rejects_non_http():
    import portraits
    with pytest.raises(ValueError, match="http"):
        portraits.download("file:///etc/passwd")


def test_official_illustration_fetched_once(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\2" * 40
    calls = []

    def official(char):
        calls.append(char)
        if char == "Bob":
            raise ValueError("introuvable")
        return png

    html = wavu_page([row(1795380992, "3-1"), row(1795380800, "1-3", left_char="Bob", change="-8")])
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "PORTRAITS_DIR": str(tmp_path / "portraits"),
                      "WAVU_FETCH": lambda pid: html, "PORTRAIT_OFFICIAL": official})
    client = app.test_client()
    client.post("/connexion", data={"polaris_id": ME})

    page = client.get("/?perso=Leroy").get_data(as_text=True)
    assert 'class="hero-art"' in page
    client.get("/?perso=Leroy")
    assert client.get("/portrait/Leroy").data == png

    assert 'class="hero-ghost"' in client.get("/?perso=Bob").get_data(as_text=True)
    client.get("/?perso=Bob")           # l'échec est mémorisé : pas de nouvel essai
    assert calls == ["Leroy", "Bob"]

    r = client.post("/portrait/Bob/officiel", follow_redirects=True)   # nouvel essai manuel
    assert "Impossible de récupérer" in r.get_data(as_text=True)
    assert calls == ["Leroy", "Bob", "Bob"]


def test_official_candidates():
    import portraits
    assert portraits.official_candidates("Leroy") == ["leroy-smith", "leroy"]
    assert portraits.official_candidates("Armor King") == ["armor-king"]


def test_original_image_url():
    import portraits
    og = ("https://static.bandainamcoent.eu/styles/og_image_1200x630/s3/high/tekken/tekken-8/"
          "02-characters/new-gallery/Wide/Leroy-Smith_new.png?itok=uYR3mROF")
    assert portraits.original_image_url(og) == (
        "https://static.bandainamcoent.eu/high/tekken/tekken-8/02-characters/new-gallery/Wide/Leroy-Smith_new.png")


def test_period_rating_delta_ignores_rounding():
    # wavu arrondit chaque gain : la somme (+10 +10 = +20) ne colle pas à l'écart réel (+19).
    ms = [M("W", played_at="2026-11-23 10:00", rating=1510, rating_change=10),
          M("W", played_at="2026-11-23 11:00", rating=1519, rating_change=10)]
    assert stats.period_rating_delta(ms) == 19
    assert stats.weekly(ms)[0]["rating_delta"] == 19
    assert stats.sessions(ms)[0]["rating_delta"] == 19
    assert stats.period_rating_delta([M("W")]) is None
