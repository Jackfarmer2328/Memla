from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from memory_system.distillation.coding_log import CodingTrace, CodingTraceLog, SimilarCodingTrace, WorkflowPriorSummary
from memory_system.distillation.comparison_runner import render_head_to_head_markdown, run_head_to_head
from memory_system.distillation.coding_proxy import CodingSession, run_proxy_once
from memory_system.distillation.demo_runner import render_demo_markdown, run_bootstrap_demo, run_showcase_demo
from memory_system.distillation.eval_harness import PlanEvalCase, evaluate_workflow_plans
from memory_system.distillation.exporter import export_accepted_traces_to_jsonl
from memory_system.distillation.acquisition_pack_builder import (
    build_acquisition_pack,
    render_acquisition_demo_flow,
    render_acquisition_pitch,
)
from memory_system.distillation.diligence_packet_builder import (
    build_diligence_packet,
    render_diligence_faq,
    render_diligence_summary,
    render_proof_table,
    render_technical_diligence,
)
from memory_system.distillation.pitch_pack_builder import (
    build_pitch_pack,
    render_demo_flow,
    render_one_sentence_pitch,
)
from memory_system.distillation.seed_runner import (
    SeedCase,
    _extract_answer_commands,
    _extract_answer_files,
    run_seed_cases,
)
from memory_system.distillation.workflow_planner import build_workflow_plan, render_workflow_plan_block
from memory_system.distillation.workspace_capture import capture_workspace_state
from memory_system.memory.episode_log import EpisodeLog


