from memory_system.memory.ontology import (
    MEMORY_STAGE_RULE,
    MEMORY_STAGE_SEMANTIC,
    MEMORY_STATUS_INVALID,
    MEMORY_STATUS_STALE,
    adjudicate_memory_trace,
    decay_memory_traces,
    load_memory_ontology,
    promote_memory_rule,
    record_memory_trace,
    summarize_memory_ontology,
)


def test_memory_ontology_promotes_from_episodic_to_semantic_on_reuse(tmp_path):
    ontology_path = tmp_path / "terminal_memory_ontology.json"
    profile = {
        "page_kind": "repo_page",
        "search_engine": "",
        "has_search_results": False,
        "has_subject": True,
        "has_evidence": False,
    }
    action_signatures = ["browser_search_subject:youtube", "open_search_result:1"]

    record_memory_trace(
        prompt="pull some yt coverage on this repo and crack open the opener",
        normalized_prompt="pull some youtube coverage on this repo and open the first one",
        tokens=["youtube", "repo", "first"],
        context_profile=profile,
        action_signatures=action_signatures,
        source="language_model",
        path=ontology_path,
        canonical_clauses=["find a youtube video about this repo and open the first one"],
    )

    adjudicate_memory_trace(
        prompt="find a youtube video about this repo and open the first one",
        normalized_prompt="find a youtube video about this repo and open the first one",
        tokens=["youtube", "repo", "first"],
        context_profile=profile,
        action_signatures=action_signatures,
        source="language_memory",
        success=True,
        path=ontology_path,
    )
    adjudicate_memory_trace(
        prompt="grab a yt clip on this repo and crack open the opener",
        normalized_prompt="grab a youtube clip on this repo and open the first one",
        tokens=["youtube", "repo", "first"],
        context_profile=profile,
        action_signatures=action_signatures,
        source="language_memory",
        success=True,
        path=ontology_path,
    )

    entries = load_memory_ontology(ontology_path)
    assert len(entries) == 1
    assert entries[0]["promotion_stage"] == MEMORY_STAGE_SEMANTIC
    assert entries[0]["reuse_count"] == 2
    assert entries[0]["successful_reuse_count"] == 2


def test_memory_ontology_promotes_to_rule_and_can_invalidate_or_decay(tmp_path):
    ontology_path = tmp_path / "terminal_memory_ontology.json"
    profile = {
        "page_kind": "search_results",
        "search_engine": "github",
        "has_search_results": True,
        "has_subject": False,
        "has_evidence": False,
    }
    action_signatures = ["browser_rank_cards:current_cards"]

    record_memory_trace(
        prompt="sort out the repo that suits a beginner weak laptop setup",
        normalized_prompt="sort out the repo that suits a beginner weak laptop setup",
        tokens=["repo", "beginner", "laptop"],
        context_profile=profile,
        action_signatures=action_signatures,
        source="language_memory",
        path=ontology_path,
    )
    promote_memory_rule(
        prompt="sort out the repo that suits a beginner weak laptop setup",
        normalized_prompt="sort out the repo that suits a beginner weak laptop setup",
        tokens=["repo", "beginner", "laptop"],
        context_profile=profile,
        action_signatures=action_signatures,
        source="language_rule",
        path=ontology_path,
    )

    entries = load_memory_ontology(ontology_path)
    assert entries[0]["promotion_stage"] == MEMORY_STAGE_RULE

    invalidation_path = tmp_path / "invalid.json"
    record_memory_trace(
        prompt="find a reddit thread about it",
        normalized_prompt="find a reddit thread about it",
        tokens=["reddit", "thread"],
        context_profile=profile,
        action_signatures=["browser_search_subject:reddit"],
        source="language_memory",
        path=invalidation_path,
    )
    adjudicate_memory_trace(
        prompt="find a reddit thread about it",
        normalized_prompt="find a reddit thread about it",
        tokens=["reddit", "thread"],
        context_profile=profile,
        action_signatures=["browser_search_subject:reddit"],
        source="language_memory",
        success=False,
        path=invalidation_path,
    )
    adjudicate_memory_trace(
        prompt="find a reddit thread about it",
        normalized_prompt="find a reddit thread about it",
        tokens=["reddit", "thread"],
        context_profile=profile,
        action_signatures=["browser_search_subject:reddit"],
        source="language_memory",
        success=False,
        path=invalidation_path,
    )
    invalid_entries = load_memory_ontology(invalidation_path)
    assert invalid_entries[0]["status"] == MEMORY_STATUS_INVALID

    decay_path = tmp_path / "stale.json"
    record_memory_trace(
        prompt="pull some yt coverage on this repo",
        normalized_prompt="pull some youtube coverage on this repo",
        tokens=["youtube", "repo"],
        context_profile=profile,
        action_signatures=["browser_search_subject:youtube"],
        source="language_model",
        path=decay_path,
        now_ts=100,
    )
    decay_memory_traces(path=decay_path, now_ts=100 + (60 * 60 * 24 * 30))

    decay_entries = load_memory_ontology(decay_path)
    summary = summarize_memory_ontology(decay_path)

    assert decay_entries[0]["status"] == MEMORY_STATUS_STALE
    assert summary["stale_count"] == 1
    assert summary["memory_count"] == 1


def test_memory_ontology_v2_tracks_autonomy_trace_kinds(tmp_path):
    ontology_path = tmp_path / "terminal_memory_ontology.json"
    profile = {
        "page_kind": "search_results",
        "search_engine": "github",
        "has_search_results": True,
        "has_subject": True,
        "has_evidence": True,
    }
    action_signatures = [
        "scout_kind:github_repo_scout",
        "browser_extract_cards:github",
        "browser_rank_cards:initial",
        "browser_read_page:top_candidate",
        "browser_rank_cards:rerank",
    ]

    for prompt in (
        "find the top 10 github repos for local llms and tell me which best fits weak hardware",
        "scout the top github repos for local llms and bring back the best weak laptop option",
    ):
        adjudicate_memory_trace(
            prompt=prompt,
            normalized_prompt=prompt,
            tokens=["github", "repos", "local", "llms", "weak", "hardware"],
            context_profile=profile,
            action_signatures=action_signatures,
            source="autonomy_scout",
            success=True,
            path=ontology_path,
            memory_kind="autonomy_github_repo_scout",
            canonical_clauses=[
                "scout github repositories",
                "rank candidates against the goal",
                "inspect top candidates",
                "rerank and return a report",
            ],
        )

    entries = load_memory_ontology(ontology_path)
    summary = summarize_memory_ontology(ontology_path)

    assert len(entries) == 1
    assert entries[0]["memory_kind"] == "autonomy_github_repo_scout"
    assert entries[0]["promotion_stage"] == MEMORY_STAGE_SEMANTIC
    assert entries[0]["successful_reuse_count"] == 2
    assert summary["autonomy_count"] == 1
    assert summary["kind_counts"]["autonomy_github_repo_scout"] == 1
