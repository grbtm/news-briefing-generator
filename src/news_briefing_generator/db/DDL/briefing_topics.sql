CREATE TABLE IF NOT EXISTS briefing_topics (
    briefing_id INTEGER,
    topic_id INTEGER,
    PRIMARY KEY (briefing_id, topic_id),
    FOREIGN KEY (briefing_id) REFERENCES briefings(id),
    FOREIGN KEY (topic_id) REFERENCES topics(id)
);