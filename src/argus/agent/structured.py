"""Structured-completion helpers — resilient calls into a (possibly flaky) LLM backend.

`complete_model` asks for schema-validated JSON and returns None if the model produced
bad JSON *or the backend call itself failed* (timeout / connection) — the caller then
takes the free-form fallback. `safe_complete` is the free-form equivalent, returning ""
on failure. So one slow or failed call degrades a single role, it never crashes the
whole deliberation (a real /brief request must not 500 on a model hiccup).
"""

import httpx
from pydantic import BaseModel, ValidationError

from argus.agent.llm import LLMBackend
from argus.logging import get_logger

log = get_logger(__name__)

# Backend failures we treat as "no answer": network/timeout from the httpx-based backends,
# plus the stdlib equivalents. Not a blanket except — a bug in our code still surfaces.
_BACKEND_ERRORS = (httpx.HTTPError, ConnectionError, TimeoutError, OSError)


def complete_model[ModelT: BaseModel](
    backend: LLMBackend,
    system: str,
    user: str,
    schema: type[ModelT],
    temperature: float | None = None,
) -> ModelT | None:
    try:
        raw = backend.complete(
            system, user, response_schema=schema.model_json_schema(), temperature=temperature
        )
        return schema.model_validate_json(raw)
    except (ValidationError, ValueError) as exc:
        log.warning("structured_output_fallback", schema=schema.__name__, error=str(exc))
        return None
    except _BACKEND_ERRORS as exc:
        log.warning("structured_backend_failed", schema=schema.__name__, error=str(exc))
        return None


def safe_complete(
    backend: LLMBackend, system: str, user: str, temperature: float | None = None
) -> str:
    """Free-form completion that returns '' on a backend failure (timeout/connection),
    so a flaky call degrades a role rather than crashing the deliberation."""
    try:
        return backend.complete(system, user, temperature=temperature)
    except _BACKEND_ERRORS as exc:
        log.warning("backend_call_failed", error=str(exc))
        return ""
