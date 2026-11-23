import os
import urllib.error
from datetime import date, datetime
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, url_for

import ewgf
import stats
import wavu
from data import CHARACTERS, RANKS, rank_level
from db import close_db, get_db, init_db, save_imported


def create_app(test_config=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-local-only"),
        DATABASE=str(Path(app.instance_path) / "progression.db"),
        # Fonctions d'accès réseau, remplaçables dans les tests.
        WAVU_FETCH=wavu.fetch_player_page,
        EWGF_FETCH=ewgf.fetch_battles,
        EWGF_API_KEY=os.environ.get("EWGF_API_KEY"),
    )
    if test_config:
        app.config.update(test_config)
    else:
        # Réglages locaux (clé API…) dans instance/config.py, exclu de Git.
        app.config.from_pyfile("config.py", silent=True)

    init_db(app.config["DATABASE"])
    app.teardown_appcontext(close_db)

    @app.context_processor
    def inject_globals():
        return {"CHARACTERS": all_characters(), "RANKS": RANKS, "profile": get_profile()}

    # ---------- Tableau de bord ----------

    @app.get("/")
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
            db = get_db()
            db.execute("UPDATE profile SET polaris_id = ? WHERE id = 1", (polaris_id,))
            db.commit()

            # 1. wavu : 500 derniers matchs classés, avec le rating.
            try:
                html = app.config["WAVU_FETCH"](polaris_id)
                found = wavu.parse_matches(html, polaris_id)
                added = save_imported(db, found)
                flash(f"wavu : {len(found)} matchs classés lus, {added} nouveaux."
                      if found else "wavu : aucun match trouvé pour cet ID.",
                      "message" if found else "error")
            except (urllib.error.URLError, TimeoutError) as e:
                flash(f"wavu : impossible de joindre wank.wavu.wiki ({e}).", "error")

            # 2. ewgf : rangs Dan des 50 derniers matchs (si une clé API est configurée).
            api_key = app.config.get("EWGF_API_KEY")
            if api_key:
                try:
                    battles = app.config["EWGF_FETCH"](polaris_id, api_key)
                    found = ewgf.parse_battles(battles, polaris_id)
                    added = save_imported(db, found)
                    flash(f"ewgf : {len(found)} matchs classés lus (rangs Dan), "
                          f"{added} nouveaux.")
                except ewgf.EwgfError as e:
                    flash(f"ewgf : erreur {e.code}. {e}", "error")
            return redirect(url_for("dashboard"))
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
            mains = [c for c in request.form.getlist("mains") if c]
            goal = request.form.get("goal_rank") or None
            raw_rating = request.form.get("goal_rating", "").strip()
            raw_id = request.form.get("polaris_id", "").strip()
            polaris_id = wavu.extract_polaris_id(raw_id) if raw_id else None
            errors = []
            if any(c not in all_characters() for c in mains):
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
                """UPDATE profile SET name = ?, polaris_id = ?, mains = ?,
                   goal_rank = ?, goal_rating = ? WHERE id = 1""",
                (name, polaris_id, ",".join(mains) or None, goal, goal_rating))
            get_db().commit()
            flash("Profil mis à jour.")
            return redirect(url_for("dashboard"))
        return render_template("profile.html")

    return app


# ---------- Accès aux données ----------

def get_profile():
    return get_db().execute("SELECT * FROM profile WHERE id = 1").fetchone()


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
    sql, params = "SELECT * FROM matches WHERE 1=1", []
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
