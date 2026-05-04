"""Smoke demo: event replay + NPC turn + backtest bundle."""

from __future__ import annotations

import sys

from .backtests import run_all_backtests
from .event_store import EventStore, WorldEvent
from .npc_agent import NPCAgent


def main() -> None:
    store = EventStore()
    store.append(WorldEvent("e1", "tick", {}))
    store.append(WorldEvent("e2", "fact_set", {"key": "season", "value": "spring"}))
    state = store.replay()
    print("replay_state:", state)

    npc = NPCAgent("merchant_a", {"role": "merchant"})
    print(npc.act("Do you remember any rumors about the bridge?"))

    summary = run_all_backtests()
    print("backtests_all_passed:", summary["all_passed"])
    for row in summary["results"]:
        bid = row.get("backtest_id")
        ok = row.get("passed")
        print(f"  {bid}: {'PASS' if ok else 'FAIL'}")
    sys.exit(0 if summary["all_passed"] else 1)


if __name__ == "__main__":
    main()
