from datetime import datetime
from typing import Optional

from jinja2 import Template

from news_briefing_generator.model.task.base import Task, TaskContext
from news_briefing_generator.model.task.result import NO_DATA_WARNING, TaskResult
from news_briefing_generator.utils.database_ops import get_topics_for_briefing
from news_briefing_generator.utils.datetime_ops import (
    get_utc_now_formatted,
    get_utc_now_simple,
)


class BriefingHtmlGenerationTask(Task):
    """Implementation of rendering task.

    Renders the HTML briefing from topics and their summaries, including
    lists of related articles with highlighting for those used in summaries.
    """

    DEFAULT_OUTPUT_PATH = f"briefings/{get_utc_now_simple()}.html"

    def __init__(self, context: TaskContext):
        super().__init__(context)

    @property
    def name(self) -> str:
        return "briefing_html_generation"

    @property
    def requires_llm(self) -> bool:
        return False

    async def execute(self) -> TaskResult:
        """Execute rendering task."""
        try:
            output_path = self.get_parameter(
                "output_path", default=self.DEFAULT_OUTPUT_PATH
            )
            briefing_id = self.get_parameter("briefing_id", default=None)
            template_string = self.get_parameter("template_string", default=None)

            return await self._run_rendering(
                output_path=output_path,
                briefing_id=briefing_id,
                template_string=template_string,
            )
        except Exception as e:
            self.logger.error(f"Rendering failed: {str(e)}", exc_info=True)
            return TaskResult(
                task_name=self.name,
                success=False,
                created_at=get_utc_now_formatted(),
                error=str(e),
                metrics={"topics_rendered": 0},
            )

    async def _run_rendering(
        self,
        output_path: str,
        briefing_id: Optional[str] = None,
        template_string: Optional[str] = None,
    ) -> TaskResult:
        """Render HTML briefing from topics and summaries."""
        db = self.context.db

        # Get briefing and topics
        briefing_id, topics = get_topics_for_briefing(db, briefing_id)
        if not topics:
            warning_msg = f"{NO_DATA_WARNING}No topics found for briefing {briefing_id}"
            self.logger.warning(warning_msg)
            return TaskResult(
                task_name=self.name,
                success=True,
                warning=warning_msg,
                created_at=get_utc_now_formatted(),
                data={"html": "<p>No topics found for briefing.</p>"},
                metrics={"topics_rendered": 0},
            )

        # Format date for display
        try:
            date_obj = datetime.strptime(briefing_id, "%Y-%m-%d-%H-%M")
            formatted_date = date_obj.strftime("%B %d, %Y %H:%M")
        except ValueError:
            formatted_date = briefing_id
            self.logger.warning(f"Could not parse briefing ID as date: {briefing_id}")

        # Fetch related articles for each topic
        topics_with_articles = []
        skipped_topics = 0

        for topic in topics:
            topic_id = topic[0]
            topic_summary = topic[3] if len(topic) > 2 else "No summary available."

            # Skip topics with no summary (when no fetched article content was found)
            if not topic_summary:
                self.logger.warning(f"Skipping topic {topic_id} with no summary")
                skipped_topics += 1
                continue

            # Skip topics with error summaries (when no coherent topic was determined)
            if "<ERROR> Cannot determine coherent topic. <ERROR>" in topic_summary:
                self.logger.warning(
                    f"Skipping topic {topic_id} due to incoherent content error"
                )
                skipped_topics += 1
                continue

            articles = db.run_query(
                f"""
                SELECT f.source, f.title, tf.used_for_summarization, f.link
                FROM feeds f
                JOIN topic_feeds tf ON f.id = tf.feed_id
                WHERE tf.topic_id = '{topic_id}'
                ORDER BY f.published DESC
            """
            )
            topics_with_articles.append(
                {
                    "title": topic[1],
                    "summary": topic[3] if len(topic) > 2 else "No summary available.",
                    "articles": [
                        {
                            "source": article[0],
                            "title": article[1],
                            "used_for_summarization": bool(article[2]),
                            "link": article[3],
                        }
                        for article in articles
                    ],
                }
            )

        # Add warning if topics were skipped
        if skipped_topics > 0:
            warning_msg = f"Skipped {skipped_topics} topic(s) without summary"
            self.logger.warning(warning_msg)

        # Prepare template data
        template_data = {
            "briefing_id": briefing_id,
            "date": formatted_date,
            "topics": topics_with_articles,
        }

        # Render HTML
        template = Template(template_string or self._get_default_template())
        html = template.render(**template_data)

        # Save to file
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(html)
            self.logger.info("=" * 50)
            self.logger.info(f"Briefing HTML saved to {output_path}")
            self.logger.info("=" * 50)
        except IOError as e:
            self.logger.error(f"Failed to save HTML to {output_path}: {str(e)}")
            raise

        return TaskResult(
            task_name=self.name,
            success=True,
            created_at=get_utc_now_formatted(),
            metrics={"topics_rendered": len(topics), "topics_skipped": skipped_topics},
            data={
                "briefing_id": briefing_id,
                "output_path": output_path,
                "topics_count": len(topics),
            },
        )

    def _get_default_template(self) -> str:
        """Get default HTML template."""
        return """<!DOCTYPE html>
        <html>
        <head>
            <title>News Briefing {{ date }}</title>
            <style>
                body { 
                    max-width: 800px; 
                    margin: 0 auto; 
                    padding: 20px;
                    font-family: Bitter,Georgia,Cambria,Times New Roman,Times,serif;
                    background: #ffffff;
                    color: #333;
                    font-size: 18px;
                    line-height: 1.6;
                    font-weight: 400;
                }
                h1 { color: #444; }
                h2 { 
                    color: #444;
                    width: 700px;
                    border-bottom: 1px solid #ddd;
                    padding-bottom: 5px;
                    margin: 20px 0;
                }
                h3 {
                    color: #666;
                    font-size: 18px;
                    margin: 20px 0 10px 0;
                }
                .summary {
                    font-size: 22px;
                    line-height: 1.6;
                    color: #222;
                    padding: 20px;
                    border-radius: 5px;
                    width: 100%;
                    text-align: left;
                    hyphens: auto;
                    margin-bottom: 20px;
                }
                .warning {
                    background: #fff3cd;
                    color: #856404;
                    padding: 15px;
                    border: 1px solid #ffeeba;
                    border-radius: 5px;
                    margin: 20px 0;
                    line-height: 1.4;
                    width: 100%;
                }
                .topic {
                    margin-top: 50px;
                    margin-bottom: 40px;
                }
                .articles {
                    list-style-type: disc;
                    margin-left: 20px;
                }
                .article {
                    margin: 8px 0;
                    font-size: 16px;
                }
                .tag {
                    background: #e1e1e1;
                    border-radius: 12px;
                    padding: 2px 8px;
                    font-size: 0.8em;
                    color: #666;
                }
                a {
                    color: #0066cc;
                    text-decoration: none;
                }
                a:hover {
                    text-decoration: underline;
                }
            </style>
        </head>
        <body>
            <h1>News Briefing</h1>
            <h4>Briefing ID: {{ briefing_id }}</h4>
            <div class="warning">
                Warning: This briefing was generated using artificial intelligence and can contain mistakes. Please verify important information from primary sources.
            </div>
            <p><em>Generated on {{ date }} UTC</em></p>
            
            {% for topic in topics %}
            <div class="topic">
                <h2>{{ topic.title }}</h2>
                <div class="summary">
                    {{ topic.summary }}
                </div>
                <h3>Related Articles:</h3>
                <ul class="articles">
                    {% for article in topic.articles %}
                    <li class="article">
                        {% if article.used_for_summarization %}
                        <span class="tag">Used in Summary</span>
                        {% endif %}
                        {{ article.source }}: <a href="{{ article.link }}">{{ article.title }}</a>
                    </li>
                    {% endfor %}
                </ul>
            </div>
            {% endfor %}
        </body>
        </html>
        """
