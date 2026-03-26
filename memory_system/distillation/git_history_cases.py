from __future__ import annotations

import argparse
import json
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from ..ollama_client import ChatMessage, UniversalLLMClient


GENERIC_SUBJECTS = {
    "changes",
    "change",
    "latest changes",
    "ui",
    "ui changes",
    "lots of changes",
    "lot of changes",
    "whole lotta changes",
    "whole lotta changess",
    "big fixes",
    "new changes",
    "latest change",
    "fixes",
    "fix",
    "again",
    "back",
}

CODE_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".json"}
LINT_EXTENSIONS = {".py", ".js", ".jsx", ".ts", ".tsx"}
SPECIAL_CODE_FILES = {"package.json", "eslint.config.js", "vite.config.js", "pyproject.toml", "setup.py", "Makefile"}


@dataclass(frozen=True)
class GitCommitRecord:
    sha: str
    subject: str
    changed_files: list[str]
    diff_excerpt: list[str]


@dataclass(frozen=True)
class GitEvalCase:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    accept_strategy: str
    min_file_recall: float
    attach_expected_commands: bool
    commit_sha: str
    commit_subject: str
    changed_files: list[str]


def _run_git(repo_root: str, args: list[str]) -> str:
    proc = subprocess.run(
        ["git", "-c", f"safe.directory={Path(repo_root).resolve()}", "-C", repo_root, *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return proc.stdout


def _clean_relative(path: str, repo_subpath: str) -> str:
    clean = path.strip().replace("\\", "/")
    prefix = repo_subpath.strip().replace("\\", "/").rstrip("/")
    if clean.startswith(prefix + "/"):
        return clean[len(prefix) + 1 :]
    return clean


def _is_interesting_file(path: str) -> bool:
    clean = path.strip().replace("\\", "/")
    name = Path(clean).name
    if not clean:
        return False
    if clean.startswith(("dist/", "node_modules/", "public/")):
        return False
    if name in {".env", ".env.local", "package-lock.json"}:
        return False
    if Path(clean).suffix.lower() not in CODE_EXTENSIONS and name not in SPECIAL_CODE_FILES:
        return False
    return True


def _interesting_changed_files(paths: list[str], repo_subpath: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for path in paths:
        rel = _clean_relative(path, repo_subpath)
        if not _is_interesting_file(rel):
            continue
        key = rel.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(rel)
    return out


def _derive_expected_commands(changed_files: list[str], package_json: dict[str, Any]) -> list[str]:
    scripts = dict(package_json.get("scripts") or {})
    commands: list[str] = []
    suffixes = {Path(path).suffix.lower() for path in changed_files}
    changed_names = {Path(path).name for path in changed_files}
    touches_code = any(suffix in CODE_EXTENSIONS for suffix in suffixes) or bool(changed_names & {"package.json", "eslint.config.js", "vite.config.js"})
    touches_lintable = any(suffix in LINT_EXTENSIONS for suffix in suffixes) or bool(changed_names & {"eslint.config.js"})
    if touches_code and "build" in scripts:
        commands.append("npm run build")
    if touches_lintable and "lint" in scripts:
        commands.append("npm run lint")
    return commands


def _derive_expected_python_commands(changed_files: list[str], pyproject: dict[str, Any]) -> list[str]:
    commands: list[str] = []
    tool_section = dict(pyproject.get("tool") or {})
    optional_deps = dict((pyproject.get("project") or {}).get("optional-dependencies") or {})
    dev_deps = {
        str(dep).lower()
        for deps in optional_deps.values()
        for dep in (deps or [])
    }
    touches_python = any(Path(path).suffix.lower() == ".py" for path in changed_files)
    touches_project_config = any(Path(path).name in {"pyproject.toml", "setup.py"} for path in changed_files)

    pytest_configured = "pytest" in tool_section or any("pytest" in dep for dep in dev_deps)
    ruff_configured = "ruff" in tool_section or any("ruff" in dep for dep in dev_deps)

    if (touches_python or touches_project_config) and pytest_configured:
        commands.append("pytest")
    if touches_python and ruff_configured:
        commands.append("ruff check .")
    return commands


def _load_manifest(path: str) -> tuple[str, dict[str, Any]]:
    manifest_path = Path(path)
    suffix = manifest_path.suffix.lower()
    if manifest_path.name == "pyproject.toml" or suffix == ".toml":
        return "pyproject", tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    return "package_json", json.loads(manifest_path.read_text(encoding="utf-8"))


def _sanitize_subject(subject: str) -> str:
    clean = " ".join((subject or "").strip().split())
    return clean.strip("-: ")


def _is_generic_subject(subject: str) -> bool:
    clean = _sanitize_subject(subject).lower()
    return not clean or clean in GENERIC_SUBJECTS or len(clean) < 6


def _path_feature_label(path: str) -> str:
    stem = Path(path).stem
    spaced = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", stem).replace("-", " ").replace("_", " ")
    return spaced.strip().lower()


def _heuristic_prompt(subject: str, changed_files: list[str]) -> str:
    if not _is_generic_subject(subject):
        clean = _sanitize_subject(subject)
        if clean.lower().startswith(("fix", "add", "update", "remove", "refactor", "ship", "improve", "componentize")):
            return clean[0].upper() + clean[1:]
        return f"Implement {clean}"

    features = []
    for path in changed_files:
        label = _path_feature_label(path)
        if label and label not in features:
            features.append(label)
        if len(features) >= 3:
            break
    if not features:
        return "Update the booking app flow and supporting frontend logic"
    if len(features) == 1:
        return f"Improve the {features[0]} flow and supporting frontend behavior"
    if len(features) == 2:
        return f"Update the {features[0]} and {features[1]} flow in the booking app"
    return f"Refine the {features[0]}, {features[1]}, and {features[2]} flow in the booking app"


def _extract_diff_excerpt(diff_text: str, limit: int = 16) -> list[str]:
    lines: list[str] = []
    for raw in diff_text.splitlines():
        if raw.startswith(("diff --git", "index ", "@@", "---", "+++", "Binary files ")):
            continue
        if not raw.startswith(("+", "-")):
            continue
        clean = raw[1:].strip()
        if not clean or clean.startswith(("import ", "export ", "}")):
            continue
        clean = " ".join(clean.split())
        if len(clean) < 6:
            continue
        if clean not in lines:
            lines.append(clean[:140])
        if len(lines) >= limit:
            break
    return lines


def load_commit_records(
    *,
    repo_root: str,
    repo_subpath: str,
    scan_limit: int = 80,
) -> list[GitCommitRecord]:
    sha_lines = _run_git(repo_root, ["rev-list", "--reverse", "HEAD", "--", repo_subpath]).splitlines()
    records: list[GitCommitRecord] = []
    for sha in sha_lines:
        if len(records) >= scan_limit:
            break
        subject = _run_git(repo_root, ["show", "-s", "--format=%s", sha]).strip()
        changed = _run_git(repo_root, ["show", "--format=", "--name-only", "--no-renames", sha, "--", repo_subpath]).splitlines()
        interesting = _interesting_changed_files(changed, repo_subpath)
        if not interesting:
            continue
        diff_text = _run_git(repo_root, ["show", "--format=", "--unified=0", sha, "--", repo_subpath])
        records.append(
            GitCommitRecord(
                sha=sha,
                subject=subject,
                changed_files=interesting,
                diff_excerpt=_extract_diff_excerpt(diff_text),
            )
        )
    return records


def _diversify_records(records: list[GitCommitRecord], limit: int) -> list[GitCommitRecord]:
    if len(records) <= limit:
        return list(records)

    chosen: list[GitCommitRecord] = []
    held_back: list[GitCommitRecord] = []
    signature_counts: dict[tuple[str, ...], int] = {}
    single_file_counts: dict[str, int] = {}

    for record in records:
        signature = tuple(record.changed_files)
        sig_count = signature_counts.get(signature, 0)
        single_key = record.changed_files[0] if len(record.changed_files) == 1 else ""
        single_count = single_file_counts.get(single_key, 0) if single_key else 0

        too_repetitive = sig_count >= 2 or (single_key and single_count >= 4)
        if too_repetitive:
            held_back.append(record)
            continue

        chosen.append(record)
        signature_counts[signature] = sig_count + 1
        if single_key:
            single_file_counts[single_key] = single_count + 1
        if len(chosen) >= limit:
            return chosen

    for record in held_back:
        if len(chosen) >= limit:
            break
        chosen.append(record)
    return chosen


def _synthesize_prompt(
    *,
    record: GitCommitRecord,
    repo_label: str,
    client: Optional[UniversalLLMClient],
    model: str,
) -> str:
    heuristic = _heuristic_prompt(record.subject, record.changed_files)
    if client is None:
        return heuristic

    user_prompt = "\n".join(
        [
            f"Repo: {repo_label}",
            f"Commit subject: {record.subject}",
            f"Changed files: {', '.join(record.changed_files[:8])}",
            "Diff excerpt:",
            *[f"- {line}" for line in record.diff_excerpt[:10]],
            "",
            "Write one short coding task prompt a developer could ask an AI coding assistant.",
            "Rules:",
            "- One sentence only.",
            "- Do not mention exact file paths.",
            "- Focus on the user-visible or engineering task implied by the change.",
            "- Keep it under 22 words.",
            f"- If the commit message is vague, infer the task from the changed files and diff excerpt.",
        ]
    )
    try:
        out = client.chat(
            model=model,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "You convert git changes into clean coding task prompts. "
                        "Output only the prompt sentence with no bullets or quotes."
                    ),
                ),
                ChatMessage(role="user", content=user_prompt),
            ],
            temperature=0.1,
            num_ctx=8192,
        ).strip()
        clean = " ".join(out.split()).strip("\"' ")
        if clean:
            return clean
    except Exception:
        pass
    return heuristic


