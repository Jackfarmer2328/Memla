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
    "today",
    "latest",
    "news",
    "weather",
    "web",
    "memla",
    "source",
    "sources",
    "answer",
}
_SLICE_PREFIX = "slice:"


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


def _classify_web_behaviors(texts: list[str]) -> list[str]:
    joined = " ".join(" ".join(str(text or "").split()) for text in texts if str(text or "").strip()).lower()
    if not joined:
        return []
    behaviors: list[str] = []
    if re.search(r"\bextract|specific|concrete|detail|summarize any available information|available news detail|specific mention\b", joined):
        behaviors.append("extract_concrete_detail")
    if re.search(r"\brecommend|suggest|visit|next step|actionable|helpful suggestion|alternative way|find current|where users can find|specific resource\b", joined):
        behaviors.append("offer_actionable_next_step")
    if re.search(r"\bsource|link|visit|check .* directly|weather\.com|directly at the link\b", joined):
        behaviors.append("direct_to_found_source")
    if re.search(r"\blimitation|honesty|honest|transparency|acknowledg|maintains honesty|plainly\b", joined):
        behaviors.append("acknowledge_limits_plainly")
    if re.search(r"\bdirect|plainly|first sentence|fact directly|state the fact\b", joined):
        behaviors.append("tight_direct_answer")
    if re.search(r"\bpage covers|page description|website navigation|headers rather than|seo\b", joined):
        behaviors.append("avoid_page_description")
    if re.search(r"\bderived_age_at_event|compute[_\s-]?age|birth_year|event_year|computed_age\b", joined):
        behaviors.append("compute_derived_fact")
    if re.search(r"\bweather_precipitation|precipitation_chance|rain_condition|forecast\b", joined):
        behaviors.append("extract_weather_fact")
    if re.search(r"\brole_holder|creator_identity|person_name|organization|creator_name\b", joined):
        behaviors.append("extract_identity_fact")
    return list(dict.fromkeys(behaviors))


def _top_weighted(items: dict[str, float], *, limit: int) -> list[str]:
    ranked = sorted(
        ((name, weight) for name, weight in items.items() if str(name).strip() and float(weight) > 0.0),
        key=lambda item: (float(item[1]), len(str(item[0])), str(item[0]).lower()),
        reverse=True,
    )
    return [name for name, _ in ranked[: max(int(limit), 0)]]


def distill_web_policy_bank(*, trace_bank_path: str, min_improvement: float = 0.0) -> dict[str, Any]:
    payload = _read_trace_bank(trace_bank_path)
    rows = list(payload.get("rows") or [])

    token_behavior_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    token_note_weights: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    behavior_examples: dict[str, list[str]] = defaultdict(list)
    token_counts: Counter[str] = Counter()
    slice_counts: Counter[str] = Counter()
    kept_rows = 0

    for row in rows:
        improvement = float(row.get("improvement_delta") or 0.0)
        if improvement < float(min_improvement):
            continue
        prompt = str(row.get("prompt") or "").strip()
        slice_kind = str(row.get("slice") or "").strip().lower() or "general"
        coaching = str(row.get("teacher_coaching") or "").strip()
        why_better = str(row.get("rescue_why_better") or "").strip()
        promotion_notes = [str(item).strip() for item in list(row.get("promotion_notes") or []) if str(item).strip()]
        question_type = str(row.get("question_type") or "").strip()
        needed_fields = [str(item).strip() for item in list(row.get("needed_fields") or []) if str(item).strip()]
        extracted_facts = [
            str(item).strip()
            for item in [
                *list(row.get("baseline_extracted_facts") or []),
                *list(row.get("rescued_extracted_facts") or []),
            ]
            if str(item).strip()
        ]
        behaviors = _classify_web_behaviors([coaching, why_better, question_type, *needed_fields, *promotion_notes, *extracted_facts])
        if not prompt or not behaviors:
            continue
        kept_rows += 1
        slice_counts[slice_kind] += 1
        tokens = _tokenize_prompt(prompt)
        slice_token = f"{_SLICE_PREFIX}{slice_kind}"
        weight = 1.0 + max(improvement, 0.0)
        if str(row.get("promoted_lane") or "").strip() == "teacher_rescue":
            weight += 0.25
        note_candidates = [coaching, why_better, *promotion_notes]
        normalized_notes = [" ".join(note.split()) for note in note_candidates if note.strip()]

        for behavior in behaviors:
            if len(behavior_examples[behavior]) < 3:
                example = next((note for note in normalized_notes if note), "")
                if example and example not in behavior_examples[behavior]:
                    behavior_examples[behavior].append(example)

        for token in tokens + [slice_token]:
            token_counts[token] += 1
            for behavior in behaviors:
                token_behavior_weights[token][behavior] += weight
            for note in normalized_notes[:3]:
                token_note_weights[token][note] += weight * 0.5

    return {
        "generated_ts": int(time.time()),
        "source_trace_bank": str(Path(trace_bank_path).resolve()),
        "rows_seen": len(rows),
        "rows_used": kept_rows,
        "min_improvement": float(min_improvement),
        "token_counts": dict(sorted(token_counts.items())),
        "slice_counts": dict(sorted(slice_counts.items())),
        "token_behavior_weights": {token: dict(weights) for token, weights in sorted(token_behavior_weights.items())},
        "token_note_weights": {token: dict(weights) for token, weights in sorted(token_note_weights.items())},
        "behavior_examples": {name: list(values) for name, values in sorted(behavior_examples.items())},
    }


