from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .constraint_graph import (
    infer_constraint_tags,
    infer_file_roles,
    infer_prompt_roles,
    infer_repo_family,
    scan_repo_role_matches,
    summarize_transmutations,
    transmutation_specificity,
)
from .coding_log import SimilarCodingTrace, WorkflowPriorSummary
from ..reasoning.trajectory import extract_output_text


@dataclass(frozen=True)
class WorkflowPlan:
    likely_files: list[str]
    likely_commands: list[str]
    likely_tests: list[str]
    patch_steps: list[str]
    source_trace_ids: list[int]
    constraint_tags: list[str] = field(default_factory=list)
    transmutations: list[str] = field(default_factory=list)
    role_targets: list[str] = field(default_factory=list)


def _split_steps(text: str) -> list[str]:
    raw = re.split(r"[.\n;]+", text or "")
    steps: list[str] = []
    for piece in raw:
        clean = " ".join(piece.strip().split())
        if len(clean) < 12:
            continue
        lowered = clean.lower()
        if lowered.startswith(("sure", "here", "i would", "you should")):
            clean = re.sub(r"^(sure|here|i would|you should)\s+", "", clean, flags=re.IGNORECASE).strip()
        if clean and clean not in steps:
            steps.append(clean)
    return steps


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


def _tokenize(text: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in re.findall(r"[a-zA-Z0-9]+", text or "")
        if len(_normalize_token(token)) >= 3
    }


def _path_prompt_score(path: str, prompt_tokens: set[str]) -> tuple[int, int, int]:
    path_tokens = _tokenize(Path(path).stem) | _tokenize(str(path).replace("\\", "/"))
    overlap = len(prompt_tokens & path_tokens)
    basename_overlap = len(prompt_tokens & _tokenize(Path(path).stem))
    non_test_bonus = 1 if "test" not in path_tokens else 0
    return (basename_overlap, overlap, non_test_bonus)


def _candidate_relevance(candidate: SimilarCodingTrace) -> float:
    return (
        float(candidate.score)
        + (len(candidate.matched_terms) * 0.12)
        + (len(candidate.matched_files) * 0.18)
        + (0.28 if candidate.repo_family_match else 0.0)
        + (sum(transmutation_specificity(text) for text in candidate.matched_transmutations) * 0.08)
    )


def _is_verification_command(command: str) -> bool:
    lowered = " ".join((command or "").strip().split()).lower()
    return (
        lowered.startswith("pytest")
        or lowered.startswith("py -3 -m pytest")
        or lowered.startswith("python -m pytest")
        or lowered.startswith("npm run build")
        or lowered.startswith("npm run lint")
        or lowered.startswith("npm test")
        or lowered.startswith("pnpm test")
        or lowered.startswith("pnpm build")
        or lowered.startswith("pnpm lint")
        or lowered.startswith("yarn test")
        or lowered.startswith("yarn build")
        or lowered.startswith("yarn lint")
        or lowered.startswith("cargo test")
        or lowered.startswith("go test")
        or lowered.startswith("uv run pytest")
    )


