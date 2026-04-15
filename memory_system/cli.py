from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request

from .distillation.coding_proxy import CodingSession
from .distillation.compile_loop_benchmark import (
    render_compile_loop_benchmark_markdown,
    run_compile_loop_benchmark,
)
from .distillation.coding_c2a_benchmark import (
    render_coding_c2a_markdown,
    run_coding_c2a_benchmark,
)
from .distillation.finance_pretrade_benchmark import (
    render_finance_pretrade_markdown,
    run_finance_pretrade_benchmark,
)
from .distillation.healthcare_denial_benchmark import (
    render_healthcare_denial_markdown,
    run_healthcare_denial_benchmark,
)
from .distillation.policy_authz_policy_bank import (
    distill_policy_authz_policy_bank,
    render_policy_authz_policy_bank_markdown,
)
from .distillation.policy_trace_bank import (
    extract_policy_trace_bank,
    render_policy_trace_bank_markdown,
)
from .distillation.finance_policy_bank import (
    distill_finance_policy_bank,
    render_finance_policy_bank_markdown,
)
from .distillation.web_policy_bank import (
    distill_web_policy_bank,
    render_web_policy_bank_markdown,
)
from .distillation.finance_trace_bank import (
    extract_finance_trace_bank,
    render_finance_trace_bank_markdown,
)
from .distillation.c2a_trace_bank import (
    extract_c2a_trace_bank,
    render_c2a_trace_bank_markdown,
)
from .distillation.c2a_policy_bank import (
    distill_c2a_policy_bank,
    render_c2a_policy_bank_markdown,
)
from .distillation.research_loop_capture import convert_research_loop_events_to_cases
from .distillation.research_loop_benchmark import (
    render_research_loop_markdown,
    run_research_loop_live_shadow_benchmark,
    run_research_loop_replay_benchmark,
)
from .distillation.math_c2a_benchmark import (
    render_math_c2a_teacher_student_markdown,
    run_math_c2a_teacher_student_benchmark,
)
from .distillation.patch_execution_benchmark import (
    render_patch_execution_markdown,
    run_patch_execution_benchmark,
)
from .distillation.policy_authz_benchmark import (
    render_policy_authz_markdown,
    run_policy_authz_benchmark,
)
from .distillation.thesis_pack_builder import build_thesis_pack
from .distillation.workflow_planner import render_workflow_plan_block
from .browser_ontology_benchmark import (
    render_browser_benchmark_markdown,
    run_browser_benchmark,
    run_language_learning_benchmark,
    run_language_rule_benchmark,
    run_memory_ontology_benchmark,
)
from .natural_terminal import (
    build_terminal_step_report,
    build_llm_client as build_terminal_llm_client,
    build_raw_terminal_plan,
    build_terminal_plan,
    execute_terminal_step,
    execute_terminal_plan,
    load_browser_session_state,
    render_terminal_benchmark_markdown,
    render_terminal_execution_text,
    render_terminal_plan_text,
    render_terminal_scout_text,
    render_terminal_step_execution_text,
    render_terminal_step_report_text,
    render_web_answer_benchmark_markdown,
    render_web_overnight_loop_markdown,
    render_web_teacher_loop_markdown,
    run_terminal_benchmark,
    run_terminal_scout,
    run_web_answer_benchmark,
    run_web_overnight_loop,
    run_web_teacher_loop,
    terminal_execution_to_dict,
    terminal_model_default,
    terminal_plan_to_dict,
    terminal_scout_to_dict,
    terminal_step_execution_to_dict,
    terminal_step_report_to_dict,
)
from .terminal_workbench import serve_terminal_workbench


def _coding_model_default() -> str:
    return os.environ.get("OLLAMA_MODEL", "qwen3.5:9b")


def _terminal_model_default() -> str:
    return terminal_model_default()


def _terminal_cases_default() -> str:
    return "cases/terminal_eval_cases.jsonl"


def _serve_memla_api(**kwargs: Any) -> None:
    from .server_api import serve_memla_api

    serve_memla_api(**kwargs)


def _browser_cases_default() -> str:
    return "cases/browser_eval_cases.jsonl"


def _browser_v2_cases_default() -> str:
    return "cases/browser_eval_cases_v2.jsonl"


def _browser_v3_cases_default() -> str:
    return "cases/browser_eval_cases_v3.jsonl"


def _browser_v4_cases_default() -> str:
    return "cases/browser_eval_cases_v4.jsonl"


def _browser_v5_cases_default() -> str:
    return "cases/browser_eval_cases_v5.jsonl"


def _browser_v6_cases_default() -> str:
    return "cases/browser_eval_cases_v6.jsonl"


def _browser_v7_cases_default() -> str:
    return "cases/browser_eval_cases_v7.jsonl"


def _browser_v8_cases_default() -> str:
    return "cases/browser_eval_cases_v8.jsonl"


def _language_v1_cases_default() -> str:
    return "cases/language_eval_cases_v1.jsonl"


def _language_v2_cases_default() -> str:
    return "cases/language_eval_cases_v2.jsonl"


def _language_v3_cases_default() -> str:
    return "cases/language_eval_cases_v3.jsonl"


def _language_v4_cases_default() -> str:
    return "cases/language_eval_cases_v4.jsonl"


def _memory_v1_cases_default() -> str:
    return "cases/memory_eval_cases_v1.jsonl"


def _web_v1_cases_default() -> str:
    return "cases/web_eval_cases_v1.jsonl"


def _user_id_default() -> str:
    return os.environ.get("USER_ID", "default")


def _timestamp_slug() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _json_default(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, default=_json_default))


def _resolve_repo_root(raw: str) -> Path:
    return Path(raw or ".").resolve()


def _resolve_db_path(raw: str, repo_root: Path) -> Path:
    if raw.strip():
        path = Path(raw)
        if not path.is_absolute():
            path = Path.cwd() / path
    else:
        path = repo_root / ".memla" / "memory.sqlite"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path.resolve()


def _default_report_dir(kind: str) -> Path:
    out_dir = Path.cwd() / "memla_reports" / f"{kind}_{_timestamp_slug()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _resolve_terminal_prompt(args: argparse.Namespace) -> str:
    direct = str(getattr(args, "prompt", "") or "").strip()
    if direct:
        return direct
    prompt_parts = [str(part).strip() for part in list(getattr(args, "prompt_text", []) or []) if str(part).strip()]
    if prompt_parts:
        return " ".join(prompt_parts).strip()
    raise SystemExit("terminal prompt is required: pass --prompt \"...\" or plain text after the subcommand")


def _resolve_shared_terminal_model(args: argparse.Namespace, lane_name: str) -> str:
    shared_model = str(getattr(args, "model", "") or "").strip()
    lane_value = str(getattr(args, lane_name, "") or "").strip()
    return lane_value or shared_model or _terminal_model_default()


def _format_terminal_duration(seconds: float) -> str:
    return f"{max(float(seconds), 0.0):.3f}s"


def _looks_like_terminal_scout_prompt(prompt: str) -> bool:
    normalized = " ".join(str(prompt or "").strip().lower().split())
    if not normalized:
        return False
    repo_hit = bool(re.search(r"\b(?:github|repo|repos|repository|repositories)\b", normalized))
    scout_hit = any(
        token in normalized
        for token in {"top ", "best repo", "align", "match", "fit", "bring back", "show me", "list ", "scout"}
    )
    return repo_hit and scout_hit


def _build_terminal_request_plan(args: argparse.Namespace, prompt: str, browser_state=None):
    if getattr(args, "without_memla", False):
        if getattr(args, "heuristic_only", False):
            raise SystemExit("--without-memla cannot be combined with --heuristic-only")
        client = build_terminal_llm_client(provider=args.provider or None, base_url=args.base_url or None)
        return build_raw_terminal_plan(
            prompt=prompt,
            model=args.model,
            client=client,
            temperature=args.temperature,
            browser_state=browser_state,
        )
    client = None if args.heuristic_only else build_terminal_llm_client(provider=args.provider or None, base_url=args.base_url or None)
    return build_terminal_plan(
        prompt=prompt,
        model=args.model,
        client=client,
        heuristic_only=args.heuristic_only,
        temperature=args.temperature,
        browser_state=browser_state,
    )


