from __future__ import annotations

import json
from pathlib import Path

from memory_system.cli import main
from memory_system.distillation.policy_authz_benchmark import (
    _normalize_action,
    _normalize_rule,
    load_policy_authz_cases,
    render_policy_authz_markdown,
    run_policy_authz_benchmark,
    _normalize_decision_payload,
)


def test_run_policy_authz_benchmark_repairs_missing_mfa(monkeypatch, tmp_path):
    cases_path = tmp_path / "policy_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "mfa_export_modify",
                "prompt": "MFA is required before export.",
                "subject": {"actor_id": "user-1", "roles": ["billing_analyst"]},
                "request": {
                    "action": "export_report",
                    "resource": "us_billing_data",
                    "owner_id": "acct-9",
                    "region": "US",
                    "local_hour": 10,
                    "mfa_present": False,
                    "break_glass_approved": False,
                },
                "policy": {
                    "owner_allowed_actions": ["read_profile"],
                    "allow_roles": [{"resource": "us_billing_data", "actions": ["export_report"], "roles": ["billing_analyst"]}],
                    "mfa_required_actions": ["export_report"],
                    "allowed_regions_by_resource": {"us_billing_data": ["US"]},
                    "change_windows": {},
                    "break_glass_actions": [],
                    "restricted_resource_roles": {},
                },
                "expected_outcome": "modify",
                "expected_rule_hits": ["mfa_required"],
                "expected_actions": ["require_mfa_then_retry"],
                "expected_rewrite": {"mfa_present": True},
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
                        "predicted_rule_hits": ["requires_mfa"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks fine.",
                    }
                )
            if self.calls == 1:
                return json.dumps(
                    {
                        "decision": "allow",
                        "predicted_rule_hits": ["requires_mfa"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks fine.",
                    }
                )
            return json.dumps(
                {
                    "decision": "modify",
                    "predicted_rule_hits": ["requires_mfa"],
                    "next_actions": ["enable_mfa"],
                    "rewrite": {"mfa_present": True},
                    "rationale": "Require MFA and retry.",
                }
            )

    monkeypatch.setattr(
        "memory_system.distillation.policy_authz_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    report = run_policy_authz_benchmark(
        cases_path=str(cases_path),
        raw_model="DeepSeek-R1",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    assert report["cases"] == 1
    assert report["avg_memla_backtest_passed"] > report["avg_raw_backtest_passed"]
    assert report["avg_memla_policy_utility"] > report["avg_raw_policy_utility"]
    row = report["rows"][0]
    assert row["raw_decision"] == "allow"
    assert row["memla_decision"] == "modify"
    assert row["memla_predicted_rule_hits"] == ["mfa_required"]
    assert row["memla_next_actions"] == ["require_mfa_then_retry"]
    assert len(row["memla_iteration_trace"]) == 2

    md = render_policy_authz_markdown(report)
    assert "# Policy Authz Benchmark" in md
    assert "Policy utility" in md


def test_memla_policy_authz_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def _fake_policy_benchmark(**kwargs):
        captured.update(kwargs)
        return {
            "avg_raw_policy_utility": 0.4,
            "avg_memla_policy_utility": 0.9,
            "memla_vs_raw_policy_utility_index": 2.25,
            "rows": [],
        }

    monkeypatch.setattr("memory_system.cli.run_policy_authz_benchmark", _fake_policy_benchmark)
    monkeypatch.setattr("memory_system.cli.render_policy_authz_markdown", lambda report: "# Policy Authz Benchmark\n")

    out_dir = tmp_path / "policy_report"
    rc = main(
        [
            "policy",
            "benchmark-authz",
            "--cases",
            "cases.jsonl",
            "--raw-model",
            "DeepSeek-R1",
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
    assert (out_dir / "policy_authz_benchmark_report.json").exists()
    assert (out_dir / "policy_authz_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote policy benchmark JSON" in out
    assert "memla utility 0.9" in out
    assert captured["raw_provider"] == "github_models"
    assert captured["memla_provider"] == "ollama"


def test_policy_alias_normalization_maps_common_names():
    assert _normalize_rule(["requires_mfa", "region_restriction", "change_window", "change_window_violation", "restricted_role"]) == [
        "mfa_required",
        "region_restricted",
        "outside_change_window",
        "restricted_resource_role",
    ]
    assert _normalize_action(["enable_mfa", "route_region", "queue_change", "deny_request", "require_break_glass_approval_then_retry"]) == [
        "require_mfa_then_retry",
        "route_to_allowed_region",
        "queue_for_change_window",
        "block_request",
        "request_break_glass_review",
    ]


def test_policy_contextual_action_normalization_maps_generic_review_to_matching_rule():
    payload = _normalize_decision_payload(
        {
            "decision": "escalate",
            "predicted_rule_hits": ["change_window_violation"],
            "next_actions": ["await_reviewer_approval"],
            "rewrite": {},
            "rationale": "Outside the change window; reviewer approval required.",
        },
        '{"decision":"escalate","predicted_rule_hits":["change_window_violation"],"next_actions":["await_reviewer_approval"]}',
    )

    assert payload.predicted_rule_hits == ["outside_change_window"]
    assert payload.next_actions == ["queue_for_change_window"]


def test_public_policy_pack_loads_and_covers_expected_rule_families():
    cases_path = Path("cases/policy_authz_eval_cases.jsonl")
    cases = load_policy_authz_cases(str(cases_path))

    assert {case.case_id for case in cases} == {
        "mfa_export_modify",
        "owner_profile_allow",
        "break_glass_delete_escalate",
        "region_route_modify",
        "change_window_escalate",
        "restricted_prod_db_block",
        "missing_role_block",
    }
    assert {rule for case in cases for rule in case.expected_rule_hits} == {
        "mfa_required",
        "break_glass_required",
        "region_restricted",
        "outside_change_window",
        "restricted_resource_role",
        "role_not_permitted",
    }
