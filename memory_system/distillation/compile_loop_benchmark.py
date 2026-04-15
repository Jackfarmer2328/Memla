from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coding_proxy import CODING_BASE_SYSTEM, CodingSession
from .eval_harness import load_eval_cases
from .seed_runner import _extract_answer_commands, _extract_answer_files
from ..ollama_client import ChatMessage, UniversalLLMClient


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


def _shorten(text: str, limit: int = 240) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


@dataclass(frozen=True)
class CompileLoopBenchmarkRow:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    raw_answer: str
    raw_files: list[str]
    raw_commands: list[str]
    raw_file_recall: float
    raw_command_recall: float
    plan_only_answer: str
    plan_only_plan_files: list[str]
    plan_only_plan_commands: list[str]
    plan_only_plan_tests: list[str]
    plan_only_answer_files: list[str]
    plan_only_answer_commands: list[str]
    plan_only_combined_files: list[str]
    plan_only_combined_commands: list[str]
    plan_only_plan_file_recall: float
    plan_only_plan_command_recall: float
    plan_only_combined_file_recall: float
    plan_only_combined_command_recall: float
    plan_only_prior_trace_ids: list[int]
    compile_answer: str
    compile_plan_files: list[str]
    compile_plan_commands: list[str]
    compile_plan_tests: list[str]
    compile_answer_files: list[str]
    compile_answer_commands: list[str]
    compile_combined_files: list[str]
    compile_combined_commands: list[str]
    compile_plan_file_recall: float
    compile_plan_command_recall: float
    compile_combined_file_recall: float
    compile_combined_command_recall: float
    compile_validated_files: list[str]
    compile_validated_commands: list[str]
    compile_residual_constraints: list[str]
    compile_prior_trace_ids: list[int]


