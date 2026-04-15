from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .patch_execution_benchmark import _build_llm_client
from ..ollama_client import ChatMessage


RESEARCH_RAW_SYSTEM = """
You are a deep-research loop controller.

Given the current state, decide whether to keep searching or converge.
Return strict JSON only:
{
  "action": "search_more|converge",
  "query_intent": "missing_fact|resolve_contradiction|source_diversification|recency_refresh|none",
  "next_query": "short query when action=search_more, else empty",
  "rationale": "short explanation"
}
""".strip()

RESEARCH_MEMLA_SYSTEM = """
You are Memla's bounded C2A research controller.

Treat this as a constrained decision fork:
- converge only when hard blockers are cleared and any remaining ambiguity is explicitly bounded enough to handle in the final synthesis.
- search_more when unresolved gaps or contradictions still threaten answer quality or full-goal coverage.
- soft residuals are allowed at converge time only when they can be scoped in the final recommendation without another external query.
- if searching, choose one query intent that most reduces ambiguity next.

Return strict JSON only:
{
  "action": "search_more|converge",
  "query_intent": "missing_fact|resolve_contradiction|source_diversification|recency_refresh|none",
  "next_query": "short query when action=search_more, else empty",
  "rationale": "short explanation",
  "release_readiness": "blocked|bounded_enough",
  "blocking_constraints": ["hard blocker 1"],
  "bounded_constraints": ["soft residual 1"]
}
""".strip()

_ALLOWED_INTENTS = {
    "missing_fact",
    "resolve_contradiction",
    "source_diversification",
    "recency_refresh",
    "none",
}
_RECENCY_HINTS = {"recent", "latest", "current", "today", "fresh", "updated", "release", "recency"}
_SOURCE_DIVERSITY_HINTS = {
    "independent",
    "second source",
    "third-party",
    "source diversity",
    "diversification",
    "benchmark",
    "confirm",
    "cross-check",
}
_KEYWORD_STOPWORDS = {
    "about",
    "across",
    "after",
    "against",
    "among",
    "are",
    "best",
    "between",
    "can",
    "current",
    "default",
    "does",
    "exact",
    "exactly",
    "find",
    "for",
    "from",
    "have",
    "how",
    "into",
    "main",
    "more",
    "most",
    "need",
    "open",
    "open-source",
    "open_source",
    "one",
    "ones",
    "out",
    "should",
    "show",
    "still",
    "that",
    "the",
    "their",
    "them",
    "there",
    "these",
    "those",
    "through",
    "top",
    "what",
    "which",
    "widely",
    "with",
    "would",
}
_RESOLUTION_HINTS = {
    "bounded",
    "by context",
    "depends on context",
    "distinguishing",
    "explicitly scoped",
    "not necessarily",
    "remaining uncertainty",
    "resolution is",
    "resolved by",
    "resolved in favor of",
    "tension resolved",
    "trade-off",
    "tradeoff",
}
_OPTIONAL_HINTS = {
    "none critical",
    "no shared benchmark exists",
    "single numeric ranking impossible",
    "remaining uncertainty is",
    "without another external query",
}
_RELEASE_HINTS = {
    "all constraints are satisfied",
    "all open gaps",
    "all residual gaps are resolved",
    "bounded enough",
    "can now answer",
    "can now be made",
    "enough to answer",
    "no further search",
    "no new facts are needed",
    "ready to answer",
    "sufficient evidence",
    "sufficiently mapped",
}
_GENERIC_RELEASE_QUERIES = {
    "",
    "fill highest-priority missing fact",
    "find one more independent confirming source",
    "refresh latest release notes or current source",
    "resolve contradiction with independent source",
}
_SYNTHESIS_HINTS = {
    "acknowledges niches",
    "articulate",
    "best serves as the core",
    "clearly communicate",
    "clearly justify",
    "clearly state",
    "coherent narrative",
    "concrete recommended stack",
    "context-dependent choices",
    "default format",
    "division of labor",
    "finalize which stack to recommend",
    "formulate a concrete recommended stack",
    "given all evidence",
    "how to phrase",
    "how to position",
    "how to present",
    "justify recommending",
    "need to translate",
    "selection guidance",
    "single framework best serves",
    "translate benchmark",
}
_ABSENCE_CHECK_HINTS = {
    "any evidence that",
    "any negative signals",
    "any new",
    "any recent pieces",
    "any strong recent counter-argument",
    "are there credible sources",
    "do these sources agree",
    "is there any",
    "most recent",
    "whether any",
    "whether there are any",
}
_BOUNDED_CONTRADICTION_HINTS = {
    "but newer data is more relevant",
    "confirming a role distinction",
    "market share vs",
    "rather than direct contradiction",
    "reconciled by",
}


@dataclass(frozen=True)
class ResearchDecisionCase:
    case_id: str
    session_id: str
    prompt: str
    user_goal: str
    known_facts: list[str]
    open_gaps: list[str]
    contradictions: list[str]
    latest_docs: list[dict[str, Any]]
    context_tokens_so_far: int
    new_docs_tokens: int
    gold_action: str
    gold_query_intent: str
    quality_passed: bool
    tokens_if_search_more: int
    tokens_if_converge: int
    estimated_output_tokens: int = 180
    contradiction_records: list[dict[str, Any]] = field(default_factory=list)
    frontier_reference_action: str = ""
    frontier_reference_query_intent: str = ""
    frontier_reference_next_query: str = ""
    frontier_reference_rationale: str = ""


@dataclass(frozen=True)
class ResearchC2AState:
    constraint_tags: list[str]
    residual_constraints: list[str]
    hard_constraints: list[str]
    soft_constraints: list[str]
    contradiction_constraints: list[str]
    evidence_constraints: list[str]
    recency_constraints: list[str]
    source_diversity_constraints: list[str]
    preferred_query_intent: str
    converge_allowed: bool
    release_mode: str
    verifier_summary: str


@dataclass(frozen=True)
class LaneDecision:
    action: str
    query_intent: str
    next_query: str
    rationale: str
    raw_response: str
    parse_mode: str
    verifier_forced: bool = False
    verifier_reason: str = ""
    residual_constraints: list[str] = field(default_factory=list)
    hard_constraints: list[str] = field(default_factory=list)
    soft_constraints: list[str] = field(default_factory=list)
    converge_allowed: bool = True
    preferred_query_intent: str = "none"
    release_readiness: str = "blocked"
    blocking_constraints: list[str] = field(default_factory=list)
    bounded_constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResearchLanePricing:
    input_price_per_million: float = 0.0
    output_price_per_million: float = 0.0
    fixed_cost_per_decision: float = 0.0


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").strip().split())


