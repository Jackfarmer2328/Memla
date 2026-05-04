from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryRecord:
    text: str
    tags: tuple[str, ...] = ()
    importance: float = 0.5
    created_ts: float = field(default_factory=time.time)


@dataclass
class MemoryEngine:
    """Working + episodic tiers (single process; swap for DB later)."""

    episodic: list[MemoryRecord] = field(default_factory=list)
    working: list[MemoryRecord] = field(default_factory=list)
    max_episodic: int = 500

    def commit_to_episodic(self, text: str, *, tags: tuple[str, ...] = ()) -> MemoryRecord:
        rec = MemoryRecord(text=text, tags=tags, importance=0.7)
        self.episodic.append(rec)
        if len(self.episodic) > self.max_episodic:
            self.episodic.pop(0)
        return rec

    def working_push(self, text: str) -> None:
        self.working.append(MemoryRecord(text=text, tags=("working",), importance=1.0))
        if len(self.working) > 32:
            self.working.pop(0)

    def retrieve(self, query: str, *, top_k: int = 5) -> list[MemoryRecord]:
        q = set(query.lower().split())
        scored: list[tuple[float, MemoryRecord]] = []
        pool = list(self.working) + list(self.episodic)
        for rec in pool:
            words = set(rec.text.lower().split())
            overlap = len(q & words)
            score = overlap * 0.4 + rec.importance * 0.3 + (1.0 / (1.0 + time.time() - rec.created_ts)) * 0.1
            scored.append((score, rec))
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]]
