from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .coding_proxy import CodingSession


@dataclass(frozen=True)
class PlanEvalCase:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]


def _normalize_list(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        clean = " ".join(str(value or "").strip().split())
        if clean:
            out.append(clean)
    return out


def _score_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_set = {value.lower() for value in predicted}
    expected_set = {value.lower() for value in expected}
    return len(predicted_set & expected_set) / max(len(expected_set), 1)


def load_eval_cases(path: str) -> list[PlanEvalCase]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cases: list[PlanEvalCase] = []
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        cases.append(
            PlanEvalCase(
                prompt=str(row.get("prompt") or ""),
                expected_files=_normalize_list(list(row.get("expected_files") or [])),
                expected_commands=_normalize_list(list(row.get("expected_commands") or [])),
            )
        )
    return cases


def evaluate_workflow_plans(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    cases: list[PlanEvalCase],
    model: str = "qwen3.5:4b",
    top_k: int = 12,
) -> dict[str, Any]:
    session = CodingSession(
        model=model,
        db_path=db_path,
        user_id=user_id,
        repo_root=repo_root,
        top_k=top_k,
    )
    try:
        rows: list[dict[str, Any]] = []
        file_scores: list[float] = []
        command_scores: list[float] = []
        for case in cases:
            plan = session.build_plan(case.prompt)
            file_score = _score_overlap(plan.likely_files, case.expected_files)
            command_score = _score_overlap(plan.likely_commands, case.expected_commands)
            file_scores.append(file_score)
            command_scores.append(command_score)
            rows.append(
                {
                    "prompt": case.prompt,
                    "predicted_files": plan.likely_files,
                    "predicted_commands": plan.likely_commands,
                    "predicted_tests": plan.likely_tests,
                    "patch_steps": plan.patch_steps,
                    "expected_files": case.expected_files,
                    "expected_commands": case.expected_commands,
                    "file_recall": round(file_score, 4),
                    "command_recall": round(command_score, 4),
                }
            )
    finally:
        session.close()

    count = len(rows)
    return {
        "cases": count,
        "avg_file_recall": round(sum(file_scores) / max(count, 1), 4),
        "avg_command_recall": round(sum(command_scores) / max(count, 1), 4),
        "rows": rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate Memla workflow plans against expected files/commands.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--cases", required=True, help="Path to JSONL with prompt, expected_files, expected_commands.")
    parser.add_argument("--model", default="qwen3.5:4b")
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)

    cases = load_eval_cases(args.cases)
    report = evaluate_workflow_plans(
        db_path=args.db,
        repo_root=args.repo_root,
        user_id=args.user_id,
        cases=cases,
        model=args.model,
        top_k=args.top_k,
    )
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(blob, encoding="utf-8")
        print(f"[plan_eval] wrote report to {out_path}")
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
