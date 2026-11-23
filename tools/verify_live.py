"""Contrôle croisé de T8 Tracker sur des profils réels (accès réseau requis).

    python tools/verify_live.py 4qLJmf7THeE2:user/97b1b8ce 4NLdDTT33td4:user/f155f1b0

Chaque argument : ID Tekken, suivi facultativement de « :<profil start.gg> ».
Les valeurs attendues sont recalculées ici directement depuis les sources (page wavu,
API ewgf, API start.gg) avec un décodage indépendant du code du site, puis comparées au
texte affiché par chaque page. Tout se passe sur une copie temporaire de la base :
les données réelles ne sont pas modifiées.
"""

import json
import os
import re
import shutil
import sys
import tempfile
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone

PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT)
os.chdir(PROJECT)

import runpy  # noqa: E402

import ewgf  # noqa: E402
import framedata  # noqa: E402
import portraits  # noqa: E402
import wavu  # noqa: E402
from app import create_app  # noqa: E402

CFG = runpy.run_path("instance/config.py") if os.path.exists("instance/config.py") else {}
TODAY = date.today()
results = []


def check(profile, label, ok, detail=""):
    results.append((profile, label, bool(ok), detail))


def text_of(html):
    html = re.sub(r"<script.*?</script>", " ", html, flags=re.S)
    html = re.sub(r"<[^>]+>", " ", html)
    html = html.replace("&#39;", "'").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", html)


# ---------- Références indépendantes ----------

def raw_wavu(pid):
    req = urllib.request.Request(f"https://wank.wavu.wiki/player/{pid}", headers={"User-Agent": "T8Tracker-verif"})
    html = urllib.request.urlopen(req, timeout=30).read().decode()
    name = re.search(r"<title>(.*?) • Wavu Wank</title>", html).group(1)
    steam = re.search(r"steamcommunity\.com/profiles/(\d+)", html)
    rows = []
    for tr in re.findall(r"<tr>(.*?)</tr>", html.split('class="game-list"')[1], re.S):
        ts = re.search(r"printDateTime\((\d+)\)", tr)
        left, right = tr.split('class="right"')
        ids = re.findall(r'href="/player/(\w+)"', tr)
        chars = re.findall(r'class="char">([^<]+)<', tr)
        rating = re.search(r'class="rating">\s*(\d+)\s*<span class="\w+">\s*([+-]?\d+)', left)
        score = re.search(r'class="result">\s*(\d+)-(\d+)', tr)
        if not (ts and score and len(chars) == 2):
            continue
        a, b = int(score.group(1)), int(score.group(2))
        if ids[0] != pid:      # le joueur est toujours à gauche sur sa propre page
            continue
        rows.append({"ts": int(ts.group(1)), "day": datetime.fromtimestamp(int(ts.group(1)), timezone.utc).date(),
                     "char": chars[0].strip(), "opp": chars[1].strip(),
                     "res": "W" if a > b else "L" if a < b else "D",
                     "after": int(rating.group(1)) + int(rating.group(2)) if rating else None,
                     "before": int(rating.group(1)) if rating else None})
    rows.sort(key=lambda r: r["ts"])
    return name, steam.group(1) if steam else None, rows


def wr(rows):
    w = sum(r["res"] == "W" for r in rows)
    return round(100 * w / len(rows), 1) if rows else None, w, sum(r["res"] == "L" for r in rows)


def delta_since(rows, since):
    rated = [r for r in rows if r["after"] is not None]
    if not rated:
        return None
    before = [r for r in rated if r["day"] < since]
    ref = before[-1]["after"] if before else rated[0]["before"]
    return rated[-1]["after"] - ref


def ewgf_rank(pid, char):
    key = CFG.get("EWGF_API_KEY")
    if not key:
        return None
    battles = ewgf.fetch_battles(pid, key)
    for b in sorted(battles, key=lambda b: b["battle_at"], reverse=True):
        if b.get("battle_type") != "RANKED_BATTLE":
            continue
        side = "p1" if b["p1_tekken_id"] == pid else "p2"
        if b[f"{side}_char"] == char:
            return b[f"{side}_dan_rank"]
    return None


# ---------- Contrôles ----------

