from __future__ import annotations

from collections import deque
from dataclasses import asdict
from pathlib import Path
import time
from typing import Any

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

from .action_capsules import action_capsule_to_dict, create_action_capsule
from .action_ontology import action_draft_to_dict, action_match_to_dict, classify_action_prompt, create_action_draft, summarize_action_ontology
from .memory.ontology import adjudicate_memory_trace, summarize_memory_ontology
from .missions import MissionQueue, mission_to_dict, summarize_mission_queue
from .persistent_world_lab.white_room_director import (
    build_counterfactual_bundle,
    build_director_bundle,
    creator_counterfactual_studio,
    explain_relation,
    simulate_player_entry,
    white_room_director_suite,
)
from .natural_terminal import (
    BrowserSessionState,
    TERMINAL_MEMORY_ONTOLOGY_FILENAME,
    TerminalExecutionResult,
    TerminalPlan,
    build_llm_client,
    build_raw_terminal_plan,
    build_terminal_plan,
    execute_terminal_plan,
    load_browser_session_state,
    run_terminal_scout,
    terminal_execution_to_dict,
    terminal_memory_ontology_path,
    terminal_model_default,
    terminal_plan_to_dict,
    terminal_scout_to_dict,
)


class MemlaRunRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    model: str = ""
    provider: str = ""
    base_url: str = ""
    temperature: float = 0.1
    heuristic_only: bool = False
    without_memla: bool = False


class MemlaScoutRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    save_state: bool = True


class MemlaFollowupRequest(MemlaRunRequest):
    pass


class MemlaActionPlanRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class MemlaActionDraftRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class MemlaActionCapsuleRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class MemlaMissionRequest(BaseModel):
    prompt: str = Field(..., min_length=1)


class MemlaMissionDecisionRequest(BaseModel):
    decision: str = Field(..., min_length=1)
    note: str = ""


class MemlaBrowserDebugCandidateRequest(BaseModel):
    role: str = ""
    label: str = ""
    score: float = 0.0
    group_key: str = ""
    group_label: str = ""
    selected: bool = False
    opens_subflow: bool = False


class MemlaBrowserDebugRequest(BaseModel):
    source: str = "ios_browser"
    reason: str = ""
    title: str = ""
    url: str = ""
    page_kind: str = ""
    page_summary: str = ""
    auth_state: str = ""
    inspection_status: str = ""
    button_action_status: str = ""
    auto_drive_enabled: bool = False
    auto_drive_status: str = ""
    residuals: list[str] = Field(default_factory=list)
    safe_actions: list[str] = Field(default_factory=list)
    service_facts: dict[str, str] = Field(default_factory=dict)
    pending_step: dict[str, str] = Field(default_factory=dict)
    top_candidates: list[MemlaBrowserDebugCandidateRequest] = Field(default_factory=list)
    agency_trace: list[str] = Field(default_factory=list)
    mirror_debug_text: str = ""
    agency_trace_text: str = ""


def _model_to_dict(model: BaseModel) -> dict[str, Any]:
    if hasattr(model, "model_dump"):
        return dict(model.model_dump())
    return dict(model.dict())


def _resolve_terminal_defaults(
    *,
    model: str,
    provider: str,
    base_url: str,
    temperature: float,
    heuristic_only: bool,
) -> dict[str, Any]:
    return {
        "model": str(model or terminal_model_default()).strip() or terminal_model_default(),
        "provider": str(provider or "ollama").strip() or "ollama",
        "base_url": str(base_url or "").strip(),
        "temperature": float(temperature),
        "heuristic_only": bool(heuristic_only),
    }


def _resolve_request_value(raw: str, default: str) -> str:
    return str(raw or "").strip() or default


def _resolve_memory_ontology_path(state_path: str | Path | None) -> Path:
    if state_path is None:
        return terminal_memory_ontology_path()
    return (Path(state_path).expanduser().resolve().parent / TERMINAL_MEMORY_ONTOLOGY_FILENAME).resolve()


