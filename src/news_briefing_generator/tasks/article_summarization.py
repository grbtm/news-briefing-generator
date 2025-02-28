import asyncio
import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from langchain_core.messages.ai import AIMessage

from news_briefing_generator.llm.base import LLM
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.prompt.summarization.article import (
    ARTICLE_SUMMARY_SYSTEM,
    ARTICLE_SUMMARY_USER,
)
from news_briefing_generator.utils.async_progress import track_async_progress
from news_briefing_generator.utils.database_ops import (
    get_feeds_for_topics,
    get_topics_for_briefing,
)
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted


@dataclass
class ArticleData:
    """Container for article processing tasks."""

    topic_id: str
    feed_id: str
    text: str


@dataclass
class ProcessingResult:
    """Container for processing results."""

    feed_id: str
    topic_id: str
    content: Optional[str]
    response_metadata: Optional[Dict] = None
    usage_metadata: Optional[Dict] = None
    success: bool = True


class ArticleSummarizationTask(Task):
    """Implementation of article summarization task.

    Generates summaries for articles associated with a briefing's topics.
    Handles concurrent processing and token usage tracking.

    Attributes:
        DEFAULT_MAX_LENGTH: Maximum length for article text
        DEFAULT_MAX_CONCURRENT: Maximum concurrent LLM requests
        DEFAULT_NR_ARTICLES: Maximum articles to process per topic
    """

    DEFAULT_MAX_LENGTH: Optional[int] = None
    DEFAULT_MAX_CONCURRENT: int = 5
    DEFAULT_NR_ARTICLES: Optional[int] = None

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "article_summarization"

    @property
    def requires_llm(self) -> bool:
        return True

    async def execute(self) -> TaskResult:
        """Execute article summarization task."""
        try:
            briefing_id = self.get_parameter("briefing_id", default=None)
            max_length = self.get_parameter(
                "max_length", default=self.DEFAULT_MAX_LENGTH
            )
            max_concurrent = self.get_parameter(
                "max_concurrent", default=self.DEFAULT_MAX_CONCURRENT
            )
            nr_articles = self.get_parameter(
                "nr_articles", default=self.DEFAULT_NR_ARTICLES
            )

            return await self._run_summarization(
                briefing_id=briefing_id,
                max_length=max_length,
                max_concurrent=max_concurrent,
                nr_articles=nr_articles,
            )
        except Exception as e:
            self.logger.error(f"Article summarization failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"articles_processed": 0, "summaries_generated": 0},
            )

    async def _run_summarization(
        self,
        briefing_id: Optional[str] = None,
        max_length: Optional[int] = None,
        max_concurrent: int = DEFAULT_MAX_CONCURRENT,
        nr_articles: Optional[int] = None,
    ) -> TaskResult:
        """Run article summarization for a briefing.

        Args:
            briefing_id: Optional briefing ID, uses most recent if None
        """
        db = self.context.db
        llm = self.context.llm

        # Get briefing topics
        briefing_id, briefing_topics = get_topics_for_briefing(db, briefing_id)
        self.logger.info(
            f"Processing briefing {briefing_id}: {len(briefing_topics)} topics"
        )

        if not briefing_topics:
            warning_msg = f"{NO_DATA_WARNING}No topics found for briefing {briefing_id}"
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                metrics={"topics_processed": 0},
            )

        # Get feeds for topics
        feeds_by_topic = get_feeds_for_topics(db, [t[0] for t in briefing_topics])
        semaphore = asyncio.Semaphore(max_concurrent)

        # Prepare article tasks
        article_tasks = []
        for topic_id, feeds in feeds_by_topic.items():
            valid_feeds = [f for f in feeds if f.get("scraped_text")]

            if not valid_feeds:
                self.logger.warning(f"No scraped articles found for topic {topic_id}")
                continue

            selected_feeds = (
                random.sample(valid_feeds, nr_articles)
                if nr_articles and len(valid_feeds) > nr_articles
                else valid_feeds
            )

            for feed in selected_feeds:
                article_tasks.append(
                    ArticleData(
                        topic_id=topic_id, feed_id=feed["id"], text=feed["scraped_text"]
                    )
                )

        if not article_tasks:
            warning_msg = (
                f"{NO_DATA_WARNING}No valid articles found for briefing {briefing_id}"
            )
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                metrics={"topics_processed": 0},
            )

        # Process articles
        self.logger.info(f"Generating summaries for {len(article_tasks)} articles")
        summarization_results = await self._process_articles(
            article_tasks, llm, semaphore, max_length
        )

        # Process results
        summaries_by_topic: Dict[str, List[Tuple[str, AIMessage]]] = {}
        successful_summaries = [
            r for r in summarization_results if r.success and r.content
        ]

        # Organize by topic
        for result in successful_summaries:
            if result.topic_id not in summaries_by_topic:
                summaries_by_topic[result.topic_id] = []
            summaries_by_topic[result.topic_id].append(
                (result.feed_id, AIMessage(content=result.content))
            )

        # Update database
        db.update_many(
            table="feeds",
            columns=["summarized_article"],
            values=[(r.content, r.feed_id) for r in successful_summaries],
            condition_columns="id",
        )

        self.logger.info(f"Successfully processed {len(successful_summaries)} articles")

        # Calculate metrics
        metrics = {
            "articles_processed": len(article_tasks),
            "summaries_generated": len(successful_summaries),
            "failed": len([r for r in summarization_results if not r.success]),
            "sum_input_tokens": sum(
                r.usage_metadata.get("input_tokens", 0)
                for r in summarization_results
                if r.success
            ),
            "sum_output_tokens": sum(
                r.usage_metadata.get("output_tokens", 0)
                for r in summarization_results
                if r.success
            ),
            "sum_total_tokens": sum(
                r.usage_metadata.get("total_tokens", 0)
                for r in summarization_results
                if r.success
            ),
            "input_tokens": [
                r.usage_metadata.get("input_tokens", 0)
                for r in summarization_results
                if r.success
            ],
            "output_tokens": [
                r.usage_metadata.get("output_tokens", 0)
                for r in summarization_results
                if r.success
            ],
        }

        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            data={"briefing_id": briefing_id, "summaries": summaries_by_topic},
            metrics=metrics,
        )

    async def _process_articles(
        self,
        tasks: List[ArticleData],
        llm: LLM,
        semaphore: asyncio.Semaphore,
        max_length: Optional[int] = None,
    ) -> List[ProcessingResult]:
        """Process article tasks concurrently."""

        async def summarize_with_semaphore(task: ArticleData) -> ProcessingResult:
            async with semaphore:
                try:
                    if not task.text:
                        self.logger.warning(
                            f"Empty article text for feed {task.feed_id}"
                        )
                        return ProcessingResult(
                            feed_id=task.feed_id,
                            topic_id=task.topic_id,
                            content=None,
                            success=False,
                        )

                    result = await self._generate_article_summary(
                        task.text, llm, max_length
                    )
                    return ProcessingResult(
                        feed_id=task.feed_id,
                        topic_id=task.topic_id,
                        content=result.content,
                        response_metadata=result.response_metadata,
                        usage_metadata=result.usage_metadata,
                    )
                except Exception as e:
                    self.logger.error(
                        f"Summarization failed for feed {task.feed_id}: {str(e)}"
                    )
                    return ProcessingResult(
                        feed_id=task.feed_id,
                        topic_id=task.topic_id,
                        content=None,
                        success=False,
                    )

        coroutines = [summarize_with_semaphore(task) for task in tasks]

        results = await track_async_progress(
            coroutines=coroutines,
            desc="Summarizing articles",
            logger=self.logger,
            unit="articles",
        )

        return results

    async def _generate_article_summary(
        self, article_text: str, llm: LLM, max_length: Optional[int] = None
    ) -> AIMessage:
        """Generate summary for single article."""
        if max_length:
            article_text = article_text[:max_length]

        prompts = llm.prepare_prompts(
            system=ARTICLE_SUMMARY_SYSTEM,
            human=ARTICLE_SUMMARY_USER.format(article=article_text),
        )
        return await llm.generate_async(prompts=prompts)