def test_coding_trace_log_persists_trace_and_feedback(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    trace_id = coding_log.save_trace(
        session_id="sess_1",
        user_id="coder",
        provider="anthropic",
        model="teacher-model",
        repo_root=str(tmp_path),
        task_text="Fix failing serializer test",
        system_prompt="You are a coding assistant.",
        messages=[
            {"role": "system", "content": "You are a coding assistant."},
            {"role": "user", "content": "Fix the serializer bug."},
        ],
        retrieved_chunk_ids=[1, 2, 3],
        trajectory_id=7,
        assistant_text="Patch the serializer and add a regression test.",
        meta={"surface": "cli"},
    )

    coding_log.mark_feedback(trace_id=trace_id, is_positive=True, meta={"accepted": True})

    recent = coding_log.fetch_recent(user_id="coder", limit=5)
    assert len(recent) == 1
    trace = recent[0]
    assert trace.id == trace_id
    assert trace.provider == "anthropic"
    assert trace.model == "teacher-model"
    assert trace.trajectory_id == 7
    assert trace.retrieved_chunk_ids == [1, 2, 3]
    assert trace.touched_files == []
    assert trace.status == "accepted"
    assert trace.acceptance_score == 1.0
    assert trace.meta["surface"] == "cli"


def test_coding_trace_log_returns_only_accepted_training_candidates(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    accepted_id = coding_log.save_trace(
        session_id="sess_a",
        user_id="coder",
        provider="openai",
        model="teacher-a",
        repo_root=str(tmp_path),
        task_text="Accepted task",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="good",
    )
    rejected_id = coding_log.save_trace(
        session_id="sess_b",
        user_id="coder",
        provider="openai",
        model="teacher-b",
        repo_root=str(tmp_path),
        task_text="Rejected task",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="bad",
    )

    coding_log.mark_feedback(trace_id=accepted_id, is_positive=True)
    coding_log.mark_feedback(trace_id=rejected_id, is_positive=False)

    candidates = coding_log.fetch_training_candidates(user_id="coder", limit=10)
    assert [trace.id for trace in candidates] == [accepted_id]


def test_coding_trace_log_finds_similar_accepted_traces(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    winner_id = coding_log.save_trace(
        session_id="sess_match",
        user_id="coder",
        provider="openai",
        model="teacher-a",
        repo_root=str(tmp_path),
        task_text="Fix serializer regression and update API contract test",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="Patch the serializer, preserve the API contract, and add a regression test.",
        touched_files=["src/serializer.py", "tests/test_api_contract.py"],
        tests=[{"command": "pytest -q", "status": "passed"}],
    )
    coding_log.mark_feedback(trace_id=winner_id, is_positive=True)

    weak_id = coding_log.save_trace(
        session_id="sess_weak",
        user_id="coder",
        provider="openai",
        model="teacher-b",
        repo_root=str(tmp_path),
        task_text="Refactor dashboard styles",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="Update the CSS module.",
        touched_files=["web/dashboard.css"],
    )
    coding_log.mark_feedback(trace_id=weak_id, is_positive=True)

    matches = coding_log.find_similar_accepted_traces(
        user_id="coder",
        repo_root=str(tmp_path),
        task_text="Fix serializer API contract failure",
        touched_files=["src/serializer.py"],
        limit=3,
    )

    assert matches
    assert matches[0].trace.id == winner_id
    assert "serializer" in matches[0].matched_terms
    assert "serializer" in matches[0].matched_files
    if len(matches) > 1:
        assert matches[0].score > matches[-1].score


def test_coding_trace_log_summarizes_workflow_priors(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    trace_id = coding_log.save_trace(
        session_id="sess_summary",
        user_id="coder",
        provider="openai",
        model="teacher",
        repo_root=str(tmp_path),
        task_text="Fix serializer regression",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="Patch the serializer.",
        touched_files=["src/serializer.py", "tests/test_serializer.py"],
        tests=[{"command": "pytest -q tests/test_serializer.py", "status": "passed"}],
    )
    coding_log.mark_feedback(trace_id=trace_id, is_positive=True)
    coding_log.append_event(
        trace_id=trace_id,
        event_type="command",
        event_name="shell_run",
        payload={"command": "rg serializer src tests", "status": "passed"},
    )
    coding_log.update_trace_artifacts(
        trace_id=trace_id,
        meta={
            "teacher_answer_files": ["memory_system/distillation/workflow_planner.py"],
            "teacher_answer_commands": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
            "seed_expected_files": ["memory_system/distillation/coding_proxy.py"],
            "seed_expected_commands": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
        },
    )

    candidates = coding_log.find_similar_accepted_traces(
        user_id="coder",
        repo_root=str(tmp_path),
        task_text="Fix serializer API regression",
        touched_files=["src/serializer.py"],
        limit=3,
    )
    summary = coding_log.summarize_workflow_priors(candidates)

    assert "src/serializer.py" in summary.suggested_files
    assert "memory_system/distillation/workflow_planner.py" in summary.suggested_files
    assert "memory_system/distillation/coding_proxy.py" in summary.suggested_files
    assert "pytest -q tests/test_serializer.py" in summary.suggested_commands
    assert "py -3 -m pytest -q tests/test_step6_coding_distillation.py" in summary.suggested_commands
    assert "rg serializer src tests" in summary.suggested_commands
    assert trace_id in summary.source_trace_ids

    plan = build_workflow_plan(candidates=candidates, summary=summary)
    assert "src/serializer.py" in plan.likely_files
    assert "pytest -q tests/test_serializer.py" in plan.likely_tests
    block = render_workflow_plan_block(plan)
    assert "MEMLA WORKFLOW PLAN" in block
    assert "Likely files:" in block
    assert "Likely patch plan:" in block


def test_workflow_plan_reranks_files_by_prompt():
    summary = WorkflowPriorSummary(
        suggested_files=[
            "memory_system/distillation/exporter.py",
            "memory_system/distillation/workflow_planner.py",
            "memory_system/distillation/coding_proxy.py",
            "tests/test_step6_coding_distillation.py",
        ],
        suggested_commands=["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
        source_trace_ids=[1],
    )
    plan = build_workflow_plan(
        candidates=[],
        summary=summary,
        prompt="Update the workflow planner and coding proxy before running tests.",
    )

    assert plan.likely_files[0] == "memory_system/distillation/workflow_planner.py"
    assert "memory_system/distillation/coding_proxy.py" in plan.likely_files[:2]
    assert "py -3 -m pytest -q tests/test_step6_coding_distillation.py" in plan.likely_tests


def test_coding_trace_log_prefers_seed_files_and_filters_generic_teacher_spillover(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.jsx").write_text("", encoding="utf-8")
    (tmp_path / "src" / "CheckoutReturnPage.jsx").write_text("", encoding="utf-8")
    (tmp_path / "src" / "main.jsx").write_text("", encoding="utf-8")
    (tmp_path / "index.html").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    db_path = tmp_path / "spillover.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    trace_id = coding_log.save_trace(
        session_id="sess_frontend",
        user_id="coder",
        provider="openai",
        model="teacher",
        repo_root=str(tmp_path),
        task_text="Refactor booking completion flow to pass real guest data through checkout return",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="[Output] Update the booking flow and keep the return page in sync.",
        touched_files=["src/App.jsx", "src/CheckoutReturnPage.jsx"],
        tests=[{"command": "npm run build", "status": "passed"}],
    )
    coding_log.mark_feedback(trace_id=trace_id, is_positive=True)
    coding_log.update_trace_artifacts(
        trace_id=trace_id,
        meta={
            "seed_expected_files": ["src/App.jsx", "src/CheckoutReturnPage.jsx"],
            "teacher_answer_files": ["index.html", "package.json", "src/main.jsx", "src/App.jsx"],
            "seed_expected_commands": ["npm run build", "npm run lint"],
            "teacher_answer_commands": [
                "npm run build",
                "npm install react@latest react-dom@latest react-router-dom@latest",
                "npm install",
            ],
        },
    )

    candidates = coding_log.find_similar_accepted_traces(
        user_id="coder",
        repo_root=str(tmp_path),
        task_text="Refactor the booking completion handler to pass real PMS confirmation codes and guest data.",
        touched_files=["src/App.jsx"],
        limit=3,
    )
    summary = coding_log.summarize_workflow_priors(
        candidates,
        repo_root=str(tmp_path),
        prompt="Refactor the booking completion handler to pass real PMS confirmation codes and guest data.",
    )

    assert summary.suggested_files[:2] == ["src/App.jsx", "src/CheckoutReturnPage.jsx"]
    assert "index.html" not in summary.suggested_files
    assert "package.json" not in summary.suggested_files
    assert "src/main.jsx" not in summary.suggested_files
    assert "npm run build" in summary.suggested_commands
    assert "npm run lint" in summary.suggested_commands
    assert not any(command.startswith("npm install") for command in summary.suggested_commands)


def test_workflow_plan_ignores_latest_install_noise_and_irrelevant_patch_steps():
    summary = WorkflowPriorSummary(
        suggested_files=["src/App.jsx", "src/CheckoutReturnPage.jsx"],
        suggested_commands=[
            "npm run build",
            "npm install react@latest react-dom@latest react-router-dom@latest",
            "npm test",
        ],
        source_trace_ids=[1],
    )
    irrelevant_candidate = SimilarCodingTrace(
        trace=CodingTrace(
            id=1,
            created_ts=1,
            session_id="sess_1",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root="repo",
            task_text="Remove the Hotjar tracking script from the HTML file.",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            trajectory_id=None,
            assistant_text="[Output] Remove the Hotjar script from index.html and check public/index.html.",
            touched_files=["index.html"],
            patch_text="",
            tests=[],
            status="accepted",
            acceptance_score=1.0,
            meta={},
        ),
        score=0.2,
        matched_terms=[],
        matched_files=[],
    )

    plan = build_workflow_plan(
        candidates=[irrelevant_candidate],
        summary=summary,
        prompt="Pass guest data and PMS confirmation codes through the checkout return flow.",
    )

    assert plan.likely_tests == ["npm run build", "npm test"]
    assert plan.patch_steps == []


def test_run_showcase_demo_uses_eval_report(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.evaluate_workflow_plans",
        lambda **kwargs: {
            "cases": 1,
            "avg_file_recall": 1.0,
            "avg_command_recall": 1.0,
            "rows": [
                {
                    "prompt": "Fix serializer",
                    "predicted_files": ["src/serializer.py"],
                    "predicted_commands": ["pytest -q tests/test_serializer.py"],
                    "predicted_tests": ["pytest -q tests/test_serializer.py"],
                    "patch_steps": ["Patch serializer", "Run tests"],
                    "expected_files": ["src/serializer.py"],
                    "expected_commands": ["pytest -q tests/test_serializer.py"],
                    "file_recall": 1.0,
                    "command_recall": 1.0,
                }
            ],
        },
    )
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.load_eval_cases",
        lambda path: [PlanEvalCase(prompt="Fix serializer", expected_files=["src/serializer.py"], expected_commands=["pytest -q tests/test_serializer.py"])],
    )

    summary = run_showcase_demo(
        db_path=str(tmp_path / "demo.sqlite"),
        repo_root=str(tmp_path),
        user_id="coder",
        cases_path="demo_cases.jsonl",
        planner_model="qwen3.5:4b",
    )

    assert summary.mode == "showcase"
    assert summary.baseline is None
    assert summary.final_report["avg_file_recall"] == 1.0
    md = render_demo_markdown(summary)
    assert "Memla Coding Distillation Demo" in md
    assert "File recall: `1.0`" in md
    assert "Fix serializer" in md


def test_run_bootstrap_demo_stages_reports(monkeypatch, tmp_path):
    eval_calls = iter(
        [
            {"cases": 1, "avg_file_recall": 0.0, "avg_command_recall": 0.0, "rows": []},
            {"cases": 1, "avg_file_recall": 0.6, "avg_command_recall": 1.0, "rows": []},
            {"cases": 1, "avg_file_recall": 1.0, "avg_command_recall": 1.0, "rows": []},
        ]
    )
    seed_calls = iter(
        [
            {"cases": 5, "accepted": 3, "accept_rate": 0.6, "avg_file_recall": 0.8, "avg_command_recall": 0.4, "rows": []},
            {"cases": 1, "accepted": 1, "accept_rate": 1.0, "avg_file_recall": 1.0, "avg_command_recall": 1.0, "rows": []},
        ]
    )
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.evaluate_workflow_plans",
        lambda **kwargs: next(eval_calls),
    )
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.run_seed_cases",
        lambda **kwargs: next(seed_calls),
    )
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.load_eval_cases",
        lambda path: [PlanEvalCase(prompt="Fix serializer", expected_files=["src/serializer.py"], expected_commands=["pytest -q tests/test_serializer.py"])],
    )
    monkeypatch.setattr(
        "memory_system.distillation.demo_runner.load_seed_cases",
        lambda path: [SeedCase(prompt="Fix serializer", expected_files=["src/serializer.py"], expected_commands=["pytest -q tests/test_serializer.py"])],
    )

    summary = run_bootstrap_demo(
        db_path=str(tmp_path / "demo.sqlite"),
        repo_root=str(tmp_path),
        user_id="coder",
        holdout_cases_path="holdout.jsonl",
        bootstrap_cases_path="bootstrap.jsonl",
        refinement_cases_path="repair.jsonl",
        teacher_model="claude-sonnet-4-20250514",
        planner_model="qwen3.5:4b",
    )

    assert summary.mode == "bootstrap"
    assert summary.baseline["avg_file_recall"] == 0.0
    assert summary.bootstrap_seed["accept_rate"] == 0.6
    assert summary.after_bootstrap["avg_file_recall"] == 0.6
    assert summary.refinement_seed["accept_rate"] == 1.0
    assert summary.final_report["avg_file_recall"] == 1.0


def test_run_head_to_head_compares_raw_and_memla(monkeypatch, tmp_path):
    class DummyClient:
        def __init__(self):
            self.provider = "anthropic"

        def chat(self, **kwargs):
            return (
                "Update `memory_system/distillation/coding_proxy.py` and "
                "`tests/test_step6_coding_distillation.py`.\n\n"
                "`py -3 -m pytest -q tests/test_step6_coding_distillation.py`"
            )

    class DummySession:
        def __init__(self, **kwargs):
            self.calls = []

        def ask(self, prompt, **kwargs):
            self.calls.append(prompt)
            return type(
                "ProxyResult",
                (),
                {
                    "answer": "Touch `memory_system/distillation/coding_log.py` and `memory_system/distillation/coding_proxy.py`.",
                    "suggested_files": [
                        "memory_system/distillation/coding_log.py",
                        "memory_system/distillation/coding_proxy.py",
                        "tests/test_step6_coding_distillation.py",
                    ],
                    "suggested_commands": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
                    "likely_tests": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
                    "patch_steps": ["Patch coding log", "Patch coding proxy"],
                    "prior_trace_ids": [7, 8],
                },
            )()

        def close(self):
            return None

    monkeypatch.setattr(
        "memory_system.distillation.comparison_runner.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )
    monkeypatch.setattr(
        "memory_system.distillation.comparison_runner.CodingSession",
        lambda **kwargs: DummySession(**kwargs),
    )
    monkeypatch.setattr(
        "memory_system.distillation.comparison_runner.load_eval_cases",
        lambda path: [
            PlanEvalCase(
                prompt="Use accepted coding traces to supply repo-specific priors to the teacher.",
                expected_files=[
                    "memory_system/distillation/coding_log.py",
                    "memory_system/distillation/coding_proxy.py",
                    "tests/test_step6_coding_distillation.py",
                ],
                expected_commands=["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
            )
        ],
    )

    report = run_head_to_head(
        db_path=str(tmp_path / "demo.sqlite"),
        repo_root=str(tmp_path),
        user_id="coder",
        cases_path="holdout.jsonl",
        teacher_model="claude-sonnet-4-20250514",
    )

    assert report["avg_raw_file_recall"] < report["avg_memla_combined_file_recall"]
    assert report["avg_memla_combined_command_recall"] == 1.0
    md = render_head_to_head_markdown(report)
    assert "Memla Head-to-Head Coding Demo" in md
    assert "Raw teacher file recall" in md
    assert "Memla in front" in md


def test_coding_trace_log_updates_artifacts(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    trace_id = coding_log.save_trace(
        session_id="sess_artifacts",
        user_id="coder",
        provider="openai",
        model="teacher",
        repo_root=str(tmp_path),
        task_text="Add a patch",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="patch it",
    )
    coding_log.update_trace_artifacts(
        trace_id=trace_id,
        touched_files=["src/app.py", "tests/test_app.py"],
        patch_text="diff --git a/src/app.py b/src/app.py",
        tests=[{"command": "pytest -q", "status": "passed"}],
        meta={"workspace_vcs": "git"},
    )

    trace = coding_log.fetch_recent(user_id="coder", limit=1)[0]
    assert trace.touched_files == ["src/app.py", "tests/test_app.py"]
    assert "diff --git" in trace.patch_text
    assert trace.tests[0]["status"] == "passed"
    assert trace.meta["workspace_vcs"] == "git"


def test_capture_workspace_state_git_repo(tmp_path):
    git = shutil.which("git")
    if not git:
        return

    subprocess.run([git, "init"], cwd=tmp_path, check=True, capture_output=True, text=True)
    subprocess.run([git, "config", "user.email", "memla@example.com"], cwd=tmp_path, check=True)
    subprocess.run([git, "config", "user.name", "Memla"], cwd=tmp_path, check=True)

    tracked = tmp_path / "hello.py"
    tracked.write_text("print('hello')\n", encoding="utf-8")
    subprocess.run([git, "add", "hello.py"], cwd=tmp_path, check=True)
    subprocess.run([git, "commit", "-m", "init"], cwd=tmp_path, check=True, capture_output=True, text=True)

    tracked.write_text("print('goodbye')\n", encoding="utf-8")
    untracked = tmp_path / "notes.txt"
    untracked.write_text("todo\n", encoding="utf-8")

    snapshot = capture_workspace_state(tmp_path)
    assert snapshot["vcs"] == "git"
    assert "hello.py" in snapshot["touched_files"]
    assert "notes.txt" in snapshot["touched_files"]
    assert "diff --git" in snapshot["patch_text"]


def test_coding_proxy_once_records_trace(monkeypatch, tmp_path):
    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] inspect memory\n[Output] Patch serializer and run pytest -q"

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )

    result = run_proxy_once(
        prompt="Fix serializer bug",
        model="teacher",
        db_path=str(tmp_path / "proxy.sqlite"),
        user_id="coder",
        repo_root=str(tmp_path),
    )
    assert result.trace_id > 0
    assert result.trajectory_id is not None
    assert "Patch serializer" in result.answer


def test_coding_trace_log_stores_workflow_events(tmp_path):
    db_path = tmp_path / "coding_distill.sqlite"
    log = EpisodeLog(db_path)
    coding_log = CodingTraceLog(log._conn)

    trace_id = coding_log.save_trace(
        session_id="sess_events",
        user_id="coder",
        provider="openai",
        model="teacher",
        repo_root=str(tmp_path),
        task_text="Trace events",
        system_prompt="sys",
        messages=[],
        retrieved_chunk_ids=[],
        assistant_text="ok",
    )
    coding_log.append_event(
        trace_id=trace_id,
        event_type="retrieval",
        event_name="retrieve_context",
        payload={"retrieved_count": 3},
    )
    coding_log.append_event(
        trace_id=trace_id,
        event_type="command",
        event_name="test_run",
        payload={"status": "passed"},
    )

    events = coding_log.fetch_events(trace_id=trace_id)
    assert [event.event_name for event in events] == ["retrieve_context", "test_run"]
    assert events[0].payload["retrieved_count"] == 3
    assert events[1].payload["status"] == "passed"


def test_coding_proxy_once_can_attach_test_command(monkeypatch, tmp_path):
    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] inspect memory\n[Output] Run the tests after patching."

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )

    result = run_proxy_once(
        prompt="Fix serializer bug",
        model="teacher",
        db_path=str(tmp_path / "proxy_with_tests.sqlite"),
        user_id="coder",
        repo_root=str(tmp_path),
        test_command=f"py -3 -c \"print('ok')\"",
    )

    assert result.test_result is not None
    assert result.test_result["status"] == "passed"

    log = EpisodeLog(tmp_path / "proxy_with_tests.sqlite")
    try:
        coding_log = CodingTraceLog(log._conn)
        trace = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert trace.tests[0]["status"] == "passed"
        events = coding_log.fetch_events(trace_id=trace.id)
        assert any(event.event_name == "test_run" for event in events)
    finally:
        log.close()


