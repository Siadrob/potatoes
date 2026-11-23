"""Widgets de l'accueil : catalogue, disposition par défaut et validation.

Une disposition est une liste ordonnée de {"id": ..., "size": "s" | "m" | "l"} :
s = petit (1/4 de largeur), m = moyen (1/2), l = large (toute la largeur).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Widget:
    title: str
    description: str
    default_size: str
    sizes: tuple


CATALOG = {
    "rating": Widget("Progression du rating", "Évolution sur 7 et 30 jours, record.", "s", ("s", "m")),
    "week": Widget("Cette semaine", "Winrate des 7 derniers jours, comparé à la semaine d'avant.", "s", ("s", "m")),
    "month": Widget("30 derniers jours", "Winrate et bilan du mois.", "s", ("s", "m")),
    "daily": Widget("Défi du jour", "Ta série de défis et l'accès au défi du jour.", "s", ("s", "m")),
    "rating_chart": Widget("Évolution du rating", "Courbe du rating en fin de journée.", "l", ("m", "l")),
    "weekly": Widget("Semaine par semaine", "Matchs, winrate et rating de chaque semaine.", "m", ("m", "l")),
    "focus": Widget("Matchups du mois", "Les matchups à travailler et tes points forts.", "m", ("m", "l")),
    "goals": Widget("Rang et rating visés", "Où tu en es par rapport à tes objectifs.", "s", ("s", "m")),
    "plan": Widget("Mon plan", "Tes objectifs d'entraînement en cours.", "s", ("s", "m", "l")),
    "activity": Widget("Calendrier d'activité", "Tes 13 dernières semaines, jour par jour.", "m", ("m", "l")),
    "matchup_chart": Widget("Analyse des matchups", "Winrate contre chaque perso, du meilleur au pire.", "l", ("m", "l")),
    "opponents": Widget("Adversaires fréquents", "Les persos que tu affrontes le plus.", "m", ("m", "l")),
    "margins": Widget("Marges de progression", "Les matchups qui te coûtent le plus de victoires.", "l", ("m", "l")),
    "knowledge": Widget("Connaissance des frames", "Tes résultats aux quiz, perso par perso.", "m", ("s", "m")),
    "characters": Widget("Mes persos", "Bilan et rating de chacun de tes persos.", "m", ("s", "m")),
}

DEFAULT_LAYOUT = [
    {"id": "rating", "size": "s"},
    {"id": "week", "size": "s"},
    {"id": "month", "size": "s"},
    {"id": "daily", "size": "s"},
    {"id": "rating_chart", "size": "l"},
    {"id": "weekly", "size": "m"},
    {"id": "focus", "size": "m"},
    {"id": "goals", "size": "s"},
    {"id": "plan", "size": "s"},
]


def normalize(layout):
    """Disposition propre : widgets connus, sans doublon, avec une taille autorisée.

    Accepte la valeur brute (liste de dicts) ; tout ce qui est invalide est ignoré.
    """
    out, seen = [], set()
    for item in layout if isinstance(layout, list) else []:
        if not isinstance(item, dict):
            continue
        wid, size = item.get("id"), item.get("size")
        widget = CATALOG.get(wid)
        if widget is None or wid in seen:
            continue
        seen.add(wid)
        out.append({"id": wid, "size": size if size in widget.sizes else widget.default_size})
    return out


def hidden(layout):
    """Widgets du catalogue absents de la disposition (proposés dans « Ajouter »)."""
    shown = {item["id"] for item in layout}
    return [(wid, w) for wid, w in CATALOG.items() if wid not in shown]
