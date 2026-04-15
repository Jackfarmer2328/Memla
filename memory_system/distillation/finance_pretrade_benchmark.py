from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..ollama_client import ChatMessage
from .finance_policy_bank import suggest_finance_policy_priors
from .patch_execution_benchmark import _build_llm_client


FINANCE_PRETRADE_SYSTEM = """
You are a pre-trade compliance analyst.

Given an order, account state, market data, and control thresholds, choose the best bounded compliance action.
Return strict JSON only with this shape:
{
  "decision": "allow|block|escalate|modify",
  "predicted_rule_hits": ["max_order_notional"],
  "next_actions": ["reduce_quantity"],
  "rewrite": {"quantity": 5000, "price": 100.0, "route": "ATS_A"},
  "rationale": "short explanation"
}

Rules:
- Use "allow" only if the order should pass as submitted.
- Use "block" when the order should be stopped outright.
- Use "escalate" when the order needs supervisor review or approval.
- Use "modify" only when a concrete rewrite creates a compliant path.
- If no rewrite is needed, return an empty object for rewrite.
- Do not include markdown fences or extra prose.
""".strip()


KNOWN_RULE_IDS = (
    "restricted_symbol",
    "max_order_notional",
    "approval_required_notional",
    "price_deviation_limit",
    "projected_long_position_limit",
    "projected_short_position_limit",
    "duplicate_order_window",
    "unsupported_route",
)

KNOWN_NEXT_ACTIONS = (
    "reduce_quantity",
    "reprice_within_band",
    "request_supervisor_approval",
    "route_to_supported_venue",
    "hold_duplicate_for_review",
    "block_order",
)

RULE_ID_ALIASES = {
    "approval_notional": "approval_required_notional",
    "approval_threshold": "approval_required_notional",
    "duplicate_window_seconds": "duplicate_order_window",
    "duplicate_review_window": "duplicate_order_window",
    "max_long_position": "projected_long_position_limit",
    "max_order_value": "max_order_notional",
    "max_price_deviation_pct": "price_deviation_limit",
    "max_short_position": "projected_short_position_limit",
    "price_band": "price_deviation_limit",
    "price_band_limit": "price_deviation_limit",
    "restricted_symbols": "restricted_symbol",
    "unsupported_venue": "unsupported_route",
}

NEXT_ACTION_ALIASES = {
    "adjust_price": "reprice_within_band",
    "block": "block_order",
    "hold_for_review": "hold_duplicate_for_review",
    "reject_order": "block_order",
    "reprice": "reprice_within_band",
    "request_approval": "request_supervisor_approval",
    "review_order": "request_supervisor_approval",
    "route_to_supported_route": "route_to_supported_venue",
    "supervisor_review": "request_supervisor_approval",
}


@dataclass(frozen=True)
class FinancePretradeCase:
    case_id: str
    prompt: str
    order: dict[str, Any]
    account: dict[str, Any]
    market: dict[str, Any]
    controls: dict[str, Any]
    recent_orders: list[dict[str, Any]]
    expected_outcome: str
    expected_rule_hits: list[str]
    expected_actions: list[str]
    expected_rewrite: dict[str, Any]


@dataclass(frozen=True)
class FinanceRuleHit:
    rule_id: str
    severity: str
    message: str
    field: str = ""
    actual: str = ""
    threshold: str = ""


@dataclass(frozen=True)
class FinanceDecision:
    decision: str
    predicted_rule_hits: list[str]
    next_actions: list[str]
    rewrite: dict[str, Any]
    rationale: str
    response_text: str
    parse_mode: str


@dataclass(frozen=True)
class FinanceBacktestResult:
    rule_hits: list[FinanceRuleHit]
    modified_rule_hits: list[FinanceRuleHit]
    modified_order: dict[str, Any]
    compliance_passed: bool
    final_status: str
    residual_constraints: list[str]


@dataclass(frozen=True)
class FinanceIterationTrace:
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
class FinancePretradeBenchmarkRow:
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
    raw_finance_utility: float
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
    memla_finance_utility: float
    memla_final_status: str
    memla_iteration_trace: list[dict[str, Any]]
    utility_delta: float


