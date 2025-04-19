TOPIC_TITLE_GENERATION_SYSTEM = (
    """You're an expert journalist who creates concise, factual topic headlines."""
)

TOPIC_TITLE_GENERATION_USER = """Create one brief headline summarizing these article headlines/abstracts.

Style requirements:
- Use title case (capitalize main words), not ALL CAPS
- Be informative and factual, avoid sensationalism
- Provide only the headline with no explanation or commentary
- Use plain text with no formatting characters (no asterisks, underscores, etc.)

HEADLINES:
{headlines}

HEADLINE:"""
