from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .comparison_runner import render_head_to_head_markdown, run_head_to_head
from .constraint_graph import infer_repo_family
from .git_history_cases import _write_cases, build_git_eval_cases
from .seed_runner import load_seed_cases, run_seed_cases


_STRUCTURAL_BOOTSTRAP_FAMILIES = {
    "python_api",
    "python_cli",
    "ts_backend_security",
    "ts_cli_tooling",
    "backend_security",
    "cli_tooling",
}


@dataclass(frozen=True)
class CurriculumRepoSpec:
    id: str
    url: str
    repo_label: str
    framework: str = ""
    notes: str = ""
    tier: str = "tier1"
    enabled: bool = True
    repo_subpath: str = "."
    local_dir: str = ""
    manifest: str = ""
    seed_count: int = 8
    unseen_count: int = 12
    recent_window: int = 45
    scan_limit: int = 120


def _progress_bar(progress: float, width: int = 28) -> str:
    clamped = max(0.0, min(1.0, float(progress)))
    filled = int(clamped * width)
    if filled <= 0:
        pointer = ""
        tail = "." * width
    elif filled >= width:
        pointer = "=" * width
        tail = ""
    else:
        pointer = "=" * (filled - 1) + ">"
        tail = "." * (width - filled)
    return f"[{pointer}{tail}]"


def _progress_line(
    *,
    progress_units: float,
    total_units: float,
    repo_index: int,
    repo_count: int,
    repo_id: str,
    stage: str,
    detail: str = "",
) -> str:
    ratio = 0.0 if total_units <= 0 else max(0.0, min(float(progress_units) / float(total_units), 1.0))
    percent = ratio * 100.0
    suffix = f" | {detail}" if detail else ""
    return (
        f"\r(=^.^=) {_progress_bar(ratio)} {percent:5.1f}% "
        f"| repo {repo_index}/{repo_count} | {repo_id} | {stage}{suffix}"
    )


def _emit_progress(
    *,
    progress_units: float,
    total_units: float,
    repo_index: int,
    repo_count: int,
    repo_id: str,
    stage: str,
    detail: str = "",
    done: bool = False,
) -> None:
    line = _progress_line(
        progress_units=progress_units,
        total_units=total_units,
        repo_index=repo_index,
        repo_count=repo_count,
        repo_id=repo_id,
        stage=stage,
        detail=detail,
    )
    if sys.stdout.isatty():
        print(line, end="\n" if done else "", flush=True)
    else:
        print(line.lstrip("\r"), flush=True)


def _slug_from_url(url: str) -> str:
    tail = url.rstrip("/").split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    return tail.strip() or "repo"


def load_repo_curriculum(path: str) -> list[CurriculumRepoSpec]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("repos") if isinstance(payload, dict) else payload
    specs: list[CurriculumRepoSpec] = []
    for row in rows or []:
        specs.append(
            CurriculumRepoSpec(
                id=str(row.get("id") or _slug_from_url(str(row.get("url") or ""))),
                url=str(row.get("url") or ""),
                repo_label=str(row.get("repo_label") or row.get("label") or _slug_from_url(str(row.get("url") or ""))),
                framework=str(row.get("framework") or ""),
                notes=str(row.get("notes") or ""),
                tier=str(row.get("tier") or "tier1"),
                enabled=bool(row.get("enabled", True)),
                repo_subpath=str(row.get("repo_subpath") or "."),
                local_dir=str(row.get("local_dir") or ""),
                manifest=str(row.get("manifest") or ""),
                seed_count=int(row.get("seed_count") or 8),
                unseen_count=int(row.get("unseen_count") or 12),
                recent_window=int(row.get("recent_window") or 45),
                scan_limit=int(row.get("scan_limit") or 120),
            )
        )
    return specs


def _resolve_repo_dir(spec: CurriculumRepoSpec, external_root: str) -> Path:
    if spec.local_dir:
        return Path(spec.local_dir)
    root = Path(external_root)
    slug = _slug_from_url(spec.url)
    direct = root / slug
    if direct.exists():
        return direct
    matches = [path for path in root.glob(f"*{slug}") if path.is_dir()]
    if len(matches) == 1:
        return matches[0]
    return direct


