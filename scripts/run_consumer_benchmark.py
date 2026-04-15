from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import statistics
import sys
import time
from typing import Any
from urllib import error as urllib_error
from urllib import parse as urllib_parse
from urllib import request as urllib_request


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from memory_system.ollama_client import ChatMessage, UniversalLLMClient


@dataclass(frozen=True)
class ConsumerCase:
    case_id: str
    app: str
    prompt: str
    terminal_state: str
    terminal_page_kinds: list[str]
    terminal_signal_roles: list[str]
    required_terms_any_event: list[str]
    target_item_terms_any_event: list[str]
    timeout_seconds: int = 180
    boundary_required: bool = True
    notes: str = ""


def _timestamp_slug() -> str:
    return time.strftime("%Y%m%d_%H%M%S")


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _http_json(method: str, url: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib_request.Request(url, data=data, headers=headers, method=method.upper())
    with urllib_request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_cases(path: Path, selected_ids: set[str], limit: int | None) -> list[ConsumerCase]:
    rows: list[ConsumerCase] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            raw = line.strip()
            if not raw:
                continue
            payload = json.loads(raw)
            case = ConsumerCase(
                case_id=str(payload.get("case_id") or "").strip(),
                app=str(payload.get("app") or "").strip(),
                prompt=str(payload.get("prompt") or "").strip(),
                terminal_state=str(payload.get("terminal_state") or "").strip(),
                terminal_page_kinds=[str(item).strip() for item in list(payload.get("terminal_page_kinds") or []) if str(item).strip()],
                terminal_signal_roles=[str(item).strip() for item in list(payload.get("terminal_signal_roles") or []) if str(item).strip()],
                required_terms_any_event=[str(item).strip() for item in list(payload.get("required_terms_any_event") or []) if str(item).strip()],
                target_item_terms_any_event=[str(item).strip() for item in list(payload.get("target_item_terms_any_event") or []) if str(item).strip()],
                timeout_seconds=int(payload.get("timeout_seconds") or 180),
                boundary_required=bool(payload.get("boundary_required", True)),
                notes=str(payload.get("notes") or "").strip(),
            )
            if selected_ids and case.case_id not in selected_ids:
                continue
            rows.append(case)
    if limit is not None:
        rows = rows[: max(int(limit), 0)]
    return rows


def _get_debug_history(base_url: str, *, after_id: int = 0, limit: int = 50) -> dict[str, Any]:
    query = urllib_parse.urlencode({"after_id": max(int(after_id), 0), "limit": min(max(int(limit), 1), 200)})
    return _http_json("GET", f"{base_url.rstrip('/')}/debug/browser?{query}")


def _collect_event_text(event: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in (
        "reason",
        "title",
        "url",
        "page_kind",
        "page_summary",
        "auth_state",
        "inspection_status",
        "button_action_status",
        "auto_drive_status",
        "mirror_debug_text",
        "agency_trace_text",
    ):
        value = str(event.get(key) or "").strip()
        if value:
            parts.append(value)
    for value in list(event.get("residuals") or []):
        clean = str(value).strip()
        if clean:
            parts.append(clean)
    for value in list(event.get("safe_actions") or []):
        clean = str(value).strip()
        if clean:
            parts.append(clean)
    for key, value in dict(event.get("service_facts") or {}).items():
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if clean_key and clean_value:
            parts.append(f"{clean_key} {clean_value}")
    for key, value in dict(event.get("pending_step") or {}).items():
        clean_key = str(key).strip()
        clean_value = str(value).strip()
        if clean_key and clean_value:
            parts.append(f"{clean_key} {clean_value}")
    for item in list(event.get("top_candidates") or []):
        role = str(item.get("role") or "").strip()
        label = str(item.get("label") or "").strip()
        group_key = str(item.get("group_key") or "").strip()
        group_label = str(item.get("group_label") or "").strip()
        if role or label or group_key or group_label:
            parts.append(" ".join(part for part in (role, label, group_key, group_label) if part))
    return _normalize_text(" ".join(parts))


def _candidate_roles(event: dict[str, Any]) -> set[str]:
    return {str(item.get("role") or "").strip() for item in list(event.get("top_candidates") or []) if str(item.get("role") or "").strip()}


def _has_terminal_signal(case: ConsumerCase, event: dict[str, Any]) -> bool:
    page_kind = str(event.get("page_kind") or "").strip()
    normalized_summary = _normalize_text(event.get("page_summary") or "")
    normalized_url = _normalize_text(event.get("url") or "")
    roles = _candidate_roles(event)
    if page_kind in set(case.terminal_page_kinds):
        if page_kind == "dd_cart_drawer" and case.terminal_signal_roles:
            if roles & set(case.terminal_signal_roles):
                return True
            if "continue path" in normalized_summary:
                return True
        else:
            return True
    if roles & set(case.terminal_signal_roles):
        return True
    if case.terminal_state == "checkout_ready" and "/consumer/checkout/" in normalized_url:
        return True
    return False


def _term_matches(events: list[dict[str, Any]], required_terms: list[str]) -> tuple[list[str], list[str]]:
    full_text = " ".join(_collect_event_text(event) for event in events)
    matched = [term for term in required_terms if _normalize_text(term) in full_text]
    missing = [term for term in required_terms if term not in matched]
    return matched, missing


def _target_item_matched(events: list[dict[str, Any]], target_item_terms: list[str]) -> bool:
    if not target_item_terms:
        return True
    full_text = " ".join(_collect_event_text(event) for event in events)
    return any(_normalize_text(term) in full_text for term in target_item_terms)


def _detect_failure_cluster(case: ConsumerCase, events: list[dict[str, Any]], missing_terms: list[str]) -> str:
    if not events:
        return "no_debug_events"
    last_event = events[-1]
    page_kind = str(last_event.get("page_kind") or "").strip()
    status = _normalize_text(last_event.get("auto_drive_status") or "")
    roles = _candidate_roles(last_event)
    if missing_terms:
        return "constraint_not_proven"
    if page_kind == "dd_item_modal":
        if "selecting" in status or "saving" in status or "continuing through" in status:
            return "customizer_stall"
        return "customizer_timeout"
    if page_kind == "dd_cart_drawer":
        if "dd_continue_cta" not in roles:
            return "cart_drawer_missing_continue"
        return "cart_drawer_no_advance"
    if page_kind == "dd_checkout":
        return "boundary_reached_but_unclassified"
    return "timeout_unknown"


def _build_event_digest(events: list[dict[str, Any]], limit: int = 8) -> str:
    lines: list[str] = []
    for event in events[-limit:]:
        roles = sorted(_candidate_roles(event))
        labels = [str(item.get("label") or "").strip() for item in list(event.get("top_candidates") or [])[:6] if str(item.get("label") or "").strip()]
        line = " | ".join(
            [
                f"id={event.get('event_id')}",
                f"reason={str(event.get('reason') or '').strip() or 'n/a'}",
                f"page_kind={str(event.get('page_kind') or '').strip() or 'unknown'}",
                f"status={str(event.get('auto_drive_status') or '').strip() or 'n/a'}",
                f"roles={','.join(roles) if roles else 'none'}",
                f"labels={'; '.join(labels) if labels else 'none'}",
            ]
        )
        lines.append(line)
    return "\n".join(lines)


def _judge_failure(
    *,
    case: ConsumerCase,
    events: list[dict[str, Any]],
    client: UniversalLLMClient | None,
    model: str,
) -> str:
    if client is None or not model or not events:
        return ""
    prompt = (
        "You are judging a Memla consumer benchmark failure.\n"
        "Reply with 2 short lines:\n"
        "cluster: <one short machine-like label>\n"
        "explanation: <one sentence>\n\n"
        f"case_id: {case.case_id}\n"
        f"prompt: {case.prompt}\n"
        f"terminal_state: {case.terminal_state}\n"
        f"required_terms: {', '.join(case.required_terms_any_event)}\n\n"
        "recent_events:\n"
        f"{_build_event_digest(events)}"
    )
    try:
        return client.chat(
            model=model,
            messages=[
                ChatMessage(role="system", content="Be terse, concrete, and deterministic."),
                ChatMessage(role="user", content=prompt),
            ],
            temperature=0.1,
        ).strip()
    except Exception as exc:
        return f"judge_error: {type(exc).__name__}: {exc}"


def _render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Consumer Benchmark Report",
        "",
        f"- generated_at: `{report['generated_at']}`",
        f"- base_url: `{report['base_url']}`",
        f"- cases: `{report['cases']}`",
        f"- observed_completion_rate: `{report['observed_completion_rate']}`",
        f"- median_duration_seconds: `{report['median_duration_seconds']}`",
        "",
        "## Failure Clusters",
        "",
    ]
    clusters = dict(report.get("failure_clusters") or {})
    if not clusters:
        lines.append("- none")
    else:
        for key, value in sorted(clusters.items(), key=lambda item: (-item[1], item[0])):
            lines.append(f"- `{key}`: {value}")
    lines.extend(["", "## Cases", ""])
    for row in list(report.get("rows") or []):
        lines.append(
            f"- `{row['case_id']}`: "
            f"{'PASS' if row['observed_pass'] else 'FAIL'} | "
            f"duration={row['duration_seconds']}s | "
            f"last_page_kind={row['last_page_kind'] or 'unknown'} | "
            f"failure_cluster={row['failure_cluster'] or 'n/a'}"
        )
    return "\n".join(lines).strip() + "\n"


def _default_out_dir() -> Path:
    out_dir = REPO_ROOT / "memla_reports" / f"consumer_benchmark_{_timestamp_slug()}"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _run_case(
    *,
    case: ConsumerCase,
    base_url: str,
    poll_seconds: float,
    pause_before_case: bool,
    capture_capsule: bool,
    judge_client: UniversalLLMClient | None,
    judge_model: str,
) -> dict[str, Any]:
    history = _get_debug_history(base_url, after_id=0, limit=1)
    after_id = int(history.get("last_event_id") or 0)
    capsule: dict[str, Any] | None = None
    if capture_capsule:
        try:
            capsule_response = _http_json("POST", f"{base_url.rstrip('/')}/actions/capsule", {"prompt": case.prompt})
            capsule = dict(capsule_response.get("capsule") or {})
        except urllib_error.URLError:
            capsule = None

    print("")
    print(f"[Case] {case.case_id}")
    print(f"Prompt: {case.prompt}")
    if case.notes:
        print(f"Notes: {case.notes}")
    if pause_before_case:
        input("Trigger this case in Memla/iPhone, then press Enter to start watching... ")

    started = time.time()
    events: list[dict[str, Any]] = []
    terminal_event: dict[str, Any] | None = None
    current_after_id = after_id

    while (time.time() - started) <= float(case.timeout_seconds):
        payload = _get_debug_history(base_url, after_id=current_after_id, limit=100)
        new_items = list(payload.get("items") or [])
        if new_items:
            events.extend(new_items)
            current_after_id = max(int(item.get("event_id") or 0) for item in new_items)
            for event in reversed(events):
                if _has_terminal_signal(case, event):
                    terminal_event = event
                    break
            if terminal_event is not None:
                break
        time.sleep(max(float(poll_seconds), 0.1))

    duration_seconds = round(time.time() - started, 2)
    matched_terms, missing_terms = _term_matches(events, case.required_terms_any_event)
    target_item_matched = _target_item_matched(events, case.target_item_terms_any_event)
    observed_pass = bool(terminal_event is not None and not missing_terms and target_item_matched)
    failure_cluster = "" if observed_pass else _detect_failure_cluster(case, events, missing_terms)
    judge_summary = "" if observed_pass else _judge_failure(case=case, events=events, client=judge_client, model=judge_model)
    last_event = events[-1] if events else {}

    return {
        "case_id": case.case_id,
        "app": case.app,
        "prompt": case.prompt,
        "terminal_state": case.terminal_state,
        "duration_seconds": duration_seconds,
        "observed_pass": observed_pass,
        "boundary_required": case.boundary_required,
        "event_count": len(events),
        "terminal_event_id": int(terminal_event.get("event_id") or 0) if terminal_event else 0,
        "terminal_page_kind": str(terminal_event.get("page_kind") or "").strip() if terminal_event else "",
        "last_page_kind": str(last_event.get("page_kind") or "").strip(),
        "last_reason": str(last_event.get("reason") or "").strip(),
        "last_status": str(last_event.get("auto_drive_status") or "").strip(),
        "matched_required_terms": matched_terms,
        "missing_required_terms": missing_terms,
        "target_item_matched": target_item_matched,
        "failure_cluster": failure_cluster,
        "judge_summary": judge_summary,
        "capsule": capsule or {},
        "recent_event_digest": _build_event_digest(events),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a lightweight consumer benchmark against the live Memla browser debug stream.")
    parser.add_argument("--cases", default=str(REPO_ROOT / "cases" / "consumer_v1_doordash_cases.jsonl"), help="Consumer benchmark case JSONL path.")
    parser.add_argument("--case-id", action="append", default=[], help="Optional case id filter. Repeat to run specific cases.")
    parser.add_argument("--limit", type=int, default=None, help="Optional max number of cases to run after filtering.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8080", help="Memla API base URL.")
    parser.add_argument("--poll-seconds", type=float, default=2.0, help="Polling interval for browser debug history.")
    parser.add_argument("--no-pause", action="store_true", help="Do not wait for Enter before each case.")
    parser.add_argument("--no-capsule", action="store_true", help="Skip the `/actions/capsule` capture step.")
    parser.add_argument("--judge-model", default="", help="Optional local model used only to summarize ambiguous failures.")
    parser.add_argument("--judge-provider", default="ollama", help="Judge model provider.")
    parser.add_argument("--judge-base-url", default="http://127.0.0.1:11434", help="Judge model base URL.")
    parser.add_argument("--out-dir", default="", help="Optional output directory for JSON and Markdown reports.")
    args = parser.parse_args()

    case_path = Path(args.cases).expanduser().resolve()
    selected_ids = {str(item).strip() for item in list(args.case_id or []) if str(item).strip()}
    cases = _load_cases(case_path, selected_ids, args.limit)
    if not cases:
        raise SystemExit("No consumer benchmark cases selected.")

    health = _http_json("GET", f"{str(args.base_url).rstrip('/')}/health")
    if not bool(health.get("ok")):
        raise SystemExit("Memla API health check failed.")

    judge_client = None
    if str(args.judge_model or "").strip():
        judge_client = UniversalLLMClient(
            provider=str(args.judge_provider or "ollama").strip() or "ollama",
            base_url=str(args.judge_base_url or "http://127.0.0.1:11434").strip() or "http://127.0.0.1:11434",
        )

    rows: list[dict[str, Any]] = []
    for case in cases:
        row = _run_case(
            case=case,
            base_url=str(args.base_url),
            poll_seconds=float(args.poll_seconds),
            pause_before_case=not bool(args.no_pause),
            capture_capsule=not bool(args.no_capsule),
            judge_client=judge_client,
            judge_model=str(args.judge_model or "").strip(),
        )
        rows.append(row)
        status = "PASS" if row["observed_pass"] else "FAIL"
        print(f"Result: {status} | duration={row['duration_seconds']}s | last_page_kind={row['last_page_kind'] or 'unknown'}")
        if row["failure_cluster"]:
            print(f"Failure cluster: {row['failure_cluster']}")
        if row["judge_summary"]:
            print(row["judge_summary"])

    pass_rows = [row for row in rows if bool(row.get("observed_pass"))]
    durations = [float(row["duration_seconds"]) for row in pass_rows]
    failure_clusters = Counter(str(row.get("failure_cluster") or "").strip() for row in rows if not bool(row.get("observed_pass")))
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": str(args.base_url).rstrip("/"),
        "cases_path": str(case_path),
        "cases": len(rows),
        "passes": len(pass_rows),
        "observed_completion_rate": round((len(pass_rows) / len(rows)), 4) if rows else 0.0,
        "median_duration_seconds": round(statistics.median(durations), 2) if durations else None,
        "failure_clusters": {key: value for key, value in sorted(failure_clusters.items()) if key},
        "rows": rows,
    }

    out_dir = Path(args.out_dir).expanduser().resolve() if str(args.out_dir or "").strip() else _default_out_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "consumer_benchmark_report.json"
    md_path = out_dir / "consumer_benchmark_report.md"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown(report), encoding="utf-8")

    print("")
    print(f"Wrote consumer benchmark JSON: {json_path}")
    print(f"Wrote consumer benchmark Markdown: {md_path}")
    print(f"Observed completion rate: {report['observed_completion_rate']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
