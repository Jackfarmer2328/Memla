from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coding_proxy import CodingSession
from .eval_harness import PlanEvalCase, load_eval_cases


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {value.lower() for value in predicted}
    expected_set = {value.lower() for value in expected}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


@dataclass(frozen=True)
class TransferEvalRow:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    baseline_files: list[str]
    baseline_commands: list[str]
    baseline_transmutations: list[str]
    baseline_roles: list[str]
    baseline_file_recall: float
    baseline_command_recall: float
    memla_files: list[str]
    memla_commands: list[str]
    memla_transmutations: list[str]
    memla_roles: list[str]
    memla_source_trace_ids: list[int]
    memla_file_recall: float
    memla_command_recall: float
    delta_file_recall: float
    delta_command_recall: float


def _plan_snapshot(session: CodingSession, case: PlanEvalCase) -> dict[str, Any]:
    plan = session.build_plan(case.prompt)
    return {
        "files": list(plan.likely_files),
        "commands": list(plan.likely_commands),
        "transmutations": list(plan.transmutations),
        "roles": list(plan.role_targets),
        "source_trace_ids": list(plan.source_trace_ids),
        "file_recall": round(_score_overlap(plan.likely_files, case.expected_files), 4),
        "command_recall": round(_score_overlap(plan.likely_commands, case.expected_commands), 4),
    }


def run_transfer_eval(
    *,
    db_path: str,
    baseline_db_path: str,
    repo_root: str,
    user_id: str,
    cases_path: str,
    model: str = "qwen3.5:4b",
    top_k: int = 12,
) -> dict[str, Any]:
    cases = load_eval_cases(cases_path)
    baseline_session = CodingSession(
        model=model,
        db_path=baseline_db_path,
        user_id=user_id,
        repo_root=repo_root,
        top_k=top_k,
    )
    memla_session = CodingSession(
        model=model,
        db_path=db_path,
        user_id=user_id,
        repo_root=repo_root,
        top_k=top_k,
    )
    try:
        rows: list[TransferEvalRow] = []
        for case in cases:
            baseline = _plan_snapshot(baseline_session, case)
            memla = _plan_snapshot(memla_session, case)
            rows.append(
                TransferEvalRow(
                    prompt=case.prompt,
                    expected_files=list(case.expected_files),
                    expected_commands=list(case.expected_commands),
                    baseline_files=baseline["files"],
                    baseline_commands=baseline["commands"],
                    baseline_transmutations=baseline["transmutations"],
                    baseline_roles=baseline["roles"],
                    baseline_file_recall=float(baseline["file_recall"]),
                    baseline_command_recall=float(baseline["command_recall"]),
                    memla_files=memla["files"],
                    memla_commands=memla["commands"],
                    memla_transmutations=memla["transmutations"],
                    memla_roles=memla["roles"],
                    memla_source_trace_ids=memla["source_trace_ids"],
                    memla_file_recall=float(memla["file_recall"]),
                    memla_command_recall=float(memla["command_recall"]),
                    delta_file_recall=round(float(memla["file_recall"]) - float(baseline["file_recall"]), 4),
                    delta_command_recall=round(float(memla["command_recall"]) - float(baseline["command_recall"]), 4),
                )
            )
    finally:
        baseline_session.close()
        memla_session.close()

    count = max(len(rows), 1)
    return {
        "repo_root": repo_root,
        "cases_path": cases_path,
        "cases": len(rows),
        "avg_baseline_file_recall": round(sum(row.baseline_file_recall for row in rows) / count, 4),
        "avg_baseline_command_recall": round(sum(row.baseline_command_recall for row in rows) / count, 4),
        "avg_memla_file_recall": round(sum(row.memla_file_recall for row in rows) / count, 4),
        "avg_memla_command_recall": round(sum(row.memla_command_recall for row in rows) / count, 4),
        "avg_delta_file_recall": round(sum(row.delta_file_recall for row in rows) / count, 4),
        "avg_delta_command_recall": round(sum(row.delta_command_recall for row in rows) / count, 4),
        "positive_file_transfer_cases": sum(1 for row in rows if row.delta_file_recall > 0),
        "positive_command_transfer_cases": sum(1 for row in rows if row.delta_command_recall > 0),
        "rows": [row.__dict__ for row in rows],
    }


def render_transfer_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Memla Transfer Eval",
        "",
        f"- Repo: `{report['repo_root']}`",
        f"- Cases: `{report['cases']}`",
        "",
        "## Aggregate",
        "",
        f"- Empty-memory file recall: `{report['avg_baseline_file_recall']}`",
        f"- Empty-memory command recall: `{report['avg_baseline_command_recall']}`",
        f"- Memla transfer file recall: `{report['avg_memla_file_recall']}`",
        f"- Memla transfer command recall: `{report['avg_memla_command_recall']}`",
        f"- Avg file recall delta: `{report['avg_delta_file_recall']}`",
        f"- Avg command recall delta: `{report['avg_delta_command_recall']}`",
        f"- Positive file-transfer cases: `{report['positive_file_transfer_cases']}`",
        f"- Positive command-transfer cases: `{report['positive_command_transfer_cases']}`",
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
                f"- Empty-memory files: `{', '.join(row['baseline_files'])}`",
                f"- Empty-memory commands: `{', '.join(row['baseline_commands'])}`",
                f"- Empty-memory transmutations: `{', '.join(row['baseline_transmutations'])}`",
                f"- Empty-memory file recall: `{row['baseline_file_recall']}`",
                f"- Empty-memory command recall: `{row['baseline_command_recall']}`",
                f"- Memla files: `{', '.join(row['memla_files'])}`",
                f"- Memla commands: `{', '.join(row['memla_commands'])}`",
                f"- Memla roles: `{', '.join(row['memla_roles'])}`",
                f"- Memla transmutations: `{', '.join(row['memla_transmutations'])}`",
                f"- Memla source trace ids: `{', '.join(str(x) for x in row['memla_source_trace_ids'])}`",
                f"- Memla file recall: `{row['memla_file_recall']}`",
                f"- Memla command recall: `{row['memla_command_recall']}`",
                f"- File recall delta: `{row['delta_file_recall']}`",
                f"- Command recall delta: `{row['delta_command_recall']}`",
                "",
            ]
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare empty-memory planning vs Memla transfer planning.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--baseline_db", required=True)
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--cases", required=True)
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--out_dir", default="./distill/transfer_eval")
    args = parser.parse_args(argv)

    report = run_transfer_eval(
        db_path=args.db,
        baseline_db_path=args.baseline_db,
        repo_root=args.repo_root,
        user_id=args.user_id,
        cases_path=args.cases,
        model=args.model,
        top_k=args.top_k,
    )

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "transfer_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / "transfer_report.md").write_text(render_transfer_markdown(report), encoding="utf-8")
    print(f"[transfer_eval] wrote transfer artifacts to {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
