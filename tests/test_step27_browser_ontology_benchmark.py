from __future__ import annotations

import json

from memory_system.browser_ontology_benchmark import (
    BrowserBacktestResult,
    backtest_browser_plan,
    load_browser_benchmark_cases,
    render_browser_benchmark_markdown,
    run_browser_benchmark,
    run_language_learning_benchmark,
    run_language_rule_benchmark,
    run_memory_ontology_benchmark,
)
from memory_system.cli import main
from memory_system.natural_terminal import TerminalAction, TerminalPlan, build_terminal_plan


def test_browser_benchmark_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases.jsonl")

    assert {case.case_id for case in cases} == {
        "github_search_llamacpp",
        "youtube_search_nine_vicious",
        "click_first_repo",
        "click_ollama_card",
        "extract_search_cards",
        "read_current_repo",
        "extract_current_repo_page",
        "open_new_tab",
        "new_tab_youtube_search",
        "close_current_tab",
        "switch_next_tab",
        "take_screenshot",
    }


def test_browser_benchmark_v2_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v2.jsonl")

    assert {case.case_id for case in cases} == {
        "rank_repos_for_beginner_local_llm",
        "rank_repos_for_cpp_inference",
        "compare_first_second_for_beginner_goal",
        "compare_first_second_for_cpp_goal",
    }


def test_browser_benchmark_v3_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v3.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_then_youtube",
        "best_cpp_repo_then_youtube",
        "current_repo_to_youtube_video",
        "compare_winner_then_youtube",
    }


def test_browser_benchmark_v4_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v4.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_then_open_youtube",
        "best_cpp_repo_then_open_youtube",
        "current_repo_to_open_youtube_video",
        "compare_winner_then_open_youtube",
    }


def test_browser_benchmark_v5_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v5.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_then_open_and_read_youtube",
        "best_cpp_repo_then_open_and_read_youtube",
        "current_repo_to_open_and_read_youtube",
        "compare_winner_then_open_and_read_youtube",
    }


def test_browser_benchmark_v6_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v6.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_then_youtube_then_reddit",
        "best_cpp_repo_then_youtube_then_reddit",
        "current_repo_to_youtube_then_reddit",
        "compare_winner_then_youtube_then_reddit",
    }


def test_browser_benchmark_v7_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v7.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_recover_youtube_then_reddit",
        "best_cpp_repo_recover_youtube_then_reddit",
        "current_repo_recover_youtube_then_reddit",
        "compare_winner_recover_youtube_then_reddit",
    }


def test_browser_benchmark_v8_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/browser_eval_cases_v8.jsonl")

    assert {case.case_id for case in cases} == {
        "best_beginner_repo_recover_youtube_then_reddit_synthesize",
        "best_cpp_repo_recover_youtube_then_reddit_synthesize",
        "current_repo_recover_youtube_then_reddit_synthesize",
        "compare_winner_recover_youtube_then_reddit_synthesize",
    }


def test_language_benchmark_v1_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/language_eval_cases_v1.jsonl")

    assert {case.case_id for case in cases} == {
        "language_beginner_repo_recover_youtube_then_reddit_synthesize",
        "language_cpp_repo_recover_youtube_then_reddit_synthesize",
        "language_current_repo_recover_youtube_then_reddit_synthesize",
        "language_compare_winner_recover_youtube_then_reddit_synthesize",
    }


def test_language_benchmark_v2_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/language_eval_cases_v2.jsonl")

    assert {case.case_id for case in cases} == {
        "language_v2_beginner_repo_chain",
        "language_v2_cpp_repo_chain",
        "language_v2_current_repo_chain",
        "language_v2_compare_winner_chain",
    }


def test_language_benchmark_v3_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/language_eval_cases_v3.jsonl")

    assert {case.case_id for case in cases} == {
        "language_v3_beginner_repo_chain",
        "language_v3_cpp_repo_chain",
        "language_v3_current_repo_chain",
        "language_v3_compare_winner_chain",
    }
    assert all(case.seed_prompt for case in cases)


