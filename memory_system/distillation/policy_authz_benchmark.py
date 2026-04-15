from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..ollama_client import ChatMessage
from .patch_execution_benchmark import _build_llm_client
from .policy_authz_policy_bank import suggest_policy_authz_priors


POLICY_AUTHZ_SYSTEM = """
You are a policy-as-code authorization analyst.

Given a subject, request, and policy bundle, choose the best bounded authorization action.
Return strict JSON only with this shape:
{
  "decision": "allow|block|escalate|modify",
  "predicted_rule_hits": ["mfa_required"],
  "next_actions": ["require_mfa_then_retry"],
  "rewrite": {"mfa_present": true, "region": "US", "local_hour": 10},
  "rationale": "short explanation"
}

Rules:
- Use "allow" only if the request should pass as submitted.
- Use "block" when the request should be denied outright.
- Use "escalate" when reviewer or break-glass approval is required.
- Use "modify" only when a concrete request rewrite creates a compliant path.
- If no rewrite is needed, return an empty object for rewrite.
- Do not include markdown fences or extra prose.
""".strip()


KNOWN_RULE_IDS = (
    "mfa_required",
    "region_restricted",
    "outside_change_window",
    "break_glass_required",
    "restricted_resource_role",
    "role_not_permitted",
)

KNOWN_NEXT_ACTIONS = (
    "require_mfa_then_retry",
    "route_to_allowed_region",
    "queue_for_change_window",
    "request_break_glass_review",
    "block_request",
)

RULE_ID_ALIASES = {
    "break_glass": "break_glass_required",
    "change_window_violation": "outside_change_window",
    "change_window": "outside_change_window",
    "missing_role": "role_not_permitted",
    "region_restriction": "region_restricted",
    "requires_mfa": "mfa_required",
    "restricted_role": "restricted_resource_role",
}

NEXT_ACTION_ALIASES = {
    "deny_request": "block_request",
    "enable_mfa": "require_mfa_then_retry",
    "require_break_glass_approval": "request_break_glass_review",
    "require_break_glass_approval_then_retry": "request_break_glass_review",
    "queue_change": "queue_for_change_window",
    "request_break_glass": "request_break_glass_review",
    "route_region": "route_to_allowed_region",
}


@dataclass(frozen=True)
class PolicyAuthzCase:
    case_id: str
    prompt: str
    subject: dict[str, Any]
    request: dict[str, Any]
    policy: dict[str, Any]
    expected_outcome: str
    expected_rule_hits: list[str]
    expected_actions: list[str]
    expected_rewrite: dict[str, Any]


@dataclass(frozen=True)
class PolicyRuleHit:
    rule_id: str
    severity: str
    message: str
    actual: str = ""
    threshold: str = ""


@dataclass(frozen=True)
class PolicyDecision:
    decision: str
    predicted_rule_hits: list[str]
    next_actions: list[str]
    rewrite: dict[str, Any]
    rationale: str
    response_text: str
    parse_mode: str


@dataclass(frozen=True)
class PolicyBacktestResult:
    rule_hits: list[PolicyRuleHit]
    modified_rule_hits: list[PolicyRuleHit]
    modified_request: dict[str, Any]
    compliance_passed: bool
    final_status: str
    residual_constraints: list[str]


@dataclass(frozen=True)
class PolicyIterationTrace:
    iteration: int
    decision: str
    predicted_rule_hits: list[str]
    next_actions: list[str]
    rewrite: dict[str, Any]
    rationale: str
    parse_mode: str
    compliance_passed: bool
    final_status: str
    residual_constraints: list[str]


@dataclass(frozen=True)
class PolicyAuthzBenchmarkRow:
    case_id: str
    prompt: str
    expected_outcome: str
    expected_rule_hits: list[str]
    expected_actions: list[str]
    expected_rewrite: dict[str, Any]
    actual_rule_hits: list[str]
    raw_decision: str
    raw_predicted_rule_hits: list[str]
    raw_next_actions: list[str]
    raw_rewrite: dict[str, Any]
    raw_rule_recall: float
    raw_action_recall: float
    raw_rewrite_recall: float
    raw_outcome_match: float
    raw_backtest_passed: float
    raw_policy_utility: float
    raw_final_status: str
    raw_iteration_trace: list[dict[str, Any]]
    memla_decision: str
    memla_predicted_rule_hits: list[str]
    memla_next_actions: list[str]
    memla_rewrite: dict[str, Any]
    memla_rule_recall: float
    memla_action_recall: float
    memla_rewrite_recall: float
    memla_outcome_match: float
    memla_backtest_passed: float
    memla_policy_utility: float
    memla_final_status: str
    memla_iteration_trace: list[dict[str, Any]]
    utility_delta: float


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    lower = str(value or "").strip().lower()
    return lower in {"1", "true", "yes", "y"}


