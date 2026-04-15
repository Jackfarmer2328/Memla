from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .coding_proxy import CodingSession
from .constraint_graph import build_repo_map, infer_file_roles, scan_repo_role_matches
from .eval_harness import PlanEvalCase, load_eval_cases
from .patch_execution_benchmark import _build_llm_client, _override_llm_env
from .seed_runner import _extract_answer_commands, _extract_answer_files
from .workflow_planner import WorkflowPlan
from ..ollama_client import ChatMessage


CODING_C2A_RAW_SYSTEM = """
You are a coding C2A analyst.

Given a repository summary and a task prompt, predict the best next bounded move.
Return strict JSON only with this shape:
{
  "likely_files": ["repo/relative/path.py"],
  "likely_commands": ["pytest -q tests/test_example.py"],
  "likely_tests": ["pytest -q tests/test_example.py"],
  "role_targets": ["service_boundary"],
  "predicted_constraints": ["verification_gate"],
  "predicted_transmutations": ["Trade vague search for a narrower verified path."],
  "rationale": "short explanation"
}

Rules:
- Focus on the next high-yield repo move, not a full implementation.
- Prefer the smallest likely file set that unlocks the task.
- Commands and tests should be concrete when useful; otherwise return empty arrays.
- Files must be repo-relative.
- Do not include markdown fences or extra prose.
""".strip()


@dataclass(frozen=True)
class CodingC2ABenchmarkRow:
    prompt: str
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
    raw_file_recall: float
    raw_command_recall: float
    raw_verification_recall: float
    raw_role_recall: float
    raw_region_recall: float
    raw_c2a_utility: float
    memla_likely_files: list[str]
    memla_likely_commands: list[str]
    memla_likely_tests: list[str]
    memla_role_targets: list[str]
    memla_predicted_constraints: list[str]
    memla_predicted_transmutations: list[str]
    memla_selected_regions: list[str]
    memla_file_recall: float
    memla_command_recall: float
    memla_verification_recall: float
    memla_role_recall: float
    memla_region_recall: float
    memla_c2a_utility: float
    utility_delta: float
    raw_response_text: str = ""
    raw_parse_mode: str = "json"


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


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {value.lower() for value in predicted}
    expected_set = {value.lower() for value in expected}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def _region_key(path: str) -> str:
    clean = str(path or "").strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    parts = [part for part in Path(clean).parts if part and part not in {".", "/"}]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    first = parts[0]
    second = parts[1] if len(parts) > 1 else ""

    if first == "packages":
        if len(parts) >= 5 and parts[2] in {"src", "test", "tests"}:
            return "/".join(parts[:5])
        return "/".join(parts[: min(len(parts), 3)])
    if first in {"src", "tests", "test"}:
        if Path(second).suffix:
            return first
        if len(parts) >= 3 and second in {"api", "auth", "core", "commands", "reunite"} and not Path(parts[2]).suffix:
            return "/".join(parts[:3])
        return "/".join(parts[:2])
    return "/".join(parts[: min(len(parts), 2)])


def _extract_json_object(text: str) -> dict[str, Any]:
    clean = str(text or "").strip()
    if not clean:
        return {}
    clean = re.sub(r",(\s*[}\]])", r"\1", clean)
    try:
        data = json.loads(clean)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", clean, flags=re.DOTALL)
    if not match:
        return {}
    blob = re.sub(r",(\s*[}\]])", r"\1", match.group(0))
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _repo_file_catalog(repo_root: str) -> tuple[list[str], dict[str, list[str]]]:
    repo = Path(repo_root)
    ignored_dirs = {
        "node_modules",
        ".git",
        "dist",
        "build",
        "memla_reports",
        ".memla",
        "proof",
        "frozen",
        ".next",
        ".turbo",
        ".venv",
        "venv",
        ".pytest_cache",
        "coverage",
        "logs",
        "__pycache__",
        ".mypy_cache",
    }
    paths: list[str] = []
    basename_index: dict[str, list[str]] = {}
    if not repo.exists():
        return paths, basename_index
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        paths.append(rel)
        basename_index.setdefault(Path(rel).name.lower(), []).append(rel)
    return paths, basename_index


