import os
import urllib.error
from datetime import date, datetime
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

import stats
import wavu
from data import CHARACTERS, RANKS, rank_level
from db import close_db, get_db, init_db


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-local-only"),
        DATABASE=str(Path(app.instance_path) / "progression.db"),
        WAVU_FETCH=wavu.fetch_player_page,  # remplaçable dans les tests
    )
    if test_config:
        app.config.update(test_config)

    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_globals():
        return {"CHARACTERS": all_characters(), "RANKS": RANKS, "profile": get_profile()}

    # ---------- Tableau de bord ----------

    @app.get("/")
    def dashboard():
        mine = request.args.get("perso") or None
        matches = all_matches(my_char=mine)
        profile = get_profile()

        last_rank = next((m["rank"] for m in reversed(matches) if m["rank"]), None)
        rank_progress = None
        cur, goal = rank_level(last_rank), rank_level(profile["goal_rank"])
        if cur is not None and goal:
            rank_progress = min(100, round(100 * cur / goal))

        # Le rating est propre à chaque perso : on suit le perso filtré, sinon le main,
        # sinon le plus joué.
        played = stats.by_key(matches, "my_char")
        rating_char = mine or (profile["main_char"] if any(
            r["name"] == profile["main_char"] for r in played) else None) or (
            played[0]["name"] if played else None)
        rating_points = stats.rating_history(matches, rating_char) if rating_char else []
        current_rating = rating_points[-1]["rating"] if rating_points else None
        peak_rating = max((p["rating"] for p in rating_points), default=None)

        return render_template(
            "dashboard.html",
            mine=mine,
            summary=stats.summary(matches),
            last50=stats.summary(matches[-50:]),
            streak=stats.current_streak(matches),
            best_streak=stats.best_streak(matches),
            last_rank=last_rank,
            rank_progress=rank_progress,
            rating_char=rating_char,
            rating_points=rating_points,
            current_rating=current_rating,
            peak_rating=peak_rating,
            worst=stats.worst_matchups(matches),
            best=stats.best_matchups(matches),
            by_char=played,
            sessions=stats.sessions(matches),
            rank_history=stats.rank_history(matches),
            rolling=stats.rolling_winrate(matches),
        )

    # ---------- Matchs ----------

    @app.get("/matchs")
    def match_list():
        opp = request.args.get("adversaire") or None
        mine = request.args.get("perso") or None
        page = max(1, request.args.get("page", 1, type=int))
        matches = list(reversed(all_matches(opp_char=opp, my_char=mine)))
        per_page = 100
        pages = max(1, -(-len(matches) // per_page))
        return render_template(
            "matches.html", matches=matches[(page - 1) * per_page: page * per_page],
            summary=stats.summary(matches), opp=opp, mine=mine, page=page, pages=pages)

    @app.route("/matchs/nouveau", methods=["GET", "POST"])
    def match_new():
        if request.method == "POST":
            data, errors = parse_match_form(request.form)
            if not errors:
                get_db().execute(
                    """INSERT INTO matches (played_at, my_char, opp_char, opp_name, result,
                       rank, rounds_won, rounds_lost, notes)
                       VALUES (:played_at, :my_char, :opp_char, :opp_name, :result, :rank,
                       :rounds_won, :rounds_lost, :notes)""", data)
                get_db().commit()
                flash("Match enregistré.")
                if request.form.get("again"):
                    return redirect(url_for("match_new"))
                return redirect(url_for("dashboard"))
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
                       WHERE id=:id""", data)
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
        get_db().execute("DELETE FROM matches WHERE id = ?", (match_id,))
        get_db().commit()
        flash("Match supprimé.")
        return redirect(url_for("match_list"))

    # ---------- Import wavu / ewgf ----------

    @app.route("/import", methods=["GET", "POST"])
    def import_page():
        if request.method == "POST":
            polaris_id = wavu.extract_polaris_id(request.form.get("polaris_id"))
            if not polaris_id:
                flash("ID joueur invalide. Colle ton ID ou l'URL de ton profil ewgf.gg.",
                      "error")
                return redirect(url_for("import_page"))
            try:
                html = app.config["WAVU_FETCH"](polaris_id)
            except (urllib.error.URLError, TimeoutError) as e:
                flash(f"Impossible de joindre wank.wavu.wiki : {e}", "error")
                return redirect(url_for("import_page"))
            matches = wavu.parse_matches(html, polaris_id)
            db = get_db()
            added = wavu.import_matches(db, matches)
            db.execute("UPDATE profile SET polaris_id = ? WHERE id = 1", (polaris_id,))
            db.commit()
            if not matches:
                flash("Aucun match trouvé pour cet ID.", "error")
            else:
                flash(f"{len(matches)} matchs lus, {added} nouveaux importés.")
            return redirect(url_for("dashboard"))
        return render_template("import.html")

    # ---------- Matchups ----------

    @app.get("/matchups")
    def matchups():
        mine = request.args.get("perso") or None
        rows = stats.by_key(all_matches(my_char=mine), "opp_char")
        sort = request.args.get("tri", "matchs")
        if sort == "winrate":
            rows.sort(key=lambda r: (r["winrate"], -r["total"]))
        noted = {r["opp_char"] for r in get_db().execute(
            "SELECT opp_char FROM matchup_notes WHERE notes != ''")}
        return render_template("matchups.html", rows=rows, noted=noted, mine=mine,
                               sort=sort)

    @app.route("/matchups/<char>", methods=["GET", "POST"])
    def matchup_detail(char):
        if char not in all_characters():
            abort(404)
        db = get_db()
        if request.method == "POST":
            db.execute(
                """INSERT INTO matchup_notes (opp_char, notes, updated_at)
                   VALUES (?, ?, CURRENT_TIMESTAMP)
                   ON CONFLICT(opp_char) DO UPDATE SET notes = excluded.notes,
                   updated_at = CURRENT_TIMESTAMP""",
                (char, request.form.get("notes", "").strip()))
            db.commit()
            flash(f"Notes sur {char} enregistrées.")
            return redirect(url_for("matchup_detail", char=char))

        matches = all_matches(opp_char=char)
        note = db.execute("SELECT notes, updated_at FROM matchup_notes WHERE opp_char = ?",
                          (char,)).fetchone()
        return render_template("matchup_detail.html", char=char, note=note,
                               summary=stats.summary(matches),
                               last20=stats.summary(matches[-20:]),
                               by_char=stats.by_key(matches, "my_char"),
                               matches=list(reversed(matches))[:50])

    # ---------- Profil ----------

    @app.route("/profil", methods=["GET", "POST"])
    def profile():
        if request.method == "POST":
            name = request.form.get("name", "").strip() or "Joueur"
            main = request.form.get("main_char") or None
            goal = request.form.get("goal_rank") or None
            raw_rating = request.form.get("goal_rating", "").strip()
            raw_id = request.form.get("polaris_id", "").strip()
            polaris_id = wavu.extract_polaris_id(raw_id) if raw_id else None
            errors = []
            if main and main not in all_characters():
                errors.append("Personnage inconnu.")
            if goal and goal not in RANKS:
                errors.append("Rang inconnu.")
            if raw_id and not polaris_id:
                errors.append("ID joueur invalide.")
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
                """UPDATE profile SET name = ?, polaris_id = ?, main_char = ?,
                   goal_rank = ?, goal_rating = ? WHERE id = 1""",
                (name, polaris_id, main, goal, goal_rating))
            get_db().commit()
            flash("Profil mis à jour.")
            return redirect(url_for("dashboard"))
        return render_template("profile.html")

    return app


# ---------- Accès aux données ----------

def get_profile():
    return get_db().execute("SELECT * FROM profile WHERE id = 1").fetchone()


def all_characters():
    """Roster connu + persos apparus dans les imports (nouveaux DLC par ex.)."""
    seen = {r[0] for r in get_db().execute(
        "SELECT my_char FROM matches UNION SELECT opp_char FROM matches")}
    return sorted(set(CHARACTERS) | seen)


def all_matches(opp_char=None, my_char=None):
    """Matchs du plus ancien au plus récent, éventuellement filtrés."""
    sql, params = "SELECT * FROM matches WHERE 1=1", []
    if opp_char:
        sql += " AND opp_char = ?"
        params.append(opp_char)
    if my_char:
        sql += " AND my_char = ?"
        params.append(my_char)
    sql += " ORDER BY played_at, id"
    return get_db().execute(sql, params).fetchall()


def get_match(match_id):
    match = get_db().execute("SELECT * FROM matches WHERE id = ?", (match_id,)).fetchone()
    if match is None:
        abort(404)
    return match


def default_match():
    """Pré-remplit le formulaire avec le dernier perso et le dernier rang utilisés."""
    db = get_db()
    last = db.execute(
        "SELECT my_char FROM matches ORDER BY played_at DESC, id DESC LIMIT 1").fetchone()
    last_rank = db.execute(
        "SELECT rank FROM matches WHERE rank IS NOT NULL "
        "ORDER BY played_at DESC, id DESC LIMIT 1").fetchone()
    return {
        "played_at": date.today().isoformat(),
        "my_char": last["my_char"] if last else get_profile()["main_char"],
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
