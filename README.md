# T8 Tracker : suivi de progression Tekken 8

Petit site web perso (Python / Flask / SQLite) pour suivre sa progression sur Tekken 8.

## Fonctionnalités

- **Import automatique** des matchs classés depuis [wank.wavu.wiki](https://wank.wavu.wiki)
  (même source qu'ewgf.gg) : colle ton ID joueur ou l'URL de ton profil ewgf.gg.
  Chaque import récupère les 500 derniers matchs sans créer de doublons :
  relance-le après chaque session pour accumuler tout ton historique.
- **Saisie manuelle** d'un match (perso, adversaire, score, rang, notes), pré-remplie
  avec ton dernier perso et ton dernier rang.
- **Tableau de bord** : winrate global et récent, séries, courbe du rating par perso,
  winrate glissant, évolution du rang, sessions par jour, matchups difficiles ou favorables.
  Filtrable par perso joué.
- **Matchups** : bilan contre chaque perso et **notes perso** par matchup
  (coups à punir, gestion de la pression…).
- **Profil** : pseudo, ID joueur, main, rang visé, rating visé.

## Installation

Il faut Python 3.10 ou plus récent.

```bash
# Debian / Ubuntu / WSL
sudo apt install -y python3 python3-venv

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

## Lancer le site

```bash
source .venv/bin/activate
flask --app app run --debug
```

Puis ouvre http://127.0.0.1:5000.

Les données sont enregistrées dans `instance/progression.db` (un seul fichier SQLite à sauvegarder).

## Tests

```bash
pytest
```

## Structure

| Fichier | Rôle |
|---|---|
| `app.py` | Routes Flask et validation des formulaires |
| `stats.py` | Calculs de statistiques (winrate, séries, sessions…) |
| `wavu.py` | Récupération et lecture de l'historique wavu |
| `data.py` | Roster et liste des rangs, à compléter à chaque nouveau DLC |
| `schema.sql` | Schéma de la base |
| `templates/`, `static/` | Pages HTML et style |

Projet non affilié à Bandai Namco. Les données de matchs proviennent de Wavu Wank.
