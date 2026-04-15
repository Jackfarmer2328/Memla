from __future__ import annotations

import json
from pathlib import Path

from memory_system.cli import main
from memory_system.distillation.web_policy_bank import (
    distill_web_policy_bank,
    suggest_web_policy_priors,
)
from memory_system.memory.ontology import load_memory_ontology
from memory_system.natural_terminal import (
    BROWSER_STATE_ENV,
    BrowserSessionState,
    TerminalExecutionRecord,
    TerminalExecutionResult,
    TerminalPlan,
    TerminalAction,
    _browser_new_tab_command,
    _compiler_surface_text,
    _extract_google_ai_overview_from_html,
    _extract_google_featured_snippet_from_html,
    _extract_google_role_holder_answer_from_html,
    _extract_google_weather_answer_from_html,
    _language_rule_plan,
    _hard_check_web_answer,
    _merge_language_actions,
    _normalize_model_actions,
    _promote_language_rules,
    _fetch_search_result_urls,
    _rescue_web_answer_with_teacher,
    _resolve_web_answer,
    build_llm_client,
    build_raw_terminal_plan,
    build_terminal_step_report,
    build_terminal_plan,
    execute_terminal_step,
    execute_terminal_plan,
    load_terminal_benchmark_cases,
    render_terminal_scout_text,
    remember_language_compile,
    run_terminal_scout,
    save_browser_session_state,
    terminal_language_memory_path,
    terminal_memory_ontology_path,
    terminal_language_rule_path,
    run_terminal_benchmark,
    run_web_answer_benchmark,
    run_web_overnight_loop,
    run_web_teacher_loop,
)


def test_terminal_heuristic_plan_launches_multiple_apps():
    plan = build_terminal_plan(prompt="open chrome and spotify", heuristic_only=True)

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["launch_app", "launch_app"]
    assert [action.resolved_target for action in plan.actions] == ["chrome", "spotify"]


def test_terminal_heuristic_plan_maps_downloads_folder():
    plan = build_terminal_plan(prompt="open downloads folder", heuristic_only=True)

    assert [action.kind for action in plan.actions] == ["open_path"]
    assert plan.actions[0].resolved_target.endswith("Downloads")


def test_terminal_heuristic_plan_builds_search_urls():
    plan = build_terminal_plan(prompt="open youtube and search lo fi hip hop", heuristic_only=True)

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_url"]
    assert plan.actions[0].resolved_target == "https://www.youtube.com/results?search_query=lo+fi+hip+hop"


