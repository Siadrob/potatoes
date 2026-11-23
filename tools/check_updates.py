"""Vérifie que les dépendances du projet sont à jour (accès réseau requis).

    python tools/check_updates.py

- Python : version utilisée et paquets installés dans l'environnement courant (pip).
- JavaScript : bibliothèques chargées depuis le CDN dans templates/ (registre npm).

Une version n'est proposée qu'une fois publiée depuis au moins 14 jours : les toutes
dernières reçoivent souvent un correctif dans la foulée.
"""

import json
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MIN_AGE_DAYS = 14


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "T8Tracker-check-updates"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def age_days(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).days


def as_tuple(version):
    return tuple(int(n) for n in re.findall(r"\d+", version)[:3])


def latest_mature(versions_with_dates):
    """Dernière version stable publiée depuis au moins MIN_AGE_DAYS jours."""
    ok = [(v, d) for v, d in versions_with_dates
          if re.fullmatch(r"\d+(\.\d+)*", v) and age_days(d) >= MIN_AGE_DAYS]
    return max(ok, key=lambda x: as_tuple(x[0]), default=(None, None))


def check_python_packages():
    print(f"Python {sys.version.split()[0]} ({sys.executable})")
    out = subprocess.run([sys.executable, "-m", "pip", "list", "--format=json"],
                         capture_output=True, text=True, check=True).stdout
    late = 0
    for pkg in sorted(json.loads(out), key=lambda p: p["name"].lower()):
        info = get_json(f"https://pypi.org/pypi/{pkg['name']}/json")
        releases = [(v, files[0]["upload_time_iso_8601"]) for v, files in info["releases"].items() if files]
        newest, date = latest_mature(releases)
        if newest and as_tuple(newest) > as_tuple(pkg["version"]):
            late += 1
            print(f"  ↑ {pkg['name']:12} {pkg['version']:>9} → {newest} (publiée le {date[:10]})")
    print("  ✓ tous les paquets Python sont à jour" if not late else
          "  Pour mettre à jour : pip install --upgrade <paquet>, puis relancer les tests.")
    return late


def check_js_libraries():
    print("Bibliothèques JavaScript (templates/)")
    used = set()
    for path in (ROOT / "templates").rglob("*.html"):
        used |= set(re.findall(r"cdn\.jsdelivr\.net/npm/([a-z0-9.-]+)@([0-9.]+)", path.read_text()))
    late = 0
    for name, version in sorted(used):
        info = get_json(f"https://registry.npmjs.org/{name}")
        newest, date = latest_mature(info["time"].items())
        if newest and as_tuple(newest) > as_tuple(version):
            late += 1
            print(f"  ↑ {name:12} {version:>9} → {newest} (publiée le {date[:10]})")
        else:
            print(f"  ✓ {name:12} {version:>9}")
    if late:
        print("  Pour mettre à jour : remplacer la version dans les templates, puis vérifier les pages.")
    return late


if __name__ == "__main__":
    total = check_python_packages() + check_js_libraries()
    sys.exit(1 if total else 0)
