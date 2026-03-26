# Memla Transfer Eval

- Repo: `C:\Users\samat\Project Memory\external\fastapi-guard`
- Cases: `12`

## Aggregate

- Empty-memory file recall: `0.1709`
- Empty-memory command recall: `0.0`
- Memla transfer file recall: `0.1682`
- Memla transfer command recall: `0.0`
- Avg file recall delta: `-0.0028`
- Avg command recall delta: `0.0`
- Positive file-transfer cases: `2`
- Positive command-transfer cases: `0`

## Case 1

**Prompt**: Update FastAPI Guard to version 3.0.2 and fix security middleware request checks.

- Expected files: `docs/versions/versions.json, guard/handlers/suspatterns_handler.py, guard/middleware.py, guard/models.py, guard/utils.py, pyproject.toml, tests/test_middleware/test_security_middleware.py, tests/test_utils/test_request_checks.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `docs/api/security-middleware.md, tests/test_middleware/test_security_middleware.py, guard/middleware.py, guard/handlers/security_headers_handler.py, guard/core/events/middleware_events.py, tests/test_security_headers/test_middleware_integration.py`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Empty-memory file recall: `0.25`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_middleware/test_security_middleware.py, guard/middleware.py, guard/handlers/security_headers_handler.py, guard/core/events/middleware_events.py, tests/test_security_headers/test_middleware_integration.py, tests/test_decorators/test_middleware_integration.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, dependency_manifest, service_boundary, test_surface`
- Memla transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Memla source trace ids: `21, 19`
- Memla file recall: `0.25`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 2

**Prompt**: Update the project version to 4.0.0 and remove the commented-out Discord notification configuration.

- Expected files: `Makefile, docs/versions/versions.json, examples/main.py, guard/decorators/access_control.py, guard/decorators/base.py, guard/detection_engine/__init__.py, guard/detection_engine/compiler.py, guard/detection_engine/monitor.py, guard/detection_engine/preprocessor.py, guard/detection_engine/semantic.py, guard/handlers/__init__.py, guard/handlers/behavior_handler.py, guard/handlers/cloud_handler.py, guard/handlers/dynamic_rule_handler.py, guard/handlers/ipban_handler.py, guard/handlers/ipinfo_handler.py, guard/handlers/ratelimit_handler.py, guard/handlers/redis_handler.py, guard/handlers/suspatterns_handler.py, guard/middleware.py, guard/models.py, guard/protocols/__init__.py, guard/protocols/agent_protocol.py, guard/protocols/geo_ip_protocol.py, guard/protocols/redis_protocol.py, guard/utils.py, pyproject.toml, tests/conftest.py, tests/test_agent/__init__.py, tests/test_agent/conftest.py, tests/test_agent/test_behavior_agent_integration.py, tests/test_agent/test_cloud_agent_integration.py, tests/test_agent/test_decorator_agent_integration.py, tests/test_agent/test_drh_agent_integration.py, tests/test_agent/test_ipban_agent_integration.py, tests/test_agent/test_ipinfo_agent_integration.py, tests/test_agent/test_middleware_agent_integration.py, tests/test_agent/test_models_agent_integration.py, tests/test_agent/test_ratelimit_agent_integration.py, tests/test_agent/test_redis_agent_integration.py, tests/test_agent/test_suspatterns_agent_integration.py, tests/test_agent/test_utils_agent_integration.py, tests/test_decorators/test_authentication.py, tests/test_decorators/test_base.py, tests/test_decorators/test_behavior_handler.py, tests/test_decorators/test_middleware_integration.py, tests/test_middleware/test_security_middleware.py, tests/test_models/test_models.py, tests/test_sus_patterns/conftest.py, tests/test_sus_patterns/test_compiler.py, tests/test_sus_patterns/test_detection_engine.py, tests/test_sus_patterns/test_extension_integration.py, tests/test_sus_patterns/test_monitor.py, tests/test_sus_patterns/test_preprocessor.py, tests/test_sus_patterns/test_semantic.py, tests/test_sus_patterns/test_sus_patterns.py, tests/test_utils/test_proxy_handling.py, tests/test_utils/test_request_checks.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `docs/versions/versions.json, docs/tutorial/security/detection-engine/configuration.md, docs/tutorial/configuration/security-config.md, docs/tutorial/configuration/logging.md, setup.py, pyproject.toml`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Empty-memory file recall: `0.0345`
- Empty-memory command recall: `0.0`
- Memla files: `setup.py, pyproject.toml, examples/simple_app/requirements.txt, examples/simple_app/main.py, examples/advanced_app/pyproject.toml, examples/advanced_app/app/main.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, dependency_manifest, test_surface`
- Memla transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Memla source trace ids: `21, 19`
- Memla file recall: `0.0172`
- Memla command recall: `0.0`
- File recall delta: `-0.0173`
- Command recall delta: `0.0`

## Case 3

**Prompt**: Fix the formatting of the geo rate limit decorator in the example code.

- Expected files: `examples/main.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `guard/decorators/rate_limiting.py, docs/tutorial/decorators/rate-limiting.md, tests/test_decorators/test_rate_limiting.py, guard/decorators/py.typed, guard/decorators/content_filtering.py, guard/decorators/behavioral.py`
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `guard/decorators/rate_limiting.py, tests/test_decorators/test_rate_limiting.py, tests/test_decorators/test_middleware_integration.py, tests/test_decorators/test_content_filtering.py, tests/test_decorators/test_behavioral.py, tests/test_decorators/test_behavior_handler_edge_cases.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, service_boundary, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `21, 20, 19, 18`
- Memla file recall: `0.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 4

