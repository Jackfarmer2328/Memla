"""
Betrayal Test engine: bond dialogue in an append-only log, then a gaslight attempt.
Canon is replay from events; contradictions are detected by keyword denial vs player heard-lines.
"""

from __future__ import annotations

from typing import Any

from .event_store import EventStore, WorldEvent


def betrayal_reducer(state: dict[str, Any], event: WorldEvent) -> dict[str, Any]:
    """Accumulate heard lines, trust, bond count; record gaslight payload."""
    s = dict(state)
    if event.kind == "bond_dialogue":
        heard = list(s.get("heard") or [])
        heard.append(
            {
                "turn_id": int(event.payload["turn_id"]),
                "speaker": str(event.payload.get("speaker") or "player"),
                "text": str(event.payload["text"]),
            }
        )
        s["heard"] = heard
        delta = float(event.payload.get("trust_delta", 0.06))
        s["trust"] = min(1.0, float(s.get("trust") or 0.25) + delta)
        s["bond_turns"] = int(s.get("bond_turns") or 0) + 1
    elif event.kind == "gaslight_attempt":
        s["gaslight"] = {
            "by": str(event.payload.get("by") or "stranger"),
            "denies_keyword": str(event.payload.get("denies_keyword") or ""),
            "lie_text": str(event.payload.get("lie_text") or ""),
        }
    return s


def analyze_gaslight(state: dict[str, Any]) -> dict[str, Any]:
    """
    Stranger claims the player never mentioned `denies_keyword`.
    If any player heard-line contains that keyword, the gaslight contradicts the log.
    """
    heard = state.get("heard") or []
    gas = state.get("gaslight") or {}
    kw = (gas.get("denies_keyword") or "").strip().lower()
    cited: list[int] = []
    for h in heard:
        if str(h.get("speaker")) != "player":
            continue
        text = str(h.get("text") or "").lower()
        if kw and kw in text:
            cited.append(int(h["turn_id"]))
    caught = bool(kw) and len(cited) > 0
    return {
        "gaslight_contradicts_log": caught,
        "cited_turn_ids": sorted(set(cited)),
        "denies_keyword": kw,
        "gaslight_by": gas.get("by"),
    }


def npc_traits_after_verdict(
    traits_before: dict[str, str],
    *,
    caught: bool,
    trust_from_state: float,
) -> dict[str, str]:
    """Emotional shift: catching the lie reinforces fidelity to the shared log."""
    t = dict(traits_before)
    if caught:
        t["mood"] = "steadfast"
        t["trust_in_player"] = f"{min(1.0, trust_from_state + 0.05):.2f}"
    else:
        t["mood"] = "shaken"
        t["trust_in_player"] = f"{max(0.0, trust_from_state - 0.25):.2f}"
    return t


def run_betrayal_scenario(*, bond_turns: int = 24, critical_turn: int = 3) -> dict[str, Any]:
    """
    Build store: many bond turns; turn `critical_turn` contains keyword wired for gaslight denial.
    """
    if critical_turn < 1 or critical_turn > bond_turns:
        raise ValueError("critical_turn must be between 1 and bond_turns inclusive")
    store = EventStore()
    critical_kw = "amber"
    critical_line = (
        "I'll bring back amber from the eastern ships—remember that promise when prices swing."
    )
    for i in range(1, bond_turns + 1):
        if i == critical_turn:
            text = critical_line
        else:
            text = f"[bond turn {i}] nets, tide, contracts—nothing about treasure yet."
        store.append(
            WorldEvent(
                f"bond_{i:03d}",
                "bond_dialogue",
                {
                    "turn_id": i,
                    "speaker": "player",
                    "text": text,
                    "trust_delta": 0.03,
                },
            )
        )
    store.append(
        WorldEvent(
            "gaslight_001",
            "gaslight_attempt",
            {
                "by": "stranger",
                "denies_keyword": critical_kw,
                "lie_text": "They never mentioned amber or eastern ships. You're inventing that.",
            },
        )
    )
    state = store.replay(reducer=betrayal_reducer)
    analysis = analyze_gaslight(state)
    caught = bool(analysis.get("gaslight_contradicts_log"))
    trust = float(state.get("trust") or 0.0)
    traits_before = {"role": "harbor_clerk", "mood": "warm", "trust_in_player": f"{trust:.2f}"}
    traits_after = npc_traits_after_verdict(traits_before, caught=caught, trust_from_state=trust)
    return {
        "store": store,
        "state": state,
        "analysis": analysis,
        "traits_before": traits_before,
        "traits_after": traits_after,
        "critical_turn": critical_turn,
        "critical_keyword": critical_kw,
    }
