from __future__ import annotations

import json
import re
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from .constraint_graph import (
    infer_constraint_tags,
    infer_file_roles,
    infer_prompt_roles,
    infer_repo_family,
    summarize_transmutations,
    transmutation_specificity,
)


_CODING_TRACE_DDL = """
CREATE TABLE IF NOT EXISTS coding_traces (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_ts INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  provider TEXT NOT NULL,
  model TEXT NOT NULL,
  repo_root TEXT NOT NULL DEFAULT '',
  task_text TEXT NOT NULL,
  system_prompt TEXT NOT NULL DEFAULT '',
  messages_json TEXT NOT NULL DEFAULT '[]',
  retrieved_chunk_ids_json TEXT NOT NULL DEFAULT '[]',
  trajectory_id INTEGER,
  assistant_text TEXT NOT NULL,
  touched_files_json TEXT NOT NULL DEFAULT '[]',
  patch_text TEXT NOT NULL DEFAULT '',
  tests_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'pending',
  acceptance_score REAL NOT NULL DEFAULT 0.0,
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_coding_traces_user_ts
ON coding_traces(user_id, created_ts DESC);

CREATE TABLE IF NOT EXISTS coding_trace_feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coding_trace_id INTEGER NOT NULL,
  created_ts INTEGER NOT NULL,
  is_positive INTEGER NOT NULL,
  note TEXT NOT NULL DEFAULT '',
  meta_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_coding_trace_feedback_trace_ts
ON coding_trace_feedback(coding_trace_id, created_ts DESC);

CREATE TABLE IF NOT EXISTS coding_trace_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  coding_trace_id INTEGER NOT NULL,
  created_ts INTEGER NOT NULL,
  event_type TEXT NOT NULL,
  event_name TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_coding_trace_events_trace_ts
ON coding_trace_events(coding_trace_id, created_ts ASC, id ASC);
"""


_SIMILARITY_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "bug",
    "by",
    "file",
    "fix",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "please",
    "repo",
    "repository",
    "test",
    "tests",
    "that",
    "the",
    "this",
    "to",
    "update",
    "with",
}


@dataclass(frozen=True)
class CodingTrace:
    id: int
    created_ts: int
    session_id: str
    user_id: str
    provider: str
    model: str
    repo_root: str
    task_text: str
    system_prompt: str
    messages: list[dict[str, Any]]
    retrieved_chunk_ids: list[int]
    trajectory_id: Optional[int]
    assistant_text: str
    touched_files: list[str]
    patch_text: str
    tests: list[dict[str, Any]]
    status: str
    acceptance_score: float
    meta: dict[str, Any]


@dataclass(frozen=True)
class CodingTraceEvent:
    id: int
    coding_trace_id: int
    created_ts: int
    event_type: str
    event_name: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class SimilarCodingTrace:
    trace: CodingTrace
    score: float
    matched_terms: list[str]
    matched_files: list[str]
    matched_constraints: list[str] = ()
    matched_transmutations: list[str] = ()
    matched_roles: list[str] = ()
    same_repo: bool = False
    repo_family: str = ""
    repo_family_match: bool = False


@dataclass(frozen=True)
class WorkflowPriorSummary:
    suggested_files: list[str]
    suggested_commands: list[str]
    source_trace_ids: list[int]


def _normalize_similarity_token(token: str) -> str:
    token = token.lower()
    if token.endswith("ies") and len(token) > 4:
        token = token[:-3] + "y"
    elif token.endswith("ing") and len(token) > 5:
        token = token[:-3]
    elif token.endswith("ed") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("es") and len(token) > 4:
        token = token[:-2]
    elif token.endswith("s") and len(token) > 3:
        token = token[:-1]
    return token


def _tokenize_similarity_text(text: str) -> set[str]:
    tokens = re.findall(r"[a-zA-Z0-9_]+", text or "")
    out: set[str] = set()
    for token in tokens:
        norm = _normalize_similarity_token(token)
        if len(norm) >= 3 and norm not in _SIMILARITY_STOPWORDS:
            out.add(norm)
    return out


