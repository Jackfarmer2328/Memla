from __future__ import annotations

import json

from memory_system.cli import main
from memory_system.distillation.c2a_policy_bank import distill_c2a_policy_bank
from memory_system.distillation.coding_log import WorkflowPriorSummary
from memory_system.distillation.workflow_planner import build_workflow_plan


def test_distill_c2a_policy_bank_aggregates_memla_and_teacher_priors(tmp_path):
    trace_bank_path = tmp_path / "c2a_trace_bank_summary.json"
    trace_bank_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "prompt": "Expose the public CLI doctor entrypoint and install metadata.",
                        "raw_model": "Meta-Llama-3.1-405B-Instruct",
                        "winner": "memla",
                        "utility_delta": 0.42,
                        "raw_c2a_utility": 0.18,
                        "memla_c2a_utility": 0.6,
                        "teaching_priority": "high",
                        "teacher_signal_class": "teacher_partial_signal",
                        "memla_predicted_constraints": ["cli_command_flow", "verification_gate"],
                        "memla_role_targets": ["cli_surface", "test_surface", "dependency_manifest"],
                        "memla_predicted_transmutations": [
                            "Trade shell flexibility for a repeatable command-line workflow."
                        ],
                        "memla_expected_file_hits": ["memla.py", "memory_system/cli.py", "pyproject.toml"],
                        "memla_selected_regions": ["memla.py", "memory_system/cli.py", "tests"],
                        "teacher_unique_constraints": ["verification_gate"],
                        "teacher_unique_transmutations": ["Expose CLI entrypoint and verify doctor command behavior."],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    bank = distill_c2a_policy_bank(trace_bank_path=str(trace_bank_path))

    assert bank["rows_used"] == 1
    assert "cli" in bank["token_constraint_weights"]
    assert bank["token_constraint_weights"]["cli"]["cli_command_flow"] > 0
    assert bank["token_role_weights"]["doctor"]["cli_surface"] > 0
    assert bank["token_teacher_transmutation_weights"]["entrypoint"][
        "Expose CLI entrypoint and verify doctor command behavior."
    ] > 0


def test_workflow_plan_uses_self_transmutation_policy_bank(tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / "memory_system").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "memla.py").write_text("print('ok')\n", encoding="utf-8")
    (tmp_path / "memory_system" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='memla'\n", encoding="utf-8")
    (tmp_path / "tests" / "test_step17_memla_cli.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / ".memla" / "c2a_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"cli": 1, "doctor": 1, "entrypoint": 1, "install": 1, "metadata": 1},
                "token_constraint_weights": {
                    "cli": {"cli_command_flow": 2.1},
                    "doctor": {"verification_gate": 1.0},
                },
                "token_role_weights": {
                    "cli": {"cli_surface": 2.0, "test_surface": 1.3},
                    "install": {"dependency_manifest": 1.2},
                },
                "token_transmutation_weights": {
                    "entrypoint": {
                        "Trade shell flexibility for a repeatable command-line workflow.": 2.4
                    }
                },
                "token_file_weights": {
                    "cli": {"memory_system/cli.py": 2.0, "memla.py": 1.8},
                    "install": {"pyproject.toml": 1.6},
                    "doctor": {"tests/test_step17_memla_cli.py": 1.4},
                },
                "token_region_weights": {
                    "cli": {"memory_system/cli.py": 2.0},
                    "doctor": {"tests": 1.5},
                    "install": {"pyproject.toml": 1.2},
                },
                "token_teacher_constraint_weights": {"doctor": {"verification_gate": 0.6}},
                "token_teacher_transmutation_weights": {
                    "entrypoint": {"Expose CLI entrypoint and verify doctor command behavior.": 0.8}
                },
            }
        ),
        encoding="utf-8",
    )
    summary = WorkflowPriorSummary(
        suggested_files=["memory_system/cli.py"],
        suggested_commands=[],
        source_trace_ids=[7],
    )

    plan = build_workflow_plan(
        candidates=[],
        summary=summary,
        prompt="Expose the public CLI doctor entrypoint and install metadata so Memla behaves like a tool.",
        repo_root=str(tmp_path),
        enable_compile_loop=False,
    )

    assert "cli_command_flow" in plan.predicted_constraints
    assert "memory_system/cli.py" in plan.likely_files
    assert "memla.py" in plan.likely_files
    assert "Trade shell flexibility for a repeatable command-line workflow." in plan.transmutations
    assert "cli" in plan.self_transmutation_boosts["matched_tokens"]
    assert "memory_system/cli.py" in plan.self_transmutation_boosts["preferred_files"]


def test_workflow_plan_can_disable_self_transmutation_policy_bank(tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / "memory_system").mkdir(parents=True)
    (tmp_path / "memory_system" / "cli.py").write_text("def main():\n    return 0\n", encoding="utf-8")
    (tmp_path / ".memla" / "c2a_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"cli": 1},
                "token_constraint_weights": {"cli": {"cli_command_flow": 2.0}},
                "token_role_weights": {"cli": {"cli_surface": 2.0}},
                "token_transmutation_weights": {
                    "cli": {"Trade shell flexibility for a repeatable command-line workflow.": 2.0}
                },
                "token_file_weights": {"cli": {"memory_system/cli.py": 2.0}},
                "token_region_weights": {"cli": {"memory_system/cli.py": 2.0}},
                "token_teacher_constraint_weights": {},
                "token_teacher_transmutation_weights": {},
            }
        ),
        encoding="utf-8",
    )
    summary = WorkflowPriorSummary(
        suggested_files=[],
        suggested_commands=[],
        source_trace_ids=[7],
    )

    plan = build_workflow_plan(
        candidates=[],
        summary=summary,
        prompt="Expose the public CLI.",
        repo_root=str(tmp_path),
        enable_compile_loop=False,
        disable_c2a_policy=True,
    )

    assert plan.self_transmutation_boosts["matched_tokens"] == []
    assert plan.self_transmutation_boosts["preferred_files"] == []
    assert plan.self_transmutation_boosts["transmutations"] == []


def test_memla_distill_c2a_writes_policy_bank(monkeypatch, capsys, tmp_path):
    trace_bank = tmp_path / "trace_bank.json"
    trace_bank.write_text('{"rows":[]}', encoding="utf-8")

    rc = main(
        [
            "coding",
            "distill-c2a",
            "--trace-bank",
            str(trace_bank),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert (tmp_path / ".memla" / "c2a_policy_bank.json").exists()
    assert (tmp_path / ".memla" / "c2a_policy_bank.md").exists()
    out = capsys.readouterr().out
    assert "Wrote C2A policy bank JSON" in out
