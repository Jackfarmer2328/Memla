"""Serialize / deserialize event log + NPC bundle for cold-start continuity (Dead Reckoning)."""

from __future__ import annotations

import json
from typing import Any

from .event_store import EventStore, WorldEvent
from .memory_engine import MemoryEngine, MemoryRecord
from .npc_agent import NPCAgent

BUNDLE_VERSION = 1


def world_event_to_dict(ev: WorldEvent) -> dict[str, Any]:
    return {"event_id": ev.event_id, "kind": ev.kind, "payload": dict(ev.payload)}


def world_event_from_dict(d: dict[str, Any]) -> WorldEvent:
    return WorldEvent(str(d["event_id"]), str(d["kind"]), dict(d.get("payload") or {}))


def memory_record_to_dict(rec: MemoryRecord) -> dict[str, Any]:
    return {
        "text": rec.text,
        "tags": list(rec.tags),
        "importance": rec.importance,
        "created_ts": rec.created_ts,
    }


def memory_record_from_dict(d: dict[str, Any]) -> MemoryRecord:
    tags = tuple(str(x) for x in (d.get("tags") or []))
    return MemoryRecord(
        text=str(d["text"]),
        tags=tags,
        importance=float(d.get("importance", 0.5)),
        created_ts=float(d["created_ts"]),
    )


def memory_engine_to_dict(mem: MemoryEngine) -> dict[str, Any]:
    return {
        "episodic": [memory_record_to_dict(r) for r in mem.episodic],
        "working": [memory_record_to_dict(r) for r in mem.working],
        "max_episodic": mem.max_episodic,
    }


def memory_engine_from_dict(d: dict[str, Any]) -> MemoryEngine:
    m = MemoryEngine(max_episodic=int(d.get("max_episodic", 500)))
    m.episodic = [memory_record_from_dict(x) for x in d.get("episodic") or []]
    m.working = [memory_record_from_dict(x) for x in d.get("working") or []]
    return m


def event_store_to_dict_list(store: EventStore) -> list[dict[str, Any]]:
    return [world_event_to_dict(ev) for ev in store.events]


def event_store_from_dict_list(events: list[dict[str, Any]]) -> EventStore:
    store = EventStore()
    for ed in events:
        store.append(world_event_from_dict(ed))
    return store


def npc_agent_to_dict(npc: NPCAgent) -> dict[str, Any]:
    return {
        "npc_id": npc.npc_id,
        "traits": dict(npc.traits),
        "session_turns": npc.session_turns,
        "memory": memory_engine_to_dict(npc.memory),
    }


def npc_agent_from_dict(d: dict[str, Any]) -> NPCAgent:
    npc = NPCAgent(
        npc_id=str(d["npc_id"]),
        traits=dict(d.get("traits") or {}),
        memory=memory_engine_from_dict(d.get("memory") or {}),
    )
    npc.session_turns = int(d.get("session_turns", 0))
    return npc


def build_bundle(store: EventStore, npc: NPCAgent) -> dict[str, Any]:
    state = store.replay()
    return {
        "bundle_version": BUNDLE_VERSION,
        "events": event_store_to_dict_list(store),
        "npc": npc_agent_to_dict(npc),
        "expected_world_state": state,
    }


def parse_bundle(data: dict[str, Any]) -> tuple[EventStore, NPCAgent, dict[str, Any]]:
    ver = int(data.get("bundle_version", 1))
    if ver != BUNDLE_VERSION:
        raise ValueError(f"unsupported bundle_version: {ver}")
    store = event_store_from_dict_list(list(data.get("events") or []))
    npc = npc_agent_from_dict(dict(data.get("npc") or {}))
    expected = dict(data.get("expected_world_state") or {})
    return store, npc, expected


def bundle_dumps(bundle: dict[str, Any]) -> str:
    return json.dumps(bundle, sort_keys=True, indent=2)


def bundle_loads(s: str) -> dict[str, Any]:
    return json.loads(s)


def world_states_equal(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def verify_replay_matches_checkpoint(store: EventStore, expected_world_state: dict[str, Any]) -> bool:
    actual = store.replay()
    return world_states_equal(actual, expected_world_state)