def _normalize_str_list(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for value in values:
        clean = " ".join(str(value or "").strip().split())
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(clean)
    return out


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


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {value.lower() for value in predicted}
    expected_set = {value.lower() for value in expected}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def load_finance_pretrade_cases(path: str) -> list[FinancePretradeCase]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cases: list[FinancePretradeCase] = []
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        cases.append(
            FinancePretradeCase(
                case_id=str(row.get("case_id") or f"case_{len(cases) + 1}"),
                prompt=str(row.get("prompt") or "").strip(),
                order=dict(row.get("order") or {}),
                account=dict(row.get("account") or {}),
                market=dict(row.get("market") or {}),
                controls=dict(row.get("controls") or {}),
                recent_orders=list(row.get("recent_orders") or []),
                expected_outcome=str(row.get("expected_outcome") or "").strip().lower(),
                expected_rule_hits=_normalize_rule(list(row.get("expected_rule_hits") or [])),
                expected_actions=_normalize_action(list(row.get("expected_actions") or [])),
                expected_rewrite=dict(row.get("expected_rewrite") or {}),
            )
        )
    return cases


def _render_case_payload(case: FinancePretradeCase) -> str:
    payload = {
        "case_id": case.case_id,
        "prompt": case.prompt,
        "order": case.order,
        "account": case.account,
        "market": case.market,
        "controls": case.controls,
        "recent_orders": case.recent_orders,
    }
    return json.dumps(payload, indent=2, sort_keys=True)


def _order_notional(order: dict[str, Any]) -> float:
    return round(_coerce_float(order.get("quantity"), 0.0) * _coerce_float(order.get("price"), 0.0), 4)


def _projected_position(order: dict[str, Any], account: dict[str, Any]) -> float:
    current_position = _coerce_float(account.get("current_position"), 0.0)
    quantity = _coerce_float(order.get("quantity"), 0.0)
    side = str(order.get("side") or "").strip().lower()
    direction = 1.0 if side == "buy" else -1.0
    return current_position + (direction * quantity)


def _same_order(a: dict[str, Any], b: dict[str, Any]) -> bool:
    keys = ("symbol", "side", "quantity", "price", "route")
    return all(str(a.get(key) or "").strip().lower() == str(b.get(key) or "").strip().lower() for key in keys)


def evaluate_pretrade_rules(case: FinancePretradeCase, order: dict[str, Any]) -> list[FinanceRuleHit]:
    hits: list[FinanceRuleHit] = []
    controls = case.controls
    account = case.account
    market = case.market
    symbol = str(order.get("symbol") or "").strip().upper()
    route = str(order.get("route") or "").strip()
    notional = _order_notional(order)
    price = _coerce_float(order.get("price"), 0.0)

    restricted_symbols = {str(item).strip().upper() for item in controls.get("restricted_symbols") or [] if str(item).strip()}
    if symbol and symbol in restricted_symbols:
        hits.append(
            FinanceRuleHit(
                rule_id="restricted_symbol",
                severity="hard",
                message=f"{symbol} is on the restricted symbol list.",
                field="symbol",
                actual=symbol,
            )
        )

    max_order_notional = _coerce_float(controls.get("max_order_notional"), 0.0)
    if max_order_notional > 0 and notional > max_order_notional:
        hits.append(
            FinanceRuleHit(
                rule_id="max_order_notional",
                severity="hard",
                message="Order notional exceeds the hard per-order limit.",
                field="notional",
                actual=str(notional),
                threshold=str(max_order_notional),
            )
        )

    approval_notional = _coerce_float(controls.get("approval_notional"), 0.0)
    if approval_notional > 0 and notional > approval_notional:
        hits.append(
            FinanceRuleHit(
                rule_id="approval_required_notional",
                severity="soft",
                message="Order exceeds the supervisor approval threshold.",
                field="notional",
                actual=str(notional),
                threshold=str(approval_notional),
            )
        )

    reference_price = _coerce_float(market.get("reference_price"), 0.0)
    max_price_deviation_pct = _coerce_float(controls.get("max_price_deviation_pct"), 0.0)
    if reference_price > 0 and max_price_deviation_pct > 0:
        deviation_pct = abs(price - reference_price) / reference_price
        if deviation_pct > max_price_deviation_pct:
            hits.append(
                FinanceRuleHit(
                    rule_id="price_deviation_limit",
                    severity="hard",
                    message="Order price falls outside the permitted reference band.",
                    field="price",
                    actual=str(price),
                    threshold=str(round(reference_price * (1 + max_price_deviation_pct), 4)),
                )
            )

    projected_position = _projected_position(order, account)
    max_long_position = _coerce_float(controls.get("max_long_position"), math.inf)
    max_short_position = _coerce_float(controls.get("max_short_position"), math.inf)
    if max_long_position != math.inf and projected_position > max_long_position:
        hits.append(
            FinanceRuleHit(
                rule_id="projected_long_position_limit",
                severity="hard",
                message="Projected long position exceeds the configured limit.",
                field="quantity",
                actual=str(round(projected_position, 4)),
                threshold=str(max_long_position),
            )
        )
    if max_short_position != math.inf and projected_position < (-1.0 * max_short_position):
        hits.append(
            FinanceRuleHit(
                rule_id="projected_short_position_limit",
                severity="hard",
                message="Projected short position exceeds the configured limit.",
                field="quantity",
                actual=str(round(projected_position, 4)),
                threshold=str(-1.0 * max_short_position),
            )
        )

    duplicate_window_seconds = _coerce_int(controls.get("duplicate_window_seconds"), 0)
    event_ts = _coerce_int(order.get("ts"), 0)
    if duplicate_window_seconds > 0 and event_ts:
        for previous in case.recent_orders:
            previous_ts = _coerce_int(previous.get("ts"), 0)
            if previous_ts <= 0:
                continue
            if abs(event_ts - previous_ts) <= duplicate_window_seconds and _same_order(order, previous):
                hits.append(
                    FinanceRuleHit(
                        rule_id="duplicate_order_window",
                        severity="soft",
                        message="A matching order was seen inside the duplicate-order review window.",
                        field="ts",
                        actual=str(event_ts),
                        threshold=str(duplicate_window_seconds),
                    )
                )
                break

    allowed_routes = {str(item).strip() for item in controls.get("allowed_routes") or [] if str(item).strip()}
    if allowed_routes and route and route not in allowed_routes:
        hits.append(
            FinanceRuleHit(
                rule_id="unsupported_route",
                severity="hard",
                message="Order route is not enabled for this control set.",
                field="route",
                actual=route,
            )
        )

    return hits


def _apply_rewrite(order: dict[str, Any], rewrite: dict[str, Any]) -> dict[str, Any]:
    updated = dict(order)
    for key in ("quantity", "price", "route", "side", "symbol"):
        if key not in rewrite or rewrite.get(key) in (None, ""):
            continue
        updated[key] = rewrite.get(key)
    return updated


def backtest_finance_decision(case: FinancePretradeCase, decision: FinanceDecision) -> FinanceBacktestResult:
    initial_hits = evaluate_pretrade_rules(case, case.order)
    residuals: list[str] = []
    modified_hits: list[FinanceRuleHit] = []
    modified_order: dict[str, Any] = {}
    current_decision = str(decision.decision or "").strip().lower()
    hard_hits = [hit for hit in initial_hits if str(hit.severity or "").strip().lower() == "hard"]
    soft_hits = [hit for hit in initial_hits if str(hit.severity or "").strip().lower() == "soft"]

    if current_decision == "allow":
        compliance_passed = not initial_hits
        final_status = "allow_ok" if compliance_passed else "unsafe_allow"
        if initial_hits:
            residuals.extend([f"order_still_violates:{hit.rule_id}" for hit in initial_hits])
    elif current_decision == "block":
        if hard_hits:
            compliance_passed = True
            final_status = "block_ok"
        elif soft_hits:
            compliance_passed = False
            final_status = "overblocked_soft_review"
            residuals.extend([f"soft_review_prefers_escalation:{hit.rule_id}" for hit in soft_hits])
        else:
            compliance_passed = False
            final_status = "unnecessary_block"
            residuals.append("no_triggered_rule_for_block")
    elif current_decision == "escalate":
        if hard_hits:
            compliance_passed = False
            final_status = "escalation_insufficient_for_hard_block"
            residuals.extend([f"hard_rule_requires_block_or_modify:{hit.rule_id}" for hit in hard_hits])
        elif soft_hits:
            compliance_passed = True
            final_status = "escalate_ok"
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
            modified_order = _apply_rewrite(case.order, decision.rewrite)
            modified_hits = evaluate_pretrade_rules(case, modified_order)
            compliance_passed = not modified_hits
            final_status = "modify_ok" if compliance_passed else "modify_still_violates"
            if modified_hits:
                residuals.extend([f"modified_order_violates:{hit.rule_id}" for hit in modified_hits])
    else:
        compliance_passed = False
        final_status = "invalid_decision"
        residuals.append("invalid_decision")

    return FinanceBacktestResult(
        rule_hits=initial_hits,
        modified_rule_hits=modified_hits,
        modified_order=modified_order,
        compliance_passed=compliance_passed,
        final_status=final_status,
        residual_constraints=_normalize_str_list(residuals),
    )


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
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


def _normalize_rewrite(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    rewrite: dict[str, Any] = {}
    for key in ("quantity", "price", "route", "side", "symbol"):
        if key not in value:
            continue
        item = value.get(key)
        if key == "quantity":
            rewrite[key] = _coerce_int(item, 0)
        elif key == "price":
            rewrite[key] = round(_coerce_float(item, 0.0), 4)
        else:
            rewrite[key] = str(item).strip()
    return {key: val for key, val in rewrite.items() if val not in ("", 0, 0.0)}


def _normalize_decision_payload(payload: dict[str, Any], response: str) -> FinanceDecision:
    normalized_rule_hits = _normalize_rule(list(payload.get("predicted_rule_hits") or []))
    if not normalized_rule_hits:
        normalized_rule_hits = _extract_label_hits_from_text(
            response,
            known=KNOWN_RULE_IDS,
            aliases=RULE_ID_ALIASES,
        )
    normalized_actions = _normalize_action(list(payload.get("next_actions") or []))
    if not normalized_actions:
        normalized_actions = _extract_label_hits_from_text(
            response,
            known=KNOWN_NEXT_ACTIONS,
            aliases=NEXT_ACTION_ALIASES,
        )
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"allow", "block", "escalate", "modify"}:
        decision = _infer_decision_from_text(response)
    return FinanceDecision(
        decision=decision if decision in {"allow", "block", "escalate", "modify"} else "block",
        predicted_rule_hits=normalized_rule_hits,
        next_actions=normalized_actions,
        rewrite=_normalize_rewrite(payload.get("rewrite") or {}),
        rationale=" ".join(str(payload.get("rationale") or "").split()),
        response_text=str(response or ""),
        parse_mode="json" if payload else "heuristic",
    )


def _repair_decision_payload(
    *,
    client: Any,
    model: str,
    response: str,
    temperature: float,
    num_ctx: int | None,
) -> FinanceDecision:
    repair_prompt = (
        "Convert the answer below into strict JSON only with the required shape.\n"
        "If a field is unknown, use empty arrays or an empty object.\n\n"
        "Answer to convert:\n"
        f"{response}"
    )
    repaired = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=FINANCE_PRETRADE_SYSTEM),
            ChatMessage(role="user", content=repair_prompt),
        ],
        temperature=min(float(temperature), 0.1),
        num_ctx=num_ctx,
    ).strip()
    decision = _normalize_decision_payload(_extract_json_object(repaired), repaired)
    parse_mode = "json_repair" if decision.parse_mode == "json" else "json_repair_heuristic"
    return FinanceDecision(
        decision=decision.decision,
        predicted_rule_hits=decision.predicted_rule_hits,
        next_actions=decision.next_actions,
        rewrite=decision.rewrite,
        rationale=decision.rationale,
        response_text=repaired,
        parse_mode=parse_mode,
    )


