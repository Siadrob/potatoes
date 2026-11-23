"""Statistiques de tournoi, à partir des tournois et sets récupérés sur start.gg.

Les sets gagnés ou perdus par forfait (DQ) sont exclus des bilans.
"""

from collections import defaultdict


def _rate(wins, total):
    return round(100 * wins / total, 1) if total else None


def summary(events, sets):
    played = [s for s in sets if not s["dq"]]
    wins = sum(s["won"] for s in played)
    games_won = sum(s["my_score"] or 0 for s in played)
    games_lost = sum(s["opp_score"] or 0 for s in played)
    placed = [e for e in events if e["placement"]]
    best = min(placed, key=lambda e: (e["top_pct"] if e["top_pct"] is not None else 101, e["placement"]),
               default=None)
    tops = [e["top_pct"] for e in placed if e["top_pct"] is not None]
    return {
        "tournaments": len(events),
        "offline": sum(not e["online"] for e in events),
        "best": best,
        "avg_top": round(sum(tops) / len(tops)) if tops else None,
        "sets": len(played), "set_wins": wins, "set_losses": len(played) - wins,
        "set_rate": _rate(wins, len(played)),
        "games_won": games_won, "games_lost": games_lost,
        "game_rate": _rate(games_won, games_won + games_lost),
        "dq": len(sets) - len(played),
    }


def placement_history(events):
    """Classement relatif (top %, plus bas = mieux) dans l'ordre chronologique."""
    return [{"date": e["date"], "top": e["top_pct"], "name": e["tournament"],
             "placement": e["placement"], "entrants": e["entrants"]}
            for e in sorted(events, key=lambda e: e["date"] or "") if e["top_pct"] is not None]


def brackets(sets):
    """Bilan en winners et en losers bracket."""
    out = {}
    for side in ("winners", "losers"):
        ss = [s for s in sets if s["bracket"] == side and not s["dq"]]
        wins = sum(s["won"] for s in ss)
        out[side] = {"wins": wins, "losses": len(ss) - wins, "rate": _rate(wins, len(ss))}
    return out


def rivals(sets, limit=8):
    """Adversaires affrontés en tournoi, les plus fréquents d'abord."""
    groups = defaultdict(list)
    for s in sets:
        if not s["dq"]:
            groups[s["opponent_id"] or s["opponent"]].append(s)
    rows = []
    for ss in groups.values():
        wins = sum(s["won"] for s in ss)
        rows.append({"name": ss[0]["opponent"], "sets": len(ss), "wins": wins,
                     "losses": len(ss) - wins, "rate": _rate(wins, len(ss)),
                     "last": max(s["date"] or "" for s in ss)})
    return sorted(rows, key=lambda r: (-r["sets"], -r["wins"], r["name"] or ""))[:limit]


def recent_sets(sets, limit=10):
    return [s for s in sets if not s["dq"]][:limit]
