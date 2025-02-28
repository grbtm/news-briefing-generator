EXTRACT_ARTICLE_SYSTEM = """You are a professional journalist from a renowned newspaper."""

EXTRACT_ARTICLE_USER = f"""Review the following scraped website text and 
extract the actual article text. Respond directly with the extracted article, 
without any introduction or meta-commentary. This is the text: {{text}}"""