from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass(frozen=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str


class UniversalLLMClient:
    """
    Universal chat client:
    - provider="ollama": local Ollama /api/chat (no API key)
    - provider="openai": OpenAI-compatible /v1/chat/completions (API key)
    - provider="anthropic": Anthropic /v1/messages (API key via x-api-key)
    - provider="github_models": GitHub Models /inference/chat/completions (GitHub token)

    Configure via constructor or env:
    - LLM_PROVIDER: "ollama" | "openai" | "anthropic" | "github_models"
    - LLM_BASE_URL: e.g. "http://127.0.0.1:11434" (ollama) or "https://api.openai.com" or "https://api.anthropic.com"
    - LLM_API_KEY: any API key string (used when provider != "ollama")
    - GITHUB_TOKEN / GITHUB_MODELS_TOKEN: optional fallback when provider="github_models"
    """

    def __init__(
        self,
        *,
        provider: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        api_key: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.provider = self._normalize_provider(provider)
        self.base_url = self._normalize_base_url(self.provider, base_url)
        self.api_key = api_key
        self.headers = headers or {}

    @classmethod
    def from_env(cls) -> "UniversalLLMClient":
        provider = cls._normalize_provider(os.environ.get("LLM_PROVIDER", "ollama"))
        base_url = cls._normalize_base_url(provider, cls._default_base_url_from_env(provider))
        api_key = os.environ.get("LLM_API_KEY")
        if provider == "github_models" and not api_key:
            api_key = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
        return cls(provider=provider, base_url=base_url, api_key=api_key)

    @staticmethod
    def _default_base_url_from_env(provider: str) -> str:
        base_url = str(os.environ.get("LLM_BASE_URL", "")).strip()
        if base_url:
            return base_url
        if provider == "ollama":
            ollama_host = str(os.environ.get("OLLAMA_HOST", "")).strip().rstrip("/")
            if ollama_host:
                if "://" not in ollama_host:
                    return f"http://{ollama_host}"
                return ollama_host
        return "http://127.0.0.1:11434"

    @staticmethod
    def _normalize_provider(provider: str) -> str:
        normalized = provider.strip().lower().replace("-", "_")
        if normalized in {"github", "githubmodels"}:
            return "github_models"
        return normalized

    @staticmethod
    def _normalize_base_url(provider: str, base_url: str) -> str:
        base = (base_url or "").strip().rstrip("/")
        if provider == "github_models":
            if not base or base in {"http://127.0.0.1:11434", "http://localhost:11434"}:
                return "https://models.github.ai/inference"
            if base == "https://models.github.ai":
                return "https://models.github.ai/inference"
        return base or "http://127.0.0.1:11434"

    def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        num_ctx: Optional[int] = None,
    ) -> str:
        if self.provider == "ollama":
            return self._chat_ollama(model=model, messages=messages, temperature=temperature, num_ctx=num_ctx)
        if self.provider == "anthropic":
            return self._chat_anthropic(model=model, messages=messages, temperature=temperature)
        if self.provider == "github_models":
            return self._chat_github_models(model=model, messages=messages, temperature=temperature)
        # default to OpenAI-compatible
        return self._chat_openai_compatible(model=model, messages=messages, temperature=temperature)

    def _chat_ollama(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
        num_ctx: Optional[int],
    ) -> str:
        url = f"{self.base_url}/api/chat"
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "think": False,
            "options": {"temperature": float(temperature)},
        }
        if num_ctx is not None:
            payload["options"]["num_ctx"] = int(num_ctx)

        resp = requests.post(url, json=payload, timeout=600, headers=self.headers)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Unexpected Ollama response: {json.dumps(data)[:500]}")
        return content

    def _chat_openai_compatible(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
    ) -> str:
        url = f"{self.base_url}/v1/chat/completions"
        hdrs = dict(self.headers)
        if self.api_key:
            hdrs.setdefault("Authorization", f"Bearer {self.api_key}")
        hdrs.setdefault("Content-Type", "application/json")

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": float(temperature),
        }

        data = self._post_chat_json_with_temperature_retry(
            url=url,
            headers=hdrs,
            payload=payload,
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(data)[:500]}") from e
        if not isinstance(content, str):
            raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(data)[:500]}")
        return content

    def _chat_github_models(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
    ) -> str:
        """
        Native GitHub Models chat endpoint.

        - Endpoint: POST /inference/chat/completions
        - Auth: Bearer token from GITHUB_TOKEN, GITHUB_MODELS_TOKEN, or LLM_API_KEY
        - Response shape mirrors OpenAI chat completions
        """
        if not self.api_key:
            raise RuntimeError(
                "GitHub Models requires a token. Set LLM_API_KEY, GITHUB_MODELS_TOKEN, or GITHUB_TOKEN."
            )

        url = f"{self.base_url}/chat/completions"
        hdrs = dict(self.headers)
        hdrs.setdefault("Accept", "application/vnd.github+json")
        hdrs.setdefault("Authorization", f"Bearer {self.api_key}")
        hdrs.setdefault("X-GitHub-Api-Version", "2022-11-28")
        hdrs.setdefault("Content-Type", "application/json")

        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": float(temperature),
        }

        data = self._post_chat_json_with_temperature_retry(
            url=url,
            headers=hdrs,
            payload=payload,
        )

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Unexpected GitHub Models response: {json.dumps(data)[:500]}") from e
        if not isinstance(content, str):
            raise RuntimeError(f"Unexpected GitHub Models response: {json.dumps(data)[:500]}")
        return content

    def _post_chat_json_with_temperature_retry(
        self,
        *,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        current_payload = dict(payload)
        last_error: Exception | None = None
        retry_delays = (5.0, 15.0, 30.0)
        for attempt in range(len(retry_delays) + 1):
            try:
                resp = requests.post(url, json=current_payload, timeout=600, headers=headers)
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as exc:
                response = exc.response
                if "temperature" in current_payload and self._response_requires_default_temperature(response):
                    current_payload = dict(current_payload)
                    current_payload.pop("temperature", None)
                    last_error = exc
                    continue
                status = response.status_code if response is not None else None
                if status not in {429, 500, 502, 503, 504, 529} or attempt >= len(retry_delays):
                    raise
                last_error = exc
                delay = self._response_retry_delay_seconds(response, retry_delays[attempt])
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                if attempt >= len(retry_delays):
                    raise
                last_error = exc
                delay = retry_delays[attempt]
            time.sleep(delay)
        if last_error is not None:
            raise last_error
        raise RuntimeError("Chat request failed without a response payload.")

    @staticmethod
    def _response_requires_default_temperature(response: Any) -> bool:
        if response is None:
            return False
        try:
            payload = response.json()
        except Exception:
            return False
        error = payload.get("error")
        if not isinstance(error, dict):
            return False
        param = str(error.get("param") or "").strip().lower()
        code = str(error.get("code") or "").strip().lower()
        message = str(error.get("message") or "").strip().lower()
        if param != "temperature":
            return False
        if code == "unsupported_value":
            return True
        return "temperature" in message and ("default" in message or "does not support" in message)

    @staticmethod
    def _response_retry_delay_seconds(response: Any, default_delay: float) -> float:
        if response is None:
            return default_delay
        headers = getattr(response, "headers", {}) or {}
        retry_after = headers.get("Retry-After") if isinstance(headers, dict) else None
        if retry_after is None:
            return default_delay
        try:
            return max(float(retry_after), 0.0)
        except (TypeError, ValueError):
            return default_delay

    def _chat_anthropic(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float,
    ) -> str:
        """
        Native Anthropic Messages API.

        - Endpoint: POST /v1/messages
        - Auth: x-api-key
        - System: top-level "system" string
        - Messages: role user/assistant with content blocks
        """
        # Default Anthropic base URL if user kept the Ollama default.
        base = self.base_url
        if base.startswith("http://127.0.0.1:11434") or base.startswith("http://localhost:11434"):
            base = "https://api.anthropic.com"
        url = f"{base.rstrip('/')}/v1/messages"

        hdrs = dict(self.headers)
        if self.api_key:
            hdrs.setdefault("x-api-key", self.api_key)
        hdrs.setdefault("anthropic-version", "2023-06-01")
        hdrs.setdefault("Content-Type", "application/json")

        system_parts = [m.content for m in messages if m.role == "system" and m.content.strip()]
        system = "\n\n".join(system_parts).strip() if system_parts else None

        amsgs = []
        for m in messages:
            if m.role == "system":
                continue
            role = m.role
            if role not in {"user", "assistant"}:
                role = "user"
            amsgs.append({"role": role, "content": [{"type": "text", "text": m.content}]})

        payload: dict[str, Any] = {
            "model": model,
            "messages": amsgs,
            "temperature": float(temperature),
            "max_tokens": 4096,
        }
        if system:
            payload["system"] = system

        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        retry_delays = (1.0, 2.5, 5.0)
        for attempt in range(len(retry_delays) + 1):
            try:
                resp = requests.post(url, json=payload, timeout=600, headers=hdrs)
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.exceptions.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status not in {429, 500, 502, 503, 504, 529} or attempt >= len(retry_delays):
                    raise
                last_error = exc
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as exc:
                if attempt >= len(retry_delays):
                    raise
                last_error = exc
            time.sleep(retry_delays[attempt])

        if data is None:
            if last_error is not None:
                raise last_error
            raise RuntimeError("Anthropic chat failed without a response payload.")

        # Response content is a list of blocks.
        content = data.get("content")
        if isinstance(content, list):
            parts = []
            for blk in content:
                if isinstance(blk, dict) and blk.get("type") == "text" and isinstance(blk.get("text"), str):
                    parts.append(blk["text"])
            out = "".join(parts).strip()
            if out:
                return out
        raise RuntimeError(f"Unexpected Anthropic response: {json.dumps(data)[:500]}")


# Backwards compat (internal). Prefer UniversalLLMClient.
OllamaClient = UniversalLLMClient