def _configure_terminal_scout_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--prompt", "-p", default="", help="Bounded autonomous scouting request.")
    parser.add_argument("prompt_text", nargs="*", help="Prompt words if you want to skip --prompt.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    parser.set_defaults(func=_handle_terminal_scout)


def _configure_memla_serve_parser(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", default="127.0.0.1", help="Host interface for the local Memla API server.")
    parser.add_argument("--port", type=int, default=8080, help="Port for the local Memla API server.")
    parser.add_argument("--state-path", default="", help="Optional explicit terminal browser state path.")
    parser.add_argument("--model", default=_terminal_model_default(), help="Default fallback local model for HTTP requests.")
    parser.add_argument("--provider", default="ollama", help="Default provider for model fallback requests.")
    parser.add_argument("--base-url", default="", help="Optional default base URL for model fallback requests.")
    parser.add_argument("--temperature", type=float, default=0.1, help="Default fallback model temperature.")
    parser.add_argument("--heuristic-only", action="store_true", help="Start the API in heuristic-only mode by default.")
    parser.set_defaults(func=_handle_memla_serve)


_PUBLIC_SITE_VERCEL_CONFIG = {
    "$schema": "https://openapi.vercel.sh/vercel.json",
    "cleanUrls": True,
    "trailingSlash": False,
    "builds": [
        {"src": "index.html", "use": "@vercel/static"},
        {"src": "og-card.svg", "use": "@vercel/static"},
        {"src": "90_second_demo.md", "use": "@vercel/static"},
        {"src": "one_sentence_pitch.txt", "use": "@vercel/static"},
        {"src": "strategic_memo.md", "use": "@vercel/static"},
        {"src": "frozen/**", "use": "@vercel/static"},
    ],
}


def _candidate_ollama_urls(preferred: str) -> list[str]:
    urls: list[str] = []
    for raw in (preferred, os.environ.get("OLLAMA_URL", ""), "http://127.0.0.1:11434", "http://127.0.0.1:11435"):
        clean = str(raw or "").strip().rstrip("/")
        if not clean or clean in urls:
            continue
        urls.append(clean)
    return urls


def _probe_ollama(url: str, *, timeout: float = 2.0) -> dict[str, Any]:
    target = f"{url.rstrip('/')}/api/tags"
    req = urllib_request.Request(target, headers={"Accept": "application/json"})
    with urllib_request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    models = payload.get("models") or []
    names = [str(model.get("name") or "").strip() for model in models if str(model.get("name") or "").strip()]
    return {
        "reachable": True,
        "url": url,
        "model_count": len(names),
        "models": names,
    }


def _sync_public_site(*, source_dir: Path, out_dir: Path) -> dict[str, Any]:
    source = source_dir.resolve()
    target = out_dir.resolve()
    files = [
        "index.html",
        "og-card.svg",
        "one_sentence_pitch.txt",
        "90_second_demo.md",
        "strategic_memo.md",
    ]
    copied: list[str] = []
    target.mkdir(parents=True, exist_ok=True)
    for name in files:
        src_file = source / name
        if not src_file.exists():
            continue
        dst_file = target / name
        shutil.copy2(src_file, dst_file)
        copied.append(name)
    frozen_src = source / "frozen"
    frozen_dst = target / "frozen"
    if frozen_dst.exists():
        shutil.rmtree(frozen_dst)
    if frozen_src.exists():
        shutil.copytree(frozen_src, frozen_dst)
        copied.append("frozen/")
    (target / "vercel.json").write_text(json.dumps(_PUBLIC_SITE_VERCEL_CONFIG, indent=2), encoding="utf-8")
    copied.append("vercel.json")
    return {
        "source_dir": str(source),
        "out_dir": str(target),
        "copied": copied,
        "site_ready": (target / "index.html").exists() and (target / "vercel.json").exists(),
    }


def _render_proxy_text(result: Any) -> str:
    lines = [str(result.answer or "").strip()]
    if result.suggested_files:
        lines.append("")
        lines.append(f"Likely files: {', '.join(result.suggested_files[:8])}")
    if result.suggested_commands:
        lines.append(f"Likely commands: {', '.join(result.suggested_commands[:6])}")
    if result.likely_tests:
        lines.append(f"Likely tests: {', '.join(result.likely_tests[:6])}")
    if result.predicted_constraints:
        lines.append(f"Predicted constraints: {', '.join(result.predicted_constraints[:6])}")
    if result.transmutations:
        lines.append(f"Transmutations: {', '.join(result.transmutations[:6])}")
    if result.residual_constraints:
        lines.append(f"Residual constraints: {', '.join(result.residual_constraints[:6])}")
    validated_trade_path = dict(result.validated_trade_path or {})
    validated_files = [str(item).strip() for item in validated_trade_path.get("supporting_files") or [] if str(item).strip()]
    validated_commands = [str(item).strip() for item in validated_trade_path.get("supporting_commands") or [] if str(item).strip()]
    if validated_files:
        lines.append(f"Validated files: {', '.join(validated_files[:6])}")
    if validated_commands:
        lines.append(f"Validated commands: {', '.join(validated_commands[:6])}")
    test_result = dict(result.test_result or {})
    if test_result:
        command = str(test_result.get("command") or "").strip()
        status = str(test_result.get("status") or "").strip()
        if command or status:
            lines.append(f"Test result: {(status or 'unknown').upper()} {command}".rstrip())
    return "\n".join(lines).strip()


def _write_report_bundle(*, report: dict[str, Any], markdown: str, out_dir: Path, stem: str) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path


def _handle_coding_run(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    db_path = _resolve_db_path(args.db, repo_root)
    session = CodingSession(
        model=args.model,
        db_path=str(db_path),
        user_id=args.user_id,
        repo_root=str(repo_root),
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
        enable_compile_loop=not args.disable_compile_loop,
        c2a_policy_path=args.c2a_policy_path,
        disable_c2a_policy=args.disable_c2a_policy,
    )
    try:
        result = session.ask(args.prompt, test_command=args.test_command)
    finally:
        session.close()
    if args.json:
        _print_json(result)
    else:
        print(_render_proxy_text(result))
    return 0


def _handle_coding_plan(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    db_path = _resolve_db_path(args.db, repo_root)
    session = CodingSession(
        model=args.model,
        db_path=str(db_path),
        user_id=args.user_id,
        repo_root=str(repo_root),
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
        enable_compile_loop=not args.disable_compile_loop,
        c2a_policy_path=args.c2a_policy_path,
        disable_c2a_policy=args.disable_c2a_policy,
    )
    try:
        plan = session.build_plan(args.prompt)
    finally:
        session.close()
    if args.json:
        _print_json(plan)
    else:
        print(render_workflow_plan_block(plan).strip() or "No workflow plan generated.")
    return 0


def _handle_patch_benchmark(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(".")
    db_path = _resolve_db_path(args.db, repo_root)
    report = run_patch_execution_benchmark(
        pack_path=args.pack,
        split=args.split,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        db_path=str(db_path),
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
        memla_c2a_policy_path=args.memla_c2a_policy_path,
        disable_memla_c2a_policy=args.disable_memla_c2a_policy,
    )
    markdown = render_patch_execution_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("patch_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="patch_execution_report",
    )
    print(f"Wrote patch benchmark JSON: {json_path}")
    print(f"Wrote patch benchmark Markdown: {md_path}")
    print(
        "Summary: "
        f"raw apply {report.get('raw_apply_rate', 0.0)} | "
        f"memla apply {report.get('memla_apply_rate', 0.0)} | "
        f"raw semantic {report.get('avg_raw_semantic_command_success_rate', 0.0)} | "
        f"memla semantic {report.get('avg_memla_semantic_command_success_rate', 0.0)}"
    )
    return 0


def _handle_compile_benchmark(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    db_path = _resolve_db_path(args.db, repo_root)
    report = run_compile_loop_benchmark(
        db_path=str(db_path),
        repo_root=str(repo_root),
        user_id=args.user_id,
        cases_path=args.cases,
        model=args.model,
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
        memla_c2a_policy_path=args.memla_c2a_policy_path,
        disable_memla_c2a_policy=args.disable_memla_c2a_policy,
    )
    markdown = render_compile_loop_benchmark_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("compile_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="compile_loop_benchmark_report",
    )
    print(f"Wrote compile benchmark JSON: {json_path}")
    print(f"Wrote compile benchmark Markdown: {md_path}")
    print(
        "Summary: "
        f"raw command recall {report.get('avg_raw_command_recall', 0.0)} | "
        f"compile combined command recall {report.get('avg_compile_combined_command_recall', 0.0)} | "
        f"compile validated command recall {report.get('avg_compile_validated_command_recall', 0.0)}"
    )
    return 0


def _handle_c2a_benchmark(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    db_path = _resolve_db_path(args.db, repo_root)
    report = run_coding_c2a_benchmark(
        db_path=str(db_path),
        repo_root=str(repo_root),
        user_id=args.user_id,
        cases_path=args.cases,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        memla_c2a_policy_path=args.memla_c2a_policy_path,
        disable_memla_c2a_policy=args.disable_memla_c2a_policy,
    )
    markdown = render_coding_c2a_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("coding_c2a_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="coding_c2a_benchmark_report",
    )
    print(f"Wrote coding C2A benchmark JSON: {json_path}")
    print(f"Wrote coding C2A benchmark Markdown: {md_path}")
    utility_index = report.get("memla_vs_raw_c2a_utility_index")
    utility_text = utility_index if utility_index is not None else "n/a"
    print(
        "Summary: "
        f"raw utility {report.get('avg_raw_c2a_utility', 0.0)} | "
        f"memla utility {report.get('avg_memla_c2a_utility', 0.0)} | "
        f"utility index {utility_text}"
    )
    return 0


def _handle_extract_c2a(args: argparse.Namespace) -> int:
    report = extract_c2a_trace_bank(
        report_paths=list(args.report or []),
        min_utility_delta=args.min_delta,
    )
    markdown = render_c2a_trace_bank_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("coding_c2a_extract")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="c2a_trace_bank_summary",
    )
    jsonl_path = out_dir / "c2a_trace_bank.jsonl"
    jsonl_lines = [json.dumps(row, ensure_ascii=True) for row in report.get("rows", [])]
    jsonl_path.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "json_summary": str(json_path),
                "markdown_summary": str(md_path),
                "jsonl_bank": str(jsonl_path),
                "rows_extracted": report.get("rows_extracted", 0),
                "winner_counts": report.get("winner_counts", {}),
                "teacher_signal_class_counts": report.get("teacher_signal_class_counts", {}),
            }
        )
    else:
        print(f"Wrote C2A trace bank JSON summary: {json_path}")
        print(f"Wrote C2A trace bank Markdown summary: {md_path}")
        print(f"Wrote C2A trace bank JSONL: {jsonl_path}")
        print(
            "Summary: "
            f"rows {report.get('rows_extracted', 0)} | "
            f"winner counts {report.get('winner_counts', {})} | "
            f"teacher signals {report.get('teacher_signal_class_counts', {})}"
        )
    return 0


def _handle_distill_c2a(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    out_path = Path(args.out).resolve() if args.out else (repo_root / ".memla" / "c2a_policy_bank.json").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = distill_c2a_policy_bank(
        trace_bank_path=args.trace_bank,
        min_priority=args.min_priority,
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_c2a_policy_bank_markdown(report), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "policy_bank": str(out_path),
                "markdown_summary": str(md_path),
                "rows_used": report.get("rows_used", 0),
                "source_models": report.get("source_models", {}),
            }
        )
    else:
        print(f"Wrote C2A policy bank JSON: {out_path}")
        print(f"Wrote C2A policy bank Markdown: {md_path}")
        print(
            "Summary: "
            f"rows used {report.get('rows_used', 0)} | "
            f"source models {report.get('source_models', {})}"
        )
    return 0


def _handle_research_convert_capture(args: argparse.Namespace) -> int:
    out_cases = str(Path(args.out_cases).resolve()) if args.out_cases else str(Path("./cases/research_loop_eval_cases_v1.jsonl").resolve())
    report = convert_research_loop_events_to_cases(
        events_path=args.events,
        out_cases_path=out_cases,
        min_iterations=args.min_iterations,
    )
    if args.json:
        _print_json(report)
    else:
        print(f"Wrote research loop cases: {report.get('out_cases_path', out_cases)}")
        print(
            "Summary: "
            f"sessions {report.get('sessions_written', 0)} / {report.get('sessions_seen', 0)} | "
            f"events {report.get('events_seen', 0)}"
        )
    return 0


def _configure_research_deployment_economics_args(
    parser: argparse.ArgumentParser,
    *,
    include_decisions_per_session: bool = False,
) -> None:
    lane_labels = {
        "raw": "raw lane",
        "memla": "Memla lane",
        "frontier": "frontier lane",
    }
    for lane_key, lane_label in lane_labels.items():
        parser.add_argument(
            f"--deploy-{lane_key}-input-price-per-million",
            type=float,
            default=None,
            help=f"Deployment-model input-token price for the {lane_label}. If omitted, no deployment pricing is assumed for that lane.",
        )
        parser.add_argument(
            f"--deploy-{lane_key}-output-price-per-million",
            type=float,
            default=None,
            help=f"Deployment-model output-token price for the {lane_label}.",
        )
        parser.add_argument(
            f"--deploy-{lane_key}-fixed-cost-per-decision",
            type=float,
            default=None,
            help=f"Deployment-model fixed USD cost per decision for the {lane_label} (useful for local GPU routing).",
        )
    parser.add_argument(
        "--deploy-memla-fallback-rate",
        type=float,
        default=None,
        help="Expected fraction of Memla decisions that escalate to the fallback frontier lane.",
    )
    parser.add_argument(
        "--deploy-memla-fallback-use-verifier-rate",
        action="store_true",
        help="Use the observed Memla verifier-override rate as the fallback-rate assumption.",
    )
    parser.add_argument(
        "--deploy-memla-fallback-input-price-per-million",
        type=float,
        default=None,
        help="Optional explicit fallback input price. Defaults to the frontier deployment pricing when omitted.",
    )
    parser.add_argument(
        "--deploy-memla-fallback-output-price-per-million",
        type=float,
        default=None,
        help="Optional explicit fallback output price. Defaults to the frontier deployment pricing when omitted.",
    )
    parser.add_argument(
        "--deploy-memla-fallback-fixed-cost-per-decision",
        type=float,
        default=None,
        help="Optional explicit fixed fallback cost per decision. Defaults to the frontier deployment pricing when omitted.",
    )
    if include_decisions_per_session:
        parser.add_argument(
            "--deploy-decisions-per-session",
            type=float,
            default=None,
            help="Optional production override for average Phase-3 decisions per session. Defaults to the observed replay slice.",
        )


_RESEARCH_PRICING_PROFILES: dict[str, dict[str, Any]] = {
    "none": {},
    "perplexity_public_sonar": {
        "deploy_raw_fixed_cost_per_decision": 0.002,
        "deploy_memla_fixed_cost_per_decision": 0.002,
        "deploy_frontier_input_price_per_million": 2.0,
        "deploy_frontier_output_price_per_million": 8.0,
        "deploy_frontier_fixed_cost_per_decision": 0.005,
        "deploy_memla_fallback_use_verifier_rate": True,
    },
    "perplexity_public_sonar_heavy": {
        "deploy_raw_fixed_cost_per_decision": 0.002,
        "deploy_memla_fixed_cost_per_decision": 0.002,
        "deploy_frontier_input_price_per_million": 2.0,
        "deploy_frontier_output_price_per_million": 8.0,
        "deploy_frontier_fixed_cost_per_decision": 0.015,
        "deploy_memla_fallback_use_verifier_rate": True,
    },
    "claude_sonnet_public": {
        "deploy_raw_fixed_cost_per_decision": 0.002,
        "deploy_memla_fixed_cost_per_decision": 0.002,
        "deploy_frontier_input_price_per_million": 3.0,
        "deploy_frontier_output_price_per_million": 15.0,
        "deploy_memla_fallback_use_verifier_rate": True,
    },
}


def _configure_research_pricing_profile_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--pricing-profile",
        default="none",
        choices=sorted(_RESEARCH_PRICING_PROFILES.keys()),
        help="Optional deployment-economics preset so the customer command can stay short.",
    )


def _apply_research_pricing_profile(args: argparse.Namespace) -> None:
    profile = dict(_RESEARCH_PRICING_PROFILES.get(str(getattr(args, "pricing_profile", "none")), {}))
    if not profile:
        return
    for key, value in profile.items():
        current = getattr(args, key, None)
        if isinstance(value, bool):
            if not current:
                setattr(args, key, value)
            continue
        if current is None:
            setattr(args, key, value)


def _handle_research_benchmark_replay(args: argparse.Namespace) -> int:
    _apply_research_pricing_profile(args)
    report = run_research_loop_replay_benchmark(
        cases_path=args.cases,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        frontier_model=args.frontier_model,
        limit=args.limit,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        frontier_provider=args.frontier_provider,
        frontier_base_url=args.frontier_base_url,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
        deploy_raw_input_price_per_million=args.deploy_raw_input_price_per_million,
        deploy_raw_output_price_per_million=args.deploy_raw_output_price_per_million,
        deploy_raw_fixed_cost_per_decision=args.deploy_raw_fixed_cost_per_decision,
        deploy_memla_input_price_per_million=args.deploy_memla_input_price_per_million,
        deploy_memla_output_price_per_million=args.deploy_memla_output_price_per_million,
        deploy_memla_fixed_cost_per_decision=args.deploy_memla_fixed_cost_per_decision,
        deploy_frontier_input_price_per_million=args.deploy_frontier_input_price_per_million,
        deploy_frontier_output_price_per_million=args.deploy_frontier_output_price_per_million,
        deploy_frontier_fixed_cost_per_decision=args.deploy_frontier_fixed_cost_per_decision,
        deploy_memla_fallback_rate=args.deploy_memla_fallback_rate,
        deploy_memla_fallback_use_verifier_rate=args.deploy_memla_fallback_use_verifier_rate,
        deploy_memla_fallback_input_price_per_million=args.deploy_memla_fallback_input_price_per_million,
        deploy_memla_fallback_output_price_per_million=args.deploy_memla_fallback_output_price_per_million,
        deploy_memla_fallback_fixed_cost_per_decision=args.deploy_memla_fallback_fixed_cost_per_decision,
        deploy_decisions_per_session=args.deploy_decisions_per_session,
        frontier_use_logged_decisions=getattr(args, "frontier_use_logged_decisions", False),
    )
    markdown = render_research_loop_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("research_loop_replay")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="research_loop_replay_report",
    )
    print(f"Wrote research replay benchmark JSON: {json_path}")
    print(f"Wrote research replay benchmark Markdown: {md_path}")
    print(
        "Summary: "
        f"raw action {report.get('raw', {}).get('action_accuracy', 0.0)} | "
        f"memla action {report.get('memla', {}).get('action_accuracy', 0.0)} | "
        f"frontier action {report.get('frontier', {}).get('action_accuracy', 0.0)}"
    )
    deployment = dict(report.get("deployment_economics") or {})
    memla_cost = dict(deployment.get("memla") or {}).get("modeled_cost_per_1k_sessions")
    frontier_cost = dict(deployment.get("frontier") or {}).get("modeled_cost_per_1k_sessions")
    memla_savings = dict(deployment.get("savings_vs_frontier_per_1k_sessions") or {}).get("memla")
    if memla_cost is not None or frontier_cost is not None or memla_savings is not None:
        print(
            "Economics: "
            f"memla/1K {memla_cost if memla_cost is not None else 'n/a'} | "
            f"frontier/1K {frontier_cost if frontier_cost is not None else 'n/a'} | "
            f"memla savings/1K {memla_savings if memla_savings is not None else 'n/a'}"
        )
    return 0


def _handle_research_benchmark_live_shadow(args: argparse.Namespace) -> int:
    _apply_research_pricing_profile(args)
    report = run_research_loop_live_shadow_benchmark(
        cases_path=args.cases,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        frontier_model=args.frontier_model,
        limit=args.limit,
        max_iterations=args.max_iterations,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        frontier_provider=args.frontier_provider,
        frontier_base_url=args.frontier_base_url,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
        deploy_raw_input_price_per_million=args.deploy_raw_input_price_per_million,
        deploy_raw_output_price_per_million=args.deploy_raw_output_price_per_million,
        deploy_raw_fixed_cost_per_decision=args.deploy_raw_fixed_cost_per_decision,
        deploy_memla_input_price_per_million=args.deploy_memla_input_price_per_million,
        deploy_memla_output_price_per_million=args.deploy_memla_output_price_per_million,
        deploy_memla_fixed_cost_per_decision=args.deploy_memla_fixed_cost_per_decision,
        deploy_frontier_input_price_per_million=args.deploy_frontier_input_price_per_million,
        deploy_frontier_output_price_per_million=args.deploy_frontier_output_price_per_million,
        deploy_frontier_fixed_cost_per_decision=args.deploy_frontier_fixed_cost_per_decision,
        deploy_memla_fallback_rate=args.deploy_memla_fallback_rate,
        deploy_memla_fallback_use_verifier_rate=args.deploy_memla_fallback_use_verifier_rate,
        deploy_memla_fallback_input_price_per_million=args.deploy_memla_fallback_input_price_per_million,
        deploy_memla_fallback_output_price_per_million=args.deploy_memla_fallback_output_price_per_million,
        deploy_memla_fallback_fixed_cost_per_decision=args.deploy_memla_fallback_fixed_cost_per_decision,
    )
    markdown = render_research_loop_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("research_loop_live_shadow")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="research_loop_live_shadow_report",
    )
    print(f"Wrote research live-shadow benchmark JSON: {json_path}")
    print(f"Wrote research live-shadow benchmark Markdown: {md_path}")
    print(
        "Summary: "
        f"raw final success {report.get('raw', {}).get('avg_final_success', 0.0)} | "
        f"memla final success {report.get('memla', {}).get('avg_final_success', 0.0)} | "
        f"frontier final success {report.get('frontier', {}).get('avg_final_success', 0.0)}"
    )
    deployment = dict(report.get("deployment_economics") or {})
    memla_cost = dict(deployment.get("memla") or {}).get("modeled_cost_per_1k_sessions")
    frontier_cost = dict(deployment.get("frontier") or {}).get("modeled_cost_per_1k_sessions")
    memla_savings = dict(deployment.get("savings_vs_frontier_per_1k_sessions") or {}).get("memla")
    if memla_cost is not None or frontier_cost is not None or memla_savings is not None:
        print(
            "Economics: "
            f"memla/1K {memla_cost if memla_cost is not None else 'n/a'} | "
            f"frontier/1K {frontier_cost if frontier_cost is not None else 'n/a'} | "
            f"memla savings/1K {memla_savings if memla_savings is not None else 'n/a'}"
        )
    return 0


def _format_eval_harness_pct(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"{float(value) * 100.0:.2f}%"


def _format_eval_harness_pp_delta(value: float | None) -> str:
    if value is None:
        return "n/a"
    sign = "+" if float(value) > 0 else ""
    return f"{sign}{float(value) * 100.0:.2f}pp"


def _format_eval_harness_usd(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${float(value):.2f}"


def _handle_research_eval_harness(args: argparse.Namespace) -> int:
    _apply_research_pricing_profile(args)
    if not args.frontier_use_logged_decisions and not str(args.frontier_model or "").strip():
        raise SystemExit("--frontier-model is required unless --frontier-use-logged-decisions is set.")
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("research_eval_harness")
    out_dir.mkdir(parents=True, exist_ok=True)
    cases_path = Path(args.input).resolve()
    if args.normalize_capture:
        normalized_path = out_dir / "research_eval_cases.jsonl"
        summary = convert_research_loop_events_to_cases(
            events_path=str(cases_path),
            out_cases_path=str(normalized_path),
            min_iterations=args.min_iterations,
        )
        cases_path = Path(str(summary.get("out_cases_path") or normalized_path)).resolve()
    raw_model = args.raw_model or args.memla_model
    report = run_research_loop_replay_benchmark(
        cases_path=str(cases_path),
        raw_model=raw_model,
        memla_model=args.memla_model,
        frontier_model=args.frontier_model,
        limit=args.limit,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        frontier_provider=args.frontier_provider,
        frontier_base_url=args.frontier_base_url,
        input_price_per_million=args.input_price_per_million,
        output_price_per_million=args.output_price_per_million,
        deploy_raw_input_price_per_million=args.deploy_raw_input_price_per_million,
        deploy_raw_output_price_per_million=args.deploy_raw_output_price_per_million,
        deploy_raw_fixed_cost_per_decision=args.deploy_raw_fixed_cost_per_decision,
        deploy_memla_input_price_per_million=args.deploy_memla_input_price_per_million,
        deploy_memla_output_price_per_million=args.deploy_memla_output_price_per_million,
        deploy_memla_fixed_cost_per_decision=args.deploy_memla_fixed_cost_per_decision,
        deploy_frontier_input_price_per_million=args.deploy_frontier_input_price_per_million,
        deploy_frontier_output_price_per_million=args.deploy_frontier_output_price_per_million,
        deploy_frontier_fixed_cost_per_decision=args.deploy_frontier_fixed_cost_per_decision,
        deploy_memla_fallback_rate=args.deploy_memla_fallback_rate,
        deploy_memla_fallback_use_verifier_rate=args.deploy_memla_fallback_use_verifier_rate,
        deploy_memla_fallback_input_price_per_million=args.deploy_memla_fallback_input_price_per_million,
        deploy_memla_fallback_output_price_per_million=args.deploy_memla_fallback_output_price_per_million,
        deploy_memla_fallback_fixed_cost_per_decision=args.deploy_memla_fallback_fixed_cost_per_decision,
        deploy_decisions_per_session=args.deploy_decisions_per_session,
        frontier_use_logged_decisions=args.frontier_use_logged_decisions,
    )
    markdown = render_research_loop_markdown(report)
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="research_eval_harness_report",
    )
    memla = dict(report.get("memla") or {})
    frontier = dict(report.get("frontier") or {})
    deployment = dict(report.get("deployment_economics") or {})
    savings = dict(deployment.get("savings_vs_frontier_per_1k_sessions") or {}).get("memla")
    memla_false = memla.get("false_converge_rate")
    frontier_false = frontier.get("false_converge_rate")
    delta = None
    if memla_false is not None and frontier_false is not None:
        delta = float(memla_false) - float(frontier_false)
    threshold_pp = float(args.acceptance_delta_pp)
    passed = delta is not None and (float(delta) * 100.0) <= threshold_pp
    verdict = "PASS" if passed else "FAIL"
    print(f"Wrote eval harness JSON: {json_path}")
    print(f"Wrote eval harness Markdown: {md_path}")
    print(f"Eval Harness Verdict: {verdict}")
    print(f"Frontier false-converge: {_format_eval_harness_pct(frontier_false)}")
    print(f"Memla false-converge: {_format_eval_harness_pct(memla_false)}")
    print(f"Delta vs baseline: {_format_eval_harness_pp_delta(delta)}")
    print(f"Estimated cost delta / 1,000 sessions: {_format_eval_harness_usd(savings)}")
    print(f"Pass/fail threshold: <= +{threshold_pp:.2f}pp")
    return 0


def _handle_math_benchmark(args: argparse.Namespace) -> int:
    report = run_math_c2a_teacher_student_benchmark(
        cases_path=args.cases,
        teacher_model=args.teacher_model,
        student_models=args.student_models,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        max_iterations=args.max_iterations,
        top_k=args.top_k,
        executor_mode=args.executor_mode,
        teacher_trace_source=args.teacher_trace_source,
    )
    markdown = render_math_c2a_teacher_student_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("math_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="math_c2a_teacher_student_report",
    )
    print(f"Wrote math benchmark JSON: {json_path}")
    print(f"Wrote math benchmark Markdown: {md_path}")
    if args.executor_mode == "stepwise_rerank":
        lane_lines = [
            f"{lane.get('lane_id')}: choice={lane.get('avg_choice_accuracy', 0.0)} ambiguous={lane.get('avg_ambiguous_choice_accuracy', 0.0)}"
            for lane in report.get("lanes", [])
        ]
    else:
        lane_lines = [
            f"{lane.get('lane_id')}: answer={lane.get('avg_answer_accuracy', 0.0)} transmutation={lane.get('avg_transmutation_recall', 0.0)}"
            for lane in report.get("lanes", [])
        ]
    print("Summary:")
    for line in lane_lines:
        print(f"  {line}")
    return 0


def _handle_finance_pretrade_benchmark(args: argparse.Namespace) -> int:
    report = run_finance_pretrade_benchmark(
        cases_path=args.cases,
        repo_root=str(_resolve_repo_root(args.repo_root)),
        case_ids=list(args.case_id or []),
        limit=args.limit,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        raw_iterations=args.raw_iterations,
        memla_iterations=args.memla_iterations,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        memla_finance_policy_path=args.memla_finance_policy_path,
        disable_memla_finance_policy=args.disable_memla_finance_policy,
    )
    markdown = render_finance_pretrade_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("finance_pretrade_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="finance_pretrade_benchmark_report",
    )
    print(f"Wrote finance benchmark JSON: {json_path}")
    print(f"Wrote finance benchmark Markdown: {md_path}")
    utility_index = report.get("memla_vs_raw_finance_utility_index")
    utility_text = utility_index if utility_index is not None else "n/a"
    print(
        "Summary: "
        f"raw utility {report.get('avg_raw_finance_utility', 0.0)} | "
        f"memla utility {report.get('avg_memla_finance_utility', 0.0)} | "
        f"utility index {utility_text}"
    )
    return 0


def _handle_extract_finance_pretrade(args: argparse.Namespace) -> int:
    report = extract_finance_trace_bank(
        report_paths=list(args.report or []),
        min_utility_delta=args.min_delta,
    )
    markdown = render_finance_trace_bank_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("finance_pretrade_extract")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="finance_trace_bank_summary",
    )
    jsonl_path = out_dir / "finance_trace_bank.jsonl"
    jsonl_lines = [json.dumps(row, ensure_ascii=True) for row in report.get("rows", [])]
    jsonl_path.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "json_summary": str(json_path),
                "markdown_summary": str(md_path),
                "jsonl_bank": str(jsonl_path),
                "rows_extracted": report.get("rows_extracted", 0),
                "winner_counts": report.get("winner_counts", {}),
                "teacher_signal_class_counts": report.get("teacher_signal_class_counts", {}),
            }
        )
    else:
        print(f"Wrote finance trace bank JSON summary: {json_path}")
        print(f"Wrote finance trace bank Markdown summary: {md_path}")
        print(f"Wrote finance trace bank JSONL: {jsonl_path}")
        print(
            "Summary: "
            f"rows {report.get('rows_extracted', 0)} | "
            f"winner counts {report.get('winner_counts', {})} | "
            f"teacher signals {report.get('teacher_signal_class_counts', {})}"
        )
    return 0