def test_coding_proxy_reuses_accepted_trace_priors(monkeypatch, tmp_path):
    db_path = tmp_path / "proxy_priors.sqlite"
    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        prior_id = coding_log.save_trace(
            session_id="sess_prior",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(tmp_path),
            task_text="Fix serializer bug and preserve API contract",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            assistant_text="[Output] Patch the serializer first, keep the API contract stable, and add a regression test.",
            touched_files=["src/serializer.py", "tests/test_serializer.py"],
            tests=[{"command": "pytest -q", "status": "passed"}],
        )
        coding_log.mark_feedback(trace_id=prior_id, is_positive=True)
        coding_log.append_event(
            trace_id=prior_id,
            event_type="command",
            event_name="shell_run",
            payload={"command": "pytest -q tests/test_serializer.py", "status": "passed"},
        )
    finally:
        log.close()

    class DummyClient:
        provider = "openai"

        def __init__(self):
            self.seen_system_prompts = []

        def chat(self, **kwargs):
            system_message = kwargs["messages"][0]["content"] if isinstance(kwargs["messages"][0], dict) else kwargs["messages"][0].content
            self.seen_system_prompts.append(system_message)
            return "[Thought] use distilled priors\n[Output] Update the serializer and run the serializer regression test."

    dummy = DummyClient()
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: dummy,
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )

    result = run_proxy_once(
        prompt="Fix serializer API contract failure",
        model="teacher",
        db_path=str(db_path),
        user_id="coder",
        repo_root=str(tmp_path),
    )

    assert result.trace_id > 0
    assert result.prior_trace_ids == [prior_id]
    assert "src/serializer.py" in (result.suggested_files or [])
    assert "pytest -q" in " ".join(result.suggested_commands or [])
    assert "pytest -q" in " ".join(result.likely_tests or [])
    assert result.patch_steps
    assert dummy.seen_system_prompts
    system_prompt = dummy.seen_system_prompts[0]
    assert "DISTILLED WORKFLOW PRIORS" in system_prompt
    assert "Likely files to inspect first:" in system_prompt
    assert "src/serializer.py" in system_prompt
    assert "Likely commands to run:" in system_prompt
    assert "MEMLA WORKFLOW PLAN" in system_prompt
    assert "Likely patch plan:" in system_prompt
    assert "DISTILLED CODING PRIORS" in system_prompt
    assert "Prior task: Fix serializer bug and preserve API contract" in system_prompt
    assert "Accepted solution pattern: Patch the serializer first" in system_prompt

    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        latest = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert prior_id in latest.meta["prior_trace_ids"]
        assert "src/serializer.py" in latest.meta["suggested_files"]
        assert latest.meta["likely_tests"]
        assert latest.meta["patch_steps"]
        events = coding_log.fetch_events(trace_id=latest.id)
        reuse_events = [event for event in events if event.event_name == "reuse_prior_traces"]
        assert reuse_events
        assert reuse_events[0].payload["trace_ids"] == [prior_id]
        workflow_events = [event for event in events if event.event_name == "distilled_workflow_priors"]
        assert workflow_events
        assert "src/serializer.py" in workflow_events[0].payload["suggested_files"]
        plan_events = [event for event in events if event.event_name == "workflow_plan"]
        assert plan_events
        assert plan_events[0].payload["likely_tests"]
    finally:
        log.close()