**Prompt**: Fix import issues by renaming the guard variable to guard_decorator to resolve decorator conflicts.

- Expected files: `examples/main.py, guard/models.py, tests/test_agent/test_models_agent_integration.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `guard/decorators/rate_limiting.py, guard/decorators/py.typed, guard/decorators/content_filtering.py, guard/decorators/behavioral.py, guard/decorators/base.py, guard/decorators/authentication.py`
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `guard/decorators/rate_limiting.py, guard/decorators/py.typed, guard/decorators/content_filtering.py, guard/decorators/behavioral.py, guard/decorators/base.py, guard/decorators/authentication.py`
- Memla commands: ``
- Memla roles: `service_boundary`
- Memla transmutations: ``
- Memla source trace ids: ``
- Memla file recall: `0.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 5

**Prompt**: Refactor the guard configuration to consolidate duplicate pattern settings into a single line.

- Expected files: `examples/main.py, guard/models.py, tests/test_agent/test_models_agent_integration.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: ``
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: ``
- Memla commands: ``
- Memla roles: ``
- Memla transmutations: ``
- Memla source trace ids: ``
- Memla file recall: `0.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 6

**Prompt**: Update the FastAPI Guard version to 4.0.1 in the project configuration and documentation.

- Expected files: `docs/versions/versions.json, pyproject.toml`
- Expected commands: `pytest`
- Empty-memory files: `guard/protocols/redis_protocol.py, guard/protocols/py.typed, guard/protocols/geo_ip_protocol.py, guard/protocols/agent_protocol.py, setup.py, pyproject.toml`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Empty-memory file recall: `0.5`
- Empty-memory command recall: `0.0`
- Memla files: `setup.py, pyproject.toml, examples/simple_app/requirements.txt, examples/simple_app/main.py, examples/advanced_app/pyproject.toml, examples/advanced_app/app/main.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, dependency_manifest, test_surface`
- Memla transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Memla source trace ids: `21, 19`
- Memla file recall: `0.5`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 7

**Prompt**: Fix the bugged Agent integration by updating version files and handler logic.