def _extract_repo_relative_file_mentions(text: str, repo_root: str) -> list[str]:
    response = str(text or "")
    exact_matches = _normalize(_extract_answer_files(response))
    repo_paths, basename_index = _repo_file_catalog(repo_root)
    response_lower = response.lower()
    recovered: list[str] = []
    for candidate in exact_matches:
        clean = candidate.replace("\\", "/").strip()
        if clean in repo_paths:
            recovered.append(clean)
            continue
        basename_matches = basename_index.get(Path(clean).name.lower(), [])
        if len(basename_matches) == 1:
            recovered.append(basename_matches[0])
    for rel in repo_paths:
        if rel.lower() in response_lower:
            recovered.append(rel)
    for basename, matches in basename_index.items():
        if len(matches) != 1:
            continue
        if basename in response_lower:
            recovered.append(matches[0])
    return _normalize(recovered)


def _repair_raw_payload_via_model(
    *,
    client: Any,
    model: str,
    response: str,
    temperature: float,
    num_ctx: int | None,
) -> tuple[dict[str, Any], str]:
    if not str(response or "").strip():
        return {}, str(response or "")
    repair_prompt = (
        "Convert the answer below into strict JSON only using this shape:\n"
        "{\n"
        '  "likely_files": ["repo/relative/path.py"],\n'
        '  "likely_commands": ["pytest -q tests/test_example.py"],\n'
        '  "likely_tests": ["pytest -q tests/test_example.py"],\n'
        '  "role_targets": ["service_boundary"],\n'
        '  "predicted_constraints": ["verification_gate"],\n'
        '  "predicted_transmutations": ["Trade vague search for a narrower verified path."],\n'
        '  "rationale": "short explanation"\n'
        "}\n\n"
        "If a field is unknown, return an empty array or empty string.\n"
        "Do not add markdown fences.\n\n"
        "Answer to convert:\n"
        f"{response}"
    )
    repaired = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=CODING_C2A_RAW_SYSTEM),
            ChatMessage(role="user", content=repair_prompt),
        ],
        temperature=min(float(temperature), 0.1),
        num_ctx=num_ctx,
    ).strip()
    return _extract_json_object(repaired), repaired


def _normalize_raw_payload(
    *,
    payload: dict[str, Any],
    response: str,
    repo_root: str,
    client: Any,
    model: str,
    temperature: float,
    num_ctx: int | None,
) -> tuple[dict[str, Any], str, str]:
    repaired_response = str(response or "")
    parse_mode = "json"
    normalized = {
        "likely_files": _normalize(list(payload.get("likely_files") or [])),
        "likely_commands": _normalize(list(payload.get("likely_commands") or [])),
        "likely_tests": _normalize(list(payload.get("likely_tests") or [])),
        "role_targets": _normalize(list(payload.get("role_targets") or [])),
        "predicted_constraints": _normalize(list(payload.get("predicted_constraints") or [])),
        "predicted_transmutations": _normalize(list(payload.get("predicted_transmutations") or [])),
        "rationale": " ".join(str(payload.get("rationale") or "").split()),
    }
    has_signal = any(
        normalized[key]
        for key in (
            "likely_files",
            "likely_commands",
            "likely_tests",
            "role_targets",
            "predicted_constraints",
            "predicted_transmutations",
        )
    )
    if not has_signal:
        repaired_payload, repaired_response = _repair_raw_payload_via_model(
            client=client,
            model=model,
            response=response,
            temperature=temperature,
            num_ctx=num_ctx,
        )
        repaired_normalized = {
            "likely_files": _normalize(list(repaired_payload.get("likely_files") or [])),
            "likely_commands": _normalize(list(repaired_payload.get("likely_commands") or [])),
            "likely_tests": _normalize(list(repaired_payload.get("likely_tests") or [])),
            "role_targets": _normalize(list(repaired_payload.get("role_targets") or [])),
            "predicted_constraints": _normalize(list(repaired_payload.get("predicted_constraints") or [])),
            "predicted_transmutations": _normalize(list(repaired_payload.get("predicted_transmutations") or [])),
            "rationale": " ".join(str(repaired_payload.get("rationale") or "").split()),
        }
        repaired_has_signal = any(
            repaired_normalized[key]
            for key in (
                "likely_files",
                "likely_commands",
                "likely_tests",
                "role_targets",
                "predicted_constraints",
                "predicted_transmutations",
            )
        )
        if repaired_has_signal:
            normalized = repaired_normalized
            parse_mode = "json_repair"
            has_signal = True
    if not normalized["likely_files"]:
        heuristic_files = _extract_repo_relative_file_mentions(repaired_response, repo_root)
        if heuristic_files:
            normalized["likely_files"] = heuristic_files
            parse_mode = "heuristic_paths" if parse_mode == "json" else f"{parse_mode}+heuristic_paths"
    if not normalized["likely_commands"]:
        heuristic_commands = _normalize(_extract_answer_commands(repaired_response))
        if heuristic_commands:
            normalized["likely_commands"] = heuristic_commands
            parse_mode = "heuristic_commands" if parse_mode == "json" else f"{parse_mode}+heuristic_commands"
    if not normalized["likely_tests"]:
        normalized["likely_tests"] = list(normalized["likely_commands"])
    return normalized, repaired_response, parse_mode


