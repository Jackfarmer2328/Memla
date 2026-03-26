from __future__ import annotations

from pathlib import Path

from memory_system.distillation.constraint_graph import (
    infer_constraint_tags,
    infer_file_roles,
    infer_prompt_roles,
    infer_repo_family,
    scan_repo_role_matches,
    summarize_constraint_trades,
    transmutation_specificity,
)
from memory_system.distillation.coding_log import CodingTraceLog
from memory_system.distillation.workflow_planner import build_workflow_plan, render_workflow_plan_block
from memory_system.memory.episode_log import EpisodeLog


def test_constraint_graph_infers_roles_and_trades():
    prompt = "Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic."

    roles = infer_prompt_roles(prompt)
    tags = infer_constraint_tags(prompt, ["src/App.jsx", "src/CheckoutReturnPage.jsx"], ["npm run build", "npm run lint"])
    trades = summarize_constraint_trades(sorted(tags))

    assert "checkout_return" in roles
    assert "payment_boundary" in roles
    assert "redirect_return_flow" in tags
    assert "payment_confirmation" in tags
    assert trades


def test_scan_repo_role_matches_surfaces_local_role_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "App.jsx").write_text("", encoding="utf-8")
    (tmp_path / "src" / "CheckoutReturnPage.jsx").write_text("", encoding="utf-8")
    (tmp_path / "src" / "PaymentForm.jsx").write_text("", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")

    matches = scan_repo_role_matches(
        str(tmp_path),
        "Fix the broken Stripe integration and update the checkout return page logic.",
        desired_roles={"checkout_return", "payment_boundary", "app_shell"},
    )

    paths = [item.path for item in matches]
    assert "src/CheckoutReturnPage.jsx" in paths[:3]
    assert "src/PaymentForm.jsx" in paths[:4]
    assert "src/App.jsx" in paths[:4]


def test_scan_repo_role_matches_ignores_artifact_results_and_prefers_python_targets(tmp_path):
    (tmp_path / "examples" / "testing" / "results" / "standard").mkdir(parents=True)
    (tmp_path / "guard").mkdir()
    (tmp_path / "tests" / "test_middleware").mkdir(parents=True)
    (tmp_path / "examples" / "main.py").write_text("", encoding="utf-8")
    (tmp_path / "examples" / "testing" / "results" / "standard" / "fastapi_guard_standard.json").write_text("{}", encoding="utf-8")
    (tmp_path / "guard" / "middleware.py").write_text("", encoding="utf-8")
    (tmp_path / "guard" / "models.py").write_text("", encoding="utf-8")
    (tmp_path / "tests" / "test_middleware" / "test_security_middleware.py").write_text("", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text("", encoding="utf-8")

    matches = scan_repo_role_matches(
        str(tmp_path),
        "Fix the security middleware request checks and update the model configuration.",
        desired_roles={"service_boundary", "contract_boundary", "dependency_manifest", "test_surface"},
    )

    paths = [item.path for item in matches]
    assert "guard/middleware.py" in paths[:3]
    assert "guard/models.py" in paths[:4]
    assert "tests/test_middleware/test_security_middleware.py" in paths[:5]
    assert all("examples/testing/results" not in path for path in paths)


def test_cross_repo_meta_cog_maps_foreign_trace_to_local_files(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    (repo_a / "web").mkdir(parents=True)
    (repo_b / "src").mkdir(parents=True)
    (repo_b / "src" / "App.jsx").write_text("", encoding="utf-8")
    (repo_b / "src" / "CheckoutReturnPage.jsx").write_text("", encoding="utf-8")
    (repo_b / "src" / "main.jsx").write_text("", encoding="utf-8")
    (repo_b / "package.json").write_text("{}", encoding="utf-8")

    db_path = tmp_path / "constraint_transfer.sqlite"
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
        coding_log.update_trace_artifacts(
            trace_id=trace_id,
            meta={
                "teacher_answer_commands": ["npm run build", "npm run lint"],
            },
        )

        candidates = coding_log.find_similar_accepted_traces(
            user_id="coder",
            repo_root=str(repo_b),
            task_text="Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic.",
            touched_files=[],
            limit=4,
        )
        assert candidates
        assert candidates[0].same_repo is False
        assert "checkout_return" in candidates[0].matched_roles
        assert "payment_confirmation" in candidates[0].matched_constraints

        summary = coding_log.summarize_workflow_priors(
            candidates,
            repo_root=str(repo_b),
            prompt="Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic.",
        )
        assert summary.suggested_files == []
        assert "npm run build" in summary.suggested_commands

        plan = build_workflow_plan(
            candidates=candidates,
            summary=summary,
            prompt="Refactor the booking confirmation flow to remove Stripe Elements and update the checkout return page logic.",
            repo_root=str(repo_b),
        )

        assert "src/CheckoutReturnPage.jsx" in plan.likely_files[:3]
        assert "src/App.jsx" in plan.likely_files[:4]
        assert "checkout_return" in plan.role_targets
        assert "payment_confirmation" in plan.constraint_tags
        assert plan.transmutations

        block = render_workflow_plan_block(plan)
        assert "Constraint tags:" in block
        assert "Transmutations:" in block
        assert "Role targets:" in block
    finally:
        log.close()


def test_constraint_graph_infers_repo_family_for_python_api_and_ts_web(tmp_path):
    py_repo = tmp_path / "py_repo"
    ts_repo = tmp_path / "ts_repo"
    py_repo.mkdir()
    ts_repo.mkdir()

    (py_repo / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi", "uvicorn", "sqlalchemy"]
""".strip(),
        encoding="utf-8",
    )
    (ts_repo / "package.json").write_text(
        """
{"dependencies":{"next":"14.0.0","react":"18.0.0","@trpc/client":"10.0.0","prisma":"5.0.0"}}
""".strip(),
        encoding="utf-8",
    )

    assert infer_repo_family(str(py_repo)) == "python_api"
    assert infer_repo_family(str(ts_repo)) == "ts_web_app"


def test_transmutation_specificity_prefers_concrete_domain_trade():
    generic = "Trade one implementation constraint for a more stable verified constraint."
    specific = "Trade permissive request flow for stricter authentication and session integrity."

    assert transmutation_specificity(specific) > transmutation_specificity(generic)
