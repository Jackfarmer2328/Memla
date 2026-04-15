from __future__ import annotations

from dataclasses import asdict
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

from .natural_terminal import (
    build_llm_client,
    build_terminal_step_report,
    execute_terminal_step,
    load_browser_session_state,
    terminal_step_execution_to_dict,
    terminal_step_report_to_dict,
    terminal_trace_log_path,
)


def _coerce_bool(value: Any, *, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _coerce_float(value: Any, *, default: float = 0.1) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _trace_path(raw: str) -> Path:
    text = str(raw or "").strip()
    if text:
        return Path(text).expanduser().resolve()
    return terminal_trace_log_path()


def _read_recent_traces(path: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


def _load_workbench_html() -> str:
    asset_path = Path(__file__).with_name("terminal_workbench.html")
    return asset_path.read_text(encoding="utf-8")


def serve_terminal_workbench(
    *,
    host: str = "127.0.0.1",
    port: int = 8766,
    model: str = "",
    provider: str = "ollama",
    base_url: str = "",
    temperature: float = 0.1,
    heuristic_only: bool = True,
    trace_log: str = "",
) -> None:
    html = _load_workbench_html().replace("__MEMLA_WORKBENCH_TITLE__", "Memla Browser Workbench")
    default_trace_path = _trace_path(trace_log)
    default_settings = {
        "model": str(model or "").strip(),
        "provider": str(provider or "ollama").strip() or "ollama",
        "base_url": str(base_url or "").strip(),
        "temperature": float(temperature),
        "heuristic_only": bool(heuristic_only),
        "trace_log": str(default_trace_path),
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def _write_json(self, payload: dict[str, Any], *, status: int = 200) -> None:
            encoded = json.dumps(payload, indent=2).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _write_html(self, body: str) -> None:
            encoded = body.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length)
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}

        def _settings_from_body(self, body: dict[str, Any]) -> dict[str, Any]:
            return {
                "model": str(body.get("model") or default_settings["model"]).strip(),
                "provider": str(body.get("provider") or default_settings["provider"]).strip() or "ollama",
                "base_url": str(body.get("base_url") or default_settings["base_url"]).strip(),
                "temperature": _coerce_float(body.get("temperature"), default=default_settings["temperature"]),
                "heuristic_only": _coerce_bool(body.get("heuristic_only"), default=default_settings["heuristic_only"]),
                "trace_log": str(body.get("trace_log") or default_settings["trace_log"]).strip() or default_settings["trace_log"],
            }

        def _state_payload(self) -> dict[str, Any]:
            state = load_browser_session_state()
            return {
                "browser_state": asdict(state),
                "defaults": dict(default_settings),
                "trace_log": str(default_trace_path),
                "recent_traces": _read_recent_traces(default_trace_path),
            }

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path in {"/", "/index.html"}:
                self._write_html(html)
                return
            if parsed.path == "/api/state":
                self._write_json(self._state_payload())
                return
            self._write_json({"error": "not_found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            body = self._read_json()
            if parsed.path == "/api/step":
                prompt = str(body.get("prompt") or "").strip()
                if not prompt:
                    self._write_json({"error": "prompt is required"}, status=400)
                    return
                settings = self._settings_from_body(body)
                client = None if settings["heuristic_only"] else build_llm_client(
                    provider=settings["provider"] or None,
                    base_url=settings["base_url"] or None,
                )
                browser_state = load_browser_session_state()
                started = time.perf_counter()
                report = build_terminal_step_report(
                    prompt=prompt,
                    model=settings["model"],
                    client=client,
                    heuristic_only=settings["heuristic_only"],
                    temperature=settings["temperature"],
                    browser_state=browser_state,
                )
                planning_seconds = round(time.perf_counter() - started, 4)
                self._write_json(
                    {
                        "report": terminal_step_report_to_dict(report),
                        "planning_duration_seconds": planning_seconds,
                        "browser_state": asdict(browser_state),
                        "recent_traces": _read_recent_traces(_trace_path(settings["trace_log"])),
                    }
                )
                return
            if parsed.path == "/api/execute":
                prompt = str(body.get("prompt") or "").strip()
                choice = str(body.get("choice") or "").strip()
                if not prompt:
                    self._write_json({"error": "prompt is required"}, status=400)
                    return
                if not choice:
                    self._write_json({"error": "choice is required"}, status=400)
                    return
                settings = self._settings_from_body(body)
                trace_path = _trace_path(settings["trace_log"])
                browser_state = load_browser_session_state()
                client = None if settings["heuristic_only"] else build_llm_client(
                    provider=settings["provider"] or None,
                    base_url=settings["base_url"] or None,
                )
                planning_started = time.perf_counter()
                report = build_terminal_step_report(
                    prompt=prompt,
                    model=settings["model"],
                    client=client,
                    heuristic_only=settings["heuristic_only"],
                    temperature=settings["temperature"],
                    browser_state=browser_state,
                )
                planning_seconds = round(time.perf_counter() - planning_started, 4)
                execution_started = time.perf_counter()
                try:
                    execution = execute_terminal_step(
                        report,
                        choice=choice,
                        browser_state=browser_state,
                        trace_path=trace_path,
                    )
                except ValueError as exc:
                    self._write_json(
                        {
                            "error": str(exc),
                            "report": terminal_step_report_to_dict(report),
                            "planning_duration_seconds": planning_seconds,
                        },
                        status=400,
                    )
                    return
                execution_seconds = round(time.perf_counter() - execution_started, 4)
                self._write_json(
                    {
                        "execution": terminal_step_execution_to_dict(execution),
                        "planning_duration_seconds": planning_seconds,
                        "execution_duration_seconds": execution_seconds,
                        "total_duration_seconds": round(planning_seconds + execution_seconds, 4),
                        "browser_state": asdict(load_browser_session_state()),
                        "recent_traces": _read_recent_traces(trace_path),
                    }
                )
                return
            self._write_json({"error": "not_found"}, status=404)

    server = ThreadingHTTPServer((host, int(port)), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


__all__ = ["serve_terminal_workbench"]
