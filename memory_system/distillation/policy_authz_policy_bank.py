from __future__ import annotations

from collections import Counter, defaultdict
import json
import os
import re
import time
from pathlib import Path
from typing import Any


_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "request",
    "choose",
    "best",
    "bounded",
    "action",
    "policy",
    "authorization",
    "state",
    "preserve",
}
_PRIORITY_WEIGHTS = {"low": 0.45, "medium": 1.0, "high": 1.35}
_SOFT_RULES = {"outside_change_window", "break_glass_required"}
_REPAIRABLE_RULES = {"mfa_required", "region_restricted"}
_HARD_RULES = {"restricted_resource_role", "role_not_permitted"}


def _normalize_token(token: str) -> str:
    token = token.lower()
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def _tokenize_prompt(text: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in re.findall(r"[A-Za-z0-9_]+", text or ""):
        token = _normalize_token(raw)
        if len(token) < 3 or token in _STOPWORDS or token in seen:
            continue
        seen.add(token)
        out.append(token)
    return out


def _normalize(values: list[str]) -> list[str]:
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


def _priority_weight(priority: str) -> float:
    return _PRIORITY_WEIGHTS.get(str(priority or "").strip().lower(), 1.0)


def _read_trace_bank(path: str) -> dict[str, Any]:
    target = Path(path).resolve()
    if target.suffix.lower() == ".jsonl":
        rows = [json.loads(line) for line in target.read_text(encoding="utf-8").splitlines() if line.strip()]
        return {"rows": rows}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload
    raise ValueError(f"Unsupported trace bank format: {target}")


def _policy_state_primitives(rule_hits: list[str]) -> list[str]:
    normalized = [str(item or "").strip().lower() for item in rule_hits if str(item or "").strip()]
    seen: set[str] = set()
    ordered: list[str] = []

    def _add(value: str) -> None:
        if value and value not in seen:
            seen.add(value)
            ordered.append(value)

    if not normalized:
        _add("clean_pass_state")
        return ordered

    hard = [item for item in normalized if item in _HARD_RULES]
    repairable = [item for item in normalized if item in _REPAIRABLE_RULES]
    soft = [item for item in normalized if item in _SOFT_RULES]

    if hard and not repairable and not soft:
        _add("hard_block_state")
    elif repairable and not hard and not soft:
        _add("repairable_state")
    elif soft and not hard and not repairable:
        _add("soft_review_state")
    elif hard and soft:
        _add("mixed_block_review_state")
    elif repairable and soft:
        _add("mixed_repair_review_state")
    else:
        _add("mixed_constraint_state")

    if "outside_change_window" in normalized:
        _add("time_window_constraint")
    if "break_glass_required" in normalized:
        _add("approval_gate_constraint")
    if "mfa_required" in normalized:
        _add("step_up_identity_constraint")
    if "region_restricted" in normalized:
        _add("location_repair_constraint")
    if "restricted_resource_role" in normalized or "role_not_permitted" in normalized:
        _add("permission_gap_constraint")

    return ordered


def _top_weighted(items: dict[str, float], *, limit: int) -> list[str]:
    ranked = sorted(
        ((name, weight) for name, weight in items.items() if str(name).strip() and float(weight) > 0.0),
        key=lambda item: (float(item[1]), len(str(item[0])), str(item[0]).lower()),
        reverse=True,
    )
    return [name for name, _ in ranked[: max(int(limit), 0)]]


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {str(item or "").strip().lower() for item in predicted if str(item or "").strip()}
    expected_set = {str(item or "").strip().lower() for item in expected if str(item or "").strip()}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def distill_policy_authz_policy_bank(*, trace_bank_path: str, min_priority: str = "medium") -> dict[str, Any]:
    payload = _read_trace_bank(trace_bank_path)
    rows = list(payload.get("rows") or [])
    min_rank = {"low": 0, "medium": 1, "high": 2}.get(str(min_priority or "medium").lower(), 1)

    token_decision_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_rule_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_action_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_teacher_decision_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_teacher_rule_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_teacher_action_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    state_decision_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    state_action_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    state_teacher_decision_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    state_teacher_action_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    state_teacher_rule_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_counts: Counter[str] = Counter()
    state_primitive_counts: Counter[str] = Counter()
    source_models: Counter[str] = Counter()
    kept_rows = 0

    for row in rows:
        priority = str(row.get("teaching_priority") or "medium").lower()
        rank = {"low": 0, "medium": 1, "high": 2}.get(priority, 1)
        if rank < min_rank:
            continue
        tokens = _tokenize_prompt(str(row.get("prompt") or ""))
        if not tokens:
            continue
        kept_rows += 1
        source_models[str(row.get("raw_model") or "unknown")] += 1
        winner = str(row.get("winner") or "tie")
        utility_delta = max(float(row.get("utility_delta", 0.0)), 0.0)
        memla_weight = _priority_weight(priority) * (1.0 + utility_delta + (0.35 if winner == "memla" else 0.0))
        teacher_weight = _priority_weight(priority) * (
            0.3 + float(row.get("raw_policy_utility", 0.0)) + (0.35 if winner == "raw" else 0.0)
        )
        if winner == "raw":
            memla_weight *= 0.15
            teacher_weight *= 1.35

        memla_decision = str(row.get("memla_decision") or "").strip().lower()
        raw_decision = str(row.get("raw_decision") or "").strip().lower()
        memla_rules = _normalize(list(row.get("memla_rule_hits") or []))
        raw_rules = _normalize(list(row.get("raw_rule_hits") or []))
        memla_actions = _normalize(list(row.get("memla_actions") or []))
        raw_actions = _normalize(list(row.get("raw_actions") or []))
        state_primitives = _policy_state_primitives(list(row.get("actual_rule_hits") or row.get("expected_rule_hits") or []))
        specific_primitives = [item for item in state_primitives if not item.endswith("_state")]
        expected_rules = _normalize(list(row.get("expected_rule_hits") or []))
        expected_actions = _normalize(list(row.get("expected_actions") or []))
        raw_rule_overlap = _score_overlap(raw_rules, expected_rules)
        memla_rule_overlap = _score_overlap(memla_rules, expected_rules)
        raw_action_overlap = _score_overlap(raw_actions, expected_actions)
        memla_action_overlap = _score_overlap(memla_actions, expected_actions)
        teacher_rule_items = raw_rules if raw_rule_overlap > memla_rule_overlap and raw_rule_overlap > 0.0 else []
        teacher_action_items = raw_actions if raw_action_overlap > memla_action_overlap and raw_action_overlap > 0.0 else []

        for token in tokens:
            token_counts[token] += 1
            if memla_decision and winner != "raw":
                token_decision_weights[token][memla_decision] += memla_weight
            for item in memla_rules:
                if winner == "raw":
                    continue
                token_rule_weights[token][item] += memla_weight
            for item in memla_actions:
                if winner == "raw":
                    continue
                token_action_weights[token][item] += memla_weight
            if raw_decision:
                token_teacher_decision_weights[token][raw_decision] += teacher_weight
            for item in teacher_rule_items:
                token_teacher_rule_weights[token][item] += teacher_weight
            for item in teacher_action_items:
                token_teacher_action_weights[token][item] += teacher_weight

        for primitive in state_primitives:
            state_primitive_counts[primitive] += 1
            if memla_decision and winner != "raw":
                state_decision_weights[primitive][memla_decision] += memla_weight
            for item in memla_actions:
                if winner == "raw":
                    continue
                state_action_weights[primitive][item] += memla_weight
            if raw_decision:
                state_teacher_decision_weights[primitive][raw_decision] += teacher_weight
        for primitive in specific_primitives:
            for item in teacher_action_items:
                state_teacher_action_weights[primitive][item] += teacher_weight
            for item in teacher_rule_items:
                state_teacher_rule_weights[primitive][item] += teacher_weight

    return {
        "generated_ts": int(time.time()),
        "source_trace_bank": str(Path(trace_bank_path).resolve()),
        "rows_seen": len(rows),
        "rows_used": kept_rows,
        "min_priority": min_priority,
        "source_models": dict(sorted(source_models.items())),
        "token_counts": dict(sorted(token_counts.items())),
        "state_primitive_counts": dict(sorted(state_primitive_counts.items())),
        "token_decision_weights": {token: dict(weights) for token, weights in sorted(token_decision_weights.items())},
        "token_rule_weights": {token: dict(weights) for token, weights in sorted(token_rule_weights.items())},
        "token_action_weights": {token: dict(weights) for token, weights in sorted(token_action_weights.items())},
        "token_teacher_decision_weights": {
            token: dict(weights) for token, weights in sorted(token_teacher_decision_weights.items())
        },
        "token_teacher_rule_weights": {
            token: dict(weights) for token, weights in sorted(token_teacher_rule_weights.items())
        },
        "token_teacher_action_weights": {
            token: dict(weights) for token, weights in sorted(token_teacher_action_weights.items())
        },
        "state_decision_weights": {state: dict(weights) for state, weights in sorted(state_decision_weights.items())},
        "state_action_weights": {state: dict(weights) for state, weights in sorted(state_action_weights.items())},
        "state_teacher_decision_weights": {
            state: dict(weights) for state, weights in sorted(state_teacher_decision_weights.items())
        },
        "state_teacher_action_weights": {
            state: dict(weights) for state, weights in sorted(state_teacher_action_weights.items())
        },
        "state_teacher_rule_weights": {
            state: dict(weights) for state, weights in sorted(state_teacher_rule_weights.items())
        },
    }


def render_policy_authz_policy_bank_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Policy Authz Self-Transmutation Bank",
        "",
        f"- Source trace bank: `{report.get('source_trace_bank', '')}`",
        f"- Rows seen: `{report.get('rows_seen', 0)}`",
        f"- Rows used: `{report.get('rows_used', 0)}`",
        f"- Minimum priority: `{report.get('min_priority', 'medium')}`",
    ]
    source_models = report.get("source_models") or {}
    if source_models:
        lines.append(f"- Source models: `{json.dumps(source_models, sort_keys=True)}`")
    lines.extend(["", "## Token priors", ""])
    for token in sorted((report.get("token_counts") or {}).keys())[:24]:
        decisions = _top_weighted(report.get("token_decision_weights", {}).get(token, {}), limit=2)
        rules = _top_weighted(report.get("token_rule_weights", {}).get(token, {}), limit=3)
        actions = _top_weighted(report.get("token_action_weights", {}).get(token, {}), limit=3)
        lines.append(
            f"- `{token}` decisions=`{', '.join(decisions)}` rules=`{', '.join(rules)}` actions=`{', '.join(actions)}`"
        )
    state_primitives = report.get("state_primitive_counts") or {}
    if state_primitives:
        lines.extend(["", "## Primitive priors", ""])
        for primitive in sorted(state_primitives.keys())[:16]:
            decisions = _top_weighted(report.get("state_decision_weights", {}).get(primitive, {}), limit=2)
            teacher_decisions = _top_weighted(report.get("state_teacher_decision_weights", {}).get(primitive, {}), limit=2)
            teacher_rules = _top_weighted(report.get("state_teacher_rule_weights", {}).get(primitive, {}), limit=2)
            lines.append(
                f"- `{primitive}` decisions=`{', '.join(decisions)}` teacher_rescue_decisions=`{', '.join(teacher_decisions)}` teacher_rules=`{', '.join(teacher_rules)}`"
            )
    return "\n".join(lines).strip() + "\n"