def _normalize_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = _normalize_text(value)
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_bool(value: Any, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return bool(default)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y"}:
        return True
    if text in {"0", "false", "no", "n"}:
        return False
    return bool(default)


def _get_first(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload and payload.get(key) is not None:
            return payload.get(key)
    return default


def _normalize_docs(values: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for value in values[:12]:
        if not isinstance(value, dict):
            continue
        source = _normalize_text(str(_get_first(value, "source", "label", "title", default="") or ""))
        snippet = _normalize_text(str(_get_first(value, "snippet", "summary", "detail", default="") or ""))
        tokens = _to_int(_get_first(value, "tokens", "tokens_estimate", default=0), 0)
        out.append(
            {
                "source": source,
                "snippet": snippet,
                "tokens": tokens,
            }
        )
    return out


def _normalize_contradictions(
    values: list[Any],
    *,
    contradiction_records: list[Any] | None = None,
) -> tuple[list[str], list[dict[str, Any]]]:
    texts: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            source = _normalize_text(str(_get_first(value, "source", "label", "title", default="") or ""))
            snippet = _normalize_text(str(_get_first(value, "snippet", "summary", "detail", default="") or ""))
            clean = _normalize_text(f"{source}: {snippet}" if source and snippet else snippet or source)
        else:
            clean = _normalize_text(str(value or ""))
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        texts.append(clean)
    records = _normalize_docs(list(contradiction_records or []))
    if not records:
        records = _normalize_docs(values)
    return texts, records


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        return {}
    clean = re.sub(r",(\s*[}\]])", r"\1", clean)
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if not match:
        return {}
    blob = re.sub(r",(\s*[}\]])", r"\1", match.group(0))
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _coerce_action(action: str) -> str:
    clean = _normalize_text(action).lower()
    if clean in {"search_more", "search", "requery", "re-query", "continue"}:
        return "search_more"
    if clean in {"converge", "stop", "finalize", "answer"}:
        return "converge"
    return "search_more"


def _coerce_intent(intent: str) -> str:
    clean = _normalize_text(intent).lower().replace("-", "_")
    alias = {
        "resolve_conflict": "resolve_contradiction",
        "contradiction": "resolve_contradiction",
        "coverage": "source_diversification",
        "diversify": "source_diversification",
        "freshness": "recency_refresh",
        "missing": "missing_fact",
        "": "none",
    }
    clean = alias.get(clean, clean)
    return clean if clean in _ALLOWED_INTENTS else "none"


def _decision_from_text(text: str) -> tuple[str, str]:
    lowered = str(text or "").lower()
    action = "search_more"
    if any(token in lowered for token in ("converge", "final answer", "ready to answer", "stop searching")):
        action = "converge"
    if any(token in lowered for token in ("search more", "re-query", "query again", "need more sources")):
        action = "search_more"
    intent = "none"
    if "contradict" in lowered:
        intent = "resolve_contradiction"
    elif any(token in lowered for token in ("divers", "independent source", "second source")):
        intent = "source_diversification"
    elif any(token in lowered for token in ("recent", "latest", "updated")):
        intent = "recency_refresh"
    elif any(token in lowered for token in ("missing", "unknown", "gap")):
        intent = "missing_fact"
    return action, intent


def _looks_like_gap(text: str, hints: set[str]) -> bool:
    lowered = _normalize_text(text).lower()
    return any(hint in lowered for hint in hints)


def _is_synthesis_gap(text: str) -> bool:
    lowered = _constraint_body(text).lower()
    return any(hint in lowered for hint in _SYNTHESIS_HINTS)


def _is_absence_check(text: str) -> bool:
    lowered = _constraint_body(text).lower()
    return any(hint in lowered for hint in _ABSENCE_CHECK_HINTS)


def _format_residual(label: str, text: str) -> str:
    clean = _normalize_text(text)
    return f"{label}: {clean}" if clean else label


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return _normalize_list([str(item) for item in value])
    if isinstance(value, str):
        clean = _normalize_text(value)
        return [clean] if clean else []
    return []


def _constraint_body(constraint: str) -> str:
    clean = _normalize_text(constraint)
    if ":" in clean:
        return clean.split(":", 1)[1].strip()
    return clean


def _keyword_tokens(text: str) -> set[str]:
    clean = _constraint_body(text).lower()
    tokens = set(re.findall(r"[a-z0-9]{3,}", clean))
    return {token for token in tokens if token not in _KEYWORD_STOPWORDS}


def _collect_evidence_texts(case: ResearchDecisionCase) -> list[str]:
    texts = list(case.known_facts) + list(case.contradictions)
    for doc in list(case.latest_docs) + list(case.contradiction_records):
        if not isinstance(doc, dict):
            continue
        source = _normalize_text(str(doc.get("source") or ""))
        snippet = _normalize_text(str(doc.get("snippet") or ""))
        text = _normalize_text(f"{source} {snippet}")
        if text:
            texts.append(text)
    return [text for text in texts if text]


def _coverage_ready_for_release(case: ResearchDecisionCase) -> bool:
    doc_count = len(case.latest_docs) + len(case.contradiction_records)
    fact_count = len(case.known_facts)
    contradiction_count = len(case.contradictions)
    if case.context_tokens_so_far >= 16000:
        return True
    if doc_count >= 7:
        return True
    if doc_count >= 6 and fact_count >= 4 and case.new_docs_tokens >= 2500:
        return True
    if doc_count >= 5 and fact_count >= 4 and contradiction_count >= 1:
        return True
    return False


def _constraint_support_score(constraint: str, evidence_tokens: set[str]) -> float:
    keywords = _keyword_tokens(constraint)
    if not keywords:
        return 0.0
    matched = len(keywords & evidence_tokens)
    return float(matched) / float(len(keywords))


def _classify_constraint(
    *,
    kind: str,
    constraint: str,
    case: ResearchDecisionCase,
    evidence_tokens: set[str],
    coverage_ready: bool,
    recent_year_present: bool,
    distinct_source_count: int,
) -> str:
    lowered = _constraint_body(constraint).lower()
    support = _constraint_support_score(constraint, evidence_tokens)
    doc_count = len(case.latest_docs) + len(case.contradiction_records)
    fact_count = len(case.known_facts)
    synthesis_gap = _is_synthesis_gap(constraint)
    absence_check = _is_absence_check(constraint)
    resolved_text = any(hint in lowered for hint in _RESOLUTION_HINTS | _BOUNDED_CONTRADICTION_HINTS)
    optional_text = any(hint in lowered for hint in _OPTIONAL_HINTS)

    if kind == "resolve_contradiction":
        if resolved_text or optional_text:
            return "soft"
        if coverage_ready and support >= 0.35 and max(doc_count, fact_count) >= 2:
            return "soft"
        return "hard"

    if kind == "refresh_recency":
        if absence_check and coverage_ready and recent_year_present and distinct_source_count >= 2:
            return "soft"
        if coverage_ready and recent_year_present and (resolved_text or support >= 0.55):
            return "soft"
        return "hard"

    if kind == "diversify_sources":
        enough_sources = distinct_source_count >= 2 or doc_count >= 7
        if synthesis_gap and coverage_ready and enough_sources:
            return "soft"
        if optional_text:
            return "soft"
        if coverage_ready and enough_sources and support >= 0.4:
            return "soft"
        return "hard"

    if kind == "fill_missing_fact":
        enough_evidence = doc_count >= 4 or fact_count >= 4
        if synthesis_gap and coverage_ready and enough_evidence:
            return "soft"
        if absence_check and coverage_ready and recent_year_present and distinct_source_count >= 2:
            return "soft"
        if optional_text or resolved_text:
            return "soft"
        if coverage_ready and support >= 0.48 and enough_evidence:
            return "soft"
        return "hard"

    return "hard"


def compile_research_c2a_state(case: ResearchDecisionCase) -> ResearchC2AState:
    contradiction_constraints = [_format_residual("resolve_contradiction", item) for item in case.contradictions]
    recency_constraints: list[str] = []
    source_diversity_constraints: list[str] = []
    evidence_constraints: list[str] = []
    for gap in case.open_gaps:
        if _is_synthesis_gap(gap):
            evidence_constraints.append(_format_residual("fill_missing_fact", gap))
        elif _looks_like_gap(gap, _RECENCY_HINTS):
            recency_constraints.append(_format_residual("refresh_recency", gap))
        elif _looks_like_gap(gap, _SOURCE_DIVERSITY_HINTS):
            source_diversity_constraints.append(_format_residual("diversify_sources", gap))
        else:
            evidence_constraints.append(_format_residual("fill_missing_fact", gap))
    residual_constraints = (
        list(contradiction_constraints)
        + list(recency_constraints)
        + list(source_diversity_constraints)
        + list(evidence_constraints)
    )
    evidence_texts = _collect_evidence_texts(case)
    evidence_tokens: set[str] = set()
    for text in evidence_texts:
        evidence_tokens.update(_keyword_tokens(text))
    recent_year_present = any(year in evidence_tokens for year in {"2024", "2025", "2026", "2027"})
    distinct_source_count = len(
        {
            _normalize_text(str(doc.get("source") or "")).lower()
            for doc in list(case.latest_docs) + list(case.contradiction_records)
            if isinstance(doc, dict) and _normalize_text(str(doc.get("source") or ""))
        }
    )
    coverage_ready = _coverage_ready_for_release(case)
    hard_constraints: list[str] = []
    soft_constraints: list[str] = []
    for kind, constraints in (
        ("resolve_contradiction", contradiction_constraints),
        ("refresh_recency", recency_constraints),
        ("diversify_sources", source_diversity_constraints),
        ("fill_missing_fact", evidence_constraints),
    ):
        for constraint in constraints:
            bucket = _classify_constraint(
                kind=kind,
                constraint=constraint,
                case=case,
                evidence_tokens=evidence_tokens,
                coverage_ready=coverage_ready,
                recent_year_present=recent_year_present,
                distinct_source_count=distinct_source_count,
            )
            if bucket == "soft":
                soft_constraints.append(constraint)
            else:
                hard_constraints.append(constraint)
    preferred_query_intent = "none"
    if any(item in hard_constraints for item in contradiction_constraints):
        preferred_query_intent = "resolve_contradiction"
    elif any(item in hard_constraints for item in recency_constraints):
        preferred_query_intent = "recency_refresh"
    elif any(item in hard_constraints for item in source_diversity_constraints):
        preferred_query_intent = "source_diversification"
    elif any(item in hard_constraints for item in evidence_constraints):
        preferred_query_intent = "missing_fact"
    constraint_tags = ["research_loop_binary_decision"]
    if contradiction_constraints:
        constraint_tags.append("research_contradiction_resolution")
    if recency_constraints:
        constraint_tags.append("research_recency_guard")
    if source_diversity_constraints:
        constraint_tags.append("research_source_diversity_guard")
    if evidence_constraints:
        constraint_tags.append("research_missing_evidence_guard")
    if hard_constraints:
        converge_allowed = False
        release_mode = "hard_blocked"
        verifier_summary = "Converge is illegal until hard research blockers are cleared."
    elif soft_constraints:
        converge_allowed = True
        release_mode = "bounded_release"
        verifier_summary = "Converge is legal if the final answer explicitly scopes the remaining bounded ambiguity."
    else:
        converge_allowed = True
        release_mode = "clean_release"
        verifier_summary = "Converge is legal; no material research blockers remain."
    return ResearchC2AState(
        constraint_tags=constraint_tags,
        residual_constraints=residual_constraints,
        hard_constraints=hard_constraints,
        soft_constraints=soft_constraints,
        contradiction_constraints=contradiction_constraints,
        evidence_constraints=evidence_constraints,
        recency_constraints=recency_constraints,
        source_diversity_constraints=source_diversity_constraints,
        preferred_query_intent=preferred_query_intent,
        converge_allowed=converge_allowed,
        release_mode=release_mode,
        verifier_summary=verifier_summary,
    )


def _render_docs(docs: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for index, doc in enumerate(docs[:8], start=1):
        if not isinstance(doc, dict):
            continue
        source = _normalize_text(str(doc.get("source") or ""))
        snippet = _normalize_text(str(doc.get("snippet") or ""))
        tokens = _to_int(doc.get("tokens"), 0)
        lines.append(f"- [{index}] source={source or 'unknown'} tokens={tokens} snippet={snippet}")
    return "\n".join(lines)


def _build_raw_case_prompt(case: ResearchDecisionCase) -> str:
    return "\n".join(
        [
            f"User goal: {case.user_goal or case.prompt}",
            f"Prompt: {case.prompt}",
            f"Known facts: {', '.join(case.known_facts) if case.known_facts else '(none)'}",
            f"Open gaps: {', '.join(case.open_gaps) if case.open_gaps else '(none)'}",
            f"Contradictions: {', '.join(case.contradictions) if case.contradictions else '(none)'}",
            f"Context tokens so far: {case.context_tokens_so_far}",
            f"New docs tokens: {case.new_docs_tokens}",
            "Latest docs:",
            _render_docs(case.latest_docs) or "- (none)",
            "Return strict JSON only.",
        ]
    )


def _build_memla_case_prompt(case: ResearchDecisionCase, state: ResearchC2AState) -> str:
    return "\n".join(
        [
            f"User goal: {case.user_goal or case.prompt}",
            f"Prompt: {case.prompt}",
            "Decision surface: search_more | converge",
            "Goal coverage rule: converge only if the current evidence covers the full user goal, not just a subset of listed open gaps.",
            "For compare/rank/recommend tasks, do not converge until the main candidate set and recommendation basis are broad enough to justify the answer.",
            "Recommendation phrasing, division-of-labor framing, and counterexample sweeps become bounded residuals once the evidence basis is already broad enough.",
            f"Known facts: {', '.join(case.known_facts) if case.known_facts else '(none)'}",
            f"Open gaps: {', '.join(case.open_gaps) if case.open_gaps else '(none)'}",
            f"Contradictions: {', '.join(case.contradictions) if case.contradictions else '(none)'}",
            f"Constraint tags: {', '.join(state.constraint_tags) if state.constraint_tags else '(none)'}",
            f"Residual constraints: {', '.join(state.residual_constraints) if state.residual_constraints else '(none)'}",
            f"Hard blockers: {', '.join(state.hard_constraints) if state.hard_constraints else '(none)'}",
            f"Soft bounded residuals: {', '.join(state.soft_constraints) if state.soft_constraints else '(none)'}",
            f"Converge legal: {'yes' if state.converge_allowed else 'no'}",
            f"Release mode: {state.release_mode}",
            f"Preferred query intent if searching: {state.preferred_query_intent}",
            f"Verifier summary: {state.verifier_summary}",
            f"Context tokens so far: {case.context_tokens_so_far}",
            f"New docs tokens: {case.new_docs_tokens}",
            "Latest docs:",
            _render_docs(case.latest_docs) or "- (none)",
            "Contradiction evidence:",
            _render_docs(case.contradiction_records) or "- (none)",
            "Return strict JSON only.",
        ]
    )


def _default_query_for_state(state: ResearchC2AState) -> str:
    if any(item in state.hard_constraints for item in state.contradiction_constraints):
        return "resolve contradiction with independent source"
    if any(item in state.hard_constraints for item in state.recency_constraints):
        return "refresh latest release notes or current source"
    if any(item in state.hard_constraints for item in state.source_diversity_constraints):
        return "find one more independent confirming source"
    if any(item in state.hard_constraints for item in state.evidence_constraints):
        return "fill highest-priority missing fact"
    return ""


def _decision_signals_release(decision: LaneDecision) -> bool:
    readiness = _normalize_text(decision.release_readiness).lower()
    if readiness == "bounded_enough":
        return True
    rationale = _normalize_text(decision.rationale).lower()
    if any(hint in rationale for hint in _RELEASE_HINTS):
        return True
    if decision.bounded_constraints and not decision.blocking_constraints:
        return True
    return False


def _apply_memla_c2a_verifier(decision: LaneDecision, state: ResearchC2AState) -> LaneDecision:
    action = decision.action
    query_intent = decision.query_intent
    next_query = decision.next_query
    forced = False
    reasons: list[str] = []

    if not state.converge_allowed and action == "converge":
        action = "search_more"
        forced = True
        reasons.append("blocked_illegal_converge")

    if state.converge_allowed and action == "search_more" and _decision_signals_release(decision):
        action = "converge"
        query_intent = "none"
        next_query = ""
        forced = True
        reasons.append("released_bounded_constraints")

    if action == "search_more":
        if state.preferred_query_intent != "none" and query_intent != state.preferred_query_intent:
            query_intent = state.preferred_query_intent
            forced = True
            reasons.append("aligned_query_intent_to_residual_constraints")
        if not next_query:
            next_query = _default_query_for_state(state)
    else:
        query_intent = "none"
        next_query = ""

    verifier_reason = "; ".join(reasons)
    rationale = decision.rationale
    if verifier_reason:
        rationale = _normalize_text(f"{rationale} verifier={verifier_reason}")
    return LaneDecision(
        action=action,
        query_intent=query_intent,
        next_query=_normalize_text(next_query),
        rationale=rationale,
        raw_response=decision.raw_response,
        parse_mode=decision.parse_mode,
        verifier_forced=forced,
        verifier_reason=verifier_reason,
        residual_constraints=list(state.residual_constraints),
        hard_constraints=list(state.hard_constraints),
        soft_constraints=list(state.soft_constraints),
        converge_allowed=state.converge_allowed,
        preferred_query_intent=state.preferred_query_intent,
        release_readiness=decision.release_readiness,
        blocking_constraints=list(decision.blocking_constraints),
        bounded_constraints=list(decision.bounded_constraints),
    )


def _query_lane_decision(
    *,
    client: Any,
    model: str,
    case: ResearchDecisionCase,
    lane: str,
    temperature: float,
    num_ctx: int | None,
) -> LaneDecision:
    state = compile_research_c2a_state(case)
    system = RESEARCH_MEMLA_SYSTEM if lane == "memla" else RESEARCH_RAW_SYSTEM
    prompt = _build_memla_case_prompt(case, state) if lane == "memla" else _build_raw_case_prompt(case)
    response = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=system),
            ChatMessage(role="user", content=prompt),
        ],
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()
    payload = _extract_json_object(response)
    parse_mode = "json"
    if not payload:
        action_guess, intent_guess = _decision_from_text(response)
        payload = {
            "action": action_guess,
            "query_intent": intent_guess,
            "next_query": "",
            "rationale": "heuristic parse from non-JSON response",
        }
        parse_mode = "heuristic"

    action = _coerce_action(str(payload.get("action") or "search_more"))
    query_intent = _coerce_intent(str(payload.get("query_intent") or "none"))
    if action == "converge":
        query_intent = "none"
    release_readiness = _normalize_text(str(payload.get("release_readiness") or ""))
    if release_readiness.lower() not in {"blocked", "bounded_enough"}:
        release_readiness = "bounded_enough" if action == "converge" else "blocked"
    blocking_constraints = _normalize_string_list(payload.get("blocking_constraints"))
    bounded_constraints = _normalize_string_list(payload.get("bounded_constraints"))
    decision = LaneDecision(
        action=action,
        query_intent=query_intent,
        next_query=_normalize_text(str(payload.get("next_query") or "")),
        rationale=_normalize_text(str(payload.get("rationale") or "")),
        raw_response=response,
        parse_mode=parse_mode,
        residual_constraints=list(state.residual_constraints),
        hard_constraints=list(state.hard_constraints),
        soft_constraints=list(state.soft_constraints),
        converge_allowed=state.converge_allowed,
        preferred_query_intent=state.preferred_query_intent,
        release_readiness=release_readiness,
        blocking_constraints=blocking_constraints,
        bounded_constraints=bounded_constraints,
    )
    if lane == "memla":
        return _apply_memla_c2a_verifier(decision, state)
    return decision


def _logged_reference_lane_decision(case: ResearchDecisionCase) -> LaneDecision:
    raw_action = _normalize_text(case.frontier_reference_action or "")
    if not raw_action:
        raise ValueError(f"Case {case.case_id} is missing frontier reference action for logged-baseline replay.")
    action = _coerce_action(raw_action)
    query_intent = _coerce_intent(case.frontier_reference_query_intent or "none")
    if action == "converge":
        query_intent = "none"
    return LaneDecision(
        action=action,
        query_intent=query_intent,
        next_query=_normalize_text(case.frontier_reference_next_query),
        rationale=_normalize_text(case.frontier_reference_rationale or "loaded from historical baseline log"),
        raw_response="",
        parse_mode="logged",
        verifier_forced=False,
        verifier_reason="",
        release_readiness="bounded_enough" if action == "converge" else "blocked",
        blocking_constraints=[],
        bounded_constraints=[],
    )


def _decision_cost(
    *,
    case: ResearchDecisionCase,
    action: str,
    input_price_per_million: float,
    output_price_per_million: float,
) -> dict[str, float]:
    base_input = max(case.context_tokens_so_far, 0) + max(case.new_docs_tokens, 0)
    follow_on = case.tokens_if_search_more if action == "search_more" else case.tokens_if_converge
    input_tokens = max(base_input + max(follow_on, 0), 0)
    output_tokens = max(case.estimated_output_tokens, 0)
    cost = (input_tokens / 1_000_000.0) * float(input_price_per_million) + (
        (output_tokens / 1_000_000.0) * float(output_price_per_million)
    )
    return {
        "estimated_input_tokens": float(input_tokens),
        "estimated_output_tokens": float(output_tokens),
        "estimated_cost": round(float(cost), 8),
    }


def _configured_lane_pricing(
    *,
    input_price_per_million: float | None = None,
    output_price_per_million: float | None = None,
    fixed_cost_per_decision: float | None = None,
) -> ResearchLanePricing | None:
    if input_price_per_million is None and output_price_per_million is None and fixed_cost_per_decision is None:
        return None
    return ResearchLanePricing(
        input_price_per_million=_to_float(input_price_per_million, 0.0),
        output_price_per_million=_to_float(output_price_per_million, 0.0),
        fixed_cost_per_decision=_to_float(fixed_cost_per_decision, 0.0),
    )


def _lane_pricing_payload(pricing: ResearchLanePricing | None) -> dict[str, Any]:
    if pricing is None:
        return {"configured": False}
    return {
        "configured": True,
        "input_price_per_million": round(float(pricing.input_price_per_million), 8),
        "output_price_per_million": round(float(pricing.output_price_per_million), 8),
        "fixed_cost_per_decision": round(float(pricing.fixed_cost_per_decision), 8),
    }


def _modeled_lane_cost(
    *,
    input_tokens: float,
    output_tokens: float,
    decision_count: float,
    pricing: ResearchLanePricing | None,
) -> float:
    if pricing is None:
        return 0.0
    variable_cost = (max(float(input_tokens), 0.0) / 1_000_000.0) * float(pricing.input_price_per_million)
    variable_cost += (max(float(output_tokens), 0.0) / 1_000_000.0) * float(pricing.output_price_per_million)
    fixed_cost = max(float(decision_count), 0.0) * float(pricing.fixed_cost_per_decision)
    return float(variable_cost + fixed_cost)


def _clamp_rate(value: float | None) -> float:
    if value is None:
        return 0.0
    return max(0.0, min(float(value), 1.0))


def _summarize_lane_deployment_costs(
    *,
    total_costs: list[float],
    base_costs: list[float] | None = None,
    fallback_costs: list[float] | None = None,
    avg_decisions: float | None = None,
    replay_mode: bool,
) -> dict[str, Any]:
    if not total_costs:
        return {"configured": False}
    avg_total = sum(float(value) for value in total_costs) / float(len(total_costs))
    payload: dict[str, Any] = {
        "configured": True,
        "modeled_cost_per_1k_sessions": round(avg_total * 1000.0, 2) if not replay_mode else 0.0,
    }
    if replay_mode:
        decisions_per_session = max(float(avg_decisions or 0.0), 0.0)
        avg_session_cost = avg_total * decisions_per_session
        payload["avg_modeled_cost_per_decision"] = round(avg_total, 8)
        payload["avg_modeled_cost_per_session"] = round(avg_session_cost, 8)
        payload["modeled_cost_per_1k_sessions"] = round(avg_session_cost * 1000.0, 2)
    else:
        payload["avg_modeled_cost_per_session"] = round(avg_total, 8)
        if avg_decisions and avg_decisions > 0:
            payload["avg_modeled_cost_per_decision"] = round(avg_total / float(avg_decisions), 8)
    if base_costs:
        avg_base = sum(float(value) for value in base_costs) / float(len(base_costs))
        if replay_mode:
            payload["avg_base_modeled_cost_per_decision"] = round(avg_base, 8)
            payload["avg_base_modeled_cost_per_session"] = round(avg_base * max(float(avg_decisions or 0.0), 0.0), 8)
        else:
            payload["avg_base_modeled_cost_per_session"] = round(avg_base, 8)
            if avg_decisions and avg_decisions > 0:
                payload["avg_base_modeled_cost_per_decision"] = round(avg_base / float(avg_decisions), 8)
    if fallback_costs:
        avg_fallback = sum(float(value) for value in fallback_costs) / float(len(fallback_costs))
        if replay_mode:
            payload["avg_fallback_modeled_cost_per_decision"] = round(avg_fallback, 8)
            payload["avg_fallback_modeled_cost_per_session"] = round(
                avg_fallback * max(float(avg_decisions or 0.0), 0.0),
                8,
            )
        else:
            payload["avg_fallback_modeled_cost_per_session"] = round(avg_fallback, 8)
            if avg_decisions and avg_decisions > 0:
                payload["avg_fallback_modeled_cost_per_decision"] = round(avg_fallback / float(avg_decisions), 8)
    return payload


def _compute_replay_deployment_economics(
    *,
    rows: list[dict[str, Any]],
    memla_verifier_override_rate: float,
    deploy_raw_pricing: ResearchLanePricing | None,
    deploy_memla_pricing: ResearchLanePricing | None,
    deploy_frontier_pricing: ResearchLanePricing | None,
    deploy_memla_fallback_pricing: ResearchLanePricing | None,
    deploy_memla_fallback_rate: float | None,
    deploy_memla_fallback_use_verifier_rate: bool,
    deploy_decisions_per_session: float | None,
) -> dict[str, Any] | None:
    requested = any(
        item is not None
        for item in (
            deploy_raw_pricing,
            deploy_memla_pricing,
            deploy_frontier_pricing,
            deploy_memla_fallback_pricing,
            deploy_memla_fallback_rate,
        )
    ) or bool(deploy_memla_fallback_use_verifier_rate or deploy_decisions_per_session is not None)
    if not requested:
        return None

    session_ids = {
        _normalize_text(str(row.get("session_id") or "")).lower()
        for row in rows
        if _normalize_text(str(row.get("session_id") or ""))
    }
    sessions_observed = len(session_ids) or max(len(rows), 1)
    decisions_observed = len(rows)
    observed_decisions_per_session = float(decisions_observed) / float(max(sessions_observed, 1))
    decisions_per_session_used = (
        float(deploy_decisions_per_session)
        if deploy_decisions_per_session is not None and float(deploy_decisions_per_session) > 0
        else observed_decisions_per_session
    )
    memla_fallback_rate = (
        _clamp_rate(deploy_memla_fallback_rate)
        if deploy_memla_fallback_rate is not None
        else (_clamp_rate(memla_verifier_override_rate) if deploy_memla_fallback_use_verifier_rate else 0.0)
    )
    fallback_rate_source = (
        "explicit"
        if deploy_memla_fallback_rate is not None
        else ("verifier_override_rate" if deploy_memla_fallback_use_verifier_rate else "none")
    )
    fallback_pricing = deploy_memla_fallback_pricing or deploy_frontier_pricing
    fallback_pricing_source = (
        "explicit"
        if deploy_memla_fallback_pricing is not None
        else ("frontier_lane" if deploy_frontier_pricing is not None else "none")
    )

    lane_totals: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}
    lane_base: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}
    lane_fallback: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}

    for row in rows:
        for lane_key, pricing in (
            ("raw", deploy_raw_pricing),
            ("memla", deploy_memla_pricing),
            ("frontier", deploy_frontier_pricing),
        ):
            base_cost = _modeled_lane_cost(
                input_tokens=float(row.get(f"{lane_key}_estimated_input_tokens", 0.0) or 0.0),
                output_tokens=float(row.get(f"{lane_key}_estimated_output_tokens", 0.0) or 0.0),
                decision_count=1.0,
                pricing=pricing,
            )
            fallback_cost = 0.0
            if lane_key == "memla" and memla_fallback_rate > 0.0 and fallback_pricing is not None:
                fallback_cost = memla_fallback_rate * _modeled_lane_cost(
                    input_tokens=float(row.get(f"{lane_key}_estimated_input_tokens", 0.0) or 0.0),
                    output_tokens=float(row.get(f"{lane_key}_estimated_output_tokens", 0.0) or 0.0),
                    decision_count=1.0,
                    pricing=fallback_pricing,
                )
            if pricing is None and fallback_cost <= 0.0:
                continue
            lane_base[lane_key].append(base_cost)
            lane_fallback[lane_key].append(fallback_cost)
            lane_totals[lane_key].append(base_cost + fallback_cost)

    raw_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["raw"],
        base_costs=lane_base["raw"],
        avg_decisions=decisions_per_session_used,
        replay_mode=True,
    )
    memla_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["memla"],
        base_costs=lane_base["memla"],
        fallback_costs=lane_fallback["memla"],
        avg_decisions=decisions_per_session_used,
        replay_mode=True,
    )
    frontier_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["frontier"],
        base_costs=lane_base["frontier"],
        avg_decisions=decisions_per_session_used,
        replay_mode=True,
    )

    frontier_cost_per_1k = frontier_summary.get("modeled_cost_per_1k_sessions") if frontier_summary.get("configured") else None
    savings_payload: dict[str, Any] = {"frontier": 0.0 if frontier_cost_per_1k is not None else None}
    for lane_key, summary in (("raw", raw_summary), ("memla", memla_summary)):
        if frontier_cost_per_1k is None or not summary.get("configured"):
            savings_payload[lane_key] = None
        else:
            savings_payload[lane_key] = round(float(frontier_cost_per_1k) - float(summary["modeled_cost_per_1k_sessions"]), 2)

    return {
        "configured": True,
        "mode": "deployment_model_v1",
        "cost_basis": "usd_per_1000_sessions",
        "sessions_observed": int(sessions_observed),
        "decisions_observed": int(decisions_observed),
        "observed_decisions_per_session": round(observed_decisions_per_session, 4),
        "decisions_per_session_used": round(decisions_per_session_used, 4),
        "memla_fallback_rate": round(memla_fallback_rate, 4),
        "memla_fallback_rate_source": fallback_rate_source,
        "pricing": {
            "raw": _lane_pricing_payload(deploy_raw_pricing),
            "memla": _lane_pricing_payload(deploy_memla_pricing),
            "frontier": _lane_pricing_payload(deploy_frontier_pricing),
            "memla_fallback": {
                **_lane_pricing_payload(fallback_pricing),
                "source": fallback_pricing_source,
            },
        },
        "raw": raw_summary,
        "memla": memla_summary,
        "frontier": frontier_summary,
        "savings_vs_frontier_per_1k_sessions": savings_payload,
    }


