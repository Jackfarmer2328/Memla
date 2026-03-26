from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Optional

from .coding_log import CodingTrace, CodingTraceLog
from ..memory.episode_log import EpisodeLog
from ..reasoning.trajectory import extract_output_text, has_trajectory_format


def trace_to_training_record(
    trace: CodingTrace,
    *,
    events: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    tests = trace.tests or []
    latest_test = tests[-1] if tests else {}
    reasoning_text = trace.assistant_text if has_trajectory_format(trace.assistant_text) else ""
    return {
        "trace_id": trace.id,
        "session_id": trace.session_id,
        "user_id": trace.user_id,
        "provider": trace.provider,
        "model": trace.model,
        "repo_root": trace.repo_root,
        "task_text": trace.task_text,
        "system_prompt": trace.system_prompt,
        "messages": trace.messages,
        "retrieved_chunk_ids": trace.retrieved_chunk_ids,
        "assistant_text": trace.assistant_text,
        "assistant_output": extract_output_text(trace.assistant_text),
        "reasoning_trace": reasoning_text,
        "touched_files": trace.touched_files,
        "patch_text": trace.patch_text,
        "tests": tests,
        "latest_test_status": latest_test.get("status", ""),
        "status": trace.status,
        "acceptance_score": trace.acceptance_score,
        "meta": trace.meta,
        "events": events or [],
    }


def export_accepted_traces_to_jsonl(
    *,
    db_path: str,
    out_path: str,
    user_id: str,
    repo_root: str = "",
    limit: int = 500,
) -> int:
    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        traces = coding_log.fetch_training_candidates(user_id=user_id, limit=limit)
        if repo_root:
            repo_root_resolved = str(Path(repo_root).resolve())
            traces = [trace for trace in traces if str(Path(trace.repo_root).resolve()) == repo_root_resolved]

        out_file = Path(out_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        count = 0
        with out_file.open("w", encoding="utf-8") as fh:
            for trace in traces:
                events = [
                    {
                        "event_type": event.event_type,
                        "event_name": event.event_name,
                        "created_ts": event.created_ts,
                        "payload": event.payload,
                    }
                    for event in coding_log.fetch_events(trace_id=trace.id)
                ]
                record = trace_to_training_record(trace, events=events)
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
                count += 1
        return count
    finally:
        log.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export accepted Memla coding traces to JSONL.")
    parser.add_argument("--db", default="./memory.sqlite")
    parser.add_argument("--out", required=True)
    parser.add_argument("--user_id", default="default")
    parser.add_argument("--repo_root", default="")
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)

    count = export_accepted_traces_to_jsonl(
        db_path=args.db,
        out_path=args.out,
        user_id=args.user_id,
        repo_root=args.repo_root,
        limit=args.limit,
    )
    print(f"[distillation_export] wrote {count} accepted traces to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