def verify(profile, app):
    pid = profile["pid"]
    tag = pid
    name, steam, rows = raw_wavu(pid)
    tag = f"{name} ({pid})"
    client = app.test_client()
    r = client.post("/connexion", data={"polaris_id": pid}, follow_redirects=True)
    home = text_of(r.get_data(as_text=True))
    check(tag, "connexion + pseudo", f"Bienvenue {name}" in home)

    by_char = defaultdict(list)
    for row in rows:
        by_char[row["char"]].append(row)
    order = sorted(by_char, key=lambda c: -len(by_char[c]))
    main = order[0]
    d7, d14, d30, d60 = (TODAY - timedelta(days=n) for n in (6, 13, 29, 59))

    # Accueil, pour les deux persos les plus joués
    for char in order[:2]:
        rs = by_char[char]
        page = text_of(client.get(f"/?perso={char}").get_data(as_text=True))
        rate, w, l = wr(rs)
        rating_now = rs[-1]["after"]
        week = [x for x in rs if x["day"] >= d7]
        month = [x for x in rs if x["day"] >= d30]
        check(tag, f"accueil {char} : titre", f"Statistiques détaillées de {char}" in page)
        check(tag, f"accueil {char} : rating μ {rating_now}", f"μ {rating_now}" in page)
        check(tag, f"accueil {char} : winrate {rate} % ({w}V/{l}D)", f"{rate} %" in page and f"{w}V / {l}D" in page)
        d = delta_since(rs, d7)
        check(tag, f"accueil {char} : rating 7 jours {d:+d}" if d is not None else f"accueil {char} : rating 7 j",
              d is None or f"{d:+d} sur 7 jours" in page, page[page.find("RATING"):page.find("RATING") + 80])
        d30v = delta_since(rs, d30)
        check(tag, f"accueil {char} : rating 30 jours {d30v:+d}", d30v is None or f"30 derniers jours {d30v:+d}" in page)
        if week:
            wrt, ww, wl = wr(week)
            check(tag, f"accueil {char} : semaine {ww}V/{wl}D", f"{ww}V / {wl}D en {len(week)} matchs" in page)
        if month:
            mr, mw, ml = wr(month)
            check(tag, f"accueil {char} : 30 jours {mw}V/{ml}D", f"{mw}V / {ml}D en {len(month)} matchs" in page)
        # Matchups du mois (4 matchs min.) : le pire doit apparaître dans « À travailler »
        opp = defaultdict(list)
        for x in month:
            opp[x["opp"]].append(x)
        cands = [(wr(v)[0], -len(v), k) for k, v in opp.items() if len(v) >= 4]
        if cands:
            worst = min(cands)[2]
            seg = page[page.find("À travailler"):page.find("Points forts")]
            check(tag, f"accueil {char} : pire matchup du mois = {worst}", worst in seg, seg[:160])
        rank = ewgf_rank(pid, char)
        if rank:
            check(tag, f"accueil {char} : rang Dan {rank}", rank in page)

    # Profil et liens
    page = text_of(client.get("/").get_data(as_text=True))
    raw = client.get("/").get_data(as_text=True)
    check(tag, f"accueil : perso le plus joué = {main}", f"Statistiques détaillées de {main}" in page)
    if steam:
        check(tag, "lien Steam", f"steamcommunity.com/profiles/{steam}" in raw)
    check(tag, "lien ewgf.gg", f"ewgf.gg/player/{pid}" in raw)

    # Statistiques : bilan de chaque perso
    stats = text_of(client.get("/stats?perso=tous").get_data(as_text=True))
    for char in order:
        rate, w, l = wr(by_char[char])
        check(tag, f"statistiques {char} : {w}V/{l}D", f"{w}V / {l}D · {len(by_char[char])} matchs" in stats)

    # Entraînement : marges de progression (60 jours) et défi du jour
    hub = client.get(f"/entrainement?perso={main}").get_data(as_text=True)
    recent = [x for x in by_char[main] if x["day"] >= d60]
    opp = defaultdict(list)
    for x in recent:
        opp[x["opp"]].append(x)
    margins = sorted(((len(v) / 2 - wr(v)[1]) / len(recent), k) for k, v in opp.items()
                     if len(v) >= 5 and len(v) / 2 - wr(v)[1] > 0)
    if margins:
        top = margins[-1][1]
        first_row = re.search(r'Marges de progression.*?<strong>([^<]+)</strong>', hub, re.S)
        check(tag, f"entraînement : 1re marge de progression = {top}", first_row and first_row.group(1) == top,
              first_row.group(1) if first_row else "")
    losers = Counter(x["opp"] for x in by_char[main] if x["day"] >= d30 and x["res"] == "L")
    top5 = [c for c, _ in losers.most_common(5)]
    m = re.search(r"10 coups de <strong[^>]*>([^<]+)</strong>", hub)
    check(tag, f"défi du jour : adversaire parmi {top5}", m and m.group(1) in top5, m.group(1) if m else "")
    loc = client.post(f"/entrainement/defi?perso={main}").headers.get("Location", "")
    quiz = client.get(loc).get_data(as_text=True) if loc else ""
    check(tag, "défi du jour : 10 questions", quiz.count('class="card qcard"') == 10)
    with app.app_context():
        from db import get_db
        db = get_db()
        sess = db.execute("SELECT questions, my_char FROM quiz_sessions WHERE player_id = ? AND mode = 'daily'",
                          (pid,)).fetchone()
        qs = json.loads(sess["questions"]) if sess else []
        my_moves = set(framedata.load(db, main)["command"])
    check(tag, f"défi du jour : joué avec {main}", sess and sess["my_char"] == main)
    bad = [q["punisher"]["command"] for q in qs if q.get("punisher") and q["punisher"]["command"] not in my_moves]
    check(tag, f"défi du jour : punitions issues des coups de {main}", not bad, str(bad))
    punish = client.get(f"/entrainement/punitions?adversaire={losers.most_common(1)[0][0] if losers else 'King'}&perso={main}")
    check(tag, "fiche de punitions", punish.status_code == 200 and "10 à 12 frames" in punish.get_data(as_text=True))

    # Tournois (on part d'un compte non lié, quel que soit l'état de la base copiée)
    if not (CFG.get("STARTGG_TOKEN") and profile.get("startgg")):
        return client
    client.post("/tournois/delier")
    t = client.get("/tournois").get_data(as_text=True)
    import startgg
    run = lambda q, v=None: startgg.post(CFG["STARTGG_TOKEN"], q, v)
    owner_display = startgg.current_user(run)["display"]
    should_suggest = " ".join(name.lower().split()) == " ".join(owner_display.lower().split())
    check(tag, "tournois : suggestion « C'est moi » seulement pour le compte du token",
          ("C'est moi" in t) == should_suggest)
    r = client.post("/tournois/lier", data={"profile": f"https://www.start.gg/{profile['startgg']}"},
                    follow_redirects=True)
    tp = text_of(r.get_data(as_text=True))
    q = """query($slug: String!, $uid: ID!) { user(slug: $slug) { id player { id }
      events(query: {perPage: 50, page: 1, filter: {videogameId: [49783]}}) { pageInfo { total }
        nodes { numEntrants userEntrant(userId: $uid) { standing { placement } } } } } }"""
    uid = run("query($s: String!) { user(slug: $s) { id } }", {"s": profile["startgg"]})["user"]["id"]
    data = run(q, {"slug": profile["startgg"], "uid": uid})["user"]
    total = data["events"]["pageInfo"]["total"]
    placed = [(n["userEntrant"]["standing"]["placement"], n["numEntrants"]) for n in data["events"]["nodes"]
              if n.get("userEntrant") and (n["userEntrant"].get("standing") or {}).get("placement")]
    best = min(placed, key=lambda p: (round(100 * p[0] / p[1]), p[0])) if placed else None
    check(tag, f"tournois : {total} tournois", f"Tournois {total} dont" in tp, tp[tp.find("Tournois"):][:60])
    if best:
        check(tag, f"tournois : meilleur placement {best[0]}e / {best[1]}", f"{best[0]}" in tp and f"/ {best[1]}" in tp)
    return client


