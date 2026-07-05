"""DISARM influence-operations technique tagging — the symmetric twin of SENTINEL's
ATT&CK mapper.

SENTINEL keys its cyber picture on MITRE ATT&CK; ARGUS keys its *narrative* picture on
**DISARM** (`https://github.com/DISARMFoundation/DISARMframeworks`), the "ATT&CK for
disinformation" adopted by ENISA, the EU External Action Service, EU DisinfoLab and the
Hybrid CoE. Tagging both graphs with technique IDs from parallel matrices is what turns two
tools into one all-source **hybrid-threat** (cyber + cognitive) fusion story — and DISARM
cross-walks to ATT&CK, so a single campaign can carry both.

`DISARM_TECHNIQUES` below is a *curated subset* for demonstration; the IDs/names follow the
DISARM Red Framework and the full generated catalog (or its STIX 2.1 bundle) can be swapped
in wholesale. Mapping is by embedding similarity (same encoder as the corpus, so a narrative
centroid maps directly), with a dependency-free lexical fallback for the no-model path.

**Responsible-use:** this is an advisory HUMAN-REVIEW signal, never an automated verdict that
a narrative *is* an influence operation. News text vs. TTP descriptions is inherently noisy;
a tag says "this framing resembles this technique — an analyst should look", nothing more.
"""

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from argus.nlp.embed import Vector, embed_texts

# The four DISARM phases (mirrors the framework's plan -> prepare -> execute -> assess arc).
PHASES = ("Plan", "Prepare", "Execute", "Assess")


@dataclass(frozen=True)
class DisarmTechnique:
    technique_id: str  # DISARM Red Framework id, e.g. "T0086.002"
    name: str
    phase: str  # one of PHASES
    description: str  # observable signature, written for embedding retrieval

    @property
    def text(self) -> str:
        return f"{self.name}. {self.description}"


@dataclass(frozen=True)
class DisarmMatch:
    technique_id: str
    name: str
    phase: str
    score: float

    def as_dict(self) -> dict[str, object]:
        return {
            "technique_id": self.technique_id,
            "name": self.name,
            "phase": self.phase,
            "score": round(self.score, 3),
        }


# Curated subset of the DISARM Red Framework, chosen for relevance to open-source news
# narratives (the text ARGUS clusters). IDs/names follow the framework; descriptions are
# paraphrased signatures. Not exhaustive — swap in the full catalog for production.
DISARM_TECHNIQUES: list[DisarmTechnique] = [
    DisarmTechnique(
        "T0002",
        "Facilitate State Propaganda",
        "Execute",
        "Amplify content aligned with a state's agenda through official or affiliated outlets.",
    ),
    DisarmTechnique(
        "T0009",
        "Create Fake Experts",
        "Prepare",
        "Fabricate credentialed-seeming voices or analysts to lend false authority to a claim.",
    ),
    DisarmTechnique(
        "T0019",
        "Generate Information Pollution",
        "Execute",
        "Flood the space with low-quality, repetitive or contradictory content to drown out "
        "reliable reporting.",
    ),
    DisarmTechnique(
        "T0022",
        "Leverage Conspiracy Theory Narratives",
        "Execute",
        "Promote conspiratorial framing to explain an event and erode trust in institutions.",
    ),
    DisarmTechnique(
        "T0023",
        "Distort Facts",
        "Execute",
        "Selectively alter, exaggerate or reframe true facts to mislead about an event.",
    ),
    DisarmTechnique(
        "T0039",
        "Bait Influencers",
        "Execute",
        "Induce authentic influencers or outlets to unwittingly amplify the operation's content.",
    ),
    DisarmTechnique(
        "T0044",
        "Seed Distortions",
        "Execute",
        "Introduce distorted or fabricated claims into the information space for others to spread.",
    ),
    DisarmTechnique(
        "T0046",
        "Use Search Engine Optimisation",
        "Prepare",
        "Manipulate search ranking and keywords so the operation's content surfaces first.",
    ),
    DisarmTechnique(
        "T0049",
        "Flood Information Space",
        "Execute",
        "Overwhelm a hashtag, topic or platform with coordinated, high-volume posting "
        "(astroturfing).",
    ),
    DisarmTechnique(
        "T0057",
        "Organise Events",
        "Execute",
        "Stage or promote real or staged events, rallies or protests to generate coverage.",
    ),
    DisarmTechnique(
        "T0068",
        "Respond to Breaking News Event or Active Crisis",
        "Execute",
        "Exploit a breaking crisis to inject framing while facts are still unclear and demand "
        "is high.",
    ),
    DisarmTechnique(
        "T0072",
        "Segment Audiences",
        "Plan",
        "Divide the target population by geography, demographic or grievance to tailor messaging.",
    ),
    DisarmTechnique(
        "T0075",
        "Discredit Credible Sources",
        "Execute",
        "Attack the credibility of legitimate outlets, journalists or fact-checkers.",
    ),
    DisarmTechnique(
        "T0084",
        "Reuse Existing Content",
        "Prepare",
        "Copy, repurpose or lightly edit existing content to scale output or launder provenance.",
    ),
    DisarmTechnique(
        "T0085",
        "Develop Text-Based Content",
        "Prepare",
        "Author articles, posts, op-eds or comments that carry the narrative.",
    ),
    DisarmTechnique(
        "T0086",
        "Develop Image-Based Content",
        "Prepare",
        "Create memes, infographics or images that carry the narrative.",
    ),
    DisarmTechnique(
        "T0086.002",
        "Develop AI-Generated Images (Deepfakes)",
        "Prepare",
        "Use generative models to fabricate photorealistic images in support of the narrative.",
    ),
    DisarmTechnique(
        "T0087",
        "Develop Video-Based Content",
        "Prepare",
        "Produce or manipulate video, including deepfakes, that carries the narrative.",
    ),
    DisarmTechnique(
        "T0088",
        "Develop Audio-Based Content",
        "Prepare",
        "Produce or manipulate audio, including voice cloning, that carries the narrative.",
    ),
    DisarmTechnique(
        "T0097",
        "Create Inauthentic Personas",
        "Prepare",
        "Build fake identities, accounts or pages to carry and amplify content at scale.",
    ),
]

