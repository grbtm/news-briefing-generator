from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from .base import LLM


class OllamaModel(LLM):
    """Ollama LLM interface."""

    def __init__(self, base_url: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__("ollama", base_url)
        self.model = ChatOllama(base_url=base_url, **kwargs)
        self.config = kwargs

    def __str__(self) -> str:
        config_str = ", ".join(f"{k}={v}" for k, v in self.config.items())
        return f"OllamaModel(base_url={self.base_url}, {config_str})"

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
