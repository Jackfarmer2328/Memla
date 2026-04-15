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


def _hits(predicted: list[str], expected: list[str]) -> list[str]:
    predicted_keys = {item.lower(): item for item in _normalize(predicted)}
    hits: list[str] = []
    seen: set[str] = set()
    for item in _normalize(expected):
        if item.lower() in predicted_keys and item.lower() not in seen:
            hits.append(item)
            seen.add(item.lower())
    return hits


def _shared(left: list[str], right: list[str]) -> list[str]:
    right_keys = {item.lower() for item in _normalize(right)}
    return [item for item in _normalize(left) if item.lower() in right_keys]


def _left_only(left: list[str], right: list[str]) -> list[str]:
    right_keys = {item.lower() for item in _normalize(right)}
    return [item for item in _normalize(left) if item.lower() not in right_keys]


def _winner(raw_utility: float, memla_utility: float, *, epsilon: float = 0.05) -> str:
    if memla_utility > raw_utility + epsilon:
        return "memla"
    if raw_utility > memla_utility + epsilon:
        return "raw"
    return "tie"


def _dominant_advantage_axes(row: dict[str, Any]) -> list[str]:
    deltas = {
        "file_targeting": float(row.get("memla_file_recall", 0.0)) - float(row.get("raw_file_recall", 0.0)),
        "command_targeting": float(row.get("memla_command_recall", 0.0)) - float(row.get("raw_command_recall", 0.0)),
        "verification_targeting": float(row.get("memla_verification_recall", 0.0)) - float(row.get("raw_verification_recall", 0.0)),
        "role_targeting": float(row.get("memla_role_recall", 0.0)) - float(row.get("raw_role_recall", 0.0)),
        "region_targeting": float(row.get("memla_region_recall", 0.0)) - float(row.get("raw_region_recall", 0.0)),
    }
    axes = [axis for axis, delta in deltas.items() if delta >= 0.15]
    if axes:
        return axes
    best_axis = max(deltas.items(), key=lambda item: item[1])[0]
    return [best_axis] if deltas[best_axis] > 0 else []


def _teacher_signal_axes(row: dict[str, Any]) -> list[str]:
    axes = {
        "file_targeting": float(row.get("raw_file_recall", 0.0)),
        "command_targeting": float(row.get("raw_command_recall", 0.0)),
        "verification_targeting": float(row.get("raw_verification_recall", 0.0)),
        "role_targeting": float(row.get("raw_role_recall", 0.0)),
        "region_targeting": float(row.get("raw_region_recall", 0.0)),
    }
    return [axis for axis, value in axes.items() if value > 0.0]


def _teacher_signal_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("raw_expected_file_hits"):
        reasons.append("expected_file_hit")
    if row.get("raw_expected_role_hits"):
        reasons.append("expected_role_hit")
    if row.get("raw_expected_region_hits"):
        reasons.append("expected_region_hit")
    if row.get("raw_likely_commands"):
        reasons.append("command_hypothesis")
    if row.get("raw_likely_tests"):
        reasons.append("verification_hypothesis")
    if row.get("raw_predicted_constraints"):
        reasons.append("constraint_hypothesis")
    if row.get("raw_predicted_transmutations"):
        reasons.append("transmutation_hypothesis")
    if str(row.get("raw_parse_mode") or "json") != "json":
        reasons.append("format_repair_needed")
    if str(row.get("raw_response_text") or "").strip() and not reasons:
        reasons.append("sparse_teacher_output")
    return reasons


def _teacher_signal_class(row: dict[str, Any]) -> str:
    raw_utility = float(row.get("raw_c2a_utility", 0.0))
    memla_utility = float(row.get("memla_c2a_utility", 0.0))
    winner = str(row.get("winner") or "tie")
    reasons = list(row.get("teacher_signal_reasons") or [])
    if raw_utility <= 0.0 and not reasons:
        return "teacher_no_signal"
    if winner == "raw":
        return "teacher_advantage"
    if winner == "tie":
        return "teacher_shared_signal"
    if raw_utility > 0.0 and str(row.get("raw_parse_mode") or "json") != "json":
        return "teacher_partial_signal_format_constrained"
    if raw_utility > 0.0 or reasons:
        return "teacher_partial_signal"
    return "teacher_no_signal"


