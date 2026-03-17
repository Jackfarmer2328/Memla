from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

import requests


@dataclass(frozen=True)
class ChatMessage:
    role: str  # system | user | assistant
    content: str


class OllamaClient:
    """
    Minimal local Ollama chat client.

    Uses the local daemon at http://127.0.0.1:11434.
    """

    def __init__(self, *, base_url: str = "http://127.0.0.1:11434") -> None:
        self.base_url = base_url.rstrip("/")

    def chat(
        self,
        *,
        model: str,
        messages: list[ChatMessage],
        temperature: float = 0.2,
        num_ctx: Optional[int] = None,
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

        resp = requests.post(url, json=payload, timeout=600)
        resp.raise_for_status()
        data = resp.json()
        msg = data.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, str):
            raise RuntimeError(f"Unexpected Ollama response: {json.dumps(data)[:500]}")
        return content

