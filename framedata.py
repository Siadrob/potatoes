"""Frame data Tekken 8 (source : Wavu Wiki, https://wavu.wiki), sous forme de DataFrames pandas.

Une requête par personnage, mise en cache dans la base SQLite (table `frame_moves`).
"""

import hashlib
import html
import json
import re
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

API_URL = "https://wavu.wiki/w/api.php"
USER_AGENT = "T8Tracker/0.1 (outil perso de progression)"
FIELDS = ["id", "name", "input", "parent", "target", "damage", "startup", "block", "hit", "ch",
          "crush", "notes", "video"]
CACHE_DAYS = 14
PUNISH_THRESHOLD = -10  # un coup à -10 ou moins en garde est punissable

# Nom du perso dans le wiki quand il diffère du nom utilisé dans l'app.
WAVU_NAMES = {"Roger": "Roger Jr."}

COLUMNS = ["move_id", "char", "command", "name", "parent", "is_root", "target", "last_level",
           "damage", "startup", "block", "hit", "launcher", "notes", "video_url"]


# ---------- Téléchargement ----------

def fetch_raw(char, timeout=30):
    """Lignes brutes du wiki pour un perso (liste de dicts)."""
    name = WAVU_NAMES.get(char, char)
    rows, offset = [], 0
    while True:
        params = {"action": "cargoquery", "tables": "Move", "fields": ",".join(f"Move.{f}" for f in FIELDS),
                  "where": f"Move.id LIKE '{name.replace(chr(39), chr(39) * 2)}-%'",
                  "limit": 500, "offset": offset, "format": "json"}
        req = urllib.request.Request(f"{API_URL}?{urllib.parse.urlencode(params)}",
                                     headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            page = [r["title"] for r in json.load(resp).get("cargoquery", [])]
        rows += page
        if len(page) < 500:
            return rows
        offset += 500
        time.sleep(1)  # une requête à la fois, sans marteler le wiki


# ---------- Nettoyage ----------

_INT = re.compile(r"[+-]?\d+")


def first_int(value):
    """'i18~19' -> 18 ; '-9~-8' -> -9 ; '+20a(+15)' -> 20 ; '' -> None."""
    if value is None:
        return None
    m = _INT.search(str(value).replace("−", "-"))
    return int(m.group()) if m else None


def total_damage(value):
    """'10,14 (9)' -> 24 (on ignore les valeurs entre parenthèses)."""
    if not value:
        return 0
    text = re.sub(r"\(.*?\)", "", str(value))
    return sum(int(n) for n in re.findall(r"\d+", text))


def is_launcher(hit):
    """Lanceur : le wiki renvoie vers les combos, ou gros avantage avec l'adversaire en l'air.

    '+20a' seul est une mise au sol, pas un lanceur.
    """
    text = str(hit or "")
    if "combos" in text.lower():
        return True
    m = re.search(r"\+(\d+)a", text)
    return bool(m and int(m.group(1)) >= 30)


def video_url(value):
    """'File:t8-p2-alisa-1,1.mp4' -> URL directe du fichier sur le wiki (chemin MediaWiki)."""
    name = str(value or "").removeprefix("File:").strip().replace(" ", "_")
    if not name:
        return None
    name = name[:1].upper() + name[1:]
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()
    return f"https://wavu.wiki/w/images/{digest[0]}/{digest[:2]}/{urllib.parse.quote(name)}"


def clean_notes(value):
    if not value:
        return ""
    text = html.unescape(str(value))
    text = re.sub(r"<[^>]+>", "", text)
    lines = [ln.strip(" *\r") for ln in text.splitlines()]
    return " · ".join(ln for ln in lines if ln)


def to_frame(raw, char):
    """Transforme les lignes brutes du wiki en DataFrame propre."""
    df = pd.DataFrame(raw, columns=FIELDS).fillna("")
    if df.empty:
        return pd.DataFrame(columns=COLUMNS)
    prefix = f"{WAVU_NAMES.get(char, char)}-"
    inputs = dict(zip(df["id"], df["input"]))
    parents = dict(zip(df["id"], df["parent"]))

    def command(move_id):
        parts, seen = [], set()
        while move_id and move_id not in seen:
            seen.add(move_id)
            parts.append(inputs.get(move_id, ""))
            move_id = parents.get(move_id)
        cmd = "".join(reversed(parts))
        return cmd or move_id.removeprefix(prefix)

    out = pd.DataFrame({
        "move_id": df["id"],
        "char": char,
        "command": df["id"].map(command),
        "name": df["name"].map(lambda s: html.unescape(str(s))),
        "parent": df["parent"].replace("", None),
        "is_root": df["parent"] == "",
        "target": df["target"].str.lstrip(","),
        "damage": df["damage"].map(total_damage),
        "startup": df["startup"].map(first_int),
        "block": df["block"].map(first_int),
        "hit": df["hit"],
        "notes": df["notes"].map(clean_notes),
        "video_url": df["video"].map(video_url),
    })
    out["last_level"] = out["target"].str.split(",").str[-1].str.strip().str.lower().str[:1]
    out["launcher"] = df["hit"].map(is_launcher)
    out["startup"] = out["startup"].astype("Int64")
    out["block"] = out["block"].astype("Int64")
    return out[COLUMNS]


# ---------- Cache SQLite ----------

def ensure_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS frame_meta (
            char TEXT PRIMARY KEY,
            fetched_at TEXT NOT NULL,
            moves INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS frame_moves (
            move_id TEXT, char TEXT, command TEXT, name TEXT, parent TEXT, is_root INTEGER,
            target TEXT, last_level TEXT, damage INTEGER, startup INTEGER, block INTEGER,
            hit TEXT, launcher INTEGER, notes TEXT, video_url TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_frame_moves_char ON frame_moves (char);
    """)
    cols = {row[1] for row in conn.execute("PRAGMA table_info(frame_moves)")}
    if "video_url" not in cols:
        # Cache d'une ancienne version : on le vide, il sera retéléchargé.
        conn.executescript("DROP TABLE frame_moves; DELETE FROM frame_meta;")
        ensure_tables(conn)


def load(conn, char, fetch=fetch_raw, max_age_days=CACHE_DAYS, force=False):
    """DataFrame des coups d'un perso, depuis le cache ou le wiki si besoin."""
    ensure_tables(conn)
    meta = conn.execute("SELECT fetched_at FROM frame_meta WHERE char = ?", (char,)).fetchone()
    fresh = meta and datetime.fromisoformat(meta[0]) > datetime.now(timezone.utc) - timedelta(days=max_age_days)
    if fresh and not force:
        df = pd.read_sql_query("SELECT * FROM frame_moves WHERE char = ?", conn, params=(char,))
        df["is_root"] = df["is_root"].astype(bool)
        df["launcher"] = df["launcher"].astype(bool)
        df["startup"] = df["startup"].astype("Int64")
        df["block"] = df["block"].astype("Int64")
        return df
    df = to_frame(fetch(char), char)
    conn.execute("DELETE FROM frame_moves WHERE char = ?", (char,))
    if not df.empty:
        df.to_sql("frame_moves", conn, if_exists="append", index=False)
    conn.execute("INSERT OR REPLACE INTO frame_meta (char, fetched_at, moves) VALUES (?, ?, ?)",
                 (char, datetime.now(timezone.utc).isoformat(), len(df)))
    conn.commit()
    return df


# ---------- Punitions ----------

_STANDING = re.compile(r"^(?:(?:f|b|df|uf)\+)?[1-4](?:\+[1-4])*(?:,[1-4](?:\+[1-4])*)*$")


def punishers(df):
    """Punisseurs possibles d'un perso : debout ('standing') ou en se relevant ('ws').

    Un enchaînement compte si chaque coup après le premier est garanti ('Combo from…').
    """
    if df.empty:
        return pd.DataFrame(columns=["command", "startup", "damage", "launcher", "kind"])
    by_id = df.set_index("move_id")
    rows = []
    for move_id, move in by_id.iterrows():
        chain, cur, ok = [], move_id, True
        while cur is not None and isinstance(cur, str) and cur in by_id.index:
            chain.append(cur)
            cur = by_id.at[cur, "parent"]
        chain.reverse()
        root = by_id.loc[chain[0]]
        for link in chain[1:]:
            if "combo from" not in by_id.at[link, "notes"].lower():
                ok = False
                break
        if not ok or pd.isna(root["startup"]) or root["last_level"] == "t":
            continue
        cmd = move["command"]
        if cmd.startswith("ws"):
            kind = "ws"
        elif _STANDING.match(cmd):
            kind = "standing"
        else:
            continue
        rows.append({"command": cmd, "startup": int(root["startup"]),
                     "damage": int(by_id.loc[chain, "damage"].sum()),
                     "launcher": bool(by_id.loc[chain, "launcher"].any()), "kind": kind})
    return pd.DataFrame(rows, columns=["command", "startup", "damage", "launcher", "kind"])


def best_punisher(punish_df, frames, kind="standing"):
    """Meilleur punisseur assez rapide : un lanceur si possible, sinon le plus de dégâts."""
    if punish_df.empty or frames is None:
        return None
    ok = punish_df[(punish_df["kind"] == kind) & (punish_df["startup"] <= frames)]
    if ok.empty:
        return None
    best = ok.sort_values(["launcher", "damage", "startup"], ascending=[False, False, True]).iloc[0]
    return best.to_dict()


def punish_sheet(opp_df, my_df):
    """Coups adverses punissables + ton meilleur punish pour chacun."""
    if opp_df.empty:
        return pd.DataFrame()
    sheet = opp_df[opp_df["block"].notna() & (opp_df["block"] <= PUNISH_THRESHOLD)
                   & ~opp_df["last_level"].isin(["t", ""])].copy()
    pun = punishers(my_df)
    sheet["frames"] = -sheet["block"].astype(int)
    sheet["punish_kind"] = sheet["last_level"].map(lambda lvl: "ws" if lvl == "l" else "standing")
    best = [best_punisher(pun, f, k) for f, k in zip(sheet["frames"], sheet["punish_kind"])]
    sheet["punisher"] = [b["command"] if b else None for b in best]
    sheet["punisher_startup"] = [b["startup"] if b else None for b in best]
    sheet["punisher_damage"] = [b["damage"] if b else None for b in best]
    sheet["punisher_launcher"] = [bool(b and b["launcher"]) for b in best]
    return sheet.sort_values(["block", "command"]).reset_index(drop=True)