def load_policy_authz_policy_bank(*, repo_root: str = "", explicit_path: str = "") -> dict[str, Any]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    if os.environ.get("MEMLA_POLICY_AUTHZ_BANK_PATH"):
        candidates.append(Path(os.environ["MEMLA_POLICY_AUTHZ_BANK_PATH"]))
    if repo_root:
        candidates.append(Path(repo_root) / ".memla" / "policy_authz_policy_bank.json")
    for candidate in candidates:
        try:
            target = candidate.resolve()
        except OSError:
            continue
        if not target.exists():
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _score_from_tokens(tokens: list[str], mapping: dict[str, dict[str, float]]) -> dict[str, float]:
    scores: dict[str, float] = defaultdict(float)
    for token in tokens:
        for item, weight in dict(mapping.get(token, {})).items():
            scores[str(item)] += float(weight)
    return dict(scores)


def _merge_scores(*score_maps: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = defaultdict(float)
    for score_map in score_maps:
        for item, weight in dict(score_map).items():
            merged[str(item)] += float(weight)
    return dict(merged)


def suggest_policy_authz_priors(
    *,
    prompt: str,
    actual_rule_hits: list[str] | None = None,
    repo_root: str = "",
    bank: dict[str, Any] | None = None,
    explicit_path: str = "",
) -> dict[str, Any]:
    policy_bank = bank or load_policy_authz_policy_bank(repo_root=repo_root, explicit_path=explicit_path)
    tokens = _tokenize_prompt(prompt)
    state_primitives = _policy_state_primitives(list(actual_rule_hits or []))
    if not policy_bank:
        return {
            "matched_tokens": [],
            "state_primitives": state_primitives,
            "decisions": [],
            "rules": [],
            "actions": [],
            "primitive_decisions": [],
            "primitive_actions": [],
            "teacher_rescue_decisions": [],
            "teacher_rescue_rules": [],
            "teacher_rescue_actions": [],
        }
    if not tokens and not state_primitives:
        return {
            "matched_tokens": [],
            "state_primitives": [],
            "decisions": [],
            "rules": [],
            "actions": [],
            "primitive_decisions": [],
            "primitive_actions": [],
            "teacher_rescue_decisions": [],
            "teacher_rescue_rules": [],
            "teacher_rescue_actions": [],
        }
    matched_tokens = [token for token in tokens if token in set(policy_bank.get("token_counts", {}).keys())]
    decision_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_decision_weights") or {}))
    rule_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_rule_weights") or {}))
    action_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_action_weights") or {}))
    teacher_decision_scores = _score_from_tokens(
        matched_tokens,
        dict(policy_bank.get("token_teacher_decision_weights") or {}),
    )
    teacher_rule_scores = _score_from_tokens(
        matched_tokens,
        dict(policy_bank.get("token_teacher_rule_weights") or {}),
    )
    teacher_action_scores = _score_from_tokens(
        matched_tokens,
        dict(policy_bank.get("token_teacher_action_weights") or {}),
    )
    state_decision_scores = _score_from_tokens(
        state_primitives,
        dict(policy_bank.get("state_decision_weights") or {}),
    )
    state_action_scores = _score_from_tokens(
        state_primitives,
        dict(policy_bank.get("state_action_weights") or {}),
    )
    state_teacher_decision_scores = _score_from_tokens(
        state_primitives,
        dict(policy_bank.get("state_teacher_decision_weights") or {}),
    )
    state_teacher_action_scores = _score_from_tokens(
        state_primitives,
        dict(policy_bank.get("state_teacher_action_weights") or {}),
    )
    state_teacher_rule_scores = _score_from_tokens(
        state_primitives,
        dict(policy_bank.get("state_teacher_rule_weights") or {}),
    )
    return {
        "matched_tokens": matched_tokens,
        "state_primitives": state_primitives,
        "decisions": _top_weighted(decision_scores, limit=2),
        "rules": _top_weighted(rule_scores, limit=4),
        "actions": _top_weighted(action_scores, limit=4),
        "primitive_decisions": _top_weighted(state_decision_scores, limit=2),
        "primitive_actions": _top_weighted(state_action_scores, limit=4),
        "teacher_rescue_decisions": _top_weighted(
            _merge_scores(teacher_decision_scores, state_teacher_decision_scores),
            limit=2,
        ),
        "teacher_rescue_rules": _top_weighted(
            _merge_scores(teacher_rule_scores, state_teacher_rule_scores),
            limit=4,
        ),
        "teacher_rescue_actions": _top_weighted(
            _merge_scores(teacher_action_scores, state_teacher_action_scores),
            limit=4,
        ),
    }
