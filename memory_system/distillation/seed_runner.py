from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from .coding_proxy import CodingSession
from .constraint_graph import infer_file_roles, infer_repo_family


_STRUCTURAL_BOOTSTRAP_FAMILIES = {
    "python_api",
    "python_cli",
    "ts_backend_security",
    "ts_cli_tooling",
    "backend_security",
    "cli_tooling",
}


@dataclass(frozen=True)
class SeedCase:
    prompt: str
    expected_files: list[str]
    expected_commands: list[str]
    test_command: str = ""
    accept_strategy: str = ""
    min_file_recall: float = 0.0
    attach_expected_commands: bool = False


@dataclass(frozen=True)
class SeedResult:
    prompt: str
    trace_id: int
    prior_trace_ids: list[int]
    suggested_files: list[str]
    suggested_commands: list[str]
    answer_files: list[str]
    answer_commands: list[str]
    likely_tests: list[str]
    patch_steps: list[str]
    file_recall: float
    role_recall: float
    command_recall: float
    accepted: bool
    answer_excerpt: str


def _normalize(values: list[str]) -> list[str]:
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


def _score_role_overlap(predicted: list[str], expected: list[str]) -> float:
    if not expected:
        return 1.0
    predicted_roles: set[str] = set()
    expected_roles: set[str] = set()
    for value in predicted:
        predicted_roles.update(infer_file_roles(value))
    for value in expected:
        expected_roles.update(infer_file_roles(value))
    if not expected_roles:
        return 0.0
    return len(predicted_roles & expected_roles) / max(len(expected_roles), 1)


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
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


def _extract_answer_files(text: str) -> list[str]:
    matches = re.findall(
        r"(?:`|^|\s)([A-Za-z0-9_./-]+\.(?:py|js|jsx|ts|tsx|css|html|json|toml|md|txt))(?:`|$|\s|,|:)",
        text or "",
        re.IGNORECASE,
    )
    extra_matches = re.findall(
        r"(?:`|^|\s)((?:[A-Za-z0-9_./-]+/)?(?:Makefile|requirements\.txt|setup\.py|pyproject\.toml))(?:`|$|\s|,|:)",
        text or "",
        re.IGNORECASE,
    )
    return _unique(matches + extra_matches)


def _extract_answer_commands(text: str) -> list[str]:
    out: list[str] = []
    fenced = re.findall(r"```(?:bash|sh|shell)?\n(.*?)```", text or "", re.DOTALL | re.IGNORECASE)
    for block in fenced:
        for line in block.splitlines():
            clean = " ".join(line.strip().split())
            if clean and any(
                token in clean.lower()
                for token in (
                    "pytest",
                    "ruff",
                    "py -3",
                    "python -m",
                    "pip install",
                    "find .",
                    "ls -la",
                    "npm run",
                    "npm test",
                    "npm install",
                    "npx ",
                )
            ):
                out.append(clean)
    for inline in re.findall(r"`([^`]+)`", text or ""):
        clean = " ".join(inline.strip().split())
        if "\n" in inline:
            continue
        if clean.lower().startswith("bash "):
            clean = clean[5:].strip()
        if clean and any(
            token in clean.lower()
            for token in (
                "pytest",
                "ruff",
                "py -3",
                "python -m",
                "pip install",
                "find .",
                "ls -la",
                "npm run",
                "npm test",
                "npm install",
                "npx ",
            )
        ):
            out.append(clean)
    return _unique(out)


def load_seed_cases(path: str) -> list[SeedCase]:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    cases: list[SeedCase] = []
    for line in lines:
        clean = line.strip()
        if not clean:
            continue
        row = json.loads(clean)
        cases.append(
            SeedCase(
                prompt=str(row.get("prompt") or ""),
                expected_files=_normalize(list(row.get("expected_files") or [])),
                expected_commands=_normalize(list(row.get("expected_commands") or [])),
                test_command=str(row.get("test_command") or "").strip(),
                accept_strategy=str(row.get("accept_strategy") or "").strip(),
                min_file_recall=float(row.get("min_file_recall") or 0.0),
                attach_expected_commands=bool(row.get("attach_expected_commands") or False),
            )
        )
    return cases


def _evaluate_seed_acceptance(
    *,
    case: SeedCase,
    file_recall: float,
    role_recall: float,
    command_recall: float,
    repo_family: str,
    accept_threshold: float,
) -> tuple[bool, str]:
    strategy = case.accept_strategy.strip().lower()
    if strategy == "git_history_file_grounded":
        min_file = max(float(case.min_file_recall), 0.0)
        if float(file_recall) >= min_file:
            return True, "exact_file_grounding"
        if repo_family in _STRUCTURAL_BOOTSTRAP_FAMILIES:
            staged_file_floor = min(min_file, 0.125) if min_file > 0 else 0.0
            if float(role_recall) >= 0.5 and (
                float(file_recall) >= staged_file_floor or float(command_recall) >= 0.5
            ):
                return True, "structural_bootstrap"
        return False, "rejected"
    blended = (float(file_recall) + float(command_recall)) / 2.0
    return blended >= float(accept_threshold), "blended_threshold"


