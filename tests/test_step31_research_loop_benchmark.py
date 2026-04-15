from __future__ import annotations

import json

from memory_system.distillation.research_loop_benchmark import (
    ResearchDecisionCase,
    compile_research_c2a_state,
    render_research_loop_markdown,
    run_research_loop_live_shadow_benchmark,
    run_research_loop_replay_benchmark,
)
from memory_system.distillation.research_loop_capture import convert_research_loop_events_to_cases


class DummyClient:
    def __init__(self, provider: str):
        self.provider = provider

    def chat(self, **kwargs):
        model = str(kwargs.get("model") or "")
        user_blob = "\n".join(str(getattr(item, "content", "") or "") for item in kwargs.get("messages") or [])
        if "open gaps: (none)" in user_blob.lower() and "contradictions: (none)" in user_blob.lower():
            return '{"action":"converge","query_intent":"none","next_query":"","rationale":"No critical gaps remain."}'
        if "memla" in model.lower():
            return '{"action":"search_more","query_intent":"resolve_contradiction","next_query":"resolve contradiction with independent source","rationale":"Need to collapse ambiguity first."}'
        if "frontier" in model.lower():
            return '{"action":"search_more","query_intent":"source_diversification","next_query":"collect one more independent source","rationale":"Need additional source diversity."}'
        return '{"action":"converge","query_intent":"none","next_query":"","rationale":"Good enough."}'


class ReleaseAwareDummyClient:
    def __init__(self, provider: str):
        self.provider = provider

    def chat(self, **kwargs):
        model = str(kwargs.get("model") or "")
        if "memla-release" in model.lower():
            return json.dumps(
                {
                    "action": "search_more",
                    "query_intent": "resolve_contradiction",
                    "next_query": "",
                    "rationale": "The remaining contradiction is bounded enough to scope in the final recommendation, and no new external query is needed.",
                    "release_readiness": "bounded_enough",
                    "blocking_constraints": [],
                    "bounded_constraints": [
                        "resolve_contradiction: Airflow is default for legacy installs while Dagster is better for greenfield projects."
                    ],
                }
            )
        return '{"action":"converge","query_intent":"none","next_query":"","rationale":"Good enough."}'