def build_git_eval_cases(
    *,
    repo_root: str,
    repo_subpath: str,
    package_json_path: str = "",
    manifest_path: str = "",
    repo_label: str,
    seed_count: int = 10,
    unseen_count: int = 20,
    recent_window: int = 45,
    scan_limit: int = 120,
    local_model: str = "qwen3.5:4b",
    ollama_base_url: str = "http://127.0.0.1:11435",
    use_local_model: bool = True,
) -> dict[str, Any]:
    records = load_commit_records(repo_root=repo_root, repo_subpath=repo_subpath, scan_limit=scan_limit)
    if recent_window > 0 and len(records) > recent_window:
        records = records[-recent_window:]
    needed = seed_count + unseen_count
    records = _diversify_records(records, needed)
    if len(records) < needed:
        raise RuntimeError(f"Need at least {needed} useful commits, found {len(records)}")

    effective_manifest = manifest_path or package_json_path
    if not effective_manifest:
        raise RuntimeError("manifest_path or package_json_path is required")
    manifest_kind, manifest_data = _load_manifest(effective_manifest)
    client = UniversalLLMClient(provider="ollama", base_url=ollama_base_url) if use_local_model else None

    selected = records[:needed]
    cases: list[GitEvalCase] = []
    for record in selected:
        cases.append(
            GitEvalCase(
                prompt=_synthesize_prompt(record=record, repo_label=repo_label, client=client, model=local_model),
                expected_files=list(record.changed_files),
                expected_commands=(
                    _derive_expected_commands(record.changed_files, manifest_data)
                    if manifest_kind == "package_json"
                    else _derive_expected_python_commands(record.changed_files, manifest_data)
                ),
                accept_strategy="git_history_file_grounded",
                min_file_recall=0.25,
                attach_expected_commands=True,
                commit_sha=record.sha,
                commit_subject=record.subject,
                changed_files=list(record.changed_files),
            )
        )

    seed_cases = cases[:seed_count]
    unseen_cases = cases[seed_count : seed_count + unseen_count]
    return {
        "repo_root": repo_root,
        "repo_subpath": repo_subpath,
        "repo_label": repo_label,
        "manifest_path": effective_manifest,
        "local_model": local_model if use_local_model else "",
        "ollama_base_url": ollama_base_url if use_local_model else "",
        "seed_count": len(seed_cases),
        "unseen_count": len(unseen_cases),
        "seed_cases": [asdict(case) for case in seed_cases],
        "unseen_cases": [asdict(case) for case in unseen_cases],
    }