def test_evaluate_workflow_plans_scores_expected_overlap(monkeypatch, tmp_path):
    db_path = tmp_path / "plan_eval.sqlite"
    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        trace_id = coding_log.save_trace(
            session_id="sess_eval",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(tmp_path),
            task_text="Fix serializer API bug",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            assistant_text="[Output] Patch the serializer, preserve the API contract, and run the serializer tests.",
            touched_files=["src/serializer.py", "tests/test_serializer.py"],
            tests=[{"command": "pytest -q tests/test_serializer.py", "status": "passed"}],
        )
        coding_log.mark_feedback(trace_id=trace_id, is_positive=True)
        coding_log.append_event(
            trace_id=trace_id,
            event_type="command",
            event_name="shell_run",
            payload={"command": "pytest -q tests/test_serializer.py", "status": "passed"},
        )
    finally:
        log.close()

    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] n/a\n[Output] n/a"

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {"vcs": "git", "touched_files": [], "patch_text": ""},
    )

    report = evaluate_workflow_plans(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="coder",
        cases=[
            PlanEvalCase(
                prompt="Fix serializer API contract failure",
                expected_files=["src/serializer.py"],
                expected_commands=["pytest -q tests/test_serializer.py"],
            )
        ],
        model="teacher",
    )

    assert report["cases"] == 1
    assert report["avg_file_recall"] == 1.0
    assert report["avg_command_recall"] == 1.0
    assert set(report["rows"][0]["predicted_files"]) == {"src/serializer.py", "tests/test_serializer.py"}


