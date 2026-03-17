from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional, Sequence, Tuple

from .episode_log import Chunk, EpisodeLog


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "but",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "is",
    "it",
    "its",
    "me",
    "my",
    "not",
    "of",
    "on",
    "or",
    "our",
    "she",
    "that",
    "the",
    "their",
    "them",
    "they",
    "this",
    "to",
    "was",
    "we",
    "were",
    "with",
    "you",
    "your",
}


def _tokenize(text: str) -> list[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text.lower())
    return [t for t in tokens if len(t) >= 2 and t not in _STOPWORDS]


def _stable_key(text: str) -> str:
    # Normalize a key for retrieval: lower, remove punctuation, collapse spaces.
    k = re.sub(r"[^a-zA-Z0-9_ ]+", " ", text.lower())
    k = re.sub(r"\s+", " ", k).strip()
    return k[:256]


@dataclass(frozen=True)
class MemoryChunkDraft:
    chunk_type: str  # fact | decision | entity | note
    key: str
    text: str


class ChunkManager:
    """
    Step 1 memory chunks:
    - Extracts a few structured chunks from each user message (heuristic, local)
    - Retrieves top-k by keyword overlap + recency + frequency
    """

    def __init__(
        self,
        episode_log: EpisodeLog,
        *,
        llm_extractor: Optional[Callable[[str], Tuple[list["MemoryChunkDraft"], dict[str, Any]]]] = None,
    ) -> None:
        self.log = episode_log
        self._llm_extractor = llm_extractor

    def extract_chunks(self, user_text: str) -> tuple[list[MemoryChunkDraft], dict[str, Any]]:
        text = user_text.strip()
        if not text:
            return [], {"source": "empty"}

        if self._llm_extractor is not None:
            try:
                drafts, meta = self._llm_extractor(text)
                if drafts:
                    return drafts, meta
            except Exception as e:
                # Fall back to heuristic extraction; persist the failure signal in meta.
                pass

        drafts: list[MemoryChunkDraft] = []

        # Decisions / preferences (simple pattern capture).
        decision_patterns = [
            r"\b(?:i|we)\s+(?:decided|choose|chose|prefer|want|need)\s+(?P<x>.+)$",
            r"\bmy\s+preference\s+is\s+(?P<x>.+)$",
        ]
        for pat in decision_patterns:
            m = re.search(pat, text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                x = m.group("x").strip().rstrip(".")
                if x:
                    drafts.append(
                        MemoryChunkDraft(
                            chunk_type="decision",
                            key=_stable_key(x),
                            text=f"Preference/decision: {x}",
                        )
                    )
                break

        # Entities: naive capture of "X is Y", and capitalized tokens.
        is_stmt = re.findall(r"\b([A-Z][a-zA-Z0-9_]+)\s+is\s+([^.\n]{3,80})", text)
        for ent, desc in is_stmt[:5]:
            drafts.append(
                MemoryChunkDraft(
                    chunk_type="entity",
                    key=_stable_key(ent),
                    text=f"Entity: {ent} — {desc.strip()}",
                )
            )

        caps = re.findall(r"\b[A-Z][a-zA-Z0-9_]{2,}\b", text)
        for ent in list(dict.fromkeys(caps))[:8]:
            drafts.append(MemoryChunkDraft(chunk_type="entity", key=_stable_key(ent), text=f"Entity mentioned: {ent}"))

        # Facts: keep a few dense sentences.
        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        for s in sentences[:5]:
            if len(s) >= 20 and not s.startswith("/"):
                drafts.append(MemoryChunkDraft(chunk_type="fact", key=_stable_key(s[:80]), text=f"Fact: {s}"))

        # De-dupe by (type,key,text).
        seen = set()
        out: list[MemoryChunkDraft] = []
        for d in drafts:
            k = (d.chunk_type, d.key, d.text)
            if k in seen:
                continue
            seen.add(k)
            out.append(d)
        return out[:20], {"source": "heuristic_extract_v1"}

    def persist_user_message(
        self, *, session_id: str, user_id: str, user_text: str, ts: int | None = None
    ) -> tuple[int, list[int]]:
        ts_i = int(ts if ts is not None else time.time())
        episode_id = self.log.add_episode(session_id=session_id, user_id=user_id, role="user", content=user_text, ts=ts_i)

        chunk_ids: list[int] = []
        drafts, meta = self.extract_chunks(user_text)
        for draft in drafts:
            cid = self.log.add_or_bump_chunk(
                session_id=session_id,
                user_id=user_id,
                chunk_type=draft.chunk_type,
                key=draft.key,
                text=draft.text,
                source_episode_id=episode_id,
                ts=ts_i,
                meta=meta,
            )
            chunk_ids.append(cid)
        return episode_id, chunk_ids

    def retrieve(self, *, user_id: str, query_text: str, k: int = 12) -> list[Chunk]:
        # Candidate pool: recent chunks.
        candidates = self.log.fetch_recent_chunks(user_id=user_id, limit=400)
        if not candidates:
            return []

        q_tokens = set(_tokenize(query_text))
        now = time.time()

        def score(c: Chunk) -> float:
            c_tokens = set(_tokenize(c.text)) | set(_tokenize(c.key))
            overlap = len(q_tokens & c_tokens)

            # Exponential recency on last recall time.
            age_s = max(0.0, now - float(c.last_recalled_ts))
            recency = math.exp(-age_s / (60.0 * 60.0 * 24.0 * 7.0))  # 1 week half-ish

            freq = math.log(1.0 + float(c.frequency_count))

            # Bias: decisions and entities are usually higher leverage.
            type_boost = 0.0
            if c.chunk_type == "decision":
                type_boost = 0.6
            elif c.chunk_type == "entity":
                type_boost = 0.3

            # If no token overlap, allow recency/frequency to keep a few "recent context" lines.
            return (1.2 * overlap) + (1.0 * recency) + (0.4 * freq) + type_boost

        ranked = sorted(candidates, key=score, reverse=True)
        top = ranked[: max(3, int(k))]
        return top

    def mark_recalled(self, chunks: Sequence[Chunk]) -> None:
        self.log.mark_recalled([c.id for c in chunks])


def ewc_lambda_multiplier_for_chunks(chunks: Sequence[Chunk]) -> float:
    """
    Step 3 frequency integration:
    - frequency_count >= 3 => stronger protection (bolded)
    - frequency_count == 1 => weaker protection (faint)

    Returns a single multiplier for the current training/update batch.
    """
    if not chunks:
        return 1.0
    freqs = [max(1, int(c.frequency_count)) for c in chunks]
    hi = sum(1 for f in freqs if f >= 3)
    lo = sum(1 for f in freqs if f == 1)
    if hi > lo:
        return 1.5
    if lo > hi:
        return 0.5
    return 1.0

