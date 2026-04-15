from __future__ import annotations

import json
import re
from typing import Any
from dataclasses import dataclass, field
from pathlib import Path

from .constraint_graph import (
    build_repo_map,
    build_repo_topology_graph,
    calibrate_hypothesis_swarm,
    RepoRoleCandidate,
    build_hypothesis_coalitions,
    build_hypothesis_swarm,
    infer_constraint_tags,
    infer_file_roles,
    infer_roles_from_constraints,
    infer_prompt_roles,
    infer_repo_family,
    predict_constraint_tags,
    scan_repo_role_matches,
    score_file_search_warmth,
    score_repo_search_path,
    score_repo_topology_path,
    score_repo_topology_walk,
    summarize_transmutations,
    transmutation_specificity,
)
from .coding_compile_loop import compile_coding_hypotheses
from .coding_log import SimilarCodingTrace, WorkflowPriorSummary
from .c2a_policy_bank import suggest_c2a_policy_priors
from ..reasoning.trajectory import extract_output_text


@dataclass(frozen=True)
class WorkflowPlan:
    likely_files: list[str]
    likely_commands: list[str]
    likely_tests: list[str]
    patch_steps: list[str]
    source_trace_ids: list[int]
    predicted_constraints: list[str] = field(default_factory=list)
    ruled_out_constraints: list[str] = field(default_factory=list)
    constraint_tags: list[str] = field(default_factory=list)
    transmutations: list[str] = field(default_factory=list)
    role_targets: list[str] = field(default_factory=list)
    ruled_out_roles: list[str] = field(default_factory=list)
    hypothesis_swarm: list[dict[str, Any]] = field(default_factory=list)
    hypothesis_coalitions: list[dict[str, Any]] = field(default_factory=list)
    compiled_hypotheses: list[dict[str, Any]] = field(default_factory=list)
    validated_trade_path: dict[str, Any] = field(default_factory=dict)
    residual_constraints: list[str] = field(default_factory=list)
    repo_map_regions: list[dict[str, Any]] = field(default_factory=list)
    selected_search_regions: list[str] = field(default_factory=list)
    topology_anchor_files: list[str] = field(default_factory=list)
    self_transmutation_boosts: dict[str, Any] = field(default_factory=dict)


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


def _merge_preferred_items(primary: list[str], secondary: list[str], *, limit: int) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in (primary, secondary):
        for raw in group:
            clean = " ".join(str(raw or "").strip().split())
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(clean)
    return merged[: max(int(limit), 0)]


def _boost_repo_map_regions(regions: list[dict[str, Any]], preferred_regions: list[str]) -> list[dict[str, Any]]:
    if not regions or not preferred_regions:
        return list(regions)
    preferred_keys = {str(region).strip().lower() for region in preferred_regions if str(region).strip()}
    boosted: list[dict[str, Any]] = []
    for item in regions:
        region = str(item.get("region") or "").strip()
        score = float(item.get("score") or 0.0)
        if region.lower() in preferred_keys:
            score += 1.1
        boosted.append({**item, "score": score})
    boosted.sort(key=lambda item: (float(item.get("score") or 0.0), str(item.get("region") or "")), reverse=True)
    return boosted


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


def _specific_path_prompt_score(path: str, prompt_tokens: set[str]) -> tuple[int, int, int]:
    path_tokens = _tokenize(Path(path).stem) | _tokenize(str(path).replace("\\", "/"))
    basename_tokens = _tokenize(Path(path).stem)
    specific_prompt_tokens = {token for token in prompt_tokens if token not in _GENERIC_PATH_ANCHOR_TOKENS}
    specific_path_tokens = {token for token in path_tokens if token not in _GENERIC_PATH_ANCHOR_TOKENS}
    specific_basename_tokens = {token for token in basename_tokens if token not in _GENERIC_PATH_ANCHOR_TOKENS}
    specific_basename_overlap = len(specific_prompt_tokens & specific_basename_tokens)
    specific_overlap = len(specific_prompt_tokens & specific_path_tokens)
    generic_overlap = len((prompt_tokens & path_tokens) - (specific_prompt_tokens & specific_path_tokens))
    return (specific_basename_overlap, specific_overlap, generic_overlap)


def _has_prompt_specific_path_support(path: str, prompt_tokens: set[str]) -> bool:
    specific_basename_overlap, specific_overlap, _ = _specific_path_prompt_score(path, prompt_tokens)
    return specific_basename_overlap > 0 or specific_overlap > 0


