#!/usr/bin/env python3
"""Lanceur tout-en-un de T8 Tracker.

    python3 run.py              (Linux, macOS, WSL)
    py run.py                   (Windows, ou double-clic sur ce fichier)

Au premier lancement : crée l'environnement Python (.venv), installe les dépendances,
puis démarre le site et ouvre le navigateur. Les fois suivantes : démarre directement.
Les dépendances sont réinstallées automatiquement si requirements.txt a changé.

Options : --port 5000 (port souhaité), --no-browser (ne pas ouvrir le navigateur).
Ce script n'utilise que la bibliothèque standard : il fonctionne avant toute installation.
"""

import argparse
import hashlib
import os
import platform
import signal
import socket
import subprocess
import sys
import threading
import time
import venv
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
STAMP = VENV / ".requirements.sha256"
MIN_PYTHON = (3, 10)


def say(message):
    print(f"[T8 Tracker] {message}", flush=True)


def venv_python(venv_dir=VENV):
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def requirements_hash(path=REQUIREMENTS):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def needs_install(venv_dir=VENV, requirements=REQUIREMENTS):
    stamp = venv_dir / ".requirements.sha256"
    return not stamp.exists() or stamp.read_text().strip() != requirements_hash(requirements)


def create_venv():
    say("Première installation : création de l'environnement Python (.venv)…")
    try:
        venv.create(VENV, with_pip=True)
    except (subprocess.CalledProcessError, OSError) as e:
        hint = ("\n  Sous Debian, Ubuntu ou WSL, installe d'abord le module venv :\n"
                "      sudo apt install -y python3-venv\n  puis relance : python3 run.py"
                if platform.system() == "Linux" else "")
        sys.exit(f"Impossible de créer l'environnement Python ({e}).{hint}")


def install_requirements():
    say("Installation des dépendances (une minute environ la première fois)…")
    py = str(venv_python())
    subprocess.check_call([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
    subprocess.check_call([py, "-m", "pip", "install", "--quiet", "-r", str(REQUIREMENTS)])
    STAMP.write_text(requirements_hash())


def free_port(preferred, host="127.0.0.1", tries=20):
    """Premier port libre à partir de `preferred` (5000 est parfois pris, ex. AirPlay sur macOS)."""
    for port in range(preferred, preferred + tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    sys.exit(f"Aucun port libre entre {preferred} et {preferred + tries - 1}.")


def open_browser(url):
    """Ouvre le navigateur, y compris celui de Windows depuis WSL."""
    if "microsoft" in platform.release().lower():
        try:
            subprocess.Popen(["cmd.exe", "/c", "start", "", url],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    try:
        webbrowser.open(url)
    except webbrowser.Error:
        pass


def main(argv=None):
    parser = argparse.ArgumentParser(description="Installe si besoin et lance T8 Tracker.")
    parser.add_argument("--port", type=int, default=5000, help="port souhaité (défaut : 5000)")
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    args = parser.parse_args(argv)

    if sys.version_info < MIN_PYTHON:
        sys.exit(f"Python {'.'.join(map(str, MIN_PYTHON))} ou plus récent est nécessaire "
                 f"(tu as {platform.python_version()}). Voir le README, section Prérequis.")

    if not venv_python().exists():
        create_venv()
    if needs_install():
        install_requirements()

    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}"
    say(f"Site disponible sur {url}  (Ctrl+C pour arrêter)")
    if not args.no_browser:
        threading.Thread(target=lambda: (time.sleep(1.5), open_browser(url)), daemon=True).start()

    # waitress : serveur web en pur Python, sans l'avertissement « development server » de Flask.
    server = subprocess.Popen([str(venv_python()), "-m", "waitress", "--host=127.0.0.1",
                               f"--port={port}", "--threads=8", "--call", "app:create_app"], cwd=ROOT)
    if hasattr(signal, "SIGTERM"):
        # Arrêt par signal (fermeture du terminal, kill) : on arrête aussi le serveur.
        signal.signal(signal.SIGTERM, lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    try:
        return server.wait()
    except KeyboardInterrupt:
        server.terminate()
        server.wait()
        say("Site arrêté. À bientôt !")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (SystemExit, subprocess.CalledProcessError) as e:
        failed = isinstance(e, subprocess.CalledProcessError) or e.code not in (0, None)
        if failed and os.name == "nt":
            # Lancé par double-clic : on laisse le temps de lire l'erreur avant que la fenêtre se ferme.
            print(e.code if isinstance(e, SystemExit) else f"Échec de l'installation ({e}).")
            input("Appuie sur Entrée pour fermer…")
        raise
