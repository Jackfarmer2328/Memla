from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Any
from urllib.parse import parse_qs, urlparse

from .memory.ontology import adjudicate_memory_trace, summarize_memory_ontology
from .natural_terminal import (
    BrowserSessionState,
    TerminalPlan,
    _action_signature,
    _append_browser_evidence,
    _canonical_clauses_from_actions,
    _browser_state_for_url,
    _browser_state_copy,
    _canonical_expected_action,
    _decode_action_note,
    _evidence_item_from_details,
    _evidence_item_from_subject,
    _fallback_cards_from_urls,
    _intent_text,
    _language_context_profile,
    _language_prompt_tokens,
    _normalize_label,
    _normalize_url,
    _rank_cards_against_goal,
    _resolve_card_by_index,
    _resolve_card_by_text,
    _compare_cards_against_goal,
    _cached_cards,
    _research_subject_from_browser_state,
    _research_subject_query_from_browser_state,
    _select_better_cached_result,
    _synthesize_browser_evidence,
    _subject_from_browser_state,
    _subject_query_from_browser_state,
    _search_url,
    _promote_language_rules,
    build_llm_client,
    build_language_learning_plan,
    build_raw_terminal_plan,
    build_terminal_plan,
    remember_language_compile,
    BROWSER_STATE_ENV,
    terminal_memory_ontology_path,
)


def _normalized_search_url_parts(url: str) -> tuple[str, str, str]:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.rstrip("/")
    query = parse_qs(parsed.query)
    if "github.com" in host and path == "/search":
        return "github", path, _normalize_label(str((query.get("q") or [""])[0] or ""))
    if "youtube.com" in host and path == "/results":
        return "youtube", path, _normalize_label(str((query.get("search_query") or [""])[0] or ""))
    if "reddit.com" in host and path == "/search":
        return "reddit", path, _normalize_label(str((query.get("q") or [""])[0] or ""))
    if "amazon." in host and path == "/s":
        return "amazon", path, _normalize_label(str((query.get("k") or [""])[0] or ""))
    if ("google." in host or host == "www.google.com") and path == "/search":
        return "google", path, _normalize_label(str((query.get("q") or [""])[0] or ""))
    return "", "", ""


def _browser_url_matches(expected_fragment: str, actual_url: str) -> bool:
    expected = str(expected_fragment or "").strip()
    actual = str(actual_url or "").strip()
    if not expected:
        return True
    if expected.lower() in actual.lower():
        return True
    expected_engine, expected_path, expected_query = _normalized_search_url_parts(expected)
    actual_engine, actual_path, actual_query = _normalized_search_url_parts(actual)
    if expected_engine and expected_engine == actual_engine and expected_path == actual_path:
        return expected_query == actual_query
    return False


@dataclass(frozen=True)
class BrowserBenchmarkCase:
    case_id: str
    prompt: str
    seed_prompt: str = ""
    rule_prompt: str = ""
    browser_state: BrowserSessionState = field(default_factory=BrowserSessionState)
    accepted_action_sets: list[list[str]] = field(default_factory=list)
    expected_page_kind: str = ""
    expected_url_contains: str = ""
    expected_search_engine: str = ""
    expected_search_query: str = ""
    expected_card_count_min: int = 0
    expected_detail_fields: list[str] = field(default_factory=list)
    expected_best_title: str = ""
    expected_compare_winner: str = ""
    expected_subject_title: str = ""
    expected_research_subject_title: str = ""
    expected_retry_selected_title: str = ""
    expected_best_source_title: str = ""
    expected_best_source_kind: str = ""
    expected_synthesis_contains: list[str] = field(default_factory=list)
    expected_evidence_count_min: int = 0
    subject_search_cards: list[dict[str, Any]] = field(default_factory=list)
    subject_search_steps: list[dict[str, Any]] = field(default_factory=list)
    page_snapshot: dict[str, Any] = field(default_factory=dict)
    page_snapshots: dict[str, dict[str, Any]] = field(default_factory=dict)
    expected_state_cleared: bool = False


@dataclass(frozen=True)
class BrowserBacktestResult:
    action_score: float
    execution_passed: bool
    semantic_success: bool
    final_state: BrowserSessionState = field(default_factory=BrowserSessionState)
    detail_fields: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)
    residual_constraints: list[str] = field(default_factory=list)


def _browser_state_from_payload(payload: dict[str, Any]) -> BrowserSessionState:
    if not isinstance(payload, dict):
        return BrowserSessionState()
    return BrowserSessionState(
        current_url=str(payload.get("current_url") or "").strip(),
        page_kind=str(payload.get("page_kind") or "").strip(),
        search_engine=str(payload.get("search_engine") or "").strip(),
        search_query=str(payload.get("search_query") or "").strip(),
        result_urls=[str(item).strip() for item in list(payload.get("result_urls") or []) if str(item).strip()],
        result_cards=[dict(item) for item in list(payload.get("result_cards") or []) if isinstance(item, dict)],
        subject_title=str(payload.get("subject_title") or "").strip(),
        subject_url=str(payload.get("subject_url") or "").strip(),
        subject_summary=str(payload.get("subject_summary") or "").strip(),
        research_subject_title=str(payload.get("research_subject_title") or "").strip(),
        research_subject_url=str(payload.get("research_subject_url") or "").strip(),
        research_subject_summary=str(payload.get("research_subject_summary") or "").strip(),
        evidence_items=[dict(item) for item in list(payload.get("evidence_items") or []) if isinstance(item, dict)],
    )


def _browser_action_matches(expected_action: str, predicted_action: str) -> bool:
    expected = _canonical_expected_action(expected_action)
    predicted = _canonical_expected_action(predicted_action)
    if expected == predicted:
        return True
    if not expected or not predicted or ":" not in expected or ":" not in predicted:
        return False
    expected_kind, expected_target = expected.split(":", 1)
    predicted_kind, predicted_target = predicted.split(":", 1)
    if expected_kind != predicted_kind:
        return False
    if expected_kind in {"browser_rank_cards", "browser_compare_cards"}:
        return True
    if expected_kind == "open_url":
        return _browser_url_matches(expected_target, predicted_target)
    return False


