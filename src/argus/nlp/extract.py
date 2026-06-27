"""Entity extraction — spaCy NER when available, a dependency-free heuristic otherwise.

The heuristic (capitalised multi-word spans) is deliberately weak; it exists so the
pipeline and tests run with no model installed. Set `ARGUS_NER_BACKEND=spacy` and
install the `nlp` extra + a model for real NER. Entities are normalised to a stable
id so the same actor/place from different documents collapses to one node.
"""

import hashlib
import re

from argus.config import get_settings
from argus.logging import get_logger

log = get_logger(__name__)

# ATT&CK-style relevance: people, orgs, places, groups, events, facilities.
_KEEP_LABELS = {"PERSON", "ORG", "GPE", "LOC", "NORP", "EVENT", "FAC"}
_CAP_SPAN_RE = re.compile(r"\b([A-Z][\w'-]+(?:\s+(?:of|the|and|[A-Z][\w'-]+)){0,4})")
# Common sentence-initial words that the heuristic would otherwise mistake for names.
_STOPWORDS = {"The", "A", "An", "This", "That", "These", "Those", "It", "But", "And", "In", "On"}

_spacy_nlp: object | None = None
_spacy_tried = False

Entity = tuple[str, str]  # (surface_name, type)


def entity_id(name: str, etype: str) -> str:
    key = f"{etype}:{name.strip().lower()}"
    return hashlib.sha256(key.encode()).hexdigest()[:24]


def _load_spacy() -> object | None:
    global _spacy_nlp, _spacy_tried
    if _spacy_tried:
        return _spacy_nlp
    _spacy_tried = True
    try:
        import spacy

        _spacy_nlp = spacy.load(get_settings().spacy_model, disable=["lemmatizer"])
        log.info("spacy_loaded", model=get_settings().spacy_model)
    except Exception as exc:  # model or package missing -> heuristic fallback
        log.warning("spacy_unavailable_using_heuristic", error=str(exc))
        _spacy_nlp = None
    return _spacy_nlp


def _spacy_entities(text: str) -> list[Entity]:
    nlp = _load_spacy()
    if nlp is None:
        return _heuristic_entities(text)
    doc = nlp(text)  # type: ignore[operator]
    return [(ent.text.strip(), ent.label_) for ent in doc.ents if ent.label_ in _KEEP_LABELS]


def _heuristic_entities(text: str) -> list[Entity]:
    out: list[Entity] = []
    for match in _CAP_SPAN_RE.findall(text):
        name = match.strip()
        first = name.split()[0]
        if first in _STOPWORDS or len(name) < 3:
            continue
        out.append((name, "ENTITY"))
    return out


def extract_entities(text: str, backend: str | None = None) -> list[Entity]:
    """Extract (name, type) entities from text using the configured NER backend."""
    if not text.strip():
        return []
    backend = backend or get_settings().ner_backend
    if backend == "spacy":
        return _spacy_entities(text)
    return _heuristic_entities(text)
