from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..ollama_client import ChatMessage
from .patch_execution_benchmark import _build_llm_client


HEALTHCARE_DENIAL_SYSTEM = """
You are a medical coding and claim-denial analyst.

Given a denied claim, denial metadata, and a bounded rule set, choose the best next action.
Return strict JSON only with this shape:
{
  "decision": "allow|block|escalate|modify",
  "predicted_rule_hits": ["mue_unit_limit"],
  "next_actions": ["reduce_units"],
  "rewrite": {
    "claim_diagnosis_codes": ["R07.9"],
    "drop_line_ids": ["2"],
    "line_updates": [
      {
        "line_id": "1",
        "procedure_code": "93000",
        "units": 1,
        "place_of_service": "11",
        "modifier_codes": ["25"],
        "diagnosis_codes": ["R07.9"]
      }
    ]
  },
  "rationale": "short explanation"
}

Rules:
- Use "allow" only if the claim should pass as submitted.
- Use "block" only when the claim should not be rebilled in its current form.
- Use "escalate" when staff review, prior auth, or documentation follow-up is required.
- Use "modify" only when a concrete claim rewrite creates a compliant rebill path.
- If no rewrite is needed, return an empty object for rewrite.
- Do not include markdown fences or extra prose.
""".strip()


KNOWN_RULE_IDS = (
    "mue_unit_limit",
    "required_modifier_missing",
    "ncci_code_pair_conflict",
    "diagnosis_support_mismatch",
    "prior_authorization_missing",
    "place_of_service_mismatch",
    "noncovered_service_code",
)

KNOWN_NEXT_ACTIONS = (
    "reduce_units",
    "add_required_modifier",
    "drop_conflicting_line",
    "replace_diagnosis_code",
    "request_prior_authorization",
    "correct_place_of_service",
    "do_not_rebill",
)

RULE_ID_ALIASES = {
    "blocked_code_pairs": "ncci_code_pair_conflict",
    "coding_conflict": "ncci_code_pair_conflict",
    "diagnosis_support": "diagnosis_support_mismatch",
    "diagnosis_mismatch": "diagnosis_support_mismatch",
    "invalid_pos": "place_of_service_mismatch",
    "missing_modifier": "required_modifier_missing",
    "noncovered_code_block": "noncovered_service_code",
    "mue_units": "mue_unit_limit",
    "ncci_conflict": "ncci_code_pair_conflict",
    "noncovered_code": "noncovered_service_code",
    "place_of_service": "place_of_service_mismatch",
    "prior_auth": "prior_authorization_missing",
    "required_modifier_add": "required_modifier_missing",
}

NEXT_ACTION_ALIASES = {
    "add_modifier_25": "add_required_modifier",
    "append_modifier": "add_required_modifier",
    "correct_pos": "correct_place_of_service",
    "drop_line": "drop_conflicting_line",
    "drop_line_ids": "drop_conflicting_line",
    "obtain_prior_auth": "request_prior_authorization",
    "request_prior_auth": "request_prior_authorization",
    "reduce_unit_count": "reduce_units",
    "swap_diagnosis_code": "replace_diagnosis_code",
    "write_off_claim": "do_not_rebill",
}


@dataclass(frozen=True)
class HealthcareClaimCase:
    case_id: str
    prompt: str
    claim: dict[str, Any]
    denial: dict[str, Any]
    controls: dict[str, Any]
    expected_outcome: str
    expected_rule_hits: list[str]
    expected_actions: list[str]
    expected_rewrite: dict[str, Any]


@dataclass(frozen=True)
class HealthcareRuleHit:
    rule_id: str
    severity: str
    message: str
    line_id: str = ""
    procedure_code: str = ""


@dataclass(frozen=True)
class HealthcareDecision:
    decision: str
    predicted_rule_hits: list[str]
    next_actions: list[str]
    rewrite: dict[str, Any]
    rationale: str
    response_text: str
    parse_mode: str


@dataclass(frozen=True)
class HealthcareBacktestResult:
    rule_hits: list[HealthcareRuleHit]
    modified_rule_hits: list[HealthcareRuleHit]
    modified_claim: dict[str, Any]
    compliance_passed: bool
    final_status: str
    residual_constraints: list[str]


@dataclass(frozen=True)
class HealthcareIterationTrace:
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
class HealthcareBenchmarkRow:
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
    raw_healthcare_utility: float
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
    memla_healthcare_utility: float
    memla_final_status: str
    memla_iteration_trace: list[dict[str, Any]]
    utility_delta: float


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


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


