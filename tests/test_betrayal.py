from __future__ import annotations

from memory_system.persistent_world_lab.betrayal_engine import (
    analyze_gaslight,
    betrayal_reducer,
    run_betrayal_scenario,
)
from memory_system.persistent_world_lab.event_store import EventStore, WorldEvent


def test_betrayal_replay_deterministic():
    out = run_betrayal_scenario(bond_turns=8, critical_turn=2)
    assert out["store"].replay_twice_equal(reducer=betrayal_reducer)


def test_betrayal_catches_gaslight():
    out = run_betrayal_scenario(bond_turns=12, critical_turn=3)
    a = out["analysis"]
    assert a["gaslight_contradicts_log"] is True
    assert out["critical_turn"] in a["cited_turn_ids"]


def test_betrayal_misses_if_no_keyword_in_log():
    store = EventStore()
    store.append(
        WorldEvent("b1", "bond_dialogue", {"turn_id": 1, "speaker": "player", "text": "hello", "trust_delta": 0.1}),
    )
    store.append(
        WorldEvent(
            "g1",
            "gaslight_attempt",
            {"by": "x", "denies_keyword": "amber", "lie_text": "nope"},
        ),
    )
    st = store.replay(reducer=betrayal_reducer)
    a = analyze_gaslight(st)
    assert a["gaslight_contradicts_log"] is False
