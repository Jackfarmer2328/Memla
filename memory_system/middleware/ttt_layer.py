from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Optional

from ..memory.chunk_manager import ChunkManager
from ..memory.episode_log import EpisodeLog
from .context_builder import BuiltContext, build_system_prompt


@dataclass
class TurnArtifacts:
    session_id: str
    user_id: str
    user_episode_id: int
    created_chunk_ids: list[int]
    retrieved: list[Any]
    built: BuiltContext


class TTTLayer:
    """
    Step 1: "Output stream is the pen" as middleware.

    In Step 1 we keep it simple:
    - intercept user message -> extract/store chunks
    - retrieve top-k memories for the upcoming call
    - build a system prompt with injected memory
    - (optionally) log assistant response as an episode
    """

    def __init__(self, *, episode_log: EpisodeLog, chunk_manager: ChunkManager) -> None:
        self.log = episode_log
        self.chunks = chunk_manager
        self._last_retrieved: list[Any] = []

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
        return self.log.add_episode(
            session_id=session_id,
            user_id=user_id,
            role="assistant",
            content=assistant_text,
            meta=meta or {},
            ts=ts_i,
        )