def test_language_benchmark_v4_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/language_eval_cases_v4.jsonl")

    assert {case.case_id for case in cases} == {
        "language_v4_beginner_repo_chain",
        "language_v4_cpp_repo_chain",
        "language_v4_current_repo_chain",
        "language_v4_compare_winner_chain",
    }
    assert all(case.seed_prompt for case in cases)
    assert all(case.rule_prompt for case in cases)


def test_memory_benchmark_v1_pack_loads_expected_cases():
    cases = load_browser_benchmark_cases("cases/memory_eval_cases_v1.jsonl")

    assert {case.case_id for case in cases} == {
        "memory_v1_repo_to_youtube",
    }
    assert all(case.seed_prompt for case in cases)
    assert all(case.rule_prompt for case in cases)


def test_browser_backtest_reads_seeded_repo_snapshot():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases.jsonl") if case.case_id == "read_current_repo")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page")],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert "repo" in result.detail_fields
    assert result.final_state.page_kind == "repo_page"


def test_language_v1_cpp_paraphrase_builds_same_successful_chain():
    case = next(
        case
        for case in load_browser_benchmark_cases("cases/language_eval_cases_v1.jsonl")
        if case.case_id == "language_cpp_repo_recover_youtube_then_reddit_synthesize"
    )

    plan = build_terminal_plan(prompt=case.prompt, heuristic_only=True, browser_state=case.browser_state)
    result = backtest_browser_plan(case, plan)

    assert [action.kind for action in plan.actions] == [
        "browser_rank_cards",
        "browser_search_subject",
        "open_search_result",
        "browser_read_page",
        "browser_retry_subject_result",
        "browser_read_page",
        "browser_search_subject",
        "open_search_result",
        "browser_read_page",
        "browser_synthesize_evidence",
    ]
    assert result.semantic_success is True, result.details


def test_language_v2_cases_build_successful_browser_chains():
    for case in load_browser_benchmark_cases("cases/language_eval_cases_v2.jsonl"):
        plan = build_terminal_plan(prompt=case.prompt, heuristic_only=True, browser_state=case.browser_state)
        result = backtest_browser_plan(case, plan)

        assert result.semantic_success is True, f"{case.case_id}: {plan.actions} -> {result.details}"


