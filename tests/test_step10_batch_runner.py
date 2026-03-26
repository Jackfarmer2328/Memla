from __future__ import annotations

import json
from pathlib import Path
from urllib.error import URLError

from memory_system.distillation.batch_runner import (
    _assert_ollama_available,
    _count_transmutations,
    _effective_seed_threshold,
    _progress_line,
    load_repo_curriculum,
    render_batch_markdown,
)


def test_load_repo_curriculum_reads_enabled_and_defaults(tmp_path):
    config_path = tmp_path / "curriculum.json"
    config_path.write_text(
        json.dumps(
            {
                "repos": [
                    {
                        "id": "alpha",
                        "url": "https://github.com/example/alpha",
                        "repo_label": "alpha repo",
                        "enabled": True,
                    },
                    {
                        "url": "https://github.com/example/beta",
                        "enabled": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    specs = load_repo_curriculum(str(config_path))

    assert len(specs) == 2
    assert specs[0].id == "alpha"
    assert specs[0].repo_label == "alpha repo"
    assert specs[0].seed_count == 8
    assert specs[1].id == "beta"
    assert specs[1].enabled is False


def test_count_transmutations_aggregates_rows():
    report = {
        "rows": [
            {"memla_transmutations": ["Trade A for B.", "Trade C for D."]},
            {"memla_transmutations": ["Trade A for B."]},
            {"memla_transmutations": []},
        ]
    }

    counts = _count_transmutations(report)

    assert counts["Trade A for B."] == 2
    assert counts["Trade C for D."] == 1


def test_render_batch_markdown_includes_repo_metrics_and_transmutations():
    summary = {
        "teacher_model": "qwen3.5:9b",
        "case_model": "qwen3.5:4b",
        "repos_attempted": 2,
        "repos_with_holdouts": 1,
        "min_seed_accept": 4,
        "default_seed_count": 8,
        "results": [
            {
                "id": "alpha",
                "repo_label": "alpha repo",
                "tier": "tier1",
                "status": "completed",
                "seed_cases": 8,
                "seed_accepted": 5,
                "seed_avg_file_recall": 0.5,
                "seed_avg_command_recall": 0.25,
                "avg_raw_file_recall": 0.2,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.6,
                "avg_memla_combined_command_recall": 0.5,
                "notes": "great fit",
            },
            {
                "id": "beta",
                "repo_label": "beta repo",
                "tier": "tier2",
                "status": "skipped_low_seed_signal",
                "seed_cases": 8,
                "seed_accepted": 3,
                "seed_avg_file_recall": 0.2,
                "seed_avg_command_recall": 0.1,
                "avg_raw_file_recall": 0.0,
                "avg_raw_command_recall": 0.0,
                "avg_memla_combined_file_recall": 0.0,
                "avg_memla_combined_command_recall": 0.0,
                "notes": "",
            },
        ],
        "top_transmutations": [
            {"text": "Trade strict server routing for client-side SPA fallback.", "count": 3}
        ],
    }

    markdown = render_batch_markdown(summary)

    assert "# Memla Repo Curriculum Batch" in markdown
    assert "alpha" in markdown
    assert "`completed`" in markdown
    assert "`0.6`" in markdown
    assert "Trade strict server routing for client-side SPA fallback." in markdown


def test_progress_line_includes_ascii_bar_percent_and_repo_stage():
    line = _progress_line(
        progress_units=4.5,
        total_units=12,
        repo_index=2,
        repo_count=4,
        repo_id="cadwyn",
        stage="seed",
        detail="8 bootstrap cases",
    )

    assert "(=^.^=)" in line
    assert "%" in line
    assert "repo 2/4" in line
    assert "cadwyn" in line
    assert "seed" in line


def test_assert_ollama_available_raises_clear_message_when_down(monkeypatch):
    def fake_urlopen(*args, **kwargs):
        raise URLError("connection refused")

    monkeypatch.setattr("memory_system.distillation.batch_runner.urllib.request.urlopen", fake_urlopen)

    try:
        _assert_ollama_available("http://127.0.0.1:11435")
    except RuntimeError as exc:
        assert "Start `ollama serve` and retry." in str(exc)
    else:
        raise AssertionError("Expected preflight failure when Ollama is unavailable.")


def test_effective_seed_threshold_relaxes_for_structural_family_with_strong_role_recall():
    threshold, mode = _effective_seed_threshold(
        repo_family="python_api",
        min_seed_accept=4,
        seed_cases=8,
        seed_role_recall=0.5,
    )

    assert threshold == 3
    assert mode == "family_structural"


def test_effective_seed_threshold_uses_ratio_mode_for_tiny_repo_with_strong_roles():
    threshold, mode = _effective_seed_threshold(
        repo_family="ts_web_app",
        min_seed_accept=4,
        seed_cases=6,
        seed_role_recall=0.4,
    )

    assert threshold == 2
    assert mode == "tiny_ratio"


def test_effective_seed_threshold_stays_default_without_structural_signal():
    threshold, mode = _effective_seed_threshold(
        repo_family="ts_web_app",
        min_seed_accept=4,
        seed_cases=8,
        seed_role_recall=0.8,
    )

    assert threshold == 4
    assert mode == "default"