def _compute_live_deployment_economics(
    *,
    rows: list[dict[str, Any]],
    memla_verifier_override_rate: float,
    deploy_raw_pricing: ResearchLanePricing | None,
    deploy_memla_pricing: ResearchLanePricing | None,
    deploy_frontier_pricing: ResearchLanePricing | None,
    deploy_memla_fallback_pricing: ResearchLanePricing | None,
    deploy_memla_fallback_rate: float | None,
    deploy_memla_fallback_use_verifier_rate: bool,
) -> dict[str, Any] | None:
    requested = any(
        item is not None
        for item in (
            deploy_raw_pricing,
            deploy_memla_pricing,
            deploy_frontier_pricing,
            deploy_memla_fallback_pricing,
            deploy_memla_fallback_rate,
        )
    ) or bool(deploy_memla_fallback_use_verifier_rate)
    if not requested:
        return None

    sessions_observed = len(rows)
    avg_iterations_observed = (
        sum(float(row.get("memla_iterations_used", 0.0) or 0.0) for row in rows) / float(max(len(rows), 1))
        if rows
        else 0.0
    )
    memla_fallback_rate = (
        _clamp_rate(deploy_memla_fallback_rate)
        if deploy_memla_fallback_rate is not None
        else (_clamp_rate(memla_verifier_override_rate) if deploy_memla_fallback_use_verifier_rate else 0.0)
    )
    fallback_rate_source = (
        "explicit"
        if deploy_memla_fallback_rate is not None
        else ("verifier_override_rate" if deploy_memla_fallback_use_verifier_rate else "none")
    )
    fallback_pricing = deploy_memla_fallback_pricing or deploy_frontier_pricing
    fallback_pricing_source = (
        "explicit"
        if deploy_memla_fallback_pricing is not None
        else ("frontier_lane" if deploy_frontier_pricing is not None else "none")
    )

    lane_totals: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}
    lane_base: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}
    lane_fallback: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}
    lane_decisions: dict[str, list[float]] = {"raw": [], "memla": [], "frontier": []}

    for row in rows:
        for lane_key, pricing in (
            ("raw", deploy_raw_pricing),
            ("memla", deploy_memla_pricing),
            ("frontier", deploy_frontier_pricing),
        ):
            decisions = float(row.get(f"{lane_key}_iterations_used", 0.0) or 0.0)
            base_cost = _modeled_lane_cost(
                input_tokens=float(row.get(f"{lane_key}_estimated_input_tokens", 0.0) or 0.0),
                output_tokens=float(row.get(f"{lane_key}_estimated_output_tokens", 0.0) or 0.0),
                decision_count=decisions,
                pricing=pricing,
            )
            fallback_cost = 0.0
            if lane_key == "memla" and memla_fallback_rate > 0.0 and fallback_pricing is not None:
                fallback_cost = memla_fallback_rate * _modeled_lane_cost(
                    input_tokens=float(row.get(f"{lane_key}_estimated_input_tokens", 0.0) or 0.0),
                    output_tokens=float(row.get(f"{lane_key}_estimated_output_tokens", 0.0) or 0.0),
                    decision_count=decisions,
                    pricing=fallback_pricing,
                )
            if pricing is None and fallback_cost <= 0.0:
                continue
            lane_base[lane_key].append(base_cost)
            lane_fallback[lane_key].append(fallback_cost)
            lane_totals[lane_key].append(base_cost + fallback_cost)
            lane_decisions[lane_key].append(decisions)

    raw_avg_decisions = sum(lane_decisions["raw"]) / float(max(len(lane_decisions["raw"]), 1)) if lane_decisions["raw"] else None
    memla_avg_decisions = sum(lane_decisions["memla"]) / float(max(len(lane_decisions["memla"]), 1)) if lane_decisions["memla"] else None
    frontier_avg_decisions = sum(lane_decisions["frontier"]) / float(max(len(lane_decisions["frontier"]), 1)) if lane_decisions["frontier"] else None
    raw_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["raw"],
        base_costs=lane_base["raw"],
        avg_decisions=raw_avg_decisions,
        replay_mode=False,
    )
    memla_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["memla"],
        base_costs=lane_base["memla"],
        fallback_costs=lane_fallback["memla"],
        avg_decisions=memla_avg_decisions,
        replay_mode=False,
    )
    frontier_summary = _summarize_lane_deployment_costs(
        total_costs=lane_totals["frontier"],
        base_costs=lane_base["frontier"],
        avg_decisions=frontier_avg_decisions,
        replay_mode=False,
    )

    frontier_cost_per_1k = frontier_summary.get("modeled_cost_per_1k_sessions") if frontier_summary.get("configured") else None
    savings_payload: dict[str, Any] = {"frontier": 0.0 if frontier_cost_per_1k is not None else None}
    for lane_key, summary in (("raw", raw_summary), ("memla", memla_summary)):
        if frontier_cost_per_1k is None or not summary.get("configured"):
            savings_payload[lane_key] = None
        else:
            savings_payload[lane_key] = round(float(frontier_cost_per_1k) - float(summary["modeled_cost_per_1k_sessions"]), 2)

    return {
        "configured": True,
        "mode": "deployment_model_v1",
        "cost_basis": "usd_per_1000_sessions",
        "sessions_observed": int(sessions_observed),
        "avg_iterations_observed": round(avg_iterations_observed, 4),
        "memla_fallback_rate": round(memla_fallback_rate, 4),
        "memla_fallback_rate_source": fallback_rate_source,
        "pricing": {
            "raw": _lane_pricing_payload(deploy_raw_pricing),
            "memla": _lane_pricing_payload(deploy_memla_pricing),
            "frontier": _lane_pricing_payload(deploy_frontier_pricing),
            "memla_fallback": {
                **_lane_pricing_payload(fallback_pricing),
                "source": fallback_pricing_source,
            },
        },
        "raw": raw_summary,
        "memla": memla_summary,
        "frontier": frontier_summary,
        "savings_vs_frontier_per_1k_sessions": savings_payload,
    }