def test_convert_research_loop_events_to_cases(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "session_id": "s1",
                        "step_index": 1,
                        "prompt": "Find best CPU stack",
                        "known_facts": ["Need independent evidence"],
                        "open_gaps": ["Missing independent benchmark"],
                        "contradictions": [
                            {
                                "source": "source_a",
                                "snippet": "Conflicts with source_b",
                                "tokens_estimate": 77,
                            }
                        ],
                        "latest_docs": [
                            {
                                "source": "bench_doc",
                                "snippet": "Independent benchmark summary",
                                "tokens_estimate": 123,
                            }
                        ],
                        "context_tokens_so_far_estimate": 4400,
                        "new_docs_tokens_estimate": 123,
                        "decision_action": "search_more",
                        "query_intent": "source_diversification",
                        "baseline_action": "converge",
                        "baseline_query_intent": "none",
                        "baseline_rationale": "Historical frontier baseline would stop here.",
                        "tokens_if_search_more_estimate": 2200,
                        "tokens_if_converge_estimate": 300,
                    }
                ),
                json.dumps(
                    {
                        "session_id": "s1",
                        "step_index": 2,
                        "prompt": "Find best CPU stack",
                        "known_facts": ["Independent benchmark found"],
                        "open_gaps": [],
                        "decision_action": "converge",
                        "query_intent": "none",
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_cases = tmp_path / "cases.jsonl"

    summary = convert_research_loop_events_to_cases(events_path=str(events), out_cases_path=str(out_cases))

    assert summary["sessions_written"] == 1
    lines = out_cases.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["session_id"] == "s1"
    assert len(row["loop_steps"]) == 2
    assert row["loop_steps"][0]["latest_docs"][0]["tokens"] == 123
    assert row["loop_steps"][0]["contradiction_records"][0]["tokens"] == 77
    assert row["loop_steps"][0]["context_tokens_so_far"] == 4400
    assert row["loop_steps"][0]["tokens_if_search_more"] == 2200
    assert row["loop_steps"][0]["frontier_reference_action"] == "converge"
    assert row["loop_steps"][0]["frontier_reference_rationale"] == "Historical frontier baseline would stop here."


def test_compile_research_c2a_state_allows_bounded_release_for_resolved_contradictions():
    case = ResearchDecisionCase(
        case_id="bounded-1",
        session_id="s-bounded",
        prompt="Map workflow orchestration options",
        user_goal="Compare the best workflow orchestrators for 2026 and recommend one with contradictions resolved.",
        known_facts=[
            "Airflow remains the common default in legacy enterprise environments.",
            "Dagster is increasingly recommended for greenfield data and ML projects.",
            "Flyte is strong for Kubernetes-native ML but is operationally heavier.",
            "Metaflow often sits on top of another orchestrator rather than replacing one outright.",
        ],
        open_gaps=[],
        contradictions=[
            "Some sources insist Airflow should still be the default, while others argue Dagster is better for new projects; tension resolved by distinguishing legacy installs from greenfield adoption."
        ],
        latest_docs=[
            {
                "source": "airflow-2026-guide",
                "snippet": "Airflow stays dominant in existing enterprise estates with broad ecosystem coverage.",
                "tokens": 240,
            },
            {
                "source": "dagster-2026-guide",
                "snippet": "Dagster is the better default for new greenfield teams prioritizing modern software-defined assets.",
                "tokens": 220,
            },
            {
                "source": "flyte-ops",
                "snippet": "Flyte excels for Kubernetes-native ML orchestration but carries more operational complexity.",
                "tokens": 180,
            },
            {
                "source": "metaflow-overview",
                "snippet": "Metaflow is better understood as an ML workflow framework layered onto schedulers rather than a full replacement.",
                "tokens": 190,
            },
            {
                "source": "workflow-landscape-2026",
                "snippet": "Most 2026 comparisons converge on Airflow for incumbents and Dagster for new projects, with the trade-off explicitly scoped.",
                "tokens": 260,
            },
        ],
        contradiction_records=[],
        context_tokens_so_far=18200,
        new_docs_tokens=3100,
        gold_action="converge",
        gold_query_intent="none",
        quality_passed=True,
        tokens_if_search_more=2400,
        tokens_if_converge=350,
    )

    state = compile_research_c2a_state(case)

    assert state.converge_allowed is True
    assert state.release_mode == "bounded_release"
    assert state.hard_constraints == []
    assert state.soft_constraints == state.residual_constraints
    assert state.preferred_query_intent == "none"


def test_compile_research_c2a_state_keeps_unsupported_recency_as_hard_blocker():
    case = ResearchDecisionCase(
        case_id="hard-1",
        session_id="s-hard",
        prompt="Map AI gateway landscape",
        user_goal="Compare the best AI gateways for 2026 with recency checks.",
        known_facts=["General API gateways exist for microservices."],
        open_gaps=["Need recent 2026 benchmark covering AI-native routing overhead."],
        contradictions=[],
        latest_docs=[
            {
                "source": "legacy-gateway-post",
                "snippet": "A 2024 overview compares generic API gateways but does not cover AI-native routing.",
                "tokens": 140,
            }
        ],
        contradiction_records=[],
        context_tokens_so_far=4200,
        new_docs_tokens=700,
        gold_action="search_more",
        gold_query_intent="recency_refresh",
        quality_passed=False,
        tokens_if_search_more=2300,
        tokens_if_converge=320,
    )

    state = compile_research_c2a_state(case)

    assert state.converge_allowed is False
    assert state.release_mode == "hard_blocked"
    assert state.hard_constraints == ["refresh_recency: Need recent 2026 benchmark covering AI-native routing overhead."]
    assert state.soft_constraints == []
    assert state.preferred_query_intent == "recency_refresh"


def test_compile_research_c2a_state_softens_recommendation_framing_when_evidence_is_saturated():
    case = ResearchDecisionCase(
        case_id="soft-synthesis-1",
        session_id="s-soft-synthesis",
        prompt="Choose the default open lakehouse format",
        user_goal="Recommend the default open lakehouse format for 2026 while acknowledging niche cases.",
        known_facts=[
            "Iceberg has broad multi-engine support across major query engines.",
            "Delta is strong in Databricks-heavy environments.",
            "Hudi remains relevant for upsert-heavy pipelines but is less often the default recommendation.",
            "Multiple 2025 and 2026 landscape articles frame Iceberg as the neutral default for general teams.",
        ],
        open_gaps=["How to phrase a recommendation that acknowledges niches while still picking one default format."],
        contradictions=[],
        latest_docs=[
            {
                "source": "lakehouse-2026-neutral-guide",
                "snippet": "Most 2026 neutral comparisons frame Iceberg as the default open format, while Delta and Hudi stay niche-advantaged in specific ecosystems.",
                "tokens": 240,
            },
            {
                "source": "iceberg-ecosystem-2026",
                "snippet": "Iceberg has the broadest open ecosystem support across engines and vendors in 2026.",
                "tokens": 220,
            },
            {
                "source": "delta-databricks-context",
                "snippet": "Delta remains compelling in Databricks-centric stacks but is not the neutral multi-vendor default.",
                "tokens": 210,
            },
            {
                "source": "hudi-context-2026",
                "snippet": "Hudi is strongest for streaming-heavy upsert workflows rather than as a universal default.",
                "tokens": 190,
            },
        ],
        contradiction_records=[],
        context_tokens_so_far=17100,
        new_docs_tokens=2800,
        gold_action="converge",
        gold_query_intent="none",
        quality_passed=True,
        tokens_if_search_more=2200,
        tokens_if_converge=320,
    )

    state = compile_research_c2a_state(case)

    assert state.converge_allowed is True
    assert state.release_mode == "bounded_release"
    assert state.hard_constraints == []
    assert state.soft_constraints == [
        "fill_missing_fact: How to phrase a recommendation that acknowledges niches while still picking one default format."
    ]


def test_compile_research_c2a_state_softens_absence_checks_with_recent_coverage():
    case = ResearchDecisionCase(
        case_id="soft-absence-1",
        session_id="s-soft-absence",
        prompt="Recommend the default lakehouse table format",
        user_goal="Recommend the best default open table format for 2026 with recent counterarguments checked.",
        known_facts=[
            "Iceberg is framed as the default neutral recommendation in several 2025-2026 comparisons.",
            "Delta remains strongest in Databricks-native environments.",
            "Hudi is still preferred in some streaming-heavy niches.",
            "Recent ecosystem articles describe the market as converging on Iceberg for general analytics teams.",
        ],
        open_gaps=["Is there any strong recent counter-argument that Delta or Hudi should be the default for general analytics teams?"],
        contradictions=[],
        latest_docs=[
            {
                "source": "lakehouse-landscape-2026",
                "snippet": "2026 comparisons place Iceberg as the default choice for cross-engine analytics teams, while Delta and Hudi remain context-specific.",
                "tokens": 240,
            },
            {
                "source": "iceberg-vs-delta-2025",
                "snippet": "A 2025 neutral guide says Delta is excellent inside Databricks, but Iceberg is the safer default outside that ecosystem.",
                "tokens": 220,
            },
            {
                "source": "hudi-streaming-2026",
                "snippet": "Hudi is recommended for certain streaming and upsert-heavy workloads, not as the broad default for general teams.",
                "tokens": 205,
            },
            {
                "source": "warehouse-adoption-2026",
                "snippet": "Recent 2026 adoption writeups emphasize Iceberg momentum across engines and vendors.",
                "tokens": 215,
            },
        ],
        contradiction_records=[],
        context_tokens_so_far=16900,
        new_docs_tokens=2600,
        gold_action="converge",
        gold_query_intent="none",
        quality_passed=True,
        tokens_if_search_more=2100,
        tokens_if_converge=300,
    )

    state = compile_research_c2a_state(case)

    assert state.converge_allowed is True
    assert state.release_mode == "bounded_release"
    assert state.hard_constraints == []
    assert state.soft_constraints == [
        "refresh_recency: Is there any strong recent counter-argument that Delta or Hudi should be the default for general analytics teams?"
    ]


def test_run_research_loop_replay_benchmark_prefers_memla(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    cases = tmp_path / "replay_cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "session_id": "s1",
                "prompt": "Assess best weak-hardware CPU inference stack",
                "user_goal": "Pick best stack with independent evidence",
                "known_facts": ["Only vendor benchmark available"],
                "open_gaps": ["Need independent benchmark"],
                "contradictions": ["Source A conflicts with source B"],
                "latest_docs": [],
                "context_tokens_so_far": 8000,
                "new_docs_tokens": 900,
                "gold_action": "search_more",
                "gold_query_intent": "resolve_contradiction",
                "quality_passed": True,
                "tokens_if_search_more": 2300,
                "tokens_if_converge": 320,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_replay_benchmark(
        cases_path=str(cases),
        raw_model="raw-small",
        memla_model="memla-small",
        frontier_model="frontier-raw",
    )

    assert report["cases"] == 1
    assert report["memla"]["action_accuracy"] >= report["raw"]["action_accuracy"]
    assert report["rows"][0]["memla_action"] == "search_more"
    assert report["rows"][0]["memla_verifier_forced"] is False
    assert report["rows"][0]["converge_allowed"] is False
    assert report["rows"][0]["preferred_query_intent"] == "resolve_contradiction"
    assert report["memla"]["illegal_converge_rate"] == 0.0
    assert report["memla"]["verifier_override_rate"] == 0.0
    md = render_research_loop_markdown(report)
    assert "# Research Loop Benchmark" in md
    assert "Illegal converge rate" in md
    assert "Action accuracy" in md


def test_run_research_loop_replay_benchmark_reports_deployment_economics(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    cases = tmp_path / "replay_cases_econ.jsonl"
    cases.write_text(
        json.dumps(
            {
                "session_id": "s-econ",
                "prompt": "Assess best weak-hardware CPU inference stack",
                "user_goal": "Pick best stack with independent evidence",
                "known_facts": ["Only vendor benchmark available"],
                "open_gaps": ["Need independent benchmark"],
                "contradictions": ["Source A conflicts with source B"],
                "latest_docs": [],
                "context_tokens_so_far": 1000,
                "new_docs_tokens": 100,
                "gold_action": "search_more",
                "gold_query_intent": "resolve_contradiction",
                "quality_passed": True,
                "tokens_if_search_more": 500,
                "tokens_if_converge": 200,
                "estimated_output_tokens": 100,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_replay_benchmark(
        cases_path=str(cases),
        raw_model="raw-small",
        memla_model="memla-small",
        frontier_model="frontier-raw",
        deploy_memla_fixed_cost_per_decision=0.001,
        deploy_frontier_input_price_per_million=10.0,
        deploy_frontier_output_price_per_million=0.0,
        deploy_memla_fallback_rate=0.25,
        deploy_decisions_per_session=4.0,
    )

    deployment = dict(report.get("deployment_economics") or {})
    assert deployment.get("configured") is True
    assert deployment.get("decisions_per_session_used") == 4.0
    assert deployment.get("memla_fallback_rate") == 0.25
    assert deployment.get("frontier", {}).get("modeled_cost_per_1k_sessions") == 64.0
    assert deployment.get("memla", {}).get("modeled_cost_per_1k_sessions") == 20.0
    assert deployment.get("savings_vs_frontier_per_1k_sessions", {}).get("memla") == 44.0


def test_run_research_loop_replay_benchmark_can_use_logged_frontier_baseline(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    cases = tmp_path / "replay_cases_logged_frontier.jsonl"
    cases.write_text(
        json.dumps(
            {
                "session_id": "s-logged",
                "prompt": "Assess best weak-hardware CPU inference stack",
                "user_goal": "Pick best stack with independent evidence",
                "known_facts": ["Only vendor benchmark available"],
                "open_gaps": ["Need independent benchmark"],
                "contradictions": [],
                "latest_docs": [],
                "context_tokens_so_far": 1000,
                "new_docs_tokens": 100,
                "gold_action": "search_more",
                "gold_query_intent": "missing_fact",
                "quality_passed": True,
                "tokens_if_search_more": 500,
                "tokens_if_converge": 200,
                "estimated_output_tokens": 100,
                "frontier_action": "converge",
                "frontier_query_intent": "none",
                "frontier_rationale": "Historical baseline stopped early.",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_replay_benchmark(
        cases_path=str(cases),
        raw_model="raw-small",
        memla_model="memla-small",
        frontier_model="",
        frontier_use_logged_decisions=True,
    )

    assert report["frontier_provider"] == "historical_log"
    assert report["frontier_model"] == "historical_log"
    assert report["rows"][0]["frontier_action"] == "converge"
    assert report["frontier"]["false_converge_rate"] == 1.0


def test_research_c2a_verifier_blocks_illegal_converge(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    cases = tmp_path / "forced_replay_cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "session_id": "s2",
                "prompt": "Assess best weak-hardware CPU inference stack",
                "user_goal": "Pick best stack with independent evidence",
                "known_facts": ["Only vendor benchmark available"],
                "open_gaps": ["Need independent benchmark"],
                "contradictions": ["Source A conflicts with source B"],
                "latest_docs": [],
                "context_tokens_so_far": 8000,
                "new_docs_tokens": 900,
                "gold_action": "search_more",
                "gold_query_intent": "resolve_contradiction",
                "quality_passed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_replay_benchmark(
        cases_path=str(cases),
        raw_model="raw-small",
        memla_model="raw-small",
        frontier_model="frontier-raw",
    )

    assert report["rows"][0]["memla_action"] == "search_more"
    assert report["rows"][0]["memla_verifier_forced"] is True
    assert report["rows"][0]["memla_verifier_reason"] == "blocked_illegal_converge; aligned_query_intent_to_residual_constraints"
    assert report["memla"]["verifier_override_rate"] == 1.0


def test_research_c2a_verifier_releases_bounded_converge(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: ReleaseAwareDummyClient(provider or "ollama"),
    )

    cases = tmp_path / "bounded_replay_cases.jsonl"
    cases.write_text(
        json.dumps(
            {
                "session_id": "bounded-release",
                "prompt": "Map workflow orchestration options",
                "user_goal": "Compare the best workflow orchestrators for 2026 and recommend one with contradictions resolved.",
                "known_facts": [
                    "Airflow remains the common default in legacy enterprise environments.",
                    "Dagster is increasingly recommended for greenfield projects.",
                    "Flyte is strong for Kubernetes-native ML but is operationally heavier.",
                    "Metaflow often layers on another orchestrator.",
                ],
                "open_gaps": [],
                "contradictions": [
                    "Some sources insist Airflow should still be the default, while others argue Dagster is better for new projects; tension resolved by distinguishing legacy installs from greenfield adoption."
                ],
                "latest_docs": [
                    {
                        "source": "workflow-landscape-2026",
                        "snippet": "Most 2026 comparisons converge on Airflow for incumbents and Dagster for new projects, with the trade-off explicitly scoped.",
                        "tokens": 260,
                    },
                    {
                        "source": "dagster-2026-guide",
                        "snippet": "Dagster is the better default for greenfield teams prioritizing modern software-defined assets.",
                        "tokens": 220,
                    },
                    {
                        "source": "airflow-2026-guide",
                        "snippet": "Airflow stays dominant in existing enterprise estates with broad ecosystem coverage.",
                        "tokens": 240,
                    },
                    {
                        "source": "flyte-ops",
                        "snippet": "Flyte excels for Kubernetes-native ML orchestration but carries more operational complexity.",
                        "tokens": 180,
                    },
                    {
                        "source": "metaflow-overview",
                        "snippet": "Metaflow is better understood as an ML workflow framework layered onto schedulers.",
                        "tokens": 190,
                    },
                ],
                "context_tokens_so_far": 18200,
                "new_docs_tokens": 3100,
                "gold_action": "converge",
                "gold_query_intent": "none",
                "quality_passed": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_replay_benchmark(
        cases_path=str(cases),
        raw_model="raw-small",
        memla_model="memla-release",
        frontier_model="frontier-raw",
    )

    assert report["rows"][0]["converge_allowed"] is True
    assert report["rows"][0]["release_mode"] == "bounded_release"
    assert report["rows"][0]["memla_action"] == "converge"
    assert report["rows"][0]["memla_verifier_forced"] is True
    assert report["rows"][0]["memla_verifier_reason"] == "released_bounded_constraints"
    assert report["rows"][0]["memla_release_readiness"] == "bounded_enough"
    assert report["memla"]["action_accuracy"] == 1.0


def test_run_research_loop_live_shadow_tracks_iterations(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "memory_system.distillation.research_loop_benchmark._build_llm_client",
        lambda provider=None, base_url=None, api_key=None: DummyClient(provider or "ollama"),
    )

    sessions = tmp_path / "live_cases.jsonl"
    sessions.write_text(
        json.dumps(
            {
                "session_id": "live1",
                "prompt": "Compare two OCR APIs",
                "user_goal": "Recommend one with legal and pricing evidence",
                "loop_steps": [
                    {
                        "step_index": 1,
                        "known_facts": ["API A pricing found"],
                        "open_gaps": ["API B legal terms missing"],
                        "contradictions": [],
                        "latest_docs": [],
                        "context_tokens_so_far": 5000,
                        "new_docs_tokens": 600,
                        "gold_action": "search_more",
                        "gold_query_intent": "missing_fact",
                    },
                    {
                        "step_index": 2,
                        "known_facts": ["API B legal terms found"],
                        "open_gaps": [],
                        "contradictions": [],
                        "latest_docs": [],
                        "context_tokens_so_far": 7400,
                        "new_docs_tokens": 500,
                        "gold_action": "converge",
                        "gold_query_intent": "none",
                    },
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = run_research_loop_live_shadow_benchmark(
        cases_path=str(sessions),
        raw_model="raw-small",
        memla_model="memla-small",
        frontier_model="frontier-raw",
        max_iterations=4,
    )

    assert report["sessions"] == 1
    assert "avg_final_success" in report["memla"]
    assert report["rows"][0]["memla_iterations_used"] >= 1
    assert "avg_illegal_converge_rate" in report["memla"]
    assert report["rows"][0]["memla_verifier_override_rate"] >= 0.0
    md = render_research_loop_markdown(report)
    assert "Avg decision accuracy" in md