def _record_action_draft_memory(*, draft: dict[str, Any], state_path: str | Path | None) -> None:
    if not bool(draft.get("ok")):
        return
    action_id = str(draft.get("action_id") or "").strip()
    if not action_id:
        return
    action_signatures = [
        f"action:{action_id}",
        f"channel:{str(draft.get('channel') or '').strip() or 'unknown'}",
        "confirmation:required" if bool(draft.get("confirmation_required")) else "confirmation:not_required",
    ]
    adjudicate_memory_trace(
        prompt=str(draft.get("prompt") or "").strip(),
        normalized_prompt=str(draft.get("prompt") or "").strip().lower(),
        tokens=[token for token in str(draft.get("prompt") or "").strip().lower().split() if token],
        context_profile={
            "page_kind": "",
            "search_engine": "",
            "has_search_results": False,
            "has_subject": False,
            "has_evidence": False,
        },
        action_signatures=action_signatures,
        source="action_draft",
        success=True,
        path=_resolve_memory_ontology_path(state_path),
        memory_kind=f"action_{action_id}",
        canonical_clauses=[str(draft.get("draft_text") or "").strip()],
    )


def _record_action_capsule_memory(*, capsule: dict[str, Any], state_path: str | Path | None) -> None:
    action_id = str(capsule.get("action_id") or "").strip()
    status = str(capsule.get("status") or "").strip()
    if not action_id or status in {"needs_slots"}:
        return
    action_signatures = [
        f"action:{action_id}",
        f"capsule_status:{status or 'unknown'}",
        f"authorization:{str(capsule.get('authorization_level') or '').strip() or 'unknown'}",
        "confirmation:required" if bool(capsule.get("confirmation_required")) else "confirmation:not_required",
    ]
    adjudicate_memory_trace(
        prompt=str(capsule.get("prompt") or "").strip(),
        normalized_prompt=str(capsule.get("prompt") or "").strip().lower(),
        tokens=[token for token in str(capsule.get("prompt") or "").strip().lower().split() if token],
        context_profile={
            "page_kind": "",
            "search_engine": "",
            "has_search_results": False,
            "has_subject": False,
            "has_evidence": False,
        },
        action_signatures=action_signatures,
        source="action_capsule",
        success=True,
        path=_resolve_memory_ontology_path(state_path),
        memory_kind=f"action_capsule_{action_id}",
        canonical_clauses=[
            str(capsule.get("summary") or "").strip(),
            str(capsule.get("draft_text") or "").strip(),
        ],
    )


def _build_run_payload(
    *,
    request: MemlaRunRequest,
    browser_state: BrowserSessionState,
    state_path: str | Path | None,
    defaults: dict[str, Any],
) -> dict[str, Any]:
    model = _resolve_request_value(request.model, str(defaults["model"]))
    provider = _resolve_request_value(request.provider, str(defaults["provider"]))
    base_url = _resolve_request_value(request.base_url, str(defaults["base_url"]))
    temperature = float(request.temperature if request.temperature is not None else defaults["temperature"])
    heuristic_only = bool(request.heuristic_only or defaults["heuristic_only"])

    client = None if heuristic_only and not request.without_memla else build_llm_client(provider=provider, base_url=base_url)
    started = time.perf_counter()
    if request.without_memla:
        plan = build_raw_terminal_plan(
            prompt=request.prompt,
            model=model,
            client=client,
            temperature=temperature,
            browser_state=browser_state,
        )
    else:
        plan = build_terminal_plan(
            prompt=request.prompt,
            model=model,
            client=client,
            heuristic_only=heuristic_only,
            temperature=temperature,
            browser_state=browser_state,
        )
    planning_seconds = round(time.perf_counter() - started, 4)
    execution: TerminalExecutionResult | None = None
    execution_seconds = 0.0
    if plan.actions:
        run_started = time.perf_counter()
        execution = execute_terminal_plan(
            plan,
            browser_state=browser_state,
            state_path=state_path,
            client=client,
            model=model,
        )
        execution_seconds = round(time.perf_counter() - run_started, 4)
    total_seconds = round(planning_seconds + execution_seconds, 4)
    return {
        "ok": bool(execution.ok if execution is not None else False),
        "prompt": request.prompt,
        "mode": "execution" if execution is not None else "plan",
        "plan": terminal_plan_to_dict(plan),
        "execution": terminal_execution_to_dict(execution) if execution is not None else None,
        "planning_duration_seconds": planning_seconds,
        "execution_duration_seconds": execution_seconds,
        "total_duration_seconds": total_seconds,
        "runtime_defaults": {
            "model": model,
            "provider": provider,
            "heuristic_only": heuristic_only,
        },
    }