def _normalize_label_token(value: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
    return clean.strip("_")


def _normalize_label_list(values: list[str], aliases: dict[str, str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = _normalize_label_token(value)
        if not token:
            continue
        canonical = aliases.get(token, token)
        if canonical in seen:
            continue
        seen.add(canonical)
        out.append(canonical)
    return out


def _normalize_rule(values: list[str]) -> list[str]:
    return _normalize_label_list(values, RULE_ID_ALIASES)


def _normalize_action(values: list[str]) -> list[str]:
    return _normalize_label_list(values, NEXT_ACTION_ALIASES)


def _normalize_roles(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        clean = str(value or "").strip().lower()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _normalize_rewrite(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rewrite: dict[str, Any] = {}
    if "mfa_present" in value:
        rewrite["mfa_present"] = _coerce_bool(value.get("mfa_present"))
    if "region" in value and str(value.get("region") or "").strip():
        rewrite["region"] = str(value.get("region") or "").strip().upper()
    if "local_hour" in value and value.get("local_hour") not in (None, ""):
        rewrite["local_hour"] = _coerce_int(value.get("local_hour"), 0)
    return rewrite


def _extract_label_hits_from_text(
    text: str,
    *,
    known: tuple[str, ...],
    aliases: dict[str, str],
) -> list[str]:
    normalized_text = _normalize_label_token(text)
    if not normalized_text:
        return []
    candidates = list(known) + list(aliases.keys())
    hits = [candidate for candidate in candidates if candidate and candidate in normalized_text]
    return _normalize_label_list(hits, aliases)


def _canonicalize_contextual_actions(actions: list[str], rule_hits: list[str], response: str) -> list[str]:
    normalized_rules = {item.strip().lower() for item in rule_hits if item.strip()}
    raw_tokens = [_normalize_label_token(item) for item in actions if str(item or "").strip()]
    inferred: list[str] = []
    for token in raw_tokens:
        if not token:
            continue
        if token in NEXT_ACTION_ALIASES or token in KNOWN_NEXT_ACTIONS:
            inferred.append(token)
            continue
        if token in {"await_reviewer_approval", "await_approval", "reviewer_approval", "reviewer_review"}:
            if "outside_change_window" in normalized_rules:
                inferred.append("queue_for_change_window")
            elif "break_glass_required" in normalized_rules:
                inferred.append("request_break_glass_review")
    normalized_actions = _normalize_action(inferred)
    if normalized_actions:
        return normalized_actions
    lower = str(response or "").strip().lower()
    if "reviewer approval" in lower or "reviewer review" in lower or "await approval" in lower:
        if "outside_change_window" in normalized_rules:
            inferred.append("queue_for_change_window")
        elif "break_glass_required" in normalized_rules:
            inferred.append("request_break_glass_review")
    return _normalize_action(inferred)


def _extract_json_object(response: str) -> dict[str, Any]:
    clean = str(response or "").strip()
    if not clean:
        return {}
    try:
        data = json.loads(clean)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _infer_decision_from_text(text: str) -> str:
    lower = str(text or "").lower()
    for decision in ("modify", "escalate", "block", "allow"):
        if decision in lower:
            return decision
    return ""


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {item.strip().lower() for item in predicted if item.strip()}
    expected_set = {item.strip().lower() for item in expected if item.strip()}
    if not expected_set:
        return 1.0
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def _rewrite_recall(actual: dict[str, Any], expected: dict[str, Any]) -> float:
    if not expected:
        return 1.0
    matched = 0
    for key, expected_value in expected.items():
        if key not in actual:
            continue
        actual_value = actual.get(key)
        if isinstance(expected_value, bool):
            if bool(actual_value) == expected_value:
                matched += 1
        elif isinstance(expected_value, int):
            if _coerce_int(actual_value, -999999) == expected_value:
                matched += 1
        else:
            if str(actual_value).strip().upper() == str(expected_value).strip().upper():
                matched += 1
    return matched / max(len(expected), 1)


def load_policy_authz_cases(path: str) -> list[PolicyAuthzCase]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cases: list[PolicyAuthzCase] = []
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        cases.append(
            PolicyAuthzCase(
                case_id=str(row.get("case_id") or f"case_{len(cases) + 1}"),
                prompt=str(row.get("prompt") or "").strip(),
                subject=dict(row.get("subject") or {}),
                request=dict(row.get("request") or {}),
                policy=dict(row.get("policy") or {}),
                expected_outcome=str(row.get("expected_outcome") or "").strip().lower(),
                expected_rule_hits=_normalize_rule(list(row.get("expected_rule_hits") or [])),
                expected_actions=_normalize_action(list(row.get("expected_actions") or [])),
                expected_rewrite=_normalize_rewrite(dict(row.get("expected_rewrite") or {})),
            )
        )
    return cases


def _render_case_payload(case: PolicyAuthzCase) -> str:
    payload = {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "subject": case.subject,
        "request": case.request,
        "policy": case.policy,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def evaluate_policy_rules(case: PolicyAuthzCase, request: dict[str, Any]) -> list[PolicyRuleHit]:
    hits: list[PolicyRuleHit] = []
    subject = case.subject
    policy = case.policy
    actor_roles = set(_normalize_roles(subject.get("roles") or []))
    actor_id = str(subject.get("actor_id") or "").strip().lower()
    owner_id = str(request.get("owner_id") or "").strip().lower()
    action = str(request.get("action") or "").strip().lower()
    resource = str(request.get("resource") or "").strip().lower()
    region = str(request.get("region") or "").strip().upper()
    local_hour = _coerce_int(request.get("local_hour"), -1)
    mfa_present = _coerce_bool(request.get("mfa_present"))
    break_glass_approved = _coerce_bool(request.get("break_glass_approved"))

    owner_override = actor_id and owner_id and actor_id == owner_id and action in {str(item).strip().lower() for item in list(policy.get("owner_allowed_actions") or []) if str(item).strip()}

    restricted_roles = set(_normalize_roles((policy.get("restricted_resource_roles") or {}).get(resource, [])))
    if restricted_roles and not (actor_roles & restricted_roles):
        hits.append(PolicyRuleHit("restricted_resource_role", "hard", "The request targets a restricted resource without the required privileged role.", actual=",".join(sorted(actor_roles)), threshold=",".join(sorted(restricted_roles))))

    allow_entries = list(policy.get("allow_roles") or [])
    matching_entries = [
        entry
        for entry in allow_entries
        if str(entry.get("resource") or "").strip().lower() == resource
        and action in {str(item).strip().lower() for item in list(entry.get("actions") or []) if str(item).strip()}
    ]
    if matching_entries and not owner_override:
        allowed_roles = {
            role
            for entry in matching_entries
            for role in _normalize_roles(entry.get("roles") or [])
        }
        if allowed_roles and not (actor_roles & allowed_roles):
            hits.append(PolicyRuleHit("role_not_permitted", "hard", "The actor lacks a permitted role for this resource and action.", actual=",".join(sorted(actor_roles)), threshold=",".join(sorted(allowed_roles))))

    mfa_actions = {str(item).strip().lower() for item in list(policy.get("mfa_required_actions") or []) if str(item).strip()}
    if action in mfa_actions and not mfa_present:
        hits.append(PolicyRuleHit("mfa_required", "hard_fixable", "Multi-factor authentication is required before this action can proceed.", actual=str(mfa_present).lower(), threshold="true"))

    allowed_regions = {
        str(item).strip().upper()
        for item in list((policy.get("allowed_regions_by_resource") or {}).get(resource, []))
        if str(item).strip()
    }
    if allowed_regions and region not in allowed_regions:
        hits.append(PolicyRuleHit("region_restricted", "hard_fixable", "The request originates from a region outside the allowed policy boundary.", actual=region, threshold=",".join(sorted(allowed_regions))))

    window = (policy.get("change_windows") or {}).get(action, {})
    start_hour = _coerce_int(window.get("start_hour"), -1)
    end_hour = _coerce_int(window.get("end_hour"), -1)
    if start_hour >= 0 and end_hour >= 0 and local_hour >= 0 and not (start_hour <= local_hour <= end_hour):
        hits.append(PolicyRuleHit("outside_change_window", "soft", "The request falls outside the configured change window and should be queued or reviewed.", actual=str(local_hour), threshold=f"{start_hour}-{end_hour}"))

    break_glass_actions = {str(item).strip().lower() for item in list(policy.get("break_glass_actions") or []) if str(item).strip()}
    if action in break_glass_actions and not break_glass_approved:
        hits.append(PolicyRuleHit("break_glass_required", "soft", "Break-glass approval is required before this action can proceed.", actual=str(break_glass_approved).lower(), threshold="true"))

    return hits


def _apply_rewrite(request: dict[str, Any], rewrite: dict[str, Any]) -> dict[str, Any]:
    updated = dict(request)
    for key in ("mfa_present", "region", "local_hour"):
        if key not in rewrite:
            continue
        updated[key] = rewrite.get(key)
    return updated


def backtest_policy_decision(case: PolicyAuthzCase, decision: PolicyDecision) -> PolicyBacktestResult:
    initial_hits = evaluate_policy_rules(case, case.request)
    residuals: list[str] = []
    modified_hits: list[PolicyRuleHit] = []
    modified_request: dict[str, Any] = {}
    current_decision = str(decision.decision or "").strip().lower()
    hard_hits = [hit for hit in initial_hits if hit.severity in {"hard", "hard_fixable"}]
    soft_hits = [hit for hit in initial_hits if hit.severity == "soft"]
    hard_fixable_hits = [hit for hit in initial_hits if hit.severity == "hard_fixable"]
    hard_block_hits = [hit for hit in initial_hits if hit.severity == "hard"]

    if current_decision == "allow":
        compliance_passed = not initial_hits
        final_status = "allow_ok" if compliance_passed else "unsafe_allow"
        if initial_hits:
            residuals.extend([f"request_still_violates:{hit.rule_id}" for hit in initial_hits])
    elif current_decision == "block":
        if hard_block_hits:
            compliance_passed = True
            final_status = "block_ok"
        elif soft_hits:
            compliance_passed = False
            final_status = "overblocked_soft_policy"
            residuals.extend([f"soft_policy_prefers_escalation:{hit.rule_id}" for hit in soft_hits])
        elif hard_fixable_hits:
            compliance_passed = False
            final_status = "overblocked_repairable_policy"
            residuals.extend([f"repairable_policy_prefers_modify:{hit.rule_id}" for hit in hard_fixable_hits])
        else:
            compliance_passed = False
            final_status = "unnecessary_block"
            residuals.append("no_triggered_rule_for_block")
    elif current_decision == "escalate":
        if soft_hits and not hard_hits:
            compliance_passed = True
            final_status = "escalate_ok"
        elif hard_fixable_hits:
            compliance_passed = False
            final_status = "escalation_insufficient_for_hard_control"
            residuals.extend([f"hard_control_requires_modify:{hit.rule_id}" for hit in hard_fixable_hits])
        elif hard_block_hits:
            compliance_passed = False
            final_status = "escalation_insufficient_for_blocked_policy"
            residuals.extend([f"blocked_policy_requires_deny:{hit.rule_id}" for hit in hard_block_hits])
        else:
            compliance_passed = False
            final_status = "unnecessary_escalation"
            residuals.append("no_triggered_rule_for_escalation")
    elif current_decision == "modify":
        if not decision.rewrite:
            compliance_passed = False
            final_status = "missing_rewrite"
            residuals.append("missing_rewrite")
        else:
            modified_request = _apply_rewrite(case.request, decision.rewrite)
            modified_hits = evaluate_policy_rules(case, modified_request)
            compliance_passed = not modified_hits
            final_status = "modify_ok" if compliance_passed else "modify_still_violates"
            if modified_hits:
                residuals.extend([f"modified_request_violates:{hit.rule_id}" for hit in modified_hits])
    else:
        compliance_passed = False
        final_status = "invalid_decision"
        residuals.append("invalid_decision")

    return PolicyBacktestResult(
        rule_hits=initial_hits,
        modified_rule_hits=modified_hits,
        modified_request=modified_request,
        compliance_passed=compliance_passed,
        final_status=final_status,
        residual_constraints=residuals,
    )


def _normalize_decision_payload(payload: dict[str, Any], response: str) -> PolicyDecision:
    normalized_rule_hits = _normalize_rule(list(payload.get("predicted_rule_hits") or []))
    if not normalized_rule_hits:
        normalized_rule_hits = _extract_label_hits_from_text(response, known=KNOWN_RULE_IDS, aliases=RULE_ID_ALIASES)
    normalized_actions = _canonicalize_contextual_actions(
        list(payload.get("next_actions") or []),
        normalized_rule_hits,
        response,
    )
    if not normalized_actions:
        normalized_actions = _canonicalize_contextual_actions(
            _extract_label_hits_from_text(response, known=KNOWN_NEXT_ACTIONS, aliases=NEXT_ACTION_ALIASES),
            normalized_rule_hits,
            response,
        )
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"allow", "block", "escalate", "modify"}:
        decision = _infer_decision_from_text(response)
    return PolicyDecision(
        decision=decision if decision in {"allow", "block", "escalate", "modify"} else "block",
        predicted_rule_hits=normalized_rule_hits,
        next_actions=normalized_actions,
        rewrite=_normalize_rewrite(payload.get("rewrite") or {}),
        rationale=" ".join(str(payload.get("rationale") or "").split()),
        response_text=str(response or ""),
        parse_mode="json" if payload else "heuristic",
    )


def _repair_decision_payload(*, client: Any, model: str, response: str, temperature: float, num_ctx: int | None) -> PolicyDecision:
    repair_prompt = (
        "Convert the answer below into strict JSON only with the required shape.\n"
        "If a field is unknown, use empty arrays or an empty object.\n\n"
        "Answer to convert:\n"
        f"{response}"
    )
    repaired = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=POLICY_AUTHZ_SYSTEM),
            ChatMessage(role="user", content=repair_prompt),
        ],
        temperature=min(float(temperature), 0.1),
        num_ctx=num_ctx,
    ).strip()
    decision = _normalize_decision_payload(_extract_json_object(repaired), repaired)
    parse_mode = "json_repair" if decision.parse_mode == "json" else "json_repair_heuristic"
    return PolicyDecision(
        decision=decision.decision,
        predicted_rule_hits=decision.predicted_rule_hits,
        next_actions=decision.next_actions,
        rewrite=decision.rewrite,
        rationale=decision.rationale,
        response_text=repaired,
        parse_mode=parse_mode,
    )


def _render_policy_bank_block(priors: dict[str, Any]) -> str:
    if not any(
        priors.get(key)
        for key in (
            "decisions",
            "rules",
            "actions",
            "primitive_decisions",
            "primitive_actions",
            "teacher_rescue_decisions",
            "teacher_rescue_rules",
            "teacher_rescue_actions",
        )
    ):
        return ""
    lines = ["=== MEMLA POLICY PRIORS ==="]
    matched_tokens = list(priors.get("matched_tokens") or [])
    if matched_tokens:
        lines.append(f"Matched prompt tokens: {', '.join(matched_tokens[:8])}")
    state_primitives = list(priors.get("state_primitives") or [])
    if state_primitives:
        lines.append(f"Primitive state: {', '.join(state_primitives[:6])}")
    rescue_decisions = list(priors.get("teacher_rescue_decisions") or [])
    rescue_rules = list(priors.get("teacher_rescue_rules") or [])
    rescue_actions = list(priors.get("teacher_rescue_actions") or [])
    if rescue_decisions:
        lines.append(
            "Teacher rescue decisions (prefer these over weaker defaults when they fit the current state): "
            + ", ".join(rescue_decisions[:3])
        )
    if rescue_rules:
        lines.append(f"Teacher rescue rules: {', '.join(rescue_rules[:4])}")
    if rescue_actions:
        lines.append(f"Teacher rescue actions: {', '.join(rescue_actions[:4])}")
    decisions = list(priors.get("decisions") or [])
    if decisions:
        lines.append(f"Preferred decisions: {', '.join(decisions[:3])}")
    primitive_decisions = list(priors.get("primitive_decisions") or [])
    if primitive_decisions:
        lines.append(f"Primitive decisions: {', '.join(primitive_decisions[:3])}")
    rules = list(priors.get("rules") or [])
    if rules:
        lines.append(f"Likely rules: {', '.join(rules[:4])}")
    actions = list(priors.get("actions") or [])
    if actions:
        lines.append(f"Likely actions: {', '.join(actions[:4])}")
    primitive_actions = list(priors.get("primitive_actions") or [])
    if primitive_actions:
        lines.append(f"Primitive actions: {', '.join(primitive_actions[:4])}")
    lines.append("Use these priors only if they fit the current state and preserve bounded authorization control.")
    return "\n".join(lines)


def _query_policy_decision(
    *,
    client: Any,
    model: str,
    case: PolicyAuthzCase,
    temperature: float,
    num_ctx: int | None,
    residual_constraints: list[str] | None = None,
    prior_trace: list[dict[str, Any]] | None = None,
    policy_priors: dict[str, Any] | None = None,
) -> PolicyDecision:
    user_parts = [
        "Evaluate this policy-as-code authorization state and return the best bounded action.",
        _render_case_payload(case),
    ]
    policy_block = _render_policy_bank_block(policy_priors or {})
    if policy_block:
        user_parts.append(policy_block)
    if residual_constraints:
        user_parts.append("Verifier residual constraints from the previous attempt:\n" + json.dumps(list(residual_constraints), indent=2))
    if prior_trace:
        user_parts.append("Prior attempts:\n" + json.dumps(prior_trace, indent=2))
    response = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=POLICY_AUTHZ_SYSTEM),
            ChatMessage(role="user", content="\n\n".join(user_parts)),
        ],
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()
    payload = _extract_json_object(response)
    decision = _normalize_decision_payload(payload, response)
    if decision.parse_mode == "heuristic":
        repaired = _repair_decision_payload(
            client=client,
            model=model,
            response=response,
            temperature=temperature,
            num_ctx=num_ctx,
        )
        if repaired.parse_mode != "heuristic":
            return repaired
    return decision


