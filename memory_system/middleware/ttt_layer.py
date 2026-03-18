from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from ..memory.chunk_manager import ChunkManager
from ..memory.episode_log import Chunk, EpisodeLog
from .context_builder import BuiltContext, build_system_prompt, deferred_train


@dataclass
class TurnArtifacts:
    session_id: str
    user_id: str
    user_episode_id: int
    created_chunk_ids: list[int]
    retrieved: list[Any]
    built: BuiltContext


@dataclass
class _PreviousTurn:
    """State from the last completed turn, used for correction detection."""
    user_query: str
    user_id: str
    retrieved: list[Chunk]
    chunk_qualities: list[Any] = field(default_factory=list)


class TTTLayer:
    """
    Turn-level middleware.

    Training flow (closed loop):
    1. on_user_message:  extract/store chunks, retrieve, build prompt.
                         If the previous turn exists, check for user correction
                         and apply retroactive negative signal.
    2. (externally):     LLM generates response.
    3. on_assistant_message: measure which chunks the LLM actually used,
                             train the retrieval LoRA with real quality signal.
    """

    def __init__(self, *, episode_log: EpisodeLog, chunk_manager: ChunkManager) -> None:
        self.log = episode_log
        self.chunks = chunk_manager
        self._last_retrieved: list[Any] = []
        self._prev_turn: Optional[_PreviousTurn] = None

    @property
    def last_retrieved(self) -> list[Any]:
        return self._last_retrieved

    def on_user_message(
        self,
        *,
        session_id: str,
        user_id: str,
        user_text: str,
        base_system: str,
        top_k: int = 12,
        ts: Optional[int] = None,
    ) -> TurnArtifacts:
        ts_i = int(ts if ts is not None else time.time())

        # --- Correction detection on the PREVIOUS turn ---
        if self._prev_turn is not None and self._prev_turn.chunk_qualities:
            try:
                from .quality import detect_correction
                correction = detect_correction(user_text)
                if correction > 0.3:
                    try:
                        deferred_train(
                            user_id=self._prev_turn.user_id,
                            user_query=self._prev_turn.user_query,
                            chunk_qualities=self._prev_turn.chunk_qualities,
                            correction_weight=correction,
                        )
                    except Exception:
                        pass
            except Exception:
                pass

        user_episode_id, created_chunk_ids = self.chunks.persist_user_message(
            session_id=session_id,
            user_id=user_id,
            user_text=user_text,
            ts=ts_i,
        )

        retrieved = self.chunks.retrieve(user_id=user_id, query_text=user_text, k=top_k)
        self._last_retrieved = list(retrieved)
        self.chunks.mark_recalled(retrieved)

        built = build_system_prompt(
            base_system=base_system,
            retrieved_chunks=list(retrieved),
            session_id=session_id,
            user_id=user_id,
            user_query=user_text,
        )

        # Prepare state for deferred training (completed in on_assistant_message).
        self._prev_turn = _PreviousTurn(
            user_query=user_text,
            user_id=user_id,
            retrieved=list(retrieved),
        )

        return TurnArtifacts(
            session_id=session_id,
            user_id=user_id,
            user_episode_id=user_episode_id,
            created_chunk_ids=created_chunk_ids,
            retrieved=list(retrieved),
            built=built,
        )

    def on_assistant_message(
        self,
        *,
        session_id: str,
        user_id: str,
        assistant_text: str,
        ts: Optional[int] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())

        episode_id = self.log.add_episode(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=assistant_text,
            meta=meta or {},
            ts=ts_i,
        )

        # --- Deferred training with real quality signal ---
        if self._prev_turn is not None and self._prev_turn.retrieved:
            try:
                from .quality import score_chunk_usage
                qualities = score_chunk_usage(
                    retrieved_chunks=self._prev_turn.retrieved,
                    assistant_response=assistant_text,
                )
                self._prev_turn.chunk_qualities = qualities

                deferred_train(
                    user_id=user_id,
                    user_query=self._prev_turn.user_query,
                    chunk_qualities=qualities,
                )
            except Exception:
                pass

        return episode_id

    def clear_turn_state(self) -> None:
        """Call on session reset to avoid cross-session correction detection."""
        self._prev_turn = None

