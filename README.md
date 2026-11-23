# T8 Tracker : suivi de progression Tekken 8

Site web perso (Python, Flask, SQLite, pandas) pour suivre sa progression sur Tekken 8
et s'entraîner sur les matchups qui posent problème. Il tourne en local, sur ta machine.

## Fonctionnalités

- **Connexion par ID Tekken** : chaque joueur entre son ID, le site va chercher le reste
  tout seul et ne montre à chacun que ses données (plusieurs joueurs possibles).
- **Accueil personnalisable** : ton perso le plus joué avec son illustration, rang et rating,
  puis des **widgets** au choix (progression, semaine, défi du jour, courbe, matchups,
  calendrier, marges de progression, plan…). Bouton « Personnaliser » : glisser-déposer,
  taille petite / moyenne / large, masquer, ajouter ; disposition enregistrée par joueur.
- **Import automatique** des matchs classés depuis [wank.wavu.wiki](https://wank.wavu.wiki)
  (500 derniers matchs à chaque import, sans doublons) et des rangs Dan via l'API
  [ewgf.gg](https://ewgf.gg) (facultatif).
- **Statistiques** : winrate par perso, calendrier d'activité, analyse des matchups.
- **Tournois** (start.gg) : tes tournois Tekken 8 avec placement et classement relatif,
  évolution des placements, derniers sets, adversaires, bilan winners / losers, tournois
  à venir. Widgets personnalisables comme l'accueil.
- **Entraînement** :
  - *défi du jour* : 10 coups d'un perso qui te bat souvent, avec la vidéo du coup
    (ou un lien vers okizeme.gg quand elle manque), à classer par frames en garde,
    et une série de jours consécutifs ;
  - *fiches de punitions* : coups adverses à −10 ou moins et ton meilleur punish ;
  - *marges de progression* : matchups qui te coûtent le plus de victoires ;
  - *plan d'entraînement* : tes objectifs à faire, en cours, acquis.
- *En pause* : liste des matchs, saisie manuelle et notes par matchup. Réactivables avec
  `ENABLE_MATCHES_PAGES = True` dans `instance/config.py`.

## Démarrage rapide

Il faut seulement **Python 3.10 ou plus récent** (voir [Prérequis](#prérequis) s'il manque).

1. **Récupère le projet** : `git clone https://github.com/Siadrob/potatoes.git`,
   ou sur GitHub, bouton « Code » puis « Download ZIP », et décompresse l'archive.
2. **Lance-le** depuis le dossier du projet :

   ```bash
   python3 run.py        # Linux, macOS, WSL
   py run.py             # Windows (ou double-clic sur run.py)
   ```

C'est tout. Le premier lancement installe ce qu'il faut (environ une minute), puis le site
s'ouvre dans ton navigateur. Les fois suivantes, il démarre directement. Arrête-le avec `Ctrl+C`.

Options : `--port 5050` pour choisir le port (par défaut le premier libre à partir de 5000),
`--no-browser` pour ne pas ouvrir le navigateur.

## Prérequis

| Outil | Version | Vérifier |
|---|---|---|
| Python | 3.10 ou plus récent (testé avec 3.13) | `python3 --version` (Windows : `py --version`) |
| Connexion internet | pour l'import, les frames, les vidéos, les graphiques et les polices | |
| Git (facultatif) | pour `git clone` et les mises à jour ; sinon, télécharge le ZIP | `git --version` |

Installer Python s'il manque :

- **Debian, Ubuntu, WSL** : `sudo apt update && sudo apt install -y python3 python3-venv`
- **macOS** (avec [Homebrew](https://brew.sh)) : `brew install python`
- **Windows** : [python.org](https://www.python.org/downloads/), en cochant « Add python.exe to PATH ».

## Installation manuelle (facultative)

Si tu préfères contrôler chaque étape, voici l'équivalent de ce que fait `run.py` :

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows : .venv\Scripts\Activate.ps1
pip install -r requirements.txt
waitress-serve --host=127.0.0.1 --port=5000 --call app:create_app
```

Puis ouvre http://127.0.0.1:5000. Sous Windows, si PowerShell refuse d'activer
l'environnement, lance une fois `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

Pour développer, `flask --app app run --debug` recharge le code à chaque modification.

## Configuration (facultative)

Sans configuration, tout fonctionne sauf les rangs Dan (clé ewgf.gg) et la rubrique
Tournois (token start.gg). Pour les activer, crée le fichier de configuration local à partir
du modèle :

```bash
mkdir -p instance
cp config.example.py instance/config.py
```

Sous Windows : `mkdir instance` puis `copy config.example.py instance\config.py`.

Ouvre ensuite `instance/config.py` et colle une clé API ewgf.gg dans `EWGF_API_KEY`.
Elle se crée sur [ewgf.gg](https://ewgf.gg) : compte, Paramètres, onglet Developer.
On peut aussi la passer par la variable d'environnement `EWGF_API_KEY`.

Pour la rubrique **Tournois**, colle un token API start.gg dans `STARTGG_TOKEN` : il se crée
sur [start.gg](https://www.start.gg), profil, Developer Settings, « Create new token ». Chaque
joueur lie ensuite son profil start.gg depuis la page Tournois (en un clic si son pseudo
start.gg correspond à son pseudo Tekken).

**Une seule clé (et un seul token) suffit pour tout le site** : les joueurs, eux, n'entrent que leur ID Tekken.
Le quota gratuit (100 requêtes par heure) est partagé entre tous les joueurs du site,
ce qui suffit largement pour un petit groupe. Le dossier `instance/` est ignoré par Git :
la clé n'est jamais commitée.

## Premier démarrage

À la première visite, le site demande ton **ID Tekken** (ex. `4qLJmf7THeE2`, visible dans
ton profil en jeu) ou l'URL de ta page ewgf.gg. Ensuite il va chercher tout seul :

- ton pseudo et tes 500 derniers matchs classés, avec ton rating (wank.wavu.wiki) ;
- tes rangs Dan, si une clé ewgf.gg est configurée ;
- l'illustration de ton perso le plus joué (site officiel) ;
- tes mains : tes deux persos les plus joués, modifiables dans le profil.

L'ID est gardé un an dans un cookie : les visites suivantes ouvrent directement ta page.
Tes matchs sont réimportés automatiquement quand tu ouvres l'accueil et que la dernière
mise à jour date de plus de 6 heures (ou à la demande : menu du joueur,
« ↻ Actualiser mes matchs »). L'historique
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
python3 run.py
```

(ou télécharge à nouveau le ZIP et décompresse-le en gardant ton dossier `instance/`).
Les dépendances sont réinstallées automatiquement si elles ont changé, et la base de
données est mise à jour au lancement.

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
source .venv/bin/activate          # Windows : .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
pytest
```

Les tests n'utilisent pas internet : les accès réseau sont simulés.

## Dépannage

| Problème | Solution |
|---|---|
| `python3: command not found` | Installe Python (voir Prérequis). Sous Windows, utilise `py` à la place de `python3`. |
| `ensurepip is not available` ou « Impossible de créer l'environnement Python » | `sudo apt install python3-venv` (Debian, Ubuntu, WSL), puis relance `python3 run.py` |
| `flask: command not found` (installation manuelle) | L'environnement n'est pas activé : `source .venv/bin/activate`, ou utilise `python3 run.py` |
| L'installation a été interrompue ou semble cassée | Supprime le dossier `.venv` et relance `python3 run.py` |
| Le navigateur ne s'ouvre pas | Ouvre à la main l'adresse affichée par `run.py` (ex. http://127.0.0.1:5000) |
| `Address already in use` / port 5000 occupé | `run.py` prend automatiquement le port libre suivant. En installation manuelle : `--port 5001`. |
| Connexion : « Cet ID est introuvable » ou « Aucun match classé » | Vérifie l'ID (12 caractères, tirets facultatifs) en cherchant ton pseudo sur ewgf.gg. Seuls les joueurs ayant des matchs classés sont reconnus. |
| Connexion : « wank.wavu.wiki est injoignable » | Vérifie ta connexion internet et réessaie. Un joueur déjà connu peut se connecter même hors ligne. |
| L'import wavu échoue (403 ou réseau) | Vérifie ta connexion, puis réessaie plus tard (menu du joueur, « ↻ Actualiser mes matchs »). |
| « ewgf : erreur invalid_api_key » | La clé dans `instance/config.py` est fausse ou révoquée : régénère-la sur ewgf.gg. |
| « ewgf : erreur rate_limit_exceeded » | Quota gratuit (100 requêtes par heure) atteint : réessaie l'heure suivante. |
| « start.gg : token start.gg invalide ou expiré » | Régénère un token sur start.gg et remplace `STARTGG_TOKEN` dans `instance/config.py`. |
| La page Tournois demande un token | Ajoute `STARTGG_TOKEN` dans `instance/config.py` (voir Configuration), puis relance le site. |
| Graphiques ou polices absents | Ils sont chargés depuis internet (jsDelivr, Google Fonts) : vérifie la connexion. |
| Une page affiche « Frame data indisponible » | Le wiki Wavu est injoignable : réessaie plus tard. Les frames déjà téléchargées restent en cache 14 jours. |

## Structure du projet

| Fichier | Rôle |
|---|---|
| `run.py` | Lanceur tout-en-un : installe si besoin et démarre le site |
| `app.py` | Application Flask : routes et formulaires |
| `db.py`, `schema.sql` | Base SQLite, schéma et migrations automatiques |
| `stats.py` | Statistiques de matchs (winrate, séries, sessions, progression) |
| `wavu.py`, `ewgf.py` | Import des matchs (wank.wavu.wiki) et des rangs Dan (API ewgf.gg) |
| `startgg.py`, `tournaments.py` | API start.gg et statistiques de tournoi |
| `framedata.py` | Frame data du wiki Wavu en DataFrames pandas, cache, punitions |
| `training.py` | Quiz, défi du jour, marges de progression |
| `widgets.py`, `templates/widgets/` | Catalogue des widgets de l'accueil et leur contenu |
| `portraits.py` | Illustrations des persos |
| `data.py` | Roster et rangs, à compléter à chaque nouveau DLC |
| `config.example.py` | Modèle de configuration locale |
| `templates/`, `static/` | Pages HTML et style |
| `tests/` | Tests automatiques (pytest) |

## Données et crédits

Projet non affilié à Bandai Namco. Matchs : [Wavu Wank](https://wank.wavu.wiki) et
[ewgf.gg](https://ewgf.gg). Tournois : [start.gg](https://www.start.gg). Frame data et vidéos des coups : [Wavu Wiki](https://wavu.wiki) ;
les coups sans vidéo renvoient vers [okizeme.gg](https://okizeme.gg).
Illustrations : site officiel Bandai Namco, téléchargées pour un usage local uniquement
et jamais commitées. Les punisseurs sont calculés automatiquement : vérifie-les en training mode.