def _decision_loop(
    *,
    client: Any,
    model: str,
    case: PolicyAuthzCase,
    iterations: int,
    temperature: float,
    num_ctx: int | None,
    policy_priors: dict[str, Any] | None = None,
) -> tuple[PolicyDecision, PolicyBacktestResult, list[dict[str, Any]]]:
    last_decision = PolicyDecision(
        decision="block",
        predicted_rule_hits=[],
        next_actions=[],
        rewrite={},
        rationale="",
        response_text="",
        parse_mode="empty",
    )
    last_backtest = PolicyBacktestResult(
        rule_hits=[],
        modified_rule_hits=[],
        modified_request={},
        compliance_passed=False,
        final_status="not_run",
        residual_constraints=["not_run"],
    )
    traces: list[dict[str, Any]] = []
    residual_constraints: list[str] = []

    for iteration in range(1, max(iterations, 1) + 1):
        decision = _query_policy_decision(
            client=client,
            model=model,
            case=case,
            temperature=temperature,
            num_ctx=num_ctx,
            residual_constraints=residual_constraints if residual_constraints else None,
            prior_trace=traces if traces else None,
            policy_priors=policy_priors,
        )
        backtest = backtest_policy_decision(case, decision)
        traces.append(
            asdict(
                PolicyIterationTrace(
                    iteration=iteration,
                    decision=decision.decision,
                    predicted_rule_hits=decision.predicted_rule_hits,
                    next_actions=decision.next_actions,
                    rewrite=decision.rewrite,
                    rationale=decision.rationale,
                    parse_mode=decision.parse_mode,
                    compliance_passed=backtest.compliance_passed,
                    final_status=backtest.final_status,
                    residual_constraints=backtest.residual_constraints,
                )
            )
        )
        last_decision = decision
        last_backtest = backtest
        residual_constraints = list(backtest.residual_constraints)
        if backtest.compliance_passed:
            break
    return last_decision, last_backtest, traces


