"""Calculs de statistiques, indépendants de Flask pour être faciles à tester.

Les fonctions reçoivent des matchs triés du plus ancien au plus récent,
sous forme de dicts (ou sqlite3.Row) avec au moins `result` ('W', 'L' ou 'D').
"""

from collections import Counter, defaultdict

from data import rank_level


def winrate(wins, total):
    return round(100 * wins / total, 1) if total else None


def _count(matches):
    c = Counter(m["result"] for m in matches)
    total = len(matches)
    return {"total": total, "wins": c["W"], "losses": c["L"], "draws": c["D"],
            "winrate": winrate(c["W"], total)}


def summary(matches):
    return _count(matches)


def current_streak(matches):
    """Série en cours : ('W', 4) = 4 victoires d'affilée. (None, 0) si aucun match."""
    if not matches:
        return None, 0
    last = matches[-1]["result"]
    count = 0
    for m in reversed(matches):
        if m["result"] != last:
            break
        count += 1
    return last, count


def best_streak(matches):
    best = cur = 0
    for m in matches:
        cur = cur + 1 if m["result"] == "W" else 0
        best = max(best, cur)
    return best


def by_key(matches, key):
    """Bilan par valeur d'un champ (ex. 'opp_char'), trié par nombre de matchs."""
    groups = defaultdict(list)
    for m in matches:
        groups[m[key]].append(m)
    rows = [{"name": name, **_count(ms)} for name, ms in groups.items()]
    return sorted(rows, key=lambda r: (-r["total"], r["name"]))


def worst_matchups(matches, min_games=5, limit=5):
    rows = [r for r in by_key(matches, "opp_char") if r["total"] >= min_games]
    return sorted(rows, key=lambda r: (r["winrate"], -r["total"]))[:limit]


def best_matchups(matches, min_games=5, limit=5):
    rows = [r for r in by_key(matches, "opp_char") if r["total"] >= min_games]
    return sorted(rows, key=lambda r: (-r["winrate"], -r["total"]))[:limit]


def rolling_winrate(matches, window=20):
    """Winrate glissant sur les `window` derniers matchs, pour chaque match."""
    points, wins = [], 0
    for i, m in enumerate(matches):
        wins += m["result"] == "W"
        if i >= window:
            wins -= matches[i - window]["result"] == "W"
        points.append(winrate(wins, min(i + 1, window)))
    return points


def rank_history(matches):
    """Points (date, rang, niveau) pour les matchs où un rang connu est renseigné."""
    out = []
    for m in matches:
        level = rank_level(m["rank"]) if m["rank"] else None
        if level is not None:
            out.append({"date": m["played_at"][:10], "rank": m["rank"], "level": level})
    return out


def rating_history(matches, char):
    """Points (date, rating) pour un personnage (le rating est propre à chaque perso)."""
    return [{"date": m["played_at"], "rating": m["rating"], "change": m["rating_change"]}
            for m in matches if m["my_char"] == char and m["rating"] is not None]


def sessions(matches, limit=10):
    """Bilan par jour de jeu, du plus récent au plus ancien."""
    days = defaultdict(list)
    for m in matches:
        days[m["played_at"][:10]].append(m)
    out = []
    for day in sorted(days, reverse=True)[:limit]:
        ms = days[day]
        changes = [m["rating_change"] for m in ms if m["rating_change"] is not None]
        out.append({"day": day, **_count(ms),
                    "chars": sorted({m["my_char"] for m in ms}),
                    "rating_delta": sum(changes) if changes else None})
    return out


# ---------- Vues "tableau de bord" ----------

def wr_class(value):
    """Classe de couleur d'un winrate : bon (> 52 %), moyen (48-52 %), mauvais (< 48 %)."""
    if value is None:
        return "none"
    return "hi" if value > 52 else "mid" if value >= 48 else "lo"


def heat_class(value):
    """Palier de couleur du calendrier d'activité."""
    if value is None:
        return "h0"
    for limit, cls in ((30, "h1"), (40, "h2"), (50, "h3"), (60, "h4")):
        if value < limit:
            return cls
    return "h5"


