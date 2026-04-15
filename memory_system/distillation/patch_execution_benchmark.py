from __future__ import annotations

import argparse
from collections.abc import Callable
from contextlib import contextmanager
import difflib
import json
import os
import re
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .coding_proxy import CODING_BASE_SYSTEM, CodingSession
from .git_history_cases import _extract_diff_excerpt
from .workflow_planner import render_workflow_plan_block
from ..ollama_client import ChatMessage, UniversalLLMClient


PROJECT_ROOT = Path(__file__).resolve().parents[2]
_PATCH_SCAN_SKIP_DIRS = {
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
_PATCH_GENERIC_TOKENS = {
    "the",
    "and",
    "for",
    "with",
    "update",
    "refactor",
    "fix",
    "implement",
    "project",
    "template",
    "code",
    "test",
    "tests",
    "file",
    "files",
}
_MAX_STRUCTURED_ANCHOR_CHARS = 120
_MAX_STRUCTURED_BEFORE_CHARS = 240


@dataclass(frozen=True)
class PatchExecutionCase:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    commit_sha: str
    changed_files: list[str]
    diff_excerpt: list[str]


@dataclass(frozen=True)
class PatchLaneResult:
    answer: str
    patch_text: str
    patch_files: list[str]
    context_files: list[str]
    file_recall: float
    diff_recall: float
    apply_check_passed: bool
    applied: bool
    command_success_rate: float
    semantic_command_success_rate: float
    command_results: list[dict[str, Any]]
    diagnostic_sheet: dict[str, Any] = field(default_factory=dict)
    active_repair_lesson: dict[str, Any] = field(default_factory=dict)
    lesson_applied: bool = False
    lesson_mastered: bool = False
    apply_check_stdout_tail: str = ""
    apply_check_stderr_tail: str = ""
    apply_stdout_tail: str = ""
    apply_stderr_tail: str = ""
    residual_constraints: list[str] = field(default_factory=list)
    iterations_used: int = 1
    iteration_trace: list[dict[str, Any]] = field(default_factory=list)


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
        for token in re.findall(r"[A-Za-z0-9]+", text or "")
        if len(_normalize_token(token)) >= 3 and _normalize_token(token) not in _PATCH_GENERIC_TOKENS
    }


def _score_diff_overlap(predicted_lines: list[str], expected_lines: list[str]) -> float:
    if not expected_lines:
        return 1.0
    predicted_tokens = [_tokenize(line) for line in predicted_lines if _tokenize(line)]
    expected_tokens = [_tokenize(line) for line in expected_lines if _tokenize(line)]
    if not expected_tokens:
        return 0.0
    matched = 0
    for expected in expected_tokens:
        if any((len(expected & candidate) / max(len(expected), 1)) >= 0.5 for candidate in predicted_tokens):
            matched += 1
    return matched / max(len(expected_tokens), 1)


def _resolve_repo_root(raw_repo_root: str) -> Path:
    candidate = Path(raw_repo_root)
    if candidate.is_absolute():
        return candidate.resolve()
    return (PROJECT_ROOT / candidate).resolve()


def load_patch_cases(pack_path: str, *, split: str = "unseen", limit: int = 0) -> tuple[Path, list[PatchExecutionCase]]:
    pack_file = Path(pack_path)
    if not pack_file.is_absolute():
        pack_file = (PROJECT_ROOT / pack_file).resolve()
    payload = json.loads(pack_file.read_text(encoding="utf-8"))
    repo_root = _resolve_repo_root(str(payload.get("repo_root") or ""))
    records = list(payload.get(f"{split}_cases") or [])
    if limit > 0:
        records = records[:limit]
    cases: list[PatchExecutionCase] = []
    for row in records:
        sha = str(row.get("commit_sha") or "").strip()
        if not sha:
            continue
        diff_text = _run_git(repo_root, ["show", "--format=", "--unified=0", sha, "--", "."])
        cases.append(
            PatchExecutionCase(
                prompt=str(row.get("prompt") or ""),
                expected_files=_normalize(list(row.get("expected_files") or [])),
                expected_commands=_normalize(list(row.get("expected_commands") or [])),
                commit_sha=sha,
                changed_files=_normalize(list(row.get("changed_files") or [])),
                diff_excerpt=_extract_diff_excerpt(diff_text),
            )
        )
    return repo_root, cases


def _run_git(repo_root: Path, args: list[str], *, check: bool = True) -> str:
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={repo_root.resolve()}", "-C", str(repo_root), *args],
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return proc.stdout


