"""Pluggable LLM backends for the ARGUS analyst agents.

Free by default. `auto` resolution prefers the user's **local Ollama** and otherwise
returns ``None`` so the caller takes the deterministic template path — it never
silently selects the paid Claude backend. Claude is used only when
``ARGUS_LLM_BACKEND=anthropic`` is set explicitly.

A backend is just ``complete(system, user) -> str``; the multi-agent graph drives the
roles by swapping the system prompt. Tests inject a fake backend implementing the same
Protocol, so the deliberation is exercised with no model and no network.
"""

from typing import Any, Protocol, runtime_checkable

import httpx

from argus.config import Settings, get_settings
from argus.logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def complete(
        self, system: str, user: str, response_schema: dict[str, Any] | None = None
    ) -> str:
        """Complete a prompt. When `response_schema` (a JSON schema) is given, ask the
        model for JSON matching it — the structured-output path."""
        ...


class OllamaBackend:
    """Local Ollama chat backend (free). Resolves to any installed model if the
    configured one isn't pulled, so the agent runs with whatever the user has."""

    def __init__(self, url: str, model: str, timeout: float) -> None:
        self.name = f"ollama:{model}"
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout

    def complete(
        self, system: str, user: str, response_schema: dict[str, Any] | None = None
    ) -> str:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {"temperature": 0.2},
        }
        if response_schema is not None:
            payload["format"] = response_schema  # Ollama structured outputs (JSON schema)
        resp = httpx.post(f"{self._url}/api/chat", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return str(content).strip()


class AnthropicBackend:
    """Claude backend (paid, opt-in). Only selected when explicitly requested."""

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.name = f"anthropic:{model}"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout

    def complete(
        self, system: str, user: str, response_schema: dict[str, Any] | None = None
    ) -> str:
        import json as _json

        import anthropic  # optional dependency, imported lazily

        if response_schema is not None:
            schema_json = _json.dumps(response_schema)
            user = f"{user}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
        client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout)
        message = client.messages.create(
            model=self._model,
            max_tokens=2048,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
        return "\n".join(parts).strip()


def ollama_models(url: str, timeout: float = 3.0) -> list[str]:
    """Installed Ollama model names, or [] if Ollama is unreachable."""
    try:
        resp = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=timeout)
        resp.raise_for_status()
        return [m["name"] for m in resp.json().get("models", [])]
    except (httpx.HTTPError, ValueError, KeyError):
        return []


def _resolve_ollama_model(preferred: str, available: list[str]) -> str:
    """Prefer the configured model (matched loosely on the ':' tag), else the first."""
    if preferred in available:
        return preferred
    for name in available:
        if name.split(":")[0] == preferred.split(":")[0]:
            return name
    return available[0]


def resolve_backend(settings: Settings | None = None) -> LLMBackend | None:
    """Return a ready LLM backend, or None to signal the deterministic template path.

    `auto` (default) = local Ollama if reachable, else None. Never spends money on its
    own — Claude is returned only for the explicit "anthropic" choice.
    """
    s = settings or get_settings()
    choice = s.llm_backend

    if choice == "template":
        return None

    if choice == "anthropic":
        key = s.anthropic_api_key
        if not key:
            log.warning("anthropic_selected_but_no_key_using_template")
            return None
        return AnthropicBackend(key, s.anthropic_model, s.llm_timeout_seconds)

    if choice in ("ollama", "auto"):
        models = ollama_models(s.ollama_url)
        if models:
            model = _resolve_ollama_model(s.ollama_model, models)
            log.info("using_ollama_backend", model=model)
            return OllamaBackend(s.ollama_url, model, s.llm_timeout_seconds)
        if choice == "ollama":
            log.warning("ollama_unreachable_using_template", url=s.ollama_url)
        return None

    log.warning("unknown_llm_backend_using_template", backend=choice)
    return None