def run_compile_loop_benchmark(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    model: str,
    temperature: float = 0.1,
    top_k: int = 12,
    num_ctx: int | None = None,
    memla_c2a_policy_path: str = "",
    disable_memla_c2a_policy: bool = False,
) -> dict[str, Any]:
    client = UniversalLLMClient.from_env()
    cases = load_eval_cases(cases_path)
    base_db = Path(db_path)

    with tempfile.TemporaryDirectory(prefix="memla_compile_loop_bench_") as tmp_dir:
        tmp_root = Path(tmp_dir)
        plan_only_db = tmp_root / "plan_only.sqlite"
        compile_db = tmp_root / "compile.sqlite"
        shutil.copyfile(base_db, plan_only_db)
        shutil.copyfile(base_db, compile_db)

        rows: list[CompileLoopBenchmarkRow] = []
        failures: list[dict[str, Any]] = []
        for case in cases:
            plan_only_session = CodingSession(
                model=model,
                db_path=str(plan_only_db),
                user_id=user_id,
                repo_root=repo_root,
                temperature=temperature,
                top_k=top_k,
                num_ctx=num_ctx,
                enable_compile_loop=False,
                c2a_policy_path=memla_c2a_policy_path,
                disable_c2a_policy=disable_memla_c2a_policy,
            )
            compile_session = CodingSession(
                model=model,
                db_path=str(compile_db),
                user_id=user_id,
                repo_root=repo_root,
                temperature=temperature,
                top_k=top_k,
                num_ctx=num_ctx,
                enable_compile_loop=True,
                c2a_policy_path=memla_c2a_policy_path,
                disable_c2a_policy=disable_memla_c2a_policy,
            )
            stage = "raw"
            try:
                stage = "raw"
                raw_answer = client.chat(
                    model=model,
                    messages=[
                        ChatMessage(role="system", content=CODING_BASE_SYSTEM),
                        ChatMessage(role="user", content=case.prompt),
                    ],
                    temperature=temperature,
                    num_ctx=num_ctx,
                ).strip()
                raw_files = _normalize(_extract_answer_files(raw_answer))
                raw_commands = _normalize(_extract_answer_commands(raw_answer))
                raw_file_recall = _score_overlap(raw_files, case.expected_files)
                raw_command_recall = _score_overlap(raw_commands, case.expected_commands)

                stage = "planning_only"
                plan_only_result = plan_only_session.ask(case.prompt)
                plan_only_answer_files = _normalize(_extract_answer_files(plan_only_result.answer))
                plan_only_answer_commands = _normalize(_extract_answer_commands(plan_only_result.answer))
                plan_only_plan_commands = _normalize(
                    list(plan_only_result.suggested_commands or []) + list(plan_only_result.likely_tests or [])
                )
                plan_only_combined_files = _normalize(list(plan_only_result.suggested_files or []) + plan_only_answer_files)
                plan_only_combined_commands = _normalize(plan_only_plan_commands + plan_only_answer_commands)
                plan_only_plan_file_recall = _score_overlap(list(plan_only_result.suggested_files or []), case.expected_files)
                plan_only_plan_command_recall = _score_overlap(plan_only_plan_commands, case.expected_commands)
                plan_only_combined_file_recall = _score_overlap(plan_only_combined_files, case.expected_files)
                plan_only_combined_command_recall = _score_overlap(plan_only_combined_commands, case.expected_commands)

                stage = "compile_loop"
                compile_result = compile_session.ask(case.prompt)
                compile_answer_files = _normalize(_extract_answer_files(compile_result.answer))
                compile_answer_commands = _normalize(_extract_answer_commands(compile_result.answer))
                compile_plan_commands = _normalize(
                    list(compile_result.suggested_commands or []) + list(compile_result.likely_tests or [])
                )
                compile_combined_files = _normalize(list(compile_result.suggested_files or []) + compile_answer_files)
                compile_combined_commands = _normalize(compile_plan_commands + compile_answer_commands)
                compile_plan_file_recall = _score_overlap(list(compile_result.suggested_files or []), case.expected_files)
                compile_plan_command_recall = _score_overlap(compile_plan_commands, case.expected_commands)
                compile_combined_file_recall = _score_overlap(compile_combined_files, case.expected_files)
                compile_combined_command_recall = _score_overlap(compile_combined_commands, case.expected_commands)

                validated_trade_path = dict(compile_result.validated_trade_path or {})
                compile_validated_files = _normalize(list(validated_trade_path.get("supporting_files") or []))
                compile_validated_commands = _normalize(list(validated_trade_path.get("supporting_commands") or []))
                compile_residual_constraints = _normalize(list(compile_result.residual_constraints or []))

                rows.append(
                    CompileLoopBenchmarkRow(
                        prompt=case.prompt,
                        expected_files=case.expected_files,
                        expected_commands=case.expected_commands,
                        raw_answer=raw_answer,
                        raw_files=raw_files,
                        raw_commands=raw_commands,
                        raw_file_recall=round(raw_file_recall, 4),
                        raw_command_recall=round(raw_command_recall, 4),
                        plan_only_answer=plan_only_result.answer,
                        plan_only_plan_files=list(plan_only_result.suggested_files or []),
                        plan_only_plan_commands=list(plan_only_result.suggested_commands or []),
                        plan_only_plan_tests=list(plan_only_result.likely_tests or []),
                        plan_only_answer_files=plan_only_answer_files,
                        plan_only_answer_commands=plan_only_answer_commands,
                        plan_only_combined_files=plan_only_combined_files,
                        plan_only_combined_commands=plan_only_combined_commands,
                        plan_only_plan_file_recall=round(plan_only_plan_file_recall, 4),
                        plan_only_plan_command_recall=round(plan_only_plan_command_recall, 4),
                        plan_only_combined_file_recall=round(plan_only_combined_file_recall, 4),
                        plan_only_combined_command_recall=round(plan_only_combined_command_recall, 4),
                        plan_only_prior_trace_ids=list(plan_only_result.prior_trace_ids or []),
                        compile_answer=compile_result.answer,
                        compile_plan_files=list(compile_result.suggested_files or []),
                        compile_plan_commands=list(compile_result.suggested_commands or []),
                        compile_plan_tests=list(compile_result.likely_tests or []),
                        compile_answer_files=compile_answer_files,
                        compile_answer_commands=compile_answer_commands,
                        compile_combined_files=compile_combined_files,
                        compile_combined_commands=compile_combined_commands,
                        compile_plan_file_recall=round(compile_plan_file_recall, 4),
                        compile_plan_command_recall=round(compile_plan_command_recall, 4),
                        compile_combined_file_recall=round(compile_combined_file_recall, 4),
                        compile_combined_command_recall=round(compile_combined_command_recall, 4),
                        compile_validated_files=compile_validated_files,
                        compile_validated_commands=compile_validated_commands,
                        compile_residual_constraints=compile_residual_constraints,
                        compile_prior_trace_ids=list(compile_result.prior_trace_ids or []),
                    )
                )
            except Exception as exc:
                failures.append(
                    {
                        "prompt": case.prompt,
                        "stage": stage,
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    }
                )
            finally:
                plan_only_session.close()
                compile_session.close()

    count = max(len(rows), 1)
    return {
        "generated_ts": int(time.time()),
        "repo_root": repo_root,
        "db_path": db_path,
        "model": model,
        "cases_path": cases_path,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failures),
        "avg_raw_file_recall": round(sum(row.raw_file_recall for row in rows) / count, 4),
        "avg_raw_command_recall": round(sum(row.raw_command_recall for row in rows) / count, 4),
        "avg_plan_only_plan_file_recall": round(sum(row.plan_only_plan_file_recall for row in rows) / count, 4),
        "avg_plan_only_plan_command_recall": round(sum(row.plan_only_plan_command_recall for row in rows) / count, 4),
        "avg_plan_only_combined_file_recall": round(sum(row.plan_only_combined_file_recall for row in rows) / count, 4),
        "avg_plan_only_combined_command_recall": round(sum(row.plan_only_combined_command_recall for row in rows) / count, 4),
        "avg_compile_plan_file_recall": round(sum(row.compile_plan_file_recall for row in rows) / count, 4),
        "avg_compile_plan_command_recall": round(sum(row.compile_plan_command_recall for row in rows) / count, 4),
        "avg_compile_combined_file_recall": round(sum(row.compile_combined_file_recall for row in rows) / count, 4),
        "avg_compile_combined_command_recall": round(sum(row.compile_combined_command_recall for row in rows) / count, 4),
        "avg_compile_validated_file_recall": round(
            sum(_score_overlap(row.compile_validated_files, row.expected_files) for row in rows) / count,
            4,
        ),
        "avg_compile_validated_command_recall": round(
            sum(_score_overlap(row.compile_validated_commands, row.expected_commands) for row in rows) / count,
            4,
        ),
        "rows": [row.__dict__ for row in rows],
        "failed_cases": failures,
    }


