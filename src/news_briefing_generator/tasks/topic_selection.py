from typing import Any, Dict, List

import typer

from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.llm.base import LLM
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.model.topic import Topic
from news_briefing_generator.prompt.topics.topic_selection import (
    TOPIC_SELECTION_SYSTEM,
    TOPIC_SELECTION_USER,
)
from news_briefing_generator.utils.database_ops import (
    get_feeds_for_topics,
    get_most_recent_topics,
    get_topics_for_briefing,
    store_briefing_with_topics,
)
from news_briefing_generator.utils.datetime_ops import get_utc_now_formatted


class TopicSelectionTask(Task):
    """Implementation of topic selection task.

    Selects the most relevant topics for a news briefing based on
    configured criteria and LLM evaluation. Creates a new briefing with
    selected topics in the database.

    Attributes:
        DEFAULT_NR_TOPICS: Default number of topics to select
        MAX_SAMPLE_HEADLINES: Maximum headlines to include per topic
        NEWLINE: Newline character for formatting
    """

    DEFAULT_NR_TOPICS: int = 12
    MAX_SAMPLE_HEADLINES: int = 8
    NEWLINE: str = chr(10)

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "topic_selection"

    @property
    def requires_llm(self) -> bool:
        return True

    async def execute(self) -> TaskResult:
        """Execute topic selection with task context.

        Args:
            context: Task context containing:
                - db: Database connection
                - llm: LLM instance
                - conf: Configuration manager
                - params: Optional parameters:
                    - nr_topics: Number of topics to select
                    - nr_sample_headlines: Headlines to show per topic

        Returns:
            TaskResult containing:
                - data: Dict with briefing_id, selected_topics, selection_overview
                - metrics: Dict with topics_available, topics_selected, token usage

        Raises:
            ValueError: If required LLM is not provided
        """
        self.validate_context(self.context)

        try:
            # Fetch parameters
            nr_topics = self.get_parameter("nr_topics", default=self.DEFAULT_NR_TOPICS)
            nr_sample_headlines = self.get_parameter(
                "nr_sample_headlines", default=self.MAX_SAMPLE_HEADLINES
            )

            # Call existing implementation
            return await self._run_topic_selection(
                db=self.context.db,
                llm=self.context.llm,
                nr_topics=nr_topics,
                nr_sample_headlines=nr_sample_headlines,
            )

        except Exception as e:
            self.logger.error(f"Topic selection failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"topics_available": 0, "topics_selected": 0},
            )

    async def _run_topic_selection(
        self, db: DatabaseManager, llm: LLM, nr_topics: int, nr_sample_headlines: int
    ) -> TaskResult:
        """Core topic selection implementation.

        Args:
            db: Database connection for fetching topics
            llm: LLM for topic selection
            nr_topics: Number of topics to select
            nr_sample_headlines: Number of headlines to show per topic

        Returns:
            TaskResult with selection results and metrics

        Raises:
            ValueError: If no topics found or LLM response invalid
        """
        try:
            # Get recent topics from database
            topics = get_most_recent_topics(db=db)
            if not topics:
                warning_msg = f"{NO_DATA_WARNING}No recent topics found for selection"
                self.logger.warning(warning_msg)
                return TaskResult(
                    task_name="topic_selection",
                    success=True,
                    warning=warning_msg,
                    created_at=get_utc_now_formatted(),
                    data={"selected_topics": []},
                    metrics={"topics_available": 0, "topics_selected": 0},
                )

            topic_ids = [topic[0] for topic in topics]
            feeds_by_topic = get_feeds_for_topics(db=db, topic_ids=topic_ids)
            self.logger.info(f"Found {len(topics)} topics for selection")

            # Create formatted text with topics and their headlines
            topics_text = []
            for topic in topics:
                topic_id, title = topic[0], topic[1]
                topic_text = self._format_topic_with_summary(
                    topic_id,
                    title,
                    feeds_by_topic.get(topic_id, []),
                    nr_sample_headlines,
                )

                topics_text.append(topic_text)

            topics_text = "\n\n".join(topics_text)

            # Prepare LLM prompts
            system_prompt = TOPIC_SELECTION_SYSTEM.format(nr_topics=str(nr_topics))
            user_prompt = TOPIC_SELECTION_USER.format(
                topics_text=topics_text, nr_topics=str(nr_topics)
            )

            # Get LLM selection
            prompts = llm.prepare_prompts(human=user_prompt, system=system_prompt)
            response = await llm.generate_async(prompts=prompts)

            # Parse response to get selected ids
            try:
                selected_topic_ids = [
                    id.strip("[] \n\t\r") for id in response.content.split(",")
                ]
                self.logger.info(f"Selected {len(selected_topic_ids)} topics")

                # Log selection overview
                self.logger.info(
                    "Selection overview:\n%s",
                    self._format_topic_selection_overview(
                        [Topic(*topic) for topic in topics], selected_topic_ids
                    ),
                )

                # Store briefing and topics in the database
                briefing_id = store_briefing_with_topics(db, selected_topic_ids)

                self.logger.info(
                    f"Created new briefing {briefing_id} with {len(selected_topic_ids)} topics: {selected_topic_ids}"
                )
                return TaskResult(
                    task_name="topic_selection",
                    success=True,
                    created_at=get_utc_now_formatted(),
                    data={
                        "briefing_id": briefing_id,
                        "selected_topics": selected_topic_ids,
                        "selection_overview": self._format_topic_selection_overview(
                            [Topic(*topic) for topic in topics], selected_topic_ids
                        ),
                    },
                    metrics={
                        "topics_available": len(topics),
                        "topics_selected": len(selected_topic_ids),
                        "input_tokens": response.usage_metadata.get("input_tokens", 0),
                        "output_tokens": response.usage_metadata.get(
                            "output_tokens", 0
                        ),
                        "total_tokens": response.usage_metadata.get("total_tokens", 0),
                    },
                )

            except (ValueError, IndexError) as e:
                error_msg = f"Error parsing LLM response: {str(e)}"
                self.logger.error(error_msg)
                return TaskResult(
                    task_name="topic_selection",
                    success=False,
                    created_at=get_utc_now_formatted(),
                    error=error_msg,
                    data={
                        "llm_response": response.content,
                    },
                    metrics={
                        "topics_available": len(topics),
                        "topics_selected": 0,
                        "input_tokens": response.usage_metadata.get("input_tokens", 0),
                        "output_tokens": response.usage_metadata.get(
                            "output_tokens", 0
                        ),
                        "total_tokens": response.usage_metadata.get("total_tokens", 0),
                    },
                )

        except Exception as e:
            self.logger.error(f"Topic selection failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name="topic_selection",
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"topics_available": len(topics), "topics_selected": 0},
            )

    def _format_topic_with_summary(
        self,
        topic_id: str,
        title: str,
        feeds: List[Dict[str, Any]],
        nr_sample_headlines: int,
    ) -> str:
        """Format topic details for LLM prompt.

        Args:
            topic_id: Unique topic identifier
            title: Topic title
            feeds: List of feed entries for topic
            nr_sample_headlines: Maximum headlines to include

        Returns:
            Formatted topic text for LLM prompt
        """
        # Get unique sources and total count
        sources = sorted(set(feed["source"] for feed in feeds))
        source_summary = f"All sources: {', '.join(sources)}"
        article_count = f"Total articles: {len(feeds)}"

        # Format sample headlines (max 8)
        sample_headlines = [
            f"          {feed['source']}: {feed['title']}"
            for feed in feeds[:nr_sample_headlines]
        ]

        topic_text = f"""{topic_id}: {title}
        {article_count}
        {source_summary}
        Headline selection:{self.NEWLINE}{self.NEWLINE.join(sample_headlines)}"""
        return topic_text

    def _format_topic_selection_overview(
        self, topics: List[Topic], selected_ids: List[str]
    ) -> str:
        """Format overview of all topics, marking selected ones with checkmark.

        Args:
            topics: List of (id, title) tuples from get_most_recent_topics
            selected_ids: List of topic IDs that were selected

        Returns:
            Formatted string with overview of all topics
        """
        formatted_topics = []
        for i, topic in enumerate(topics, 1):
            checkmark = "✓" if topic.id in selected_ids else " "
            formatted_topics.append(f"{topic.id}: [{checkmark}] {topic.title}")

        return "\n".join(formatted_topics)

    def get_user_review(self, result: TaskResult) -> str:
        """Custom user review logic for topic selection.

        Args:
            result: Task execution result

        Returns:
            str: "accepted", "rejected", or "re-run"
        """
        typer.echo(f"\nReview output for task: {self.name}")
        typer.echo("\nMetrics:")
        for key, value in result.metrics.items():
            typer.echo(f"  {key}: {value}")
        typer.echo(f"\nWarnings: {result.warning or 'None'}")

        while True:
            typer.echo("\nOptions:")
            typer.echo("1. Approve current selection")
            typer.echo("2. Re-run with different parameters")
            typer.echo("3. Manually select topics")
            typer.echo("4. Reject")

            choice = input("\nSelect option (1-4): ").strip()

            if choice == "1":
                return "accepted"
            elif choice == "2":
                updated_params = self._get_updated_parameters()
                self.context.params.update(updated_params)
                return "re-run"
            elif choice == "3":
                # Manually select topics and store briefing
                selected_ids = self._get_manual_topic_selection()
                briefing_id = store_briefing_with_topics(self.context.db, selected_ids)
                _, topics = get_topics_for_briefing(self.context.db, briefing_id)

                # Log selection overview
                self.logger.info(
                    f"Created new briefing {briefing_id} with {len(selected_ids)} manually selected topics."
                )

                # Update result data
                result.data["briefing_id"] = briefing_id
                result.data["selected_topics"] = selected_ids
                result.data["selection_overview"] = (
                    self._format_topic_selection_overview(
                        [Topic(*topic) for topic in topics], selected_ids
                    )
                )
                return "accepted"
            elif choice == "4":
                return "rejected"
            else:
                typer.echo("Invalid choice, please try again")

    def _get_manual_topic_selection(self) -> List[str]:
        """Get manual topic selection from user."""
        topics = get_most_recent_topics(self.context.db)
        topics = [Topic(*topic) for topic in topics]

        typer.echo("\nAvailable topics:")
        for i, topic in enumerate(topics, 1):
            typer.echo(f"{i}. [{topic.id}] {topic.title}")

        typer.echo("\nEnter topic index numbers to select (comma-separated):")
        while True:
            try:
                selections = input().strip()
                indices = [int(x.strip()) - 1 for x in selections.split(",")]
                selected_topics = [topics[i].id for i in indices]
                return selected_topics
            except (ValueError, IndexError):
                typer.echo("Invalid input, please try again")