def _teaching_priority(row: dict[str, Any]) -> str:
    signal_class = str(row.get("teacher_signal_class") or "teacher_no_signal")
    raw_utility = float(row.get("raw_c2a_utility", 0.0))
    if signal_class == "teacher_no_signal":
        return "low"
    if signal_class in {"teacher_advantage", "teacher_shared_signal"} or raw_utility >= 0.3:
        return "high"
    return "medium"


@dataclass(frozen=True)
class ExtractedC2ATraceRow:
    source_report: str
    source_case_index: int
    repo_root: str
    cases_path: str
    prompt: str
    raw_model: str
    memla_model: str
    raw_provider: str
    memla_provider: str
    expected_files: list[str]
    expected_commands: list[str]
    expected_roles: list[str]
    expected_regions: list[str]
    raw_likely_files: list[str]
    raw_likely_commands: list[str]
    raw_likely_tests: list[str]
    raw_role_targets: list[str]
    raw_predicted_constraints: list[str]
    raw_predicted_transmutations: list[str]
    raw_response_text: str
    raw_parse_mode: str
    raw_expected_file_hits: list[str]
    raw_expected_role_hits: list[str]
    raw_expected_region_hits: list[str]
    memla_likely_files: list[str]
    memla_likely_commands: list[str]
    memla_likely_tests: list[str]
    memla_role_targets: list[str]
    memla_predicted_constraints: list[str]
    memla_predicted_transmutations: list[str]
    memla_selected_regions: list[str]
    memla_expected_file_hits: list[str]
    memla_expected_role_hits: list[str]
    memla_expected_region_hits: list[str]
    shared_file_hits: list[str]
    teacher_unique_expected_file_hits: list[str]
    memla_unique_expected_file_hits: list[str]
    shared_constraints: list[str]
    teacher_unique_constraints: list[str]
    memla_unique_constraints: list[str]
    shared_transmutations: list[str]
    teacher_unique_transmutations: list[str]
    memla_unique_transmutations: list[str]
    raw_file_recall: float
    raw_command_recall: float
    raw_verification_recall: float
    raw_role_recall: float
    raw_region_recall: float
    raw_c2a_utility: float
    memla_file_recall: float
    memla_command_recall: float
    memla_verification_recall: float
    memla_role_recall: float
    memla_region_recall: float
    memla_c2a_utility: float
    utility_delta: float
    winner: str
    teacher_signal_axes: list[str]
    dominant_advantage_axes: list[str]
    teacher_signal_reasons: list[str]
    teacher_signal_class: str
    teaching_priority: str


