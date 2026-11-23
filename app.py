import json
import os
import random
import secrets
import urllib.error
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from flask import (Flask, abort, flash, g, redirect, render_template, request, send_file,
                   session, url_for)

import pandas as pd

import ewgf
import framedata
import portraits
import stats
import training
import wavu
from data import CHARACTERS, RANKS, rank_level
from db import adopt_orphans, close_db, get_db, init_db, save_imported

# Réimport automatique des matchs si le dernier date de plus de :
AUTO_REFRESH = timedelta(hours=6)
# Pages accessibles sans être identifié.
PUBLIC_ENDPOINTS = {"login", "static", "portrait"}


def _offline(*_args, **_kwargs):
    raise urllib.error.URLError("accès réseau désactivé pendant les tests")


def _secret_key(instance_path):
    """Clé de signature des cookies : générée une fois, gardée dans instance/ (hors Git)."""
    path = Path(instance_path) / "secret_key"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_hex(32))
        path.chmod(0o600)
    return path.read_text().strip()


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=365),
        SESSION_COOKIE_SAMESITE="Lax",
        DATABASE=str(Path(app.instance_path) / "progression.db"),
        PORTRAITS_DIR=str(Path(app.instance_path) / "portraits"),
        EWGF_API_KEY=os.environ.get("EWGF_API_KEY"),
        # Fonctions d'accès réseau, remplaçables dans les tests.
        WAVU_FETCH=wavu.fetch_player_page,
        EWGF_FETCH=ewgf.fetch_battles,
        PORTRAIT_DOWNLOAD=portraits.download,
        PORTRAIT_OFFICIAL=portraits.fetch_official,
        FRAMEDATA_FETCH=framedata.fetch_raw,
    )
    if test_config:
        # Pas d'accès réseau implicite pendant les tests.
        app.config.update({"PORTRAIT_OFFICIAL": None, "WAVU_FETCH": _offline,
                           "FRAMEDATA_FETCH": _offline, "SECRET_KEY": "tests", **test_config})
    else:
        # Réglages locaux (clé API…) dans instance/config.py, exclu de Git.
        app.config.from_pyfile("config.py", silent=True)
    if not app.config.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = _secret_key(app.instance_path)

    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)

    @app.before_request
    def load_player():
        """Le joueur est identifié par son ID Tekken, gardé dans un cookie signé."""
        pid = session.get("player")
        g.player = get_db().execute("SELECT * FROM players WHERE polaris_id = ?",
                                    (pid,)).fetchone() if pid else None
        if g.player is None and request.endpoint not in PUBLIC_ENDPOINTS:
            session.pop("player", None)
            return redirect(url_for("login"))
        if g.player is not None and request.method == "GET" and request.endpoint == "home":
            last = g.player["last_import_at"]
            stale = not last or datetime.fromisoformat(last).replace(tzinfo=timezone.utc) \
                < datetime.now(timezone.utc) - AUTO_REFRESH
            if stale:
                refresh_player(g.player["polaris_id"], quiet=True)

    @app.context_processor
    def inject_globals():
        return {"CHARACTERS": all_characters(), "RANKS": RANKS, "profile": get_profile()}

    def refresh_player(pid, html=None, quiet=False):
        """Va chercher tout ce qu'on peut savoir du joueur : matchs, rating, rangs Dan.

        `quiet` : mise à jour automatique, on ne signale que les nouveautés et les erreurs.
        """
        db = get_db()
        added_total = 0
        if html is None:
            try:
                html = app.config["WAVU_FETCH"](pid)
            except (urllib.error.URLError, TimeoutError) as e:
                flash(f"wavu : impossible de joindre wank.wavu.wiki ({e}).", "error")
        if html is not None:
            found = wavu.parse_matches(html, pid)
            added = save_imported(db, found, pid)
            added_total += added
            if not quiet:
                flash(f"wavu : {len(found)} matchs classés lus, {added} nouveaux."
                      if found else "wavu : aucun match trouvé pour cet ID.",
                      "message" if found else "error")
        api_key = app.config.get("EWGF_API_KEY")
        if api_key:
            try:
                found = ewgf.parse_battles(app.config["EWGF_FETCH"](pid, api_key), pid)
                added = save_imported(db, found, pid)
                added_total += added
                if not quiet:
                    flash(f"ewgf : {len(found)} matchs classés lus (rangs Dan), {added} nouveaux.")
            except ewgf.EwgfError as e:
                flash(f"ewgf : erreur {e.code}. {e}", "error")
        db.execute("UPDATE players SET last_import_at = ? WHERE polaris_id = ?",
                   (datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"), pid))
        db.commit()
        if quiet and added_total:
            flash(f"{added_total} nouveau{'x' if added_total > 1 else ''} match"
                  f"{'s' if added_total > 1 else ''} importé{'s' if added_total > 1 else ''}.")
        return added_total

    @app.route("/connexion", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            if g.player is not None:
                return redirect(url_for("home"))
            return render_template("login.html", value="")

        raw = request.form.get("polaris_id", "").strip()
        pid = wavu.extract_polaris_id(raw)
        if not pid:
            flash("ID invalide : colle ton ID Tekken (ex. 4qLJmf7THeE2) ou l'URL de ton profil ewgf.gg.",
                  "error")
            return render_template("login.html", value=raw), 400
        db = get_db()
        known = db.execute("SELECT * FROM players WHERE polaris_id = ?", (pid,)).fetchone()

        # On vérifie l'ID sur wavu : c'est aussi là qu'on trouve le pseudo et les matchs.
        html = None
        try:
            html = app.config["WAVU_FETCH"](pid)
        except urllib.error.HTTPError as e:
            if not known:
                flash("Cet ID est introuvable sur wank.wavu.wiki. Vérifie-le sur ewgf.gg."
                      if e.code == 404 else f"wank.wavu.wiki répond une erreur {e.code} : réessaie plus tard.",
                      "error")
                return render_template("login.html", value=raw), 400 if e.code == 404 else 503
        except (urllib.error.URLError, TimeoutError):
            if not known:
                flash("Impossible de vérifier cet ID : wank.wavu.wiki est injoignable. Réessaie plus tard.",
                      "error")
                return render_template("login.html", value=raw), 503
        if html is not None and not known and not wavu.parse_matches(html, pid):
            flash("Aucun match classé trouvé pour cet ID. Vérifie-le sur ewgf.gg.", "error")
            return render_template("login.html", value=raw), 400

        if not known:
            first_player = db.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 0
            db.execute("INSERT INTO players (polaris_id, name) VALUES (?, ?)",
                       (pid, wavu.parse_player_name(html) or pid))
            if first_player:
                adopt_orphans(db, pid)   # données d'une ancienne version mono-joueur
            db.commit()
        elif html is not None and (name := wavu.parse_player_name(html)):
            db.execute("UPDATE players SET name = ? WHERE polaris_id = ?", (name, pid))
            db.commit()

        session.clear()
        session["player"] = pid
        session.permanent = True
        g.player = db.execute("SELECT * FROM players WHERE polaris_id = ?", (pid,)).fetchone()
        if html is not None:
            refresh_player(pid, html=html)
        else:
            flash("wank.wavu.wiki est injoignable : tes matchs n'ont pas été mis à jour.", "error")
        flash(f"Bienvenue {g.player['name']} !")
        return redirect(url_for("home"))

    @app.post("/deconnexion")
    def logout():
        session.clear()
        flash("Tu peux entrer un autre ID Tekken.")
        return redirect(url_for("login"))

    # ---------- Accueil : progression du perso principal ----------

    @app.get("/")
    def home():
        everything = all_matches()
        if not everything:
            return render_template("home.html", char=None)
        played = stats.by_key(everything, "my_char")
        char = request.args.get("perso") or played[0]["name"]
        ms = [m for m in everything if m["my_char"] == char]
        if not ms:
            abort(404)

        today = date.today()
        d7, d14, d30 = ((today - timedelta(days=n)).isoformat() for n in (6, 13, 29))
        points = stats.rating_history(ms, char)
        profile = get_profile()
        rating = points[-1]["rating"] if points else None
        peak = max((p["rating"] for p in points), default=None)
        goal_rating = profile["goal_rating"]

        rank = next((m["rank"] for m in reversed(ms) if m["rank"]), None)
        rank_progress = None
        cur, goal = rank_level(rank), rank_level(profile["goal_rank"])
        if cur is not None and goal:
            rank_progress = min(100, round(100 * cur / goal))

        recent = [m for m in ms if m["played_at"][:10] >= d30]
        has_portrait = ensure_official_portrait(char)
        db = get_db()
        done_days = daily_done_days()
        daily_done = today.isoformat() in done_days
        goals_open = db.execute("SELECT COUNT(*) FROM training_goals WHERE status != 'done' "
                                "AND player_id = ?", (player_id(),)).fetchone()[0]
        mains = get_mains(everything)
        switch = [r for r in played if r["name"] in mains or r["name"] == char]

        return render_template(
            "home.html",
            char=char,
            switch=switch,
            portrait=has_portrait,
            streak=training.streak(done_days, today),
            daily_done=daily_done,
            goals_open=goals_open,
            hue=sum(map(ord, char)) * 47 % 360,
            summary=stats.summary(ms),
            rating=rating,
            peak=peak,
            delta7=stats.rating_delta(points, d7),
            delta30=stats.rating_delta(points, d30),
            goal_rating=goal_rating,
            goal_progress=(min(100, round(100 * rating / goal_rating))
                           if rating and goal_rating else None),
            week=stats.period_summary(ms, d7),
            prev_week=stats.period_summary(ms, d14, d7),
            month=stats.summary(recent),
            rank=rank,
            rank_progress=rank_progress,
            daily=stats.daily_rating(points),
            weeks=stats.weekly(ms),
            to_work=stats.worst_matchups(recent, min_games=4, limit=3),
            strengths=stats.best_matchups(recent, min_games=4, limit=3),
            last_seen=ms[-1]["played_at"],
            wr_class=stats.wr_class,
        )

    # ---------- Portraits ----------

    @app.get("/portrait/<char>")
    def portrait(char):
        path = portraits.find(app.config["PORTRAITS_DIR"], char)
        if path is None:
            abort(404)
        return send_file(path, max_age=0)

    @app.post("/portrait/<char>")
    def portrait_upload(char):
        if char not in all_characters():
            abort(404)
        file = request.files.get("image")
        url = request.form.get("url", "").strip()
        try:
            if file and file.filename:
                data = file.read()
            elif url:
                data = app.config["PORTRAIT_DOWNLOAD"](url)
            else:
                raise ValueError("Choisis une image ou colle son adresse.")
            portraits.save(app.config["PORTRAITS_DIR"], char, data)
            flash(f"Portrait de {char} enregistré.")
        except ValueError as e:
            flash(str(e), "error")
        return redirect(url_for("home", perso=char))

    @app.post("/portrait/<char>/officiel")
    def portrait_official(char):
        if char not in all_characters():
            abort(404)
        folder = app.config["PORTRAITS_DIR"]
        portraits.remove(folder, char)
        portraits.failed_marker(folder, char).unlink(missing_ok=True)
        if ensure_official_portrait(char):
            flash(f"Illustration officielle de {char} récupérée.")
        else:
            flash(f"Impossible de récupérer l'illustration de {char} : "
                  "colle l'adresse d'une image à la place.", "error")
        return redirect(url_for("home", perso=char))

    def ensure_official_portrait(char):
        """Récupère une fois l'illustration officielle si aucun portrait n'existe."""
        folder = app.config["PORTRAITS_DIR"]
        if portraits.find(folder, char):
            return True
        fetch = app.config.get("PORTRAIT_OFFICIAL")
        marker = portraits.failed_marker(folder, char)
        if fetch is None or marker.exists():
            return False
        try:
            portraits.save(folder, char, fetch(char))
            return True
        except ValueError:
            Path(folder).mkdir(parents=True, exist_ok=True)
            marker.touch()
            return False

    @app.post("/portrait/<char>/supprimer")
    def portrait_delete(char):
        portraits.remove(app.config["PORTRAITS_DIR"], char)
        flash(f"Portrait de {char} retiré.")
        return redirect(url_for("home", perso=char))

    # ---------- Statistiques détaillées ----------

    @app.get("/stats")
    def dashboard():
        everything = all_matches()
        mains = get_mains(everything)
        cards = stats.character_cards(everything, mains)

        # Par défaut on affiche le premier main ; "tous" = tous les persos confondus.
        requested = request.args.get("perso")
        if requested == "tous":
            selected = None
        elif requested:
            selected = requested
        else:
            selected = mains[0] if mains else None
        matches = [m for m in everything if selected is None or m["my_char"] == selected]

        profile = get_profile()
        last_rank = next((m["rank"] for m in reversed(matches) if m["rank"]), None)
        rank_progress = None
        cur, goal = rank_level(last_rank), rank_level(profile["goal_rank"])
        if cur is not None and goal:
            rank_progress = min(100, round(100 * cur / goal))

        rating_points = stats.rating_history(matches, selected) if selected else []
        current_rating = rating_points[-1]["rating"] if rating_points else None
        peak_rating = max((p["rating"] for p in rating_points), default=None)
        goal_rating = profile["goal_rating"]
        rating_progress = (min(100, round(100 * current_rating / goal_rating))
                           if current_rating and goal_rating else None)

        chart, hidden = stats.matchup_chart(matches)
        last_day = everything[-1]["played_at"][:10] if everything else None
        end = max(date.today(), date.fromisoformat(last_day)) if last_day else date.today()

        return render_template(
            "dashboard.html",
            selected=selected,
            mains=mains,
            cards=cards,
            main_cards=[c for c in cards if c["is_main"]],
            last_seen=everything[-1]["played_at"] if everything else None,
            summary=stats.summary(matches),
            last50=stats.summary(matches[-50:]),
            streak=stats.current_streak(matches),
            best_streak=stats.best_streak(matches),
            activity=stats.activity(matches, end),
            last_rank=last_rank,
            rank_progress=rank_progress,
            rating_points=rating_points,
            current_rating=current_rating,
            peak_rating=peak_rating,
            rating_progress=rating_progress,
            opponents=stats.by_key(matches, "opp_char")[:6],
            chart=chart,
            chart_hidden=hidden,
            sessions=stats.sessions(matches, limit=7),
            wr_class=stats.wr_class,
        )

    # ---------- Matchs ----------

    @app.get("/matchs")
    def match_list():
        opp = request.args.get("adversaire") or None
        mine = request.args.get("perso") or None
        day = request.args.get("jour") or None
        page = max(1, request.args.get("page", 1, type=int))
        matches = list(reversed(all_matches(opp_char=opp, my_char=mine, day=day)))
        per_page = 100
        pages = max(1, -(-len(matches) // per_page))
        return render_template(
            "matches.html", matches=matches[(page - 1) * per_page: page * per_page],
            summary=stats.summary(matches), opp=opp, mine=mine, day=day, page=page,
            pages=pages)

    @app.route("/matchs/nouveau", methods=["GET", "POST"])
    def match_new():
        if request.method == "POST":
            data, errors = parse_match_form(request.form)
            if not errors:
                get_db().execute(
                    """INSERT INTO matches (player_id, played_at, my_char, opp_char, opp_name,
                       result, rank, rounds_won, rounds_lost, notes)
                       VALUES (:player_id, :played_at, :my_char, :opp_char, :opp_name, :result,
                       :rank, :rounds_won, :rounds_lost, :notes)""", {**data, "player_id": player_id()})
                get_db().commit()
                flash("Match enregistré.")
                if request.form.get("again"):
                    return redirect(url_for("match_new"))
                return redirect(url_for("home"))
            for e in errors:
                flash(e, "error")
            return render_template("match_form.html", match=request.form, editing=False)
        return render_template("match_form.html", match=default_match(), editing=False)

    @app.route("/matchs/<int:match_id>/modifier", methods=["GET", "POST"])
    def match_edit(match_id):
        match = get_match(match_id)
        if request.method == "POST":
            data, errors = parse_match_form(request.form)
            if not errors:
                data["id"] = match_id
                get_db().execute(
                    """UPDATE matches SET played_at=:played_at, my_char=:my_char,
                       opp_char=:opp_char, opp_name=:opp_name, result=:result, rank=:rank,
                       rounds_won=:rounds_won, rounds_lost=:rounds_lost, notes=:notes
                       WHERE id=:id AND player_id=:player_id""", {**data, "player_id": player_id()})
                get_db().commit()
                flash("Match modifié.")
                return redirect(url_for("match_list"))
            for e in errors:
                flash(e, "error")
            return render_template("match_form.html", match=request.form, editing=True,
                                   match_id=match_id)
        return render_template("match_form.html", match=match, editing=True,
                               match_id=match_id)

    @app.post("/matchs/<int:match_id>/supprimer")
    def match_delete(match_id):
        get_match(match_id)
        get_db().execute("DELETE FROM matches WHERE id = ? AND player_id = ?", (match_id, player_id()))
        get_db().commit()
        flash("Match supprimé.")
        return redirect(url_for("match_list"))

    # ---------- Import wavu / ewgf ----------

    @app.route("/import", methods=["GET", "POST"])
    def import_page():
        if request.method == "POST":
            refresh_player(player_id())
            return redirect(url_for("home"))
        return render_template("import.html", has_ewgf_key=bool(app.config.get("EWGF_API_KEY")))

    # ---------- Matchups ----------

    @app.get("/matchups")
    def matchups():
        mine = request.args.get("perso") or None
        rows = stats.by_key(all_matches(my_char=mine), "opp_char")
        sort = request.args.get("tri", "matchs")
        if sort == "winrate":
            rows.sort(key=lambda r: (r["winrate"], -r["total"]))
        noted = {r["opp_char"] for r in get_db().execute(
            "SELECT opp_char FROM matchup_notes WHERE notes != '' AND player_id = ?", (player_id(),))}
        return render_template("matchups.html", rows=rows, noted=noted, mine=mine,
                               sort=sort)

    @app.route("/matchups/<char>", methods=["GET", "POST"])
    def matchup_detail(char):
        if char not in all_characters():
            abort(404)
        db = get_db()
        if request.method == "POST":
            db.execute(
                """INSERT INTO matchup_notes (player_id, opp_char, notes, updated_at)
                   VALUES (?, ?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(player_id, opp_char) DO UPDATE SET notes = excluded.notes,
                   updated_at = CURRENT_TIMESTAMP""",
                (player_id(), char, request.form.get("notes", "").strip()))
            db.commit()
            flash(f"Notes sur {char} enregistrées.")
            return redirect(url_for("matchup_detail", char=char))

        matches = all_matches(opp_char=char)
        note = db.execute("SELECT notes, updated_at FROM matchup_notes "
                          "WHERE opp_char = ? AND player_id = ?", (char, player_id())).fetchone()
        return render_template("matchup_detail.html", char=char, note=note,
                               summary=stats.summary(matches),
                               last20=stats.summary(matches[-20:]),
                               by_char=stats.by_key(matches, "my_char"),
                               matches=list(reversed(matches))[:50])

    # ---------- Entraînement ----------

    def frames(char):
        """Frame data d'un perso (cache ou wiki). None si le wiki est injoignable."""
        try:
            return framedata.load(get_db(), char, fetch=app.config["FRAMEDATA_FETCH"])
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            flash(f"Frame data de {char} indisponible ({e}).", "error")
            return None

    def training_char():
        played = stats.by_key(all_matches(), "my_char")
        return request.args.get("perso") or (played[0]["name"] if played else None)

    def answers_frame():
        return pd.read_sql_query(
            "SELECT a.opp_char, a.correct, a.answered_at FROM quiz_answers a "
            "JOIN quiz_sessions s ON s.id = a.session_id WHERE s.player_id = ?",
            get_db(), params=(player_id(),))

    def create_session(mode, my_char, opponents, seed):
        my_df = frames(my_char) if my_char else None
        my_pun = framedata.punishers(my_df) if my_df is not None else framedata.punishers(pd.DataFrame())
        by_opp = {}
        for opp in opponents:
            df = frames(opp)
            if df is not None and not df.empty:
                by_opp[opp] = df
        questions = training.make_questions(by_opp, my_pun, seed)
        if not questions:
            return None
        cur = get_db().execute(
            "INSERT INTO quiz_sessions (player_id, mode, day, my_char, questions) VALUES (?, ?, ?, ?, ?)",
            (player_id(), mode, training.today().isoformat(), my_char, json.dumps(questions)))
        get_db().commit()
        return cur.lastrowid

    @app.get("/entrainement")
    def training_hub():
        char = training_char()
        db = get_db()
        today = training.today()
        since = (today - timedelta(days=59)).isoformat()
        matches = training.matches_frame(all_matches(my_char=char))
        answers = answers_frame()
        done_days = daily_done_days()
        daily = db.execute("SELECT * FROM quiz_sessions WHERE mode = 'daily' AND day = ? "
                           "AND player_id = ?", (today.isoformat(), player_id())).fetchone()
        daily_score = None
        if daily and daily["completed_at"]:
            daily_score = db.execute("SELECT SUM(correct), COUNT(*) FROM quiz_answers "
                                     "WHERE session_id = ?", (daily["id"],)).fetchone()
        goals = db.execute("SELECT * FROM training_goals WHERE status != 'done' AND player_id = ? "
                           "ORDER BY status = 'doing' DESC, created_at DESC LIMIT 6",
                           (player_id(),)).fetchall()
        k = training.knowledge(answers).reset_index()
        return render_template(
            "training.html",
            char=char,
            margins=training.margins(matches, answers, since).to_dict("records"),
            knowledge=k.sort_values("quiz_rate").to_dict("records"),
            streak=training.streak(done_days, today),
            daily=daily,
            daily_score=daily_score,
            daily_opponent=training.daily_opponent(
                matches, (today - timedelta(days=29)).isoformat(), today),
            goals=goals,
            opponents=sorted({m["opp_char"] for m in all_matches(my_char=char)}) or all_characters(),
        )

    @app.post("/entrainement/defi")
    def daily_challenge():
        db = get_db()
        today = training.today()
        row = db.execute("SELECT * FROM quiz_sessions WHERE mode = 'daily' AND day = ? "
                         "AND player_id = ?", (today.isoformat(), player_id())).fetchone()
        if row:
            outdated = any(q.get("kind") != "bracket" for q in json.loads(row["questions"]))
            if row["completed_at"] or not outdated:
                return redirect(url_for("quiz_session", session_id=row["id"]))
            # Défi pas commencé, créé par une version précédente : on le régénère.
            db.execute("DELETE FROM quiz_sessions WHERE id = ?", (row["id"],))
            db.commit()
        char = training_char()
        since = (today - timedelta(days=29)).isoformat()
        opponent = training.daily_opponent(training.matches_frame(all_matches(my_char=char)), since, today)
        if not opponent:
            opponent = random.Random(training.daily_seed(today)).choice(CHARACTERS)
        session_id = create_session("daily", char, [opponent], training.daily_seed(today))
        if session_id is None:
            flash("Impossible de préparer le défi du jour (frame data indisponible).", "error")
            return redirect(url_for("training_hub"))
        return redirect(url_for("quiz_session", session_id=session_id))

    @app.post("/entrainement/libre")
    def free_quiz():
        opp = request.form.get("adversaire")
        if opp not in all_characters():
            abort(400)
        session_id = create_session("libre", training_char(), [opp], random.randrange(10**9))
        if session_id is None:
            flash(f"Impossible de préparer un quiz sur {opp}.", "error")
            return redirect(url_for("training_hub"))
        return redirect(url_for("quiz_session", session_id=session_id))

    @app.route("/entrainement/quiz/<int:session_id>", methods=["GET", "POST"])
    def quiz_session(session_id):
        db = get_db()
        quiz = db.execute("SELECT * FROM quiz_sessions WHERE id = ? AND player_id = ?",
                          (session_id, player_id())).fetchone()
        if quiz is None:
            abort(404)
        questions = json.loads(quiz["questions"])
        if request.method == "POST" and not quiz["completed_at"]:
            rows = []
            for i, q in enumerate(questions):
                given = request.form.get(f"q{i}")
                rows.append((session_id, i, q["opp_char"], q["move_id"], q["kind"], given,
                             q["expected"], int(given == q["expected"])))
            db.executemany(
                "INSERT INTO quiz_answers (session_id, idx, opp_char, move_id, kind, given, "
                "expected, correct) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", rows)
            db.execute("UPDATE quiz_sessions SET completed_at = CURRENT_TIMESTAMP WHERE id = ?",
                       (session_id,))
            db.commit()
            return redirect(url_for("quiz_session", session_id=session_id))
        answers = {r["idx"]: r for r in db.execute(
            "SELECT * FROM quiz_answers WHERE session_id = ?", (session_id,))}
        score = sum(a["correct"] for a in answers.values())
        return render_template("quiz.html", session=quiz, questions=questions,
                               answers=answers, score=score)

    @app.get("/entrainement/punitions")
    def punish_page():
        char = training_char()
        opp = request.args.get("adversaire")
        sheet, groups = None, []
        if opp:
            if opp not in all_characters():
                abort(404)
            opp_df, my_df = frames(opp), frames(char) if char else None
            if opp_df is not None and my_df is not None:
                sheet = framedata.punish_sheet(opp_df, my_df)
                windows = [("10 à 12 frames", 10, 12), ("13 à 14 frames", 13, 14),
                           ("15 frames et plus : punition lourde", 15, 999)]
                for label, lo, hi in windows:
                    part = sheet[(sheet["frames"] >= lo) & (sheet["frames"] <= hi)]
                    if not part.empty:
                        groups.append((label, part.to_dict("records")))
        planned = {r[0] for r in get_db().execute(
            "SELECT title FROM training_goals WHERE category = 'punish' AND opp_char = ? "
            "AND player_id = ?", (opp, player_id()))}
        return render_template("punish.html", char=char, opp=opp, groups=groups,
                               total=0 if sheet is None else len(sheet), planned=planned)

    # ---------- Plan d'entraînement ----------

    GOAL_CATEGORIES = {"punish": "Punition", "knowledge": "Connaissance",
                       "matchup": "Matchup", "autre": "Autre"}
    GOAL_STATUSES = {"todo": "À faire", "doing": "En cours", "done": "Acquis"}

    @app.route("/plan", methods=["GET", "POST"])
    def plan():
        db = get_db()
        if request.method == "POST":
            category = request.form.get("category", "autre")
            title = request.form.get("title", "").strip()
            opp = request.form.get("opp_char") or None
            if category not in GOAL_CATEGORIES or not title or (opp and opp not in all_characters()):
                flash("Objectif invalide : il faut au moins un intitulé.", "error")
            else:
                db.execute("INSERT INTO training_goals (player_id, category, opp_char, title, notes) "
                           "VALUES (?, ?, ?, ?, ?)",
                           (player_id(), category, opp, title[:200],
                            request.form.get("notes", "").strip() or None))
                db.commit()
                flash("Objectif ajouté au plan.")
            nxt = request.form.get("next", "")
            safe = nxt.startswith("/") and not nxt.startswith("//")
            return redirect(nxt if safe else url_for("plan"))
        goals = db.execute("SELECT * FROM training_goals WHERE player_id = ? "
                           "ORDER BY created_at DESC, id DESC", (player_id(),)).fetchall()
        columns = {s: [g for g in goals if g["status"] == s] for s in GOAL_STATUSES}
        return render_template("plan.html", columns=columns, categories=GOAL_CATEGORIES,
                               statuses=GOAL_STATUSES)

    @app.post("/plan/<int:goal_id>/statut")
    def plan_status(goal_id):
        status = request.form.get("status")
        if status not in GOAL_STATUSES:
            abort(400)
        get_db().execute(
            "UPDATE training_goals SET status = ?, done_at = CASE WHEN ? = 'done' "
            "THEN CURRENT_TIMESTAMP END WHERE id = ? AND player_id = ?",
            (status, status, goal_id, player_id()))
        get_db().commit()
        return redirect(url_for("plan"))

    @app.post("/plan/<int:goal_id>/supprimer")
    def plan_delete(goal_id):
        get_db().execute("DELETE FROM training_goals WHERE id = ? AND player_id = ?",
                         (goal_id, player_id()))
        get_db().commit()
        flash("Objectif supprimé.")
        return redirect(url_for("plan"))

    @app.context_processor
    def inject_plan_labels():
        return {"GOAL_CATEGORIES": GOAL_CATEGORIES, "GOAL_STATUSES": GOAL_STATUSES}

    # ---------- Profil ----------

    @app.route("/profil", methods=["GET", "POST"])
    def profile():
        if request.method == "POST":
            name = request.form.get("name", "").strip() or "Joueur"
            mains = [c for c in request.form.getlist("mains") if c]
            goal = request.form.get("goal_rank") or None
            raw_rating = request.form.get("goal_rating", "").strip()
            errors = []
            if any(c not in all_characters() for c in mains):
                errors.append("Personnage inconnu.")
            if goal and goal not in RANKS:
                errors.append("Rang inconnu.")
            goal_rating = None
            if raw_rating:
                if raw_rating.isdigit():
                    goal_rating = int(raw_rating)
                else:
                    errors.append("Le rating visé doit être un nombre.")
            if errors:
                for e in errors:
                    flash(e, "error")
                return render_template("profile.html"), 400
            get_db().execute(
                """UPDATE players SET name = ?, mains = ?, goal_rank = ?, goal_rating = ?
                   WHERE polaris_id = ?""",
                (name, ",".join(mains) or None, goal, goal_rating, player_id()))
            get_db().commit()
            flash("Profil mis à jour.")
            return redirect(url_for("home"))
        return render_template("profile.html")

    return app


# ---------- Accès aux données ----------

def get_profile():
    """Le joueur connecté (ligne de la table players), ou None."""
    return g.get("player")


def player_id():
    return g.player["polaris_id"]


def daily_done_days():
    return [r[0] for r in get_db().execute(
        "SELECT day FROM quiz_sessions WHERE mode = 'daily' AND completed_at IS NOT NULL "
        "AND player_id = ?", (player_id(),))]


def get_mains(matches=None):
    """Mains choisis dans le profil (sinon les 2 persos les plus joués), du plus joué au moins joué."""
    played = stats.by_key(matches if matches is not None else all_matches(), "my_char")
    raw = get_profile()["mains"]
    if not raw:
        return [r["name"] for r in played[:2]]
    chosen = [c for c in raw.split(",") if c]
    games = {r["name"]: r["total"] for r in played}
    return sorted(chosen, key=lambda c: -games.get(c, 0))


def all_characters():
    """Roster connu + persos apparus dans les imports (nouveaux DLC par ex.)."""
    seen = {r[0] for r in get_db().execute(
        "SELECT my_char FROM matches UNION SELECT opp_char FROM matches")}
    return sorted(set(CHARACTERS) | seen)


def all_matches(opp_char=None, my_char=None, day=None):
    """Matchs du plus ancien au plus récent, éventuellement filtrés."""
    sql, params = "SELECT * FROM matches WHERE player_id = ?", [player_id()]
    if day:
        sql += " AND substr(played_at, 1, 10) = ?"
        params.append(day)
    if opp_char:
        sql += " AND opp_char = ?"
        params.append(opp_char)
    if my_char:
        sql += " AND my_char = ?"
        params.append(my_char)
    sql += " ORDER BY played_at, id"
    return get_db().execute(sql, params).fetchall()


def get_match(match_id):
    match = get_db().execute("SELECT * FROM matches WHERE id = ? AND player_id = ?",
                             (match_id, player_id())).fetchone()
    if match is None:
        abort(404)
    return match


def default_match():
    """Pré-remplit le formulaire avec le dernier perso et le dernier rang utilisés."""
    db = get_db()
    last = db.execute(
        "SELECT my_char FROM matches WHERE player_id = ? ORDER BY played_at DESC, id DESC LIMIT 1",
        (player_id(),)).fetchone()
    last_rank = db.execute(
        "SELECT rank FROM matches WHERE rank IS NOT NULL AND player_id = ? "
        "ORDER BY played_at DESC, id DESC LIMIT 1", (player_id(),)).fetchone()
    return {
        "played_at": date.today().isoformat(),
        "my_char": last["my_char"] if last else next(iter(get_mains()), None),
        "rank": last_rank["rank"] if last_rank else None,
    }


def parse_match_form(form):
    errors = []
    characters = all_characters()
    data = {
        "played_at": form.get("played_at", "").strip(),
        "my_char": form.get("my_char", ""),
        "opp_char": form.get("opp_char", ""),
        "opp_name": form.get("opp_name", "").strip() or None,
        "result": form.get("result", ""),
        "rank": form.get("rank") or None,
        "notes": form.get("notes", "").strip() or None,
    }
    try:
        if len(data["played_at"]) > 10:
            datetime.strptime(data["played_at"], "%Y-%m-%d %H:%M")
        else:
            date.fromisoformat(data["played_at"])
    except ValueError:
        errors.append("Date invalide.")
    if data["my_char"] not in characters:
        errors.append("Choisis ton personnage.")
    if data["opp_char"] not in characters:
        errors.append("Choisis le personnage adverse.")
    if data["result"] not in ("W", "L", "D"):
        errors.append("Indique victoire, défaite ou nul.")
    if data["rank"] and data["rank"] not in RANKS:
        errors.append("Rang inconnu.")
    for field in ("rounds_won", "rounds_lost"):
        raw = (form.get(field) or "").strip()
        data[field] = None
        if raw:
            if raw.isdigit() and int(raw) <= 5:
                data[field] = int(raw)
            else:
                errors.append("Les rounds doivent être un nombre entre 0 et 5.")
    return data, errors


if __name__ == "__main__":
    create_app().run(debug=True)
