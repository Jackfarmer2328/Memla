from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any


MEMORY_STAGE_EPISODIC = "episodic"
MEMORY_STAGE_SEMANTIC = "semantic"
MEMORY_STAGE_RULE = "rule"

MEMORY_STATUS_ACTIVE = "active"
MEMORY_STATUS_STALE = "stale"
MEMORY_STATUS_INVALID = "invalid"

MEMORY_KIND_LANGUAGE_COMPILATION = "language_compilation"
MEMORY_KIND_AUTONOMY_PREFIX = "autonomy_"
MEMORY_KIND_ACTION_PREFIX = "action_"


def load_memory_ontology(path: str | Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        return []
    ontology_path = Path(path).expanduser().resolve()
    if not ontology_path.exists():
        return []
    try:
        payload = json.loads(ontology_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def save_memory_ontology(entries: list[dict[str, Any]], path: str | Path | None = None) -> Path:
    if path is None:
        raise ValueError("path is required to save memory ontology")
    ontology_path = Path(path).expanduser().resolve()
    ontology_path.parent.mkdir(parents=True, exist_ok=True)
    clean_entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
    ontology_path.write_text(json.dumps(clean_entries, ensure_ascii=True, indent=2), encoding="utf-8")
    return ontology_path


def _coerce_context_profile(profile: dict[str, Any] | None) -> dict[str, Any]:
    payload = dict(profile or {})
    return {
        "page_kind": str(payload.get("page_kind") or "").strip(),
        "search_engine": str(payload.get("search_engine") or "").strip(),
        "has_search_results": bool(payload.get("has_search_results")),
        "has_subject": bool(payload.get("has_subject")),
        "has_evidence": bool(payload.get("has_evidence")),
    }


def _coerce_signatures(action_signatures: list[str] | None) -> list[str]:
    return [str(item).strip() for item in list(action_signatures or []) if str(item).strip()]


def _memory_key(
    *,
    memory_kind: str,
    context_profile: dict[str, Any],
    action_signatures: list[str],
) -> str:
    payload = {
        "memory_kind": str(memory_kind or "").strip(),
        "page_kind": str(context_profile.get("page_kind") or "").strip(),
        "search_engine": str(context_profile.get("search_engine") or "").strip(),
        "has_search_results": bool(context_profile.get("has_search_results")),
        "has_subject": bool(context_profile.get("has_subject")),
        "has_evidence": bool(context_profile.get("has_evidence")),
        "action_signatures": list(action_signatures),
    }
    digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
    return f"{payload['memory_kind']}:{digest[:16]}"


def _unique_extend(existing: list[str], incoming: list[str], *, limit: int) -> list[str]:
    seen = {str(item).strip() for item in existing if str(item).strip()}
    merged = [str(item).strip() for item in existing if str(item).strip()]
    for raw in incoming:
        item = str(raw).strip()
        if not item or item in seen:
            continue
        merged.append(item)
        seen.add(item)
    return merged[-limit:]


def _find_entry(
    entries: list[dict[str, Any]],
    *,
    memory_kind: str,
    context_profile: dict[str, Any],
    action_signatures: list[str],
) -> dict[str, Any] | None:
    memory_id = _memory_key(
        memory_kind=memory_kind,
        context_profile=context_profile,
        action_signatures=action_signatures,
    )
    for entry in entries:
        if str(entry.get("memory_id") or "").strip() == memory_id:
            return entry
    return None


def _initial_trust(source: str) -> float:
    normalized = str(source or "").strip()
    if normalized == "language_rule":
        return 0.92
    if normalized == "language_memory":
        return 0.72
    if normalized.startswith("autonomy_"):
        return 0.74
    if normalized.startswith("action_"):
        return 0.68
    return 0.58


def _source_counts_as_reuse(source: str) -> bool:
    normalized = str(source or "").strip()
    return (
        normalized in {"language_memory", "language_rule"}
        or normalized.startswith("autonomy_")
        or normalized.startswith("action_")
    )


def _promote_to_semantic(entry: dict[str, Any], *, now_ts: int) -> None:
    if str(entry.get("promotion_stage") or "") != MEMORY_STAGE_EPISODIC:
        return
    entry["promotion_stage"] = MEMORY_STAGE_SEMANTIC
    entry["promotion_count"] = int(entry.get("promotion_count") or 0) + 1
    entry["last_promoted_ts"] = now_ts
    transfer_scope = dict(entry.get("transfer_scope") or {})
    transfer_scope["generalized"] = True
    entry["transfer_scope"] = transfer_scope


def _promote_to_rule(entry: dict[str, Any], *, now_ts: int) -> None:
    if str(entry.get("promotion_stage") or "") != MEMORY_STAGE_RULE:
        entry["promotion_count"] = int(entry.get("promotion_count") or 0) + 1
    entry["promotion_stage"] = MEMORY_STAGE_RULE
    entry["status"] = MEMORY_STATUS_ACTIVE
    entry["trust"] = round(max(float(entry.get("trust") or 0.0), 0.92), 4)
    entry["last_promoted_ts"] = now_ts
    entry["last_adjudication"] = "promoted_rule"
    transfer_scope = dict(entry.get("transfer_scope") or {})
    transfer_scope["generalized"] = True
    transfer_scope["rule_backed"] = True
    entry["transfer_scope"] = transfer_scope


def record_memory_trace(
    *,
    prompt: str,
    normalized_prompt: str,
    tokens: list[str] | None,
    context_profile: dict[str, Any] | None,
    action_signatures: list[str] | None,
    source: str,
    path: str | Path | None,
    memory_kind: str = MEMORY_KIND_LANGUAGE_COMPILATION,
    canonical_clauses: list[str] | None = None,
    now_ts: int | None = None,
) -> Path | None:
    normalized_context = _coerce_context_profile(context_profile)
    normalized_signatures = _coerce_signatures(action_signatures)
    if path is None or not normalized_signatures:
        return None
    timestamp = int(time.time()) if now_ts is None else int(now_ts)
    entries = load_memory_ontology(path)
    entry = _find_entry(
        entries,
        memory_kind=memory_kind,
        context_profile=normalized_context,
        action_signatures=normalized_signatures,
    )
    if entry is None:
        entry = {
            "memory_id": _memory_key(
                memory_kind=memory_kind,
                context_profile=normalized_context,
                action_signatures=normalized_signatures,
            ),
            "memory_kind": memory_kind,
            "status": MEMORY_STATUS_ACTIVE,
            "promotion_stage": MEMORY_STAGE_RULE if source == "language_rule" else MEMORY_STAGE_EPISODIC,
            "origin_sources": [str(source).strip()],
            "context_profile": normalized_context,
            "transfer_scope": {
                "page_kind": normalized_context.get("page_kind"),
                "search_engine": normalized_context.get("search_engine"),
                "generalized": bool(source == "language_rule"),
                "rule_backed": bool(source == "language_rule"),
            },
            "action_signatures": list(normalized_signatures),
            "action_count": len(normalized_signatures),
            "canonical_clauses": [str(item).strip() for item in list(canonical_clauses or []) if str(item).strip()],
            "example_prompts": [str(prompt).strip()],
            "normalized_prompts": [str(normalized_prompt).strip()] if str(normalized_prompt).strip() else [],
            "tokens": sorted({str(item).strip() for item in list(tokens or []) if str(item).strip()}),
            "created_ts": timestamp,
            "freshness_ts": timestamp,
            "last_used_ts": timestamp,
            "last_promoted_ts": timestamp if source == "language_rule" else 0,
            "verifier_outcome": "validated_success",
            "observation_count": 1,
            "reuse_count": 0,
            "successful_reuse_count": 0,
            "failed_reuse_count": 0,
            "promotion_count": 1 if source == "language_rule" else 0,
            "trust": round(_initial_trust(source), 4),
            "last_adjudication": "stored",
        }
        entries.append(entry)
    else:
        entry["status"] = MEMORY_STATUS_ACTIVE
        entry["freshness_ts"] = timestamp
        entry["verifier_outcome"] = "validated_success"
        entry["observation_count"] = int(entry.get("observation_count") or 0) + 1
        entry["origin_sources"] = _unique_extend(list(entry.get("origin_sources") or []), [str(source).strip()], limit=8)
        entry["example_prompts"] = _unique_extend(list(entry.get("example_prompts") or []), [prompt], limit=8)
        entry["normalized_prompts"] = _unique_extend(
            list(entry.get("normalized_prompts") or []),
            [normalized_prompt],
            limit=12,
        )
        entry["tokens"] = sorted(
            {
                str(item).strip()
                for item in list(entry.get("tokens") or []) + list(tokens or [])
                if str(item).strip()
            }
        )
        if canonical_clauses:
            entry["canonical_clauses"] = _unique_extend(
                list(entry.get("canonical_clauses") or []),
                [str(item).strip() for item in canonical_clauses if str(item).strip()],
                limit=12,
            )
        entry["trust"] = round(max(float(entry.get("trust") or 0.0), _initial_trust(source)), 4)
        if source == "language_rule":
            _promote_to_rule(entry, now_ts=timestamp)
    return save_memory_ontology(entries, path)


def adjudicate_memory_trace(
    *,
    prompt: str,
    normalized_prompt: str,
    tokens: list[str] | None,
    context_profile: dict[str, Any] | None,
    action_signatures: list[str] | None,
    source: str,
    success: bool,
    path: str | Path | None,
    memory_kind: str = MEMORY_KIND_LANGUAGE_COMPILATION,
    canonical_clauses: list[str] | None = None,
    now_ts: int | None = None,
    semantic_threshold: int = 2,
    invalidate_threshold: int = 2,
) -> Path | None:
    normalized_context = _coerce_context_profile(context_profile)
    normalized_signatures = _coerce_signatures(action_signatures)
    if path is None or not normalized_signatures:
        return None
    timestamp = int(time.time()) if now_ts is None else int(now_ts)
    entries = load_memory_ontology(path)
    entry = _find_entry(
        entries,
        memory_kind=memory_kind,
        context_profile=normalized_context,
        action_signatures=normalized_signatures,
    )
    if entry is None:
        if not success:
            return None
        record_memory_trace(
            prompt=prompt,
            normalized_prompt=normalized_prompt,
            tokens=tokens,
            context_profile=normalized_context,
            action_signatures=normalized_signatures,
            source=source,
            path=path,
            memory_kind=memory_kind,
            canonical_clauses=canonical_clauses,
            now_ts=timestamp,
        )
        entries = load_memory_ontology(path)
        entry = _find_entry(
            entries,
            memory_kind=memory_kind,
            context_profile=normalized_context,
            action_signatures=normalized_signatures,
        )
        if entry is None:
            return None
    entry["example_prompts"] = _unique_extend(list(entry.get("example_prompts") or []), [prompt], limit=8)
    entry["normalized_prompts"] = _unique_extend(
        list(entry.get("normalized_prompts") or []),
        [normalized_prompt],
        limit=12,
    )
    entry["tokens"] = sorted(
        {
            str(item).strip()
            for item in list(entry.get("tokens") or []) + list(tokens or [])
            if str(item).strip()
        }
    )
    if canonical_clauses:
        entry["canonical_clauses"] = _unique_extend(
            list(entry.get("canonical_clauses") or []),
            [str(item).strip() for item in canonical_clauses if str(item).strip()],
            limit=12,
        )
    if success:
        entry["status"] = MEMORY_STATUS_ACTIVE
        entry["verifier_outcome"] = "validated_success"
        entry["freshness_ts"] = timestamp
        entry["last_used_ts"] = timestamp
        counts_as_reuse = _source_counts_as_reuse(source)
        entry["last_adjudication"] = "reuse_success" if counts_as_reuse else "validated_success"
        entry["trust"] = round(min(1.0, float(entry.get("trust") or 0.0) + (0.1 if counts_as_reuse else 0.05)), 4)
        if counts_as_reuse:
            entry["reuse_count"] = int(entry.get("reuse_count") or 0) + 1
            entry["successful_reuse_count"] = int(entry.get("successful_reuse_count") or 0) + 1
        if int(entry.get("successful_reuse_count") or 0) >= max(int(semantic_threshold), 1):
            _promote_to_semantic(entry, now_ts=timestamp)
        if source == "language_rule":
            _promote_to_rule(entry, now_ts=timestamp)
    else:
        entry["failed_reuse_count"] = int(entry.get("failed_reuse_count") or 0) + 1
        entry["verifier_outcome"] = "validated_failure"
        entry["last_adjudication"] = "reuse_failure"
        entry["trust"] = round(max(0.0, float(entry.get("trust") or 0.0) - 0.2), 4)
        if (
            int(entry.get("failed_reuse_count") or 0) >= max(int(invalidate_threshold), 1)
            and float(entry.get("trust") or 0.0) < 0.35
        ):
            entry["status"] = MEMORY_STATUS_INVALID
    return save_memory_ontology(entries, path)


def promote_memory_rule(
    *,
    prompt: str,
    normalized_prompt: str,
    tokens: list[str] | None,
    context_profile: dict[str, Any] | None,
    action_signatures: list[str] | None,
    source: str,
    path: str | Path | None,
    memory_kind: str = MEMORY_KIND_LANGUAGE_COMPILATION,
    canonical_clauses: list[str] | None = None,
    now_ts: int | None = None,
) -> Path | None:
    normalized_context = _coerce_context_profile(context_profile)
    normalized_signatures = _coerce_signatures(action_signatures)
    if path is None or not normalized_signatures:
        return None
    timestamp = int(time.time()) if now_ts is None else int(now_ts)
    record_memory_trace(
        prompt=prompt,
        normalized_prompt=normalized_prompt,
        tokens=tokens,
        context_profile=normalized_context,
        action_signatures=normalized_signatures,
        source="language_memory" if source == "language_rule" else source,
        path=path,
        memory_kind=memory_kind,
        canonical_clauses=canonical_clauses,
        now_ts=timestamp,
    )
    entries = load_memory_ontology(path)
    entry = _find_entry(
        entries,
        memory_kind=memory_kind,
        context_profile=normalized_context,
        action_signatures=normalized_signatures,
    )
    if entry is None:
        return None
    _promote_to_rule(entry, now_ts=timestamp)
    return save_memory_ontology(entries, path)


def decay_memory_traces(
    *,
    path: str | Path | None,
    now_ts: int | None = None,
    stale_after_seconds: int = 60 * 60 * 24 * 14,
) -> Path | None:
    if path is None:
        return None
    entries = load_memory_ontology(path)
    if not entries:
        return None
    timestamp = int(time.time()) if now_ts is None else int(now_ts)
    changed = False
    for entry in entries:
        if str(entry.get("status") or "") != MEMORY_STATUS_ACTIVE:
            continue
        if str(entry.get("promotion_stage") or "") == MEMORY_STAGE_RULE:
            continue
        freshness_ts = max(
            int(entry.get("freshness_ts") or 0),
            int(entry.get("last_used_ts") or 0),
            int(entry.get("created_ts") or 0),
        )
        if freshness_ts and (timestamp - freshness_ts) >= int(stale_after_seconds):
            entry["status"] = MEMORY_STATUS_STALE
            entry["trust"] = round(max(0.0, float(entry.get("trust") or 0.0) * 0.8), 4)
            entry["last_adjudication"] = "stale_decay"
            changed = True
    if not changed:
        return None
    return save_memory_ontology(entries, path)


def summarize_memory_ontology(path: str | Path | None = None) -> dict[str, Any]:
    entries = load_memory_ontology(path)
    count = len(entries)
    if count == 0:
        return {
            "memory_count": 0,
            "active_count": 0,
            "stale_count": 0,
            "invalid_count": 0,
            "episodic_count": 0,
            "semantic_count": 0,
            "rule_count": 0,
            "avg_trust": 0.0,
            "kind_counts": {},
            "stage_counts_by_kind": {},
            "status_counts_by_kind": {},
            "source_counts": {},
            "autonomy_count": 0,
            "action_count": 0,
            "language_count": 0,
        }
    kind_counts: dict[str, int] = {}
    stage_counts_by_kind: dict[str, dict[str, int]] = {}
    status_counts_by_kind: dict[str, dict[str, int]] = {}
    source_counts: dict[str, int] = {}
    for entry in entries:
        kind = str(entry.get("memory_kind") or "").strip() or "unknown"
        stage = str(entry.get("promotion_stage") or "").strip() or "unknown"
        status = str(entry.get("status") or "").strip() or "unknown"
        kind_counts[kind] = kind_counts.get(kind, 0) + 1
        stage_bucket = stage_counts_by_kind.setdefault(kind, {})
        stage_bucket[stage] = stage_bucket.get(stage, 0) + 1
        status_bucket = status_counts_by_kind.setdefault(kind, {})
        status_bucket[status] = status_bucket.get(status, 0) + 1
        for source in list(entry.get("origin_sources") or []):
            clean_source = str(source or "").strip()
            if clean_source:
                source_counts[clean_source] = source_counts.get(clean_source, 0) + 1
    return {
        "memory_count": count,
        "active_count": sum(1 for entry in entries if str(entry.get("status") or "") == MEMORY_STATUS_ACTIVE),
        "stale_count": sum(1 for entry in entries if str(entry.get("status") or "") == MEMORY_STATUS_STALE),
        "invalid_count": sum(1 for entry in entries if str(entry.get("status") or "") == MEMORY_STATUS_INVALID),
        "episodic_count": sum(1 for entry in entries if str(entry.get("promotion_stage") or "") == MEMORY_STAGE_EPISODIC),
        "semantic_count": sum(1 for entry in entries if str(entry.get("promotion_stage") or "") == MEMORY_STAGE_SEMANTIC),
        "rule_count": sum(1 for entry in entries if str(entry.get("promotion_stage") or "") == MEMORY_STAGE_RULE),
        "avg_trust": round(sum(float(entry.get("trust") or 0.0) for entry in entries) / count, 4),
        "kind_counts": kind_counts,
        "stage_counts_by_kind": stage_counts_by_kind,
        "status_counts_by_kind": status_counts_by_kind,
        "source_counts": source_counts,
        "autonomy_count": sum(1 for entry in entries if str(entry.get("memory_kind") or "").startswith(MEMORY_KIND_AUTONOMY_PREFIX)),
        "action_count": sum(1 for entry in entries if str(entry.get("memory_kind") or "").startswith(MEMORY_KIND_ACTION_PREFIX)),
        "language_count": sum(1 for entry in entries if str(entry.get("memory_kind") or "") == MEMORY_KIND_LANGUAGE_COMPILATION),
    }