def _extract_trace_row(report_path: Path, report: dict[str, Any], row: dict[str, Any], index: int) -> ExtractedC2ATraceRow:
    expected_files = list(row.get("expected_files") or [])
    expected_roles = list(row.get("expected_roles") or [])
    expected_regions = list(row.get("expected_regions") or [])
    raw_files = list(row.get("raw_likely_files") or [])
    raw_roles = list(row.get("raw_role_targets") or [])
    raw_constraints = list(row.get("raw_predicted_constraints") or [])
    raw_transmutations = list(row.get("raw_predicted_transmutations") or [])
    memla_files = list(row.get("memla_likely_files") or [])
    memla_roles = list(row.get("memla_role_targets") or [])
    memla_constraints = list(row.get("memla_predicted_constraints") or [])
    memla_transmutations = list(row.get("memla_predicted_transmutations") or [])

    raw_expected_file_hits = _hits(raw_files, expected_files)
    memla_expected_file_hits = _hits(memla_files, expected_files)
    raw_expected_role_hits = _hits(raw_roles, expected_roles)
    memla_expected_role_hits = _hits(memla_roles, expected_roles)
    raw_expected_region_hits = _hits(raw_files + list(row.get("raw_selected_regions") or []), expected_regions)
    memla_expected_region_hits = _hits(list(row.get("memla_selected_regions") or []) + memla_files, expected_regions)
    winner = _winner(float(row.get("raw_c2a_utility", 0.0)), float(row.get("memla_c2a_utility", 0.0)))

    extracted = {
        "winner": winner,
        "raw_c2a_utility": round(float(row.get("raw_c2a_utility", 0.0)), 4),
        "memla_c2a_utility": round(float(row.get("memla_c2a_utility", 0.0)), 4),
        "raw_parse_mode": str(row.get("raw_parse_mode") or "json"),
        "raw_expected_file_hits": raw_expected_file_hits,
        "raw_expected_role_hits": raw_expected_role_hits,
        "raw_expected_region_hits": raw_expected_region_hits,
        "raw_likely_commands": list(row.get("raw_likely_commands") or []),
        "raw_likely_tests": list(row.get("raw_likely_tests") or []),
        "raw_predicted_constraints": raw_constraints,
        "raw_predicted_transmutations": raw_transmutations,
        "raw_response_text": str(row.get("raw_response_text") or ""),
    }
    reasons = _teacher_signal_reasons(extracted)
    extracted["teacher_signal_reasons"] = reasons
    signal_class = _teacher_signal_class(extracted)
    extracted["teacher_signal_class"] = signal_class
    extracted["teaching_priority"] = _teaching_priority(extracted)

    return ExtractedC2ATraceRow(
        source_report=str(report_path.resolve()),
        source_case_index=index,
        repo_root=str(report.get("repo_root") or ""),
        cases_path=str(report.get("cases_path") or ""),
        prompt=str(row.get("prompt") or ""),
        raw_model=str(report.get("raw_model") or ""),
        memla_model=str(report.get("memla_model") or ""),
        raw_provider=str(report.get("raw_provider") or ""),
        memla_provider=str(report.get("memla_provider") or ""),
        expected_files=expected_files,
        expected_commands=list(row.get("expected_commands") or []),
        expected_roles=expected_roles,
        expected_regions=expected_regions,
        raw_likely_files=raw_files,
        raw_likely_commands=list(row.get("raw_likely_commands") or []),
        raw_likely_tests=list(row.get("raw_likely_tests") or []),
        raw_role_targets=raw_roles,
        raw_predicted_constraints=raw_constraints,
        raw_predicted_transmutations=raw_transmutations,
        raw_response_text=str(row.get("raw_response_text") or ""),
        raw_parse_mode=str(row.get("raw_parse_mode") or "json"),
        raw_expected_file_hits=raw_expected_file_hits,
        raw_expected_role_hits=raw_expected_role_hits,
        raw_expected_region_hits=raw_expected_region_hits,
        memla_likely_files=memla_files,
        memla_likely_commands=list(row.get("memla_likely_commands") or []),
        memla_likely_tests=list(row.get("memla_likely_tests") or []),
        memla_role_targets=memla_roles,
        memla_predicted_constraints=memla_constraints,
        memla_predicted_transmutations=memla_transmutations,
        memla_selected_regions=list(row.get("memla_selected_regions") or []),
        memla_expected_file_hits=memla_expected_file_hits,
        memla_expected_role_hits=memla_expected_role_hits,
        memla_expected_region_hits=memla_expected_region_hits,
        shared_file_hits=_shared(raw_expected_file_hits, memla_expected_file_hits),
        teacher_unique_expected_file_hits=_left_only(raw_expected_file_hits, memla_expected_file_hits),
        memla_unique_expected_file_hits=_left_only(memla_expected_file_hits, raw_expected_file_hits),
        shared_constraints=_shared(raw_constraints, memla_constraints),
        teacher_unique_constraints=_left_only(raw_constraints, memla_constraints),
        memla_unique_constraints=_left_only(memla_constraints, raw_constraints),
        shared_transmutations=_shared(raw_transmutations, memla_transmutations),
        teacher_unique_transmutations=_left_only(raw_transmutations, memla_transmutations),
        memla_unique_transmutations=_left_only(memla_transmutations, raw_transmutations),
        raw_file_recall=round(float(row.get("raw_file_recall", 0.0)), 4),
        raw_command_recall=round(float(row.get("raw_command_recall", 0.0)), 4),
        raw_verification_recall=round(float(row.get("raw_verification_recall", 0.0)), 4),
        raw_role_recall=round(float(row.get("raw_role_recall", 0.0)), 4),
        raw_region_recall=round(float(row.get("raw_region_recall", 0.0)), 4),
        raw_c2a_utility=round(float(row.get("raw_c2a_utility", 0.0)), 4),
        memla_file_recall=round(float(row.get("memla_file_recall", 0.0)), 4),
        memla_command_recall=round(float(row.get("memla_command_recall", 0.0)), 4),
        memla_verification_recall=round(float(row.get("memla_verification_recall", 0.0)), 4),
        memla_role_recall=round(float(row.get("memla_role_recall", 0.0)), 4),
        memla_region_recall=round(float(row.get("memla_region_recall", 0.0)), 4),
        memla_c2a_utility=round(float(row.get("memla_c2a_utility", 0.0)), 4),
        utility_delta=round(float(row.get("utility_delta", 0.0)), 4),
        winner=winner,
        teacher_signal_axes=_teacher_signal_axes(row),
        dominant_advantage_axes=_dominant_advantage_axes(row),
        teacher_signal_reasons=reasons,
        teacher_signal_class=signal_class,
        teaching_priority=str(extracted["teaching_priority"]),
    )


