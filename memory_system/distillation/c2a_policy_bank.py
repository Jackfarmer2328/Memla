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
    "from",
    "that",
    "this",
    "into",
    "inside",
    "like",
    "tool",
    "repo",
    "repository",
    "bounded",
    "memla",
    "coding",
}
_PRIORITY_WEIGHTS = {"low": 0.45, "medium": 1.0, "high": 1.35}


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
        rows = [
            json.loads(line)
            for line in target.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return {"rows": rows}
    payload = json.loads(target.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload
    raise ValueError(f"Unsupported trace bank format: {target}")


def _top_weighted(items: dict[str, float], *, limit: int) -> list[str]:
    ranked = sorted(
        ((name, weight) for name, weight in items.items() if str(name).strip() and float(weight) > 0.0),
        key=lambda item: (float(item[1]), len(str(item[0])), str(item[0]).lower()),
        reverse=True,
    )
    return [name for name, _ in ranked[: max(int(limit), 0)]]


def distill_c2a_policy_bank(*, trace_bank_path: str, min_priority: str = "medium") -> dict[str, Any]:
    payload = _read_trace_bank(trace_bank_path)
    rows = list(payload.get("rows") or [])
    min_rank = {"low": 0, "medium": 1, "high": 2}.get(str(min_priority or "medium").lower(), 1)

    token_constraint_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_role_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_transmutation_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_file_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_region_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_teacher_constraint_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_teacher_transmutation_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_counts: Counter[str] = Counter()
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
        raw_utility = float(row.get("raw_c2a_utility", 0.0))
        memla_utility = float(row.get("memla_c2a_utility", 0.0))
        utility_delta = max(float(row.get("utility_delta", 0.0)), 0.0)
        weight = _priority_weight(priority) * (1.0 + utility_delta + (0.35 if winner == "memla" else 0.0))
        if winner == "tie":
            weight *= 0.85

        memla_constraints = _normalize(list(row.get("memla_predicted_constraints") or []))
        memla_roles = _normalize(list(row.get("memla_role_targets") or []))
        memla_transmutations = _normalize(list(row.get("memla_predicted_transmutations") or []))
        memla_files = _normalize(
            list(row.get("memla_expected_file_hits") or []) or list(row.get("memla_likely_files") or [])[:4]
        )
        memla_regions = _normalize(
            list(row.get("memla_expected_region_hits") or []) or list(row.get("memla_selected_regions") or [])[:4]
        )
        teacher_constraints = _normalize(
            list(row.get("teacher_unique_constraints") or []) or list(row.get("raw_predicted_constraints") or [])[:3]
        )
        teacher_transmutations = _normalize(
            list(row.get("teacher_unique_transmutations") or []) or list(row.get("raw_predicted_transmutations") or [])[:3]
        )

        teacher_weight = _priority_weight(priority) * (0.3 + min(raw_utility, 0.4))
        if "format_constrained" in str(row.get("teacher_signal_class") or ""):
            teacher_weight *= 0.85
        if winner == "raw":
            teacher_weight *= 1.25

        for token in tokens:
            token_counts[token] += 1
            for item in memla_constraints:
                token_constraint_weights[token][item] += weight
            for item in memla_roles:
                token_role_weights[token][item] += weight
            for item in memla_transmutations:
                token_transmutation_weights[token][item] += weight
            for item in memla_files:
                token_file_weights[token][item] += weight
            for item in memla_regions:
                token_region_weights[token][item] += weight
            for item in teacher_constraints:
                token_teacher_constraint_weights[token][item] += teacher_weight
            for item in teacher_transmutations:
                token_teacher_transmutation_weights[token][item] += teacher_weight

    return {
        "generated_ts": int(time.time()),
        "source_trace_bank": str(Path(trace_bank_path).resolve()),
        "rows_seen": len(rows),
        "rows_used": kept_rows,
        "min_priority": min_priority,
        "source_models": dict(sorted(source_models.items())),
        "token_counts": dict(sorted(token_counts.items())),
        "token_constraint_weights": {token: dict(weights) for token, weights in sorted(token_constraint_weights.items())},
        "token_role_weights": {token: dict(weights) for token, weights in sorted(token_role_weights.items())},
        "token_transmutation_weights": {token: dict(weights) for token, weights in sorted(token_transmutation_weights.items())},
        "token_file_weights": {token: dict(weights) for token, weights in sorted(token_file_weights.items())},
        "token_region_weights": {token: dict(weights) for token, weights in sorted(token_region_weights.items())},
        "token_teacher_constraint_weights": {
            token: dict(weights) for token, weights in sorted(token_teacher_constraint_weights.items())
        },
        "token_teacher_transmutation_weights": {
            token: dict(weights) for token, weights in sorted(token_teacher_transmutation_weights.items())
        },
    }


def render_c2a_policy_bank_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# C2A Self-Transmutation Policy Bank",
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
        constraints = _top_weighted(report.get("token_constraint_weights", {}).get(token, {}), limit=3)
        roles = _top_weighted(report.get("token_role_weights", {}).get(token, {}), limit=3)
        transmutations = _top_weighted(report.get("token_transmutation_weights", {}).get(token, {}), limit=2)
        lines.append(
            f"- `{token}` constraints=`{', '.join(constraints)}` roles=`{', '.join(roles)}` transmutations=`{', '.join(transmutations)}`"
        )
    return "\n".join(lines).strip() + "\n"


def load_c2a_policy_bank(*, repo_root: str = "", explicit_path: str = "") -> dict[str, Any]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    if os.environ.get("MEMLA_C2A_POLICY_PATH"):
        candidates.append(Path(os.environ["MEMLA_C2A_POLICY_PATH"]))
    if repo_root:
        candidates.append(Path(repo_root) / ".memla" / "c2a_policy_bank.json")
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


def suggest_c2a_policy_priors(
    *,
    prompt: str,
    repo_root: str = "",
    bank: dict[str, Any] | None = None,
    explicit_path: str = "",
) -> dict[str, Any]:
    policy_bank = bank or load_c2a_policy_bank(repo_root=repo_root, explicit_path=explicit_path)
    if not policy_bank:
        return {
            "matched_tokens": [],
            "constraints": [],
            "roles": [],
            "transmutations": [],
            "preferred_files": [],
            "preferred_regions": [],
            "teacher_rescue_constraints": [],
            "teacher_rescue_transmutations": [],
        }
    tokens = _tokenize_prompt(prompt)
    if not tokens:
        return {
            "matched_tokens": [],
            "constraints": [],
            "roles": [],
            "transmutations": [],
            "preferred_files": [],
            "preferred_regions": [],
            "teacher_rescue_constraints": [],
            "teacher_rescue_transmutations": [],
        }
    matched_tokens = [token for token in tokens if token in set(policy_bank.get("token_counts", {}).keys())]
    constraint_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_constraint_weights") or {}))
    role_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_role_weights") or {}))
    transmutation_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_transmutation_weights") or {}))
    file_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_file_weights") or {}))
    region_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_region_weights") or {}))
    teacher_constraint_scores = _score_from_tokens(
        matched_tokens,
        dict(policy_bank.get("token_teacher_constraint_weights") or {}),
    )
    teacher_transmutation_scores = _score_from_tokens(
        matched_tokens,
        dict(policy_bank.get("token_teacher_transmutation_weights") or {}),
    )

    preferred_files = _top_weighted(file_scores, limit=6)
    if repo_root:
        repo = Path(repo_root)
        preferred_files = [path for path in preferred_files if (repo / path).exists()]

    return {
        "matched_tokens": matched_tokens,
        "constraints": _top_weighted(constraint_scores, limit=4),
        "roles": _top_weighted(role_scores, limit=4),
        "transmutations": _top_weighted(transmutation_scores, limit=4),
        "preferred_files": preferred_files[:6],
        "preferred_regions": _top_weighted(region_scores, limit=4),
        "teacher_rescue_constraints": _top_weighted(teacher_constraint_scores, limit=3),
        "teacher_rescue_transmutations": _top_weighted(teacher_transmutation_scores, limit=3),
    }
