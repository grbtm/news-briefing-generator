from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages.ai import AIMessage
from pytest import LogCaptureFixture

from news_briefing_generator.tasks.topic_summarization import (
    TopicData,
    TopicSummarizationTask,
)


@pytest.mark.asyncio
async def test_error_pattern_detection(caplog: LogCaptureFixture) -> None:
    """Test that error pattern in topic summary generates warning log."""
    # Setup
    mock_context = MagicMock()
    mock_context.db = MagicMock()
    mock_context.db.update_many = MagicMock()

    # Mock the logger_manager in the context
    mock_logger = MagicMock()
    mock_context.logger_manager = MagicMock()
    mock_context.logger_manager.get_logger.return_value = mock_logger

    # Create the task with our mocked context
    task = TopicSummarizationTask(mock_context)

    # Create test data
    test_topic_data = TopicData(
        topic_id="test_id",
        topic_title="Test Topic",
        summaries_text="Test summaries",
    )

    # Mock AIMessage with error pattern
    error_message = AIMessage(
        content="<ERROR> Cannot determine coherent topic. <ERROR>"
    )

    # Call the method
    task._process_results([test_topic_data], [error_message])

    # Assert warnings were logged to the mocked logger
    mock_logger.warning.assert_any_call(
        "Topic test_id (Test Topic) has an incoherent content error"
    )
    mock_logger.warning.assert_any_call(
        "1 out of 1 topics have incoherent content errors"
    )

    # Verify database was updated despite the error
    mock_context.db.update_many.assert_called_once()
