from __future__ import annotations

from memory_system.persistent_world_lab.white_room_director import (
    creator_counterfactual_studio,
    build_counterfactual_bundle,
    build_director_bundle,
    explain_relation,
    simulate_player_entry,
    white_room_director_suite,
)


def test_white_room_bundle_structure():
    bundle = build_director_bundle(days=30, seed=777)
    assert bundle["days"] == 30
    assert len(bundle["cast"]) == 8
    assert bundle["player_present"] is False
    assert "30" in bundle["timeline"]
    assert bundle["proof"]["replay_verified"] is True


def test_white_room_suite_passes():
    suite = white_room_director_suite(days=30, seed=777)
    assert suite["backtest_id"] == "white_room_director_suite"
    assert suite["passed"] is True
    assert len(suite["checks"]) == 12
    assert all(bool(c["passed"]) for c in suite["checks"])


def test_explainability_chain_has_event_ids():
    bundle = build_director_bundle(days=30, seed=777)
    state = bundle["timeline"]["30"]
    rel = state["relations"][0]
    exp = explain_relation(bundle=bundle, day=30, a=rel["a"], b=rel["b"])
    assert exp["causal_chain"]
    assert all(bool(row["event_id"]) for row in exp["causal_chain"])


def test_counterfactual_creates_divergence():
    fork = build_counterfactual_bundle(days=30, seed=777, fork_day=16, a="aldric", b="crath", forced_relation="alliance")
    assert int(fork["comparison"]["changed_count"]) > 0
    assert int(fork["rewrite_count"]) > 0


def test_player_entry_cites_prehistory():
    bundle = build_director_bundle(days=30, seed=777)
    entry = simulate_player_entry(
        bundle=bundle,
        day=30,
        npc_id="aldric",
        player_message="Who were your allies before I arrived?",
    )
    assert entry["prehistory_count"] > 0
    assert entry["cited_event_ids"]


def test_canon_vs_belief_divergence_exists():
    bundle = build_director_bundle(days=30, seed=777)
    beliefs = bundle["belief_timeline"]["30"]
    assert int(beliefs["divergence_count"]) > 0
    assert beliefs["npc_beliefs"]


def test_narrative_compiler_passes_at_day_30():
    bundle = build_director_bundle(days=30, seed=777)
    report = bundle["narrative_timeline"]["30"]
    assert report["passed"] is True
    assert len(report["rules"]) == 3


def test_creator_studio_returns_ranked_scenarios():
    studio = creator_counterfactual_studio(days=30, seed=777, top_k=5)
    assert studio["passed"] is True
    assert int(studio["scenario_count"]) >= 2
    assert studio["scenarios"]