def _normalize_code_list(values: Any) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in list(values or []):
        clean = str(value or "").strip().upper()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        out.append(clean)
    return out


def _normalize_line_update(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    line_id = str(value.get("line_id") or "").strip()
    if not line_id:
        return {}
    update: dict[str, Any] = {"line_id": line_id}
    if "procedure_code" in value and str(value.get("procedure_code") or "").strip():
        update["procedure_code"] = str(value.get("procedure_code") or "").strip().upper()
    if "units" in value and value.get("units") not in (None, ""):
        update["units"] = _coerce_int(value.get("units"), 0)
    if "place_of_service" in value and str(value.get("place_of_service") or "").strip():
        update["place_of_service"] = str(value.get("place_of_service") or "").strip()
    if "modifier_codes" in value:
        modifiers = _normalize_code_list(value.get("modifier_codes") or [])
        if modifiers:
            update["modifier_codes"] = modifiers
    if "diagnosis_codes" in value:
        diagnoses = _normalize_code_list(value.get("diagnosis_codes") or [])
        if diagnoses:
            update["diagnosis_codes"] = diagnoses
    return update


def _normalize_rewrite(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rewrite: dict[str, Any] = {}
    claim_diagnosis_codes = _normalize_code_list(value.get("claim_diagnosis_codes") or [])
    if claim_diagnosis_codes:
        rewrite["claim_diagnosis_codes"] = claim_diagnosis_codes
    drop_line_ids = sorted({str(item).strip() for item in list(value.get("drop_line_ids") or []) if str(item).strip()})
    if drop_line_ids:
        rewrite["drop_line_ids"] = drop_line_ids
    line_updates = [_normalize_line_update(item) for item in list(value.get("line_updates") or [])]
    line_updates = [item for item in line_updates if item]
    if line_updates:
        rewrite["line_updates"] = sorted(line_updates, key=lambda item: item.get("line_id", ""))
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


def _canonical_jsonish(value: Any) -> Any:
    if isinstance(value, dict):
        if "line_id" in value:
            ordered = {"line_id": str(value.get("line_id") or "").strip()}
            for key in ("procedure_code", "units", "place_of_service", "modifier_codes", "diagnosis_codes"):
                if key in value:
                    ordered[key] = _canonical_jsonish(value.get(key))
            return ordered
        return {str(key): _canonical_jsonish(val) for key, val in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, list):
        items = [_canonical_jsonish(item) for item in value]
        if items and all(isinstance(item, dict) and "line_id" in item for item in items):
            return sorted(items, key=lambda item: str(item.get("line_id") or ""))
        normalized = [str(item).strip().upper() if not isinstance(item, (dict, list)) else item for item in items]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else str(item))
    if isinstance(value, str):
        return value.strip().upper()
    return value


def _line_update_contains(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    actual_line_id = str(actual.get("line_id") or "").strip()
    expected_line_id = str(expected.get("line_id") or "").strip()
    if expected_line_id and actual_line_id != expected_line_id:
        return False
    for key, expected_value in expected.items():
        if key == "line_id":
            continue
        if key not in actual:
            return False
        if _canonical_jsonish(actual.get(key)) != _canonical_jsonish(expected_value):
            return False
    return True


def _rewrite_recall(actual: dict[str, Any], expected: dict[str, Any]) -> float:
    if not expected:
        return 1.0
    matched = 0
    for key, expected_value in expected.items():
        if key not in actual:
            continue
        actual_value = actual.get(key)
        if key == "line_updates":
            expected_updates = list(expected_value or [])
            actual_updates = list(actual_value or [])
            if expected_updates and all(
                any(_line_update_contains(actual_item, expected_item) for actual_item in actual_updates)
                for expected_item in expected_updates
            ):
                matched += 1
                continue
        if key == "drop_line_ids":
            expected_ids = {str(item).strip() for item in list(expected_value or []) if str(item).strip()}
            actual_ids = {str(item).strip() for item in list(actual_value or []) if str(item).strip()}
            if expected_ids and expected_ids.issubset(actual_ids):
                matched += 1
                continue
        if _canonical_jsonish(actual_value) == _canonical_jsonish(expected_value):
            matched += 1
    return matched / max(len(expected), 1)


def load_healthcare_claim_cases(path: str) -> list[HealthcareClaimCase]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cases: list[HealthcareClaimCase] = []
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        cases.append(
            HealthcareClaimCase(
                case_id=str(row.get("case_id") or f"case_{len(cases) + 1}"),
                prompt=str(row.get("prompt") or "").strip(),
                claim=dict(row.get("claim") or {}),
                denial=dict(row.get("denial") or {}),
                controls=dict(row.get("controls") or {}),
                expected_outcome=str(row.get("expected_outcome") or "").strip().lower(),
                expected_rule_hits=_normalize_rule(list(row.get("expected_rule_hits") or [])),
                expected_actions=_normalize_action(list(row.get("expected_actions") or [])),
                expected_rewrite=_normalize_rewrite(dict(row.get("expected_rewrite") or {})),
            )
        )
    return cases


def _render_case_payload(case: HealthcareClaimCase) -> str:
    payload = {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "claim": case.claim,
        "denial": case.denial,
        "controls": case.controls,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def evaluate_healthcare_rules(case: HealthcareClaimCase, claim: dict[str, Any]) -> list[HealthcareRuleHit]:
    hits: list[HealthcareRuleHit] = []
    controls = case.controls
    claim_diagnosis_codes = _normalize_code_list(claim.get("diagnosis_codes") or [])
    service_lines = [dict(item) for item in list(claim.get("service_lines") or [])]

    noncovered_codes = {code for code in _normalize_code_list(controls.get("noncovered_codes") or [])}
    required_prior_auth_codes = {code for code in _normalize_code_list(controls.get("required_prior_auth_codes") or [])}
    max_units_by_code = {str(key).strip().upper(): _coerce_int(val, 0) for key, val in dict(controls.get("max_units_by_code") or {}).items()}
    required_modifiers_by_code = {
        str(key).strip().upper(): _normalize_code_list(val or [])
        for key, val in dict(controls.get("required_modifiers_by_code") or {}).items()
    }
    supported_diagnosis_by_code = {
        str(key).strip().upper(): _normalize_code_list(val or [])
        for key, val in dict(controls.get("supported_diagnosis_by_code") or {}).items()
    }
    allowed_pos_by_code = {
        str(key).strip().upper(): {str(item).strip() for item in list(val or []) if str(item).strip()}
        for key, val in dict(controls.get("allowed_pos_by_code") or {}).items()
    }
    blocked_code_pairs = [
        tuple(_normalize_code_list(pair)[:2])
        for pair in list(controls.get("blocked_code_pairs") or [])
        if len(_normalize_code_list(pair)) >= 2
    ]

    active_codes: dict[str, str] = {}
    for line in service_lines:
        line_id = str(line.get("line_id") or "").strip()
        procedure_code = str(line.get("procedure_code") or "").strip().upper()
        if not line_id or not procedure_code:
            continue
        active_codes[procedure_code] = line_id

        if procedure_code in noncovered_codes:
            hits.append(HealthcareRuleHit("noncovered_service_code", "terminal", "The service code is marked non-covered under the configured rules.", line_id, procedure_code))
        if procedure_code in required_prior_auth_codes and not bool(claim.get("prior_authorization_present")):
            hits.append(HealthcareRuleHit("prior_authorization_missing", "soft", "The service requires prior authorization before rebilling.", line_id, procedure_code))

        max_units = max_units_by_code.get(procedure_code, 0)
        units = _coerce_int(line.get("units"), 0)
        if max_units > 0 and units > max_units:
            hits.append(HealthcareRuleHit("mue_unit_limit", "hard", "Claim units exceed the configured medically unlikely edit threshold.", line_id, procedure_code))

        required_modifiers = set(required_modifiers_by_code.get(procedure_code, []))
        actual_modifiers = set(_normalize_code_list(line.get("modifier_codes") or []))
        if required_modifiers and not required_modifiers.issubset(actual_modifiers):
            hits.append(HealthcareRuleHit("required_modifier_missing", "hard", "A required modifier is missing for this procedure line.", line_id, procedure_code))

        supported_diagnoses = set(supported_diagnosis_by_code.get(procedure_code, []))
        line_diagnosis_codes = _normalize_code_list(line.get("diagnosis_codes") or []) or claim_diagnosis_codes
        if supported_diagnoses and not (supported_diagnoses & set(line_diagnosis_codes)):
            hits.append(HealthcareRuleHit("diagnosis_support_mismatch", "hard", "The diagnosis codes on this line do not support the billed procedure.", line_id, procedure_code))

        allowed_pos = allowed_pos_by_code.get(procedure_code, set())
        actual_pos = str(line.get("place_of_service") or "").strip()
        if allowed_pos and actual_pos not in allowed_pos:
            hits.append(HealthcareRuleHit("place_of_service_mismatch", "hard", "The place of service is not allowed for this procedure.", line_id, procedure_code))

    for first_code, second_code in blocked_code_pairs:
        if first_code in active_codes and second_code in active_codes:
            hits.append(
                HealthcareRuleHit(
                    "ncci_code_pair_conflict",
                    "hard",
                    "The claim contains a disallowed code pair that should not be billed together.",
                    f"{active_codes[first_code]},{active_codes[second_code]}",
                    f"{first_code},{second_code}",
                )
            )

    return hits


def _apply_rewrite(claim: dict[str, Any], rewrite: dict[str, Any]) -> dict[str, Any]:
    updated = json.loads(json.dumps(claim))
    if "claim_diagnosis_codes" in rewrite:
        updated["diagnosis_codes"] = list(rewrite.get("claim_diagnosis_codes") or [])

    drop_line_ids = {str(item).strip() for item in list(rewrite.get("drop_line_ids") or []) if str(item).strip()}
    service_lines = [dict(item) for item in list(updated.get("service_lines") or [])]
    if drop_line_ids:
        service_lines = [line for line in service_lines if str(line.get("line_id") or "").strip() not in drop_line_ids]

    updates = {str(item.get("line_id") or "").strip(): dict(item) for item in list(rewrite.get("line_updates") or []) if str(item.get("line_id") or "").strip()}
    for line in service_lines:
        line_id = str(line.get("line_id") or "").strip()
        update = updates.get(line_id)
        if not update:
            continue
        if "procedure_code" in update:
            line["procedure_code"] = str(update.get("procedure_code") or "").strip().upper()
        if "units" in update:
            line["units"] = _coerce_int(update.get("units"), 0)
        if "place_of_service" in update:
            line["place_of_service"] = str(update.get("place_of_service") or "").strip()
        if "modifier_codes" in update:
            line["modifier_codes"] = list(update.get("modifier_codes") or [])
        if "diagnosis_codes" in update:
            line["diagnosis_codes"] = list(update.get("diagnosis_codes") or [])

    updated["service_lines"] = service_lines
    return updated


def backtest_healthcare_decision(case: HealthcareClaimCase, decision: HealthcareDecision) -> HealthcareBacktestResult:
    initial_hits = evaluate_healthcare_rules(case, case.claim)
    residuals: list[str] = []
    modified_hits: list[HealthcareRuleHit] = []
    modified_claim: dict[str, Any] = {}
    current_decision = str(decision.decision or "").strip().lower()
    terminal_hits = [hit for hit in initial_hits if hit.severity == "terminal"]
    soft_hits = [hit for hit in initial_hits if hit.severity == "soft"]
    hard_hits = [hit for hit in initial_hits if hit.severity == "hard"]

    if current_decision == "allow":
        compliance_passed = not initial_hits
        final_status = "allow_ok" if compliance_passed else "unsafe_allow"
        if initial_hits:
            residuals.extend([f"claim_still_violates:{hit.rule_id}" for hit in initial_hits])
    elif current_decision == "block":
        if terminal_hits and not hard_hits and not soft_hits:
            compliance_passed = True
            final_status = "block_ok"
        elif soft_hits and not hard_hits and not terminal_hits:
            compliance_passed = False
            final_status = "overblocked_soft_review"
            residuals.extend([f"soft_review_prefers_escalation:{hit.rule_id}" for hit in soft_hits])
        else:
            compliance_passed = False
            final_status = "overblocked_repairable_claim"
            residuals.extend([f"repairable_claim_prefers_modify:{hit.rule_id}" for hit in hard_hits or terminal_hits])
    elif current_decision == "escalate":
        if soft_hits and not hard_hits and not terminal_hits:
            compliance_passed = True
            final_status = "escalate_ok"
        elif terminal_hits:
            compliance_passed = False
            final_status = "escalation_insufficient_for_noncovered"
            residuals.extend([f"noncovered_service_prefers_block:{hit.rule_id}" for hit in terminal_hits])
        else:
            compliance_passed = False
            final_status = "escalation_insufficient_for_coding_fix"
            residuals.extend([f"hard_rule_requires_modify_or_block:{hit.rule_id}" for hit in hard_hits])
    elif current_decision == "modify":
        if not decision.rewrite:
            compliance_passed = False
            final_status = "missing_rewrite"
            residuals.append("missing_rewrite")
        else:
            modified_claim = _apply_rewrite(case.claim, decision.rewrite)
            modified_hits = evaluate_healthcare_rules(case, modified_claim)
            compliance_passed = not modified_hits
            final_status = "modify_ok" if compliance_passed else "modify_still_violates"
            if modified_hits:
                residuals.extend([f"modified_claim_violates:{hit.rule_id}" for hit in modified_hits])
    else:
        compliance_passed = False
        final_status = "invalid_decision"
        residuals.append("invalid_decision")

    return HealthcareBacktestResult(
        rule_hits=initial_hits,
        modified_rule_hits=modified_hits,
        modified_claim=modified_claim,
        compliance_passed=compliance_passed,
        final_status=final_status,
        residual_constraints=residuals,
    )


def _normalize_decision_payload(payload: dict[str, Any], response: str) -> HealthcareDecision:
    normalized_rule_hits = _normalize_rule(list(payload.get("predicted_rule_hits") or []))
    if not normalized_rule_hits:
        normalized_rule_hits = _extract_label_hits_from_text(response, known=KNOWN_RULE_IDS, aliases=RULE_ID_ALIASES)
    normalized_actions = _normalize_action(list(payload.get("next_actions") or []))
    if not normalized_actions:
        normalized_actions = _extract_label_hits_from_text(response, known=KNOWN_NEXT_ACTIONS, aliases=NEXT_ACTION_ALIASES)
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"allow", "block", "escalate", "modify"}:
        decision = _infer_decision_from_text(response)
    return HealthcareDecision(
        decision=decision if decision in {"allow", "block", "escalate", "modify"} else "block",
        predicted_rule_hits=normalized_rule_hits,
        next_actions=normalized_actions,
        rewrite=_normalize_rewrite(payload.get("rewrite") or {}),
        rationale=" ".join(str(payload.get("rationale") or "").split()),
        response_text=str(response or ""),
        parse_mode="json" if payload else "heuristic",
    )


def _repair_decision_payload(*, client: Any, model: str, response: str, temperature: float, num_ctx: int | None) -> HealthcareDecision:
    repair_prompt = (
        "Convert the answer below into strict JSON only with the required shape.\n"
        "If a field is unknown, use empty arrays or an empty object.\n\n"
        "Answer to convert:\n"
        f"{response}"
    )
    repaired = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=HEALTHCARE_DENIAL_SYSTEM),
            ChatMessage(role="user", content=repair_prompt),
        ],
        temperature=min(float(temperature), 0.1),
        num_ctx=num_ctx,
    ).strip()
    decision = _normalize_decision_payload(_extract_json_object(repaired), repaired)
    parse_mode = "json_repair" if decision.parse_mode == "json" else "json_repair_heuristic"
    return HealthcareDecision(
        decision=decision.decision,
        predicted_rule_hits=decision.predicted_rule_hits,
        next_actions=decision.next_actions,
        rewrite=decision.rewrite,
        rationale=decision.rationale,
        response_text=repaired,
        parse_mode=parse_mode,
    )


