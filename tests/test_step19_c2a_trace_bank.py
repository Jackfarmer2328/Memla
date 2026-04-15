from __future__ import annotations

import json

from memory_system.cli import main
from memory_system.distillation.c2a_trace_bank import extract_c2a_trace_bank


def test_extract_c2a_trace_bank_classifies_partial_teacher_signal(tmp_path):
    report_path = tmp_path / "coding_c2a_benchmark_report.json"
    report_path.write_text(
        json.dumps(
            {
                "repo_root": str(tmp_path),
                "cases_path": str(tmp_path / "cases.jsonl"),
                "raw_model": "Meta-Llama-3.1-405B-Instruct",
                "memla_model": "qwen3.5:9b",
                "raw_provider": "github_models",
                "memla_provider": "ollama",
                "rows": [
                    {
                        "prompt": "Build a workflow planner from accepted repo wins.",
                        "expected_files": [
                            "memory_system/distillation/workflow_planner.py",
                            "tests/test_step17_memla_cli.py",
                        ],
                        "expected_commands": ["py -3 -m pytest -q tests/test_step17_memla_cli.py"],
                        "expected_roles": ["cli_surface", "test_surface"],
                        "expected_regions": ["memory_system/distillation", "tests"],
                        "raw_likely_files": ["memory_system/distillation/workflow_planner.py"],
                        "raw_likely_commands": [],
                        "raw_likely_tests": [],
                        "raw_role_targets": [],
                        "raw_predicted_constraints": ["verification_gate"],
                        "raw_predicted_transmutations": ["Trade vague search for a narrower path."],
                        "raw_file_recall": 0.5,
                        "raw_command_recall": 0.0,
                        "raw_verification_recall": 0.0,
                        "raw_role_recall": 0.0,
                        "raw_region_recall": 0.5,
                        "raw_c2a_utility": 0.275,
                        "memla_likely_files": [
                            "memory_system/distillation/workflow_planner.py",
                            "tests/test_step17_memla_cli.py",
                        ],
                        "memla_likely_commands": ["pytest"],
                        "memla_likely_tests": ["pytest"],
                        "memla_role_targets": ["cli_surface", "test_surface"],
                        "memla_predicted_constraints": ["verification_gate", "cli_command_flow"],
                        "memla_predicted_transmutations": ["Trade shell flexibility for a repeatable CLI flow."],
                        "memla_selected_regions": ["memory_system/distillation", "tests"],
                        "memla_file_recall": 1.0,
                        "memla_command_recall": 0.0,
                        "memla_verification_recall": 0.0,
                        "memla_role_recall": 1.0,
                        "memla_region_recall": 1.0,
                        "memla_c2a_utility": 0.7,
                        "utility_delta": 0.425,
                        "raw_response_text": "{\"likely_files\":[\"memory_system/distillation/workflow_planner.py\"]}",
                        "raw_parse_mode": "heuristic_paths",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    bank = extract_c2a_trace_bank(report_paths=[str(report_path)])

    assert bank["rows_extracted"] == 1
    assert bank["winner_counts"] == {"memla": 1}
    row = bank["rows"][0]
    assert row["teacher_signal_class"] == "teacher_partial_signal_format_constrained"
    assert row["teaching_priority"] == "medium"
    assert row["raw_expected_file_hits"] == ["memory_system/distillation/workflow_planner.py"]
    assert row["memla_expected_file_hits"] == [
        "memory_system/distillation/workflow_planner.py",
        "tests/test_step17_memla_cli.py",
    ]
    assert "format_repair_needed" in row["teacher_signal_reasons"]
    assert "file_targeting" in row["teacher_signal_axes"]
    assert "role_targeting" in row["dominant_advantage_axes"]


def test_memla_extract_c2a_writes_trace_bank_bundle(monkeypatch, capsys, tmp_path):
    def _fake_extract(**kwargs):
        return {
            "rows_extracted": 2,
            "winner_counts": {"memla": 2},
            "teacher_signal_class_counts": {"teacher_partial_signal": 2},
            "rows": [
                {
                    "prompt": "one",
                    "winner": "memla",
                    "teacher_signal_class": "teacher_partial_signal",
                    "teaching_priority": "medium",
                },
                {
                    "prompt": "two",
                    "winner": "memla",
                    "teacher_signal_class": "teacher_partial_signal",
                    "teaching_priority": "high",
                },
            ],
        }

    monkeypatch.setattr("memory_system.cli.extract_c2a_trace_bank", _fake_extract)
    monkeypatch.setattr(
        "memory_system.cli.render_c2a_trace_bank_markdown",
        lambda report: "# Coding C2A Trace Bank\n",
    )

    out_dir = tmp_path / "trace_bank"
    rc = main(
        [
            "coding",
            "extract-c2a",
            "--report",
            "one.json",
            "--report",
            "two.json",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "c2a_trace_bank_summary.json").exists()
    assert (out_dir / "c2a_trace_bank_summary.md").exists()
    assert (out_dir / "c2a_trace_bank.jsonl").exists()
    jsonl_lines = (out_dir / "c2a_trace_bank.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(jsonl_lines) == 2
    out = capsys.readouterr().out
    assert "Wrote C2A trace bank JSONL" in out
    assert "rows 2" in out
