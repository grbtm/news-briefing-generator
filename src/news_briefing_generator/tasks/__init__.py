from typing import Dict, Type

from news_briefing_generator.model.task.base import Task
from news_briefing_generator.tasks.article_summarization import ArticleSummarizationTask
from news_briefing_generator.tasks.briefing_html_generation import (
    BriefingHtmlGenerationTask,
)
from news_briefing_generator.tasks.content_fetching import ContentFetchingTask
from news_briefing_generator.tasks.feed_collection import FeedCollectionTask
from news_briefing_generator.tasks.feed_hdbscan_clustering import (
    FeedHdbscanClusteringTask,
)
from news_briefing_generator.tasks.topic_selection import TopicSelectionTask
from news_briefing_generator.tasks.topic_summarization import TopicSummarizationTask
from news_briefing_generator.tasks.topic_title_generation import (
    TopicTitleGenerationTask,
)

TASK_REGISTRY: Dict[str, Type[Task]] = {
    "TopicSelectionTask": TopicSelectionTask,
    "FeedCollectionTask": FeedCollectionTask,
    "FeedHdbscanClusteringTask": FeedHdbscanClusteringTask,
    "ContentFetchingTask": ContentFetchingTask,
    "TopicTitleGenerationTask": TopicTitleGenerationTask,
    "ArticleSummarizationTask": ArticleSummarizationTask,
    "TopicSummarizationTask": TopicSummarizationTask,
    "BriefingHtmlGenerationTask": BriefingHtmlGenerationTask,
}
