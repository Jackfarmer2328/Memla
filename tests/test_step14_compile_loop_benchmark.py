from __future__ import annotations

from memory_system.distillation.compile_loop_benchmark import (
    render_compile_loop_benchmark_markdown,
    run_compile_loop_benchmark,
)
from memory_system.distillation.eval_harness import PlanEvalCase


def test_run_compile_loop_benchmark_compares_planning_only_and_full(monkeypatch, tmp_path):
    db_path = tmp_path / "seeded.sqlite"
    db_path.write_text("seed", encoding="utf-8")

    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "Touch `raw.py` and run `pytest`."

    class DummySession:
        def __init__(self, **kwargs):
            self.enable_compile_loop = bool(kwargs.get("enable_compile_loop", True))

        def ask(self, prompt, **kwargs):
            if self.enable_compile_loop:
                return type(
                    "ProxyResult",
                    (),
                    {
                        "answer": "Touch `src/compile.py` and `tests/test_compile.py`. Run `pytest`.",
                        "suggested_files": ["src/compile.py", "tests/test_compile.py"],
                        "suggested_commands": ["pytest"],
                        "likely_tests": ["pytest"],
                        "prior_trace_ids": [2],
                        "validated_trade_path": {
                            "supporting_files": ["src/compile.py"],
                            "supporting_commands": ["pytest"],
                        },
                        "residual_constraints": [],
                    },
                )()
            return type(
                "ProxyResult",
                (),
                {
                    "answer": "Touch `src/plan.py` and run `pytest`.",
                    "suggested_files": ["src/plan.py"],
                    "suggested_commands": ["pytest"],
                    "likely_tests": ["pytest"],
                    "prior_trace_ids": [1],
                    "validated_trade_path": {},
                    "residual_constraints": ["ownership_resolution_gap"],
                },
            )()

        def close(self):
            return None

    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )
    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.CodingSession",
        lambda **kwargs: DummySession(**kwargs),
    )
    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.load_eval_cases",
        lambda path: [
            PlanEvalCase(
                prompt="Compile the coding hypothesis into repo-local actions.",
                expected_files=["src/compile.py", "tests/test_compile.py"],
                expected_commands=["pytest"],
            )
        ],
    )

    report = run_compile_loop_benchmark(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="default",
        cases_path="cases.jsonl",
        model="qwen3.5:4b",
    )

    assert report["avg_raw_file_recall"] < report["avg_compile_combined_file_recall"]
    assert report["avg_plan_only_combined_file_recall"] < report["avg_compile_combined_file_recall"]
    assert report["avg_compile_validated_command_recall"] == 1.0
    md = render_compile_loop_benchmark_markdown(report)
    assert "Memla Compile Loop Benchmark" in md
    assert "Planning-only combined file recall" in md
    assert "Full compile/backtest" in md


def test_run_compile_loop_benchmark_records_failed_cases_and_continues(monkeypatch, tmp_path):
    db_path = tmp_path / "seeded.sqlite"
    db_path.write_text("seed", encoding="utf-8")

    class DummyClient:
        provider = "openai"

        def chat(self, **kwargs):
            return "Touch `raw.py` and run `pytest`."

    class DummySession:
        def __init__(self, **kwargs):
            self.enable_compile_loop = bool(kwargs.get("enable_compile_loop", True))

        def ask(self, prompt, **kwargs):
            if "first" in prompt:
                raise TimeoutError("simulated timeout")
            return type(
                "ProxyResult",
                (),
                {
                    "answer": "Touch `src/compile.py` and run `pytest`.",
                    "suggested_files": ["src/compile.py"],
                    "suggested_commands": ["pytest"],
                    "likely_tests": ["pytest"],
                    "prior_trace_ids": [1],
                    "validated_trade_path": {"supporting_files": ["src/compile.py"], "supporting_commands": ["pytest"]},
                    "residual_constraints": [],
                },
            )()

        def close(self):
            return None

    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.UniversalLLMClient.from_env",
        lambda: DummyClient(),
    )
    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.CodingSession",
        lambda **kwargs: DummySession(**kwargs),
    )
    monkeypatch.setattr(
        "memory_system.distillation.compile_loop_benchmark.load_eval_cases",
        lambda path: [
            PlanEvalCase(
                prompt="first case should timeout",
                expected_files=["src/compile.py"],
                expected_commands=["pytest"],
            ),
            PlanEvalCase(
                prompt="second case should pass",
                expected_files=["src/compile.py"],
                expected_commands=["pytest"],
            ),
        ],
    )

    report = run_compile_loop_benchmark(
        db_path=str(db_path),
        repo_root=str(tmp_path),
        user_id="default",
        cases_path="cases.jsonl",
        model="qwen3.5:4b",
    )

    assert report["cases_requested"] == 2
    assert report["cases"] == 1
    assert report["failed_case_count"] == 1
    assert report["failed_cases"][0]["stage"] == "planning_only"
    md = render_compile_loop_benchmark_markdown(report)
    assert "Failed Cases" in md
