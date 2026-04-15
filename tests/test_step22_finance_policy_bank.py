from __future__ import annotations

import json

from memory_system.cli import main
from memory_system.distillation.finance_policy_bank import (
    distill_finance_policy_bank,
    suggest_finance_policy_priors,
)
from memory_system.distillation.finance_trace_bank import extract_finance_trace_bank


def test_extract_finance_trace_bank_marks_teacher_advantage(tmp_path):
    report_path = tmp_path / "finance_pretrade_benchmark_report.json"
    report_path.write_text(
        json.dumps(
            {
                "raw_model": "meta/Llama-3.3-70B-Instruct",
                "memla_model": "qwen3.5:9b",
                "raw_provider": "github_models",
                "memla_provider": "ollama",
                "rows": [
                    {
                        "prompt": "A matching order reappears inside the duplicate-order review window.",
                        "expected_outcome": "escalate",
                        "expected_rule_hits": ["duplicate_order_window"],
                        "expected_actions": ["hold_duplicate_for_review", "request_supervisor_approval"],
                        "actual_rule_hits": ["duplicate_order_window"],
                        "raw_decision": "escalate",
                        "raw_predicted_rule_hits": ["duplicate_order_window"],
                        "raw_next_actions": ["request_supervisor_approval"],
                        "raw_rewrite": {},
                        "raw_final_status": "escalate_ok",
                        "raw_finance_utility": 0.95,
                        "raw_iteration_trace": [{"parse_mode": "json", "rationale": "soft duplicate review"}],
                        "memla_decision": "block",
                        "memla_predicted_rule_hits": ["duplicate_order_window"],
                        "memla_next_actions": ["block_order"],
                        "memla_rewrite": {},
                        "memla_final_status": "block_ok",
                        "memla_finance_utility": 0.6,
                        "memla_iteration_trace": [{"parse_mode": "json", "rationale": "block duplicate"}],
                        "utility_delta": -0.35,
                        "raw_outcome_match": 1.0,
                        "memla_outcome_match": 0.0,
                        "raw_rule_recall": 1.0,
                        "memla_rule_recall": 1.0,
                        "raw_action_recall": 0.5,
                        "memla_action_recall": 0.0,
                        "raw_rewrite_recall": 1.0,
                        "memla_rewrite_recall": 1.0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    bank = extract_finance_trace_bank(report_paths=[str(report_path)])

    assert bank["rows_extracted"] == 1
    assert bank["winner_counts"] == {"raw": 1}
    row = bank["rows"][0]
    assert row["teacher_signal_class"] == "teacher_advantage"
    assert row["teaching_priority"] == "high"
    assert row["teacher_unique_actions"] == ["request_supervisor_approval"]


def test_distill_finance_policy_bank_aggregates_teacher_rescue_priors(tmp_path):
    trace_bank_path = tmp_path / "finance_trace_bank_summary.json"
    trace_bank_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "prompt": "A matching order reappears inside the duplicate-order review window.",
                        "raw_model": "meta/Llama-3.3-70B-Instruct",
                        "winner": "raw",
                        "utility_delta": -0.35,
                        "raw_finance_utility": 0.95,
                        "memla_finance_utility": 0.6,
                        "teaching_priority": "high",
                        "raw_decision": "escalate",
                        "raw_rule_hits": ["duplicate_order_window"],
                        "raw_actions": ["request_supervisor_approval"],
                        "memla_decision": "block",
                        "memla_rule_hits": ["duplicate_order_window"],
                        "memla_actions": ["block_order"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    bank = distill_finance_policy_bank(trace_bank_path=str(trace_bank_path))

    assert bank["rows_used"] == 1
    assert bank["token_teacher_decision_weights"]["duplicate"]["escalate"] > 0
    assert bank["token_teacher_action_weights"]["review"]["request_supervisor_approval"] > 0
    assert bank["token_decision_weights"].get("duplicate", {}).get("block", 0.0) == 0.0


def test_suggest_finance_policy_priors_reads_local_bank(tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / ".memla" / "finance_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"duplicate": 1, "review": 1},
                "token_decision_weights": {"duplicate": {"block": 1.2}},
                "token_rule_weights": {"duplicate": {"duplicate_order_window": 1.0}},
                "token_action_weights": {"duplicate": {"block_order": 1.0}},
                "token_teacher_decision_weights": {"duplicate": {"escalate": 2.1}},
                "token_teacher_rule_weights": {"review": {"duplicate_order_window": 1.5}},
                "token_teacher_action_weights": {"review": {"request_supervisor_approval": 1.8}},
            }
        ),
        encoding="utf-8",
    )

    priors = suggest_finance_policy_priors(
        prompt="A duplicate review event needs bounded handling.",
        repo_root=str(tmp_path),
    )

    assert "duplicate" in priors["matched_tokens"]
    assert priors["decisions"] == ["block"]
    assert priors["teacher_rescue_decisions"] == ["escalate"]
    assert "request_supervisor_approval" in priors["teacher_rescue_actions"]


def test_run_finance_benchmark_uses_teacher_rescue_override_wording(monkeypatch, tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / ".memla" / "finance_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"duplicate": 1},
                "token_decision_weights": {},
                "token_rule_weights": {"duplicate": {"duplicate_order_window": 1.0}},
                "token_action_weights": {},
                "token_teacher_decision_weights": {"duplicate": {"escalate": 2.5}},
                "token_teacher_rule_weights": {"duplicate": {"duplicate_order_window": 2.0}},
                "token_teacher_action_weights": {"duplicate": {"request_supervisor_approval": 2.0}},
            }
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "finance_case.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "duplicate_window_escalate",
                "prompt": "A matching order reappears inside the duplicate-order review window.",
                "order": {
                    "symbol": "MSFT",
                    "side": "buy",
                    "quantity": 100,
                    "price": 412.5,
                    "route": "ARCA",
                    "ts": 1712251320,
                },
                "account": {"current_position": 0},
                "market": {"reference_price": 412.5},
                "controls": {
                    "max_order_notional": 1000000.0,
                    "approval_notional": 800000.0,
                    "max_long_position": 5000,
                    "max_short_position": 5000,
                    "max_price_deviation_pct": 0.05,
                    "duplicate_window_seconds": 5,
                    "allowed_routes": ["ARCA"],
                },
                "recent_orders": [
                    {
                        "symbol": "MSFT",
                        "side": "buy",
                        "quantity": 100,
                        "price": 412.5,
                        "route": "ARCA",
                        "ts": 1712251317,
                    }
                ],
                "expected_outcome": "escalate",
                "expected_rule_hits": ["duplicate_order_window"],
                "expected_actions": ["request_supervisor_approval"],
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
            return json.dumps(
                {
                    "decision": "escalate" if "prefer these over weaker defaults" in content else "block",
                    "predicted_rule_hits": ["duplicate_order_window"],
                    "next_actions": ["request_supervisor_approval"],
                    "rewrite": {},
                    "rationale": "Teacher rescue override should be visible.",
                }
            )

    client = DummyClient("ollama")

    monkeypatch.setattr(
        "memory_system.distillation.finance_pretrade_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: client,
    )

    rc = main(
        [
            "finance",
            "benchmark-pretrade",
            "--cases",
            str(cases_path),
            "--repo-root",
            str(tmp_path),
            "--case-id",
            "duplicate_window_escalate",
            "--raw-model",
            "meta/Llama-3.3-70B-Instruct",
            "--memla-model",
            "qwen3.5:9b",
            "--raw-provider",
            "ollama",
            "--memla-provider",
            "ollama",
            "--out-dir",
            str(tmp_path / "finance_report"),
        ]
    )

    assert rc == 0
    assert any("Teacher rescue decisions (prefer these over weaker defaults" in message for message in client.messages)


def test_run_finance_benchmark_uses_finance_policy_bank_for_memla_lane(monkeypatch, tmp_path):
    (tmp_path / ".memla").mkdir(parents=True)
    (tmp_path / ".memla" / "finance_policy_bank.json").write_text(
        json.dumps(
            {
                "token_counts": {"duplicate": 1, "review": 1},
                "token_decision_weights": {"duplicate": {"block": 1.0}},
                "token_rule_weights": {"duplicate": {"duplicate_order_window": 1.0}},
                "token_action_weights": {"duplicate": {"block_order": 1.0}},
                "token_teacher_decision_weights": {"duplicate": {"escalate": 2.5}},
                "token_teacher_rule_weights": {"review": {"duplicate_order_window": 1.4}},
                "token_teacher_action_weights": {"review": {"request_supervisor_approval": 2.2}},
            }
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "finance_case.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "duplicate_window_escalate",
                "prompt": "A matching order reappears inside the duplicate-order review window.",
                "order": {
                    "symbol": "MSFT",
                    "side": "buy",
                    "quantity": 100,
                    "price": 412.5,
                    "route": "ARCA",
                    "ts": 1712251320,
                },
                "account": {"current_position": 0},
                "market": {"reference_price": 412.5},
                "controls": {
                    "max_order_notional": 1000000.0,
                    "approval_notional": 800000.0,
                    "max_long_position": 5000,
                    "max_short_position": 5000,
                    "max_price_deviation_pct": 0.05,
                    "duplicate_window_seconds": 5,
                    "allowed_routes": ["ARCA"],
                },
                "recent_orders": [
                    {
                        "symbol": "MSFT",
                        "side": "buy",
                        "quantity": 100,
                        "price": 412.5,
                        "route": "ARCA",
                        "ts": 1712251317,
                    }
                ],
                "expected_outcome": "escalate",
                "expected_rule_hits": ["duplicate_order_window"],
                "expected_actions": ["request_supervisor_approval"],
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
                        "predicted_rule_hits": ["duplicate_order_window"],
                        "next_actions": ["request_supervisor_approval"],
                        "rewrite": {},
                        "rationale": "Escalate duplicate order for review.",
                    }
                )
            return json.dumps(
                {
                    "decision": "escalate" if "Teacher rescue decisions: escalate" in content else "block",
                    "predicted_rule_hits": ["duplicate_order_window"],
                    "next_actions": ["request_supervisor_approval"] if "Teacher rescue decisions: escalate" in content else ["block_order"],
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
        "memory_system.distillation.finance_pretrade_benchmark._build_llm_client",
        _fake_build,
    )

    rc = main(
        [
            "finance",
            "benchmark-pretrade",
            "--cases",
            str(cases_path),
            "--repo-root",
            str(tmp_path),
            "--raw-model",
            "meta/Llama-3.3-70B-Instruct",
            "--memla-model",
            "qwen3.5:9b",
            "--raw-provider",
            "github_models",
            "--memla-provider",
            "ollama",
            "--memla-finance-policy-path",
            str(tmp_path / ".memla" / "finance_policy_bank.json"),
            "--out-dir",
            str(tmp_path / "finance_report"),
        ]
    )

    assert rc == 0
    assert "Teacher rescue decisions (prefer these over weaker defaults" in clients["ollama"].messages[0]


def test_memla_finance_extract_and_distill_write_bundles(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.extract_finance_trace_bank",
        lambda **kwargs: {
            "rows_extracted": 1,
            "winner_counts": {"raw": 1},
            "teacher_signal_class_counts": {"teacher_advantage": 1},
            "rows": [{"prompt": "duplicate review", "winner": "raw"}],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_finance_trace_bank_markdown",
        lambda report: "# Finance Pre-Trade Trace Bank\n",
    )

    extract_dir = tmp_path / "finance_trace_bank"
    rc = main(
        [
            "finance",
            "extract-pretrade",
            "--report",
            "finance_report.json",
            "--out-dir",
            str(extract_dir),
        ]
    )

    assert rc == 0
    assert (extract_dir / "finance_trace_bank_summary.json").exists()
    assert (extract_dir / "finance_trace_bank_summary.md").exists()
    assert (extract_dir / "finance_trace_bank.jsonl").exists()

    trace_bank = tmp_path / "trace_bank.json"
    trace_bank.write_text('{"rows":[]}', encoding="utf-8")

    rc = main(
        [
            "finance",
            "distill-pretrade",
            "--trace-bank",
            str(trace_bank),
            "--repo-root",
            str(tmp_path),
        ]
    )

    assert rc == 0
    assert (tmp_path / ".memla" / "finance_policy_bank.json").exists()
    assert (tmp_path / ".memla" / "finance_policy_bank.md").exists()
    out = capsys.readouterr().out
    assert "Wrote finance policy bank JSON" in out