def _rewrite_recall(actual: dict[str, Any], expected: dict[str, Any]) -> float:
    if not expected:
        return 1.0
    matched = 0
    for key, expected_value in expected.items():
        if key not in actual:
            continue
        actual_value = actual.get(key)
        if isinstance(expected_value, float):
            if abs(_coerce_float(actual_value) - float(expected_value)) < 1e-6:
                matched += 1
        else:
            if str(actual_value).strip().lower() == str(expected_value).strip().lower():
                matched += 1
    return matched / max(len(expected), 1)


def _finance_utility(
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


def _render_finance_policy_block(priors: dict[str, Any]) -> str:
    if not any(priors.get(key) for key in ("decisions", "rules", "actions", "teacher_rescue_decisions", "teacher_rescue_actions")):
        return ""
    lines = ["=== MEMLA FINANCE PRIORS ==="]
    matched_tokens = list(priors.get("matched_tokens") or [])
    if matched_tokens:
        lines.append(f"Matched prompt tokens: {', '.join(matched_tokens[:8])}")
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
    rules = list(priors.get("rules") or [])
    if rules:
        lines.append(f"Likely rules: {', '.join(rules[:4])}")
    actions = list(priors.get("actions") or [])
    if actions:
        lines.append(f"Likely actions: {', '.join(actions[:4])}")
    lines.append("Use these priors only if they fit the current state and preserve direct control.")
    return "\n".join(lines)


def _query_finance_decision(
    *,
    client: Any,
    model: str,
    case: FinancePretradeCase,
    temperature: float,
    num_ctx: int | None,
    residual_constraints: list[str] | None = None,
    prior_trace: list[dict[str, Any]] | None = None,
    policy_priors: dict[str, Any] | None = None,
) -> FinanceDecision:
    user_parts = [
        "Evaluate this pre-trade compliance state and return the best bounded action.",
        _render_case_payload(case),
    ]
    policy_block = _render_finance_policy_block(policy_priors or {})
    if policy_block:
        user_parts.append(policy_block)
    if residual_constraints:
        user_parts.append(
            "Verifier residual constraints from the previous attempt:\n"
            + json.dumps(list(residual_constraints), indent=2)
        )
    if prior_trace:
        user_parts.append("Prior attempts:\n" + json.dumps(prior_trace, indent=2))
    response = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=FINANCE_PRETRADE_SYSTEM),
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
    case: FinancePretradeCase,
    iterations: int,
    temperature: float,
    num_ctx: int | None,
    policy_priors: dict[str, Any] | None = None,
) -> tuple[FinanceDecision, FinanceBacktestResult, list[dict[str, Any]]]:
    last_decision = FinanceDecision(
        decision="block",
        predicted_rule_hits=[],
        next_actions=[],
        rewrite={},
        rationale="",
        response_text="",
        parse_mode="empty",
    )
    last_backtest = FinanceBacktestResult(
        rule_hits=[],
        modified_rule_hits=[],
        modified_order={},
        compliance_passed=False,
        final_status="not_run",
        residual_constraints=["not_run"],
    )
    traces: list[dict[str, Any]] = []
    residual_constraints: list[str] = []

    for iteration in range(1, max(iterations, 1) + 1):
        decision = _query_finance_decision(
            client=client,
            model=model,
            case=case,
            temperature=temperature,
            num_ctx=num_ctx,
            residual_constraints=residual_constraints if residual_constraints else None,
            prior_trace=traces if traces else None,
            policy_priors=policy_priors,
        )
        backtest = backtest_finance_decision(case, decision)
        traces.append(
            asdict(
                FinanceIterationTrace(
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


def run_finance_pretrade_benchmark(
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
    memla_finance_policy_path: str = "",
    disable_memla_finance_policy: bool = False,
) -> dict[str, Any]:
    cases = load_finance_pretrade_cases(cases_path)
    if case_ids:
        wanted = {str(case_id).strip().lower() for case_id in case_ids if str(case_id).strip()}
        cases = [case for case in cases if case.case_id.strip().lower() in wanted]
    if limit is not None and int(limit) >= 0:
        cases = cases[: int(limit)]
    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    rows: list[FinancePretradeBenchmarkRow] = []
    failures: list[dict[str, Any]] = []

    for case in cases:
        try:
            actual_rule_hits = _normalize_action([hit.rule_id for hit in evaluate_pretrade_rules(case, case.order)])
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
                if disable_memla_finance_policy
                else suggest_finance_policy_priors(
                    prompt=case.prompt,
                    repo_root=repo_root,
                    explicit_path=memla_finance_policy_path,
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
            raw_utility = _finance_utility(
                outcome_match=raw_outcome_match,
                backtest_passed=raw_backtest_passed,
                rule_recall=raw_rule_recall,
                action_recall=raw_action_recall,
                rewrite_recall=raw_rewrite_recall,
            )
            memla_utility = _finance_utility(
                outcome_match=memla_outcome_match,
                backtest_passed=memla_backtest_passed,
                rule_recall=memla_rule_recall,
                action_recall=memla_action_recall,
                rewrite_recall=memla_rewrite_recall,
            )

            rows.append(
                FinancePretradeBenchmarkRow(
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
                    raw_finance_utility=raw_utility,
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
                    memla_finance_utility=memla_utility,
                    memla_final_status=memla_backtest.final_status,
                    memla_iteration_trace=list(memla_trace),
                    utility_delta=round(memla_utility - raw_utility, 4),
                )
            )
        except Exception as exc:
            failures.append(
                {
                    "case_id": case.case_id,
                    "prompt": case.prompt,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
            )

    count = max(len(rows), 1)
    avg_raw_utility = round(sum(row.raw_finance_utility for row in rows) / count, 4)
    avg_memla_utility = round(sum(row.memla_finance_utility for row in rows) / count, 4)
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
        "memla_finance_policy_path": str(Path(memla_finance_policy_path).resolve()) if memla_finance_policy_path else "",
        "memla_finance_policy_enabled": not disable_memla_finance_policy,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failures),
        "avg_raw_outcome_match": round(sum(row.raw_outcome_match for row in rows) / count, 4),
        "avg_raw_rule_recall": round(sum(row.raw_rule_recall for row in rows) / count, 4),
        "avg_raw_action_recall": round(sum(row.raw_action_recall for row in rows) / count, 4),
        "avg_raw_backtest_passed": round(sum(row.raw_backtest_passed for row in rows) / count, 4),
        "avg_raw_finance_utility": avg_raw_utility,
        "avg_memla_outcome_match": round(sum(row.memla_outcome_match for row in rows) / count, 4),
        "avg_memla_rule_recall": round(sum(row.memla_rule_recall for row in rows) / count, 4),
        "avg_memla_action_recall": round(sum(row.memla_action_recall for row in rows) / count, 4),
        "avg_memla_backtest_passed": round(sum(row.memla_backtest_passed for row in rows) / count, 4),
        "avg_memla_finance_utility": avg_memla_utility,
        "memla_vs_raw_finance_utility_index": utility_index,
        "rows": [asdict(row) for row in rows],
        "failed_cases": failures,
    }


def render_finance_pretrade_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Finance Pre-Trade Benchmark",
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
        f"| Finance utility | `{report.get('avg_raw_finance_utility', 0.0)}` | `{report.get('avg_memla_finance_utility', 0.0)}` |",
    ]
    utility_index = report.get("memla_vs_raw_finance_utility_index")
    if utility_index is not None:
        lines.extend(["", f"- Memla vs raw finance utility index: `{utility_index}`"])
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
                f"- Raw utility: `{row.get('raw_finance_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_finance_utility', 0.0)}`",
                f"- Utility delta: `{row.get('utility_delta', 0.0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