def _tokenize_paths(paths: list[str]) -> set[str]:
    out: set[str] = set()
    for path in paths:
        raw = str(path or "").replace("\\", "/")
        pieces = [piece for piece in raw.split("/") if piece]
        for piece in pieces:
            stem = Path(piece).stem if "." in piece else piece
            out.update(_tokenize_similarity_text(stem))
            out.update(_tokenize_similarity_text(stem.replace("_", " ").replace("-", " ")))
    return out


def _recent_test_signal(tests: list[dict[str, Any]]) -> float:
    if not tests:
        return 0.0
    latest = tests[-1]
    status = str(latest.get("status") or "").strip().lower()
    if status == "passed":
        return 0.2
    if status == "failed":
        return -0.15
    return 0.0


def _normalize_repo_path(path: str) -> str:
    clean = str(path or "").strip().replace("\\", "/")
    while clean.startswith("./"):
        clean = clean[2:]
    return clean


def _normalize_command(command: str) -> str:
    return " ".join(str(command or "").strip().split())


def _repo_relative_exists(path: str, repo_root: str) -> bool:
    clean = _normalize_repo_path(path)
    if not clean or not repo_root:
        return bool(clean)
    repo = Path(repo_root).resolve()
    candidate = (repo / clean).resolve()
    try:
        candidate.relative_to(repo)
    except ValueError:
        return False
    return candidate.exists()


def _path_overlap_count(path: str, prompt_tokens: set[str]) -> int:
    if not prompt_tokens:
        return 0
    return len(prompt_tokens & _tokenize_paths([path]))


def _is_generic_repo_path(path: str) -> bool:
    lowered = _normalize_repo_path(path).lower()
    return lowered in {
        "index.html",
        "package.json",
        "package-lock.json",
        "src/main.js",
        "src/main.jsx",
        "src/main.ts",
        "src/main.tsx",
        "src/index.css",
        "src/index.html",
        "public/index.html",
    }


