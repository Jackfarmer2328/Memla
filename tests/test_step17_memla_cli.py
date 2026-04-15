from __future__ import annotations

import json
import tomllib
from pathlib import Path

from memory_system.cli import _build_parser, _rewrite_bare_terminal_argv, main
from memory_system.distillation.coding_proxy import ProxyResult
from memory_system.distillation.workflow_planner import WorkflowPlan


def test_memla_coding_plan_renders_workflow_block(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    class DummySession:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.kwargs = kwargs

        def build_plan(self, prompt: str):
            assert prompt == "Fix the auth regression"
            return WorkflowPlan(
                likely_files=["src/auth.py", "tests/test_auth.py"],
                likely_commands=["pytest -q"],
                likely_tests=["pytest -q"],
                patch_steps=["Update the auth helper and refresh the failing test."],
                source_trace_ids=[11, 12],
                predicted_constraints=["ownership_resolution_gap"],
                transmutations=["Trade ambiguous ownership for a single source of truth"],
            )

        def close(self):
            return None

    monkeypatch.setattr("memory_system.cli.CodingSession", DummySession)

    rc = main(
        [
            "coding",
            "plan",
            "--prompt",
            "Fix the auth regression",
            "--repo-root",
            str(tmp_path),
            "--db",
            str(tmp_path / "memory.sqlite"),
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "=== MEMLA WORKFLOW PLAN ===" in out
    assert "Likely files: src/auth.py, tests/test_auth.py" in out
    assert "Predicted constraints: ownership_resolution_gap" in out
    assert captured["c2a_policy_path"] == ""
    assert captured["disable_c2a_policy"] is False


def test_memla_coding_run_json_outputs_structured_proxy_result(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    class DummySession:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.kwargs = kwargs

        def ask(self, prompt: str, *, test_command: str | None = None):
            assert prompt == "Repair the auth regression"
            assert test_command == "pytest -q"
            return ProxyResult(
                answer="Update `src/auth.py` and rerun `pytest -q`.",
                trace_id=7,
                trajectory_id=None,
                retrieved_chunk_ids=[1, 2],
                test_result={"command": "pytest -q", "status": "passed"},
                prior_trace_ids=[5],
                suggested_files=["src/auth.py", "tests/test_auth.py"],
                suggested_commands=["pytest -q"],
                likely_tests=["pytest -q"],
                patch_steps=["Update the auth guard."],
                predicted_constraints=["ownership_resolution_gap"],
                transmutations=["Trade ambiguity for a single auth path"],
                validated_trade_path={
                    "supporting_files": ["src/auth.py"],
                    "supporting_commands": ["pytest -q"],
                },
                residual_constraints=["missing_import_or_dependency"],
            )

        def close(self):
            return None

    monkeypatch.setattr("memory_system.cli.CodingSession", DummySession)

    rc = main(
        [
            "coding",
            "run",
            "--prompt",
            "Repair the auth regression",
            "--repo-root",
            str(tmp_path),
            "--db",
            str(tmp_path / "memory.sqlite"),
            "--test-command",
            "pytest -q",
            "--disable-c2a-policy",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["suggested_files"] == ["src/auth.py", "tests/test_auth.py"]
    assert payload["validated_trade_path"]["supporting_commands"] == ["pytest -q"]
    assert payload["residual_constraints"] == ["missing_import_or_dependency"]
    assert captured["disable_c2a_policy"] is True


def test_memla_patch_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def _fake_patch_benchmark(**kwargs):
        captured.update(kwargs)
        return {
            "raw_apply_rate": 0.0,
            "memla_apply_rate": 0.6667,
            "avg_raw_semantic_command_success_rate": 0.0,
            "avg_memla_semantic_command_success_rate": 0.6667,
            "rows": [],
        }

    monkeypatch.setattr(
        "memory_system.cli.run_patch_execution_benchmark",
        _fake_patch_benchmark,
    )
    monkeypatch.setattr(
        "memory_system.cli.render_patch_execution_markdown",
        lambda report: "# Patch Execution Report\n",
    )

    out_dir = tmp_path / "patch_report"
    rc = main(
        [
            "coding",
            "benchmark-patch",
            "--pack",
            "cases.json",
            "--raw-model",
            "qwen2.5:32b",
            "--memla-model",
            "qwen3.5:9b",
            "--raw-provider",
            "github_models",
            "--raw-base-url",
            "https://models.github.ai/inference",
            "--memla-provider",
            "ollama",
            "--memla-base-url",
            "http://127.0.0.1:11435",
            "--disable-memla-c2a-policy",
            "--db",
            str(tmp_path / "bench.sqlite"),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "patch_execution_report.json").exists()
    assert (out_dir / "patch_execution_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote patch benchmark JSON" in out
    assert "memla apply 0.6667" in out
    assert captured["raw_provider"] == "github_models"
    assert captured["raw_base_url"] == "https://models.github.ai/inference"
    assert captured["memla_provider"] == "ollama"
    assert captured["memla_base_url"] == "http://127.0.0.1:11435"
    assert captured["disable_memla_c2a_policy"] is True


def test_memla_coding_c2a_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def _fake_c2a_benchmark(**kwargs):
        captured.update(kwargs)
        return {
            "avg_raw_c2a_utility": 0.42,
            "avg_memla_c2a_utility": 0.81,
            "memla_vs_raw_c2a_utility_index": 1.9286,
            "rows": [],
        }

    monkeypatch.setattr(
        "memory_system.cli.run_coding_c2a_benchmark",
        _fake_c2a_benchmark,
    )
    monkeypatch.setattr(
        "memory_system.cli.render_coding_c2a_markdown",
        lambda report: "# Coding C2A Benchmark\n",
    )

    out_dir = tmp_path / "c2a_report"
    rc = main(
        [
            "coding",
            "benchmark-c2a",
            "--cases",
            "cases.jsonl",
            "--repo-root",
            str(tmp_path),
            "--raw-model",
            "meta/Llama-3.1-405B-Instruct",
            "--memla-model",
            "qwen3.5:9b",
            "--raw-provider",
            "github_models",
            "--raw-base-url",
            "https://models.github.ai/inference",
            "--memla-provider",
            "ollama",
            "--memla-base-url",
            "http://127.0.0.1:11435",
            "--memla-c2a-policy-path",
            str(tmp_path / ".memla" / "bank.json"),
            "--db",
            str(tmp_path / "bench.sqlite"),
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "coding_c2a_benchmark_report.json").exists()
    assert (out_dir / "coding_c2a_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote coding C2A benchmark JSON" in out
    assert "memla utility 0.81" in out
    assert captured["raw_provider"] == "github_models"
    assert captured["memla_provider"] == "ollama"
    assert captured["memla_c2a_policy_path"] == str(tmp_path / ".memla" / "bank.json")


def test_memla_pack_thesis_routes_to_builder(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.build_thesis_pack",
        lambda **kwargs: {
            "out_dir": kwargs["out_dir"],
            "frozen_coding": str(tmp_path / "coding.json"),
            "frozen_rerank": str(tmp_path / "rerank.json"),
            "frozen_progress": str(tmp_path / "progress.json"),
        },
    )

    rc = main(
        [
            "pack",
            "thesis",
            "--coding",
            "coding.json",
            "--math-rerank",
            "math_rerank.json",
            "--math-progress",
            "math_progress.json",
            "--out-dir",
            str(tmp_path / "pack"),
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["out_dir"] == str((tmp_path / "pack").resolve())


def test_memla_pack_publish_site_copies_pack_files(capsys, tmp_path):
    source = tmp_path / "source_pack"
    frozen = source / "frozen"
    frozen.mkdir(parents=True)
    (source / "index.html").write_text("<html>site</html>", encoding="utf-8")
    (source / "vercel.json").write_text('{"cleanUrls": true}', encoding="utf-8")
    (source / "og-card.svg").write_text("<svg></svg>", encoding="utf-8")
    (source / "one_sentence_pitch.txt").write_text("pitch", encoding="utf-8")
    (source / "90_second_demo.md").write_text("# demo", encoding="utf-8")
    (source / "strategic_memo.md").write_text("# memo", encoding="utf-8")
    (frozen / "report.json").write_text('{"ok": true}', encoding="utf-8")

    target = tmp_path / "site_root"
    rc = main(
        [
            "pack",
            "publish-site",
            "--source",
            str(source),
            "--out-dir",
            str(target),
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["site_ready"] is True
    assert (target / "index.html").read_text(encoding="utf-8") == "<html>site</html>"
    assert (target / "frozen" / "report.json").exists()


def test_memla_doctor_reports_status_with_json(monkeypatch, capsys, tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / ".git").mkdir()

    monkeypatch.setattr(
        "memory_system.cli._probe_ollama",
        lambda url, timeout=2.0: {
            "reachable": True,
            "url": url,
            "model_count": 2,
            "models": ["qwen3.5:9b", "qwen2.5:32b"],
        },
    )

    rc = main(
        [
            "doctor",
            "--repo-root",
            str(repo_root),
            "--db",
            str(repo_root / ".memla" / "memory.sqlite"),
            "--model",
            "qwen3.5:9b",
            "--ollama-url",
            "http://127.0.0.1:11435",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["repo_root"]["git_repo"] is True
    assert payload["ollama"]["reachable"] is True
    assert payload["ollama"]["model_present"] is True


def test_memla_bare_prompt_routes_to_terminal_run(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_terminal_run(args):
        captured["prompt"] = args.prompt
        captured["heuristic_only"] = args.heuristic_only
        captured["model"] = args.model
        return 0

    monkeypatch.setattr("memory_system.cli._handle_terminal_run", _fake_terminal_run)

    rc = main(["open", "github", "and", "search", "llama.cpp"])

    assert rc == 0
    assert captured["prompt"] == "open github and search llama.cpp"
    assert captured["heuristic_only"] is False
    assert captured["model"] == "phi3:mini"


def test_memla_bare_prompt_preserves_terminal_flags(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_terminal_run(args):
        captured["prompt"] = args.prompt
        captured["heuristic_only"] = args.heuristic_only
        captured["model"] = args.model
        return 0

    monkeypatch.setattr("memory_system.cli._handle_terminal_run", _fake_terminal_run)

    rc = main(["open github and search llama.cpp", "--heuristic-only", "--model", "phi3:mini"])

    assert rc == 0
    assert captured["prompt"] == "open github and search llama.cpp"
    assert captured["heuristic_only"] is True
    assert captured["model"] == "phi3:mini"


def test_memla_bare_repo_scout_prompt_routes_to_terminal_scout():
    parser = _build_parser()

    rewritten = _rewrite_bare_terminal_argv(
        parser,
        ["find", "the", "top", "10", "github", "repos", "for", "local", "llms"],
    )

    assert rewritten[:3] == ["terminal", "scout", "--prompt"]
    assert rewritten[3] == "find the top 10 github repos for local llms"


def test_memla_serve_dispatches_to_api_server(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def _fake_serve(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("memory_system.cli._serve_memla_api", _fake_serve)

    rc = main(
        [
            "serve",
            "--host",
            "0.0.0.0",
            "--port",
            "8080",
            "--model",
            "phi3:mini",
            "--heuristic-only",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Serving Memla API at http://0.0.0.0:8080" in out
    assert captured["host"] == "0.0.0.0"
    assert captured["port"] == 8080
    assert captured["default_model"] == "phi3:mini"
    assert captured["default_heuristic_only"] is True


def test_memla_terminal_serve_alias_dispatches_to_api_server(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_serve(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("memory_system.cli._serve_memla_api", _fake_serve)

    rc = main(
        [
            "terminal",
            "serve",
            "--port",
            "9090",
            "--provider",
            "ollama",
            "--base-url",
            "http://127.0.0.1:11435",
        ]
    )

    assert rc == 0
    assert captured["port"] == 9090
    assert captured["default_provider"] == "ollama"
    assert captured["default_base_url"] == "http://127.0.0.1:11435"


def test_memla_terminal_benchmark_web_v1_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_terminal_benchmark(args):
        captured["cases"] = args.cases
        captured["raw_provider"] = args.raw_provider
        captured["memla_provider"] = args.memla_provider
        return 0

    monkeypatch.setattr("memory_system.cli._handle_terminal_benchmark", _fake_terminal_benchmark)

    rc = main(
        [
            "terminal",
            "benchmark-web-v1",
            "--raw-provider",
            "anthropic",
            "--memla-provider",
            "anthropic",
        ]
    )

    assert rc == 0
    assert captured["cases"] == "cases/web_eval_cases_v1.jsonl"
    assert captured["raw_provider"] == "anthropic"
    assert captured["memla_provider"] == "anthropic"


def test_memla_terminal_benchmark_web_answer_v1_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_web_answer_benchmark(args):
        captured["cases"] = args.cases
        captured["memla_provider"] = args.memla_provider
        captured["judge_provider"] = args.judge_provider
        return 0

    monkeypatch.setattr("memory_system.cli._handle_web_answer_benchmark", _fake_web_answer_benchmark)

    rc = main(
        [
            "terminal",
            "benchmark-web-answer-v1",
            "--memla-provider",
            "anthropic",
            "--judge-provider",
            "anthropic",
        ]
    )

    assert rc == 0
    assert captured["cases"] == "cases/web_eval_cases_v1.jsonl"
    assert captured["memla_provider"] == "anthropic"
    assert captured["judge_provider"] == "anthropic"


def test_memla_terminal_benchmark_web_teacher_v1_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_web_teacher_loop(args):
        captured["cases"] = args.cases
        captured["teacher_provider"] = args.teacher_provider
        captured["judge_provider"] = args.judge_provider
        captured["rescue_threshold"] = args.rescue_threshold
        return 0

    monkeypatch.setattr("memory_system.cli._handle_web_teacher_loop", _fake_web_teacher_loop)

    rc = main(
        [
            "terminal",
            "benchmark-web-teacher-v1",
            "--teacher-provider",
            "anthropic",
            "--judge-provider",
            "anthropic",
            "--rescue-threshold",
            "4",
        ]
    )

    assert rc == 0
    assert captured["cases"] == "cases/web_eval_cases_v1.jsonl"
    assert captured["teacher_provider"] == "anthropic"
    assert captured["judge_provider"] == "anthropic"
    assert captured["rescue_threshold"] == 4


def test_memla_terminal_distill_web_policy_v1_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_distill_web_policy(args):
        captured["trace_bank"] = args.trace_bank
        captured["min_improvement"] = args.min_improvement
        return 0

    monkeypatch.setattr("memory_system.cli._handle_distill_web_policy", _fake_distill_web_policy)

    rc = main(
        [
            "terminal",
            "distill-web-policy-v1",
            "--trace-bank",
            "web_teacher_trace_bank.jsonl",
            "--min-improvement",
            "0.5",
        ]
    )

    assert rc == 0
    assert captured["trace_bank"] == "web_teacher_trace_bank.jsonl"
    assert captured["min_improvement"] == 0.5


def test_memla_terminal_train_web_overnight_v1_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_web_overnight_loop(args):
        captured["seed_cases"] = args.seed_cases
        captured["question_count"] = args.question_count
        captured["teacher_provider"] = args.teacher_provider
        captured["target_overall"] = args.target_overall
        captured["target_hard_pass_rate"] = args.target_hard_pass_rate
        return 0

    monkeypatch.setattr("memory_system.cli._handle_web_overnight_loop", _fake_web_overnight_loop)

    rc = main(
        [
            "terminal",
            "train-web-overnight-v1",
            "--teacher-provider",
            "anthropic",
            "--question-count",
            "48",
            "--target-overall",
            "4.4",
            "--target-hard-pass-rate",
            "0.75",
        ]
    )

    assert rc == 0
    assert captured["seed_cases"] == "cases/web_eval_cases_v1.jsonl"
    assert captured["question_count"] == 48
    assert captured["teacher_provider"] == "anthropic"
    assert captured["target_overall"] == 4.4
    assert captured["target_hard_pass_rate"] == 0.75


def test_memla_top_level_scout_command_dispatches(monkeypatch):
    captured: dict[str, object] = {}

    def _fake_terminal_scout(args):
        captured["prompt"] = " ".join(args.prompt_text)
        return 0

    monkeypatch.setattr("memory_system.cli._handle_terminal_scout", _fake_terminal_scout)

    rc = main(["scout", "find", "the", "top", "5", "github", "repos", "for", "local", "llms"])

    assert rc == 0
    assert captured["prompt"] == "find the top 5 github repos for local llms"


def test_pyproject_exposes_memla_console_script():
    repo_root = Path(__file__).resolve().parents[1]
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))

    assert pyproject["project"]["name"] == "memla"
    assert pyproject["project"]["version"] == "0.1.1"
    assert pyproject["project"]["scripts"]["memla"] == "memory_system.cli:main"
    assert pyproject["project"]["readme"]["file"] == "PYPI_README.md"
    assert any(dep.startswith("sympy>=") for dep in pyproject["project"]["dependencies"])
