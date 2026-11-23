import json
import re

import pytest

import startgg
import tournaments
import widgets
from app import create_app
from conftest import ME, login
from db import get_db

OWNER = {"id": 11, "slug": "user/97b1b8ce", "player": {"id": 44, "gamerTag": "Moi", "prefix": "PLS |"},
         "images": [{"url": "https://images.start.gg/a.jpg", "type": "profile"}]}
FRIEND = {"id": 12, "slug": "user/0a0b0c0d", "player": {"id": 45, "gamerTag": "Pote", "prefix": ""}, "images": []}


def tourney_set(sid, won, my, opp, round_text="Winners Round 1", game=49783, opp_id=90, ts=1795353361,
                display=None):
    me_slot = {"standing": {"stats": {"score": {"value": my}}},
               "entrant": {"id": 1, "name": "PLS | Moi", "participants": [{"player": {"id": 44}}]}}
    opp_slot = {"standing": {"stats": {"score": {"value": opp}}},
                "entrant": {"id": 2, "name": f"Rival{opp_id}", "participants": [{"player": {"id": opp_id}}]}}
    return {"id": sid, "fullRoundText": round_text, "winnerId": 1 if won else 2, "completedAt": ts,
            "displayScore": display, "slots": [opp_slot, me_slot],
            "event": {"id": 1, "name": "T8", "videogame": {"id": game},
                      "tournament": {"name": "Ranking #1409", "slug": "tournament/ranking-1409"}}}


EVENTS = [
    {"id": 1, "name": "Ranking Tekken 8", "slug": "tournament/ranking-1409/event/r", "numEntrants": 12,
     "startAt": 1792274400, "isOnline": False, "state": "COMPLETED",
     "tournament": {"name": "Ranking #1409", "slug": "tournament/ranking-1409", "city": "Lyon", "countryCode": "FR"},
     "userEntrant": {"standing": {"placement": 2}}},
    {"id": 2, "name": "Heatwave", "slug": "tournament/heatwave-4/event/h", "numEntrants": 115,
     "startAt": 1795352400, "isOnline": True, "state": "COMPLETED",
     "tournament": {"name": "HEATWAVE #4", "slug": "tournament/heatwave-4", "city": None, "countryCode": None},
     "userEntrant": {"standing": {"placement": 65}}},
]
SETS = [
    tourney_set(1, True, 2, 1, opp_id=90),
    tourney_set(2, False, 0, 2, "Losers Round 2", opp_id=90),
    tourney_set(3, True, 0, -1, display="DQ", opp_id=91),          # victoire par forfait : exclue
    tourney_set(4, True, 2, 0, game=1386),                           # autre jeu : ignoré
    tourney_set(5, False, 1, 2, "Losers Round 1", opp_id=92),
]


class FakeStartGG:
    def __init__(self):
        self.calls = []

    def __call__(self, query, variables=None):
        variables = variables or {}
        kind = ("currentUser" if "currentUser" in query else "events" if "events(" in query
                else "sets" if "sets(" in query else "upcoming" if "tournaments(" in query else "user")
        self.calls.append(kind)
        if kind == "currentUser":
            return {"currentUser": OWNER}
        if kind == "user":
            return {"user": {"user/97b1b8ce": OWNER, "user/0a0b0c0d": FRIEND}.get(variables["slug"])}
        if kind == "events":
            return {"user": {"events": {"pageInfo": {"totalPages": 1}, "nodes": EVENTS}}}
        if kind == "sets":
            return {"player": {"sets": {"pageInfo": {"totalPages": 1}, "nodes": SETS}}}
        return {"user": {"tournaments": {"nodes": [
            {"name": "Next Up", "slug": "tournament/next-up", "startAt": 1796000000, "city": None,
             "isOnline": True, "numAttendees": 40}]}}}


@pytest.fixture
def fake():
    return FakeStartGG()


@pytest.fixture
def app(tmp_path, fake):
    return create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                       "STARTGG_TOKEN": "x", "STARTGG_RUN": fake})


@pytest.fixture
def client(app):
    return login(app, app.test_client(), name="PLS | Moi")


# ---------- client start.gg ----------

def test_parse_slug():
    assert startgg.parse_slug("https://www.start.gg/user/97b1b8ce/details") == "user/97b1b8ce"
    assert startgg.parse_slug("user/97B1B8CE") == "user/97b1b8ce"
    assert startgg.parse_slug("97b1b8ce") == "user/97b1b8ce"
    assert startgg.parse_slug("pas un profil") is None


