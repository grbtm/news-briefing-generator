from typing import List, Optional

from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.utils.datetime_ops import (
    get_utc_now_simple,
    get_utc_now_formatted
)


def get_most_recent_briefing(db: DatabaseManager) -> Optional[tuple[str, str, str]]:
    """Get the most recent briefing from the database.

    Args:
        db (DatabaseManager): Database connection manager

    Returns:
        Optional[tuple[str, str, str]]: Tuple of (id, title, generated_at) for most recent briefing,
                                       or None if no briefings exist
    """
    briefings = db.select(table="briefings", columns=["id", "title", "generated_at"])

    if not briefings:
        return None

    # Extract timestamps from briefing IDs (format: YYYY-MM-DD-HH-MM)
    most_recent = max(briefing[0] for briefing in briefings)

    # Get the most recent briefing
    recent_briefing = [
        briefing for briefing in briefings if briefing[0] == most_recent
    ][0]

    return recent_briefing


def get_most_recent_topics(
    db: DatabaseManager, time_window_hours: int = 24
) -> list[str]:
    """Fetch most recent topic clusters from database within specified time window.

    Topics are ordered by creation timestamp descending (newest first).

    Args:
        db (DatabaseManager): Database connection manager
        time_window_hours (int, optional): Time window in hours to look back.
            Defaults to 24.

    Returns:
        List[Tuple[str, str]]: List of tuples containing:
            - topic_id (str): Unique identifier for the topic
            - generated_at (str): ISO formatted timestamp when topic was created

    Example:
        >>> topics = get_most_recent_topics(db, time_window_hours=12)
        >>> print(topics[0])
        ('2024-01-29-12-01', '2024-01-29T12:01:00Z')
    """
    # Get all topics from last time_window_hours
    topics = db.select(
        table="topics",
        columns=["id", "title", "generated_at", "summary"],
        condition=f"generated_at >= datetime('now', '-{time_window_hours} hours')",
    )

    if not topics:
        return []

    # Extract timestamps from topic IDs
    timestamps = set()
    for topic in topics:
        topic_id = topic[0]
        timestamp = "-".join(topic_id.split("-")[:5])  # Get YYYY-MM-DD-HH-MM part
        timestamps.add(timestamp)

    # Get most recent timestamp
    most_recent = max(timestamps)

    # Filter topics for most recent timestamp
    recent_topics = [
        topic for topic in topics if "-".join(topic[0].split("-")[:5]) == most_recent
    ]

    return recent_topics


def get_feeds_for_topics(
    db: DatabaseManager, topic_ids: list[str]
) -> dict[str, list[dict]]:
    """Get all related feed entries for given topics by joining topic_feeds and feeds tables.

    Args:
        db (DatabaseManager): Database connection manager
        topic_ids (list[str]): List of topic IDs to fetch feeds for

    Returns:
        dict[str, list[dict]]: Dictionary mapping topic IDs to lists of feed entries

    Example:
        >>> topics = get_most_recent_topics(db)
        >>> topic_feeds = get_feeds_for_topics(db, [t[0] for t in topics])
    """
    if not topic_ids:
        return {}

    # Format topic IDs for SQL IN clause
    topic_ids_str = ",".join(f"'{tid}'" for tid in topic_ids)

    # Join feeds and topic_feeds tables to get all related feeds
    query = f"""
        SELECT 
            tf.topic_id,
            f.id,
            f.title,
            f.link,
            f.summary,
            f.source,
            f.feed_url,
            f.published,
            f.scraped_text,
            f.summarized_article
        FROM topic_feeds tf
        JOIN feeds f ON tf.feed_id = f.id
        WHERE tf.topic_id IN ({topic_ids_str})
        ORDER BY tf.topic_id, f.published DESC
    """

    results = db.run_query(query)

    # Organize results by topic_id
    feeds_by_topic = {}
    for row in results:
        topic_id = row[0]
        feed_entry = {
            "id": row[1],
            "title": row[2],
            "link": row[3],
            "summary": row[4],
            "source": row[5],
            "feed_url": row[6],
            "published": row[7],
            "scraped_text": row[8],
            "summarized_article": row[9],
        }

        if topic_id not in feeds_by_topic:
            feeds_by_topic[topic_id] = []
        feeds_by_topic[topic_id].append(feed_entry)

    return feeds_by_topic


def get_topics_for_briefing(
    db: DatabaseManager, briefing_id: Optional[str] = None
) -> tuple[str, list[tuple]]:
    """Get topics associated with a briefing by joining topics and briefing_topics tables.

    If no briefing_id is provided, fetches topics for the most recent briefing.
    Table joins: topics <- briefing_topics -> briefings

    Args:
        db (DatabaseManager): Database connection manager
        briefing_id (Optional[str]): Specific briefing ID (format: YYYY-MM-DD-HH-MM),
                                    if None uses most recent briefing

    Returns:
        tuple[str, list[tuple]]: Tuple containing:
            - str: briefing ID
            - list[tuple]: List of topic tuples (id, title, generated_at, summary)
                          Empty list if no topics or briefing found

    """
    if briefing_id is None:
        recent_briefing = get_most_recent_briefing(db)
        if not recent_briefing:
            return []
        briefing_id = recent_briefing[0]

    topics_query = f"""
        SELECT t.id, t.title, t.generated_at, t.summary
        FROM topics t
        JOIN briefing_topics bt ON t.id = bt.topic_id
        WHERE bt.briefing_id = '{briefing_id}'
    """
    briefing_topics = db.run_query(topics_query)

    return briefing_id, briefing_topics


def store_briefing_with_topics(
    db: DatabaseManager,
    selected_topic_ids: List[str],
    briefing_id: Optional[str] = None,
) -> str:
    """Store a new briefing and its associated topics in the database.

    Args:
            db (DatabaseManager): Database connection manager
            selected_topic_ids (List[str]): List of selected topic IDs
            briefing_id (Optional[str]): Unique identifier for the briefing. Defaults to current UTC timestamp.

    Returns:
        str: The unique identifier for the created briefing.
    """
    if briefing_id is None:
        briefing_id = get_utc_now_simple()

    # Create a new entry in the briefings table
    utc_now_formatted = get_utc_now_formatted()
    db.insert(
        table="briefings",
        columns=["id", "generated_at"],
        values=[briefing_id, utc_now_formatted],
    )

    # Insert selected topic IDs into the briefing_topics table
    for topic_id in selected_topic_ids:
        db.insert(
            table="briefing_topics",
            columns=["briefing_id", "topic_id"],
            values=[briefing_id, topic_id],
        )
    return briefing_id