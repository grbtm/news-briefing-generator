CREATE TABLE IF NOT EXISTS feeds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT,
    link TEXT,
    published TEXT,
    summary TEXT,
    source TEXT,
    feed_url TEXT,
    fetched_at TEXT,
    scraped_text TEXT,
    extracted_article TEXT,
    summarized_article TEXT,
    UNIQUE(source, link)
);