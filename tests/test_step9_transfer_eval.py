from __future__ import annotations

import json

from memory_system.distillation.coding_log import CodingTraceLog
from memory_system.distillation.transfer_eval import run_transfer_eval
from memory_system.memory.episode_log import EpisodeLog


def test_transfer_eval_shows_cross_repo_lift(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    (repo_a / "web").mkdir(parents=True)
    (repo_b / "src").mkdir(parents=True)
    (repo_b / "src" / "App.jsx").write_text("", encoding="utf-8")
    (repo_b / "src" / "CheckoutReturnPage.jsx").write_text("", encoding="utf-8")
    (repo_b / "src" / "main.jsx").write_text("", encoding="utf-8")
    (repo_b / "package.json").write_text("{}", encoding="utf-8")

    db_path = tmp_path / "memla.sqlite"
    baseline_db_path = tmp_path / "empty.sqlite"
    cases_path = tmp_path / "cases.jsonl"
    cases_path.write_text(
        json.dumps(
            {
                "prompt": "Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic.",
                "expected_files": ["src/App.jsx", "src/CheckoutReturnPage.jsx"],
                "expected_commands": ["npm run build"],
            }
        )
        + "\n",
        encoding="utf-8",
    )

    log = EpisodeLog(db_path)
    try:
        coding_log = CodingTraceLog(log._conn)
        trace_id = coding_log.save_trace(
            session_id="sess_transfer",
            user_id="coder",
            provider="openai",
            model="teacher",
            repo_root=str(repo_a),
            task_text="Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic.",
            system_prompt="sys",
            messages=[],
            retrieved_chunk_ids=[],
            assistant_text="[Output] Move payment confirmation to the redirect return handler and keep the app shell in sync.",
            touched_files=["web/BookingConfirmation.tsx", "web/CheckoutReturnView.tsx"],
            tests=[{"command": "npm run build", "status": "passed"}],
        )
        coding_log.mark_feedback(trace_id=trace_id, is_positive=True)
    finally:
        log.close()

    report = run_transfer_eval(
        db_path=str(db_path),
        baseline_db_path=str(baseline_db_path),
        repo_root=str(repo_b),
        user_id="coder",
        cases_path=str(cases_path),
    )

    assert report["avg_memla_file_recall"] >= report["avg_baseline_file_recall"]
    assert report["avg_memla_command_recall"] >= report["avg_baseline_command_recall"]
    assert report["positive_command_transfer_cases"] >= 1
    assert report["rows"][0]["memla_source_trace_ids"]
    assert report["rows"][0]["memla_transmutations"]
