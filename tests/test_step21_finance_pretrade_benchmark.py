from __future__ import annotations

import json
from pathlib import Path

from memory_system.cli import main
from memory_system.distillation.finance_pretrade_benchmark import (
    FinanceDecision,
    backtest_finance_decision,
    _normalize_action,
    _normalize_rule,
    load_finance_pretrade_cases,
    render_finance_pretrade_markdown,
    run_finance_pretrade_benchmark,
)


def test_run_finance_pretrade_benchmark_repairs_notional_breach(monkeypatch, tmp_path):
    cases_path = tmp_path / "finance_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "notional_reduce_to_limit",
                "prompt": "Reduce the order to the configured hard limit.",
                "order": {
                    "symbol": "AAPL",
                    "side": "buy",
                    "quantity": 7000,
                    "price": 100.0,
                    "route": "NYSE",
                    "ts": 1712251200,
                },
                "account": {"current_position": 12000},
                "market": {"reference_price": 100.0},
                "controls": {
                    "max_order_notional": 500000.0,
                    "approval_notional": 500000.0,
                    "max_long_position": 25000,
                    "max_short_position": 10000,
                    "max_price_deviation_pct": 0.05,
                    "duplicate_window_seconds": 5,
                    "allowed_routes": ["NYSE", "ARCA"],
                },
                "recent_orders": [],
                "expected_outcome": "modify",
                "expected_rule_hits": ["max_order_notional"],
                "expected_actions": ["reduce_quantity"],
                "expected_rewrite": {"quantity": 5000},
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
                        "predicted_rule_hits": ["max_order_notional"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks safe enough.",
                    }
                )
            if self.calls == 1:
                return json.dumps(
                    {
                        "decision": "allow",
                        "predicted_rule_hits": ["max_order_notional"],
                        "next_actions": [],
                        "rewrite": {},
                        "rationale": "Looks safe enough.",
                    }
                )
            return json.dumps(
                {
                    "decision": "modify",
                    "predicted_rule_hits": ["max_order_notional", "approval_required_notional"],
                    "next_actions": ["reduce_quantity"],
                    "rewrite": {"quantity": 5000},
                    "rationale": "Reduce quantity to the hard notional threshold.",
                }
            )

    monkeypatch.setattr(
        "memory_system.distillation.finance_pretrade_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    report = run_finance_pretrade_benchmark(
        cases_path=str(cases_path),
        raw_model="grok-3",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    assert report["cases"] == 1
    assert report["raw_provider"] == "github_models"
    assert report["memla_provider"] == "ollama"
    assert report["avg_memla_backtest_passed"] > report["avg_raw_backtest_passed"]
    assert report["avg_memla_finance_utility"] > report["avg_raw_finance_utility"]
    assert report["memla_vs_raw_finance_utility_index"] is not None
    assert report["memla_vs_raw_finance_utility_index"] > 1.0
    row = report["rows"][0]
    assert row["raw_decision"] == "allow"
    assert row["memla_decision"] == "modify"
    assert len(row["memla_iteration_trace"]) == 2

    md = render_finance_pretrade_markdown(report)
    assert "# Finance Pre-Trade Benchmark" in md
    assert "Finance utility" in md
    assert "Utility delta" in md


def test_memla_finance_pretrade_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    captured: dict[str, object] = {}

    def _fake_finance_benchmark(**kwargs):
        captured.update(kwargs)
        return {
            "avg_raw_finance_utility": 0.3,
            "avg_memla_finance_utility": 0.8,
            "memla_vs_raw_finance_utility_index": 2.6667,
            "rows": [],
        }

    monkeypatch.setattr(
        "memory_system.cli.run_finance_pretrade_benchmark",
        _fake_finance_benchmark,
    )
    monkeypatch.setattr(
        "memory_system.cli.render_finance_pretrade_markdown",
        lambda report: "# Finance Pre-Trade Benchmark\n",
    )

    out_dir = tmp_path / "finance_report"
    rc = main(
        [
            "finance",
            "benchmark-pretrade",
            "--cases",
            "cases.jsonl",
            "--raw-model",
            "Meta-Llama-3.1-405B-Instruct",
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
    assert (out_dir / "finance_pretrade_benchmark_report.json").exists()
    assert (out_dir / "finance_pretrade_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote finance benchmark JSON" in out
    assert "memla utility 0.8" in out
    assert captured["raw_provider"] == "github_models"
    assert captured["memla_provider"] == "ollama"


def test_finance_alias_normalization_maps_common_rule_and_action_names():
    assert _normalize_rule(
        [
            "approval_notional",
            "restricted_symbols",
            "duplicate_window_seconds",
            "max_price_deviation_pct",
        ]
    ) == [
        "approval_required_notional",
        "restricted_symbol",
        "duplicate_order_window",
        "price_deviation_limit",
    ]
    assert _normalize_action(
        [
            "review_order",
            "reprice",
            "hold_for_review",
            "reject_order",
        ]
    ) == [
        "request_supervisor_approval",
        "reprice_within_band",
        "hold_duplicate_for_review",
        "block_order",
    ]


def test_run_finance_pretrade_benchmark_scores_alias_labels_as_matches(monkeypatch, tmp_path):
    cases_path = tmp_path / "finance_alias_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "approval_alias_case",
                "prompt": "Escalate the order for approval rather than blocking it.",
                "order": {
                    "symbol": "AAPL",
                    "side": "buy",
                    "quantity": 3000,
                    "price": 100.0,
                    "route": "NYSE",
                    "ts": 1712251200,
                },
                "account": {"current_position": 12000},
                "market": {"reference_price": 100.0},
                "controls": {
                    "max_order_notional": 500000.0,
                    "approval_notional": 250000.0,
                    "max_long_position": 25000,
                    "max_short_position": 10000,
                    "max_price_deviation_pct": 0.05,
                    "duplicate_window_seconds": 5,
                    "allowed_routes": ["NYSE", "ARCA"],
                },
                "recent_orders": [],
                "expected_outcome": "escalate",
                "expected_rule_hits": ["approval_required_notional"],
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

        def chat(self, **kwargs):
            return json.dumps(
                {
                    "decision": "escalate",
                    "predicted_rule_hits": ["approval_notional"],
                    "next_actions": ["review_order"],
                    "rewrite": {},
                    "rationale": "Supervisor review is required above the approval threshold.",
                }
            )

    monkeypatch.setattr(
        "memory_system.distillation.finance_pretrade_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    report = run_finance_pretrade_benchmark(
        cases_path=str(cases_path),
        raw_model="meta/Llama-3.3-70B-Instruct",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    row = report["rows"][0]
    assert row["raw_rule_recall"] == 1.0
    assert row["raw_action_recall"] == 1.0
    assert row["memla_rule_recall"] == 1.0
    assert row["memla_action_recall"] == 1.0


def test_run_finance_pretrade_benchmark_can_filter_case_ids(monkeypatch, tmp_path):
    cases_path = tmp_path / "finance_cases.jsonl"
    cases_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "keep_me",
                        "prompt": "Block the restricted symbol.",
                        "order": {"symbol": "MEMX", "side": "buy", "quantity": 10, "price": 100.0, "route": "NYSE", "ts": 1},
                        "account": {"current_position": 0},
                        "market": {"reference_price": 100.0},
                        "controls": {
                            "restricted_symbols": ["MEMX"],
                            "allowed_routes": ["NYSE"],
                        },
                        "recent_orders": [],
                        "expected_outcome": "block",
                        "expected_rule_hits": ["restricted_symbol"],
                        "expected_actions": ["block_order"],
                        "expected_rewrite": {},
                    }
                ),
                json.dumps(
                    {
                        "case_id": "skip_me",
                        "prompt": "Escalate the approval threshold case.",
                        "order": {"symbol": "AAPL", "side": "buy", "quantity": 3000, "price": 100.0, "route": "NYSE", "ts": 2},
                        "account": {"current_position": 0},
                        "market": {"reference_price": 100.0},
                        "controls": {
                            "approval_notional": 250000.0,
                            "allowed_routes": ["NYSE"],
                        },
                        "recent_orders": [],
                        "expected_outcome": "escalate",
                        "expected_rule_hits": ["approval_required_notional"],
                        "expected_actions": ["request_supervisor_approval"],
                        "expected_rewrite": {},
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    class DummyClient:
        def __init__(self, provider: str):
            self.provider = provider

        def chat(self, **kwargs):
            return json.dumps(
                {
                    "decision": "block",
                    "predicted_rule_hits": ["restricted_symbol"],
                    "next_actions": ["block_order"],
                    "rewrite": {},
                    "rationale": "Block the restricted symbol.",
                }
            )

    monkeypatch.setattr(
        "memory_system.distillation.finance_pretrade_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    report = run_finance_pretrade_benchmark(
        cases_path=str(cases_path),
        case_ids=["keep_me"],
        raw_model="meta/Llama-3.3-70B-Instruct",
        memla_model="qwen3.5:9b",
        raw_provider="github_models",
        memla_provider="ollama",
    )

    assert report["cases_requested"] == 1
    assert report["cases"] == 1
    assert report["rows"][0]["case_id"] == "keep_me"


def test_backtest_finance_decision_prefers_escalation_for_soft_duplicate_controls(tmp_path):
    cases_path = tmp_path / "finance_cases.jsonl"
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
    case = load_finance_pretrade_cases(str(cases_path))[0]

    blocked = backtest_finance_decision(
        case,
        FinanceDecision(
            decision="block",
            predicted_rule_hits=["duplicate_order_window"],
            next_actions=["block_order"],
            rewrite={},
            rationale="Block duplicate.",
            response_text="",
            parse_mode="json",
        ),
    )
    escalated = backtest_finance_decision(
        case,
        FinanceDecision(
            decision="escalate",
            predicted_rule_hits=["duplicate_order_window"],
            next_actions=["request_supervisor_approval"],
            rewrite={},
            rationale="Escalate duplicate for review.",
            response_text="",
            parse_mode="json",
        ),
    )

    assert blocked.compliance_passed is False
    assert blocked.final_status == "overblocked_soft_review"
    assert "soft_review_prefers_escalation:duplicate_order_window" in blocked.residual_constraints
    assert escalated.compliance_passed is True
    assert escalated.final_status == "escalate_ok"


def test_public_finance_pack_loads_and_covers_expected_rule_families():
    cases_path = Path("cases/finance_pretrade_public_eval_cases.jsonl")
    cases = load_finance_pretrade_cases(str(cases_path))

    case_ids = {case.case_id for case in cases}
    assert case_ids == {
        "public_credit_limit_reduce",
        "public_restricted_symbol_block",
        "public_duplicate_soft_review_escalate",
        "public_price_band_reprice",
        "public_approval_threshold_escalate",
        "public_unsupported_route_block",
        "public_projected_long_position_block",
        "public_projected_short_position_block",
    }

    expected_rules = {rule for case in cases for rule in case.expected_rule_hits}
    assert expected_rules == {
        "max_order_notional",
        "restricted_symbol",
        "duplicate_order_window",
        "price_deviation_limit",
        "approval_required_notional",
        "unsupported_route",
        "projected_long_position_limit",
        "projected_short_position_limit",
    }