def _infer_repo_verification_commands(repo_root: str) -> list[str]:
    if not repo_root:
        return []
    package_json = Path(repo_root) / "package.json"
    if not package_json.exists():
        return []
    try:
        payload = json.loads(package_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    scripts = payload.get("scripts") or {}
    if not isinstance(scripts, dict):
        return []
    commands: list[str] = []
    for script_name in ("build", "lint", "test"):
        if script_name in scripts:
            commands.append(f"npm run {script_name}")
    return commands


def _collect_transfer_roles(candidates: list[SimilarCodingTrace]) -> set[str]:
    roles: set[str] = set()
    for candidate in candidates:
        roles.update(candidate.matched_roles)
        for path in list(candidate.trace.touched_files) + list(candidate.trace.meta.get("seed_expected_files") or []):
            roles.update(infer_file_roles(path))
    return roles


def build_workflow_plan(
    *,
    candidates: list[SimilarCodingTrace],
    summary: WorkflowPriorSummary,
    prompt: str = "",
    repo_root: str = "",
    max_steps: int = 4,
) -> WorkflowPlan:
    prompt_tokens = _tokenize(prompt)
    desired_roles = infer_prompt_roles(prompt)
    current_family = infer_repo_family(repo_root) if repo_root else "unknown"
    family_candidates = [candidate for candidate in candidates if candidate.same_repo or candidate.repo_family_match]
    active_candidates = family_candidates or candidates
    transfer_roles = _collect_transfer_roles(active_candidates)
    constraint_tags = sorted(infer_constraint_tags(prompt, summary.suggested_files, summary.suggested_commands))
    ranked_files = list(summary.suggested_files)
    combined_roles = desired_roles | transfer_roles
    if repo_root and combined_roles:
        role_candidates = scan_repo_role_matches(repo_root, prompt, combined_roles, limit=8)
        ranked_files = [
            candidate.path
            for candidate in role_candidates
            if candidate.path not in ranked_files
        ] + ranked_files
    if prompt_tokens and ranked_files:
        indexed = list(enumerate(ranked_files))
        indexed.sort(
            key=lambda item: (
                -_path_prompt_score(item[1], prompt_tokens)[0],
                -_path_prompt_score(item[1], prompt_tokens)[1],
                -_path_prompt_score(item[1], prompt_tokens)[2],
                item[0],
            ),
        )
        ranked_files = [path for _, path in indexed]

    focus_tokens = _tokenize(" ".join(ranked_files[:6]))

    patch_steps: list[str] = []
    for candidate in active_candidates:
        relevance = _candidate_relevance(candidate)
        if prompt_tokens and relevance < 0.5:
            continue
        output = extract_output_text(candidate.trace.assistant_text)
        for step in _split_steps(output):
            step_tokens = _tokenize(step)
            token_overlap = len(prompt_tokens & step_tokens)
            focus_overlap = len(focus_tokens & step_tokens)
            if prompt_tokens and token_overlap == 0 and focus_overlap == 0 and relevance < 0.9:
                continue
            if step not in patch_steps:
                patch_steps.append(step)
            if len(patch_steps) >= max_steps:
                break
        if len(patch_steps) >= max_steps:
            break

    likely_tests: list[str] = []
    for command in summary.suggested_commands:
        if _is_verification_command(command) and command not in likely_tests:
            likely_tests.append(command)

    likely_commands = list(summary.suggested_commands)
    if candidates and not likely_commands and repo_root:
        for command in _infer_repo_verification_commands(repo_root):
            if command not in likely_commands:
                likely_commands.append(command)
            if _is_verification_command(command) and command not in likely_tests:
                likely_tests.append(command)

    for candidate in active_candidates:
        for tag in candidate.matched_constraints:
            if tag not in constraint_tags:
                constraint_tags.append(tag)
    transmutations = summarize_transmutations(constraint_tags)
    for candidate in active_candidates:
        for transmutation in candidate.matched_transmutations:
            if transmutation not in transmutations:
                transmutations.append(transmutation)
    transmutations.sort(key=lambda item: transmutation_specificity(item), reverse=True)
    if current_family != "unknown":
        constraint_tags = list(dict.fromkeys(constraint_tags))

    return WorkflowPlan(
        likely_files=ranked_files[:6],
        likely_commands=likely_commands[:4],
        likely_tests=likely_tests[:4],
        patch_steps=patch_steps[: max(max_steps, 0)],
        source_trace_ids=list(summary.source_trace_ids),
        constraint_tags=constraint_tags[:6],
        transmutations=transmutations[:6],
        role_targets=sorted(combined_roles)[:6],
    )


def render_workflow_plan_block(plan: WorkflowPlan) -> str:
    if not (plan.likely_files or plan.likely_commands or plan.patch_steps):
        return ""
    lines = [
        "",
        "=== MEMLA WORKFLOW PLAN ===",
        "Structured pre-teacher plan inferred from accepted repo-specific wins.",
    ]
    if plan.likely_files:
        lines.append(f"Likely files: {', '.join(plan.likely_files[:6])}")
    if plan.likely_commands:
        lines.append(f"Likely commands: {', '.join(plan.likely_commands[:4])}")
    if plan.likely_tests:
        lines.append(f"Likely tests: {', '.join(plan.likely_tests[:4])}")
    if plan.role_targets:
        lines.append(f"Role targets: {', '.join(plan.role_targets[:4])}")
    if plan.constraint_tags:
        lines.append(f"Constraint tags: {', '.join(plan.constraint_tags[:6])}")
    if plan.patch_steps:
        lines.append("Likely patch plan:")
        for idx, step in enumerate(plan.patch_steps[:4], start=1):
            lines.append(f"{idx}. {step}")
    if plan.transmutations:
        lines.append("Transmutations:")
        for idx, transmutation in enumerate(plan.transmutations[:4], start=1):
            lines.append(f"{idx}. {transmutation}")
    lines.append("=== END MEMLA WORKFLOW PLAN ===")
    return "\n".join(lines)
