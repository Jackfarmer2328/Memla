from __future__ import annotations

import json

from memory_system.distillation.patch_execution_benchmark import (
    _candidate_local_bin_paths,
    _build_llm_client,
    _build_diagnostic_sheet,
    _build_patch_prompt,
    _build_retry_feedback_block,
    _classify_command_blockage,
    _compile_structured_edits_to_patch,
    _derive_active_repair_lesson,
    _derive_residual_constraints,
    _extract_diff_block,
    _extract_diagnostic_entries,
    _extract_json_object,
    _extract_patch_files,
    _filter_retry_target_paths,
    _lesson_applied,
    _merge_retry_context_paths,
    _prioritize_code_context_paths,
    _rank_allowed_structured_files,
    _run_expected_commands,
    _scan_prompt_candidate_files,
    _score_diff_overlap,
    _select_dependency_bootstrap_command,
    extract_technician_cases,
)


def test_build_llm_client_supports_github_models_env_fallback(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "gh-test-token")

    client = _build_llm_client(
        provider="github_models",
        base_url="https://models.github.ai/inference",
    )

    assert client.provider == "github_models"
    assert client.base_url == "https://models.github.ai/inference"
    assert client.api_key == "gh-test-token"


def test_build_llm_client_uses_ollama_host_when_base_url_missing(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.setenv("OLLAMA_HOST", "127.0.0.1:11435")

    client = _build_llm_client(
        provider="ollama",
    )

    assert client.provider == "ollama"
    assert client.base_url == "http://127.0.0.1:11435"


def test_extract_diff_block_from_fenced_answer():
    answer = """
Here is the fix.

```diff
diff --git a/src/index.ts b/src/index.ts
--- a/src/index.ts
+++ b/src/index.ts
@@ -1 +1 @@
-const value = "old"
+const value = "new"
```
""".strip()

    diff = _extract_diff_block(answer)

    assert diff.startswith("diff --git a/src/index.ts b/src/index.ts")
    assert 'const value = "new"' in diff


def test_extract_patch_files_reads_unified_diff_headers():
    diff = """
diff --git a/src/index.ts b/src/index.ts
--- a/src/index.ts
+++ b/src/index.ts
@@ -1 +1 @@
-const value = "old"
+const value = "new"
diff --git a/test/client_auth.test.ts b/test/client_auth.test.ts
--- a/test/client_auth.test.ts
+++ b/test/client_auth.test.ts
@@ -1 +1 @@
-expect(true).toBe(false)
+expect(true).toBe(true)
""".strip()

    files = _extract_patch_files(diff)

    assert files == ["src/index.ts", "test/client_auth.test.ts"]


def test_score_diff_overlap_rewards_matching_hunks():
    predicted = [
        'throw new TypeError("missing client_secret_jwt JWS alg")',
        "client_secret_jwt is required",
    ]
    expected = [
        'throw new TypeError("missing client_secret_jwt JWS alg")',
        "client_secret_jwt is required",
        "assert.throws(() => foo())",
    ]

    score = _score_diff_overlap(predicted, expected)

    assert round(score, 4) == 0.6667


def test_scan_prompt_candidate_files_prefers_prompt_named_paths(tmp_path):
    (tmp_path / "src" / "controllers").mkdir(parents=True)
    (tmp_path / "src" / "repositories").mkdir(parents=True)
    (tmp_path / "src" / "controllers" / "user.py").write_text("class UserController: ...\n", encoding="utf-8")
    (tmp_path / "src" / "repositories" / "user.py").write_text("class UserRepository: ...\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("docs\n", encoding="utf-8")

    paths = _scan_prompt_candidate_files(
        tmp_path,
        "Refactor the project structure by renaming the controllers directory to repositories and updating all related imports.",
        limit=4,
    )

    assert "src/controllers/user.py" in paths
    assert "src/repositories/user.py" in paths


def test_prioritize_code_context_paths_promotes_source_and_manifests(tmp_path):
    (tmp_path / "src").mkdir(parents=True)
    (tmp_path / "test").mkdir(parents=True)
    (tmp_path / "docs" / "interfaces").mkdir(parents=True)
    (tmp_path / "src" / "index.ts").write_text("export const jwksCooldown = 5\n", encoding="utf-8")
    (tmp_path / "test" / "jwks.test.ts").write_text("test('jwks', () => {})\n", encoding="utf-8")
    (tmp_path / "docs" / "interfaces" / "JWK.md").write_text("jwks docs\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    (tmp_path / "tsconfig.json").write_text('{"compilerOptions":{}}\n', encoding="utf-8")

    prioritized = _prioritize_code_context_paths(
        tmp_path,
        "Update the JWKS refetch interval to 10 minutes and adjust the test accordingly.",
        [
            "test/jwks.test.ts",
            "docs/interfaces/JWK.md",
        ],
        limit=4,
    )

    assert prioritized[:3] == ["test/jwks.test.ts", "src/index.ts", "package.json"]
    assert "tsconfig.json" in prioritized


def test_derive_residual_constraints_classifies_apply_and_command_failures():
    residuals = _derive_residual_constraints(
        patch_text='diff --git a/src/index.ts b/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n+foo\n',
        patch_files=["src/index.ts"],
        apply_check_stdout_tail="",
        apply_check_stderr_tail="error: patch failed: src/index.ts:10\nerror: src/index.ts: patch does not apply\n",
        applied=False,
        command_results=[
            {
                "command": "pytest -q",
                "status": "failed",
                "stdout_tail": "",
                "stderr_tail": "ModuleNotFoundError: No module named 'foo'\nAssertionError: expected 200",
            }
        ],
    )

    assert "hunk_context_mismatch" in residuals
    assert "missing_import_or_dependency" in residuals
    assert "behavior_verification_failure" in residuals
    assert "verification_failed:pytest -q" in residuals


def test_derive_residual_constraints_marks_missing_local_tooling():
    residuals = _derive_residual_constraints(
        patch_text='diff --git a/src/index.ts b/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n+foo\n',
        patch_files=["src/index.ts"],
        apply_check_stdout_tail="",
        apply_check_stderr_tail="",
        applied=True,
        command_results=[
            {
                "command": "npm run build",
                "status": "failed",
                "stdout_tail": "",
                "stderr_tail": "'tsc' is not recognized as an internal or external command",
            }
        ],
    )

    assert "missing_local_tooling" in residuals


def test_build_retry_feedback_block_includes_previous_patch_and_feedback():
    block = _build_retry_feedback_block(
        residual_constraints=["hunk_context_mismatch", "missing_import_or_dependency"],
        previous_patch_text='diff --git a/src/index.ts b/src/index.ts\n+++ b/src/index.ts\n@@ -1 +1 @@\n+foo\n',
        apply_check_stdout_tail="",
        apply_check_stderr_tail="error: src/index.ts: patch does not apply",
        apply_stdout_tail="",
        apply_stderr_tail="",
        command_results=[
            {
                "command": "pytest -q",
                "status": "failed",
                "stdout_tail": "",
                "stderr_tail": "ModuleNotFoundError: No module named foo",
            }
        ],
    )

    assert "Residual constraints from the last attempt" in block
    assert "Validation feedback" in block
    assert "Previous patch draft to repair" in block
    assert "pytest -q" in block


def test_merge_retry_context_paths_surfaces_feedback_named_files(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "src" / "helper.ts").write_text("export const helper = true;\n", encoding="utf-8")

    merged = _merge_retry_context_paths(
        repo_root=tmp_path,
        prompt="Fix src index behavior",
        current_paths=["src/helper.ts"],
        patch_files=[],
        residual_constraints=["hunk_context_mismatch"],
        apply_feedback_text="error: patch failed: src/index.ts:10",
        command_results=[],
        retry_context_paths=[],
        limit=3,
    )

    assert merged[0] == "src/index.ts"
    assert "src/helper.ts" in merged


def test_filter_retry_target_paths_blocks_docs_examples_and_expansion():
    filtered = _filter_retry_target_paths(
        prompt="Fix the auth bug in the source module",
        candidate_paths=[
            "docs/guide.md",
            "examples/demo.ts",
            "src/index.ts",
            "test/auth.test.ts",
            "src/outside.ts",
        ],
        original_context_paths=[
            "src/index.ts",
            "docs/guide.md",
            "examples/demo.ts",
        ],
    )

    assert filtered == ["src/index.ts"]


def test_filter_retry_target_paths_allows_missing_create_file_targets():
    filtered = _filter_retry_target_paths(
        prompt="Add a new lifecycle test for jwks refresh",
        candidate_paths=[
            "test/jwks.test.ts",
            "test/jwks_lifecycle.test.ts",
        ],
        original_context_paths=[
            "test/jwks.test.ts",
        ],
        allowed_missing_paths=["test/jwks_lifecycle.test.ts"],
    )

    assert filtered == ["test/jwks.test.ts", "test/jwks_lifecycle.test.ts"]


def test_merge_retry_context_paths_keeps_retry_targets_inside_original_code_context(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / "examples").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "docs" / "guide.md").write_text("guide\n", encoding="utf-8")
    (tmp_path / "examples" / "demo.ts").write_text("console.log('demo')\n", encoding="utf-8")
    (tmp_path / "src" / "other.ts").write_text("export const other = 2;\n", encoding="utf-8")

    merged = _merge_retry_context_paths(
        repo_root=tmp_path,
        prompt="Fix the source auth logic",
        current_paths=["src/index.ts", "docs/guide.md"],
        original_context_paths=["src/index.ts", "docs/guide.md", "examples/demo.ts"],
        patch_files=["docs/guide.md"],
        residual_constraints=["edit_anchor_not_found"],
        apply_feedback_text="error: patch failed: docs/guide.md:4\nerror in src/other.ts",
        command_results=[],
        diagnostic_sheet={"target_files": ["docs/guide.md", "src/other.ts"]},
        retry_context_paths=["examples/demo.ts", "src/other.ts"],
        limit=6,
    )

    assert merged == ["src/index.ts"]


def test_extract_json_object_reads_fenced_payload():
    payload = _extract_json_object(
        """```json
{"edits":[{"file":"src/index.ts","op":"replace","before":"old","after":"new"}]}
```"""
    )

    assert payload == {"edits": [{"file": "src/index.ts", "op": "replace", "before": "old", "after": "new"}]}


def test_compile_structured_edits_to_patch_builds_valid_diff(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "index.ts"
    target.write_text("export const value = 1;\n", encoding="utf-8")

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"edits":[{"file":"src/index.ts","op":"replace","before":"export const value = 1;\\n","after":"export const value = 2;\\n"}]}""",
    )

    assert "diff --git a/src/index.ts b/src/index.ts" in patch_text
    assert "\n--- a/src/index.ts\n+++ b/src/index.ts\n" in patch_text
    assert patch_files == ["src/index.ts"]
    assert residuals == []
    assert feedback == ""


def test_compile_structured_edits_to_patch_accepts_single_edit_object(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "index.ts"
    target.write_text("export const value = 1;\n", encoding="utf-8")

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"file":"src/index.ts","op":"replace","before":"export const value = 1;\\n","after":"export const value = 2;\\n"}""",
        allowed_files=["src/index.ts"],
    )

    assert "diff --git a/src/index.ts b/src/index.ts" in patch_text
    assert patch_files == ["src/index.ts"]
    assert residuals == []
    assert feedback == ""


def test_compile_structured_edits_to_patch_rejects_long_anchor(tmp_path):
    (tmp_path / "docs").mkdir()
    target = tmp_path / "docs" / "guide.md"
    anchor = "A" * 121
    target.write_text(anchor + "\nrest\n", encoding="utf-8")

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        json.dumps(
            {
                "file": "docs/guide.md",
                "op": "insert_after",
                "anchor": anchor,
                "content": "\nnew line",
            }
        ),
        allowed_files=["docs/guide.md"],
    )

    assert patch_text == ""
    assert patch_files == []
    assert "anchor_too_long" in residuals
    assert "longer than 120 characters" in feedback