def _resolve_manifest(spec: CurriculumRepoSpec, repo_dir: Path) -> Path:
    if spec.manifest:
        return (repo_dir / spec.manifest).resolve()
    for candidate in ("pyproject.toml", "package.json"):
        path = repo_dir / candidate
        if path.exists():
            return path.resolve()
    raise FileNotFoundError(f"No manifest found for {spec.id} under {repo_dir}")


def _clone_repo(spec: CurriculumRepoSpec, repo_dir: Path) -> None:
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "clone", spec.url, str(repo_dir)], check=True, text=True)


def _count_transmutations(report: dict[str, Any]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in report.get("rows") or []:
        for item in row.get("memla_transmutations") or []:
            clean = " ".join(str(item or "").split())
            if clean:
                counts[clean] += 1
    return counts


def _effective_seed_threshold(
    *,
    repo_family: str,
    min_seed_accept: int,
    seed_cases: int,
    seed_role_recall: float,
) -> tuple[int, str]:
    threshold = max(1, min(int(min_seed_accept), max(int(seed_cases), 1)))
    if int(seed_cases) <= 6 and float(seed_role_recall) >= 0.4:
        ratio_threshold = max(2, math.ceil(int(seed_cases) * 0.33))
        threshold = min(threshold, ratio_threshold)
        return threshold, "tiny_ratio"
    if (
        repo_family in _STRUCTURAL_BOOTSTRAP_FAMILIES
        and int(seed_cases) >= 6
        and float(seed_role_recall) >= 0.45
        and threshold > 1
    ):
        return threshold - 1, "family_structural"
    return threshold, "default"


def _is_sparse_commit_error(exc: Exception) -> bool:
    return "need at least" in str(exc).strip().lower() and "useful commits" in str(exc).strip().lower()


def _is_retryable_timeout(exc: Exception) -> bool:
    lowered = str(exc).strip().lower()
    return "read timed out" in lowered or "connection reset" in lowered or "temporarily unavailable" in lowered


def _build_case_pack_with_fallback(
    *,
    spec: CurriculumRepoSpec,
    repo_dir: Path,
    manifest_path: Path,
    case_model: str,
    ollama_base_url: str,
) -> dict[str, Any]:
    shapes = [
        (spec.seed_count, spec.unseen_count),
        (6, 8),
        (6, 6),
        (4, 6),
        (4, 4),
    ]
    seen: set[tuple[int, int]] = set()
    last_error: Exception | None = None

    for seed_count, unseen_count in shapes:
        shape = (int(seed_count), int(unseen_count))
        if shape in seen:
            continue
        seen.add(shape)
        try:
            return build_git_eval_cases(
                repo_root=str(repo_dir),
                repo_subpath=spec.repo_subpath,
                manifest_path=str(manifest_path),
                repo_label=spec.repo_label,
                seed_count=shape[0],
                unseen_count=shape[1],
                recent_window=spec.recent_window,
                scan_limit=spec.scan_limit,
                local_model=case_model,
                ollama_base_url=ollama_base_url,
                use_local_model=True,
            )
        except Exception as exc:
            last_error = exc
            if not _is_sparse_commit_error(exc):
                raise
    if last_error is not None:
        raise last_error
    raise RuntimeError("Unable to build git-history case pack.")


def _run_head_to_head_with_retry(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    teacher_model: str,
    temperature: float,
    top_k: int,
    num_ctx: int | None,
    attempts: int = 2,
) -> dict[str, Any]:
    last_error: Exception | None = None
    for attempt in range(1, max(int(attempts), 1) + 1):
        try:
            return run_head_to_head(
                db_path=db_path,
                repo_root=repo_root,
                user_id=user_id,
                cases_path=cases_path,
                teacher_model=teacher_model,
                temperature=temperature,
                top_k=top_k,
                num_ctx=num_ctx,
            )
        except Exception as exc:
            last_error = exc
            if attempt >= attempts or not _is_retryable_timeout(exc):
                raise
            time.sleep(2.0 * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Head-to-head retry loop exited unexpectedly.")


def _assert_ollama_available(ollama_base_url: str, timeout_seconds: float = 5.0) -> None:
    base = str(ollama_base_url or "").rstrip("/")
    if not base:
        raise RuntimeError("Missing Ollama base URL for curriculum batch.")

    request = urllib.request.Request(f"{base}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status = getattr(response, "status", 200)
            if int(status) >= 400:
                raise RuntimeError(
                    f"Ollama preflight failed with HTTP {status} at {base}. Start `ollama serve` and retry."
                )
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Ollama preflight failed at {base}. Start `ollama serve` and retry."
        ) from exc


def render_batch_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Memla Repo Curriculum Batch",
        "",
        f"- Teacher model: `{summary['teacher_model']}`",
        f"- Case model: `{summary['case_model']}`",
        f"- Repos attempted: `{summary['repos_attempted']}`",
        f"- Repos with holdouts: `{summary['repos_with_holdouts']}`",
        f"- Skip threshold: `< {summary['min_seed_accept']}/{summary['default_seed_count']}` accepted seeds",
        "",
        "## Repo Results",
        "",
    ]
    for row in summary.get("results") or []:
        lines.extend(
            [
                f"### {row['id']}",
                "",
                f"- Repo: `{row['repo_label']}`",
                f"- Tier: `{row['tier']}`",
                f"- Status: `{row['status']}`",
                f"- Seed accepted: `{row['seed_accepted']}/{row['seed_cases']}`",
                f"- Seed threshold: `{row.get('seed_required_accept', summary['min_seed_accept'])}/{row['seed_cases']}` ({row.get('seed_gate_mode', 'default')})",
                f"- Seed file recall: `{row['seed_avg_file_recall']}`",
                f"- Seed role recall: `{row.get('seed_avg_role_recall', 0.0)}`",
                f"- Seed command recall: `{row['seed_avg_command_recall']}`",
            ]
        )
        if row.get("status") == "completed":
            lines.extend(
                [
                    f"- Raw file recall: `{row['avg_raw_file_recall']}`",
                    f"- Memla combined file recall: `{row['avg_memla_combined_file_recall']}`",
                    f"- Raw command recall: `{row['avg_raw_command_recall']}`",
                    f"- Memla combined command recall: `{row['avg_memla_combined_command_recall']}`",
                ]
            )
        if row.get("notes"):
            lines.append(f"- Notes: {row['notes']}")
        lines.append("")

    top_transmutations = summary.get("top_transmutations") or []
    if top_transmutations:
        lines.extend(["## Top Transmutations", ""])
        for row in top_transmutations:
            lines.append(f"- `{row['count']}` x {row['text']}")
        lines.append("")
    return "\n".join(lines)


def run_repo_curriculum(
    *,
    config_path: str,
    out_dir: str,
    external_root: str,
    teacher_model: str = "qwen3.5:9b",
    case_model: str = "qwen3.5:4b",
    user_id: str = "default",
    top_k: int = 12,
    temperature: float = 0.1,
    num_ctx: int | None = None,
    min_seed_accept: int = 4,
    clone_missing: bool = False,
    max_repos: int = 0,
    ollama_base_url: str = "http://127.0.0.1:11435",
) -> dict[str, Any]:
    specs = [spec for spec in load_repo_curriculum(config_path) if spec.enabled]
    if max_repos > 0:
        specs = specs[:max_repos]

    os.environ["LLM_PROVIDER"] = "ollama"
    os.environ["LLM_BASE_URL"] = ollama_base_url
    _assert_ollama_available(ollama_base_url)

    out_root = Path(out_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    transmutation_counts: Counter[str] = Counter()
    results: list[dict[str, Any]] = []
    total_units = max(len(specs) * 3, 1)

    for index, spec in enumerate(specs, start=1):
        repo_dir = _resolve_repo_dir(spec, external_root)
        repo_out = out_root / spec.id
        repo_out.mkdir(parents=True, exist_ok=True)
        repo_base = (index - 1) * 3

        result: dict[str, Any] = {
            "id": spec.id,
            "repo_label": spec.repo_label,
            "tier": spec.tier,
            "framework": spec.framework,
            "notes": spec.notes,
            "repo_family": "",
            "status": "pending",
            "seed_cases": spec.seed_count,
            "seed_accepted": 0,
            "seed_required_accept": int(min_seed_accept),
            "seed_gate_mode": "default",
            "seed_avg_file_recall": 0.0,
            "seed_avg_role_recall": 0.0,
            "seed_avg_command_recall": 0.0,
            "avg_raw_file_recall": 0.0,
            "avg_raw_command_recall": 0.0,
            "avg_memla_combined_file_recall": 0.0,
            "avg_memla_combined_command_recall": 0.0,
            "repo_dir": str(repo_dir),
        }

        try:
            _emit_progress(
                progress_units=repo_base + 0.15,
                total_units=total_units,
                repo_index=index,
                repo_count=len(specs),
                repo_id=spec.id,
                stage="prepare",
                detail="cloning / generating cases",
            )
            if not repo_dir.exists():
                if not clone_missing:
                    result["status"] = "missing_repo"
                    _emit_progress(
                        progress_units=repo_base + 3,
                        total_units=total_units,
                        repo_index=index,
                        repo_count=len(specs),
                        repo_id=spec.id,
                        stage="skipped",
                        detail="repo missing",
                        done=True,
                    )
                    results.append(result)
                    continue
                _clone_repo(spec, repo_dir)

            manifest_path = _resolve_manifest(spec, repo_dir)
            repo_family = infer_repo_family(str(repo_dir))
            result["repo_family"] = repo_family
            case_pack = _build_case_pack_with_fallback(
                spec=spec,
                repo_dir=repo_dir,
                manifest_path=manifest_path,
                case_model=case_model,
                ollama_base_url=ollama_base_url,
            )
            result["seed_cases"] = int(case_pack.get("seed_count") or spec.seed_count)
            result["unseen_cases"] = int(case_pack.get("unseen_count") or spec.unseen_count)

            (repo_out / "git_history_case_pack.json").write_text(
                json.dumps(case_pack, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            _write_cases(repo_out / "seed_cases.jsonl", list(case_pack["seed_cases"]))
            _write_cases(repo_out / "unseen_cases.jsonl", list(case_pack["unseen_cases"]))

            db_path = repo_out / "curriculum.sqlite"
            _emit_progress(
                progress_units=repo_base + 1.15,
                total_units=total_units,
                repo_index=index,
                repo_count=len(specs),
                repo_id=spec.id,
                stage="seed",
                detail=f"{result['seed_cases']} bootstrap cases",
            )
            seed_report = run_seed_cases(
                db_path=str(db_path),
                repo_root=str(repo_dir),
                user_id=user_id,
                model=teacher_model,
                cases=load_seed_cases(str(repo_out / "seed_cases.jsonl")),
                top_k=top_k,
                temperature=temperature,
                num_ctx=num_ctx,
            )
            (repo_out / "seed_report.json").write_text(json.dumps(seed_report, ensure_ascii=False, indent=2), encoding="utf-8")

            result["seed_accepted"] = int(seed_report.get("accepted") or 0)
            result["seed_avg_file_recall"] = float(seed_report.get("avg_file_recall") or 0.0)
            result["seed_avg_role_recall"] = float(seed_report.get("avg_role_recall") or 0.0)
            result["seed_avg_command_recall"] = float(seed_report.get("avg_command_recall") or 0.0)
            seed_required_accept, seed_gate_mode = _effective_seed_threshold(
                repo_family=repo_family,
                min_seed_accept=min_seed_accept,
                seed_cases=int(result["seed_cases"]),
                seed_role_recall=float(result["seed_avg_role_recall"]),
            )
            result["seed_required_accept"] = int(seed_required_accept)
            result["seed_gate_mode"] = seed_gate_mode

            if result["seed_accepted"] < seed_required_accept:
                result["status"] = "skipped_low_seed_signal"
                _emit_progress(
                    progress_units=repo_base + 3,
                    total_units=total_units,
                    repo_index=index,
                        repo_count=len(specs),
                        repo_id=spec.id,
                        stage="skipped",
                        detail=(
                            f"seeded {result['seed_accepted']}/{result['seed_cases']} "
                            f"(need {seed_required_accept})"
                        ),
                        done=True,
                    )
                results.append(result)
                continue

            _emit_progress(
                progress_units=repo_base + 2.15,
                total_units=total_units,
                repo_index=index,
                repo_count=len(specs),
                repo_id=spec.id,
                stage="holdout",
                detail=f"{result['unseen_cases']} unseen cases",
            )
            comparison = _run_head_to_head_with_retry(
                db_path=str(db_path),
                repo_root=str(repo_dir),
                user_id=user_id,
                cases_path=str(repo_out / "unseen_cases.jsonl"),
                teacher_model=teacher_model,
                temperature=temperature,
                top_k=top_k,
                num_ctx=num_ctx,
            )
            comparison_out = repo_out / "head_to_head"
            comparison_out.mkdir(parents=True, exist_ok=True)
            (comparison_out / "comparison_report.json").write_text(
                json.dumps(comparison, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            (comparison_out / "comparison_report.md").write_text(
                render_head_to_head_markdown(comparison),
                encoding="utf-8",
            )

            result["status"] = "completed"
            result["avg_raw_file_recall"] = float(comparison.get("avg_raw_file_recall") or 0.0)
            result["avg_raw_command_recall"] = float(comparison.get("avg_raw_command_recall") or 0.0)
            result["avg_memla_combined_file_recall"] = float(comparison.get("avg_memla_combined_file_recall") or 0.0)
            result["avg_memla_combined_command_recall"] = float(comparison.get("avg_memla_combined_command_recall") or 0.0)
            transmutation_counts.update(_count_transmutations(comparison))
            _emit_progress(
                progress_units=repo_base + 3,
                total_units=total_units,
                repo_index=index,
                repo_count=len(specs),
                repo_id=spec.id,
                stage="done",
                detail=(
                    f"raw {result['avg_raw_file_recall']:.4f} -> "
                    f"memla {result['avg_memla_combined_file_recall']:.4f}"
                ),
                done=True,
            )
        except Exception as exc:
            result["status"] = "error"
            result["error"] = str(exc)
            _emit_progress(
                progress_units=repo_base + 3,
                total_units=total_units,
                repo_index=index,
                repo_count=len(specs),
                repo_id=spec.id,
                stage="error",
                detail=str(exc)[:80],
                done=True,
            )

        results.append(result)

    summary = {
        "generated_ts": int(time.time()),
        "teacher_model": teacher_model,
        "case_model": case_model,
        "config_path": str(Path(config_path).resolve()),
        "out_dir": str(out_root.resolve()),
        "repos_attempted": len(specs),
        "repos_with_holdouts": sum(1 for row in results if row.get("status") == "completed"),
        "min_seed_accept": min_seed_accept,
        "default_seed_count": specs[0].seed_count if specs else 0,
        "results": results,
        "top_transmutations": [
            {"text": text, "count": count}
            for text, count in transmutation_counts.most_common(20)
        ],
    }
    _emit_progress(
        progress_units=total_units,
        total_units=total_units,
        repo_index=len(specs),
        repo_count=len(specs),
        repo_id="batch",
        stage="complete",
        detail=f"{summary['repos_with_holdouts']} holdouts finished",
        done=True,
    )
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Memla's overnight repo curriculum.")
    parser.add_argument("--config", required=True)
    parser.add_argument("--out_dir", default="./distill/repo_curriculum_run")
    parser.add_argument("--external_root", default="./external")
    parser.add_argument("--teacher_model", default="qwen3.5:9b")
    parser.add_argument("--case_model", default="qwen3.5:4b")
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--min_seed_accept", type=int, default=4)
    parser.add_argument("--max_repos", type=int, default=0)
    parser.add_argument("--ollama_base_url", default="http://127.0.0.1:11435")
    parser.add_argument("--clone_missing", action="store_true")
    args = parser.parse_args(argv)

    summary = run_repo_curriculum(
        config_path=args.config,
        out_dir=args.out_dir,
        external_root=args.external_root,
        teacher_model=args.teacher_model,
        case_model=args.case_model,
        user_id=args.user_id,
        top_k=args.top_k,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        min_seed_accept=args.min_seed_accept,
        clone_missing=args.clone_missing,
        max_repos=args.max_repos,
        ollama_base_url=args.ollama_base_url,
    )

    out_root = Path(args.out_dir)
    out_root.mkdir(parents=True, exist_ok=True)
    (out_root / "batch_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "batch_summary.md").write_text(render_batch_markdown(summary), encoding="utf-8")
    print(json.dumps({"summary": str((out_root / "batch_summary.json").resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