def load_research_loop_cases(path: str) -> list[ResearchDecisionCase]:
    cases: list[ResearchDecisionCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        session_id = _normalize_text(str(row.get("session_id") or row.get("case_id") or "session"))
        prompt = _normalize_text(str(row.get("prompt") or row.get("user_goal") or ""))
        user_goal = _normalize_text(str(row.get("user_goal") or prompt))

        loop_steps = list(row.get("loop_steps") or [])
        if loop_steps:
            for index, step in enumerate(loop_steps, start=1):
                contradictions, contradiction_records = _normalize_contradictions(
                    list(step.get("contradictions") or []),
                    contradiction_records=list(step.get("contradiction_records") or []),
                )
                cases.append(
                    ResearchDecisionCase(
                        case_id=_normalize_text(str(step.get("case_id") or f"{session_id}_step_{index}")),
                        session_id=session_id,
                        prompt=prompt,
                        user_goal=user_goal,
                        known_facts=_normalize_list(list(step.get("known_facts") or [])),
                        open_gaps=_normalize_list(list(step.get("open_gaps") or [])),
                        contradictions=contradictions,
                        latest_docs=_normalize_docs(list(step.get("latest_docs") or [])),
                        context_tokens_so_far=_to_int(
                            _get_first(step, "context_tokens_so_far", "context_tokens_so_far_estimate", default=0),
                            0,
                        ),
                        new_docs_tokens=_to_int(
                            _get_first(step, "new_docs_tokens", "new_docs_tokens_estimate", default=0),
                            0,
                        ),
                        gold_action=_coerce_action(
                            str(_get_first(step, "gold_action", "decision_action", default="search_more"))
                        ),
                        gold_query_intent=_coerce_intent(
                            str(_get_first(step, "gold_query_intent", "query_intent", default="none"))
                        ),
                        quality_passed=_to_bool(step.get("quality_passed"), _to_bool(row.get("quality_passed"), True)),
                        tokens_if_search_more=_to_int(
                            _get_first(step, "tokens_if_search_more", "tokens_if_search_more_estimate", default=2500),
                            2500,
                        ),
                        tokens_if_converge=_to_int(
                            _get_first(step, "tokens_if_converge", "tokens_if_converge_estimate", default=350),
                            350,
                        ),
                        estimated_output_tokens=_to_int(
                            _get_first(step, "estimated_output_tokens", "estimated_output_tokens_estimate", default=180),
                            180,
                        ),
                        contradiction_records=contradiction_records,
                        frontier_reference_action=_coerce_action(
                            str(
                                _get_first(
                                    step,
                                    "frontier_reference_action",
                                    "frontier_action",
                                    "baseline_action",
                                    "production_action",
                                    default="",
                                )
                            )
                        ),
                        frontier_reference_query_intent=_coerce_intent(
                            str(
                                _get_first(
                                    step,
                                    "frontier_reference_query_intent",
                                    "frontier_query_intent",
                                    "baseline_query_intent",
                                    "production_query_intent",
                                    default="none",
                                )
                            )
                        ),
                        frontier_reference_next_query=_normalize_text(
                            str(
                                _get_first(
                                    step,
                                    "frontier_reference_next_query",
                                    "frontier_next_query",
                                    "baseline_next_query",
                                    "production_next_query",
                                    default="",
                                )
                            )
                        ),
                        frontier_reference_rationale=_normalize_text(
                            str(
                                _get_first(
                                    step,
                                    "frontier_reference_rationale",
                                    "frontier_rationale",
                                    "baseline_rationale",
                                    "production_rationale",
                                    default="",
                                )
                            )
                        ),
                    )
                )
            continue

        contradictions, contradiction_records = _normalize_contradictions(
            list(row.get("contradictions") or []),
            contradiction_records=list(row.get("contradiction_records") or []),
        )
        cases.append(
            ResearchDecisionCase(
                case_id=_normalize_text(str(row.get("case_id") or session_id)),
                session_id=session_id,
                prompt=prompt,
                user_goal=user_goal,
                known_facts=_normalize_list(list(row.get("known_facts") or [])),
                open_gaps=_normalize_list(list(row.get("open_gaps") or [])),
                contradictions=contradictions,
                latest_docs=_normalize_docs(list(row.get("latest_docs") or [])),
                context_tokens_so_far=_to_int(
                    _get_first(row, "context_tokens_so_far", "context_tokens_so_far_estimate", default=0),
                    0,
                ),
                new_docs_tokens=_to_int(_get_first(row, "new_docs_tokens", "new_docs_tokens_estimate", default=0), 0),
                gold_action=_coerce_action(str(_get_first(row, "gold_action", "decision_action", default="search_more"))),
                gold_query_intent=_coerce_intent(str(_get_first(row, "gold_query_intent", "query_intent", default="none"))),
                quality_passed=_to_bool(row.get("quality_passed"), True),
                tokens_if_search_more=_to_int(
                    _get_first(row, "tokens_if_search_more", "tokens_if_search_more_estimate", default=2500),
                    2500,
                ),
                tokens_if_converge=_to_int(
                    _get_first(row, "tokens_if_converge", "tokens_if_converge_estimate", default=350),
                    350,
                ),
                estimated_output_tokens=_to_int(
                    _get_first(row, "estimated_output_tokens", "estimated_output_tokens_estimate", default=180),
                    180,
                ),
                contradiction_records=contradiction_records,
                frontier_reference_action=_coerce_action(
                    str(
                        _get_first(
                            row,
                            "frontier_reference_action",
                            "frontier_action",
                            "baseline_action",
                            "production_action",
                            default="",
                        )
                    )
                ),
                frontier_reference_query_intent=_coerce_intent(
                    str(
                        _get_first(
                            row,
                            "frontier_reference_query_intent",
                            "frontier_query_intent",
                            "baseline_query_intent",
                            "production_query_intent",
                            default="none",
                        )
                    )
                ),
                frontier_reference_next_query=_normalize_text(
                    str(
                        _get_first(
                            row,
                            "frontier_reference_next_query",
                            "frontier_next_query",
                            "baseline_next_query",
                            "production_next_query",
                            default="",
                        )
                    )
                ),
                frontier_reference_rationale=_normalize_text(
                    str(
                        _get_first(
                            row,
                            "frontier_reference_rationale",
                            "frontier_rationale",
                            "baseline_rationale",
                            "production_rationale",
                            default="",
                        )
                    )
                ),
            )
        )
    return cases


def _score_lane_rows(rows: list[dict[str, Any]], *, lane_key: str) -> dict[str, float]:
    count = max(len(rows), 1)
    action_correct = sum(1.0 for row in rows if row[f"{lane_key}_action_correct"])
    intent_total = sum(1.0 for row in rows if row.get("gold_action") == "search_more")
    intent_correct = sum(
        1.0
        for row in rows
        if row.get("gold_action") == "search_more" and row[f"{lane_key}_intent_correct"]
    )
    false_converge = sum(1.0 for row in rows if row[f"{lane_key}_false_converge"])
    unnecessary_search = sum(1.0 for row in rows if row[f"{lane_key}_unnecessary_search"])
    illegal_converge = sum(1.0 for row in rows if row[f"{lane_key}_illegal_converge"])
    verifier_override = sum(1.0 for row in rows if row[f"{lane_key}_verifier_forced"])
    quality_pass = sum(1.0 for row in rows if row.get("quality_passed", True) and not row[f"{lane_key}_false_converge"])
    avg_input_tokens = sum(float(row[f"{lane_key}_estimated_input_tokens"]) for row in rows) / count
    avg_output_tokens = sum(float(row[f"{lane_key}_estimated_output_tokens"]) for row in rows) / count
    avg_cost = sum(float(row[f"{lane_key}_estimated_cost"]) for row in rows) / count
    return {
        "action_accuracy": round(action_correct / count, 4),
        "intent_accuracy": round((intent_correct / max(intent_total, 1.0)), 4),
        "false_converge_rate": round(false_converge / count, 4),
        "unnecessary_search_rate": round(unnecessary_search / count, 4),
        "illegal_converge_rate": round(illegal_converge / count, 4),
        "verifier_override_rate": round(verifier_override / count, 4),
        "quality_pass_proxy": round(quality_pass / count, 4),
        "avg_estimated_input_tokens": round(avg_input_tokens, 2),
        "avg_estimated_output_tokens": round(avg_output_tokens, 2),
        "avg_estimated_cost": round(avg_cost, 8),
    }


def run_research_loop_replay_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    frontier_model: str,
    limit: int = 0,
    temperature: float = 0.1,
    num_ctx: int | None = None,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    frontier_provider: str = "",
    frontier_base_url: str = "",
    input_price_per_million: float = 2.0,
    output_price_per_million: float = 8.0,
    deploy_raw_input_price_per_million: float | None = None,
    deploy_raw_output_price_per_million: float | None = None,
    deploy_raw_fixed_cost_per_decision: float | None = None,
    deploy_memla_input_price_per_million: float | None = None,
    deploy_memla_output_price_per_million: float | None = None,
    deploy_memla_fixed_cost_per_decision: float | None = None,
    deploy_frontier_input_price_per_million: float | None = None,
    deploy_frontier_output_price_per_million: float | None = None,
    deploy_frontier_fixed_cost_per_decision: float | None = None,
    deploy_memla_fallback_rate: float | None = None,
    deploy_memla_fallback_use_verifier_rate: bool = False,
    deploy_memla_fallback_input_price_per_million: float | None = None,
    deploy_memla_fallback_output_price_per_million: float | None = None,
    deploy_memla_fallback_fixed_cost_per_decision: float | None = None,
    deploy_decisions_per_session: float | None = None,
    frontier_use_logged_decisions: bool = False,
) -> dict[str, Any]:
    cases = load_research_loop_cases(cases_path)
    if limit > 0:
        cases = cases[:limit]

    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    frontier_client = (
        None
        if frontier_use_logged_decisions
        else _build_llm_client(provider=frontier_provider or None, base_url=frontier_base_url or None)
    )

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for case in cases:
        try:
            c2a_state = compile_research_c2a_state(case)
            raw_decision = _query_lane_decision(
                client=raw_client,
                model=raw_model,
                case=case,
                lane="raw",
                temperature=temperature,
                num_ctx=num_ctx,
            )
            memla_decision = _query_lane_decision(
                client=memla_client,
                model=memla_model,
                case=case,
                lane="memla",
                temperature=temperature,
                num_ctx=num_ctx,
            )
            frontier_decision = (
                _logged_reference_lane_decision(case)
                if frontier_use_logged_decisions
                else _query_lane_decision(
                    client=frontier_client,
                    model=frontier_model,
                    case=case,
                    lane="raw",
                    temperature=temperature,
                    num_ctx=num_ctx,
                )
            )

            raw_cost = _decision_cost(
                case=case,
                action=raw_decision.action,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )
            memla_cost = _decision_cost(
                case=case,
                action=memla_decision.action,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )
            frontier_cost = _decision_cost(
                case=case,
                action=frontier_decision.action,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )

            row = {
                "case_id": case.case_id,
                "session_id": case.session_id,
                "prompt": case.prompt,
                "user_goal": case.user_goal,
                "gold_action": case.gold_action,
                "gold_query_intent": case.gold_query_intent,
                "quality_passed": case.quality_passed,
                "c2a_state": asdict(c2a_state),
                "constraint_tags": list(c2a_state.constraint_tags),
                "residual_constraints": list(c2a_state.residual_constraints),
                "hard_constraints": list(c2a_state.hard_constraints),
                "soft_constraints": list(c2a_state.soft_constraints),
                "preferred_query_intent": c2a_state.preferred_query_intent,
                "converge_allowed": c2a_state.converge_allowed,
                "release_mode": c2a_state.release_mode,
            }
            for lane_key, decision, cost_blob in (
                ("raw", raw_decision, raw_cost),
                ("memla", memla_decision, memla_cost),
                ("frontier", frontier_decision, frontier_cost),
            ):
                row[f"{lane_key}_action"] = decision.action
                row[f"{lane_key}_query_intent"] = decision.query_intent
                row[f"{lane_key}_next_query"] = decision.next_query
                row[f"{lane_key}_rationale"] = decision.rationale
                row[f"{lane_key}_parse_mode"] = decision.parse_mode
                row[f"{lane_key}_raw_response"] = decision.raw_response
                row[f"{lane_key}_verifier_forced"] = decision.verifier_forced
                row[f"{lane_key}_verifier_reason"] = decision.verifier_reason
                row[f"{lane_key}_release_readiness"] = decision.release_readiness
                row[f"{lane_key}_blocking_constraints"] = list(decision.blocking_constraints)
                row[f"{lane_key}_bounded_constraints"] = list(decision.bounded_constraints)
                row[f"{lane_key}_action_correct"] = decision.action == case.gold_action
                row[f"{lane_key}_intent_correct"] = (
                    True
                    if case.gold_action != "search_more"
                    else decision.query_intent == case.gold_query_intent
                )
                row[f"{lane_key}_false_converge"] = decision.action == "converge" and case.gold_action == "search_more"
                row[f"{lane_key}_unnecessary_search"] = decision.action == "search_more" and case.gold_action == "converge"
                row[f"{lane_key}_illegal_converge"] = decision.action == "converge" and not c2a_state.converge_allowed
                row[f"{lane_key}_estimated_input_tokens"] = cost_blob["estimated_input_tokens"]
                row[f"{lane_key}_estimated_output_tokens"] = cost_blob["estimated_output_tokens"]
                row[f"{lane_key}_estimated_cost"] = cost_blob["estimated_cost"]
            rows.append(row)
        except Exception as exc:
            failures.append(
                {
                    "case_id": case.case_id,
                    "session_id": case.session_id,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    raw_summary = _score_lane_rows(rows, lane_key="raw")
    memla_summary = _score_lane_rows(rows, lane_key="memla")
    frontier_summary = _score_lane_rows(rows, lane_key="frontier")
    deployment_economics = _compute_replay_deployment_economics(
        rows=rows,
        memla_verifier_override_rate=float(memla_summary.get("verifier_override_rate", 0.0)),
        deploy_raw_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_raw_input_price_per_million,
            output_price_per_million=deploy_raw_output_price_per_million,
            fixed_cost_per_decision=deploy_raw_fixed_cost_per_decision,
        ),
        deploy_memla_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_memla_input_price_per_million,
            output_price_per_million=deploy_memla_output_price_per_million,
            fixed_cost_per_decision=deploy_memla_fixed_cost_per_decision,
        ),
        deploy_frontier_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_frontier_input_price_per_million,
            output_price_per_million=deploy_frontier_output_price_per_million,
            fixed_cost_per_decision=deploy_frontier_fixed_cost_per_decision,
        ),
        deploy_memla_fallback_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_memla_fallback_input_price_per_million,
            output_price_per_million=deploy_memla_fallback_output_price_per_million,
            fixed_cost_per_decision=deploy_memla_fallback_fixed_cost_per_decision,
        ),
        deploy_memla_fallback_rate=deploy_memla_fallback_rate,
        deploy_memla_fallback_use_verifier_rate=deploy_memla_fallback_use_verifier_rate,
        deploy_decisions_per_session=deploy_decisions_per_session,
    )

    report = {
        "generated_ts": int(time.time()),
        "benchmark_type": "research_loop_replay",
        "cases_path": str(Path(cases_path).resolve()),
        "cases_requested": len(cases),
        "cases": len(rows),
        "failed_case_count": len(failures),
        "raw_model": raw_model,
        "memla_model": memla_model,
        "frontier_model": frontier_model if not frontier_use_logged_decisions else (frontier_model or "historical_log"),
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "frontier_provider": frontier_client.provider if frontier_client is not None else "historical_log",
        "input_price_per_million": float(input_price_per_million),
        "output_price_per_million": float(output_price_per_million),
        "c2a_runtime": {
            "mode": "research_residual_gate_v2",
            "description": "Compile hard blockers vs bounded residuals and only block converge when material research constraints remain.",
        },
        "raw": raw_summary,
        "memla": memla_summary,
        "frontier": frontier_summary,
        "rows": rows,
        "failed_cases": failures,
    }
    if deployment_economics:
        report["deployment_economics"] = deployment_economics
    return report


