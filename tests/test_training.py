import json
from datetime import date

import pandas as pd
import pytest

import framedata as fd
import training
from app import create_app
from conftest import ME, login
from db import get_db


def mv(char, cmd, target, startup, block, damage="10", hit="+2", parent=None, inp=None, notes="",
       video=None, name=""):
    return {"id": f"{char}-{cmd}", "name": name, "input": inp if inp is not None else cmd,
            "parent": f"{char}-{parent}" if parent else None, "target": target, "damage": damage,
            "startup": f"i{startup}", "block": block, "hit": hit, "ch": None, "crush": None,
            "notes": notes, "video": video}


ME_MOVES = [
    mv("Leroy", "1", "h", 10, "+1", "5"),
    mv("Leroy", "1,2", ",h", 12, "-1", ",12", parent="1", inp=",2", notes="Combo from 1st hit"),
    mv("Leroy", "df+1", "m", 13, "-3", "14"),
    mv("Leroy", "1+3", "t", 12, "", "35"),                               # chope : jamais punisseur
    mv("Leroy", "df+2,1+2", "m", 15, "-14", "22", hit="+33a (+23)"),     # pas un enfant : commande directe
    mv("Leroy", "ws2", "m", 15, "-13", "21", hit="[[Leroy_combos#Staples|+51a]]"),
    mv("Leroy", "ws4", "m", 11, "-5", "16"),
]
OPP_MOVES = [
    mv("King", "1", "h", 10, "+1", video="File:t8-p2-king-1.mp4", name="Dragon&#039;s Jab"),
    mv("King", "df+2", "m", 15, "-13", "15"),
    mv("King", "d+4", "l", 16, "-12", "8"),
    mv("King", "f+2", "h", 14, "-17", "20"),
    mv("King", "b+1", "m", 13, "-4"),
    mv("King", "b+2", "m", 16, "-8"),
    mv("King", "uf+2", "m", 18, "+3"),
    mv("King", "db+3", "l", 20, "-11~-10"),
    mv("King", "2+4", "t", 12, ""),
    mv("King", "d+1", "s", 10, "-5"),
    mv("King", "f+1+2", "m", 17, "-9"),
    mv("King", "b+4", "m", 19, "-12"),
]
FAKE = {"Leroy": ME_MOVES, "King": OPP_MOVES, "Jin": [mv("Jin", "df+1", "m", 13, "-12")]}


def test_to_frame_parses_and_builds_commands():
    df = fd.to_frame(ME_MOVES, "Leroy")
    row = df.set_index("command").loc["1,2"]
    assert row["parent"] == "Leroy-1" and not row["is_root"]
    assert (row["startup"], row["block"], row["damage"]) == (12, -1, 12)
    assert df.set_index("command").loc["ws2", "launcher"]
    assert not df.set_index("command").loc["df+1", "launcher"]
    assert fd.first_int("-11~-10") == -11 and fd.first_int("") is None
    assert fd.total_damage("10,14 (9)") == 24
    assert fd.clean_notes("&lt;div&gt;\n* Jails\n* Combo from 1st hit\n&lt;/div&gt;") == "Jails · Combo from 1st hit"


def test_punishers_and_sheet():
    me = fd.to_frame(ME_MOVES, "Leroy")
    pun = fd.punishers(me)
    assert "1+3" not in set(pun["command"])                 # pas de chope
    combo = pun.set_index("command").loc["1,2"]
    assert (combo["startup"], combo["damage"]) == (10, 17)  # 5 + 12, vitesse du jab
    assert fd.best_punisher(pun, 10)["command"] == "1,2"
    assert fd.best_punisher(pun, 15)["command"] == "df+2,1+2"     # lanceur prioritaire
    assert fd.best_punisher(pun, 12, "ws")["command"] == "ws4"
    assert fd.best_punisher(pun, 9) is None

    sheet = fd.punish_sheet(fd.to_frame(OPP_MOVES, "King"), me).set_index("command")
    assert set(sheet.index) == {"f+2", "df+2", "d+4", "b+4", "db+3"}
    assert sheet.loc["d+4", "punish_kind"] == "ws" and sheet.loc["d+4", "punisher"] == "ws4"
    assert sheet.loc["f+2", "punisher"] == "df+2,1+2"
    assert sheet.loc["db+3", "frames"] == 11


def test_cache(tmp_path):
    import sqlite3
    calls = []
    conn = sqlite3.connect(tmp_path / "f.db")
    fetch = lambda c: calls.append(c) or FAKE[c]
    a = fd.load(conn, "King", fetch=fetch)
    b = fd.load(conn, "King", fetch=fetch)
    assert calls == ["King"] and len(a) == len(b) == len(OPP_MOVES)
    assert b["block"].dtype == "Int64" and b["is_root"].dtype == bool
    fd.load(conn, "King", fetch=fetch, force=True)
    assert calls == ["King", "King"]


