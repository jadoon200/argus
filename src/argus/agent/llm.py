"""Pluggable LLM backends for the ARGUS analyst agents.

Free by default. `auto` resolution prefers the user's **local Ollama** and otherwise
returns ``None`` so the caller takes the deterministic template path — it never
silently selects the paid Claude backend. Claude is used only when
``ARGUS_LLM_BACKEND=anthropic`` is set explicitly.

A backend is just ``complete(system, user) -> str``; the multi-agent graph drives the
roles by swapping the system prompt. Tests inject a fake backend implementing the same
Protocol, so the deliberation is exercised with no model and no network.
"""

import json
from typing import Any, Protocol, runtime_checkable

import httpx

from argus.config import Settings, get_settings
from argus.logging import get_logger

log = get_logger(__name__)


_DEFAULT_TEMPERATURE = 0.2


@runtime_checkable
class LLMBackend(Protocol):
    name: str

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        """Complete a prompt. When `response_schema` (a JSON schema) is given, ask the
        model for JSON matching it — the structured-output path. `temperature` lets the
        deliberation sample each role differently (divergent red team, deterministic
        adjudicator); ``None`` uses the backend default."""
        ...


@runtime_checkable
class SeedableBackend(Protocol):
    """Optional capability used by the multi-seed evaluation harness."""

    def set_seed(self, seed: int) -> None:
        """Make subsequent local generations reproducible for one evaluation run."""
        ...


class OllamaBackend:
    """Local Ollama chat backend (free). Resolves to any installed model if the
    configured one isn't pulled, so the agent runs with whatever the user has."""

    def __init__(self, url: str, model: str, timeout: float) -> None:
        self.name = f"ollama:{model}"
        self._url = url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._seed: int | None = None

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        temp = _DEFAULT_TEMPERATURE if temperature is None else temperature
        options: dict[str, Any] = {"temperature": temp}
        if self._seed is not None:
            options["seed"] = self._seed
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": options,
        }
        if response_schema is not None:
            payload["format"] = response_schema  # Ollama structured outputs (JSON schema)
        resp = httpx.post(f"{self._url}/api/chat", json=payload, timeout=self._timeout)
        resp.raise_for_status()
        content = resp.json().get("message", {}).get("content", "")
        return str(content).strip()


class AnthropicBackend:
    """Claude backend (paid, opt-in). Only selected when explicitly requested."""

    # Generous ceiling: a truncated structured Finding is invalid JSON, which silently
    # demotes the deliberation to the free-form fallback.
    _MAX_TOKENS = 8192

    def __init__(self, api_key: str, model: str, timeout: float) -> None:
        self.name = f"anthropic:{model}"
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client: Any | None = None

    def _get_client(self) -> Any:
        if self._client is None:
            import anthropic  # optional dependency, imported lazily

            self._client = anthropic.Anthropic(api_key=self._api_key, timeout=self._timeout)
        return self._client

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        if response_schema is not None:
            schema_json = json.dumps(response_schema)
            user = f"{user}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
        message = self._get_client().messages.create(
            model=self._model,
            max_tokens=self._MAX_TOKENS,
            temperature=_DEFAULT_TEMPERATURE if temperature is None else temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        parts = [block.text for block in message.content if getattr(block, "type", "") == "text"]
        return "\n".join(parts).strip()


class OpenAIBackend:
    """OpenAI-compatible chat backend (httpx, no SDK). Works against any server that
    speaks /v1/chat/completions — vLLM, llama.cpp, LM Studio, groq, together. Free when
    pointed at a local server."""

    def __init__(self, base_url: str, api_key: str | None, model: str, timeout: float) -> None:
        self.name = f"openai:{model}"
        self._url = base_url.rstrip("/")
        self._key = api_key
        self._model = model
        self._timeout = timeout
        self._seed: int | None = None

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> str:
        if response_schema is not None:
            schema_json = json.dumps(response_schema)
            user = f"{user}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": _DEFAULT_TEMPERATURE if temperature is None else temperature,
        }
        if self._seed is not None:
            payload["seed"] = self._seed
        if response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self._key}"} if self._key else {}
        resp = httpx.post(
            f"{self._url}/chat/completions", json=payload, headers=headers, timeout=self._timeout
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"]).strip()


class MLXBackend:
    """Apple-Silicon-native local inference via mlx-lm (free). Also the path to serving
    a model fine-tuned locally with MLX LoRA. The model loads lazily and is cached."""

    def __init__(self, model: str, adapter_path: str | None = None) -> None:
        suffix = "+lora" if adapter_path else ""
        self.name = f"mlx:{model}{suffix}"
        self._model_name = model
        self._adapter_path = adapter_path
        self._loaded: tuple[Any, Any] | None = None
        self._seed: int | None = None

    def set_seed(self, seed: int) -> None:
        self._seed = seed

    def _ensure_loaded(self) -> tuple[Any, Any]:
        if self._loaded is None:
            from mlx_lm import load

            # load() returns (model, tokenizer) — or a 3-tuple with return_config; take the
            # first two so the type is a clean (model, tokenizer) regardless of version.
            result = load(self._model_name, adapter_path=self._adapter_path)
            self._loaded = (result[0], result[1])
        return self._loaded

    def complete(
        self,
        system: str,
        user: str,
        response_schema: dict[str, Any] | None = None,
        temperature: float | None = None,  # mlx-lm sampling left at its default
    ) -> str:
        if self._seed is not None:
            # Import dynamically so MLX remains an optional, Darwin-only dependency.
            import importlib

            mlx_core = importlib.import_module("mlx.core")
            mlx_core.random.seed(self._seed)
        from mlx_lm import generate

        if response_schema is not None:
            schema_json = json.dumps(response_schema)
            user = f"{user}\n\nRespond with ONLY valid JSON matching this schema:\n{schema_json}"
        model, tokenizer = self._ensure_loaded()
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        return str(generate(model, tokenizer, prompt=prompt, max_tokens=2048)).strip()


def set_backend_seed(backend: LLMBackend, seed: int) -> bool:
    """Seed a backend when it exposes reproducible sampling.

    Backends without an explicit seed adapter are rejected: the eval harness refuses to label
    repeated unseeded calls as a multi-seed result.
    """
    if not isinstance(backend, SeedableBackend):
        return False
    backend.set_seed(seed)
    return True


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

    if choice == "mlx":
        return MLXBackend(s.mlx_model, s.mlx_adapter_path)

    if choice == "openai":
        return OpenAIBackend(
            s.openai_base_url, s.openai_api_key, s.openai_model, s.llm_timeout_seconds
        )

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
