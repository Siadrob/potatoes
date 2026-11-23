"""Client de l'API start.gg (GraphQL) pour la rubrique Tournois.

Un token (STARTGG_TOKEN dans instance/config.py) sert à tout le site ; chaque joueur
lie ensuite son propre profil start.gg (user/xxxxxxxx).
"""

import json
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.start.gg/gql/alpha"
TEKKEN8 = 49783           # identifiant du jeu Tekken 8 sur start.gg
SITE = "https://www.start.gg"
SETS_PAGES = 8            # 8 x 25 = les 200 derniers sets au plus


class StartGGError(Exception):
    pass


def post(token, query, variables=None, timeout=30):
    """Exécute une requête GraphQL et renvoie `data` (lève StartGGError sinon)."""
    req = urllib.request.Request(
        API_URL, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "T8Tracker/0.1 (outil perso de progression)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as e:
        raise StartGGError({401: "token start.gg invalide ou expiré",
                            429: "trop de requêtes, réessaie dans une minute"}.get(e.code, f"erreur HTTP {e.code}")) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise StartGGError(f"start.gg injoignable ({e})") from e
    if payload.get("errors"):
        raise StartGGError(payload["errors"][0].get("message", "erreur start.gg"))
    return payload.get("data") or {}


def parse_slug(text):
    """'https://www.start.gg/user/97b1b8ce/details', 'user/97b1b8ce' ou '97b1b8ce' -> 'user/97b1b8ce'."""
    m = re.search(r"(?:user/)?\b([0-9a-f]{8})\b", (text or "").strip().lower())
    return f"user/{m.group(1)}" if m else None


# ---------- Identité ----------

_IDENTITY = "id slug player { id gamerTag prefix } images { url type }"


def _identity(user):
    if not user or not user.get("player"):
        return None
    player = user["player"]
    avatar = next((i["url"] for i in user.get("images") or [] if i.get("type") == "profile"), None)
    prefix = (player.get("prefix") or "").strip()
    return {"user_id": user["id"], "slug": user["slug"], "player_id": player["id"],
            "gamer_tag": player["gamerTag"], "prefix": prefix, "avatar": avatar,
            "display": f"{prefix} {player['gamerTag']}".strip()}


def current_user(run):
    """Le compte start.gg propriétaire du token."""
    return _identity(run(f"{{ currentUser {{ {_IDENTITY} }} }}").get("currentUser"))


def user_by_slug(run, slug):
    data = run(f"query($slug: String!) {{ user(slug: $slug) {{ {_IDENTITY} }} }}", {"slug": slug})
    return _identity(data.get("user"))


# ---------- Tournois et sets ----------

_EVENTS = """query($slug: String!, $uid: ID!, $page: Int!) { user(slug: $slug) {
  events(query: {perPage: 25, page: $page, filter: {videogameId: [%d]}}) {
    pageInfo { totalPages }
    nodes { id name slug numEntrants startAt isOnline state
      tournament { name slug city countryCode }
      userEntrant(userId: $uid) { standing { placement } } } } } }""" % TEKKEN8

_UPCOMING = """query($slug: String!) { user(slug: $slug) {
  tournaments(query: {perPage: 10, page: 1, filter: {upcoming: true, videogameId: [%d]}}) {
    nodes { name slug startAt city isOnline numAttendees } } } }""" % TEKKEN8

_SETS = """query($pid: ID!, $page: Int!) { player(id: $pid) { sets(perPage: 25, page: $page) {
  pageInfo { totalPages }
  nodes { id fullRoundText winnerId completedAt displayScore
    event { id name videogame { id } tournament { name slug } }
    slots { standing { stats { score { value } } }
      entrant { id name participants { player { id } } } } } } } }"""


def _date(ts):
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else None


def parse_event(node):
    t = node.get("tournament") or {}
    entrants = node.get("numEntrants") or 0
    placement = ((node.get("userEntrant") or {}).get("standing") or {}).get("placement")
    return {
        "id": node["id"], "event": node.get("name"), "tournament": t.get("name"),
        "url": f"{SITE}/{node['slug']}" if node.get("slug") else None,
        "date": _date(node.get("startAt")), "online": bool(node.get("isOnline")),
        "city": t.get("city"), "entrants": entrants, "placement": placement,
        "top_pct": round(100 * placement / entrants) if placement and entrants else None,
        "state": node.get("state"),
    }


def parse_set(node, player_id):
    """Un set du point de vue du joueur ; None si ce n'est pas du Tekken 8 ou s'il n'y figure pas."""
    event = node.get("event") or {}
    if str((event.get("videogame") or {}).get("id")) != str(TEKKEN8):
        return None
    mine = other = None
    for slot in node.get("slots") or []:
        entrant = slot.get("entrant") or {}
        players = [str((p.get("player") or {}).get("id")) for p in entrant.get("participants") or []]
        score = (((slot.get("standing") or {}).get("stats") or {}).get("score") or {}).get("value")
        info = {"entrant_id": entrant.get("id"), "name": entrant.get("name"), "score": score,
                "player_id": players[0] if players else None}
        if str(player_id) in players:
            mine = info
        else:
            other = info
    if mine is None or other is None or node.get("winnerId") is None:
        return None
    dq = node.get("displayScore") == "DQ" or -1 in (mine["score"], other["score"])
    round_text = node.get("fullRoundText") or ""
    t = event.get("tournament") or {}
    return {
        "id": node["id"], "date": _date(node.get("completedAt")),
        "tournament": t.get("name"), "url": f"{SITE}/{t['slug']}" if t.get("slug") else None,
        "round": round_text,
        "bracket": "losers" if "loser" in round_text.lower() else "winners",
        "won": node["winnerId"] == mine["entrant_id"], "dq": dq,
        "my_score": None if dq else mine["score"], "opp_score": None if dq else other["score"],
        "opponent": other["name"], "opponent_id": other["player_id"],
    }


def fetch_all(run, ident):
    """Tournois Tekken 8, sets et tournois à venir du joueur lié."""
    events, page = [], 1
    while True:
        data = run(_EVENTS, {"slug": ident["slug"], "uid": ident["user_id"], "page": page})
        block = ((data.get("user") or {}).get("events")) or {}
        events += [parse_event(n) for n in block.get("nodes") or []]
        if page >= (block.get("pageInfo") or {}).get("totalPages", 1) or page >= 8:
            break
        page += 1
        time.sleep(0.3)

    sets, page = [], 1
    while True:
        data = run(_SETS, {"pid": ident["player_id"], "page": page})
        block = ((data.get("player") or {}).get("sets")) or {}
        sets += [s for s in (parse_set(n, ident["player_id"]) for n in block.get("nodes") or []) if s]
        if page >= (block.get("pageInfo") or {}).get("totalPages", 1) or page >= SETS_PAGES:
            break
        page += 1
        time.sleep(0.3)

    data = run(_UPCOMING, {"slug": ident["slug"]})
    upcoming = [{"name": n["name"], "url": f"{SITE}/{n['slug']}", "date": _date(n.get("startAt")),
                 "city": n.get("city"), "online": bool(n.get("isOnline")),
                 "attendees": n.get("numAttendees")}
                for n in (((data.get("user") or {}).get("tournaments")) or {}).get("nodes") or []]

    events.sort(key=lambda e: e["date"] or "", reverse=True)
    sets.sort(key=lambda s: (s["date"] or "", s["id"]), reverse=True)
    return {"events": events, "sets": sets, "upcoming": upcoming}