def test_questions_are_deterministic_and_use_brackets():
    frames = {"King": fd.to_frame(OPP_MOVES, "King")}
    pun = fd.punishers(fd.to_frame(ME_MOVES, "Leroy"))
    q1 = training.make_questions(frames, pun, seed=20261123)
    q2 = training.make_questions(frames, pun, seed=20261123)
    assert q1 == q2 and len(q1) == 10
    assert len({q["move_id"] for q in q1}) == 10                 # pas de doublon
    assert all(q["move_id"] != "King-2+4" for q in q1)            # pas de chope
    for q in q1:
        assert q["choices"] == [b for b, *_ in training.BRACKETS]
        assert q["expected"] == training.bracket(q["block"])
    assert len({q["expected"] for q in q1}) >= 3                  # pas toujours la même tranche
    jab = next(q for q in q1 if q["move_id"] == "King-1")
    assert jab["video"].startswith("https://wavu.wiki/w/images/") and jab["name"] == "Dragon's Jab"
    json.dumps(q1)                                                # sérialisable


def test_brackets_and_video_url():
    assert [training.bracket(v) for v in (5, 1, 0, -9, -10, -11, -12, -14, -15, -40)] == [
        "+1 ou plus", "+1 ou plus", "0 à −9", "0 à −9", "−10 à −11", "−10 à −11",
        "−12 à −14", "−12 à −14", "−15 ou moins", "−15 ou moins"]
    assert fd.video_url("File:t8-p2-alisa-1,1.mp4") == "https://wavu.wiki/w/images/8/8e/T8-p2-alisa-1%2C1.mp4"
    assert fd.video_url(None) is None and fd.video_url("") is None


def test_margins_streak_and_opponents():
    matches = pd.DataFrame([
        {"played_at": "2026-11-20", "my_char": "Leroy", "opp_char": "King", "result": r} for r in "LLLLW"
    ] + [{"played_at": "2026-11-20", "my_char": "Leroy", "opp_char": "Jin", "result": r} for r in "WWWWL"])
    answers = pd.DataFrame([{"opp_char": "King", "correct": c} for c in (1, 0, 0, 0)])
    m = training.margins(matches, answers, "2026-10-01")
    assert list(m["opp_char"]) == ["King"]
    assert m.loc[0, "gain_pts"] == 15.0          # (5/2 - 1) / 10 matchs
    assert m.loc[0, "missing_wins"] == 2         # 1,5 arrondi au supérieur
    assert m.loc[0, "quiz_rate"] == 25
    assert training.daily_opponents(matches, "2026-10-01") == ["King", "Jin"]
    picks = {training.daily_opponent(matches, "2026-10-01", date(2026, 11, d)) for d in (23, 24)}
    assert picks == {"King", "Jin"}                               # un perso par jour, en rotation
    today = date(2026, 11, 23)
    assert training.streak(["2026-11-21", "2026-11-22"], today) == 2          # pas encore fait aujourd'hui
    assert training.streak(["2026-11-21", "2026-11-22", "2026-11-23"], today) == 3
    assert training.streak(["2026-11-20"], today) == 0


# ---------- routes ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "today", lambda: date(2026, 11, 23))
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "FRAMEDATA_FETCH": lambda c: FAKE.get(c, [])})
    with app.app_context():
        db = get_db()
        rows = [(ME, "2026-11-20 10:00", "Leroy", "King", r) for r in "LLLLLW"]
        db.executemany("INSERT INTO matches (player_id, played_at, my_char, opp_char, result) "
                       "VALUES (?, ?, ?, ?, ?)", rows)
        db.commit()
    c = login(app, app.test_client())
    c.app = app
    return c


def test_daily_challenge_flow(client):
    page = client.get("/entrainement").get_data(as_text=True)
    assert "Lancer le défi" in page and "King" in page and "+30.0 pt" not in page

    r = client.post("/entrainement/defi")
    assert r.status_code == 302
    url = r.headers["Location"]
    assert client.post("/entrainement/defi").headers["Location"] == url   # un seul défi par jour

    quiz = client.get(url).get_data(as_text=True)
    assert "Question 1 / 10" in quiz and 'id="quizForm"' in quiz
    with client.app.app_context():
        session = get_db().execute("SELECT * FROM quiz_sessions").fetchone()
        questions = json.loads(session["questions"])
    assert {q["opp_char"] for q in questions} == {"King"}         # un seul perso par défi
    answers = {f"q{i}": q["expected"] for i, q in enumerate(questions)}
    answers["q0"] = "faux"
    done = client.post(url, data=answers, follow_redirects=True).get_data(as_text=True)
    assert f"{len(questions) - 1}/{len(questions)}" in done
    assert "tu as répondu faux" in done and "Retour à l'entraînement" in done

    hub = client.get("/entrainement").get_data(as_text=True)
    assert "🔥 1 jour" in hub and "Revoir les corrections" in hub
    assert "🔥 1" in client.get("/").get_data(as_text=True)


