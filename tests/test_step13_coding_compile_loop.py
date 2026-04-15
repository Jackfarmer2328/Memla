from __future__ import annotations

from memory_system.distillation.coding_compile_loop import compile_coding_hypotheses
from memory_system.distillation.constraint_graph import build_repo_map, build_repo_topology_graph, scan_repo_role_matches
from memory_system.distillation.coding_log import WorkflowPriorSummary
from memory_system.distillation.workflow_planner import build_workflow_plan, render_workflow_plan_block


def test_compile_loop_validates_supported_repo_commands_and_files(tmp_path):
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "api" / "v1" / "users").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "src" / "core" / "dependency.py").write_text(
        "class PermissionControl: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "src" / "api" / "v1" / "users" / "users.py").write_text(
        "from src.core.dependency import PermissionControl\nrouter = object()\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_permissions.py").write_text(
        "from src.core.dependency import PermissionControl\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115", "pytest>=8.0", "ruff>=0.6"]
""".strip(),
        encoding="utf-8",
    )

    prompt = "Tighten permission enforcement for protected user endpoints and keep the permission tests aligned."
    desired_roles = {"security_surface", "service_boundary", "test_surface"}
    repo_role_candidates = scan_repo_role_matches(str(tmp_path), prompt, desired_roles, limit=8)
    repo_map_regions = build_repo_map(
        str(tmp_path),
        prompt=prompt,
        predicted_constraints=["auth_session_integrity", "middleware_interception", "verification_gate"],
        desired_roles=desired_roles,
        limit=6,
    )
    repo_topology_graph = build_repo_topology_graph(
        str(tmp_path),
        prompt=prompt,
        desired_roles=desired_roles,
        limit=64,
        neighbor_limit=6,
    )

    compiled, validated = compile_coding_hypotheses(
        prompt=prompt,
        repo_root=str(tmp_path),
        repo_family="python_api",
        predicted_constraints=["auth_session_integrity", "middleware_interception", "verification_gate"],
        transmutations=[
            "Trade permissive request flow for stricter authentication and session integrity.",
            "Trade downstream flexibility for earlier middleware enforcement and validation.",
        ],
        role_targets=sorted(desired_roles),
        ruled_out_roles=[],
        ranked_files=[
            "tests/test_permissions.py",
            "src/api/v1/users/users.py",
            "src/core/dependency.py",
        ],
        likely_commands=["pytest.ini"],
        likely_tests=["pytest"],
        repo_role_candidates=repo_role_candidates,
        repo_map_regions=repo_map_regions,
        repo_topology_graph=repo_topology_graph,
        topology_anchor_files=["tests/test_permissions.py"],
        hypothesis_swarm=[
            {
                "label": "Security Sentinel",
                "score": 1.1,
                "predicted_constraints": ["auth_session_integrity", "verification_gate"],
                "predicted_roles": ["security_surface", "test_surface"],
                "predicted_transmutations": [
                    "Trade permissive request flow for stricter authentication and session integrity.",
                ],
                "probe_commands": ["pytest"],
            }
        ],
    )

    assert compiled
    assert validated
    assert "pytest" in validated["supporting_commands"]
    assert "verification_gap" not in validated["residual_constraints"]
    assert any(path.endswith("src/core/dependency.py") for path in validated["supporting_files"])


def test_compile_loop_emits_residuals_when_repo_support_is_missing(tmp_path):
    (tmp_path / "README.md").write_text("notes\n", encoding="utf-8")

    compiled, validated = compile_coding_hypotheses(
        prompt="Tighten command handling and keep validation strict.",
        repo_root=str(tmp_path),
        repo_family="general",
        predicted_constraints=["verification_gate"],
        transmutations=["Trade shell flexibility for a repeatable command-line workflow."],
        role_targets=["cli_surface"],
        ruled_out_roles=[],
        ranked_files=["README.md"],
        likely_commands=["pytest.ini"],
        likely_tests=[],
        repo_role_candidates=[],
        repo_map_regions=[],
        repo_topology_graph=[],
        topology_anchor_files=[],
        hypothesis_swarm=[],
    )

    assert compiled
    assert validated
    assert "verification_gap" in validated["residual_constraints"]
    assert "role_mapping_gap" in validated["residual_constraints"]


def test_workflow_plan_surfaces_validated_trade_path(tmp_path):
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "src" / "core" / "dependency.py").write_text(
        "class PermissionControl: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_permissions.py").write_text(
        "from src.core.dependency import PermissionControl\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115", "pytest>=8.0"]
""".strip(),
        encoding="utf-8",
    )
    summary = WorkflowPriorSummary(
        suggested_files=["tests/test_permissions.py", "src/core/dependency.py"],
        suggested_commands=["pytest.ini"],
        source_trace_ids=[11],
    )

    plan = build_workflow_plan(
        candidates=[],
        summary=summary,
        prompt="Keep permission enforcement strict and update the permission tests if the guard changes.",
        repo_root=str(tmp_path),
    )

    assert plan.compiled_hypotheses
    assert plan.validated_trade_path
    assert "pytest" in plan.likely_tests
    block = render_workflow_plan_block(plan)
    assert "Validated trade path:" in block
    assert "Validated commands:" in block


