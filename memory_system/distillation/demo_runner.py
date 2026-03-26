from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .eval_harness import evaluate_workflow_plans, load_eval_cases
from .seed_runner import load_seed_cases, run_seed_cases


@dataclass(frozen=True)
class DemoSummary:
    mode: str
    generated_ts: int
    repo_root: str
    db_path: str
    planner_model: str
    teacher_model: str
    cases_path: str
    bootstrap_cases_path: str
    refinement_cases_path: str
    baseline: dict[str, Any] | None
    bootstrap_seed: dict[str, Any] | None
    after_bootstrap: dict[str, Any] | None
    refinement_seed: dict[str, Any] | None
    final_report: dict[str, Any]


def run_showcase_demo(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    planner_model: str = "qwen3.5:4b",
    top_k: int = 12,
) -> DemoSummary:
    final_report = evaluate_workflow_plans(
        db_path=db_path,
        repo_root=repo_root,
        user_id=user_id,
        cases=load_eval_cases(cases_path),
        model=planner_model,
        top_k=top_k,
    )
    return DemoSummary(
        mode="showcase",
        generated_ts=int(time.time()),
        repo_root=repo_root,
        db_path=db_path,
        planner_model=planner_model,
        teacher_model="",
        cases_path=cases_path,
        bootstrap_cases_path="",
        refinement_cases_path="",
        baseline=None,
        bootstrap_seed=None,
        after_bootstrap=None,
        refinement_seed=None,
        final_report=final_report,
    )


def run_bootstrap_demo(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    holdout_cases_path: str,
    bootstrap_cases_path: str,
    teacher_model: str,
    planner_model: str = "qwen3.5:4b",
    refinement_cases_path: str = "",
    top_k: int = 12,
    accept_threshold: float = 0.5,
) -> DemoSummary:
    holdout_cases = load_eval_cases(holdout_cases_path)
    baseline = evaluate_workflow_plans(
        db_path=db_path,
        repo_root=repo_root,
        user_id=user_id,
        cases=holdout_cases,
        model=planner_model,
        top_k=top_k,
    )
    bootstrap_seed = run_seed_cases(
        db_path=db_path,
        repo_root=repo_root,
        user_id=user_id,
        model=teacher_model,
        cases=load_seed_cases(bootstrap_cases_path),
        top_k=top_k,
        accept_threshold=accept_threshold,
    )
    after_bootstrap = evaluate_workflow_plans(
        db_path=db_path,
        repo_root=repo_root,
        user_id=user_id,
        cases=holdout_cases,
        model=planner_model,
        top_k=top_k,
    )

    refinement_seed: dict[str, Any] | None = None
    final_report = after_bootstrap
    if refinement_cases_path:
        refinement_seed = run_seed_cases(
            db_path=db_path,
            repo_root=repo_root,
            user_id=user_id,
            model=teacher_model,
            cases=load_seed_cases(refinement_cases_path),
            top_k=top_k,
            accept_threshold=accept_threshold,
        )
        final_report = evaluate_workflow_plans(
            db_path=db_path,
            repo_root=repo_root,
            user_id=user_id,
            cases=holdout_cases,
            model=planner_model,
            top_k=top_k,
        )

    return DemoSummary(
        mode="bootstrap",
        generated_ts=int(time.time()),
        repo_root=repo_root,
        db_path=db_path,
        planner_model=planner_model,
        teacher_model=teacher_model,
        cases_path=holdout_cases_path,
        bootstrap_cases_path=bootstrap_cases_path,
        refinement_cases_path=refinement_cases_path,
        baseline=baseline,
        bootstrap_seed=bootstrap_seed,
        after_bootstrap=after_bootstrap,
        refinement_seed=refinement_seed,
        final_report=final_report,
    )


