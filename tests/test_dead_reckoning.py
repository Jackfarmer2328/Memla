from __future__ import annotations

from pathlib import Path

from memory_system.persistent_world_lab.dead_reckoning_codec import (
    build_bundle,
    bundle_dumps,
    bundle_loads,
    event_store_from_dict_list,
    event_store_to_dict_list,
    memory_engine_from_dict,
    memory_engine_to_dict,
    parse_bundle,
    verify_replay_matches_checkpoint,
    world_states_equal,
)
from memory_system.persistent_world_lab.event_store import EventStore, WorldEvent
from memory_system.persistent_world_lab.memory_engine import MemoryEngine
from memory_system.persistent_world_lab.npc_agent import NPCAgent


def test_memory_engine_round_trip():
    m = MemoryEngine()
    m.commit_to_episodic("hello world", tags=("a", "b"))
    m.working_push("short")
    d = memory_engine_to_dict(m)
    m2 = memory_engine_from_dict(d)
    assert len(m2.episodic) == 1
    assert m2.episodic[0].text == "hello world"
    assert m2.episodic[0].tags == ("a", "b")
    assert len(m2.working) == 1


def test_event_list_round_trip():
    s = EventStore()
    s.append(WorldEvent("1", "tick", {}))
    s.append(WorldEvent("2", "fact_set", {"key": "k", "value": "v"}))
    lst = event_store_to_dict_list(s)
    s2 = event_store_from_dict_list(lst)
    assert world_states_equal(s.replay(), s2.replay())


def test_bundle_world_checkpoint_stable():
    store = EventStore()
    store.append(WorldEvent("t", "tick", {}))
    npc = NPCAgent("n", {"role": "r"})
    npc.act("ping")
    bundle = build_bundle(store, npc)
    raw = bundle_dumps(bundle)
    data = bundle_loads(raw)
    store2, _, expected = parse_bundle(data)
    assert verify_replay_matches_checkpoint(store2, expected)


def test_dead_reckoning_two_phase_simulated(tmp_path: Path):
    """Same disk lifecycle as the demo: phase1 write, phase2 load + verify + continue."""
    from memory_system.persistent_world_lab.dead_reckoning_demo import run_phase1, run_phase2

    state_path = tmp_path / "dead_reckoning.state.json"
    run_phase1(state_path)
    assert state_path.exists()

    exit_code = run_phase2(state_path)
    assert exit_code == 0

    data = bundle_loads(state_path.read_text(encoding="utf-8"))
    _, npc_after_parse, _ = parse_bundle(data)
    assert npc_after_parse.session_turns == 1
