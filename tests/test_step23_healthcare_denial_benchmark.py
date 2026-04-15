from __future__ import annotations

import json
from pathlib import Path

from memory_system.cli import main
from memory_system.distillation.healthcare_denial_benchmark import (
    _normalize_action,
    _normalize_rule,
    load_healthcare_claim_cases,
    render_healthcare_denial_markdown,
    run_healthcare_denial_benchmark,
)


def test_run_healthcare_denial_benchmark_repairs_unit_limit(monkeypatch, tmp_path):
    cases_path = tmp_path / "healthcare_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "units_exceed_mue_reduce",
                "prompt": "Reduce units to the configured ceiling.",
                "claim": {
                    "claim_id": "hc-1",
                    "claim_type": "professional",
                    "prior_authorization_present": True,
                    "diagnosis_codes": ["M25.561"],
                    "service_lines": [
                        {
                            "line_id": "1",
                            "procedure_code": "97110",
                            "modifier_codes": [],
                            "units": 6,
                            "place_of_service": "11",
                            "diagnosis_codes": ["M25.561"],
                        }
                    ],
                },
                "denial": {"claim_adjustment_reason_codes": ["CO151"], "summary": "Units exceed threshold."},
                "controls": {"max_units_by_code": {"97110": 4}},
                "expected_outcome": "modify",
                "expected_rule_hits": ["mue_unit_limit"],
                "expected_actions": ["reduce_units"],
                "expected_rewrite": {"line_updates": [{"line_id": "1", "units": 4}]},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, provider: str):
            self.provider = provider
            self.calls = 0

        def chat(self, **kwargs):
            self.calls += 1
            if self.provider == "github_models":
                return json.dumps(
                    {
                        "decision": "allow",
                        "predicted_rule_hits": ["mue_unit_limit"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks billable.",
                    }
                )
            if self.calls == 1:
                return json.dumps(
                    {
                        "decision": "allow",
                        "predicted_rule_hits": ["mue_unit_limit"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks billable.",
                    }
                )
            return json.dumps(
                {
                    "decision": "modify",
                    "predicted_rule_hits": ["mue_units"],
                    "next_actions": ["reduce_unit_count"],
                    "rewrite": {"line_updates": [{"line_id": "1", "units": 4}]},
                    "rationale": "Reduce the units to the allowed maximum.",
                }
            )

    monkeypatch.setattr(
        "memory_system.distillation.healthcare_denial_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    report = run_healthcare_denial_benchmark(
        cases_path=str(cases_path),
        raw_model="meta/Llama-3.3-70B-Instruct",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    assert report["cases"] == 1
    assert report["avg_memla_backtest_passed"] > report["avg_raw_backtest_passed"]
    assert report["avg_memla_healthcare_utility"] > report["avg_raw_healthcare_utility"]
    assert report["memla_vs_raw_healthcare_utility_index"] is not None
    row = report["rows"][0]
    assert row["raw_decision"] == "allow"
    assert row["memla_decision"] == "modify"
    assert row["memla_predicted_rule_hits"] == ["mue_unit_limit"]
    assert row["memla_next_actions"] == ["reduce_units"]
    assert len(row["memla_iteration_trace"]) == 2

    md = render_healthcare_denial_markdown(report)
    assert "# Healthcare Claim-Denial Benchmark" in md
    assert "Healthcare utility" in md


def test_memla_healthcare_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def _fake_healthcare_benchmark(**kwargs):
        captured.update(kwargs)
        return {
            "avg_raw_healthcare_utility": 0.4,
            "avg_memla_healthcare_utility": 0.9,
            "memla_vs_raw_healthcare_utility_index": 2.25,
            "rows": [],
        }

    monkeypatch.setattr("memory_system.cli.run_healthcare_denial_benchmark", _fake_healthcare_benchmark)
    monkeypatch.setattr("memory_system.cli.render_healthcare_denial_markdown", lambda report: "# Healthcare Claim-Denial Benchmark\n")

    out_dir = tmp_path / "healthcare_report"
    rc = main(
        [
            "healthcare",
            "benchmark-denials",
            "--cases",
            "cases.jsonl",
            "--raw-model",
            "meta/Llama-3.3-70B-Instruct",
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
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "healthcare_denial_benchmark_report.json").exists()
    assert (out_dir / "healthcare_denial_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote healthcare benchmark JSON" in out
    assert "memla utility 0.9" in out
    assert captured["raw_provider"] == "github_models"
    assert captured["memla_provider"] == "ollama"


def test_healthcare_alias_normalization_maps_common_names():
    assert _normalize_rule(["mue_units", "missing_modifier", "ncci_conflict", "invalid_pos"]) == [
        "mue_unit_limit",
        "required_modifier_missing",
        "ncci_code_pair_conflict",
        "place_of_service_mismatch",
    ]
    assert _normalize_action(["reduce_unit_count", "append_modifier", "drop_line", "write_off_claim"]) == [
        "reduce_units",
        "add_required_modifier",
        "drop_conflicting_line",
        "do_not_rebill",
    ]


def test_public_healthcare_pack_loads_and_covers_expected_rule_families():
    cases_path = Path("cases/healthcare_denial_eval_cases.jsonl")
    cases = load_healthcare_claim_cases(str(cases_path))

    assert {case.case_id for case in cases} == {
        "units_exceed_mue_reduce",
        "required_modifier_add",
        "ncci_pair_drop_line",
        "diagnosis_support_replace",
        "prior_auth_missing_escalate",
        "pos_mismatch_correct",
        "noncovered_code_block",
    }
    assert {rule for case in cases for rule in case.expected_rule_hits} == {
        "mue_unit_limit",
        "required_modifier_missing",
        "ncci_code_pair_conflict",
        "diagnosis_support_mismatch",
        "prior_authorization_missing",
        "place_of_service_mismatch",
        "noncovered_service_code",
    }