def _render_repo_summary(repo_root: str, prompt: str) -> str:
    repo_map = build_repo_map(repo_root, prompt=prompt, limit=6)
    anchors = scan_repo_role_matches(repo_root, prompt, set(), limit=6)
    lines = ["Repository summary:"]
    if repo_map:
        lines.append("Top regions:")
        for item in repo_map[:6]:
            region = str(item.get("region") or "").strip()
            roles = ", ".join(item.get("roles") or [])
            sample_files = ", ".join(item.get("sample_files") or [])
            bits = [f"- {region}"]
            if roles:
                bits.append(f"roles={roles}")
            if sample_files:
                bits.append(f"samples={sample_files}")
            lines.append(" ".join(bits))
    if anchors:
        lines.append("Prompt-matched file anchors:")
        for item in anchors[:6]:
            if hasattr(item, "path"):
                target_paths = str(getattr(item, "path") or "").strip()
            else:
                target_paths = ", ".join(getattr(item, "get", lambda *_: [])("target_paths") or [])
            if target_paths:
                lines.append(f"- {target_paths}")
    return "\n".join(lines)


def _query_raw_c2a(
    *,
    repo_root: str,
    prompt: str,
    model: str,
    temperature: float,
    num_ctx: int | None,
    provider: str | None = None,
    base_url: str | None = None,
) -> dict[str, Any]:
    client = _build_llm_client(provider=provider, base_url=base_url)
    repo_summary = _render_repo_summary(repo_root, prompt)
    response = client.chat(
        model=model,
        messages=[
            ChatMessage(role="system", content=CODING_C2A_RAW_SYSTEM),
            ChatMessage(
                role="user",
                content=f"{repo_summary}\n\nTask:\n{prompt}\n\nReturn strict JSON only.",
            ),
        ],
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()
    payload = _extract_json_object(response)
    normalized, repaired_response, parse_mode = _normalize_raw_payload(
        payload=payload,
        response=response,
        repo_root=repo_root,
        client=client,
        model=model,
        temperature=temperature,
        num_ctx=num_ctx,
    )
    normalized["raw_response"] = repaired_response
    normalized["parse_mode"] = parse_mode
    return normalized


def _roles_for_files(paths: list[str], extra_roles: list[str] | None = None) -> list[str]:
    roles = {
        role
        for path in paths
        for role in infer_file_roles(path)
    }
    roles.update(str(role).strip() for role in (extra_roles or []) if str(role).strip())
    return sorted(roles)


def _regions_for_files(paths: list[str], extra_regions: list[str] | None = None) -> list[str]:
    regions = {_region_key(path) for path in paths if _region_key(path)}
    regions.update(str(region).strip() for region in (extra_regions or []) if str(region).strip())
    return sorted(regions)


def _score_c2a_utility(
    *,
    file_recall: float,
    command_recall: float,
    verification_recall: float,
    role_recall: float,
    region_recall: float,
) -> float:
    utility = (
        (0.45 * float(file_recall))
        + (0.2 * float(command_recall))
        + (0.1 * float(verification_recall))
        + (0.15 * float(role_recall))
        + (0.1 * float(region_recall))
    )
    return round(float(utility), 4)


def _build_memla_plan(
    *,
    session: CodingSession,
    prompt: str,
) -> WorkflowPlan:
    return session.build_plan(prompt)


def run_coding_c2a_benchmark(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    temperature: float = 0.1,
    top_k: int = 12,
    num_ctx: int | None = None,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    memla_c2a_policy_path: str = "",
    disable_memla_c2a_policy: bool = False,
) -> dict[str, Any]:
    cases = load_eval_cases(cases_path)
    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    rows: list[CodingC2ABenchmarkRow] = []
    failures: list[dict[str, Any]] = []

    with _override_llm_env(provider=memla_provider or None, base_url=memla_base_url or None):
        session = CodingSession(
            model=memla_model,
            db_path=db_path,
            user_id=user_id,
            repo_root=repo_root,
            temperature=temperature,
            top_k=top_k,
            num_ctx=num_ctx,
            enable_compile_loop=True,
            c2a_policy_path=memla_c2a_policy_path,
            disable_c2a_policy=disable_memla_c2a_policy,
        )
        try:
            for case in cases:
                try:
                    expected_roles = _roles_for_files(case.expected_files)
                    expected_regions = _regions_for_files(case.expected_files)

                    raw_payload = _query_raw_c2a(
                        repo_root=repo_root,
                        prompt=case.prompt,
                        model=raw_model,
                        temperature=temperature,
                        num_ctx=num_ctx,
                        provider=raw_provider or None,
                        base_url=raw_base_url or None,
                    )
                    raw_files = list(raw_payload.get("likely_files") or [])
                    raw_commands = list(raw_payload.get("likely_commands") or [])
                    raw_tests = list(raw_payload.get("likely_tests") or [])
                    raw_roles = _roles_for_files(raw_files, list(raw_payload.get("role_targets") or []))
                    raw_regions = _regions_for_files(raw_files)
                    raw_command_score = _score_overlap(raw_commands, case.expected_commands)
                    raw_verification_score = _score_overlap(_normalize(raw_commands + raw_tests), case.expected_commands)
                    raw_row_utility = _score_c2a_utility(
                        file_recall=_score_overlap(raw_files, case.expected_files),
                        command_recall=raw_command_score,
                        verification_recall=raw_verification_score,
                        role_recall=_score_overlap(raw_roles, expected_roles),
                        region_recall=_score_overlap(raw_regions, expected_regions),
                    )

                    plan = _build_memla_plan(session=session, prompt=case.prompt)
                    memla_files = list(plan.likely_files or [])
                    memla_commands = list(plan.likely_commands or [])
                    memla_tests = list(plan.likely_tests or [])
                    memla_roles = _roles_for_files(memla_files, list(plan.role_targets or []))
                    memla_regions = _regions_for_files(memla_files, list(plan.selected_search_regions or []))
                    memla_command_score = _score_overlap(memla_commands, case.expected_commands)
                    memla_verification_score = _score_overlap(_normalize(memla_commands + memla_tests), case.expected_commands)
                    memla_row_utility = _score_c2a_utility(
                        file_recall=_score_overlap(memla_files, case.expected_files),
                        command_recall=memla_command_score,
                        verification_recall=memla_verification_score,
                        role_recall=_score_overlap(memla_roles, expected_roles),
                        region_recall=_score_overlap(memla_regions, expected_regions),
                    )

                    rows.append(
                        CodingC2ABenchmarkRow(
                            prompt=case.prompt,
                            expected_files=list(case.expected_files),
                            expected_commands=list(case.expected_commands),
                            expected_roles=expected_roles,
                            expected_regions=expected_regions,
                            raw_likely_files=raw_files,
                            raw_likely_commands=raw_commands,
                            raw_likely_tests=raw_tests,
                            raw_role_targets=raw_roles,
                            raw_predicted_constraints=list(raw_payload.get("predicted_constraints") or []),
                            raw_predicted_transmutations=list(raw_payload.get("predicted_transmutations") or []),
                            raw_file_recall=round(_score_overlap(raw_files, case.expected_files), 4),
                            raw_command_recall=round(raw_command_score, 4),
                            raw_verification_recall=round(raw_verification_score, 4),
                            raw_role_recall=round(_score_overlap(raw_roles, expected_roles), 4),
                            raw_region_recall=round(_score_overlap(raw_regions, expected_regions), 4),
                            raw_c2a_utility=raw_row_utility,
                            memla_likely_files=memla_files,
                            memla_likely_commands=memla_commands,
                            memla_likely_tests=memla_tests,
                            memla_role_targets=memla_roles,
                            memla_predicted_constraints=list(plan.predicted_constraints or []),
                            memla_predicted_transmutations=list(plan.transmutations or []),
                            memla_selected_regions=list(plan.selected_search_regions or []),
                            memla_file_recall=round(_score_overlap(memla_files, case.expected_files), 4),
                            memla_command_recall=round(memla_command_score, 4),
                            memla_verification_recall=round(memla_verification_score, 4),
                            memla_role_recall=round(_score_overlap(memla_roles, expected_roles), 4),
                            memla_region_recall=round(_score_overlap(memla_regions, expected_regions), 4),
                            memla_c2a_utility=memla_row_utility,
                            utility_delta=round(memla_row_utility - raw_row_utility, 4),
                            raw_response_text=str(raw_payload.get("raw_response") or ""),
                            raw_parse_mode=str(raw_payload.get("parse_mode") or "json"),
                        )
                    )
                except Exception as exc:
                    failures.append(
                        {
                            "prompt": case.prompt,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
        finally:
            session.close()

    count = max(len(rows), 1)
    avg_raw_utility = round(sum(row.raw_c2a_utility for row in rows) / count, 4)
    avg_memla_utility = round(sum(row.memla_c2a_utility for row in rows) / count, 4)
    utility_index = round(avg_memla_utility / avg_raw_utility, 4) if avg_raw_utility > 0 else None
    return {
        "generated_ts": int(time.time()),
        "repo_root": str(Path(repo_root).resolve()),
        "db_path": str(Path(db_path).resolve()),
        "cases_path": str(Path(cases_path).resolve()),
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failures),
        "avg_raw_file_recall": round(sum(row.raw_file_recall for row in rows) / count, 4),
        "avg_raw_command_recall": round(sum(row.raw_command_recall for row in rows) / count, 4),
        "avg_raw_verification_recall": round(sum(row.raw_verification_recall for row in rows) / count, 4),
        "avg_raw_role_recall": round(sum(row.raw_role_recall for row in rows) / count, 4),
        "avg_raw_region_recall": round(sum(row.raw_region_recall for row in rows) / count, 4),
        "avg_raw_c2a_utility": avg_raw_utility,
        "avg_memla_file_recall": round(sum(row.memla_file_recall for row in rows) / count, 4),
        "avg_memla_command_recall": round(sum(row.memla_command_recall for row in rows) / count, 4),
        "avg_memla_verification_recall": round(sum(row.memla_verification_recall for row in rows) / count, 4),
        "avg_memla_role_recall": round(sum(row.memla_role_recall for row in rows) / count, 4),
        "avg_memla_region_recall": round(sum(row.memla_region_recall for row in rows) / count, 4),
        "avg_memla_c2a_utility": avg_memla_utility,
        "memla_vs_raw_c2a_utility_index": utility_index,
        "rows": [asdict(row) for row in rows],
        "failed_cases": failures,
    }


def render_coding_c2a_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Coding C2A Benchmark",
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
        f"| File recall | `{report.get('avg_raw_file_recall', 0.0)}` | `{report.get('avg_memla_file_recall', 0.0)}` |",
        f"| Command recall | `{report.get('avg_raw_command_recall', 0.0)}` | `{report.get('avg_memla_command_recall', 0.0)}` |",
        f"| Verification recall | `{report.get('avg_raw_verification_recall', 0.0)}` | `{report.get('avg_memla_verification_recall', 0.0)}` |",
        f"| Role recall | `{report.get('avg_raw_role_recall', 0.0)}` | `{report.get('avg_memla_role_recall', 0.0)}` |",
        f"| Region recall | `{report.get('avg_raw_region_recall', 0.0)}` | `{report.get('avg_memla_region_recall', 0.0)}` |",
        f"| C2A utility | `{report.get('avg_raw_c2a_utility', 0.0)}` | `{report.get('avg_memla_c2a_utility', 0.0)}` |",
    ]
    utility_index = report.get("memla_vs_raw_c2a_utility_index")
    if utility_index is not None:
        lines.extend(["", f"- Memla vs raw utility index: `{utility_index}`"])
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for item in report.get("failed_cases", []):
            lines.append(
                f"- `{item.get('prompt', '')}` [{item.get('error_type', 'Error')}] {item.get('error', '')}"
            )
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        lines.extend(
            [
                f"### {row.get('prompt', '').strip()}",
                "",
                f"- Expected files: `{', '.join(row.get('expected_files', []))}`",
                f"- Raw files: `{', '.join(row.get('raw_likely_files', []))}`",
                f"- Memla files: `{', '.join(row.get('memla_likely_files', []))}`",
                f"- Raw utility: `{row.get('raw_c2a_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_c2a_utility', 0.0)}`",
                f"- Utility delta: `{row.get('utility_delta', 0.0)}`",
                f"- Raw parse mode: `{row.get('raw_parse_mode', 'json')}`",
                f"- Raw constraints: `{', '.join(row.get('raw_predicted_constraints', []))}`",
                f"- Memla constraints: `{', '.join(row.get('memla_predicted_constraints', []))}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"