def _handle_distill_finance_pretrade(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    out_path = Path(args.out).resolve() if args.out else (repo_root / ".memla" / "finance_policy_bank.json").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = distill_finance_policy_bank(
        trace_bank_path=args.trace_bank,
        min_priority=args.min_priority,
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_finance_policy_bank_markdown(report), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "policy_bank": str(out_path),
                "markdown_summary": str(md_path),
                "rows_used": report.get("rows_used", 0),
                "source_models": report.get("source_models", {}),
            }
        )
    else:
        print(f"Wrote finance policy bank JSON: {out_path}")
        print(f"Wrote finance policy bank Markdown: {md_path}")
        print(
            "Summary: "
            f"rows used {report.get('rows_used', 0)} | "
            f"source models {report.get('source_models', {})}"
        )
    return 0


def _handle_healthcare_denial_benchmark(args: argparse.Namespace) -> int:
    report = run_healthcare_denial_benchmark(
        cases_path=args.cases,
        case_ids=list(args.case_id or []),
        limit=args.limit,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        raw_iterations=args.raw_iterations,
        memla_iterations=args.memla_iterations,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
    )
    markdown = render_healthcare_denial_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("healthcare_denial_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="healthcare_denial_benchmark_report",
    )
    print(f"Wrote healthcare benchmark JSON: {json_path}")
    print(f"Wrote healthcare benchmark Markdown: {md_path}")
    utility_index = report.get("memla_vs_raw_healthcare_utility_index")
    utility_text = utility_index if utility_index is not None else "n/a"
    print(
        "Summary: "
        f"raw utility {report.get('avg_raw_healthcare_utility', 0.0)} | "
        f"memla utility {report.get('avg_memla_healthcare_utility', 0.0)} | "
        f"utility index {utility_text}"
    )
    return 0


def _handle_policy_authz_benchmark(args: argparse.Namespace) -> int:
    report = run_policy_authz_benchmark(
        cases_path=args.cases,
        repo_root=str(_resolve_repo_root(args.repo_root)),
        case_ids=list(args.case_id or []),
        limit=args.limit,
        raw_model=args.raw_model,
        memla_model=args.memla_model,
        raw_iterations=args.raw_iterations,
        memla_iterations=args.memla_iterations,
        temperature=args.temperature,
        num_ctx=args.num_ctx,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        memla_policy_bank_path=args.memla_policy_bank_path,
        disable_memla_policy_bank=args.disable_memla_policy_bank,
    )
    markdown = render_policy_authz_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("policy_authz_benchmark")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="policy_authz_benchmark_report",
    )
    print(f"Wrote policy benchmark JSON: {json_path}")
    print(f"Wrote policy benchmark Markdown: {md_path}")
    utility_index = report.get("memla_vs_raw_policy_utility_index")
    utility_text = utility_index if utility_index is not None else "n/a"
    print(
        "Summary: "
        f"raw utility {report.get('avg_raw_policy_utility', 0.0)} | "
        f"memla utility {report.get('avg_memla_policy_utility', 0.0)} | "
        f"utility index {utility_text}"
    )
    return 0


def _handle_extract_policy_authz(args: argparse.Namespace) -> int:
    report = extract_policy_trace_bank(
        report_paths=list(args.report or []),
        min_utility_delta=args.min_delta,
    )
    markdown = render_policy_trace_bank_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("policy_trace_bank")
    json_path, md_path = _write_report_bundle(
        report=report,
        markdown=markdown,
        out_dir=out_dir,
        stem="policy_trace_bank_summary",
    )
    jsonl_path = out_dir / "policy_trace_bank.jsonl"
    jsonl_lines = [json.dumps(row, ensure_ascii=True) for row in report.get("rows", [])]
    jsonl_path.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "json_summary": str(json_path),
                "markdown_summary": str(md_path),
                "jsonl_bank": str(jsonl_path),
                "rows_extracted": report.get("rows_extracted", 0),
                "winner_counts": report.get("winner_counts", {}),
                "teacher_signal_class_counts": report.get("teacher_signal_class_counts", {}),
            }
        )
    else:
        print(f"Wrote policy trace bank JSON summary: {json_path}")
        print(f"Wrote policy trace bank Markdown summary: {md_path}")
        print(f"Wrote policy trace bank JSONL: {jsonl_path}")
        print(
            "Summary: "
            f"rows {report.get('rows_extracted', 0)} | "
            f"winner counts {report.get('winner_counts', {})} | "
            f"teacher signals {report.get('teacher_signal_class_counts', {})}"
        )
    return 0


def _handle_distill_policy_authz(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    out_path = Path(args.out).resolve() if args.out else (repo_root / ".memla" / "policy_authz_policy_bank.json").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = distill_policy_authz_policy_bank(
        trace_bank_path=args.trace_bank,
        min_priority=args.min_priority,
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_policy_authz_policy_bank_markdown(report), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "policy_bank": str(out_path),
                "markdown_summary": str(md_path),
                "rows_used": report.get("rows_used", 0),
                "source_models": report.get("source_models", {}),
            }
        )
    else:
        print(f"Wrote policy bank JSON: {out_path}")
        print(f"Wrote policy bank Markdown: {md_path}")
        print(
            "Summary: "
            f"rows used {report.get('rows_used', 0)} | "
            f"source models {report.get('source_models', {})}"
        )
    return 0


def _handle_terminal_plan(args: argparse.Namespace) -> int:
    prompt = _resolve_terminal_prompt(args)
    browser_state = load_browser_session_state()
    started = time.perf_counter()
    plan = _build_terminal_request_plan(args, prompt, browser_state=browser_state)
    planning_seconds = round(time.perf_counter() - started, 4)
    if args.json:
        payload = terminal_plan_to_dict(plan)
        payload["planning_duration_seconds"] = planning_seconds
        _print_json(payload)
    else:
        print(render_terminal_plan_text(plan))
        print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
    return 0 if plan.actions else 1


