from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class WorldEvent:
    event_id: str
    kind: str
    payload: dict[str, Any]


Reducer = Callable[[dict[str, Any], WorldEvent], dict[str, Any]]


def default_reducer(state: dict[str, Any], event: WorldEvent) -> dict[str, Any]:
    """Fold events into a canonical world dict (fork-safe copy per step)."""
    next_state = dict(state)
    if event.kind == "fact_set":
        facts = dict(next_state.get("facts") or {})
        key = str(event.payload.get("key") or "")
        if key:
            facts[key] = event.payload.get("value")
        next_state["facts"] = facts
    elif event.kind == "entity_move":
        entities = dict(next_state.get("entities") or {})
        eid = str(event.payload.get("entity_id") or "")
        if eid:
            row = dict(entities.get(eid) or {})
            if "location" in event.payload:
                row["location"] = event.payload["location"]
            entities[eid] = row
        next_state["entities"] = entities
    elif event.kind == "tick":
        next_state["tick"] = int(next_state.get("tick") or 0) + 1
    return next_state


@dataclass
class EventStore:
    """Append-only event log with deterministic replay."""

    events: list[WorldEvent] = field(default_factory=list)

    def append(self, event: WorldEvent) -> None:
        self.events.append(event)

    def replay(self, reducer: Reducer | None = None, initial: dict[str, Any] | None = None) -> dict[str, Any]:
        fn = reducer or default_reducer
        state: dict[str, Any] = dict(initial or {})
        for ev in self.events:
            state = fn(state, ev)
        return state

    def replay_twice_equal(self, reducer: Reducer | None = None, initial: dict[str, Any] | None = None) -> bool:
        a = self.replay(reducer=reducer, initial=initial)
        b = self.replay(reducer=reducer, initial=initial)
        return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
