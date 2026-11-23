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
    return [{"date": m["played_at"], "rating": m["rating"]}
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