def main(argv):
    profiles = []
    for arg in argv:
        pid, _, slug = arg.partition(":")
        profiles.append({"pid": pid, "startgg": slug or None})
    if len(profiles) < 2:
        sys.exit("Donne au moins deux profils : python tools/verify_live.py ID1[:user/xxxx] ID2[:user/yyyy]")
    work = tempfile.mkdtemp(prefix="t8-verif-")
    db = os.path.join(work, "verify.db")
    source = os.path.join(PROJECT, "instance/progression.db")
    if os.path.exists(source):
        shutil.copy(source, db)
    pdir = os.path.join(work, "portraits")
    os.makedirs(pdir, exist_ok=True)
    app = create_app({"DATABASE": db, "PORTRAITS_DIR": pdir, "SECRET_KEY": "verif",
                      "WAVU_FETCH": wavu.fetch_player_page, "FRAMEDATA_FETCH": framedata.fetch_raw,
                      "PORTRAIT_OFFICIAL": portraits.fetch_official, "EWGF_API_KEY": CFG.get("EWGF_API_KEY"),
                      "STARTGG_TOKEN": CFG.get("STARTGG_TOKEN"), "ENABLE_MATCHES_PAGES": False})
    clients = [verify(p, app) for p in profiles]

    # Séparation des données entre les deux premiers joueurs
    a, b = clients[:2]
    a.post("/plan", data={"category": "autre", "title": "OBJECTIF-SECRET-A"})
    a.post("/widgets", json={"layout": [{"id": "plan", "size": "l"}]})
    b_home = b.get("/").get_data(as_text=True)
    check("séparation", "le plan de A n'apparaît pas chez B", "OBJECTIF-SECRET-A" not in b.get("/plan").get_data(as_text=True))
    check("séparation", "la disposition de A ne s'applique pas à B", b_home.count('class="card widget') > 1)
    check("séparation", "A garde sa disposition", a.get("/").get_data(as_text=True).count('class="card widget') == 1)
    if all(p.get("startgg") for p in profiles[:2]) and CFG.get("STARTGG_TOKEN"):
        check("séparation", "les tournois de A et B diffèrent",
              text_of(a.get("/tournois").get_data(as_text=True))[:3000]
              != text_of(b.get("/tournois").get_data(as_text=True))[:3000])

    width = max(len(r[1]) for r in results)
    for prof, label, ok, detail in results:
        print(f"{'✓' if ok else '✗'} [{prof}] {label.ljust(width)} {'' if ok else '→ ' + detail[:150]}")
    failed = [r for r in results if not r[2]]
    print(f"\n{len(results) - len(failed)}/{len(results)} contrôles réussis")
    shutil.rmtree(work, ignore_errors=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
