import re


def remove_outer_quotes(text: str) -> str:
    """Remove outer quotes from a string if present.

    Args:
        text (str): Input text that may have outer quotes

    Returns:
        str: Text with outer quotes removed if present
    """
    if text.startswith('"') and text.endswith('"'):
        return text[1:-1]
    if text.startswith("'") and text.endswith("'"):
        return text[1:-1]
    return text


def remove_think_tags(text: str) -> str:
    """Remove content between <think></think> tags from LLM output.

    Args:
        text (str): Input text that may contain think tags from LLM reasoning

    Returns:
        str: Text with think tag content removed
    """
    pattern = r"<think>.*?</think>"
    return re.sub(pattern, "", text, flags=re.DOTALL).strip()


def preprocess_llm_output(text: str) -> str:
    """Preprocess LLM output by removing think tags and outer quotes.

    Args:
        text (str): Input text from LLM output

    Returns:
        str: Preprocessed text
    """
    text = remove_think_tags(text)
    text = remove_outer_quotes(text)
    return text
