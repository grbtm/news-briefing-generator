from dataclasses import dataclass

from news_briefing_generator.preprocessing.parsing import html_to_text, to_dt_utc
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted


@dataclass
class FeedItem:
    """Dataclass to store feed items."""

    title: str | None = None
    link: str | None = None
    published: str | None = None
    summary: str | None = None
    source: str | None = None
    feed_url: str | None = None
    fetched_at: str | None = None

    @classmethod
    def from_entry(self, entry: str, source: str, feed_url: str) -> "FeedItem":
        """Creates a FeedItem object from a feedparser entry."""

        # If the entry does not have a link, skip it
        if "link" not in entry:
            return None

        self.source = source
        self.feed_url = feed_url
        self.title = entry.get("title", None)
        self.link = entry.link
        self.published = to_dt_utc(entry.get("published", entry.get("updated", None)))
        self.summary = html_to_text(entry.get("summary", None))
        self.fetched_at = get_utc_now_formatted()

        return FeedItem(
            self.title,
            self.link,
            self.published,
            self.summary,
            self.source,
            self.feed_url,
            self.fetched_at,
        )

    def to_tuple(self) -> tuple:
        """Converts the FeedItem object to a tuple."""
        return (
            self.title,
            self.link,
            self.published,
            self.summary,
            self.source,
            self.feed_url,
            self.fetched_at,
        )
