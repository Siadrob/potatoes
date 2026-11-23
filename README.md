# T8 Tracker : suivi de progression Tekken 8

Site web perso (Python, Flask, SQLite, pandas) pour suivre sa progression sur Tekken 8
et s'entraîner sur les matchups qui posent problème. Il tourne en local, sur ta machine.

## Fonctionnalités

- **Accueil** : ton perso le plus joué avec son illustration, rang, rating, évolution sur
  7 et 30 jours, semaine par semaine, matchups à travailler.
- **Import automatique** des matchs classés depuis [wank.wavu.wiki](https://wank.wavu.wiki)
  (500 derniers matchs à chaque import, sans doublons) et des rangs Dan via l'API
  [ewgf.gg](https://ewgf.gg) (facultatif).
- **Statistiques** : winrate par perso, calendrier d'activité, analyse des matchups.
- **Entraînement** :
  - *défi du jour* : 10 coups d'un perso qui te bat souvent, avec la vidéo du coup,
    à classer par frames en garde, et une série de jours consécutifs ;
  - *fiches de punitions* : coups adverses à −10 ou moins et ton meilleur punish ;
  - *marges de progression* : matchups qui te coûtent le plus de victoires ;
  - *plan d'entraînement* : tes objectifs à faire, en cours, acquis.
- **Saisie manuelle** de matchs et **notes** par matchup.

## Prérequis

| Outil | Version | Vérifier |
|---|---|---|
| Python | 3.10 ou plus récent (testé avec 3.13) | `python3 --version` |
| Git | n'importe laquelle | `git --version` |
| Connexion internet | pour l'import, les frames, les vidéos, les graphiques et les polices | |

Installer ce qui manque :

- **Debian, Ubuntu, WSL** : `sudo apt update && sudo apt install -y python3 python3-venv git`
- **macOS** (avec [Homebrew](https://brew.sh)) : `brew install python git`
- **Windows** : installe Python depuis [python.org](https://www.python.org/downloads/)
  en cochant « Add python.exe to PATH », et Git depuis [git-scm.com](https://git-scm.com).

## Installation

### Linux, macOS, WSL

```bash
git clone https://github.com/Siadrob/potatoes.git
cd potatoes

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Windows (PowerShell)

```powershell
git clone https://github.com/Siadrob/potatoes.git
cd potatoes

py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Si PowerShell refuse d'activer l'environnement, lance une fois
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`, puis réessaie.

Dans la suite, les commandes supposent que l'environnement est activé : `(.venv)` apparaît
au début de la ligne. À chaque nouveau terminal, réactive-le avec `source .venv/bin/activate`
(ou `.venv\Scripts\Activate.ps1` sous Windows).

## Configuration (facultative)

Sans configuration, tout fonctionne sauf la récupération des rangs Dan. Pour l'activer,
crée le fichier de configuration local à partir du modèle :

```bash
mkdir -p instance
cp config.example.py instance/config.py
```

Sous Windows : `mkdir instance` puis `copy config.example.py instance\config.py`.

Ouvre ensuite `instance/config.py` et colle ta clé API ewgf.gg dans `EWGF_API_KEY`.
Elle se crée sur [ewgf.gg](https://ewgf.gg) : compte, Paramètres, onglet Developer.
On peut aussi la passer par la variable d'environnement `EWGF_API_KEY`.

Le dossier `instance/` est ignoré par Git : ta clé n'est jamais commitée.

## Lancer le site

```bash
flask --app app run
```

Ouvre ensuite http://127.0.0.1:5000. Arrête le serveur avec `Ctrl+C`.

- Port déjà utilisé : `flask --app app run --port 5001`.
- Mode développement, qui recharge le code à chaque modification : ajoute `--debug`.
- Le site n'a pas de mot de passe : garde-le en local, ne l'expose pas sur internet.

## Premier démarrage

À la première visite, le site demande ton **ID Tekken** (ex. `4qLJmf7THeE2`, visible dans
ton profil en jeu) ou l'URL de ta page ewgf.gg. Ensuite il va chercher tout seul :

- ton pseudo et tes 500 derniers matchs classés, avec ton rating (wank.wavu.wiki) ;
- tes rangs Dan, si une clé ewgf.gg est configurée ;
- l'illustration de ton perso le plus joué (site officiel) ;
- tes mains : tes deux persos les plus joués, modifiables dans le profil.

L'ID est gardé un an dans un cookie : les visites suivantes ouvrent directement ta page.
Tes matchs sont réimportés automatiquement quand la dernière mise à jour date de plus de
6 heures (ou à la demande : menu du joueur, « ↻ Actualiser mes matchs »). L'historique
s'accumule au fil du temps, au-delà des 500 derniers matchs.

**Plusieurs joueurs** peuvent utiliser le même site : chacun entre son ID et ne voit que
ses données (menu du joueur, « Changer de joueur »). Il n'y a pas de mot de passe : l'ID
Tekken est public, donc quiconque l'entre sur ce site voit tes notes et ton plan.
Garde le site en local ou entre personnes de confiance.

La base de données est créée automatiquement au premier lancement, dans
`instance/progression.db`, avec la clé qui signe les cookies (`instance/secret_key`).

## Mettre à jour

```bash
git pull
source .venv/bin/activate
pip install -r requirements.txt
```

La base de données existante est mise à jour automatiquement au lancement suivant.

## Sauvegarder ou changer de machine

Toutes tes données sont dans le dossier `instance/` :

| Fichier | Contenu |
|---|---|
| `instance/progression.db` | joueurs, matchs, notes, quiz, plans d'entraînement, cache des frames |
| `instance/config.py` | ta configuration (clé API) |
| `instance/secret_key` | clé de signature des cookies (générée automatiquement) |
| `instance/portraits/` | illustrations des persos |

Pour changer de machine : installe le projet comme ci-dessus, puis copie ce dossier
`instance/` à la racine du projet.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

Les tests n'utilisent pas internet : les accès réseau sont simulés.

## Dépannage

| Problème | Solution |
|---|---|
| `python3: command not found` | Installe Python (voir Prérequis). Sous Windows, utilise `py` à la place de `python3`. |
| `ensurepip is not available` à la création du venv | `sudo apt install python3-venv` (Debian, Ubuntu, WSL) |
| `flask: command not found` | L'environnement n'est pas activé : `source .venv/bin/activate` |
| `Address already in use` / port 5000 occupé | Un autre serveur tourne déjà : arrête-le, ou lance avec `--port 5001`. Sur macOS, le port 5000 est souvent pris par AirPlay. |
| L'import wavu échoue (403 ou réseau) | Vérifie ta connexion et l'ID joueur, puis réessaie plus tard. |
| « ewgf : erreur invalid_api_key » | La clé dans `instance/config.py` est fausse ou révoquée : régénère-la sur ewgf.gg. |
| « ewgf : erreur rate_limit_exceeded » | Quota gratuit (100 requêtes par heure) atteint : réessaie l'heure suivante. |
| Graphiques ou polices absents | Ils sont chargés depuis internet (jsDelivr, Google Fonts) : vérifie la connexion. |
| Une page affiche « Frame data indisponible » | Le wiki Wavu est injoignable : réessaie plus tard. Les frames déjà téléchargées restent en cache 14 jours. |

## Structure du projet

| Fichier | Rôle |
|---|---|
| `app.py` | Application Flask : routes et formulaires |
| `db.py`, `schema.sql` | Base SQLite, schéma et migrations automatiques |
| `stats.py` | Statistiques de matchs (winrate, séries, sessions, progression) |
| `wavu.py`, `ewgf.py` | Import des matchs (wank.wavu.wiki) et des rangs Dan (API ewgf.gg) |
| `framedata.py` | Frame data du wiki Wavu en DataFrames pandas, cache, punitions |
| `training.py` | Quiz, défi du jour, marges de progression |
| `portraits.py` | Illustrations des persos |
| `data.py` | Roster et rangs, à compléter à chaque nouveau DLC |
| `config.example.py` | Modèle de configuration locale |
| `templates/`, `static/` | Pages HTML et style |
| `tests/` | Tests automatiques (pytest) |

## Données et crédits

Projet non affilié à Bandai Namco. Matchs : [Wavu Wank](https://wank.wavu.wiki) et
[ewgf.gg](https://ewgf.gg). Frame data et vidéos des coups : [Wavu Wiki](https://wavu.wiki).
Illustrations : site officiel Bandai Namco, téléchargées pour un usage local uniquement
et jamais commitées. Les punisseurs sont calculés automatiquement : vérifie-les en training mode.
