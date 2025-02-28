import numpy as np
from langchain_huggingface import HuggingFaceEmbeddings


class HFEmbeddings:
    """HuggingFace Embeddings interface."""

    def __init__(self, **kwargs):
        self.model = HuggingFaceEmbeddings(**kwargs)

    def embed(self, docs: list[str]) -> list[np.ndarray]:
        embeddings = self.model.embed_documents(docs)  # list[list[float]]
        embeddings = [np.array(lst) for lst in embeddings]
        return embeddings
