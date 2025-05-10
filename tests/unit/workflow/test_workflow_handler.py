from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from news_briefing_generator.llm.ollama import OllamaModel
from news_briefing_generator.llm.openai import OpenAIModel
from news_briefing_generator.model.task.config import TaskConfig
from news_briefing_generator.workflow.workflow_handler import WorkflowHandler


@pytest.fixture
def mock_chat_ollama():
    """Mock Ollama chat functionality."""
    with patch("news_briefing_generator.llm.ollama.ChatOllama") as mock_class:
        mock_instance = mock_class.return_value
        mock_instance.invoke.return_value = AIMessage(content="Mocked Ollama response")
        mock_instance.ainvoke.return_value = AIMessage(content="Mocked Ollama response")
        yield mock_class


@pytest.fixture
def mock_chat_openai():
    with patch("news_briefing_generator.llm.openai.ChatOpenAI") as mock:
        # Configure the mock to return a predetermined response
        instance = mock.return_value
        instance.invoke.return_value = AIMessage(content="Mocked OpenAI response")
        instance.ainvoke = AsyncMock(
            return_value=AIMessage(content="Mocked OpenAI response")
        )
        yield mock


def test_task_level_llm_config_precedence(mock_chat_ollama, mock_chat_openai):
    """Test that task-level LLM configurations override global settings."""
    # Create task configs with custom LLM settings
    task_config_ollama = TaskConfig(
        name="test_task",
        task_type="TestTask",
        depends_on=[],
        llm_config={"type": "ollama", "model": "custom-model", "temperature": 0.8},
    )

    task_config_openai = TaskConfig(
        name="test_task",
        task_type="TestTask",
        depends_on=[],
        llm_config={"type": "openai", "model": "gpt-4.1", "temperature": 0.8},
    )

    # Create handler with default LLMs
    default_ollama = OllamaModel(base_url="http://default:11434", model="default-model")
    default_openai = OpenAIModel(api_key="default-key", model="gpt-3.5-turbo")

    # Mock the config manager
    mock_conf = MagicMock()

    # Test with Ollama default, Ollama task-specific
    handler = WorkflowHandler(
        db=MagicMock(),
        default_llm=default_ollama,
        conf=mock_conf,
        logger_manager=MagicMock(),
    )
    task_llm = handler._get_task_llm(task_config_ollama)
    assert isinstance(task_llm, OllamaModel)
    assert task_llm.config["model"] == "custom-model"
    assert task_llm.config["temperature"] == 0.8
    assert task_llm.base_url == "http://default:11434"  # Should inherit from default

    # Test with OpenAI default, OpenAI task-specific
    # Mock the get_openai_api_key function to return a test key
    with patch(
        "news_briefing_generator.workflow.workflow_handler.get_openai_api_key",
        return_value="test-api-key",
    ) as mock_get_key:
        handler = WorkflowHandler(
            db=MagicMock(),
            default_llm=default_openai,
            conf=mock_conf,
            logger_manager=MagicMock(),
        )
        task_llm = handler._get_task_llm(task_config_openai)

        # Verify the API key was fetched using the utility function
        mock_get_key.assert_called_once_with(mock_conf)

        assert isinstance(task_llm, OpenAIModel)
        assert task_llm.config["model"] == "gpt-4.1"
        assert task_llm.config["temperature"] == 0.8

        # Verify the model was created with the right API key
        mock_chat_openai.assert_called_with(
            api_key="test-api-key", model="gpt-4.1", temperature=0.8
        )


def test_get_task_llm_defaults_and_errors():
    """Test _get_task_llm behavior with no config or invalid config."""
    # Setup
    default_llm = OllamaModel(base_url="http://default:11434", model="default-model")
    mock_conf = MagicMock()
    mock_logger_manager = MagicMock()

    handler = WorkflowHandler(
        db=MagicMock(),
        default_llm=default_llm,
        conf=mock_conf,
        logger_manager=mock_logger_manager,
    )

    # Case 1: No LLM config specified - should return default LLM
    task_config_no_llm = TaskConfig(
        name="test_task_no_llm",
        task_type="TestTask",
        depends_on=[],
        llm_config=None,
    )
    result_llm = handler._get_task_llm(task_config_no_llm)
    assert result_llm is default_llm  # Should be the exact same instance

    # Case 2: Unknown LLM type - should return default LLM and log warning
    task_config_unknown = TaskConfig(
        name="test_task_unknown",
        task_type="TestTask",
        depends_on=[],
        llm_config={"type": "unknown_llm_type"},
    )
    result_llm = handler._get_task_llm(task_config_unknown)
    assert result_llm is default_llm  # Should be the exact same instance

    # Should have logged a warning
    handler.logger.warning.assert_called_once_with(
        f"Unknown LLM type unknown_llm_type for task test_task_unknown, "
        "using default LLM"
    )

    # Case 3: OpenAI LLM type - should call get_openai_api_key
    with patch(
        "news_briefing_generator.workflow.workflow_handler.get_openai_api_key",
        return_value="test-api-key",
    ) as mock_get_key:
        with patch(
            "news_briefing_generator.workflow.workflow_handler.OpenAIModel"
        ) as mock_openai_model:
            task_config_openai = TaskConfig(
                name="test_task_openai",
                task_type="TestTask",
                depends_on=[],
                llm_config={"type": "openai", "model": "gpt-4.1", "temperature": 0.7},
            )
            handler._get_task_llm(task_config_openai)

            # Verify API key was fetched
            mock_get_key.assert_called_once_with(mock_conf)

            # Verify OpenAIModel was created with right params
            mock_openai_model.assert_called_once_with(
                api_key="test-api-key", model="gpt-4.1", temperature=0.7
            )
