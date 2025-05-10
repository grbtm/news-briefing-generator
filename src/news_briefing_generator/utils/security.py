import os
from typing import Optional

from news_briefing_generator.config.config_manager import ConfigManager


def get_openai_api_key(config_manager: Optional[ConfigManager] = None) -> str:
    """Retrieve OpenAI API key from environment variable or config.

    Args:
        config_manager: Optional config manager to retrieve key from settings

    Returns:
        API key as string

    Raises:
        ValueError: If no API key is found
    """
    api_key = os.getenv("NBG_OPENAI_API_KEY")
    if not api_key and config_manager:
        api_key = config_manager.get_param("openai.api_key", default="").value
    if not api_key:
        raise ValueError("OpenAI API key not found in environment or configuration")
    return api_key
