from __future__ import annotations

import json

from memory_system.cli import main
from memory_system.distillation.policy_authz_policy_bank import (
    distill_policy_authz_policy_bank,
    suggest_policy_authz_priors,
)
from memory_system.distillation.policy_trace_bank import extract_policy_trace_bank


def test_extract_policy_trace_bank_marks_teacher_advantage(tmp_path):
    report_path = tmp_path / "policy_authz_benchmark_report.json"
    report_path.write_text(
        json.dumps(
            {
                "raw_model": "DeepSeek-R1",
                "memla_model": "qwen3.5:9b",
                "raw_provider": "github_models",
                "memla_provider": "ollama",
                "rows": [
                    {
                        "prompt": "A production deploy request falls outside the change window and should be reviewed.",
                        "expected_outcome": "escalate",
                        "expected_rule_hits": ["outside_change_window"],
                        "expected_actions": ["queue_for_change_window"],
                        "actual_rule_hits": ["outside_change_window"],
                        "raw_decision": "escalate",
                        "raw_predicted_rule_hits": ["outside_change_window"],
                        "raw_next_actions": ["queue_for_change_window"],
                        "raw_rewrite": {},
                        "raw_final_status": "escalate_ok",
                        "raw_policy_utility": 0.9,
                        "raw_iteration_trace": [{"parse_mode": "json", "rationale": "change window review"}],
                        "memla_decision": "escalate",
                        "memla_predicted_rule_hits": [],
                        "memla_next_actions": ["queue_for_change_window"],
                        "memla_rewrite": {},
                        "memla_final_status": "escalate_ok",
                        "memla_policy_utility": 0.7,
                        "memla_iteration_trace": [{"parse_mode": "json", "rationale": "escalate"}],
                        "utility_delta": -0.2,
                        "raw_outcome_match": 1.0,
                        "memla_outcome_match": 1.0,
                        "raw_rule_recall": 1.0,
                        "memla_rule_recall": 0.0,
                        "raw_action_recall": 1.0,
                        "memla_action_recall": 1.0,
                        "raw_rewrite_recall": 1.0,
                        "memla_rewrite_recall": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    bank = extract_policy_trace_bank(report_paths=[str(report_path)])

    assert bank["rows_extracted"] == 1
    assert bank["winner_counts"] == {"raw": 1}
    row = bank["rows"][0]
    assert row["teacher_signal_class"] == "teacher_advantage"
    assert row["teaching_priority"] == "high"
    assert row["teacher_unique_rule_hits"] == ["outside_change_window"]


def test_distill_policy_authz_bank_aggregates_teacher_rule_priors(tmp_path):
    trace_bank_path = tmp_path / "policy_trace_bank_summary.json"
    trace_bank_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "prompt": "A production deploy request falls outside the change window and should be reviewed.",
                        "raw_model": "DeepSeek-R1",
                        "winner": "raw",
                        "utility_delta": -0.2,
                        "raw_policy_utility": 0.9,
                        "memla_policy_utility": 0.7,
                        "teaching_priority": "high",
                        "actual_rule_hits": ["outside_change_window"],
                        "expected_rule_hits": ["outside_change_window"],
                        "expected_actions": ["queue_for_change_window"],
                        "raw_decision": "escalate",
                        "raw_rule_hits": ["outside_change_window"],
                        "raw_actions": ["queue_for_change_window"],
                        "memla_decision": "escalate",
                        "memla_rule_hits": [],
                        "memla_actions": ["queue_for_change_window"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    bank = distill_policy_authz_policy_bank(trace_bank_path=str(trace_bank_path))

    assert bank["rows_used"] == 1
    assert bank["token_teacher_rule_weights"]["window"]["outside_change_window"] > 0
    assert bank["token_teacher_decision_weights"]["review"]["escalate"] > 0
    assert bank["state_teacher_decision_weights"]["soft_review_state"]["escalate"] > 0
    assert bank["state_teacher_rule_weights"]["time_window_constraint"]["outside_change_window"] > 0


def test_suggest_policy_authz_priors_reads_local_bank(tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / ".memla" / "policy_authz_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"window": 1, "review": 1},
                "state_primitive_counts": {"soft_review_state": 1, "time_window_constraint": 1},
                "token_decision_weights": {"window": {"block": 1.2}},
                "token_rule_weights": {"window": {"outside_change_window": 1.0}},
                "token_action_weights": {"window": {"queue_for_change_window": 1.0}},
                "state_decision_weights": {"soft_review_state": {"block": 1.1}},
                "state_action_weights": {"time_window_constraint": {"queue_for_change_window": 1.2}},
                "token_teacher_decision_weights": {"review": {"escalate": 2.1}},
                "token_teacher_rule_weights": {"window": {"outside_change_window": 2.0}},
                "token_teacher_action_weights": {"review": {"queue_for_change_window": 1.8}},
                "state_teacher_decision_weights": {"soft_review_state": {"escalate": 2.4}},
                "state_teacher_action_weights": {"time_window_constraint": {"queue_for_change_window": 2.2}},
                "state_teacher_rule_weights": {"time_window_constraint": {"outside_change_window": 2.1}},
            }
        ),
        encoding="utf-8",
    )

    priors = suggest_policy_authz_priors(
        prompt="This review request is outside the change window.",
        actual_rule_hits=["outside_change_window"],
        repo_root=str(tmp_path),
    )

    assert "window" in priors["matched_tokens"]
    assert "soft_review_state" in priors["state_primitives"]
    assert priors["decisions"] == ["block"]
    assert priors["primitive_decisions"] == ["block"]
    assert priors["teacher_rescue_decisions"] == ["escalate"]
    assert "outside_change_window" in priors["teacher_rescue_rules"]


def test_run_policy_benchmark_uses_policy_bank_for_memla_lane(monkeypatch, tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    bank_path = tmp_path / ".memla" / "policy_authz_policy_bank.json"
    bank_path.write_text(
        json.dumps(
            {
                "token_counts": {"window": 1, "review": 1},
                "token_decision_weights": {},
                "token_rule_weights": {},
                "token_action_weights": {},
                "token_teacher_decision_weights": {"window": {"escalate": 2.5}},
                "token_teacher_rule_weights": {"window": {"outside_change_window": 2.0}},
                "token_teacher_action_weights": {"review": {"queue_for_change_window": 2.0}},
            }
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "policy_case.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "change_window_escalate",
                "prompt": "A production deploy request is outside the change window and should be reviewed.",
                "subject": {"actor_id": "user-1", "roles": ["deployer"]},
                "request": {
                    "action": "deploy_prod",
                    "resource": "prod_api",
                    "owner_id": "svc-1",
                    "region": "US",
                    "local_hour": 23,
                    "mfa_present": True,
                    "break_glass_approved": False,
                },
                "policy": {
                    "owner_allowed_actions": ["read_profile"],
                    "allow_roles": [{"resource": "prod_api", "actions": ["deploy_prod"], "roles": ["deployer"]}],
                    "mfa_required_actions": [],
                    "allowed_regions_by_resource": {"prod_api": ["US"]},
                    "change_windows": {"deploy_prod": {"start_hour": 9, "end_hour": 17}},
                    "break_glass_actions": [],
                    "restricted_resource_roles": {},
                },
                "expected_outcome": "escalate",
                "expected_rule_hits": ["outside_change_window"],
                "expected_actions": ["queue_for_change_window"],
                "expected_rewrite": {},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, provider: str):
            self.provider = provider
            self.messages: list[str] = []

        def chat(self, **kwargs):
            content = str(kwargs["messages"][-1].content)
            self.messages.append(content)
            if self.provider == "github_models":
                return json.dumps(
                    {
                        "decision": "escalate",
                        "predicted_rule_hits": ["outside_change_window"],
                        "next_actions": ["queue_for_change_window"],
                        "rewrite": {},
                        "rationale": "Queue deploy outside the approved window.",
                    }
                )
            return json.dumps(
                {
                    "decision": "escalate" if "Teacher rescue decisions" in content else "block",
                    "predicted_rule_hits": ["outside_change_window"] if "Teacher rescue rules" in content else [],
                    "next_actions": ["queue_for_change_window"],
                    "rewrite": {},
                    "rationale": "Use policy priors if available.",
                }
            )

    clients: dict[str, DummyClient] = {}

    def _fake_build(provider=None, base_url=None, api_key=None):
        key = provider or "ollama"
        client = DummyClient(key)
        clients[key] = client
        return client

    monkeypatch.setattr(
        "memory_system.distillation.policy_authz_benchmark._build_llm_client",
        _fake_build,
    )

    rc = main(
        [
            "policy",
            "benchmark-authz",
            "--cases",
            str(cases_path),
            "--repo-root",
            str(tmp_path),
            "--raw-model",
            "DeepSeek-R1",
            "--memla-model",
            "qwen3.5:9b",
            "--raw-provider",
            "github_models",
            "--memla-provider",
            "ollama",
            "--memla-policy-bank-path",
            str(bank_path),
            "--out-dir",
            str(tmp_path / "policy_report"),
        ]
    )

    assert rc == 0
    assert "Teacher rescue decisions (prefer these over weaker defaults" in clients["ollama"].messages[0]
    assert "Primitive state: soft_review_state, time_window_constraint" in clients["ollama"].messages[0]


def test_memla_policy_extract_and_distill_write_bundles(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.extract_policy_trace_bank",
        lambda **kwargs: {
            "rows_extracted": 1,
            "winner_counts": {"raw": 1},
            "teacher_signal_class_counts": {"teacher_advantage": 1},
            "rows": [{"prompt": "change window review", "winner": "raw"}],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_policy_trace_bank_markdown",
        lambda report: "# Policy Authz Trace Bank\n",
    )

    extract_dir = tmp_path / "policy_trace_bank"
    rc = main(
        [
            "policy",
            "extract-authz",
            "--report",
            "policy_report.json",
            "--out-dir",
            str(extract_dir),
        ]
    )

    assert rc == 0
    assert (extract_dir / "policy_trace_bank_summary.json").exists()
    assert (extract_dir / "policy_trace_bank_summary.md").exists()
    assert (extract_dir / "policy_trace_bank.jsonl").exists()

    trace_bank = tmp_path / "trace_bank.json"
    trace_bank.write_text('{"rows":[]}', encoding="utf-8")

    rc = main(
        [
            "policy",
            "distill-authz",
            "--trace-bank",
            str(trace_bank),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert (tmp_path / ".memla" / "policy_authz_policy_bank.json").exists()
    assert (tmp_path / ".memla" / "policy_authz_policy_bank.md").exists()
    out = capsys.readouterr().out
    assert "Wrote policy bank JSON" in out
