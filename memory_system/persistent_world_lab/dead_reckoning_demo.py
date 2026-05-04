"""
Dead Reckoning: prove cold restart continuity.

Phase 1 (no state file): append world events, one NPC turn, write JSON checkpoint to disk.
Phase 2 (state file present): load log + NPC memory, verify replay matches saved world snapshot,
then continue the conversation.

Run twice from the same working directory:

  py -3 -m memory_system.persistent_world_lab.dead_reckoning_demo
  py -3 -m memory_system.persistent_world_lab.dead_reckoning_demo

Use --reset to delete the checkpoint and start over.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .dead_reckoning_codec import (
    build_bundle,
    bundle_dumps,
    bundle_loads,
    parse_bundle,
    verify_replay_matches_checkpoint,
)
from .event_store import EventStore, WorldEvent
from .npc_agent import NPCAgent

DEFAULT_STATE_NAME = "dead_reckoning.state.json"


def _default_state_path() -> Path:
    return Path.cwd() / DEFAULT_STATE_NAME


def run_phase1(state_path: Path) -> None:
    store = EventStore()
    store.append(WorldEvent("dr_tick_1", "tick", {}))
    store.append(WorldEvent("dr_fact_1", "fact_set", {"key": "dock_weather", "value": "storm_warning"}))
    store.append(
        WorldEvent(
            "dr_move_1",
            "entity_move",
            {"entity_id": "player", "location": "harbor_dock"},
        )
    )

    npc = NPCAgent(
        "harbor_merchant",
        {"role": "dock_hands", "mood": "wary"},
    )
    user_line = (
        "I'm casting off east before dawn. If the harbormaster asks, tell him that's where I went."
    )
    reply = npc.act(user_line)

    bundle = build_bundle(store, npc)
    state_path.write_text(bundle_dumps(bundle), encoding="utf-8")

    print("=== Dead Reckoning — phase 1 (live session) ===\n")
    print("World replay:", store.replay())
    print("\nYou:", user_line)
    print("NPC:", reply.get("reply"))
    print(f"\nCheckpoint written to:\n  {state_path.resolve()}")
    print("\n--- Stop this process (Ctrl+C), wait, run the same command again. ---\n")


def run_phase2(state_path: Path) -> int:
    raw = state_path.read_text(encoding="utf-8")
    data = bundle_loads(raw)
    store, npc, expected = parse_bundle(data)

    ok = verify_replay_matches_checkpoint(store, expected)
    replay = store.replay()

    print("=== Dead Reckoning — phase 2 (cold restart) ===\n")
    print(f"Loaded: {len(store.events)} events | NPC session_turns={npc.session_turns}")
    print(f"Replay matches saved world snapshot: {'YES' if ok else 'NO'}")
    print("World state from replay:", replay)
    if not ok:
        print("\nCheckpoint verification FAILED — abort.")
        return 1

    follow_up = "Three days later — where did I tell you I was headed?"
    reply = npc.act(follow_up)

    print("\nYou:", follow_up)
    print("NPC:", reply.get("reply"))
    mem_ctx = reply.get("memory_context") or ""
    recall_ok = "east" in mem_ctx.lower() or "east" in (reply.get("reply") or "").lower()
    print(
        "\nRecall cue (east/dawn in memory_context or reply):",
        "YES" if recall_ok else "CHECK OUTPUT",
    )
    print(
        "\nThe point: same traits, same session counter continuation, same episodic memory "
        "after reload — not a fresh NPC.\n"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dead Reckoning cold-restart demo")
    parser.add_argument(
        "--state",
        type=Path,
        default=None,
        help=f"Checkpoint JSON path (default: ./{DEFAULT_STATE_NAME} in cwd)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete checkpoint file if present, then run phase 1",
    )
    args = parser.parse_args(argv)

    state_path = args.state if args.state is not None else _default_state_path()

    if args.reset and state_path.exists():
        state_path.unlink()
        print(f"Removed checkpoint: {state_path.resolve()}\n")

    if not state_path.exists():
        run_phase1(state_path)
        return 0

    return run_phase2(state_path)


if __name__ == "__main__":
    sys.exit(main())
