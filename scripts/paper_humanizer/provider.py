"""LLM provider abstraction.

The host agent can act as the LLM itself (agent mode, see SKILL.md); for pure
CLI usage, any OpenAI-compatible chat-completions endpoint works — OpenAI,
Qwen/DashScope compatible mode, vLLM, Ollama, etc. Configuration is read from
environment variables only; no keys are ever hardcoded:

  PAPER_HUMANIZER_API_KEY    required to enable the provider
  PAPER_HUMANIZER_BASE_URL   default https://api.openai.com/v1
  PAPER_HUMANIZER_MODEL      required when an API key is set
  PAPER_HUMANIZER_TIMEOUT    optional seconds (default 120)
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Mapping, Protocol


class LLMProvider(Protocol):
    available: bool

    def complete(self, prompt: str, *, system: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 4096) -> str: ...


class NullProvider:
    """Placeholder used when no provider is configured."""

    available = False

    def complete(self, prompt: str, *, system: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 4096) -> str:
        raise NotImplementedError("NullProvider cannot complete prompts")


class OpenAICompatibleProvider:
    available = True

    def __init__(self, base_url: str, api_key: str, model: str, *,
                 timeout: float = 120.0, opener=None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self._opener = opener or urllib.request.urlopen

    def complete(self, prompt: str, *, system: str | None = None,
                 temperature: float = 0.2, max_tokens: int = 4096) -> str:
        from paper_humanizer.errors import ProviderError

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body = json.dumps({
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers={"Content-Type": "application/json",
                     "Authorization": f"Bearer {self.api_key}"},
            method="POST",
        )
        try:
            with self._opener(request, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise ProviderError(f"provider HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ProviderError(f"provider unreachable: {exc.reason}") from exc
        except json.JSONDecodeError as exc:
            raise ProviderError(f"provider returned non-JSON body: {exc}") from exc
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"unexpected provider response shape: {json.dumps(payload, default=str)[:200]}"
            ) from exc


def provider_from_env(env: Mapping[str, str] | None = None) -> LLMProvider:
    from paper_humanizer.errors import ProviderNotConfigured

    env = os.environ if env is None else env
    api_key = env.get("PAPER_HUMANIZER_API_KEY", "").strip()
    if not api_key:
        return NullProvider()
    base_url = env.get("PAPER_HUMANIZER_BASE_URL", "https://api.openai.com/v1").strip()
    model = env.get("PAPER_HUMANIZER_MODEL", "").strip()
    if not model:
        raise ProviderNotConfigured(
            "PAPER_HUMANIZER_MODEL must be set when PAPER_HUMANIZER_API_KEY is provided"
        )
    timeout = float(env.get("PAPER_HUMANIZER_TIMEOUT", "120") or 120)
    return OpenAICompatibleProvider(base_url, api_key, model, timeout=timeout)
