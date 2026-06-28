"""Structured-completion helper: ask a backend for schema-validated JSON.

Returns a validated pydantic model, or None if the model didn't produce parseable JSON
matching the schema — the caller then falls back to the free-form text path.
"""

from pydantic import BaseModel, ValidationError

from argus.agent.llm import LLMBackend
from argus.logging import get_logger

log = get_logger(__name__)


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
