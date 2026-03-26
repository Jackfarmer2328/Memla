from __future__ import annotations

import json

from memory_system.distillation.git_history_cases import (
    GitCommitRecord,
    _diversify_records,
    _derive_expected_commands,
    _derive_expected_python_commands,
    _heuristic_prompt,
    _interesting_changed_files,
    build_git_eval_cases,
)
from memory_system.distillation.seed_runner import _extract_answer_commands, _extract_answer_files


def test_interesting_changed_files_filters_assets_and_lockfiles():
    paths = [
        "hotel-booking-app/public/logo.jpg",
        "hotel-booking-app/package-lock.json",
        "hotel-booking-app/src/App.jsx",
        "hotel-booking-app/src/index.css",
        "hotel-booking-app/package.json",
    ]
    result = _interesting_changed_files(paths, "hotel-booking-app")
    assert result == [
        "src/App.jsx",
        "src/index.css",
        "package.json",
    ]


def test_derive_expected_commands_uses_repo_scripts():
    package_json = {
        "scripts": {
            "build": "vite build",
            "lint": "eslint .",
        }
    }
    assert _derive_expected_commands(["src/App.jsx"], package_json) == [
        "npm run build",
        "npm run lint",
    ]
    assert _derive_expected_commands(["src/index.css"], package_json) == [
        "npm run build",
    ]


def test_derive_expected_python_commands_uses_pyproject_features():
    pyproject = {
        "project": {
            "optional-dependencies": {
                "dev": ["pytest", "ruff"],
            }
        },
        "tool": {
            "pytest": {"ini_options": {}},
            "ruff": {"line-length": 100},
        },
    }
    assert _derive_expected_python_commands(["guard/middleware.py"], pyproject) == [
        "pytest",
        "ruff check .",
    ]
    assert _derive_expected_python_commands(["pyproject.toml"], pyproject) == [
        "pytest",
    ]


def test_heuristic_prompt_falls_back_for_generic_subjects():
    prompt = _heuristic_prompt("changes", ["src/GuestInfoPage.jsx", "src/index.css"])
    assert "guest info page" in prompt.lower()


def test_build_git_eval_cases_splits_seed_and_unseen(monkeypatch, tmp_path):
    records = [
        GitCommitRecord(
            sha=f"sha-{idx}",
            subject="changes" if idx % 2 else f"Feature {idx}",
            changed_files=["src/App.jsx", "src/index.css"] if idx % 2 else ["src/GuestInfoPage.jsx"],
            diff_excerpt=["Improve layout", "Refine booking flow"],
        )
        for idx in range(6)
    ]

    monkeypatch.setattr(
        "memory_system.distillation.git_history_cases.load_commit_records",
        lambda **kwargs: records,
    )

    package_json_path = tmp_path / "package.json"
    package_json_path.write_text(
        json.dumps({"scripts": {"build": "vite build", "lint": "eslint ."}}),
        encoding="utf-8",
    )

    report = build_git_eval_cases(
        repo_root="unused",
        repo_subpath="hotel-booking-app",
        package_json_path=str(package_json_path),
        repo_label="hotel booking frontend",
        seed_count=2,
        unseen_count=3,
        recent_window=5,
        scan_limit=20,
        use_local_model=False,
    )

    assert report["seed_count"] == 2
    assert report["unseen_count"] == 3
    assert len(report["seed_cases"]) == 2
    assert len(report["unseen_cases"]) == 3
    assert report["seed_cases"][0]["commit_sha"] == "sha-1"
    assert report["unseen_cases"][-1]["commit_sha"] == "sha-5"
    assert report["seed_cases"][0]["expected_commands"] == ["npm run build", "npm run lint"]
    assert report["seed_cases"][0]["accept_strategy"] == "git_history_file_grounded"
    assert report["seed_cases"][0]["min_file_recall"] == 0.25
    assert report["seed_cases"][0]["attach_expected_commands"] is True


def test_build_git_eval_cases_supports_pyproject_manifests(monkeypatch, tmp_path):
    records = [
        GitCommitRecord(
            sha=f"sha-{idx}",
            subject=f"Feature {idx}",
            changed_files=["guard/middleware.py"] if idx % 2 else ["tests/test_middleware.py"],
            diff_excerpt=["Improve security middleware"],
        )
        for idx in range(5)
    ]

    monkeypatch.setattr(
        "memory_system.distillation.git_history_cases.load_commit_records",
        lambda **kwargs: records,
    )

    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(
        """
[project]
name = "fastapi_guard"

[project.optional-dependencies]
dev = ["pytest", "ruff"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
""".strip(),
        encoding="utf-8",
    )

    report = build_git_eval_cases(
        repo_root="unused",
        repo_subpath=".",
        manifest_path=str(pyproject_path),
        repo_label="fastapi guard",
        seed_count=2,
        unseen_count=2,
        recent_window=4,
        scan_limit=10,
        use_local_model=False,
    )

    assert report["seed_count"] == 2
    assert report["unseen_count"] == 2
    assert report["seed_cases"][0]["expected_commands"] == ["pytest", "ruff check ."]
    assert report["manifest_path"] == str(pyproject_path)
    assert report["seed_cases"][0]["accept_strategy"] == "git_history_file_grounded"


def test_diversify_records_limits_repetitive_single_file_runs():
    records = [
        GitCommitRecord(
            sha=f"sha-{idx}",
            subject="changes",
            changed_files=["src/GuestInfoPage.jsx"],
            diff_excerpt=["payment tweak"],
        )
        for idx in range(6)
    ] + [
        GitCommitRecord(
            sha="sha-app",
            subject="Update booking app shell",
            changed_files=["src/App.jsx", "src/index.css"],
            diff_excerpt=["layout update"],
        ),
        GitCommitRecord(
            sha="sha-booking",
            subject="Update booking page",
            changed_files=["src/BookingPage.jsx"],
            diff_excerpt=["booking update"],
        ),
    ]

    chosen = _diversify_records(records, 6)
    guest_only = [record for record in chosen if record.changed_files == ["src/GuestInfoPage.jsx"]]

    assert len(chosen) == 6
    assert len(guest_only) <= 4
    assert any(record.changed_files == ["src/BookingPage.jsx"] for record in chosen)


def test_seed_runner_extracts_frontend_files_and_npm_commands():
    answer = """
    Update `src/App.jsx`, `src/index.css`, and `package.json`.

    ```bash
    npm run build
    npm run lint
    ```
    """
    assert _extract_answer_files(answer) == [
        "src/App.jsx",
        "src/index.css",
        "package.json",
    ]
    assert _extract_answer_commands(answer) == [
        "npm run build",
        "npm run lint",
    ]


def test_seed_runner_extracts_python_commands():
    answer = """
    Update `guard/middleware.py` and `tests/test_middleware.py`.

    ```bash
    pytest
    ruff check .
    ```
    """
    assert _extract_answer_files(answer) == [
        "guard/middleware.py",
        "tests/test_middleware.py",
    ]
    assert _extract_answer_commands(answer) == [
        "pytest",
        "ruff check .",
    ]
