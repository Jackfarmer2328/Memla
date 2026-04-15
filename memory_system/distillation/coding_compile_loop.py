from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constraint_graph import RepoRoleCandidate, infer_file_roles, infer_roles_from_constraints


_GENERIC_STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "be",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "update",
    "with",
}

_COMMAND_VERBS = (
    "npm ",
    "npm",
    "pnpm",
    "yarn",
    "pytest",
    "py ",
    "python",
    "ruff",
    "cargo",
    "go ",
    "uv ",
    "make",
)
_PATH_SCAN_SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    "dist",
    "build",
}
_DOC_PROMPT_TOKENS = {"doc", "docs", "documentation", "readme", "mkdocs", "architecture", "link", "contact"}
_REFACTOR_PROMPT_TOKENS = {"refactor", "rename", "move", "import", "structure", "directory", "controller", "repository"}
_TYPE_TEST_PROMPT_TOKENS = {"type", "annotation", "fixture", "fixtures", "pep", "format", "unused", "test", "tests"}


@dataclass(frozen=True)
class CompileProbeResult:
    supported_commands: list[str] = field(default_factory=list)
    role_supported_files: list[str] = field(default_factory=list)
    topology_supported_files: list[str] = field(default_factory=list)
    region_supported_files: list[str] = field(default_factory=list)
    residual_constraints: list[str] = field(default_factory=list)
    score: float = 0.0


@dataclass(frozen=True)
class CompiledCodingHypothesis:
    label: str
    source: str
    source_score: float
    constraints: list[str]
    transmutations: list[str]
    role_targets: list[str]
    candidate_files: list[str]
    candidate_commands: list[str]
    probe_plan: list[str]
    probe_result: CompileProbeResult
    calibrated_score: float


@dataclass(frozen=True)
class ValidatedTradePath:
    label: str
    supporting_files: list[str] = field(default_factory=list)
    supporting_commands: list[str] = field(default_factory=list)
    supporting_regions: list[str] = field(default_factory=list)
    residual_constraints: list[str] = field(default_factory=list)
    support_summary: list[str] = field(default_factory=list)
    calibrated_score: float = 0.0


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
        if len(_normalize_token(token)) >= 3 and _normalize_token(token) not in _GENERIC_STOPWORDS
    }


