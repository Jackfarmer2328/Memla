from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..ollama_client import ChatMessage, OllamaClient
from .chunk_manager import MemoryChunkDraft, _stable_key


_EXTRACT_SYSTEM = """
Extract durable memory chunks from the user's message.

Return ONLY strict JSON (no markdown, no prose), with this schema:
{
  "chunks": [
    {"type": "fact|decision|entity|note", "key": "<short key>", "text": "<memory text>"}
  ]
}

Rules:
- Prefer atomic memories (one idea per chunk).
- Keep each text under 200 chars.
- Include only information likely to matter later (names, preferences, constraints, definitions, commitments, identifiers).
- Do NOT invent information.
""".strip()


def _strip_to_json(s: str) -> str:
    # Defensive: if model adds leading/trailing text, keep the largest JSON object-ish substring.
    s = s.strip()
    if s.startswith("{") and s.endswith("}"):
        return s
    m = re.search(r"\{[\s\S]*\}", s)
    return m.group(0) if m else s


@dataclass
class LLMChunkExtractor:
    client: OllamaClient
    model: str
    temperature: float = 0.0
    num_ctx: Optional[int] = None

    def extract(self, user_text: str) -> tuple[list[MemoryChunkDraft], dict[str, Any]]:
        messages = [
            ChatMessage(role="system", content=_EXTRACT_SYSTEM),
            ChatMessage(role="user", content=user_text),
        ]
        raw = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            num_ctx=self.num_ctx,
        )
        raw_json = _strip_to_json(raw)
        data = json.loads(raw_json)

        chunks = []
        for ch in (data.get("chunks") or [])[:30]:
            t = str(ch.get("type") or "").strip().lower()
            if t not in {"fact", "decision", "entity", "note"}:
                continue
            key = str(ch.get("key") or "").strip()
            text = str(ch.get("text") or "").strip()
            if not text:
                continue
            key2 = _stable_key(key or text)
            text2 = text[:200]
            chunks.append(MemoryChunkDraft(chunk_type=t, key=key2, text=text2))

        meta = {"source": "ollama_extract_v1", "raw_len": len(raw)}
        return chunks, meta

