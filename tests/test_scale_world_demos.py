from __future__ import annotations

from pathlib import Path

from memory_system.persistent_world_lab.chorus_engine import recall_correct, run_chorus, consistency_ratio
from memory_system.persistent_world_lab.sleeping_world_engine import (
    events_for_day,
    simulate_days,
    sleeping_world_reducer,
)
from memory_system.persistent_world_lab.tribunal_engine import build_tribunal_scenario, tribunal_canon_reducer


def test_chorus_small_population_all_correct():
    r = run_chorus(population=80, noise_lines=25, top_k=8)
    assert r.correct == r.population
    assert consistency_ratio(r) == 1.0


def test_chorus_recall_single():
    from memory_system.persistent_world_lab.chorus_engine import _seed_npc_memory

    mem = _seed_npc_memory(42, noise_lines=30)
    assert recall_correct(mem, 42, top_k=5)


def test_tribunal_refuses_contradiction():
    out = build_tribunal_scenario(total_turns=50)
    refusals = out["state"].get("refusal_log") or []
    assert len(refusals) >= 1
    assert "1200" in str(refusals[0].get("canonical_value")) or refusals[0].get("canonical_value") == 1200
    assert out["store"].replay_twice_equal(reducer=tribunal_canon_reducer)


def test_sleeping_world_replay_and_day_slice():
    store = simulate_days(days=10, rng_seed=7)
    a = store.replay(reducer=sleeping_world_reducer)
    b = store.replay(reducer=sleeping_world_reducer)
    assert a == b
    d3 = events_for_day(store, 3)
    assert any(ev.kind == "day_open" for ev in d3)
    assert len(d3) >= 2


def test_sleeping_world_demo_json_only(tmp_path: Path, monkeypatch):
    """Avoid writing JSONL to repo root during tests."""
    import memory_system.persistent_world_lab.sleeping_world_demo as swd

    monkeypatch.chdir(tmp_path)
    assert swd.main(["--days", "5", "--json"]) == 0
    assert (tmp_path / "sleeping_world_events.jsonl").exists()
