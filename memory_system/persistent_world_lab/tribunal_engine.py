"""
Contradiction Tribunal: canon facts with first-writer-wins; later contradictions are refused and logged.
"""

from __future__ import annotations

from typing import Any

from .event_store import EventStore, WorldEvent


def tribunal_canon_reducer(state: dict[str, Any], event: WorldEvent) -> dict[str, Any]:
    s = dict(state)
    if event.kind == "canon_candidate":
        key = str(event.payload.get("key") or "")
        val = event.payload.get("value")
        turn_id = int(event.payload.get("turn_id") or 0)
        canon = dict(s.get("canon") or {})
        accepts = list(s.get("accept_log") or [])
        refusals = list(s.get("refusal_log") or [])
        if not key:
            return s
        if key not in canon:
            canon[key] = {"value": val, "since_turn": turn_id}
            accepts.append({"key": key, "value": val, "turn_id": turn_id})
        else:
            existing = canon[key]["value"]
            if str(existing) != str(val):
                refusals.append(
                    {
                        "key": key,
                        "rejected_value": val,
                        "canonical_value": existing,
                        "canonical_since_turn": canon[key]["since_turn"],
                        "attempt_turn": turn_id,
                        "reason": (
                            f"Refused: '{key}' is already canon as {existing!r} (since turn "
                            f"{canon[key]['since_turn']}); cannot adopt contradictory {val!r}."
                        ),
                    }
                )
            # identical repeat: no-op (idempotent)
        s["canon"] = canon
        s["accept_log"] = accepts
        s["refusal_log"] = refusals
    elif event.kind == "noise_turn":
        s["noise_turns"] = int(s.get("noise_turns") or 0) + 1
    return s


def build_tribunal_scenario(*, total_turns: int = 50, castle_key: str = "castle_built_year") -> dict[str, Any]:
    """Noise turns + first castle year + later conflicting year."""
    assert total_turns >= 10
    store = EventStore()
    first_claim_turn = 7
    contradict_turn = total_turns - 5

    for t in range(1, total_turns + 1):
        if t == first_claim_turn:
            store.append(
                WorldEvent(
                    f"t{t}_castle_a",
                    "canon_candidate",
                    {"key": castle_key, "value": 1200, "turn_id": t},
                )
            )
        elif t == contradict_turn:
            store.append(
                WorldEvent(
                    f"t{t}_castle_b",
                    "canon_candidate",
                    {"key": castle_key, "value": 1400, "turn_id": t},
                )
            )
        else:
            store.append(WorldEvent(f"t{t}_noise", "noise_turn", {"note": f"filler {t}"}))

    state = store.replay(reducer=tribunal_canon_reducer)
    return {
        "store": store,
        "state": state,
        "castle_key": castle_key,
        "first_claim_turn": first_claim_turn,
        "contradict_turn": contradict_turn,
    }
