from __future__ import annotations

from contextlib import contextmanager

from memory_system.distillation.coding_c2a_benchmark import (
    render_coding_c2a_markdown,
    run_coding_c2a_benchmark,
)
from memory_system.distillation.eval_harness import PlanEvalCase
from memory_system.distillation.workflow_planner import WorkflowPlan


def test_run_coding_c2a_benchmark_prefers_memla_plan(monkeypatch, tmp_path):
    case = PlanEvalCase(
        prompt="Expose the public CLI entrypoint and packaging metadata so Memla can be installed like a tool.",
        expected_files=["memla.py", "memory_system/cli.py", "tests/test_step17_memla_cli.py"],
        expected_commands=["py -3 -m pytest -q tests/test_step17_memla_cli.py"],
    )

    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark.load_eval_cases",
        lambda path: [case],
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark.build_repo_map",
        lambda repo_root, prompt="", limit=6: [
            {
                "region": "memory_system",
                "roles": ["cli_surface"],
                "sample_files": ["memory_system/cli.py"],
                "score": 2.0,
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark.scan_repo_role_matches",
        lambda repo_root, prompt, desired_roles, limit=6: [
            {"target_paths": ["memla.py"]},
            {"target_paths": ["memory_system/cli.py"]},
        ],
    )

    class DummyClient:
        def __init__(self, provider: str):
            self.provider = provider

        def chat(self, **kwargs):
            return (
                '{"likely_files":["memory_system/cli.py"],'
                '"likely_commands":["py -3 -m pytest -q tests/test_step17_memla_cli.py"],'
                '"likely_tests":["py -3 -m pytest -q tests/test_step17_memla_cli.py"],'
                '"role_targets":["cli_surface"],'
                '"predicted_constraints":["cli_command_flow"],'
                '"predicted_transmutations":["Trade vague search for a narrower verified path."]}'
            )

    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    @contextmanager
    def _no_override(**kwargs):
        yield

    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark._override_llm_env",
        _no_override,
    )

    class DummySession:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def build_plan(self, prompt: str):
            return WorkflowPlan(
                likely_files=["memla.py", "memory_system/cli.py", "tests/test_step17_memla_cli.py"],
                likely_commands=["py -3 -m pytest -q tests/test_step17_memla_cli.py"],
                likely_tests=["py -3 -m pytest -q tests/test_step17_memla_cli.py"],
                patch_steps=["Expose the CLI surface and verify the install path."],
                source_trace_ids=[7],
                predicted_constraints=["cli_command_flow", "verification_gate"],
                transmutations=["Trade local invocation friction for an installable CLI"],
                role_targets=["cli_surface", "test_surface"],
                selected_search_regions=["memory_system", "tests"],
            )

        def close(self):
            return None

    monkeypatch.setattr(
        "memory_system.distillation.coding_c2a_benchmark.CodingSession",
        DummySession,
    )

    report = run_coding_c2a_benchmark(
        db_path=str(tmp_path / "memory.sqlite"),
        repo_root=str(tmp_path),
        user_id="default",
        cases_path=str(tmp_path / "cases.jsonl"),
        raw_model="grok-3",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    assert report["cases"] == 1
    assert report["raw_provider"] == "github_models"
    assert report["memla_provider"] == "ollama"
    assert report["avg_memla_file_recall"] > report["avg_raw_file_recall"]
    assert report["avg_memla_c2a_utility"] > report["avg_raw_c2a_utility"]
    assert report["memla_vs_raw_c2a_utility_index"] is not None
    assert report["memla_vs_raw_c2a_utility_index"] > 1.0

    md = render_coding_c2a_markdown(report)
    assert "# Coding C2A Benchmark" in md
    assert "C2A utility" in md
    assert "Utility delta" in md