def _dedupe(items: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in items:
        clean = " ".join(str(raw or "").strip().split())
        if not clean:
            continue
        key = clean.lower()
        if key in seen:
            continue
        seen.add(key)
        merged.append(clean)
    return merged


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            clean = " ".join(str(raw or "").strip().split())
            if not clean:
                continue
            key = clean.lower()
            if key in seen:
                continue
            seen.add(key)
            merged.append(clean)
    return merged


def _normalize_path(path: str) -> str:
    return str(path or "").strip().replace("\\", "/")


def _looks_like_command(command: str) -> bool:
    clean = " ".join(str(command or "").strip().split()).lower()
    if not clean:
        return False
    return clean.startswith(_COMMAND_VERBS)


def _infer_repo_commands(repo_root: str) -> list[str]:
    repo = Path(repo_root)
    if not repo.exists():
        return []

    commands: list[str] = []
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        scripts = payload.get("scripts") or {}
        if isinstance(scripts, dict):
            for name in ("build", "lint", "test", "typecheck"):
                if name in scripts:
                    commands.append(f"npm run {name}")

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        deps: list[str] = []
        deps.extend(str(item) for item in ((payload.get("project") or {}).get("dependencies") or []))
        optional = ((payload.get("project") or {}).get("optional-dependencies") or {}).values()
        for items in optional:
            deps.extend(str(item) for item in items)
        dep_blob = " ".join(deps).lower()
        if "pytest" in dep_blob:
            commands.append("pytest")
        if "ruff" in dep_blob:
            commands.append("ruff check .")

    requirements_txt = repo / "requirements.txt"
    if requirements_txt.exists():
        try:
            dep_blob = requirements_txt.read_text(encoding="utf-8").lower()
        except OSError:
            dep_blob = ""
        if "pytest" in dep_blob:
            commands.append("pytest")
        if "ruff" in dep_blob:
            commands.append("ruff check .")

    return _dedupe(commands)


def _command_supported(command: str, repo_commands: list[str]) -> bool:
    clean = " ".join(str(command or "").strip().split()).lower()
    if not clean or not _looks_like_command(clean):
        return False
    repo_set = {item.lower() for item in repo_commands}
    if clean in repo_set:
        return True
    if clean == "pytest" and any(item.startswith("pytest") or item.startswith("py -3 -m pytest") for item in repo_set):
        return True
    if clean.startswith("ruff") and any(item.startswith("ruff") for item in repo_set):
        return True
    if clean.startswith("npm run ") and clean.replace("npm run ", "npm ") in repo_set:
        return True
    if clean == "npm test" and "npm run test" in repo_set:
        return True
    return False


def _collect_region_scores(
    files: list[str],
    repo_map_regions: list[dict[str, Any]],
    role_targets: list[str],
) -> tuple[dict[str, float], dict[str, list[str]]]:
    wanted_roles = set(role_targets)
    region_scores: dict[str, float] = {}
    region_names: dict[str, list[str]] = {}
    for path in files:
        clean_path = _normalize_path(path)
        if not clean_path:
            continue
        path_roles = infer_file_roles(clean_path)
        for region in repo_map_regions[:6]:
            region_name = str(region.get("region") or "").strip()
            if not region_name:
                continue
            sample_files = [_normalize_path(item) for item in (region.get("sample_files") or [])]
            if clean_path not in sample_files and not clean_path.startswith(region_name.rstrip("/") + "/"):
                continue
            region_roles = {str(role).strip() for role in (region.get("roles") or []) if str(role).strip()}
            role_alignment = len((path_roles | region_roles) & wanted_roles)
            bonus = float(region.get("score") or 0.0) + (role_alignment * 0.28)
            region_scores[clean_path] = max(region_scores.get(clean_path, 0.0), bonus)
            region_names.setdefault(clean_path, [])
            if region_name not in region_names[clean_path]:
                region_names[clean_path].append(region_name)
    return region_scores, region_names


def _collect_prompt_path_scores(repo_root: str, prompt: str, *, limit: int = 18) -> dict[str, float]:
    repo = Path(repo_root)
    if not repo.exists():
        return {}

    prompt_tokens = _tokenize(prompt)
    specific_prompt_tokens = prompt_tokens - _GENERIC_STOPWORDS
    if not specific_prompt_tokens:
        return {}

    doc_prompt = bool(prompt_tokens & _DOC_PROMPT_TOKENS)
    refactor_prompt = bool(prompt_tokens & _REFACTOR_PROMPT_TOKENS)
    type_or_test_prompt = bool(prompt_tokens & _TYPE_TEST_PROMPT_TOKENS)

    scored: list[tuple[str, float]] = []
    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _PATH_SCAN_SKIP_DIRS for part in path.parts):
            continue
        try:
            rel_path = _normalize_path(str(path.relative_to(repo)))
        except ValueError:
            rel_path = _normalize_path(str(path))
        if not rel_path:
            continue
        path_tokens = _tokenize(rel_path) | _tokenize(path.stem)
        basename_tokens = _tokenize(path.stem)
        specific_overlap = len(specific_prompt_tokens & path_tokens)
        basename_overlap = len(specific_prompt_tokens & basename_tokens)
        if specific_overlap == 0 and basename_overlap == 0:
            if not (
                doc_prompt and path.suffix.lower() in {".md", ".rst", ".txt"}
                or refactor_prompt and ({"controller", "repository"} & path_tokens)
                or type_or_test_prompt and ("test" in path_tokens or "conftest" in path_tokens)
            ):
                continue
        score = (basename_overlap * 0.72) + (specific_overlap * 0.46)
        if doc_prompt and path.suffix.lower() in {".md", ".rst", ".txt"}:
            score += 0.38
        if refactor_prompt and ({"controller", "repository"} & path_tokens):
            score += 0.42
        if type_or_test_prompt and ("test" in path_tokens or "conftest" in path_tokens):
            score += 0.24
        if score > 0.0:
            scored.append((rel_path, round(score, 4)))

    scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return dict(scored[: max(int(limit), 1)])


