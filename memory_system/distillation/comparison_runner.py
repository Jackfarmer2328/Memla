from __future__ import annotations

import argparse
import json
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
class ComparisonRow:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    raw_answer: str
    raw_files: list[str]
    raw_commands: list[str]
    raw_file_recall: float
    raw_command_recall: float
    memla_answer: str
    memla_plan_files: list[str]
    memla_plan_commands: list[str]
    memla_plan_tests: list[str]
    memla_patch_steps: list[str]
    memla_constraint_tags: list[str]
    memla_transmutations: list[str]
    memla_role_targets: list[str]
    memla_answer_files: list[str]
    memla_answer_commands: list[str]
    memla_combined_files: list[str]
    memla_combined_commands: list[str]
    memla_plan_file_recall: float
    memla_plan_command_recall: float
    memla_combined_file_recall: float
    memla_combined_command_recall: float
    prior_trace_ids: list[int]


def run_head_to_head(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    teacher_model: str,
    temperature: float = 0.1,
    top_k: int = 12,
    num_ctx: int | None = None,
) -> dict[str, Any]:
    client = UniversalLLMClient.from_env()
    cases = load_eval_cases(cases_path)
    session = CodingSession(
        model=teacher_model,
        db_path=db_path,
        user_id=user_id,
        repo_root=repo_root,
        temperature=temperature,
        top_k=top_k,
        num_ctx=num_ctx,
    )
    try:
        rows: list[ComparisonRow] = []
        for case in cases:
            raw_answer = client.chat(
                model=teacher_model,
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

            memla_result = session.ask(case.prompt)
            memla_answer_files = _normalize(_extract_answer_files(memla_result.answer))
            memla_answer_commands = _normalize(_extract_answer_commands(memla_result.answer))
            memla_plan_commands = _normalize(list(memla_result.suggested_commands or []) + list(memla_result.likely_tests or []))
            memla_combined_files = _normalize(list(memla_result.suggested_files or []) + memla_answer_files)
            memla_combined_commands = _normalize(memla_plan_commands + memla_answer_commands)
            memla_plan_file_recall = _score_overlap(list(memla_result.suggested_files or []), case.expected_files)
            memla_plan_command_recall = _score_overlap(memla_plan_commands, case.expected_commands)
            memla_combined_file_recall = _score_overlap(memla_combined_files, case.expected_files)
            memla_combined_command_recall = _score_overlap(memla_combined_commands, case.expected_commands)

            rows.append(
                ComparisonRow(
                    prompt=case.prompt,
                    expected_files=case.expected_files,
                    expected_commands=case.expected_commands,
                    raw_answer=raw_answer,
                    raw_files=raw_files,
                    raw_commands=raw_commands,
                    raw_file_recall=round(raw_file_recall, 4),
                    raw_command_recall=round(raw_command_recall, 4),
                    memla_answer=memla_result.answer,
                    memla_plan_files=list(memla_result.suggested_files or []),
                    memla_plan_commands=list(memla_result.suggested_commands or []),
                    memla_plan_tests=list(memla_result.likely_tests or []),
                    memla_patch_steps=list(memla_result.patch_steps or []),
                    memla_constraint_tags=list(getattr(memla_result, "constraint_tags", None) or []),
                    memla_transmutations=list(getattr(memla_result, "transmutations", None) or []),
                    memla_role_targets=list(getattr(memla_result, "role_targets", None) or []),
                    memla_answer_files=memla_answer_files,
                    memla_answer_commands=memla_answer_commands,
                    memla_combined_files=memla_combined_files,
                    memla_combined_commands=memla_combined_commands,
                    memla_plan_file_recall=round(memla_plan_file_recall, 4),
                    memla_plan_command_recall=round(memla_plan_command_recall, 4),
                    memla_combined_file_recall=round(memla_combined_file_recall, 4),
                    memla_combined_command_recall=round(memla_combined_command_recall, 4),
                    prior_trace_ids=list(memla_result.prior_trace_ids or []),
                )
            )
    finally:
        session.close()

    count = max(len(rows), 1)
    return {
        "generated_ts": int(time.time()),
        "repo_root": repo_root,
        "db_path": db_path,
        "teacher_model": teacher_model,
        "cases_path": cases_path,
        "cases": len(rows),
        "avg_raw_file_recall": round(sum(row.raw_file_recall for row in rows) / count, 4),
        "avg_raw_command_recall": round(sum(row.raw_command_recall for row in rows) / count, 4),
        "avg_memla_plan_file_recall": round(sum(row.memla_plan_file_recall for row in rows) / count, 4),
        "avg_memla_plan_command_recall": round(sum(row.memla_plan_command_recall for row in rows) / count, 4),
        "avg_memla_combined_file_recall": round(sum(row.memla_combined_file_recall for row in rows) / count, 4),
        "avg_memla_combined_command_recall": round(sum(row.memla_combined_command_recall for row in rows) / count, 4),
        "rows": [row.__dict__ for row in rows],
    }


def render_head_to_head_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Memla Head-to-Head Coding Demo",
        "",
        f"- Teacher model: `{report['teacher_model']}`",
        f"- Repo: `{report['repo_root']}`",
        f"- Cases: `{report['cases']}`",
        "",
        "## Aggregate Result",
        "",
        f"- Raw teacher file recall: `{report['avg_raw_file_recall']}`",
        f"- Raw teacher command recall: `{report['avg_raw_command_recall']}`",
        f"- Memla plan file recall: `{report['avg_memla_plan_file_recall']}`",
        f"- Memla plan command recall: `{report['avg_memla_plan_command_recall']}`",
        f"- Memla combined file recall: `{report['avg_memla_combined_file_recall']}`",
        f"- Memla combined command recall: `{report['avg_memla_combined_command_recall']}`",
        "",
    ]

    for index, row in enumerate(report.get("rows") or [], start=1):
        lines.extend(
            [
                f"## Case {index}",
                "",
                f"**Prompt**: {row['prompt']}",
                "",
                f"- Expected files: `{', '.join(row['expected_files'])}`",
                f"- Expected commands: `{', '.join(row['expected_commands'])}`",
                f"- Raw teacher file recall: `{row['raw_file_recall']}`",
                f"- Raw teacher command recall: `{row['raw_command_recall']}`",
                f"- Memla plan file recall: `{row['memla_plan_file_recall']}`",
                f"- Memla plan command recall: `{row['memla_plan_command_recall']}`",
                f"- Memla combined file recall: `{row['memla_combined_file_recall']}`",
                f"- Memla combined command recall: `{row['memla_combined_command_recall']}`",
                "",
                "**Raw teacher**",
                "",
                f"- Files: `{', '.join(row['raw_files'])}`",
                f"- Commands: `{', '.join(row['raw_commands'])}`",
                f"- Answer excerpt: {_shorten(row['raw_answer'])}",
                "",
                "**Memla in front**",
                "",
                f"- Prior trace ids: `{', '.join(str(x) for x in row['prior_trace_ids'])}`",
                f"- Plan files: `{', '.join(row['memla_plan_files'])}`",
                f"- Plan commands: `{', '.join(row['memla_plan_commands'])}`",
                f"- Plan tests: `{', '.join(row['memla_plan_tests'])}`",
                f"- Role targets: `{', '.join(row['memla_role_targets'])}`",
                f"- Constraint tags: `{', '.join(row['memla_constraint_tags'])}`",
                f"- Combined files: `{', '.join(row['memla_combined_files'])}`",
                f"- Combined commands: `{', '.join(row['memla_combined_commands'])}`",
                f"- Answer excerpt: {_shorten(row['memla_answer'])}",
            ]
        )
        transmutations = row.get("memla_transmutations") or []
        if transmutations:
            lines.append("- Transmutations:")
            for transmutation in transmutations[:4]:
                lines.append(f"  - {transmutation}")
        patch_steps = row.get("memla_patch_steps") or []
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
            ". .\\.anthropic_env.ps1",
            "py -3 -m memory_system.distillation.comparison_runner "
            f"--db \"{report['db_path']}\" "
            f"--repo_root \"{report['repo_root']}\" "
            "--user_id default "
            f"--teacher_model {report['teacher_model']} "
            f"--cases \"{report['cases_path']}\" "
            "--out_dir .\\distill\\head_to_head_demo",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a raw-teacher vs Memla-assisted coding comparison.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--teacher_model", required=True)
    parser.add_argument("--cases", default="./distill/coding_holdout_cases.jsonl")
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--out_dir", default="./distill/head_to_head_demo")
    args = parser.parse_args(argv)

    report = run_head_to_head(
        db_path=args.db,
        repo_root=args.repo_root,
        user_id=args.user_id,
        cases_path=args.cases,
        teacher_model=args.teacher_model,
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "comparison_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "comparison_report.md").write_text(render_head_to_head_markdown(report), encoding="utf-8")
    print(f"[comparison_runner] wrote comparison artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
