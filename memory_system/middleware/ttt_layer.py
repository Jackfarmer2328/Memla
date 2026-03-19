from __future__ import annotations

import threading
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
    """State from the last completed turn, used for correction detection + backward extraction."""
    user_query: str
    user_id: str
    session_id: str
    retrieved: list[Chunk]
    assistant_text: str = ""
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
        self._is_correction_turn = False

        # --- Correction detection on the PREVIOUS turn (background) ---
        if self._prev_turn is not None and self._prev_turn.chunk_qualities:
            try:
                from .quality import detect_correction
                correction = detect_correction(user_text)
                if correction > 0.3:
                    self._is_correction_turn = True
                    prev = self._prev_turn

                    def _bg_correction(uid=prev.user_id, uq=prev.user_query,
                                       cq=list(prev.chunk_qualities), cw=correction):
                        try:
                            deferred_train(user_id=uid, user_query=uq,
                                           chunk_qualities=cq, correction_weight=cw)
                        except Exception:
                            pass

                    threading.Thread(target=_bg_correction, daemon=True).start()
            except Exception:
                pass

        # --- Backward extraction (C8): mine the assistant's last response ---
        # If the user's reply is a continuation (not a correction), the assistant
        # response contains knowledge the user implicitly confirmed as useful.
        # Filter assistant sentences by overlap with the user's new message.
        if (self._prev_turn is not None
                and self._prev_turn.assistant_text
                and not self._is_correction_turn):
            self._backward_extract(
                assistant_text=self._prev_turn.assistant_text,
                user_filter=user_text,
                session_id=self._prev_turn.session_id,
                user_id=self._prev_turn.user_id,
                ts=ts_i,
            )

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
            session_id=session_id,
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

        # Store assistant response for backward extraction in the next user turn.
        if self._prev_turn is not None:
            self._prev_turn.assistant_text = assistant_text

        # --- Deferred training with real quality signal (background) ---
        if self._prev_turn is not None and self._prev_turn.retrieved:
            try:
                from .quality import score_chunk_usage
                qualities = score_chunk_usage(
                    retrieved_chunks=self._prev_turn.retrieved,
                    assistant_response=assistant_text,
                )
                self._prev_turn.chunk_qualities = qualities

                def _bg_train(uid=user_id, uq=self._prev_turn.user_query,
                              cq=list(qualities)):
                    try:
                        deferred_train(user_id=uid, user_query=uq,
                                       chunk_qualities=cq)
                    except Exception:
                        pass

                threading.Thread(target=_bg_train, daemon=True).start()
            except Exception:
                pass

        return episode_id

    def explicit_feedback(self, *, is_positive: bool) -> bool:
        """
        User invoked /good or /bad on the last response.

        /good: high-confidence positive signal (quality_signal=1.0).
        /bad:  high-confidence correction (correction_weight=1.0, flips signal).

        Returns True if feedback was applied, False if no previous turn exists.
        """
        if self._prev_turn is None or not self._prev_turn.chunk_qualities:
            return False

        prev = self._prev_turn

        if is_positive:
            def _bg(uid=prev.user_id, uq=prev.user_query,
                    cq=list(prev.chunk_qualities)):
                try:
                    deferred_train(user_id=uid, user_query=uq,
                                   chunk_qualities=cq, correction_weight=0.0)
                except Exception:
                    pass
        else:
            def _bg(uid=prev.user_id, uq=prev.user_query,
                    cq=list(prev.chunk_qualities)):
                try:
                    deferred_train(user_id=uid, user_query=uq,
                                   chunk_qualities=cq, correction_weight=1.0)
                except Exception:
                    pass

        threading.Thread(target=_bg, daemon=True).start()
        return True

    def _backward_extract(
        self, *, assistant_text: str, user_filter: str,
        session_id: str, user_id: str, ts: int,
    ) -> None:
        """C8: Extract chunks from the assistant's response, filtered by the user's reply.

        The user's continuation message acts as a relevance filter: only assistant
        sentences that share keywords with the user's new message get persisted as
        confirmed knowledge.
        """
        import re
        filter_tokens = set(re.findall(r"[a-zA-Z0-9_]+", user_filter.lower()))
        filter_tokens -= {"a", "an", "the", "is", "are", "was", "were", "i", "you",
                          "it", "that", "this", "my", "your", "we", "they", "he", "she",
                          "and", "or", "but", "for", "to", "in", "on", "of", "at", "by",
                          "not", "be", "have", "has", "do", "did", "will", "can", "with"}
        if len(filter_tokens) < 2:
            return

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", assistant_text) if len(s.strip()) >= 20]
        for s in sentences[:10]:
            s_tokens = set(re.findall(r"[a-zA-Z0-9_]+", s.lower()))
            overlap = len(filter_tokens & s_tokens)
            if overlap < 2:
                continue
            key = re.sub(r"[^a-zA-Z0-9_ ]+", " ", s[:80].lower()).strip()[:256]
            try:
                self.log.add_or_bump_chunk(
                    session_id=session_id,
                    user_id=user_id,
                    chunk_type="fact",
                    key=key,
                    text=f"[Confirmed] {s}",
                    source_episode_id=None,
                    meta={"source": "backward_extract_c8"},
                    ts=ts,
                )
            except Exception:
                pass

    def clear_turn_state(self) -> None:
        """Call on session reset to avoid cross-session correction detection."""
        self._prev_turn = None