def create_memla_app(
    *,
    state_path: str | Path | None = None,
    default_model: str = "",
    default_provider: str = "ollama",
    default_base_url: str = "",
    default_temperature: float = 0.1,
    default_heuristic_only: bool = False,
) -> FastAPI:
    defaults = _resolve_terminal_defaults(
        model=default_model,
        provider=default_provider,
        base_url=default_base_url,
        temperature=default_temperature,
        heuristic_only=default_heuristic_only,
    )
    app = FastAPI(
        title="Memla API",
        version="0.1.1",
        description="Thin HTTP wrapper around Memla's bounded terminal/browser runtime.",
    )
    static_dir = (Path(__file__).resolve().parent.parent / "static").resolve()
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
    mission_queue = MissionQueue()
    browser_debug_history: deque[dict[str, Any]] = deque(maxlen=500)
    browser_debug_last_id = 0

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "ok": True,
            "service": "memla-api",
            "api_version": app.version,
            "capabilities": {
                "browser_debug_upload": True,
            },
            "runtime_defaults": {
                "model": defaults["model"],
                "provider": defaults["provider"],
                "heuristic_only": defaults["heuristic_only"],
            },
        }

    @app.get("/white-room/bootstrap")
    def white_room_bootstrap(days: int = 30, seed: int = 777) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        return {
            "ok": True,
            "bundle": build_director_bundle(days=safe_days, seed=safe_seed),
        }

    @app.get("/white-room/fortress")
    def white_room_fortress(days: int = 30, seed: int = 777) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        suite = white_room_director_suite(days=safe_days, seed=safe_seed)
        return {
            "ok": True,
            "suite": suite,
        }

    @app.get("/white-room/explain")
    def white_room_explain(
        day: int = 30,
        a: str = "aldric",
        b: str = "crath",
        days: int = 30,
        seed: int = 777,
    ) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        safe_day = min(max(int(day), 1), safe_days)
        bundle = build_director_bundle(days=safe_days, seed=safe_seed)
        return {
            "ok": True,
            "explanation": explain_relation(bundle=bundle, day=safe_day, a=str(a), b=str(b)),
        }

    @app.get("/white-room/fork")
    def white_room_fork(
        days: int = 30,
        seed: int = 777,
        fork_day: int = 16,
        a: str = "aldric",
        b: str = "crath",
        forced_relation: str = "alliance",
    ) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        payload = build_counterfactual_bundle(
            days=safe_days,
            seed=safe_seed,
            fork_day=int(fork_day),
            a=str(a),
            b=str(b),
            forced_relation=str(forced_relation),
        )
        return {"ok": True, "fork": payload}

    @app.get("/white-room/player-entry")
    def white_room_player_entry(
        day: int = 30,
        npc_id: str = "aldric",
        message: str = "I just arrived. What happened here?",
        days: int = 30,
        seed: int = 777,
    ) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        safe_day = min(max(int(day), 1), safe_days)
        bundle = build_director_bundle(days=safe_days, seed=safe_seed)
        result = simulate_player_entry(
            bundle=bundle,
            day=safe_day,
            npc_id=str(npc_id),
            player_message=str(message),
        )
        return {"ok": True, "entry": result}

    @app.get("/white-room/studio")
    def white_room_studio(days: int = 30, seed: int = 777, top_k: int = 5) -> dict[str, Any]:
        safe_days = min(max(int(days), 1), 90)
        safe_seed = int(seed)
        safe_top_k = min(max(int(top_k), 1), 20)
        payload = creator_counterfactual_studio(days=safe_days, seed=safe_seed, top_k=safe_top_k)
        return {"ok": True, "studio": payload}

    @app.get("/state")
    def state() -> dict[str, Any]:
        browser_state = load_browser_session_state(state_path)
        return {
            "ok": True,
            "state": asdict(browser_state),
        }

    @app.get("/memory")
    def memory() -> dict[str, Any]:
        ontology_path = _resolve_memory_ontology_path(state_path)
        return {
            "ok": True,
            "path": str(ontology_path),
            "summary": summarize_memory_ontology(ontology_path),
        }

    @app.get("/actions")
    def actions() -> dict[str, Any]:
        return {
            "ok": True,
            "summary": summarize_action_ontology(),
        }

    @app.post("/actions/plan")
    def action_plan(request: MemlaActionPlanRequest) -> dict[str, Any]:
        return {
            "ok": True,
            "match": action_match_to_dict(classify_action_prompt(request.prompt)),
        }

    @app.post("/actions/draft")
    def action_draft(request: MemlaActionDraftRequest) -> dict[str, Any]:
        draft = action_draft_to_dict(create_action_draft(request.prompt))
        try:
            _record_action_draft_memory(draft=draft, state_path=state_path)
        except OSError:
            draft["residual_constraints"] = list(draft.get("residual_constraints") or []) + ["action_memory_persist_failed"]
        return {
            "ok": True,
            "draft": draft,
        }

    @app.post("/actions/capsule")
    def action_capsule(request: MemlaActionCapsuleRequest) -> dict[str, Any]:
        capsule = action_capsule_to_dict(create_action_capsule(request.prompt))
        try:
            _record_action_capsule_memory(capsule=capsule, state_path=state_path)
        except OSError:
            capsule["residual_constraints"] = list(capsule.get("residual_constraints") or []) + ["action_capsule_memory_persist_failed"]
        return {
            "ok": True,
            "capsule": capsule,
        }

    @app.get("/missions")
    def missions() -> dict[str, Any]:
        return {
            "ok": True,
            "summary": summarize_mission_queue(mission_queue),
            "missions": [mission_to_dict(mission) for mission in mission_queue.list()],
        }

    @app.post("/missions")
    def create_mission(request: MemlaMissionRequest) -> dict[str, Any]:
        mission = mission_queue.create(request.prompt)
        return {
            "ok": True,
            "mission": mission_to_dict(mission),
        }

    @app.get("/missions/{mission_id:path}")
    def mission(mission_id: str) -> dict[str, Any]:
        found = mission_queue.get(mission_id)
        if found is None:
            return {
                "ok": False,
                "error": "mission_not_found",
            }
        return {
            "ok": True,
            "mission": mission_to_dict(found),
        }

    @app.post("/missions/{mission_id:path}/decision")
    def mission_decision(mission_id: str, request: MemlaMissionDecisionRequest) -> dict[str, Any]:
        found = mission_queue.decide(mission_id, decision=request.decision, note=request.note)
        if found is None:
            return {
                "ok": False,
                "error": "mission_not_found",
            }
        return {
            "ok": True,
            "mission": mission_to_dict(found),
        }

    @app.post("/scout")
    def scout(request: MemlaScoutRequest) -> dict[str, Any]:
        browser_state = load_browser_session_state(state_path)
        started = time.perf_counter()
        result = run_terminal_scout(
            request.prompt,
            browser_state=browser_state,
            state_path=state_path,
            save_state=request.save_state,
        )
        total_seconds = round(time.perf_counter() - started, 4)
        return {
            "ok": result.ok,
            "mode": "scout",
            "result": terminal_scout_to_dict(result),
            "total_duration_seconds": total_seconds,
        }

    @app.post("/run")
    def run(request: MemlaRunRequest) -> dict[str, Any]:
        browser_state = load_browser_session_state(state_path)
        return _build_run_payload(
            request=request,
            browser_state=browser_state,
            state_path=state_path,
            defaults=defaults,
        )

    @app.post("/followup")
    def followup(request: MemlaFollowupRequest) -> dict[str, Any]:
        browser_state = load_browser_session_state(state_path)
        return _build_run_payload(
            request=request,
            browser_state=browser_state,
            state_path=state_path,
            defaults=defaults,
        )

    @app.get("/debug/browser")
    def browser_debug(after_id: int = 0, limit: int = 25) -> dict[str, Any]:
        safe_after_id = max(int(after_id), 0)
        safe_limit = min(max(int(limit), 1), 200)
        items = [item for item in browser_debug_history if int(item.get("event_id") or 0) > safe_after_id]
        if len(items) > safe_limit:
            items = items[-safe_limit:]
        return {
            "ok": True,
            "count": len(items),
            "last_event_id": browser_debug_last_id,
            "items": items,
        }

    @app.post("/debug/browser")
    def debug_browser(request: MemlaBrowserDebugRequest) -> dict[str, Any]:
        nonlocal browser_debug_last_id
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        browser_debug_last_id += 1
        browser_debug_history.append(
            {
                "event_id": browser_debug_last_id,
                "logged_at": stamp,
                **_model_to_dict(request),
            }
        )
        print(f"[Memla Browser Debug][{stamp}] source={request.source or 'unknown'} reason={request.reason or 'unspecified'}")
        if request.title:
            print(f"Title: {request.title}")
        if request.url:
            print(f"URL: {request.url}")
        summary_parts = [
            f"page_kind={request.page_kind or 'unknown'}",
            f"auth={request.auth_state or 'unknown'}",
            f"inspection={request.inspection_status or 'n/a'}",
            f"button={request.button_action_status or 'n/a'}",
            f"agency={'enabled' if request.auto_drive_enabled else 'disabled'}",
            f"status={request.auto_drive_status or 'n/a'}",
        ]
        print("State: " + " | ".join(summary_parts))
        if request.pending_step:
            pending_bits = [f"{key}={value}" for key, value in request.pending_step.items() if str(value).strip()]
            if pending_bits:
                print("PendingStep: " + " | ".join(pending_bits))
        if request.residuals:
            print("Residuals: " + ", ".join(request.residuals[:8]))
        if request.safe_actions:
            print("SafeActions: " + ", ".join(request.safe_actions[:8]))
        if request.service_facts:
            fact_bits = [f"{key}={value}" for key, value in sorted(request.service_facts.items()) if str(value).strip()]
            if fact_bits:
                print("ServiceFacts: " + " | ".join(fact_bits[:18]))
        if request.top_candidates:
            print("TopCandidates:")
            for candidate in request.top_candidates[:10]:
                score = f"{candidate.score:.1f}"
                detail_parts = [
                    candidate.role or "unknown",
                    candidate.label or "(empty)",
                    f"score={score}",
                ]
                if candidate.group_key:
                    detail_parts.append(f"group={candidate.group_key}")
                if candidate.group_label:
                    detail_parts.append(f"group_label={candidate.group_label}")
                if candidate.selected:
                    detail_parts.append("selected=true")
                if candidate.opens_subflow:
                    detail_parts.append("opens_subflow=true")
                print("  - " + " | ".join(detail_parts))
        if request.agency_trace:
            print("AgencyTrace:")
            for line in request.agency_trace[-18:]:
                print(f"  {line}")
        elif request.agency_trace_text.strip():
            print("AgencyTraceText:")
            print(request.agency_trace_text.strip())
        if request.mirror_debug_text.strip():
            print("MirrorDebugText:")
            print(request.mirror_debug_text.strip())
        print("[/Memla Browser Debug]")
        return {
            "ok": True,
            "message": "browser_debug_logged",
            "event_id": browser_debug_last_id,
        }

    return app


def serve_memla_api(
    *,
    host: str = "127.0.0.1",
    port: int = 8080,
    state_path: str | Path | None = None,
    default_model: str = "",
    default_provider: str = "ollama",
    default_base_url: str = "",
    default_temperature: float = 0.1,
    default_heuristic_only: bool = False,
) -> None:
    app = create_memla_app(
        state_path=state_path,
        default_model=default_model,
        default_provider=default_provider,
        default_base_url=default_base_url,
        default_temperature=default_temperature,
        default_heuristic_only=default_heuristic_only,
    )
    uvicorn.run(app, host=str(host or "127.0.0.1").strip() or "127.0.0.1", port=int(port))


__all__ = [
    "MemlaActionDraftRequest",
    "MemlaActionCapsuleRequest",
    "MemlaActionPlanRequest",
    "MemlaFollowupRequest",
    "MemlaMissionDecisionRequest",
    "MemlaMissionRequest",
    "MemlaRunRequest",
    "MemlaScoutRequest",
    "create_memla_app",
    "serve_memla_api",
]
