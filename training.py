"""Entraînement : quiz de frames, marges de progression, série de défis du jour."""

import random
from datetime import date, timedelta

import pandas as pd

import framedata as fd

QUIZ_SIZE = 10

# Tranches de frames en garde : ce sont les fenêtres de punition qui comptent en match.
BRACKETS = [
    ("+1 ou plus", 1, 999),
    ("0 à −9", -9, 0),
    ("−10 à −11", -11, -10),
    ("−12 à −14", -14, -12),
    ("−15 ou moins", -999, -15),
]


def bracket(value):
    return next(label for label, lo, hi in BRACKETS if lo <= value <= hi)


# ---------- Marges de progression ----------

def matches_frame(rows):
    """Lignes sqlite -> DataFrame de matchs."""
    cols = ["played_at", "my_char", "opp_char", "result"]
    return pd.DataFrame([{c: r[c] for c in cols} for r in rows], columns=cols)


def margins(matches, answers, since, min_games=5, limit=8):
    """Matchups qui coûtent le plus de winrate, avec ton niveau de connaissance au quiz.

    gain_pts : points de winrate global gagnés si ce matchup remontait à 50 %.
    """
    recent = matches[matches["played_at"].str[:10] >= since]
    if recent.empty:
        return pd.DataFrame(columns=["opp_char", "games", "wins", "winrate", "gain_pts",
                                     "quiz_total", "quiz_rate"])
    g = recent.groupby("opp_char").agg(games=("result", "size"),
                                       wins=("result", lambda s: int((s == "W").sum())))
    g["winrate"] = (100 * g["wins"] / g["games"]).round(1)
    g["missing_wins"] = (g["games"] / 2 - g["wins"]).apply(lambda x: int(-(-x // 1)))  # arrondi sup.
    g["gain_pts"] = ((g["games"] / 2 - g["wins"]) / len(recent) * 100).round(2)
    g = g[(g["games"] >= min_games) & (g["gain_pts"] > 0)]
    k = knowledge(answers)
    out = g.join(k, how="left").reset_index()
    out["quiz_total"] = pd.to_numeric(out["quiz_total"], errors="coerce").fillna(0).astype(int)
    return out.sort_values("gain_pts", ascending=False).head(limit).reset_index(drop=True)


def knowledge(answers):
    """Taux de bonnes réponses au quiz par perso adverse."""
    if answers.empty:
        return pd.DataFrame(columns=["quiz_total", "quiz_rate"]).rename_axis("opp_char")
    k = answers.groupby("opp_char").agg(quiz_total=("correct", "size"),
                                        quiz_ok=("correct", "sum"))
    k["quiz_rate"] = (100 * k["quiz_ok"] / k["quiz_total"]).round(0)
    return k[["quiz_total", "quiz_rate"]]


def streak(done_days, today):
    """Jours consécutifs de défi réussi, jusqu'à aujourd'hui (ou hier si pas encore fait)."""
    days = set(done_days)
    cur = today if today.isoformat() in days else today - timedelta(days=1)
    n = 0
    while cur.isoformat() in days:
        n += 1
        cur -= timedelta(days=1)
    return n


def daily_opponents(matches, since, limit=5):
    """Persos qui t'ont le plus battu récemment : ce sont eux qu'on révise."""
    recent = matches[(matches["played_at"].str[:10] >= since) & (matches["result"] == "L")]
    return recent["opp_char"].value_counts().head(limit).index.tolist()


# ---------- Génération des questions ----------

QUIZ_MODES = {"mix": "Mélange", "neutral": "En neutre", "stances": "Stances et positions"}
NEUTRAL_SHARE = 0.8   # en mode « mélange », part des coups en neutre


def question_pool(df, mode="mix"):
    """Coups utilisables en quiz : frames en garde connues, pas de chope, pas de fin de longue chaîne,
    pas de situation particulière (adversaire au sol, au mur…)."""
    if df.empty:
        return df
    pool = fd.add_context(df)
    pool = pool[pool["block"].notna() & ~pool["last_level"].isin(["t", ""])
                & (pool["block"] >= -25) & (pool["block"] <= 8)
                & (pool["command"].str.count(",") <= 1) & (pool["context_kind"] != "situation")]
    if mode == "neutral":
        pool = pool[pool["context_kind"] == "neutral"]
    elif mode == "stances":
        pool = pool[pool["context_kind"] != "neutral"]
    return pool


def make_questions(frames_by_opp, my_punishers, seed, size=QUIZ_SIZE, mode="mix"):
    """`frames_by_opp` : {perso: DataFrame}. Retourne une liste de questions (dicts JSON).

    Chaque question tire d'abord une tranche au hasard puis un coup de cette tranche,
    pour ne pas tomber sans arrêt sur « 0 à −9 ».
    """
    rng = random.Random(seed)
    pools = {c: question_pool(df, mode) for c, df in frames_by_opp.items()}
    pools = {c: p.assign(bracket=p["block"].astype(int).map(bracket)) for c, p in pools.items() if not p.empty}
    if not pools:
        return []
    chars = list(pools)
    questions, used = [], set()
    for i in range(size * 3):                     # quelques essais de rab si une tranche est vide
        if len(questions) >= size:
            break
        char = chars[len(questions) % len(chars)]
        pool = pools[char][~pools[char]["move_id"].isin(used)]
        if pool.empty:
            continue
        # Mélange : on choisit d'abord neutre (4 fois sur 5) ou stance / position, puis la
        # tranche de frames parmi ces coups-là (sinon les persos à stances fausseraient le dosage).
        if mode == "mix":
            neutral = pool[pool["context_kind"] == "neutral"]
            others = pool[pool["context_kind"] != "neutral"]
            if not neutral.empty and (others.empty or rng.random() < NEUTRAL_SHARE):
                pool = neutral
            elif not others.empty:
                pool = others
        available = [b for b, *_ in BRACKETS if (pool["bracket"] == b).any()]
        pool = pool[pool["bracket"] == rng.choice(available)]
        with_video = pool[pool["video_url"].notna() & (pool["video_url"] != "")] \
            if "video_url" in pool else pool.iloc[0:0]
        if not with_video.empty and rng.random() < 0.85:
            pool = with_video
        move = pool.iloc[rng.randrange(len(pool))]
        used.add(move["move_id"])
        questions.append(build_question(char, move, my_punishers))
    return questions


def build_question(char, move, my_punishers):
    block = int(move["block"])
    punish_kind = "ws" if move["last_level"] == "l" else "standing"
    best = fd.best_punisher(my_punishers, -block, punish_kind) if block <= fd.PUNISH_THRESHOLD else None
    video = move.get("video_url") if hasattr(move, "get") else None
    return {
        "kind": "bracket",
        "opp_char": char,
        "move_id": move["move_id"],
        "command": move["command"],
        "name": move["name"] or "",
        "target": move["target"],
        "startup": None if pd.isna(move["startup"]) else int(move["startup"]),
        "block": block,
        "punishable": block <= fd.PUNISH_THRESHOLD,
        "punisher": ({"command": best["command"], "startup": int(best["startup"]),
                      "damage": int(best["damage"]), "launcher": bool(best["launcher"])}
                     if best else None),
        "punish_kind": punish_kind,
        "video": video if isinstance(video, str) and video else None,
        "context_kind": move.get("context_kind", "neutral") if hasattr(move, "get") else "neutral",
        "context": move.get("context", "En neutre") if hasattr(move, "get") else "En neutre",
        "choices": [label for label, *_ in BRACKETS],
        "expected": bracket(block),
    }


def daily_opponent(matches, since, day):
    """Un seul perso par défi : on tourne chaque jour parmi ceux qui te battent le plus."""
    opponents = daily_opponents(matches, since)
    return opponents[day.toordinal() % len(opponents)] if opponents else None


def daily_seed(day):
    return int(day.strftime("%Y%m%d"))


def today():
    return date.today()