def load_research_loop_sessions(path: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        if list(row.get("loop_steps") or []):
            rows.append(row)
    return rows


def _to_decision_case_from_step(session: dict[str, Any], step: dict[str, Any], default_case_id: str) -> ResearchDecisionCase:
    contradictions, contradiction_records = _normalize_contradictions(
        list(step.get("contradictions") or []),
        contradiction_records=list(step.get("contradiction_records") or []),
    )
    return ResearchDecisionCase(
        case_id=_normalize_text(str(step.get("case_id") or default_case_id)),
        session_id=_normalize_text(str(session.get("session_id") or default_case_id)),
        prompt=_normalize_text(str(session.get("prompt") or session.get("user_goal") or "")),
        user_goal=_normalize_text(str(session.get("user_goal") or session.get("prompt") or "")),
        known_facts=_normalize_list(list(step.get("known_facts") or [])),
        open_gaps=_normalize_list(list(step.get("open_gaps") or [])),
        contradictions=contradictions,
        latest_docs=_normalize_docs(list(step.get("latest_docs") or [])),
        context_tokens_so_far=_to_int(_get_first(step, "context_tokens_so_far", "context_tokens_so_far_estimate", default=0), 0),
        new_docs_tokens=_to_int(_get_first(step, "new_docs_tokens", "new_docs_tokens_estimate", default=0), 0),
        gold_action=_coerce_action(str(_get_first(step, "gold_action", "decision_action", default="search_more"))),
        gold_query_intent=_coerce_intent(str(_get_first(step, "gold_query_intent", "query_intent", default="none"))),
        quality_passed=_to_bool(step.get("quality_passed"), _to_bool(session.get("quality_passed"), True)),
        tokens_if_search_more=_to_int(_get_first(step, "tokens_if_search_more", "tokens_if_search_more_estimate", default=2500), 2500),
        tokens_if_converge=_to_int(_get_first(step, "tokens_if_converge", "tokens_if_converge_estimate", default=350), 350),
        estimated_output_tokens=_to_int(_get_first(step, "estimated_output_tokens", "estimated_output_tokens_estimate", default=180), 180),
        contradiction_records=contradiction_records,
    )


def _score_live_lane(rows: list[dict[str, Any]], lane_key: str) -> dict[str, float]:
    count = max(len(rows), 1)
    decision_acc = sum(float(row[f"{lane_key}_decision_accuracy"]) for row in rows) / count
    final_success = sum(float(row[f"{lane_key}_final_success"]) for row in rows) / count
    stop_delta = sum(float(row[f"{lane_key}_stop_step_delta"]) for row in rows) / count
    avg_cost = sum(float(row[f"{lane_key}_estimated_cost"]) for row in rows) / count
    avg_input = sum(float(row[f"{lane_key}_estimated_input_tokens"]) for row in rows) / count
    avg_iters = sum(float(row[f"{lane_key}_iterations_used"]) for row in rows) / count
    avg_illegal_converge = sum(float(row[f"{lane_key}_illegal_converge_rate"]) for row in rows) / count
    avg_verifier_override = sum(float(row[f"{lane_key}_verifier_override_rate"]) for row in rows) / count
    return {
        "avg_decision_accuracy": round(decision_acc, 4),
        "avg_final_success": round(final_success, 4),
        "avg_stop_step_delta": round(stop_delta, 4),
        "avg_iterations_used": round(avg_iters, 4),
        "avg_illegal_converge_rate": round(avg_illegal_converge, 4),
        "avg_verifier_override_rate": round(avg_verifier_override, 4),
        "avg_estimated_input_tokens": round(avg_input, 2),
        "avg_estimated_cost": round(avg_cost, 8),
    }


def _run_lane_live_shadow(
    *,
    client: Any,
    model: str,
    lane: str,
    session: dict[str, Any],
    max_iterations: int,
    temperature: float,
    num_ctx: int | None,
    input_price_per_million: float,
    output_price_per_million: float,
) -> dict[str, Any]:
    loop_steps = list(session.get("loop_steps") or [])
    lane_trace: list[dict[str, Any]] = []
    total_input_tokens = 0.0
    total_output_tokens = 0.0
    correct = 0
    visited = 0
    illegal_converge = 0
    verifier_forced = 0
    predicted_stop = len(loop_steps) - 1 if loop_steps else 0

    for index, step in enumerate(loop_steps[: max(int(max_iterations), 1)]):
        case = _to_decision_case_from_step(session, step, f"{session.get('session_id', 'session')}_step_{index + 1}")
        c2a_state = compile_research_c2a_state(case)
        decision = _query_lane_decision(
            client=client,
            model=model,
            case=case,
            lane=lane,
            temperature=temperature,
            num_ctx=num_ctx,
        )
        cost_blob = _decision_cost(
            case=case,
            action=decision.action,
            input_price_per_million=input_price_per_million,
            output_price_per_million=output_price_per_million,
        )
        total_input_tokens += float(cost_blob["estimated_input_tokens"])
        total_output_tokens += float(cost_blob["estimated_output_tokens"])
        visited += 1
        if decision.verifier_forced:
            verifier_forced += 1
        if decision.action == "converge" and not c2a_state.converge_allowed:
            illegal_converge += 1
        is_correct = decision.action == case.gold_action
        if is_correct:
            correct += 1
        lane_trace.append(
            {
                "step_index": index + 1,
                "gold_action": case.gold_action,
                "gold_query_intent": case.gold_query_intent,
                "constraint_tags": list(c2a_state.constraint_tags),
                "residual_constraints": list(c2a_state.residual_constraints),
                "hard_constraints": list(c2a_state.hard_constraints),
                "soft_constraints": list(c2a_state.soft_constraints),
                "preferred_query_intent": c2a_state.preferred_query_intent,
                "converge_allowed": c2a_state.converge_allowed,
                "release_mode": c2a_state.release_mode,
                "action": decision.action,
                "query_intent": decision.query_intent,
                "action_correct": is_correct,
                "parse_mode": decision.parse_mode,
                "verifier_forced": decision.verifier_forced,
                "verifier_reason": decision.verifier_reason,
                "release_readiness": decision.release_readiness,
                "blocking_constraints": list(decision.blocking_constraints),
                "bounded_constraints": list(decision.bounded_constraints),
                "illegal_converge": decision.action == "converge" and not c2a_state.converge_allowed,
                "estimated_input_tokens": cost_blob["estimated_input_tokens"],
                "estimated_output_tokens": cost_blob["estimated_output_tokens"],
                "estimated_cost": cost_blob["estimated_cost"],
            }
        )
        if decision.action == "converge":
            predicted_stop = index
            break

    gold_stop = next(
        (
            idx
            for idx, step in enumerate(loop_steps)
            if _coerce_action(str(step.get("gold_action") or "search_more")) == "converge"
        ),
        max(len(loop_steps) - 1, 0),
    )
    final_success = 1.0 if predicted_stop >= gold_stop else 0.0
    decision_accuracy = float(correct) / max(visited, 1)
    est_cost = (total_input_tokens / 1_000_000.0) * float(input_price_per_million) + (
        (total_output_tokens / 1_000_000.0) * float(output_price_per_million)
    )
    return {
        "iterations_used": visited,
        "decision_accuracy": round(decision_accuracy, 4),
        "final_success": final_success,
        "stop_step_delta": abs(int(predicted_stop) - int(gold_stop)),
        "illegal_converge_rate": round(float(illegal_converge) / max(visited, 1), 4),
        "verifier_override_rate": round(float(verifier_forced) / max(visited, 1), 4),
        "estimated_input_tokens": round(total_input_tokens, 2),
        "estimated_output_tokens": round(total_output_tokens, 2),
        "estimated_cost": round(est_cost, 8),
        "trace": lane_trace,
    }


def run_research_loop_live_shadow_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    frontier_model: str,
    limit: int = 0,
    max_iterations: int = 8,
    temperature: float = 0.1,
    num_ctx: int | None = None,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    frontier_provider: str = "",
    frontier_base_url: str = "",
    input_price_per_million: float = 2.0,
    output_price_per_million: float = 8.0,
    deploy_raw_input_price_per_million: float | None = None,
    deploy_raw_output_price_per_million: float | None = None,
    deploy_raw_fixed_cost_per_decision: float | None = None,
    deploy_memla_input_price_per_million: float | None = None,
    deploy_memla_output_price_per_million: float | None = None,
    deploy_memla_fixed_cost_per_decision: float | None = None,
    deploy_frontier_input_price_per_million: float | None = None,
    deploy_frontier_output_price_per_million: float | None = None,
    deploy_frontier_fixed_cost_per_decision: float | None = None,
    deploy_memla_fallback_rate: float | None = None,
    deploy_memla_fallback_use_verifier_rate: bool = False,
    deploy_memla_fallback_input_price_per_million: float | None = None,
    deploy_memla_fallback_output_price_per_million: float | None = None,
    deploy_memla_fallback_fixed_cost_per_decision: float | None = None,
) -> dict[str, Any]:
    sessions = load_research_loop_sessions(cases_path)
    if limit > 0:
        sessions = sessions[:limit]

    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    frontier_client = _build_llm_client(provider=frontier_provider or None, base_url=frontier_base_url or None)

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for session in sessions:
        try:
            session_id = _normalize_text(str(session.get("session_id") or f"session_{len(rows) + 1}"))
            raw_lane = _run_lane_live_shadow(
                client=raw_client,
                model=raw_model,
                lane="raw",
                session=session,
                max_iterations=max_iterations,
                temperature=temperature,
                num_ctx=num_ctx,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )
            memla_lane = _run_lane_live_shadow(
                client=memla_client,
                model=memla_model,
                lane="memla",
                session=session,
                max_iterations=max_iterations,
                temperature=temperature,
                num_ctx=num_ctx,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )
            frontier_lane = _run_lane_live_shadow(
                client=frontier_client,
                model=frontier_model,
                lane="raw",
                session=session,
                max_iterations=max_iterations,
                temperature=temperature,
                num_ctx=num_ctx,
                input_price_per_million=input_price_per_million,
                output_price_per_million=output_price_per_million,
            )
            rows.append(
                {
                    "session_id": session_id,
                    "prompt": _normalize_text(str(session.get("prompt") or session.get("user_goal") or "")),
                    "user_goal": _normalize_text(str(session.get("user_goal") or session.get("prompt") or "")),
                    "gold_iterations": len(list(session.get("loop_steps") or [])),
                    "raw_iterations_used": raw_lane["iterations_used"],
                    "raw_decision_accuracy": raw_lane["decision_accuracy"],
                    "raw_final_success": raw_lane["final_success"],
                    "raw_stop_step_delta": raw_lane["stop_step_delta"],
                    "raw_illegal_converge_rate": raw_lane["illegal_converge_rate"],
                    "raw_verifier_override_rate": raw_lane["verifier_override_rate"],
                    "raw_estimated_input_tokens": raw_lane["estimated_input_tokens"],
                    "raw_estimated_output_tokens": raw_lane["estimated_output_tokens"],
                    "raw_estimated_cost": raw_lane["estimated_cost"],
                    "raw_trace": raw_lane["trace"],
                    "memla_iterations_used": memla_lane["iterations_used"],
                    "memla_decision_accuracy": memla_lane["decision_accuracy"],
                    "memla_final_success": memla_lane["final_success"],
                    "memla_stop_step_delta": memla_lane["stop_step_delta"],
                    "memla_illegal_converge_rate": memla_lane["illegal_converge_rate"],
                    "memla_verifier_override_rate": memla_lane["verifier_override_rate"],
                    "memla_estimated_input_tokens": memla_lane["estimated_input_tokens"],
                    "memla_estimated_output_tokens": memla_lane["estimated_output_tokens"],
                    "memla_estimated_cost": memla_lane["estimated_cost"],
                    "memla_trace": memla_lane["trace"],
                    "frontier_iterations_used": frontier_lane["iterations_used"],
                    "frontier_decision_accuracy": frontier_lane["decision_accuracy"],
                    "frontier_final_success": frontier_lane["final_success"],
                    "frontier_stop_step_delta": frontier_lane["stop_step_delta"],
                    "frontier_illegal_converge_rate": frontier_lane["illegal_converge_rate"],
                    "frontier_verifier_override_rate": frontier_lane["verifier_override_rate"],
                    "frontier_estimated_input_tokens": frontier_lane["estimated_input_tokens"],
                    "frontier_estimated_output_tokens": frontier_lane["estimated_output_tokens"],
                    "frontier_estimated_cost": frontier_lane["estimated_cost"],
                    "frontier_trace": frontier_lane["trace"],
                }
            )
        except Exception as exc:
            failures.append(
                {
                    "session_id": str(session.get("session_id") or ""),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    report = {
        "generated_ts": int(time.time()),
        "benchmark_type": "research_loop_live_shadow",
        "cases_path": str(Path(cases_path).resolve()),
        "sessions_requested": len(sessions),
        "sessions": len(rows),
        "failed_case_count": len(failures),
        "raw_model": raw_model,
        "memla_model": memla_model,
        "frontier_model": frontier_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "frontier_provider": frontier_client.provider,
        "input_price_per_million": float(input_price_per_million),
        "output_price_per_million": float(output_price_per_million),
        "c2a_runtime": {
            "mode": "research_residual_gate_v2",
            "description": "Compile hard blockers vs bounded residuals and only block converge when material research constraints remain.",
        },
        "raw": _score_live_lane(rows, "raw"),
        "memla": _score_live_lane(rows, "memla"),
        "frontier": _score_live_lane(rows, "frontier"),
        "rows": rows,
        "failed_cases": failures,
    }
    deployment_economics = _compute_live_deployment_economics(
        rows=rows,
        memla_verifier_override_rate=float(report.get("memla", {}).get("avg_verifier_override_rate", 0.0)),
        deploy_raw_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_raw_input_price_per_million,
            output_price_per_million=deploy_raw_output_price_per_million,
            fixed_cost_per_decision=deploy_raw_fixed_cost_per_decision,
        ),
        deploy_memla_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_memla_input_price_per_million,
            output_price_per_million=deploy_memla_output_price_per_million,
            fixed_cost_per_decision=deploy_memla_fixed_cost_per_decision,
        ),
        deploy_frontier_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_frontier_input_price_per_million,
            output_price_per_million=deploy_frontier_output_price_per_million,
            fixed_cost_per_decision=deploy_frontier_fixed_cost_per_decision,
        ),
        deploy_memla_fallback_pricing=_configured_lane_pricing(
            input_price_per_million=deploy_memla_fallback_input_price_per_million,
            output_price_per_million=deploy_memla_fallback_output_price_per_million,
            fixed_cost_per_decision=deploy_memla_fallback_fixed_cost_per_decision,
        ),
        deploy_memla_fallback_rate=deploy_memla_fallback_rate,
        deploy_memla_fallback_use_verifier_rate=deploy_memla_fallback_use_verifier_rate,
    )
    if deployment_economics:
        report["deployment_economics"] = deployment_economics
    return report