def _command_tokens(command: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[a-zA-Z0-9_.:/@-]+", command or "")}


def _is_setup_command(command: str) -> bool:
    lowered = _normalize_command(command).lower()
    return lowered.startswith(
        (
            "npm install",
            "npm i ",
            "pnpm install",
            "pnpm add ",
            "yarn add ",
            "pip install",
            "uv pip install",
        )
    )


def _is_verification_command(command: str) -> bool:
    lowered = _normalize_command(command).lower()
    return (
        lowered.startswith("pytest")
        or lowered.startswith("py -3 -m pytest")
        or lowered.startswith("python -m pytest")
        or lowered.startswith("npm run build")
        or lowered.startswith("npm run lint")
        or lowered.startswith("npm test")
        or lowered.startswith("pnpm test")
        or lowered.startswith("pnpm build")
        or lowered.startswith("pnpm lint")
        or lowered.startswith("yarn test")
        or lowered.startswith("yarn build")
        or lowered.startswith("yarn lint")
        or lowered.startswith("cargo test")
        or lowered.startswith("go test")
        or lowered.startswith("uv run pytest")
    )


def _is_search_command(command: str) -> bool:
    lowered = _normalize_command(command).lower()
    return lowered.startswith(("rg ", "find ", "git diff", "git status", "ls ", "dir "))


def _command_bonus(command: str) -> float:
    if _is_verification_command(command):
        return 0.45
    if _is_search_command(command):
        return 0.2
    if _is_setup_command(command):
        return -0.2
    return 0.0


class CodingTraceLog:
    """Persistent log of coding/workflow traces for later distillation."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(_CODING_TRACE_DDL)
        self._migrate_column("touched_files_json", "TEXT NOT NULL DEFAULT '[]'")
        self._conn.commit()

    def _migrate_column(self, column_name: str, column_sql: str) -> None:
        try:
            self._conn.execute(f"SELECT {column_name} FROM coding_traces LIMIT 1")
        except sqlite3.OperationalError:
            self._conn.execute(f"ALTER TABLE coding_traces ADD COLUMN {column_name} {column_sql}")

    def save_trace(
        self,
        *,
        session_id: str,
        user_id: str,
        provider: str,
        model: str,
        repo_root: str,
        task_text: str,
        system_prompt: str,
        messages: list[dict[str, Any]],
        retrieved_chunk_ids: list[int],
        assistant_text: str,
        trajectory_id: Optional[int] = None,
        touched_files: Optional[list[str]] = None,
        patch_text: str = "",
        tests: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        stored_meta = dict(meta or {})
        stored_meta.setdefault("repo_family", infer_repo_family(repo_root))
        cur = self._conn.execute(
            """
            INSERT INTO coding_traces(
              created_ts, session_id, user_id, provider, model, repo_root,
              task_text, system_prompt, messages_json, retrieved_chunk_ids_json,
              trajectory_id, assistant_text, touched_files_json, patch_text, tests_json, meta_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ts_i,
                session_id,
                user_id,
                provider,
                model,
                repo_root,
                task_text,
                system_prompt,
                json.dumps(messages, ensure_ascii=False),
                json.dumps([int(cid) for cid in retrieved_chunk_ids], ensure_ascii=False),
                int(trajectory_id) if trajectory_id is not None else None,
                assistant_text,
                json.dumps([str(path) for path in (touched_files or [])], ensure_ascii=False),
                patch_text,
                json.dumps(tests or [], ensure_ascii=False),
                json.dumps(stored_meta, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def update_trace_artifacts(
        self,
        *,
        trace_id: int,
        touched_files: Optional[list[str]] = None,
        patch_text: Optional[str] = None,
        tests: Optional[list[dict[str, Any]]] = None,
        meta: Optional[dict[str, Any]] = None,
    ) -> None:
        row = self._conn.execute(
            "SELECT touched_files_json, patch_text, tests_json, meta_json FROM coding_traces WHERE id = ?",
            (int(trace_id),),
        ).fetchone()
        if row is None:
            return
        merged_meta = dict(json.loads(row["meta_json"] or "{}"))
        if meta:
            merged_meta.update(meta)
        self._conn.execute(
            """
            UPDATE coding_traces
            SET touched_files_json = ?,
                patch_text = ?,
                tests_json = ?,
                meta_json = ?
            WHERE id = ?
            """,
            (
                json.dumps([str(path) for path in (touched_files or json.loads(row["touched_files_json"] or "[]"))], ensure_ascii=False),
                patch_text if patch_text is not None else str(row["patch_text"] or ""),
                json.dumps(tests if tests is not None else json.loads(row["tests_json"] or "[]"), ensure_ascii=False),
                json.dumps(merged_meta, ensure_ascii=False),
                int(trace_id),
            ),
        )
        self._conn.commit()

    def mark_feedback(
        self,
        *,
        trace_id: int,
        is_positive: bool,
        note: str = "",
        meta: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> None:
        ts_i = int(ts if ts is not None else time.time())
        status = "accepted" if is_positive else "rejected"
        score_delta = 1.0 if is_positive else -1.0
        self._conn.execute(
            """
            INSERT INTO coding_trace_feedback(coding_trace_id, created_ts, is_positive, note, meta_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(trace_id),
                ts_i,
                1 if is_positive else 0,
                note,
                json.dumps(meta or {}, ensure_ascii=False),
            ),
        )
        self._conn.execute(
            """
            UPDATE coding_traces
            SET status = ?, acceptance_score = acceptance_score + ?
            WHERE id = ?
            """,
            (status, float(score_delta), int(trace_id)),
        )
        self._conn.commit()

    def append_event(
        self,
        *,
        trace_id: int,
        event_type: str,
        event_name: str,
        payload: Optional[dict[str, Any]] = None,
        ts: Optional[int] = None,
    ) -> int:
        ts_i = int(ts if ts is not None else time.time())
        cur = self._conn.execute(
            """
            INSERT INTO coding_trace_events(coding_trace_id, created_ts, event_type, event_name, payload_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(trace_id),
                ts_i,
                str(event_type).strip(),
                str(event_name).strip(),
                json.dumps(payload or {}, ensure_ascii=False),
            ),
        )
        self._conn.commit()
        return int(cur.lastrowid)

    def fetch_events(self, *, trace_id: int) -> list[CodingTraceEvent]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM coding_trace_events
            WHERE coding_trace_id = ?
            ORDER BY created_ts ASC, id ASC
            """,
            (int(trace_id),),
        ).fetchall()
        return [
            CodingTraceEvent(
                id=int(row["id"]),
                coding_trace_id=int(row["coding_trace_id"]),
                created_ts=int(row["created_ts"]),
                event_type=str(row["event_type"]),
                event_name=str(row["event_name"]),
                payload=dict(json.loads(row["payload_json"] or "{}")),
            )
            for row in rows
        ]

    def fetch_recent(self, *, user_id: str, limit: int = 20) -> list[CodingTrace]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM coding_traces
            WHERE user_id = ?
            ORDER BY created_ts DESC, id DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def fetch_training_candidates(self, *, user_id: str, limit: int = 100) -> list[CodingTrace]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM coding_traces
            WHERE user_id = ? AND status = 'accepted'
            ORDER BY acceptance_score DESC, created_ts DESC, id DESC
            LIMIT ?
            """,
            (user_id, int(limit)),
        ).fetchall()
        return [self._row_to_trace(row) for row in rows]

    def find_similar_accepted_traces(
        self,
        *,
        user_id: str,
        repo_root: str,
        task_text: str,
        touched_files: Optional[list[str]] = None,
        limit: int = 5,
        pool_limit: int = 200,
        exclude_trace_ids: Optional[list[int]] = None,
    ) -> list[SimilarCodingTrace]:
        rows = self._conn.execute(
            """
            SELECT *
            FROM coding_traces
            WHERE user_id = ?
              AND status = 'accepted'
            ORDER BY acceptance_score DESC, created_ts DESC, id DESC
            LIMIT ?
            """,
            (user_id, int(pool_limit)),
        ).fetchall()
        excluded = {int(x) for x in (exclude_trace_ids or [])}
        query_tokens = _tokenize_similarity_text(task_text)
        query_file_tokens = _tokenize_paths(touched_files or [])
        query_constraints = infer_constraint_tags(task_text, touched_files or [], [])
        query_transmutations = set(summarize_transmutations(sorted(query_constraints)))
        query_roles = infer_prompt_roles(task_text)
        current_repo = str(Path(repo_root).resolve()) if repo_root else ""
        current_family = infer_repo_family(repo_root) if repo_root else "unknown"
        scored: list[SimilarCodingTrace] = []

        for row in rows:
            trace = self._row_to_trace(row)
            if trace.id in excluded:
                continue
            trace_repo = str(Path(trace.repo_root).resolve()) if trace.repo_root else ""
            same_repo = bool(current_repo and trace_repo and current_repo == trace_repo)
            trace_family = str(trace.meta.get("repo_family") or infer_repo_family(trace.repo_root)).strip() or "unknown"
            family_match = bool(current_family and current_family != "unknown" and trace_family == current_family)
            task_tokens = _tokenize_similarity_text(trace.task_text)
            task_overlap = sorted(query_tokens & task_tokens)
            if query_tokens or task_tokens:
                task_score = len(task_overlap) / max(len(query_tokens | task_tokens), 1)
            else:
                task_score = 0.0

            trace_files = list(trace.touched_files) + list(trace.meta.get("seed_expected_files") or [])
            trace_file_tokens = _tokenize_paths(trace_files)
            file_overlap = sorted(query_file_tokens & trace_file_tokens)
            if query_file_tokens or trace_file_tokens:
                file_score = len(file_overlap) / max(len(query_file_tokens | trace_file_tokens), 1)
            else:
                file_score = 0.0

            trace_commands = [str(test.get("command") or "") for test in trace.tests]
            trace_constraints = infer_constraint_tags(
                f"{trace.task_text}\n{trace.assistant_text}",
                trace_files,
                trace_commands + list(trace.meta.get("teacher_answer_commands") or []),
            )
            constraint_overlap = sorted(query_constraints & trace_constraints)
            trace_transmutations = set(summarize_transmutations(sorted(trace_constraints)))
            transmutation_overlap = sorted(query_transmutations & trace_transmutations)
            trace_roles: set[str] = set()
            for path in trace_files:
                trace_roles.update(infer_file_roles(path))
            role_overlap = sorted(query_roles & trace_roles)
            transmutation_bonus = sum(transmutation_specificity(text) for text in transmutation_overlap)

            score = (
                (task_score * 1.6)
                + (file_score * 1.1)
                + (len(constraint_overlap) * 0.55)
                + (transmutation_bonus * 0.55)
                + (len(role_overlap) * 0.45)
                + (0.6 if same_repo else 0.0)
                + (0.35 if family_match else 0.0)
                + min(float(trace.acceptance_score), 3.0) * 0.1
                + _recent_test_signal(trace.tests)
            )
            if not task_overlap and not file_overlap and not constraint_overlap and not transmutation_overlap and not role_overlap:
                continue
            scored.append(
                SimilarCodingTrace(
                    trace=trace,
                    score=float(score),
                    matched_terms=task_overlap,
                    matched_files=file_overlap,
                    matched_constraints=constraint_overlap,
                    matched_transmutations=transmutation_overlap,
                    matched_roles=role_overlap,
                    same_repo=same_repo,
                    repo_family=trace_family,
                    repo_family_match=family_match,
                )
            )

        scored.sort(
            key=lambda item: (
                item.same_repo,
                item.score,
                len(item.matched_terms),
                len(item.matched_files),
                len(item.matched_constraints),
                len(item.matched_transmutations),
                len(item.matched_roles),
                item.trace.acceptance_score,
                item.trace.created_ts,
                item.trace.id,
            ),
            reverse=True,
        )
        return scored[: max(int(limit), 0)]

    def summarize_workflow_priors(
        self,
        candidates: list[SimilarCodingTrace],
        *,
        repo_root: str = "",
        prompt: str = "",
        max_files: int = 6,
        max_commands: int = 4,
    ) -> WorkflowPriorSummary:
        file_scores: dict[str, float] = {}
        command_scores: dict[str, float] = {}
        source_ids: list[int] = []
        prompt_tokens = _tokenize_similarity_text(prompt)

        for candidate in candidates:
            trace = candidate.trace
            source_ids.append(trace.id)
            base_weight = (
                max(float(candidate.score), 0.1)
                + max(float(trace.acceptance_score), 0.0) * 0.15
                + (len(candidate.matched_terms) * 0.08)
                + (len(candidate.matched_files) * 0.12)
                + (0.28 if candidate.repo_family_match else 0.0)
                + (sum(transmutation_specificity(text) for text in candidate.matched_transmutations) * 0.08)
            )

            expected_files = {
                _normalize_repo_path(path)
                for path in list(trace.meta.get("seed_expected_files") or [])
                if _normalize_repo_path(path)
            }
            expected_commands = {
                _normalize_command(command)
                for command in list(trace.meta.get("seed_expected_commands") or [])
                if _normalize_command(command)
            }
            passed_commands: set[str] = set()

            for test in trace.tests:
                command = _normalize_command(test.get("command") or "")
                if not command:
                    continue
                status = str(test.get("status") or "").strip().lower()
                if status == "passed":
                    passed_commands.add(command)

            for event in self.fetch_events(trace_id=trace.id):
                if event.event_name not in {"shell_run", "test_run"}:
                    continue
                command = _normalize_command(event.payload.get("command") or "")
                if not command:
                    continue
                status = str(event.payload.get("status") or "").strip().lower()
                if status == "passed":
                    passed_commands.add(command)

            def add_file(path: str, weight: float, *, require_overlap: bool = False) -> None:
                clean_path = _normalize_repo_path(path)
                if not clean_path:
                    return
                overlap = _path_overlap_count(clean_path, prompt_tokens)
                if prompt_tokens and require_overlap and clean_path not in expected_files and overlap == 0:
                    return
                adjusted = float(weight) + (overlap * 0.35)
                if repo_root and not _repo_relative_exists(clean_path, repo_root):
                    adjusted *= 0.35
                if clean_path in expected_files:
                    adjusted += 0.45
                elif _is_generic_repo_path(clean_path) and overlap == 0:
                    adjusted *= 0.45
                if adjusted > 0:
                    file_scores[clean_path] = file_scores.get(clean_path, 0.0) + adjusted

            for path in expected_files:
                if candidate.same_repo:
                    add_file(path, base_weight * 2.8)

            for path in trace.touched_files:
                clean_path = _normalize_repo_path(path)
                if not clean_path:
                    continue
                weight = base_weight * (0.55 if clean_path in expected_files else 0.18)
                if candidate.same_repo:
                    add_file(clean_path, weight, require_overlap=clean_path not in expected_files)

            for path in list(trace.meta.get("teacher_answer_files") or []):
                clean_path = _normalize_repo_path(path)
                if not clean_path:
                    continue
                weight = base_weight * (0.7 if clean_path in expected_files else 0.16)
                if candidate.same_repo:
                    add_file(clean_path, weight, require_overlap=clean_path not in expected_files)

            for command in expected_commands:
                command_scores[command] = command_scores.get(command, 0.0) + (base_weight * 2.8) + _command_bonus(command)

            for test in trace.tests:
                command = _normalize_command(test.get("command") or "")
                if not command:
                    continue
                status = str(test.get("status") or "").strip().lower()
                if status != "passed":
                    continue
                command_scores[command] = command_scores.get(command, 0.0) + (base_weight * 1.5) + _command_bonus(command)

            for command in list(trace.meta.get("teacher_answer_commands") or []):
                clean_command = _normalize_command(command)
                if not clean_command or _is_setup_command(clean_command):
                    continue
                if (
                    clean_command not in expected_commands
                    and clean_command not in passed_commands
                    and not _is_verification_command(clean_command)
                    and not _is_search_command(clean_command)
                ):
                    continue
                weight = base_weight * (0.9 if clean_command in expected_commands else 0.28)
                command_scores[clean_command] = command_scores.get(clean_command, 0.0) + weight + _command_bonus(clean_command)

            for command in passed_commands:
                if not command:
                    continue
                command_scores[command] = command_scores.get(command, 0.0) + (base_weight * 1.2) + _command_bonus(command)

        sorted_files = sorted(file_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        sorted_commands = sorted(command_scores.items(), key=lambda item: (item[1], item[0]), reverse=True)
        return WorkflowPriorSummary(
            suggested_files=[path for path, _ in sorted_files[: max(int(max_files), 0)]],
            suggested_commands=[command for command, _ in sorted_commands[: max(int(max_commands), 0)]],
            source_trace_ids=source_ids,
        )

    def _row_to_trace(self, row: sqlite3.Row) -> CodingTrace:
        return CodingTrace(
            id=int(row["id"]),
            created_ts=int(row["created_ts"]),
            session_id=str(row["session_id"]),
            user_id=str(row["user_id"]),
            provider=str(row["provider"]),
            model=str(row["model"]),
            repo_root=str(row["repo_root"]),
            task_text=str(row["task_text"]),
            system_prompt=str(row["system_prompt"]),
            messages=list(json.loads(row["messages_json"] or "[]")),
            retrieved_chunk_ids=[int(x) for x in json.loads(row["retrieved_chunk_ids_json"] or "[]")],
            trajectory_id=int(row["trajectory_id"]) if row["trajectory_id"] is not None else None,
            assistant_text=str(row["assistant_text"]),
            touched_files=[str(x) for x in json.loads(row["touched_files_json"] or "[]")],
            patch_text=str(row["patch_text"] or ""),
            tests=list(json.loads(row["tests_json"] or "[]")),
            status=str(row["status"]),
            acceptance_score=float(row["acceptance_score"]),
            meta=dict(json.loads(row["meta_json"] or "{}")),
        )