def test_free_quiz_and_punish_page(client):
    r = client.post("/entrainement/libre", data={"adversaire": "King"})
    assert r.status_code == 302 and "/entrainement/quiz/" in r.headers["Location"]
    assert client.post("/entrainement/libre", data={"adversaire": "Personne"}).status_code == 400

    page = client.get("/entrainement/punitions?adversaire=King&perso=Leroy").get_data(as_text=True)
    assert "f+2" in page and "df+2,1+2" in page and "15 frames et plus" in page
    assert client.get("/entrainement/punitions?adversaire=Personne").status_code == 404


def test_plan_crud(client):
    r = client.post("/plan", data={"category": "punish", "opp_char": "King",
                                   "title": "Punir le f+2 de King", "next": "/entrainement"})
    assert r.headers["Location"].endswith("/entrainement")
    r = client.post("/plan", data={"category": "autre", "title": "x", "next": "https://evil.example"})
    assert r.headers["Location"].endswith("/plan")
    assert "Punir le f+2 de King" in client.get("/plan").get_data(as_text=True)
    with client.app.app_context():
        goal_id = get_db().execute("SELECT id FROM training_goals WHERE category = 'punish'").fetchone()[0]
    client.post(f"/plan/{goal_id}/statut", data={"status": "done"})
    with client.app.app_context():
        row = get_db().execute("SELECT status, done_at FROM training_goals WHERE id = ?", (goal_id,)).fetchone()
    assert row["status"] == "done" and row["done_at"]
    assert client.post(f"/plan/{goal_id}/statut", data={"status": "nimp"}).status_code == 400
    client.post(f"/plan/{goal_id}/supprimer")
    assert "Punir le f+2" not in client.get("/plan").get_data(as_text=True)
    r = client.post("/plan", data={"category": "punish", "title": ""}, follow_redirects=True)
    assert "Objectif invalide" in r.get_data(as_text=True)


def test_outdated_daily_is_regenerated(client):
    old = [{"kind": "punish", "opp_char": "King", "move_id": "King-f+2", "command": "f+2", "name": "",
            "target": "h", "startup": 14, "block": -17, "punishable": True, "punisher": None,
            "punish_kind": "standing", "choices": ["Oui", "Non"], "expected": "Oui"}]
    with client.app.app_context():
        db = get_db()
        db.execute("INSERT INTO quiz_sessions (player_id, mode, day, my_char, questions) "
                   "VALUES (?, 'daily', '2026-11-23', 'Leroy', ?)", (ME, json.dumps(old)))
        db.commit()
    assert "Oui" in client.get("/entrainement/quiz/1").get_data(as_text=True)   # l'ancien format reste lisible
    client.post("/entrainement/defi")
    with client.app.app_context():
        rows = get_db().execute("SELECT questions FROM quiz_sessions WHERE mode = 'daily'").fetchall()
    assert len(rows) == 1 and json.loads(rows[0][0])[0]["kind"] == "bracket"


def test_okizeme_links(client):
    assert fd.okizeme_url("Fahkumram") == "https://okizeme.gg/database/fahkumram"
    assert fd.okizeme_url("Armor King") == "https://okizeme.gg/database/armor-king"
    assert fd.okizeme_url("Roger") == "https://okizeme.gg/database/roger-jr"
    page = client.get("/entrainement/punitions?adversaire=King&perso=Leroy").get_data(as_text=True)
    assert "https://okizeme.gg/database/king" in page
    loc = client.post("/entrainement/libre", data={"adversaire": "Jin"}).headers["Location"]
    quiz = client.get(loc).get_data(as_text=True)           # Jin n'a pas de vidéo dans FAKE
    assert "Voir le coup sur okizeme.gg" in quiz and "https://okizeme.gg/database/jin" in quiz


# ---------- neutre / stances / positions ----------

STANCE_MOVES = OPP_MOVES + [
    mv("King", "JGR.1", "m", 14, "-13"),          # stance Jaguar Run
    mv("King", "JGR.2", "h", 12, "-4"),
    mv("King", "BT.2", "h", 10, "-12"),           # dos tourné
    mv("King", "SS.3", "m", 16, "-6"),            # pas de côté
    mv("King", "H.2+3", "m", 15, "-15"),          # Heat
    mv("King", "OTG.3", "l", 20, "-20"),          # adversaire au sol : situation, hors quiz
]