- Expected files: `docs/versions/versions.json, guard/decorators/base.py, guard/handlers/behavior_handler.py, guard/handlers/cloud_handler.py, guard/handlers/dynamic_rule_handler.py, guard/handlers/ipban_handler.py, guard/handlers/ipinfo_handler.py, guard/handlers/ratelimit_handler.py, guard/handlers/redis_handler.py, guard/handlers/suspatterns_handler.py, guard/middleware.py, guard/utils.py, pyproject.toml, tests/test_agent/conftest.py, tests/test_agent/test_middleware_agent_integration.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `tests/test_agent/test_middleware_agent_integration.py, tests/test_agent/test_decorator_agent_integration.py, guard/handlers/suspatterns_handler.py, guard/handlers/security_headers_handler.py, guard/handlers/redis_handler.py, guard/handlers/ratelimit_handler.py`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Empty-memory file recall: `0.2667`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_agent/test_middleware_agent_integration.py, tests/test_agent/test_decorator_agent_integration.py, tests/test_security_headers/test_middleware_integration.py, tests/test_decorators/test_middleware_integration.py, tests/test_decorators/test_behavior_handler_edge_cases.py, tests/test_decorators/test_behavior_handler.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, dependency_manifest, service_boundary, test_surface`
- Memla transmutations: `Trade stale dependency stability for updated compatibility plus verification.`
- Memla source trace ids: `21, 19`
- Memla file recall: `0.0667`
- Memla command recall: `0.0`
- File recall delta: `-0.2`
- Command recall delta: `0.0`

## Case 8

**Prompt**: Fix the custom_log_file configuration so file logging works correctly and is only enabled when explicitly set.

- Expected files: `docs/versions/versions.json, examples/main.py, guard/decorators/base.py, guard/detection_engine/preprocessor.py, guard/handlers/behavior_handler.py, guard/handlers/cloud_handler.py, guard/handlers/dynamic_rule_handler.py, guard/handlers/ipban_handler.py, guard/handlers/ipinfo_handler.py, guard/handlers/ratelimit_handler.py, guard/handlers/redis_handler.py, guard/handlers/suspatterns_handler.py, guard/middleware.py, guard/utils.py, pyproject.toml, tests/conftest.py, tests/test_agent/test_middleware_agent_integration.py, tests/test_agent/test_redis_agent_integration.py, tests/test_agent/test_suspatterns_agent_integration.py, tests/test_middleware/test_security_middleware.py, tests/test_utils/test_logging.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: ``
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_utils/test_logging.py, tests/test_features/test_structured_json_logging.py, examples/simple_app/main.py, examples/advanced_app/app/main.py, tests/test_security_headers/test_middleware_integration.py, tests/test_models/test_models.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `18, 13, 8`
- Memla file recall: `0.0476`
- Memla command recall: `0.0`
- File recall delta: `0.0476`
- Command recall delta: `0.0`

## Case 9

**Prompt**: Fix flaky test assertion by making it more robust against log message variations.

- Expected files: `tests/test_utils/test_logging.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `tests/test_security_headers/test_middleware_integration.py, tests/test_models/test_models.py, tests/test_middleware/test_security_middleware.py, tests/test_features/test_context_aware_detection.py, tests/test_decorators/test_rate_limiting.py, tests/test_decorators/test_middleware_integration.py`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_security_headers/test_middleware_integration.py, tests/test_models/test_models.py, tests/test_middleware/test_security_middleware.py, tests/test_features/test_context_aware_detection.py, tests/test_decorators/test_rate_limiting.py, tests/test_decorators/test_middleware_integration.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `21, 20, 19, 18`
- Memla file recall: `0.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 10

**Prompt**: Fix the formatting inconsistency in the logging test assertion.

- Expected files: `tests/test_utils/test_logging.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `tests/test_utils/test_logging.py, tests/test_features/test_structured_json_logging.py, tests/test_security_headers/test_middleware_integration.py, tests/test_models/test_models.py, tests/test_middleware/test_security_middleware.py, tests/test_features/test_context_aware_detection.py`
- Empty-memory commands: ``
- Empty-memory transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Empty-memory file recall: `1.0`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_utils/test_logging.py, tests/test_features/test_structured_json_logging.py, tests/test_security_headers/test_middleware_integration.py, tests/test_models/test_models.py, tests/test_middleware/test_security_middleware.py, tests/test_features/test_context_aware_detection.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `18, 13, 8, 21`
- Memla file recall: `1.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`

