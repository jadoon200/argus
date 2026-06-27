"""Dense embedding backend — free, local sentence-transformers.

Lazily loads the model (a few hundred MB on first use) so importing this module is
cheap and the test suite never pulls a model. Embeddings are L2-normalised, so cosine
similarity is a plain dot product downstream.
"""

from typing import cast

import numpy as np
from numpy.typing import NDArray

from argus.config import get_settings
from argus.logging import get_logger

log = get_logger(__name__)

Vector = NDArray[np.float32]

_model: object | None = None


def _get_model() -> object:
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer

        name = get_settings().embedding_model
        log.info("loading_embedder", model=name)
        _model = SentenceTransformer(name)
    return _model


def embed_texts(texts: list[str]) -> Vector:
    """Encode texts into an (n, d) array of L2-normalised float32 vectors."""
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    model = _get_model()
    vecs = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)  # type: ignore[attr-defined]
    return cast(Vector, np.asarray(vecs, dtype=np.float32))


def embed_text(text: str) -> Vector:
    """Encode a single text into a 1-D normalised vector."""
    return cast(Vector, embed_texts([text])[0])