def character_cards(matches, mains):
    """Une carte par perso joué : bilan + dernier rating. Les mains d'abord."""
    last_rating, last_rank = {}, {}
    for m in matches:
        if m["rating"] is not None:
            last_rating[m["my_char"]] = m["rating"]
        if m["rank"]:
            last_rank[m["my_char"]] = m["rank"]
    cards = [{**row, "rating": last_rating.get(row["name"]), "rank": last_rank.get(row["name"]),
              "is_main": row["name"] in mains}
             for row in by_key(matches, "my_char")]
    order = {name: i for i, name in enumerate(mains)}
    return sorted(cards, key=lambda c: (order.get(c["name"], len(order)), -c["total"]))


def activity(matches, end, weeks=13):
    """Calendrier : colonnes = semaines (lundi→dimanche), terminé par la semaine de `end`."""
    from datetime import timedelta

    per_day = defaultdict(list)
    for m in matches:
        per_day[m["played_at"][:10]].append(m)

    start = end - timedelta(days=end.weekday() + 7 * (weeks - 1))
    columns, cells_in_range = [], []
    for w in range(weeks):
        week_start = start + timedelta(weeks=w)
        cells = []
        for d in range(7):
            day = week_start + timedelta(days=d)
            ms = per_day.get(day.isoformat(), [])
            c = _count(ms)
            cell = {"day": day.isoformat(), "future": day > end, **c,
                    "cls": heat_class(c["winrate"])}
            cells.append(cell)
            if not cell["future"]:
                cells_in_range.append(cell)
        month = week_start.strftime("%m") if w == 0 or week_start.day <= 7 else None
        columns.append({"month": month, "cells": cells})

    played = [c for c in cells_in_range if c["total"]]
    total = sum(c["total"] for c in played)
    wins = sum(c["wins"] for c in played)
    busiest = max(played, key=lambda c: c["total"], default=None)
    return {
        "columns": columns,
        "total": total, "wins": wins, "losses": sum(c["losses"] for c in played),
        "winrate": winrate(wins, total), "active_days": len(played),
        "per_day": round(total / len(played), 1) if played else None,
        "busiest": busiest,
    }


def matchup_chart(matches, min_games=3):
    """Winrate par perso adverse, du meilleur au pire, pour le graphique en barres."""
    rows = [r for r in by_key(matches, "opp_char") if r["total"] >= min_games]
    for r in rows:
        r["cls"] = wr_class(r["winrate"])
    hidden = sum(1 for r in by_key(matches, "opp_char") if r["total"] < min_games)
    return sorted(rows, key=lambda r: (-r["winrate"], -r["total"])), hidden


# ---------- Progression (page d'accueil) ----------

def rating_delta(points, since):
    """Évolution du rating depuis la date `since` ('AAAA-MM-JJ').

    Référence = dernier rating connu avant `since` ; à défaut, le rating avant le
    premier match de la période (premier rating moins son gain).
    """
    if not points:
        return None
    before = [p for p in points if p["date"][:10] < since]
    if before:
        ref = before[-1]["rating"]
    else:
        first = points[0]
        ref = first["rating"] - (first.get("change") or 0)
    return points[-1]["rating"] - ref


def daily_rating(points):
    """Rating en fin de journée : une valeur par jour joué, courbe moins bruitée."""
    days = {}
    for p in points:
        days[p["date"][:10]] = p["rating"]
    return [{"date": d, "rating": r} for d, r in days.items()]


def period_summary(matches, start, end=None):
    """Bilan des matchs joués entre `start` inclus et `end` exclu (dates ISO)."""
    ms = [m for m in matches if m["played_at"][:10] >= start and (end is None or m["played_at"][:10] < end)]
    return _count(ms)


def weekly(matches, limit=8):
    """Bilan par semaine (lundi), de la plus récente à la plus ancienne."""
    from datetime import date, timedelta

    weeks = defaultdict(list)
    for m in matches:
        d = date.fromisoformat(m["played_at"][:10])
        weeks[(d - timedelta(days=d.weekday())).isoformat()].append(m)
    out = []
    for start in sorted(weeks, reverse=True)[:limit]:
        ms = weeks[start]
        changes = [m["rating_change"] for m in ms if m["rating_change"] is not None]
        ratings = [m["rating"] for m in ms if m["rating"] is not None]
        ranks = [m["rank"] for m in ms if m["rank"]]
        out.append({"start": start, **_count(ms),
                    "rating_delta": sum(changes) if changes else None,
                    "rating_end": ratings[-1] if ratings else None,
                    "rank": ranks[-1] if ranks else None})
    return out
