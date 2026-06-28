"""Narrative clustering — group documents that push the same framing/claim.

Distinct from event dedup (`nlp/events.py`): events are the *same happening* (tight cosine
+ a time window); a narrative is a shared *message* that can span events and time, so we
cluster on embedding similarity alone at a looser threshold and keep only clusters large
enough to be a narrative (not a one-off).
"""

import numpy as np

from argus.nlp.embed import Vector
from argus.nlp.events import _normalize


def cluster_narratives(embeddings: Vector, threshold: float, min_size: int) -> list[list[int]]:
    """Greedy cosine clustering with no time gate; returns clusters of >= min_size."""
    centroids: list[Vector] = []
    members: list[list[int]] = []
    for i in range(len(embeddings)):
        vec = _normalize(embeddings[i])
        best, best_sim = -1, threshold
        for c, centroid in enumerate(centroids):
            sim = float(np.dot(vec, centroid))
            if sim >= best_sim:
                best, best_sim = c, sim
        if best >= 0:
            members[best].append(i)
            k = len(members[best])
            centroids[best] = _normalize(centroids[best] * (k - 1) / k + vec / k)
        else:
            centroids.append(vec)
            members.append([i])
    return [m for m in members if len(m) >= min_size]