def test_run_seed_cases_auto_accepts_matching_case(monkeypatch, tmp_path):
    db_path = tmp_path / "seed.sqlite"
    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        prior_id = coding_log.save_trace(
            session_id="sess_seed_prior",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(tmp_path),
            task_text="Add workflow planner for serializer tasks",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            assistant_text="[Output] Update the workflow planner and run the distillation tests.",
            touched_files=["memory_system/distillation/workflow_planner.py", "tests/test_step6_coding_distillation.py"],
            tests=[{"command": "py -3 -m pytest -q tests/test_step6_coding_distillation.py", "status": "passed"}],
        )
        coding_log.mark_feedback(trace_id=prior_id, is_positive=True)
        coding_log.append_event(
            trace_id=prior_id,
            event_type="command",
            event_name="shell_run",
            payload={"command": "py -3 -m pytest -q tests/test_step6_coding_distillation.py", "status": "passed"},
        )
    finally:
        log.close()

    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] use prior planner work\n[Output] Touch the workflow planner and run the distillation tests."

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {"vcs": "git", "touched_files": [], "patch_text": ""},
    )

    report = run_seed_cases(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="coder",
        model="teacher",
        cases=[
            SeedCase(
                prompt="Add workflow planner for serializer tasks",
                expected_files=["memory_system/distillation/workflow_planner.py"],
                expected_commands=["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
            )
        ],
        accept_threshold=0.5,
    )

    assert report["cases"] == 1
    assert report["accepted"] == 1
    assert report["avg_command_recall"] == 1.0
    assert report["rows"][0]["prior_trace_ids"] == [prior_id]

    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        latest = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert latest.status == "accepted"
        assert latest.meta["teacher_answer_files"]
        assert latest.meta["teacher_answer_commands"]
        assert latest.meta["seed_expected_files"] == ["memory_system/distillation/workflow_planner.py"]
        assert latest.meta["seed_expected_commands"] == ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"]
    finally:
        log.close()


def test_run_seed_cases_git_history_strategy_accepts_file_grounding_and_attaches_commands(monkeypatch, tmp_path):
    db_path = tmp_path / "seed_git_history.sqlite"

    class DummyClient:
        provider = "ollama"

        def chat(self, **kwargs):
            return (
                "[Thought] update middleware path\n"
                "[Output] Update `guard/middleware.py`, `pyproject.toml`, and `tests/test_middleware/test_security_middleware.py`."
            )

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {"vcs": "git", "touched_files": [], "patch_text": ""},
    )

    report = run_seed_cases(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="coder",
        model="qwen3.5:9b",
        cases=[
            SeedCase(
                prompt="Update FastAPI Guard to version 3.0.2 and fix security middleware request checks.",
                expected_files=[
                    "guard/middleware.py",
                    "pyproject.toml",
                    "tests/test_middleware/test_security_middleware.py",
                ],
                expected_commands=["pytest", "ruff check ."],
                accept_strategy="git_history_file_grounded",
                min_file_recall=0.25,
                attach_expected_commands=True,
            )
        ],
        accept_threshold=0.9,
    )

    assert report["cases"] == 1
    assert report["accepted"] == 1
    assert report["avg_file_recall"] == 1.0
    assert report["avg_role_recall"] == 1.0
    assert report["avg_command_recall"] == 0.0

    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        latest = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert latest.status == "accepted"
        assert latest.meta["seed_expected_files"] == [
            "guard/middleware.py",
            "pyproject.toml",
            "tests/test_middleware/test_security_middleware.py",
        ]
        assert latest.meta["seed_expected_commands"] == ["pytest", "ruff check ."]
        assert latest.meta["seed_accept_strategy"] == "git_history_file_grounded"
        assert latest.meta["seed_accept_mode"] == "exact_file_grounding"
    finally:
        log.close()


