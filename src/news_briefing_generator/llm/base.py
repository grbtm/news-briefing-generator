from abc import abstractmethod
from typing import Any, Optional

from langchain_core.messages.base import BaseMessage


class LLM:
    """Base LLM interface."""

    def __init__(self, type: str, base_url: Optional[str] = None) -> None:
        self._type = type
        self.base_url = base_url

    def __str__(self) -> str:
        return f"LLM(type={self._type}, base_url={self.base_url})"

    @abstractmethod
    def generate(self, prompts: Any) -> BaseMessage:
        pass

    @abstractmethod
    async def generate_async(self, prompts: Any) -> BaseMessage:
        pass

    @abstractmethod
    def prepare_prompts(self, human: str, system: str) -> Any:
        pass