def load_browser_benchmark_cases(path: str) -> list[BrowserBenchmarkCase]:
    cases: list[BrowserBenchmarkCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        payload = json.loads(clean)
        case_id = str(payload.get("case_id") or "").strip()
        prompt = str(payload.get("prompt") or "").strip()
        if not case_id or not prompt:
            continue
        accepted_action_sets = [
            [str(item).strip() for item in list(row or []) if str(item).strip()]
            for row in list(payload.get("accepted_action_sets") or [])
            if isinstance(row, list)
        ]
        if not accepted_action_sets:
            expected_actions = [str(item).strip() for item in list(payload.get("expected_actions") or []) if str(item).strip()]
            if expected_actions:
                accepted_action_sets = [expected_actions]
        cases.append(
            BrowserBenchmarkCase(
                case_id=case_id,
                prompt=prompt,
                seed_prompt=str(payload.get("seed_prompt") or "").strip(),
                rule_prompt=str(payload.get("rule_prompt") or "").strip(),
                browser_state=_browser_state_from_payload(payload.get("browser_state") or {}),
                accepted_action_sets=accepted_action_sets,
                expected_page_kind=str(payload.get("expected_page_kind") or "").strip(),
                expected_url_contains=str(payload.get("expected_url_contains") or "").strip(),
                expected_search_engine=str(payload.get("expected_search_engine") or "").strip(),
                expected_search_query=str(payload.get("expected_search_query") or "").strip(),
                expected_card_count_min=max(int(payload.get("expected_card_count_min") or 0), 0),
                expected_detail_fields=[
                    str(item).strip() for item in list(payload.get("expected_detail_fields") or []) if str(item).strip()
                ],
                expected_best_title=str(payload.get("expected_best_title") or "").strip(),
                expected_compare_winner=str(payload.get("expected_compare_winner") or "").strip(),
                expected_subject_title=str(payload.get("expected_subject_title") or "").strip(),
                expected_research_subject_title=str(payload.get("expected_research_subject_title") or "").strip(),
                expected_retry_selected_title=str(payload.get("expected_retry_selected_title") or "").strip(),
                expected_best_source_title=str(payload.get("expected_best_source_title") or "").strip(),
                expected_best_source_kind=str(payload.get("expected_best_source_kind") or "").strip(),
                expected_synthesis_contains=[
                    str(item).strip() for item in list(payload.get("expected_synthesis_contains") or []) if str(item).strip()
                ],
                expected_evidence_count_min=max(int(payload.get("expected_evidence_count_min") or 0), 0),
                subject_search_cards=[
                    dict(item) for item in list(payload.get("subject_search_cards") or []) if isinstance(item, dict)
                ],
                subject_search_steps=[
                    {
                        "engine": str(item.get("engine") or "").strip(),
                        "cards": [dict(card) for card in list(item.get("cards") or []) if isinstance(card, dict)],
                    }
                    for item in list(payload.get("subject_search_steps") or [])
                    if isinstance(item, dict)
                ],
                page_snapshot=dict(payload.get("page_snapshot") or {}) if isinstance(payload.get("page_snapshot"), dict) else {},
                page_snapshots={
                    str(key).strip(): dict(value)
                    for key, value in dict(payload.get("page_snapshots") or {}).items()
                    if str(key).strip() and isinstance(value, dict)
                },
                expected_state_cleared=bool(payload.get("expected_state_cleared")),
            )
        )
    return cases


def _action_recall_against_set(plan: TerminalPlan, expected_actions: list[str]) -> float:
    expected = [str(item).strip() for item in expected_actions if str(item or "").strip()]
    if not expected:
        return 1.0 if not plan.actions else 0.0
    predicted = [_action_signature(action) for action in plan.actions]
    hits = sum(1 for item in expected if any(_browser_action_matches(item, candidate) for candidate in predicted))
    return round(hits / len(expected), 4)


def _browser_action_score(plan: TerminalPlan, case: BrowserBenchmarkCase) -> float:
    if not case.accepted_action_sets:
        return 1.0 if not plan.actions else 0.0
    return round(
        max(_action_recall_against_set(plan, accepted) for accepted in case.accepted_action_sets),
        4,
    )


def _infer_search_context_from_url(url: str) -> tuple[str, str]:
    parsed = urlparse(str(url or "").strip())
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    query = parse_qs(parsed.query)
    if "github.com" in host and path.rstrip("/") == "/search":
        return "github", str((query.get("q") or [""])[0] or "").strip()
    if "youtube.com" in host and path == "/results":
        return "youtube", str((query.get("search_query") or [""])[0] or "").strip()
    if "reddit.com" in host and path.startswith("/search"):
        return "reddit", str((query.get("q") or [""])[0] or "").strip()
    if "amazon." in host and path == "/s":
        return "amazon", str((query.get("k") or [""])[0] or "").strip()
    if ("google." in host or host == "www.google.com") and path == "/search":
        return "google", str((query.get("q") or [""])[0] or "").strip()
    return "", ""


def _snapshot_from_case(case: BrowserBenchmarkCase, state: BrowserSessionState) -> dict[str, Any]:
    details = {}
    if state.current_url:
        direct = case.page_snapshots.get(state.current_url)
        if isinstance(direct, dict):
            details = dict(direct)
        else:
            normalized_current = _normalize_url(state.current_url)
            for key, value in case.page_snapshots.items():
                if _normalize_url(key) == normalized_current and isinstance(value, dict):
                    details = dict(value)
                    break
    if not details:
        details = dict(case.page_snapshot or {})
    details.setdefault("url", state.current_url)
    details.setdefault("page_kind", state.page_kind or "web_page")
    if state.page_kind == "repo_page":
        repo = str(details.get("repo") or "").strip()
        details.setdefault("title", repo or state.current_url)
        details.setdefault("summary", str(details.get("description") or repo or state.current_url).strip())
    else:
        details.setdefault("title", state.current_url)
        details.setdefault("summary", state.current_url)
    return {key: value for key, value in details.items() if value not in ("", None, [], {})}


def backtest_browser_plan(case: BrowserBenchmarkCase, plan: TerminalPlan) -> BrowserBacktestResult:
    state = BrowserSessionState(**asdict(case.browser_state))
    residuals = list(plan.residual_constraints)
    details: dict[str, Any] = {}
    retry_selected_title = ""
    subject_search_steps = [dict(item) for item in list(case.subject_search_steps or []) if isinstance(item, dict)]
    subject_search_step_index = 0

    if not plan.actions:
        return BrowserBacktestResult(
            action_score=_browser_action_score(plan, case),
            execution_passed=False,
            semantic_success=False,
            final_state=state,
            detail_fields=[],
            details={},
            residual_constraints=residuals or ["no_actions"],
        )

    execution_passed = True
    for action in plan.actions:
        kind = str(action.kind or "").strip()
        if kind == "open_url":
            target = _normalize_url(action.resolved_target or action.target)
            if not target:
                residuals.append("invalid_open_url")
                execution_passed = False
                break
            note_payload = _decode_action_note(action.note)
            search_engine = str(note_payload.get("search_engine") or "").strip()
            search_query = str(note_payload.get("search_query") or "").strip()
            if not search_engine or not search_query:
                inferred_engine, inferred_query = _infer_search_context_from_url(target)
                search_engine = search_engine or inferred_engine
                search_query = search_query or inferred_query
            state = _browser_state_for_url(
                target,
                search_engine=search_engine,
                search_query=search_query,
            )
            continue
        if kind == "browser_new_tab":
            state = BrowserSessionState(
                current_url="browser://new-tab",
                page_kind="blank_tab",
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
                evidence_items=[dict(item) for item in list(state.evidence_items or []) if isinstance(item, dict)],
            )
            continue
        if kind == "browser_close_tab":
            state = BrowserSessionState()
            continue
        if kind in {"browser_switch_tab", "browser_back", "browser_forward"}:
            state = BrowserSessionState()
            continue
        if kind in {"browser_scroll", "browser_type_text", "browser_submit", "browser_wait", "browser_screenshot", "browser_media_pause", "browser_media_play"}:
            if kind == "browser_screenshot":
                details = {"path": "benchmark://browser-screenshot.png"}
            continue
        if kind == "open_search_result":
            if state.page_kind != "search_results":
                residuals.append("browser_state_missing_search_results")
                execution_passed = False
                break
            try:
                result_index = max(int(action.resolved_target or action.target), 1)
            except ValueError:
                result_index = 1
            result_urls = list(state.result_urls or [])
            if not result_urls and state.result_cards:
                result_urls = [str(card.get("url") or "").strip() for card in state.result_cards if str(card.get("url") or "").strip()]
            if len(result_urls) < result_index:
                residuals.append("search_result_unavailable")
                execution_passed = False
                break
            selected_card = _resolve_card_by_index(state, result_index)
            state = _browser_state_for_url(
                result_urls[result_index - 1],
                search_engine=state.search_engine,
                search_query=state.search_query,
                result_urls=result_urls,
                result_cards=list(state.result_cards or []),
                subject_title=str(selected_card.get("title") or "").strip(),
                subject_url=str(selected_card.get("url") or result_urls[result_index - 1]).strip(),
                subject_summary=str(selected_card.get("summary") or "").strip(),
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
                evidence_items=state.evidence_items,
            )
            continue
        if kind == "browser_click_index":
            try:
                card = _resolve_card_by_index(state, max(int(action.resolved_target or action.target), 1))
            except ValueError:
                card = {}
            target_url = str(card.get("url") or "").strip()
            if not target_url:
                residuals.append("click_target_unavailable")
                execution_passed = False
                break
            state = _browser_state_for_url(
                target_url,
                subject_title=str(card.get("title") or "").strip(),
                subject_url=str(card.get("url") or target_url).strip(),
                subject_summary=str(card.get("summary") or "").strip(),
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
            )
            continue
        if kind == "browser_click_text":
            card = _resolve_card_by_text(state, action.resolved_target or action.target)
            target_url = str(card.get("url") or "").strip()
            if not target_url:
                residuals.append("click_target_unavailable")
                execution_passed = False
                break
            state = _browser_state_for_url(
                target_url,
                subject_title=str(card.get("title") or "").strip(),
                subject_url=str(card.get("url") or target_url).strip(),
                subject_summary=str(card.get("summary") or "").strip(),
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
                evidence_items=state.evidence_items,
            )
            continue
        if kind in {"browser_read_page", "browser_extract_page"}:
            if not state.current_url:
                residuals.append("browser_state_missing_current_url")
                execution_passed = False
                break
            details = _snapshot_from_case(case, state)
            state = _append_browser_evidence(state, _evidence_item_from_details(state, details))
            continue
        if kind == "browser_extract_cards":
            if state.page_kind != "search_results":
                residuals.append("browser_state_missing_search_results")
                execution_passed = False
                break
            cards = [dict(item) for item in list(state.result_cards or []) if isinstance(item, dict)]
            if not cards and state.result_urls:
                cards = _fallback_cards_from_urls(state.result_urls)
            state = BrowserSessionState(
                current_url=state.current_url,
                page_kind=state.page_kind,
                search_engine=state.search_engine,
                search_query=state.search_query,
                result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
                result_cards=cards,
                subject_title=state.subject_title,
                subject_url=state.subject_url,
                subject_summary=state.subject_summary,
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
                evidence_items=[dict(item) for item in list(state.evidence_items or []) if isinstance(item, dict)],
            )
            details = {"cards": cards}
            continue
        if kind == "browser_rank_cards":
            if state.page_kind != "search_results":
                residuals.append("browser_state_missing_search_results")
                execution_passed = False
                break
            cards = _cached_cards(state)
            if not cards:
                residuals.append("browser_cards_missing")
                execution_passed = False
                break
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            ranked = _rank_cards_against_goal(cards, goal)
            best = dict(ranked[0]) if ranked else {}
            state = BrowserSessionState(
                current_url=state.current_url,
                page_kind=state.page_kind,
                search_engine=state.search_engine,
                search_query=state.search_query,
                result_urls=[str(item).strip() for item in list(state.result_urls or []) if str(item).strip()],
                result_cards=[dict(item) for item in list(state.result_cards or []) if isinstance(item, dict)],
                subject_title=str(best.get("title") or "").strip(),
                subject_url=str(best.get("url") or "").strip(),
                subject_summary=str(best.get("summary") or "").strip(),
                research_subject_title=str(best.get("title") or "").strip(),
                research_subject_url=str(best.get("url") or "").strip(),
                research_subject_summary=str(best.get("summary") or "").strip(),
                evidence_items=[dict(item) for item in list(state.evidence_items or []) if isinstance(item, dict)],
            )
            state = _append_browser_evidence(state, _evidence_item_from_subject(best, source_kind="repo_page", meta="github repo"))
            details = {
                "goal": goal,
                "best_title": str(best.get("title") or "").strip(),
                "best_url": str(best.get("url") or "").strip(),
                "best_score": float(best.get("score") or 0.0),
                "ranking": ranked,
            }
            continue
        if kind == "browser_compare_cards":
            if state.page_kind != "search_results":
                residuals.append("browser_state_missing_search_results")
                execution_passed = False
                break
            cards = _cached_cards(state)
            if not cards:
                residuals.append("browser_cards_missing")
                execution_passed = False
                break
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            requested_indexes = [int(item) for item in list(note_payload.get("indexes") or []) if str(item).isdigit()]
            if not requested_indexes:
                requested_indexes = [int(part) for part in str(action.resolved_target or action.target or "").split(",") if part.strip().isdigit()]
            if not requested_indexes:
                requested_indexes = [1, 2]
            selected_cards = []
            for index in requested_indexes[:2]:
                card = _resolve_card_by_index(state, index)
                if card:
                    selected_cards.append(card)
            if len(selected_cards) < 2:
                residuals.append("compare_target_unavailable")
                execution_passed = False
                break
            details = _compare_cards_against_goal(selected_cards, goal)
            state = BrowserSessionState(
                current_url=state.current_url,
                page_kind=state.page_kind,
                search_engine=state.search_engine,
                search_query=state.search_query,
                result_urls=[str(item).strip() for item in list(state.result_urls or []) if str(item).strip()],
                result_cards=[dict(item) for item in list(state.result_cards or []) if isinstance(item, dict)],
                subject_title=str(details.get("winner_title") or "").strip(),
                subject_url=str(details.get("winner_url") or "").strip(),
                subject_summary="",
                research_subject_title=str(details.get("winner_title") or "").strip(),
                research_subject_url=str(details.get("winner_url") or "").strip(),
                research_subject_summary="",
                evidence_items=[dict(item) for item in list(state.evidence_items or []) if isinstance(item, dict)],
            )
            state = _append_browser_evidence(
                state,
                _evidence_item_from_subject(
                    {
                        "title": details.get("winner_title"),
                        "url": details.get("winner_url"),
                        "summary": "",
                    },
                    source_kind="repo_page",
                    meta="github repo",
                ),
            )
            continue
        if kind == "browser_search_subject":
            note_payload = _decode_action_note(action.note)
            engine = str(note_payload.get("engine") or action.resolved_target or action.target or "").strip()
            if state.page_kind == "repo_page":
                state = _append_browser_evidence(
                    state,
                    _evidence_item_from_subject(
                        _research_subject_from_browser_state(state),
                        source_kind="repo_page",
                        fallback_url=state.current_url,
                        meta="github repo",
                    ),
                )
            subject = _research_subject_from_browser_state(state)
            subject_query = _research_subject_query_from_browser_state(state)
            if not engine:
                residuals.append("browser_subject_search_engine_missing")
                execution_passed = False
                break
            if not subject_query:
                residuals.append("browser_subject_missing")
                execution_passed = False
                break
            target_url = _search_url(engine, subject_query)
            if not target_url:
                residuals.append("browser_subject_search_url_invalid")
                execution_passed = False
                break
            subject_search_cards: list[dict[str, Any]] = []
            if subject_search_steps:
                matched_step_index = None
                for idx in range(subject_search_step_index, len(subject_search_steps)):
                    step = subject_search_steps[idx]
                    if not engine or not str(step.get("engine") or "").strip() or _normalize_label(str(step.get("engine") or "")) == _normalize_label(engine):
                        matched_step_index = idx
                        break
                if matched_step_index is None and subject_search_step_index < len(subject_search_steps):
                    matched_step_index = subject_search_step_index
                if matched_step_index is not None:
                    step = subject_search_steps[matched_step_index]
                    subject_search_cards = [dict(item) for item in list(step.get("cards") or []) if isinstance(item, dict)]
                    subject_search_step_index = matched_step_index + 1
            if not subject_search_cards:
                subject_search_cards = [dict(item) for item in list(case.subject_search_cards or []) if isinstance(item, dict)]
            subject_search_urls = [str(card.get("url") or "").strip() for card in subject_search_cards if str(card.get("url") or "").strip()]
            state = _browser_state_for_url(
                target_url,
                search_engine=engine,
                search_query=subject_query,
                result_urls=subject_search_urls,
                result_cards=subject_search_cards,
                subject_title=str(subject.get("title") or "").strip(),
                subject_url=str(subject.get("url") or "").strip(),
                subject_summary=str(subject.get("summary") or "").strip(),
                research_subject_title=str(subject.get("title") or "").strip(),
                research_subject_url=str(subject.get("url") or "").strip(),
                research_subject_summary=str(subject.get("summary") or "").strip(),
                evidence_items=state.evidence_items,
            )
            details = {
                "subject_title": str(subject.get("title") or "").strip(),
                "subject_url": str(subject.get("url") or "").strip(),
                "search_engine": engine,
                "search_query": subject_query,
                "search_url": target_url,
            }
            continue
        if kind == "browser_retry_subject_result":
            cards = _cached_cards(state)
            if not cards:
                residuals.append("browser_cards_missing")
                execution_passed = False
                break
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or "").strip()
            if not goal:
                goal = _research_subject_query_from_browser_state(state) or state.search_query or plan.prompt
            selected = _select_better_cached_result(state, goal)
            target_url = str(selected.get("url") or "").strip()
            if not target_url:
                residuals.append("browser_retry_result_unavailable")
                execution_passed = False
                break
            state = _browser_state_for_url(
                target_url,
                search_engine=state.search_engine,
                search_query=state.search_query,
                result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
                result_cards=cards,
                subject_title=str(selected.get("title") or "").strip(),
                subject_url=str(selected.get("url") or target_url).strip(),
                subject_summary=str(selected.get("summary") or "").strip(),
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
                evidence_items=state.evidence_items,
            )
            retry_selected_title = str(selected.get("title") or "").strip()
            details = {
                "goal": goal,
                "selected_index": int(selected.get("index") or 0),
                "selected_title": str(selected.get("title") or "").strip(),
                "selected_url": target_url,
                "ranking": list(selected.get("ranking") or []),
            }
            continue
        if kind == "browser_synthesize_evidence":
            if not state.evidence_items:
                residuals.append("browser_evidence_missing")
                execution_passed = False
                break
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            details = _synthesize_browser_evidence(state.evidence_items, goal, _research_subject_from_browser_state(state))
            if not details:
                residuals.append("browser_evidence_missing")
                execution_passed = False
                break
            state = _browser_state_copy(
                state,
                subject_title=str(details.get("best_source_title") or state.subject_title).strip(),
                subject_url=str(details.get("best_source_url") or state.subject_url).strip(),
                subject_summary=str(details.get("synthesis") or state.subject_summary).strip(),
            )
            continue
        residuals.append(f"unsupported_action:{kind}")
        execution_passed = False
        break

    action_score = _browser_action_score(plan, case)
    semantic_success = execution_passed and action_score >= 1.0
    if semantic_success and case.expected_state_cleared:
        semantic_success = not any(
            [
                state.current_url,
                state.page_kind,
                state.search_engine,
                state.search_query,
                state.result_urls,
                state.result_cards,
                state.subject_title,
                state.subject_url,
                state.subject_summary,
                state.research_subject_title,
                state.research_subject_url,
                state.research_subject_summary,
                state.evidence_items,
            ]
        )
    if semantic_success and case.expected_page_kind:
        semantic_success = _normalize_label(state.page_kind) == _normalize_label(case.expected_page_kind)
    if semantic_success and case.expected_url_contains:
        semantic_success = _browser_url_matches(case.expected_url_contains, state.current_url)
    if semantic_success and case.expected_search_engine:
        semantic_success = _normalize_label(state.search_engine) == _normalize_label(case.expected_search_engine)
    if semantic_success and case.expected_search_query:
        semantic_success = _normalize_label(state.search_query) == _normalize_label(case.expected_search_query)
    if semantic_success and case.expected_card_count_min:
        semantic_success = len(list(state.result_cards or [])) >= int(case.expected_card_count_min)
    if semantic_success and case.expected_detail_fields:
        semantic_success = set(case.expected_detail_fields).issubset(set(details.keys()))
    if semantic_success and case.expected_best_title:
        semantic_success = _normalize_label(str(details.get("best_title") or "")) == _normalize_label(case.expected_best_title)
    if semantic_success and case.expected_compare_winner:
        semantic_success = _normalize_label(str(details.get("winner_title") or "")) == _normalize_label(case.expected_compare_winner)
    if semantic_success and case.expected_subject_title:
        semantic_success = _normalize_label(str(state.subject_title or "")) == _normalize_label(case.expected_subject_title)
    if semantic_success and case.expected_research_subject_title:
        semantic_success = _normalize_label(str(state.research_subject_title or "")) == _normalize_label(case.expected_research_subject_title)
    if semantic_success and case.expected_retry_selected_title:
        semantic_success = _normalize_label(retry_selected_title) == _normalize_label(case.expected_retry_selected_title)
    if semantic_success and case.expected_best_source_title:
        semantic_success = _normalize_label(str(details.get("best_source_title") or "")) == _normalize_label(case.expected_best_source_title)
    if semantic_success and case.expected_best_source_kind:
        semantic_success = _normalize_label(str(details.get("best_source_kind") or "")) == _normalize_label(case.expected_best_source_kind)
    if semantic_success and case.expected_synthesis_contains:
        synthesis_text = _normalize_label(str(details.get("synthesis") or ""))
        semantic_success = all(_normalize_label(item) in synthesis_text for item in case.expected_synthesis_contains)
    if semantic_success and case.expected_evidence_count_min:
        semantic_success = len(list(state.evidence_items or [])) >= int(case.expected_evidence_count_min)

    detail_fields = sorted(str(key).strip() for key in details.keys() if str(key).strip())
    return BrowserBacktestResult(
        action_score=action_score,
        execution_passed=execution_passed,
        semantic_success=semantic_success,
        final_state=state,
        detail_fields=detail_fields,
        details=details,
        residual_constraints=residuals,
    )


