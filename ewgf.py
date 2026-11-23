"""Import depuis l'API ewgf.gg (https://ewgf.gg/api-docs).

Plan gratuit : 100 requêtes/heure, 50 derniers matchs (tous modes), avec 24 h de décalage.
On n'en garde que les matchs classés, pour récupérer le rang Dan qui manque à wavu.
"""

import json
import urllib.error
import urllib.request
from datetime import datetime, timezone

API_URL = "https://api.ewgf.gg"


class EwgfError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fetch_battles(tekken_id, api_key, timeout=30):
    req = urllib.request.Request(
        f"{API_URL}/external/battles/{tekken_id}",
        headers={"Authorization": f"Bearer {api_key}", "Accept-Encoding": "identity"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err = json.loads(e.read().decode("utf-8"))["error"]
            raise EwgfError(err.get("code", f"http_{e.code}"), err.get("message", "")) from e
        except (ValueError, KeyError, TypeError):
            raise EwgfError(f"http_{e.code}", str(e)) from e
    except (urllib.error.URLError, TimeoutError) as e:
        raise EwgfError("network", str(e)) from e
    return payload.get("data") or []


def parse_battles(battles, tekken_id):
    """Matchs classés de `tekken_id`, au même format que l'import wavu."""
    matches = []
    for b in battles:
        if b.get("battle_type") != "RANKED_BATTLE":
            continue
        if b.get("p1_tekken_id") == tekken_id:
            me, opp, my_slot = "p1", "p2", 1
        elif b.get("p2_tekken_id") == tekken_id:
            me, opp, my_slot = "p2", "p1", 2
        else:
            continue
        try:
            played = datetime.fromisoformat(b["battle_at"].replace("Z", "+00:00"))
        except (KeyError, ValueError):
            continue
        played = played.astimezone(timezone.utc)
        won, lost = b.get(f"{me}_rounds_won"), b.get(f"{opp}_rounds_won")
        winner = b.get("winner")
        matches.append({
            "played_at": played.strftime("%Y-%m-%d %H:%M"),
            "my_char": b.get(f"{me}_char"),
            "opp_char": b.get(f"{opp}_char"),
            "opp_name": b.get(f"{opp}_name"),
            "result": "W" if winner == my_slot else "L" if winner in (1, 2) else "D",
            "rounds_won": won,
            "rounds_lost": lost,
            "rating": None,
            "rating_change": None,
            "rank": b.get(f"{me}_dan_rank"),
            "opp_rank": b.get(f"{opp}_dan_rank"),
            "source": "ewgf",
            "external_id": f"battle:{int(played.timestamp())}:{b.get(f'{opp}_tekken_id', '')}",
        })
    return [m for m in matches if m["my_char"] and m["opp_char"]]
