from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ..memory.episode_log import Chunk


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
) -> list[Chunk]:
    """
    Step 2: rerank retrieved chunks using a local LoRA retrieval model.

    Constraints:
    - Ollama stays untouched (generation remains black-box).
    - If HF download/load is unavailable, fall back silently (no exceptions).

    Note:
    We only see `retrieved_chunks` here (selected upstream by SQLite + heuristic retrieval).
    This layer is a reranker, not a retriever.
    """
    if len(retrieved_chunks) <= 1:
        return retrieved_chunks

    try:
        from ..adapters.lora_manager import RetrievalLoRAManager
        from ..memory.chunk_manager import ewc_lambda_multiplier_for_chunks
    except Exception:
        return retrieved_chunks

    # Build a query from the chunk keys/texts we already have.
    # We cannot access the raw user message here due to Step 2 constraints (no changes to TTT/main).
    query = " ".join([c.key for c in retrieved_chunks[:8]]).strip() or "memory retrieval"
    texts = [c.text for c in retrieved_chunks]

    mgr = RetrievalLoRAManager()
    try:
        # Load adapter if present; if missing, scoring still works but will be untrained.
        mgr.load_adapter(user_id=user_id)
        scores = mgr.score_chunks(query=query, chunks=texts)
        if len(scores) != len(retrieved_chunks):
            return retrieved_chunks
        order = sorted(range(len(scores)), key=lambda i: float(scores[i]), reverse=True)
        reranked = [retrieved_chunks[i] for i in order]

        # Opportunistic micro-update (very small) so the retrieval adapter improves over time,
        # without requiring changes to main/TTT.
        # Training signal: treat higher-scored chunks as positives within this candidate set.
        try:
            from ..adapters.gradient_pass import micro_gradient_pass

            top_n = max(1, min(4, len(reranked) // 2))
            retrieved_texts = [c.text for c in reranked[:top_n]]
            candidate_texts = [c.text for c in reranked]
            lam_mult = ewc_lambda_multiplier_for_chunks(reranked[:top_n])
            micro_gradient_pass(
                manager=mgr,
                user_id=user_id,
                query=query,
                retrieved_texts=retrieved_texts,
                candidate_texts=candidate_texts,
                steps=3,
                learning_rate=1e-5,
                quality_signal=None,
                lambda_ewc=500.0 * float(lam_mult),
            )
        except Exception:
            pass

        return reranked
    except Exception:
        # Silent fallback: never break the chat loop.
        return retrieved_chunks


def build_system_prompt(
    *,
    base_system: str,
    retrieved_chunks: list[Chunk],
    session_id: str,
    user_id: str,
) -> BuiltContext:
    """
    Builds a system prompt that injects retrieved memory chunks.
    This is the Step 1 "pen": the model only sees memories via prompt.
    """

    reranked = _rerank_with_lora(user_id=user_id, retrieved_chunks=list(retrieved_chunks))
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

