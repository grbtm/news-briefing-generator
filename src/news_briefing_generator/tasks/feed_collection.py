import asyncio
from typing import List

import aiohttp
import feedparser

from news_briefing_generator.model.feed import FeedItem
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import TaskResult
from news_briefing_generator.utils.async_progress import track_async_progress
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted


class FeedCollectionTask(Task):
    """Implementation of feed collection task.

    Collects feed entries from configured RSS/ATOM sources and stores them
    in the database. Handles async fetching, parsing and deduplication.

    Attributes:
        DEFAULT_TIMEOUT: Default timeout for feed requests in seconds
        DEFAULT_USER_AGENT: Default user agent string for requests
    """

    DEFAULT_TIMEOUT: int = 15
    DEFAULT_USER_AGENT: str = "Mozilla/5.0"

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "feed_collection"

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Execute feed collection with task context.

        Args:
            context: Task context containing:
                - db: Database connection
                - conf: Configuration manager
                - params: Optional parameters:
                    - timeout: Request timeout in seconds
                    - user_agent: User agent string for requests

        Returns:
            TaskResult containing:
                - data: Dict with feeds_processed count
                - metrics: Dict with total_feeds and entries_stored counts
        """
        try:
            # Get feed URLs from config
            feed_urls = [feed["url"] for feed in self.context.conf.get("feeds")]
            self.logger.info(f"Starting feed collection for {len(feed_urls)} sources")

            # Get optional parameters
            timeout = self.get_parameter("timeout", default=self.DEFAULT_TIMEOUT)
            user_agent = self.get_parameter(
                "user_agent", default=self.DEFAULT_USER_AGENT
            )

            # Collect feeds
            feeds = await self._collect_feeds(
                feed_urls=feed_urls, timeout=timeout, user_agent=user_agent
            )
            self.logger.info(f"Successfully fetched {len(feeds)} feed entries")

            # Store feeds in database
            self.logger.debug("Writing feeds to database")
            self.context.db.insert_many(
                table="feeds",
                columns=[
                    "title",
                    "link",
                    "published",
                    "summary",
                    "source",
                    "feed_url",
                    "fetched_at",
                ],
                values=feeds,
            )
            self.logger.info(f"Successfully stored {len(feeds)} feed entries")

            return TaskResult(
                task_name=self.name,
                success=True,
                created_at=get_utc_now_formatted(),
                metrics={"total_feeds": len(feed_urls), "entries_stored": len(feeds)},
            )

        except Exception as e:
            self.logger.error(f"Feed collection failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"total_feeds": len(feed_urls), "entries_stored": 0},
            )

    async def _collect_feeds(
        self, feed_urls: List[str], timeout: int, user_agent: str
    ) -> List[tuple]:
        """Collect and process feed entries from provided URLs.

        Args:
            feed_urls: List of RSS/ATOM feed URLs to fetch
            timeout: Request timeout in seconds
            user_agent: User agent string for requests

        Returns:
            List of feed entry tuples ready for database insertion
        """
        processed_items = set()
        collected_items = []

        async def fetch_feed(session: aiohttp.ClientSession, url: str) -> tuple:
            """Fetch single feed asynchronously."""
            try:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=timeout)
                ) as response:
                    text = await response.text()
                    self.logger.debug(f"Successfully fetched feed from {url}")
                    return (url, text)
            except asyncio.TimeoutError:
                self.logger.warning(f"Timeout error for URL: {url}")
                return (url, None)
            except Exception as e:
                self.logger.error(f"Error fetching URL {url}: {str(e)}")
                return (url, None)

        # Fetch feeds concurrently
        headers = {"User-Agent": user_agent}
        async with aiohttp.ClientSession(headers=headers) as session:
            tasks = [fetch_feed(session, url) for url in feed_urls]
            responses = await track_async_progress(
                coroutines=tasks,
                desc="Fetching feeds",
                logger=self.logger,
                unit="feeds",
            )

        # Process responses
        for feed_url, response in responses:
            if not response:
                continue

            feed = feedparser.parse(response)
            if not feed.entries:
                self.logger.warning(
                    f"No entries found for feed: {feed_url}. See feed: {feed}"
                )
                continue

            # Get source name from config or feed
            source = self.context.conf.url_to_feedname.get(
                feed_url, feed.feed.get("title", feed_url)
            )

            # Process entries
            entries_processed = 0
            for entry in feed.entries:
                feed_item = FeedItem.from_entry(entry, source, feed_url)
                if feed_item is None:
                    continue

                item = feed_item.to_tuple()
                item_key = (feed_item.source, feed_item.link)

                # Drop duplicates
                if item_key not in processed_items:
                    collected_items.append(item)
                    processed_items.add(item_key)
                    entries_processed += 1

            self.logger.debug(
                f"Processed {entries_processed} entries from {source} ({feed_url})"
            )

        self.logger.info(
            f"Feed collection completed. Total entries: {len(collected_items)}"
        )
        return collected_items
