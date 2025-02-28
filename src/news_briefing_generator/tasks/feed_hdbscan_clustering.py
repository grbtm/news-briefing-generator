import pandas as pd

from news_briefing_generator.clustering.hdbscan import HDBSCAN
from news_briefing_generator.db.schema import (
    FEED_COLUMNS,
    TABLE_FEEDS,
    TABLE_TOPIC_FEEDS,
    TABLE_TOPICS,
)
from news_briefing_generator.db.sqlite import DatabaseManager
from news_briefing_generator.embedding.huggingface import HFEmbeddings
from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.utils.datetime_ops import (
    get_utc_now_formatted,
    get_utc_now_simple,
)


class FeedHdbscanClusteringTask(Task):
    """Clusters RSS/Atom feed entries using HDBSCAN into topics.

    This task implements a complete clustering pipeline that:
    1. Retrieves recent feed entries from database
    2. Creates embeddings from headlines and summaries
    3. Performs HDBSCAN clustering on the embeddings
    4. Stores cluster assignments as topics in the database

    Attributes:
        DEFAULT_TIME_WINDOW: Default time window for feed selection in hours
        DEFAULT_EMBEDDING_MODEL: Default model for text embeddings
        DEFAULT_HDBSCAN_MIN_SAMPLES: Default min_samples for HDBSCAN
        DEFAULT_HDBSCAN_MIN_CLUSTER_SIZE: Default min_cluster_size for HDBSCAN
        DEFAULT_HDBSCAN_CLUSTER_SELECTION_EPSILON: Default cluster_selection_epsilon for HDBSCAN
    """

    DEFAULT_TIME_WINDOW: int = 24
    DEFAULT_EMBEDDING_MODEL: str = "sentence-transformers/all-mpnet-base-v2"
    DEFAULT_HDBSCAN_MIN_SAMPLES: int = 2
    DEFAULT_HDBSCAN_MIN_CLUSTER_SIZE: int = 2
    DEFAULT_HDBSCAN_CLUSTER_SELECTION_EPSILON: float = 0.1

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "feed_hdbscan_clustering"

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Execute clustering task with context.

        Returns:
            TaskResult containing:
                - data: Dict with clusters and entries
                - metrics: Dict with clustering statistics
        """
        try:
            # Get configuration parameters
            time_window = self.get_parameter(
                "time_window_hours", default=self.DEFAULT_TIME_WINDOW
            )
            embedding_model = self.get_parameter(
                "embedding_model", default=self.DEFAULT_EMBEDDING_MODEL
            )

            # Execute core clustering logic
            return await self._run_clustering(
                db=self.context.db,
                time_window=time_window,
                embedding_model=embedding_model,
            )

        except Exception as e:
            self.logger.error(f"Clustering failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"total_entries": 0, "clusters_created": 0},
            )

    async def _run_clustering(
        self, db: DatabaseManager, time_window: int, embedding_model: str
    ) -> TaskResult:
        """Run core clustering logic.

        Args:
            db: Database connection for fetching feeds
            time_window: Hours of feed entries to process
            embedding_model: Name of embedding model to use

        Returns:
            TaskResult with clustering results and metrics
        """
        # Read recent feeds from database
        data = db.select(
            table=TABLE_FEEDS,
            columns=FEED_COLUMNS,
            condition=f"published >= datetime('now', '-{time_window} hours')",
        )
        df = pd.DataFrame(data, columns=FEED_COLUMNS)
        self.logger.info(
            f"{len(df)} feed entries found in the last {time_window} hours"
        )

        if len(df) == 0:
            warning_msg = f"{NO_DATA_WARNING}No feed entries found in the last {time_window} hours"
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                metrics={"total_entries": 0, "clusters_created": 0},
            )

        # Create embeddings
        headlines_series = df.apply(
            lambda row: f"{row['source']}: {row['title']}. {row['summary']}", axis=1
        )
        self.logger.info(f"Loading embedding model: {embedding_model}")
        emb_model = HFEmbeddings(model_name=embedding_model)

        self.logger.info("Creating embeddings")
        embeddings = emb_model.embed(docs=headlines_series.tolist())

        # Run clustering
        self.logger.info("Running HDBSCAN clustering")
        min_samples = self.get_parameter(
            "min_samples", default=self.DEFAULT_HDBSCAN_MIN_SAMPLES
        )
        min_cluster_size = self.get_parameter(
            "min_cluster_size", default=self.DEFAULT_HDBSCAN_MIN_CLUSTER_SIZE
        )
        cluster_selection_epsilon = self.get_parameter(
            "cluster_selection_epsilon",
            default=self.DEFAULT_HDBSCAN_CLUSTER_SELECTION_EPSILON,
        )

        hdbscan = HDBSCAN(
            min_samples=min_samples,
            min_cluster_size=min_cluster_size,
            cluster_selection_epsilon=cluster_selection_epsilon,
        )
        clusters = hdbscan.cluster(embeddings=embeddings)

        # Check if clustering failed (all points assigned to noise cluster -1)
        unique_clusters = set(str(c) for c in clusters)
        if unique_clusters == {"-1"}:
            error_msg = (
                "Clustering failed: No valid clusters found. "
                "All entries were classified as noise. "
                "Try adjusting clustering parameters (min_samples, min_cluster_size, "
                "cluster_selection_epsilon) to allow for smaller or more relaxed clusters."
            )
            self.logger.error(error_msg)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=error_msg,
                metrics={
                    "total_entries": len(df),
                    "clusters_created": 0,
                    "clustering_params": {
                        "min_samples": min_samples,
                        "min_cluster_size": min_cluster_size,
                        "cluster_selection_epsilon": cluster_selection_epsilon,
                    },
                },
            )

        # Process results
        df["cluster"] = clusters
        current_time_str = get_utc_now_simple()
        df["cluster"] = df["cluster"].apply(lambda x: f"{current_time_str}-{x}")
        df = df[df.cluster != f"{current_time_str}--1"]  # Drop unclustered entries

        # Store clusters in database
        self._store_clusters(db, df)

        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            metrics={
                "entries_clustered": len(df),
                "clusters_created": df.cluster.nunique(),
            },
        )

    def _store_clusters(self, db: DatabaseManager, df: pd.DataFrame) -> None:
        """Store cluster assignments in database.

        Args:
            db: Database connection
            df: DataFrame with cluster assignments
        """
        for _, row in df.iterrows():
            topic_id = row["cluster"]
            feed_entry_id = row["id"]

            # Check if topic exists
            topic_results = db.select(
                table=TABLE_TOPICS, columns=["id"], condition=f"id = '{topic_id}'"
            )

            if not topic_results:
                # Create new topic
                db.insert(
                    table=TABLE_TOPICS,
                    columns=["id", "generated_at"],
                    values=(topic_id, get_utc_now_formatted()),
                )

            # Link feed to topic
            db.insert(
                table=TABLE_TOPIC_FEEDS,
                columns=["topic_id", "feed_id"],
                values=(topic_id, feed_entry_id),
            )
