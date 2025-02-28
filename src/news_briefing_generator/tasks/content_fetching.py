import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import aiohttp
import requests
from bs4 import BeautifulSoup

from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.utils.async_progress import track_async_progress
from news_briefing_generator.utils.database_ops import (
    get_feeds_for_topics,
    get_topics_for_briefing,
)
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted


@dataclass
class ScrapedContent:
    """Container for scraped content and metadata."""

    url: str
    content: str
    timestamp: str
    status_code: int


class ContentFetchingTask(Task):
    """Implementation of content fetching task for RSS/ATOM feed articles.

    This task fetches the full article content for all feed entries associated with
    the most recent briefing's topics. It handles asynchronous fetching with rate
    limiting, robots.txt compliance, and error handling. The content is then stored
    back in the feeds table for further processing.

    Attributes:
    DEFAULT_TIMEOUT (int): Default request timeout in seconds (30)
    DEFAULT_MAX_CONCURRENT (int): Default maximum concurrent requests (5)
    DEFAULT_RATE_LIMIT (float): Default delay between requests in seconds (0.5)
    DEFAULT_CHECK_ROBOTS_TXT (bool): Default setting for robots.txt compliance (True)
    """

    DEFAULT_TIMEOUT: int = 30
    DEFAULT_MAX_CONCURRENT: int = 5
    DEFAULT_RATE_LIMIT: float = 0.5
    DEFAULT_CHECK_ROBOTS_TXT: bool = True

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "content_fetching"

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Execute the scraping task."""
        try:
            return await self._run_content_fetching()
        except Exception as e:
            self.logger.error(f"Scraping task failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"total_urls": 0, "successful_fetches": 0},
            )

    async def _run_content_fetching(self) -> TaskResult:
        """Scrape article content for feeds associated with the most recent briefing."""
        db = self.context.db

        # 1. Get topics from the most recent briefing
        briefing_id, briefing_topics = get_topics_for_briefing(db=db)
        self.logger.info(
            f"Found {len(briefing_topics)} topics for briefing {briefing_id}"
        )

        if not briefing_topics:
            warning_msg = f"{NO_DATA_WARNING}No topics found for briefing {briefing_id}, skipping scraping"
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                data={"feeds_scraped": 0},
                metrics={"total_urls": 0, "successful_fetches": 0},
            )

        # 2. Fetch related feed entries
        topic_ids = [topic[0] for topic in briefing_topics]
        feeds_by_topic = get_feeds_for_topics(db=db, topic_ids=topic_ids)

        # Flatten feeds into a single list
        all_feeds = []
        for feed_list in feeds_by_topic.values():
            all_feeds.extend(feed_list)

        if not all_feeds:
            warning_msg = f"{NO_DATA_WARNING}No feeds found for briefing {briefing_id} topics, skipping scraping"
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                data={"feeds_scraped": 0},
                metrics={"total_urls": 0, "successful_fetches": 0},
            )

        # 3. Collect URLs and fetch content
        urls = [feed["link"] for feed in all_feeds]
        params = self._resolve_fetch_params()

        self.logger.info(f"Attempting to fetch {len(urls)} URLs")
        scraped_results = await self._fetch_content(urls=urls, **params)

        # Count successful scrapes
        successful_fetches = len([r for r in scraped_results if r is not None])
        self.logger.info(f"Successfully fetched {successful_fetches}/{len(urls)} URLs")

        # 4. Write fetched content back to feeds table
        updates = [(text, feed["id"]) for feed, text in zip(all_feeds, scraped_results)]
        db.update_many(
            table="feeds",
            columns=["scraped_text"],
            values=updates,
            condition_columns="id",
        )

        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            data={"feeds_scraped": len(updates), "briefing_id": briefing_id},
            metrics={
                "total_urls": len(urls),
                "successful_fetches": successful_fetches,
                "success_rate": successful_fetches / len(urls) if urls else 0,
            },
        )

    async def _fetch_content(
        self,
        urls: List[str],
        max_concurrent: int,
        rate_limit: float,
        timeout: int,
        user_agent: Optional[str] = None,
        check_robots_txt: bool = True,
    ) -> List[str]:
        """Asynchronously scrape a list of URLs."""
        sem = asyncio.Semaphore(max_concurrent)
        fetched_contents: List[str] = []
        robots_cache: Dict[str, bool] = {}
        requests_session = self._setup_requests_session()

        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=timeout)
        ) as session:

            async def rate_limited_fetch(url: str) -> Optional[str]:
                try:
                    async with sem:
                        if check_robots_txt:
                            domain = urlparse(url).netloc
                            if domain not in robots_cache:
                                robots_cache[domain] = await self._check_robots_txt(
                                    session, url, user_agent
                                )
                            if not robots_cache[domain]:
                                self.logger.warning(
                                    f"Skipping {url}: not allowed by robots.txt"
                                )
                                return None

                        await asyncio.sleep(rate_limit)
                        result = await self._fetch_page(session, requests_session, url)
                        if result:
                            return BeautifulSoup(
                                result.content, "html.parser"
                            ).get_text()
                        return None
                except Exception as e:
                    self.logger.error(f"Error fetching {url}: {str(e)}")
                    return None

            # Create tasks
            tasks = [rate_limited_fetch(url) for url in urls]
            fetched_contents = await track_async_progress(
                tasks, desc="Fetching content", logger=self.logger
            )

        return fetched_contents

    async def _fetch_page(
        self,
        session: aiohttp.ClientSession,
        requests_session: requests.Session,
        url: str,
    ) -> Optional[ScrapedContent]:
        """Fetch single page with error handling."""
        try:
            kwargs: Dict = dict(
                headers=requests_session.headers,
                cookies=requests_session.cookies.get_dict(),
            )
            async with session.get(url, **kwargs) as response:
                if response.status == 200:
                    content = await response.text()
                    return ScrapedContent(
                        url=url,
                        content=content,
                        timestamp=get_utc_now_formatted(),
                        status_code=response.status,
                    )
                self.logger.warning(f"Failed to fetch {url}, status: {response.status}")
        except Exception as e:
            self.logger.error(f"Error fetching {url}: {str(e)}")
        return None

    async def _check_robots_txt(
        self, session: aiohttp.ClientSession, url: str, user_agent: str
    ) -> bool:
        """Check if URL is allowed by robots.txt."""
        try:
            parsed_url = urlparse(url)
            domain = f"{parsed_url.scheme}://{parsed_url.netloc}"
            robots_url = f"{domain}/robots.txt"

            async with session.get(robots_url) as response:
                if response.status == 200:
                    robots_content = await response.text()
                    parser = RobotFileParser()
                    parser.parse(robots_content.splitlines())
                    return parser.can_fetch(user_agent, url)
                return True  # If no robots.txt, assume allowed
        except Exception as e:
            self.logger.warning(f"Error checking robots.txt for {url}: {e}")
            return True

    def _resolve_fetch_params(self) -> Dict[str, Any]:
        """Resolve parameters for content fetching from config sources."""
        return {
            "user_agent": self.get_parameter("user_agent", default=None),
            "check_robots_txt": self.get_parameter(
                "check_robots_txt", default=self.DEFAULT_CHECK_ROBOTS_TXT
            ),
            "timeout": self.get_parameter("timeout", default=self.DEFAULT_TIMEOUT),
            "max_concurrent": self.get_parameter(
                "max_concurrent", default=self.DEFAULT_MAX_CONCURRENT
            ),
            "rate_limit": self.get_parameter(
                "rate_limit", default=self.DEFAULT_RATE_LIMIT
            ),
        }

    @staticmethod
    def _setup_requests_session() -> requests.Session:
        default_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:132.0) Gecko/20100101 Firefox/132.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*"
            ";q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": "https://www.google.com/",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        session = requests.Session()
        session.headers = dict(default_headers)
        session.verify = True
        return session