CATALOG_BY_ID: dict[str, DisarmTechnique] = {t.technique_id: t for t in DISARM_TECHNIQUES}

EmbedFn = Callable[[list[str]], NDArray[np.float32]]

_TOKEN = re.compile(r"[a-z]{4,}")


def _normalize_rows(matrix: NDArray[np.floating]) -> NDArray[np.float32]:
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    return np.asarray(matrix / np.maximum(norms, 1e-12), dtype=np.float32)


def _normalize_vec(vec: NDArray[np.floating]) -> NDArray[np.float32]:
    return np.asarray(vec / max(float(np.linalg.norm(vec)), 1e-12), dtype=np.float32)


class DisarmMapper:
    """Retrieve DISARM techniques nearest to a narrative's text or centroid embedding.

    The catalog is embedded once (lazily) with the *same* encoder as the corpus, so a
    narrative centroid — a mean of stored document embeddings — can be mapped directly with
    no re-embedding. Mirrors SENTINEL's `TechniqueMapper` (bi-encoder retrieval).
    """

    def __init__(
        self,
        techniques: Sequence[DisarmTechnique] = DISARM_TECHNIQUES,
        embed: EmbedFn = embed_texts,
    ) -> None:
        if not techniques:
            raise ValueError("DISARM catalog is empty")
        self._techniques = list(techniques)
        self._embed = embed
        self._index: NDArray[np.float32] | None = None

    def _ensure_index(self) -> NDArray[np.float32]:
        if self._index is None:
            vecs = np.asarray(self._embed([t.text for t in self._techniques]), dtype=np.float32)
            self._index = _normalize_rows(vecs)
        return self._index

    def map_vector(self, vec: Vector, top_k: int = 3, threshold: float = 0.28) -> list[DisarmMatch]:
        index = self._ensure_index()
        query = _normalize_vec(vec)
        if query.shape[0] != index.shape[1]:  # dimension mismatch -> can't compare, no tags
            return []
        cosine = np.asarray(index @ query, dtype=np.float64)
        order = np.argsort(cosine)[::-1]
        matches = [
            DisarmMatch(
                self._techniques[i].technique_id,
                self._techniques[i].name,
                self._techniques[i].phase,
                float(cosine[i]),
            )
            for i in order
            if cosine[i] >= threshold
        ]
        return matches[:top_k]

    def map_text(self, text: str, top_k: int = 3, threshold: float = 0.28) -> list[DisarmMatch]:
        vec = np.asarray(self._embed([text]), dtype=np.float32)[0]
        return self.map_vector(vec, top_k=top_k, threshold=threshold)


def lexical_match(text: str, top_k: int = 3) -> list[DisarmMatch]:
    """Dependency-free fallback: rank techniques by token overlap with `text` (no model).

    Coarser than the embedding mapper, but keeps DISARM tagging available with no
    sentence-transformers install (slim deployments, CI) — the ARGUS 'degrade to lexical'
    pattern. Scores are Jaccard-like overlaps, not cosine; use only when embeddings are out.
    """
    tokens = set(_TOKEN.findall(text.lower()))
    if not tokens:
        return []
    scored: list[DisarmMatch] = []
    for t in DISARM_TECHNIQUES:
        terms = set(_TOKEN.findall(t.text.lower()))
        overlap = len(tokens & terms)
        if overlap:
            scored.append(DisarmMatch(t.technique_id, t.name, t.phase, overlap / len(terms)))
    scored.sort(key=lambda m: m.score, reverse=True)
    return scored[:top_k]


_default_mapper: DisarmMapper | None = None


def default_mapper() -> DisarmMapper:
    """Process-wide mapper backed by the real encoder (catalog embedded once)."""
    global _default_mapper
    if _default_mapper is None:
        _default_mapper = DisarmMapper()
    return _default_mapper