def test_compile_structured_edits_to_patch_rejects_placeholder_or_disallowed_file(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"file":"repo/path.ext","op":"replace_lines","start_line":1,"end_line":1,"content":"x\\n"}""",
        allowed_files=["src/index.ts"],
    )

    assert patch_text == ""
    assert patch_files == []
    assert "placeholder_structured_edit_file" in residuals
    assert "placeholder path" in feedback


def test_candidate_local_bin_paths_walks_up_parent_tree(tmp_path):
    repo_root = tmp_path / "repo" / ".memla_patch_exec_tmp" / "case_a"
    repo_root.mkdir(parents=True)
    parent_bin = tmp_path / "repo" / "node_modules" / ".bin"
    parent_bin.mkdir(parents=True)

    paths = _candidate_local_bin_paths(repo_root)

    assert str(parent_bin) in paths


def test_select_dependency_bootstrap_command_prefers_lockfile_ci(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"demo"}\n', encoding="utf-8")
    (tmp_path / "package-lock.json").write_text('{"name":"demo","lockfileVersion":3}\n', encoding="utf-8")

    command = _select_dependency_bootstrap_command(tmp_path, ["npm run build"])

    assert command == "npm ci --ignore-scripts"


def test_classify_command_blockage_detects_external_dependency_drift():
    blocked, reason = _classify_command_blockage(
        "../../../node_modules/@types/ws/index.d.ts(334,18): error TS2315: Type 'Server' is not generic."
    )

    assert blocked is True
    assert reason == "external_dependency_typing_drift"


def test_run_expected_commands_treats_blocked_failures_as_semantically_neutral(tmp_path, monkeypatch):
    class _Completed:
        def __init__(self):
            self.returncode = 2
            self.stdout = "../../../node_modules/@types/ws/index.d.ts(334,18): error TS2315: Type 'Server' is not generic.\n"
            self.stderr = ""

    monkeypatch.setattr(
        "memory_system.distillation.patch_execution_benchmark.subprocess.run",
        lambda *args, **kwargs: _Completed(),
    )

    strict_rate, semantic_rate, results = _run_expected_commands(tmp_path, ["npm run build"])

    assert strict_rate == 0.0
    assert semantic_rate == 1.0
    assert results[0]["blocked"] is True


def test_extract_diagnostic_entries_parses_typescript_errors(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value: string = 1;\n", encoding="utf-8")

    entries = _extract_diagnostic_entries(
        tmp_path,
        "src/index.ts(1,14): error TS2322: Type 'number' is not assignable to type 'string'.",
        source="command_feedback",
        command="npm run build",
    )

    assert len(entries) == 1
    assert entries[0]["file"] == "src/index.ts"
    assert entries[0]["line"] == 1
    assert entries[0]["code"] == "TS2322"


def test_build_diagnostic_sheet_and_lesson_focus_top_failure(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text(
        "export const value: string = 1;\nconsole.log(value)\n",
        encoding="utf-8",
    )

    sheet = _build_diagnostic_sheet(
        repo_root=tmp_path,
        prompt="Fix src/index.ts type mismatch",
        patch_files=["src/index.ts"],
        apply_feedback_text="",
        command_results=[
            {
                "command": "npm run build",
                "status": "failed",
                "stdout_tail": "",
                "stderr_tail": "src/index.ts(1,14): error TS2322: Type 'number' is not assignable to type 'string'.",
                "blocked": False,
                "blocked_reason": "",
            }
        ],
    )
    lesson = _derive_active_repair_lesson(
        residual_constraints=[],
        diagnostic_sheet=sheet,
    )

    assert sheet["target_files"][0] == "src/index.ts"
    assert sheet["focus_map"]["src/index.ts"][0]["line"] == 1
    assert "TS2322" in lesson["title"]
    assert lesson["target_files"][0] == "src/index.ts"


def test_build_diagnostic_sheet_short_circuits_to_create_file(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value = 1\n", encoding="utf-8")

    sheet = _build_diagnostic_sheet(
        repo_root=tmp_path,
        prompt="Add a new lifecycle test for jwks refresh",
        patch_files=[],
        apply_feedback_text="",
        command_results=[],
        expected_files_missing_in_parent=["test/jwks_lifecycle.test.ts"],
    )
    lesson = _derive_active_repair_lesson(
        residual_constraints=[],
        diagnostic_sheet=sheet,
    )

    assert sheet["task_type"] == "create_file"
    assert sheet["target_files"] == ["test/jwks_lifecycle.test.ts"]
    assert "New file required" in sheet["summary"]
    assert lesson["title"] == "Create the missing file"
    assert lesson["target_files"] == ["test/jwks_lifecycle.test.ts"]


def test_lesson_applied_requires_target_file_match():
    lesson = {
        "title": "Repair the owning file",
        "target_files": ["src/index.ts"],
    }

    assert _lesson_applied(lesson, ["src/index.ts"]) is True
    assert _lesson_applied(lesson, ["src/helper.ts"]) is False


def test_compile_structured_edits_to_patch_supports_replace_lines(tmp_path):
    (tmp_path / "src").mkdir()
    target = tmp_path / "src" / "index.ts"
    target.write_text("line1\nline2\nline3\nline4\n", encoding="utf-8")

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"edits":[{"file":"src/index.ts","op":"replace_lines","start_line":2,"end_line":3,"content":"updated2\\nupdated3\\n"}]}""",
    )

    assert "updated2" in patch_text
    assert patch_files == ["src/index.ts"]
    assert residuals == []
    assert feedback == ""