def _collect_topology_scores(
    files: list[str],
    repo_topology_graph: list[dict[str, Any]],
    topology_anchor_files: list[str],
    prompt_tokens: set[str],
    role_targets: list[str],
) -> dict[str, float]:
    anchor_set = {_normalize_path(path) for path in topology_anchor_files}
    wanted_roles = set(role_targets)
    index = {
        _normalize_path(item.get("path") or ""): dict(item)
        for item in repo_topology_graph
        if isinstance(item, dict) and _normalize_path(item.get("path") or "")
    }
    scores: dict[str, float] = {}
    for path in files:
        clean_path = _normalize_path(path)
        node = index.get(clean_path) or {}
        if not node:
            continue
        edge_hits = [_normalize_path(item) for item in (node.get("edge_hits") or []) if _normalize_path(item)]
        neighbors = [_normalize_path(item) for item in (node.get("neighbors") or []) if _normalize_path(item)]
        node_roles = {str(role).strip() for role in (node.get("roles") or []) if str(role).strip()}
        path_roles = infer_file_roles(clean_path)
        score = 0.0
        if anchor_set and (anchor_set & set(edge_hits) or anchor_set & set(neighbors)):
            score += 0.8
        token_overlap = len(prompt_tokens & (_tokenize(clean_path) | _tokenize(Path(clean_path).stem)))
        if token_overlap:
            score += min(0.48, token_overlap * 0.18)
        score += len((path_roles | node_roles) & wanted_roles) * 0.22
        if score > 0.0:
            scores[clean_path] = score
    return scores


