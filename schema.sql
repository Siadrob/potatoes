-- Les index qui portent sur player_id sont créés par db._migrate (après l'ajout
-- de la colonne dans les bases d'une version précédente).

-- Un joueur = un ID Tekken (identifiant saisi à la connexion, gardé en cookie).
CREATE TABLE IF NOT EXISTS players (
    polaris_id TEXT PRIMARY KEY,         -- ex. 4qLJmf7THeE2
    name TEXT NOT NULL,
    mains TEXT,                          -- persos principaux, séparés par des virgules
    goal_rank TEXT,
    goal_rating INTEGER,
    layout TEXT,                         -- disposition des widgets de l'accueil (JSON)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_import_at TEXT
);

-- Ancienne table mono-joueur, conservée pour la migration.
CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT 'Joueur',
    polaris_id TEXT,                     -- ID joueur Tekken (ex. 4qLJmf7THeE2)
    main_char TEXT,                      -- obsolète, remplacé par `mains`
    mains TEXT,                          -- persos principaux, séparés par des virgules
    goal_rank TEXT,
    goal_rating INTEGER
);

INSERT OR IGNORE INTO profile (id) VALUES (1);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT,                      -- polaris_id du joueur
    played_at TEXT NOT NULL,             -- 'AAAA-MM-JJ' ou 'AAAA-MM-JJ HH:MM' (UTC pour les imports)
    my_char TEXT NOT NULL,
    opp_char TEXT NOT NULL,
    opp_name TEXT,
    result TEXT NOT NULL CHECK (result IN ('W', 'L', 'D')),
    rounds_won INTEGER,
    rounds_lost INTEGER,
    rank TEXT,                           -- rang Dan au moment du match (ewgf ou saisie manuelle)
    opp_rank TEXT,                       -- rang Dan de l'adversaire (ewgf)
    rating INTEGER,                      -- rating glicko après le match (import wavu)
    rating_change INTEGER,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manuel',
    external_id TEXT UNIQUE,             -- '<joueur>|battle:<timestamp>:<id adverse>' (wavu et ewgf)
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_played_at ON matches (played_at);

CREATE TABLE IF NOT EXISTS matchup_notes (
    player_id TEXT NOT NULL,
    opp_char TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (player_id, opp_char)
);

-- ---------- Entraînement ----------

CREATE TABLE IF NOT EXISTS quiz_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT,
    mode TEXT NOT NULL CHECK (mode IN ('daily', 'libre')),
    day TEXT NOT NULL,                   -- jour du quiz (AAAA-MM-JJ)
    my_char TEXT,
    questions TEXT NOT NULL,             -- JSON
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS quiz_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES quiz_sessions (id) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    opp_char TEXT NOT NULL,
    move_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    given TEXT,
    expected TEXT NOT NULL,
    correct INTEGER NOT NULL,
    answered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS training_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id TEXT,
    category TEXT NOT NULL CHECK (category IN ('punish', 'knowledge', 'matchup', 'autre')),
    opp_char TEXT,
    title TEXT NOT NULL,
    notes TEXT,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN ('todo', 'doing', 'done')),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    done_at TEXT
);