def extract_c2a_trace_bank(*, report_paths: list[str], min_utility_delta: float | None = None) -> dict[str, Any]:
    traces: list[ExtractedC2ATraceRow] = []
    report_count = 0
    skipped_rows = 0

    for raw_path in report_paths:
        report_path = Path(raw_path).resolve()
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report_count += 1
        for index, row in enumerate(report.get("rows", []), start=1):
            extracted = _extract_trace_row(report_path, report, row, index)
            if min_utility_delta is not None and float(extracted.utility_delta) < float(min_utility_delta):
                skipped_rows += 1
                continue
            traces.append(extracted)

    winner_counts = Counter(trace.winner for trace in traces)
    signal_counts = Counter(trace.teacher_signal_class for trace in traces)
    priority_counts = Counter(trace.teaching_priority for trace in traces)
    parse_mode_counts = Counter(trace.raw_parse_mode for trace in traces)
    raw_model_counts = Counter(trace.raw_model for trace in traces)
    dominant_axis_counts = Counter(axis for trace in traces for axis in trace.dominant_advantage_axes)

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
        "raw_parse_mode_counts": dict(sorted(parse_mode_counts.items())),
        "dominant_advantage_axis_counts": dict(sorted(dominant_axis_counts.items())),
        "rows_by_raw_model": dict(sorted(raw_model_counts.items())),
        "rows": [asdict(trace) for trace in traces],
    }


def render_c2a_trace_bank_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Coding C2A Trace Bank",
        "",
        f"- Reports ingested: `{report.get('reports_ingested', 0)}`",
        f"- Rows extracted: `{report.get('rows_extracted', 0)}`",
    ]
    min_delta = report.get("min_utility_delta")
    if min_delta is not None:
        lines.append(f"- Minimum utility delta filter: `{min_delta}`")
    raw_models = report.get("raw_models") or []
    if raw_models:
        lines.append(f"- Raw models: `{', '.join(raw_models)}`")

    lines.extend(["", "## Summary", ""])
    lines.append(f"- Winner counts: `{json.dumps(report.get('winner_counts', {}), sort_keys=True)}`")
    lines.append(f"- Teacher signal classes: `{json.dumps(report.get('teacher_signal_class_counts', {}), sort_keys=True)}`")
    lines.append(f"- Teaching priority: `{json.dumps(report.get('teaching_priority_counts', {}), sort_keys=True)}`")
    lines.append(f"- Raw parse modes: `{json.dumps(report.get('raw_parse_mode_counts', {}), sort_keys=True)}`")
    lines.append(f"- Dominant Memla advantage axes: `{json.dumps(report.get('dominant_advantage_axis_counts', {}), sort_keys=True)}`")

    lines.extend(["", "## Extracted rows", ""])
    for row in report.get("rows", []):
        lines.extend(
            [
                f"### {row.get('raw_model', 'unknown')} :: case {row.get('source_case_index', 0)}",
                "",
                f"- Prompt: `{row.get('prompt', '')}`",
                f"- Winner: `{row.get('winner', 'tie')}`",
                f"- Teacher signal class: `{row.get('teacher_signal_class', 'teacher_no_signal')}`",
                f"- Teaching priority: `{row.get('teaching_priority', 'low')}`",
                f"- Raw utility: `{row.get('raw_c2a_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_c2a_utility', 0.0)}`",
                f"- Utility delta: `{row.get('utility_delta', 0.0)}`",
                f"- Teacher signal reasons: `{', '.join(row.get('teacher_signal_reasons', []))}`",
                f"- Teacher signal axes: `{', '.join(row.get('teacher_signal_axes', []))}`",
                f"- Dominant Memla advantage axes: `{', '.join(row.get('dominant_advantage_axes', []))}`",
                f"- Teacher file hits: `{', '.join(row.get('raw_expected_file_hits', []))}`",
                f"- Memla file hits: `{', '.join(row.get('memla_expected_file_hits', []))}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