def _candidate_relevance(candidate: SimilarCodingTrace) -> float:
    return (
        float(candidate.score)
        + (len(candidate.matched_terms) * 0.12)
        + (len(candidate.matched_files) * 0.18)
        + (0.28 if candidate.repo_family_match else 0.0)
        + (float(candidate.trace.meta.get("constraint_prediction_f1") or 0.0) * 0.18)
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


_SUPPORTING_FILE_ROLES = {"dependency_manifest", "cli_surface", "test_surface"}
_GENERIC_PATH_ANCHOR_TOKENS = {
    "src",
    "source",
    "lib",
    "app",
    "apps",
    "index",
    "main",
    "test",
    "tests",
    "spec",
    "specs",
    "file",
    "files",
    "update",
}
_CLI_PROMPT_TOKENS = {"cli", "command", "commands", "terminal", "argv", "stdin", "stdout", "prompt", "shell", "flag", "option"}


def _collect_transfer_role_scores(candidates: list[SimilarCodingTrace]) -> dict[str, float]:
    role_scores: dict[str, float] = {}
    for candidate in candidates:
        base = 0.55 + (0.28 if candidate.same_repo else 0.0) + (0.14 if candidate.repo_family_match else 0.0)
        for role in candidate.matched_roles:
            role_scores[role] = role_scores.get(role, 0.0) + (base * 1.2)
        coalition_nodes = list((candidate.trace.meta.get("hypothesis_swarm_node") or {}).get("top_coalitions") or [])
        for coalition in coalition_nodes[:2]:
            coalition_base = (base * 0.55) + (float(coalition.get("support_score") or 0.0) * 0.4)
            for role in coalition.get("confirmed_roles") or []:
                clean_role = str(role).strip()
                if not clean_role:
                    continue
                multiplier = 0.45 if clean_role in _SUPPORTING_FILE_ROLES else 1.0
                role_scores[clean_role] = role_scores.get(clean_role, 0.0) + (coalition_base * 1.15 * multiplier)
            for role in coalition.get("predicted_roles") or []:
                clean_role = str(role).strip()
                if not clean_role:
                    continue
                multiplier = 0.45 if clean_role in _SUPPORTING_FILE_ROLES else 1.0
                role_scores[clean_role] = role_scores.get(clean_role, 0.0) + (coalition_base * 0.72 * multiplier)
        for path in list(candidate.trace.touched_files) + list(candidate.trace.meta.get("seed_expected_files") or []):
            for role in infer_file_roles(path):
                role_scores[role] = role_scores.get(role, 0.0) + base
    return role_scores


def _select_transfer_roles(candidates: list[SimilarCodingTrace], desired_roles: set[str]) -> set[str]:
    selected: set[str] = set(desired_roles)
    role_scores = _collect_transfer_role_scores(candidates)
    for role, score in sorted(role_scores.items(), key=lambda item: (item[1], item[0]), reverse=True):
        threshold = 1.05 if role in _SUPPORTING_FILE_ROLES else 0.72
        if score >= threshold:
            selected.add(role)
    return selected


def _select_file_routing_roles(
    *,
    desired_roles: set[str],
    transfer_roles: set[str],
    predicted_roles: set[str],
    summary_files: list[str],
) -> set[str]:
    routing_roles: set[str] = set(desired_roles) | set(transfer_roles)
    summary_file_roles: set[str] = set()
    for path in summary_files:
        summary_file_roles.update(infer_file_roles(path))
    for role in predicted_roles:
        if role in routing_roles:
            continue
        if role in _SUPPORTING_FILE_ROLES and role not in summary_file_roles:
            continue
        routing_roles.add(role)
    return routing_roles


def _collect_candidate_constraints(candidates: list[SimilarCodingTrace]) -> list[str]:
    tags: list[str] = []
    for candidate in candidates:
        trace = candidate.trace
        confirmed = [str(tag).strip() for tag in (trace.meta.get("confirmed_constraints") or []) if str(tag).strip()]
        if confirmed:
            tags.extend(confirmed)
            tags.extend(confirmed)
        trace_files = list(trace.touched_files) + list(trace.meta.get("seed_expected_files") or [])
        trace_commands = [str(test.get("command") or "") for test in trace.tests] + list(
            trace.meta.get("teacher_answer_commands") or []
        )
        tags.extend(
            trace.meta.get("realized_constraint_tags")
            or infer_constraint_tags(
                f"{trace.task_text}\n{trace.assistant_text}",
                trace_files,
                trace_commands,
            )
        )
    return tags


def _collect_candidate_transmutations(candidates: list[SimilarCodingTrace]) -> list[str]:
    items: list[str] = []
    for candidate in candidates:
        for transmutation in candidate.matched_transmutations:
            clean = str(transmutation).strip()
            if clean:
                items.append(clean)
        for transmutation in candidate.trace.meta.get("winning_trades") or []:
            clean = str(transmutation).strip()
            if clean:
                items.append(clean)
    return list(dict.fromkeys(items))


def _collect_repo_map_region_scores(files: list[str], repo_map_regions: list[dict[str, Any]]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for path in files:
        clean_path = str(path or "").replace("\\", "/")
        if not clean_path:
            continue
        for index, region in enumerate(repo_map_regions[:4]):
            region_name = str(region.get("region") or "").strip()
            if not region_name:
                continue
            if clean_path == region_name or clean_path.startswith(region_name.rstrip("/") + "/"):
                bonus = max(float(region.get("score") or 0.0), 0.0) * max(0.36, 1.0 - (index * 0.15))
                scores[clean_path] = max(scores.get(clean_path, 0.0), bonus)
    return scores


def _collect_candidate_search_path_scores(
    files: list[str],
    *,
    candidates: list[SimilarCodingTrace],
    prompt_roles: set[str],
    prompt_constraints: set[str],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidate in candidates:
        node = candidate.trace.meta.get("repo_search_path_node") or {}
        if not isinstance(node, dict):
            continue
        trace_constraints = {
            str(tag).strip()
            for tag in (node.get("realized_constraints") or [])
            if str(tag).strip()
        }
        trace_roles = {
            str(role).strip()
            for role in (node.get("selected_roles") or [])
            if str(role).strip()
        }
        alignment = 1.0 + (len(prompt_constraints & trace_constraints) * 0.18) + (len(prompt_roles & trace_roles) * 0.14)
        for path in files:
            search_score = score_repo_search_path(
                path,
                node,
                prompt_roles=prompt_roles,
                prompt_constraints=prompt_constraints,
            )
            if float(search_score.get("score") or 0.0) <= 0.0:
                continue
            boosted = float(search_score["score"]) * alignment
            scores[path] = max(scores.get(path, 0.0), boosted)
    return scores


def _collect_repo_topology_scores(
    files: list[str],
    *,
    repo_topology_graph: list[dict[str, Any]],
    anchor_paths: list[str],
    prompt_tokens: set[str],
    prompt_roles: set[str],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    graph_index = {
        str(item.get("path") or "").strip().replace("\\", "/"): dict(item)
        for item in repo_topology_graph
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    for path in files:
        topology_score = score_repo_topology_path(
            path,
            repo_topology_graph,
            anchor_paths=anchor_paths,
            prompt_tokens=prompt_tokens,
            prompt_roles=prompt_roles,
        )
        value = float(topology_score.get("score") or 0.0)
        edge_hits = " ".join(str(item) for item in (topology_score.get("edge_hits") or []) if str(item).strip())
        node = graph_index.get(path) or {}
        command_overlap = len(
            {
                str(token).strip()
                for token in (node.get("command_tokens") or [])
                if str(token).strip()
            }
            & prompt_tokens
        )
        if "router_dependency" in edge_hits:
            value += 0.42
        elif "router_include" in edge_hits:
            value += 0.18
        if "command_handler" in edge_hits:
            value += 0.48
        if command_overlap:
            value += command_overlap * 0.26
        if value > 0.0:
            scores[path] = max(scores.get(path, 0.0), value)
    return scores


def _collect_candidate_topology_walk_scores(
    files: list[str],
    *,
    candidates: list[SimilarCodingTrace],
    prompt_tokens: set[str],
    prompt_roles: set[str],
) -> dict[str, float]:
    scores: dict[str, float] = {}
    for candidate in candidates:
        node = candidate.trace.meta.get("repo_topology_walk_node") or {}
        if not isinstance(node, dict):
            continue
        alignment = 1.0
        trace_constraints = {
            str(tag).strip()
            for tag in (node.get("realized_constraints") or [])
            if str(tag).strip()
        }
        if trace_constraints:
            alignment += min(len(trace_constraints), 4) * 0.04
        for path in files:
            walk_score = score_repo_topology_walk(
                path,
                node,
                prompt_tokens=prompt_tokens,
                prompt_roles=prompt_roles,
            )
            value = float(walk_score.get("score") or 0.0)
            if value <= 0.0:
                continue
            scores[path] = max(scores.get(path, 0.0), value * alignment)
    return scores


def _collect_candidate_topology_walk_candidates(
    candidates: list[SimilarCodingTrace],
    *,
    prompt_tokens: set[str],
    desired_roles: set[str],
    limit: int = 6,
) -> list[RepoRoleCandidate]:
    scored: dict[str, float] = {}
    for candidate in candidates:
        node = candidate.trace.meta.get("repo_topology_walk_node") or {}
        if not isinstance(node, dict):
            continue
        for walk in node.get("winning_walks") or []:
            if not isinstance(walk, dict):
                continue
            target = str(walk.get("target") or "").strip().replace("\\", "/")
            if not target:
                continue
            roles = infer_file_roles(target)
            specific_basename_overlap, specific_overlap, _ = _specific_path_prompt_score(target, prompt_tokens)
            role_overlap = _weighted_role_overlap(roles, desired_roles)
            score = float(walk.get("score") or 0.0) + (specific_basename_overlap * 0.38) + (specific_overlap * 0.08) + (role_overlap * 0.18)
            if roles <= _SUPPORTING_FILE_ROLES and specific_basename_overlap == 0 and role_overlap == 0:
                score -= 0.7
            scored[target] = max(scored.get(target, float("-inf")), score)
    ranked = sorted(scored.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return [
        RepoRoleCandidate(path=path, roles=sorted(infer_file_roles(path)), score=float(score))
        for path, score in ranked[: max(int(limit), 0)]
        if score > 0.0
    ]


def _merge_file_candidates(summary_files: list[str], repo_role_candidates: list[RepoRoleCandidate]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in list(summary_files) + [candidate.path for candidate in repo_role_candidates]:
        clean = str(raw or "").strip().replace("\\", "/")
        if not clean or clean in seen:
            continue
        seen.add(clean)
        merged.append(clean)
    return merged


def _should_include_repo_map_sample(
    path: str,
    *,
    prompt_tokens: set[str],
    file_routing_roles: set[str],
) -> bool:
    clean_path = str(path or "").strip().replace("\\", "/")
    if not clean_path:
        return False
    file_roles = infer_file_roles(clean_path)
    specific_basename_overlap, specific_overlap, _ = _specific_path_prompt_score(clean_path, prompt_tokens)
    non_supporting_overlap = len((file_roles - _SUPPORTING_FILE_ROLES) & (file_routing_roles - _SUPPORTING_FILE_ROLES))
    supporting_overlap = len((file_roles & _SUPPORTING_FILE_ROLES) & file_routing_roles)

    if not file_roles and specific_basename_overlap == 0 and specific_overlap == 0:
        return False
    if file_roles and file_roles <= _SUPPORTING_FILE_ROLES:
        if specific_basename_overlap == 0 and specific_overlap == 0 and supporting_overlap == 0:
            return False
        if "cli_surface" in file_roles and not (prompt_tokens & _CLI_PROMPT_TOKENS):
            return False
        if (
            "dependency_manifest" in file_roles
            and "dependency_manifest" not in file_routing_roles
            and not (prompt_tokens & {"dependency", "package", "version", "pyproject", "requirements", "lock"})
        ):
            return False
        if (
            "test_surface" in file_roles
            and specific_basename_overlap == 0
            and "test" not in prompt_tokens
            and "verify" not in prompt_tokens
        ):
            return False
    return non_supporting_overlap > 0 or supporting_overlap > 0 or specific_basename_overlap > 0 or specific_overlap > 0


def _select_repo_topology_anchor_files(
    files: list[str],
    *,
    prompt_tokens: set[str],
    desired_roles: set[str],
    file_routing_roles: set[str],
    repo_role_scores: dict[str, float],
    limit: int = 4,
) -> list[str]:
    anchors: list[str] = []
    for path in files:
        clean_path = str(path or "").strip().replace("\\", "/")
        if not clean_path:
            continue
        file_roles = infer_file_roles(clean_path)
        specific_basename_overlap, specific_overlap, _ = _specific_path_prompt_score(clean_path, prompt_tokens)
        role_overlap = _weighted_role_overlap(file_roles, desired_roles | file_routing_roles)
        repo_bonus = float(repo_role_scores.get(clean_path, 0.0))
        if specific_basename_overlap >= 1:
            anchors.append(clean_path)
        elif "test_surface" in file_roles and specific_overlap >= 1:
            anchors.append(clean_path)
        elif role_overlap >= 1.0 and repo_bonus >= 1.4:
            anchors.append(clean_path)
        if len(anchors) >= max(int(limit), 0):
            break
    if not anchors:
        anchors = [str(path).strip().replace("\\", "/") for path in files[:2] if str(path).strip()]
    return list(dict.fromkeys(anchors))[: max(int(limit), 0)]


def _collect_repo_topology_candidates(
    repo_topology_graph: list[dict[str, Any]],
    *,
    anchor_paths: list[str],
    prompt_tokens: set[str],
    desired_roles: set[str],
    limit: int = 8,
) -> list[RepoRoleCandidate]:
    graph_index = {
        str(item.get("path") or "").strip().replace("\\", "/"): dict(item)
        for item in repo_topology_graph
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    graph_paths = [
        str(item.get("path") or "").strip().replace("\\", "/")
        for item in repo_topology_graph
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ]
    candidate_scores: dict[str, float] = {}
    for target in graph_paths:
        if not target or target in anchor_paths:
            continue
        roles = infer_file_roles(target)
        specific_basename_overlap, specific_overlap, _ = _specific_path_prompt_score(target, prompt_tokens)
        role_overlap = _weighted_role_overlap(roles, desired_roles)
        node = graph_index.get(target) or {}
        command_overlap = len(
            {
                str(token).strip()
                for token in (node.get("command_tokens") or [])
                if str(token).strip()
            }
            & prompt_tokens
        )
        intrinsic_score = float(node.get("score") or 0.0)
        topology_score = score_repo_topology_path(
            target,
            repo_topology_graph,
            anchor_paths=anchor_paths,
            prompt_tokens=prompt_tokens,
            prompt_roles=desired_roles,
            max_hops=2,
        )
        score = float(topology_score.get("score") or 0.0)
        if score <= 0.0 and command_overlap <= 0 and intrinsic_score < 1.2:
            continue
        edge_hits = " ".join(str(item) for item in (topology_score.get("edge_hits") or []) if str(item).strip())
        if score <= 0.0:
            score = (command_overlap * 0.72) + (min(intrinsic_score, 4.0) * 0.22)
        score += (role_overlap * 0.3) + (specific_basename_overlap * 0.42) + (specific_overlap * 0.08)
        if "router_dependency" in edge_hits:
            score += 0.48
        elif "router_include" in edge_hits:
            score += 0.18
        if "command_handler" in edge_hits:
            score += 0.56
        if command_overlap:
            score += command_overlap * 0.34
        if roles <= _SUPPORTING_FILE_ROLES and specific_basename_overlap == 0 and role_overlap == 0:
            score -= 0.85
        if "cli_surface" in roles and not (prompt_tokens & _CLI_PROMPT_TOKENS) and command_overlap == 0:
            score -= 0.7
        candidate_scores[target] = max(candidate_scores.get(target, float("-inf")), score)
    ranked = sorted(candidate_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return [
        RepoRoleCandidate(path=path, roles=sorted(infer_file_roles(path)), score=float(score))
        for path, score in ranked[: max(int(limit), 0)]
        if score > 0.0
    ]


def _collect_hypothesis_role_scores(hypothesis_swarm: list[dict[str, Any]]) -> dict[str, float]:
    role_scores: dict[str, float] = {}
    for hypothesis in hypothesis_swarm[:4]:
        if str(hypothesis.get("style") or "").strip() == "precise":
            continue
        base = float(hypothesis.get("score") or 0.0)
        if base <= 0.0:
            continue
        if hypothesis.get("repo_family_fit"):
            base *= 1.12
        base += len(hypothesis.get("predicted_constraints") or []) * 0.06
        for role in hypothesis.get("predicted_roles") or []:
            clean_role = str(role).strip()
            if not clean_role:
                continue
            multiplier = 0.35 if clean_role in _SUPPORTING_FILE_ROLES else 1.0
            role_scores[clean_role] = role_scores.get(clean_role, 0.0) + (base * multiplier)
    return role_scores


def _collect_hypothesis_negative_role_scores(hypothesis_swarm: list[dict[str, Any]]) -> dict[str, float]:
    role_scores: dict[str, float] = {}
    for hypothesis in hypothesis_swarm[:4]:
        base = float(hypothesis.get("score") or 0.0)
        if base <= 0.0:
            continue
        if hypothesis.get("repo_family_fit"):
            base *= 1.06
        base += len(hypothesis.get("negative_constraints") or []) * 0.04
        for role in hypothesis.get("negative_roles") or []:
            clean_role = str(role).strip()
            if not clean_role:
                continue
            multiplier = 0.35 if clean_role in _SUPPORTING_FILE_ROLES else 1.0
            role_scores[clean_role] = role_scores.get(clean_role, 0.0) + (base * multiplier)
    return role_scores


def _collect_hypothesis_coalition_role_scores(hypothesis_coalitions: list[dict[str, Any]]) -> dict[str, float]:
    role_scores: dict[str, float] = {}
    for coalition in hypothesis_coalitions[:3]:
        base = float(coalition.get("support_score") or coalition.get("avg_fitness") or coalition.get("avg_score") or 0.0)
        if base <= 0.0:
            continue
        base += max(int(coalition.get("member_count") or 1) - 1, 0) * 0.08
        if "precise" in {str(style).strip() for style in (coalition.get("styles") or []) if str(style).strip()}:
            base *= 0.72
        confirmed_roles = {str(role).strip() for role in (coalition.get("confirmed_roles") or []) if str(role).strip()}
        predicted_roles = {str(role).strip() for role in (coalition.get("predicted_roles") or []) if str(role).strip()}
        if not ((confirmed_roles | predicted_roles) - _SUPPORTING_FILE_ROLES):
            base *= 0.18
        for role in sorted(confirmed_roles):
            multiplier = 0.45 if role in _SUPPORTING_FILE_ROLES else 1.0
            role_scores[role] = role_scores.get(role, 0.0) + (base * 1.2 * multiplier)
        for role in sorted(predicted_roles - confirmed_roles):
            multiplier = 0.45 if role in _SUPPORTING_FILE_ROLES else 1.0
            role_scores[role] = role_scores.get(role, 0.0) + (base * 0.82 * multiplier)
    return role_scores


def _collect_candidate_coalition_role_scores(candidates: list[SimilarCodingTrace]) -> dict[str, float]:
    role_scores: dict[str, float] = {}
    for candidate in candidates:
        swarm_node = candidate.trace.meta.get("hypothesis_swarm_node") or {}
        coalition_nodes = list(swarm_node.get("top_coalitions") or swarm_node.get("coalitions") or [])
        candidate_base = (0.18 if candidate.repo_family_match else 0.08) + min(float(candidate.score), 2.5) * 0.08
        for coalition in coalition_nodes[:2]:
            coalition_base = candidate_base + (float(coalition.get("support_score") or 0.0) * 0.34)
            confirmed_roles = {str(role).strip() for role in (coalition.get("confirmed_roles") or []) if str(role).strip()}
            predicted_roles = {str(role).strip() for role in (coalition.get("predicted_roles") or []) if str(role).strip()}
            for role in sorted(confirmed_roles):
                multiplier = 0.45 if role in _SUPPORTING_FILE_ROLES else 1.0
                role_scores[role] = role_scores.get(role, 0.0) + (coalition_base * 1.12 * multiplier)
            for role in sorted(predicted_roles - confirmed_roles):
                multiplier = 0.45 if role in _SUPPORTING_FILE_ROLES else 1.0
                role_scores[role] = role_scores.get(role, 0.0) + (coalition_base * 0.72 * multiplier)
    return role_scores


def _collect_precise_path_scores(hypothesis_swarm: list[dict[str, Any]]) -> dict[str, float]:
    path_scores: dict[str, float] = {}
    for hypothesis in hypothesis_swarm[:5]:
        if str(hypothesis.get("style") or "").strip() != "precise":
            continue
        base = float(hypothesis.get("score") or 0.0) + float(hypothesis.get("fitness") or 0.0) * 0.2
        if base <= 0.0:
            continue
        for path in hypothesis.get("target_paths") or []:
            clean_path = str(path).strip().replace("\\", "/")
            if not clean_path:
                continue
            path_scores[clean_path] = path_scores.get(clean_path, 0.0) + (base * 1.35)
    return path_scores


def _collect_coalition_path_scores(hypothesis_coalitions: list[dict[str, Any]]) -> dict[str, float]:
    path_scores: dict[str, float] = {}
    for coalition in hypothesis_coalitions[:3]:
        styles = {str(style).strip() for style in (coalition.get("styles") or []) if str(style).strip()}
        if "precise" not in styles:
            continue
        base = float(coalition.get("support_score") or coalition.get("avg_fitness") or 0.0)
        if base <= 0.0:
            continue
        for path in coalition.get("target_paths") or []:
            clean_path = str(path).strip().replace("\\", "/")
            if not clean_path:
                continue
            path_scores[clean_path] = path_scores.get(clean_path, 0.0) + (base * 1.05)
    return path_scores


def _merge_role_score_maps(*maps: dict[str, float]) -> dict[str, float]:
    merged: dict[str, float] = {}
    for current in maps:
        for role, score in current.items():
            clean_role = str(role).strip()
            if not clean_role:
                continue
            merged[clean_role] = merged.get(clean_role, 0.0) + float(score)
    return merged


def _collect_candidate_file_search_scores(
    files: list[str],
    *,
    candidates: list[SimilarCodingTrace],
    prompt_tokens: set[str],
    prompt_constraints: set[str],
    prompt_roles: set[str],
    prompt_transmutations: set[str],
    repo_role_scores: dict[str, float],
) -> dict[str, float]:
    path_scores: dict[str, float] = {}
    strict_test_anchor = any(
        "test_surface" in infer_file_roles(path) and _specific_path_prompt_score(path, prompt_tokens)[0] >= 1
        for path in files
    )
    for candidate in candidates:
        node = candidate.trace.meta.get("file_search_node") or {}
        if not node:
            continue
        node_constraints = {
            str(item).strip()
            for item in ((node.get("diagnostic_signals") or []) + (node.get("realized_constraints") or []))
            if str(item).strip()
        }
        node_roles = {str(item).strip() for item in (node.get("resolved_roles") or []) if str(item).strip()}
        node_trades = {str(item).strip() for item in (node.get("winning_trades") or []) if str(item).strip()}
        if not candidate.same_repo and not candidate.repo_family_match:
            if not ((prompt_constraints & node_constraints) or (prompt_roles & node_roles) or (prompt_transmutations & node_trades)):
                continue
        base = (
            min(float(candidate.score), 3.0) * 0.18
            + (0.34 if candidate.same_repo else 0.0)
            + (0.18 if candidate.repo_family_match else 0.0)
        )
        for path in files:
            specific_basename_overlap, specific_overlap, generic_overlap = _specific_path_prompt_score(path, prompt_tokens)
            file_roles = infer_file_roles(path)
            if (
                strict_test_anchor
                and "test_surface" in file_roles
                and specific_basename_overlap == 0
                and specific_overlap == 0
            ):
                continue
            non_supporting_prompt_roles = {
                role for role in (file_roles & prompt_roles) if role not in _SUPPORTING_FILE_ROLES
            }
            supporting_prompt_role_overlap = len((file_roles & prompt_roles) & _SUPPORTING_FILE_ROLES)
            repo_anchor = float(repo_role_scores.get(path, 0.0))
            anchor_strength = (
                (specific_basename_overlap * 1.05)
                + (specific_overlap * 0.24)
                + (generic_overlap * 0.04)
                + (len(non_supporting_prompt_roles) * 0.75)
                + (supporting_prompt_role_overlap * 0.08)
                + min(repo_anchor, 2.0) * 0.24
            )
            if anchor_strength <= 0.0:
                continue
            if (
                specific_basename_overlap == 0
                and specific_overlap == 0
                and not non_supporting_prompt_roles
                and repo_anchor < 0.4
                and file_roles <= _SUPPORTING_FILE_ROLES
            ):
                continue
            warmth = score_file_search_warmth(
                path,
                node,
                prompt_roles=prompt_roles,
                prompt_constraints=prompt_constraints,
                prompt_transmutations=prompt_transmutations,
            )
            warmth_score = float(warmth.get("score") or 0.0)
            if warmth_score <= 0.0:
                continue
            stage_hits = list(warmth.get("stage_hits") or [])
            anchor_multiplier = min(1.45, 0.42 + anchor_strength)
            path_scores[path] = path_scores.get(path, 0.0) + (
                base * warmth_score * anchor_multiplier * (0.78 + len(stage_hits) * 0.07)
            )
    return path_scores


def _weighted_role_overlap(file_roles: set[str], target_roles: set[str]) -> float:
    score = 0.0
    for role in file_roles & target_roles:
        score += 0.45 if role in _SUPPORTING_FILE_ROLES else 1.0
    return score


def _score_file_candidate(
    path: str,
    *,
    prompt_tokens: set[str],
    desired_roles: set[str],
    file_routing_roles: set[str],
    repo_role_scores: dict[str, float],
    precise_path_scores: dict[str, float],
    file_search_scores: dict[str, float],
    repo_map_region_scores: dict[str, float],
    candidate_search_path_scores: dict[str, float],
    repo_topology_scores: dict[str, float],
    candidate_topology_walk_scores: dict[str, float],
    hypothesis_role_scores: dict[str, float],
    coalition_role_scores: dict[str, float],
    hypothesis_negative_role_scores: dict[str, float],
    prefer_source_modules: bool,
    prefer_non_cli_paths: bool,
    prefer_specific_test_anchor: bool,
) -> float:
    basename_overlap, overlap, non_test_bonus = _path_prompt_score(path, prompt_tokens)
    specific_basename_overlap, specific_overlap, generic_overlap = _specific_path_prompt_score(path, prompt_tokens)
    file_roles = infer_file_roles(path)
    desired_overlap = _weighted_role_overlap(file_roles, desired_roles)
    routing_overlap = _weighted_role_overlap(file_roles, file_routing_roles)
    precise_path_bonus = float(precise_path_scores.get(path, 0.0))
    search_warmth_bonus = float(file_search_scores.get(path, 0.0))
    repo_map_region_bonus = float(repo_map_region_scores.get(path, 0.0))
    candidate_search_path_bonus = float(candidate_search_path_scores.get(path, 0.0))
    repo_topology_bonus = float(repo_topology_scores.get(path, 0.0))
    candidate_topology_walk_bonus = float(candidate_topology_walk_scores.get(path, 0.0))
    swarm_role_bonus = sum(hypothesis_role_scores.get(role, 0.0) for role in file_roles)
    coalition_role_bonus = sum(coalition_role_scores.get(role, 0.0) for role in file_roles)
    swarm_negative_role_penalty = sum(hypothesis_negative_role_scores.get(role, 0.0) for role in file_roles)
    repo_role_bonus = float(repo_role_scores.get(path, 0.0))
    clean_path = path.replace("\\", "/")
    if (
        prefer_specific_test_anchor
        and "test_surface" in file_roles
        and specific_basename_overlap == 0
        and specific_overlap == 0
    ):
        repo_role_bonus *= 0.18
        swarm_role_bonus *= 0.55
        coalition_role_bonus *= 0.4
    if prefer_source_modules and "test_surface" in file_roles and basename_overlap < 3:
        swarm_role_bonus *= 0.22
        coalition_role_bonus *= 0.12
    extraneous_support_roles = {
        role for role in (file_roles & _SUPPORTING_FILE_ROLES) if role not in desired_roles and role not in file_routing_roles
    }
    effective_basename_overlap = specific_basename_overlap + (generic_overlap * 0.12)
    effective_overlap = specific_overlap + (generic_overlap * 0.06)
    score = (
        (effective_basename_overlap * 3.0)
        + (effective_overlap * 0.9)
        + (desired_overlap * 2.25)
        + (routing_overlap * 1.15)
        + repo_role_bonus
        + (precise_path_bonus * 1.12)
        + (search_warmth_bonus * 0.95)
        + (repo_map_region_bonus * 0.42)
        + (candidate_search_path_bonus * 0.28)
        + (repo_topology_bonus * 0.78)
        + (candidate_topology_walk_bonus * 0.58)
        + (swarm_role_bonus * 0.82)
        + (coalition_role_bonus * 0.94)
        + (non_test_bonus * 0.05)
    )
    if specific_basename_overlap >= 1 and "test_surface" not in file_roles:
        score += 1.2
    if specific_basename_overlap >= 1 and "test_surface" in file_roles:
        score += 3.0
    score -= len(extraneous_support_roles) * 0.95
    if prefer_source_modules and "test_surface" in file_roles and basename_overlap < 3:
        score -= 1.75
    if prefer_specific_test_anchor and "test_surface" not in file_roles:
        if clean_path.startswith("src/") or "/src/" in clean_path:
            score += 0.95
    if (
        file_roles <= _SUPPORTING_FILE_ROLES
        and desired_overlap == 0
        and specific_basename_overlap == 0
        and specific_overlap == 0
        and repo_role_scores.get(path, 0.0) < 0.4
    ):
        score -= 1.8
    if Path(path).name == "__init__.py" and "init" not in prompt_tokens and "initialize" not in prompt_tokens:
        score -= 2.55
    if (
        "cli_surface" in file_roles
        and "cli_surface" not in desired_roles
        and desired_overlap == 0
        and repo_role_scores.get(path, 0.0) < 0.4
    ):
        score -= 2.1
    if (
        "test_surface" in file_roles
        and specific_basename_overlap == 0
        and specific_overlap == 0
    ):
        score -= 5.0
    if (
        prefer_specific_test_anchor
        and "test_surface" in file_roles
        and specific_basename_overlap == 0
        and specific_overlap == 0
    ):
        score -= 6.1
    if "cli_surface" in file_roles and not (prompt_tokens & _CLI_PROMPT_TOKENS):
        score -= 2.2
    if prefer_non_cli_paths and "cli_surface" in file_roles and "cli_surface" not in desired_roles:
        score -= 1.1
    score -= swarm_negative_role_penalty * 0.72
    if file_roles and file_roles <= _SUPPORTING_FILE_ROLES and desired_overlap == 0 and routing_overlap == 0:
        score -= 1.1
    if "test_surface" in file_roles and "test" not in prompt_tokens and "verify" not in prompt_tokens:
        score -= 0.35
    if Path(path).suffix.lower() in {".md", ".mdx", ".rst", ".txt"} and not {
        "doc",
        "docs",
        "readme",
        "guide",
        "documentation",
    } & prompt_tokens:
        score -= 0.45
    return float(score)


def _rerank_files_with_swarm(
    files: list[str],
    *,
    prompt_tokens: set[str],
    desired_roles: set[str],
    file_routing_roles: set[str],
    repo_role_candidates: list[RepoRoleCandidate],
    hypothesis_swarm: list[dict[str, Any]],
    hypothesis_coalitions: list[dict[str, Any]],
    active_candidates: list[SimilarCodingTrace],
    prompt_constraints: set[str],
    prompt_transmutations: set[str],
    repo_map_regions: list[dict[str, Any]],
    repo_topology_graph: list[dict[str, Any]],
    topology_anchor_files: list[str],
) -> list[str]:
    repo_role_scores = {candidate.path: float(candidate.score) for candidate in repo_role_candidates}
    precise_path_scores: dict[str, float] = {}
    file_search_scores = _collect_candidate_file_search_scores(
        files,
        candidates=active_candidates,
        prompt_tokens=prompt_tokens,
        prompt_constraints=prompt_constraints,
        prompt_roles=desired_roles | file_routing_roles,
        prompt_transmutations=prompt_transmutations,
        repo_role_scores=repo_role_scores,
    )
    repo_map_region_scores = _collect_repo_map_region_scores(files, repo_map_regions)
    candidate_search_path_scores = _collect_candidate_search_path_scores(
        files,
        candidates=active_candidates,
        prompt_roles=desired_roles | file_routing_roles,
        prompt_constraints=prompt_constraints,
    )
    repo_topology_scores = _collect_repo_topology_scores(
        files,
        repo_topology_graph=repo_topology_graph,
        anchor_paths=topology_anchor_files,
        prompt_tokens=prompt_tokens,
        prompt_roles=desired_roles | file_routing_roles,
    )
    candidate_topology_walk_scores = _collect_candidate_topology_walk_scores(
        files,
        candidates=active_candidates,
        prompt_tokens=prompt_tokens,
        prompt_roles=desired_roles | file_routing_roles,
    )
    hypothesis_role_scores = _collect_hypothesis_role_scores(hypothesis_swarm)
    coalition_role_scores: dict[str, float] = {}
    hypothesis_negative_role_scores = _collect_hypothesis_negative_role_scores(hypothesis_swarm)
    file_roles = {path: infer_file_roles(path) for path in files}
    prefer_source_modules = any(
        _path_prompt_score(path, prompt_tokens)[0] >= 2 and "test_surface" not in roles
        for path, roles in file_roles.items()
    )
    prefer_non_cli_paths = any(
        "cli_surface" not in roles and (_weighted_role_overlap(roles, file_routing_roles) >= 1.0 or _path_prompt_score(path, prompt_tokens)[0] >= 1)
        for path, roles in file_roles.items()
    )
    prefer_specific_test_anchor = any(
        "test_surface" in roles and _specific_path_prompt_score(path, prompt_tokens)[0] >= 1
        for path, roles in file_roles.items()
    )
    indexed = list(enumerate(files))
    indexed.sort(
        key=lambda item: (
            _score_file_candidate(
                item[1],
                prompt_tokens=prompt_tokens,
                desired_roles=desired_roles,
                file_routing_roles=file_routing_roles,
                repo_role_scores=repo_role_scores,
                precise_path_scores=precise_path_scores,
                file_search_scores=file_search_scores,
                repo_map_region_scores=repo_map_region_scores,
                candidate_search_path_scores=candidate_search_path_scores,
                repo_topology_scores=repo_topology_scores,
                candidate_topology_walk_scores=candidate_topology_walk_scores,
                hypothesis_role_scores=hypothesis_role_scores,
                coalition_role_scores=coalition_role_scores,
                hypothesis_negative_role_scores=hypothesis_negative_role_scores,
                prefer_source_modules=prefer_source_modules,
                prefer_non_cli_paths=prefer_non_cli_paths,
                prefer_specific_test_anchor=prefer_specific_test_anchor,
            ),
            -item[0],
        ),
        reverse=True,
    )
    return [path for _, path in indexed]


def build_workflow_plan(
    *,
    candidates: list[SimilarCodingTrace],
    summary: WorkflowPriorSummary,
    prompt: str = "",
    repo_root: str = "",
    max_steps: int = 4,
    enable_compile_loop: bool = True,
    c2a_policy_path: str = "",
    disable_c2a_policy: bool = False,
) -> WorkflowPlan:
    prompt_tokens = _tokenize(prompt)
    policy_priors = (
        {
            "matched_tokens": [],
            "constraints": [],
            "roles": [],
            "transmutations": [],
            "preferred_files": [],
            "preferred_regions": [],
            "teacher_rescue_constraints": [],
            "teacher_rescue_transmutations": [],
        }
        if disable_c2a_policy
        else suggest_c2a_policy_priors(prompt=prompt, repo_root=repo_root, explicit_path=c2a_policy_path)
    )
    desired_roles = infer_prompt_roles(prompt)
    current_family = infer_repo_family(repo_root) if repo_root else "unknown"
    family_candidates = [candidate for candidate in candidates if candidate.same_repo or candidate.repo_family_match]
    active_candidates = family_candidates or candidates
    transfer_roles = _select_transfer_roles(active_candidates, desired_roles)
    candidate_constraint_votes = _collect_candidate_constraints(active_candidates)
    candidate_transmutation_votes = _collect_candidate_transmutations(active_candidates)
    predicted_constraints = predict_constraint_tags(
        prompt,
        repo_family=current_family,
        paths=summary.suggested_files,
        commands=summary.suggested_commands,
        candidate_constraints=candidate_constraint_votes,
    )
    predicted_constraints = list(
        dict.fromkeys(
            list(predicted_constraints)
            + list(policy_priors.get("constraints") or [])
            + list(policy_priors.get("teacher_rescue_constraints") or [])
        )
    )
    hypothesis_swarm = build_hypothesis_swarm(
        prompt,
        repo_family=current_family,
        paths=summary.suggested_files,
        commands=summary.suggested_commands,
        candidate_constraints=candidate_constraint_votes,
        candidate_transmutations=candidate_transmutation_votes,
        limit=5,
    )
    hypothesis_swarm = calibrate_hypothesis_swarm(
        hypothesis_swarm,
        repo_root=repo_root,
        prompt=prompt,
        repo_family=current_family,
        paths=summary.suggested_files,
        commands=summary.suggested_commands,
    )
    hypothesis_coalitions = build_hypothesis_coalitions(
        hypothesis_swarm,
        max_agents=3,
        max_coalitions=3,
    )
    swarm_constraints: list[str] = []
    swarm_roles: set[str] = set()
    swarm_negative_constraints: list[str] = []
    swarm_negative_roles: set[str] = set()
    for hypothesis in hypothesis_swarm[:3]:
        if float(hypothesis.get("score") or 0.0) < 0.7:
            continue
        swarm_constraints.extend(str(tag).strip() for tag in (hypothesis.get("predicted_constraints") or []) if str(tag).strip())
        swarm_roles.update(str(role).strip() for role in (hypothesis.get("predicted_roles") or []) if str(role).strip())
    for hypothesis in hypothesis_swarm[:4]:
        if float(hypothesis.get("score") or 0.0) < 0.55:
            continue
        swarm_negative_constraints.extend(
            str(tag).strip() for tag in (hypothesis.get("negative_constraints") or []) if str(tag).strip()
        )
        swarm_negative_roles.update(str(role).strip() for role in (hypothesis.get("negative_roles") or []) if str(role).strip())
    predicted_constraints = list(dict.fromkeys(list(predicted_constraints) + swarm_constraints))
    ruled_out_constraints = [
        tag for tag in dict.fromkeys(swarm_negative_constraints) if tag and tag not in predicted_constraints
    ]
    predicted_roles = infer_roles_from_constraints(predicted_constraints) | swarm_roles | set(
        policy_priors.get("roles") or []
    )
    ruled_out_roles = sorted(role for role in swarm_negative_roles if role and role not in predicted_roles)
    constraint_tags = list(predicted_constraints)
    ranked_files = _merge_preferred_items(
        list(policy_priors.get("preferred_files") or []),
        list(summary.suggested_files),
        limit=10,
    )
    repo_role_candidates: list[RepoRoleCandidate] = []
    repo_map_regions: list[dict[str, Any]] = []
    repo_topology_graph: list[dict[str, Any]] = []
    topology_anchor_files: list[str] = []
    file_routing_roles = _select_file_routing_roles(
        desired_roles=desired_roles,
        transfer_roles=transfer_roles,
        predicted_roles=predicted_roles,
        summary_files=ranked_files,
    )
    if repo_root:
        repo_map_regions = build_repo_map(
            repo_root,
            prompt=prompt,
            predicted_constraints=predicted_constraints,
            desired_roles=file_routing_roles,
            limit=6,
        )
        repo_map_regions = _boost_repo_map_regions(repo_map_regions, list(policy_priors.get("preferred_regions") or []))
        repo_topology_graph = build_repo_topology_graph(
            repo_root,
            prompt=prompt,
            desired_roles=file_routing_roles,
            limit=96,
            neighbor_limit=6,
        )
    if repo_root and file_routing_roles:
        repo_role_candidates = scan_repo_role_matches(repo_root, prompt, file_routing_roles, limit=8)
    if policy_priors.get("preferred_files"):
        policy_candidates = [
            RepoRoleCandidate(
                path=str(path),
                roles=list(policy_priors.get("roles") or []),
                score=max(1.45 - (index * 0.08), 0.7),
            )
            for index, path in enumerate(list(policy_priors.get("preferred_files") or [])[:6])
            if str(path).strip()
        ]
        repo_role_candidates = list(policy_candidates) + list(repo_role_candidates)
    ranked_files = _merge_file_candidates(ranked_files, repo_role_candidates)
    candidate_topology_walk_candidates = _collect_candidate_topology_walk_candidates(
        active_candidates,
        prompt_tokens=prompt_tokens,
        desired_roles=desired_roles | file_routing_roles,
        limit=6,
    )
    if candidate_topology_walk_candidates:
        repo_role_candidates = list(repo_role_candidates) + candidate_topology_walk_candidates
        ranked_files = _merge_file_candidates(ranked_files, candidate_topology_walk_candidates)
    repo_role_scores = {candidate.path: float(candidate.score) for candidate in repo_role_candidates}
    if repo_topology_graph and ranked_files:
        topology_anchor_files = _select_repo_topology_anchor_files(
            ranked_files,
            prompt_tokens=prompt_tokens,
            desired_roles=desired_roles,
            file_routing_roles=file_routing_roles,
            repo_role_scores=repo_role_scores,
        )
        topology_candidates = _collect_repo_topology_candidates(
            repo_topology_graph,
            anchor_paths=topology_anchor_files,
            prompt_tokens=prompt_tokens,
            desired_roles=desired_roles | file_routing_roles,
            limit=8,
        )
        if topology_candidates:
            repo_role_candidates = list(repo_role_candidates) + topology_candidates
            ranked_files = _merge_file_candidates(ranked_files, topology_candidates)
    if repo_map_regions and len(ranked_files) < 8:
        region_samples = [
            RepoRoleCandidate(
                path=str(sample),
                roles=list(region.get("roles") or []),
                score=float(region.get("score") or 0.0) * 0.35,
            )
            for region in repo_map_regions[:3]
            for sample in (region.get("sample_files") or [])[:2]
            if str(sample).strip()
            and _should_include_repo_map_sample(
                str(sample),
                prompt_tokens=prompt_tokens,
                file_routing_roles=file_routing_roles,
            )
        ]
        ranked_files = _merge_file_candidates(ranked_files, region_samples)
    if ranked_files:
        predicted_transmutations = set(summarize_transmutations(predicted_constraints))
        ranked_files = _rerank_files_with_swarm(
            ranked_files,
            prompt_tokens=prompt_tokens,
            desired_roles=desired_roles,
            file_routing_roles=file_routing_roles,
            repo_role_candidates=repo_role_candidates,
            hypothesis_swarm=hypothesis_swarm,
            hypothesis_coalitions=hypothesis_coalitions,
            active_candidates=active_candidates,
            prompt_constraints=set(predicted_constraints),
            prompt_transmutations=predicted_transmutations,
            repo_map_regions=repo_map_regions,
            repo_topology_graph=repo_topology_graph,
            topology_anchor_files=topology_anchor_files,
        )

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
    if not likely_commands:
        for hypothesis in hypothesis_swarm[:3]:
            for command in hypothesis.get("probe_commands") or []:
                clean_command = " ".join(str(command or "").strip().split())
                if clean_command and clean_command not in likely_commands:
                    likely_commands.append(clean_command)
                if clean_command and _is_verification_command(clean_command) and clean_command not in likely_tests:
                    likely_tests.append(clean_command)
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
    for transmutation in list(policy_priors.get("transmutations") or []) + list(
        policy_priors.get("teacher_rescue_transmutations") or []
    ):
        clean_transmutation = str(transmutation).strip()
        if clean_transmutation and clean_transmutation not in transmutations:
            transmutations.append(clean_transmutation)
    for candidate in active_candidates:
        for transmutation in candidate.matched_transmutations:
            if transmutation not in transmutations:
                transmutations.append(transmutation)
    transmutations.sort(key=lambda item: transmutation_specificity(item), reverse=True)
    if current_family != "unknown":
        constraint_tags = list(dict.fromkeys(constraint_tags))

    compiled_hypotheses: list[dict[str, Any]] = []
    validated_trade_path: dict[str, Any] = {}
    residual_constraints: list[str] = []
    if repo_root and enable_compile_loop:
        compiled_hypotheses, validated_trade_path = compile_coding_hypotheses(
            prompt=prompt,
            repo_root=repo_root,
            repo_family=current_family,
            predicted_constraints=list(predicted_constraints),
            transmutations=list(transmutations[:6]),
            role_targets=sorted(file_routing_roles),
            ruled_out_roles=ruled_out_roles,
            ranked_files=ranked_files,
            likely_commands=likely_commands,
            likely_tests=likely_tests,
            repo_role_candidates=repo_role_candidates,
            repo_map_regions=repo_map_regions,
            repo_topology_graph=repo_topology_graph,
            topology_anchor_files=topology_anchor_files,
            hypothesis_swarm=hypothesis_swarm,
        )
        if validated_trade_path:
            validated_supporting_files = list(validated_trade_path.get("supporting_files") or [])
            preferred_validated_files = [
                path
                for path in validated_supporting_files
                if _has_prompt_specific_path_support(path, prompt_tokens)
            ]
            if preferred_validated_files:
                validated_trade_path = dict(validated_trade_path)
                validated_trade_path["prompt_supported_files"] = list(preferred_validated_files[:4])
                ranked_files = _merge_preferred_items(
                    preferred_validated_files,
                    ranked_files,
                    limit=6,
                )
                likely_commands = _merge_preferred_items(
                    list(validated_trade_path.get("supporting_commands") or []),
                    likely_commands,
                    limit=4,
                )
                likely_tests = _merge_preferred_items(
                    [
                        command
                        for command in list(validated_trade_path.get("supporting_commands") or [])
                        if _is_verification_command(command)
                    ],
                    likely_tests,
                    limit=4,
                )
                residual_constraints = [
                    str(item).strip()
                    for item in (validated_trade_path.get("residual_constraints") or [])
                    if str(item).strip()
                ][:6]
            else:
                validated_trade_path = {}

    return WorkflowPlan(
        likely_files=ranked_files[:6],
        likely_commands=likely_commands[:4],
        likely_tests=likely_tests[:4],
        patch_steps=patch_steps[: max(max_steps, 0)],
        source_trace_ids=list(summary.source_trace_ids),
        predicted_constraints=predicted_constraints[:6],
        ruled_out_constraints=ruled_out_constraints[:6],
        constraint_tags=constraint_tags[:6],
        transmutations=transmutations[:6],
        role_targets=sorted(file_routing_roles)[:6],
        ruled_out_roles=ruled_out_roles[:6],
        hypothesis_swarm=hypothesis_swarm,
        hypothesis_coalitions=hypothesis_coalitions,
        compiled_hypotheses=compiled_hypotheses[:4],
        validated_trade_path=validated_trade_path,
        residual_constraints=residual_constraints,
        repo_map_regions=repo_map_regions,
        selected_search_regions=[
            str(item.get("region") or "").strip()
            for item in repo_map_regions[:4]
            if str(item.get("region") or "").strip()
        ],
        topology_anchor_files=topology_anchor_files[:4],
        self_transmutation_boosts={
            "matched_tokens": list(policy_priors.get("matched_tokens") or []),
            "constraints": list(policy_priors.get("constraints") or []),
            "teacher_rescue_constraints": list(policy_priors.get("teacher_rescue_constraints") or []),
            "roles": list(policy_priors.get("roles") or []),
            "transmutations": list(policy_priors.get("transmutations") or []),
            "teacher_rescue_transmutations": list(policy_priors.get("teacher_rescue_transmutations") or []),
            "preferred_files": list(policy_priors.get("preferred_files") or []),
            "preferred_regions": list(policy_priors.get("preferred_regions") or []),
        },
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
    if plan.predicted_constraints:
        lines.append(f"Predicted constraints: {', '.join(plan.predicted_constraints[:6])}")
    if plan.self_transmutation_boosts.get("matched_tokens"):
        lines.append(
            "Self-transmutation tokens: "
            + ", ".join(list(plan.self_transmutation_boosts.get("matched_tokens") or [])[:6])
        )
    if plan.ruled_out_constraints:
        lines.append(f"Ruled-out constraints: {', '.join(plan.ruled_out_constraints[:6])}")
    if plan.topology_anchor_files:
        lines.append(f"Topology anchors: {', '.join(plan.topology_anchor_files[:4])}")
    if plan.hypothesis_swarm:
        labels = [str(item.get("label") or item.get("id") or "").strip() for item in plan.hypothesis_swarm[:3]]
        labels = [label for label in labels if label]
        if labels:
            lines.append(f"Swarm hypotheses: {', '.join(labels)}")
    if plan.validated_trade_path:
        label = str(plan.validated_trade_path.get("label") or "").strip()
        supporting_files = [
            str(item).strip()
            for item in (plan.validated_trade_path.get("prompt_supported_files") or [])
            if str(item).strip()
        ]
        supporting_commands = [
            str(item).strip()
            for item in (plan.validated_trade_path.get("supporting_commands") or [])
            if str(item).strip()
        ]
        if label and supporting_files:
            lines.append(f"Validated trade path: {label}")
        if supporting_files:
            lines.append(f"Validated files: {', '.join(supporting_files[:4])}")
        if supporting_files and supporting_commands:
            lines.append(f"Validated commands: {', '.join(supporting_commands[:4])}")
    if plan.selected_search_regions:
        lines.append(f"Search regions: {', '.join(plan.selected_search_regions[:4])}")
    boosted_files = list(plan.self_transmutation_boosts.get("preferred_files") or [])
    if boosted_files:
        lines.append(f"Self-transmutation files: {', '.join(boosted_files[:4])}")
    if plan.constraint_tags:
        lines.append(f"Constraint tags: {', '.join(plan.constraint_tags[:6])}")
    if plan.residual_constraints:
        lines.append(f"Compile residuals: {', '.join(plan.residual_constraints[:6])}")
    if plan.ruled_out_roles:
        lines.append(f"Ruled-out roles: {', '.join(plan.ruled_out_roles[:4])}")
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
