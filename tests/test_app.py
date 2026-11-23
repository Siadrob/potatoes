import pytest

import stats
import wavu
from app import create_app
from db import get_db

ME = "AAAAbbbbCCCC"

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
    return app.test_client()


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
    assert (first["rating"], first["rating_change"]) == (1900, 10)
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

    r = client.post("/import", data={"polaris_id": f"https://www.ewgf.gg/player/{ME}"},
                    follow_redirects=True)
    assert "3 matchs lus, 3 nouveaux" in r.get_data(as_text=True)
    r = client.post("/import", data={"polaris_id": ME}, follow_redirects=True)
    assert "3 matchs lus, 0 nouveaux" in r.get_data(as_text=True)
    assert calls == [ME, ME]

    with app.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 3
        assert get_db().execute("SELECT polaris_id FROM profile").fetchone()[0] == ME

    # Un perso inconnu du roster apparaît quand même dans l'app.
    assert client.get("/matchups/Nouveau Perso").status_code == 200
    page = client.get("/").get_data(as_text=True)
    assert "Rating Leroy" in page


def test_import_rejects_bad_id(client):
    r = client.post("/import", data={"polaris_id": "n'importe quoi"}, follow_redirects=True)
    assert "ID joueur invalide" in r.get_data(as_text=True)


# ---------- pages ----------

def test_empty_dashboard(client):
    r = client.get("/")
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
    assert "Garyu" in page and "100.0 %" in page

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
    r = client.post("/profil", data={"name": "Sia", "main_char": "Leroy", "goal_rank": "Tekken King",
                                     "goal_rating": "2000",
                                     "polaris_id": "https://www.ewgf.gg/player/4qLJmf7THeE2"},
                    follow_redirects=True)
    assert "Salut Sia" in r.get_data(as_text=True)
    assert client.post("/profil", data={"goal_rating": "beaucoup"}).status_code == 400


@pytest.mark.parametrize("url", ["/", "/matchs", "/matchups", "/import", "/profil",
                                 "/matchs/nouveau", "/matchs?perso=Leroy&adversaire=Jin&page=2"])
def test_pages_render(client, url):
    assert client.get(url).status_code == 200
