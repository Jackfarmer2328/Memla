from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
from typing import Any

from .action_capsules import ActionBridgeOption, ActionCapsule, action_capsule_to_dict, create_action_capsule


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mission_id(prompt: str, created_at: str) -> str:
    digest = hashlib.sha1(f"{created_at}:{prompt}".encode("utf-8")).hexdigest()[:12]
    return f"mission:{digest}"


@dataclass
class MissionCheckpoint:
    checkpoint_id: str
    kind: str
    title: str
    detail: str
    status: str
    decisions: list[str]
    safety_level: str
    bridge_option: ActionBridgeOption | None = None


@dataclass
class MissionEvent:
    timestamp: str
    kind: str
    detail: str


@dataclass
class Mission:
    mission_id: str
    prompt: str
    title: str
    action_id: str
    status: str
    created_at: str
    updated_at: str
    capsule: ActionCapsule
    checkpoint: MissionCheckpoint
    history: list[MissionEvent] = field(default_factory=list)


def _best_bridge_option(capsule: ActionCapsule) -> ActionBridgeOption | None:
    if not capsule.bridge_options:
        return None
    return next((option for option in capsule.bridge_options if option.kind == "in_app_web"), capsule.bridge_options[0])


def _initial_checkpoint(capsule: ActionCapsule) -> MissionCheckpoint:
    bridge = _best_bridge_option(capsule)
    if capsule.action_id in {"ask_contact", "draft_message", "send_email"}:
        return MissionCheckpoint(
            checkpoint_id="checkpoint:message_draft",
            kind="message_draft_approval",
            title="Review message draft",
            detail="Memla can open the draft. You still choose the recipient and press Send.",
            status="pending",
            decisions=["approve", "open", "cancel", "modify"],
            safety_level="human_send_required",
            bridge_option=bridge,
        )
    if bridge is not None:
        return MissionCheckpoint(
            checkpoint_id="checkpoint:open_bridge",
            kind="bridge_approval",
            title=f"Open {bridge.label}",
            detail=f"{capsule.summary} Memla will stop before final payment, send, booking, or purchase.",
            status="pending",
            decisions=["approve", "open", "cancel", "modify"],
            safety_level="final_confirmation_required",
            bridge_option=bridge,
        )
    if not capsule.confirmation_required:
        return MissionCheckpoint(
            checkpoint_id="checkpoint:auto_ready",
            kind="auto_run_ready",
            title="Ready to run",
            detail=capsule.summary,
            status="pending",
            decisions=["approve", "cancel", "modify"],
            safety_level="read_only_or_low_risk",
        )
    return MissionCheckpoint(
        checkpoint_id="checkpoint:design_required",
        kind="bridge_design_required",
        title="Bridge required",
        detail=capsule.summary or "Memla recognizes this mission, but a safe bridge is not implemented yet.",
        status="pending",
        decisions=["cancel", "modify"],
        safety_level="unsupported_bridge",
    )


def mission_to_dict(mission: Mission) -> dict[str, Any]:
    payload = asdict(mission)
    payload["capsule"] = action_capsule_to_dict(mission.capsule)
    return payload


class MissionQueue:
    def __init__(self) -> None:
        self._missions: dict[str, Mission] = {}

    def create(self, prompt: str) -> Mission:
        created_at = _now_iso()
        capsule = create_action_capsule(prompt)
        mission = Mission(
            mission_id=_mission_id(prompt, created_at),
            prompt=prompt,
            title=capsule.title,
            action_id=capsule.action_id,
            status="needs_approval",
            created_at=created_at,
            updated_at=created_at,
            capsule=capsule,
            checkpoint=_initial_checkpoint(capsule),
            history=[
                MissionEvent(
                    timestamp=created_at,
                    kind="created",
                    detail=f"Mission created for {capsule.action_id}.",
                )
            ],
        )
        self._missions[mission.mission_id] = mission
        return mission

    def list(self) -> list[Mission]:
        return sorted(self._missions.values(), key=lambda item: item.updated_at, reverse=True)

    def get(self, mission_id: str) -> Mission | None:
        return self._missions.get(mission_id)

    def decide(self, mission_id: str, decision: str, note: str = "") -> Mission | None:
        mission = self._missions.get(mission_id)
        if mission is None:
            return None
        clean_decision = str(decision or "").strip().lower()
        clean_note = str(note or "").strip()
        now = _now_iso()
        if clean_decision == "cancel":
            mission.status = "cancelled"
            mission.checkpoint.status = "cancelled"
        elif clean_decision == "modify":
            mission.status = "needs_approval"
            mission.checkpoint.status = "pending"
            mission.checkpoint.detail = clean_note or "User requested a modification before continuing."
        elif clean_decision in {"approve", "open"}:
            mission.checkpoint.status = "approved"
            if mission.checkpoint.bridge_option is not None:
                mission.status = "needs_user_browser"
                mission.checkpoint = MissionCheckpoint(
                    checkpoint_id="checkpoint:user_browser",
                    kind="open_user_browser",
                    title=f"Open {mission.checkpoint.bridge_option.label}",
                    detail="Open the bridge and continue under Website C2A. Memla still stops before final payment/send/book/place-order.",
                    status="ready",
                    decisions=["open", "cancel", "modify"],
                    safety_level=mission.checkpoint.safety_level,
                    bridge_option=mission.checkpoint.bridge_option,
                )
            else:
                mission.status = "running"
        else:
            mission.status = "needs_approval"
            mission.checkpoint.status = "pending"
            clean_decision = clean_decision or "unknown"
        mission.updated_at = now
        detail = f"Decision: {clean_decision}."
        if clean_note:
            detail = f"{detail} Note: {clean_note}"
        mission.history.append(MissionEvent(timestamp=now, kind="decision", detail=detail))
        return mission


def summarize_mission_queue(queue: MissionQueue) -> dict[str, Any]:
    missions = queue.list()
    status_counts: dict[str, int] = {}
    for mission in missions:
        status_counts[mission.status] = status_counts.get(mission.status, 0) + 1
    return {
        "mission_count": len(missions),
        "status_counts": status_counts,
        "latest_mission_id": missions[0].mission_id if missions else "",
    }