def _handle_terminal_run(args: argparse.Namespace) -> int:
    prompt = _resolve_terminal_prompt(args)
    browser_state = load_browser_session_state()
    plan_started = time.perf_counter()
    plan = _build_terminal_request_plan(args, prompt, browser_state=browser_state)
    planning_seconds = round(time.perf_counter() - plan_started, 4)
    if not plan.actions:
        if args.json:
            payload = terminal_plan_to_dict(plan)
            payload["planning_duration_seconds"] = planning_seconds
            _print_json(payload)
        else:
            print(render_terminal_plan_text(plan))
            print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
        return 1
    run_started = time.perf_counter()
    result = execute_terminal_plan(plan, browser_state=browser_state)
    execution_seconds = round(time.perf_counter() - run_started, 4)
    total_seconds = round(planning_seconds + execution_seconds, 4)
    if args.json:
        payload = terminal_execution_to_dict(result)
        payload["planning_duration_seconds"] = planning_seconds
        payload["execution_duration_seconds"] = execution_seconds
        payload["total_duration_seconds"] = total_seconds
        _print_json(payload)
    else:
        print(render_terminal_execution_text(result))
        print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
        print(f"Execution time: {_format_terminal_duration(execution_seconds)}")
        print(f"Total time: {_format_terminal_duration(total_seconds)}")
    return 0 if result.ok else 1


def _handle_terminal_scout(args: argparse.Namespace) -> int:
    prompt = _resolve_terminal_prompt(args)
    browser_state = load_browser_session_state()
    started = time.perf_counter()
    result = run_terminal_scout(
        prompt,
        browser_state=browser_state,
        save_state=True,
    )
    total_seconds = round(time.perf_counter() - started, 4)
    if args.json:
        payload = terminal_scout_to_dict(result)
        payload["total_duration_seconds"] = total_seconds
        _print_json(payload)
    else:
        print(render_terminal_scout_text(result))
        print(f"Total time: {_format_terminal_duration(total_seconds)}")
    return 0 if result.ok else 1


def _handle_terminal_step(args: argparse.Namespace) -> int:
    prompt = _resolve_terminal_prompt(args)
    browser_state = load_browser_session_state()
    client = None if args.heuristic_only else build_terminal_llm_client(provider=args.provider or None, base_url=args.base_url or None)
    started = time.perf_counter()
    report = build_terminal_step_report(
        prompt=prompt,
        model=args.model,
        client=client,
        heuristic_only=args.heuristic_only,
        temperature=args.temperature,
        browser_state=browser_state,
    )
    planning_seconds = round(time.perf_counter() - started, 4)
    if not args.choice:
        if args.json:
            payload = terminal_step_report_to_dict(report)
            payload["planning_duration_seconds"] = planning_seconds
            _print_json(payload)
        else:
            print(render_terminal_step_report_text(report))
            print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
            if report.candidates:
                print('Run again with `--choice N` to execute a candidate and log the trace.')
        return 0 if report.candidates else 1

    execution_started = time.perf_counter()
    try:
        execution = execute_terminal_step(
            report,
            choice=args.choice,
            browser_state=browser_state,
            trace_path=args.trace_log or None,
        )
    except ValueError as exc:
        if args.json:
            _print_json(
                {
                    "prompt": prompt,
                    "planning_duration_seconds": planning_seconds,
                    "error": str(exc),
                }
            )
        else:
            print(render_terminal_step_report_text(report))
            print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
            print(str(exc))
        return 1
    execution_seconds = round(time.perf_counter() - execution_started, 4)
    total_seconds = round(planning_seconds + execution_seconds, 4)
    if args.json:
        payload = terminal_step_execution_to_dict(execution)
        payload["planning_duration_seconds"] = planning_seconds
        payload["execution_duration_seconds"] = execution_seconds
        payload["total_duration_seconds"] = total_seconds
        _print_json(payload)
    else:
        print(render_terminal_step_execution_text(execution))
        print(f"Planning time: {_format_terminal_duration(planning_seconds)}")
        print(f"Execution time: {_format_terminal_duration(execution_seconds)}")
        print(f"Total time: {_format_terminal_duration(total_seconds)}")
    return 0 if execution.result.ok else 1


def _handle_terminal_workbench(args: argparse.Namespace) -> int:
    host = str(args.host or "127.0.0.1").strip() or "127.0.0.1"
    port = int(args.port)
    print(f"Serving Memla browser workbench at http://{host}:{port}")
    print("Press Ctrl+C to stop the local UI server.")
    try:
        serve_terminal_workbench(
            host=host,
            port=port,
            model=args.model,
            provider=args.provider,
            base_url=args.base_url,
            temperature=args.temperature,
            heuristic_only=args.heuristic_only,
            trace_log=args.trace_log,
        )
    except KeyboardInterrupt:
        print("Stopped Memla browser workbench.")
    return 0


def _handle_memla_serve(args: argparse.Namespace) -> int:
    host = str(args.host or "127.0.0.1").strip() or "127.0.0.1"
    port = int(args.port)
    print(f"Serving Memla API at http://{host}:{port}")
    print("Memla API version: 0.1.1")
    print("Routes: GET /health, GET /state, GET /memory, GET /actions, GET /missions, GET /debug/browser, POST /missions, POST /actions/plan, POST /actions/draft, POST /actions/capsule, POST /run, POST /scout, POST /followup, POST /debug/browser")
    print("Browser debug upload/history: enabled at POST /debug/browser and GET /debug/browser")
    print("If an iPhone debug upload gets HTTP 404 for /debug/browser, restart the server from this repo checkout with `py -3 memla.py serve ...`.")
    print("Press Ctrl+C to stop the local API server.")
    try:
        _serve_memla_api(
            host=host,
            port=port,
            state_path=args.state_path or None,
            default_model=args.model,
            default_provider=args.provider,
            default_base_url=args.base_url,
            default_temperature=args.temperature,
            default_heuristic_only=args.heuristic_only,
        )
    except KeyboardInterrupt:
        print("Stopped Memla API server.")
    return 0


def _handle_terminal_compare(args: argparse.Namespace) -> int:
    prompt = _resolve_terminal_prompt(args)
    raw_model = _resolve_shared_terminal_model(args, "raw_model")
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    raw_client = build_terminal_llm_client(provider=args.raw_provider or None, base_url=args.raw_base_url or None)
    memla_client = build_terminal_llm_client(provider=args.memla_provider or None, base_url=args.memla_base_url or None)
    browser_state = load_browser_session_state()
    raw_started = time.perf_counter()
    raw_plan = build_raw_terminal_plan(
        prompt=prompt,
        model=raw_model,
        client=raw_client,
        temperature=args.temperature,
        browser_state=browser_state,
    )
    raw_seconds = round(time.perf_counter() - raw_started, 4)
    memla_started = time.perf_counter()
    memla_plan = build_terminal_plan(
        prompt=prompt,
        model=memla_model,
        client=memla_client,
        heuristic_only=args.heuristic_only,
        temperature=args.temperature,
        browser_state=browser_state,
    )
    memla_seconds = round(time.perf_counter() - memla_started, 4)
    speedup = round(raw_seconds / memla_seconds, 4) if memla_seconds > 0 else None
    payload = {
        "prompt": prompt,
        "raw": terminal_plan_to_dict(raw_plan),
        "memla": terminal_plan_to_dict(memla_plan),
        "raw_duration_seconds": raw_seconds,
        "memla_duration_seconds": memla_seconds,
        "memla_speedup": speedup,
    }
    if args.json:
        _print_json(payload)
    else:
        print("=== RAW ===")
        print(render_terminal_plan_text(raw_plan))
        print(f"Planning time: {_format_terminal_duration(raw_seconds)}")
        print("")
        print("=== MEMLA ===")
        print(render_terminal_plan_text(memla_plan))
        print(f"Planning time: {_format_terminal_duration(memla_seconds)}")
        if speedup is not None:
            print("")
            print(f"Speedup: {speedup}x")
    return 0


def _handle_terminal_benchmark(args: argparse.Namespace) -> int:
    raw_model = _resolve_shared_terminal_model(args, "raw_model")
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    report = run_terminal_benchmark(
        cases_path=args.cases,
        raw_model=raw_model,
        memla_model=memla_model,
        raw_provider=args.raw_provider,
        raw_base_url=args.raw_base_url,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        temperature=args.temperature,
        case_ids=args.case_id,
        limit=args.limit,
        heuristic_only=args.heuristic_only,
    )
    markdown = render_terminal_benchmark_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("terminal_benchmark")
    json_path, md_path = _write_report_bundle(
        out_dir=out_dir,
        stem="terminal_benchmark_report",
        report=report,
        markdown=markdown,
    )
    print(f"Wrote terminal benchmark JSON: {json_path}")
    print(f"Wrote terminal benchmark Markdown: {md_path}")
    speedup = report.get("memla_vs_raw_speedup")
    speedup_text = f"{speedup}x" if speedup else "n/a"
    print(
        "Summary: "
        f"raw latency {report.get('avg_raw_latency_ms', 0.0)} ms | "
        f"memla latency {report.get('avg_memla_latency_ms', 0.0)} ms | "
        f"speedup {speedup_text}"
    )
    return 0


def _handle_web_answer_benchmark(args: argparse.Namespace) -> int:
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    report = run_web_answer_benchmark(
        cases_path=args.cases,
        memla_model=memla_model,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        judge_model=args.judge_model,
        judge_provider=args.judge_provider,
        judge_base_url=args.judge_base_url,
        temperature=args.temperature,
        case_ids=args.case_id,
        limit=args.limit,
        heuristic_only=args.heuristic_only,
    )
    markdown = render_web_answer_benchmark_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("web_answer_benchmark")
    json_path, md_path = _write_report_bundle(
        out_dir=out_dir,
        stem="web_answer_benchmark_report",
        report=report,
        markdown=markdown,
    )
    print(f"Wrote web answer benchmark JSON: {json_path}")
    print(f"Wrote web answer benchmark Markdown: {md_path}")
    print(
        "Summary: "
        f"answered {report.get('answered_count', 0)} / {report.get('cases', 0)} | "
        f"avg plan {report.get('avg_plan_latency_ms', 0.0)} ms | "
        f"avg answer {report.get('avg_answer_latency_ms', 0.0)} ms | "
        f"teacher overall {report.get('avg_teacher_overall', 0.0)}"
    )
    return 0


def _handle_web_teacher_loop(args: argparse.Namespace) -> int:
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    teacher_model = args.teacher_model or args.model or memla_model
    report = run_web_teacher_loop(
        cases_path=args.cases,
        memla_model=memla_model,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        teacher_model=teacher_model,
        teacher_provider=args.teacher_provider,
        teacher_base_url=args.teacher_base_url,
        judge_model=args.judge_model,
        judge_provider=args.judge_provider,
        judge_base_url=args.judge_base_url,
        temperature=args.temperature,
        case_ids=args.case_id,
        limit=args.limit,
        heuristic_only=args.heuristic_only,
        rescue_threshold=args.rescue_threshold,
    )
    markdown = render_web_teacher_loop_markdown(report)
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("web_teacher_loop")
    json_path, md_path = _write_report_bundle(
        out_dir=out_dir,
        stem="web_teacher_loop_report",
        report=report,
        markdown=markdown,
    )
    jsonl_path = out_dir / "web_teacher_trace_bank.jsonl"
    jsonl_lines = [json.dumps(row, ensure_ascii=True) for row in report.get("trace_rows", [])]
    jsonl_path.write_text("\n".join(jsonl_lines) + ("\n" if jsonl_lines else ""), encoding="utf-8")
    print(f"Wrote web teacher loop JSON: {json_path}")
    print(f"Wrote web teacher loop Markdown: {md_path}")
    print(f"Wrote web teacher trace bank JSONL: {jsonl_path}")
    print(
        "Summary: "
        f"rescued {report.get('rescued_count', 0)} | "
        f"improved {report.get('improved_count', 0)} | "
        f"promoted rescue {report.get('promoted_rescue_count', 0)} | "
        f"avg baseline {report.get('avg_baseline_overall', 0.0)} | "
        f"avg promoted {report.get('avg_promoted_overall', 0.0)}"
    )
    return 0