def test_run_seed_cases_git_history_strategy_accepts_structural_foothold_for_backend_repo(monkeypatch, tmp_path):
    db_path = tmp_path / "seed_git_history_structural.sqlite"
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115", "sqlalchemy>=2.0"]
""".strip(),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

        def chat(self, **kwargs):
            return (
                "[Thought] update auth middleware zone\n"
                "[Output] Update `auth/middleware.py`, `tests/test_auth_flow.py`, and run `pytest` plus `ruff check .`."
            )

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {"vcs": "git", "touched_files": [], "patch_text": ""},
    )

    report = run_seed_cases(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="coder",
        model="qwen3.5:9b",
        cases=[
            SeedCase(
                prompt="Harden auth session middleware checks for the FastAPI service and verify it.",
                expected_files=[
                    "guard/token_guard.py",
                    "guard/session_manager.py",
                    "tests/test_security_guard.py",
                    "pyproject.toml",
                    "README.md",
                ],
                expected_commands=["pytest", "ruff check ."],
                accept_strategy="git_history_file_grounded",
                min_file_recall=0.25,
                attach_expected_commands=True,
            )
        ],
        accept_threshold=0.9,
    )

    assert report["cases"] == 1
    assert report["accepted"] == 1
    assert report["avg_file_recall"] == 0.0
    assert report["avg_role_recall"] == 0.5
    assert report["avg_command_recall"] == 1.0

    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        latest = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert latest.status == "accepted"
        assert latest.meta["seed_accept_strategy"] == "git_history_file_grounded"
        assert latest.meta["seed_accept_mode"] == "structural_bootstrap"
        assert latest.meta["seed_repo_family"] == "python_api"
        assert latest.meta["seed_role_recall"] == 0.5
        assert latest.meta["seed_expected_commands"] == ["pytest", "ruff check ."]
    finally:
        log.close()


def test_seed_runner_extracts_files_and_commands_from_teacher_answer():
    answer = """
    Update `memory_system/distillation/workflow_planner.py` and `tests/test_step6_coding_distillation.py`.

    ```bash
    py -3 -m pytest -q tests/test_step6_coding_distillation.py
    ```
    """
    assert _extract_answer_files(answer) == [
        "memory_system/distillation/workflow_planner.py",
        "tests/test_step6_coding_distillation.py",
    ]
    assert _extract_answer_commands(answer) == [
        "py -3 -m pytest -q tests/test_step6_coding_distillation.py"
    ]


def test_seed_runner_extracts_python_manifest_and_makefile_paths():
    answer = """
    Update `pyproject.toml`, `setup.py`, and `Makefile`.

    ```bash
    pytest
    ruff check .
    ```
    """
    assert _extract_answer_files(answer) == [
        "pyproject.toml",
        "setup.py",
        "Makefile",
    ]
    assert _extract_answer_commands(answer) == [
        "pytest",
        "ruff check .",
    ]


def test_export_accepted_traces_to_jsonl(tmp_path):
    db_path = tmp_path / "export.sqlite"
    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        accepted_id = coding_log.save_trace(
            session_id="sess_export",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(tmp_path),
            task_text="Fix serializer bug",
            system_prompt="sys",
            messages=[{"role": "user", "content": "Fix serializer bug"}],
            retrieved_chunk_ids=[1, 2],
            assistant_text="[Thought] inspect\n[Output] Patch serializer and add a regression test.",
            touched_files=["src/serializer.py"],
            patch_text="diff --git a/src/serializer.py b/src/serializer.py",
            tests=[{"command": "pytest -q", "status": "passed"}],
            meta={"surface": "coding_proxy"},
        )
        coding_log.mark_feedback(trace_id=accepted_id, is_positive=True)
        coding_log.append_event(
            trace_id=accepted_id,
            event_type="workspace",
            event_name="workspace_snapshot",
            payload={"vcs": "git", "touched_files": ["src/serializer.py"]},
        )

        rejected_id = coding_log.save_trace(
            session_id="sess_reject",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(tmp_path),
            task_text="Refactor css",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            assistant_text="[Output] Update styles.",
        )
        coding_log.mark_feedback(trace_id=rejected_id, is_positive=False)
    finally:
        log.close()

    out_path = tmp_path / "accepted.jsonl"
    count = export_accepted_traces_to_jsonl(
        db_path=str(db_path),
        out_path=str(out_path),
        user_id="coder",
        repo_root=str(tmp_path),
        limit=10,
    )

    assert count == 1
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["trace_id"] == accepted_id
    assert record["assistant_output"] == "Patch serializer and add a regression test."
    assert record["events"][0]["event_name"] == "workspace_snapshot"
    assert record["latest_test_status"] == "passed"


def test_coding_session_keeps_history_and_feedback(monkeypatch, tmp_path):
    class DummyClient:
        provider = "openai"

        def __init__(self):
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return "[Thought] inspect memory\n[Output] First answer"
            return "[Thought] reuse prior context\n[Output] Second answer"

    dummy = DummyClient()
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: dummy,
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )

    session = CodingSession(
        model="teacher",
        db_path=str(tmp_path / "session.sqlite"),
        user_id="coder",
        repo_root=str(tmp_path),
    )
    try:
        first = session.ask("First task")
        second = session.ask("Second task")
        assert first.trace_id != second.trace_id
        assert len(session.history) == 4
        monkeypatch.setattr(session.ttt, "explicit_feedback", lambda **kwargs: True)
        assert session.mark_feedback(is_positive=True)
    finally:
        session.close()

    log = EpisodeLog(tmp_path / "session.sqlite")
    try:
        coding_log = CodingTraceLog(log._conn)
        traces = coding_log.fetch_recent(user_id="coder", limit=5)
        assert len(traces) == 2
        latest = traces[0]
        assert latest.status == "accepted"
        events = coding_log.fetch_events(trace_id=latest.id)
        assert any(event.event_name == "accept" for event in events)
    finally:
        log.close()


def test_coding_session_records_workspace_snapshot_event(monkeypatch, tmp_path):
    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] inspect memory\n[Output] Update serializer and run tests."

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {
            "vcs": "git",
            "touched_files": ["src/serializer.py"],
            "patch_text": "diff --git a/src/serializer.py b/src/serializer.py",
        },
    )

    result = run_proxy_once(
        prompt="Fix serializer bug",
        model="teacher",
        db_path=str(tmp_path / "workspace.sqlite"),
        user_id="coder",
        repo_root=str(tmp_path),
    )

    log = EpisodeLog(tmp_path / "workspace.sqlite")
    try:
        coding_log = CodingTraceLog(log._conn)
        trace = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert trace.id == result.trace_id
        assert trace.meta["workspace_vcs"] == "git"
        assert trace.meta["workspace_touched_files"] == ["src/serializer.py"]
        events = coding_log.fetch_events(trace_id=trace.id)
        workspace_events = [event for event in events if event.event_name == "workspace_snapshot"]
        assert workspace_events
        assert workspace_events[0].payload["touched_files"] == ["src/serializer.py"]
    finally:
        log.close()


def test_coding_session_run_command_logs_shell_event(monkeypatch, tmp_path):
    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "[Thought] inspect memory\n[Output] Run a quick verification command."

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )

    class DummyExtractor:
        def __init__(self, *args, **kwargs):
            pass

        def extract(self, text):
            return []

    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.LLMChunkExtractor",
        DummyExtractor,
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_proxy.capture_workspace_state",
        lambda repo_root: {
            "vcs": "git",
            "touched_files": ["src/serializer.py"],
            "patch_text": "diff --git a/src/serializer.py b/src/serializer.py",
        },
    )

    session = CodingSession(
        model="teacher",
        db_path=str(tmp_path / "shell.sqlite"),
        user_id="coder",
        repo_root=str(tmp_path),
    )
    try:
        first = session.ask("Verify serializer patch")
        cmd = session.run_command('py -3 -c "print(\'ok\')"')
        assert first.trace_id > 0
        assert cmd is not None
        assert cmd.status == "passed"
        assert "ok" in cmd.stdout_tail
    finally:
        session.close()

    log = EpisodeLog(tmp_path / "shell.sqlite")
    try:
        coding_log = CodingTraceLog(log._conn)
        trace = coding_log.fetch_recent(user_id="coder", limit=1)[0]
        assert trace.meta["last_shell_status"] == "passed"
        events = coding_log.fetch_events(trace_id=trace.id)
        assert any(event.event_name == "shell_run" for event in events)
        post_events = [event for event in events if event.event_name == "post_command_workspace_snapshot"]
        assert post_events
        assert post_events[0].payload["touched_files"] == ["src/serializer.py"]
    finally:
        log.close()


def test_pitch_pack_builder_writes_pitch_flow_html_and_frozen_inputs(tmp_path):
    showcase_path = tmp_path / "showcase.json"
    head_path = tmp_path / "head.json"
    unseen_path = tmp_path / "unseen.json"

    showcase_path.write_text(
        json.dumps(
            {
                "final_report": {
                    "avg_file_recall": 1.0,
                    "avg_command_recall": 1.0,
                    "rows": [],
                }
            }
        ),
        encoding="utf-8",
    )
    head_path.write_text(
        json.dumps(
            {
                "avg_raw_file_recall": 0.0,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 1.0,
                "avg_memla_combined_command_recall": 1.0,
                "rows": [
                    {
                        "prompt": "Seen case",
                        "raw_file_recall": 0.0,
                        "raw_command_recall": 0.0,
                        "memla_combined_file_recall": 1.0,
                        "memla_combined_command_recall": 1.0,
                        "memla_plan_files": ["memory_system/distillation/coding_proxy.py"],
                        "memla_combined_commands": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
                        "prior_trace_ids": [1, 2],
                        "memla_patch_steps": ["Inspect priors", "Inject plan"],
                        "raw_answer": "I need more context.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    unseen_path.write_text(
        json.dumps(
            {
                "avg_raw_file_recall": 0.1,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.8,
                "avg_memla_combined_command_recall": 1.0,
                "rows": [
                    {
                        "prompt": "Unseen case",
                        "raw_file_recall": 0.1,
                        "raw_command_recall": 0.0,
                        "memla_combined_file_recall": 0.8,
                        "memla_combined_command_recall": 1.0,
                        "memla_plan_files": ["memory_system/distillation/demo_runner.py"],
                        "memla_combined_commands": ["py -3 -m pytest -q tests/test_step6_coding_distillation.py"],
                        "prior_trace_ids": [3],
                        "memla_patch_steps": ["Pull accepted priors"],
                        "raw_answer": "Try exploring the repo first.",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stale = tmp_path / "pack" / "frozen"
    stale.mkdir(parents=True, exist_ok=True)
    (stale / "old.json").write_text("{}", encoding="utf-8")

    outputs = build_pitch_pack(
        showcase_path=str(showcase_path),
        head_to_head_path=str(head_path),
        unseen_path=str(unseen_path),
        out_dir=str(tmp_path / "pack"),
    )

    pitch_text = (tmp_path / "pack" / "one_sentence_pitch.txt").read_text(encoding="utf-8")
    demo_flow = (tmp_path / "pack" / "90_second_demo.md").read_text(encoding="utf-8")
    html = (tmp_path / "pack" / "index.html").read_text(encoding="utf-8")

    assert Path(outputs["pitch"]).exists()
    assert Path(outputs["demo_flow"]).exists()
    assert Path(outputs["html"]).exists()
    assert Path(outputs["frozen_showcase"]).exists()
    assert Path(outputs["frozen_head_to_head"]).exists()
    assert Path(outputs["frozen_unseen"]).exists()
    assert outputs["frozen_head_to_head"] != outputs["frozen_unseen"]
    assert not (tmp_path / "pack" / "frozen" / "old.json").exists()
    assert "Memla turns frontier-model coding usage into owned repo-specific intelligence" in pitch_text
    assert "90-Second Demo Flow" in demo_flow
    assert "Unseen validation" in html
    assert "Seen case" in html
    assert "Unseen case" in html
    assert json.loads(Path(outputs["frozen_head_to_head"]).read_text(encoding="utf-8"))["rows"][0]["prompt"] == "Seen case"
    assert json.loads(Path(outputs["frozen_unseen"]).read_text(encoding="utf-8"))["rows"][0]["prompt"] == "Unseen case"


def test_pitch_pack_text_renderers_include_metrics():
    showcase = {"final_report": {"avg_file_recall": 1.0, "avg_command_recall": 0.9}}
    head_to_head = {
        "avg_raw_file_recall": 0.0,
        "avg_raw_command_recall": 0.1,
        "avg_memla_combined_file_recall": 1.0,
        "avg_memla_combined_command_recall": 0.9,
    }
    unseen = {
        "avg_memla_combined_file_recall": 0.8,
        "avg_memla_combined_command_recall": 0.7,
    }

    pitch = render_one_sentence_pitch(
        showcase=showcase,
        head_to_head=head_to_head,
        unseen=unseen,
    )
    flow = render_demo_flow(head_to_head=head_to_head, unseen=unseen)

    assert "0.0 to 1.0" in pitch
    assert "0.8/0.7" in pitch
    assert "Raw teacher recall on the buyer set: file `0.0`, command `0.1`." in flow
    assert "Memla combined recall on unseen set: file `0.8`, command `0.7`." in flow


def test_acquisition_pack_builder_writes_updated_artifacts(tmp_path):
    showcase_path = tmp_path / "showcase.json"
    transfer_path = tmp_path / "transfer.json"
    frontier_path = tmp_path / "frontier.json"
    public_frontier_path = tmp_path / "public_frontier.json"
    curriculum_batch_path = tmp_path / "curriculum_batch.json"

    showcase_path.write_text(
        json.dumps({"final_report": {"avg_file_recall": 1.0, "avg_command_recall": 1.0}}),
        encoding="utf-8",
    )
    transfer_path.write_text(
        json.dumps(
            {
                "avg_baseline_file_recall": 0.6,
                "avg_baseline_command_recall": 0.0,
                "avg_memla_file_recall": 0.86,
                "avg_memla_command_recall": 1.0,
                "rows": [
                    {
                        "prompt": "Transfer case",
                        "baseline_file_recall": 0.0,
                        "memla_file_recall": 0.5,
                        "delta_file_recall": 0.5,
                        "delta_command_recall": 1.0,
                        "memla_files": ["src/App.jsx"],
                        "memla_commands": ["npm run build", "npm run lint"],
                        "memla_transmutations": ["Trade transient UI state for recoverable session-backed booking state."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    frontier_path.write_text(
        json.dumps(
            {
                "avg_raw_file_recall": 0.1667,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.9167,
                "avg_memla_combined_command_recall": 1.0,
                "rows": [
                    {
                        "prompt": "Frontier case",
                        "raw_file_recall": 0.0,
                        "memla_combined_file_recall": 1.0,
                        "memla_combined_command_recall": 1.0,
                        "memla_plan_files": ["src/App.jsx"],
                        "memla_plan_tests": ["npm run build", "npm run lint"],
                        "memla_transmutations": ["Trade embedded payment state for redirect-safe confirmation recovery."],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    public_frontier_path.write_text(
        json.dumps(
            {
                "avg_raw_file_recall": 0.2653,
                "avg_memla_combined_file_recall": 0.4597,
            }
        ),
        encoding="utf-8",
    )
    curriculum_batch_path.write_text(
        json.dumps(
            {
                "repos_attempted": 7,
                "repos_with_holdouts": 6,
                "results": [
                    {
                        "repo_label": "guardian cli",
                        "status": "completed",
                        "avg_raw_file_recall": 0.1667,
                        "avg_memla_combined_file_recall": 0.6728,
                        "avg_raw_command_recall": 0.1667,
                        "avg_memla_combined_command_recall": 0.8333,
                    }
                ],
                "top_transmutations": [
                    {"text": "Trade shell flexibility for a repeatable command-line workflow.", "count": 13}
                ],
            }
        ),
        encoding="utf-8",
    )

    outputs = build_acquisition_pack(
        showcase_path=str(showcase_path),
        transfer_path=str(transfer_path),
        frontier_path=str(frontier_path),
        public_frontier_path=str(public_frontier_path),
        curriculum_batch_path=str(curriculum_batch_path),
        out_dir=str(tmp_path / "acq_pack"),
    )

    pitch = Path(outputs["pitch"]).read_text(encoding="utf-8")
    demo = Path(outputs["demo_flow"]).read_text(encoding="utf-8")
    memo = Path(outputs["memo"]).read_text(encoding="utf-8")
    targets = Path(outputs["targets"]).read_text(encoding="utf-8")
    email = Path(outputs["email"]).read_text(encoding="utf-8")
    html = Path(outputs["html"]).read_text(encoding="utf-8")
    og_card = Path(outputs["og_card"]).read_text(encoding="utf-8")
    vercel = Path(outputs["vercel"]).read_text(encoding="utf-8")

    assert "transferable intelligence" in pitch
    assert "0.1667" in pitch
    assert "0.9167" in pitch
    assert "6/7" in pitch
    assert "Memla does not just remember file names" in demo
    assert "Memla is a coding intelligence layer" in memo
    assert "LangChain" in targets
    assert "Memla turns accepted coding work into transferable intelligence" in email
    assert "Memla | Transferable Coding Intelligence" in html
    assert "Proof Layers" in html
    assert "Frontier case" in html
    assert "guardian cli" in html
    assert "Same model. New repo." in og_card
    assert "\"cleanUrls\": true" in vercel


def test_acquisition_text_renderers_include_transfer_metrics():
    showcase = {"final_report": {"avg_file_recall": 1.0, "avg_command_recall": 1.0}}
    transfer = {
        "avg_baseline_file_recall": 0.6111,
        "avg_baseline_command_recall": 0.0,
        "avg_memla_file_recall": 0.8611,
        "avg_memla_command_recall": 1.0,
    }
    frontier = {
        "avg_raw_file_recall": 0.1667,
        "avg_memla_combined_file_recall": 0.9167,
    }

    pitch = render_acquisition_pitch(showcase=showcase, transfer=transfer, frontier=frontier)
    flow = render_acquisition_demo_flow(transfer=transfer, frontier=frontier)

    assert "0.6111" in pitch
    assert "0.8611" in pitch
    assert "0.1667" in pitch
    assert "0.9167" in pitch
    assert "Empty-memory file recall: `0.6111` -> Memla transfer file recall: `0.8611`." in flow


def test_diligence_packet_builder_writes_async_docs_and_public_support(tmp_path):
    showcase_path = tmp_path / "showcase.json"
    transfer_path = tmp_path / "transfer.json"
    frontier_path = tmp_path / "frontier.json"
    public_seed_path = tmp_path / "public_seed.json"
    public_frontier_path = tmp_path / "public_frontier.json"
    curriculum_batch_path = tmp_path / "curriculum_batch.json"

    showcase_path.write_text(
        json.dumps({"final_report": {"avg_file_recall": 1.0, "avg_command_recall": 1.0}}),
        encoding="utf-8",
    )
    transfer_path.write_text(
        json.dumps(
            {
                "avg_baseline_file_recall": 0.6111,
                "avg_baseline_command_recall": 0.0,
                "avg_memla_file_recall": 0.8611,
                "avg_memla_command_recall": 1.0,
            }
        ),
        encoding="utf-8",
    )
    frontier_path.write_text(
        json.dumps(
            {
                "avg_raw_file_recall": 0.1667,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.9167,
                "avg_memla_combined_command_recall": 1.0,
            }
        ),
        encoding="utf-8",
    )
    public_seed_path.write_text(
        json.dumps(
            {
                "cases": 8,
                "accepted": 5,
                "accept_rate": 0.625,
            }
        ),
        encoding="utf-8",
    )
    public_frontier_path.write_text(
        json.dumps(
            {
                "repo_root": "C:\\Users\\samat\\Project Memory\\external\\trpc-examples-next-prisma-starter",
                "teacher_model": "qwen3.5:9b",
                "avg_raw_file_recall": 0.0535,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.2126,
                "avg_memla_combined_command_recall": 0.6667,
            }
        ),
        encoding="utf-8",
    )
    curriculum_batch_path.write_text(
        json.dumps(
            {
                "repos_attempted": 7,
                "results": [
                    {
                        "id": "oauth4webapi",
                        "status": "completed",
                        "avg_raw_command_recall": 0.0,
                        "avg_memla_combined_command_recall": 0.75,
                    },
                    {
                        "id": "teamhide_fastapi_boilerplate",
                        "status": "completed",
                        "avg_raw_command_recall": 1.0,
                        "avg_memla_combined_command_recall": 1.0,
                    },
                    {
                        "id": "fastapi_template",
                        "status": "completed",
                        "avg_raw_command_recall": 0.0625,
                        "avg_memla_combined_command_recall": 0.875,
                    },
                    {
                        "id": "redocly_cli",
                        "status": "completed",
                        "avg_raw_command_recall": 0.125,
                        "avg_memla_combined_command_recall": 0.875,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    outputs = build_diligence_packet(
        showcase_path=str(showcase_path),
        transfer_path=str(transfer_path),
        frontier_path=str(frontier_path),
        public_seed_path=str(public_seed_path),
        public_frontier_path=str(public_frontier_path),
        curriculum_batch_path=str(curriculum_batch_path),
        out_dir=str(tmp_path / "packet"),
    )

    summary = Path(outputs["summary"]).read_text(encoding="utf-8")
    faq = Path(outputs["faq"]).read_text(encoding="utf-8")
    proof_table = Path(outputs["proof_table"]).read_text(encoding="utf-8")
    technical = Path(outputs["technical"]).read_text(encoding="utf-8")
    html = Path(outputs["html"]).read_text(encoding="utf-8")

    assert "Memla Diligence Summary" in summary
    assert "trpc examples next prisma starter" in summary.lower()
    assert "seeded support" in faq.lower()
    assert "Public seeded head-to-head" in proof_table
    assert "Public curriculum rerun" in proof_table
    assert "same-model comparison" in technical
    assert "Multi-Family Curriculum Rerun" in technical
    assert "Memla Diligence Packet" in html
    assert Path(outputs["frozen_public_seed"]).exists()
    assert Path(outputs["frozen_public_frontier"]).exists()
    assert Path(outputs["frozen_curriculum_batch"]).exists()


def test_diligence_packet_renderers_include_public_support():
    showcase = {"final_report": {"avg_file_recall": 1.0, "avg_command_recall": 1.0}}
    transfer = {
        "avg_baseline_file_recall": 0.6111,
        "avg_baseline_command_recall": 0.0,
        "avg_memla_file_recall": 0.8611,
        "avg_memla_command_recall": 1.0,
    }
    frontier = {
        "avg_raw_file_recall": 0.1667,
        "avg_raw_command_recall": 0.0,
        "avg_memla_combined_file_recall": 0.9167,
        "avg_memla_combined_command_recall": 1.0,
    }
    public_seed = {"cases": 8, "accepted": 5, "accept_rate": 0.625}
    public_frontier = {
        "repo_root": "C:\\Users\\samat\\Project Memory\\external\\trpc-examples-next-prisma-starter",
        "teacher_model": "qwen3.5:9b",
        "avg_raw_file_recall": 0.0535,
        "avg_raw_command_recall": 0.0,
        "avg_memla_combined_file_recall": 0.2126,
        "avg_memla_combined_command_recall": 0.6667,
    }
    curriculum_batch = {
        "repos_attempted": 7,
        "results": [
            {
                "id": "oauth4webapi",
                "status": "completed",
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_command_recall": 0.75,
            },
            {
                "id": "teamhide_fastapi_boilerplate",
                "status": "completed",
                "avg_raw_command_recall": 1.0,
                "avg_memla_combined_command_recall": 1.0,
            },
            {
                "id": "fastapi_template",
                "status": "completed",
                "avg_raw_command_recall": 0.0625,
                "avg_memla_combined_command_recall": 0.875,
            },
            {
                "id": "redocly_cli",
                "status": "completed",
                "avg_raw_command_recall": 0.125,
                "avg_memla_combined_command_recall": 0.875,
            },
        ],
    }

    summary = render_diligence_summary(
        showcase=showcase,
        transfer=transfer,
        frontier=frontier,
        public_seed=public_seed,
        public_frontier=public_frontier,
        curriculum_batch=curriculum_batch,
    )
    faq = render_diligence_faq(
        showcase=showcase,
        transfer=transfer,
        frontier=frontier,
        public_seed=public_seed,
        public_frontier=public_frontier,
        curriculum_batch=curriculum_batch,
    )
    proof = render_proof_table(
        showcase=showcase,
        transfer=transfer,
        frontier=frontier,
        public_seed=public_seed,
        public_frontier=public_frontier,
        curriculum_batch=curriculum_batch,
    )
    technical = render_technical_diligence(
        showcase=showcase,
        transfer=transfer,
        frontier=frontier,
        public_seed=public_seed,
        public_frontier=public_frontier,
        curriculum_batch=curriculum_batch,
    )

    assert "0.2126" in summary
    assert "4/7" in summary
    assert "trpc examples next prisma starter" in summary.lower()
    assert "seed accept rate `0.625`" in faq
    assert "fastapi_template" in faq
    assert "Supporting public proof (trpc examples next prisma starter)" in proof
    assert "Public curriculum rerun" in proof
    assert "accepted `5/8` seed cases" in proof
    assert "trpc examples next prisma starter" in technical.lower()
    assert "Seed accept count: `5/8`" in technical
    assert "Multi-Family Curriculum Rerun" in technical
