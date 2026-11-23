"""Import de l'historique de matchs depuis Wavu Wank (wank.wavu.wiki).

Wavu publie les matchs classés de Tekken 8 (mêmes données qu'ewgf.gg).
On lit la page joueur (500 derniers matchs) en une seule requête.
"""

import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

BASE_URL = "https://wank.wavu.wiki"
POLARIS_ID_RE = re.compile(r"^[A-Za-z0-9]{8,20}$")
USER_AGENT = "tekken-progress-tracker (usage personnel)"


def extract_polaris_id(text):
    """Accepte un ID brut ou une URL ewgf.gg / wavu (…/player/<id>)."""
    text = (text or "").strip().rstrip("/")
    m = re.search(r"/player/([A-Za-z0-9]+)", text)
    candidate = m.group(1) if m else text
    return candidate if POLARIS_ID_RE.match(candidate) else None


def fetch_player_page(polaris_id, timeout=30):
    """Page joueur standard : les 500 derniers matchs classés.

    Le paramètre `?limit=` du site est refusé (403) aux clients automatisés :
    on s'en tient à la page par défaut et on accumule l'historique import après import.
    """
    url = f"{BASE_URL}/player/{polaris_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


class _GameListParser(HTMLParser):
    """Extrait les lignes du tableau <div class="game-list">."""

    def __init__(self):
        super().__init__()
        self.rows = []
        self._in_list = False
        self._div_depth = 0
        self._row = None
        self._td = None
        self._spans = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        cls = (attrs.get("class") or "").split()
        if tag == "div":
            if self._in_list:
                self._div_depth += 1
            elif "game-list" in cls:
                self._in_list, self._div_depth = True, 1
            return
        if not self._in_list:
            return
        if tag == "tr":
            self._row = {"left": {}, "right": {}, "score": ""}
        elif tag == "td" and self._row is not None:
            self._td = cls[0] if cls else None
        elif tag == "span":
            self._spans.append(cls[0] if cls else None)
        elif tag == "script":
            self._in_script = True
        elif tag == "a" and self._td in ("left", "right") and "player" in self._spans:
            m = re.search(r"/player/([A-Za-z0-9]+)", attrs.get("href", ""))
            if m:
                self._row[self._td]["id"] = m.group(1)

    def handle_endtag(self, tag):
        if not self._in_list:
            return
        if tag == "div":
            self._div_depth -= 1
            if self._div_depth == 0:
                self._in_list = False
        elif tag == "tr" and self._row is not None:
            self.rows.append(self._row)
            self._row = None
        elif tag == "td":
            self._td = None
        elif tag == "span" and self._spans:
            self._spans.pop()
        elif tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._row is None or not data.strip():
            return
        text = data.strip()
        if self._td == "battle-at" and self._in_script:
            m = re.search(r"\((\d+)\)", text)
            if m:
                self._row["battle_at"] = int(m.group(1))
        elif self._td == "result":
            self._row["score"] += text
        elif self._td in ("left", "right") and self._spans:
            side = self._row[self._td]
            span = self._spans[-1]
            if span == "player":
                side["name"] = text
            elif span == "char":
                side["char"] = text
            elif span == "rating":
                side["rating"] = int(text) if text.lstrip("-").isdigit() else None
            elif span in ("win", "lose", "draw"):
                side["change"] = int(text) if re.fullmatch(r"[+-]?\d+", text) else None


def parse_matches(html, polaris_id):
    """Transforme la page joueur en matchs, toujours du point de vue de `polaris_id`."""
    parser = _GameListParser()
    parser.feed(html)
    matches = []
    for row in parser.rows:
        left, right = row["left"], row["right"]
        score = re.fullmatch(r"(\d+)\s*-\s*(\d+)", row["score"].strip())
        if not (score and "battle_at" in row and left.get("char") and right.get("char")):
            continue
        a, b = int(score.group(1)), int(score.group(2))
        if right.get("id") == polaris_id:
            left, right, a, b = right, left, b, a
        elif left.get("id") != polaris_id:
            continue
        played = datetime.fromtimestamp(row["battle_at"], tz=timezone.utc)
        matches.append({
            "played_at": played.strftime("%Y-%m-%d %H:%M"),
            "my_char": left["char"],
            "opp_char": right["char"],
            "opp_name": right.get("name"),
            "result": "W" if a > b else "L" if a < b else "D",
            "rounds_won": a,
            "rounds_lost": b,
            # wavu affiche le rating d'avant le match : on stocke celui d'après.
            "rating": (left["rating"] + (left.get("change") or 0)
                       if left.get("rating") is not None else None),
            "rating_change": left.get("change"),
            "source": "wavu",
            "external_id": f"battle:{row['battle_at']}:{right.get('id', '')}",
        })
    return matches


def parse_player_name(html_text):
    """Pseudo du joueur, lu dans le titre de la page ('PLS | Sia • Wavu Wank')."""
    import html as html_lib

    m = re.search(r"<title>(.*?)</title>", html_text or "", re.S)
    if not m:
        return None
    name = html_lib.unescape(m.group(1)).split("•")[0].strip()
    return name or None
