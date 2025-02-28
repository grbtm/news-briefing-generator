TABLE_FEEDS = "feeds"
TABLE_TOPICS = "topics"
TABLE_TOPIC_FEEDS = "topic_feeds"
TABLE_BRIEFINGS = "briefings"
TABLE_BRIEFING_TOPICS = "briefing_topics"

FEED_COLUMNS = ["id", "title", "link", "published", "summary", "source", "feed_url", "fetched_at", "scraped_text", "extracted_article", "summarized_article"]
TOPICS_COLUMNS = ["id", "title", "generated_at", "summary"]
BRIEFINGS_COLUMNS = ["id", "generated_at"]
BRIEFING_TOPICS_COLUMNS = ["briefing_id", "topic_id"]