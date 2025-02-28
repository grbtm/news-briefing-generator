CREATE TABLE IF NOT EXISTS topics (
    id INTEGER,
    title TEXT,
    generated_at TEXT,
    summary TEXT,
    UNIQUE(id)
);