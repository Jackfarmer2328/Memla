from __future__ import annotations

import json
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

    Configure via constructor or env:
    - LLM_PROVIDER: "ollama" | "openai" | "anthropic"
    - LLM_BASE_URL: e.g. "http://127.0.0.1:11434" (ollama) or "https://api.openai.com" or "https://api.anthropic.com"
    - LLM_API_KEY: any API key string (used when provider != "ollama")
    """

    def __init__(
        self,
        *,
        provider: str = "ollama",
        base_url: str = "http://127.0.0.1:11434",
        api_key: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.provider = provider.strip().lower()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.headers = headers or {}

    @classmethod
    def from_env(cls) -> "UniversalLLMClient":
        import os

        provider = os.environ.get("LLM_PROVIDER", "ollama")
        base_url = os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434")
        api_key = os.environ.get("LLM_API_KEY")
        return cls(provider=provider, base_url=base_url, api_key=api_key)

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

        resp = requests.post(url, json=payload, timeout=600, headers=hdrs)
        resp.raise_for_status()
        data = resp.json()

        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(data)[:500]}") from e
        if not isinstance(content, str):
            raise RuntimeError(f"Unexpected OpenAI-compatible response: {json.dumps(data)[:500]}")
        return content

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

        resp = requests.post(url, json=payload, timeout=600, headers=hdrs)
        resp.raise_for_status()
        data = resp.json()

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

