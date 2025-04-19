from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .base import LLM


class OpenAIModel(LLM):
    """OpenAI LLM interface."""

    def __init__(self, api_key: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__("openai", None)  # OpenAI doesn't use base_url like Ollama
        self.model = ChatOpenAI(api_key=api_key, **kwargs)
        self.config = kwargs

    def __str__(self) -> str:
        # Exclude API key from string representation for security
        safe_config = {k: v for k, v in self.config.items() if k != "api_key"}
        config_str = ", ".join(f"{k}={v}" for k, v in safe_config.items())
        return f"OpenAIModel({config_str})"

    def generate(self, prompts: Any) -> BaseMessage:
        return self.model.invoke(prompts)

    async def generate_async(self, prompts: Any) -> BaseMessage:
        response = await self.model.ainvoke(prompts)
        return response

    @staticmethod
    def prepare_prompts(human: str, system: str) -> List[BaseMessage]:
        """Prepare prompt messages for LLM generation.

        Args:
            human (str): The human/user message content
            system (str): The system instruction content

        Returns:
            List[BaseMessage]: List of messages in correct order for LLM

        Raises:
            ValueError: If either input string is empty
        """
        if not human or not system:
            raise ValueError("Both human and system prompts must not be empty")

        return [SystemMessage(content=system), HumanMessage(content=human)]
