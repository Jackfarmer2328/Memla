from __future__ import annotations

from collections import Counter
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


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


def _winner(raw_utility: float, memla_utility: float, *, epsilon: float = 0.05) -> str:
    if memla_utility > raw_utility + epsilon:
        return "memla"
    if raw_utility > memla_utility + epsilon:
        return "raw"
    return "tie"


def _left_only(left: list[str], right: list[str]) -> list[str]:
    right_keys = {item.lower() for item in _normalize(right)}
    return [item for item in _normalize(left) if item.lower() not in right_keys]


def _shared(left: list[str], right: list[str]) -> list[str]:
    right_keys = {item.lower() for item in _normalize(right)}
    return [item for item in _normalize(left) if item.lower() in right_keys]


def _teacher_signal_class(*, row: dict[str, Any], winner: str) -> str:
    raw_utility = float(row.get("raw_policy_utility", 0.0))
    raw_parse_mode = str((row.get("raw_iteration_trace") or [{}])[0].get("parse_mode") or "json")
    if raw_utility <= 0.0:
        return "teacher_no_signal"
    if winner == "raw":
        return "teacher_advantage"
    if winner == "tie":
        return "teacher_shared_signal"
    if raw_parse_mode != "json":
        return "teacher_partial_signal_format_constrained"
    return "teacher_partial_signal"


def _teaching_priority(*, row: dict[str, Any], winner: str, signal_class: str) -> str:
    if signal_class == "teacher_no_signal":
        return "low"
    if winner == "raw":
        return "high"
    raw_utility = float(row.get("raw_policy_utility", 0.0))
    if signal_class == "teacher_shared_signal" or raw_utility >= 0.9:
        return "high"
    return "medium"


def _dominant_advantage_axes(row: dict[str, Any]) -> list[str]:
    deltas = {
        "outcome_selection": float(row.get("memla_outcome_match", 0.0)) - float(row.get("raw_outcome_match", 0.0)),
        "rule_targeting": float(row.get("memla_rule_recall", 0.0)) - float(row.get("raw_rule_recall", 0.0)),
        "action_targeting": float(row.get("memla_action_recall", 0.0)) - float(row.get("raw_action_recall", 0.0)),
        "rewrite_quality": float(row.get("memla_rewrite_recall", 0.0)) - float(row.get("raw_rewrite_recall", 0.0)),
    }
    axes = [axis for axis, delta in deltas.items() if delta >= 0.15]
    if axes:
        return axes
    best_axis = max(deltas.items(), key=lambda item: item[1])[0]
    return [best_axis] if deltas[best_axis] > 0 else []


@dataclass(frozen=True)
class ExtractedPolicyTraceRow:
    source_report: str
    source_case_index: int
    prompt: str
    raw_model: str
    memla_model: str
    raw_provider: str
    memla_provider: str
    expected_outcome: str
    expected_rule_hits: list[str]
    expected_actions: list[str]
    actual_rule_hits: list[str]
    raw_decision: str
    raw_rule_hits: list[str]
    raw_actions: list[str]
    raw_rewrite: dict[str, Any]
    raw_final_status: str
    raw_parse_mode: str
    raw_rationale: str
    raw_policy_utility: float
    memla_decision: str
    memla_rule_hits: list[str]
    memla_actions: list[str]
    memla_rewrite: dict[str, Any]
    memla_final_status: str
    memla_parse_mode: str
    memla_rationale: str
    memla_policy_utility: float
    shared_rule_hits: list[str]
    teacher_unique_rule_hits: list[str]
    memla_unique_rule_hits: list[str]
    shared_actions: list[str]
    teacher_unique_actions: list[str]
    memla_unique_actions: list[str]
    utility_delta: float
    winner: str
    teacher_signal_class: str
    teaching_priority: str
    dominant_advantage_axes: list[str]