def _rank_candidate_files(
    *,
    prompt: str,
    role_targets: list[str],
    ruled_out_roles: list[str],
    ranked_files: list[str],
    repo_role_candidates: list[RepoRoleCandidate],
    prompt_path_scores: dict[str, float],
    region_scores: dict[str, float],
    topology_scores: dict[str, float],
) -> list[str]:
    prompt_tokens = _tokenize(prompt)
    wanted_roles = set(role_targets)
    blocked_roles = set(ruled_out_roles)
    candidate_scores: dict[str, float] = {}
    base_files = _merge_unique(
        [_normalize_path(path) for path in ranked_files],
        [_normalize_path(candidate.path) for candidate in repo_role_candidates],
        list(prompt_path_scores.keys()),
    )
    repo_role_score_map = {_normalize_path(candidate.path): float(candidate.score) for candidate in repo_role_candidates}
    for path in base_files:
        if not path:
            continue
        path_roles = infer_file_roles(path)
        path_tokens = _tokenize(path) | _tokenize(Path(path).stem)
        role_overlap = len(path_roles & wanted_roles)
        prompt_overlap = len(path_tokens & prompt_tokens)
        blocked_overlap = len(path_roles & blocked_roles)
        score = (
            repo_role_score_map.get(path, 0.0)
            + (role_overlap * 0.78)
            + (prompt_overlap * 0.18)
            + prompt_path_scores.get(path, 0.0)
            + region_scores.get(path, 0.0)
            + topology_scores.get(path, 0.0)
        )
        score -= blocked_overlap * 0.55
        if path_roles and path_roles <= {"test_surface"} and "test" not in prompt_tokens and "verify" not in prompt_tokens:
            score -= 0.45
        candidate_scores[path] = score
    ranked = sorted(candidate_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
    return [path for path, score in ranked if score > -0.2][:6]


def _probe_hypothesis(
    *,
    candidate_files: list[str],
    candidate_commands: list[str],
    role_targets: list[str],
    region_scores: dict[str, float],
    topology_scores: dict[str, float],
    repo_commands: list[str],
) -> CompileProbeResult:
    wanted_roles = set(role_targets)
    supported_commands = [command for command in candidate_commands if _command_supported(command, repo_commands)]
    role_supported_files = [
        path for path in candidate_files if infer_file_roles(path) & wanted_roles
    ]
    topology_supported_files = [path for path in candidate_files if topology_scores.get(path, 0.0) > 0.0]
    region_supported_files = [path for path in candidate_files if region_scores.get(path, 0.0) > 0.0]

    residuals: list[str] = []
    if not candidate_files:
        residuals.append("file_localization_gap")
    if not role_supported_files:
        residuals.append("role_mapping_gap")
    if candidate_files and not topology_supported_files:
        residuals.append("ownership_resolution_gap")
    if not supported_commands:
        residuals.append("verification_gap")
    if candidate_files and not region_supported_files:
        residuals.append("subsystem_grounding_gap")

    score = 0.0
    score += min(len(role_supported_files), 3) * 0.22
    score += min(len(topology_supported_files), 3) * 0.24
    score += min(len(region_supported_files), 3) * 0.12
    score += min(len(supported_commands), 3) * 0.18
    if candidate_files:
        score += 0.08
    score -= len(residuals) * 0.09

    return CompileProbeResult(
        supported_commands=supported_commands[:4],
        role_supported_files=role_supported_files[:4],
        topology_supported_files=topology_supported_files[:4],
        region_supported_files=region_supported_files[:4],
        residual_constraints=_dedupe(residuals),
        score=round(score, 4),
    )


def compile_coding_hypotheses(
    *,
    prompt: str,
    repo_root: str,
    repo_family: str,
    predicted_constraints: list[str],
    transmutations: list[str],
    role_targets: list[str],
    ruled_out_roles: list[str],
    ranked_files: list[str],
    likely_commands: list[str],
    likely_tests: list[str],
    repo_role_candidates: list[RepoRoleCandidate],
    repo_map_regions: list[dict[str, Any]],
    repo_topology_graph: list[dict[str, Any]],
    topology_anchor_files: list[str],
    hypothesis_swarm: list[dict[str, Any]],
    limit: int = 4,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repo_commands = _infer_repo_commands(repo_root)
    prompt_tokens = _tokenize(prompt)
    prompt_path_scores = _collect_prompt_path_scores(repo_root, prompt)

    base_commands = [
        command
        for command in _merge_unique(likely_commands, likely_tests, repo_commands)
        if _looks_like_command(command)
    ]
    hypothesis_specs: list[dict[str, Any]] = [
        {
            "label": "Primary Trade Path",
            "source": "primary",
            "score": 1.0,
            "predicted_constraints": list(predicted_constraints),
            "predicted_transmutations": list(transmutations),
            "predicted_roles": list(role_targets),
            "probe_commands": list(base_commands),
        }
    ]
    for hypothesis in hypothesis_swarm[:3]:
        hypothesis_specs.append(
            {
                "label": str(hypothesis.get("label") or hypothesis.get("id") or "Swarm Hypothesis").strip(),
                "source": "swarm",
                "score": float(hypothesis.get("calibrated_score") or hypothesis.get("score") or 0.0),
                "predicted_constraints": _merge_unique(
                    list(predicted_constraints),
                    [str(tag).strip() for tag in (hypothesis.get("predicted_constraints") or []) if str(tag).strip()],
                ),
                "predicted_transmutations": _merge_unique(
                    list(transmutations),
                    [str(item).strip() for item in (hypothesis.get("predicted_transmutations") or []) if str(item).strip()],
                ),
                "predicted_roles": _merge_unique(
                    list(role_targets),
                    [str(role).strip() for role in (hypothesis.get("predicted_roles") or []) if str(role).strip()],
                ),
                "probe_commands": _merge_unique(
                    base_commands,
                    [str(command).strip() for command in (hypothesis.get("probe_commands") or []) if str(command).strip()],
                ),
            }
        )

    compiled: list[CompiledCodingHypothesis] = []
    for raw in hypothesis_specs[: max(int(limit), 1)]:
        merged_constraints = _dedupe(list(raw.get("predicted_constraints") or []))
        merged_roles = _merge_unique(
            list(raw.get("predicted_roles") or []),
            sorted(infer_roles_from_constraints(merged_constraints)),
        )
        region_scores, region_names = _collect_region_scores(ranked_files, repo_map_regions, merged_roles)
        topology_scores = _collect_topology_scores(
            ranked_files,
            repo_topology_graph,
            topology_anchor_files,
            prompt_tokens,
            merged_roles,
        )
        candidate_files = _rank_candidate_files(
            prompt=prompt,
            role_targets=merged_roles,
            ruled_out_roles=ruled_out_roles,
            ranked_files=ranked_files,
            repo_role_candidates=repo_role_candidates,
            prompt_path_scores=prompt_path_scores,
            region_scores=region_scores,
            topology_scores=topology_scores,
        )
        candidate_commands = _dedupe(list(raw.get("probe_commands") or []))
        probe_plan = [
            "Check whether compiled commands are actually supported by the repo.",
            "Check whether compiled roles map onto concrete candidate files.",
            "Check whether topology or region evidence supports the compiled files.",
        ]
        probe_result = _probe_hypothesis(
            candidate_files=candidate_files,
            candidate_commands=candidate_commands,
            role_targets=merged_roles,
            region_scores=region_scores,
            topology_scores=topology_scores,
            repo_commands=repo_commands,
        )
        calibrated_score = round(float(raw.get("score") or 0.0) + float(probe_result.score), 4)
        compiled.append(
            CompiledCodingHypothesis(
                label=str(raw.get("label") or "Compiled Hypothesis").strip(),
                source=str(raw.get("source") or "primary").strip(),
                source_score=round(float(raw.get("score") or 0.0), 4),
                constraints=merged_constraints,
                transmutations=_dedupe(list(raw.get("predicted_transmutations") or []))[:6],
                role_targets=merged_roles[:6],
                candidate_files=candidate_files[:6],
                candidate_commands=candidate_commands[:4],
                probe_plan=probe_plan,
                probe_result=probe_result,
                calibrated_score=calibrated_score,
            )
        )

    compiled.sort(
        key=lambda item: (
            item.calibrated_score,
            item.probe_result.score,
            len(item.probe_result.topology_supported_files),
            len(item.probe_result.supported_commands),
            item.label,
        ),
        reverse=True,
    )
    top = compiled[0] if compiled else None
    if top is None:
        return [], {}

    top_region_scores, top_region_names = _collect_region_scores(top.candidate_files, repo_map_regions, top.role_targets)
    supporting_files = _merge_unique(
        top.probe_result.topology_supported_files,
        top.probe_result.role_supported_files,
        top.probe_result.region_supported_files,
        top.candidate_files,
    )[:6]
    supporting_regions = _dedupe(
        [
            region
            for path in supporting_files
            for region in top_region_names.get(_normalize_path(path), [])
        ]
    )[:4]
    support_summary = _dedupe(
        [
            f"validated {len(top.probe_result.supported_commands)} repo-supported commands"
            if top.probe_result.supported_commands
            else "",
            f"validated {len(top.probe_result.topology_supported_files)} ownership-backed files"
            if top.probe_result.topology_supported_files
            else "",
            f"grounded {len(top.probe_result.region_supported_files)} files in repo regions"
            if top.probe_result.region_supported_files
            else "",
        ]
    )
    validated = ValidatedTradePath(
        label=top.label,
        supporting_files=supporting_files,
        supporting_commands=top.probe_result.supported_commands[:4],
        supporting_regions=supporting_regions,
        residual_constraints=top.probe_result.residual_constraints[:6],
        support_summary=support_summary,
        calibrated_score=top.calibrated_score,
    )
    serialized_hypotheses = [
        {
            "label": item.label,
            "source": item.source,
            "source_score": item.source_score,
            "constraints": list(item.constraints),
            "transmutations": list(item.transmutations),
            "role_targets": list(item.role_targets),
            "candidate_files": list(item.candidate_files),
            "candidate_commands": list(item.candidate_commands),
            "probe_plan": list(item.probe_plan),
            "probe_result": {
                "supported_commands": list(item.probe_result.supported_commands),
                "role_supported_files": list(item.probe_result.role_supported_files),
                "topology_supported_files": list(item.probe_result.topology_supported_files),
                "region_supported_files": list(item.probe_result.region_supported_files),
                "residual_constraints": list(item.probe_result.residual_constraints),
                "score": item.probe_result.score,
            },
            "calibrated_score": item.calibrated_score,
        }
        for item in compiled
    ]
    serialized_validated = {
        "label": validated.label,
        "supporting_files": list(validated.supporting_files),
        "supporting_commands": list(validated.supporting_commands),
        "supporting_regions": list(validated.supporting_regions),
        "residual_constraints": list(validated.residual_constraints),
        "support_summary": list(validated.support_summary),
        "calibrated_score": validated.calibrated_score,
    }
    return serialized_hypotheses, serialized_validated
