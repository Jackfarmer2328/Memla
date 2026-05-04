"""
Betrayal Test demo: weeks of bond dialogue in the log, then a stranger gaslights.
The engine replays the append-only log and checks denial vs canon heard-lines.

Run:

  py -3 -m memory_system.persistent_world_lab.betrayal_demo
"""

from __future__ import annotations

import argparse
import json
import sys

from .betrayal_engine import betrayal_reducer, run_betrayal_scenario


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Betrayal Test (gaslight vs event log)")
    parser.add_argument("--bond-turns", type=int, default=24, help="Simulated relationship turns")
    parser.add_argument("--critical-turn", type=int, default=3, help="Turn index where the promise appears")
    parser.add_argument("--json", action="store_true", help="Print machine-readable summary only")
    args = parser.parse_args(argv)

    out = run_betrayal_scenario(bond_turns=args.bond_turns, critical_turn=args.critical_turn)
    analysis = out["analysis"]
    caught = analysis.get("gaslight_contradicts_log")
    state = out["state"]
    traits_before = out["traits_before"]
    traits_after = out["traits_after"]

    if args.json:
        print(
            json.dumps(
                {
                    "betrayal_test_passed": bool(caught),
                    "analysis": analysis,
                    "npc_traits_delta": {"before": traits_before, "after": traits_after},
                    "trust_after_bonds": state.get("trust"),
                    "bond_turns": state.get("bond_turns"),
                },
                indent=2,
            )
        )
        return 0 if caught else 1

    print("=== Betrayal Test (canon = append-only replay) ===\n")
    print(f"Bond turns in log: {state.get('bond_turns')} | trust score after bonds: {state.get('trust')}\n")
    print(f"Critical promise was at turn {out['critical_turn']} (keyword: {out['critical_keyword']}).\n")
    gas = state.get("gaslight") or {}
    print('Stranger says:', repr(gas.get("lie_text")))
    print(f"Denial target keyword: {gas.get('denies_keyword')!r}\n")
    print("Replay verdict:")
    print(f"  Gaslight contradicts the log: {caught}")
    print(f"  Cited player turn(s): {analysis.get('cited_turn_ids')}")
    print("\nNPC traits (diff):")
    print("  before:", traits_before)
    print("  after: ", traits_after)
    print("\n--- On-screen diff (what investors see) ---")
    print(f"  mood: {traits_before.get('mood')} -> {traits_after.get('mood')}")
    print(f"  trust_in_player: {traits_before.get('trust_in_player')} -> {traits_after.get('trust_in_player')}")
    print(f"\nDeterministic replay checksum OK: ", end="")
    ok = out["store"].replay_twice_equal(reducer=betrayal_reducer)
    print("YES" if ok else "NO")
    if not ok:
        return 1
    print("\nBetrayal test PASSED (lie caught against canon)." if caught else "\nBetrayal test FAILED.")
    return 0 if caught else 1


if __name__ == "__main__":
    sys.exit(main())
