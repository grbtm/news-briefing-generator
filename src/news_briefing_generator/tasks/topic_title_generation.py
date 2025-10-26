from typing import Any, Dict, List, Optional

from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.prompt.topics.topic_titles import (
    TOPIC_TITLE_GENERATION_SYSTEM,
    TOPIC_TITLE_GENERATION_USER,
)
from news_briefing_generator.utils.async_progress import track_async_progress
from news_briefing_generator.utils.database_ops import (
    get_feeds_for_topics,
    get_most_recent_topics,
)
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted
from news_briefing_generator.utils.text_processing import preprocess_llm_output


class TopicTitleGenerationTask(Task):
    """Implementation of topic title generation task.

    Generates descriptive titles for topic clusters using LLM. Processes multiple
    topics concurrently and collects token usage metrics for each LLM call.

    Attributes:
        DEFAULT_MAX_SUMMARY_LENGTH (int): Default character limit for article summaries
        DEFAULT_MAX_TITLE_WORDS (int): Default maximum words for generated topic titles
    """

    DEFAULT_MAX_SUMMARY_LENGTH: int = 500
    DEFAULT_MAX_TITLE_WORDS: int = 10

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "topic_title_generation"

    @property
    def requires_llm(self) -> bool:
        return True

    async def execute(self) -> TaskResult:
        """Execute topic title generation task."""
        try:
            max_summary_length = self.get_parameter(
                "max_summary_length", default=self.DEFAULT_MAX_SUMMARY_LENGTH
            )
            max_title_words = self.get_parameter(
                "max_title_words", default=self.DEFAULT_MAX_TITLE_WORDS
            )
            return await self._run_title_generation(max_summary_length, max_title_words)
        except Exception as e:
            self.logger.error(f"Topic title generation failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"topics_processed": 0, "titles_generated": 0},
            )

    async def _run_title_generation(
        self, max_summary_length: Optional[int], max_title_words: int
    ) -> TaskResult:
        """Generate titles for topic clusters using LLM.

        Processes multiple topics concurrently, collecting token usage metrics for each LLM call.
        Fetches the most recent topics and their associated feed entries from the database,
        then generates descriptive titles using the provided language model.

        Args:
            max_summary_length: Character limit for article summaries
            max_title_words: Maximum words for generated topic titles

        Returns:
            TaskResult with generated titles and metrics
        """
        db = self.context.db
        llm = self.context.llm

        # Get most recent topics
        topics = get_most_recent_topics(db)
        if not topics:
            warning_msg = (
                f"{NO_DATA_WARNING}No recent topics found for title generation"
            )
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                data={"titles_generated": 0},
                metrics={"topics_processed": 0},
            )

        # Get associated feeds for each topic
        topic_ids = [topic[0] for topic in topics]
        feeds_by_topic = get_feeds_for_topics(db, topic_ids)

        # Prepare LLM prompts
        tasks = []
        valid_topic_ids = []
        valid_formatted_texts = []

        for topic_id in topic_ids:
            headlines = feeds_by_topic.get(topic_id, [])
            formatted_text = self._prepare_topic_prompts(
                topic_id, headlines, max_summary_length
            )

            if formatted_text:
                prompts = llm.prepare_prompts(
                    human=TOPIC_TITLE_GENERATION_USER.format(
                        headlines=formatted_text, max_words=max_title_words
                    ),
                    system=TOPIC_TITLE_GENERATION_SYSTEM,
                )
                tasks.append(llm.generate_async(prompts=prompts))
                valid_topic_ids.append(topic_id)
                valid_formatted_texts.append(formatted_text)

        self.logger.info(f"Generating titles for {len(tasks)} topics")
        aimessages = await track_async_progress(
            coroutines=tasks,
            desc="Generating titles",
            logger=self.logger,
            unit="topics",
        )

        # Process results
        updates = []
        for topic_id, message, formatted_text in zip(
            valid_topic_ids, aimessages, valid_formatted_texts
        ):
            title = preprocess_llm_output(message.content)
            updates.append(
                (title, topic_id)
            )  # this tuple order is expected in sqlite executemany update
            # self.logger.debug(
            #     f"Topic ID: {topic_id}, Generated Title: {title}, Headlines: {formatted_text}"
            # )

        # Write topic titles to database
        db.update_many(
            table="topics",
            columns=["title"],
            values=updates,
            condition_columns="id",
        )

        # Collect metrics
        metrics = {
            "sum_input_tokens": sum(
                msg.usage_metadata.get("input_tokens", 0) for msg in aimessages
            ),
            "sum_output_tokens": sum(
                msg.usage_metadata.get("output_tokens", 0) for msg in aimessages
            ),
            "sum_total_tokens": sum(
                msg.usage_metadata.get("total_tokens", 0) for msg in aimessages
            ),
            "input_tokens": [
                msg.usage_metadata.get("input_tokens", 0) for msg in aimessages
            ],
            "output_tokens": [
                msg.usage_metadata.get("output_tokens", 0) for msg in aimessages
            ],
            "topics_processed": len(topics),
            "titles_generated": len(updates),
        }

        self.logger.info(f"Successfully generated {len(updates)} topic titles")
        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            metrics=metrics,
        )

    def _format_headline(
        self, headline: Dict[str, Any], index: int, max_summary_length: Optional[int]
    ) -> str:
        """Format single headline with source and summary."""
        source = self.context.conf.url_to_feedname.get(
            headline["feed_url"], headline["source"]
        )
        summary = headline.get("summary", "")

        if summary and max_summary_length:
            summary = f"{summary[:max_summary_length]}{'...' if len(summary) > max_summary_length else ''}"

        return f"Headline {index}: \n{source}: {headline['title']}\nAbstract: {summary}"

    def _prepare_topic_prompts(
        self,
        topic_id: str,
        headlines: List[Dict[str, Any]],
        max_summary_length: Optional[int] = None,
    ) -> str:
        """Prepare formatted headlines string for LLM prompt."""
        if not headlines:
            self.logger.warning(f"No headlines found for topic {topic_id}")
            return None

        formatted_headlines = [
            self._format_headline(h, i, max_summary_length)
            for i, h in enumerate(headlines, start=1)
        ]
        return "\n\n".join(formatted_headlines)