## Case 11

**Prompt**: Add HTTP security headers to the FastAPI Guard library.

- Expected files: `docs/versions/versions.json, examples/main.py, guard/__init__.py, guard/decorators/__init__.py, guard/decorators/access_control.py, guard/decorators/advanced.py, guard/decorators/authentication.py, guard/decorators/base.py, guard/decorators/behavioral.py, guard/decorators/content_filtering.py, guard/decorators/rate_limiting.py, guard/detection_engine/__init__.py, guard/detection_engine/compiler.py, guard/detection_engine/monitor.py, guard/detection_engine/preprocessor.py, guard/detection_engine/semantic.py, guard/handlers/__init__.py, guard/handlers/behavior_handler.py, guard/handlers/cloud_handler.py, guard/handlers/dynamic_rule_handler.py, guard/handlers/ipban_handler.py, guard/handlers/ipinfo_handler.py, guard/handlers/ratelimit_handler.py, guard/handlers/redis_handler.py, guard/handlers/security_headers_handler.py, guard/handlers/suspatterns_handler.py, guard/middleware.py, guard/models.py, guard/protocols/__init__.py, guard/protocols/agent_protocol.py, guard/protocols/geo_ip_protocol.py, guard/protocols/redis_protocol.py, guard/scripts/__init__.py, guard/scripts/rate_lua.py, pyproject.toml, tests/test_security_headers/__init__.py, tests/test_security_headers/test_agent_integration.py, tests/test_security_headers/test_cors_integration.py, tests/test_security_headers/test_csp_validation.py, tests/test_security_headers/test_edge_cases.py, tests/test_security_headers/test_headers_core.py, tests/test_security_headers/test_middleware_integration.py, tests/test_security_headers/test_redis_integration.py, tests/test_security_headers/test_security_validation.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: ``
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_security_headers/test_security_validation.py, tests/test_security_headers/test_headers_core.py, tests/test_security_headers/test_middleware_integration.py, tests/test_security_headers/test_redis_integration.py, tests/test_security_headers/test_edge_cases.py, tests/test_security_headers/test_csp_validation.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `18, 13, 8, 17`
- Memla file recall: `0.1364`
- Memla command recall: `0.0`
- File recall delta: `0.1364`
- Command recall delta: `0.0`

## Case 12

**Prompt**: Remove trailing commas from the security headers notes in the example file.

- Expected files: `examples/main.py`
- Expected commands: `pytest, ruff check .`
- Empty-memory files: `guard/handlers/security_headers_handler.py, docs/api/security-headers.md, docs/tutorial/security/http-security-headers.md, tests/test_security_headers/test_security_validation.py, tests/test_security_headers/test_middleware_integration.py, tests/test_security_headers/test_redis_integration.py`
- Empty-memory commands: ``
- Empty-memory transmutations: ``
- Empty-memory file recall: `0.0`
- Empty-memory command recall: `0.0`
- Memla files: `tests/test_security_headers/test_security_validation.py, tests/test_security_headers/test_headers_core.py, tests/test_security_headers/test_middleware_integration.py, tests/test_security_headers/test_redis_integration.py, tests/test_security_headers/test_edge_cases.py, tests/test_security_headers/test_csp_validation.py`
- Memla commands: `py -3 -m pytest -q tests/test_step6_coding_distillation.py`
- Memla roles: `app_shell, test_surface`
- Memla transmutations: `Trade one implementation constraint for a more stable verified constraint.`
- Memla source trace ids: `21, 20, 19, 18`
- Memla file recall: `0.0`
- Memla command recall: `0.0`
- File recall delta: `0.0`
- Command recall delta: `0.0`
