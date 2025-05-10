from typing import Any, List, Optional

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from .base import LLM


class OpenAIModel(LLM):
    """OpenAI LLM interface."""

    def __init__(self, api_key: Optional[str] = None, **kwargs: Any) -> None:
        super().__init__("openai", None)

        # Use api_key from kwargs if the explicit parameter is None
        if api_key is None and "api_key" in kwargs:
            api_key = kwargs.pop("api_key")

        # Always ensure api_key is removed from kwargs
        kwargs.pop("api_key", None)

        # Pass the API key to ChatOpenAI but don't store it
        self.model = ChatOpenAI(api_key=api_key, **kwargs)

        # Store kwargs
        self.config = kwargs

    def __str__(self) -> str:
        safe_config = self.config.copy()
        if "api_key" in safe_config:
            safe_config.pop("api_key")

        config_str = ", ".join(f"{k}={v}" for k, v in safe_config.items())
        return f"OpenAIModel(base_url={self.base_url}, {config_str})"

    def __repr__(self) -> str:
        # Use the same implementation as __str__ to avoid leaking API key in debugging
        return self.__str__()

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