def extract_policy_trace_bank(*, report_paths: list[str], min_utility_delta: float | None = None) -> dict[str, Any]:
    traces: list[ExtractedPolicyTraceRow] = []
    report_count = 0
    skipped_rows = 0

    for raw_path in report_paths:
        report_path = Path(raw_path).resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_count += 1
        for index, row in enumerate(report.get("rows", []), start=1):
            winner = _winner(float(row.get("raw_policy_utility", 0.0)), float(row.get("memla_policy_utility", 0.0)))
            utility_delta = round(float(row.get("utility_delta", 0.0)), 4)
            if min_utility_delta is not None and utility_delta < float(min_utility_delta):
                skipped_rows += 1
                continue
            raw_trace = list(row.get("raw_iteration_trace") or [])
            memla_trace = list(row.get("memla_iteration_trace") or [])
            raw_first = dict(raw_trace[0]) if raw_trace else {}
            memla_first = dict(memla_trace[0]) if memla_trace else {}
            signal_class = _teacher_signal_class(row=row, winner=winner)
            traces.append(
                ExtractedPolicyTraceRow(
                    source_report=str(report_path),
                    source_case_index=index,
                    prompt=str(row.get("prompt") or ""),
                    raw_model=str(report.get("raw_model") or ""),
                    memla_model=str(report.get("memla_model") or ""),
                    raw_provider=str(report.get("raw_provider") or ""),
                    memla_provider=str(report.get("memla_provider") or ""),
                    expected_outcome=str(row.get("expected_outcome") or ""),
                    expected_rule_hits=list(row.get("expected_rule_hits") or []),
                    expected_actions=list(row.get("expected_actions") or []),
                    actual_rule_hits=list(row.get("actual_rule_hits") or []),
                    raw_decision=str(row.get("raw_decision") or ""),
                    raw_rule_hits=list(row.get("raw_predicted_rule_hits") or []),
                    raw_actions=list(row.get("raw_next_actions") or []),
                    raw_rewrite=dict(row.get("raw_rewrite") or {}),
                    raw_final_status=str(row.get("raw_final_status") or ""),
                    raw_parse_mode=str(raw_first.get("parse_mode") or "json"),
                    raw_rationale=str(raw_first.get("rationale") or ""),
                    raw_policy_utility=round(float(row.get("raw_policy_utility", 0.0)), 4),
                    memla_decision=str(row.get("memla_decision") or ""),
                    memla_rule_hits=list(row.get("memla_predicted_rule_hits") or []),
                    memla_actions=list(row.get("memla_next_actions") or []),
                    memla_rewrite=dict(row.get("memla_rewrite") or {}),
                    memla_final_status=str(row.get("memla_final_status") or ""),
                    memla_parse_mode=str(memla_first.get("parse_mode") or "json"),
                    memla_rationale=str(memla_first.get("rationale") or ""),
                    memla_policy_utility=round(float(row.get("memla_policy_utility", 0.0)), 4),
                    shared_rule_hits=_shared(list(row.get("raw_predicted_rule_hits") or []), list(row.get("memla_predicted_rule_hits") or [])),
                    teacher_unique_rule_hits=_left_only(list(row.get("raw_predicted_rule_hits") or []), list(row.get("memla_predicted_rule_hits") or [])),
                    memla_unique_rule_hits=_left_only(list(row.get("memla_predicted_rule_hits") or []), list(row.get("raw_predicted_rule_hits") or [])),
                    shared_actions=_shared(list(row.get("raw_next_actions") or []), list(row.get("memla_next_actions") or [])),
                    teacher_unique_actions=_left_only(list(row.get("raw_next_actions") or []), list(row.get("memla_next_actions") or [])),
                    memla_unique_actions=_left_only(list(row.get("memla_next_actions") or []), list(row.get("raw_next_actions") or [])),
                    utility_delta=utility_delta,
                    winner=winner,
                    teacher_signal_class=signal_class,
                    teaching_priority=_teaching_priority(row=row, winner=winner, signal_class=signal_class),
                    dominant_advantage_axes=_dominant_advantage_axes(row),
                )
            )

    winner_counts = Counter(trace.winner for trace in traces)
    signal_counts = Counter(trace.teacher_signal_class for trace in traces)
    priority_counts = Counter(trace.teaching_priority for trace in traces)
    raw_model_counts = Counter(trace.raw_model for trace in traces)

    return {
        "generated_ts": int(time.time()),
        "reports_ingested": report_count,
        "input_reports": [str(Path(path).resolve()) for path in report_paths],
        "rows_extracted": len(traces),
        "rows_skipped_by_delta": skipped_rows,
        "min_utility_delta": min_utility_delta,
        "raw_models": sorted(raw_model_counts),
        "winner_counts": dict(sorted(winner_counts.items())),
        "teacher_signal_class_counts": dict(sorted(signal_counts.items())),
        "teaching_priority_counts": dict(sorted(priority_counts.items())),
        "rows_by_raw_model": dict(sorted(raw_model_counts.items())),
        "rows": [asdict(trace) for trace in traces],
    }


def render_policy_trace_bank_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Policy Authz Trace Bank",
        "",
        f"- Reports ingested: `{report.get('reports_ingested', 0)}`",
        f"- Rows extracted: `{report.get('rows_extracted', 0)}`",
        f"- Winner counts: `{json.dumps(report.get('winner_counts', {}), sort_keys=True)}`",
        f"- Teacher signal classes: `{json.dumps(report.get('teacher_signal_class_counts', {}), sort_keys=True)}`",
        f"- Teaching priority: `{json.dumps(report.get('teaching_priority_counts', {}), sort_keys=True)}`",
        "",
        "## Extracted rows",
        "",
    ]
    for row in report.get("rows", []):
        lines.extend(
            [
                f"### {row.get('raw_model', 'unknown')} :: case {row.get('source_case_index', 0)}",
                "",
                f"- Prompt: `{row.get('prompt', '')}`",
                f"- Winner: `{row.get('winner', 'tie')}`",
                f"- Teacher signal class: `{row.get('teacher_signal_class', 'teacher_no_signal')}`",
                f"- Teaching priority: `{row.get('teaching_priority', 'low')}`",
                f"- Raw decision/actions: `{row.get('raw_decision', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                f"- Memla decision/actions: `{row.get('memla_decision', '')}` / `{', '.join(row.get('memla_actions', []))}`",
                f"- Raw utility: `{row.get('raw_policy_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_policy_utility', 0.0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
