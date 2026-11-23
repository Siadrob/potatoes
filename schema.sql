CREATE TABLE IF NOT EXISTS profile (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    name TEXT NOT NULL DEFAULT 'Joueur',
    polaris_id TEXT,                     -- ID joueur Tekken (ex. 4qLJmf7THeE2)
    main_char TEXT,
    goal_rank TEXT,
    goal_rating INTEGER
);

INSERT OR IGNORE INTO profile (id) VALUES (1);

CREATE TABLE IF NOT EXISTS matches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    played_at TEXT NOT NULL,             -- 'AAAA-MM-JJ' ou 'AAAA-MM-JJ HH:MM' (UTC pour les imports)
    my_char TEXT NOT NULL,
    opp_char TEXT NOT NULL,
    opp_name TEXT,
    result TEXT NOT NULL CHECK (result IN ('W', 'L', 'D')),
    rounds_won INTEGER,
    rounds_lost INTEGER,
    rank TEXT,                           -- rang en jeu après le match (saisie manuelle)
    rating INTEGER,                      -- rating glicko après le match (import wavu)
    rating_change INTEGER,
    notes TEXT,
    source TEXT NOT NULL DEFAULT 'manuel',
    external_id TEXT UNIQUE,             -- évite les doublons lors des imports
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_matches_played_at ON matches (played_at);

CREATE TABLE IF NOT EXISTS matchup_notes (
    opp_char TEXT PRIMARY KEY,
    notes TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