def _handle_distill_web_policy(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(".")
    out_path = Path(args.out).resolve() if args.out else (repo_root / ".memla" / "web_policy_bank.json").resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    report = distill_web_policy_bank(
        trace_bank_path=args.trace_bank,
        min_improvement=args.min_improvement,
    )
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(render_web_policy_bank_markdown(report), encoding="utf-8")
    if args.json:
        _print_json(
            {
                "policy_bank": str(out_path),
                "markdown_summary": str(md_path),
                "rows_used": report.get("rows_used", 0),
                "slice_counts": report.get("slice_counts", {}),
            }
        )
    else:
        print(f"Wrote web policy bank JSON: {out_path}")
        print(f"Wrote web policy bank Markdown: {md_path}")
        print(
            "Summary: "
            f"rows used {report.get('rows_used', 0)} | "
            f"slices {report.get('slice_counts', {})}"
        )
    return 0


def _handle_web_overnight_loop(args: argparse.Namespace) -> int:
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    teacher_model = args.teacher_model or args.model or memla_model
    judge_model = args.judge_model or teacher_model
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("web_overnight_loop")
    report = run_web_overnight_loop(
        out_dir=str(out_dir),
        seed_cases_path=args.seed_cases,
        question_count=args.question_count,
        memla_model=memla_model,
        memla_provider=args.memla_provider,
        memla_base_url=args.memla_base_url,
        teacher_model=teacher_model,
        teacher_provider=args.teacher_provider,
        teacher_base_url=args.teacher_base_url,
        judge_model=judge_model,
        judge_provider=args.judge_provider,
        judge_base_url=args.judge_base_url,
        temperature=args.temperature,
        heuristic_only=args.heuristic_only,
        max_rounds=args.max_rounds,
        benchmark_every=args.benchmark_every,
        target_overall=args.target_overall,
        target_hard_pass_rate=args.target_hard_pass_rate,
        allowed_rescues=args.allowed_rescues,
        patience=args.patience,
        min_delta=args.min_delta,
        rescue_threshold=args.rescue_threshold,
        repo_root=args.repo_root,
    )
    markdown = render_web_overnight_loop_markdown(report)
    json_path, md_path = _write_report_bundle(
        out_dir=out_dir,
        stem="web_overnight_loop_report",
        report=report,
        markdown=markdown,
    )
    print(f"Wrote web overnight loop JSON: {json_path}")
    print(f"Wrote web overnight loop Markdown: {md_path}")
    print(
        "Summary: "
        f"questions {report.get('question_count_actual', 0)} | "
        f"initial overall {dict(report.get('initial_benchmark') or {}).get('avg_teacher_overall', 0.0)} | "
        f"best overall {report.get('best_score', 0.0)} | "
        f"hard pass {dict(report.get('latest_benchmark') or {}).get('hard_pass_rate', 0.0)} | "
        f"stop {report.get('stop_reason', '')}"
    )
    return 0


def _handle_terminal_browser_benchmark(args: argparse.Namespace) -> int:
    raw_model = _resolve_shared_terminal_model(args, "raw_model")
    memla_model = _resolve_shared_terminal_model(args, "memla_model")
    ontology_version = str(getattr(args, "ontology_version", "browser_v1") or "browser_v1")
    if ontology_version == "memory_v1":
        benchmark_slug = "memory_benchmark_v1"
    elif ontology_version == "language_v4":
        benchmark_slug = "language_benchmark_v4"
    elif ontology_version == "language_v3":
        benchmark_slug = "language_benchmark_v3"
    elif ontology_version == "language_v2":
        benchmark_slug = "language_benchmark_v2"
    elif ontology_version == "language_v1":
        benchmark_slug = "language_benchmark_v1"
    elif ontology_version == "browser_v8":
        benchmark_slug = "browser_benchmark_v8"
    elif ontology_version == "browser_v7":
        benchmark_slug = "browser_benchmark_v7"
    elif ontology_version == "browser_v6":
        benchmark_slug = "browser_benchmark_v6"
    elif ontology_version == "browser_v5":
        benchmark_slug = "browser_benchmark_v5"
    elif ontology_version == "browser_v4":
        benchmark_slug = "browser_benchmark_v4"
    elif ontology_version == "browser_v3":
        benchmark_slug = "browser_benchmark_v3"
    elif ontology_version == "browser_v2":
        benchmark_slug = "browser_benchmark_v2"
    else:
        benchmark_slug = "browser_benchmark"
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir(benchmark_slug)
    if ontology_version == "memory_v1":
        report = run_memory_ontology_benchmark(
            cases_path=args.cases,
            raw_model=raw_model,
            memla_model=memla_model,
            raw_provider=args.raw_provider,
            raw_base_url=args.raw_base_url,
            memla_provider=args.memla_provider,
            memla_base_url=args.memla_base_url,
            temperature=args.temperature,
            case_ids=args.case_id,
            limit=args.limit,
            memory_root=str(out_dir),
        )
    elif ontology_version == "language_v4":
        report = run_language_rule_benchmark(
            cases_path=args.cases,
            raw_model=raw_model,
            memla_model=memla_model,
            raw_provider=args.raw_provider,
            raw_base_url=args.raw_base_url,
            memla_provider=args.memla_provider,
            memla_base_url=args.memla_base_url,
            temperature=args.temperature,
            case_ids=args.case_id,
            limit=args.limit,
            memory_root=str(out_dir),
        )
    elif ontology_version == "language_v3":
        report = run_language_learning_benchmark(
            cases_path=args.cases,
            raw_model=raw_model,
            memla_model=memla_model,
            raw_provider=args.raw_provider,
            raw_base_url=args.raw_base_url,
            memla_provider=args.memla_provider,
            memla_base_url=args.memla_base_url,
            temperature=args.temperature,
            case_ids=args.case_id,
            limit=args.limit,
            memory_root=str(out_dir),
        )
    else:
        report = run_browser_benchmark(
            cases_path=args.cases,
            raw_model=raw_model,
            memla_model=memla_model,
            raw_provider=args.raw_provider,
            raw_base_url=args.raw_base_url,
            memla_provider=args.memla_provider,
            memla_base_url=args.memla_base_url,
            temperature=args.temperature,
            case_ids=args.case_id,
            limit=args.limit,
            heuristic_only=args.heuristic_only,
            ontology_version=ontology_version,
        )
    markdown = render_browser_benchmark_markdown(report)
    json_path, md_path = _write_report_bundle(
        out_dir=out_dir,
        stem="browser_benchmark_report",
        report=report,
        markdown=markdown,
    )
    print(f"Wrote browser benchmark JSON: {json_path}")
    print(f"Wrote browser benchmark Markdown: {md_path}")
    speedup = report.get("memla_vs_raw_speedup")
    speedup_text = f"{speedup}x" if speedup else "n/a"
    print(
        "Summary: "
        f"raw semantic {report.get('avg_raw_semantic_success', 0.0)} | "
        f"memla semantic {report.get('avg_memla_rule_semantic_success', report.get('avg_memla_warm_semantic_success', report.get('avg_memla_semantic_success', 0.0)))} | "
        f"speedup {speedup_text}"
    )
    return 0


def _handle_thesis_pack(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve() if args.out_dir else _default_report_dir("thesis_pack")
    result = build_thesis_pack(
        coding_path=args.coding,
        math_rerank_path=args.math_rerank,
        math_progress_path=args.math_progress,
        out_dir=str(out_dir),
        site_url=args.site_url,
        coding_secondary_path=args.coding_secondary,
        compile_support_path=args.compile_support,
    )
    _print_json(result)
    return 0


def _handle_publish_site(args: argparse.Namespace) -> int:
    source_dir = Path(args.source).resolve()
    out_dir = Path(args.out_dir).resolve()
    result = _sync_public_site(source_dir=source_dir, out_dir=out_dir)
    if args.json:
        _print_json(result)
    else:
        print(f"Published site from {result['source_dir']} to {result['out_dir']}")
        print(f"Copied: {', '.join(result['copied'])}")
        print(f"Site ready: {'yes' if result['site_ready'] else 'no'}")
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    repo_root = _resolve_repo_root(args.repo_root)
    db_path = _resolve_db_path(args.db, repo_root)
    db_parent = db_path.parent
    report: dict[str, Any] = {
        "python": {
            "version": sys.version.split()[0],
            "ok": sys.version_info >= (3, 11),
        },
        "repo_root": {
            "path": str(repo_root),
            "exists": repo_root.exists(),
            "git_repo": (repo_root / ".git").exists(),
        },
        "db_path": {
            "path": str(db_path),
            "parent_exists": db_parent.exists(),
            "parent_writable": os.access(db_parent, os.W_OK),
        },
        "site": {
            "root_index": str((repo_root / "index.html").resolve()),
            "root_vercel_json": str((repo_root / "vercel.json").resolve()),
            "ready": (repo_root / "index.html").exists() and (repo_root / "vercel.json").exists(),
        },
        "ollama": {
            "requested_model": args.model,
            "reachable": False,
            "url": "",
            "model_count": 0,
            "model_present": False,
            "models": [],
            "error": "",
        },
    }

    last_error = ""
    for url in _candidate_ollama_urls(args.ollama_url):
        try:
            ollama = _probe_ollama(url)
        except (urllib_error.URLError, urllib_error.HTTPError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = str(exc)
            continue
        report["ollama"].update(ollama)
        report["ollama"]["reachable"] = True
        report["ollama"]["model_present"] = args.model in set(ollama.get("models") or [])
        break
    else:
        report["ollama"]["error"] = last_error or "Could not reach Ollama."

    report["overall_ok"] = all(
        [
            report["python"]["ok"],
            report["repo_root"]["exists"],
            report["db_path"]["parent_writable"],
        ]
    )

    if args.json:
        _print_json(report)
        return 0

    def _status(ok: bool) -> str:
        return "PASS" if ok else "FAIL"

    print(f"[{_status(report['python']['ok'])}] Python {report['python']['version']} (need 3.11+)")
    print(
        f"[{_status(report['repo_root']['exists'])}] Repo root {report['repo_root']['path']}"
        + (" (git repo)" if report["repo_root"]["git_repo"] else " (no .git found)")
    )
    print(
        f"[{_status(report['db_path']['parent_writable'])}] DB parent {db_parent}"
        + ("" if report["db_path"]["parent_writable"] else " is not writable")
    )
    print(
        f"[{_status(report['site']['ready'])}] Root site "
        + ("is Vercel-ready" if report["site"]["ready"] else "is not published at repo root yet")
    )
    if report["ollama"]["reachable"]:
        model_note = "present" if report["ollama"]["model_present"] else "missing"
        print(
            f"[PASS] Ollama reachable at {report['ollama']['url']} "
            f"({report['ollama']['model_count']} models, requested model {model_note})"
        )
    else:
        print(f"[FAIL] Ollama unreachable: {report['ollama']['error']}")
    return 0 if report["overall_ok"] else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="memla",
        description="Memla CLI for bounded coding and math runtimes.",
    )
    subparsers = parser.add_subparsers(dest="command")

    coding_parser = subparsers.add_parser("coding", help="Run coding plans, repairs, and coding benchmarks.")
    coding_sub = coding_parser.add_subparsers(dest="coding_command")

    run_parser = coding_sub.add_parser("run", help="Run a Memla-assisted coding turn against a repository.")
    run_parser.add_argument("--prompt", required=True, help="Task prompt for the coding assistant.")
    run_parser.add_argument("--repo-root", default=".", help="Repository root to operate in. Defaults to the current directory.")
    run_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to <repo>/.memla/memory.sqlite.")
    run_parser.add_argument("--user-id", default=_user_id_default(), help="User or tenant identifier for memory retrieval.")
    run_parser.add_argument("--model", default=_coding_model_default(), help="Technician model to run.")
    run_parser.add_argument("--test-command", default="", help="Optional command to run after the answer is produced.")
    run_parser.add_argument("--temperature", type=float, default=0.1)
    run_parser.add_argument("--top-k", type=int, default=12)
    run_parser.add_argument("--num-ctx", type=int, default=None)
    run_parser.add_argument("--disable-compile-loop", action="store_true", help="Turn off compile-loop priors for this run.")
    run_parser.add_argument("--c2a-policy-path", default="", help="Optional explicit C2A policy bank JSON path.")
    run_parser.add_argument("--disable-c2a-policy", action="store_true", help="Disable self-transmutation priors for this run.")
    run_parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    run_parser.set_defaults(func=_handle_coding_run)

    plan_parser = coding_sub.add_parser("plan", help="Build a Memla workflow plan without asking the model for a final answer.")
    plan_parser.add_argument("--prompt", required=True, help="Task prompt to plan.")
    plan_parser.add_argument("--repo-root", default=".", help="Repository root to inspect. Defaults to the current directory.")
    plan_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to <repo>/.memla/memory.sqlite.")
    plan_parser.add_argument("--user-id", default=_user_id_default(), help="User or tenant identifier for memory retrieval.")
    plan_parser.add_argument("--model", default=_coding_model_default(), help="Model used for retrieval-backed planning.")
    plan_parser.add_argument("--temperature", type=float, default=0.1)
    plan_parser.add_argument("--top-k", type=int, default=12)
    plan_parser.add_argument("--num-ctx", type=int, default=None)
    plan_parser.add_argument("--disable-compile-loop", action="store_true", help="Turn off compile-loop priors while planning.")
    plan_parser.add_argument("--c2a-policy-path", default="", help="Optional explicit C2A policy bank JSON path.")
    plan_parser.add_argument("--disable-c2a-policy", action="store_true", help="Disable self-transmutation priors while planning.")
    plan_parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    plan_parser.set_defaults(func=_handle_coding_plan)

    patch_parser = coding_sub.add_parser("benchmark-patch", help="Run raw-vs-Memla patch execution on git-history patch cases.")
    patch_parser.add_argument("--pack", required=True, help="Patch case pack JSON path.")
    patch_parser.add_argument("--raw-model", required=True, help="Baseline raw model.")
    patch_parser.add_argument("--memla-model", required=True, help="Memla-assisted model.")
    patch_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to ./.memla/memory.sqlite.")
    patch_parser.add_argument("--user-id", default=_user_id_default(), help="User or tenant identifier for memory retrieval.")
    patch_parser.add_argument("--split", default="unseen", help="Case split to evaluate.")
    patch_parser.add_argument("--limit", type=int, default=0, help="Optional case limit.")
    patch_parser.add_argument("--top-k", type=int, default=12)
    patch_parser.add_argument("--temperature", type=float, default=0.1)
    patch_parser.add_argument("--num-ctx", type=int, default=None)
    patch_parser.add_argument("--raw-iterations", type=int, default=1)
    patch_parser.add_argument("--memla-iterations", type=int, default=3)
    patch_parser.add_argument("--raw-provider", default="", help="Optional provider override for the raw lane.")
    patch_parser.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    patch_parser.add_argument("--memla-provider", default="", help="Optional provider override for the Memla lane.")
    patch_parser.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    patch_parser.add_argument("--memla-c2a-policy-path", default="", help="Optional explicit C2A policy bank JSON path for the Memla lane.")
    patch_parser.add_argument("--disable-memla-c2a-policy", action="store_true", help="Disable self-transmutation priors for the Memla lane.")
    patch_parser.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    patch_parser.set_defaults(func=_handle_patch_benchmark)

    compile_parser = coding_sub.add_parser("benchmark-compile", help="Run the compile-loop coding benchmark.")
    compile_parser.add_argument("--cases", required=True, help="Plan eval case JSONL path.")
    compile_parser.add_argument("--repo-root", required=True, help="Repository root under test.")
    compile_parser.add_argument("--model", required=True, help="Model to benchmark.")
    compile_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to <repo>/.memla/memory.sqlite.")
    compile_parser.add_argument("--user-id", default=_user_id_default(), help="User or tenant identifier for memory retrieval.")
    compile_parser.add_argument("--temperature", type=float, default=0.1)
    compile_parser.add_argument("--top-k", type=int, default=12)
    compile_parser.add_argument("--num-ctx", type=int, default=None)
    compile_parser.add_argument("--memla-c2a-policy-path", default="", help="Optional explicit C2A policy bank JSON path for the planning and compile lanes.")
    compile_parser.add_argument("--disable-memla-c2a-policy", action="store_true", help="Disable self-transmutation priors for the planning and compile lanes.")
    compile_parser.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    compile_parser.set_defaults(func=_handle_compile_benchmark)

    c2a_parser = coding_sub.add_parser("benchmark-c2a", help="Run a pure next-move coding C2A benchmark.")
    c2a_parser.add_argument("--cases", required=True, help="Coding C2A case JSONL path.")
    c2a_parser.add_argument("--repo-root", required=True, help="Repository root under test.")
    c2a_parser.add_argument("--raw-model", required=True, help="Baseline raw model.")
    c2a_parser.add_argument("--memla-model", required=True, help="Memla-assisted planning model.")
    c2a_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to <repo>/.memla/memory.sqlite.")
    c2a_parser.add_argument("--user-id", default=_user_id_default(), help="User or tenant identifier for memory retrieval.")
    c2a_parser.add_argument("--temperature", type=float, default=0.1)
    c2a_parser.add_argument("--top-k", type=int, default=12)
    c2a_parser.add_argument("--num-ctx", type=int, default=None)
    c2a_parser.add_argument("--raw-provider", default="", help="Optional provider override for the raw lane.")
    c2a_parser.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    c2a_parser.add_argument("--memla-provider", default="", help="Optional provider override for the Memla lane.")
    c2a_parser.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    c2a_parser.add_argument("--memla-c2a-policy-path", default="", help="Optional explicit C2A policy bank JSON path for the Memla lane.")
    c2a_parser.add_argument("--disable-memla-c2a-policy", action="store_true", help="Disable self-transmutation priors for the Memla lane.")
    c2a_parser.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    c2a_parser.set_defaults(func=_handle_c2a_benchmark)

    extract_parser = coding_sub.add_parser("extract-c2a", help="Extract normalized teacher-vs-Memla rows from coding C2A benchmark reports.")
    extract_parser.add_argument(
        "--report",
        action="append",
        required=True,
        help="Path to a coding_c2a_benchmark_report.json file. Repeat for multiple reports.",
    )
    extract_parser.add_argument(
        "--min-delta",
        type=float,
        default=None,
        help="Optional minimum Memla-minus-raw utility delta required to keep a row.",
    )
    extract_parser.add_argument("--out-dir", default="", help="Directory for extracted trace-bank artifacts. Defaults to ./memla_reports/<timestamp>.")
    extract_parser.add_argument("--json", action="store_true", help="Print the extraction summary as JSON.")
    extract_parser.set_defaults(func=_handle_extract_c2a)

    distill_parser = coding_sub.add_parser("distill-c2a", help="Distill a self-transmutation policy bank from an extracted C2A trace bank.")
    distill_parser.add_argument("--trace-bank", required=True, help="Path to a c2a_trace_bank summary JSON or JSONL file.")
    distill_parser.add_argument("--repo-root", default=".", help="Repository root where the policy bank should live. Defaults to the current directory.")
    distill_parser.add_argument("--out", default="", help="Optional explicit output JSON path. Defaults to <repo>/.memla/c2a_policy_bank.json.")
    distill_parser.add_argument(
        "--min-priority",
        default="medium",
        choices=["low", "medium", "high"],
        help="Minimum teaching priority a row must have to influence the distilled bank.",
    )
    distill_parser.add_argument("--json", action="store_true", help="Print the distillation summary as JSON.")
    distill_parser.set_defaults(func=_handle_distill_c2a)

    research_parser = subparsers.add_parser("research", help="Run bounded deep-research loop capture and benchmarks.")
    research_sub = research_parser.add_subparsers(dest="research_command")

    research_convert = research_sub.add_parser(
        "convert-capture",
        help="Convert captured deep-research loop events into normalized eval cases.",
    )
    research_convert.add_argument("--events", required=True, help="Path to captured research-loop events JSONL.")
    research_convert.add_argument("--out-cases", default="", help="Output JSONL path for normalized benchmark cases.")
    research_convert.add_argument("--min-iterations", type=int, default=1, help="Minimum iterations required to keep a captured session.")
    research_convert.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    research_convert.set_defaults(func=_handle_research_convert_capture)

    research_eval = research_sub.add_parser(
        "eval-harness",
        help="Run the customer-facing research replay harness and print a compact pass/fail summary.",
    )
    research_eval.add_argument("--input", required=True, help="JSONL of historical decision logs or normalized research eval cases.")
    research_eval.add_argument(
        "--normalize-capture",
        action="store_true",
        help="First convert raw per-step capture events into normalized session cases before replay.",
    )
    research_eval.add_argument("--min-iterations", type=int, default=1, help="Minimum iterations required when --normalize-capture is enabled.")
    research_eval.add_argument("--raw-model", default="", help="Optional explicit raw lane model. Defaults to the Memla model when omitted.")
    research_eval.add_argument("--memla-model", required=True, help="Memla-assisted small-model lane.")
    research_eval.add_argument("--frontier-model", default="", help="Frontier raw comparison lane. Optional when --frontier-use-logged-decisions is set.")
    research_eval.add_argument(
        "--frontier-use-logged-decisions",
        action="store_true",
        help="Use baseline frontier decisions already present in the input logs instead of querying a live frontier endpoint.",
    )
    research_eval.add_argument("--limit", type=int, default=0, help="Optional max number of decision cases to run.")
    research_eval.add_argument("--temperature", type=float, default=0.1)
    research_eval.add_argument("--num-ctx", type=int, default=None)
    research_eval.add_argument("--raw-provider", default="", help="Optional provider override for raw lane.")
    research_eval.add_argument("--raw-base-url", default="", help="Optional base URL override for raw lane.")
    research_eval.add_argument("--memla-provider", default="", help="Optional provider override for Memla lane.")
    research_eval.add_argument("--memla-base-url", default="", help="Optional base URL override for Memla lane.")
    research_eval.add_argument("--frontier-provider", default="", help="Optional provider override for frontier lane.")
    research_eval.add_argument("--frontier-base-url", default="", help="Optional base URL override for frontier lane.")
    research_eval.add_argument("--input-price-per-million", type=float, default=2.0, help="Estimated input-token price used for proxy accounting.")
    research_eval.add_argument("--output-price-per-million", type=float, default=8.0, help="Estimated output-token price used for proxy accounting.")
    research_eval.add_argument(
        "--acceptance-delta-pp",
        type=float,
        default=3.0,
        help="Pass/fail threshold for Memla false-converge delta versus the frontier baseline, in percentage points.",
    )
    _configure_research_pricing_profile_arg(research_eval)
    _configure_research_deployment_economics_args(research_eval, include_decisions_per_session=True)
    research_eval.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    research_eval.set_defaults(func=_handle_research_eval_harness)

    research_replay = research_sub.add_parser(
        "benchmark-replay",
        help="Benchmark replayed Phase-3 decisions across raw, Memla, and frontier lanes.",
    )
    research_replay.add_argument("--cases", required=True, help="Research loop eval case JSONL path.")
    research_replay.add_argument("--raw-model", required=True, help="Raw small-model lane.")
    research_replay.add_argument("--memla-model", required=True, help="Memla-assisted small-model lane.")
    research_replay.add_argument("--frontier-model", required=True, help="Frontier raw comparison lane.")
    research_replay.add_argument("--limit", type=int, default=0, help="Optional max number of decision cases to run.")
    research_replay.add_argument("--temperature", type=float, default=0.1)
    research_replay.add_argument("--num-ctx", type=int, default=None)
    research_replay.add_argument("--raw-provider", default="", help="Optional provider override for raw lane.")
    research_replay.add_argument("--raw-base-url", default="", help="Optional base URL override for raw lane.")
    research_replay.add_argument("--memla-provider", default="", help="Optional provider override for Memla lane.")
    research_replay.add_argument("--memla-base-url", default="", help="Optional base URL override for Memla lane.")
    research_replay.add_argument("--frontier-provider", default="", help="Optional provider override for frontier lane.")
    research_replay.add_argument("--frontier-base-url", default="", help="Optional base URL override for frontier lane.")
    research_replay.add_argument("--input-price-per-million", type=float, default=2.0, help="Estimated input-token price used for ROI accounting.")
    research_replay.add_argument("--output-price-per-million", type=float, default=8.0, help="Estimated output-token price used for ROI accounting.")
    research_replay.add_argument(
        "--frontier-use-logged-decisions",
        action="store_true",
        help="Use baseline frontier decisions already present in the input logs instead of querying a live frontier endpoint.",
    )
    _configure_research_pricing_profile_arg(research_replay)
    _configure_research_deployment_economics_args(research_replay, include_decisions_per_session=True)
    research_replay.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    research_replay.set_defaults(func=_handle_research_benchmark_replay)

    research_live = research_sub.add_parser(
        "benchmark-live-shadow",
        help="Benchmark sequential loop decisions over captured sessions in a live-shadow rollout style.",
    )
    research_live.add_argument("--cases", required=True, help="Research loop session JSONL path with loop_steps.")
    research_live.add_argument("--raw-model", required=True, help="Raw small-model lane.")
    research_live.add_argument("--memla-model", required=True, help="Memla-assisted small-model lane.")
    research_live.add_argument("--frontier-model", required=True, help="Frontier raw comparison lane.")
    research_live.add_argument("--limit", type=int, default=0, help="Optional max number of sessions to run.")
    research_live.add_argument("--max-iterations", type=int, default=8, help="Maximum loop decisions per session per lane.")
    research_live.add_argument("--temperature", type=float, default=0.1)
    research_live.add_argument("--num-ctx", type=int, default=None)
    research_live.add_argument("--raw-provider", default="", help="Optional provider override for raw lane.")
    research_live.add_argument("--raw-base-url", default="", help="Optional base URL override for raw lane.")
    research_live.add_argument("--memla-provider", default="", help="Optional provider override for Memla lane.")
    research_live.add_argument("--memla-base-url", default="", help="Optional base URL override for Memla lane.")
    research_live.add_argument("--frontier-provider", default="", help="Optional provider override for frontier lane.")
    research_live.add_argument("--frontier-base-url", default="", help="Optional base URL override for frontier lane.")
    research_live.add_argument("--input-price-per-million", type=float, default=2.0, help="Estimated input-token price used for ROI accounting.")
    research_live.add_argument("--output-price-per-million", type=float, default=8.0, help="Estimated output-token price used for ROI accounting.")
    _configure_research_deployment_economics_args(research_live)
    research_live.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    research_live.set_defaults(func=_handle_research_benchmark_live_shadow)

    math_parser = subparsers.add_parser("math", help="Run bounded math teacher-student benchmarks.")
    math_sub = math_parser.add_subparsers(dest="math_command")
    math_bench = math_sub.add_parser("benchmark", help="Run a math C2A benchmark.")
    math_bench.add_argument("--cases", required=True, help="Math case JSONL path.")
    math_bench.add_argument("--teacher-model", required=True, help="Teacher model for trace capture or labeling.")
    math_bench.add_argument(
        "--student-models",
        nargs="+",
        required=True,
        help="One or more student models to benchmark.",
    )
    math_bench.add_argument("--temperature", type=float, default=0.1)
    math_bench.add_argument("--num-ctx", type=int, default=None)
    math_bench.add_argument("--max-iterations", type=int, default=3)
    math_bench.add_argument("--top-k", type=int, default=3)
    math_bench.add_argument(
        "--executor-mode",
        default="oneshot",
        choices=["oneshot", "stepwise", "stepwise_select", "stepwise_rerank"],
        help="Math executor mode to evaluate.",
    )
    math_bench.add_argument(
        "--teacher-trace-source",
        default="llm",
        choices=["llm", "sympy", "hybrid"],
        help="Source for teacher traces.",
    )
    math_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    math_bench.set_defaults(func=_handle_math_benchmark)

    finance_parser = subparsers.add_parser("finance", help="Run finance compliance backtests and benchmarks.")
    finance_sub = finance_parser.add_subparsers(dest="finance_command")
    finance_bench = finance_sub.add_parser("benchmark-pretrade", help="Run a pre-trade compliance replay benchmark.")
    finance_bench.add_argument("--cases", required=True, help="Finance pre-trade case JSONL path.")
    finance_bench.add_argument("--repo-root", default=".", help="Repository root used for local finance policy banks.")
    finance_bench.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to run only specific finance cases.")
    finance_bench.add_argument("--limit", type=int, default=None, help="Optional max number of finance cases to run after filtering.")
    finance_bench.add_argument("--raw-model", required=True, help="Baseline raw model.")
    finance_bench.add_argument("--memla-model", required=True, help="Memla repair-loop model.")
    finance_bench.add_argument("--raw-iterations", type=int, default=1, help="How many attempts the raw lane gets.")
    finance_bench.add_argument("--memla-iterations", type=int, default=3, help="How many verifier-backed repair attempts the Memla lane gets.")
    finance_bench.add_argument("--temperature", type=float, default=0.1)
    finance_bench.add_argument("--num-ctx", type=int, default=None)
    finance_bench.add_argument("--raw-provider", default="", help="Optional provider override for the raw lane.")
    finance_bench.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    finance_bench.add_argument("--memla-provider", default="", help="Optional provider override for the Memla lane.")
    finance_bench.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    finance_bench.add_argument("--memla-finance-policy-path", default="", help="Optional explicit finance policy bank JSON path for the Memla lane.")
    finance_bench.add_argument("--disable-memla-finance-policy", action="store_true", help="Disable finance self-transmutation priors for the Memla lane.")
    finance_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    finance_bench.set_defaults(func=_handle_finance_pretrade_benchmark)

    finance_extract = finance_sub.add_parser("extract-pretrade", help="Extract normalized teacher-vs-Memla rows from finance pre-trade benchmark reports.")
    finance_extract.add_argument(
        "--report",
        action="append",
        required=True,
        help="Path to a finance_pretrade_benchmark_report.json file. Repeat for multiple reports.",
    )
    finance_extract.add_argument(
        "--min-delta",
        type=float,
        default=None,
        help="Optional minimum Memla-minus-raw utility delta required to keep a row.",
    )
    finance_extract.add_argument("--out-dir", default="", help="Directory for extracted finance trace-bank artifacts. Defaults to ./memla_reports/<timestamp>.")
    finance_extract.add_argument("--json", action="store_true", help="Print the extraction summary as JSON.")
    finance_extract.set_defaults(func=_handle_extract_finance_pretrade)

    finance_distill = finance_sub.add_parser("distill-pretrade", help="Distill a finance self-transmutation policy bank from extracted finance traces.")
    finance_distill.add_argument("--trace-bank", required=True, help="Path to a finance trace-bank summary JSON or JSONL file.")
    finance_distill.add_argument("--repo-root", default=".", help="Repository root where the finance policy bank should live. Defaults to the current directory.")
    finance_distill.add_argument("--out", default="", help="Optional explicit output JSON path. Defaults to <repo>/.memla/finance_policy_bank.json.")
    finance_distill.add_argument(
        "--min-priority",
        default="medium",
        choices=["low", "medium", "high"],
        help="Minimum teaching priority a row must have to influence the distilled finance bank.",
    )
    finance_distill.add_argument("--json", action="store_true", help="Print the distillation summary as JSON.")
    finance_distill.set_defaults(func=_handle_distill_finance_pretrade)

    healthcare_parser = subparsers.add_parser("healthcare", help="Run healthcare denial replay benchmarks.")
    healthcare_sub = healthcare_parser.add_subparsers(dest="healthcare_command")
    healthcare_bench = healthcare_sub.add_parser("benchmark-denials", help="Run a denied-claim replay benchmark.")
    healthcare_bench.add_argument("--cases", required=True, help="Healthcare denied-claim case JSONL path.")
    healthcare_bench.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to run only specific healthcare cases.")
    healthcare_bench.add_argument("--limit", type=int, default=None, help="Optional max number of healthcare cases to run after filtering.")
    healthcare_bench.add_argument("--raw-model", required=True, help="Baseline raw model.")
    healthcare_bench.add_argument("--memla-model", required=True, help="Memla repair-loop model.")
    healthcare_bench.add_argument("--raw-iterations", type=int, default=1, help="How many attempts the raw lane gets.")
    healthcare_bench.add_argument("--memla-iterations", type=int, default=3, help="How many verifier-backed repair attempts the Memla lane gets.")
    healthcare_bench.add_argument("--temperature", type=float, default=0.1)
    healthcare_bench.add_argument("--num-ctx", type=int, default=None)
    healthcare_bench.add_argument("--raw-provider", default="", help="Optional provider override for the raw lane.")
    healthcare_bench.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    healthcare_bench.add_argument("--memla-provider", default="", help="Optional provider override for the Memla lane.")
    healthcare_bench.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    healthcare_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    healthcare_bench.set_defaults(func=_handle_healthcare_denial_benchmark)

    policy_parser = subparsers.add_parser("policy", help="Run policy-as-code authorization benchmarks.")
    policy_sub = policy_parser.add_subparsers(dest="policy_command")
    policy_bench = policy_sub.add_parser("benchmark-authz", help="Run a bounded policy authorization replay benchmark.")
    policy_bench.add_argument("--cases", required=True, help="Policy authz case JSONL path.")
    policy_bench.add_argument("--repo-root", default=".", help="Repository root used for local policy banks.")
    policy_bench.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to run only specific policy cases.")
    policy_bench.add_argument("--limit", type=int, default=None, help="Optional max number of policy cases to run after filtering.")
    policy_bench.add_argument("--raw-model", required=True, help="Baseline raw model.")
    policy_bench.add_argument("--memla-model", required=True, help="Memla repair-loop model.")
    policy_bench.add_argument("--raw-iterations", type=int, default=1, help="How many attempts the raw lane gets.")
    policy_bench.add_argument("--memla-iterations", type=int, default=3, help="How many verifier-backed repair attempts the Memla lane gets.")
    policy_bench.add_argument("--temperature", type=float, default=0.1)
    policy_bench.add_argument("--num-ctx", type=int, default=None)
    policy_bench.add_argument("--raw-provider", default="", help="Optional provider override for the raw lane.")
    policy_bench.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    policy_bench.add_argument("--memla-provider", default="", help="Optional provider override for the Memla lane.")
    policy_bench.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    policy_bench.add_argument("--memla-policy-bank-path", default="", help="Optional explicit policy bank JSON path for the Memla lane.")
    policy_bench.add_argument("--disable-memla-policy-bank", action="store_true", help="Disable policy self-transmutation priors for the Memla lane.")
    policy_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    policy_bench.set_defaults(func=_handle_policy_authz_benchmark)

    policy_extract = policy_sub.add_parser("extract-authz", help="Extract normalized teacher-vs-Memla rows from policy authz benchmark reports.")
    policy_extract.add_argument(
        "--report",
        action="append",
        required=True,
        help="Path to a policy_authz_benchmark_report.json file. Repeat for multiple reports.",
    )
    policy_extract.add_argument(
        "--min-delta",
        type=float,
        default=None,
        help="Optional minimum Memla-minus-raw utility delta required to keep a row.",
    )
    policy_extract.add_argument("--out-dir", default="", help="Directory for extracted policy trace-bank artifacts. Defaults to ./memla_reports/<timestamp>.")
    policy_extract.add_argument("--json", action="store_true", help="Print the extraction summary as JSON.")
    policy_extract.set_defaults(func=_handle_extract_policy_authz)

    policy_distill = policy_sub.add_parser("distill-authz", help="Distill a policy self-transmutation bank from extracted policy traces.")
    policy_distill.add_argument("--trace-bank", required=True, help="Path to a policy trace-bank summary JSON or JSONL file.")
    policy_distill.add_argument("--repo-root", default=".", help="Repository root where the policy bank should live. Defaults to the current directory.")
    policy_distill.add_argument("--out", default="", help="Optional explicit output JSON path. Defaults to <repo>/.memla/policy_authz_policy_bank.json.")
    policy_distill.add_argument(
        "--min-priority",
        default="medium",
        choices=["low", "medium", "high"],
        help="Minimum teaching priority a row must have to influence the distilled policy bank.",
    )
    policy_distill.add_argument("--json", action="store_true", help="Print the distillation summary as JSON.")
    policy_distill.set_defaults(func=_handle_distill_policy_authz)

    serve_parser = subparsers.add_parser("serve", help="Serve Memla over HTTP for thin clients like iPhone or Shortcuts.")
    _configure_memla_serve_parser(serve_parser)

    scout_parser = subparsers.add_parser("scout", help="Run a bounded autonomous scout and bring a report back.")
    _configure_terminal_scout_parser(scout_parser)

    terminal_parser = subparsers.add_parser("terminal", help="Run a bounded natural-language terminal assistant.")
    terminal_sub = terminal_parser.add_subparsers(dest="terminal_command")
    terminal_plan = terminal_sub.add_parser("plan", help="Build a safe action plan from a natural-language terminal request.")
    terminal_plan.add_argument("--prompt", "-p", default="", help="Natural-language terminal request.")
    terminal_plan.add_argument("prompt_text", nargs="*", help="Prompt words if you want to skip --prompt.")
    terminal_plan.add_argument("--model", default=_terminal_model_default(), help="Fallback local model name. Defaults to a small Phi-3 tag.")
    terminal_plan.add_argument("--provider", default="ollama", help="Provider override for model fallback.")
    terminal_plan.add_argument("--base-url", default="", help="Optional base URL override for the terminal planner.")
    terminal_plan.add_argument("--temperature", type=float, default=0.1)
    terminal_plan.add_argument("--heuristic-only", action="store_true", help="Skip the model fallback and only use the built-in bounded parser.")
    terminal_plan.add_argument("--without-memla", action="store_true", help="Bypass Memla heuristics and use the raw model-only terminal planner.")
    terminal_plan.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    terminal_plan.set_defaults(func=_handle_terminal_plan)

    terminal_run = terminal_sub.add_parser("run", help="Execute a safe bounded natural-language terminal request.")
    terminal_run.add_argument("--prompt", "-p", default="", help="Natural-language terminal request.")
    terminal_run.add_argument("prompt_text", nargs="*", help="Prompt words if you want to skip --prompt.")
    terminal_run.add_argument("--model", default=_terminal_model_default(), help="Fallback local model name. Defaults to a small Phi-3 tag.")
    terminal_run.add_argument("--provider", default="ollama", help="Provider override for model fallback.")
    terminal_run.add_argument("--base-url", default="", help="Optional base URL override for the terminal planner.")
    terminal_run.add_argument("--temperature", type=float, default=0.1)
    terminal_run.add_argument("--heuristic-only", action="store_true", help="Skip the model fallback and only use the built-in bounded parser.")
    terminal_run.add_argument("--without-memla", action="store_true", help="Bypass Memla heuristics and use the raw model-only terminal planner.")
    terminal_run.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    terminal_run.set_defaults(func=_handle_terminal_run)

    terminal_scout = terminal_sub.add_parser("scout", help="Run a bounded autonomous GitHub scout and return a report.")
    _configure_terminal_scout_parser(terminal_scout)

    terminal_step = terminal_sub.add_parser("step", help="Inspect candidate terminal/browser transmutations and optionally execute one.")
    terminal_step.add_argument("--prompt", "-p", default="", help="Natural-language terminal request.")
    terminal_step.add_argument("prompt_text", nargs="*", help="Prompt words if you want to skip --prompt.")
    terminal_step.add_argument("--model", default=_terminal_model_default(), help="Fallback local model name. Defaults to a small Phi-3 tag.")
    terminal_step.add_argument("--provider", default="ollama", help="Provider override for model fallback.")
    terminal_step.add_argument("--base-url", default="", help="Optional base URL override for the terminal planner.")
    terminal_step.add_argument("--temperature", type=float, default=0.1)
    terminal_step.add_argument("--heuristic-only", action="store_true", help="Skip the model fallback and only use the built-in bounded parser.")
    terminal_step.add_argument("--choice", default="", help="Candidate number or candidate id to execute and log.")
    terminal_step.add_argument("--trace-log", default="", help="Optional JSONL path for approved transmutation traces.")
    terminal_step.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    terminal_step.set_defaults(func=_handle_terminal_step)

    terminal_workbench = terminal_sub.add_parser("workbench", help="Launch a local browser workbench UI for approving transmutations.")
    terminal_workbench.add_argument("--host", default="127.0.0.1", help="Host interface for the local UI server.")
    terminal_workbench.add_argument("--port", type=int, default=8766, help="Port for the local UI server.")
    terminal_workbench.add_argument("--model", default=_terminal_model_default(), help="Fallback local model name for proposal generation.")
    terminal_workbench.add_argument("--provider", default="ollama", help="Provider override for the workbench fallback model.")
    terminal_workbench.add_argument("--base-url", default="", help="Optional base URL override for the workbench fallback model.")
    terminal_workbench.add_argument("--temperature", type=float, default=0.1)
    terminal_workbench.add_argument("--heuristic-only", action="store_true", help="Start the workbench in heuristic-only mode by default.")
    terminal_workbench.add_argument("--trace-log", default="", help="Optional JSONL path for approved transmutation traces.")
    terminal_workbench.set_defaults(func=_handle_terminal_workbench)

    terminal_serve = terminal_sub.add_parser("serve", help="Serve the Memla HTTP API for thin clients like iPhone or Shortcuts.")
    _configure_memla_serve_parser(terminal_serve)

    terminal_compare = terminal_sub.add_parser("compare", help="Compare a raw small-model terminal plan against Memla on the same prompt.")
    terminal_compare.add_argument("--prompt", "-p", default="", help="Natural-language terminal request.")
    terminal_compare.add_argument("prompt_text", nargs="*", help="Prompt words if you want to skip --prompt.")
    terminal_compare.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_compare.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_compare.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_compare.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_compare.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_compare.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_compare.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_compare.add_argument("--temperature", type=float, default=0.1)
    terminal_compare.add_argument("--heuristic-only", action="store_true", help="Keep the Memla lane heuristic-first. Raw still uses the model directly.")
    terminal_compare.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    terminal_compare.set_defaults(func=_handle_terminal_compare)

    terminal_bench = terminal_sub.add_parser("benchmark", help="Benchmark raw terminal planning latency versus Memla on a bundled prompt pack.")
    terminal_bench.add_argument("--cases", default=_terminal_cases_default(), help="Terminal benchmark case JSONL path.")
    terminal_bench.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_bench.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_bench.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_bench.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_bench.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_bench.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_bench.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_bench.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_bench.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_bench.add_argument("--temperature", type=float, default=0.1)
    terminal_bench.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_bench.set_defaults(func=_handle_terminal_benchmark)

    terminal_web_bench_v1 = terminal_sub.add_parser(
        "benchmark-web-v1",
        help="Benchmark raw-vs-Memla bounded web-question planning on the Web V1 prompt pack.",
    )
    terminal_web_bench_v1.add_argument("--cases", default=_web_v1_cases_default(), help="Web V1 benchmark case JSONL path.")
    terminal_web_bench_v1.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_web_bench_v1.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_web_bench_v1.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_web_bench_v1.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_web_bench_v1.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_web_bench_v1.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_web_bench_v1.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_web_bench_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_web_bench_v1.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_web_bench_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_web_bench_v1.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_web_bench_v1.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_web_bench_v1.set_defaults(func=_handle_terminal_benchmark)

    terminal_web_answer_bench_v1 = terminal_sub.add_parser(
        "benchmark-web-answer-v1",
        help="Benchmark Memla's returned web answers, source handoffs, and optional teacher grading on the Web V1 pack.",
    )
    terminal_web_answer_bench_v1.add_argument("--cases", default=_web_v1_cases_default(), help="Web V1 benchmark case JSONL path.")
    terminal_web_answer_bench_v1.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_web_answer_bench_v1.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_web_answer_bench_v1.add_argument("--model", default="", help="Shared model default for the Memla answer lane.")
    terminal_web_answer_bench_v1.add_argument("--memla-model", default="", help="Memla answer model. Defaults to --model or the small terminal default.")
    terminal_web_answer_bench_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla answer lane.")
    terminal_web_answer_bench_v1.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla answer lane.")
    terminal_web_answer_bench_v1.add_argument("--judge-model", default="", help="Optional teacher/judge model for grading answer quality and voice.")
    terminal_web_answer_bench_v1.add_argument("--judge-provider", default="", help="Optional provider override for the teacher lane. Defaults to the Memla lane when blank.")
    terminal_web_answer_bench_v1.add_argument("--judge-base-url", default="", help="Optional base URL override for the teacher lane.")
    terminal_web_answer_bench_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_web_answer_bench_v1.add_argument("--heuristic-only", action="store_true", help="Force the Memla planner to stay heuristic-only before answering.")
    terminal_web_answer_bench_v1.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_web_answer_bench_v1.set_defaults(func=_handle_web_answer_benchmark)

    terminal_web_teacher_v1 = terminal_sub.add_parser(
        "benchmark-web-teacher-v1",
        help="Run Memla web answers through a teacher rescue loop and write a reusable web trace bank.",
    )
    terminal_web_teacher_v1.add_argument("--cases", default=_web_v1_cases_default(), help="Web V1 benchmark case JSONL path.")
    terminal_web_teacher_v1.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_web_teacher_v1.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_web_teacher_v1.add_argument("--model", default="", help="Shared model default for the Memla and teacher lanes.")
    terminal_web_teacher_v1.add_argument("--memla-model", default="", help="Memla answer model. Defaults to --model or the small terminal default.")
    terminal_web_teacher_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla answer lane.")
    terminal_web_teacher_v1.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla answer lane.")
    terminal_web_teacher_v1.add_argument("--teacher-model", default="", help="Teacher rescue model. Defaults to --model or the Memla model.")
    terminal_web_teacher_v1.add_argument("--teacher-provider", default="", help="Optional provider override for the teacher lane. Defaults to the Memla lane when blank.")
    terminal_web_teacher_v1.add_argument("--teacher-base-url", default="", help="Optional base URL override for the teacher lane.")
    terminal_web_teacher_v1.add_argument("--judge-model", default="", help="Optional judge model. Defaults to the teacher model when blank.")
    terminal_web_teacher_v1.add_argument("--judge-provider", default="", help="Optional provider override for the judge lane.")
    terminal_web_teacher_v1.add_argument("--judge-base-url", default="", help="Optional base URL override for the judge lane.")
    terminal_web_teacher_v1.add_argument("--rescue-threshold", type=int, default=4, help="Teacher overall score below this threshold triggers rescue.")
    terminal_web_teacher_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_web_teacher_v1.add_argument("--heuristic-only", action="store_true", help="Force the Memla planner to stay heuristic-only before answering.")
    terminal_web_teacher_v1.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_web_teacher_v1.set_defaults(func=_handle_web_teacher_loop)

    terminal_web_policy_v1 = terminal_sub.add_parser(
        "distill-web-policy-v1",
        help="Distill a reusable web answer policy bank from a web teacher trace bank.",
    )
    terminal_web_policy_v1.add_argument("--trace-bank", required=True, help="Path to a web_teacher_trace_bank JSONL or report JSON file.")
    terminal_web_policy_v1.add_argument("--min-improvement", type=float, default=0.0, help="Only keep rescue rows at or above this improvement delta.")
    terminal_web_policy_v1.add_argument("--out", default="", help="Optional explicit output JSON path. Defaults to <repo>/.memla/web_policy_bank.json.")
    terminal_web_policy_v1.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    terminal_web_policy_v1.set_defaults(func=_handle_distill_web_policy)

    terminal_web_overnight_v1 = terminal_sub.add_parser(
        "train-web-overnight-v1",
        help="Generate an everyday web-question pack, run teacher-rescue rounds, distill policy, and benchmark until the score target or plateau.",
    )
    terminal_web_overnight_v1.add_argument("--seed-cases", default=_web_v1_cases_default(), help="Seed Web benchmark case JSONL path.")
    terminal_web_overnight_v1.add_argument("--question-count", type=int, default=60, help="Total everyday web questions to train against.")
    terminal_web_overnight_v1.add_argument("--model", default="", help="Shared model default for the Memla and teacher lanes.")
    terminal_web_overnight_v1.add_argument("--memla-model", default="", help="Memla answer model. Defaults to --model or the small terminal default.")
    terminal_web_overnight_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla answer lane.")
    terminal_web_overnight_v1.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla answer lane.")
    terminal_web_overnight_v1.add_argument("--teacher-model", default="", help="Teacher rescue/generation model. Defaults to --model or the Memla model.")
    terminal_web_overnight_v1.add_argument("--teacher-provider", default="", help="Optional provider override for the teacher lane. Defaults to the Memla lane when blank.")
    terminal_web_overnight_v1.add_argument("--teacher-base-url", default="", help="Optional base URL override for the teacher lane.")
    terminal_web_overnight_v1.add_argument("--judge-model", default="", help="Optional judge model. Defaults to the teacher model when blank.")
    terminal_web_overnight_v1.add_argument("--judge-provider", default="", help="Optional provider override for the judge lane.")
    terminal_web_overnight_v1.add_argument("--judge-base-url", default="", help="Optional base URL override for the judge lane.")
    terminal_web_overnight_v1.add_argument("--max-rounds", type=int, default=4, help="Maximum teacher/distillation rounds to run.")
    terminal_web_overnight_v1.add_argument("--benchmark-every", type=int, default=1, help="Run the answer benchmark every N rounds.")
    terminal_web_overnight_v1.add_argument("--target-overall", type=float, default=4.25, help="Stop once the Claude-judged average overall score reaches this target.")
    terminal_web_overnight_v1.add_argument("--target-hard-pass-rate", type=float, default=0.0, help="Optional hard factual pass-rate target for narrow slices like creator/age questions.")
    terminal_web_overnight_v1.add_argument("--allowed-rescues", type=int, default=2, help="Allow at most this many promoted teacher rescues on the final successful round.")
    terminal_web_overnight_v1.add_argument("--patience", type=int, default=2, help="Stop after this many rounds without meaningful improvement.")
    terminal_web_overnight_v1.add_argument("--min-delta", type=float, default=0.05, help="Minimum benchmark improvement that counts as progress.")
    terminal_web_overnight_v1.add_argument("--rescue-threshold", type=int, default=4, help="Teacher overall score below this threshold triggers rescue.")
    terminal_web_overnight_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_web_overnight_v1.add_argument("--heuristic-only", action="store_true", help="Force the Memla planner to stay heuristic-only before answering.")
    terminal_web_overnight_v1.add_argument("--repo-root", default=".", help="Repo root used for writing .memla/web_policy_bank.json.")
    terminal_web_overnight_v1.add_argument("--out-dir", default="", help="Directory for overnight-loop artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_web_overnight_v1.set_defaults(func=_handle_web_overnight_loop)

    terminal_browser_bench = terminal_sub.add_parser(
        "benchmark-browser",
        help="Benchmark raw-vs-Memla browser planning and backtesting on the locked Browser Ontology V1 pack.",
    )
    terminal_browser_bench.add_argument("--cases", default=_browser_cases_default(), help="Browser benchmark case JSONL path.")
    terminal_browser_bench.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v1")

    terminal_browser_bench_v2 = terminal_sub.add_parser(
        "benchmark-browser-v2",
        help="Benchmark raw-vs-Memla ranking/comparison on Browser Ontology V2.",
    )
    terminal_browser_bench_v2.add_argument("--cases", default=_browser_v2_cases_default(), help="Browser Ontology V2 benchmark case JSONL path.")
    terminal_browser_bench_v2.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v2.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v2.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v2.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v2.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v2.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v2.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v2.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v2.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v2.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v2.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v2.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v2.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v2")

    terminal_browser_bench_v3 = terminal_sub.add_parser(
        "benchmark-browser-v3",
        help="Benchmark raw-vs-Memla multi-step research handoffs on Browser Ontology V3.",
    )
    terminal_browser_bench_v3.add_argument("--cases", default=_browser_v3_cases_default(), help="Browser Ontology V3 benchmark case JSONL path.")
    terminal_browser_bench_v3.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v3.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v3.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v3.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v3.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v3.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v3.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v3.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v3.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v3.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v3.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v3.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v3.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v3")

    terminal_browser_bench_v4 = terminal_sub.add_parser(
        "benchmark-browser-v4",
        help="Benchmark raw-vs-Memla research chains that search a second site and open the best result on Browser Ontology V4.",
    )
    terminal_browser_bench_v4.add_argument("--cases", default=_browser_v4_cases_default(), help="Browser Ontology V4 benchmark case JSONL path.")
    terminal_browser_bench_v4.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v4.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v4.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v4.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v4.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v4.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v4.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v4.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v4.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v4.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v4.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v4.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v4.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v4")

    terminal_browser_bench_v5 = terminal_sub.add_parser(
        "benchmark-browser-v5",
        help="Benchmark raw-vs-Memla research chains that open and then read the follow-on result on Browser Ontology V5.",
    )
    terminal_browser_bench_v5.add_argument("--cases", default=_browser_v5_cases_default(), help="Browser Ontology V5 benchmark case JSONL path.")
    terminal_browser_bench_v5.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v5.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v5.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v5.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v5.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v5.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v5.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v5.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v5.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v5.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v5.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v5.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v5.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v5")

    terminal_browser_bench_v6 = terminal_sub.add_parser(
        "benchmark-browser-v6",
        help="Benchmark raw-vs-Memla multi-hop research chains that carry the same subject across YouTube and Reddit on Browser Ontology V6.",
    )
    terminal_browser_bench_v6.add_argument("--cases", default=_browser_v6_cases_default(), help="Browser Ontology V6 benchmark case JSONL path.")
    terminal_browser_bench_v6.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v6.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v6.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v6.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v6.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v6.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v6.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v6.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v6.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v6.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v6.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v6.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v6.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v6")

    terminal_browser_bench_v7 = terminal_sub.add_parser(
        "benchmark-browser-v7",
        help="Benchmark raw-vs-Memla bounded recovery chains that reopen a stronger follow-on result when the first one is weak on Browser Ontology V7.",
    )
    terminal_browser_bench_v7.add_argument("--cases", default=_browser_v7_cases_default(), help="Browser Ontology V7 benchmark case JSONL path.")
    terminal_browser_bench_v7.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v7.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v7.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v7.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v7.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v7.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v7.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v7.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v7.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v7.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v7.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v7.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v7.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v7")

    terminal_browser_bench_v8 = terminal_sub.add_parser(
        "benchmark-browser-v8",
        help="Benchmark raw-vs-Memla bounded cross-source synthesis chains on Browser Ontology V8.",
    )
    terminal_browser_bench_v8.add_argument("--cases", default=_browser_v8_cases_default(), help="Browser Ontology V8 benchmark case JSONL path.")
    terminal_browser_bench_v8.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_browser_bench_v8.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_browser_bench_v8.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_browser_bench_v8.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v8.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_browser_bench_v8.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_browser_bench_v8.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_browser_bench_v8.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_browser_bench_v8.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_browser_bench_v8.add_argument("--temperature", type=float, default=0.1)
    terminal_browser_bench_v8.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_browser_bench_v8.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_browser_bench_v8.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="browser_v8")

    terminal_language_bench_v1 = terminal_sub.add_parser(
        "benchmark-language-v1",
        help="Benchmark paraphrase robustness on Language Ontology V1 over the locked browser runtime.",
    )
    terminal_language_bench_v1.add_argument("--cases", default=_language_v1_cases_default(), help="Language Ontology V1 benchmark case JSONL path.")
    terminal_language_bench_v1.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_language_bench_v1.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_language_bench_v1.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_language_bench_v1.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v1.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v1.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_language_bench_v1.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_language_bench_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_language_bench_v1.add_argument("--memla-base-url", default="", help="Optional base URL override for the Memla lane.")
    terminal_language_bench_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_language_bench_v1.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_language_bench_v1.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_language_bench_v1.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="language_v1")

    terminal_language_bench_v2 = terminal_sub.add_parser(
        "benchmark-language-v2",
        help="Benchmark Language Ontology V2 with LLM language compilation above the locked browser runtime.",
    )
    terminal_language_bench_v2.add_argument("--cases", default=_language_v2_cases_default(), help="Language Ontology V2 benchmark case JSONL path.")
    terminal_language_bench_v2.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_language_bench_v2.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_language_bench_v2.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_language_bench_v2.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v2.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v2.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_language_bench_v2.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_language_bench_v2.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_language_bench_v2.add_argument("--memla-base-url", dest="memla_base_url", default="", help="Optional base URL override for the Memla lane.")
    terminal_language_bench_v2.add_argument("--temperature", type=float, default=0.1)
    terminal_language_bench_v2.add_argument("--heuristic-only", action="store_true", help="Force the Memla lane to stay heuristic-only.")
    terminal_language_bench_v2.add_argument("--out-dir", default="", help="Directory for report artifacts. Defaults to ./memla_reports/<timestamp>.")
    terminal_language_bench_v2.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="language_v2")

    terminal_language_bench_v3 = terminal_sub.add_parser(
        "benchmark-language-v3",
        help="Benchmark Language Ontology V3 as a cold-vs-warm learning loop over the locked browser runtime.",
    )
    terminal_language_bench_v3.add_argument("--cases", default=_language_v3_cases_default(), help="Language Ontology V3 benchmark case JSONL path.")
    terminal_language_bench_v3.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_language_bench_v3.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_language_bench_v3.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_language_bench_v3.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v3.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v3.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_language_bench_v3.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_language_bench_v3.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_language_bench_v3.add_argument("--memla-base-url", dest="memla_base_url", default="", help="Optional base URL override for the Memla lane.")
    terminal_language_bench_v3.add_argument("--temperature", type=float, default=0.1)
    terminal_language_bench_v3.add_argument("--out-dir", default="", help="Directory for report artifacts and temporary language memory. Defaults to ./memla_reports/<timestamp>.")
    terminal_language_bench_v3.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="language_v3")

    terminal_language_bench_v4 = terminal_sub.add_parser(
        "benchmark-language-v4",
        help="Benchmark Language Ontology V4 as compiler -> memory -> promoted rule coverage.",
    )
    terminal_language_bench_v4.add_argument("--cases", default=_language_v4_cases_default(), help="Language Ontology V4 benchmark case JSONL path.")
    terminal_language_bench_v4.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_language_bench_v4.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_language_bench_v4.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_language_bench_v4.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v4.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_language_bench_v4.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_language_bench_v4.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_language_bench_v4.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_language_bench_v4.add_argument("--memla-base-url", dest="memla_base_url", default="", help="Optional base URL override for the Memla lane.")
    terminal_language_bench_v4.add_argument("--temperature", type=float, default=0.1)
    terminal_language_bench_v4.add_argument("--out-dir", default="", help="Directory for report artifacts and temporary language memory/rules. Defaults to ./memla_reports/<timestamp>.")
    terminal_language_bench_v4.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="language_v4")

    terminal_memory_bench_v1 = terminal_sub.add_parser(
        "benchmark-memory-v1",
        help="Benchmark Memory Ontology V1 as episodic -> semantic -> rule lifecycle transitions over the language stack.",
    )
    terminal_memory_bench_v1.add_argument("--cases", default=_memory_v1_cases_default(), help="Memory Ontology V1 benchmark case JSONL path.")
    terminal_memory_bench_v1.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to benchmark only specific prompts.")
    terminal_memory_bench_v1.add_argument("--limit", type=int, default=None, help="Optional max number of benchmark prompts to run after filtering.")
    terminal_memory_bench_v1.add_argument("--model", default="", help="Shared model for both lanes.")
    terminal_memory_bench_v1.add_argument("--raw-model", default="", help="Raw baseline model. Defaults to --model or the small terminal default.")
    terminal_memory_bench_v1.add_argument("--memla-model", default="", help="Memla model. Defaults to --model or the small terminal default.")
    terminal_memory_bench_v1.add_argument("--raw-provider", default="ollama", help="Provider override for the raw lane.")
    terminal_memory_bench_v1.add_argument("--raw-base-url", default="", help="Optional base URL override for the raw lane.")
    terminal_memory_bench_v1.add_argument("--memla-provider", default="ollama", help="Provider override for the Memla lane.")
    terminal_memory_bench_v1.add_argument("--memla-base-url", dest="memla_base_url", default="", help="Optional base URL override for the Memla lane.")
    terminal_memory_bench_v1.add_argument("--temperature", type=float, default=0.1)
    terminal_memory_bench_v1.add_argument("--out-dir", default="", help="Directory for report artifacts and temporary memory ontology state. Defaults to ./memla_reports/<timestamp>.")
    terminal_memory_bench_v1.set_defaults(func=_handle_terminal_browser_benchmark, ontology_version="memory_v1")

    pack_parser = subparsers.add_parser("pack", help="Build Memla proof and buyer packs.")
    pack_sub = pack_parser.add_subparsers(dest="pack_command")
    thesis_parser = pack_sub.add_parser("thesis", help="Build the current thesis proof pack.")
    thesis_parser.add_argument("--coding", required=True, help="Primary coding report JSON.")
    thesis_parser.add_argument("--math-rerank", required=True, help="Math reranker report JSON.")
    thesis_parser.add_argument("--math-progress", required=True, help="Math end-to-end report JSON.")
    thesis_parser.add_argument("--coding-secondary", default="", help="Optional second coding repo-family report JSON.")
    thesis_parser.add_argument("--compile-support", default="", help="Optional compile-loop support report JSON.")
    thesis_parser.add_argument("--out-dir", default="", help="Output directory. Defaults to ./memla_reports/<timestamp>.")
    thesis_parser.add_argument("--site-url", default="https://memla.vercel.app", help="Site URL embedded in the pack.")
    thesis_parser.set_defaults(func=_handle_thesis_pack)

    publish_site_parser = pack_sub.add_parser("publish-site", help="Publish a proof pack as a Vercel-ready static site directory.")
    publish_site_parser.add_argument("--source", default="proof/current_pack", help="Source pack directory to publish.")
    publish_site_parser.add_argument("--out-dir", default=".", help="Output directory for the static site.")
    publish_site_parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    publish_site_parser.set_defaults(func=_handle_publish_site)

    doctor_parser = subparsers.add_parser("doctor", help="Check Python, repo, Ollama, and site readiness.")
    doctor_parser.add_argument("--repo-root", default=".", help="Repository root to inspect.")
    doctor_parser.add_argument("--db", default="", help="SQLite path for Memla memory. Defaults to <repo>/.memla/memory.sqlite.")
    doctor_parser.add_argument("--model", default=_coding_model_default(), help="Model to look for in Ollama.")
    doctor_parser.add_argument("--ollama-url", default="", help="Optional Ollama base URL override.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit structured JSON instead of readable text.")
    doctor_parser.set_defaults(func=_handle_doctor)

    return parser