def _policy_utility(
    *,
    outcome_match: float,
    backtest_passed: float,
    rule_recall: float,
    action_recall: float,
    rewrite_recall: float,
) -> float:
    utility = (
        (0.3 * float(outcome_match))
        + (0.3 * float(backtest_passed))
        + (0.2 * float(rule_recall))
        + (0.1 * float(action_recall))
        + (0.1 * float(rewrite_recall))
    )
    return round(float(utility), 4)


def run_policy_authz_benchmark(
    *,
    cases_path: str,
    repo_root: str = "",
    case_ids: list[str] | None = None,
    limit: int | None = None,
    raw_model: str,
    memla_model: str,
    raw_iterations: int = 1,
    memla_iterations: int = 3,
    temperature: float = 0.1,
    num_ctx: int | None = None,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    memla_policy_bank_path: str = "",
    disable_memla_policy_bank: bool = False,
) -> dict[str, Any]:
    cases = load_policy_authz_cases(cases_path)
    if case_ids:
        wanted = {str(case_id).strip().lower() for case_id in case_ids if str(case_id).strip()}
        cases = [case for case in cases if case.case_id.strip().lower() in wanted]
    if limit is not None and int(limit) >= 0:
        cases = cases[: int(limit)]

    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    rows: list[PolicyAuthzBenchmarkRow] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        try:
            actual_rule_hits = _normalize_rule([hit.rule_id for hit in evaluate_policy_rules(case, case.request)])
            policy_priors = (
                {
                    "matched_tokens": [],
                    "decisions": [],
                    "rules": [],
                    "actions": [],
                    "teacher_rescue_decisions": [],
                    "teacher_rescue_rules": [],
                    "teacher_rescue_actions": [],
                }
                if disable_memla_policy_bank
                else suggest_policy_authz_priors(
                    prompt=case.prompt,
                    actual_rule_hits=actual_rule_hits,
                    repo_root=repo_root,
                    explicit_path=memla_policy_bank_path,
                )
            )
            raw_decision, raw_backtest, raw_trace = _decision_loop(
                client=raw_client,
                model=raw_model,
                case=case,
                iterations=max(raw_iterations, 1),
                temperature=temperature,
                num_ctx=num_ctx,
            )
            memla_decision, memla_backtest, memla_trace = _decision_loop(
                client=memla_client,
                model=memla_model,
                case=case,
                iterations=max(memla_iterations, 1),
                temperature=temperature,
                num_ctx=num_ctx,
                policy_priors=policy_priors,
            )

            raw_rule_recall = _score_overlap(raw_decision.predicted_rule_hits, case.expected_rule_hits)
            memla_rule_recall = _score_overlap(memla_decision.predicted_rule_hits, case.expected_rule_hits)
            raw_action_recall = _score_overlap(raw_decision.next_actions, case.expected_actions)
            memla_action_recall = _score_overlap(memla_decision.next_actions, case.expected_actions)
            raw_rewrite_recall = _rewrite_recall(raw_decision.rewrite, case.expected_rewrite)
            memla_rewrite_recall = _rewrite_recall(memla_decision.rewrite, case.expected_rewrite)
            raw_outcome_match = 1.0 if raw_decision.decision == case.expected_outcome else 0.0
            memla_outcome_match = 1.0 if memla_decision.decision == case.expected_outcome else 0.0
            raw_backtest_passed = 1.0 if raw_backtest.compliance_passed else 0.0
            memla_backtest_passed = 1.0 if memla_backtest.compliance_passed else 0.0
            raw_utility = _policy_utility(
                outcome_match=raw_outcome_match,
                backtest_passed=raw_backtest_passed,
                rule_recall=raw_rule_recall,
                action_recall=raw_action_recall,
                rewrite_recall=raw_rewrite_recall,
            )
            memla_utility = _policy_utility(
                outcome_match=memla_outcome_match,
                backtest_passed=memla_backtest_passed,
                rule_recall=memla_rule_recall,
                action_recall=memla_action_recall,
                rewrite_recall=memla_rewrite_recall,
            )

            rows.append(
                PolicyAuthzBenchmarkRow(
                    case_id=case.case_id,
                    prompt=case.prompt,
                    expected_outcome=case.expected_outcome,
                    expected_rule_hits=list(case.expected_rule_hits),
                    expected_actions=list(case.expected_actions),
                    expected_rewrite=dict(case.expected_rewrite),
                    actual_rule_hits=actual_rule_hits,
                    raw_decision=raw_decision.decision,
                    raw_predicted_rule_hits=list(raw_decision.predicted_rule_hits),
                    raw_next_actions=list(raw_decision.next_actions),
                    raw_rewrite=dict(raw_decision.rewrite),
                    raw_rule_recall=round(raw_rule_recall, 4),
                    raw_action_recall=round(raw_action_recall, 4),
                    raw_rewrite_recall=round(raw_rewrite_recall, 4),
                    raw_outcome_match=round(raw_outcome_match, 4),
                    raw_backtest_passed=round(raw_backtest_passed, 4),
                    raw_policy_utility=raw_utility,
                    raw_final_status=raw_backtest.final_status,
                    raw_iteration_trace=list(raw_trace),
                    memla_decision=memla_decision.decision,
                    memla_predicted_rule_hits=list(memla_decision.predicted_rule_hits),
                    memla_next_actions=list(memla_decision.next_actions),
                    memla_rewrite=dict(memla_decision.rewrite),
                    memla_rule_recall=round(memla_rule_recall, 4),
                    memla_action_recall=round(memla_action_recall, 4),
                    memla_rewrite_recall=round(memla_rewrite_recall, 4),
                    memla_outcome_match=round(memla_outcome_match, 4),
                    memla_backtest_passed=round(memla_backtest_passed, 4),
                    memla_policy_utility=memla_utility,
                    memla_final_status=memla_backtest.final_status,
                    memla_iteration_trace=list(memla_trace),
                    utility_delta=round(memla_utility - raw_utility, 4),
                )
            )
        except Exception as exc:
            failures.append({"case_id": case.case_id, "prompt": case.prompt, "error_type": type(exc).__name__, "error": str(exc)})

    count = max(len(rows), 1)
    avg_raw_utility = round(sum(row.raw_policy_utility for row in rows) / count, 4)
    avg_memla_utility = round(sum(row.memla_policy_utility for row in rows) / count, 4)
    utility_index = round(avg_memla_utility / avg_raw_utility, 4) if avg_raw_utility > 0 else None
    return {
        "generated_ts": int(time.time()),
        "cases_path": str(Path(cases_path).resolve()),
        "case_ids": list(case_ids or []),
        "limit": limit,
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "repo_root": str(Path(repo_root).resolve()) if repo_root else "",
        "memla_policy_bank_path": str(Path(memla_policy_bank_path).resolve()) if memla_policy_bank_path else "",
        "memla_policy_bank_enabled": not disable_memla_policy_bank,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failures),
        "avg_raw_outcome_match": round(sum(row.raw_outcome_match for row in rows) / count, 4),
        "avg_raw_rule_recall": round(sum(row.raw_rule_recall for row in rows) / count, 4),
        "avg_raw_action_recall": round(sum(row.raw_action_recall for row in rows) / count, 4),
        "avg_raw_backtest_passed": round(sum(row.raw_backtest_passed for row in rows) / count, 4),
        "avg_raw_policy_utility": avg_raw_utility,
        "avg_memla_outcome_match": round(sum(row.memla_outcome_match for row in rows) / count, 4),
        "avg_memla_rule_recall": round(sum(row.memla_rule_recall for row in rows) / count, 4),
        "avg_memla_action_recall": round(sum(row.memla_action_recall for row in rows) / count, 4),
        "avg_memla_backtest_passed": round(sum(row.memla_backtest_passed for row in rows) / count, 4),
        "avg_memla_policy_utility": avg_memla_utility,
        "memla_vs_raw_policy_utility_index": utility_index,
        "rows": [asdict(row) for row in rows],
        "failed_cases": failures,
    }


