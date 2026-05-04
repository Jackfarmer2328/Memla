"""
Sleeping World: compressed simulated days; alliances, grudges, goals in replay state.
"""

from __future__ import annotations

from typing import Any

from .event_store import EventStore, WorldEvent


def sleeping_world_reducer(state: dict[str, Any], event: WorldEvent) -> dict[str, Any]:
    s = dict(state)
    if event.kind == "day_open":
        s["day"] = int(event.payload.get("day") or 0)
    elif event.kind == "alliance":
        a, b = str(event.payload.get("a")), str(event.payload.get("b"))
        if a and b and a != b:
            pairs = list(s.get("alliances") or [])
            pairs.append(sorted([a, b]))
            s["alliances"] = pairs
    elif event.kind == "grudge":
        a, b = str(event.payload.get("a")), str(event.payload.get("b"))
        if a and b and a != b:
            g = list(s.get("grudges") or [])
            g.append(sorted([a, b]))
            s["grudges"] = g
    elif event.kind == "goal_set":
        ent = str(event.payload.get("entity") or "")
        goal = str(event.payload.get("goal") or "")
        if ent:
            goals = dict(s.get("goals") or {})
            goals[ent] = goal
            s["goals"] = goals
    return s


def simulate_days(*, days: int = 30, rng_seed: int = 42) -> EventStore:
    """Deterministic pseudo-random autonomous ticks (no wall-clock wait)."""
    store = EventStore()
    r = rng_seed
    entities = [f"npc_{k}" for k in range(24)]

    def rand() -> int:
        nonlocal r
        r = (1103515245 * r + 12345) & 0x7FFFFFFF
        return r

    for day in range(1, days + 1):
        store.append(WorldEvent(f"d{day}_open", "day_open", {"day": day}))
        steps = 12
        for _ in range(steps):
            i = rand() % len(entities)
            j = rand() % len(entities)
            if i == j:
                continue
            a, b = entities[i], entities[j]
            kind_roll = rand() % 100
            if kind_roll < 38:
                store.append(WorldEvent(f"al_{day}_{rand()}", "alliance", {"a": a, "b": b}))
            elif kind_roll < 62:
                store.append(WorldEvent(f"gr_{day}_{rand()}", "grudge", {"a": a, "b": b}))
            else:
                store.append(
                    WorldEvent(
                        f"go_{day}_{rand()}",
                        "goal_set",
                        {"entity": a, "goal": f"survive_day_{day}_priority_{rand() % 5}"},
                    )
                )
    return store


def export_jsonl_lines(store: EventStore) -> list[str]:
    import json

    lines: list[str] = []
    for ev in store.events:
        lines.append(
            json.dumps(
                {"event_id": ev.event_id, "kind": ev.kind, "payload": ev.payload},
                sort_keys=True,
            )
        )
    return lines


def events_for_day(store: EventStore, day: int) -> list[WorldEvent]:
    """Slice events between day_open(day) and the next day_open."""
    out: list[WorldEvent] = []
    active = False
    for ev in store.events:
        if ev.kind == "day_open":
            d = int(ev.payload.get("day") or 0)
            if active and d != day:
                break
            if d == day:
                active = True
                out.append(ev)
            continue
        if active:
            out.append(ev)
    return out
