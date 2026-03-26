from __future__ import annotations

import argparse
import os
import secrets
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..distillation.coding_log import CodingTraceLog, SimilarCodingTrace, WorkflowPriorSummary
from ..distillation.workflow_planner import WorkflowPlan, build_workflow_plan, render_workflow_plan_block
from ..distillation.workspace_capture import capture_workspace_state
from ..memory.chunk_manager import ChunkManager
from ..memory.episode_log import EpisodeLog
from ..memory.llm_extractor import LLMChunkExtractor
from ..middleware.ttt_layer import TTTLayer
from ..ollama_client import ChatMessage, UniversalLLMClient
from ..reasoning.trajectory import (
    Trajectory,
    TrajectoryLog,
    extract_output_text,
    has_trajectory_format,
    inject_reasoning_prompt,
    parse_trajectory,
)


CODING_BASE_SYSTEM = """
You are a coding copilot working inside a real repository.

Use retrieved memory when it contains repo-specific conventions, previous fixes,
accepted implementation patterns, or user preferences. Prefer concrete,
minimal, implementation-shaped answers over generic advice.

When suggesting code changes:
- preserve existing project conventions
- call out the exact files likely involved
- prefer the smallest correct patch
- mention tests to run when relevant
""".strip()


def _new_session_id() -> str:
    return f"coding_{int(time.time())}_{secrets.token_hex(3)}"


@dataclass(frozen=True)
class ProxyResult:
    answer: str
    trace_id: int
    trajectory_id: Optional[int]
    retrieved_chunk_ids: list[int]
    test_result: Optional[dict[str, object]] = None
    prior_trace_ids: list[int] | None = None
    suggested_files: list[str] | None = None
    suggested_commands: list[str] | None = None
    likely_tests: list[str] | None = None
    patch_steps: list[str] | None = None
    constraint_tags: list[str] | None = None
    transmutations: list[str] | None = None
    role_targets: list[str] | None = None


@dataclass(frozen=True)
class ShellCommandResult:
    command: str
    status: str
    returncode: int
    stdout_tail: str
    stderr_tail: str


def _shorten(text: str, limit: int = 220) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 3].rstrip() + "..."


def _build_distilled_priors_block(candidates: list[SimilarCodingTrace]) -> str:
    if not candidates:
        return ""
    lines = [
        "",
        "=== DISTILLED CODING PRIORS FROM ACCEPTED PAST SOLUTIONS ===",
        "These are repo-specific prior wins that resemble the current task.",
        "Reuse their patterns when they truly fit; do not cargo-cult irrelevant details.",
        "",
    ]
    for index, candidate in enumerate(candidates, start=1):
        trace = candidate.trace
        lines.append(f"{index}. Prior task: {_shorten(trace.task_text, 140)}")
        if candidate.matched_terms:
            lines.append(f"   Matched terms: {', '.join(candidate.matched_terms[:8])}")
        if candidate.matched_files:
            lines.append(f"   Matched files: {', '.join(candidate.matched_files[:8])}")
        if trace.touched_files:
            lines.append(f"   Touched files: {', '.join(trace.touched_files[:4])}")
        if trace.tests:
            latest = trace.tests[-1]
            status = str(latest.get('status') or '').strip()
            command = str(latest.get('command') or '').strip()
            if status or command:
                lines.append(f"   Latest test: {status or 'unknown'} {command}".rstrip())
        lines.append(f"   Accepted solution pattern: {_shorten(extract_output_text(trace.assistant_text), 220)}")
        lines.append("")
    lines.append("=== END DISTILLED CODING PRIORS ===")
    return "\n".join(lines)


def _build_workflow_priors_block(summary: WorkflowPriorSummary) -> str:
    if not summary.suggested_files and not summary.suggested_commands:
        return ""
    lines = [
        "",
        "=== DISTILLED WORKFLOW PRIORS ===",
        "These are Memla's best guesses from accepted repo-specific wins before asking the teacher model.",
    ]
    if summary.suggested_files:
        lines.append(f"Likely files to inspect first: {', '.join(summary.suggested_files[:6])}")
    if summary.suggested_commands:
        lines.append(f"Likely commands to run: {', '.join(summary.suggested_commands[:4])}")
    lines.append("=== END DISTILLED WORKFLOW PRIORS ===")
    return "\n".join(lines)