def render_research_loop_markdown(report: dict[str, Any]) -> str:
    benchmark_type = str(report.get("benchmark_type") or "research_loop")

    def _econ_cell(payload: dict[str, Any] | None, key: str) -> str:
        data = dict(payload or {})
        if not data.get("configured"):
            return "(not configured)"
        value = data.get(key)
        if value is None:
            return "(n/a)"
        if isinstance(value, float):
            return f"{value:.4f}" if abs(value) < 10 else f"{value:.2f}"
        return str(value)

    def _pricing_cell(payload: dict[str, Any] | None, key: str) -> str:
        data = dict(payload or {})
        if not data.get("configured"):
            return "(not configured)"
        value = data.get(key, 0.0)
        return f"{float(value):.6f}"

    lines = [
        "# Research Loop Benchmark",
        "",
        f"- Type: `{benchmark_type}`",
        f"- Cases path: `{report.get('cases_path', '')}`",
        f"- Raw model: `{report.get('raw_model', 'unknown')}` ({report.get('raw_provider', 'unknown')})",
        f"- Memla model: `{report.get('memla_model', 'unknown')}` ({report.get('memla_provider', 'unknown')})",
        f"- Frontier model: `{report.get('frontier_model', 'unknown')}` ({report.get('frontier_provider', 'unknown')})",
        f"- C2A runtime: `{dict(report.get('c2a_runtime') or {}).get('mode', 'research_residual_gate_v2')}`",
        "",
        "## Lane summary",
        "",
        "| Metric | Raw | Memla | Frontier |",
        "| --- | --- | --- | --- |",
    ]
    if benchmark_type == "research_loop_replay":
        lines.extend(
            [
                f"| Action accuracy | `{report.get('raw', {}).get('action_accuracy', 0.0)}` | `{report.get('memla', {}).get('action_accuracy', 0.0)}` | `{report.get('frontier', {}).get('action_accuracy', 0.0)}` |",
                f"| Intent accuracy | `{report.get('raw', {}).get('intent_accuracy', 0.0)}` | `{report.get('memla', {}).get('intent_accuracy', 0.0)}` | `{report.get('frontier', {}).get('intent_accuracy', 0.0)}` |",
                f"| False converge rate | `{report.get('raw', {}).get('false_converge_rate', 0.0)}` | `{report.get('memla', {}).get('false_converge_rate', 0.0)}` | `{report.get('frontier', {}).get('false_converge_rate', 0.0)}` |",
                f"| Unnecessary search rate | `{report.get('raw', {}).get('unnecessary_search_rate', 0.0)}` | `{report.get('memla', {}).get('unnecessary_search_rate', 0.0)}` | `{report.get('frontier', {}).get('unnecessary_search_rate', 0.0)}` |",
                f"| Illegal converge rate | `{report.get('raw', {}).get('illegal_converge_rate', 0.0)}` | `{report.get('memla', {}).get('illegal_converge_rate', 0.0)}` | `{report.get('frontier', {}).get('illegal_converge_rate', 0.0)}` |",
                f"| Verifier override rate | `{report.get('raw', {}).get('verifier_override_rate', 0.0)}` | `{report.get('memla', {}).get('verifier_override_rate', 0.0)}` | `{report.get('frontier', {}).get('verifier_override_rate', 0.0)}` |",
                f"| Quality pass proxy | `{report.get('raw', {}).get('quality_pass_proxy', 0.0)}` | `{report.get('memla', {}).get('quality_pass_proxy', 0.0)}` | `{report.get('frontier', {}).get('quality_pass_proxy', 0.0)}` |",
                f"| Avg estimated input tokens | `{report.get('raw', {}).get('avg_estimated_input_tokens', 0.0)}` | `{report.get('memla', {}).get('avg_estimated_input_tokens', 0.0)}` | `{report.get('frontier', {}).get('avg_estimated_input_tokens', 0.0)}` |",
                f"| Avg estimated cost | `{report.get('raw', {}).get('avg_estimated_cost', 0.0)}` | `{report.get('memla', {}).get('avg_estimated_cost', 0.0)}` | `{report.get('frontier', {}).get('avg_estimated_cost', 0.0)}` |",
            ]
        )
    else:
        lines.extend(
            [
                f"| Avg decision accuracy | `{report.get('raw', {}).get('avg_decision_accuracy', 0.0)}` | `{report.get('memla', {}).get('avg_decision_accuracy', 0.0)}` | `{report.get('frontier', {}).get('avg_decision_accuracy', 0.0)}` |",
                f"| Avg final success | `{report.get('raw', {}).get('avg_final_success', 0.0)}` | `{report.get('memla', {}).get('avg_final_success', 0.0)}` | `{report.get('frontier', {}).get('avg_final_success', 0.0)}` |",
                f"| Avg stop-step delta | `{report.get('raw', {}).get('avg_stop_step_delta', 0.0)}` | `{report.get('memla', {}).get('avg_stop_step_delta', 0.0)}` | `{report.get('frontier', {}).get('avg_stop_step_delta', 0.0)}` |",
                f"| Avg iterations used | `{report.get('raw', {}).get('avg_iterations_used', 0.0)}` | `{report.get('memla', {}).get('avg_iterations_used', 0.0)}` | `{report.get('frontier', {}).get('avg_iterations_used', 0.0)}` |",
                f"| Avg illegal converge rate | `{report.get('raw', {}).get('avg_illegal_converge_rate', 0.0)}` | `{report.get('memla', {}).get('avg_illegal_converge_rate', 0.0)}` | `{report.get('frontier', {}).get('avg_illegal_converge_rate', 0.0)}` |",
                f"| Avg verifier override rate | `{report.get('raw', {}).get('avg_verifier_override_rate', 0.0)}` | `{report.get('memla', {}).get('avg_verifier_override_rate', 0.0)}` | `{report.get('frontier', {}).get('avg_verifier_override_rate', 0.0)}` |",
                f"| Avg estimated input tokens | `{report.get('raw', {}).get('avg_estimated_input_tokens', 0.0)}` | `{report.get('memla', {}).get('avg_estimated_input_tokens', 0.0)}` | `{report.get('frontier', {}).get('avg_estimated_input_tokens', 0.0)}` |",
                f"| Avg estimated cost | `{report.get('raw', {}).get('avg_estimated_cost', 0.0)}` | `{report.get('memla', {}).get('avg_estimated_cost', 0.0)}` | `{report.get('frontier', {}).get('avg_estimated_cost', 0.0)}` |",
            ]
        )

    deployment = dict(report.get("deployment_economics") or {})
    if deployment:
        pricing = dict(deployment.get("pricing") or {})
        savings = dict(deployment.get("savings_vs_frontier_per_1k_sessions") or {})
        lines.extend(
            [
                "",
                "## Deployment Economics",
                "",
                f"- Mode: `{deployment.get('mode', 'deployment_model_v1')}`",
                f"- Cost basis: `{deployment.get('cost_basis', 'usd_per_1000_sessions')}`",
            ]
        )
        if benchmark_type == "research_loop_replay":
            lines.append(
                f"- Decisions per session used: `{deployment.get('decisions_per_session_used', 0.0)}` "
                f"(observed `{deployment.get('observed_decisions_per_session', 0.0)}`)"
            )
        else:
            lines.append(f"- Avg iterations observed: `{deployment.get('avg_iterations_observed', 0.0)}`")
        lines.extend(
            [
                f"- Memla fallback rate: `{deployment.get('memla_fallback_rate', 0.0)}` "
                f"(`{deployment.get('memla_fallback_rate_source', 'none')}`)",
                f"- Fallback pricing source: `{dict(pricing.get('memla_fallback') or {}).get('source', 'none')}`",
                "",
                "| Pricing assumption | Raw | Memla | Frontier |",
                "| --- | --- | --- | --- |",
                f"| Input $/M | `{_pricing_cell(pricing.get('raw'), 'input_price_per_million')}` | `{_pricing_cell(pricing.get('memla'), 'input_price_per_million')}` | `{_pricing_cell(pricing.get('frontier'), 'input_price_per_million')}` |",
                f"| Output $/M | `{_pricing_cell(pricing.get('raw'), 'output_price_per_million')}` | `{_pricing_cell(pricing.get('memla'), 'output_price_per_million')}` | `{_pricing_cell(pricing.get('frontier'), 'output_price_per_million')}` |",
                f"| Fixed $/decision | `{_pricing_cell(pricing.get('raw'), 'fixed_cost_per_decision')}` | `{_pricing_cell(pricing.get('memla'), 'fixed_cost_per_decision')}` | `{_pricing_cell(pricing.get('frontier'), 'fixed_cost_per_decision')}` |",
                "",
                "| Metric | Raw | Memla | Frontier |",
                "| --- | --- | --- | --- |",
                f"| Cost / 1,000 sessions | `{_econ_cell(deployment.get('raw'), 'modeled_cost_per_1k_sessions')}` | `{_econ_cell(deployment.get('memla'), 'modeled_cost_per_1k_sessions')}` | `{_econ_cell(deployment.get('frontier'), 'modeled_cost_per_1k_sessions')}` |",
                f"| Avg modeled cost / session | `{_econ_cell(deployment.get('raw'), 'avg_modeled_cost_per_session')}` | `{_econ_cell(deployment.get('memla'), 'avg_modeled_cost_per_session')}` | `{_econ_cell(deployment.get('frontier'), 'avg_modeled_cost_per_session')}` |",
            ]
        )
        if benchmark_type == "research_loop_replay":
            lines.append(
                f"| Avg modeled cost / decision | `{_econ_cell(deployment.get('raw'), 'avg_modeled_cost_per_decision')}` | `{_econ_cell(deployment.get('memla'), 'avg_modeled_cost_per_decision')}` | `{_econ_cell(deployment.get('frontier'), 'avg_modeled_cost_per_decision')}` |"
            )
        lines.extend(
            [
                "",
                "| Savings vs frontier / 1,000 sessions | Raw | Memla |",
                "| --- | --- | --- |",
                f"| USD | `{savings.get('raw', '(n/a)')}` | `{savings.get('memla', '(n/a)')}` |",
            ]
        )

    lines.extend(["", "## Rows", ""])
    for row in report.get("rows", [])[:10]:
        if benchmark_type == "research_loop_replay":
            lines.extend(
                [
                    f"### {row.get('case_id', 'case')} :: {row.get('session_id', '')}",
                    "",
                    f"- Gold action: `{row.get('gold_action', '')}`",
                    f"- Residual constraints: `{', '.join(row.get('residual_constraints') or []) or '(none)'}`",
                    f"- Hard constraints: `{', '.join(row.get('hard_constraints') or []) or '(none)'}`",
                    f"- Soft residuals: `{', '.join(row.get('soft_constraints') or []) or '(none)'}`",
                    f"- Converge legal: `{row.get('converge_allowed', False)}`",
                    f"- Release mode: `{row.get('release_mode', 'hard_blocked')}`",
                    f"- Raw action: `{row.get('raw_action', '')}`",
                    f"- Memla action: `{row.get('memla_action', '')}`",
                    f"- Memla verifier: `{row.get('memla_verifier_reason', '') or 'pass-through'}`",
                    f"- Memla release readiness: `{row.get('memla_release_readiness', 'blocked')}`",
                    f"- Frontier action: `{row.get('frontier_action', '')}`",
                    f"- Estimated costs: raw `{row.get('raw_estimated_cost', 0.0)}` | memla `{row.get('memla_estimated_cost', 0.0)}` | frontier `{row.get('frontier_estimated_cost', 0.0)}`",
                    "",
                ]
            )
        else:
            lines.extend(
                [
                    f"### {row.get('session_id', 'session')}",
                    "",
                    f"- Raw final success: `{row.get('raw_final_success', 0.0)}` | iterations `{row.get('raw_iterations_used', 0)}`",
                    f"- Memla final success: `{row.get('memla_final_success', 0.0)}` | iterations `{row.get('memla_iterations_used', 0)}`",
                    f"- Frontier final success: `{row.get('frontier_final_success', 0.0)}` | iterations `{row.get('frontier_iterations_used', 0)}`",
                    "",
                ]
            )
    return "\n".join(lines).strip() + "\n"