def _build_worktree(repo_root: Path, commit_sha: str, dest: Path) -> tuple[str, Path]:
    parent_sha = _run_git(repo_root, ["rev-parse", f"{commit_sha}^"]).strip()
    subprocess.run(
        ["git", "-c", f"safe.directory={repo_root.resolve()}", "-C", str(repo_root), "worktree", "add", "--detach", str(dest), parent_sha],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return parent_sha, dest


def _remove_worktree(repo_root: Path, dest: Path) -> None:
    subprocess.run(
        ["git", "-c", f"safe.directory={repo_root.resolve()}", "-C", str(repo_root), "worktree", "remove", "--force", str(dest)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _candidate_local_bin_paths(repo_root: Path) -> list[str]:
    paths: list[str] = []
    current = repo_root.resolve()
    seen: set[str] = set()
    while True:
        candidate = current / "node_modules" / ".bin"
        if candidate.exists() and candidate.is_dir():
            normalized = str(candidate)
            if normalized not in seen:
                seen.add(normalized)
                paths.append(normalized)
        if current.parent == current:
            break
        current = current.parent
    return paths


def _has_local_node_modules(repo_root: Path) -> bool:
    return (repo_root / "node_modules").exists()


def _select_dependency_bootstrap_command(repo_root: Path, commands: list[str]) -> str | None:
    normalized_commands = " ".join(str(command or "").lower() for command in commands)
    if "npm " not in normalized_commands:
        return None
    if not (repo_root / "package.json").exists():
        return None
    if (repo_root / "package-lock.json").exists():
        return "npm ci --ignore-scripts"
    return "npm install --ignore-scripts"


def _bootstrap_worktree_dependencies(repo_root: Path, commands: list[str]) -> dict[str, Any] | None:
    if (repo_root / "node_modules").exists():
        return None
    bootstrap_command = _select_dependency_bootstrap_command(repo_root, commands)
    if not bootstrap_command:
        return None
    env = os.environ.copy()
    local_bins = _candidate_local_bin_paths(repo_root)
    if local_bins:
        env["PATH"] = os.pathsep.join(local_bins + [env.get("PATH") or ""])
    completed = subprocess.run(
        bootstrap_command,
        cwd=str(repo_root),
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=1800,
        check=False,
        env=env,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "Dependency bootstrap failed for worktree:\n"
            + _trim_tail((completed.stdout or "") + "\n" + (completed.stderr or ""), limit=2400)
        )
    return {
        "command": bootstrap_command,
        "returncode": int(completed.returncode),
        "stdout_tail": _trim_tail(completed.stdout or "", limit=1200),
        "stderr_tail": _trim_tail(completed.stderr or "", limit=1200),
    }


def _classify_command_blockage(feedback_text: str) -> tuple[bool, str]:
    lower_feedback = (feedback_text or "").lower()
    if any(
        token in lower_feedback
        for token in (
            "is not recognized as an internal or external command",
            "command not found",
            "could not determine executable to run",
        )
    ):
        return True, "missing_local_tooling"
    if "option 'importsnotusedasvalues' has been removed" in lower_feedback:
        return True, "toolchain_version_drift"
    if ("node_modules/" in lower_feedback or "node_modules\\" in lower_feedback) and any(
        token in lower_feedback
        for token in (
            "error ts",
            "cannot find module",
            "type '",
            "does not satisfy the constraint",
        )
    ):
        return True, "external_dependency_typing_drift"
    return False, ""


def _scan_prompt_candidate_files(repo_root: Path, prompt: str, *, limit: int = 6) -> list[str]:
    prompt_tokens = _tokenize(prompt)
    scored: list[tuple[str, float]] = []
    for path in repo_root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in _PATCH_SCAN_SKIP_DIRS for part in path.parts):
            continue
        try:
            rel_path = path.relative_to(repo_root).as_posix()
        except ValueError:
            rel_path = path.as_posix()
        path_tokens = _tokenize(rel_path) | _tokenize(path.stem)
        overlap = len(prompt_tokens & path_tokens)
        content_overlap = 0
        if overlap == 0:
            try:
                blob = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                blob = ""
            if blob:
                content_overlap = len(prompt_tokens & _tokenize(blob[:4000]))
        if overlap == 0 and content_overlap == 0:
            continue
        basename_overlap = len(prompt_tokens & _tokenize(path.stem))
        suffix_bonus = 0.2 if path.suffix.lower() in {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".toml", ".json"} else 0.0
        scored.append(
            (
                rel_path,
                (basename_overlap * 0.7)
                + (overlap * 0.45)
                + (content_overlap * 0.18)
                + suffix_bonus,
            )
        )
    scored.sort(key=lambda item: (item[1], item[0]), reverse=True)
    return [path for path, _ in scored[: max(int(limit), 1)]]


def _repo_has_file(repo_root: Path, rel_path: str) -> bool:
    target = (repo_root / str(rel_path or "").replace("\\", "/").lstrip("./")).resolve()
    try:
        target.relative_to(repo_root.resolve())
    except ValueError:
        return False
    return target.exists() and target.is_file()


def _is_source_owner_path(rel_path: str) -> bool:
    path_lower = str(rel_path or "").lower()
    if _is_docs_like_path(path_lower) or _is_example_like_path(path_lower):
        return False
    suffix = Path(path_lower).suffix.lower()
    if suffix not in {".py", ".ts", ".tsx", ".js", ".jsx"}:
        return False
    return path_lower.startswith(("src/", "lib/")) or "/src/" in path_lower or "/lib/" in path_lower


def _is_test_path(rel_path: str) -> bool:
    path_lower = str(rel_path or "").lower()
    return (
        path_lower.startswith("test/")
        or path_lower.startswith("tests/")
        or "/test/" in path_lower
        or "/tests/" in path_lower
        or ".test." in path_lower
        or ".spec." in path_lower
    )


def _prioritize_code_context_paths(
    repo_root: Path,
    prompt: str,
    paths: list[str],
    *,
    limit: int = 6,
) -> list[str]:
    existing = [path for path in _normalize(list(paths or [])) if _repo_has_file(repo_root, path)]
    if not existing:
        return []

    primary = [path for path in existing if not _is_docs_like_path(path) and not _is_example_like_path(path)]
    secondary = [path for path in existing if path not in primary]
    merged = list(primary)
    merged_lower = {path.lower() for path in merged}

    source_scan = [
        path
        for path in _scan_prompt_candidate_files(repo_root, prompt, limit=max(limit * 2, 8))
        if _is_source_owner_path(path) and _repo_has_file(repo_root, path)
    ]
    canonical_source_candidates = [
        "src/index.ts",
        "src/index.tsx",
        "src/index.js",
        "src/index.jsx",
        "src/main.ts",
        "src/main.js",
        "lib/index.ts",
        "lib/index.js",
    ]
    manifest_candidates = ["package.json", "tsconfig.json"]

    if not any(_is_source_owner_path(path) for path in merged):
        for candidate in source_scan + canonical_source_candidates:
            if not _repo_has_file(repo_root, candidate):
                continue
            clean = candidate.replace("\\", "/").lstrip("./")
            if clean.lower() in merged_lower:
                continue
            merged.append(clean)
            merged_lower.add(clean.lower())
            if any(_is_source_owner_path(path) for path in merged):
                break

    if any(_is_test_path(path) for path in merged):
        for candidate in manifest_candidates:
            if not _repo_has_file(repo_root, candidate):
                continue
            if candidate.lower() in merged_lower:
                continue
            merged.append(candidate)
            merged_lower.add(candidate.lower())

    for path in secondary:
        if path.lower() in merged_lower:
            continue
        merged.append(path)
        merged_lower.add(path.lower())

    return merged[: max(int(limit), 1)]


def _render_line_window(blob: str, *, center_line: int, radius: int = 6) -> str:
    lines = blob.splitlines()
    if not lines:
        return ""
    start = max(1, int(center_line) - max(int(radius), 0))
    end = min(len(lines), int(center_line) + max(int(radius), 0))
    return "\n".join(f"{idx:>4} | {lines[idx - 1]}" for idx in range(start, end + 1))


def _read_file_context(
    repo_root: Path,
    paths: list[str],
    *,
    max_chars_per_file: int = 2500,
    focus_map: dict[str, list[dict[str, Any]]] | None = None,
) -> list[tuple[str, str]]:
    context: list[tuple[str, str]] = []
    for rel_path in _normalize(paths):
        target = repo_root / rel_path
        if not target.exists() or not target.is_file():
            continue
        try:
            blob = target.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        focus_entries = list((focus_map or {}).get(rel_path) or [])
        focus_sections: list[str] = []
        for entry in focus_entries[:2]:
            line_number = int(entry.get("line") or 0)
            if line_number <= 0:
                continue
            numbered = _render_line_window(blob, center_line=line_number, radius=5)
            raw_lines = blob.splitlines()
            start = max(1, line_number - 2)
            end = min(len(raw_lines), line_number + 2)
            exact_excerpt = "\n".join(raw_lines[start - 1:end])
            focus_sections.append(
                "\n".join(
                    [
                        f"# Diagnostic focus: line {line_number}",
                        numbered,
                        "# Exact excerpt for anchors:",
                        exact_excerpt,
                    ]
                ).strip()
            )
        if focus_sections:
            rendered = "\n\n".join(section for section in focus_sections if section)
        else:
            rendered = blob
            if len(rendered) > max_chars_per_file:
                rendered = rendered[:max_chars_per_file] + "\n# [truncated]"
        context.append((rel_path, rendered))
    return context


def _trim_tail(text: str, *, limit: int = 1600) -> str:
    clean = (text or "").strip()
    if len(clean) <= limit:
        return clean
    return clean[-limit:]


def _extract_repo_relative_paths(repo_root: Path, text: str) -> list[str]:
    paths: list[str] = []
    for raw_match in re.findall(
        r"([A-Za-z0-9_./\\\\-]+\.(?:py|ts|tsx|js|jsx|json|toml|md|ya?ml))",
        text or "",
        re.IGNORECASE,
    ):
        candidate = raw_match.replace("\\", "/").lstrip("./")
        target = (repo_root / candidate).resolve()
        try:
            rel_path = target.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            continue
        if target.exists() and target.is_file():
            paths.append(rel_path)
    return _normalize(paths)


def _extract_diagnostic_entries(
    repo_root: Path,
    text: str,
    *,
    source: str,
    command: str = "",
    blocked: bool = False,
    blocked_reason: str = "",
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for match in re.finditer(
        r"(?P<file>[A-Za-z0-9_./\\\\-]+\.(?:py|ts|tsx|js|jsx|json|toml|md|ya?ml))\((?P<line>\d+),(?P<column>\d+)\):\s*error\s+(?P<code>[A-Z]{2,}\d+):\s*(?P<message>.+)",
        text or "",
        re.IGNORECASE,
    ):
        rel_files = _extract_repo_relative_paths(repo_root, match.group("file"))
        if not rel_files:
            continue
        entries.append(
            {
                "source": source,
                "command": command,
                "kind": "compiler_error",
                "file": rel_files[0],
                "line": int(match.group("line")),
                "column": int(match.group("column")),
                "code": match.group("code"),
                "message": match.group("message").strip(),
                "blocked": bool(blocked),
                "blocked_reason": blocked_reason,
            }
        )
    for match in re.finditer(
        r"patch failed:\s*(?P<file>[A-Za-z0-9_./\\\\-]+\.(?:py|ts|tsx|js|jsx|json|toml|md|ya?ml)):(?P<line>\d+)",
        text or "",
        re.IGNORECASE,
    ):
        rel_files = _extract_repo_relative_paths(repo_root, match.group("file"))
        if not rel_files:
            continue
        entries.append(
            {
                "source": source,
                "command": command,
                "kind": "patch_failure",
                "file": rel_files[0],
                "line": int(match.group("line")),
                "column": None,
                "code": "",
                "message": "Patch failed to apply against the expected live context.",
                "blocked": bool(blocked),
                "blocked_reason": blocked_reason,
            }
        )
    seen_files = {str(entry.get("file") or "").lower() for entry in entries}
    for rel_path in _extract_repo_relative_paths(repo_root, text):
        if rel_path.lower() in seen_files:
            continue
        entries.append(
            {
                "source": source,
                "command": command,
                "kind": "referenced_path",
                "file": rel_path,
                "line": None,
                "column": None,
                "code": "",
                "message": "Referenced in validation feedback.",
                "blocked": bool(blocked),
                "blocked_reason": blocked_reason,
            }
        )
    return entries


def _summarize_diagnostic_entry(entry: dict[str, Any]) -> str:
    file_part = str(entry.get("file") or "")
    line_number = entry.get("line")
    location = f"{file_part}:{line_number}" if file_part and line_number else file_part or "repo"
    code = str(entry.get("code") or "").strip()
    message = str(entry.get("message") or "").strip()
    if code and message:
        return f"{location} {code} {message}"
    if message:
        return f"{location} {message}"
    return location


def _build_diagnostic_sheet(
    *,
    repo_root: Path,
    prompt: str,
    patch_files: list[str],
    apply_feedback_text: str,
    command_results: list[dict[str, Any]],
    expected_files_missing_in_parent: list[str] | None = None,
) -> dict[str, Any]:
    missing_in_parent = [
        path
        for path in _normalize(list(expected_files_missing_in_parent or []))
        if not _repo_has_file(repo_root, path)
    ]
    if missing_in_parent:
        entries = [
            {
                "source": "benchmark_hint",
                "command": "",
                "kind": "missing_target_file",
                "file": path,
                "line": None,
                "column": None,
                "code": "CREATE_FILE",
                "message": "Expected change introduces a new file not present in the parent snapshot.",
                "blocked": False,
                "blocked_reason": "",
            }
            for path in missing_in_parent[:4]
        ]
        return {
            "task_type": "create_file",
            "summary": "New file required: " + ", ".join(missing_in_parent[:4]),
            "entries": entries,
            "target_files": missing_in_parent[:4],
            "focus_map": {},
            "environment_blocked": False,
        }

    entries: list[dict[str, Any]] = []
    entries.extend(
        _extract_diagnostic_entries(
            repo_root,
            apply_feedback_text,
            source="apply_feedback",
        )
    )
    for item in command_results:
        feedback_text = f"{item.get('stdout_tail') or ''}\n{item.get('stderr_tail') or ''}"
        entries.extend(
            _extract_diagnostic_entries(
                repo_root,
                feedback_text,
                source="command_feedback",
                command=str(item.get("command") or ""),
                blocked=bool(item.get("blocked")),
                blocked_reason=str(item.get("blocked_reason") or ""),
            )
        )
    target_files = _normalize(
        list(patch_files or [])
        + [str(entry.get("file") or "") for entry in entries if entry.get("file")]
        + _scan_prompt_candidate_files(
            repo_root,
            " ".join(
                part
                for part in [
                    prompt,
                    apply_feedback_text,
                    " ".join(_summarize_diagnostic_entry(entry) for entry in entries[:3]),
                ]
                if part
            ),
            limit=4,
        )
    )
    focus_map: dict[str, list[dict[str, Any]]] = {}
    for entry in entries:
        rel_path = str(entry.get("file") or "").strip()
        if not rel_path:
            continue
        focus_map.setdefault(rel_path, []).append(entry)
    environment_blocked = bool(command_results) and all(bool(item.get("blocked")) for item in command_results)
    summary_bits = []
    if entries:
        summary_bits.append(_summarize_diagnostic_entry(entries[0]))
    elif environment_blocked:
        summary_bits.append("verification blocked by external environment drift")
    elif patch_files:
        summary_bits.append(f"repair the latest patch target: {patch_files[0]}")
    return {
        "summary": "; ".join(summary_bits) if summary_bits else "No concrete diagnostics extracted yet.",
        "entries": entries[:6],
        "target_files": target_files[:4],
        "focus_map": {path: details[:2] for path, details in focus_map.items()},
        "environment_blocked": environment_blocked,
    }


def _derive_active_repair_lesson(
    *,
    residual_constraints: list[str],
    diagnostic_sheet: dict[str, Any],
    previous_lesson: dict[str, Any] | None = None,
) -> dict[str, Any]:
    target_files = list(diagnostic_sheet.get("target_files") or [])
    entries = list(diagnostic_sheet.get("entries") or [])
    title = "Repair the top diagnostic first"
    description = "Make the smallest grounded edit that resolves the strongest current failure signal."
    practice_question = "Which single failure is most concrete right now, and what smallest edit addresses it?"
    if str(diagnostic_sheet.get("task_type") or "").strip() == "create_file":
        title = "Create the missing file"
        description = "This task introduces a new file. Create one minimal sibling file at the hinted path instead of patching an existing file."
        practice_question = "What is the smallest valid new file you can add at the target path?"
    elif any(item in residual_constraints for item in ("edit_anchor_not_found", "hunk_context_mismatch")):
        title = "Anchor to exact live code"
        description = "Use the exact existing snippet or focused lines from the real target file before changing anything."
        practice_question = "Which exact live lines are you replacing in the target file?"
    elif "wrong_file_path_or_missing_target" in residual_constraints:
        title = "Repair the owning file"
        description = "Stop guessing paths. Patch the real owning file named by the diagnostics or strongest repo clue."
        practice_question = "Which real repo file actually owns this behavior?"
    elif any(item in residual_constraints for item in ("missing_structured_edits", "invalid_structured_edit_json", "missing_patch_output")):
        title = "Return one grounded edit"
        description = "Emit one minimal JSON edit against one concrete file from context before attempting anything broader."
        practice_question = "What is the smallest valid edit you can prove from the current context?"
    elif entries:
        top_entry = entries[0]
        location = str(top_entry.get("file") or "repo")
        if top_entry.get("line"):
            location = f"{location}:{top_entry.get('line')}"
        code = str(top_entry.get("code") or "").strip()
        title = f"Fix {code or 'the top diagnostic'}"
        description = f"Resolve the concrete diagnostic at {location} before making broader edits."
        practice_question = f"What smallest edit resolves the diagnostic at {location}?"
    elif diagnostic_sheet.get("environment_blocked"):
        title = "Hold course through environment drift"
        description = "Verification is blocked by external drift. Keep the code edit minimal and grounded instead of chasing the environment."
        practice_question = "What is the smallest grounded code edit independent of the blocked environment?"
    attempts = 1
    if previous_lesson and str(previous_lesson.get("title") or "") == title:
        attempts = int(previous_lesson.get("attempts") or 0) + 1
    return {
        "title": title,
        "description": description,
        "practice_question": practice_question,
        "target_files": target_files[:3],
        "attempts": attempts,
    }


def _lesson_applied(active_repair_lesson: dict[str, Any], patch_files: list[str]) -> bool:
    target_files = {str(path).lower() for path in active_repair_lesson.get("target_files") or []}
    if target_files:
        return any(str(path).lower() in target_files for path in patch_files or [])
    return bool(patch_files)


def _lesson_mastered(result: PatchLaneResult) -> bool:
    if not result.applied:
        return False
    if result.semantic_command_success_rate < 1.0:
        return False
    return True


def _derive_residual_constraints(
    *,
    patch_text: str,
    patch_files: list[str],
    apply_check_stdout_tail: str,
    apply_check_stderr_tail: str,
    applied: bool,
    command_results: list[dict[str, Any]],
) -> list[str]:
    residuals: list[str] = []
    if not patch_text.strip():
        residuals.append("missing_patch_output")
    elif not patch_files:
        residuals.append("missing_patch_file_headers")
    apply_feedback = "\n".join(part for part in [apply_check_stdout_tail, apply_check_stderr_tail] if part)
    lower_apply = apply_feedback.lower()
    if "corrupt patch" in lower_apply or "malformed patch" in lower_apply:
        residuals.append("invalid_unified_diff_format")
    if "no such file or directory" in lower_apply:
        residuals.append("wrong_file_path_or_missing_target")
    if "patch does not apply" in lower_apply or "patch failed" in lower_apply:
        residuals.append("hunk_context_mismatch")
    if patch_text and not apply_feedback.strip() and not applied:
        residuals.append("patch_needs_verification")
    if patch_text and patch_files and apply_feedback.strip() and "patch_needs_verification" in residuals:
        residuals.remove("patch_needs_verification")
    if patch_text and patch_files and not applied and "invalid_unified_diff_format" not in residuals and "hunk_context_mismatch" not in residuals and "wrong_file_path_or_missing_target" not in residuals:
        residuals.append("patch_apply_runtime_failure")
    for command_result in command_results:
        if str(command_result.get("status") or "") == "passed":
            continue
        if bool(command_result.get("blocked")):
            residuals.append(f"verification_environment_blocked:{command_result.get('command') or 'command'}")
            blocked_reason = str(command_result.get("blocked_reason") or "").strip()
            if blocked_reason:
                residuals.append(blocked_reason)
            continue
        residuals.append(f"verification_failed:{command_result.get('command') or 'command'}")
        feedback = f"{command_result.get('stdout_tail') or ''}\n{command_result.get('stderr_tail') or ''}".lower()
        if any(
            token in feedback
            for token in (
                "is not recognized as an internal or external command",
                "command not found",
                "no such file or directory",
                "could not determine executable to run",
            )
        ):
            residuals.append("missing_local_tooling")
        if any(token in feedback for token in ("syntaxerror", "unexpected token", "parseerror")):
            residuals.append("syntax_or_parse_error")
        if any(token in feedback for token in ("module not found", "modulenotfounderror", "cannot find module", "importerror")):
            residuals.append("missing_import_or_dependency")
        if any(token in feedback for token in ("nameerror", "referenceerror", "attributeerror", "typeerror")):
            residuals.append("symbol_or_api_mismatch")
        if any(token in feedback for token in ("assertionerror", "expected", "failed", "traceback")):
            residuals.append("behavior_verification_failure")
    return _normalize(residuals)


def _build_retry_feedback_block(
    *,
    residual_constraints: list[str],
    previous_patch_text: str,
    apply_check_stdout_tail: str,
    apply_check_stderr_tail: str,
    apply_stdout_tail: str,
    apply_stderr_tail: str,
    command_results: list[dict[str, Any]],
    diagnostic_sheet: dict[str, Any] | None = None,
    active_repair_lesson: dict[str, Any] | None = None,
) -> str:
    sections: list[str] = []
    if active_repair_lesson:
        sections.extend(
            [
                "Active repair lesson:",
                f"- {active_repair_lesson.get('title') or 'Repair lesson'}",
                f"- {active_repair_lesson.get('description') or ''}",
                f"- Practice question: {active_repair_lesson.get('practice_question') or ''}",
            ]
        )
        target_files = active_repair_lesson.get("target_files") or []
        if target_files:
            sections.append(f"- Target files: {', '.join(str(path) for path in target_files)}")
    if residual_constraints:
        if sections:
            sections.append("")
        sections.append("Residual constraints from the last attempt:")
        sections.extend(f"- {item}" for item in residual_constraints)
    if diagnostic_sheet:
        summary = str(diagnostic_sheet.get("summary") or "").strip()
        entries = list(diagnostic_sheet.get("entries") or [])
        if summary or entries:
            sections.extend(["", "Diagnostic sheet:"])
            if summary:
                sections.append(f"- Summary: {summary}")
            for entry in entries[:3]:
                sections.append(f"- {_summarize_diagnostic_entry(entry)}")
    feedback_chunks = [
        _trim_tail(apply_check_stdout_tail),
        _trim_tail(apply_check_stderr_tail),
        _trim_tail(apply_stdout_tail),
        _trim_tail(apply_stderr_tail),
    ]
    feedback_text = "\n".join(chunk for chunk in feedback_chunks if chunk)
    if feedback_text:
        sections.extend(["", "Validation feedback:", f"```text\n{feedback_text}\n```"])
    failed_commands = [item for item in command_results if str(item.get("status") or "") != "passed"]
    if failed_commands:
        command_lines = []
        for item in failed_commands[:3]:
            command_lines.append(f"$ {item.get('command') or ''}")
            stderr_tail = _trim_tail(str(item.get("stderr_tail") or ""))
            stdout_tail = _trim_tail(str(item.get("stdout_tail") or ""))
            if stderr_tail:
                command_lines.append(stderr_tail)
            elif stdout_tail:
                command_lines.append(stdout_tail)
        sections.extend(["", "Verification command failures:", f"```text\n{chr(10).join(command_lines)}\n```"])
    previous_patch = _trim_tail(previous_patch_text, limit=2200)
    if previous_patch:
        sections.extend(["", "Previous patch draft to repair:", f"```diff\n{previous_patch}\n```"])
    return "\n".join(sections).strip()


def _prompt_mentions_docs(prompt: str) -> bool:
    lower_prompt = (prompt or "").lower()
    return any(token in lower_prompt for token in ("doc", "docs", "documentation", "readme", "markdown", ".md"))


def _prompt_mentions_examples(prompt: str) -> bool:
    lower_prompt = (prompt or "").lower()
    return any(token in lower_prompt for token in ("example", "examples", "sample", "samples"))


def _is_docs_like_path(rel_path: str) -> bool:
    path_lower = str(rel_path or "").lower()
    return (
        path_lower.endswith(".md")
        or path_lower == "readme.md"
        or path_lower.startswith("docs/")
        or "/docs/" in path_lower
    )


def _is_example_like_path(rel_path: str) -> bool:
    path_lower = str(rel_path or "").lower()
    return path_lower.startswith("examples/") or "/examples/" in path_lower


def _is_code_like_path(rel_path: str) -> bool:
    path_lower = str(rel_path or "").lower()
    if _is_docs_like_path(path_lower) or _is_example_like_path(path_lower):
        return False
    suffix = Path(path_lower).suffix.lower()
    return suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".toml", ".yaml", ".yml"} or bool(path_lower)


def _filter_retry_target_paths(
    *,
    prompt: str,
    candidate_paths: list[str],
    original_context_paths: list[str] | None = None,
    allowed_missing_paths: list[str] | None = None,
) -> list[str]:
    original_paths = _normalize(list(original_context_paths or []))
    original_set = {path.lower() for path in original_paths}
    allowed_missing_set = {path.lower() for path in _normalize(list(allowed_missing_paths or []))}
    prompt_mentions_docs = _prompt_mentions_docs(prompt)
    prompt_mentions_examples = _prompt_mentions_examples(prompt)
    original_has_code = any(_is_code_like_path(path) for path in original_paths)

    def _allowed(rel_path: str) -> bool:
        path_lower = str(rel_path or "").lower()
        if original_set and path_lower not in original_set and path_lower not in allowed_missing_set:
            return False
        if _is_docs_like_path(path_lower) and original_has_code and not prompt_mentions_docs:
            return False
        if _is_example_like_path(path_lower) and original_has_code and not prompt_mentions_examples:
            return False
        return True

    filtered = [path for path in _normalize(candidate_paths) if _allowed(path)]
    if filtered:
        return filtered
    return [path for path in original_paths if _allowed(path)]


def _merge_retry_context_paths(
    *,
    repo_root: Path,
    prompt: str,
    current_paths: list[str],
    original_context_paths: list[str] | None = None,
    patch_files: list[str],
    residual_constraints: list[str],
    apply_feedback_text: str,
    command_results: list[dict[str, Any]],
    diagnostic_sheet: dict[str, Any] | None = None,
    retry_context_paths: list[str] | None = None,
    limit: int = 6,
) -> list[str]:
    command_feedback_paths: list[str] = []
    for item in command_results:
        command_feedback_paths.extend(
            _extract_repo_relative_paths(
                repo_root,
                f"{item.get('stdout_tail') or ''}\n{item.get('stderr_tail') or ''}",
            )
        )
    scanned = _scan_prompt_candidate_files(
        repo_root,
        " ".join(
            part
            for part in [
                prompt,
                " ".join(residual_constraints or []),
                apply_feedback_text or "",
            ]
            if part
        ),
        limit=max(limit, 6),
    )
    merged = _normalize(
        list(retry_context_paths or [])
        + list((diagnostic_sheet or {}).get("target_files") or [])
        + patch_files
        + _extract_repo_relative_paths(repo_root, apply_feedback_text)
        + command_feedback_paths
        + list(current_paths or [])
        + scanned
    )
    filtered = _filter_retry_target_paths(
        prompt=prompt,
        candidate_paths=merged,
        original_context_paths=original_context_paths,
        allowed_missing_paths=list((diagnostic_sheet or {}).get("target_files") or [])
        if str((diagnostic_sheet or {}).get("task_type") or "").strip() == "create_file"
        else [],
    )
    return filtered[: max(int(limit), 1)]


def _lane_external_score(result: PatchLaneResult) -> tuple[float, float, float, float]:
    return (
        1.0 if result.applied else 0.0,
        float(result.semantic_command_success_rate),
        1.0 if result.apply_check_passed else 0.0,
        1.0 if bool(result.patch_text.strip()) else 0.0,
    )


def _build_allowed_file_excerpt(prompt: str, blob: str, *, max_lines: int = 3, max_chars: int = 220) -> str:
    prompt_tokens = _tokenize(prompt)
    scored: list[tuple[float, str]] = []
    fallback: list[str] = []
    for raw_line in (blob or "").splitlines():
        clean_line = raw_line.strip()
        if not clean_line:
            continue
        if clean_line.startswith("# Diagnostic focus:") or clean_line.startswith("# Exact excerpt for anchors:"):
            continue
        display_line = re.sub(r"^\s*\d+\s*\|\s*", "", clean_line).strip()
        if not display_line:
            continue
        if display_line.startswith(("```", "FILE:")):
            continue
        line_tokens = _tokenize(display_line)
        overlap = len(prompt_tokens & line_tokens)
        if display_line not in fallback:
            fallback.append(display_line)
        bonus = 0.4 if re.search(r"\bit\s*\(|\btest\s*\(|\bdescribe\s*\(|\bexport\b|\binterface\b|\bfunction\b", display_line) else 0.0
        penalty = 0.2 if display_line in {"{", "}", "(", ")", "[]"} else 0.0
        score = float(overlap + bonus - penalty)
        if overlap > 0 or bonus > 0:
            scored.append((score, display_line))
    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    chosen: list[str] = []
    for _, line in scored:
        if line not in chosen:
            chosen.append(line)
        if len(chosen) >= max(int(max_lines), 1):
            break
    for line in fallback:
        if line not in chosen:
            chosen.append(line)
        if len(chosen) >= max(int(max_lines), 1):
            break
    excerpt = " / ".join(chosen).strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[: max_chars - 3].rstrip() + "..."
    return excerpt




def _rank_allowed_structured_files(
    *,
    prompt: str,
    context_files: list[tuple[str, str]],
    diagnostic_sheet: dict[str, Any] | None = None,
    limit: int = 6,
) -> list[dict[str, Any]]:
    prompt_tokens = _tokenize(prompt)
    diagnostic_entries = list((diagnostic_sheet or {}).get("entries") or [])
    diagnostic_targets = _normalize(list((diagnostic_sheet or {}).get("target_files") or []))
    diagnostic_file = str(diagnostic_entries[0].get("file") or "").strip() if diagnostic_entries else ""
    docs_prompt = _prompt_mentions_docs(prompt)
    examples_prompt = _prompt_mentions_examples(prompt)
    ranked: list[dict[str, Any]] = []
    for index, (rel_path, blob) in enumerate(context_files):
        path_lower = rel_path.lower()
        file_tokens = _tokenize(rel_path)
        snippet_tokens = _tokenize(blob[:2000])
        path_overlap = len(prompt_tokens & file_tokens)
        snippet_overlap = len(prompt_tokens & snippet_tokens)
        score = float(path_overlap * 2.0 + snippet_overlap * 0.7)
        tier = 1
        reason = "related code file"
        is_docs_like = _is_docs_like_path(path_lower)
        is_example_like = _is_example_like_path(path_lower)
        if is_docs_like and not docs_prompt:
            tier = 0
            reason = "documentation — use only if no code file applies"
        elif is_example_like and not examples_prompt:
            tier = 0
            reason = "example file — use only if no source or test file applies"
        if rel_path == diagnostic_file:
            score += 6.0
            reason = "top diagnostic target"
        elif rel_path in diagnostic_targets[:2]:
            score += 3.0
            reason = "retrieved as a strong repair target"
        elif tier == 1 and (path_overlap > 0 or snippet_overlap > 0):
            reason = "strongest prompt token match" if (path_overlap * 2 + snippet_overlap) >= 3 else "prompt token overlap"
        if tier == 0:
            score -= 4.0
        score -= index * 0.05
        ranked.append(
            {
                "path": rel_path,
                "tier": tier,
                "score": round(score, 4),
                "reason": reason,
                "excerpt": _build_allowed_file_excerpt(prompt, blob),
            }
        )
    ranked.sort(key=lambda item: (item["tier"], item["score"], item["path"]), reverse=True)
    return ranked[: max(int(limit), 1)]


def _build_patch_prompt(
    *,
    prompt: str,
    repo_root: Path,
    context_files: list[tuple[str, str]],
    workflow_block: str = "",
    iteration: int = 1,
    retry_feedback_block: str = "",
    diagnostic_sheet: dict[str, Any] | None = None,
    active_repair_lesson: dict[str, Any] | None = None,
    response_mode: str = "diff",
) -> list[ChatMessage]:
    file_sections = []
    for rel_path, blob in context_files:
        file_sections.append(f"FILE: {rel_path}\n```text\n{blob}\n```")
    ranked_allowed_files = _rank_allowed_structured_files(
        prompt=prompt,
        context_files=context_files,
        diagnostic_sheet=diagnostic_sheet,
        limit=6,
    )
    allowed_structured_files = [str(item.get("path") or "") for item in ranked_allowed_files if item.get("path")]
    if not allowed_structured_files:
        fallback_paths = _normalize(list((diagnostic_sheet or {}).get("target_files") or []))
        ranked_allowed_files = [
            {"path": path, "score": 0.0, "reason": "related context file", "excerpt": ""}
            for path in fallback_paths[:6]
        ]
        allowed_structured_files = [item["path"] for item in ranked_allowed_files]
    user_parts: list[str] = []
    if response_mode == "structured":
        create_file_mode = str((diagnostic_sheet or {}).get("task_type") or "").strip() == "create_file"
        user_parts.extend(
            [
                'Respond with a single JSON object matching this schema. Do not explain. Do not summarize. Output only the JSON.',
                '{"file":"repo/path.ext","op":"replace|insert_after|insert_before|delete|replace_lines|create_file","before":"exact existing snippet for replace/delete","after":"replacement snippet for replace","anchor":"exact existing snippet for insert_after/insert_before","content":"content for insert_after/insert_before, replace_lines, or create_file","start_line":42,"end_line":45}',
                "Rules:",
                "- Return exactly one edit object. Do not use an edits array.",
                "- Do not wrap the JSON in markdown fences.",
                "- Only target files present in the allowed file path list below, unless the diagnostic sheet explicitly says a new file is required.",
                f"- Keep anchor strings short and precise, at most {_MAX_STRUCTURED_ANCHOR_CHARS} characters.",
                f"- Keep before snippets short and precise, at most {_MAX_STRUCTURED_BEFORE_CHARS} characters.",
                "- If you cannot point to a short exact anchor, use replace_lines with start_line/end_line instead.",
                "- Prefer the smallest edit that addresses the top diagnostic first.",
                "- The file field must exactly equal one of the allowed file paths listed below.",
                "- Use op=create_file only for a new-file task. For create_file provide only file, op, and content.",
                "- For create_file, content must be the raw file text only. Do not include markdown fences, prose, summaries, or leading commentary inside content.",
                "Examples:",
                'Allowed files: src/config.ts, README.md',
                '{"file":"src/config.ts","op":"replace_lines","start_line":12,"end_line":12,"content":"export const timeout = 5000\\n"}',
                'Allowed files: src/index.ts, docs/guide.md',
                '{"file":"src/index.ts","op":"insert_after","anchor":"export interface RequestOptions {","content":"\\n  headers?: Headers"}',
                'Allowed files: src/auth.ts, test/auth.test.ts',
                '{"file":"src/auth.ts","op":"replace","before":"if (!token) throw new Error(\\"missing\\")\\n","after":"if (!token) throw new TypeError(\\"missing token\\")\\n"}',
            ]
        )
        if create_file_mode:
            user_parts.extend(
                [
                    "- This is a new-file task. Create exactly one missing sibling file at an allowed path.",
                    "- Keep the new file minimal and focused on the requested behavior.",
                    'Allowed files: test/jwks_lifecycle.test.ts',
                    '{"file":"test/jwks_lifecycle.test.ts","op":"create_file","content":"import test from \\"ava\\"\\n\\ntest(\\"jwks lifecycle\\", async (t) => {\\n  t.pass()\\n})\\n"}',
                ]
            )
        if allowed_structured_files:
            user_parts.append("Allowed file paths:")
            for idx, item in enumerate(ranked_allowed_files[:6], start=1):
                user_parts.append(f"- {idx}. {item['path']} — {item['reason']}")
                excerpt = str(item.get("excerpt") or "").strip()
                if excerpt:
                    user_parts.append(f"  Excerpt: {excerpt}")
        user_parts.extend(
            [
                "",
                f"Task: {prompt}",
            ]
        )
    else:
        user_parts.extend(
            [
                f"Task: {prompt}",
                "Produce only a unified diff patch that can be applied with git apply.",
                "Use real repo-relative paths and keep the patch minimal.",
                "If the task cannot be completed from the provided context, still output your best minimal diff.",
            ]
        )
    if iteration > 1:
        user_parts.extend(
            [
                "",
                f"Repair iteration: {iteration}",
                "The previous patch did not validate cleanly. Repair it using the feedback below instead of restarting from scratch unless the old patch was clearly targeting the wrong area.",
            ]
        )
    if workflow_block:
        user_parts.extend(["", workflow_block.strip()])
    if active_repair_lesson:
        user_parts.extend(
            [
                "",
                "Active repair lesson:",
                f"- {active_repair_lesson.get('title') or 'Repair lesson'}",
                f"- {active_repair_lesson.get('description') or ''}",
                f"- Practice question: {active_repair_lesson.get('practice_question') or ''}",
            ]
        )
    if diagnostic_sheet:
        summary = str(diagnostic_sheet.get("summary") or "").strip()
        entries = list(diagnostic_sheet.get("entries") or [])
        if summary or entries:
            user_parts.extend(["", "Diagnostic sheet:"])
            if entries:
                top_entry = entries[0]
                top_file = str(top_entry.get("file") or "").strip()
                top_line = top_entry.get("line")
                if top_file and top_line:
                    user_parts.append(f"- Preferred first repair target: {top_file}:{top_line}")
            if summary:
                user_parts.append(f"- Summary: {summary}")
            for entry in entries[:3]:
                user_parts.append(f"- {_summarize_diagnostic_entry(entry)}")
    if retry_feedback_block:
        user_parts.extend(["", retry_feedback_block.strip()])
    if file_sections:
        user_parts.extend(["", "Repo snapshot:", *file_sections])
    return [
        ChatMessage(
            role="system",
            content=(
                CODING_BASE_SYSTEM
                + "\n\n"
                + (
                    "Respond with a single JSON object matching the requested schema. Do not add prose, summaries, markdown fences, or arrays."
                    if response_mode == "structured"
                    else "Output only a unified diff patch. Do not add prose before or after the diff."
                )
            ),
        ),
        ChatMessage(role="user", content="\n".join(user_parts)),
    ]


def _build_structured_normalizer_prompt(
    *,
    prompt: str,
    raw_answer: str,
    diagnostic_sheet: dict[str, Any] | None = None,
    active_repair_lesson: dict[str, Any] | None = None,
    allowed_files: list[str] | None = None,
) -> list[ChatMessage]:
    summary = str((diagnostic_sheet or {}).get("summary") or "").strip()
    target_files = list((diagnostic_sheet or {}).get("target_files") or [])
    lesson_title = str((active_repair_lesson or {}).get("title") or "").strip()
    user_parts = [
        'Convert the draft below into exactly one valid JSON edit object. Output only JSON. No prose. No markdown fences. No arrays.',
        '{"file":"repo/path.ext","op":"replace|insert_after|insert_before|delete|replace_lines|create_file","before":"exact existing snippet for replace/delete","after":"replacement snippet for replace","anchor":"exact existing snippet for insert_after/insert_before","content":"content for insert_after/insert_before, replace_lines, or create_file","start_line":42,"end_line":45}',
        "Rules:",
        "- Return exactly one edit object.",
        f"- Keep anchor strings at most {_MAX_STRUCTURED_ANCHOR_CHARS} characters.",
        f"- Keep before snippets at most {_MAX_STRUCTURED_BEFORE_CHARS} characters.",
        "- The file field must exactly equal one of the allowed file paths listed below.",
        "- Use op=create_file only when the draft clearly indicates a new-file task.",
        "- If the draft does not contain a recoverable edit, return {}.",
        "",
        f"Original task: {prompt}",
    ]
    if summary:
        user_parts.append(f"Diagnostic summary: {summary}")
    if lesson_title:
        user_parts.append(f"Active repair lesson: {lesson_title}")
    if target_files:
        user_parts.append(f"Target files: {', '.join(str(path) for path in target_files[:3])}")
    normalized_allowed = _normalize(list(allowed_files or []))
    if normalized_allowed:
        user_parts.extend(
            [
                "Allowed file paths:",
                *[f"- {path}" for path in normalized_allowed[:6]],
            ]
        )
    user_parts.extend(
        [
            "",
            "Draft to normalize:",
            f"```text\n{_trim_tail(raw_answer, limit=5000)}\n```",
        ]
    )
    return [
        ChatMessage(
            role="system",
            content="You normalize repair drafts into one valid JSON edit object. Output only JSON.",
        ),
        ChatMessage(role="user", content="\n".join(user_parts)),
    ]


def _normalize_structured_answer(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    raw_answer: str,
    diagnostic_sheet: dict[str, Any] | None = None,
    active_repair_lesson: dict[str, Any] | None = None,
    allowed_files: list[str] | None = None,
    temperature: float = 0.0,
    num_ctx: int | None = None,
) -> str:
    if not raw_answer.strip():
        return ""
    messages = _build_structured_normalizer_prompt(
        prompt=prompt,
        raw_answer=raw_answer,
        diagnostic_sheet=diagnostic_sheet,
        active_repair_lesson=active_repair_lesson,
        allowed_files=allowed_files,
    )
    return client.chat(
        model=model,
        messages=messages,
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()


def _extract_diff_block(answer: str) -> str:
    text = (answer or "").strip()
    fenced = re.findall(r"```(?:diff|patch)?\n(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fenced:
        return "\n".join(block.strip("\n") for block in fenced if block.strip()).strip()
    if "diff --git" in text:
        return text[text.index("diff --git") :].strip()
    if "\n--- " in "\n" + text and "\n+++ " in "\n" + text:
        return text.strip()
    return ""


def _extract_patch_files(diff_text: str) -> list[str]:
    files: list[str] = []
    for match in re.finditer(r"^\+\+\+\s+b/(.+)$", diff_text or "", re.MULTILINE):
        files.append(match.group(1).strip())
    if files:
        return _normalize(files)
    for match in re.finditer(r"^diff --git a/(.+?) b/(.+)$", diff_text or "", re.MULTILINE):
        files.append(match.group(2).strip())
    return _normalize(files)


def _extract_json_object(answer: str) -> dict[str, Any] | None:
    candidates: list[str] = []
    fenced = re.findall(r"```(?:json)?\n(.*?)```", answer or "", re.DOTALL | re.IGNORECASE)
    candidates.extend(block.strip() for block in fenced if block.strip())
    text = (answer or "").strip()
    if text:
        candidates.append(text)
    decoder = json.JSONDecoder()
    for candidate in candidates:
        for start in range(len(candidate)):
            if candidate[start] not in "[{":
                continue
            try:
                obj, _ = decoder.raw_decode(candidate[start:])
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                return obj
    return None


def _normalize_created_file_content(content: str) -> str:
    text = str(content or "")
    fenced = re.findall(r"```(?:[A-Za-z0-9_+-]+)?\n(.*?)```", text, re.DOTALL)
    if fenced:
        return fenced[0].strip("\n") + ("\n" if fenced[0] and not fenced[0].endswith("\n") else "")
    return text


def _compile_structured_edits_to_patch(
    repo_root: Path,
    answer: str,
    *,
    allowed_files: list[str] | None = None,
) -> tuple[str, list[str], list[str], str]:
    payload = _extract_json_object(answer)
    if not payload:
        return "", [], ["invalid_structured_edit_json"], "Could not parse JSON edit plan from model output."
    raw_edits: list[Any] = []
    if isinstance(payload.get("edit"), dict):
        raw_edits = [payload.get("edit")]
    elif isinstance(payload.get("edits"), list):
        raw_edits = list(payload.get("edits") or [])
    elif any(
        key in payload
        for key in ("file", "op", "before", "after", "anchor", "content", "start_line", "end_line")
    ):
        raw_edits = [payload]
    if not raw_edits:
        return "", [], ["missing_structured_edits"], "Structured edit plan did not include any edits."

    patch_chunks: list[str] = []
    touched_files: list[str] = []
    residuals: list[str] = []
    feedback_lines: list[str] = []
    allowed_file_set = {str(path).lower() for path in _normalize(list(allowed_files or []))}
    if len(raw_edits) > 1:
        residuals.append("multiple_structured_edits_supplied")
        feedback_lines.append("Only one structured edit is allowed per iteration; later edits were ignored.")
        raw_edits = raw_edits[:1]

    for index, raw_edit in enumerate(raw_edits, start=1):
        if not isinstance(raw_edit, dict):
            residuals.append("invalid_structured_edit_entry")
            feedback_lines.append(f"Edit {index} is not an object.")
            continue
        rel_path = str(raw_edit.get("file") or "").replace("\\", "/").lstrip("./")
        op = str(raw_edit.get("op") or "replace").strip().lower()
        if not rel_path:
            residuals.append("missing_structured_edit_file")
            feedback_lines.append(f"Edit {index} omitted a file path.")
            continue
        if rel_path.lower() == "repo/path.ext":
            residuals.append("placeholder_structured_edit_file")
            feedback_lines.append("Edit used the placeholder path repo/path.ext instead of a real repo file.")
            continue
        if allowed_file_set and rel_path.lower() not in allowed_file_set:
            residuals.append("file_not_in_allowed_context")
            feedback_lines.append(f"Edit {index} targeted {rel_path}, which is not in the allowed file path list.")
            continue
        target = (repo_root / rel_path).resolve()
        try:
            target.relative_to(repo_root.resolve())
        except ValueError:
            residuals.append("structured_edit_outside_repo")
            feedback_lines.append(f"Edit {index} targeted a path outside the repo: {rel_path}")
            continue
        if op == "create_file":
            content = _normalize_created_file_content(str(raw_edit.get("content") or ""))
            if target.exists():
                residuals.append("target_already_exists")
                feedback_lines.append(f"Edit {index} targeted an existing file with create_file: {rel_path}")
                continue
            if not content:
                residuals.append("missing_create_file_content")
                feedback_lines.append(f"Edit {index} is missing content for create_file in {rel_path}.")
                continue
            diff_body = "".join(
                difflib.unified_diff(
                    [],
                    content.splitlines(True),
                    fromfile="/dev/null",
                    tofile=f"b/{rel_path}",
                    lineterm="\n",
                )
            )
            if not diff_body.strip():
                residuals.append("structured_edit_no_change")
                feedback_lines.append(f"Edit {index} produced no diff for {rel_path}.")
                continue
            patch_chunks.append(
                f"diff --git a/{rel_path} b/{rel_path}\nnew file mode 100644\n{diff_body}"
            )
            touched_files.append(rel_path)
            continue
        if not target.exists() or not target.is_file():
            residuals.append("wrong_file_path_or_missing_target")
            feedback_lines.append(f"Edit {index} targeted a missing file: {rel_path}")
            continue

        original = target.read_text(encoding="utf-8", errors="replace")
        updated = original
        if op == "replace":
            before = str(raw_edit.get("before") or "")
            after = str(raw_edit.get("after") or "")
            if not before:
                residuals.append("missing_replace_anchor")
                feedback_lines.append(f"Edit {index} is missing a before snippet for replace in {rel_path}.")
                continue
            if len(before) > _MAX_STRUCTURED_BEFORE_CHARS:
                residuals.append("before_too_long")
                feedback_lines.append(
                    f"Edit {index} used a before snippet longer than {_MAX_STRUCTURED_BEFORE_CHARS} characters in {rel_path}."
                )
                continue
            if before not in updated:
                residuals.append("edit_anchor_not_found")
                feedback_lines.append(f"Replace anchor not found in {rel_path}.")
                continue
            updated = updated.replace(before, after, 1)
        elif op == "delete":
            before = str(raw_edit.get("before") or "")
            if not before:
                residuals.append("missing_delete_anchor")
                feedback_lines.append(f"Edit {index} is missing a before snippet for delete in {rel_path}.")
                continue
            if len(before) > _MAX_STRUCTURED_BEFORE_CHARS:
                residuals.append("before_too_long")
                feedback_lines.append(
                    f"Edit {index} used a before snippet longer than {_MAX_STRUCTURED_BEFORE_CHARS} characters in {rel_path}."
                )
                continue
            if before not in updated:
                residuals.append("edit_anchor_not_found")
                feedback_lines.append(f"Delete anchor not found in {rel_path}.")
                continue
            updated = updated.replace(before, "", 1)
        elif op in {"insert_after", "insert_before"}:
            anchor = str(raw_edit.get("anchor") or "")
            content = str(raw_edit.get("content") or "")
            if not anchor:
                residuals.append("missing_insert_anchor")
                feedback_lines.append(f"Edit {index} is missing an anchor for {op} in {rel_path}.")
                continue
            if len(anchor) > _MAX_STRUCTURED_ANCHOR_CHARS:
                residuals.append("anchor_too_long")
                feedback_lines.append(
                    f"Edit {index} used an anchor longer than {_MAX_STRUCTURED_ANCHOR_CHARS} characters in {rel_path}."
                )
                continue
            if anchor not in updated:
                residuals.append("edit_anchor_not_found")
                feedback_lines.append(f"Insert anchor not found in {rel_path}.")
                continue
            if op == "insert_after":
                updated = updated.replace(anchor, anchor + content, 1)
            else:
                updated = updated.replace(anchor, content + anchor, 1)
        elif op == "replace_lines":
            try:
                start_line = int(raw_edit.get("start_line"))
                end_line = int(raw_edit.get("end_line") or start_line)
            except (TypeError, ValueError):
                residuals.append("missing_line_span")
                feedback_lines.append(f"Edit {index} is missing a valid line span for replace_lines in {rel_path}.")
                continue
            original_lines = original.splitlines(True)
            if start_line < 1 or end_line < start_line or end_line > len(original_lines):
                residuals.append("invalid_line_span")
                feedback_lines.append(f"Edit {index} referenced an invalid line span in {rel_path}.")
                continue
            replacement = str(raw_edit.get("content") or "")
            replacement_lines = replacement.splitlines(True)
            updated = "".join(original_lines[: start_line - 1] + replacement_lines + original_lines[end_line:])
        else:
            residuals.append("unsupported_structured_edit_op")
            feedback_lines.append(f"Unsupported op '{op}' for {rel_path}.")
            continue

        if updated == original:
            residuals.append("structured_edit_no_change")
            feedback_lines.append(f"Edit {index} did not change {rel_path}.")
            continue

        diff_body = "".join(
            difflib.unified_diff(
                original.splitlines(True),
                updated.splitlines(True),
                fromfile=f"a/{rel_path}",
                tofile=f"b/{rel_path}",
                lineterm="\n",
            )
        )
        if not diff_body.strip():
            residuals.append("structured_edit_no_change")
            feedback_lines.append(f"Edit {index} produced no diff for {rel_path}.")
            continue
        patch_chunks.append(f"diff --git a/{rel_path} b/{rel_path}\n{diff_body}")
        touched_files.append(rel_path)

    patch_text = "\n".join(chunk.rstrip("\n") for chunk in patch_chunks if chunk.strip()).strip()
    return patch_text, _normalize(touched_files), _normalize(residuals), "\n".join(feedback_lines).strip()


def _run_expected_commands(repo_root: Path, commands: list[str]) -> tuple[float, float, list[dict[str, Any]]]:
    if not commands:
        return 1.0, 1.0, []
    results: list[dict[str, Any]] = []
    passed = 0
    semantic_passed = 0
    semantic_total = 0
    env = os.environ.copy()
    local_bins = _candidate_local_bin_paths(repo_root)
    if local_bins:
        env["PATH"] = os.pathsep.join(local_bins + [env.get("PATH") or ""])
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=600,
            check=False,
            env=env,
        )
        ok = completed.returncode == 0
        feedback_text = f"{completed.stdout or ''}\n{completed.stderr or ''}"
        blocked, blocked_reason = _classify_command_blockage(feedback_text)
        if ok:
            passed += 1
            semantic_passed += 1
            semantic_total += 1
        elif not blocked:
            semantic_total += 1
        results.append(
            {
                "command": command,
                "returncode": int(completed.returncode),
                "status": "passed" if ok else "failed",
                "blocked": bool(blocked),
                "blocked_reason": blocked_reason,
                "stdout_tail": (completed.stdout or "")[-1200:],
                "stderr_tail": (completed.stderr or "")[-1200:],
            }
        )
    semantic_rate = 1.0 if semantic_total == 0 else (semantic_passed / semantic_total)
    return passed / max(len(commands), 1), semantic_rate, results


def _evaluate_lane_once(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    worktree_root: Path,
    expected_files: list[str],
    expected_commands: list[str],
    expected_diff_excerpt: list[str],
    context_paths: list[str],
    original_context_paths: list[str] | None = None,
    workflow_block: str = "",
    iteration: int = 1,
    retry_feedback_block: str = "",
    diagnostic_sheet: dict[str, Any] | None = None,
    active_repair_lesson: dict[str, Any] | None = None,
    structured_compiler: bool = False,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> PatchLaneResult:
    context_files = _read_file_context(
        worktree_root,
        context_paths,
        focus_map=(diagnostic_sheet or {}).get("focus_map"),
    )
    create_targets = (
        list((diagnostic_sheet or {}).get("target_files") or [])
        if str((diagnostic_sheet or {}).get("task_type") or "").strip() == "create_file"
        else []
    )
    allowed_structured_files = _filter_retry_target_paths(
        prompt=prompt,
        candidate_paths=(
            [path for path, _ in context_files]
            + list((diagnostic_sheet or {}).get("target_files") or [])
        ),
        original_context_paths=original_context_paths or context_paths,
        allowed_missing_paths=create_targets,
    )
    messages = _build_patch_prompt(
        prompt=prompt,
        repo_root=worktree_root,
        context_files=context_files,
        workflow_block=workflow_block,
        iteration=iteration,
        retry_feedback_block=retry_feedback_block,
        diagnostic_sheet=diagnostic_sheet,
        active_repair_lesson=active_repair_lesson,
        response_mode="structured" if structured_compiler else "diff",
    )
    answer = client.chat(
        model=model,
        messages=messages,
        temperature=temperature,
        num_ctx=num_ctx,
    ).strip()
    compiler_feedback = ""
    compiler_residuals: list[str] = []
    if structured_compiler:
        patch_text, patch_files, compiler_residuals, compiler_feedback = _compile_structured_edits_to_patch(
            worktree_root,
            answer,
            allowed_files=allowed_structured_files,
        )
        if any(
            item in compiler_residuals
            for item in (
                "invalid_structured_edit_json",
                "missing_structured_edits",
                "wrong_file_path_or_missing_target",
                "file_not_in_allowed_context",
                "placeholder_structured_edit_file",
            )
        ):
            normalized_answer = _normalize_structured_answer(
                client=client,
                model=model,
                prompt=prompt,
                raw_answer=answer,
                diagnostic_sheet=diagnostic_sheet,
                active_repair_lesson=active_repair_lesson,
                allowed_files=allowed_structured_files,
                temperature=0.0,
                num_ctx=num_ctx,
            )
            if normalized_answer and normalized_answer.strip() and normalized_answer.strip() != answer.strip():
                normalized_patch_text, normalized_patch_files, normalized_residuals, normalized_feedback = (
                    _compile_structured_edits_to_patch(
                        worktree_root,
                        normalized_answer,
                        allowed_files=allowed_structured_files,
                    )
                )
                original_failed_hard = any(
                    item in compiler_residuals for item in ("invalid_structured_edit_json", "missing_structured_edits")
                )
                normalized_failed_hard = any(
                    item in normalized_residuals for item in ("invalid_structured_edit_json", "missing_structured_edits")
                )
                if (
                    normalized_patch_text
                    or (original_failed_hard and not normalized_failed_hard)
                    or len(normalized_residuals) < len(compiler_residuals)
                ):
                    answer = normalized_answer
                    patch_text = normalized_patch_text
                    patch_files = normalized_patch_files
                    compiler_residuals = normalized_residuals
                    compiler_feedback = normalized_feedback
    else:
        patch_text = _extract_diff_block(answer)
        patch_files = _extract_patch_files(patch_text)
    diff_recall = _score_diff_overlap(_extract_diff_excerpt(patch_text), expected_diff_excerpt)
    file_recall = _score_overlap(patch_files, expected_files)

    apply_check_passed = False
    applied = False
    command_success_rate = 0.0
    semantic_command_success_rate = 0.0
    command_results: list[dict[str, Any]] = []
    apply_check_stdout_tail = ""
    apply_check_stderr_tail = ""
    apply_stdout_tail = ""
    apply_stderr_tail = ""
    if patch_text:
        patch_file = worktree_root / ".memla_patch.diff"
        patch_file.write_text(patch_text + ("\n" if not patch_text.endswith("\n") else ""), encoding="utf-8")
        check_proc = subprocess.run(
            ["git", "-c", f"safe.directory={worktree_root.resolve()}", "-C", str(worktree_root), "apply", "--check", str(patch_file)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        apply_check_passed = check_proc.returncode == 0
        apply_check_stdout_tail = _trim_tail(check_proc.stdout or "")
        apply_check_stderr_tail = _trim_tail(check_proc.stderr or "")
        if apply_check_passed:
            apply_proc = subprocess.run(
                ["git", "-c", f"safe.directory={worktree_root.resolve()}", "-C", str(worktree_root), "apply", str(patch_file)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            applied = apply_proc.returncode == 0
            apply_stdout_tail = _trim_tail(apply_proc.stdout or "")
            apply_stderr_tail = _trim_tail(apply_proc.stderr or "")
            if applied:
                command_success_rate, semantic_command_success_rate, command_results = _run_expected_commands(
                    worktree_root,
                    expected_commands,
                )
    elif compiler_feedback:
        apply_check_stderr_tail = _trim_tail(compiler_feedback)
    residual_constraints = _derive_residual_constraints(
        patch_text=patch_text,
        patch_files=patch_files,
        apply_check_stdout_tail=apply_check_stdout_tail,
        apply_check_stderr_tail=apply_check_stderr_tail,
        applied=applied,
        command_results=command_results,
    )
    residual_constraints = _normalize(list(compiler_residuals or []) + list(residual_constraints or []))

    return PatchLaneResult(
        answer=answer,
        patch_text=patch_text,
        patch_files=patch_files,
        context_files=[path for path, _ in context_files],
        file_recall=round(file_recall, 4),
        diff_recall=round(diff_recall, 4),
        apply_check_passed=apply_check_passed,
        applied=applied,
        command_success_rate=round(command_success_rate, 4),
        semantic_command_success_rate=round(semantic_command_success_rate, 4),
        command_results=command_results,
        diagnostic_sheet=diagnostic_sheet or {},
        active_repair_lesson=active_repair_lesson or {},
        apply_check_stdout_tail=apply_check_stdout_tail,
        apply_check_stderr_tail=apply_check_stderr_tail,
        apply_stdout_tail=apply_stdout_tail,
        apply_stderr_tail=apply_stderr_tail,
        residual_constraints=residual_constraints,
    )


def _evaluate_lane(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    worktree_root: Path,
    expected_files: list[str],
    expected_commands: list[str],
    expected_diff_excerpt: list[str],
    context_paths: list[str],
    workflow_block: str = "",
    retry_workflow_builder: Callable[[str], tuple[str, list[str]]] | None = None,
    structured_compiler: bool = False,
    expected_files_missing_in_parent: list[str] | None = None,
    max_iterations: int = 1,
    temperature: float = 0.1,
    num_ctx: int | None = None,
) -> PatchLaneResult:
    original_context_paths = _normalize(list(context_paths or []))
    current_context_paths = list(original_context_paths)
    current_workflow_block = workflow_block
    retry_feedback_block = ""
    current_diagnostic_sheet: dict[str, Any] = (
        _build_diagnostic_sheet(
            repo_root=worktree_root,
            prompt=prompt,
            patch_files=[],
            apply_feedback_text="",
            command_results=[],
            expected_files_missing_in_parent=expected_files_missing_in_parent,
        )
        if expected_files_missing_in_parent
        else {}
    )
    current_active_repair_lesson: dict[str, Any] = (
        _derive_active_repair_lesson(
            residual_constraints=[],
            diagnostic_sheet=current_diagnostic_sheet,
        )
        if current_diagnostic_sheet
        else {}
    )
    best_result: PatchLaneResult | None = None
    iteration_trace: list[dict[str, Any]] = []
    seen_signatures: set[tuple[str, str, str]] = set()
    stagnation_count = 0

    for iteration in range(1, max(int(max_iterations), 1) + 1):
        result = _evaluate_lane_once(
            client=client,
            model=model,
            prompt=prompt,
            worktree_root=worktree_root,
            expected_files=expected_files,
            expected_commands=expected_commands,
            expected_diff_excerpt=expected_diff_excerpt,
            context_paths=current_context_paths,
            original_context_paths=original_context_paths,
            workflow_block=current_workflow_block,
            iteration=iteration,
            retry_feedback_block=retry_feedback_block,
            diagnostic_sheet=current_diagnostic_sheet,
            active_repair_lesson=current_active_repair_lesson,
            structured_compiler=structured_compiler,
            temperature=temperature,
            num_ctx=num_ctx,
        )
        apply_feedback_text = "\n".join(
            part
            for part in [
                result.apply_check_stdout_tail,
                result.apply_check_stderr_tail,
                result.apply_stdout_tail,
                result.apply_stderr_tail,
            ]
            if part
        )
        next_diagnostic_sheet = _build_diagnostic_sheet(
            repo_root=worktree_root,
            prompt=prompt,
            patch_files=result.patch_files,
            apply_feedback_text=apply_feedback_text,
            command_results=result.command_results,
            expected_files_missing_in_parent=expected_files_missing_in_parent,
        )
        next_active_repair_lesson = _derive_active_repair_lesson(
            residual_constraints=result.residual_constraints,
            diagnostic_sheet=next_diagnostic_sheet,
            previous_lesson=current_active_repair_lesson,
        )
        lesson_applied = _lesson_applied(next_active_repair_lesson, result.patch_files)
        lesson_mastered = bool(result.applied and (not expected_commands or result.semantic_command_success_rate >= 1.0))
        iteration_trace.append(
            {
                "iteration": iteration,
                "context_files": list(result.context_files),
                "patch_files": list(result.patch_files),
                "file_recall": result.file_recall,
                "diff_recall": result.diff_recall,
                "apply_check_passed": result.apply_check_passed,
                "applied": result.applied,
                "command_success_rate": result.command_success_rate,
                "semantic_command_success_rate": result.semantic_command_success_rate,
                "residual_constraints": list(result.residual_constraints),
                "diagnostic_sheet": next_diagnostic_sheet,
                "active_repair_lesson": next_active_repair_lesson,
                "lesson_applied": lesson_applied,
                "lesson_mastered": lesson_mastered,
                "answer": result.answer,
                "command_results": result.command_results,
            }
        )
        if best_result is None or _lane_external_score(result) >= _lane_external_score(best_result):
            best_result = result
            stagnation_count = 0
        else:
            stagnation_count += 1
        if lesson_mastered:
            best_result = result
            break
        signature = (
            "|".join(result.residual_constraints),
            "|".join(result.patch_files),
            (result.patch_text or "").strip(),
        )
        if signature in seen_signatures:
            break
        seen_signatures.add(signature)
        if iteration >= max(int(max_iterations), 1):
            break
        if stagnation_count >= 2:
            break
        retry_feedback_block = _build_retry_feedback_block(
            residual_constraints=result.residual_constraints,
            previous_patch_text=result.patch_text,
            apply_check_stdout_tail=result.apply_check_stdout_tail,
            apply_check_stderr_tail=result.apply_check_stderr_tail,
            apply_stdout_tail=result.apply_stdout_tail,
            apply_stderr_tail=result.apply_stderr_tail,
            command_results=result.command_results,
            diagnostic_sheet=next_diagnostic_sheet,
            active_repair_lesson=next_active_repair_lesson,
        )
        retry_context_paths: list[str] = []
        if retry_workflow_builder and result.residual_constraints:
            retry_prompt = prompt.strip() + "\n\nResidual constraints:\n" + "\n".join(
                f"- {item}" for item in result.residual_constraints
            )
            try:
                current_workflow_block, retry_context_paths = retry_workflow_builder(retry_prompt)
            except Exception:
                retry_context_paths = []
        current_context_paths = _merge_retry_context_paths(
            repo_root=worktree_root,
            prompt=prompt,
            current_paths=current_context_paths,
            original_context_paths=original_context_paths,
            patch_files=result.patch_files,
            residual_constraints=result.residual_constraints,
            apply_feedback_text=apply_feedback_text,
            command_results=result.command_results,
            diagnostic_sheet=next_diagnostic_sheet,
            retry_context_paths=retry_context_paths,
            limit=6,
        )
        current_diagnostic_sheet = next_diagnostic_sheet
        current_active_repair_lesson = next_active_repair_lesson

    final_result = best_result or PatchLaneResult(
        answer="",
        patch_text="",
        patch_files=[],
        context_files=[],
        file_recall=0.0,
        diff_recall=0.0,
        apply_check_passed=False,
        applied=False,
        command_success_rate=0.0,
        semantic_command_success_rate=0.0,
        command_results=[],
        diagnostic_sheet={},
        active_repair_lesson={},
    )
    return PatchLaneResult(
        answer=final_result.answer,
        patch_text=final_result.patch_text,
        patch_files=final_result.patch_files,
        context_files=final_result.context_files,
        file_recall=final_result.file_recall,
        diff_recall=final_result.diff_recall,
        apply_check_passed=final_result.apply_check_passed,
        applied=final_result.applied,
        command_success_rate=final_result.command_success_rate,
        semantic_command_success_rate=final_result.semantic_command_success_rate,
        command_results=final_result.command_results,
        diagnostic_sheet=current_diagnostic_sheet,
        active_repair_lesson=current_active_repair_lesson,
        lesson_applied=bool(iteration_trace[-1].get("lesson_applied")) if iteration_trace else False,
        lesson_mastered=bool(iteration_trace[-1].get("lesson_mastered")) if iteration_trace else False,
        apply_check_stdout_tail=final_result.apply_check_stdout_tail,
        apply_check_stderr_tail=final_result.apply_check_stderr_tail,
        apply_stdout_tail=final_result.apply_stdout_tail,
        apply_stderr_tail=final_result.apply_stderr_tail,
        residual_constraints=final_result.residual_constraints,
        iterations_used=len(iteration_trace) or 1,
        iteration_trace=iteration_trace,
    )


def _build_memla_workflow_block(
    *,
    planner_model: str,
    db_path: str,
    user_id: str,
    repo_root: Path,
    prompt: str,
    top_k: int,
    num_ctx: int | None,
    provider: str | None = None,
    base_url: str | None = None,
    c2a_policy_path: str = "",
    disable_c2a_policy: bool = False,
) -> tuple[str, list[str]]:
    with _override_llm_env(provider=provider, base_url=base_url):
        session = CodingSession(
            model=planner_model,
            db_path=db_path,
            user_id=user_id,
            repo_root=str(repo_root),
            top_k=top_k,
            num_ctx=num_ctx,
            enable_compile_loop=True,
            c2a_policy_path=c2a_policy_path,
            disable_c2a_policy=disable_c2a_policy,
        )
        try:
            workspace_snapshot = session.build_plan(prompt)
            workflow_block = render_workflow_plan_block(workspace_snapshot)
            context_paths = list(workspace_snapshot.likely_files[:6])
            return workflow_block, context_paths
        finally:
            session.close()


def _missing_expected_files(repo_root: Path, expected_files: list[str]) -> list[str]:
    return [path for path in _normalize(list(expected_files or [])) if not _repo_has_file(repo_root, path)]


def _build_llm_client(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> UniversalLLMClient:
    if not any(value for value in (provider, base_url, api_key)):
        return UniversalLLMClient.from_env()
    resolved_provider = str(provider or os.environ.get("LLM_PROVIDER", "ollama")).strip()
    normalized_provider = UniversalLLMClient._normalize_provider(resolved_provider)
    resolved_base_url = str(base_url or UniversalLLMClient._default_base_url_from_env(normalized_provider)).strip()
    resolved_api_key = api_key or os.environ.get("LLM_API_KEY")
    if normalized_provider == "github_models" and not resolved_api_key:
        resolved_api_key = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return UniversalLLMClient(
        provider=normalized_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
    )


@contextmanager
def _override_llm_env(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
):
    tracked_keys = ("LLM_PROVIDER", "LLM_BASE_URL", "LLM_API_KEY")
    previous = {key: os.environ.get(key) for key in tracked_keys}
    try:
        if provider:
            os.environ["LLM_PROVIDER"] = str(provider)
        if base_url:
            os.environ["LLM_BASE_URL"] = str(base_url)
        if api_key:
            os.environ["LLM_API_KEY"] = str(api_key)
        yield
    finally:
        for key, old_value in previous.items():
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value


def run_patch_execution_benchmark(
    *,
    pack_path: str,
    split: str,
    raw_model: str,
    memla_model: str,
    db_path: str,
    user_id: str,
    limit: int = 0,
    top_k: int = 12,
    temperature: float = 0.1,
    num_ctx: int | None = None,
    raw_iterations: int = 1,
    memla_iterations: int = 3,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    memla_c2a_policy_path: str = "",
    disable_memla_c2a_policy: bool = False,
) -> dict[str, Any]:
    repo_root, cases = load_patch_cases(pack_path, split=split, limit=limit)
    raw_client = _build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = _build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    temp_parent = None
    if _has_local_node_modules(repo_root):
        temp_parent = repo_root / ".memla_patch_exec_tmp"
        temp_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix="memla_patch_exec_",
        dir=str(temp_parent) if temp_parent else None,
    ) as tmp_dir:
        tmp_root = Path(tmp_dir)
        for index, case in enumerate(cases, start=1):
            worktree_dir = tmp_root / f"case_{index}_{case.commit_sha[:8]}"
            parent_sha = ""
            try:
                stage = "worktree_raw"
                parent_sha, _ = _build_worktree(repo_root, case.commit_sha, worktree_dir)
                raw_context = _scan_prompt_candidate_files(worktree_dir, case.prompt, limit=6)
                workflow_block, memla_context = _build_memla_workflow_block(
                    planner_model=memla_model,
                    db_path=db_path,
                    user_id=user_id,
                    repo_root=repo_root,
                    prompt=case.prompt,
                    top_k=top_k,
                    num_ctx=num_ctx,
                    provider=memla_provider or None,
                    base_url=memla_base_url or None,
                    c2a_policy_path=memla_c2a_policy_path,
                    disable_c2a_policy=disable_memla_c2a_policy,
                )
                stage = "raw_lane"
                raw_bootstrap_result = _bootstrap_worktree_dependencies(worktree_dir, case.expected_commands)
                raw_result = _evaluate_lane(
                    client=raw_client,
                    model=raw_model,
                    prompt=case.prompt,
                    worktree_root=worktree_dir,
                    expected_files=case.expected_files,
                    expected_commands=case.expected_commands,
                    expected_diff_excerpt=case.diff_excerpt,
                    context_paths=raw_context,
                    max_iterations=raw_iterations,
                    temperature=temperature,
                    num_ctx=num_ctx,
                )

                stage = "worktree_memla"
                _remove_worktree(repo_root, worktree_dir)
                worktree_dir = tmp_root / f"case_{index}_{case.commit_sha[:8]}_memla"
                _build_worktree(repo_root, case.commit_sha, worktree_dir)

                stage = "memla_lane"
                memla_bootstrap_result = _bootstrap_worktree_dependencies(worktree_dir, case.expected_commands)
                def _retry_workflow_builder(retry_prompt: str) -> tuple[str, list[str]]:
                    return _build_memla_workflow_block(
                        planner_model=memla_model,
                        db_path=db_path,
                        user_id=user_id,
                        repo_root=repo_root,
                        prompt=retry_prompt,
                        top_k=top_k,
                        num_ctx=num_ctx,
                        provider=memla_provider or None,
                        base_url=memla_base_url or None,
                        c2a_policy_path=memla_c2a_policy_path,
                        disable_c2a_policy=disable_memla_c2a_policy,
                    )

                memla_result = _evaluate_lane(
                    client=memla_client,
                    model=memla_model,
                    prompt=case.prompt,
                    worktree_root=worktree_dir,
                    expected_files=case.expected_files,
                    expected_commands=case.expected_commands,
                    expected_diff_excerpt=case.diff_excerpt,
                    context_paths=_normalize(list(raw_context or []) + list(memla_context or []))[:6],
                    workflow_block=workflow_block,
                    retry_workflow_builder=_retry_workflow_builder,
                    structured_compiler=True,
                    expected_files_missing_in_parent=_missing_expected_files(worktree_dir, case.expected_files),
                    max_iterations=memla_iterations,
                    temperature=temperature,
                    num_ctx=num_ctx,
                )
                rows.append(
                    {
                        "prompt": case.prompt,
                        "commit_sha": case.commit_sha,
                        "parent_sha": parent_sha,
                        "expected_files": case.expected_files,
                        "expected_files_missing_in_parent": _missing_expected_files(worktree_dir, case.expected_files),
                        "expected_commands": case.expected_commands,
                        "expected_diff_excerpt": case.diff_excerpt,
                        "raw_model": raw_model,
                        "raw_context_files": raw_result.context_files,
                        "raw_patch_files": raw_result.patch_files,
                        "raw_file_recall": raw_result.file_recall,
                        "raw_diff_recall": raw_result.diff_recall,
                        "raw_apply_check_passed": raw_result.apply_check_passed,
                        "raw_applied": raw_result.applied,
                        "raw_command_success_rate": raw_result.command_success_rate,
                        "raw_semantic_command_success_rate": raw_result.semantic_command_success_rate,
                        "raw_iterations_used": raw_result.iterations_used,
                        "raw_residual_constraints": raw_result.residual_constraints,
                        "raw_command_results": raw_result.command_results,
                        "raw_bootstrap_result": raw_bootstrap_result,
                        "raw_iteration_trace": raw_result.iteration_trace,
                        "raw_answer": raw_result.answer,
                        "memla_model": memla_model,
                        "memla_context_files": memla_result.context_files,
                        "memla_patch_files": memla_result.patch_files,
                        "memla_file_recall": memla_result.file_recall,
                        "memla_diff_recall": memla_result.diff_recall,
                        "memla_apply_check_passed": memla_result.apply_check_passed,
                        "memla_applied": memla_result.applied,
                        "memla_command_success_rate": memla_result.command_success_rate,
                        "memla_semantic_command_success_rate": memla_result.semantic_command_success_rate,
                        "memla_iterations_used": memla_result.iterations_used,
                        "memla_residual_constraints": memla_result.residual_constraints,
                        "memla_diagnostic_sheet": memla_result.diagnostic_sheet,
                        "memla_active_repair_lesson": memla_result.active_repair_lesson,
                        "memla_lesson_applied": memla_result.lesson_applied,
                        "memla_lesson_mastered": memla_result.lesson_mastered,
                        "memla_command_results": memla_result.command_results,
                        "memla_bootstrap_result": memla_bootstrap_result,
                        "memla_iteration_trace": memla_result.iteration_trace,
                        "memla_answer": memla_result.answer,
                    }
                )
            except Exception as exc:
                failures.append(
                    {
                        "prompt": case.prompt,
                        "commit_sha": case.commit_sha,
                        "parent_sha": parent_sha,
                        "stage": stage,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            finally:
                _remove_worktree(repo_root, worktree_dir)

    count = max(len(rows), 1)
    return {
        "generated_ts": int(time.time()),
        "repo_root": str(repo_root),
        "pack_path": str(pack_path),
        "split": split,
        "cases_requested": len(cases),
        "cases": len(rows),
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "raw_iterations": int(raw_iterations),
        "memla_iterations": int(memla_iterations),
        "failed_case_count": len(failures),
        "avg_raw_file_recall": round(sum(float(row["raw_file_recall"]) for row in rows) / count, 4),
        "avg_raw_diff_recall": round(sum(float(row["raw_diff_recall"]) for row in rows) / count, 4),
        "raw_apply_check_rate": round(sum(1.0 for row in rows if row["raw_apply_check_passed"]) / count, 4),
        "raw_apply_rate": round(sum(1.0 for row in rows if row["raw_applied"]) / count, 4),
        "avg_raw_command_success_rate": round(sum(float(row["raw_command_success_rate"]) for row in rows) / count, 4),
        "avg_raw_semantic_command_success_rate": round(sum(float(row["raw_semantic_command_success_rate"]) for row in rows) / count, 4),
        "avg_raw_iterations_used": round(sum(float(row["raw_iterations_used"]) for row in rows) / count, 4),
        "avg_memla_file_recall": round(sum(float(row["memla_file_recall"]) for row in rows) / count, 4),
        "avg_memla_diff_recall": round(sum(float(row["memla_diff_recall"]) for row in rows) / count, 4),
        "memla_apply_check_rate": round(sum(1.0 for row in rows if row["memla_apply_check_passed"]) / count, 4),
        "memla_apply_rate": round(sum(1.0 for row in rows if row["memla_applied"]) / count, 4),
        "avg_memla_command_success_rate": round(sum(float(row["memla_command_success_rate"]) for row in rows) / count, 4),
        "avg_memla_semantic_command_success_rate": round(sum(float(row["memla_semantic_command_success_rate"]) for row in rows) / count, 4),
        "avg_memla_iterations_used": round(sum(float(row["memla_iterations_used"]) for row in rows) / count, 4),
        "failed_cases": failures,
        "rows": rows,
    }


def render_patch_execution_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Patch Execution Benchmark",
        "",
        f"- Repo: `{report['repo_root']}`",
        f"- Cases: `{report['cases']}`",
        f"- Cases requested: `{report.get('cases_requested', report['cases'])}`",
        f"- Raw model: `{report['raw_model']}`",
        f"- Raw provider: `{report.get('raw_provider', 'unknown')}`",
        f"- Memla model: `{report['memla_model']}`",
        f"- Memla provider: `{report.get('memla_provider', 'unknown')}`",
        f"- Raw iterations: `{report.get('raw_iterations', 1)}`",
        f"- Memla iterations: `{report.get('memla_iterations', 1)}`",
        "",
        "## Aggregate",
        "",
        f"- Raw file recall: `{report['avg_raw_file_recall']}`",
        f"- Raw diff recall: `{report['avg_raw_diff_recall']}`",
        f"- Raw apply-check rate: `{report['raw_apply_check_rate']}`",
        f"- Raw apply rate: `{report['raw_apply_rate']}`",
        f"- Raw command success rate: `{report['avg_raw_command_success_rate']}`",
        f"- Raw semantic command success rate: `{report.get('avg_raw_semantic_command_success_rate', report['avg_raw_command_success_rate'])}`",
        f"- Raw iterations used: `{report.get('avg_raw_iterations_used', 1.0)}`",
        f"- Memla file recall: `{report['avg_memla_file_recall']}`",
        f"- Memla diff recall: `{report['avg_memla_diff_recall']}`",
        f"- Memla apply-check rate: `{report['memla_apply_check_rate']}`",
        f"- Memla apply rate: `{report['memla_apply_rate']}`",
        f"- Memla command success rate: `{report['avg_memla_command_success_rate']}`",
        f"- Memla semantic command success rate: `{report.get('avg_memla_semantic_command_success_rate', report['avg_memla_command_success_rate'])}`",
        f"- Memla iterations used: `{report.get('avg_memla_iterations_used', 1.0)}`",
        "",
    ]
    failed_cases = report.get("failed_cases") or []
    if failed_cases:
        lines.extend(
            [
                "## Failed Cases",
                "",
                *[
                    f"- `{item.get('stage')}` {item.get('prompt')} [{item.get('error_type')}]"
                    for item in failed_cases
                ],
                "",
            ]
        )
    for index, row in enumerate(report.get("rows") or [], start=1):
        lines.extend(
            [
                f"## Case {index}",
                "",
                f"**Prompt**: {row['prompt']}",
                "",
                f"- Expected files: `{', '.join(row['expected_files'])}`",
                f"- Expected commands: `{', '.join(row['expected_commands'])}`",
                f"- Raw context files: `{', '.join(row['raw_context_files'])}`",
                f"- Raw patch files: `{', '.join(row['raw_patch_files'])}`",
                f"- Raw file recall: `{row['raw_file_recall']}`",
                f"- Raw diff recall: `{row['raw_diff_recall']}`",
                f"- Raw applied: `{row['raw_applied']}`",
                f"- Raw iterations used: `{row.get('raw_iterations_used', 1)}`",
                f"- Raw residual constraints: `{', '.join(row.get('raw_residual_constraints') or [])}`",
                f"- Memla context files: `{', '.join(row['memla_context_files'])}`",
                f"- Memla patch files: `{', '.join(row['memla_patch_files'])}`",
                f"- Memla file recall: `{row['memla_file_recall']}`",
                f"- Memla diff recall: `{row['memla_diff_recall']}`",
                f"- Memla applied: `{row['memla_applied']}`",
                f"- Memla iterations used: `{row.get('memla_iterations_used', 1)}`",
                f"- Memla residual constraints: `{', '.join(row.get('memla_residual_constraints') or [])}`",
                "",
            ]
        )
    return "\n".join(lines)


def extract_technician_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    technician_cases: list[dict[str, Any]] = []
    for row in report.get("rows") or []:
        for trace in row.get("memla_iteration_trace") or []:
            technician_cases.append(
                {
                    "prompt": row.get("prompt"),
                    "commit_sha": row.get("commit_sha"),
                    "expected_files": row.get("expected_files") or [],
                    "expected_commands": row.get("expected_commands") or [],
                    "iteration": trace.get("iteration"),
                    "context_files": trace.get("context_files") or [],
                    "patch_files": trace.get("patch_files") or [],
                    "diagnostic_sheet": trace.get("diagnostic_sheet") or {},
                    "active_repair_lesson": trace.get("active_repair_lesson") or {},
                    "lesson_applied": bool(trace.get("lesson_applied")),
                    "lesson_mastered": bool(trace.get("lesson_mastered")),
                    "file_recall": trace.get("file_recall"),
                    "diff_recall": trace.get("diff_recall"),
                    "apply_check_passed": bool(trace.get("apply_check_passed")),
                    "applied": bool(trace.get("applied")),
                    "command_success_rate": trace.get("command_success_rate"),
                    "semantic_command_success_rate": trace.get("semantic_command_success_rate"),
                    "residual_constraints": trace.get("residual_constraints") or [],
                    "command_results": trace.get("command_results") or [],
                    "answer": trace.get("answer") or "",
                }
            )
    return technician_cases


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    payload = "\n".join(json.dumps(row, ensure_ascii=False) for row in rows)
    if payload:
        payload += "\n"
    path.write_text(payload, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark raw patch drafting vs Memla-assisted patch drafting on git-history cases.")
    parser.add_argument("--pack", required=True)
    parser.add_argument("--split", default="unseen", choices=("seed", "unseen"))
    parser.add_argument("--raw_model", required=True)
    parser.add_argument("--memla_model", required=True)
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--raw_iterations", type=int, default=1)
    parser.add_argument("--memla_iterations", type=int, default=3)
    parser.add_argument("--raw_provider", default="")
    parser.add_argument("--raw_base_url", default="")
    parser.add_argument("--memla_provider", default="")
    parser.add_argument("--memla_base_url", default="")
    parser.add_argument("--out_dir", default="./distill/patch_execution_benchmark")
    args = parser.parse_args(argv)

    report = run_patch_execution_benchmark(
        pack_path=args.pack,
        split=args.split,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        db_path=args.db,
        user_id=args.user_id,
        limit=args.limit,
        top_k=args.top_k,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_iterations=args.raw_iterations,
        memla_iterations=args.memla_iterations,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    technician_cases = extract_technician_cases(report)
    (out_dir / "patch_execution_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "patch_execution_report.md").write_text(render_patch_execution_markdown(report), encoding="utf-8")
    _write_jsonl(out_dir / "technician_cases.jsonl", technician_cases)
    print(f"[patch_execution_benchmark] wrote benchmark artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