def test_move_context():
    assert fd.move_context("df+1") == ("neutral", "En neutre")
    assert fd.move_context("f,F+2")[0] == "neutral"
    assert fd.move_context("ws2") == ("position", "En se relevant (ws)")
    assert fd.move_context("HRM.1") == ("stance", "Stance Hermit (HRM)")
    assert fd.move_context("KAT.3") == ("stance", "Stance KAT")          # nom inconnu : abréviation
    assert fd.move_context("BT.3")[0] == "position"
    assert fd.move_context("H.2+3") == ("power", "Heat")
    assert fd.move_context("OTG.d+3")[0] == "situation"


def test_quiz_modes():
    frames = {"King": fd.to_frame(STANCE_MOVES, "King")}
    pun = fd.punishers(fd.to_frame(ME_MOVES, "Leroy"))
    neutral = training.make_questions(frames, pun, seed=1, mode="neutral")
    assert neutral and all(q["context_kind"] == "neutral" for q in neutral)
    stances = training.make_questions(frames, pun, seed=1, mode="stances")
    assert stances and all(q["context_kind"] in ("position", "stance", "power") for q in stances)
    assert {q["command"] for q in stances} <= {"JGR.1", "JGR.2", "BT.2", "SS.3", "H.2+3"}
    for seed in range(5):
        mixed = training.make_questions(frames, pun, seed=seed)
        assert all(q["command"] != "OTG.3" for q in mixed)               # jamais de situation
        assert sum(q["context_kind"] == "neutral" for q in mixed) >= len(mixed) // 2
    # Sur beaucoup de tirages, environ 80 % de coups en neutre.
    total = [q["context_kind"] == "neutral" for s in range(40)
             for q in training.make_questions(frames, pun, seed=s)]
    assert 0.65 <= sum(total) / len(total) <= 0.95


def test_punish_sheet_sections(tmp_path, monkeypatch):
    monkeypatch.setattr(training, "today", lambda: date(2026, 11, 23))
    fake = dict(FAKE, King=STANCE_MOVES)
    app = create_app({"TESTING": True, "DATABASE": str(tmp_path / "t.db"),
                      "FRAMEDATA_FETCH": lambda c: fake.get(c, [])})
    with app.app_context():
        get_db().execute("INSERT INTO matches (player_id, played_at, my_char, opp_char, result) "
                         "VALUES (?, '2026-11-20', 'Leroy', 'King', 'L')", (ME,))
        get_db().commit()
    client = login(app, app.test_client())
    html = client.get("/entrainement/punitions?adversaire=King&perso=Leroy").get_data(as_text=True)
    neutral_part, stance_part = html.split("Stances, positions et Heat")
    assert "f+2" in neutral_part and "JGR.1" not in neutral_part and "BT.2" not in neutral_part
    assert "Jaguar Run (JGR)" in stance_part and "Stance Jaguar Run" not in stance_part   # pas de doublon
    assert "Dos tourné (BT)" in stance_part and "Heat" in stance_part
    assert stance_part.index("Dos tourné") < stance_part.index("Jaguar Run") < stance_part.index("ctx-power")
    loc = client.post("/entrainement/libre", data={"adversaire": "King", "mode": "stances"}).headers["Location"]
    quiz = client.get(loc).get_data(as_text=True)
    assert "Stance Jaguar Run (JGR)" in quiz or "Dos tourné (BT)" in quiz or "Heat" in quiz
    assert client.post("/entrainement/libre", data={"adversaire": "King", "mode": "nimp"}).status_code == 400


def test_daily_without_context_is_regenerated(client):
    old = [{"kind": "bracket", "opp_char": "King", "move_id": "King-f+2", "command": "f+2", "name": "",
            "target": "h", "startup": 14, "block": -17, "punishable": True, "punisher": None,
            "punish_kind": "standing", "choices": ["x"], "expected": "x"}]
    with client.app.app_context():
        db = get_db()
        db.execute("INSERT INTO quiz_sessions (player_id, mode, day, my_char, questions) "
                   "VALUES (?, 'daily', '2026-11-23', 'Leroy', ?)", (ME, json.dumps(old)))
        db.commit()
    client.post("/entrainement/defi")
    with client.app.app_context():
        rows = get_db().execute("SELECT questions FROM quiz_sessions WHERE mode = 'daily'").fetchall()
    assert len(rows) == 1 and all("context_kind" in q for q in json.loads(rows[0][0]))