def run_seed_cases(
    *,
    db_path: str,
    repo_root: str,
    user_id: str,
    model: str,
    cases: list[SeedCase],
    top_k: int = 12,
    temperature: float = 0.1,
    num_ctx: Optional[int] = None,
    accept_threshold: float = 0.6,
) -> dict[str, Any]:
    repo_family = infer_repo_family(repo_root)
    session = CodingSession(
        model=model,
        db_path=db_path,
        user_id=user_id,
        repo_root=repo_root,
        top_k=top_k,
        temperature=temperature,
        num_ctx=num_ctx,
    )
    try:
        rows: list[SeedResult] = []
        accepted_count = 0
        for case in cases:
            result = session.ask(case.prompt, test_command=case.test_command or None)
            answer_files = _extract_answer_files(result.answer)
            answer_commands = _extract_answer_commands(result.answer)
            combined_files = _unique(list(result.suggested_files or []) + answer_files)
            predicted_commands = list(result.suggested_commands or [])
            combined_commands = _unique(list(predicted_commands))
            for test_cmd in result.likely_tests or []:
                combined_commands.append(test_cmd)
            combined_commands = _unique(combined_commands + answer_commands)
            attached_expected_commands = _normalize(list(case.expected_commands)) if case.attach_expected_commands else []
            session.coding_log.update_trace_artifacts(
                trace_id=result.trace_id,
                meta={
                    # Keep the raw extraction for analysis, but store the full
                    # workflow hints Memla+teacher produced so accepted traces
                    # become reusable priors even when the final prose is vague.
                    "teacher_extracted_files": answer_files,
                    "teacher_extracted_commands": answer_commands,
                    "teacher_answer_files": combined_files,
                    "teacher_answer_commands": combined_commands,
                },
            )
            file_recall = _score_overlap(combined_files, case.expected_files)
            role_recall = _score_role_overlap(combined_files, case.expected_files)
            command_recall = _score_overlap(combined_commands, case.expected_commands)
            accepted, accept_mode = _evaluate_seed_acceptance(
                case=case,
                file_recall=file_recall,
                role_recall=role_recall,
                command_recall=command_recall,
                repo_family=repo_family,
                accept_threshold=accept_threshold,
            )
            session.coding_log.update_trace_artifacts(
                trace_id=result.trace_id,
                meta={
                    "seed_expected_files": list(case.expected_files if accepted else []),
                    "seed_expected_commands": list(attached_expected_commands if accepted and case.attach_expected_commands else (case.expected_commands if accepted else [])),
                    "seed_accept_strategy": case.accept_strategy,
                    "seed_accept_mode": accept_mode,
                    "seed_min_file_recall": float(case.min_file_recall),
                    "seed_role_recall": float(role_recall),
                    "seed_repo_family": repo_family,
                },
            )
            note = (
                f"auto-seed file_recall={file_recall:.2f} "
                f"role_recall={role_recall:.2f} "
                f"command_recall={command_recall:.2f} threshold={accept_threshold:.2f} "
                f"strategy={case.accept_strategy or 'default'} mode={accept_mode}"
            )
            session.mark_feedback(is_positive=accepted, note=note)
            if accepted:
                accepted_count += 1
            rows.append(
                SeedResult(
                    prompt=case.prompt,
                    trace_id=result.trace_id,
                    prior_trace_ids=list(result.prior_trace_ids or []),
                    suggested_files=combined_files,
                    suggested_commands=combined_commands,
                    answer_files=answer_files,
                    answer_commands=answer_commands,
                    likely_tests=list(result.likely_tests or []),
                    patch_steps=list(result.patch_steps or []),
                    file_recall=round(file_recall, 4),
                    role_recall=round(role_recall, 4),
                    command_recall=round(command_recall, 4),
                    accepted=accepted,
                    answer_excerpt=" ".join((result.answer or "").split())[:280],
                )
            )
    finally:
        session.close()

    count = len(rows)
    return {
        "cases": count,
        "accepted": accepted_count,
        "accept_rate": round(accepted_count / max(count, 1), 4),
        "avg_file_recall": round(sum(row.file_recall for row in rows) / max(count, 1), 4),
        "avg_role_recall": round(sum(row.role_recall for row in rows) / max(count, 1), 4),
        "avg_command_recall": round(sum(row.command_recall for row in rows) / max(count, 1), 4),
        "rows": [asdict(row) for row in rows],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Seed Memla coding traces using teacher-model runs over repo-local cases.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--repo_root", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--model", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--out", default="")
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--num_ctx", type=int, default=None)
    parser.add_argument("--accept_threshold", type=float, default=0.6)
    args = parser.parse_args(argv)

    cases = load_seed_cases(args.cases)
    report = run_seed_cases(
        db_path=args.db,
        repo_root=args.repo_root,
        user_id=args.user_id,
        model=args.model,
        cases=cases,
        top_k=args.top_k,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        accept_threshold=args.accept_threshold,
    )
    blob = json.dumps(report, ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(blob, encoding="utf-8")
        print(f"[seed_runner] wrote report to {out_path}")
    else:
        print(blob)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
