"""Hub Tekken : vidéos YouTube sur un perso et lives Twitch Tekken 8.

Une clé par service pour tout le site (instance/config.py) : YOUTUBE_API_KEY,
TWITCH_CLIENT_ID et TWITCH_CLIENT_SECRET. Les résultats sont mis en cache en base.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

USER_AGENT = "T8Tracker/0.1 (outil perso de progression)"
VIDEOS_TTL = timedelta(hours=24)     # quota YouTube : ~100 recherches par jour
STREAMS_TTL = timedelta(minutes=5)


class MediaError(Exception):
    pass


def _get_json(url, headers=None, data=None, timeout=20):
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        try:
            detail = json.load(e).get("error", {})
            message = detail.get("message") if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError):
            message = ""
        raise MediaError(f"erreur {e.code}{' : ' + message if message else ''}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise MediaError(f"service injoignable ({e})") from e


# ---------- YouTube ----------

# Mots qui signalent un match de tournoi dans un titre de vidéo.
TOURNAMENT_WORDS = ("twt", "evo", "ewc", "top 8", "top 16", "grand final", "winners", "losers", "final",
                    "tournament", "tournoi", "pools", "cup", "major", "masters", "championship", "dojo")


def youtube_videos(api_key, char, limit=8, get=_get_json):
    """Matchs compétitifs récents (moins d'un an) où l'on voit le perso.

    On garde les vidéos dont le titre cite le perso, matchs de tournoi d'abord, puis les
    plus récentes. Durée moyenne (4 à 20 min) : des sets, pas des VOD de plusieurs heures.
    """
    since = (datetime.now(timezone.utc) - timedelta(days=365)).strftime("%Y-%m-%dT%H:%M:%SZ")
    params = {"part": "snippet", "type": "video", "maxResults": 25, "order": "relevance",
              "q": f"Tekken 8 {char} tournament", "publishedAfter": since, "videoDuration": "medium",
              "safeSearch": "moderate", "key": api_key}
    data = get("https://www.googleapis.com/youtube/v3/search?" + urllib.parse.urlencode(params))
    videos = []
    for item in data.get("items") or []:
        vid = (item.get("id") or {}).get("videoId")
        s = item.get("snippet") or {}
        if not vid:
            continue
        thumbs = s.get("thumbnails") or {}
        thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url")
        videos.append({"id": vid, "title": _unescape(s.get("title")), "channel": s.get("channelTitle"),
                       "date": (s.get("publishedAt") or "")[:10], "thumb": thumb,
                       "url": f"https://www.youtube.com/watch?v={vid}"})
    return rank_videos(videos, char, limit)


def rank_videos(videos, char, limit=8):
    char_l = char.lower()
    on_char = [v for v in videos if char_l in v["title"].lower()]
    pool = on_char if len(on_char) >= 4 else on_char + [v for v in videos if v not in on_char]
    for v in pool:
        v["competitive"] = any(w in v["title"].lower() for w in TOURNAMENT_WORDS)
    # Tri stable : d'abord les plus récentes, puis les matchs de tournoi remontent en tête.
    pool.sort(key=lambda v: v["date"], reverse=True)
    pool.sort(key=lambda v: not v["competitive"])
    return pool[:limit]


def _unescape(text):
    import html
    return html.unescape(text or "")


# ---------- Twitch ----------

class Twitch:
    """Client Helix minimal (jeton d'application, gardé jusqu'à son expiration)."""

    def __init__(self, client_id, client_secret, get=_get_json):
        self.client_id, self.client_secret, self.get = client_id, client_secret, get
        self._token, self._expires = None, 0
        self._game_id = None

    def _auth(self):
        if self._token and time.time() < self._expires - 60:
            return self._token
        data = self.get("https://id.twitch.tv/oauth2/token", data=urllib.parse.urlencode({
            "client_id": self.client_id, "client_secret": self.client_secret,
            "grant_type": "client_credentials"}).encode())
        self._token, self._expires = data["access_token"], time.time() + data.get("expires_in", 3600)
        return self._token

    def helix(self, path, params):
        headers = {"Client-Id": self.client_id, "Authorization": f"Bearer {self._auth()}"}
        return self.get(f"https://api.twitch.tv/helix/{path}?{urllib.parse.urlencode(params, doseq=True)}",
                        headers=headers)

    def game_id(self):
        if self._game_id is None:
            games = self.helix("games", {"name": "TEKKEN 8"}).get("data") or []
            if not games:
                raise MediaError("Tekken 8 introuvable sur Twitch")
            self._game_id = games[0]["id"]
        return self._game_id

    def streams(self, first=100):
        data = self.helix("streams", {"game_id": self.game_id(), "first": first, "type": "live"})
        out = []
        for s in data.get("data") or []:
            thumb = (s.get("thumbnail_url") or "").replace("{width}", "320").replace("{height}", "180")
            out.append({"user": s.get("user_name"), "login": s.get("user_login"), "title": s.get("title") or "",
                        "viewers": s.get("viewer_count") or 0, "language": s.get("language"),
                        "thumb": thumb, "url": f"https://www.twitch.tv/{s.get('user_login')}"})
        return out


def rank_streams(streams, char, languages=("fr", "en"), limit=6):
    """Les lives en français d'abord, puis en anglais, puis les autres ; les plus regardés en tête.

    Les lives qui citent le perso dans leur titre reçoivent un badge.
    """
    char_l = (char or "").lower()
    order = {lang: i for i, lang in enumerate(languages)}
    ranked = sorted(streams, key=lambda s: (order.get(s["language"], len(order)), -s["viewers"]))[:limit]
    for s in ranked:
        s["mentions_char"] = bool(char_l) and char_l in s["title"].lower()
    return ranked


# ---------- Cache en base ----------

def ensure_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS media_cache (
        key TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL)""")


def cached(conn, key, ttl, fetch):
    """Valeur en cache si elle a moins de `ttl`, sinon `fetch()` ; garde l'ancienne valeur en cas d'erreur."""
    ensure_table(conn)
    row = conn.execute("SELECT payload, fetched_at FROM media_cache WHERE key = ?", (key,)).fetchone()
    if row and datetime.fromisoformat(row[1]) > datetime.now(timezone.utc) - ttl:
        return json.loads(row[0])
    try:
        value = fetch()
    except MediaError:
        if row:
            return json.loads(row[0])
        raise
    conn.execute("INSERT OR REPLACE INTO media_cache (key, payload, fetched_at) VALUES (?, ?, ?)",
                 (key, json.dumps(value), datetime.now(timezone.utc).isoformat(timespec="seconds")))
    conn.commit()
    return value
