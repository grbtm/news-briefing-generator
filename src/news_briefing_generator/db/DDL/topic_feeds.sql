CREATE TABLE IF NOT EXISTS topic_feeds (
    topic_id INTEGER,
    feed_id INTEGER,
    used_for_summarization INTEGER DEFAULT 0,
    PRIMARY KEY (topic_id, feed_id),
    FOREIGN KEY (topic_id) REFERENCES topics(id),
    FOREIGN KEY (feed_id) REFERENCES feeds(id)
);