def _top_level_subcommand_names(parser: argparse.ArgumentParser) -> set[str]:
    for action in getattr(parser, "_actions", []):
        choices = getattr(action, "choices", None)
        if isinstance(choices, dict):
            return {str(name) for name in choices}
    return set()


def _rewrite_bare_terminal_argv(parser: argparse.ArgumentParser, argv: list[str] | None) -> list[str]:
    argv_list = list(sys.argv[1:] if argv is None else argv)
    if not argv_list:
        return argv_list
    first = str(argv_list[0]).strip()
    if not first or first.startswith("-"):
        return argv_list
    if first in _top_level_subcommand_names(parser):
        return argv_list
    prompt_parts: list[str] = []
    option_start = len(argv_list)
    for index, token in enumerate(argv_list):
        token_text = str(token).strip()
        if index > 0 and token_text.startswith("-"):
            option_start = index
            break
        if token_text:
            prompt_parts.append(token_text)
    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        return argv_list
    if _looks_like_terminal_scout_prompt(prompt):
        return ["terminal", "scout", "--prompt", prompt, *argv_list[option_start:]]
    return ["terminal", "run", "--prompt", prompt, *argv_list[option_start:]]


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(_rewrite_bare_terminal_argv(parser, argv))
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help(sys.stderr)
        return 2
    return int(func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
