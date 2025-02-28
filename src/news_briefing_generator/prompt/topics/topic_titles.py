

TOPIC_TITLE_GENERATION_SYSTEM = f"""
                        You're an expert journalist. You're helping me write short but compelling 
                        topic headlines summarizing a collection of news articles."""
TOPIC_TITLE_GENERATION_USER = f"""
                        Using the following article headlines/abstracts, write an one sentence title that 
                        summarizes them.
                        Respond directly with the topic title (after the 'TOPIC TITLE:' statement below)
                        without any introduction or meta-commentary and offer exactly one topic title.
                        Go for a title that is informative, sticking to the facts, concise and to the point 
                        - avoid tabloid-style sensationalism.
                        \n\nHEADLINES:
                        \n\n{{headlines}}
                        \n\nTOPIC TITLE (REMEMBER TO RESPOND DIRECTLY WITH EXACTLY ONE TOPIC HEADLINE):"""