def render_policy_authz_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Policy Authz Benchmark",
        "",
        f"- Raw provider: `{report.get('raw_provider', 'unknown')}`",
        f"- Memla provider: `{report.get('memla_provider', 'unknown')}`",
        f"- Raw model: `{report.get('raw_model', 'unknown')}`",
        f"- Memla model: `{report.get('memla_model', 'unknown')}`",
        f"- Cases completed: `{report.get('cases', 0)}` / `{report.get('cases_requested', 0)}`",
        "",
        "## Lane summary",
        "",
        "| Metric | Raw | Memla |",
        "| --- | --- | --- |",
        f"| Outcome match | `{report.get('avg_raw_outcome_match', 0.0)}` | `{report.get('avg_memla_outcome_match', 0.0)}` |",
        f"| Rule recall | `{report.get('avg_raw_rule_recall', 0.0)}` | `{report.get('avg_memla_rule_recall', 0.0)}` |",
        f"| Action recall | `{report.get('avg_raw_action_recall', 0.0)}` | `{report.get('avg_memla_action_recall', 0.0)}` |",
        f"| Backtest passed | `{report.get('avg_raw_backtest_passed', 0.0)}` | `{report.get('avg_memla_backtest_passed', 0.0)}` |",
        f"| Policy utility | `{report.get('avg_raw_policy_utility', 0.0)}` | `{report.get('avg_memla_policy_utility', 0.0)}` |",
    ]
    utility_index = report.get("memla_vs_raw_policy_utility_index")
    if utility_index is not None:
        lines.extend(["", f"- Memla vs raw policy utility index: `{utility_index}`"])
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for item in report.get("failed_cases", []):
            lines.append(f"- `{item.get('case_id', '')}` [{item.get('error_type', 'Error')}] {item.get('error', '')}")
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        lines.extend(
            [
                f"### {row.get('case_id', '').strip()}",
                "",
                f"- Prompt: {row.get('prompt', '').strip()}",
                f"- Expected outcome: `{row.get('expected_outcome', '')}`",
                f"- Actual triggered rules: `{', '.join(row.get('actual_rule_hits', []))}`",
                f"- Raw decision: `{row.get('raw_decision', '')}` ({row.get('raw_final_status', '')})",
                f"- Memla decision: `{row.get('memla_decision', '')}` ({row.get('memla_final_status', '')})",
                f"- Raw utility: `{row.get('raw_policy_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_policy_utility', 0.0)}`",
                f"- Utility delta: `{row.get('utility_delta', 0.0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
