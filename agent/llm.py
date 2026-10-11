"""
Provider-Agnostic LLM Interface with Caching and Retries.

Supported providers (all use the OpenAI chat-completions wire format):
  - groq         → https://api.groq.com/openai/v1        (env: GROQ_API_KEY)
  - openrouter   → https://openrouter.ai/api/v1          (env: OPENROUTER_API_KEY)
  - openai       → https://api.openai.com/v1             (env: OPENAI_API_KEY)
  - ollama       → http://localhost:11434/v1             (no key required)
  - gemini       → https://generativelanguage.googleapis.com/v1beta/openai
                                                         (env: GEMINI_API_KEY)

Configuration — set in .env (see .env.example):
  LLM_PROVIDER=groq
  LLM_MODEL=llama-3.1-8b-instant
  GROQ_API_KEY=gsk_...

Design decisions:
  - No simulator / fallback. Missing key or API failure → raises immediately.
    A result from a failed run is worse than no result: it silently corrupts
    your numbers.
  - cache key includes (model, provider, messages, tools, temperature) so
    temperature sweeps are stored independently.
  - _call_live_api wraps json.loads(arguments) in try/except and records
    malformed tool calls as a traceable error category.
  - Every LLMResponse carries model, provider, and timestamp for provenance.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".cache")
os.makedirs(CACHE_DIR, exist_ok=True)
CACHE_FILE = os.path.join(CACHE_DIR, "llm_cache.json")

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

class MalformedToolCallError(Exception):
    """Raised when the model returns a tool call whose arguments are not valid JSON."""


class LLMResponse:
    def __init__(
        self,
        content: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        model: str = "",
        provider: str = "",
        timestamp: float = 0.0,
    ):
        self.content = content
        self.tool_calls = tool_calls or []
        self.model = model
        self.provider = provider
        self.timestamp = timestamp or time.time()

    def __repr__(self) -> str:
        return (
            f"LLMResponse(model={self.model!r}, provider={self.provider!r}, "
            f"tool_calls={len(self.tool_calls)}, content_len={len(self.content or '')})"
        )


# ---------------------------------------------------------------------------
# Provider registry
# ---------------------------------------------------------------------------

_PROVIDER_BASE_URLS: Dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
}

_PROVIDER_ENV_VARS: Dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "ollama": "",  # no key required
}

# Recommended model pairs (one small/fast, one larger) — verified active endpoints
# Groq: openai/gpt-oss-20b (small), openai/gpt-oss-120b (large)
# OpenRouter free: google/gemma-2-9b-it:free (small), meta-llama/llama-3.1-70b-instruct:free (large)
RECOMMENDED_MODELS = {
    "groq": {
        "small": "openai/gpt-oss-20b",
        "large": "openai/gpt-oss-120b",
    },
    "openrouter": {
        "small": "google/gemma-2-9b-it:free",
        "large": "meta-llama/llama-3.1-70b-instruct:free",
    },
}


# ---------------------------------------------------------------------------
# LLMProvider
# ---------------------------------------------------------------------------

class LLMProvider:
    """
    Thin wrapper around any OpenAI-compatible chat-completions endpoint.

    Parameters
    ----------
    model_name : str
        Model identifier as understood by the provider (e.g. "llama-3.1-8b-instant").
    provider : str
        One of: "groq", "openrouter", "openai", "ollama", "gemini".
    api_key : str | None
        API key. If None, read from the provider's env var. Raises if missing
        (except for "ollama" which needs no key).
    base_url : str | None
        Override the provider's default base URL.
    enable_cache : bool
        Cache responses to .cache/llm_cache.json keyed by (model, provider,
        messages, tools, temperature). Useful for re-runs during development.
    max_retries : int
        Number of HTTP retry attempts with exponential back-off (2^attempt s).
    timeout_s : float
        Per-request HTTP timeout in seconds.
    """

    def __init__(
        self,
        model_name: str,
        provider: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        enable_cache: bool = True,
        max_retries: int = 3,
        timeout_s: float = 60.0,
    ):
        self.model_name = model_name
        self.provider = provider.lower()
        self.enable_cache = enable_cache
        self.max_retries = max_retries
        self.timeout_s = timeout_s

        # Resolve base URL
        self.base_url = (
            base_url
            or _PROVIDER_BASE_URLS.get(self.provider)
            or (_ for _ in ()).throw(  # type: ignore[attr-defined]
                ValueError(f"Unknown provider {self.provider!r}. "
                           f"Known: {list(_PROVIDER_BASE_URLS)}")
            )
        )

        # Resolve API key
        if self.provider == "ollama":
            self.api_key = "ollama"  # placeholder; Ollama ignores the header
        else:
            env_var = _PROVIDER_ENV_VARS.get(self.provider, "")
            self.api_key = api_key or (os.getenv(env_var) if env_var else None)
            if not self.api_key:
                raise EnvironmentError(
                    f"No API key for provider '{self.provider}'. "
                    f"Set {env_var} in your environment or .env file. "
                    f"See .env.example for configuration details."
                )

        self._cache: Dict[str, Any] = self._load_cache()

    # ------------------------------------------------------------------
    # Cache helpers
    # ------------------------------------------------------------------

    def _load_cache(self) -> Dict[str, Any]:
        if os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                return {}
        return {}

    def _save_cache(self) -> None:
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._cache, fh, indent=2)
        except Exception as exc:
            log.warning("Could not save LLM cache: %s", exc)

    def _cache_key(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float,
    ) -> str:
        """
        Cache key includes temperature so runs at different temperatures are
        stored independently.
        """
        payload = {
            "model": self.model_name,
            "provider": self.provider,
            "temperature": temperature,
            "messages": messages,
            "tools": tools,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        """
        Call the model and return an LLMResponse.

        Raises
        ------
        EnvironmentError
            If the API key is missing.
        httpx.HTTPStatusError
            If the API returns a non-2xx status after all retries.
        MalformedToolCallError
            If the model returns a tool call with arguments that are not valid JSON.
            This is a *real failure category* — log it and count it.
        """
        key = self._cache_key(messages, tools, temperature)
        if self.enable_cache and key in self._cache:
            entry = self._cache[key]
            log.debug("Cache hit for key %s…", key[:12])
            return LLMResponse(
                content=entry.get("content"),
                tool_calls=entry.get("tool_calls", []),
                model=self.model_name,
                provider=self.provider,
                timestamp=entry.get("timestamp", 0.0),
            )

        response = self._call_live_api(messages, tools, temperature)

        if self.enable_cache:
            self._cache[key] = {
                "content": response.content,
                "tool_calls": response.tool_calls,
                "timestamp": response.timestamp,
            }
            self._save_cache()

        return response

    # ------------------------------------------------------------------
    # Internal HTTP call
    # ------------------------------------------------------------------

    def _call_live_api(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
        temperature: float,
    ) -> LLMResponse:
        url = self.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "model": self.model_name,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            try:
                with httpx.Client(timeout=self.timeout_s) as client:
                    resp = client.post(url, headers=headers, json=payload)
                    resp.raise_for_status()
                    data = resp.json()

                choice = data["choices"][0]["message"]
                ts = time.time()

                tool_calls: List[Dict[str, Any]] = []
                for tc in choice.get("tool_calls") or []:
                    raw_args = tc["function"]["arguments"]
                    try:
                        parsed_args = json.loads(raw_args)
                    except (json.JSONDecodeError, TypeError) as parse_err:
                        # Real models occasionally emit truncated or invalid JSON.
                        # This is a distinct, trackable failure category:
                        # "malformed_tool_call". Do NOT silently coerce — raise
                        # so the caller can log and count it.
                        raise MalformedToolCallError(
                            f"Model '{self.model_name}' returned a tool call for "
                            f"'{tc['function']['name']}' with non-JSON arguments.\n"
                            f"Raw: {raw_args!r}\n"
                            f"Parse error: {parse_err}"
                        ) from parse_err

                    tool_calls.append(
                        {
                            "id": tc.get("id", f"call_{int(ts * 1000)}"),
                            "name": tc["function"]["name"],
                            "arguments": parsed_args,
                        }
                    )

                return LLMResponse(
                    content=choice.get("content"),
                    tool_calls=tool_calls,
                    model=self.model_name,
                    provider=self.provider,
                    timestamp=ts,
                )

            except MalformedToolCallError:
                raise  # propagate immediately — not a transient error

            except Exception as exc:
                last_exc = exc
                wait = 2 ** attempt
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                    retry_after = exc.response.headers.get("retry-after")
                    if retry_after and retry_after.isdigit():
                        wait = max(int(retry_after) + 1, wait)
                    else:
                        wait = max(5 * (attempt + 1), wait)

                log.warning(
                    "LLM call attempt %d/%d failed (%s). Retrying in %ds…",
                    attempt + 1,
                    self.max_retries,
                    exc,
                    wait,
                )
                time.sleep(wait)

        # All retries exhausted — raise. Do NOT fall back to a simulator.
        raise RuntimeError(
            f"LLM call to provider='{self.provider}' model='{self.model_name}' "
            f"failed after {self.max_retries} attempts. Last error: {last_exc}"
        ) from last_exc


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def provider_from_env(
    enable_cache: bool = True,
    max_retries: int = 3,
) -> LLMProvider:
    """
    Build an LLMProvider from environment variables.

    Required env vars:
        LLM_PROVIDER   e.g. "groq"
        LLM_MODEL      e.g. "llama-3.1-8b-instant"
    Plus the provider-specific key (GROQ_API_KEY, etc.).
    """
    provider_name = os.getenv("LLM_PROVIDER", "").strip()
    model_name = os.getenv("LLM_MODEL", "").strip()

    if not provider_name:
        raise EnvironmentError(
            "LLM_PROVIDER is not set. Add it to your .env file. "
            "Example: LLM_PROVIDER=groq"
        )
    if not model_name:
        raise EnvironmentError(
            "LLM_MODEL is not set. Add it to your .env file. "
            f"Example for {provider_name}: LLM_MODEL={RECOMMENDED_MODELS.get(provider_name, {}).get('small', 'your-model-name')}"
        )

    return LLMProvider(
        model_name=model_name,
        provider=provider_name,
        enable_cache=enable_cache,
        max_retries=max_retries,
    )
