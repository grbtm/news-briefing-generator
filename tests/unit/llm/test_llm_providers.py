import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from news_briefing_generator.llm.base import LLM
from news_briefing_generator.llm.ollama import OllamaModel
from news_briefing_generator.llm.openai import OpenAIModel


@pytest.fixture
def mock_chat_ollama():
    with patch("news_briefing_generator.llm.ollama.ChatOllama") as mock:
        # Configure the mock to return a predetermined response
        instance = mock.return_value
        instance.invoke.return_value = AIMessage(content="Mocked Ollama response")
        instance.ainvoke = AsyncMock(
            return_value=AIMessage(content="Mocked Ollama response")
        )
        yield mock


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


def test_ollama_model_instantiation(mock_chat_ollama):
    """Test OllamaModel can be instantiated with correct parameters."""
    model = OllamaModel(
        base_url="http://test:11434", model="llama3", temperature=0.5, num_ctx=1000
    )

    # Verify OllamaModel is properly initialized
    assert model._type == "ollama"
    assert model.base_url == "http://test:11434"
    assert isinstance(model, LLM)

    # Verify ChatOllama was instantiated with correct parameters
    mock_chat_ollama.assert_called_once()
    args, kwargs = mock_chat_ollama.call_args
    assert kwargs["base_url"] == "http://test:11434"
    assert kwargs["model"] == "llama3"
    assert kwargs["temperature"] == 0.5


def test_openai_model_instantiation(mock_chat_openai):
    """Test OpenAIModel can be instantiated with correct parameters."""
    model = OpenAIModel(
        api_key="test-key", model="gpt-3.5-turbo", temperature=0.7, max_tokens=500
    )

    # Verify OpenAIModel is properly initialized
    assert model._type == "openai"
    assert isinstance(model, LLM)

    # Verify ChatOpenAI was instantiated with correct parameters
    mock_chat_openai.assert_called_once()
    args, kwargs = mock_chat_openai.call_args
    assert kwargs["api_key"] == "test-key"
    assert kwargs["model"] == "gpt-3.5-turbo"
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 500


def test_ollama_generate(mock_chat_ollama):
    """Test OllamaModel's generate method."""
    model = OllamaModel(base_url="http://test:11434", model="llama3")

    # Create test prompts
    prompts = [SystemMessage(content="test system"), HumanMessage(content="test human")]

    # Test generate method
    response = model.generate(prompts)

    # Verify response and that the mock was called correctly
    assert response.content == "Mocked Ollama response"
    model.model.invoke.assert_called_once_with(prompts)


def test_openai_generate(mock_chat_openai):
    """Test OpenAIModel's generate method."""
    model = OpenAIModel(api_key="test-key", model="gpt-3.5-turbo")

    # Create test prompts
    prompts = [SystemMessage(content="test system"), HumanMessage(content="test human")]

    # Test generate method
    response = model.generate(prompts)

    # Verify response and that the mock was called correctly
    assert response.content == "Mocked OpenAI response"
    model.model.invoke.assert_called_once_with(prompts)


@pytest.mark.asyncio
async def test_ollama_generate_async(mock_chat_ollama):
    """Test OllamaModel's generate_async method."""
    model = OllamaModel(base_url="http://test:11434", model="llama3")

    # Create test prompts
    prompts = [SystemMessage(content="test system"), HumanMessage(content="test human")]

    # Test generate_async method
    response = await model.generate_async(prompts)

    # Verify response and that the mock was called correctly
    assert response.content == "Mocked Ollama response"
    model.model.ainvoke.assert_called_once_with(prompts)


@pytest.mark.asyncio
async def test_openai_generate_async(mock_chat_openai):
    """Test OpenAIModel's generate_async method."""
    model = OpenAIModel(api_key="test-key", model="gpt-3.5-turbo")

    # Create test prompts
    prompts = [SystemMessage(content="test system"), HumanMessage(content="test human")]

    # Test generate_async method
    response = await model.generate_async(prompts)

    # Verify response and that the mock was called correctly
    assert response.content == "Mocked OpenAI response"
    model.model.ainvoke.assert_called_once_with(prompts)


def test_prepare_prompts():
    """Test that prepare_prompts formats messages correctly."""
    # Both Ollama and OpenAI should use the same format
    human_msg = "This is a test question"
    system_msg = "You are a helpful assistant"

    # Test with OllamaModel (could use either since they share the same implementation)
    messages = OllamaModel.prepare_prompts(human_msg, system_msg)

    assert len(messages) == 2
    assert isinstance(messages[0], SystemMessage)
    assert messages[0].content == system_msg
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == human_msg

    # Test with empty inputs
    with pytest.raises(ValueError):
        OllamaModel.prepare_prompts("", system_msg)

    with pytest.raises(ValueError):
        OllamaModel.prepare_prompts(human_msg, "")