def _write_cases(path: Path, cases: list[dict[str, Any]]) -> None:
    lines = []
    for case in cases:
        payload = {
            "prompt": case["prompt"],
            "expected_files": case["expected_files"],
            "expected_commands": case["expected_commands"],
        }
        if case.get("accept_strategy"):
            payload["accept_strategy"] = case["accept_strategy"]
        if case.get("min_file_recall") is not None:
            payload["min_file_recall"] = case["min_file_recall"]
        if case.get("attach_expected_commands") is not None:
            payload["attach_expected_commands"] = case["attach_expected_commands"]
        lines.append(json.dumps(payload, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate second-repo coding eval cases from git history.")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--repo_subpath", required=True)
    parser.add_argument("--package_json", default="")
    parser.add_argument("--manifest", default="")
    parser.add_argument("--repo_label", default="booking app")
    parser.add_argument("--seed_count", type=int, default=10)
    parser.add_argument("--unseen_count", type=int, default=20)
    parser.add_argument("--recent_window", type=int, default=45)
    parser.add_argument("--scan_limit", type=int, default=120)
    parser.add_argument("--local_model", default="qwen3.5:4b")
    parser.add_argument("--ollama_base_url", default="http://127.0.0.1:11435")
    parser.add_argument("--no_local_model", action="store_true")
    parser.add_argument("--out_dir", default="./distill/second_repo_booking")
    args = parser.parse_args(argv)

    report = build_git_eval_cases(
        repo_root=args.repo_root,
        repo_subpath=args.repo_subpath,
        package_json_path=args.package_json,
        manifest_path=args.manifest,
        repo_label=args.repo_label,
        seed_count=args.seed_count,
        unseen_count=args.unseen_count,
        recent_window=args.recent_window,
        scan_limit=args.scan_limit,
        local_model=args.local_model,
        ollama_base_url=args.ollama_base_url,
        use_local_model=not args.no_local_model,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta_path = out_dir / "git_history_case_pack.json"
    seed_path = out_dir / "seed_cases.jsonl"
    unseen_path = out_dir / "unseen_cases.jsonl"

    meta_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_cases(seed_path, list(report["seed_cases"]))
    _write_cases(unseen_path, list(report["unseen_cases"]))

    print(
        json.dumps(
            {
                "meta": str(meta_path),
                "seed": str(seed_path),
                "unseen": str(unseen_path),
                "seed_count": report["seed_count"],
                "unseen_count": report["unseen_count"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
