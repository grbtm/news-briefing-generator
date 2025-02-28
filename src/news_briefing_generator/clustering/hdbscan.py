from typing import List

import hdbscan
import numpy as np


class HDBSCAN:
    def __init__(
        self,
        min_cluster_size: int = 5,
        min_samples: int = 5,
        cluster_selection_epsilon: float = 0.3,
    ) -> None:
        self.min_cluster_size = min_cluster_size
        self.min_samples = min_samples
        self.cluster_selection_epsilon = cluster_selection_epsilon
        self.model = hdbscan.HDBSCAN(
            min_cluster_size=self.min_cluster_size, min_samples=self.min_samples
        )

    def cluster(self, embeddings: List[np.ndarray]) -> List[str]:
        """Run HDBSCAN clustering on the input embeddings and return the cluster labels."""
        return self.model.fit(embeddings).labels_.astype(str).tolist()
