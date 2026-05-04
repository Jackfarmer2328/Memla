from __future__ import annotations

from memory_system.persistent_world_lab.white_room_director import (
    build_director_bundle,
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
    assert len(suite["checks"]) == 6
    assert all(bool(c["passed"]) for c in suite["checks"])