def _browser_utility(plan: TerminalPlan, backtest: BrowserBacktestResult) -> float:
    support = 1.0 if plan.actions else 0.0
    execution = 1.0 if backtest.execution_passed else 0.0
    semantic = 1.0 if backtest.semantic_success else 0.0
    return round((0.2 * support) + (0.3 * backtest.action_score) + (0.2 * execution) + (0.3 * semantic), 4)


def run_browser_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    heuristic_only: bool = False,
    ontology_version: str = "browser_v1",
) -> dict[str, Any]:
    cases = load_browser_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    raw_client = build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    raw_model_calls = 0
    memla_model_calls = 0
    memla_language_model_calls = 0
    memla_language_memory_hits = 0
    memla_heuristic_hits = 0

    for case in cases:
        try:
            raw_start = time.perf_counter()
            raw_plan = build_raw_terminal_plan(
                prompt=case.prompt,
                model=raw_model,
                client=raw_client,
                temperature=temperature,
                browser_state=case.browser_state,
            )
            raw_latency_ms = round((time.perf_counter() - raw_start) * 1000.0, 2)

            memla_start = time.perf_counter()
            memla_plan = build_terminal_plan(
                prompt=case.prompt,
                model=memla_model,
                client=memla_client,
                heuristic_only=heuristic_only,
                temperature=temperature,
                browser_state=case.browser_state,
            )
            memla_latency_ms = round((time.perf_counter() - memla_start) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        if raw_plan.source == "raw_model":
            raw_model_calls += 1
        if memla_plan.source in {"model", "language_model"}:
            memla_model_calls += 1
        if memla_plan.source == "language_model":
            memla_language_model_calls += 1
        if memla_plan.source == "language_memory":
            memla_language_memory_hits += 1
        if memla_plan.source == "heuristic":
            memla_heuristic_hits += 1

        raw_backtest = backtest_browser_plan(case, raw_plan)
        memla_backtest = backtest_browser_plan(case, memla_plan)

        rows.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "initial_browser_state": asdict(case.browser_state),
                "accepted_action_sets": [list(items) for items in case.accepted_action_sets],
                "expected_page_kind": case.expected_page_kind,
                "expected_url_contains": case.expected_url_contains,
                "expected_search_engine": case.expected_search_engine,
                "expected_search_query": case.expected_search_query,
                "expected_card_count_min": case.expected_card_count_min,
                "expected_detail_fields": list(case.expected_detail_fields),
                "expected_best_source_title": case.expected_best_source_title,
                "expected_best_source_kind": case.expected_best_source_kind,
                "raw_source": raw_plan.source,
                "raw_latency_ms": raw_latency_ms,
                "raw_actions": [_action_signature(action) for action in raw_plan.actions],
                "raw_action_score": raw_backtest.action_score,
                "raw_execution_passed": 1.0 if raw_backtest.execution_passed else 0.0,
                "raw_semantic_success": 1.0 if raw_backtest.semantic_success else 0.0,
                "raw_browser_utility": _browser_utility(raw_plan, raw_backtest),
                "raw_final_state": asdict(raw_backtest.final_state),
                "raw_detail_fields": list(raw_backtest.detail_fields),
                "raw_residual_constraints": list(raw_backtest.residual_constraints),
                "memla_source": memla_plan.source,
                "memla_latency_ms": memla_latency_ms,
                "memla_actions": [_action_signature(action) for action in memla_plan.actions],
                "memla_action_score": memla_backtest.action_score,
                "memla_execution_passed": 1.0 if memla_backtest.execution_passed else 0.0,
                "memla_semantic_success": 1.0 if memla_backtest.semantic_success else 0.0,
                "memla_browser_utility": _browser_utility(memla_plan, memla_backtest),
                "memla_final_state": asdict(memla_backtest.final_state),
                "memla_detail_fields": list(memla_backtest.detail_fields),
                "memla_residual_constraints": list(memla_backtest.residual_constraints),
                "latency_delta_ms": round(raw_latency_ms - memla_latency_ms, 2),
            }
        )

    count = len(rows) or 1
    avg_raw_latency_ms = round(sum(float(row["raw_latency_ms"]) for row in rows) / count, 2)
    avg_memla_latency_ms = round(sum(float(row["memla_latency_ms"]) for row in rows) / count, 2)
    speedup = round(avg_raw_latency_ms / avg_memla_latency_ms, 4) if avg_memla_latency_ms > 0 else None

    return {
        "generated_ts": int(time.time()),
        "ontology_version": str(ontology_version or "browser_v1"),
        "cases_path": str(Path(cases_path).resolve()),
        "case_ids": [case.case_id for case in cases],
        "limit": limit,
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "avg_raw_latency_ms": avg_raw_latency_ms,
        "avg_memla_latency_ms": avg_memla_latency_ms,
        "memla_vs_raw_speedup": speedup,
        "avg_raw_action_score": round(sum(float(row["raw_action_score"]) for row in rows) / count, 4),
        "avg_memla_action_score": round(sum(float(row["memla_action_score"]) for row in rows) / count, 4),
        "avg_raw_execution_passed": round(sum(float(row["raw_execution_passed"]) for row in rows) / count, 4),
        "avg_memla_execution_passed": round(sum(float(row["memla_execution_passed"]) for row in rows) / count, 4),
        "avg_raw_semantic_success": round(sum(float(row["raw_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_semantic_success": round(sum(float(row["memla_semantic_success"]) for row in rows) / count, 4),
        "avg_raw_browser_utility": round(sum(float(row["raw_browser_utility"]) for row in rows) / count, 4),
        "avg_memla_browser_utility": round(sum(float(row["memla_browser_utility"]) for row in rows) / count, 4),
        "raw_model_call_count": raw_model_calls,
        "memla_model_call_count": memla_model_calls,
        "memla_language_model_call_count": memla_language_model_calls,
        "memla_language_memory_hit_count": memla_language_memory_hits,
        "memla_heuristic_hit_count": memla_heuristic_hits,
        "rows": rows,
        "failed_cases": failed_cases,
    }


def run_language_learning_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    memory_root: str = "",
) -> dict[str, Any]:
    cases = load_browser_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    raw_client = build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    raw_model_calls = 0
    memla_cold_model_calls = 0
    memla_cold_language_model_calls = 0
    memla_warm_model_calls = 0
    memla_warm_language_model_calls = 0
    memla_warm_language_memory_hits = 0
    promoted_reuses = 0

    root_dir = Path(memory_root).resolve() if str(memory_root or "").strip() else Path(tempfile.mkdtemp(prefix="memla_language_v3_"))
    root_dir.mkdir(parents=True, exist_ok=True)
    original_state_env = os.environ.get(BROWSER_STATE_ENV)

    try:
        for case in cases:
            case_dir = (root_dir / case.case_id).resolve()
            case_dir.mkdir(parents=True, exist_ok=True)
            case_state_path = (case_dir / "browser_state.json").resolve()
            if case_state_path.exists():
                case_state_path.unlink()
            case_memory_path = (case_dir / "terminal_language_memory.jsonl").resolve()
            if case_memory_path.exists():
                case_memory_path.unlink()
            os.environ[BROWSER_STATE_ENV] = str(case_state_path)
            seed_prompt = str(case.seed_prompt or case.prompt).strip()
            warm_prompt = str(case.prompt or "").strip()
            try:
                raw_start = time.perf_counter()
                raw_plan = build_raw_terminal_plan(
                    prompt=warm_prompt,
                    model=raw_model,
                    client=raw_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                raw_latency_ms = round((time.perf_counter() - raw_start) * 1000.0, 2)

                cold_start = time.perf_counter()
                cold_plan = build_language_learning_plan(
                    prompt=seed_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                cold_latency_ms = round((time.perf_counter() - cold_start) * 1000.0, 2)

                cold_backtest = backtest_browser_plan(case, cold_plan)
                if cold_backtest.execution_passed and cold_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(
                        prompt=seed_prompt,
                        browser_state=case.browser_state,
                        plan=cold_plan,
                    )

                warm_start = time.perf_counter()
                warm_plan = build_language_learning_plan(
                    prompt=warm_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                warm_latency_ms = round((time.perf_counter() - warm_start) * 1000.0, 2)
            except Exception as exc:
                failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
                continue

            if raw_plan.source == "raw_model":
                raw_model_calls += 1
            if cold_plan.source in {"model", "language_model"}:
                memla_cold_model_calls += 1
            if cold_plan.source == "language_model":
                memla_cold_language_model_calls += 1
            if warm_plan.source in {"model", "language_model"}:
                memla_warm_model_calls += 1
            if warm_plan.source == "language_model":
                memla_warm_language_model_calls += 1
            if warm_plan.source == "language_memory":
                memla_warm_language_memory_hits += 1

            raw_backtest = backtest_browser_plan(case, raw_plan)
            warm_backtest = backtest_browser_plan(case, warm_plan)
            if warm_backtest.execution_passed and warm_plan.source == "language_memory":
                remember_language_compile(
                    prompt=warm_prompt,
                    browser_state=case.browser_state,
                    plan=warm_plan,
                )
                promoted_reuses += 1

            rows.append(
                {
                    "case_id": case.case_id,
                    "seed_prompt": seed_prompt,
                    "warm_prompt": warm_prompt,
                    "initial_browser_state": asdict(case.browser_state),
                    "accepted_action_sets": [list(items) for items in case.accepted_action_sets],
                    "raw_source": raw_plan.source,
                    "raw_latency_ms": raw_latency_ms,
                    "raw_actions": [_action_signature(action) for action in raw_plan.actions],
                    "raw_action_score": raw_backtest.action_score,
                    "raw_execution_passed": 1.0 if raw_backtest.execution_passed else 0.0,
                    "raw_semantic_success": 1.0 if raw_backtest.semantic_success else 0.0,
                    "raw_browser_utility": _browser_utility(raw_plan, raw_backtest),
                    "memla_cold_source": cold_plan.source,
                    "memla_cold_latency_ms": cold_latency_ms,
                    "memla_cold_actions": [_action_signature(action) for action in cold_plan.actions],
                    "memla_cold_action_score": cold_backtest.action_score,
                    "memla_cold_execution_passed": 1.0 if cold_backtest.execution_passed else 0.0,
                    "memla_cold_semantic_success": 1.0 if cold_backtest.semantic_success else 0.0,
                    "memla_cold_browser_utility": _browser_utility(cold_plan, cold_backtest),
                    "memla_warm_source": warm_plan.source,
                    "memla_warm_latency_ms": warm_latency_ms,
                    "memla_warm_actions": [_action_signature(action) for action in warm_plan.actions],
                    "memla_warm_action_score": warm_backtest.action_score,
                    "memla_warm_execution_passed": 1.0 if warm_backtest.execution_passed else 0.0,
                    "memla_warm_semantic_success": 1.0 if warm_backtest.semantic_success else 0.0,
                    "memla_warm_browser_utility": _browser_utility(warm_plan, warm_backtest),
                    "warm_memory_hit": 1.0 if warm_plan.source == "language_memory" else 0.0,
                    "cold_to_warm_transition": f"{cold_plan.source}->{warm_plan.source}",
                    "latency_delta_ms": round(raw_latency_ms - warm_latency_ms, 2),
                }
            )
    finally:
        if original_state_env is None:
            os.environ.pop(BROWSER_STATE_ENV, None)
        else:
            os.environ[BROWSER_STATE_ENV] = original_state_env

    count = len(rows) or 1
    avg_raw_latency_ms = round(sum(float(row["raw_latency_ms"]) for row in rows) / count, 2)
    avg_memla_cold_latency_ms = round(sum(float(row["memla_cold_latency_ms"]) for row in rows) / count, 2)
    avg_memla_warm_latency_ms = round(sum(float(row["memla_warm_latency_ms"]) for row in rows) / count, 2)
    speedup = round(avg_raw_latency_ms / avg_memla_warm_latency_ms, 4) if avg_memla_warm_latency_ms > 0 else None

    return {
        "generated_ts": int(time.time()),
        "ontology_version": "language_v3",
        "cases_path": str(Path(cases_path).resolve()),
        "memory_root": str(root_dir),
        "case_ids": [case.case_id for case in cases],
        "limit": limit,
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "avg_raw_latency_ms": avg_raw_latency_ms,
        "avg_memla_cold_latency_ms": avg_memla_cold_latency_ms,
        "avg_memla_warm_latency_ms": avg_memla_warm_latency_ms,
        "memla_vs_raw_speedup": speedup,
        "avg_raw_semantic_success": round(sum(float(row["raw_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_cold_semantic_success": round(sum(float(row["memla_cold_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_warm_semantic_success": round(sum(float(row["memla_warm_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_warm_memory_hit_rate": round(sum(float(row["warm_memory_hit"]) for row in rows) / count, 4),
        "raw_model_call_count": raw_model_calls,
        "memla_cold_model_call_count": memla_cold_model_calls,
        "memla_cold_language_model_call_count": memla_cold_language_model_calls,
        "memla_warm_model_call_count": memla_warm_model_calls,
        "memla_warm_language_model_call_count": memla_warm_language_model_calls,
        "memla_warm_language_memory_hit_count": memla_warm_language_memory_hits,
        "memla_promoted_reuse_count": promoted_reuses,
        "rows": rows,
        "failed_cases": failed_cases,
    }


def run_language_rule_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    memory_root: str = "",
) -> dict[str, Any]:
    cases = load_browser_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    raw_client = build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    raw_model_calls = 0
    memla_cold_language_model_calls = 0
    memla_warm_language_memory_hits = 0
    memla_rule_hits = 0

    root_dir = Path(memory_root).resolve() if str(memory_root or "").strip() else Path(tempfile.mkdtemp(prefix="memla_language_v4_"))
    root_dir.mkdir(parents=True, exist_ok=True)
    original_state_env = os.environ.get(BROWSER_STATE_ENV)

    try:
        for case in cases:
            case_dir = (root_dir / case.case_id).resolve()
            case_dir.mkdir(parents=True, exist_ok=True)
            case_state_path = (case_dir / "browser_state.json").resolve()
            if case_state_path.exists():
                case_state_path.unlink()
            os.environ[BROWSER_STATE_ENV] = str(case_state_path)
            seed_prompt = str(case.seed_prompt or case.prompt).strip()
            warm_prompt = str(case.prompt or "").strip()
            rule_prompt = str(case.rule_prompt or warm_prompt).strip()
            case_context_profile = _language_context_profile(case.browser_state)
            try:
                raw_start = time.perf_counter()
                raw_plan = build_raw_terminal_plan(
                    prompt=rule_prompt,
                    model=raw_model,
                    client=raw_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                raw_latency_ms = round((time.perf_counter() - raw_start) * 1000.0, 2)

                cold_start = time.perf_counter()
                cold_plan = build_language_learning_plan(
                    prompt=seed_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                cold_latency_ms = round((time.perf_counter() - cold_start) * 1000.0, 2)
                cold_backtest = backtest_browser_plan(case, cold_plan)
                if cold_backtest.execution_passed and cold_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=seed_prompt, browser_state=case.browser_state, plan=cold_plan)

                warm_start = time.perf_counter()
                warm_plan = build_language_learning_plan(
                    prompt=warm_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                warm_latency_ms = round((time.perf_counter() - warm_start) * 1000.0, 2)
                warm_backtest = backtest_browser_plan(case, warm_plan)
                if warm_backtest.execution_passed and warm_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=warm_prompt, browser_state=case.browser_state, plan=warm_plan)
                if warm_backtest.execution_passed and warm_plan.source == "language_memory":
                    _promote_language_rules(prompt=warm_prompt, browser_state=case.browser_state, plan=warm_plan)

                warm2_start = time.perf_counter()
                warm2_plan = build_language_learning_plan(
                    prompt=warm_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                warm2_latency_ms = round((time.perf_counter() - warm2_start) * 1000.0, 2)
                warm2_backtest = backtest_browser_plan(case, warm2_plan)
                if warm2_backtest.execution_passed and warm2_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=warm_prompt, browser_state=case.browser_state, plan=warm2_plan)
                if warm2_backtest.execution_passed and warm2_plan.source == "language_memory":
                    _promote_language_rules(prompt=warm_prompt, browser_state=case.browser_state, plan=warm2_plan)

                rule_start = time.perf_counter()
                rule_plan = build_language_learning_plan(
                    prompt=rule_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                rule_latency_ms = round((time.perf_counter() - rule_start) * 1000.0, 2)
                rule_backtest = backtest_browser_plan(case, rule_plan)
            except Exception as exc:
                failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
                continue

            if raw_plan.source == "raw_model":
                raw_model_calls += 1
            if cold_plan.source == "language_model":
                memla_cold_language_model_calls += 1
            if warm_plan.source == "language_memory":
                memla_warm_language_memory_hits += 1
            if warm2_plan.source == "language_memory":
                memla_warm_language_memory_hits += 1
            if rule_plan.source == "language_rule":
                memla_rule_hits += 1

            rows.append(
                {
                    "case_id": case.case_id,
                    "seed_prompt": seed_prompt,
                    "warm_prompt": warm_prompt,
                    "rule_prompt": rule_prompt,
                    "accepted_action_sets": [list(items) for items in case.accepted_action_sets],
                    "raw_source": raw_plan.source,
                    "raw_latency_ms": raw_latency_ms,
                    "raw_actions": [_action_signature(action) for action in raw_plan.actions],
                    "raw_semantic_success": 1.0 if backtest_browser_plan(case, raw_plan).semantic_success else 0.0,
                    "memla_cold_source": cold_plan.source,
                    "memla_cold_latency_ms": cold_latency_ms,
                    "memla_cold_actions": [_action_signature(action) for action in cold_plan.actions],
                    "memla_cold_semantic_success": 1.0 if cold_backtest.semantic_success else 0.0,
                    "memla_warm_source": warm2_plan.source,
                    "memla_warm_latency_ms": warm2_latency_ms,
                    "memla_warm_actions": [_action_signature(action) for action in warm2_plan.actions],
                    "memla_warm_semantic_success": 1.0 if warm2_backtest.semantic_success else 0.0,
                    "memla_rule_source": rule_plan.source,
                    "memla_rule_latency_ms": rule_latency_ms,
                    "memla_rule_actions": [_action_signature(action) for action in rule_plan.actions],
                    "memla_rule_semantic_success": 1.0 if rule_backtest.semantic_success else 0.0,
                }
            )
    finally:
        if original_state_env is None:
            os.environ.pop(BROWSER_STATE_ENV, None)
        else:
            os.environ[BROWSER_STATE_ENV] = original_state_env

    count = len(rows) or 1
    avg_raw_latency_ms = round(sum(float(row["raw_latency_ms"]) for row in rows) / count, 2)
    avg_memla_rule_latency_ms = round(sum(float(row["memla_rule_latency_ms"]) for row in rows) / count, 2)
    speedup = round(avg_raw_latency_ms / avg_memla_rule_latency_ms, 4) if avg_memla_rule_latency_ms > 0 else None
    return {
        "generated_ts": int(time.time()),
        "ontology_version": "language_v4",
        "cases_path": str(Path(cases_path).resolve()),
        "memory_root": str(root_dir),
        "case_ids": [case.case_id for case in cases],
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "avg_raw_latency_ms": avg_raw_latency_ms,
        "avg_memla_cold_latency_ms": round(sum(float(row["memla_cold_latency_ms"]) for row in rows) / count, 2),
        "avg_memla_warm_latency_ms": round(sum(float(row["memla_warm_latency_ms"]) for row in rows) / count, 2),
        "avg_memla_rule_latency_ms": avg_memla_rule_latency_ms,
        "memla_vs_raw_speedup": speedup,
        "avg_raw_semantic_success": round(sum(float(row["raw_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_cold_semantic_success": round(sum(float(row["memla_cold_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_warm_semantic_success": round(sum(float(row["memla_warm_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_rule_semantic_success": round(sum(float(row["memla_rule_semantic_success"]) for row in rows) / count, 4),
        "raw_model_call_count": raw_model_calls,
        "memla_cold_language_model_call_count": memla_cold_language_model_calls,
        "memla_warm_language_memory_hit_count": memla_warm_language_memory_hits,
        "memla_rule_hit_count": memla_rule_hits,
        "rows": rows,
        "failed_cases": failed_cases,
    }


def run_memory_ontology_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    memory_root: str = "",
) -> dict[str, Any]:
    cases = load_browser_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    raw_client = build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    raw_model_calls = 0
    memla_cold_language_model_calls = 0
    memla_warm_language_memory_hits = 0
    memla_rule_hits = 0
    cold_episodic_transitions = 0
    warm_semantic_transitions = 0
    rule_stage_transitions = 0

    root_dir = Path(memory_root).resolve() if str(memory_root or "").strip() else Path(tempfile.mkdtemp(prefix="memla_memory_v1_"))
    root_dir.mkdir(parents=True, exist_ok=True)
    original_state_env = os.environ.get(BROWSER_STATE_ENV)

    try:
        for case in cases:
            case_dir = (root_dir / case.case_id).resolve()
            case_dir.mkdir(parents=True, exist_ok=True)
            case_state_path = (case_dir / "browser_state.json").resolve()
            if case_state_path.exists():
                case_state_path.unlink()
            case_memory_path = (case_dir / "terminal_language_memory.jsonl").resolve()
            if case_memory_path.exists():
                case_memory_path.unlink()
            case_rule_path = (case_dir / "terminal_language_rules.json").resolve()
            if case_rule_path.exists():
                case_rule_path.unlink()
            case_ontology_path = (case_dir / "terminal_memory_ontology.json").resolve()
            if case_ontology_path.exists():
                case_ontology_path.unlink()
            os.environ[BROWSER_STATE_ENV] = str(case_state_path)
            seed_prompt = str(case.seed_prompt or case.prompt).strip()
            warm_prompt = str(case.prompt or "").strip()
            rule_prompt = str(case.rule_prompt or warm_prompt).strip()
            case_context_profile = _language_context_profile(case.browser_state)
            try:
                raw_start = time.perf_counter()
                raw_plan = build_raw_terminal_plan(
                    prompt=rule_prompt,
                    model=raw_model,
                    client=raw_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                raw_latency_ms = round((time.perf_counter() - raw_start) * 1000.0, 2)
                raw_backtest = backtest_browser_plan(case, raw_plan)

                cold_start = time.perf_counter()
                cold_plan = build_language_learning_plan(
                    prompt=seed_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                cold_latency_ms = round((time.perf_counter() - cold_start) * 1000.0, 2)
                cold_backtest = backtest_browser_plan(case, cold_plan)
                if cold_backtest.execution_passed and cold_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=seed_prompt, browser_state=case.browser_state, plan=cold_plan)
                if cold_backtest.execution_passed and cold_plan.source in {"language_model", "language_memory", "language_rule"}:
                    adjudicate_memory_trace(
                        prompt=seed_prompt,
                        normalized_prompt=_intent_text(seed_prompt),
                        tokens=_language_prompt_tokens(seed_prompt),
                        context_profile=case_context_profile,
                        action_signatures=[_action_signature(action) for action in cold_plan.actions],
                        source=cold_plan.source,
                        success=True,
                        path=terminal_memory_ontology_path(),
                        canonical_clauses=_canonical_clauses_from_actions(cold_plan.actions),
                    )
                cold_summary = summarize_memory_ontology(terminal_memory_ontology_path())

                warm_start = time.perf_counter()
                warm_plan = build_language_learning_plan(
                    prompt=warm_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                warm_latency_ms = round((time.perf_counter() - warm_start) * 1000.0, 2)
                warm_backtest = backtest_browser_plan(case, warm_plan)
                if warm_backtest.execution_passed and warm_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=warm_prompt, browser_state=case.browser_state, plan=warm_plan)
                if warm_backtest.execution_passed and warm_plan.source == "language_memory":
                    _promote_language_rules(prompt=warm_prompt, browser_state=case.browser_state, plan=warm_plan)
                if warm_backtest.execution_passed and warm_plan.source in {"language_model", "language_memory", "language_rule"}:
                    adjudicate_memory_trace(
                        prompt=warm_prompt,
                        normalized_prompt=_intent_text(warm_prompt),
                        tokens=_language_prompt_tokens(warm_prompt),
                        context_profile=case_context_profile,
                        action_signatures=[_action_signature(action) for action in warm_plan.actions],
                        source=warm_plan.source,
                        success=True,
                        path=terminal_memory_ontology_path(),
                        canonical_clauses=_canonical_clauses_from_actions(warm_plan.actions),
                    )

                warm2_start = time.perf_counter()
                warm2_plan = build_language_learning_plan(
                    prompt=warm_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                warm2_latency_ms = round((time.perf_counter() - warm2_start) * 1000.0, 2)
                warm2_backtest = backtest_browser_plan(case, warm2_plan)
                if warm2_backtest.execution_passed and warm2_plan.source in {"language_model", "language_memory"}:
                    remember_language_compile(prompt=warm_prompt, browser_state=case.browser_state, plan=warm2_plan)
                if warm2_backtest.execution_passed and warm2_plan.source in {"language_model", "language_memory", "language_rule"}:
                    adjudicate_memory_trace(
                        prompt=warm_prompt,
                        normalized_prompt=_intent_text(warm_prompt),
                        tokens=_language_prompt_tokens(warm_prompt),
                        context_profile=case_context_profile,
                        action_signatures=[_action_signature(action) for action in warm2_plan.actions],
                        source=warm2_plan.source,
                        success=True,
                        path=terminal_memory_ontology_path(),
                        canonical_clauses=_canonical_clauses_from_actions(warm2_plan.actions),
                    )
                warm_summary = summarize_memory_ontology(terminal_memory_ontology_path())
                if warm2_backtest.execution_passed and warm2_plan.source == "language_memory":
                    _promote_language_rules(prompt=warm_prompt, browser_state=case.browser_state, plan=warm2_plan)

                rule_seed_memory_hit = False
                rule_start = time.perf_counter()
                rule_plan = build_language_learning_plan(
                    prompt=rule_prompt,
                    model=memla_model,
                    client=memla_client,
                    temperature=temperature,
                    browser_state=case.browser_state,
                )
                rule_latency_ms = round((time.perf_counter() - rule_start) * 1000.0, 2)
                rule_backtest = backtest_browser_plan(case, rule_plan)
                if rule_backtest.execution_passed and rule_plan.source in {"language_model", "language_memory", "language_rule"}:
                    adjudicate_memory_trace(
                        prompt=rule_prompt,
                        normalized_prompt=_intent_text(rule_prompt),
                        tokens=_language_prompt_tokens(rule_prompt),
                        context_profile=case_context_profile,
                        action_signatures=[_action_signature(action) for action in rule_plan.actions],
                        source=rule_plan.source,
                        success=True,
                        path=terminal_memory_ontology_path(),
                        canonical_clauses=_canonical_clauses_from_actions(rule_plan.actions),
                    )
                rule_summary = summarize_memory_ontology(terminal_memory_ontology_path())
                if int(warm_summary.get("semantic_count", 0)) <= 0 and int(rule_summary.get("semantic_count", 0)) > 0:
                    warm_summary = rule_summary
                if rule_backtest.execution_passed and rule_plan.source == "language_memory":
                    rule_seed_memory_hit = True
                    _promote_language_rules(prompt=rule_prompt, browser_state=case.browser_state, plan=rule_plan)
                    promoted_rule_start = time.perf_counter()
                    promoted_rule_plan = build_language_learning_plan(
                        prompt=rule_prompt,
                        model=memla_model,
                        client=memla_client,
                        temperature=temperature,
                        browser_state=case.browser_state,
                    )
                    promoted_rule_latency_ms = round((time.perf_counter() - promoted_rule_start) * 1000.0, 2)
                    promoted_rule_backtest = backtest_browser_plan(case, promoted_rule_plan)
                    if promoted_rule_backtest.execution_passed and promoted_rule_plan.source in {"language_model", "language_memory", "language_rule"}:
                        adjudicate_memory_trace(
                            prompt=rule_prompt,
                            normalized_prompt=_intent_text(rule_prompt),
                            tokens=_language_prompt_tokens(rule_prompt),
                            context_profile=case_context_profile,
                            action_signatures=[_action_signature(action) for action in promoted_rule_plan.actions],
                            source=promoted_rule_plan.source,
                            success=True,
                            path=terminal_memory_ontology_path(),
                            canonical_clauses=_canonical_clauses_from_actions(promoted_rule_plan.actions),
                        )
                    rule_plan = promoted_rule_plan
                    rule_latency_ms = promoted_rule_latency_ms
                    rule_backtest = promoted_rule_backtest
                    rule_summary = summarize_memory_ontology(terminal_memory_ontology_path())
            except Exception as exc:
                failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
                continue

            if raw_plan.source == "raw_model":
                raw_model_calls += 1
            if cold_plan.source == "language_model":
                memla_cold_language_model_calls += 1
            if warm_plan.source == "language_memory":
                memla_warm_language_memory_hits += 1
            if warm2_plan.source == "language_memory":
                memla_warm_language_memory_hits += 1
            if rule_seed_memory_hit:
                memla_warm_language_memory_hits += 1
            if rule_plan.source == "language_rule":
                memla_rule_hits += 1
            if int(cold_summary.get("episodic_count", 0)) > 0:
                cold_episodic_transitions += 1
            if int(warm_summary.get("semantic_count", 0)) > 0:
                warm_semantic_transitions += 1
            if int(rule_summary.get("rule_count", 0)) > 0:
                rule_stage_transitions += 1

            rows.append(
                {
                    "case_id": case.case_id,
                    "seed_prompt": seed_prompt,
                    "warm_prompt": warm_prompt,
                    "rule_prompt": rule_prompt,
                    "accepted_action_sets": [list(items) for items in case.accepted_action_sets],
                    "raw_source": raw_plan.source,
                    "raw_latency_ms": raw_latency_ms,
                    "raw_actions": [_action_signature(action) for action in raw_plan.actions],
                    "raw_semantic_success": 1.0 if raw_backtest.semantic_success else 0.0,
                    "memla_cold_source": cold_plan.source,
                    "memla_cold_latency_ms": cold_latency_ms,
                    "memla_cold_actions": [_action_signature(action) for action in cold_plan.actions],
                    "memla_cold_semantic_success": 1.0 if cold_backtest.semantic_success else 0.0,
                    "memla_warm_source": warm2_plan.source,
                    "memla_warm_latency_ms": warm2_latency_ms,
                    "memla_warm_actions": [_action_signature(action) for action in warm2_plan.actions],
                    "memla_warm_semantic_success": 1.0 if warm2_backtest.semantic_success else 0.0,
                    "memla_rule_source": rule_plan.source,
                    "memla_rule_latency_ms": rule_latency_ms,
                    "memla_rule_actions": [_action_signature(action) for action in rule_plan.actions],
                    "memla_rule_semantic_success": 1.0 if rule_backtest.semantic_success else 0.0,
                    "cold_memory_summary": cold_summary,
                    "warm_memory_summary": warm_summary,
                    "rule_memory_summary": rule_summary,
                }
            )
    finally:
        if original_state_env is None:
            os.environ.pop(BROWSER_STATE_ENV, None)
        else:
            os.environ[BROWSER_STATE_ENV] = original_state_env

    count = len(rows) or 1
    avg_raw_latency_ms = round(sum(float(row["raw_latency_ms"]) for row in rows) / count, 2)
    avg_memla_rule_latency_ms = round(sum(float(row["memla_rule_latency_ms"]) for row in rows) / count, 2)
    speedup = round(avg_raw_latency_ms / avg_memla_rule_latency_ms, 4) if avg_memla_rule_latency_ms > 0 else None
    return {
        "generated_ts": int(time.time()),
        "ontology_version": "memory_v1",
        "cases_path": str(Path(cases_path).resolve()),
        "memory_root": str(root_dir),
        "case_ids": [case.case_id for case in cases],
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "avg_raw_latency_ms": avg_raw_latency_ms,
        "avg_memla_cold_latency_ms": round(sum(float(row["memla_cold_latency_ms"]) for row in rows) / count, 2),
        "avg_memla_warm_latency_ms": round(sum(float(row["memla_warm_latency_ms"]) for row in rows) / count, 2),
        "avg_memla_rule_latency_ms": avg_memla_rule_latency_ms,
        "memla_vs_raw_speedup": speedup,
        "avg_raw_semantic_success": round(sum(float(row["raw_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_cold_semantic_success": round(sum(float(row["memla_cold_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_warm_semantic_success": round(sum(float(row["memla_warm_semantic_success"]) for row in rows) / count, 4),
        "avg_memla_rule_semantic_success": round(sum(float(row["memla_rule_semantic_success"]) for row in rows) / count, 4),
        "raw_model_call_count": raw_model_calls,
        "memla_cold_language_model_call_count": memla_cold_language_model_calls,
        "memla_warm_language_memory_hit_count": memla_warm_language_memory_hits,
        "memla_rule_hit_count": memla_rule_hits,
        "cold_episodic_transition_count": cold_episodic_transitions,
        "warm_semantic_transition_count": warm_semantic_transitions,
        "rule_stage_transition_count": rule_stage_transitions,
        "avg_cold_episodic_count": round(sum(float(row["cold_memory_summary"].get("episodic_count", 0)) for row in rows) / count, 4),
        "avg_warm_semantic_count": round(sum(float(row["warm_memory_summary"].get("semantic_count", 0)) for row in rows) / count, 4),
        "avg_rule_rule_count": round(sum(float(row["rule_memory_summary"].get("rule_count", 0)) for row in rows) / count, 4),
        "avg_rule_avg_trust": round(sum(float(row["rule_memory_summary"].get("avg_trust", 0.0)) for row in rows) / count, 4),
        "rows": rows,
        "failed_cases": failed_cases,
    }


def render_browser_benchmark_markdown(report: dict[str, Any]) -> str:
    ontology_version = str(report.get("ontology_version", "browser_v1") or "browser_v1")
    if ontology_version == "memory_v1":
        title = "# Memory Ontology V1 Benchmark"
    elif ontology_version == "language_v4":
        title = "# Language Ontology V4 Benchmark"
    elif ontology_version == "language_v3":
        title = "# Language Ontology V3 Benchmark"
    elif ontology_version == "language_v2":
        title = "# Language Ontology V2 Benchmark"
    elif ontology_version == "language_v1":
        title = "# Language Ontology V1 Benchmark"
    elif ontology_version == "browser_v8":
        title = "# Browser Ontology V8 Benchmark"
    elif ontology_version == "browser_v7":
        title = "# Browser Ontology V7 Benchmark"
    elif ontology_version == "browser_v6":
        title = "# Browser Ontology V6 Benchmark"
    elif ontology_version == "browser_v5":
        title = "# Browser Ontology V5 Benchmark"
    elif ontology_version == "browser_v4":
        title = "# Browser Ontology V4 Benchmark"
    elif ontology_version == "browser_v3":
        title = "# Browser Ontology V3 Benchmark"
    elif ontology_version == "browser_v2":
        title = "# Browser Ontology V2 Benchmark"
    else:
        title = "# Browser Ontology V1 Benchmark"
    lines = [
        title,
        "",
        f"- Ontology version: `{ontology_version}`",
        f"- Raw provider: `{report.get('raw_provider', '')}`",
        f"- Memla provider: `{report.get('memla_provider', '')}`",
        f"- Raw model: `{report.get('raw_model', '')}`",
        f"- Memla model: `{report.get('memla_model', '')}`",
        f"- Cases completed: `{report.get('cases', 0)}` / `{report.get('cases_requested', 0)}`",
        "",
        "## Lane summary",
        "",
    ]
    if ontology_version == "memory_v1":
        lines.extend(
            [
                "| Metric | Raw | Memla Cold | Memla Warm | Memla Rule |",
                "| --- | --- | --- | --- | --- |",
                f"| Avg latency (ms) | `{report.get('avg_raw_latency_ms', 0.0)}` | `{report.get('avg_memla_cold_latency_ms', 0.0)}` | `{report.get('avg_memla_warm_latency_ms', 0.0)}` | `{report.get('avg_memla_rule_latency_ms', 0.0)}` |",
                f"| Semantic success | `{report.get('avg_raw_semantic_success', 0.0)}` | `{report.get('avg_memla_cold_semantic_success', 0.0)}` | `{report.get('avg_memla_warm_semantic_success', 0.0)}` | `{report.get('avg_memla_rule_semantic_success', 0.0)}` |",
                "",
                f"- Raw model calls: `{report.get('raw_model_call_count', 0)}`",
                f"- Memla cold language-model calls: `{report.get('memla_cold_language_model_call_count', 0)}`",
                f"- Memla warm language-memory hits: `{report.get('memla_warm_language_memory_hit_count', 0)}`",
                f"- Memla rule hits: `{report.get('memla_rule_hit_count', 0)}`",
                f"- Cold episodic transitions: `{report.get('cold_episodic_transition_count', 0)}`",
                f"- Warm semantic transitions: `{report.get('warm_semantic_transition_count', 0)}`",
                f"- Rule-stage transitions: `{report.get('rule_stage_transition_count', 0)}`",
                f"- Avg cold episodic count: `{report.get('avg_cold_episodic_count', 0.0)}`",
                f"- Avg warm semantic count: `{report.get('avg_warm_semantic_count', 0.0)}`",
                f"- Avg rule count: `{report.get('avg_rule_rule_count', 0.0)}`",
                f"- Avg rule-stage trust: `{report.get('avg_rule_avg_trust', 0.0)}`",
            ]
        )
    elif ontology_version == "language_v4":
        lines.extend(
            [
                "| Metric | Raw | Memla Cold | Memla Warm | Memla Rule |",
                "| --- | --- | --- | --- | --- |",
                f"| Avg latency (ms) | `{report.get('avg_raw_latency_ms', 0.0)}` | `{report.get('avg_memla_cold_latency_ms', 0.0)}` | `{report.get('avg_memla_warm_latency_ms', 0.0)}` | `{report.get('avg_memla_rule_latency_ms', 0.0)}` |",
                f"| Semantic success | `{report.get('avg_raw_semantic_success', 0.0)}` | `{report.get('avg_memla_cold_semantic_success', 0.0)}` | `{report.get('avg_memla_warm_semantic_success', 0.0)}` | `{report.get('avg_memla_rule_semantic_success', 0.0)}` |",
                "",
                f"- Raw model calls: `{report.get('raw_model_call_count', 0)}`",
                f"- Memla cold language-model calls: `{report.get('memla_cold_language_model_call_count', 0)}`",
                f"- Memla warm language-memory hits: `{report.get('memla_warm_language_memory_hit_count', 0)}`",
                f"- Memla promoted rule hits: `{report.get('memla_rule_hit_count', 0)}`",
            ]
        )
    elif ontology_version == "language_v3":
        lines.extend(
            [
                "| Metric | Raw | Memla Cold | Memla Warm |",
                "| --- | --- | --- | --- |",
                f"| Avg latency (ms) | `{report.get('avg_raw_latency_ms', 0.0)}` | `{report.get('avg_memla_cold_latency_ms', 0.0)}` | `{report.get('avg_memla_warm_latency_ms', 0.0)}` |",
                f"| Semantic success | `{report.get('avg_raw_semantic_success', 0.0)}` | `{report.get('avg_memla_cold_semantic_success', 0.0)}` | `{report.get('avg_memla_warm_semantic_success', 0.0)}` |",
                "",
                f"- Raw model calls: `{report.get('raw_model_call_count', 0)}`",
                f"- Memla cold model calls: `{report.get('memla_cold_model_call_count', 0)}`",
                f"- Memla cold language-model calls: `{report.get('memla_cold_language_model_call_count', 0)}`",
                f"- Memla warm model calls: `{report.get('memla_warm_model_call_count', 0)}`",
                f"- Memla warm language-model calls: `{report.get('memla_warm_language_model_call_count', 0)}`",
                f"- Memla warm language-memory hits: `{report.get('memla_warm_language_memory_hit_count', 0)}`",
                f"- Warm memory-hit rate: `{report.get('avg_memla_warm_memory_hit_rate', 0.0)}`",
                f"- Promoted reuses: `{report.get('memla_promoted_reuse_count', 0)}`",
            ]
        )
    else:
        lines.extend(
            [
                "| Metric | Raw | Memla |",
                "| --- | --- | --- |",
                f"| Avg latency (ms) | `{report.get('avg_raw_latency_ms', 0.0)}` | `{report.get('avg_memla_latency_ms', 0.0)}` |",
                f"| Action score | `{report.get('avg_raw_action_score', 0.0)}` | `{report.get('avg_memla_action_score', 0.0)}` |",
                f"| Execution passed | `{report.get('avg_raw_execution_passed', 0.0)}` | `{report.get('avg_memla_execution_passed', 0.0)}` |",
                f"| Semantic success | `{report.get('avg_raw_semantic_success', 0.0)}` | `{report.get('avg_memla_semantic_success', 0.0)}` |",
                f"| Browser utility | `{report.get('avg_raw_browser_utility', 0.0)}` | `{report.get('avg_memla_browser_utility', 0.0)}` |",
                "",
                f"- Raw model calls: `{report.get('raw_model_call_count', 0)}`",
                f"- Memla model calls: `{report.get('memla_model_call_count', 0)}`",
                f"- Memla language-model calls: `{report.get('memla_language_model_call_count', 0)}`",
                f"- Memla language-memory hits: `{report.get('memla_language_memory_hit_count', 0)}`",
                f"- Memla heuristic hits: `{report.get('memla_heuristic_hit_count', 0)}`",
            ]
        )
    speedup = report.get("memla_vs_raw_speedup")
    if speedup:
        lines.extend(["", f"- Raw-vs-Memla latency speedup: `{speedup}x`"])
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for failure in report["failed_cases"]:
            lines.append(f"- `{failure.get('case_id', '')}` [{failure.get('error_type', '')}] {failure.get('message', '')}".rstrip())
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        if ontology_version == "memory_v1":
            lines.extend(
                [
                    f"### {row.get('case_id', '')}",
                    "",
                    f"- Seed prompt: `{row.get('seed_prompt', '')}`",
                    f"- Warm prompt: `{row.get('warm_prompt', '')}`",
                    f"- Rule prompt: `{row.get('rule_prompt', '')}`",
                    f"- Accepted actions: `{json.dumps(row.get('accepted_action_sets', []), ensure_ascii=True)}`",
                    f"- Raw source/actions: `{row.get('raw_source', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                    f"- Memla cold source/actions: `{row.get('memla_cold_source', '')}` / `{', '.join(row.get('memla_cold_actions', []))}`",
                    f"- Memla warm source/actions: `{row.get('memla_warm_source', '')}` / `{', '.join(row.get('memla_warm_actions', []))}`",
                    f"- Memla rule source/actions: `{row.get('memla_rule_source', '')}` / `{', '.join(row.get('memla_rule_actions', []))}`",
                    f"- Cold memory summary: `{json.dumps(row.get('cold_memory_summary', {}), ensure_ascii=True)}`",
                    f"- Warm memory summary: `{json.dumps(row.get('warm_memory_summary', {}), ensure_ascii=True)}`",
                    f"- Rule memory summary: `{json.dumps(row.get('rule_memory_summary', {}), ensure_ascii=True)}`",
                    f"- Raw semantic success: `{row.get('raw_semantic_success', 0.0)}`",
                    f"- Memla cold semantic success: `{row.get('memla_cold_semantic_success', 0.0)}`",
                    f"- Memla warm semantic success: `{row.get('memla_warm_semantic_success', 0.0)}`",
                    f"- Memla rule semantic success: `{row.get('memla_rule_semantic_success', 0.0)}`",
                    "",
                ]
            )
        elif ontology_version == "language_v4":
            lines.extend(
                [
                    f"### {row.get('case_id', '')}",
                    "",
                    f"- Seed prompt: `{row.get('seed_prompt', '')}`",
                    f"- Warm prompt: `{row.get('warm_prompt', '')}`",
                    f"- Rule prompt: `{row.get('rule_prompt', '')}`",
                    f"- Accepted actions: `{json.dumps(row.get('accepted_action_sets', []), ensure_ascii=True)}`",
                    f"- Raw source/actions: `{row.get('raw_source', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                    f"- Memla cold source/actions: `{row.get('memla_cold_source', '')}` / `{', '.join(row.get('memla_cold_actions', []))}`",
                    f"- Memla warm source/actions: `{row.get('memla_warm_source', '')}` / `{', '.join(row.get('memla_warm_actions', []))}`",
                    f"- Memla rule source/actions: `{row.get('memla_rule_source', '')}` / `{', '.join(row.get('memla_rule_actions', []))}`",
                    f"- Raw semantic success: `{row.get('raw_semantic_success', 0.0)}`",
                    f"- Memla cold semantic success: `{row.get('memla_cold_semantic_success', 0.0)}`",
                    f"- Memla warm semantic success: `{row.get('memla_warm_semantic_success', 0.0)}`",
                    f"- Memla rule semantic success: `{row.get('memla_rule_semantic_success', 0.0)}`",
                    "",
                ]
            )
        elif ontology_version == "language_v3":
            lines.extend(
                [
                    f"### {row.get('case_id', '')}",
                    "",
                    f"- Seed prompt: `{row.get('seed_prompt', '')}`",
                    f"- Warm prompt: `{row.get('warm_prompt', '')}`",
                    f"- Accepted actions: `{json.dumps(row.get('accepted_action_sets', []), ensure_ascii=True)}`",
                    f"- Raw source/actions: `{row.get('raw_source', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                    f"- Memla cold source/actions: `{row.get('memla_cold_source', '')}` / `{', '.join(row.get('memla_cold_actions', []))}`",
                    f"- Memla warm source/actions: `{row.get('memla_warm_source', '')}` / `{', '.join(row.get('memla_warm_actions', []))}`",
                    f"- Transition: `{row.get('cold_to_warm_transition', '')}`",
                    f"- Raw semantic success: `{row.get('raw_semantic_success', 0.0)}`",
                    f"- Memla cold semantic success: `{row.get('memla_cold_semantic_success', 0.0)}`",
                    f"- Memla warm semantic success: `{row.get('memla_warm_semantic_success', 0.0)}`",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"### {row.get('case_id', '')}",
                    "",
                    f"- Prompt: `{row.get('prompt', '')}`",
                    f"- Accepted actions: `{json.dumps(row.get('accepted_action_sets', []), ensure_ascii=True)}`",
                    f"- Raw source/actions: `{row.get('raw_source', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                    f"- Memla source/actions: `{row.get('memla_source', '')}` / `{', '.join(row.get('memla_actions', []))}`",
                    f"- Raw semantic success: `{row.get('raw_semantic_success', 0.0)}`",
                    f"- Memla semantic success: `{row.get('memla_semantic_success', 0.0)}`",
                    f"- Raw browser utility: `{row.get('raw_browser_utility', 0.0)}`",
                    f"- Memla browser utility: `{row.get('memla_browser_utility', 0.0)}`",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"
