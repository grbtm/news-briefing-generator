from dataclasses import dataclass
from typing import Dict, List, Optional

from langchain_core.messages.ai import AIMessage

from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.prompt.summarization.topic import (
    TOPIC_SUMMARY_SYSTEM,
    TOPIC_SUMMARY_USER,
)
from news_briefing_generator.utils.async_progress import track_async_progress
from news_briefing_generator.utils.database_ops import get_topics_for_briefing
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted
from news_briefing_generator.utils.text_processing import preprocess_llm_output


@dataclass
class TopicData:
    """Container for topic summary task data."""

    topic_id: str
    topic_title: str
    summaries_text: str


class TopicSummarizationTask(Task):
    """Implementation of topic summarization task.

    Generates comprehensive summaries for each topic in a briefing by analyzing
    the summaries of its associated articles.

    Attributes:
        DEFAULT_SUMMARIES_PER_TOPIC: Maximum article summaries to include per topic
    """

    DEFAULT_SUMMARIES_PER_TOPIC: int = 10

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "topic_summarization"

    @property
    def requires_llm(self) -> bool:
        return True

    async def execute(self) -> TaskResult:
        """Execute topic summarization task."""
        try:
            summaries_per_topic = self.get_parameter(
                "summaries_per_topic", default=self.DEFAULT_SUMMARIES_PER_TOPIC
            )
            return await self._run_summarization(summaries_per_topic)
        except Exception as e:
            self.logger.error(f"Topic summarization failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"topics_processed": 0, "summaries_generated": 0},
            )

    async def _run_summarization(self, summaries_per_topic: int) -> TaskResult:
        """Generate topic summaries from article summaries.

        Args:
            summaries_per_topic: Number of article summaries to include per topic
        """
        db = self.context.db

        # Get briefing topics
        briefing_id, briefing_topics = get_topics_for_briefing(db)
        if not briefing_topics:
            return self._create_no_topics_result(briefing_id)

        self.logger.info(f"Processing topic summaries for briefing {briefing_id}")

        # Prepare summary tasks
        summary_tasks = self._prepare_summary_tasks(
            briefing_topics, summaries_per_topic
        )
        if not summary_tasks:
            return self._create_no_summaries_result(briefing_id, len(briefing_topics))

        # Generate summaries
        self.logger.info(f"Generating summaries for {len(summary_tasks)} topics")
        aimessages = await self._generate_summaries(summary_tasks)

        # Update database and organize results
        topic_summaries = self._process_results(summary_tasks, aimessages)

        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            data={"briefing_id": briefing_id, "topic_summaries": topic_summaries},
            metrics=self._calculate_metrics(briefing_topics, summary_tasks, aimessages),
        )

    def _prepare_summary_tasks(
        self, topics: List[tuple], summaries_per_topic: int
    ) -> List[TopicData]:
        """Prepare summary tasks from topics."""
        tasks = []
        for topic_id, topic_title in [(t[0], t[1]) for t in topics]:
            summaries_text = self._get_article_summaries(topic_id, summaries_per_topic)
            if summaries_text:
                tasks.append(
                    TopicData(
                        topic_id=topic_id,
                        topic_title=topic_title,
                        summaries_text=summaries_text,
                    )
                )
            else:
                self.logger.warning(f"No article summaries found for topic {topic_id}")
        return tasks

    def _get_article_summaries(self, topic_id: str, limit: int) -> Optional[str]:
        """Get formatted article summaries for a topic and mark used articles.

        Args:
            topic_id: Topic ID to get summaries for
            limit: Maximum number of summaries to include

        Returns:
            Formatted text of summaries or None if no summaries found
        """
        query = f"""
            SELECT f.source, f.title, f.summarized_article, f.id
            FROM feeds f
            JOIN topic_feeds tf ON f.id = tf.feed_id
            WHERE tf.topic_id = '{topic_id}'
            AND f.summarized_article IS NOT NULL
            ORDER BY f.published DESC
            LIMIT {limit}
        """
        results = self.context.db.run_query(query)
        if not results:
            return None

        if len(results) < limit:
            self.logger.info(
                f"Only {len(results)} summaries available for topic {topic_id}"
            )

        # Mark articles as used for summarization
        feed_ids = [row[3] for row in results]
        self.context.db.update_many(
            table="topic_feeds",
            columns=["used_for_summarization"],
            values=[(1, topic_id, feed_id) for feed_id in feed_ids],
            condition_columns=["topic_id", "feed_id"],
        )
        return "\n\n".join(
            f"Article {i+1} from {summary[0]}:\n"
            f"Title: {summary[1]}\n"
            f"Summary: {summary[2]}"
            for i, summary in enumerate(results)
        )

    async def _generate_summaries(self, tasks: List[TopicData]) -> List[AIMessage]:
        """Generate summaries concurrently."""
        coroutines = []
        for task in tasks:
            prompts = self.context.llm.prepare_prompts(
                system=TOPIC_SUMMARY_SYSTEM,
                human=TOPIC_SUMMARY_USER.format(article_summaries=task.summaries_text),
            )
            coroutines.append(self.context.llm.generate_async(prompts=prompts))

        results = await track_async_progress(
            coroutines,
            desc="Generating topic summaries",
            logger=self.logger,
            unit="topics",
        )

        return results

    def _process_results(
        self, tasks: List[TopicData], messages: List[AIMessage]
    ) -> Dict[str, AIMessage]:
        """Process results and update database."""
        # Create result mapping
        topic_summaries = {
            task.topic_id: message for task, message in zip(tasks, messages)
        }

        # Update database
        updates = [
            (preprocess_llm_output(message.content), task.topic_id)
            for task, message in zip(tasks, messages)
        ]
        self.context.db.update_many(
            table="topics", columns=["summary"], values=updates, condition_columns="id"
        )
        self.logger.info(
            f"Topic summaries generated and stored for {len(updates)} topics"
        )
        return topic_summaries

    def _calculate_metrics(
        self,
        topics: List[tuple],
        tasks: List[TopicData],
        messages: List[AIMessage],
    ) -> Dict[str, int]:
        """Calculate task metrics."""
        return {
            "topics_processed": len(topics),
            "summaries_generated": len(tasks),
            "sum_input_tokens": sum(
                msg.usage_metadata.get("input_tokens", 0) for msg in messages
            ),
            "sum_output_tokens": sum(
                msg.usage_metadata.get("output_tokens", 0) for msg in messages
            ),
            "sum_total_tokens": sum(
                msg.usage_metadata.get("total_tokens", 0) for msg in messages
            ),
            "input_tokens": [
                msg.usage_metadata.get("input_tokens", 0) for msg in messages
            ],
            "output_tokens": [
                msg.usage_metadata.get("output_tokens", 0) for msg in messages
            ],
        }

    def _create_no_topics_result(self, briefing_id: str) -> TaskResult:
        """Create result for no topics case."""
        warning_msg = f"{NO_DATA_WARNING}No topics found for briefing {briefing_id}"
        self.logger.warning(warning_msg)
        return TaskResult(
            task_name=self.name,
            success=True,
            warning=warning_msg,
            created_at=get_utc_now_formatted(),
            data={"briefing_id": briefing_id},
            metrics={"topics_processed": 0, "summaries_generated": 0},
        )

    def _create_no_summaries_result(
        self, briefing_id: str, topic_count: int
    ) -> TaskResult:
        """Create result for no summaries case."""
        warning_msg = f"{NO_DATA_WARNING}No topic summary tasks created"
        self.logger.warning(warning_msg)
        return TaskResult(
            task_name=self.name,
            success=True,
            warning=warning_msg,
            created_at=get_utc_now_formatted(),
            data={"briefing_id": briefing_id},
            metrics={
                "topics_processed": topic_count,
                "summaries_generated": 0,
            },
        )