def test_language_v3_benchmark_reports_cold_to_warm_learning(monkeypatch, tmp_path):
    cases_path = tmp_path / "language_v3_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "language_v3_demo",
                "seed_prompt": "scope out some youtube coverage on this repo and peel open the top one",
                "prompt": "scope out some youtube coverage on this repo and peel open the top one please",
                "browser_state": {
                    "current_url": "https://github.com/ggml-org/llama.cpp",
                    "page_kind": "repo_page",
                },
                "accepted_action_sets": [["browser_search_subject:youtube", "open_search_result:1"]],
                "expected_page_kind": "video_page",
                "expected_url_contains": "https://www.youtube.com/watch?v=llama-cpp-overview",
                "expected_search_engine": "youtube",
                "expected_search_query": "ggml org llama cpp",
                "expected_research_subject_title": "ggml-org/llama.cpp",
                "subject_search_steps": [
                    {
                        "engine": "youtube",
                        "cards": [
                            {
                                "index": 1,
                                "title": "llama.cpp overview",
                                "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                                "summary": "An overview of the llama.cpp project.",
                            }
                        ],
                    }
                ],
                "page_snapshots": {
                    "https://www.youtube.com/watch?v=llama-cpp-overview": {
                        "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                        "page_kind": "video_page",
                        "title": "llama.cpp overview",
                        "summary": "An overview of the llama.cpp project.",
                        "channel": "Repo Scout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_llm_client", lambda **kwargs: DummyClient())

    def fake_raw(**kwargs):
        return TerminalPlan(prompt=kwargs["prompt"], source="raw_model", actions=[])

    def fake_memla(**kwargs):
        prompt = kwargs["prompt"]
        if prompt.endswith("please"):
            return TerminalPlan(
                prompt=prompt,
                source="language_memory",
                actions=[
                    TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                    TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
                ],
            )
        return TerminalPlan(
            prompt=prompt,
            source="language_model",
            actions=[
                TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            ],
        )

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_raw_terminal_plan", fake_raw)
    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_language_learning_plan", fake_memla)

    report = run_language_learning_benchmark(
        cases_path=str(cases_path),
        raw_model="phi3:mini",
        memla_model="phi3:mini",
        memory_root=str(tmp_path / "memroot"),
    )

    assert report["ontology_version"] == "language_v3"
    assert report["avg_memla_cold_semantic_success"] == 1.0
    assert report["avg_memla_warm_semantic_success"] == 1.0
    assert report["memla_cold_language_model_call_count"] == 1
    assert report["memla_warm_language_memory_hit_count"] == 1
    assert report["memla_promoted_reuse_count"] == 1

    markdown = render_browser_benchmark_markdown(report)
    assert "Language Ontology V3 Benchmark" in markdown
    assert "Memla warm language-memory hits" in markdown


def test_language_v4_benchmark_reports_rule_hits(monkeypatch, tmp_path):
    cases_path = tmp_path / "language_v4_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "language_v4_demo",
                "seed_prompt": "pull some yt coverage on this repo and crack open the opener",
                "prompt": "pull some yt coverage on this repo and crack open the opener please",
                "rule_prompt": "pull some yt coverage on this repo and crack open the opener please",
                "browser_state": {
                    "current_url": "https://github.com/ggml-org/llama.cpp",
                    "page_kind": "repo_page",
                },
                "accepted_action_sets": [["browser_search_subject:youtube", "open_search_result:1"]],
                "expected_page_kind": "video_page",
                "expected_url_contains": "https://www.youtube.com/watch?v=llama-cpp-overview",
                "expected_search_engine": "youtube",
                "expected_search_query": "ggml org llama cpp",
                "expected_research_subject_title": "ggml-org/llama.cpp",
                "subject_search_steps": [
                    {
                        "engine": "youtube",
                        "cards": [
                            {
                                "index": 1,
                                "title": "llama.cpp overview",
                                "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                                "summary": "An overview of the llama.cpp project.",
                            }
                        ],
                    }
                ],
                "page_snapshots": {
                    "https://www.youtube.com/watch?v=llama-cpp-overview": {
                        "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                        "page_kind": "video_page",
                        "title": "llama.cpp overview",
                        "summary": "An overview of the llama.cpp project.",
                        "channel": "Repo Scout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_llm_client", lambda **kwargs: DummyClient())

    def fake_raw(**kwargs):
        return TerminalPlan(prompt=kwargs["prompt"], source="raw_model", actions=[])

    def fake_learning(**kwargs):
        prompt = kwargs["prompt"]
        if prompt.endswith("please"):
            return TerminalPlan(
                prompt=prompt,
                source="language_rule",
                actions=[
                    TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                    TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
                ],
            )
        return TerminalPlan(
            prompt=prompt,
            source="language_model",
            actions=[
                TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            ],
        )

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_raw_terminal_plan", fake_raw)
    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_language_learning_plan", fake_learning)

    report = run_language_rule_benchmark(
        cases_path=str(cases_path),
        raw_model="phi3:mini",
        memla_model="phi3:mini",
        memory_root=str(tmp_path / "memroot"),
    )

    assert report["ontology_version"] == "language_v4"
    assert report["avg_memla_rule_semantic_success"] == 1.0
    assert report["memla_rule_hit_count"] == 1

    markdown = render_browser_benchmark_markdown(report)
    assert "Language Ontology V4 Benchmark" in markdown
    assert "Memla promoted rule hits" in markdown


def test_memory_v1_benchmark_reports_lifecycle_transitions(monkeypatch, tmp_path):
    cases_path = tmp_path / "memory_v1_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "memory_v1_demo",
                "seed_prompt": "pull some yt coverage on this repo and crack open the opener",
                "prompt": "pull some yt coverage on this repo and crack open the opener please",
                "rule_prompt": "pull some yt coverage on this repo and crack open the opener please",
                "browser_state": {
                    "current_url": "https://github.com/ggml-org/llama.cpp",
                    "page_kind": "repo_page",
                },
                "accepted_action_sets": [["browser_search_subject:youtube", "open_search_result:1"]],
                "expected_page_kind": "video_page",
                "expected_url_contains": "https://www.youtube.com/watch?v=llama-cpp-overview",
                "expected_search_engine": "youtube",
                "expected_search_query": "ggml org llama cpp",
                "expected_research_subject_title": "ggml-org/llama.cpp",
                "subject_search_steps": [
                    {
                        "engine": "youtube",
                        "cards": [
                            {
                                "index": 1,
                                "title": "llama.cpp overview",
                                "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                                "summary": "An overview of the llama.cpp project.",
                            }
                        ],
                    }
                ],
                "page_snapshots": {
                    "https://www.youtube.com/watch?v=llama-cpp-overview": {
                        "url": "https://www.youtube.com/watch?v=llama-cpp-overview",
                        "page_kind": "video_page",
                        "title": "llama.cpp overview",
                        "summary": "An overview of the llama.cpp project.",
                        "channel": "Repo Scout",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_llm_client", lambda **kwargs: DummyClient())

    call_count = {"warm": 0}

    def fake_raw(**kwargs):
        return TerminalPlan(prompt=kwargs["prompt"], source="raw_model", actions=[])

    def fake_learning(**kwargs):
        prompt = kwargs["prompt"]
        if prompt == "pull some yt coverage on this repo and crack open the opener":
            return TerminalPlan(
                prompt=prompt,
                source="language_model",
                actions=[
                    TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                    TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
                ],
            )
        if prompt.endswith("please"):
            call_count["warm"] += 1
            source = "language_rule" if call_count["warm"] >= 3 else "language_memory"
            return TerminalPlan(
                prompt=prompt,
                source=source,
                actions=[
                    TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube"),
                    TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
                ],
            )
        return TerminalPlan(prompt=prompt, source="language_model", actions=[])

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_raw_terminal_plan", fake_raw)
    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_language_learning_plan", fake_learning)

    report = run_memory_ontology_benchmark(
        cases_path=str(cases_path),
        raw_model="phi3:mini",
        memla_model="phi3:mini",
        memory_root=str(tmp_path / "memroot"),
    )

    assert report["ontology_version"] == "memory_v1"
    assert report["avg_memla_rule_semantic_success"] == 1.0
    assert report["cold_episodic_transition_count"] == 1
    assert report["warm_semantic_transition_count"] == 1
    assert report["rule_stage_transition_count"] == 1
    assert report["memla_warm_language_memory_hit_count"] == 2
    assert report["memla_rule_hit_count"] == 1

    markdown = render_browser_benchmark_markdown(report)
    assert "Memory Ontology V1 Benchmark" in markdown
    assert "Warm semantic transitions" in markdown


def test_browser_backtest_treats_github_search_url_variants_as_equivalent():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases.jsonl") if case.case_id == "github_search_llamacpp")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="open_url",
                target="https://github.com/search?q=llama+cpp&type=repositories",
                resolved_target="https://github.com/search?q=llama+cpp&type=repositories",
            )
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.action_score == 1.0
    assert result.semantic_success is True


def test_browser_backtest_ranks_cards_and_picks_expected_winner():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v2.jsonl") if case.case_id == "rank_repos_for_beginner_local_llm")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[TerminalAction(kind="browser_rank_cards", target="current_cards", resolved_target="current_cards")],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert result.details["best_title"] == "ollama/ollama"


def test_browser_backtest_ranks_cards_for_cpp_goal():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v2.jsonl") if case.case_id == "rank_repos_for_cpp_inference")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=json.dumps({"goal": case.prompt}),
            )
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert result.details["best_title"] == "ggml-org/llama.cpp"


def test_browser_backtest_compares_cards_and_picks_expected_winner():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v2.jsonl") if case.case_id == "compare_first_second_for_cpp_goal")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_compare_cards",
                target="1,2",
                resolved_target="1,2",
                note=json.dumps({"goal": case.prompt, "indexes": [1, 2]}),
            )
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert result.details["winner_title"] == "ggml-org/llama.cpp"


def test_browser_backtest_rank_then_search_subject():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v3.jsonl") if case.case_id == "best_cpp_repo_then_youtube")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=json.dumps({"goal": "c++ llm inference on cpu"}),
            ),
            TerminalAction(
                kind="browser_search_subject",
                target="youtube",
                resolved_target="youtube",
                note=json.dumps({"engine": "youtube"}),
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert result.final_state.search_engine == "youtube"
    assert result.final_state.subject_title == "ggml-org/llama.cpp"
    assert result.details["search_query"] == "ggml org llama cpp"


def test_browser_backtest_rank_search_and_open_subject_result():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v4.jsonl") if case.case_id == "best_cpp_repo_then_open_youtube")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=json.dumps({"goal": "c++ llm inference on cpu"}),
            ),
            TerminalAction(
                kind="browser_search_subject",
                target="youtube",
                resolved_target="youtube",
                note=json.dumps({"engine": "youtube"}),
            ),
            TerminalAction(
                kind="open_search_result",
                target="1",
                resolved_target="1",
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True, result.details
    assert result.final_state.page_kind == "video_page"
    assert result.final_state.current_url == "https://www.youtube.com/watch?v=llama-cpp-cpu"
    assert result.final_state.subject_title == "llama.cpp CPU inference walkthrough"


def test_browser_backtest_rank_search_open_and_read_subject_result():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v5.jsonl") if case.case_id == "best_cpp_repo_then_open_and_read_youtube")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=json.dumps({"goal": "c++ llm inference on cpu"}),
            ),
            TerminalAction(
                kind="browser_search_subject",
                target="youtube",
                resolved_target="youtube",
                note=json.dumps({"engine": "youtube"}),
            ),
            TerminalAction(
                kind="open_search_result",
                target="1",
                resolved_target="1",
            ),
            TerminalAction(
                kind="browser_read_page",
                target="current_page",
                resolved_target="current_page",
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True
    assert result.final_state.page_kind == "video_page"
    assert result.details["title"] == "llama.cpp CPU inference walkthrough"
    assert result.details["channel"] == "Local LLM Lab"


def test_browser_backtest_carries_research_subject_across_youtube_to_reddit():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v6.jsonl") if case.case_id == "best_cpp_repo_then_youtube_then_reddit")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=json.dumps({"goal": "c++ llm inference on cpu"}),
            ),
            TerminalAction(
                kind="browser_search_subject",
                target="youtube",
                resolved_target="youtube",
                note=json.dumps({"engine": "youtube"}),
            ),
            TerminalAction(
                kind="open_search_result",
                target="1",
                resolved_target="1",
            ),
            TerminalAction(
                kind="browser_read_page",
                target="current_page",
                resolved_target="current_page",
            ),
            TerminalAction(
                kind="browser_search_subject",
                target="reddit",
                resolved_target="reddit",
                note=json.dumps({"engine": "reddit"}),
            ),
            TerminalAction(
                kind="open_search_result",
                target="1",
                resolved_target="1",
            ),
            TerminalAction(
                kind="browser_read_page",
                target="current_page",
                resolved_target="current_page",
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    assert result.semantic_success is True
    assert result.final_state.page_kind == "post_page"
    assert result.final_state.search_engine == "reddit"
    assert result.final_state.search_query == "ggml org llama cpp"
    assert result.final_state.research_subject_title == "ggml-org/llama.cpp"
    assert result.final_state.subject_title == "Best way to use llama.cpp on weak hardware?"
    assert result.details["title"] == "Best way to use llama.cpp on weak hardware?"


def test_browser_backtest_current_repo_chain_uses_repo_page_as_research_subject():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v6.jsonl") if case.case_id == "current_repo_to_youtube_then_reddit")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_search_subject", target="reddit", resolved_target="reddit", note=json.dumps({"engine": "reddit"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    if not result.semantic_success:
        raise AssertionError(result.details)
    assert result.final_state.page_kind == "post_page"
    assert result.final_state.research_subject_title == "ggml-org/llama.cpp"
    assert result.final_state.search_query == "ggml org llama cpp"


def test_browser_backtest_recovers_to_stronger_subject_result():
    case = next(case for case in load_browser_benchmark_cases("cases/browser_eval_cases_v7.jsonl") if case.case_id == "best_cpp_repo_recover_youtube_then_reddit")
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(kind="browser_rank_cards", target="current_cards", resolved_target="current_cards", note=json.dumps({"goal": "c++ llm inference on cpu"})),
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_retry_subject_result", target="better_result", resolved_target="better_result"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_search_subject", target="reddit", resolved_target="reddit", note=json.dumps({"engine": "reddit"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    if not result.semantic_success:
        raise AssertionError(result.details)
    assert result.final_state.page_kind == "post_page"
    assert result.final_state.research_subject_title == "ggml-org/llama.cpp"


def test_browser_backtest_synthesizes_best_cross_source_answer():
    case = next(
        case
        for case in load_browser_benchmark_cases("cases/browser_eval_cases_v8.jsonl")
        if case.case_id == "best_cpp_repo_recover_youtube_then_reddit_synthesize"
    )
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(kind="browser_rank_cards", target="current_cards", resolved_target="current_cards", note=json.dumps({"goal": "c++ llm inference on cpu"})),
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_retry_subject_result", target="better_result", resolved_target="better_result"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_search_subject", target="reddit", resolved_target="reddit", note=json.dumps({"engine": "reddit"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(
                kind="browser_synthesize_evidence",
                target="current_evidence",
                resolved_target="current_evidence",
                note=json.dumps({"goal": "which source best explains cpu inference on weak hardware"}),
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    if not result.semantic_success:
        raise AssertionError(result.details)
    assert result.details["best_source_title"] == "llama.cpp CPU inference walkthrough"
    assert result.details["best_source_kind"] == "video_page"


def test_browser_backtest_synthesizes_current_repo_to_overview_video():
    case = next(
        case
        for case in load_browser_benchmark_cases("cases/browser_eval_cases_v8.jsonl")
        if case.case_id == "current_repo_recover_youtube_then_reddit_synthesize"
    )
    plan = TerminalPlan(
        prompt=case.prompt,
        source="heuristic",
        actions=[
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_retry_subject_result", target="better_result", resolved_target="better_result"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_search_subject", target="reddit", resolved_target="reddit", note=json.dumps({"engine": "reddit"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(
                kind="browser_synthesize_evidence",
                target="current_evidence",
                resolved_target="current_evidence",
                note=json.dumps({"goal": "tell me which source best explains what this repo is for"}),
            ),
        ],
    )

    result = backtest_browser_plan(case, plan)

    assert result.execution_passed is True
    if not result.semantic_success:
        raise AssertionError(result.details)
    assert result.details["best_source_title"] == "llama.cpp overview"
    assert result.details["best_source_kind"] == "video_page"


def test_browser_benchmark_reports_semantic_success(monkeypatch, tmp_path):
    cases_path = tmp_path / "browser_cases.jsonl"
    cases_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "case_id": "tab",
                        "prompt": "open a new tab",
                        "accepted_action_sets": [["browser_new_tab:new_tab"]],
                        "expected_page_kind": "blank_tab",
                        "expected_url_contains": "browser://new-tab",
                    }
                ),
                json.dumps(
                    {
                        "case_id": "repo",
                        "prompt": "what is this repo",
                        "browser_state": {"current_url": "https://github.com/ggml-org/llama.cpp", "page_kind": "repo_page"},
                        "accepted_action_sets": [["browser_read_page:current_page"]],
                        "expected_page_kind": "repo_page",
                        "expected_detail_fields": ["repo", "language"],
                        "page_snapshot": {
                            "url": "https://github.com/ggml-org/llama.cpp",
                            "page_kind": "repo_page",
                            "repo": "ggml-org/llama.cpp",
                            "description": "LLM inference in C/C++.",
                            "language": "C++",
                            "summary": "ggml-org/llama.cpp: LLM inference in C/C++.",
                        },
                    }
                ),
            ]
        ),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

    monkeypatch.setattr("memory_system.browser_ontology_benchmark.build_llm_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        "memory_system.browser_ontology_benchmark.build_raw_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="raw_model",
            actions=[TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab")]
            if "new tab" in kwargs["prompt"]
            else [],
            residual_constraints=[] if "new tab" in kwargs["prompt"] else ["unsupported_or_ambiguous_request"],
        ),
    )
    monkeypatch.setattr(
        "memory_system.browser_ontology_benchmark.build_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab")]
            if "new tab" in kwargs["prompt"]
            else [TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page")],
        ),
    )
    timeline = iter([0.0, 1.0, 1.0, 1.2, 2.0, 2.8, 2.8, 2.9])
    monkeypatch.setattr("memory_system.browser_ontology_benchmark.time.perf_counter", lambda: next(timeline))

    report = run_browser_benchmark(
        cases_path=str(cases_path),
        raw_model="phi3",
        memla_model="phi3",
    )

    assert report["cases"] == 2
    assert report["avg_raw_semantic_success"] == 0.5
    assert report["avg_memla_semantic_success"] == 1.0
    assert report["avg_raw_latency_ms"] == 900.0
    assert report["avg_memla_latency_ms"] == 150.0
    assert report["memla_vs_raw_speedup"] == 6.0
    assert report["memla_heuristic_hit_count"] == 2


def test_memla_browser_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_browser_benchmark",
        lambda **kwargs: {
            "avg_raw_semantic_success": 0.25,
            "avg_memla_semantic_success": 0.75,
            "memla_vs_raw_speedup": 12.0,
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_browser_benchmark_markdown",
        lambda report: "# Browser Ontology V1 Benchmark\n",
    )

    out_dir = tmp_path / "browser_benchmark"
    rc = main(
        [
            "terminal",
            "benchmark-browser",
            "--model",
            "phi3",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "browser_benchmark_report.json").exists()
    assert (out_dir / "browser_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote browser benchmark JSON" in out
    assert "raw semantic 0.25" in out
    assert "speedup 12.0x" in out


def test_memla_browser_v2_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_browser_benchmark",
        lambda **kwargs: {
            "ontology_version": "browser_v2",
            "avg_raw_semantic_success": 0.0,
            "avg_memla_semantic_success": 1.0,
            "memla_vs_raw_speedup": 22.0,
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_browser_benchmark_markdown",
        lambda report: "# Browser Ontology V2 Benchmark\n",
    )

    out_dir = tmp_path / "browser_benchmark_v2"
    rc = main(
        [
            "terminal",
            "benchmark-browser-v2",
            "--model",
            "phi3",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "browser_benchmark_report.json").exists()
    assert (out_dir / "browser_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote browser benchmark JSON" in out
    assert "raw semantic 0.0" in out
    assert "speedup 22.0x" in out