def _query_healthcare_decision(
    *,
    client: Any,
    model: str,
    case: HealthcareClaimCase,
    temperature: float,
    num_ctx: int | None,
    residual_constraints: list[str] | None = None,
    prior_trace: list[dict[str, Any]] | None = None,
) -> HealthcareDecision:
    user_parts = [
        "Evaluate this denied-claim replay state and return the best bounded next action.",
        _render_case_payload(case),
    ]
    if residual_constraints:
        user_parts.append("Verifier residual constraints from the previous attempt:\n" + json.dumps(list(residual_constraints), indent=2))
    if prior_trace:
        user_parts.append("Prior attempts:\n" + json.dumps(prior_trace, indent=2))
    response = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=HEALTHCARE_DENIAL_SYSTEM),
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
    case: HealthcareClaimCase,
    iterations: int,
    temperature: float,
    num_ctx: int | None,
) -> tuple[HealthcareDecision, HealthcareBacktestResult, list[dict[str, Any]]]:
    last_decision = HealthcareDecision(
        decision="block",
        predicted_rule_hits=[],
        next_actions=[],
        rewrite={},
        rationale="",
        response_text="",
        parse_mode="empty",
    )
    last_backtest = HealthcareBacktestResult(
        rule_hits=[],
        modified_rule_hits=[],
        modified_claim={},
        compliance_passed=False,
        final_status="not_run",
        residual_constraints=["not_run"],
    )
    traces: list[dict[str, Any]] = []
    residual_constraints: list[str] = []

    for iteration in range(1, max(iterations, 1) + 1):
        decision = _query_healthcare_decision(
            client=client,
            model=model,
            case=case,
            temperature=temperature,
            num_ctx=num_ctx,
            residual_constraints=residual_constraints if residual_constraints else None,
            prior_trace=traces if traces else None,
        )
        backtest = backtest_healthcare_decision(case, decision)
        traces.append(
            asdict(
                HealthcareIterationTrace(
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


def _healthcare_utility(
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


def run_healthcare_denial_benchmark(
    *,
    cases_path: str,
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
) -> dict[str, Any]:
    cases = load_healthcare_claim_cases(cases_path)
    if case_ids:
        wanted = {str(case_id).strip().lower() for case_id in case_ids if str(case_id).strip()}
        cases = [case for case in cases if case.case_id.strip().lower() in wanted]
    if limit is not None and int(limit) >= 0:
        cases = cases[: int(limit)]

    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    rows: list[HealthcareBenchmarkRow] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        try:
            actual_rule_hits = _normalize_rule([hit.rule_id for hit in evaluate_healthcare_rules(case, case.claim)])
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
            raw_utility = _healthcare_utility(
                outcome_match=raw_outcome_match,
                backtest_passed=raw_backtest_passed,
                rule_recall=raw_rule_recall,
                action_recall=raw_action_recall,
                rewrite_recall=raw_rewrite_recall,
            )
            memla_utility = _healthcare_utility(
                outcome_match=memla_outcome_match,
                backtest_passed=memla_backtest_passed,
                rule_recall=memla_rule_recall,
                action_recall=memla_action_recall,
                rewrite_recall=memla_rewrite_recall,
            )

            rows.append(
                HealthcareBenchmarkRow(
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
                    raw_healthcare_utility=raw_utility,
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
                    memla_healthcare_utility=memla_utility,
                    memla_final_status=memla_backtest.final_status,
                    memla_iteration_trace=list(memla_trace),
                    utility_delta=round(memla_utility - raw_utility, 4),
                )
            )
        except Exception as exc:
            failures.append({"case_id": case.case_id, "prompt": case.prompt, "error_type": type(exc).__name__, "error": str(exc)})

    count = max(len(rows), 1)
    avg_raw_utility = round(sum(row.raw_healthcare_utility for row in rows) / count, 4)
    avg_memla_utility = round(sum(row.memla_healthcare_utility for row in rows) / count, 4)
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
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failures),
        "avg_raw_outcome_match": round(sum(row.raw_outcome_match for row in rows) / count, 4),
        "avg_raw_rule_recall": round(sum(row.raw_rule_recall for row in rows) / count, 4),
        "avg_raw_action_recall": round(sum(row.raw_action_recall for row in rows) / count, 4),
        "avg_raw_backtest_passed": round(sum(row.raw_backtest_passed for row in rows) / count, 4),
        "avg_raw_healthcare_utility": avg_raw_utility,
        "avg_memla_outcome_match": round(sum(row.memla_outcome_match for row in rows) / count, 4),
        "avg_memla_rule_recall": round(sum(row.memla_rule_recall for row in rows) / count, 4),
        "avg_memla_action_recall": round(sum(row.memla_action_recall for row in rows) / count, 4),
        "avg_memla_backtest_passed": round(sum(row.memla_backtest_passed for row in rows) / count, 4),
        "avg_memla_healthcare_utility": avg_memla_utility,
        "memla_vs_raw_healthcare_utility_index": utility_index,
        "rows": [asdict(row) for row in rows],
        "failed_cases": failures,
    }


def render_healthcare_denial_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Healthcare Claim-Denial Benchmark",
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
        f"| Healthcare utility | `{report.get('avg_raw_healthcare_utility', 0.0)}` | `{report.get('avg_memla_healthcare_utility', 0.0)}` |",
    ]
    utility_index = report.get("memla_vs_raw_healthcare_utility_index")
    if utility_index is not None:
        lines.extend(["", f"- Memla vs raw healthcare utility index: `{utility_index}`"])
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
                f"- Raw utility: `{row.get('raw_healthcare_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_healthcare_utility', 0.0)}`",
                f"- Utility delta: `{row.get('utility_delta', 0.0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