def render_web_policy_bank_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Web Self-Transmutation Policy Bank",
        "",
        f"- Source trace bank: `{report.get('source_trace_bank', '')}`",
        f"- Rows seen: `{report.get('rows_seen', 0)}`",
        f"- Rows used: `{report.get('rows_used', 0)}`",
        f"- Minimum improvement: `{report.get('min_improvement', 0.0)}`",
    ]
    if report.get("slice_counts"):
        lines.append(f"- Slice counts: `{json.dumps(report.get('slice_counts', {}), sort_keys=True)}`")
    lines.extend(["", "## Token priors", ""])
    token_counts = report.get("token_counts") or {}
    for token in sorted(token_counts.keys())[:24]:
        behaviors = _top_weighted(dict(report.get("token_behavior_weights", {}).get(token, {})), limit=4)
        notes = _top_weighted(dict(report.get("token_note_weights", {}).get(token, {})), limit=2)
        lines.append(f"- `{token}` behaviors=`{', '.join(behaviors)}` notes=`{'; '.join(notes)}`")
    examples = report.get("behavior_examples") or {}
    if examples:
        lines.extend(["", "## Behavior examples", ""])
        for behavior in sorted(examples.keys()):
            lines.append(f"- `{behavior}`: {' | '.join(examples.get(behavior, [])[:2])}")
    return "\n".join(lines).strip() + "\n"


def load_web_policy_bank(*, repo_root: str = "", explicit_path: str = "") -> dict[str, Any]:
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    if os.environ.get("MEMLA_WEB_POLICY_PATH"):
        candidates.append(Path(os.environ["MEMLA_WEB_POLICY_PATH"]))
    if repo_root:
        candidates.append(Path(repo_root) / ".memla" / "web_policy_bank.json")
    candidates.append(Path.cwd() / ".memla" / "web_policy_bank.json")
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


def suggest_web_policy_priors(
    *,
    prompt: str,
    query: str = "",
    slice_kind: str = "",
    repo_root: str = "",
    bank: dict[str, Any] | None = None,
    explicit_path: str = "",
) -> dict[str, Any]:
    policy_bank = bank or load_web_policy_bank(repo_root=repo_root, explicit_path=explicit_path)
    target_slice = str(slice_kind or "").strip().lower()
    tokens = _tokenize_prompt(" ".join(part for part in [prompt, query] if str(part).strip()))
    if target_slice:
        tokens.append(f"{_SLICE_PREFIX}{target_slice}")
    if not policy_bank or not tokens:
        return {
            "matched_tokens": [],
            "behaviors": [],
            "teacher_notes": [],
        }
    matched_tokens = [token for token in tokens if token in set(policy_bank.get("token_counts", {}).keys())]
    behavior_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_behavior_weights") or {}))
    note_scores = _score_from_tokens(matched_tokens, dict(policy_bank.get("token_note_weights") or {}))
    return {
        "matched_tokens": matched_tokens,
        "behaviors": _top_weighted(behavior_scores, limit=5),
        "teacher_notes": _top_weighted(note_scores, limit=3),
    }


__all__ = [
    "distill_web_policy_bank",
    "render_web_policy_bank_markdown",
    "load_web_policy_bank",
    "suggest_web_policy_priors",
]
