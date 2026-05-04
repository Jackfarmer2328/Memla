"""
Sleeping World: 30 *simulated* days of autonomous ticks (compressed time), full event log,
replay + JSONL DVR export.

Run:

  py -3 -m memory_system.persistent_world_lab.sleeping_world_demo
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .event_store import EventStore
from .sleeping_world_engine import (
    export_jsonl_lines,
    events_for_day,
    simulate_days,
    sleeping_world_reducer,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sleeping world (compressed autonomous simulation)")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--jsonl", type=Path, default=None, help="Write events JSONL (default: cwd sleeping_world_events.jsonl)")
    parser.add_argument("--seek-day", type=int, default=None, help="Print slice for this simulated day")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    store = simulate_days(days=args.days, rng_seed=args.seed)
    state = store.replay(reducer=sleeping_world_reducer)
    ok = store.replay_twice_equal(reducer=sleeping_world_reducer)

    jsonl_path = args.jsonl
    if jsonl_path is None:
        jsonl_path = Path.cwd() / "sleeping_world_events.jsonl"

    lines = export_jsonl_lines(store)
    jsonl_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    alliances = state.get("alliances") or []
    grudges = state.get("grudges") or []
    goals = state.get("goals") or {}

    if args.json:
        print(
            json.dumps(
                {
                    "sleeping_world_ok": True,
                    "replay_deterministic": ok,
                    "event_count": len(store.events),
                    "days_simulated": args.days,
                    "alliance_edges": len(alliances),
                    "grudge_edges": len(grudges),
                    "entities_with_goals": len(goals),
                    "jsonl_path": str(jsonl_path.resolve()),
                },
                indent=2,
            )
        )
        return 0 if ok else 1

    print("=== Sleeping World (time-compressed autonomous simulation) ===\n")
    print(f"Simulated days: {args.days} | RNG seed: {args.seed}")
    print(f"Total events: {len(store.events)}")
    print(f"Replay deterministic (twice equal): {'YES' if ok else 'NO'}")
    print(f"Alliance records (directed pairs logged): {len(alliances)}")
    print(f"Grudge records: {len(grudges)}")
    print(f"Latest goals per entity (sample): {dict(list(goals.items())[:5])}")
    print(f"\nDVR export (scrub in editor or jq):\n  {jsonl_path.resolve()}")

    if args.seek_day is not None:
        day_ev = events_for_day(store, args.seek_day)
        print(f"\n--- Seek day {args.seek_day} ({len(day_ev)} events) ---")
        for ev in day_ev[:24]:
            print(f"  {ev.kind} {ev.payload}")
        if len(day_ev) > 24:
            print(f"  ... ({len(day_ev) - 24} more that day)")

    print(
        "\nNote: '30 days' is simulated game time in one process pass — "
        "proof is replayable canon + exported log, not wall-clock soak.\n"
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
