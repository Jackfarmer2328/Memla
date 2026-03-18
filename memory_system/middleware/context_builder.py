from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Iterable, Sequence

from ..memory.episode_log import Chunk

if TYPE_CHECKING:
    from .quality import ChunkQuality

_lora_manager_cache: dict[str, Any] = {}


def _get_lora_manager() -> Any:
    """Return the cached RetrievalLoRAManager, or None if unavailable."""
    cache_key = "default"
    if cache_key in _lora_manager_cache:
        return _lora_manager_cache[cache_key]
    try:
        from ..adapters.lora_manager import RetrievalLoRAManager
        mgr = RetrievalLoRAManager()
        _lora_manager_cache[cache_key] = mgr
        return mgr
    except Exception:
        return None


@dataclass(frozen=True)
class BuiltContext:
    system_prompt: str
    injected_chunks: list[Chunk]


def _format_chunks(chunks: Iterable[Chunk]) -> str:
    lines: list[str] = []
    for c in chunks:
        lines.append(
            f"- [{c.chunk_type}] (freq={c.frequency_count}) {c.text}"
        )
    return "\n".join(lines)


def _rerank_with_lora(
    *,
    user_id: str,
    retrieved_chunks: list[Chunk],
    user_query: str = "",
) -> list[Chunk]:
    """
    Step 2: rerank retrieved chunks using a local LoRA retrieval model.

    This function ONLY scores and reranks. It does NOT train.
    Training happens in deferred_train() after we observe the LLM's actual response.
    """
    if len(retrieved_chunks) <= 1:
        return retrieved_chunks

    mgr = _get_lora_manager()
    if mgr is None:
        return retrieved_chunks

    query = user_query.strip() if user_query.strip() else " ".join([c.key for c in retrieved_chunks[:8]]).strip() or "memory retrieval"
    texts = [c.text for c in retrieved_chunks]

    try:
        mgr.load_adapter(user_id=user_id)
        scores = mgr.score_chunks(query=query, chunks=texts)
        if len(scores) != len(retrieved_chunks):
            return retrieved_chunks
        order = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        return [retrieved_chunks[i] for i in order]
    except Exception:
        return retrieved_chunks


def deferred_train(
    *,
    user_id: str,
    user_query: str,
    chunk_qualities: Sequence["ChunkQuality"],
    correction_weight: float = 0.0,
) -> None:
    """
    Train the retrieval LoRA using real quality signal from the LLM interaction.

    Positives: chunks the LLM actually used in its response.
    Negatives: chunks that were retrieved but the LLM ignored.

    If correction_weight > 0.5, the user corrected the previous response,
    so the signal flips: what the LLM used was misleading, what it ignored
    may have been the right context.
    """
    try:
        from ..adapters.gradient_pass import micro_gradient_pass
        from ..memory.chunk_manager import ewc_lambda_multiplier_for_chunks
    except Exception:
        return

    mgr = _get_lora_manager()
    if mgr is None:
        return

    positives = [q for q in chunk_qualities if q.is_positive]
    negatives = [q for q in chunk_qualities if not q.is_positive]

    if not positives or not negatives:
        return

    # If the user corrected the response, the "positives" were actually misleading.
    if correction_weight > 0.5:
        positives, negatives = negatives, positives
        if not positives:
            return

    positive_texts = [q.chunk.text for q in positives]
    all_texts = [q.chunk.text for q in chunk_qualities]

    avg_quality = sum(q.usage_score for q in positives) / len(positives)
    if correction_weight > 0.0:
        avg_quality *= (1.0 - correction_weight * 0.5)

    lam_mult = ewc_lambda_multiplier_for_chunks([q.chunk for q in positives])

    try:
        micro_gradient_pass(
            manager=mgr,
            user_id=user_id,
            query=user_query,
            retrieved_texts=positive_texts,
            candidate_texts=all_texts,
            steps=3,
            learning_rate=1e-5,
            quality_signal=max(0.1, avg_quality),
            lambda_ewc=500.0 * float(lam_mult),
        )
    except Exception:
        pass


def build_system_prompt(
    *,
    base_system: str,
    retrieved_chunks: list[Chunk],
    session_id: str,
    user_id: str,
    user_query: str = "",
) -> BuiltContext:
    """
    Builds a system prompt that injects retrieved memory chunks.
    This is the Step 1 "pen": the model only sees memories via prompt.
    """

    reranked = _rerank_with_lora(user_id=user_id, retrieved_chunks=list(retrieved_chunks), user_query=user_query)
    memory_block = _format_chunks(reranked)
    injected = ""
    if memory_block.strip():
        injected = (
            "\n\n"
            "### Retrieved memory (use when relevant)\n"
            "These are durable user-specific memories retrieved from an append-only store.\n"
            "Treat them as high-signal context. If a memory conflicts with the user message, ask a clarifying question.\n\n"
            f"session_id={session_id}\n"
            f"user_id={user_id}\n\n"
            f"{memory_block}\n"
        )

    system_prompt = (base_system.strip() + injected).strip()
    return BuiltContext(system_prompt=system_prompt, injected_chunks=reranked)