def render_compile_loop_benchmark_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Memla Compile Loop Benchmark",
        "",
        f"- Model: `{report['model']}`",
        f"- Repo: `{report['repo_root']}`",
        f"- Cases: `{report['cases']}`",
        f"- Requested cases: `{report.get('cases_requested', report['cases'])}`",
        f"- Failed cases: `{report.get('failed_case_count', 0)}`",
        "",
        "## Aggregate Result",
        "",
        f"- Raw file recall: `{report['avg_raw_file_recall']}`",
        f"- Raw command recall: `{report['avg_raw_command_recall']}`",
        f"- Planning-only combined file recall: `{report['avg_plan_only_combined_file_recall']}`",
        f"- Planning-only combined command recall: `{report['avg_plan_only_combined_command_recall']}`",
        f"- Full compile-loop combined file recall: `{report['avg_compile_combined_file_recall']}`",
        f"- Full compile-loop combined command recall: `{report['avg_compile_combined_command_recall']}`",
        f"- Full compile validated-file recall: `{report['avg_compile_validated_file_recall']}`",
        f"- Full compile validated-command recall: `{report['avg_compile_validated_command_recall']}`",
        "",
    ]

    failed_cases = list(report.get("failed_cases") or [])
    if failed_cases:
        lines.extend(
            [
                "## Failed Cases",
                "",
            ]
        )
        for item in failed_cases[:8]:
            lines.append(
                f"- `{item.get('stage', 'unknown')}` failed for `{_shorten(str(item.get('prompt') or ''), 120)}`: {_shorten(str(item.get('error') or ''), 180)}"
            )
        lines.append("")

    for index, row in enumerate(report.get("rows") or [], start=1):
        lines.extend(
            [
                f"## Case {index}",
                "",
                f"**Prompt**: {row['prompt']}",
                "",
                f"- Expected files: `{', '.join(row['expected_files'])}`",
                f"- Expected commands: `{', '.join(row['expected_commands'])}`",
                f"- Raw file recall: `{row['raw_file_recall']}`",
                f"- Raw command recall: `{row['raw_command_recall']}`",
                f"- Planning-only combined file recall: `{row['plan_only_combined_file_recall']}`",
                f"- Planning-only combined command recall: `{row['plan_only_combined_command_recall']}`",
                f"- Full compile-loop combined file recall: `{row['compile_combined_file_recall']}`",
                f"- Full compile-loop combined command recall: `{row['compile_combined_command_recall']}`",
                "",
                "**Planning-only**",
                "",
                f"- Plan files: `{', '.join(row['plan_only_plan_files'])}`",
                f"- Plan commands: `{', '.join(row['plan_only_plan_commands'])}`",
                f"- Plan tests: `{', '.join(row['plan_only_plan_tests'])}`",
                f"- Combined files: `{', '.join(row['plan_only_combined_files'])}`",
                f"- Combined commands: `{', '.join(row['plan_only_combined_commands'])}`",
                f"- Answer excerpt: {_shorten(row['plan_only_answer'])}",
                "",
                "**Full compile/backtest**",
                "",
                f"- Plan files: `{', '.join(row['compile_plan_files'])}`",
                f"- Plan commands: `{', '.join(row['compile_plan_commands'])}`",
                f"- Plan tests: `{', '.join(row['compile_plan_tests'])}`",
                f"- Validated files: `{', '.join(row['compile_validated_files'])}`",
                f"- Validated commands: `{', '.join(row['compile_validated_commands'])}`",
                f"- Residual constraints: `{', '.join(row['compile_residual_constraints'])}`",
                f"- Combined files: `{', '.join(row['compile_combined_files'])}`",
                f"- Combined commands: `{', '.join(row['compile_combined_commands'])}`",
                f"- Answer excerpt: {_shorten(row['compile_answer'])}",
                "",
            ]
        )

    lines.extend(
        [
            "## Run It",
            "",
            "```powershell",
            "cd \"C:\\Users\\samat\\Project Memory\\Project-Memory\"",
            "py -3 -m memory_system.distillation.compile_loop_benchmark "
            f"--db \"{report['db_path']}\" "
            f"--repo_root \"{report['repo_root']}\" "
            "--user_id default "
            f"--model {report['model']} "
            f"--cases \"{report['cases_path']}\" "
            "--out_dir .\\distill\\compile_loop_benchmark_demo",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark raw vs planning-only vs full compile-loop Memla behavior.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", default="./distill/coding_holdout_cases.jsonl")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--out_dir", default="./distill/compile_loop_benchmark")
    args = parser.parse_args(argv)

    report = run_compile_loop_benchmark(
        db_path=args.db,
        repo_root=args.repo_root,
        user_id=args.user_id,
        cases_path=args.cases,
        model=args.model,
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "compile_loop_benchmark_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (out_dir / "compile_loop_benchmark_report.md").write_text(
        render_compile_loop_benchmark_markdown(report),
        encoding="utf-8",
    )
    print(f"[compile_loop_benchmark] wrote benchmark artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
