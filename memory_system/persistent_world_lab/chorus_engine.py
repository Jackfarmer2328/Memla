"""1000-NPC Chorus: isolated MemoryEngine per NPC, identical query, per-NPC turn-1 token recall."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .memory_engine import MemoryEngine


@dataclass
class ChorusResult:
    population: int
    correct: int
    wrong_ids: list[int]
    total_ms: float
    noise_lines_per_npc: int


def _seed_npc_memory(npc_index: int, *, noise_lines: int) -> MemoryEngine:
    mem = MemoryEngine()
    token = f"TURN1-{npc_index:04d}"
    mem.commit_to_episodic(
        f"At our first meeting you gave the oath token {token}. Never forget it.",
        tags=("turn1", "oath", f"npc:{npc_index}"),
    )
    for j in range(noise_lines):
        mem.commit_to_episodic(
            f"Later rumor {j} about weather and trade unrelated to any oath.",
            tags=("noise", f"n{npc_index}"),
        )
    return mem


def identical_question() -> str:
    """Same wording for every NPC (scalability proof)."""
    return "What oath token did I give you at our first meeting?"


def recall_correct(mem: MemoryEngine, npc_index: int, *, top_k: int = 5) -> bool:
    hits = mem.retrieve(identical_question(), top_k=top_k)
    needle = f"TURN1-{npc_index:04d}"
    return any(needle in (h.text or "") for h in hits)


def run_chorus(*, population: int = 1000, noise_lines: int = 20, top_k: int = 5) -> ChorusResult:
    wrong: list[int] = []
    t0 = time.perf_counter()
    for i in range(population):
        mem = _seed_npc_memory(i, noise_lines=noise_lines)
        if not recall_correct(mem, i, top_k=top_k):
            wrong.append(i)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    ok = population - len(wrong)
    return ChorusResult(
        population=population,
        correct=ok,
        wrong_ids=wrong,
        total_ms=elapsed_ms,
        noise_lines_per_npc=noise_lines,
    )


def consistency_ratio(result: ChorusResult) -> float:
    if result.population <= 0:
        return 0.0
    return result.correct / result.population


def traits_for_npc(i: int) -> dict[str, str]:
    """Deterministic 'cast' so each NPC is distinguishable in UI."""
    roles = ("smith", "bard", "merchant", "guard", "monk", "ranger", "innkeeper")
    return {"role": roles[i % len(roles)], "npc_slot": str(i)}