def test_compile_structured_edits_to_patch_supports_create_file(tmp_path):
    (tmp_path / "test").mkdir()

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"file":"test/jwks_lifecycle.test.ts","op":"create_file","content":"import test from 'ava'\\n\\ntest('jwks lifecycle', (t) => {\\n  t.pass()\\n})\\n"}""",
        allowed_files=["test/jwks_lifecycle.test.ts"],
    )

    assert "new file mode 100644" in patch_text
    assert "+++ b/test/jwks_lifecycle.test.ts" in patch_text
    assert patch_files == ["test/jwks_lifecycle.test.ts"]
    assert residuals == []
    assert feedback == ""


def test_compile_structured_edits_to_patch_strips_create_file_fences(tmp_path):
    (tmp_path / "test").mkdir()

    patch_text, patch_files, residuals, feedback = _compile_structured_edits_to_patch(
        tmp_path,
        """{"file":"test/jwks_lifecycle.test.ts","op":"create_file","content":"```typescript\\nimport test from 'ava'\\n\\ntest('jwks lifecycle', (t) => {\\n  t.pass()\\n})\\n```"}""",
        allowed_files=["test/jwks_lifecycle.test.ts"],
    )

    assert "```typescript" not in patch_text
    assert "import test from 'ava'" in patch_text
    assert patch_files == ["test/jwks_lifecycle.test.ts"]
    assert residuals == []
    assert feedback == ""


def test_extract_technician_cases_flattens_iteration_trace():
    cases = extract_technician_cases(
        {
            "rows": [
                {
                    "prompt": "Fix auth typing",
                    "commit_sha": "abc123",
                    "expected_files": ["src/index.ts"],
                    "expected_commands": ["npm run build"],
                    "memla_iteration_trace": [
                        {
                            "iteration": 1,
                            "context_files": ["src/index.ts"],
                            "patch_files": ["src/index.ts"],
                            "diagnostic_sheet": {"summary": "src/index.ts:1 TS2322"},
                            "active_repair_lesson": {"title": "Fix TS2322"},
                            "lesson_applied": True,
                            "lesson_mastered": False,
                            "file_recall": 1.0,
                            "diff_recall": 0.5,
                            "apply_check_passed": True,
                            "applied": False,
                            "command_success_rate": 0.0,
                            "semantic_command_success_rate": 0.0,
                            "residual_constraints": ["missing_import_or_dependency"],
                            "command_results": [],
                            "answer": "{\"edits\":[]}",
                        }
                    ],
                }
            ]
        }
    )

    assert len(cases) == 1
    assert cases[0]["prompt"] == "Fix auth typing"
    assert cases[0]["diagnostic_sheet"]["summary"] == "src/index.ts:1 TS2322"
    assert cases[0]["active_repair_lesson"]["title"] == "Fix TS2322"


def test_build_patch_prompt_puts_structured_schema_first(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "index.ts").write_text("export const value = 1;\n", encoding="utf-8")

    messages = _build_patch_prompt(
        prompt="Fix src/index.ts",
        repo_root=tmp_path,
        context_files=[("src/index.ts", "1 | export const value = 1;")],
        response_mode="structured",
    )

    user_content = messages[1].content
    assert user_content.startswith("Respond with a single JSON object")
    assert '"file":"repo/path.ext"' in user_content
    assert "Allowed file paths:" in user_content
    assert "1. src/index.ts" in user_content
    assert "Excerpt:" in user_content
    assert "Task: Fix src/index.ts" in user_content


def test_build_patch_prompt_includes_create_file_guidance(tmp_path):
    (tmp_path / "test").mkdir(parents=True)
    (tmp_path / "test" / "jwks.test.ts").write_text("import test from 'ava'\n\ntest('jwks', (t) => {\n  t.pass()\n})\n", encoding="utf-8")

    messages = _build_patch_prompt(
        prompt="Update the JWKS refetch interval to 10 minutes and adjust the test accordingly.",
        repo_root=tmp_path,
        context_files=[("test/jwks.test.ts", "import test from 'ava'\n\ntest('jwks', (t) => {\n  t.pass()\n})\n")],
        diagnostic_sheet={
            "task_type": "create_file",
            "target_files": ["test/jwks_lifecycle.test.ts"],
            "summary": "New file required: test/jwks_lifecycle.test.ts",
            "entries": [],
        },
        response_mode="structured",
    )

    user_content = messages[1].content
    assert "This is a new-file task" in user_content
    assert "content must be the raw file text only" in user_content
    assert "Allowed files: test/jwks_lifecycle.test.ts" in user_content


def test_rank_allowed_structured_files_prefers_diagnostic_and_demotes_docs():
    ranked = _rank_allowed_structured_files(
        prompt="Fix the jwt auth handler and update tests",
        context_files=[
            ("README.md", "jwt auth docs"),
            ("examples/demo.ts", "jwt auth example"),
            ("src/auth.ts", "export function jwtAuth() {}\nthrow new Error('bad token')"),
            ("test/auth.test.ts", "jwt auth test"),
        ],
        diagnostic_sheet={
            "entries": [
                {
                    "file": "src/auth.ts",
                    "line": 8,
                    "code": "TS2322",
                    "message": "bad type",
                }
            ],
            "target_files": ["src/auth.ts", "test/auth.test.ts"],
        },
    )

    assert ranked[0]["path"] == "src/auth.ts"
    assert ranked[0]["reason"] == "top diagnostic target"
    assert ranked[0]["tier"] == 1
    assert "export function jwtAuth" in ranked[0]["excerpt"]
    readme_item = next(item for item in ranked if item["path"] == "README.md")
    example_item = next(item for item in ranked if item["path"] == "examples/demo.ts")
    assert readme_item["tier"] == 0
    assert "documentation" in readme_item["reason"]
    assert example_item["tier"] == 0
    assert "example file" in example_item["reason"]
