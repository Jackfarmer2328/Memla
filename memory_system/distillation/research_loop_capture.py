from __future__ import annotations

import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


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


def convert_research_loop_events_to_cases(
    *,
    events_path: str,
    out_cases_path: str,
    min_iterations: int = 1,
) -> dict[str, Any]:
    events_file = Path(events_path).resolve()
    out_file = Path(out_cases_path).resolve()
    out_file.parent.mkdir(parents=True, exist_ok=True)

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_events = 0
    for line in events_file.read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        total_events += 1
        session_id = _normalize_text(str(row.get("session_id") or "")) or f"session_{total_events}"
        grouped[session_id].append(row)

    converted_rows: list[dict[str, Any]] = []
    skipped_sessions = 0
    for session_id, rows in grouped.items():
        ordered = sorted(rows, key=lambda item: _to_int(item.get("step_index"), 0))
        if len(ordered) < max(int(min_iterations), 1):
            skipped_sessions += 1
            continue

        first = ordered[0]
        last = ordered[-1]
        loop_steps: list[dict[str, Any]] = []
        for index, row in enumerate(ordered, start=1):
            known_facts = _normalize_list(list(row.get("known_facts") or []))
            open_gaps = _normalize_list(list(row.get("open_gaps") or []))
            contradictions, contradiction_records = _normalize_contradictions(
                list(row.get("contradictions") or []),
                contradiction_records=list(row.get("contradiction_records") or []),
            )
            normalized_docs = _normalize_docs(list(row.get("latest_docs") or []))

            action = _normalize_text(str(row.get("gold_action") or row.get("decision_action") or "search_more"))
            if action not in {"search_more", "converge"}:
                action = "search_more"
            loop_steps.append(
                {
                    "step_index": _to_int(row.get("step_index"), index),
                    "known_facts": known_facts,
                    "open_gaps": open_gaps,
                    "contradictions": contradictions,
                    "contradiction_records": contradiction_records,
                    "latest_docs": normalized_docs,
                    "context_tokens_so_far": _to_int(
                        _get_first(row, "context_tokens_so_far", "context_tokens_so_far_estimate", default=0),
                        0,
                    ),
                    "new_docs_tokens": _to_int(
                        _get_first(row, "new_docs_tokens", "new_docs_tokens_estimate", default=0),
                        0,
                    ),
                    "gold_action": action,
                    "gold_query_intent": _normalize_text(str(row.get("gold_query_intent") or row.get("query_intent") or "")),
                    "tokens_if_search_more": _to_int(
                        _get_first(row, "tokens_if_search_more", "tokens_if_search_more_estimate", default=2500),
                        2500,
                    ),
                    "tokens_if_converge": _to_int(
                        _get_first(row, "tokens_if_converge", "tokens_if_converge_estimate", default=350),
                        350,
                    ),
                    "estimated_output_tokens": _to_int(
                        _get_first(row, "estimated_output_tokens", "estimated_output_tokens_estimate", default=180),
                        180,
                    ),
                    "quality_passed": _to_bool(row.get("quality_passed"), True),
                    "frontier_reference_action": _normalize_text(
                        str(
                            _get_first(
                                row,
                                "frontier_reference_action",
                                "frontier_action",
                                "baseline_action",
                                "production_action",
                                default="",
                            )
                            or ""
                        )
                    ),
                    "frontier_reference_query_intent": _normalize_text(
                        str(
                            _get_first(
                                row,
                                "frontier_reference_query_intent",
                                "frontier_query_intent",
                                "baseline_query_intent",
                                "production_query_intent",
                                default="",
                            )
                            or ""
                        )
                    ),
                    "frontier_reference_next_query": _normalize_text(
                        str(
                            _get_first(
                                row,
                                "frontier_reference_next_query",
                                "frontier_next_query",
                                "baseline_next_query",
                                "production_next_query",
                                default="",
                            )
                            or ""
                        )
                    ),
                    "frontier_reference_rationale": _normalize_text(
                        str(
                            _get_first(
                                row,
                                "frontier_reference_rationale",
                                "frontier_rationale",
                                "baseline_rationale",
                                "production_rationale",
                                default="",
                            )
                            or ""
                        )
                    ),
                }
            )

        converted_rows.append(
            {
                "session_id": session_id,
                "prompt": _normalize_text(str(first.get("prompt") or first.get("user_goal") or "")),
                "user_goal": _normalize_text(str(first.get("user_goal") or first.get("prompt") or "")),
                "quality_passed": _to_bool(last.get("quality_passed"), _to_bool(first.get("quality_passed"), True)),
                "loop_steps": loop_steps,
            }
        )

    lines = [json.dumps(row, ensure_ascii=False) for row in converted_rows]
    out_file.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return {
        "generated_ts": int(time.time()),
        "events_path": str(events_file),
        "out_cases_path": str(out_file),
        "sessions_seen": len(grouped),
        "sessions_written": len(converted_rows),
        "sessions_skipped": skipped_sessions,
        "events_seen": total_events,
    }
