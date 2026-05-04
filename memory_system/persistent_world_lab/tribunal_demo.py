"""
Contradiction Tribunal: 50-turn feed with a deliberate contradiction on castle year.
Canon refuses the second value and records reasoning.

Run:

  py -3 -m memory_system.persistent_world_lab.tribunal_demo
"""

from __future__ import annotations

import argparse
import json
import sys

from .event_store import EventStore
from .tribunal_engine import build_tribunal_scenario, tribunal_canon_reducer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Contradiction tribunal (canon hygiene)")
    parser.add_argument("--turns", type=int, default=50)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    out = build_tribunal_scenario(total_turns=args.turns)
    state = out["state"]
    store: EventStore = out["store"]
    refusals = state.get("refusal_log") or []

    ok_replay = store.replay_twice_equal(reducer=tribunal_canon_reducer)
    passed = len(refusals) >= 1 and ok_replay

    if args.json:
        print(
            json.dumps(
                {
                    "tribunal_passed": passed,
                    "replay_deterministic": ok_replay,
                    "canon": state.get("canon"),
                    "refusal_log": refusals,
                    "accept_count": len(state.get("accept_log") or []),
                },
                indent=2,
            )
        )
        return 0 if passed else 1

    print("=== Contradiction Tribunal (append-only + canon reducer) ===\n")
    print(f"Turns in log: {len(store.events)}")
    print(f"Castle key: {out['castle_key']}")
    print(f"First claim turn: {out['first_claim_turn']} | Contradiction attempt turn: {out['contradict_turn']}\n")
    print("Canon after replay:")
    print(" ", json.dumps(state.get("canon"), indent=2))
    print("\nGovernor refusals (epistemic hygiene):")
    for r in refusals:
        print(" ", r.get("reason"))
    print(f"\nReplay deterministic (twice equal): {'YES' if ok_replay else 'NO'}")
    print("\nPASS: contradiction refused with logged reasoning." if passed else "\nFAIL.")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