def test_parse_set_and_stats():
    parsed = [startgg.parse_set(s, 44) for s in SETS]
    assert parsed[3] is None                                     # autre jeu
    win = parsed[0]
    assert (win["won"], win["my_score"], win["opp_score"], win["opponent"], win["bracket"]) == \
        (True, 2, 1, "Rival90", "winners")
    assert parsed[2]["dq"] and parsed[2]["my_score"] is None
    sets = [s for s in parsed if s]
    s = tournaments.summary([startgg.parse_event(e) for e in EVENTS], sets)
    assert (s["sets"], s["set_wins"], s["set_losses"], s["dq"]) == (3, 1, 2, 1)
    assert (s["games_won"], s["games_lost"]) == (3, 5)
    assert s["best"]["placement"] == 2 and s["avg_top"] == round((17 + 57) / 2)
    b = tournaments.brackets(sets)
    assert b["winners"] == {"wins": 1, "losses": 0, "rate": 100.0}
    assert b["losers"]["losses"] == 2
    rivals = tournaments.rivals(sets)
    assert rivals[0]["name"] == "Rival90" and (rivals[0]["wins"], rivals[0]["losses"]) == (1, 1)


# ---------- pages ----------

def test_no_token(tmp_path):
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db")})
    page = login(app, app.test_client()).get("/tournois").get_data(as_text=True)
    assert "STARTGG_TOKEN" in page


def test_link_suggests_token_owner_when_names_match(client, app):
    page = client.get("/tournois").get_data(as_text=True)
    assert "Lie ton compte start.gg" in page and "C'est moi" in page
    other = login(app, app.test_client(), pid="ZZZZyyyyXXXX", name="Quelqu'un")
    assert "C'est moi" not in other.get("/tournois").get_data(as_text=True)


def test_link_owner_then_dashboard(client, fake):
    r = client.post("/tournois/lier", data={"owner": "1"}, follow_redirects=True)
    html = r.get_data(as_text=True)
    assert "Compte start.gg lié : PLS | Moi" in html
    assert "Ranking #1409" in html and "HEATWAVE #4" in html          # derniers tournois
    assert "placementChart" in html and "Rival90" in html             # courbe, sets, adversaires
    assert "33.3 %" in html                                           # 1 set gagné sur 3 (forfait exclu)
    assert "https://www.start.gg/user/97b1b8ce" in html
    fetches = fake.calls.count("events")
    client.get("/tournois")
    assert fake.calls.count("events") == fetches                      # cache : pas de nouvel appel
    client.post("/tournois/actualiser")
    assert fake.calls.count("events") == fetches + 1


def test_link_by_url_and_unlink(client, app):
    r = client.post("/tournois/lier", data={"profile": "https://www.start.gg/user/0a0b0c0d"},
                    follow_redirects=True)
    assert "Compte start.gg lié : Pote" in r.get_data(as_text=True)
    r = client.post("/tournois/lier", data={"profile": "n'importe quoi"}, follow_redirects=True)
    assert "Adresse start.gg invalide" in r.get_data(as_text=True)
    r = client.post("/tournois/lier", data={"profile": "user/ffffffff"}, follow_redirects=True)
    assert "introuvable" in r.get_data(as_text=True)
    client.post("/tournois/delier")
    with app.app_context():
        assert get_db().execute("SELECT startgg FROM players WHERE polaris_id = ?", (ME,)).fetchone()[0] is None
    assert "Lie ton compte start.gg" in client.get("/tournois").get_data(as_text=True)


def test_startgg_error_is_reported(tmp_path):
    def failing(query, variables=None):
        raise startgg.StartGGError("token start.gg invalide ou expiré")

    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "STARTGG_TOKEN": "x", "STARTGG_RUN": failing})
    client = login(app, app.test_client())
    with app.app_context():
        get_db().execute("UPDATE players SET startgg = ?", (json.dumps(startgg._identity(OWNER)),))
        get_db().commit()
    html = client.get("/tournois").get_data(as_text=True)
    assert "token start.gg invalide" in html and "Réessayer" in html


def test_tournament_widgets_board(client):
    client.post("/tournois/lier", data={"owner": "1"})
    every = [{"id": wid, "size": w.sizes[-1]} for wid, w in widgets.TOURNAMENT_CATALOG.items()]
    assert client.post("/widgets?board=tournois", json={"layout": every}).status_code == 200
    html = client.get("/tournois").get_data(as_text=True)
    ids = re.findall(r'class="card widget w-\w" data-id="(\w+)"', html)
    assert ids == list(widgets.TOURNAMENT_CATALOG)
    assert "Next Up" in html and "Forfaits" in html                   # à venir, bilan
    # La disposition des tournois ne touche pas celle de l'accueil.
    home = client.get("/").get_data(as_text=True)
    assert "t_recent" not in home
    assert client.post("/widgets?board=nope", json={"layout": []}).status_code == 400
    r = client.post("/widgets/reinitialiser?board=tournois", follow_redirects=True)
    ids = re.findall(r'class="card widget w-\w" data-id="(\w+)"', r.get_data(as_text=True))
    assert ids == [w["id"] for w in widgets.TOURNAMENT_LAYOUT]
