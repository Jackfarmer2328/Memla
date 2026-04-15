from __future__ import annotations

import json
from pathlib import Path

from memory_system.cli import main


def test_memla_research_convert_capture_dispatches(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.convert_research_loop_events_to_cases",
        lambda events_path, out_cases_path, min_iterations=1: {
            "sessions_written": 2,
            "events_seen": 10,
            "out_cases_path": out_cases_path,
        },
    )

    out_cases = tmp_path / "research_cases.jsonl"
    rc = main(
        [
            "research",
            "convert-capture",
            "--events",
            "capture.jsonl",
            "--out-cases",
            str(out_cases),
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["sessions_written"] == 2


def test_memla_research_benchmark_replay_writes_bundle(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_research_loop_replay_benchmark",
        lambda **kwargs: {
            "benchmark_type": "research_loop_replay",
            "raw": {"action_accuracy": 0.25, "avg_estimated_cost": 0.018},
            "memla": {"action_accuracy": 0.75, "avg_estimated_cost": 0.011},
            "frontier": {"action_accuracy": 0.75, "avg_estimated_cost": 0.013},
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Loop Benchmark\n",
    )

    out_dir = tmp_path / "research_replay"
    rc = main(
        [
            "research",
            "benchmark-replay",
            "--cases",
            "cases/research_loop_eval_cases_v1.jsonl",
            "--raw-model",
            "qwen3.5:9b",
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-model",
            "sonar-deep-research",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "research_loop_replay_report.json").exists()
    assert (out_dir / "research_loop_replay_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote research replay benchmark JSON" in out


def test_memla_research_benchmark_live_writes_bundle(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_research_loop_live_shadow_benchmark",
        lambda **kwargs: {
            "benchmark_type": "research_loop_live_shadow",
            "raw": {"avg_decision_accuracy": 0.4, "avg_estimated_cost": 0.025},
            "memla": {"avg_decision_accuracy": 0.8, "avg_estimated_cost": 0.017},
            "frontier": {"avg_decision_accuracy": 0.8, "avg_estimated_cost": 0.02},
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Loop Benchmark\n",
    )

    out_dir = tmp_path / "research_live"
    rc = main(
        [
            "research",
            "benchmark-live-shadow",
            "--cases",
            "cases/research_loop_eval_cases_v1.jsonl",
            "--raw-model",
            "qwen3.5:9b",
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-model",
            "sonar-deep-research",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "research_loop_live_shadow_report.json").exists()
    assert (out_dir / "research_loop_live_shadow_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote research live-shadow benchmark JSON" in out


def test_memla_research_benchmark_replay_forwards_deployment_economics_args(monkeypatch, capsys, tmp_path):
    seen: dict[str, object] = {}

    def _fake_run(**kwargs):
        seen.update(kwargs)
        return {
            "benchmark_type": "research_loop_replay",
            "raw": {"action_accuracy": 0.25, "avg_estimated_cost": 0.018},
            "memla": {"action_accuracy": 0.75, "avg_estimated_cost": 0.011},
            "frontier": {"action_accuracy": 0.75, "avg_estimated_cost": 0.013},
            "deployment_economics": {
                "memla": {"modeled_cost_per_1k_sessions": 44.0},
                "frontier": {"modeled_cost_per_1k_sessions": 656.0},
                "savings_vs_frontier_per_1k_sessions": {"memla": 612.0},
            },
            "rows": [],
        }

    monkeypatch.setattr("memory_system.cli.run_research_loop_replay_benchmark", _fake_run)
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Loop Benchmark\n",
    )

    out_dir = tmp_path / "research_replay_econ"
    rc = main(
        [
            "research",
            "benchmark-replay",
            "--cases",
            "cases/research_loop_eval_cases_v1.jsonl",
            "--raw-model",
            "qwen3.5:9b",
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-model",
            "claude-sonnet-4-20250514",
            "--deploy-memla-fixed-cost-per-decision",
            "0.0012",
            "--deploy-frontier-input-price-per-million",
            "15",
            "--deploy-frontier-output-price-per-million",
            "75",
            "--deploy-memla-fallback-use-verifier-rate",
            "--deploy-decisions-per-session",
            "3.8",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert seen["deploy_memla_fixed_cost_per_decision"] == 0.0012
    assert seen["deploy_frontier_input_price_per_million"] == 15.0
    assert seen["deploy_frontier_output_price_per_million"] == 75.0
    assert seen["deploy_memla_fallback_use_verifier_rate"] is True
    assert seen["deploy_decisions_per_session"] == 3.8
    out = capsys.readouterr().out
    assert "Economics:" in out


def test_memla_research_eval_harness_prints_compact_verdict(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_research_loop_replay_benchmark",
        lambda **kwargs: {
            "benchmark_type": "research_loop_replay",
            "memla": {"false_converge_rate": 0.0132},
            "frontier": {"false_converge_rate": 0.0263},
            "deployment_economics": {
                "savings_vs_frontier_per_1k_sessions": {"memla": 132.84},
            },
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Eval Harness\n",
    )

    input_path = tmp_path / "historical_logs.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    out_dir = tmp_path / "research_eval_harness"
    rc = main(
        [
            "research",
            "eval-harness",
            "--input",
            str(input_path),
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-model",
            "claude-sonnet-4-20250514",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "research_eval_harness_report.json").exists()
    assert (out_dir / "research_eval_harness_report.md").exists()
    out = capsys.readouterr().out
    assert "Eval Harness Verdict: PASS" in out
    assert "Frontier false-converge: 2.63%" in out
    assert "Memla false-converge: 1.32%" in out
    assert "Delta vs baseline: -1.31pp" in out
    assert "Estimated cost delta / 1,000 sessions: $132.84" in out


def test_memla_research_eval_harness_normalizes_capture_when_requested(monkeypatch, capsys, tmp_path):
    seen: dict[str, object] = {}

    def _fake_convert(events_path, out_cases_path, min_iterations=1):
        seen["events_path"] = events_path
        seen["out_cases_path"] = out_cases_path
        seen["min_iterations"] = min_iterations
        Path(out_cases_path).write_text("{}\n", encoding="utf-8")
        return {"out_cases_path": out_cases_path}

    def _fake_run(**kwargs):
        seen.update(kwargs)
        return {
            "benchmark_type": "research_loop_replay",
            "memla": {"false_converge_rate": 0.01},
            "frontier": {"false_converge_rate": 0.02},
            "rows": [],
        }

    monkeypatch.setattr("memory_system.cli.convert_research_loop_events_to_cases", _fake_convert)
    monkeypatch.setattr("memory_system.cli.run_research_loop_replay_benchmark", _fake_run)
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Eval Harness\n",
    )

    input_path = tmp_path / "capture.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    out_dir = tmp_path / "research_eval_harness_norm"
    rc = main(
        [
            "research",
            "eval-harness",
            "--input",
            str(input_path),
            "--normalize-capture",
            "--min-iterations",
            "2",
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-model",
            "claude-sonnet-4-20250514",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert seen["events_path"] == str(input_path.resolve())
    assert str(seen["cases_path"]).endswith("research_eval_cases.jsonl")
    assert seen["min_iterations"] == 2


def test_memla_research_eval_harness_applies_pricing_profile_and_logged_baseline(monkeypatch, capsys, tmp_path):
    seen: dict[str, object] = {}

    def _fake_run(**kwargs):
        seen.update(kwargs)
        return {
            "benchmark_type": "research_loop_replay",
            "memla": {"false_converge_rate": 0.01},
            "frontier": {"false_converge_rate": 0.02},
            "deployment_economics": {
                "savings_vs_frontier_per_1k_sessions": {"memla": 111.11},
            },
            "rows": [],
        }

    monkeypatch.setattr("memory_system.cli.run_research_loop_replay_benchmark", _fake_run)
    monkeypatch.setattr(
        "memory_system.cli.render_research_loop_markdown",
        lambda report: "# Research Eval Harness\n",
    )

    input_path = tmp_path / "historical_logs.jsonl"
    input_path.write_text("{}\n", encoding="utf-8")
    out_dir = tmp_path / "research_eval_harness_profile"
    rc = main(
        [
            "research",
            "eval-harness",
            "--input",
            str(input_path),
            "--memla-model",
            "qwen3.5:9b",
            "--frontier-use-logged-decisions",
            "--pricing-profile",
            "perplexity_public_sonar",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert seen["frontier_use_logged_decisions"] is True
    assert seen["deploy_memla_fixed_cost_per_decision"] == 0.002
    assert seen["deploy_frontier_input_price_per_million"] == 2.0
    assert seen["deploy_frontier_output_price_per_million"] == 8.0
    assert seen["deploy_frontier_fixed_cost_per_decision"] == 0.005
    assert seen["deploy_memla_fallback_use_verifier_rate"] is True
