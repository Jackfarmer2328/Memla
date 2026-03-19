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
    - Extracts a few structured chunks from each user message (heuristic or LLM)
    - Retrieves top-k by hybrid scoring: semantic (MiniLM) + keyword + recency + frequency
    - Falls back to keyword-only if the embedding model is unavailable
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
        candidates = self.log.fetch_top_level_chunks(user_id=user_id, limit=400)
        if not candidates:
            return []

        q_tokens = set(_tokenize(query_text))
        now = time.time()

        # --- Graph-augmented contextual retrieval (C1) ---
        # Enrich chunk text with connected node context before embedding.
        # MiniLM doesn't know domain vocabulary, but reads context clues.
        enriched_texts = self._enrich_with_graph_context(candidates, user_id)

        # --- Attempt semantic scoring via MiniLM embeddings ---
        sem_scores: dict[int, float] = {}
        try:
            from ..middleware.context_builder import _get_lora_manager
            mgr = _get_lora_manager()
            if mgr is not None:
                q_emb = mgr.embed_query(query_text)
                c_embs = mgr.embed_many(enriched_texts)
                if q_emb and c_embs:
                    for idx, c_emb in enumerate(c_embs):
                        dot = sum(a * b for a, b in zip(q_emb, c_emb))
                        sem_scores[candidates[idx].id] = float(dot)
        except Exception:
            pass

        has_semantic = bool(sem_scores)

        def score(c: Chunk) -> float:
            c_tokens = set(_tokenize(c.text)) | set(_tokenize(c.key))
            overlap = len(q_tokens & c_tokens)

            age_s = max(0.0, now - float(c.last_recalled_ts))
            recency = math.exp(-age_s / (60.0 * 60.0 * 24.0 * 7.0))

            freq = math.log(1.0 + float(c.frequency_count))

            type_boost = 0.0
            if c.chunk_type == "decision":
                type_boost = 0.6
            elif c.chunk_type == "entity":
                type_boost = 0.3

            if has_semantic:
                # Cosine sim is in [-1, 1]; shift to [0, 2] for positive weighting.
                semantic = (sem_scores.get(c.id, 0.0) + 1.0)
                return (2.0 * semantic) + (0.6 * overlap) + (0.6 * recency) + (0.3 * freq) + type_boost
            else:
                return (1.2 * overlap) + (1.0 * recency) + (0.4 * freq) + type_boost

        ranked = sorted(candidates, key=score, reverse=True)
        top = ranked[: max(3, int(k))]
        return top

    def _enrich_with_graph_context(self, chunks: list[Chunk], user_id: str) -> list[str]:
        """Prepend connected-node context clues to each chunk before embedding.

        The graph becomes a living dictionary: MiniLM doesn't know "Project Phoenix",
        but it reads "[Context: React frontend, Supabase database]" and maps correctly.
        """
        try:
            links = self.log._conn.execute(
                "SELECT chunk_a_id, chunk_b_id FROM user_links WHERE user_id=?",
                (user_id,),
            ).fetchall()
        except Exception:
            return [c.text for c in chunks]

        if not links:
            return [c.text for c in chunks]

        neighbors: dict[int, set[int]] = {}
        for a, b in links:
            neighbors.setdefault(a, set()).add(b)
            neighbors.setdefault(b, set()).add(a)

        chunk_by_id = {c.id: c for c in chunks}
        all_chunks_by_id = chunk_by_id.copy()
        missing_ids = set()
        for c in chunks:
            for nid in neighbors.get(c.id, set()):
                if nid not in all_chunks_by_id:
                    missing_ids.add(nid)
        if missing_ids:
            all_db = self.log.fetch_recent_chunks(user_id=user_id, limit=9999)
            for c in all_db:
                if c.id in missing_ids:
                    all_chunks_by_id[c.id] = c

        enriched: list[str] = []
        for c in chunks:
            nids = neighbors.get(c.id, set())
            if not nids:
                enriched.append(c.text)
                continue
            clues = []
            for nid in list(nids)[:5]:
                nc = all_chunks_by_id.get(nid)
                if nc:
                    clues.append(nc.key)
            if clues:
                context = ", ".join(clues)
                enriched.append(f"{c.text} [Context: {context}]")
            else:
                enriched.append(c.text)
        return enriched

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

