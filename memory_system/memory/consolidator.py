"""
Hierarchical memory consolidation (Constraint 7).

Detects dense clusters of similar episodic chunks, generates a summary node,
and demotes the raw chunks by setting their parent_id to the summary.
The summary stays in the active retrieval window; the raw chunks are only
surfaced on-demand via memory_expand.
"""
from __future__ import annotations

import re
import time
from typing import Callable, Optional

from .episode_log import Chunk, EpisodeLog


_STOP = frozenset({
    "a","an","and","are","as","at","be","but","by","for","from","has","have",
    "he","her","his","i","in","is","it","its","me","my","not","of","on","or",
    "our","she","that","the","their","them","they","this","to","was","we",
    "were","with","you","your","fact","entity","decision","note","mentioned",
    "preference",
})


def _tok(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(t) >= 2 and t not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def _find_clusters(
    chunks: list[Chunk],
    similarity_threshold: float = 0.35,
    min_cluster_size: int = 5,
) -> list[list[Chunk]]:
    """Single-linkage clustering on token Jaccard similarity."""
    n = len(chunks)
    tokenized = [_tok(c.text + " " + c.key) for c in chunks]

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    for i in range(n):
        for j in range(i + 1, n):
            if _jaccard(tokenized[i], tokenized[j]) >= similarity_threshold:
                union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        r = find(i)
        groups.setdefault(r, []).append(i)

    return [
        [chunks[i] for i in idxs]
        for idxs in groups.values()
        if len(idxs) >= min_cluster_size
    ]


def _default_summary(chunks: list[Chunk]) -> str:
    """Heuristic summary when no LLM is available."""
    common_tokens = None
    for c in chunks:
        t = _tok(c.text + " " + c.key)
        if common_tokens is None:
            common_tokens = t.copy()
        else:
            common_tokens &= t

    themes = " ".join(sorted(common_tokens or set()))[:200] or "various topics"
    return (
        f"Summary of {len(chunks)} related memories about: {themes}. "
        f"Use memory_expand to see the {len(chunks)} original detailed memories."
    )


def consolidate(
    log: EpisodeLog,
    *,
    user_id: str,
    similarity_threshold: float = 0.35,
    min_cluster_size: int = 5,
    llm_summarize: Optional[Callable[[list[str]], str]] = None,
) -> list[int]:
    """
    Run consolidation for a user. Returns IDs of newly created summary chunks.

    1. Fetch all top-level chunks
    2. Cluster by token similarity
    3. For each cluster: create a summary node, set parent_id on originals
    """
    top_level = log.fetch_top_level_chunks(user_id=user_id, limit=9999)
    if len(top_level) < min_cluster_size:
        return []

    clusters = _find_clusters(
        top_level,
        similarity_threshold=similarity_threshold,
        min_cluster_size=min_cluster_size,
    )

    summary_ids: list[int] = []
    for cluster in clusters:
        texts = [c.text for c in cluster]

        if llm_summarize is not None:
            try:
                summary_text = llm_summarize(texts)
            except Exception:
                summary_text = _default_summary(cluster)
        else:
            summary_text = _default_summary(cluster)

        common_key = _common_key(cluster)
        total_freq = sum(c.frequency_count for c in cluster)

        summary_id = log.add_or_bump_chunk(
            session_id=cluster[0].session_id,
            user_id=user_id,
            chunk_type="summary",
            key=common_key,
            text=summary_text,
            source_episode_id=None,
            meta={"consolidated_from": [c.id for c in cluster], "child_count": len(cluster)},
        )

        if summary_id:
            log.set_parent(
                chunk_ids=[c.id for c in cluster],
                parent_id=summary_id,
            )
            log._conn.execute(
                "UPDATE chunks SET frequency_count = ? WHERE id = ?",
                (total_freq, summary_id),
            )
            log._conn.commit()
            summary_ids.append(summary_id)

    return summary_ids


def _common_key(chunks: list[Chunk]) -> str:
    tokens = None
    for c in chunks:
        t = _tok(c.key)
        if tokens is None:
            tokens = t.copy()
        else:
            tokens &= t
    key = " ".join(sorted(tokens or set()))[:120]
    return key or f"cluster_{int(time.time())}"
