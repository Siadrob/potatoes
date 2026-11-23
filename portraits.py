"""Portraits de personnages fournis par l'utilisateur (stockés dans instance/portraits)."""

import re
import unicodedata
from pathlib import Path

MAX_BYTES = 3 * 1024 * 1024

# Signature des formats d'image acceptés -> extension.
SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
)
EXTENSIONS = ("png", "jpg", "gif", "webp")


def slug(char):
    text = unicodedata.normalize("NFKD", char).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "perso"


def detect_format(data):
    for magic, ext in SIGNATURES:
        if data.startswith(magic):
            return ext
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def find(folder, char):
    for ext in EXTENSIONS:
        path = Path(folder) / f"{slug(char)}.{ext}"
        if path.exists():
            return path
    return None


def save(folder, char, data):
    """Enregistre l'image ; lève ValueError si elle est invalide."""
    if not data:
        raise ValueError("Aucun fichier reçu.")
    if len(data) > MAX_BYTES:
        raise ValueError("Image trop lourde (3 Mo maximum).")
    ext = detect_format(data)
    if ext is None:
        raise ValueError("Format non reconnu : utilise une image PNG, JPG, GIF ou WebP.")
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    remove(folder, char)
    (folder / f"{slug(char)}.{ext}").write_bytes(data)


def remove(folder, char):
    for ext in EXTENSIONS:
        (Path(folder) / f"{slug(char)}.{ext}").unlink(missing_ok=True)


def download(url, timeout=15):
    """Télécharge une image depuis une URL http(s) ; lève ValueError en cas de problème."""
    import urllib.error
    import urllib.request
    from urllib.parse import urlparse

    if urlparse(url).scheme not in ("http", "https"):
        raise ValueError("L'adresse doit commencer par http:// ou https://.")
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (portrait perso)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read(MAX_BYTES + 1)
    except (urllib.error.URLError, TimeoutError, ValueError) as e:
        raise ValueError(f"Impossible de télécharger l'image ({e}).") from e
    if len(data) > MAX_BYTES:
        raise ValueError("Image trop lourde (3 Mo maximum).")
    return data


# ---------- Illustration officielle (site Bandai Namco Europe) ----------

OFFICIAL_PAGE = "https://en.bandainamcoent.eu/tekken/tekken-8/characters/{}"

# Identifiant de la fiche officielle quand il diffère du nom court du perso.
OFFICIAL_SLUGS = {
    "Alisa": "alisa-bosconovitch", "Anna": "anna-williams", "Asuka": "asuka-kazama",
    "Bryan": "bryan-fury", "Claudio": "claudio-serafino", "Clive": "clive-rosfield",
    "Dragunov": "sergei-dragunov", "Eddy": "eddy-gordo", "Feng": "feng-wei",
    "Heihachi": "heihachi-mishima", "Jin": "jin-kazama", "Jun": "jun-kazama",
    "Kazuya": "kazuya-mishima", "Lars": "lars-alexandersson", "Law": "marshall-law",
    "Lee": "lee-chaolan", "Leo": "leo-kliesen", "Leroy": "leroy-smith",
    "Lidia": "lidia-sobieska", "Nina": "nina-williams", "Paul": "paul-phoenix",
    "Roger": "roger-jr", "Steve": "steve-fox", "Victor": "victor-chevalier",
    "Xiaoyu": "ling-xiaoyu",
}


def official_candidates(char):
    first = OFFICIAL_SLUGS.get(char)
    return [s for s in dict.fromkeys([first, slug(char)]) if s]


def fetch_official(char, timeout=10):
    """Télécharge l'illustration (balise og:image) de la fiche officielle du perso."""
    import urllib.error
    import urllib.request

    headers = {"User-Agent": "Mozilla/5.0 (portrait perso)"}
    for page_slug in official_candidates(char):
        req = urllib.request.Request(OFFICIAL_PAGE.format(page_slug), headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                html = resp.read(2_000_000).decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError):
            continue
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if m:
            og = m.group(1).replace("&amp;", "&")
            # og:image est recadré en 1200x630 (tête coupée) : on préfère l'image d'origine.
            for url in (original_image_url(og), og):
                try:
                    return download(url, timeout=timeout)
                except ValueError:
                    continue
    raise ValueError(f"Illustration officielle introuvable pour {char}.")


def original_image_url(url):
    """'…/styles/og_image_1200x630/s3/high/x.png?itok=…' -> '…/high/x.png'."""
    return re.sub(r"/styles/[^/]+/s3/", "/", url).split("?")[0]


def failed_marker(folder, char):
    return Path(folder) / f"{slug(char)}.introuvable"