def test_terminal_heuristic_plan_builds_search_urls_for_casual_phrase():
    plan = build_terminal_plan(
        prompt="open youtube bro then i want you to search lo fi hip hop",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_url"]
    assert plan.actions[0].resolved_target == "https://www.youtube.com/results?search_query=lo+fi+hip+hop"


def test_terminal_heuristic_plan_builds_search_urls_for_look_up_phrase():
    plan = build_terminal_plan(
        prompt="hey memla go to youtube and look up nine vicious",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_url"]
    assert plan.actions[0].resolved_target == "https://www.youtube.com/results?search_query=nine+vicious"


def test_terminal_heuristic_plan_builds_bounded_web_answer_for_news():
    plan = build_terminal_plan(
        prompt="what's happening in the news about AI agents today?",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "ai agents news today"


def test_terminal_heuristic_plan_builds_bounded_web_answer_for_top_news():
    plan = build_terminal_plan(
        prompt="whats on the news",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "top news today"


def test_terminal_heuristic_plan_builds_bounded_web_answer_for_weather():
    plan = build_terminal_plan(
        prompt="what's the weather today in minneapolis",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "weather today minneapolis"


def test_terminal_heuristic_plan_builds_bounded_web_answer_for_weather_without_location():
    plan = build_terminal_plan(
        prompt="whats the weather today",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "weather today"


def test_terminal_heuristic_plan_builds_bounded_web_answer_for_contracted_fact_question():
    plan = build_terminal_plan(
        prompt="who's the ceo of openai",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "who is the ceo of openai"


def test_terminal_heuristic_plan_prefers_standalone_web_question_over_browser_context():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggerganov/llama.cpp",
        page_kind="repo_page",
        search_engine="github",
        search_query="local llm repos",
        subject_title="ggerganov/llama.cpp",
        subject_url="https://github.com/ggerganov/llama.cpp",
        subject_summary="Local LLM inference in C/C++.",
        result_cards=[
            {
                "index": 1,
                "title": "ggerganov/llama.cpp",
                "url": "https://github.com/ggerganov/llama.cpp",
                "summary": "Local LLM inference in C/C++.",
            }
        ],
    )

    plan = build_terminal_plan(
        prompt="who is the ceo of openai",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_answer_query"]
    assert plan.actions[0].resolved_target == "who is the ceo of openai"


def test_terminal_heuristic_plan_handles_noisy_click_first_video_follow_up():
    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=nine+vicious",
        page_kind="search_results",
        search_engine="youtube",
        search_query="nine vicious",
    )

    plan = build_terminal_plan(
        prompt="click he first vid you see",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_search_result"]
    assert plan.actions[0].resolved_target == "1"


def test_terminal_heuristic_plan_sequences_noisy_initial_browser_prompt():
    plan = build_terminal_plan(
        prompt="hey memla open a tab put nine vicious click he first vid you see then open a new tab and find local llm github repo",
        heuristic_only=True,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == [
        "browser_new_tab",
        "open_url",
        "open_search_result",
        "browser_new_tab",
        "open_url",
    ]
    assert plan.actions[1].resolved_target == "https://www.youtube.com/results?search_query=nine+vicious"
    assert plan.actions[4].resolved_target == "https://github.com/search?q=local+llm&type=repositories"


def test_terminal_heuristic_plan_uses_browser_state_for_follow_up():
    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
        page_kind="search_results",
        search_engine="youtube",
        search_query="lo fi hip hop",
    )

    plan = build_terminal_plan(
        prompt="now press on the video so i can listen",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_search_result"]
    assert plan.actions[0].resolved_target == "1"


def test_terminal_heuristic_plan_handles_click_first_vid_follow_up():
    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
        page_kind="search_results",
        search_engine="youtube",
        search_query="lo fi hip hop",
    )

    plan = build_terminal_plan(
        prompt="now click the first vid",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["open_search_result"]
    assert plan.actions[0].resolved_target == "1"


def test_terminal_heuristic_plan_reads_current_repo_page():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="what is this repo",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_read_page"]


def test_terminal_scout_fetches_and_ranks_repo_results(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    cards = [
        {
            "index": 1,
            "title": "ollama/ollama",
            "url": "https://github.com/ollama/ollama",
            "summary": "Run local language models with a simple CLI.",
            "meta": "beginner | local models",
        },
        {
            "index": 2,
            "title": "ggml-org/llama.cpp",
            "url": "https://github.com/ggml-org/llama.cpp",
            "summary": "Portable C/C++ LLM inference runtime with strong CPU support for weak hardware.",
            "meta": "c++ | cpu | portable",
        },
        {
            "index": 3,
            "title": "oobabooga/text-generation-webui",
            "url": "https://github.com/oobabooga/text-generation-webui",
            "summary": "A configurable web UI for running local language models.",
            "meta": "webui | configurable",
        },
    ]
    snapshots = {
        ("ollama", "ollama"): {
            "repo": "ollama/ollama",
            "description": "Run local language models quickly on laptops.",
            "stars": "10k",
            "language": "Go",
        },
        ("ggml-org", "llama.cpp"): {
            "repo": "ggml-org/llama.cpp",
            "description": "Low-level C/C++ inference runtime optimized for CPU and portable weak-hardware setups.",
            "stars": "77k",
            "language": "C++",
            "topics": "cpu, inference, portable",
        },
        ("oobabooga", "text-generation-webui"): {
            "repo": "oobabooga/text-generation-webui",
            "description": "Web UI for local model experimentation.",
            "stars": "40k",
            "language": "Python",
        },
    }

    monkeypatch.setattr("memory_system.natural_terminal._fetch_github_search_cards", lambda query, limit=5: cards[:limit])
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_github_repo_snapshot",
        lambda owner, repo: snapshots.get((owner, repo), {}),
    )

    result = run_terminal_scout("find the top 3 github repos for local llms and tell me which best fits weak hardware")

    assert result.ok is True
    assert result.query == "local llms"
    assert result.best_match["title"] == "ggml-org/llama.cpp"
    assert len(result.top_results) == 3
    assert any(step.transmutation == "browser_read_page" for step in result.steps)
    assert result.browser_state["research_subject_title"] == "ggml-org/llama.cpp"
    assert "Top results:" in render_terminal_scout_text(result)
    autonomy_entries = load_memory_ontology(tmp_path / "terminal_memory_ontology.json")
    assert len(autonomy_entries) == 1
    assert autonomy_entries[0]["memory_kind"] == "autonomy_github_repo_scout"
    assert autonomy_entries[0]["origin_sources"] == ["autonomy_scout"]


def test_terminal_scout_reuses_current_github_results_when_query_is_missing(monkeypatch):
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_urls=[
            "https://github.com/ollama/ollama",
            "https://github.com/ggml-org/llama.cpp",
        ],
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Run local models with a simple CLI.",
                "meta": "beginner | local",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "Portable CPU inference runtime for local LLMs.",
                "meta": "c++ | cpu | portable",
            },
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_github_repo_snapshot",
        lambda owner, repo: {
            "repo": f"{owner}/{repo}",
            "description": "Portable CPU inference runtime for local LLMs." if repo == "llama.cpp" else "Run local models with a simple CLI.",
            "language": "C++" if repo == "llama.cpp" else "Go",
        },
    )

    result = run_terminal_scout(
        "show me the top 2 repos and bring back the best one for cpu inference",
        browser_state=browser_state,
    )

    assert result.ok is True
    assert result.query == "local llm"
    assert result.steps[0].message.startswith("Reused 2 cached GitHub repo results")
    assert result.best_match["title"] == "ggml-org/llama.cpp"


def test_terminal_heuristic_plan_reads_current_page_for_tell_me_about_this():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="tell me about this",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_read_page"]


def test_terminal_heuristic_plan_opens_new_tab_from_browser_state():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="open a new tab",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_new_tab"]


def test_terminal_heuristic_plan_opens_new_tab_then_searches():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="then open a new tab and put youtube then search nine vicious",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_new_tab", "open_url"]
    assert plan.actions[1].resolved_target == "https://www.youtube.com/results?search_query=nine+vicious"


def test_terminal_heuristic_plan_closes_current_tab():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="close the tab",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert plan.source == "heuristic"
    assert [action.kind for action in plan.actions] == ["browser_close_tab"]


def test_terminal_heuristic_plan_switches_tab():
    browser_state = BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page")

    plan = build_terminal_plan(prompt="switch to the next tab", heuristic_only=True, browser_state=browser_state)

    assert [action.kind for action in plan.actions] == ["browser_switch_tab"]
    assert plan.actions[0].resolved_target == "next"


def test_terminal_heuristic_plan_scrolls_and_submits_and_waits():
    browser_state = BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page")

    scroll_plan = build_terminal_plan(prompt="scroll down", heuristic_only=True, browser_state=browser_state)
    submit_plan = build_terminal_plan(prompt="submit", heuristic_only=True, browser_state=browser_state)
    wait_plan = build_terminal_plan(prompt="wait 2 seconds", heuristic_only=True, browser_state=browser_state)

    assert [action.kind for action in scroll_plan.actions] == ["browser_scroll"]
    assert [action.kind for action in submit_plan.actions] == ["browser_submit"]
    assert [action.kind for action in wait_plan.actions] == ["browser_wait"]
    assert wait_plan.actions[0].resolved_target == "2"


def test_terminal_heuristic_plan_types_text_and_extracts_cards():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=llama.cpp&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="llama.cpp",
    )

    type_plan = build_terminal_plan(prompt="type hello world", heuristic_only=True, browser_state=browser_state)
    cards_plan = build_terminal_plan(prompt="show me the top 5 results", heuristic_only=True, browser_state=browser_state)

    assert [action.kind for action in type_plan.actions] == ["browser_type_text"]
    assert [action.kind for action in cards_plan.actions] == ["browser_extract_cards"]


def test_terminal_heuristic_plan_clicks_by_text_and_index():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=llama.cpp&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="llama.cpp",
        result_cards=[
            {"index": 1, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "LLM inference in C/C++"},
            {"index": 2, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Get up and running with LLMs"},
        ],
    )

    click_text_plan = build_terminal_plan(prompt="click ollama", heuristic_only=True, browser_state=browser_state)
    click_index_plan = build_terminal_plan(prompt="click item 2", heuristic_only=True, browser_state=browser_state)

    assert [action.kind for action in click_text_plan.actions] == ["browser_click_text"]
    assert [action.kind for action in click_index_plan.actions] == ["browser_click_index"]


def test_terminal_heuristic_plan_ranks_cards_for_goal():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {"index": 1, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Simple CLI for local models."},
            {"index": 2, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "C/C++ inference runtime."},
        ],
    )

    plan = build_terminal_plan(
        prompt="which repo best matches a beginner local llm workflow on a laptop",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert [action.kind for action in plan.actions] == ["browser_rank_cards"]
    assert plan.actions[0].resolved_target == "current_cards"


def test_terminal_heuristic_plan_compares_first_two_cards():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {"index": 1, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Simple CLI for local models."},
            {"index": 2, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "C/C++ inference runtime."},
        ],
    )

    plan = build_terminal_plan(
        prompt="compare the first and second repo for c++ llm inference on cpu",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert [action.kind for action in plan.actions] == ["browser_compare_cards"]
    assert plan.actions[0].resolved_target == "1,2"


def test_terminal_heuristic_plan_extracts_page_and_takes_screenshot():
    browser_state = BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page")

    extract_plan = build_terminal_plan(prompt="extract current page", heuristic_only=True, browser_state=browser_state)
    screenshot_plan = build_terminal_plan(prompt="take screenshot", heuristic_only=True, browser_state=browser_state)

    assert [action.kind for action in extract_plan.actions] == ["browser_extract_page"]
    assert [action.kind for action in screenshot_plan.actions] == ["browser_screenshot"]


def test_terminal_step_report_includes_prompt_and_state_candidates():
    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
        page_kind="search_results",
        search_engine="youtube",
        search_query="lo fi hip hop",
        result_urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    report = build_terminal_step_report(
        prompt="now click the first vid",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert report.constraints["page_kind"] == "search_results"
    assert report.constraints["search_engine"] == "youtube"
    assert report.candidates[0].recommended is True
    assert report.candidates[0].plan.actions[0].kind == "open_search_result"
    assert "YouTube video" in report.candidates[0].target_preview
    assert "Open result #1 from the current youtube search." == report.candidates[0].expected_outcome
    labels = [candidate.label for candidate in report.candidates]
    assert "Open search result #2" in labels


def test_terminal_step_report_ignores_stale_state_candidates_for_new_search():
    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=old+query",
        page_kind="search_results",
        search_engine="youtube",
        search_query="old query",
    )

    report = build_terminal_step_report(
        prompt="open github and search llama.cpp",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert report.candidates[0].label == 'Open github search for "llama cpp"'
    labels = [candidate.label for candidate in report.candidates]
    assert "Open search result #1" not in labels
    assert "Go back" not in labels
    assert report.candidates[0].target_preview == 'Github search results for "llama cpp"'


def test_terminal_step_report_shows_read_page_extraction_fields():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    report = build_terminal_step_report(
        prompt="what is this repo",
        heuristic_only=True,
        browser_state=browser_state,
    )

    candidate = report.candidates[0]
    assert candidate.target_preview == "ggml-org/llama.cpp"
    assert candidate.expected_outcome == "Extract a structured repo summary from the current GitHub repository page."
    assert candidate.expected_fields == ["repo", "description", "stars", "forks", "language", "topics"]


def test_terminal_step_report_for_new_tab_uses_new_primitive():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    report = build_terminal_step_report(
        prompt="open a new tab",
        heuristic_only=True,
        browser_state=browser_state,
    )

    candidate = report.candidates[0]
    assert candidate.plan.actions[0].kind == "browser_new_tab"
    assert candidate.target_preview == "Active browser"
    assert candidate.expected_outcome == "Open a fresh blank tab in the current browser."


def test_terminal_step_report_for_new_tab_search_shows_compound_preview():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    report = build_terminal_step_report(
        prompt="then open a new tab and put youtube then search nine vicious",
        heuristic_only=True,
        browser_state=browser_state,
    )

    candidate = report.candidates[0]
    assert [action.kind for action in candidate.plan.actions] == ["browser_new_tab", "open_url"]
    assert candidate.label == 'Open a new tab + Open youtube search for "nine vicious"'
    assert candidate.target_preview == 'Active browser -> Youtube search for "nine vicious"'
    assert candidate.expected_outcome == "Open a fresh tab, then navigate it to the requested search results."


def test_terminal_step_report_for_close_tab_uses_close_candidate_only():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    report = build_terminal_step_report(
        prompt="close the tab",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert len(report.candidates) == 1
    candidate = report.candidates[0]
    assert candidate.plan.actions[0].kind == "browser_close_tab"
    assert candidate.label == "Close the current tab"
    assert candidate.expected_outcome == "Close the active browser tab."


def test_terminal_step_report_for_extract_cards_uses_cached_cards():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=llama.cpp&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="llama.cpp",
        result_cards=[{"index": 1, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp"}],
    )

    report = build_terminal_step_report(
        prompt="extract cards",
        heuristic_only=True,
        browser_state=browser_state,
    )

    candidate = report.candidates[0]
    assert candidate.plan.actions[0].kind == "browser_extract_cards"
    assert candidate.target_preview == "1 cached result cards"


def test_terminal_step_report_for_rank_cards_shows_goal_fields():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {"index": 1, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Simple CLI for local models."},
            {"index": 2, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "C/C++ inference runtime."},
        ],
    )

    report = build_terminal_step_report(
        prompt="which repo best matches a beginner local llm workflow on a laptop",
        heuristic_only=True,
        browser_state=browser_state,
    )

    candidate = report.candidates[0]
    assert candidate.plan.actions[0].kind == "browser_rank_cards"
    assert candidate.expected_fields == ["goal", "best_title", "best_url", "best_score", "ranking"]


def test_terminal_step_report_does_not_offer_irrelevant_context_for_unknown_prompt():
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    report = build_terminal_step_report(
        prompt="do the thing from earlier but cooler",
        heuristic_only=True,
        browser_state=browser_state,
    )

    assert report.candidates == []
    assert "planner_clarification" in report.constraints


def test_raw_terminal_plan_receives_browser_context():
    captured_messages = {}

    class DummyClient:
        def chat(self, *, model, messages, temperature):
            captured_messages["messages"] = messages
            return json.dumps({"actions": [{"kind": "open_search_result", "target": "1"}]})

    browser_state = BrowserSessionState(
        current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
        page_kind="search_results",
        search_engine="youtube",
        search_query="lo fi hip hop",
        result_urls=["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    plan = build_raw_terminal_plan(
        prompt="click the first video",
        model="phi3:mini",
        client=DummyClient(),
        browser_state=browser_state,
    )

    assert plan.source == "raw_model"
    assert plan.actions[0].kind == "open_search_result"
    system_message = captured_messages["messages"][0].content
    assert "Current browser URL" in system_message
    assert "youtube" in system_message
    assert "Cached browser results: 1" in system_message


def test_language_v2_model_fallback_compiles_messy_prompt(monkeypatch):
    captured_messages = {}

    class DummyClient:
        def chat(self, *, model, messages, temperature):
            captured_messages["messages"] = messages
            return json.dumps(
                {
                    "actions": [
                        {"kind": "browser_search_subject", "target": "youtube"},
                        {"kind": "open_search_result", "target": "1"},
                    ]
                }
            )

    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )
    monkeypatch.setenv(BROWSER_STATE_ENV, str(Path.cwd() / ".pytest_language_state.json"))
    monkeypatch.setattr("memory_system.natural_terminal._heuristic_plan", lambda *args, **kwargs: None)

    plan = build_terminal_plan(
        prompt="pull some yt coverage on this repo and crack open the opener",
        model="phi3:mini",
        client=DummyClient(),
        browser_state=browser_state,
    )

    assert plan.source == "language_model"
    assert [action.kind for action in plan.actions] == ["browser_search_subject", "open_search_result"]
    system_message = captured_messages["messages"][0].content
    assert "Memla Language Ontology V2" in system_message
    assert "compile messy human language" in system_message
    user_message = captured_messages["messages"][1].content
    assert "Normalized translation surface" in user_message


def test_compiler_surface_rewrites_v3_frontier_language():
    surface = _compiler_surface_text(
        "sort out the repo that suits a beginner local llm setup on a weak laptop then scope out some youtube coverage on the winner and peel open the top one then tell me which source lands the clearest explanation"
    )

    assert "find whatever repo fits best" in surface
    assert "find a youtube video about the winner" in surface
    assert "open the first one" in surface
    assert "best explains" in surface


def test_merge_language_actions_completes_partial_v3_chain():
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {"index": 1, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Beginner local models", "meta": "beginner | local"},
            {"index": 2, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "CPU inference in C/C++", "meta": "cpp | cpu"},
        ],
    )
    partial = [
        TerminalAction(kind="browser_rank_cards", target="current_cards", resolved_target="current_cards"),
        TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
    ]

    merged = _merge_language_actions(
        partial,
        prompt="sort out the repo that suits a beginner local llm setup on a weak laptop, then scope out some youtube coverage on the winner and peel open the top one, then if that first clip is weak crack a stronger one and sum it up, then scope out a reddit thread on it and peel open the top one, then tell me which source lands the clearest beginner weak laptop explanation",
        browser_state=browser_state,
    )

    assert [action.kind for action in merged] == [
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


def test_language_v2_rejects_invalid_compiled_plan():
    class DummyClient:
        def chat(self, *, model, messages, temperature):
            return json.dumps({"actions": [{"kind": "browser_synthesize_evidence", "target": "cpu inference"}]})

    plan = build_terminal_plan(
        prompt="pull it all together",
        model="phi3:mini",
        client=DummyClient(),
    )

    assert plan.source == "language_model"
    assert plan.actions == []
    assert "browser_evidence_missing" in plan.residual_constraints


def test_language_memory_reuses_prior_compile_without_model(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )
    remembered = TerminalPlan(
        prompt="pull some yt coverage on this repo and crack open the opener",
        source="language_model",
        actions=[
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
        ],
    )

    remember_language_compile(
        prompt=remembered.prompt,
        browser_state=browser_state,
        plan=remembered,
    )

    class FailClient:
        def chat(self, *, model, messages, temperature):
            raise AssertionError("language model should not be called when memory matches")

    monkeypatch.setattr("memory_system.natural_terminal._heuristic_plan", lambda *args, **kwargs: None)

    plan = build_terminal_plan(
        prompt="pull some yt coverage on this repo and crack open the opener please",
        model="phi3:mini",
        client=FailClient(),
        browser_state=browser_state,
    )

    assert plan.source == "language_memory"
    assert [action.kind for action in plan.actions] == ["browser_search_subject", "open_search_result"]


def test_execute_terminal_plan_persists_language_memory_after_success(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )
    plan = TerminalPlan(
        prompt="pull some yt coverage on this repo and crack open the opener",
        source="language_model",
        actions=[
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
        ],
    )

    result = execute_terminal_plan(plan, platform_name="linux", browser_state=browser_state)

    assert result.ok is True
    assert terminal_language_memory_path().exists() is True


def test_execute_terminal_plan_persists_memory_ontology_after_success(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )
    plan = TerminalPlan(
        prompt="pull some yt coverage on this repo and crack open the opener",
        source="language_model",
        actions=[
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
        ],
    )

    result = execute_terminal_plan(plan, platform_name="linux", browser_state=browser_state)

    assert result.ok is True
    ontology_entries = load_memory_ontology(terminal_memory_ontology_path())
    assert len(ontology_entries) == 1
    assert ontology_entries[0]["memory_kind"] == "language_compilation"
    assert ontology_entries[0]["promotion_stage"] == "episodic"
    assert ontology_entries[0]["status"] == "active"


def test_execute_terminal_plan_promotes_memory_ontology_to_semantic_after_reuse(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    browser_state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )
    seed_plan = TerminalPlan(
        prompt="pull some yt coverage on this repo and crack open the opener",
        source="language_model",
        actions=[
            TerminalAction(
                kind="open_url",
                target="https://www.youtube.com/results?search_query=llama.cpp",
                resolved_target="https://www.youtube.com/results?search_query=llama.cpp",
            ),
        ],
    )
    remember_language_compile(
        prompt=seed_plan.prompt,
        browser_state=browser_state,
        plan=seed_plan,
    )
    reused_plan = TerminalPlan(
        prompt="find a youtube video about this repo and open the first one",
        source="language_memory",
        actions=seed_plan.actions,
    )

    execute_terminal_plan(reused_plan, platform_name="linux", browser_state=browser_state)
    execute_terminal_plan(reused_plan, platform_name="linux", browser_state=browser_state)

    ontology_entries = load_memory_ontology(terminal_memory_ontology_path())
    assert len(ontology_entries) == 1
    assert ontology_entries[0]["promotion_stage"] == "semantic"
    assert ontology_entries[0]["reuse_count"] >= 2
    assert ontology_entries[0]["successful_reuse_count"] >= 2


def test_language_rule_plan_activates_after_repeated_memory_hits(monkeypatch, tmp_path):
    monkeypatch.setenv(BROWSER_STATE_ENV, str(tmp_path / "browser_state.json"))
    browser_state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {"index": 1, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Beginner local models", "meta": "beginner | local"},
            {"index": 2, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "CPU inference in C/C++", "meta": "cpp | cpu"},
        ],
    )
    plan = TerminalPlan(
        prompt="sort out the repo that suits a beginner local llm setup on a weak laptop, then scope out some youtube coverage on the winner and peel open the top one please, then if that first clip is weak crack a stronger one and sum it up, then scope out a reddit thread on it and peel open the top one, then tell me which source lands the clearest beginner weak laptop explanation",
        source="language_memory",
        actions=[
            TerminalAction(kind="browser_rank_cards", target="current_cards", resolved_target="current_cards", note=json.dumps({"goal": "beginner weak laptop local llm"})),
            TerminalAction(kind="browser_search_subject", target="youtube", resolved_target="youtube", note=json.dumps({"engine": "youtube"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_retry_subject_result", target="better_result", resolved_target="better_result"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_search_subject", target="reddit", resolved_target="reddit", note=json.dumps({"engine": "reddit"})),
            TerminalAction(kind="open_search_result", target="1", resolved_target="1"),
            TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"),
            TerminalAction(kind="browser_synthesize_evidence", target="current_evidence", resolved_target="current_evidence", note=json.dumps({"goal": "beginner weak laptop explanation"})),
        ],
    )

    _promote_language_rules(prompt=plan.prompt, browser_state=browser_state, plan=plan)
    _promote_language_rules(prompt=plan.prompt, browser_state=browser_state, plan=plan)

    promoted = _language_rule_plan(plan.prompt, browser_state=browser_state)

    assert terminal_language_rule_path().exists() is True
    assert promoted is not None
    assert promoted.source == "language_rule"
    ontology_entries = load_memory_ontology(terminal_memory_ontology_path())
    assert len(ontology_entries) == 1
    assert ontology_entries[0]["promotion_stage"] == "rule"
    assert [action.kind for action in promoted.actions] == [
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


def test_terminal_execute_plan_launches_linux_apps(monkeypatch):
    launched: list[list[str]] = []

    def fake_which(name: str) -> str | None:
        if name == "google-chrome-stable":
            return "/usr/bin/google-chrome-stable"
        if name == "spotify":
            return "/usr/bin/spotify"
        return None

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", fake_which)
    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    plan = build_terminal_plan(prompt="open chrome and spotify", heuristic_only=True)
    result = execute_terminal_plan(plan, platform_name="linux")

    assert result.ok is True
    assert launched == [
        ["/usr/bin/google-chrome-stable"],
        ["/usr/bin/spotify"],
    ]


def test_terminal_execute_plan_opens_first_search_result(monkeypatch, tmp_path):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    state_path = tmp_path / "browser_state.json"
    save_browser_session_state(
        BrowserSessionState(
            current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
            page_kind="search_results",
            search_engine="youtube",
            search_query="lo fi hip hop",
        ),
        state_path,
    )
    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_urls",
        lambda engine, query, limit=5: ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    plan = TerminalPlan(
        prompt="click the first video",
        source="heuristic",
        actions=[TerminalAction(kind="open_search_result", target="1", resolved_target="1")],
    )
    result = execute_terminal_plan(plan, platform_name="linux", state_path=state_path)

    assert result.ok is True
    assert launched == [["xdg-open", "https://www.youtube.com/watch?v=dQw4w9WgXcQ"]]
    assert result.browser_state["page_kind"] == "video_page"
    assert result.browser_state["current_url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_terminal_execute_search_primes_result_cache(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {"index": 1, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp"},
            {"index": 2, "title": "oobabooga/text-generation-webui", "url": "https://github.com/oobabooga/text-generation-webui"},
        ],
    )

    plan = build_terminal_plan(prompt="open github and search llama.cpp", heuristic_only=True)
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=BrowserSessionState())

    assert result.ok is True
    assert launched == [["xdg-open", "https://github.com/search?q=llama+cpp&type=repositories"]]
    assert result.browser_state["page_kind"] == "search_results"
    assert result.browser_state["result_urls"] == [
        "https://github.com/ggml-org/llama.cpp",
        "https://github.com/oobabooga/text-generation-webui",
    ]


def test_terminal_execute_plan_opens_new_tab(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)

    plan = TerminalPlan(
        prompt="open a new tab",
        source="heuristic",
        actions=[TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab")],
    )
    result = execute_terminal_plan(
        plan,
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )

    assert result.ok is True
    assert launched == [["/usr/bin/xdotool", "key", "ctrl+t"]]
    assert result.browser_state["page_kind"] == "blank_tab"


def test_terminal_execute_plan_closes_tab(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)

    plan = build_terminal_plan(
        prompt="close the tab",
        heuristic_only=True,
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )
    result = execute_terminal_plan(
        plan,
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )

    assert result.ok is True
    assert launched == [["/usr/bin/xdotool", "key", "ctrl+w"]]
    assert result.browser_state["current_url"] == ""


def test_terminal_execute_plan_switches_tab_and_scrolls_and_submits(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)

    switch_result = execute_terminal_plan(
        TerminalPlan(prompt="switch tabs", source="heuristic", actions=[TerminalAction(kind="browser_switch_tab", target="next", resolved_target="next")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )
    scroll_result = execute_terminal_plan(
        TerminalPlan(prompt="scroll down", source="heuristic", actions=[TerminalAction(kind="browser_scroll", target="down", resolved_target="down")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )
    submit_result = execute_terminal_plan(
        TerminalPlan(prompt="submit", source="heuristic", actions=[TerminalAction(kind="browser_submit", target="submit", resolved_target="submit")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )

    assert switch_result.ok is True
    assert scroll_result.ok is True
    assert submit_result.ok is True
    assert launched == [
        ["/usr/bin/xdotool", "key", "ctrl+Tab"],
        ["/usr/bin/xdotool", "key", "Page_Down"],
        ["/usr/bin/xdotool", "key", "Return"],
    ]


def test_terminal_execute_plan_clicks_text_and_extracts_cards(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    state = BrowserSessionState(
        current_url="https://github.com/search?q=llama.cpp&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="llama.cpp",
        result_cards=[
            {"index": 1, "title": "ggml-org/llama.cpp", "url": "https://github.com/ggml-org/llama.cpp", "summary": "LLM inference"},
            {"index": 2, "title": "ollama/ollama", "url": "https://github.com/ollama/ollama", "summary": "Run LLMs"},
        ],
    )

    click_result = execute_terminal_plan(
        TerminalPlan(prompt="click ollama", source="heuristic", actions=[TerminalAction(kind="browser_click_text", target="ollama", resolved_target="ollama")]),
        platform_name="linux",
        browser_state=state,
    )
    cards_result = execute_terminal_plan(
        TerminalPlan(prompt="extract cards", source="heuristic", actions=[TerminalAction(kind="browser_extract_cards", target="current_cards", resolved_target="current_cards")]),
        platform_name="linux",
        browser_state=state,
    )

    assert click_result.ok is True
    assert launched == [["xdg-open", "https://github.com/ollama/ollama"]]
    assert cards_result.ok is True
    assert len(cards_result.records[0].details["cards"]) == 2


def test_terminal_execute_plan_types_waits_extracts_and_screenshots(monkeypatch, tmp_path):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

        def wait(self, timeout=None):
            return 0

    sleeps: list[float] = []

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    monkeypatch.setattr("memory_system.natural_terminal.time.sleep", lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr("memory_system.natural_terminal.terminal_browser_state_path", lambda: tmp_path / "browser_state.json")
    monkeypatch.setattr("memory_system.natural_terminal.time.time", lambda: 1234567890)
    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", lambda url: "<html><title>Example</title></html>")
    monkeypatch.setattr(
        "memory_system.natural_terminal._browser_screenshot_command",
        lambda output_path, platform_name: ["/usr/bin/gnome-screenshot", "-f", str(output_path)],
    )

    type_result = execute_terminal_plan(
        TerminalPlan(prompt="type hello", source="heuristic", actions=[TerminalAction(kind="browser_type_text", target="hello", resolved_target="hello")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://example.com", page_kind="web_page"),
    )
    wait_result = execute_terminal_plan(
        TerminalPlan(prompt="wait 2", source="heuristic", actions=[TerminalAction(kind="browser_wait", target="2", resolved_target="2")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://example.com", page_kind="web_page"),
    )
    extract_result = execute_terminal_plan(
        TerminalPlan(prompt="extract page", source="heuristic", actions=[TerminalAction(kind="browser_extract_page", target="current_page", resolved_target="current_page")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://example.com", page_kind="web_page"),
    )
    screenshot_result = execute_terminal_plan(
        TerminalPlan(prompt="screenshot", source="heuristic", actions=[TerminalAction(kind="browser_screenshot", target="current_page", resolved_target="current_page")]),
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://example.com", page_kind="web_page"),
    )

    assert type_result.ok is True
    assert wait_result.ok is True
    assert extract_result.ok is True
    assert screenshot_result.ok is True
    assert launched[0] == ["/usr/bin/xdotool", "type", "--delay", "0", "hello"]
    assert sleeps == [2.0]


def test_windows_browser_new_tab_command_activates_browser_first(monkeypatch):
    monkeypatch.setenv("MEMLA_BROWSER_APP", "brave")

    command = _browser_new_tab_command(platform_name="win32")

    assert command[:3] == ["powershell.exe", "-NoProfile", "-Command"]
    assert "AppActivate($title)" in command[3]
    assert "Brave" in command[3]
    assert "$wshell.SendKeys('^t')" in command[3]


def test_windows_new_tab_followed_by_url_falls_back_safely(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            self.command = list(command)
            launched.append(self.command)

        def wait(self, timeout=None):
            if self.command and str(self.command[0]).lower().endswith("powershell.exe"):
                return 17
            return 0

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    plan = build_terminal_plan(
        prompt="open a new tab with youtube and find a cool video on llms",
        heuristic_only=True,
    )
    result = execute_terminal_plan(
        plan,
        platform_name="win32",
        browser_state=BrowserSessionState(
            current_url="https://github.com/ggml-org/llama.cpp",
            page_kind="repo_page",
            browser_app="brave",
        ),
    )

    assert result.ok is True
    assert launched[0][0] == "powershell.exe"
    assert launched[1][:4] == ["cmd", "/c", "start", ""]
    assert launched[1][4] == "https://www.youtube.com/results?search_query=cool+llms"
    assert result.records[0].message.startswith("Skipped the raw new-tab shortcut")
    assert result.browser_state["current_url"] == "https://www.youtube.com/results?search_query=cool+llms"


def test_terminal_execute_plan_new_tab_then_search_uses_active_tab_navigation(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr("memory_system.natural_terminal.shutil.which", lambda name: "/usr/bin/xdotool" if name == "xdotool" else None)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_urls",
        lambda engine, query, limit=5: ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"],
    )

    plan = build_terminal_plan(
        prompt="now open a new tab and within that tab open youtube and search nine vicious",
        heuristic_only=True,
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )
    result = execute_terminal_plan(
        plan,
        platform_name="linux",
        browser_state=BrowserSessionState(current_url="https://github.com/ggml-org/llama.cpp", page_kind="repo_page"),
    )

    assert result.ok is True
    assert launched == [
        ["/usr/bin/xdotool", "key", "ctrl+t"],
        [
            "/usr/bin/xdotool",
            "key",
            "ctrl+l",
            "type",
            "--delay",
            "0",
            "https://www.youtube.com/results?search_query=nine+vicious",
            "key",
            "Return",
        ],
    ]
    assert result.browser_state["page_kind"] == "search_results"
    assert result.records[1].message.startswith("Navigated the active browser tab to")


def test_build_llm_client_prefers_reachable_ollama_port(monkeypatch):
    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def _fake_urlopen(request, timeout=0.0):
        full_url = request.full_url
        if "11435" in full_url:
            return DummyResponse()
        raise OSError("connection refused")

    monkeypatch.delenv("OLLAMA_URL", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setattr("memory_system.natural_terminal.urllib_request.urlopen", _fake_urlopen)

    client = build_llm_client(provider="ollama")

    assert client.base_url == "http://127.0.0.1:11435"


def test_build_llm_client_respects_explicit_base_url(monkeypatch):
    called = {"urlopen": False}

    def _fake_urlopen(request, timeout=0.0):
        called["urlopen"] = True
        raise AssertionError("urlopen should not be called when base_url is explicit")

    monkeypatch.setattr("memory_system.natural_terminal.urllib_request.urlopen", _fake_urlopen)

    client = build_llm_client(provider="ollama", base_url="http://127.0.0.1:9999")

    assert client.base_url == "http://127.0.0.1:9999"
    assert called["urlopen"] is False


def test_normalize_model_actions_converts_url_like_open_path_to_open_url():
    actions = _normalize_model_actions(
        {
            "actions": [
                {
                    "kind": "open_path",
                    "target": "https://github.com/mudler/LocalAI",
                }
            ]
        }
    )

    assert [action.kind for action in actions] == ["open_url"]
    assert actions[0].resolved_target == "https://github.com/mudler/LocalAI"


def test_fetch_search_result_urls_uses_github_api_first(monkeypatch):
    def fake_fetch(url: str, *, accept: str = "text/html") -> str:
        assert "api.github.com/search/repositories" in url
        assert accept == "application/vnd.github+json"
        return json.dumps(
            {
                "items": [
                    {"html_url": "https://github.com/ggml-org/llama.cpp"},
                    {"html_url": "https://github.com/oobabooga/text-generation-webui"},
                ]
            }
        )

    monkeypatch.setattr("memory_system.natural_terminal._fetch_url_text", fake_fetch)

    results = _fetch_search_result_urls("github", "llama.cpp", limit=2)

    assert results == [
        "https://github.com/ggml-org/llama.cpp",
        "https://github.com/oobabooga/text-generation-webui",
    ]


def test_fetch_search_result_urls_uses_web_backend_for_google(monkeypatch):
    def fake_fetch(url: str, *, accept: str = "text/html") -> str:
        assert "html.duckduckgo.com/html/" in url
        return """
        <html>
          <body>
            <a class="result__a" href="https://example.com/ai-agents-news">AI agents today</a>
            <a class="result__a" href="https://example.com/weather-minneapolis">Weather</a>
          </body>
        </html>
        """

    monkeypatch.setattr("memory_system.natural_terminal._fetch_url_text", fake_fetch)

    results = _fetch_search_result_urls("google", "ai agents news today", limit=2)

    assert results == [
        "https://example.com/ai-agents-news",
        "https://example.com/weather-minneapolis",
    ]


def test_terminal_execute_plan_reads_current_repo_page(monkeypatch, tmp_path):
    state_path = tmp_path / "browser_state.json"
    save_browser_session_state(
        BrowserSessionState(
            current_url="https://github.com/ggml-org/llama.cpp",
            page_kind="repo_page",
        ),
        state_path,
    )
    html = """
    <html>
      <head>
        <title>ggml-org/llama.cpp: LLM inference in C/C++</title>
        <meta property="og:description" content="Inference of LLaMA models in pure C/C++." />
      </head>
      <body>
        <a href="/ggml-org/llama.cpp/stargazers"><span>77.7k</span></a>
        <a href="/ggml-org/llama.cpp/forks"><span>11.2k</span></a>
      </body>
    </html>
    """
    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", lambda url: html)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_github_repo_snapshot",
        lambda owner, repo: {
            "repo": "ggml-org/llama.cpp",
            "description": "Inference of LLaMA models in pure C/C++.",
            "summary": "ggml-org/llama.cpp: Inference of LLaMA models in pure C/C++.",
            "stars": "77.7k",
            "forks": "11.2k",
            "language": "C++",
            "topics": "llm, inference, cpp",
        },
    )

    plan = TerminalPlan(
        prompt="what is this repo",
        source="heuristic",
        actions=[TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page")],
    )
    result = execute_terminal_plan(plan, platform_name="linux", state_path=state_path)

    assert result.ok is True
    assert result.records[0].details["repo"] == "ggml-org/llama.cpp"
    assert result.records[0].details["stars"] == "77.7k"
    assert result.records[0].details["forks"] == "11.2k"
    assert "Repo summary:" in result.records[0].message
    assert "language C++" in result.records[0].message


def test_terminal_execute_plan_answers_bounded_web_query(monkeypatch, tmp_path):
    state_path = tmp_path / "browser_state.json"
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and product launches are accelerating in the AI agents space.",
            },
        ],
    )

    def fake_fetch_page_html(url: str) -> str:
        if "funding" in url:
            return """
            <html>
              <head>
                <title>AI agents funding</title>
                <meta name="description" content="Funding and product launches are accelerating in the AI agents space." />
              </head>
            </html>
            """
        return """
        <html>
          <head>
            <title>AI agents today</title>
            <meta name="description" content="AI agents are getting more capable across coding and commerce workflows." />
          </head>
        </html>
        """

    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", fake_fetch_page_html)

    plan = TerminalPlan(
        prompt="what's happening in the news about AI agents today?",
        source="heuristic",
        actions=[
            TerminalAction(
                kind="browser_answer_query",
                target="ai agents news today",
                resolved_target="ai agents news today",
                note=json.dumps(
                    {
                        "goal": "what's happening in the news about AI agents today?",
                        "query": "ai agents news today",
                    }
                ),
            )
        ],
    )

    result = execute_terminal_plan(plan, platform_name="linux", state_path=state_path)

    assert result.ok is True
    assert result.records[0].status == "ok"
    assert "AI agents are getting more capable" in result.records[0].message
    assert result.browser_state["current_url"] == "https://example.com/ai-agents"
    assert result.browser_state["search_query"] == "ai agents news today"
    assert len(result.browser_state["result_cards"]) == 2
    assert len(result.browser_state["evidence_items"]) == 2
    assert result.records[0].details["source_count"] == 2


def test_resolve_web_answer_renders_memla_friend_voice(monkeypatch):
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and product launches are accelerating in the AI agents space.",
            },
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: f"""
        <html>
          <head>
            <title>{'AI agents today' if 'funding' not in url else 'AI agents funding'}</title>
            <meta name="description" content="{'AI agents are getting more capable across coding and commerce workflows.' if 'funding' not in url else 'Funding and product launches are accelerating in the AI agents space.'}" />
          </head>
        </html>
        """,
    )

    payload = _resolve_web_answer(
        prompt="what's happening in the news about AI agents today?",
        query="ai agents news today",
    )

    assert payload["raw_answer"].startswith("AI agents are getting more capable")
    assert payload["answer"].startswith("AI agents are getting more capable")
    assert "I checked 2 sources" in payload["answer"]
    assert payload["answer_style"]["voice"] == "memla_web_friend_v1"
    assert payload["answer_style"]["slice"] == "news"


def test_resolve_web_answer_uses_model_renderer_when_available(monkeypatch):
    class DummyClient:
        def chat(self, **kwargs):
            return json.dumps({"answer": "Dario Amodei is Anthropic's CEO."})

    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "Anthropic's CEO Spends 40% of His Time on One Thing—and It's Not ...",
                "url": "https://example.com/anthropic-ceo",
                "summary": "Anthropic's",
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>Anthropic's CEO Spends 40% of His Time on One Thing—and It's Not ...</title>
            <meta name="description" content="Anthropic's" />
          </head>
          <body>
            <article>Dario Amodei leads Anthropic as chief executive officer.</article>
          </body>
        </html>
        """,
    )

    payload = _resolve_web_answer(
        prompt="who is the ceo of anthropic?",
        query="who is the ceo of anthropic",
        client=DummyClient(),
        model="claude-sonnet-4-20250514",
    )

    assert payload["raw_answer"] == "Dario Amodei is Anthropic's CEO."
    assert payload["answer_style"]["generator"] == "model"
    assert payload["answer"].startswith("Dario Amodei is Anthropic's CEO.")


def test_resolve_web_answer_prefers_query_focused_body_fact_over_page_slogan(monkeypatch):
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "Weather Forecast and Conditions for Minneapolis",
                "url": "https://example.com/minneapolis-weather",
                "summary": "Get accurate hourly forecasts for Minneapolis today, tonight and tomorrow.",
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>Weather Forecast and Conditions for Minneapolis</title>
            <meta name="description" content="Get accurate hourly forecasts for Minneapolis today, tonight and tomorrow." />
          </head>
          <body>
            <nav>today hourly ten day radar</nav>
            <article>
              Tomorrow in Minneapolis, light rain is expected in the afternoon with a 62% chance of precipitation.
              The high will be 61 F and the low will be 47 F.
            </article>
          </body>
        </html>
        """,
    )

    payload = _resolve_web_answer(
        prompt="is it raining tomorrow in minneapolis?",
        query="is it raining tomorrow in minneapolis",
    )

    assert "light rain is expected" in payload["raw_answer"].lower()
    assert "62% chance of precipitation" in payload["raw_answer"]


def test_resolve_web_answer_model_renderer_receives_real_body_chunks(monkeypatch):
    captured = {"prompt": ""}

    class DummyClient:
        def chat(self, **kwargs):
            captured["prompt"] = kwargs["messages"][-1].content
            return json.dumps(
                {
                    "answer": "Yes. Minneapolis is expected to get light rain tomorrow with about a 62% chance of precipitation and a high near 61 F.",
                    "question_type": "weather_precipitation",
                    "relevant_chunk_ids": ["s1c2"],
                    "extracted_facts": ["62% chance of precipitation", "high near 61 F"],
                    "missing_fields": [],
                }
            )

    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "Weather Forecast and Conditions for Minneapolis",
                "url": "https://example.com/minneapolis-weather",
                "summary": "Get accurate hourly forecasts for Minneapolis today, tonight and tomorrow.",
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>Weather Forecast and Conditions for Minneapolis</title>
            <meta name="description" content="Get accurate hourly forecasts for Minneapolis today, tonight and tomorrow." />
          </head>
          <body>
            <nav>today hourly ten day radar</nav>
            <article>
              Tomorrow in Minneapolis, light rain is expected in the afternoon with a 62% chance of precipitation.
              The high will be 61 F and the low will be 47 F.
            </article>
          </body>
        </html>
        """,
    )

    payload = _resolve_web_answer(
        prompt="is it raining tomorrow in minneapolis?",
        query="is it raining tomorrow in minneapolis",
        client=DummyClient(),
        model="claude-sonnet-4-20250514",
    )

    assert "62% chance of precipitation" in captured["prompt"]
    assert payload["question_type"] == "weather_precipitation"
    assert payload["relevant_chunk_ids"] == ["s1c2"]
    assert payload["extracted_facts"] == ["62% chance of precipitation", "high near 61 F"]
    assert payload["answer"].startswith("Yes.")


def test_run_web_answer_benchmark_collects_answer_rows(monkeypatch, tmp_path):
    cases_path = tmp_path / "web_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "web_news_topic",
                "prompt": "what's happening in the news about AI agents today?",
                "expected_actions": ["browser_answer_query:ai agents news today"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and product launches are accelerating in the AI agents space.",
            },
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: f"""
        <html>
          <head>
            <title>{'AI agents today' if 'funding' not in url else 'AI agents funding'}</title>
            <meta name="description" content="{'AI agents are getting more capable across coding and commerce workflows.' if 'funding' not in url else 'Funding and product launches are accelerating in the AI agents space.'}" />
          </head>
        </html>
        """,
    )

    report = run_web_answer_benchmark(
        cases_path=str(cases_path),
        memla_model="claude-sonnet-4-20250514",
        memla_provider="anthropic",
        heuristic_only=True,
    )

    assert report["cases"] == 1
    assert report["answered_count"] == 1
    assert report["rows"][0]["query"] == "ai agents news today"
    assert report["rows"][0]["answer_voice"] == "memla_web_friend_v1"
    assert report["rows"][0]["source_count"] == 2


def test_rescue_web_answer_with_teacher_parses_rewrite_payload():
    class DummyClient:
        def chat(self, **kwargs):
            return json.dumps(
                {
                    "answer": "Anthropic was co-founded in 2021 by Dario Amodei and Daniela Amodei.",
                    "why_better": "It states the fact directly instead of describing a page.",
                    "promotion_notes": ["prefer direct founder statement", "avoid page-description phrasing"],
                    "question_type": "creator_identity",
                    "relevant_chunk_ids": ["s1c2"],
                    "extracted_facts": ["Founded in 2021", "Dario Amodei", "Daniela Amodei"],
                    "missing_fields": [],
                }
            )

    payload = _rescue_web_answer_with_teacher(
        client=DummyClient(),
        model="claude-sonnet-4-20250514",
        prompt="who founded anthropic?",
        query="who founded anthropic",
        slice_kind="fact",
        current_answer="This page covers Anthropic leadership.",
        source_title="Anthropic founders",
        source_url="https://example.com/anthropic-founders",
        source_count=2,
        result_cards=[
            {
                "title": "Anthropic founders",
                "summary": "Anthropic was founded by Dario Amodei and Daniela Amodei.",
                "url": "https://example.com/anthropic-founders",
            }
        ],
        evidence_items=[
            {
                "title": "Anthropic founders",
                "summary": "Anthropic was founded by Dario Amodei and Daniela Amodei.",
                "content_preview": "Anthropic launched in 2021.",
                "url": "https://example.com/anthropic-founders",
            }
        ],
        evidence_chunks=[
            {
                "chunk_id": "s1c2",
                "title": "Anthropic founders",
                "url": "https://example.com/anthropic-founders",
                "text": "Anthropic was founded in 2021 by Dario Amodei and Daniela Amodei.",
            }
        ],
        coaching="Answer directly.",
    )

    assert payload["answer"].startswith("Anthropic was co-founded")
    assert payload["why_better"] == "It states the fact directly instead of describing a page."
    assert payload["promotion_notes"] == ["prefer direct founder statement", "avoid page-description phrasing"]
    assert payload["question_type"] == "creator_identity"
    assert payload["relevant_chunk_ids"] == ["s1c2"]
    assert payload["extracted_facts"] == ["Founded in 2021", "Dario Amodei", "Daniela Amodei"]


def test_hard_check_web_answer_fails_caption_like_creator_output():
    result = _hard_check_web_answer(
        prompt="who invented the light bulb",
        question_type="creator_identity",
        answer="Meet the largely forgotten pioneers who started creating the light bulb some 80 years before Edison.",
        extracted_facts=[],
        missing_fields=["creator_name"],
    )

    assert result["applicable"] is True
    assert result["passed"] is False
    assert "answer_looks_like_caption_or_headline" in result["reasons"]
    assert "missing_creator_name" in result["reasons"]


def test_hard_check_web_answer_passes_age_at_event_with_computed_age():
    result = _hard_check_web_answer(
        prompt="who founded apple and how old was steve jobs then",
        question_type="derived_age_at_event",
        answer="Steve Jobs co-founded Apple in 1976, when he was 21 years old.",
        extracted_facts=["Steve Jobs", "born 1955", "Apple founded 1976", "age 21"],
        missing_fields=[],
    )

    assert result["applicable"] is True
    assert result["passed"] is True
    assert result["score"] >= 0.8


def test_extract_google_ai_overview_from_html_parses_answer_and_sources():
    html = """
    <html>
      <body>
        <div>AI Overview</div>
        <div>
          Thomas Edison patented the first practical incandescent light bulb in 1879-1880.
          Born on February 11, 1847, Edison was 32 years old when his team at Menlo Park developed a long-lasting bulb.
        </div>
        <a href="https://www.energy.gov/articles/history-light-bulb">Department of Energy</a>
        <a href="https://www.britannica.com/technology/light-bulb">Britannica</a>
        <h3>Department of Energy (.gov)</h3>
      </body>
    </html>
    """

    payload = _extract_google_ai_overview_from_html(html)

    assert "Thomas Edison patented the first practical incandescent light bulb" in payload["answer"]
    assert payload["answer_kind"] == "google_ai_overview"
    assert len(payload["source_cards"]) >= 2
    assert payload["source_cards"][0]["url"] == "https://www.energy.gov/articles/history-light-bulb"


def test_extract_google_ai_overview_from_html_stops_before_web_results():
    html = """
    <html>
      <body>
        <div>AI Overview</div>
        <div>
          Sam Altman is the CEO of OpenAI.
          He has held this position since 2019, leading the company through the launch of ChatGPT.
        </div>
        <a href="https://en.wikipedia.org/wiki/Sam_Altman">Wikipedia</a>
        <div>Web results</div>
        <h3>Sam Altman</h3>
      </body>
    </html>
    """

    payload = _extract_google_ai_overview_from_html(html, query="who is the ceo of openai")

    assert payload["answer"] == "Sam Altman is the CEO of OpenAI. He has held this position since 2019, leading the company through the launch of ChatGPT."
    assert payload["answer_kind"] == "google_ai_overview"
    assert payload["source_cards"][0]["url"] == "https://en.wikipedia.org/wiki/Sam_Altman"


def test_extract_google_weather_answer_from_html_answers_precipitation_question():
    html = """
    <html>
      <body>
        <div id="gsr">
          AI Mode All News Search Results Minneapolis, MN • Choose area Weather Friday, April 10
          52°/31° Sunny 35° 12 AM
          Thu 47°/31° Fri 52°/31° Sat 59°/36°
          Precipitation·0%
          12 AM – 0% 1 AM – 0%
        </div>
        <a href="https://www.mprnews.org/weather">MPR weather</a>
      </body>
    </html>
    """

    payload = _extract_google_weather_answer_from_html(
        html,
        query="is it raining tomorrow in minneapolis",
    )

    assert payload["answer_kind"] == "google_weather"
    assert payload["answer"].startswith("No, it doesn't look like rain tomorrow in Minneapolis, MN.")
    assert "0% precipitation chance" in payload["answer"]
    assert payload["source_cards"][0]["url"] == "https://www.mprnews.org/weather"


def test_extract_google_role_holder_answer_from_html_parses_breadcrumb_answer():
    html = """
    <html>
      <body>
        <div>
          AI Overview Sam Altman is the CEO of OpenAI.
          Explore more OpenAI › CEO Sam Altman Nov 29, 2023
        </div>
        <a href="https://en.wikipedia.org/wiki/Sam_Altman">Wikipedia</a>
      </body>
    </html>
    """

    payload = _extract_google_role_holder_answer_from_html(
        html,
        query="who is the ceo of openai",
    )

    assert payload["answer_kind"] == "google_role_holder"
    assert payload["answer"] == "Sam Altman is the CEO of OpenAI."
    assert payload["source_cards"][0]["url"] == "https://en.wikipedia.org/wiki/Sam_Altman"


def test_extract_google_featured_snippet_rejects_article_teaser_for_creator_query():
    html = """
    <html>
      <body>
        <div class="hgKElc">
          The light bulb literally brightened the whole world and changed history forever.
        </div>
      </body>
    </html>
    """

    payload = _extract_google_featured_snippet_from_html(
        html,
        query="who invented the light bulb and how old were they",
    )

    assert payload == {}


def test_resolve_web_answer_prefers_google_answer_surface(monkeypatch):
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_google_answer_surface",
        lambda query: {
            "answer": "Thomas Edison patented the first practical incandescent light bulb in 1879 and was 32 years old then.",
            "answer_kind": "google_ai_overview",
            "search_url": "https://www.google.com/search?q=who+invented+the+light+bulb+and+how+old+were+they",
            "source_cards": [
                {
                    "title": "Department of Energy",
                    "url": "https://www.energy.gov/articles/history-light-bulb",
                    "summary": "",
                }
            ],
        },
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_urls",
        lambda engine, query, limit=5: [],
    )

    payload = _resolve_web_answer(
        prompt="who invented the light bulb and how old were they when they did it",
        query="who invented the light bulb and how old were they when they did it",
    )

    assert payload["raw_answer"] == "Thomas Edison patented the first practical incandescent light bulb in 1879 and was 32 years old then."
    assert payload["answer_style"]["source_kind"] == "google_ai_overview"
    assert payload["answer"] == "Thomas Edison patented the first practical incandescent light bulb in 1879 and was 32 years old then."
    assert payload["source_count"] == 1


def test_run_web_teacher_loop_promotes_rescued_answers(monkeypatch, tmp_path):
    cases_path = tmp_path / "web_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "web_fact_founder",
                "prompt": "who founded anthropic?",
                "expected_actions": ["browser_answer_query:who founded anthropic"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "Anthropic founders",
                "url": "https://example.com/anthropic-founders",
                "summary": "Anthropic leadership and company overview.",
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>Anthropic founders</title>
            <meta name="description" content="Anthropic leadership and company overview." />
          </head>
          <body>
            <article>Anthropic was founded in 2021 by Dario Amodei and Daniela Amodei.</article>
          </body>
        </html>
        """,
    )

    class SequenceClient:
        def __init__(self, responses):
            self._responses = list(responses)

        def chat(self, **kwargs):
            assert self._responses
            return self._responses.pop(0)

    teacher_client = SequenceClient(
        [
            json.dumps(
                {
                    "answer": "Anthropic was founded in 2021 by Dario Amodei and Daniela Amodei.",
                    "why_better": "It answers the question directly.",
                    "promotion_notes": ["promote direct founder wording"],
                    "question_type": "creator_identity",
                    "relevant_chunk_ids": ["s1c2"],
                    "extracted_facts": ["Founded in 2021", "Dario Amodei", "Daniela Amodei"],
                    "missing_fields": [],
                }
            )
        ]
    )
    judge_client = SequenceClient(
        [
            json.dumps(
                {
                    "directness": 2,
                    "warmth": 3,
                    "groundedness": 3,
                    "helpfulness": 2,
                    "overall": 2,
                    "verdict": "too vague",
                    "coaching": "Answer the founder fact directly.",
                }
            ),
            json.dumps(
                {
                    "directness": 5,
                    "warmth": 4,
                    "groundedness": 5,
                    "helpfulness": 5,
                    "overall": 5,
                    "verdict": "strong",
                    "coaching": "Keep this direct style.",
                }
            ),
        ]
    )

    def _fake_build_client(provider=None, base_url=None):
        if provider == "teacher":
            return teacher_client
        if provider == "judge":
            return judge_client
        raise AssertionError(f"unexpected provider {provider}")

    monkeypatch.setattr("memory_system.natural_terminal.build_llm_client", _fake_build_client)

    report = run_web_teacher_loop(
        cases_path=str(cases_path),
        memla_model="claude-sonnet-4-20250514",
        teacher_model="claude-sonnet-4-20250514",
        teacher_provider="teacher",
        judge_model="claude-sonnet-4-20250514",
        judge_provider="judge",
        heuristic_only=True,
        rescue_threshold=4,
    )

    assert report["cases"] == 1
    assert report["rescued_count"] == 1
    assert report["improved_count"] == 1
    assert report["promoted_rescue_count"] == 1
    assert report["trace_row_count"] == 1
    row = report["rows"][0]
    assert row["promoted_lane"] == "teacher_rescue"
    assert row["rescued_answer"].startswith("Anthropic was founded in 2021")
    assert row["promotion_notes"] == ["promote direct founder wording"]
    assert report["trace_rows"][0]["promoted_lane"] == "teacher_rescue"
    assert report["trace_rows"][0]["question_type"] == "creator_identity"
    assert report["trace_rows"][0]["rescued_relevant_chunk_ids"] == ["s1c2"]
    assert report["hard_pass_rate"] == 1.0


def test_distill_web_policy_bank_extracts_web_behaviors(tmp_path):
    trace_path = tmp_path / "web_teacher_trace_bank.jsonl"
    trace_path.write_text(
        json.dumps(
            {
                "prompt": "what's the weather today in minneapolis",
                "query": "weather today minneapolis",
                "slice": "weather",
                "promoted_lane": "teacher_rescue",
                "improvement_delta": 1.0,
                "teacher_coaching": "Suggest they visit the weather.com link you found for current conditions.",
                "rescue_why_better": "Acknowledges the limitation while being more helpful by directing the user to the specific weather.com page.",
                "question_type": "weather_precipitation",
                "needed_fields": ["target_place", "target_period", "precipitation_chance", "rain_condition"],
                "promotion_notes": [
                    "Directs user to found weather source",
                    "More helpful than just stating limitation",
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    report = distill_web_policy_bank(trace_bank_path=str(trace_path))
    priors = suggest_web_policy_priors(
        prompt="what's the weather today in minneapolis",
        query="weather today minneapolis",
        slice_kind="weather",
        bank=report,
    )

    assert report["rows_used"] == 1
    assert "direct_to_found_source" in priors["behaviors"]
    assert "offer_actionable_next_step" in priors["behaviors"]
    assert "extract_weather_fact" in priors["behaviors"]


def test_run_web_overnight_loop_stops_after_target_and_writes_policy(monkeypatch, tmp_path):
    cases_path = tmp_path / "seed_cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "case_id": "seed_case",
                "prompt": "who is the ceo of anthropic",
                "expected_actions": ["browser_answer_query:who is the ceo of anthropic"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "memory_system.natural_terminal._compose_web_training_case_rows",
        lambda **kwargs: [
            {
                "case_id": "seed_case",
                "prompt": "who is the ceo of anthropic",
                "expected_actions": ["browser_answer_query:who is the ceo of anthropic"],
                "category": "seed",
                "source": "seed",
            },
            {
                "case_id": "generated_case",
                "prompt": "is it raining tomorrow in minneapolis",
                "expected_actions": [],
                "category": "weather",
                "source": "teacher_generated",
            },
        ],
    )

    benchmark_calls = {"count": 0}

    def fake_benchmark(**kwargs):
        benchmark_calls["count"] += 1
        if benchmark_calls["count"] == 1:
            return {
                "avg_teacher_overall": 3.2,
                "avg_answer_latency_ms": 22000.0,
                "answer_rate": 1.0,
            }
        return {
            "avg_teacher_overall": 4.4,
            "avg_answer_latency_ms": 16000.0,
            "answer_rate": 1.0,
        }

    monkeypatch.setattr("memory_system.natural_terminal.run_web_answer_benchmark", fake_benchmark)
    monkeypatch.setattr(
        "memory_system.natural_terminal.run_web_teacher_loop",
        lambda **kwargs: {
            "avg_promoted_overall": 4.5,
            "avg_baseline_overall": 3.5,
            "promoted_rescue_count": 0,
            "trace_row_count": 1,
            "trace_rows": [
                {
                    "case_id": "generated_case",
                    "prompt": "is it raining tomorrow in minneapolis",
                    "query": "is it raining tomorrow in minneapolis",
                    "slice": "weather",
                    "question_type": "weather_precipitation",
                    "needed_fields": ["target_place", "target_period", "precipitation_chance", "rain_condition"],
                    "baseline_answer": "Get accurate hourly forecasts...",
                    "baseline_overall": 2,
                    "baseline_relevant_chunk_ids": [],
                    "baseline_extracted_facts": [],
                    "rescued_answer": "Yes, light rain is expected tomorrow in Minneapolis.",
                    "rescued_overall": 5,
                    "rescued_relevant_chunk_ids": ["s1c2"],
                    "rescued_extracted_facts": ["light rain expected"],
                    "promoted_answer": "Yes, light rain is expected tomorrow in Minneapolis.",
                    "promoted_lane": "teacher_rescue",
                    "improvement_delta": 3.0,
                    "teacher_coaching": "Use the forecast chunk directly.",
                    "rescue_why_better": "It answers the user's actual question.",
                    "promotion_notes": ["prefer direct forecast facts"],
                    "source_title": "Weather Forecast and Conditions for Minneapolis",
                    "source_url": "https://example.com/weather",
                    "source_count": 1,
                    "evidence_chunk_count": 2,
                }
            ],
        },
    )

    monkeypatch.setattr(
        "memory_system.natural_terminal.distill_web_policy_bank",
        lambda trace_bank_path, min_improvement=0.0: {
            "rows_used": 1,
            "slice_counts": {"weather": 1},
            "token_counts": {"minneapolis": 1},
            "token_behavior_weights": {"minneapolis": {"extract_weather_fact": 1.0}},
            "token_note_weights": {},
            "behavior_examples": {"extract_weather_fact": ["Use the forecast chunk directly."]},
        },
    )

    report = run_web_overnight_loop(
        out_dir=str(tmp_path / "overnight"),
        seed_cases_path=str(cases_path),
        question_count=2,
        memla_model="claude-sonnet-4-20250514",
        memla_provider="anthropic",
        teacher_model="claude-sonnet-4-20250514",
        teacher_provider="anthropic",
        judge_model="claude-sonnet-4-20250514",
        judge_provider="anthropic",
        max_rounds=3,
        target_overall=4.25,
        allowed_rescues=0,
        repo_root=str(tmp_path / "repo"),
    )

    assert report["stop_reason"] == "target_reached"
    assert report["question_count_actual"] == 2
    assert report["best_score"] == 4.4
    assert Path(report["cases_path"]).exists()
    assert Path(report["combined_trace_bank"]).exists()
    assert Path(report["policy_bank_path"]).exists()


def test_resolve_web_answer_applies_policy_priors_to_limitation(monkeypatch):
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "Weather Forecast and Conditions for Minneapolis, Minnesota 55450 | weather.com",
                "url": "https://weather.com/weather/today/l/minneapolis",
                "summary": "Weather.com Minneapolis page",
            }
        ],
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>Weather Forecast and Conditions for Minneapolis, Minnesota 55450 | weather.com</title>
            <meta name="description" content="Weather.com Minneapolis page" />
          </head>
          <body>
            <nav>today hourly ten day radar</nav>
          </body>
        </html>
        """,
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal.suggest_web_policy_priors",
        lambda **kwargs: {
            "matched_tokens": ["minneapolis", "slice:weather"],
            "behaviors": ["direct_to_found_source", "offer_actionable_next_step", "acknowledge_limits_plainly"],
            "teacher_notes": ["Direct the user to the found source"],
        },
    )

    payload = _resolve_web_answer(
        prompt="what's the weather today in minneapolis",
        query="weather today minneapolis",
    )

    assert "check Weather Forecast and Conditions for Minneapolis, Minnesota 55450 | weather.com directly" in payload["answer"]
    assert "direct_to_found_source" in payload["answer_style"]["policy_behaviors"]


def test_terminal_heuristic_plan_opens_second_source_after_web_answer():
    state = BrowserSessionState(
        current_url="https://example.com/ai-agents",
        page_kind="web_page",
        search_engine="web",
        search_query="ai agents news today",
        result_cards=[
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and launches are accelerating in the AI agents space.",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="open the second source",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == ["open_search_result"]
    assert plan.actions[0].resolved_target == "2"


def test_terminal_heuristic_plan_compares_web_sources_after_answer():
    state = BrowserSessionState(
        current_url="https://example.com/ai-agents",
        page_kind="web_page",
        search_engine="web",
        search_query="ai agents news today",
        result_cards=[
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and launches are accelerating in the AI agents space.",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="compare the first and second source for which is more complete",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == ["browser_compare_cards"]
    assert plan.actions[0].resolved_target == "1,2"


def test_terminal_execute_plan_opens_second_source_after_web_answer(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    state = BrowserSessionState(
        current_url="https://example.com/ai-agents",
        page_kind="web_page",
        search_engine="web",
        search_query="ai agents news today",
        result_cards=[
            {
                "index": 1,
                "title": "AI agents today",
                "url": "https://example.com/ai-agents",
                "summary": "AI agents are getting more capable across coding and commerce workflows.",
            },
            {
                "index": 2,
                "title": "AI agents funding",
                "url": "https://example.com/ai-agents-funding",
                "summary": "Funding and launches are accelerating in the AI agents space.",
            },
        ],
    )
    plan = TerminalPlan(
        prompt="open the second source",
        source="heuristic",
        actions=[TerminalAction(kind="open_search_result", target="2", resolved_target="2")],
    )

    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert launched == [["xdg-open", "https://example.com/ai-agents-funding"]]
    assert result.browser_state["current_url"] == "https://example.com/ai-agents-funding"
    assert result.browser_state["search_query"] == "ai agents news today"
    assert len(result.browser_state["result_cards"]) == 2


def test_terminal_execute_plan_ranks_and_compares_cards():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu",
            },
        ],
    )

    rank_plan = build_terminal_plan(
        prompt="which repo best matches a beginner local llm workflow on a laptop",
        heuristic_only=True,
        browser_state=state,
    )
    cpp_rank_plan = build_terminal_plan(
        prompt="rank these repos for local c++ inference on weak hardware",
        heuristic_only=True,
        browser_state=state,
    )
    compare_plan = build_terminal_plan(
        prompt="compare the first and second repo for c++ llm inference on cpu",
        heuristic_only=True,
        browser_state=state,
    )

    rank_result = execute_terminal_plan(rank_plan, browser_state=state)
    cpp_rank_result = execute_terminal_plan(cpp_rank_plan, browser_state=state)
    compare_result = execute_terminal_plan(compare_plan, browser_state=state)

    assert rank_result.records[0].details["best_title"] == "ollama/ollama"
    assert cpp_rank_result.records[0].details["best_title"] == "ggml-org/llama.cpp"
    assert compare_result.records[0].details["winner_title"] == "ggml-org/llama.cpp"


def test_terminal_heuristic_plan_chains_rank_then_youtube_subject_search():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == ["browser_rank_cards", "browser_search_subject"]
    assert json.loads(plan.actions[1].note)["engine"] == "youtube"


def test_terminal_heuristic_plan_chains_rank_search_and_open_video():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it and open the first one",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == ["browser_rank_cards", "browser_search_subject", "open_search_result"]


def test_terminal_heuristic_plan_chains_rank_search_open_and_read_video():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it and open the first one and summarize it",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == [
        "browser_rank_cards",
        "browser_search_subject",
        "open_search_result",
        "browser_read_page",
    ]


def test_terminal_heuristic_plan_searches_youtube_for_current_repo():
    state = BrowserSessionState(
        current_url="https://github.com/ggml-org/llama.cpp",
        page_kind="repo_page",
    )

    plan = build_terminal_plan(
        prompt="find a youtube video about this repo",
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == ["browser_search_subject"]
    assert plan.actions[0].resolved_target == "youtube"


def test_terminal_execute_plan_rank_then_search_subject(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_search_result_cards",
        lambda engine, query, limit=5: [
            {
                "index": 1,
                "title": "llama.cpp walkthrough",
                "url": "https://www.youtube.com/watch?v=demo",
                "summary": "A walkthrough of llama.cpp.",
                "meta": "video",
            }
        ]
        if engine == "youtube"
        else [],
    )

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )
    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it",
        heuristic_only=True,
        browser_state=state,
    )

    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.records[0].details["best_title"] == "ggml-org/llama.cpp"
    assert result.records[1].details["subject_title"] == "ggml-org/llama.cpp"
    assert result.browser_state["search_engine"] == "youtube"
    assert result.browser_state["search_query"] == "ggml org llama cpp"
    assert result.browser_state["subject_title"] == "ggml-org/llama.cpp"
    assert launched[-1] == [
        "xdg-open",
        "https://www.youtube.com/results?search_query=ggml+org+llama+cpp",
    ]


def test_terminal_execute_plan_rank_search_and_open_subject_result(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    def fake_cards(engine, query, limit=5):
        if engine == "youtube":
            return [
                {
                    "index": 1,
                    "title": "llama.cpp CPU inference walkthrough",
                    "url": "https://www.youtube.com/watch?v=llama-cpp-cpu",
                    "summary": "A walkthrough of llama.cpp on CPU.",
                    "meta": "youtube | c++ | cpu",
                }
            ]
        return []

    monkeypatch.setattr("memory_system.natural_terminal._fetch_search_result_cards", fake_cards)

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it and open the first one",
        heuristic_only=True,
        browser_state=state,
    )
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.browser_state["page_kind"] == "video_page"
    assert result.browser_state["current_url"] == "https://www.youtube.com/watch?v=llama-cpp-cpu"
    assert result.browser_state["subject_title"] == "llama.cpp CPU inference walkthrough"
    assert launched[-1] == ["xdg-open", "https://www.youtube.com/watch?v=llama-cpp-cpu"]


def test_terminal_execute_plan_rank_search_open_and_read_subject_result(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    def fake_cards(engine, query, limit=5):
        if engine == "youtube":
            return [
                {
                    "index": 1,
                    "title": "llama.cpp CPU inference walkthrough",
                    "url": "https://www.youtube.com/watch?v=llama-cpp-cpu",
                    "summary": "A walkthrough of llama.cpp on CPU.",
                    "meta": "youtube | c++ | cpu",
                }
            ]
        return []

    monkeypatch.setattr("memory_system.natural_terminal._fetch_search_result_cards", fake_cards)
    monkeypatch.setattr(
        "memory_system.natural_terminal._fetch_page_html",
        lambda url: """
        <html>
          <head>
            <title>llama.cpp CPU inference walkthrough</title>
            <meta property=\"og:description\" content=\"A walkthrough of llama.cpp running LLM inference efficiently on CPU hardware.\" />
            <meta itemprop=\"channelId\" content=\"Local LLM Lab\" />
          </head>
        </html>
        """,
    )

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt="find the best repo for c++ llm inference on cpu then find a youtube video about it and open the first one and summarize it",
        heuristic_only=True,
        browser_state=state,
    )
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.records[-1].kind == "browser_read_page"
    assert result.records[-1].details["title"] == "llama.cpp CPU inference walkthrough"
    assert result.records[-1].details["summary"] == "A walkthrough of llama.cpp running LLM inference efficiently on CPU hardware."


def test_terminal_heuristic_plan_chains_youtube_then_reddit_about_same_subject():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then find a reddit post about it "
            "then open the first one and explain it"
        ),
        heuristic_only=True,
        browser_state=state,
    )

    assert [action.kind for action in plan.actions] == [
        "browser_rank_cards",
        "browser_search_subject",
        "open_search_result",
        "browser_read_page",
        "browser_search_subject",
        "open_search_result",
        "browser_read_page",
    ]
    assert json.loads(plan.actions[1].note)["engine"] == "youtube"
    assert json.loads(plan.actions[4].note)["engine"] == "reddit"


def test_terminal_execute_plan_carries_research_subject_from_youtube_to_reddit(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    def fake_cards(engine, query, limit=5):
        if engine == "youtube":
            return [
                {
                    "index": 1,
                    "title": "llama.cpp CPU inference walkthrough",
                    "url": "https://www.youtube.com/watch?v=llama-cpp-cpu",
                    "summary": "A walkthrough of llama.cpp on CPU.",
                    "meta": "youtube | c++ | cpu",
                }
            ]
        if engine == "reddit":
            return [
                {
                    "index": 1,
                    "title": "Best way to use llama.cpp on weak hardware?",
                    "url": "https://www.reddit.com/r/LocalLLaMA/comments/llama_cpp_weak_hw",
                    "summary": "Discussion of llama.cpp on laptops and CPU-only boxes.",
                    "meta": "reddit | weak hardware | cpu",
                }
            ]
        return []

    monkeypatch.setattr("memory_system.natural_terminal._fetch_search_result_cards", fake_cards)

    def fake_html(url):
        if "youtube.com/watch" in url:
            return """
            <html>
              <head>
                <title>llama.cpp CPU inference walkthrough</title>
                <meta property=\"og:description\" content=\"A walkthrough of llama.cpp running LLM inference efficiently on CPU hardware.\" />
                <meta itemprop=\"channelId\" content=\"Local LLM Lab\" />
              </head>
            </html>
            """
        return """
        <html>
          <head>
            <title>Best way to use llama.cpp on weak hardware?</title>
            <meta property=\"og:description\" content=\"Reddit discussion about using llama.cpp on laptops and CPU-only systems.\" />
          </head>
          <body>
            <a href=\"/r/LocalLLaMA\">r/LocalLLaMA</a>
          </body>
        </html>
        """

    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", fake_html)

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then find a reddit post about it "
            "then open the first one and explain it"
        ),
        heuristic_only=True,
        browser_state=state,
    )
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.browser_state["page_kind"] == "post_page"
    assert result.browser_state["search_engine"] == "reddit"
    assert result.browser_state["search_query"] == "ggml org llama cpp"
    assert result.browser_state["subject_title"] == "Best way to use llama.cpp on weak hardware?"
    assert result.browser_state["research_subject_title"] == "ggml-org/llama.cpp"
    assert result.records[-1].details["title"] == "Best way to use llama.cpp on weak hardware?"
    assert launched[-1] == ["xdg-open", "https://www.reddit.com/r/LocalLLaMA/comments/llama_cpp_weak_hw"]


def test_terminal_heuristic_plan_retries_weak_subject_result_before_reddit():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then if the first one seems weak open a better one and summarize it "
            "then find a reddit post about it then open the first one and explain it"
        ),
        heuristic_only=True,
        browser_state=state,
    )

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
    ]


def test_terminal_execute_plan_recovers_to_better_subject_result(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    def fake_cards(engine, query, limit=5):
        if engine == "youtube":
            return [
                {
                    "index": 1,
                    "title": "Local AI news roundup",
                    "url": "https://www.youtube.com/watch?v=local-ai-news",
                    "summary": "A generic local AI roundup with little llama.cpp CPU guidance.",
                    "meta": "youtube | roundup | generic",
                },
                {
                    "index": 2,
                    "title": "llama.cpp CPU inference walkthrough",
                    "url": "https://www.youtube.com/watch?v=llama-cpp-cpu",
                    "summary": "A walkthrough of llama.cpp running LLM inference on CPU.",
                    "meta": "youtube | c++ | cpu | inference",
                },
            ]
        if engine == "reddit":
            return [
                {
                    "index": 1,
                    "title": "Best way to use llama.cpp on weak hardware?",
                    "url": "https://www.reddit.com/r/LocalLLaMA/comments/llama_cpp_weak_hw",
                    "summary": "Discussion of llama.cpp on laptops and CPU-only boxes.",
                    "meta": "reddit | weak hardware | cpu",
                }
            ]
        return []

    monkeypatch.setattr("memory_system.natural_terminal._fetch_search_result_cards", fake_cards)

    def fake_html(url):
        if "local-ai-news" in url:
            return """
            <html><head>
            <title>Local AI news roundup</title>
            <meta property=\"og:description\" content=\"A generic local AI roundup with little llama.cpp CPU guidance.\" />
            <meta itemprop=\"channelId\" content=\"Local Model News\" />
            </head></html>
            """
        if "youtube.com/watch" in url:
            return """
            <html><head>
            <title>llama.cpp CPU inference walkthrough</title>
            <meta property=\"og:description\" content=\"A walkthrough of llama.cpp running LLM inference efficiently on CPU hardware.\" />
            <meta itemprop=\"channelId\" content=\"Local LLM Lab\" />
            </head></html>
            """
        return """
        <html><head>
        <title>Best way to use llama.cpp on weak hardware?</title>
        <meta property=\"og:description\" content=\"Reddit discussion about using llama.cpp on laptops and CPU-only systems.\" />
        </head><body><a href=\"/r/LocalLLaMA\">r/LocalLLaMA</a></body></html>
        """

    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", fake_html)

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then if the first one seems weak open a better one and summarize it "
            "then find a reddit post about it then open the first one and explain it"
        ),
        heuristic_only=True,
        browser_state=state,
    )
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.records[4].kind == "browser_retry_subject_result"
    assert result.records[4].details["selected_title"] == "llama.cpp CPU inference walkthrough"
    assert result.records[4].command == ["xdg-open", "https://www.youtube.com/watch?v=llama-cpp-cpu"]
    assert result.browser_state["page_kind"] == "post_page"
    assert result.browser_state["research_subject_title"] == "ggml-org/llama.cpp"


def test_terminal_heuristic_plan_chains_cross_source_synthesis():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then if the first one seems weak open a better one and summarize it "
            "then find a reddit post about it then open the first one and explain it "
            "then tell me which source best explains cpu inference on weak hardware"
        ),
        heuristic_only=True,
        browser_state=state,
    )

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


def test_terminal_heuristic_plan_chains_cross_source_synthesis_for_paraphrase():
    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c plus plus llm inference on cpu then grab a youtube vid on it "
            "then open the first one and sum it up then if that one seems weak pick a better one and sum it up "
            "then grab a reddit thread on it then open the first one and explain it "
            "then tell me which source best explains cpu inference on weak hardware"
        ),
        heuristic_only=True,
        browser_state=state,
    )

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


def test_terminal_execute_plan_synthesizes_cross_source_evidence(monkeypatch):
    launched: list[list[str]] = []

    class DummyProcess:
        def __init__(self, command, **kwargs):
            launched.append(list(command))

    monkeypatch.setattr("memory_system.natural_terminal.subprocess.Popen", DummyProcess)

    def fake_cards(engine, query, limit=5):
        if engine == "youtube":
            return [
                {
                    "index": 1,
                    "title": "Local AI news roundup",
                    "url": "https://www.youtube.com/watch?v=local-ai-news",
                    "summary": "A generic local AI roundup with little llama.cpp CPU guidance.",
                    "meta": "youtube | roundup | generic",
                },
                {
                    "index": 2,
                    "title": "llama.cpp CPU inference walkthrough",
                    "url": "https://www.youtube.com/watch?v=llama-cpp-cpu",
                    "summary": "A step-by-step walkthrough of llama.cpp CPU inference on weak hardware laptops.",
                    "meta": "youtube | c++ | cpu | weak hardware | walkthrough",
                },
            ]
        if engine == "reddit":
            return [
                {
                    "index": 1,
                    "title": "Best way to use llama.cpp on weak hardware?",
                    "url": "https://www.reddit.com/r/LocalLLaMA/comments/llama_cpp_weak_hw",
                    "summary": "Community discussion about using llama.cpp on laptops and CPU-only systems.",
                    "meta": "reddit | weak hardware | cpu | discussion",
                }
            ]
        return []

    monkeypatch.setattr("memory_system.natural_terminal._fetch_search_result_cards", fake_cards)

    def fake_html(url):
        if "local-ai-news" in url:
            return """
            <html><head>
            <title>Local AI news roundup</title>
            <meta property=\"og:description\" content=\"A generic local AI roundup with little llama.cpp CPU guidance.\" />
            <meta itemprop=\"channelId\" content=\"Local Model News\" />
            </head></html>
            """
        if "youtube.com/watch" in url:
            return """
            <html><head>
            <title>llama.cpp CPU inference walkthrough</title>
            <meta property=\"og:description\" content=\"A step-by-step walkthrough of llama.cpp CPU inference on weak hardware laptops.\" />
            <meta itemprop=\"channelId\" content=\"Local LLM Lab\" />
            </head></html>
            """
        return """
        <html><head>
        <title>Best way to use llama.cpp on weak hardware?</title>
        <meta property=\"og:description\" content=\"Community discussion about using llama.cpp on laptops and CPU-only systems.\" />
        </head><body><a href=\"/r/LocalLLaMA\">r/LocalLLaMA</a></body></html>
        """

    monkeypatch.setattr("memory_system.natural_terminal._fetch_page_html", fake_html)

    state = BrowserSessionState(
        current_url="https://github.com/search?q=local+llm&type=repositories",
        page_kind="search_results",
        search_engine="github",
        search_query="local llm",
        result_cards=[
            {
                "index": 1,
                "title": "ollama/ollama",
                "url": "https://github.com/ollama/ollama",
                "summary": "Simple CLI for local models on laptops.",
                "meta": "cli | beginner",
            },
            {
                "index": 2,
                "title": "ggml-org/llama.cpp",
                "url": "https://github.com/ggml-org/llama.cpp",
                "summary": "C/C++ inference runtime for CPUs.",
                "meta": "c++ | inference | cpu | portable",
            },
        ],
    )

    plan = build_terminal_plan(
        prompt=(
            "find the best repo for c++ llm inference on cpu then find a youtube video about it "
            "then open the first one and summarize it then if the first one seems weak open a better one and summarize it "
            "then find a reddit post about it then open the first one and explain it "
            "then tell me which source best explains cpu inference on weak hardware"
        ),
        heuristic_only=True,
        browser_state=state,
    )
    result = execute_terminal_plan(plan, platform_name="linux", browser_state=state)

    assert result.ok is True
    assert result.records[-1].kind == "browser_synthesize_evidence"
    assert result.records[-1].details["best_source_title"] == "llama.cpp CPU inference walkthrough"
    assert result.records[-1].details["best_source_kind"] == "video_page"
    assert result.records[-1].details["source_count"] >= 3
    assert "weak hardware" in result.records[-1].details["synthesis"].lower()


def test_execute_terminal_step_logs_trace(monkeypatch, tmp_path):
    state_path = tmp_path / "browser_state.json"
    trace_path = tmp_path / "trace.jsonl"
    save_browser_session_state(
        BrowserSessionState(
            current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
            page_kind="search_results",
            search_engine="youtube",
            search_query="lo fi hip hop",
        ),
        state_path,
    )

    report = build_terminal_step_report(
        prompt="now click the first vid",
        heuristic_only=True,
        browser_state=BrowserSessionState(
            current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
            page_kind="search_results",
            search_engine="youtube",
            search_query="lo fi hip hop",
        ),
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal.execute_terminal_plan",
        lambda plan, **kwargs: TerminalExecutionResult(
            prompt=plan.prompt,
            plan_source=plan.source,
            ok=True,
            records=[TerminalExecutionRecord(kind="open_search_result", target="1", status="ok", message="Opened result.")],
        ),
    )

    execution = execute_terminal_step(
        report,
        choice="1",
        state_path=state_path,
        trace_path=trace_path,
    )

    assert execution.result.ok is True
    assert execution.chosen_candidate.candidate_id == "prompt_plan"
    lines = trace_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["chosen_candidate_id"] == "prompt_plan"
    assert payload["execution"]["ok"] is True


def test_memla_terminal_plan_json_outputs_structured_plan(monkeypatch, capsys):
    timeline = iter([0.0, 0.25])
    monkeypatch.setattr("memory_system.cli.time.perf_counter", lambda: next(timeline))
    rc = main(
        [
            "terminal",
            "plan",
            "--prompt",
            "open chrome and spotify",
            "--heuristic-only",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "heuristic"
    assert [action["resolved_target"] for action in payload["actions"]] == ["chrome", "spotify"]
    assert payload["planning_duration_seconds"] == 0.25


def test_memla_terminal_plan_without_memla_uses_raw_model(monkeypatch, capsys):
    monkeypatch.setattr(
        "memory_system.cli.build_raw_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="raw_model",
            actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")],
        ),
    )
    monkeypatch.setattr(
        "memory_system.cli.build_terminal_plan",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("memla plan path should not run")),
    )

    rc = main(
        [
            "terminal",
            "plan",
            "open",
            "chrome",
            "--without-memla",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["source"] == "raw_model"
    assert payload["actions"][0]["resolved_target"] == "chrome"


def test_memla_terminal_run_json_outputs_execution(monkeypatch, capsys):
    plan = TerminalPlan(prompt="open chrome", source="heuristic", actions=build_terminal_plan(prompt="open chrome", heuristic_only=True).actions)
    timeline = iter([1.0, 1.2, 1.2, 1.35])

    monkeypatch.setattr("memory_system.cli.build_terminal_plan", lambda **kwargs: plan)
    monkeypatch.setattr("memory_system.cli.time.perf_counter", lambda: next(timeline))
    monkeypatch.setattr(
        "memory_system.cli.execute_terminal_plan",
        lambda current_plan, **kwargs: TerminalExecutionResult(
            prompt=current_plan.prompt,
            plan_source=current_plan.source,
            ok=True,
            records=[
                TerminalExecutionRecord(
                    kind="launch_app",
                    target="chrome",
                    status="ok",
                    message="Launched chrome.",
                    command=["/usr/bin/google-chrome"],
                )
            ],
        ),
    )

    rc = main(
        [
            "terminal",
            "run",
            "--prompt",
            "open chrome",
            "--heuristic-only",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["records"][0]["command"] == ["/usr/bin/google-chrome"]
    assert payload["planning_duration_seconds"] == 0.2
    assert payload["execution_duration_seconds"] == 0.15
    assert payload["total_duration_seconds"] == 0.35


def test_memla_terminal_run_without_memla_executes_raw_plan(monkeypatch, capsys):
    plan = TerminalPlan(
        prompt="open chrome",
        source="raw_model",
        actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")],
    )

    monkeypatch.setattr("memory_system.cli.build_raw_terminal_plan", lambda **kwargs: plan)
    monkeypatch.setattr(
        "memory_system.cli.build_terminal_plan",
        lambda **kwargs: (_ for _ in ()).throw(AssertionError("memla plan path should not run")),
    )
    monkeypatch.setattr(
        "memory_system.cli.execute_terminal_plan",
        lambda current_plan, **kwargs: TerminalExecutionResult(
            prompt=current_plan.prompt,
            plan_source=current_plan.source,
            ok=True,
            records=[
                TerminalExecutionRecord(
                    kind="launch_app",
                    target="chrome",
                    status="ok",
                    message="Launched chrome.",
                    command=["/usr/bin/google-chrome"],
                )
            ],
        ),
    )

    rc = main(
        [
            "terminal",
            "run",
            "open",
            "chrome",
            "--without-memla",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["plan_source"] == "raw_model"
    assert payload["records"][0]["command"] == ["/usr/bin/google-chrome"]


def test_memla_terminal_step_json_outputs_candidates(monkeypatch, capsys):
    timeline = iter([3.0, 3.25])
    monkeypatch.setattr("memory_system.cli.time.perf_counter", lambda: next(timeline))
    monkeypatch.setattr(
        "memory_system.cli.build_terminal_step_report",
        lambda **kwargs: build_terminal_step_report(
            prompt=kwargs["prompt"],
            heuristic_only=True,
            browser_state=BrowserSessionState(
                current_url="https://www.youtube.com/results?search_query=lo+fi+hip+hop",
                page_kind="search_results",
                search_engine="youtube",
                search_query="lo fi hip hop",
            ),
        ),
    )

    rc = main(
        [
            "terminal",
            "step",
            "now",
            "click",
            "the",
            "first",
            "vid",
            "--heuristic-only",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["constraints"]["page_kind"] == "search_results"
    assert payload["candidates"][0]["recommended"] is True
    assert payload["planning_duration_seconds"] == 0.25


def test_memla_terminal_step_choice_executes_candidate(monkeypatch, capsys, tmp_path):
    timeline = iter([5.0, 5.2, 5.2, 5.35])
    report = build_terminal_step_report(
        prompt="what is this repo",
        heuristic_only=True,
        browser_state=BrowserSessionState(
            current_url="https://github.com/ggml-org/llama.cpp",
            page_kind="repo_page",
        ),
    )
    monkeypatch.setattr("memory_system.cli.time.perf_counter", lambda: next(timeline))
    monkeypatch.setattr("memory_system.cli.build_terminal_step_report", lambda **kwargs: report)
    monkeypatch.setattr(
        "memory_system.cli.execute_terminal_step",
        lambda current_report, **kwargs: type(
            "DummyExecution",
            (),
            {
                "report": current_report,
                "chosen_candidate": current_report.candidates[0],
                "result": TerminalExecutionResult(
                    prompt=current_report.prompt,
                    plan_source=current_report.candidates[0].plan.source,
                    ok=True,
                    records=[TerminalExecutionRecord(kind="browser_read_page", target="current_page", status="ok", message="Read page.")],
                ),
                "trace_path": str(tmp_path / "trace.jsonl"),
            },
        )(),
    )

    rc = main(
        [
            "terminal",
            "step",
            "what",
            "is",
            "this",
            "repo",
            "--heuristic-only",
            "--choice",
            "1",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["chosen_candidate"]["candidate_id"] == "prompt_plan"
    assert payload["result"]["ok"] is True
    assert payload["planning_duration_seconds"] == 0.2
    assert payload["execution_duration_seconds"] == 0.15
    assert payload["total_duration_seconds"] == 0.35


def test_memla_terminal_workbench_invokes_server(monkeypatch, capsys):
    captured: dict[str, object] = {}

    def fake_serve_terminal_workbench(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("memory_system.cli.serve_terminal_workbench", fake_serve_terminal_workbench)

    rc = main(
        [
            "terminal",
            "workbench",
            "--host",
            "127.0.0.1",
            "--port",
            "8766",
            "--heuristic-only",
            "--model",
            "phi3:mini",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "Serving Memla browser workbench at http://127.0.0.1:8766" in out
    assert captured["host"] == "127.0.0.1"
    assert captured["port"] == 8766
    assert captured["heuristic_only"] is True
    assert captured["model"] == "phi3:mini"


def test_memla_terminal_compare_json_outputs_raw_and_memla(monkeypatch, capsys):
    timeline = iter([2.0, 4.0, 4.0, 4.5])

    monkeypatch.setattr(
        "memory_system.cli.build_raw_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="raw_model",
            actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")],
        ),
    )
    monkeypatch.setattr(
        "memory_system.cli.build_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[
                TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome"),
                TerminalAction(kind="launch_app", target="spotify", resolved_target="spotify"),
            ],
        ),
    )
    monkeypatch.setattr("memory_system.cli.time.perf_counter", lambda: next(timeline))

    rc = main(
        [
            "terminal",
            "compare",
            "--prompt",
            "open chrome and spotify",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["raw"]["source"] == "raw_model"
    assert [action["resolved_target"] for action in payload["memla"]["actions"]] == ["chrome", "spotify"]
    assert payload["raw_duration_seconds"] == 2.0
    assert payload["memla_duration_seconds"] == 0.5
    assert payload["memla_speedup"] == 4.0


def test_memla_terminal_compare_accepts_positional_prompt(monkeypatch, capsys):
    monkeypatch.setattr(
        "memory_system.cli.build_raw_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="raw_model",
            actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")],
        ),
    )
    monkeypatch.setattr(
        "memory_system.cli.build_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[TerminalAction(kind="launch_app", target="spotify", resolved_target="spotify")],
        ),
    )

    rc = main(
        [
            "terminal",
            "compare",
            "open",
            "chrome",
            "and",
            "spotify",
            "--json",
        ]
    )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["prompt"] == "open chrome and spotify"


def test_terminal_benchmark_pack_loads_expected_cases():
    cases = load_terminal_benchmark_cases("cases/terminal_eval_cases.jsonl")

    assert {case.case_id for case in cases} == {
        "open_chrome",
        "open_chrome_and_spotify",
        "open_downloads",
        "open_github",
        "search_youtube_lofi",
        "search_github_llamacpp",
        "search_reddit_local_llm",
        "list_documents",
        "check_disk_usage",
        "show_battery",
        "open_vscode",
    }


def test_terminal_benchmark_reports_latency_and_heuristic_hits(monkeypatch, tmp_path):
    cases_path = tmp_path / "terminal_cases.jsonl"
    cases_path.write_text(
        "\n".join(
            [
                json.dumps({"case_id": "a", "prompt": "open chrome", "expected_actions": ["launch_app:chrome"]}),
                json.dumps({"case_id": "b", "prompt": "open downloads folder", "expected_actions": ["open_path:downloads"]}),
            ]
        ),
        encoding="utf-8",
    )

    class DummyClient:
        provider = "ollama"

    monkeypatch.setattr("memory_system.natural_terminal.build_llm_client", lambda **kwargs: DummyClient())
    monkeypatch.setattr(
        "memory_system.natural_terminal.build_raw_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="raw_model",
            actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")]
            if "chrome" in kwargs["prompt"]
            else [TerminalAction(kind="open_path", target="downloads", resolved_target="/tmp/Downloads")],
        ),
    )
    monkeypatch.setattr(
        "memory_system.natural_terminal.build_terminal_plan",
        lambda **kwargs: TerminalPlan(
            prompt=kwargs["prompt"],
            source="heuristic",
            actions=[TerminalAction(kind="launch_app", target="chrome", resolved_target="chrome")]
            if "chrome" in kwargs["prompt"]
            else [TerminalAction(kind="open_path", target="downloads", resolved_target="/tmp/Downloads")],
        ),
    )
    timeline = iter([0.0, 1.0, 1.0, 1.1, 2.0, 2.8, 2.8, 2.9])
    monkeypatch.setattr("memory_system.natural_terminal.time.perf_counter", lambda: next(timeline))

    report = run_terminal_benchmark(
        cases_path=str(cases_path),
        raw_model="phi3",
        memla_model="phi3",
    )

    assert report["cases"] == 2
    assert report["avg_raw_latency_ms"] == 900.0
    assert report["avg_memla_latency_ms"] == 100.0
    assert report["memla_vs_raw_speedup"] == 9.0
    assert report["memla_heuristic_hit_count"] == 2
    assert report["avg_memla_terminal_utility"] == 1.0


def test_memla_terminal_benchmark_writes_report_bundle(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(
        "memory_system.cli.run_terminal_benchmark",
        lambda **kwargs: {
            "avg_raw_latency_ms": 950.0,
            "avg_memla_latency_ms": 25.0,
            "memla_vs_raw_speedup": 38.0,
            "rows": [],
        },
    )
    monkeypatch.setattr(
        "memory_system.cli.render_terminal_benchmark_markdown",
        lambda report: "# Terminal Benchmark\n",
    )

    out_dir = tmp_path / "terminal_benchmark"
    rc = main(
        [
            "terminal",
            "benchmark",
            "--model",
            "phi3",
            "--out-dir",
            str(out_dir),
        ]
    )

    assert rc == 0
    assert (out_dir / "terminal_benchmark_report.json").exists()
    assert (out_dir / "terminal_benchmark_report.md").exists()
    out = capsys.readouterr().out
    assert "Wrote terminal benchmark JSON" in out
    assert "speedup 38.0x" in out