def _run_test_command(*, command: str, repo_root: str) -> dict[str, object]:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return {
        "command": command,
        "status": "passed" if completed.returncode == 0 else "failed",
        "returncode": int(completed.returncode),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def _run_shell_command(*, command: str, repo_root: str, timeout_seconds: int = 300) -> ShellCommandResult:
    completed = subprocess.run(
        command,
        cwd=repo_root,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_seconds,
        check=False,
    )
    stdout = completed.stdout or ""
    stderr = completed.stderr or ""
    return ShellCommandResult(
        command=command,
        status="passed" if completed.returncode == 0 else "failed",
        returncode=int(completed.returncode),
        stdout_tail=stdout[-4000:],
        stderr_tail=stderr[-4000:],
    )


class CodingSession:
    """Long-lived coding proxy session that accumulates traces across turns."""

    def __init__(
        self,
        *,
        model: str,
        db_path: str,
        user_id: str,
        repo_root: str,
        temperature: float = 0.1,
        top_k: int = 12,
        num_ctx: int | None = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.model = model
        self.user_id = user_id
        self.repo_root = str(Path(repo_root).resolve())
        self.temperature = temperature
        self.top_k = top_k
        self.num_ctx = num_ctx
        self.session_id = session_id or _new_session_id()

        self.log = EpisodeLog(db_path)
        self.client = UniversalLLMClient.from_env()
        extractor = LLMChunkExtractor(client=self.client, model=model, temperature=0.0, num_ctx=num_ctx)
        cm = ChunkManager(self.log, llm_extractor=extractor.extract)
        self.ttt = TTTLayer(episode_log=self.log, chunk_manager=cm)
        self.traj_log = TrajectoryLog(self.log._conn)
        self.coding_log = CodingTraceLog(self.log._conn)
        self.history: list[ChatMessage] = []
        self.max_history_turns = 20
        self.last_trace_id: Optional[int] = None

    def close(self) -> None:
        self.log.close()

    def build_plan(self, prompt: str) -> WorkflowPlan:
        workspace_snapshot = capture_workspace_state(self.repo_root)
        similar_traces = self.coding_log.find_similar_accepted_traces(
            user_id=self.user_id,
            repo_root=self.repo_root,
            task_text=prompt,
            touched_files=workspace_snapshot.get("touched_files") or [],
            limit=4,
            exclude_trace_ids=[self.last_trace_id] if self.last_trace_id is not None else None,
        )
        workflow_priors = self.coding_log.summarize_workflow_priors(
            similar_traces,
            repo_root=self.repo_root,
            prompt=prompt,
            max_files=10,
        )
        return build_workflow_plan(
            candidates=similar_traces,
            summary=workflow_priors,
            prompt=prompt,
            repo_root=self.repo_root,
        )

    def ask(self, prompt: str, *, test_command: Optional[str] = None) -> ProxyResult:
        workspace_snapshot = capture_workspace_state(self.repo_root)
        similar_traces = self.coding_log.find_similar_accepted_traces(
            user_id=self.user_id,
            repo_root=self.repo_root,
            task_text=prompt,
            touched_files=workspace_snapshot.get("touched_files") or [],
            limit=4,
            exclude_trace_ids=[self.last_trace_id] if self.last_trace_id is not None else None,
        )
        workflow_priors = self.coding_log.summarize_workflow_priors(
            similar_traces,
            repo_root=self.repo_root,
            prompt=prompt,
            max_files=10,
        )
        workflow_plan = build_workflow_plan(
            candidates=similar_traces,
            summary=workflow_priors,
            prompt=prompt,
            repo_root=self.repo_root,
        )
        distilled_priors = _build_distilled_priors_block(similar_traces)
        workflow_priors_block = _build_workflow_priors_block(workflow_priors)
        workflow_plan_block = render_workflow_plan_block(workflow_plan)

        artifacts = self.ttt.on_user_message(
            session_id=self.session_id,
            user_id=self.user_id,
            user_text=prompt,
            base_system=CODING_BASE_SYSTEM + workflow_priors_block + workflow_plan_block + distilled_priors,
            top_k=self.top_k,
        )

        system_prompt = inject_reasoning_prompt(artifacts.built.system_prompt)
        messages = [
            ChatMessage(role="system", content=system_prompt),
            *self.history[-(self.max_history_turns * 2):],
            ChatMessage(role="user", content=prompt),
        ]
        answer = self.client.chat(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            num_ctx=self.num_ctx,
        ).strip()

        self.ttt.on_assistant_message(
            session_id=self.session_id,
            user_id=self.user_id,
            assistant_text=answer,
            meta={"retrieved_chunk_ids": [c.id for c in artifacts.retrieved]},
        )

        trajectory_id: Optional[int] = None
        if has_trajectory_format(answer):
            steps = parse_trajectory(answer)
            if steps:
                trajectory_id = self.traj_log.save(
                    Trajectory(
                        session_id=self.session_id,
                        user_id=self.user_id,
                        user_query=prompt,
                        steps=steps,
                        ts=int(time.time()),
                    )
                )

        trace_id = self.coding_log.save_trace(
            session_id=self.session_id,
            user_id=self.user_id,
            provider=self.client.provider,
            model=self.model,
            repo_root=self.repo_root,
            task_text=prompt,
            system_prompt=system_prompt,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            retrieved_chunk_ids=[c.id for c in artifacts.retrieved],
            trajectory_id=trajectory_id,
            assistant_text=answer,
            meta={
                "surface": "coding_proxy",
                "prior_trace_ids": [candidate.trace.id for candidate in similar_traces],
                "prior_trace_scores": {
                    str(candidate.trace.id): round(candidate.score, 4) for candidate in similar_traces
                },
                "suggested_files": list(workflow_plan.likely_files),
                "raw_suggested_files": list(workflow_priors.suggested_files),
                "suggested_commands": list(workflow_priors.suggested_commands),
                "likely_tests": list(workflow_plan.likely_tests),
                "patch_steps": list(workflow_plan.patch_steps),
                "constraint_tags": list(workflow_plan.constraint_tags),
                "transmutations": list(workflow_plan.transmutations),
                "role_targets": list(workflow_plan.role_targets),
            },
        )
        self.coding_log.update_trace_artifacts(
            trace_id=trace_id,
            meta={
                "workspace_vcs": workspace_snapshot.get("vcs", ""),
                "workspace_touched_files": list(workspace_snapshot.get("touched_files") or []),
                "workspace_patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        self.coding_log.append_event(
            trace_id=trace_id,
            event_type="workspace",
            event_name="workspace_snapshot",
            payload={
                "vcs": workspace_snapshot.get("vcs", ""),
                "touched_files": list(workspace_snapshot.get("touched_files") or []),
                "patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        self.coding_log.append_event(
            trace_id=trace_id,
            event_type="retrieval",
            event_name="retrieve_context",
            payload={
                "top_k": int(self.top_k),
                "retrieved_chunk_ids": [c.id for c in artifacts.retrieved],
                "retrieved_count": len(artifacts.retrieved),
            },
        )
        if similar_traces:
            self.coding_log.append_event(
                trace_id=trace_id,
                event_type="distillation",
                event_name="reuse_prior_traces",
                payload={
                    "candidate_count": len(similar_traces),
                    "trace_ids": [candidate.trace.id for candidate in similar_traces],
                    "scores": {
                        str(candidate.trace.id): round(candidate.score, 4) for candidate in similar_traces
                    },
                    "matched_terms": {
                        str(candidate.trace.id): candidate.matched_terms for candidate in similar_traces
                    },
                    "matched_files": {
                        str(candidate.trace.id): candidate.matched_files for candidate in similar_traces
                    },
                },
            )
        if workflow_priors.suggested_files or workflow_priors.suggested_commands:
            self.coding_log.append_event(
                trace_id=trace_id,
                event_type="distillation",
                event_name="distilled_workflow_priors",
                payload={
                    "trace_ids": list(workflow_priors.source_trace_ids),
                    "suggested_files": list(workflow_priors.suggested_files),
                    "suggested_commands": list(workflow_priors.suggested_commands),
                },
            )
        if workflow_plan.patch_steps or workflow_plan.likely_tests:
            self.coding_log.append_event(
                trace_id=trace_id,
                event_type="distillation",
                event_name="workflow_plan",
                payload={
                    "trace_ids": list(workflow_plan.source_trace_ids),
                    "likely_files": list(workflow_plan.likely_files),
                    "likely_commands": list(workflow_plan.likely_commands),
                    "likely_tests": list(workflow_plan.likely_tests),
                    "patch_steps": list(workflow_plan.patch_steps),
                    "constraint_tags": list(workflow_plan.constraint_tags),
                    "transmutations": list(workflow_plan.transmutations),
                    "role_targets": list(workflow_plan.role_targets),
                },
            )
        self.coding_log.append_event(
            trace_id=trace_id,
            event_type="model",
            event_name="teacher_chat",
            payload={
                "provider": self.client.provider,
                "model": self.model,
                "temperature": float(self.temperature),
                "trajectory_id": trajectory_id,
            },
        )
        test_result: Optional[dict[str, object]] = None
        if test_command and test_command.strip():
            test_result = _run_test_command(command=test_command.strip(), repo_root=self.repo_root)
            self.coding_log.update_trace_artifacts(
                trace_id=trace_id,
                tests=[test_result],
                meta={"auto_test_command": test_command.strip()},
            )
            self.coding_log.append_event(
                trace_id=trace_id,
                event_type="command",
                event_name="test_run",
                payload=test_result,
            )

        self.history.append(ChatMessage(role="user", content=prompt))
        self.history.append(ChatMessage(role="assistant", content=answer))
        self.last_trace_id = trace_id
        return ProxyResult(
            answer=answer,
            trace_id=trace_id,
            trajectory_id=trajectory_id,
            retrieved_chunk_ids=[c.id for c in artifacts.retrieved],
            test_result=test_result,
            prior_trace_ids=[candidate.trace.id for candidate in similar_traces],
            suggested_files=list(workflow_plan.likely_files),
            suggested_commands=list(workflow_priors.suggested_commands),
            likely_tests=list(workflow_plan.likely_tests),
            patch_steps=list(workflow_plan.patch_steps),
            constraint_tags=list(workflow_plan.constraint_tags),
            transmutations=list(workflow_plan.transmutations),
            role_targets=list(workflow_plan.role_targets),
        )

    def mark_feedback(self, *, is_positive: bool, note: str = "") -> bool:
        ok = self.ttt.explicit_feedback(is_positive=is_positive)
        if not ok or self.last_trace_id is None:
            return False
        workspace_snapshot = capture_workspace_state(self.repo_root)
        self.coding_log.update_trace_artifacts(
            trace_id=self.last_trace_id,
            touched_files=workspace_snapshot.get("touched_files") or None,
            patch_text=str(workspace_snapshot.get("patch_text") or ""),
            meta={
                "workspace_vcs": workspace_snapshot.get("vcs", ""),
                "workspace_touched_files": list(workspace_snapshot.get("touched_files") or []),
                "workspace_patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        self.coding_log.append_event(
            trace_id=self.last_trace_id,
            event_type="workspace",
            event_name="feedback_workspace_snapshot",
            payload={
                "vcs": workspace_snapshot.get("vcs", ""),
                "touched_files": list(workspace_snapshot.get("touched_files") or []),
                "patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        self.coding_log.mark_feedback(
            trace_id=self.last_trace_id,
            is_positive=is_positive,
            note=note,
            meta={"surface": "coding_proxy"},
        )
        self.coding_log.append_event(
            trace_id=self.last_trace_id,
            event_type="feedback",
            event_name="accept" if is_positive else "reject",
            payload={"note": note},
        )
        return True

    def run_command(self, command: str, *, timeout_seconds: int = 300) -> Optional[ShellCommandResult]:
        if self.last_trace_id is None:
            return None
        result = _run_shell_command(command=command, repo_root=self.repo_root, timeout_seconds=timeout_seconds)
        self.coding_log.append_event(
            trace_id=self.last_trace_id,
            event_type="command",
            event_name="shell_run",
            payload={
                "command": result.command,
                "status": result.status,
                "returncode": result.returncode,
                "stdout_tail": result.stdout_tail,
                "stderr_tail": result.stderr_tail,
            },
        )
        workspace_snapshot = capture_workspace_state(self.repo_root)
        self.coding_log.update_trace_artifacts(
            trace_id=self.last_trace_id,
            touched_files=workspace_snapshot.get("touched_files") or None,
            patch_text=str(workspace_snapshot.get("patch_text") or ""),
            meta={
                "last_shell_command": result.command,
                "last_shell_status": result.status,
                "workspace_vcs": workspace_snapshot.get("vcs", ""),
                "workspace_touched_files": list(workspace_snapshot.get("touched_files") or []),
                "workspace_patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        self.coding_log.append_event(
            trace_id=self.last_trace_id,
            event_type="workspace",
            event_name="post_command_workspace_snapshot",
            payload={
                "command": result.command,
                "vcs": workspace_snapshot.get("vcs", ""),
                "touched_files": list(workspace_snapshot.get("touched_files") or []),
                "patch_chars": len(str(workspace_snapshot.get("patch_text") or "")),
            },
        )
        return result


def run_proxy_once(
    *,
    prompt: str,
    model: str,
    db_path: str,
    user_id: str,
    repo_root: str,
    temperature: float = 0.1,
    top_k: int = 12,
    num_ctx: int | None = None,
    test_command: Optional[str] = None,
    session_id: Optional[str] = None,
) -> ProxyResult:
    session = CodingSession(
        model=model,
        db_path=db_path,
        user_id=user_id,
        repo_root=repo_root,
        temperature=temperature,
        top_k=top_k,
        num_ctx=num_ctx,
        session_id=session_id,
    )
    try:
        return session.ask(prompt, test_command=test_command)
    finally:
        session.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="First-pass coding proxy for Memla distillation.")
    parser.add_argument("prompt", nargs="?", default="")
    parser.add_argument("--model", default=os.environ.get("OLLAMA_MODEL", "qwen3.5:4b"))
    parser.add_argument("--db", default=os.environ.get("MEMORY_DB", "./memory.sqlite"))
    parser.add_argument("--user_id", default=os.environ.get("USER_ID", "default"))
    parser.add_argument("--repo_root", default=os.getcwd())
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--top_k", type=int, default=12)
    parser.add_argument("--num_ctx", type=int, default=int(os.environ["OLLAMA_NUM_CTX"]) if "OLLAMA_NUM_CTX" in os.environ else None)
    parser.add_argument("--test_cmd", default="")
    parser.add_argument("--interactive", action="store_true")
    parser.add_argument("--plan_only", action="store_true")
    args = parser.parse_args(argv)

    prompt = args.prompt.strip()
    interactive = bool(args.interactive or not prompt)

    if args.plan_only:
        session = CodingSession(
            model=args.model,
            db_path=args.db,
            user_id=args.user_id,
            repo_root=args.repo_root,
            temperature=args.temperature,
            top_k=args.top_k,
            num_ctx=args.num_ctx,
        )
        try:
            plan = session.build_plan(prompt)
        finally:
            session.close()
        print(render_workflow_plan_block(plan).strip())
        return 0

    if not interactive:
        result = run_proxy_once(
            prompt=prompt,
            model=args.model,
            db_path=args.db,
            user_id=args.user_id,
            repo_root=args.repo_root,
            temperature=args.temperature,
            top_k=args.top_k,
            num_ctx=args.num_ctx,
            test_command=args.test_cmd or None,
        )
        print(result.answer)
        print()
        if result.test_result:
            print(f"[coding_proxy] test {result.test_result['status']} rc={result.test_result['returncode']}: {result.test_result['command']}")
        if result.suggested_files or result.suggested_commands or result.likely_tests or result.patch_steps:
            print(f"[coding_proxy] suggested_files={result.suggested_files} suggested_commands={result.suggested_commands}")
            print(f"[coding_proxy] likely_tests={result.likely_tests} patch_steps={result.patch_steps}")
        print(f"[coding_proxy] trace_id={result.trace_id} trajectory_id={result.trajectory_id} retrieved={result.retrieved_chunk_ids}")
        return 0

    session = CodingSession(
        model=args.model,
        db_path=args.db,
        user_id=args.user_id,
        repo_root=args.repo_root,
        temperature=args.temperature,
        top_k=args.top_k,
        num_ctx=args.num_ctx,
    )
    print(f"[coding_proxy] session_id={session.session_id} model={args.model} repo={session.repo_root}")
    print("[coding_proxy] Commands: /good, /bad, /test <cmd>, /run <cmd>, /exit")
    pending_test_cmd = args.test_cmd.strip()
    try:
        while True:
            raw = input("coding> ").strip()
            if not raw:
                continue
            if raw == "/exit":
                break
            if raw == "/good":
                print("[coding_proxy] accepted" if session.mark_feedback(is_positive=True) else "[coding_proxy] no trace to accept")
                continue
            if raw == "/bad":
                print("[coding_proxy] rejected" if session.mark_feedback(is_positive=False) else "[coding_proxy] no trace to reject")
                continue
            if raw.startswith("/test "):
                pending_test_cmd = raw[6:].strip()
                print(f"[coding_proxy] next test command set: {pending_test_cmd}")
                continue
            if raw.startswith("/run "):
                result = session.run_command(raw[5:].strip())
                if result is None:
                    print("[coding_proxy] no trace yet; ask a coding question first")
                else:
                    print(f"[coding_proxy] shell {result.status} rc={result.returncode}: {result.command}")
                    if result.stdout_tail:
                        print(result.stdout_tail)
                    if result.stderr_tail:
                        print(result.stderr_tail)
                continue

            result = session.ask(raw, test_command=pending_test_cmd or None)
            print(result.answer)
            print()
            if result.test_result:
                print(f"[coding_proxy] test {result.test_result['status']} rc={result.test_result['returncode']}: {result.test_result['command']}")
            print(f"[coding_proxy] trace_id={result.trace_id} trajectory_id={result.trajectory_id} retrieved={result.retrieved_chunk_ids}")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
