from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


def _run_git(repo_root: Path, *args: str) -> str:
    git = shutil.which("git")
    if not git:
        return ""
    try:
        completed = subprocess.run(
            [git, *args],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except Exception:
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout


def capture_workspace_state(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
    """Capture current repo diff/touched files for coding-trace enrichment.

    The first version is intentionally git-first. If the path is not a git repo,
    we still return a stable empty payload so the distillation pipeline can proceed.
    """
    root = Path(repo_root).resolve()
    inside = _run_git(root, "rev-parse", "--is-inside-work-tree").strip().lower()
    if inside != "true":
        return {
            "repo_root": str(root),
            "vcs": "none",
            "touched_files": [],
            "patch_text": "",
        }

    unstaged_names = _run_git(root, "diff", "--name-only")
    staged_names = _run_git(root, "diff", "--cached", "--name-only")
    untracked_names = _run_git(root, "ls-files", "--others", "--exclude-standard")
    touched_files = sorted(
        {
            line.strip()
            for block in (unstaged_names, staged_names, untracked_names)
            for line in block.splitlines()
            if line.strip()
        }
    )

    patch_blocks = []
    unstaged_patch = _run_git(root, "diff", "--no-ext-diff", "--unified=0")
    staged_patch = _run_git(root, "diff", "--cached", "--no-ext-diff", "--unified=0")
    if staged_patch.strip():
        patch_blocks.append(staged_patch.strip())
    if unstaged_patch.strip():
        patch_blocks.append(unstaged_patch.strip())

    patch_text = "\n\n".join(block for block in patch_blocks if block).strip()
    if len(patch_text) > 120_000:
        patch_text = patch_text[:120_000] + "\n\n[truncated]"

    return {
        "repo_root": str(root),
        "vcs": "git",
        "touched_files": touched_files,
        "patch_text": patch_text,
    }