def render_demo_markdown(summary: DemoSummary) -> str:
    lines = [
        "# Memla Coding Distillation Demo",
        "",
        f"- Mode: `{summary.mode}`",
        f"- Repo: `{summary.repo_root}`",
        f"- DB: `{summary.db_path}`",
        f"- Planner model: `{summary.planner_model}`",
    ]
    if summary.teacher_model:
        lines.append(f"- Teacher model: `{summary.teacher_model}`")
    lines.extend(
        [
            f"- Holdout cases: `{summary.cases_path}`",
            "",
        ]
    )
    if summary.baseline:
        lines.extend(
            [
                "## Stage Scores",
                "",
                f"- Baseline file recall: `{summary.baseline['avg_file_recall']}`",
                f"- Baseline command recall: `{summary.baseline['avg_command_recall']}`",
            ]
        )
        if summary.bootstrap_seed:
            lines.append(f"- Bootstrap accept rate: `{summary.bootstrap_seed['accept_rate']}`")
        if summary.after_bootstrap:
            lines.append(f"- After bootstrap file recall: `{summary.after_bootstrap['avg_file_recall']}`")
            lines.append(f"- After bootstrap command recall: `{summary.after_bootstrap['avg_command_recall']}`")
        if summary.refinement_seed:
            lines.append(f"- Refinement accept rate: `{summary.refinement_seed['accept_rate']}`")
        lines.append(f"- Final file recall: `{summary.final_report['avg_file_recall']}`")
        lines.append(f"- Final command recall: `{summary.final_report['avg_command_recall']}`")
        lines.append("")
    else:
        lines.extend(
            [
                "## Current Capability",
                "",
                f"- File recall: `{summary.final_report['avg_file_recall']}`",
                f"- Command recall: `{summary.final_report['avg_command_recall']}`",
                "",
            ]
        )

    lines.extend(
        [
            "## Showcase Cases",
            "",
        ]
    )
    for index, row in enumerate(summary.final_report.get("rows") or [], start=1):
        lines.extend(
            [
                f"### Case {index}",
                "",
                f"**Prompt**: {row['prompt']}",
                "",
                f"- Predicted files: `{', '.join(row.get('predicted_files') or [])}`",
                f"- Predicted commands: `{', '.join(row.get('predicted_commands') or [])}`",
                f"- Predicted tests: `{', '.join(row.get('predicted_tests') or [])}`",
                f"- File recall: `{row['file_recall']}`",
                f"- Command recall: `{row['command_recall']}`",
            ]
        )
        patch_steps = row.get("patch_steps") or []
        if patch_steps:
            lines.append("- Patch steps:")
            for step in patch_steps[:4]:
                lines.append(f"  - {step}")
        lines.append("")

    lines.extend(
        [
            "## Run It",
            "",
            "```powershell",
            "cd \"C:\\Users\\samat\\Project Memory\\Project-Memory\"",
        ]
    )
    if summary.mode == "bootstrap":
        lines.extend(
            [
                ". .\\.anthropic_env.ps1",
                "py -3 -m memory_system.distillation.demo_runner --mode bootstrap "
                f"--db \"{summary.db_path}\" "
                f"--repo_root \"{summary.repo_root}\" "
                f"--user_id default "
                f"--planner_model {summary.planner_model} "
                f"--teacher_model {summary.teacher_model} "
                f"--holdout_cases \"{summary.cases_path}\" "
                f"--bootstrap_cases \"{summary.bootstrap_cases_path}\" "
                + (
                    f"--refinement_cases \"{summary.refinement_cases_path}\" "
                    if summary.refinement_cases_path
                    else ""
                )
                + "--out_dir .\\distill\\demo_run",
            ]
        )
    else:
        lines.append(
            "py -3 -m memory_system.distillation.demo_runner --mode showcase "
            f"--db \"{summary.db_path}\" "
            f"--repo_root \"{summary.repo_root}\" "
            f"--user_id default "
            f"--planner_model {summary.planner_model} "
            f"--holdout_cases \"{summary.cases_path}\" "
            "--out_dir .\\distill\\demo_run"
        )
    lines.extend(["```", ""])
    return "\n".join(lines)


def _summary_to_json(summary: DemoSummary) -> dict[str, Any]:
    return {
        "mode": summary.mode,
        "generated_ts": summary.generated_ts,
        "repo_root": summary.repo_root,
        "db_path": summary.db_path,
        "planner_model": summary.planner_model,
        "teacher_model": summary.teacher_model,
        "cases_path": summary.cases_path,
        "bootstrap_cases_path": summary.bootstrap_cases_path,
        "refinement_cases_path": summary.refinement_cases_path,
        "baseline": summary.baseline,
        "bootstrap_seed": summary.bootstrap_seed,
        "after_bootstrap": summary.after_bootstrap,
        "refinement_seed": summary.refinement_seed,
        "final_report": summary.final_report,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a ready-made Memla coding distillation demo.")
    parser.add_argument("--mode", choices=["showcase", "bootstrap"], default="showcase")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--planner_model", default="qwen3.5:4b")
    parser.add_argument("--teacher_model", default="")
    parser.add_argument("--holdout_cases", default="./distill/coding_holdout_cases.jsonl")
    parser.add_argument("--bootstrap_cases", default="./distill/coding_bootstrap_cases.jsonl")
    parser.add_argument("--refinement_cases", default="./distill/coding_workflow_planner_repair_case.jsonl")
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--accept_threshold", type=float, default=0.5)
    parser.add_argument("--out_dir", default="./distill/demo_run")
    args = parser.parse_args(argv)

    if args.mode == "bootstrap" and not args.teacher_model:
        raise SystemExit("--teacher_model is required for bootstrap mode")

    if args.mode == "bootstrap":
        summary = run_bootstrap_demo(
            db_path=args.db,
            repo_root=args.repo_root,
            user_id=args.user_id,
            holdout_cases_path=args.holdout_cases,
            bootstrap_cases_path=args.bootstrap_cases,
            teacher_model=args.teacher_model,
            planner_model=args.planner_model,
            refinement_cases_path=args.refinement_cases,
            top_k=args.top_k,
            accept_threshold=args.accept_threshold,
        )
    else:
        summary = run_showcase_demo(
            db_path=args.db,
            repo_root=args.repo_root,
            user_id=args.user_id,
            cases_path=args.holdout_cases,
            planner_model=args.planner_model,
            top_k=args.top_k,
        )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "demo_summary.json").write_text(
        json.dumps(_summary_to_json(summary), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "demo_report.md").write_text(render_demo_markdown(summary), encoding="utf-8")
    print(f"[demo_runner] wrote demo artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