def test_workflow_plan_hides_unanchored_validated_trade_path(tmp_path):
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "tests").mkdir(parents=True)
    (tmp_path / "src" / "core" / "dependency.py").write_text(
        "class PermissionControl: ...\n",
        encoding="utf-8",
    )
    (tmp_path / "tests" / "test_permissions.py").write_text(
        "from src.core.dependency import PermissionControl\n",
        encoding="utf-8",
    )
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115", "pytest>=8.0"]
""".strip(),
        encoding="utf-8",
    )
    summary = WorkflowPriorSummary(
        suggested_files=["tests/test_permissions.py", "src/core/dependency.py"],
        suggested_commands=["pytest.ini"],
        source_trace_ids=[11],
    )

    plan = build_workflow_plan(
        candidates=[],
        summary=summary,
        prompt="Refresh the documentation and examples for the project architecture.",
        repo_root=str(tmp_path),
    )

    assert plan.compiled_hypotheses
    assert not plan.validated_trade_path
    block = render_workflow_plan_block(plan)
    assert "Validated trade path:" not in block
    assert "Validated commands:" not in block


def test_compile_loop_uses_prompt_direct_path_matches_for_structure_refactors(tmp_path):
    (tmp_path / "src" / "controllers").mkdir(parents=True)
    (tmp_path / "src" / "repositories").mkdir(parents=True)
    (tmp_path / "src" / "core").mkdir(parents=True)
    (tmp_path / "src" / "controllers" / "user.py").write_text("class UserController: ...\n", encoding="utf-8")
    (tmp_path / "src" / "repositories" / "user.py").write_text("class UserRepository: ...\n", encoding="utf-8")
    (tmp_path / "src" / "core" / "dependency.py").write_text("class PermissionControl: ...\n", encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
dependencies = ["fastapi>=0.115", "pytest>=8.0", "ruff>=0.6"]
""".strip(),
        encoding="utf-8",
    )

    compiled, validated = compile_coding_hypotheses(
        prompt="Refactor the project structure by renaming the controllers directory to repositories and updating all related imports.",
        repo_root=str(tmp_path),
        repo_family="python_api",
        predicted_constraints=["interface_contract_integrity"],
        transmutations=["Trade legacy path naming for a consistent repository structure."],
        role_targets=["service_boundary"],
        ruled_out_roles=[],
        ranked_files=["src/core/dependency.py"],
        likely_commands=["pytest"],
        likely_tests=["pytest"],
        repo_role_candidates=[],
        repo_map_regions=[],
        repo_topology_graph=[],
        topology_anchor_files=[],
        hypothesis_swarm=[],
    )

    assert compiled
    candidate_files = compiled[0]["candidate_files"]
    assert any(path.endswith("src/controllers/user.py") for path in candidate_files)
    assert any(path.endswith("src/repositories/user.py") for path in candidate_files)
