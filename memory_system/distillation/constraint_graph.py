from __future__ import annotations

import json
import posixpath
import re
import tomllib
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path


_STOPWORDS = {
    "a",
    "an",
    "and",
    "app",
    "be",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "page",
    "screen",
    "the",
    "this",
    "to",
    "update",
    "with",
}

_ASSET_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".mp4",
    ".woff",
    ".woff2",
}

_GENERIC_TRANSFORMATION_TOKENS = {
    "trade",
    "constraint",
    "stable",
    "verified",
    "implementation",
    "local",
    "freedom",
    "preserved",
    "one",
    "more",
    "safer",
    "cleaner",
}

_PRECISE_SUPPORTING_ROLES = {"dependency_manifest", "cli_surface", "test_surface"}
_GENERIC_FILE_HINT_TOKENS = {
    "src",
    "lib",
    "app",
    "apps",
    "core",
    "pkg",
    "package",
    "module",
    "modules",
    "test",
    "tests",
    "spec",
    "specs",
    "index",
    "main",
    "dist",
    "build",
    "file",
    "files",
    "handler",
    "handlers",
}

_CONSTRAINT_HINTS: dict[str, set[str]] = {
    "state_persistence": {"resume", "restore", "persist", "recover", "rehydrate", "stateful", "continue"},
    "redirect_return_flow": {"return", "redirect", "callback", "success", "resume", "handoff"},
    "payment_confirmation": {"checkout", "payment", "billing", "receipt", "invoice", "charge", "confirm"},
    "deployment_routing": {"spa", "rewrite", "fallback", "deploy", "routing", "route", "edge"},
    "dependency_upgrade": {"upgrade", "bump", "compatibility", "version", "migrate", "dependency"},
    "api_contract_preservation": {"contract", "compatibility", "payload", "response", "serialize", "client"},
    "layout_adjustment": {"layout", "spacing", "height", "container", "compact", "visual"},
    "loading_state_cleanup": {"loading", "spinner", "skeleton", "steady", "flicker"},
    "booking_state_handshake": {"booking", "guest", "reservation", "handoff", "confirm"},
    "verification_gate": {"verify", "verified", "validate", "test", "build", "lint", "pytest", "ruff"},
    "auth_session_integrity": {
        "auth",
        "session",
        "cookie",
        "csrf",
        "anonymous",
        "unauthenticated",
        "permission",
        "login",
        "secure",
        "strict",
    },
    "middleware_interception": {"middleware", "guard", "intercept", "downstream", "request", "handler", "block", "before"},
    "cli_command_flow": {"cli", "command", "argv", "stdin", "stdout", "prompt", "terminal", "flag", "option", "shell"},
    "schema_validation": {"schema", "validator", "validate", "field", "payload", "openapi", "spec", "invalid", "parse"},
}

_FAMILY_CONSTRAINT_PRIORS: dict[str, dict[str, float]] = {
    "python_api": {
        "verification_gate": 0.35,
        "api_contract_preservation": 0.35,
        "schema_validation": 0.35,
    },
    "python_cli": {
        "cli_command_flow": 0.55,
        "verification_gate": 0.25,
    },
    "ts_web_app": {
        "redirect_return_flow": 0.25,
        "state_persistence": 0.25,
        "verification_gate": 0.2,
    },
    "ts_backend_security": {
        "auth_session_integrity": 0.45,
        "middleware_interception": 0.45,
        "verification_gate": 0.25,
    },
    "ts_cli_tooling": {
        "cli_command_flow": 0.5,
        "schema_validation": 0.2,
        "verification_gate": 0.25,
    },
    "backend_security": {
        "auth_session_integrity": 0.45,
        "middleware_interception": 0.45,
    },
    "cli_tooling": {
        "cli_command_flow": 0.5,
        "verification_gate": 0.2,
    },
    "web_app": {
        "redirect_return_flow": 0.2,
        "deployment_routing": 0.2,
        "state_persistence": 0.2,
    },
}

_CONSTRAINT_ROLE_MAP: dict[str, set[str]] = {
    "state_persistence": {"state_holder"},
    "redirect_return_flow": {"checkout_return", "routing_surface"},
    "payment_confirmation": {"payment_boundary", "checkout_return"},
    "deployment_routing": {"deployment_config", "routing_surface"},
    "dependency_upgrade": {"dependency_manifest"},
    "api_contract_preservation": {"contract_boundary", "service_boundary"},
    "layout_adjustment": {"style_surface"},
    "loading_state_cleanup": {"style_surface"},
    "booking_state_handshake": {"booking_flow", "state_holder"},
    "verification_gate": {"test_surface"},
    "auth_session_integrity": {"security_surface"},
    "middleware_interception": {"security_surface", "service_boundary"},
    "cli_command_flow": {"cli_surface"},
    "schema_validation": {"contract_boundary", "service_boundary"},
}

_ROLE_CONSTRAINT_PRIORS: dict[str, dict[str, float]] = {
    "checkout_return": {"redirect_return_flow": 0.6, "payment_confirmation": 0.25},
    "booking_flow": {"booking_state_handshake": 0.45, "state_persistence": 0.2},
    "payment_boundary": {"payment_confirmation": 0.65},
    "state_holder": {"state_persistence": 0.55},
    "routing_surface": {"redirect_return_flow": 0.25, "deployment_routing": 0.3},
    "service_boundary": {"middleware_interception": 0.25, "api_contract_preservation": 0.2},
    "security_surface": {"auth_session_integrity": 0.6, "middleware_interception": 0.3},
    "cli_surface": {"cli_command_flow": 0.7},
    "test_surface": {"verification_gate": 0.6},
    "contract_boundary": {"api_contract_preservation": 0.45, "schema_validation": 0.45},
}

_CONSTRAINT_TENSIONS: list[tuple[set[str], str]] = [
    (
        {"auth_session_integrity", "api_contract_preservation"},
        "Trade stricter security guarantees against external compatibility expectations.",
    ),
    (
        {"middleware_interception", "api_contract_preservation"},
        "Trade early enforcement against downstream implementation flexibility.",
    ),
    (
        {"dependency_upgrade", "verification_gate"},
        "Trade change velocity against stability and verification burden.",
    ),
    (
        {"redirect_return_flow", "state_persistence"},
        "Trade boundary-crossing flow recovery against simpler local state handling.",
    ),
    (
        {"cli_command_flow", "schema_validation"},
        "Trade command-line flexibility against stricter validated input contracts.",
    ),
]

_TRADE_RULES: list[dict[str, object]] = [
    {
        "trade": "Trade embedded payment state for redirect-safe confirmation recovery.",
        "all_of": {"payment_confirmation", "redirect_return_flow"},
        "support_tags": {"payment_confirmation", "redirect_return_flow"},
    },
    {
        "trade": "Trade transient UI state for recoverable session-backed booking state.",
        "any_of": {"state_persistence", "booking_state_handshake"},
        "support_tags": {"state_persistence", "booking_state_handshake"},
    },
    {
        "trade": "Trade strict server routing for client-side SPA fallback.",
        "all_of": {"deployment_routing"},
        "support_tags": {"deployment_routing"},
    },
    {
        "trade": "Trade stale dependency stability for updated compatibility plus verification.",
        "all_of": {"dependency_upgrade"},
        "support_tags": {"dependency_upgrade", "verification_gate"},
    },
    {
        "trade": "Trade local implementation freedom for a preserved external contract.",
        "all_of": {"api_contract_preservation"},
        "support_tags": {"api_contract_preservation"},
    },
    {
        "trade": "Trade permissive request flow for stricter authentication and session integrity.",
        "all_of": {"auth_session_integrity"},
        "support_tags": {"auth_session_integrity"},
    },
    {
        "trade": "Trade downstream flexibility for earlier middleware enforcement and validation.",
        "all_of": {"middleware_interception"},
        "support_tags": {"middleware_interception"},
    },
    {
        "trade": "Trade shell flexibility for a repeatable command-line workflow.",
        "all_of": {"cli_command_flow"},
        "support_tags": {"cli_command_flow"},
    },
    {
        "trade": "Trade loose input handling for stricter schema-driven validation.",
        "all_of": {"schema_validation"},
        "support_tags": {"schema_validation"},
    },
    {
        "trade": "Trade visual compactness for clearer interaction space.",
        "all_of": {"layout_adjustment"},
        "support_tags": {"layout_adjustment"},
    },
    {
        "trade": "Trade temporary user feedback scaffolding for a cleaner steady-state flow.",
        "all_of": {"loading_state_cleanup"},
        "support_tags": {"loading_state_cleanup"},
    },
]

_HYPOTHESIS_AGENT_SPECS: list[dict[str, object]] = [
    {
        "id": "security_sentinel",
        "label": "Security Sentinel",
        "style": "structural",
        "repo_families": {"backend_security", "ts_backend_security", "python_api"},
        "constraints": {"auth_session_integrity", "verification_gate"},
        "roles": {"security_surface", "test_surface"},
        "diagnostic_focus": {"auth_session_integrity", "verification_gate"},
        "exclude_constraints": {"cli_command_flow", "layout_adjustment", "loading_state_cleanup"},
        "exclude_roles": {"cli_surface", "style_surface"},
    },
    {
        "id": "middleware_guard",
        "label": "Middleware Guard",
        "style": "structural",
        "repo_families": {"backend_security", "ts_backend_security", "python_api"},
        "constraints": {"middleware_interception", "verification_gate"},
        "roles": {"security_surface", "service_boundary"},
        "diagnostic_focus": {"middleware_interception", "verification_gate"},
        "exclude_constraints": {"cli_command_flow", "layout_adjustment"},
        "exclude_roles": {"cli_surface", "style_surface"},
    },
    {
        "id": "contract_keeper",
        "label": "Contract Keeper",
        "style": "structural",
        "repo_families": {"python_api", "ts_backend_security", "ts_web_app"},
        "constraints": {"api_contract_preservation", "schema_validation"},
        "roles": {"contract_boundary", "service_boundary"},
        "diagnostic_focus": {"api_contract_preservation", "schema_validation"},
        "exclude_constraints": {"cli_command_flow", "loading_state_cleanup"},
        "exclude_roles": {"cli_surface", "style_surface"},
    },
    {
        "id": "cli_operator",
        "label": "CLI Operator",
        "style": "structural",
        "repo_families": {"cli_tooling", "ts_cli_tooling", "python_cli"},
        "constraints": {"cli_command_flow", "verification_gate"},
        "roles": {"cli_surface", "test_surface"},
        "diagnostic_focus": {"cli_command_flow", "verification_gate"},
        "exclude_constraints": {"auth_session_integrity", "middleware_interception", "redirect_return_flow", "payment_confirmation"},
        "exclude_roles": {"security_surface", "checkout_return", "payment_boundary"},
    },
    {
        "id": "dependency_shepherd",
        "label": "Dependency Shepherd",
        "style": "structural",
        "repo_families": {"ts_web_app", "ts_backend_security", "ts_cli_tooling", "python_api", "python_cli"},
        "constraints": {"dependency_upgrade", "verification_gate"},
        "roles": {"dependency_manifest", "test_surface"},
        "diagnostic_focus": {"dependency_upgrade", "verification_gate"},
        "exclude_constraints": {"loading_state_cleanup"},
        "exclude_roles": {"style_surface"},
    },
    {
        "id": "redirect_recovery",
        "label": "Redirect Recovery",
        "style": "structural",
        "repo_families": {"web_app", "ts_web_app"},
        "constraints": {"redirect_return_flow", "payment_confirmation"},
        "roles": {"checkout_return", "routing_surface", "payment_boundary"},
        "diagnostic_focus": {"redirect_return_flow", "payment_confirmation"},
        "exclude_constraints": {"cli_command_flow", "auth_session_integrity", "middleware_interception"},
        "exclude_roles": {"cli_surface", "security_surface"},
    },
    {
        "id": "state_reconciler",
        "label": "State Reconciler",
        "style": "structural",
        "repo_families": {"web_app", "ts_web_app"},
        "constraints": {"state_persistence", "booking_state_handshake"},
        "roles": {"state_holder", "booking_flow"},
        "diagnostic_focus": {"state_persistence", "booking_state_handshake"},
        "exclude_constraints": {"cli_command_flow", "middleware_interception"},
        "exclude_roles": {"cli_surface", "security_surface"},
    },
    {
        "id": "verification_gatekeeper",
        "label": "Verification Gatekeeper",
        "style": "structural",
        "repo_families": {"general", "web_app", "python_api", "backend_security", "ts_backend_security", "ts_web_app"},
        "constraints": {"verification_gate"},
        "roles": {"test_surface"},
        "diagnostic_focus": {"verification_gate"},
        "exclude_constraints": set(),
        "exclude_roles": set(),
    },
]


@dataclass(frozen=True)
class RepoRoleCandidate:
    path: str
    roles: list[str]
    score: float


@dataclass(frozen=True)
class RepoMapRegionCandidate:
    region: str
    roles: list[str]
    sample_files: list[str]
    score: float


def _normalize_token(token: str) -> str:
    token = token.lower()
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        return token[:-3]
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and len(token) > 3:
        return token[:-1]
    return token


def tokenize_text(text: str) -> set[str]:
    return {
        _normalize_token(token)
        for token in re.findall(r"[a-zA-Z0-9]+", text or "")
        if len(_normalize_token(token)) >= 3 and _normalize_token(token) not in _STOPWORDS
    }


def _expand_identifier(text: str) -> str:
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", text or "")
    return expanded.replace("_", " ").replace("-", " ")


def tokenize_path(path: str) -> set[str]:
    raw = str(path or "").replace("\\", "/")
    out: set[str] = set()
    for piece in [part for part in raw.split("/") if part]:
        stem = Path(piece).stem if "." in piece else piece
        out.update(tokenize_text(stem))
        out.update(tokenize_text(_expand_identifier(stem)))
    return out


def infer_file_roles(path: str) -> set[str]:
    normalized = str(path or "").replace("\\", "/")
    lowered = normalized.lower()
    tokens = tokenize_path(normalized)
    stem = Path(normalized).stem.lower()
    roles: set[str] = set()

    if lowered.endswith(("package.json", "package-lock.json", "pnpm-lock.yaml", "yarn.lock")):
        roles.add("dependency_manifest")
    if lowered.endswith(("pyproject.toml", "setup.py", "requirements.txt", "poetry.lock", "uv.lock")):
        roles.add("dependency_manifest")
    if lowered.endswith(("vercel.json", "vite.config.js", "vite.config.ts", "next.config.js", "next.config.ts")):
        roles.add("deployment_config")
    if stem in {"main", "__init__"} and {"example", "examples"} & tokens:
        roles.add("app_shell")
    if lowered.endswith((".css", ".scss", ".sass", ".less")) or {"style", "layout", "theme"} & tokens:
        roles.add("style_surface")
    if stem in {"app", "main", "root"} or {"app", "main", "root"} & tokens:
        roles.add("app_shell")
    if {"checkout", "return", "success", "callback"} & tokens:
        roles.add("checkout_return")
    if {"booking", "reservation", "guest", "confirm"} & tokens:
        roles.add("booking_flow")
    if {"stripe", "payment", "pms", "billing"} & tokens:
        roles.add("payment_boundary")
    if {"state", "store", "context", "session", "persist"} & tokens:
        roles.add("state_holder")
    if {"route", "router", "navigation", "redirect"} & tokens:
        roles.add("routing_surface")
    if {"service", "client", "api", "handler", "controller"} & tokens:
        roles.add("service_boundary")
    if {"middleware", "decorator", "decorators"} & tokens:
        roles.add("service_boundary")
    if stem in {"dependency", "dependencies"} or ({"dependency", "dependencies"} & tokens and "/core/" in lowered):
        roles.add("service_boundary")
    if {"oauth", "auth", "security", "guard", "token", "cookie", "csrf"} & tokens:
        roles.add("security_surface")
    elif "session" in tokens and (
        {"auth", "security", "guard", "cookie", "middleware"} & tokens
        or "/security/" in lowered
        or "/auth/" in lowered
    ):
        roles.add("security_surface")
    if stem in {"dependency", "dependencies"} and ("/core/" in lowered or "/auth/" in lowered or "/security/" in lowered):
        roles.add("security_surface")
    if {"cli", "command", "terminal", "prompt"} & tokens:
        roles.add("cli_surface")
    if {"test", "spec"} & tokens:
        roles.add("test_surface")
    if {"serialize", "serializer", "schema", "contract"} & tokens:
        roles.add("contract_boundary")
    if {"model", "models", "protocol", "protocols", "openapi", "swagger", "spec"} & tokens:
        roles.add("contract_boundary")
    return roles


def infer_prompt_roles(text: str) -> set[str]:
    tokens = tokenize_text(text)
    roles: set[str] = set()
    if {"checkout", "return", "success", "callback"} & tokens:
        roles.update({"checkout_return", "routing_surface"})
    if {"booking", "reservation", "guest", "confirm"} & tokens:
        roles.add("booking_flow")
    if {"stripe", "payment", "pms", "billing"} & tokens:
        roles.add("payment_boundary")
    if {"session", "storage", "persist", "state", "initialization"} & tokens:
        roles.add("state_holder")
    if {"route", "router", "redirect", "navigation", "spa", "vercel"} & tokens:
        roles.add("routing_surface")
    if {"flow", "integration", "navigation", "state"} & tokens and (
        {"checkout", "booking", "reservation", "payment", "stripe"} & tokens
    ):
        roles.add("app_shell")
    if {"app", "entrypoint", "bootstrap"} & tokens:
        roles.add("app_shell")
    if {"style", "layout", "height", "container", "loading"} & tokens:
        roles.add("style_surface")
    if {"react", "router", "dependency", "version", "upgrade"} & tokens:
        roles.add("dependency_manifest")
    if {"python", "pyproject", "dependency", "version", "upgrade", "package"} & tokens:
        roles.add("dependency_manifest")
    if {"middleware", "handler", "logging", "logger", "import"} & tokens:
        roles.add("service_boundary")
    if {"decorator", "decorators"} & tokens:
        roles.add("service_boundary")
    if {"oauth", "auth", "token", "session", "guard", "security"} & tokens:
        roles.add("security_surface")
    if {"cli", "terminal", "command", "prompt", "subprocess"} & tokens:
        roles.add("cli_surface")
    if {"model", "models", "protocol", "protocols"} & tokens:
        roles.add("contract_boundary")
    if {"openapi", "schema", "spec", "swagger", "validator"} & tokens:
        roles.add("contract_boundary")
    if {"example", "examples"} & tokens:
        roles.add("app_shell")
    if {"api", "contract", "serialize", "serializer"} & tokens:
        roles.update({"contract_boundary", "service_boundary"})
    if {"test", "verify", "lint", "build"} & tokens:
        roles.add("test_surface")
    return roles


def infer_constraint_tags(text: str, paths: list[str] | None = None, commands: list[str] | None = None) -> set[str]:
    tokens = tokenize_text(text)
    path_tokens: set[str] = set()
    for path in paths or []:
        path_tokens.update(tokenize_path(path))
    command_blob = " ".join(commands or [])
    command_tokens = tokenize_text(command_blob)
    merged = tokens | path_tokens | command_tokens
    tags: set[str] = set()

    if {"session", "storage", "persist", "restore", "initialization"} & merged:
        tags.add("state_persistence")
    if {"checkout", "return", "redirect", "callback", "success"} & merged:
        tags.add("redirect_return_flow")
    if {"stripe", "payment", "pms", "billing", "confirmation"} & merged:
        tags.add("payment_confirmation")
    if {"vercel", "spa", "route", "router", "rewrite"} & merged:
        tags.add("deployment_routing")
    if {"react", "router", "dependency", "version", "upgrade"} & merged:
        tags.add("dependency_upgrade")
    if {"serialize", "serializer", "contract", "schema"} & merged:
        tags.add("api_contract_preservation")
    if {"height", "layout", "container", "style", "css"} & merged:
        tags.add("layout_adjustment")
    if {"loading", "spinner", "skeleton"} & merged:
        tags.add("loading_state_cleanup")
    if {"booking", "guest", "reservation"} & merged and {"checkout", "return", "redirect"} & merged:
        tags.add("booking_state_handshake")
    if {"build", "lint", "pytest", "test"} & merged:
        tags.add("verification_gate")
    if {"oauth", "auth", "token", "session", "cookie", "login"} & merged:
        tags.add("auth_session_integrity")
    if {"middleware", "guard", "header", "rate", "limit", "intercept"} & merged:
        tags.add("middleware_interception")
    if {"cli", "command", "terminal", "prompt", "subprocess"} & merged:
        tags.add("cli_command_flow")
    if {"openapi", "schema", "spec", "swagger", "validator"} & merged:
        tags.add("schema_validation")
    return tags


def infer_roles_from_constraints(tags: list[str] | set[str]) -> set[str]:
    roles: set[str] = set()
    for tag in tags:
        roles.update(_CONSTRAINT_ROLE_MAP.get(str(tag), set()))
    return roles


def predict_constraint_tags(
    text: str,
    *,
    repo_family: str = "",
    paths: list[str] | None = None,
    commands: list[str] | None = None,
    candidate_constraints: list[str] | None = None,
    limit: int = 6,
) -> list[str]:
    prompt_roles = infer_prompt_roles(text)
    observed = infer_constraint_tags(text, paths, commands)
    merged_tokens = tokenize_text(text)
    for path in paths or []:
        merged_tokens.update(tokenize_path(path))
    merged_tokens.update(tokenize_text(" ".join(commands or [])))

    scores: dict[str, float] = {}

    def _bump(tag: str, amount: float) -> None:
        if not tag or amount <= 0:
            return
        scores[tag] = scores.get(tag, 0.0) + float(amount)

    for tag in observed:
        _bump(tag, 2.4)

    for tag, amount in _FAMILY_CONSTRAINT_PRIORS.get(repo_family or "", {}).items():
        _bump(tag, amount)

    for role in prompt_roles:
        for tag, amount in _ROLE_CONSTRAINT_PRIORS.get(role, {}).items():
            _bump(tag, amount)

    for tag, hints in _CONSTRAINT_HINTS.items():
        overlap = len(merged_tokens & hints)
        if overlap:
            _bump(tag, min(1.2, overlap * 0.34))

    if candidate_constraints:
        counts: dict[str, int] = {}
        for raw in candidate_constraints:
            tag = str(raw or "").strip()
            if not tag:
                continue
            counts[tag] = counts.get(tag, 0) + 1
        for tag, count in counts.items():
            _bump(tag, min(1.0, count * 0.22))

    ranked = sorted(
        scores.items(),
        key=lambda item: (item[1], item[0] in observed, item[0]),
        reverse=True,
    )
    selected = [tag for tag, score in ranked if score >= 0.65 or tag in observed]
    if not selected:
        selected = [tag for tag, _ in ranked[: max(int(limit), 0)]]
    return list(dict.fromkeys(selected))[: max(int(limit), 0)]


def infer_constraint_tensions(tags: list[str] | set[str]) -> list[str]:
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    tensions: list[str] = []
    for required_tags, text in _CONSTRAINT_TENSIONS:
        if required_tags <= tag_set and text not in tensions:
            tensions.append(text)
    return tensions[:4]


def assess_constraint_predictions(predicted: list[str] | set[str], observed: list[str] | set[str]) -> dict[str, object]:
    predicted_set = {str(tag).strip() for tag in predicted if str(tag).strip()}
    observed_set = {str(tag).strip() for tag in observed if str(tag).strip()}
    confirmed = sorted(predicted_set & observed_set)
    missed = sorted(observed_set - predicted_set)
    false_positives = sorted(predicted_set - observed_set)
    if not predicted_set and not observed_set:
        precision = 1.0
        recall = 1.0
        f1 = 1.0
    else:
        precision = len(confirmed) / max(len(predicted_set), 1)
        recall = len(confirmed) / max(len(observed_set), 1)
        f1 = 0.0 if precision + recall == 0 else (2 * precision * recall) / (precision + recall)
    return {
        "predicted": sorted(predicted_set),
        "observed": sorted(observed_set),
        "confirmed": confirmed,
        "missed": missed,
        "false_positives": false_positives,
        "precision": round(float(precision), 4),
        "recall": round(float(recall), 4),
        "f1": round(float(f1), 4),
    }


def _dedupe_preserve(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / max(len(left | right), 1)


def _hypothesis_similarity(left: dict[str, object], right: dict[str, object]) -> float:
    left_constraints = {str(tag).strip() for tag in (left.get("predicted_constraints") or []) if str(tag).strip()}
    right_constraints = {str(tag).strip() for tag in (right.get("predicted_constraints") or []) if str(tag).strip()}
    left_roles = {str(role).strip() for role in (left.get("predicted_roles") or []) if str(role).strip()}
    right_roles = {str(role).strip() for role in (right.get("predicted_roles") or []) if str(role).strip()}
    left_trades = {str(text).strip() for text in (left.get("predicted_transmutations") or []) if str(text).strip()}
    right_trades = {str(text).strip() for text in (right.get("predicted_transmutations") or []) if str(text).strip()}
    left_negative_constraints = {
        str(tag).strip() for tag in (left.get("negative_constraints") or []) if str(tag).strip()
    }
    right_negative_constraints = {
        str(tag).strip() for tag in (right.get("negative_constraints") or []) if str(tag).strip()
    }
    left_negative_roles = {str(role).strip() for role in (left.get("negative_roles") or []) if str(role).strip()}
    right_negative_roles = {str(role).strip() for role in (right.get("negative_roles") or []) if str(role).strip()}
    left_paths = {str(path).strip().replace("\\", "/") for path in (left.get("target_paths") or []) if str(path).strip()}
    right_paths = {str(path).strip().replace("\\", "/") for path in (right.get("target_paths") or []) if str(path).strip()}
    return (
        (_jaccard_similarity(left_constraints, right_constraints) * 0.42)
        + (_jaccard_similarity(left_roles, right_roles) * 0.24)
        + (_jaccard_similarity(left_trades, right_trades) * 0.18)
        + (_jaccard_similarity(left_negative_constraints, right_negative_constraints) * 0.1)
        + (_jaccard_similarity(left_negative_roles, right_negative_roles) * 0.06)
        + (_jaccard_similarity(left_paths, right_paths) * 0.22)
    )


def _diversify_hypotheses(hypotheses: list[dict[str, object]], *, limit: int) -> list[dict[str, object]]:
    if limit <= 0 or not hypotheses:
        return []
    ranked = list(hypotheses)
    ranked.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            bool(item.get("repo_family_fit")),
            len(item.get("predicted_constraints") or []),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    selected: list[dict[str, object]] = []
    seen_styles: set[str] = set()
    seen_constraints: set[str] = set()
    seen_roles: set[str] = set()
    seen_trades: set[str] = set()
    seen_negative_constraints: set[str] = set()

    while ranked and len(selected) < limit:
        if not selected:
            seed = dict(ranked.pop(0))
            seed["novelty_score"] = round(
                (
                    len({str(tag).strip() for tag in (seed.get("predicted_constraints") or []) if str(tag).strip()}) * 0.18
                    + len({str(role).strip() for role in (seed.get("predicted_roles") or []) if str(role).strip()}) * 0.08
                    + len(
                        {str(text).strip() for text in (seed.get("predicted_transmutations") or []) if str(text).strip()}
                    )
                    * 0.09
                ),
                4,
            )
            seed["diversity_penalty"] = 0.0
            seed["selection_score"] = round(float(seed.get("score") or 0.0) + float(seed["novelty_score"]), 4)
            selected.append(seed)
            if str(seed.get("style") or "").strip():
                seen_styles.add(str(seed.get("style") or "").strip())
            seen_constraints.update(str(tag).strip() for tag in (seed.get("predicted_constraints") or []) if str(tag).strip())
            seen_roles.update(str(role).strip() for role in (seed.get("predicted_roles") or []) if str(role).strip())
            seen_trades.update(
                str(text).strip() for text in (seed.get("predicted_transmutations") or []) if str(text).strip()
            )
            seen_negative_constraints.update(
                str(tag).strip() for tag in (seed.get("negative_constraints") or []) if str(tag).strip()
            )
            continue

        best_index = -1
        best_value = float("-inf")
        best_payload: dict[str, float] | None = None
        for index, candidate in enumerate(ranked):
            candidate_constraints = {
                str(tag).strip() for tag in (candidate.get("predicted_constraints") or []) if str(tag).strip()
            }
            candidate_roles = {str(role).strip() for role in (candidate.get("predicted_roles") or []) if str(role).strip()}
            candidate_trades = {
                str(text).strip() for text in (candidate.get("predicted_transmutations") or []) if str(text).strip()
            }
            candidate_negative_constraints = {
                str(tag).strip() for tag in (candidate.get("negative_constraints") or []) if str(tag).strip()
            }
            novelty_score = (
                len(candidate_constraints - seen_constraints) * 0.2
                + len(candidate_roles - seen_roles) * 0.08
                + len(candidate_trades - seen_trades) * 0.09
                + len(candidate_negative_constraints - seen_negative_constraints) * 0.04
            )
            pairwise = [_hypothesis_similarity(candidate, existing) for existing in selected]
            max_similarity = max(pairwise) if pairwise else 0.0
            avg_similarity = sum(pairwise) / max(len(pairwise), 1) if pairwise else 0.0
            diversity_penalty = (max_similarity * 0.82) + (avg_similarity * 0.28)
            selection_score = float(candidate.get("score") or 0.0) + novelty_score - diversity_penalty
            if candidate.get("repo_family_fit") and novelty_score > 0.0:
                selection_score += 0.08
            candidate_style = str(candidate.get("style") or "").strip()
            if candidate_style and candidate_style not in seen_styles:
                selection_score += 0.18
            if selection_score > best_value:
                best_value = selection_score
                best_index = index
                best_payload = {
                    "novelty_score": round(float(novelty_score), 4),
                    "diversity_penalty": round(float(diversity_penalty), 4),
                    "selection_score": round(float(selection_score), 4),
                }

        if best_index < 0:
            break
        chosen = dict(ranked.pop(best_index))
        chosen.update(best_payload or {})
        selected.append(chosen)
        if str(chosen.get("style") or "").strip():
            seen_styles.add(str(chosen.get("style") or "").strip())
        seen_constraints.update(str(tag).strip() for tag in (chosen.get("predicted_constraints") or []) if str(tag).strip())
        seen_roles.update(str(role).strip() for role in (chosen.get("predicted_roles") or []) if str(role).strip())
        seen_trades.update(
            str(text).strip() for text in (chosen.get("predicted_transmutations") or []) if str(text).strip()
        )
        seen_negative_constraints.update(
            str(tag).strip() for tag in (chosen.get("negative_constraints") or []) if str(tag).strip()
        )

    return selected[:limit]


def _build_precise_file_hypotheses(
    text: str,
    *,
    paths: list[str] | None = None,
    commands: list[str] | None = None,
    base_constraints: list[str] | None = None,
    candidate_transmutations: set[str] | None = None,
    limit: int = 3,
) -> list[dict[str, object]]:
    prompt_tokens = tokenize_text(text)
    prompt_roles = infer_prompt_roles(text)
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for raw_path in paths or []:
        clean_path = str(raw_path or "").strip().replace("\\", "/")
        if not clean_path or clean_path in seen:
            continue
        seen.add(clean_path)
        path_tokens = tokenize_path(clean_path)
        if not path_tokens:
            continue
        basename_tokens = tokenize_text(Path(clean_path).stem) | tokenize_text(_expand_identifier(Path(clean_path).stem))
        basename_overlap = len(prompt_tokens & basename_tokens)
        overlap = len(prompt_tokens & path_tokens)
        file_roles = infer_file_roles(clean_path)
        if basename_overlap == 0 and overlap == 0 and not file_roles:
            continue
        path_constraints = infer_constraint_tags(text, [clean_path], commands or [])
        combined_constraints = _dedupe_preserve(list(path_constraints) + list(base_constraints or []))
        predicted_constraints = [tag for tag in combined_constraints if tag in path_constraints or tag in (base_constraints or [])][:3]
        predicted_roles = sorted(file_roles | infer_roles_from_constraints(predicted_constraints))
        predicted_transmutations = [
            trade
            for trade in summarize_transmutations(predicted_constraints)
            if trade in (candidate_transmutations or set()) or not candidate_transmutations
        ] or summarize_transmutations(predicted_constraints)
        if not predicted_roles and basename_overlap == 0 and overlap < 2:
            continue
        role_alignment = len(file_roles & prompt_roles)
        role_mismatch_penalty = 0.0
        if "cli_surface" in file_roles and "cli_surface" not in prompt_roles and {"security_surface", "service_boundary"} & prompt_roles:
            role_mismatch_penalty += 1.1
        if "test_surface" in file_roles and "test_surface" not in prompt_roles and basename_overlap < 2:
            role_mismatch_penalty += 0.55
        if file_roles and file_roles <= _PRECISE_SUPPORTING_ROLES and role_alignment == 0:
            role_mismatch_penalty += 0.6
        score = (
            0.32
            + (basename_overlap * 0.92)
            + (overlap * 0.24)
            + (role_alignment * 0.35)
            + (len(set(predicted_roles) - _PRECISE_SUPPORTING_ROLES) * 0.18)
            + (0.08 if "test_surface" not in file_roles else 0.0)
            - role_mismatch_penalty
        )
        if score <= 0.0:
            continue
        candidates.append(
            {
                "id": f"precise_path::{clean_path}",
                "label": f"Path Anchor {Path(clean_path).name}",
                "style": "precise",
                "score": round(float(score), 4),
                "repo_family_fit": True,
                "predicted_constraints": list(predicted_constraints),
                "predicted_roles": list(predicted_roles),
                "negative_constraints": [],
                "negative_roles": [],
                "predicted_transmutations": list(predicted_transmutations[:4]),
                "diagnostic_focus": [],
                "target_paths": [clean_path],
                "lifecycle_status": "candidate",
                "fitness": 0.0,
            }
        )

    candidates.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            len(item.get("predicted_roles") or []),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return candidates[: max(int(limit), 0)]


def _matching_trade_rules(tags: list[str] | set[str]) -> list[tuple[str, list[str]]]:
    tag_set = {str(tag).strip() for tag in tags if str(tag).strip()}
    matched: list[tuple[str, list[str]]] = []
    for rule in _TRADE_RULES:
        required = {str(tag).strip() for tag in (rule.get("all_of") or set()) if str(tag).strip()}
        optional = {str(tag).strip() for tag in (rule.get("any_of") or set()) if str(tag).strip()}
        if required and not required <= tag_set:
            continue
        if optional and not (optional & tag_set):
            continue
        if not required and not optional:
            continue
        support_tags = {str(tag).strip() for tag in (rule.get("support_tags") or set()) if str(tag).strip()}
        active_support = sorted((support_tags or (required | optional)) & tag_set)
        matched.append((str(rule["trade"]), active_support))
    if not matched and tag_set:
        matched.append(("Trade one implementation constraint for a more stable verified constraint.", sorted(tag_set)))
    return matched[:4]


def summarize_constraint_trades(tags: list[str]) -> list[str]:
    return [trade for trade, _ in _matching_trade_rules(tags)]


def summarize_transmutations(tags: list[str]) -> list[str]:
    return summarize_constraint_trades(tags)


def attribute_trade_success(
    *,
    predicted_constraints: list[str] | set[str],
    realized_constraints: list[str] | set[str],
    predicted_transmutations: list[str] | None = None,
    diagnostic_commands: list[str] | None = None,
    touched_files: list[str] | None = None,
    role_targets: list[str] | None = None,
) -> dict[str, object]:
    predicted_tags = _dedupe_preserve(list(predicted_constraints or []))
    realized_tags = _dedupe_preserve(list(realized_constraints or []))
    predicted_trades = _dedupe_preserve(list(predicted_transmutations or summarize_transmutations(predicted_tags)))
    winning_pairs = _matching_trade_rules(realized_tags)
    winning_trades = [trade for trade, _ in winning_pairs]
    diagnostic_commands_clean = _dedupe_preserve(list(diagnostic_commands or []))
    touched_files_clean = _dedupe_preserve(list(touched_files or []))
    resolved_roles = sorted(
        {
            *[str(role).strip() for role in (role_targets or []) if str(role).strip()],
            *{role for path in touched_files_clean for role in infer_file_roles(path)},
        }
    )
    diagnostic_signals = sorted(infer_constraint_tags("", [], diagnostic_commands_clean))
    confirmed_trade_predictions = sorted(set(predicted_trades) & set(winning_trades))
    missed_trade_predictions = sorted(set(winning_trades) - set(predicted_trades))
    false_trade_predictions = sorted(set(predicted_trades) - set(winning_trades))

    attribution: list[dict[str, object]] = []
    for trade, supporting_constraints in winning_pairs:
        active_diagnostic_signals = sorted(set(diagnostic_signals) & set(supporting_constraints))
        support_score = len(supporting_constraints) / max(len(realized_tags), 1)
        attribution.append(
            {
                "trade": trade,
                "realized_constraints": list(supporting_constraints),
                "diagnostic_signals": list(active_diagnostic_signals),
                "diagnostic_commands": list(diagnostic_commands_clean),
                "resolved_files": list(touched_files_clean),
                "resolved_roles": list(resolved_roles),
                "support_score": round(float(support_score), 4),
            }
        )

    return {
        "diagnostic_commands": list(diagnostic_commands_clean),
        "diagnostic_signals": list(diagnostic_signals),
        "predicted_transmutations": list(predicted_trades),
        "winning_trades": list(winning_trades),
        "confirmed_trade_predictions": list(confirmed_trade_predictions),
        "missed_trade_predictions": list(missed_trade_predictions),
        "false_trade_predictions": list(false_trade_predictions),
        "resolved_roles": list(resolved_roles),
        "trade_success_attribution": attribution,
    }


def _normalize_search_path(path: str) -> str:
    clean = str(path or "").strip().replace("\\", "/")
    if not clean:
        return ""
    normalized = posixpath.normpath(clean)
    if normalized == ".":
        return ""
    return normalized


def _path_prefixes(path: str) -> list[str]:
    clean = _normalize_search_path(path)
    parts = [part for part in Path(clean).parts if part and part not in {".", "/"}]
    prefixes: list[str] = []
    for idx in range(1, len(parts)):
        prefix = "/".join(parts[:idx])
        if prefix:
            prefixes.append(prefix)
    return prefixes


def _path_hint_tokens(path: str) -> set[str]:
    clean = _normalize_search_path(path)
    if not clean:
        return set()
    basename = Path(clean).stem
    tokens = tokenize_path(clean) | tokenize_text(basename) | tokenize_text(_expand_identifier(basename))
    return {token for token in tokens if token not in _GENERIC_FILE_HINT_TOKENS and token not in _STOPWORDS}


def build_file_search_node(
    *,
    repo_family: str,
    diagnostic_commands: list[str] | None = None,
    realized_constraints: list[str] | set[str] | None = None,
    winning_trades: list[str] | set[str] | None = None,
    touched_files: list[str] | None = None,
) -> dict[str, object]:
    resolved_files = _dedupe_preserve([_normalize_search_path(path) for path in (touched_files or []) if _normalize_search_path(path)])
    resolved_roles = sorted({role for path in resolved_files for role in infer_file_roles(path)})
    directory_weights: dict[str, float] = {}
    token_weights: dict[str, float] = {}
    for path in resolved_files:
        prefixes = _path_prefixes(path)
        for prefix in prefixes:
            depth = len([part for part in prefix.split("/") if part])
            weight = min(0.22 + (depth * 0.24), 1.0)
            directory_weights[prefix] = max(directory_weights.get(prefix, 0.0), weight)
        basename_tokens = tokenize_text(Path(path).stem) | tokenize_text(_expand_identifier(Path(path).stem))
        path_tokens = _path_hint_tokens(path)
        for token in path_tokens:
            weight = 0.52 if token in basename_tokens else 0.28
            token_weights[token] = max(token_weights.get(token, 0.0), weight)
    directory_hints = [
        {"path": prefix, "weight": round(float(weight), 4)}
        for prefix, weight in sorted(
            directory_weights.items(),
            key=lambda item: (item[1], len(item[0]), item[0]),
            reverse=True,
        )
    ]
    token_hints = [
        {"token": token, "weight": round(float(weight), 4)}
        for token, weight in sorted(token_weights.items(), key=lambda item: (item[1], item[0]), reverse=True)
    ]
    realized_constraint_list = _dedupe_preserve(list(realized_constraints or []))
    winning_trade_list = _dedupe_preserve(list(winning_trades or []))
    diagnostic_command_list = _dedupe_preserve(list(diagnostic_commands or []))
    diagnostic_signals = sorted(infer_constraint_tags("", [], diagnostic_command_list))
    return {
        "repo_family": str(repo_family or "").strip() or "unknown",
        "resolved_files": list(resolved_files),
        "resolved_roles": list(resolved_roles),
        "realized_constraints": list(realized_constraint_list),
        "diagnostic_commands": list(diagnostic_command_list),
        "diagnostic_signals": list(diagnostic_signals),
        "winning_trades": list(winning_trade_list),
        "directory_hints": directory_hints[:8],
        "token_hints": token_hints[:10],
        "search_stages": [
            {"stage": "role", "hints": list(resolved_roles)},
            {"stage": "directory", "hints": [item["path"] for item in directory_hints[:6]]},
            {"stage": "token", "hints": [item["token"] for item in token_hints[:8]]},
            {"stage": "exact", "hints": list(resolved_files)},
        ],
    }


def _region_key(path: str) -> str:
    clean = _normalize_search_path(path)
    parts = [part for part in Path(clean).parts if part and part not in {".", "/"}]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]

    first = parts[0]
    second = parts[1] if len(parts) > 1 else ""

    if first == "packages":
        if len(parts) >= 5 and parts[2] in {"src", "test", "tests"}:
            return "/".join(parts[:5])
        return "/".join(parts[: min(len(parts), 3)])
    if first in {"src", "tests", "test"}:
        if Path(second).suffix:
            return first
        if len(parts) >= 3 and second in {"api", "auth", "core", "commands", "reunite"} and not Path(parts[2]).suffix:
            return "/".join(parts[:3])
        return "/".join(parts[:2])
    return "/".join(parts[: min(len(parts), 2)])


_IGNORED_REPO_SEARCH_SUFFIXES = (
    ".sqlite",
    ".sqlite-wal",
    ".sqlite-shm",
    ".db",
    ".db-wal",
    ".db-shm",
    ".wal",
    ".shm",
    ".pyc",
    ".pyo",
    ".tmp",
    ".cache",
)


def _should_skip_repo_index_file(path: Path, rel: str) -> bool:
    lowered_rel = rel.lower()
    if path.suffix.lower() in _ASSET_SUFFIXES:
        return True
    if any(lowered_rel.endswith(suffix) for suffix in _IGNORED_REPO_SEARCH_SUFFIXES):
        return True
    return False


def _module_aliases_for_path(rel: str) -> set[str]:
    clean = _normalize_search_path(rel)
    if not clean:
        return set()
    parts = [part for part in Path(clean).parts if part and part not in {".", "/"}]
    if not parts:
        return set()
    stem = Path(clean).stem
    if stem == "__init__":
        parts = parts[:-1]
    else:
        parts[-1] = stem
    if not parts:
        return set()
    aliases = {".".join(parts)}
    aliases.add(parts[-1])
    if len(parts) >= 2:
        aliases.add(".".join(parts[-2:]))
    if parts[0] == "src" and len(parts) > 1:
        aliases.add(".".join(parts[1:]))
        aliases.add(parts[-1])
    return {alias for alias in aliases if alias and alias != "."}


def _extract_python_import_refs(text: str) -> set[str]:
    refs: set[str] = set()
    for match in re.finditer(r"^\s*(?:from\s+([A-Za-z0-9_\.]+)\s+import|import\s+([A-Za-z0-9_\.]+))", text or "", re.MULTILINE):
        ref = str(match.group(1) or match.group(2) or "").strip()
        if ref and not ref.startswith("."):
            refs.add(ref)
    return refs


def _extract_python_import_aliases(text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in re.finditer(r"^\s*from\s+([A-Za-z0-9_\.]+|\.[A-Za-z0-9_\.]+)\s+import\s+([^\n#]+)", text or "", re.MULTILINE):
        module_ref = str(match.group(1) or "").strip()
        imports_blob = str(match.group(2) or "").strip()
        if not module_ref or not imports_blob:
            continue
        for raw_part in imports_blob.split(","):
            part = str(raw_part or "").strip()
            if not part or part == "*":
                continue
            imported_name = part
            alias_name = part
            if " as " in part:
                imported_name, alias_name = [segment.strip() for segment in part.split(" as ", 1)]
            if alias_name:
                aliases[alias_name] = module_ref
                if imported_name:
                    aliases[imported_name] = module_ref
    for match in re.finditer(r"^\s*import\s+([A-Za-z0-9_\.]+)(?:\s+as\s+([A-Za-z_][A-Za-z0-9_]*))?", text or "", re.MULTILINE):
        module_ref = str(match.group(1) or "").strip()
        alias_name = str(match.group(2) or "").strip()
        if not module_ref:
            continue
        if alias_name:
            aliases[alias_name] = module_ref
        aliases[module_ref.split(".")[-1]] = module_ref
    return aliases


def _extract_js_import_aliases(text: str) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for match in re.finditer(r"import\s+([^\n;]+?)\s+from\s+['\"]([^'\"]+)['\"]", text or ""):
        import_blob = str(match.group(1) or "").strip()
        module_ref = str(match.group(2) or "").strip()
        if not import_blob or not module_ref:
            continue
        if import_blob.startswith("{") and import_blob.endswith("}"):
            import_blob = import_blob[1:-1]
        parts = [segment.strip() for segment in import_blob.split(",") if segment.strip()]
        for part in parts:
            if part.startswith("{") and part.endswith("}"):
                names_blob = part[1:-1]
                for raw_name in names_blob.split(","):
                    name_part = str(raw_name or "").strip()
                    if not name_part:
                        continue
                    name_part = re.sub(r"^\s*type\s+", "", name_part).strip()
                    imported_name = name_part
                    local_name = name_part
                    if " as " in name_part:
                        imported_name, local_name = [segment.strip() for segment in name_part.split(" as ", 1)]
                    if local_name:
                        aliases[local_name] = module_ref
                    if imported_name:
                        aliases[imported_name] = module_ref
                continue
            clean_part = re.sub(r"^\s*type\s+", "", part).strip()
            if clean_part:
                aliases[clean_part] = module_ref
    for match in re.finditer(r"export\s+\{([^}]+)\}\s+from\s+['\"]([^'\"]+)['\"]", text or ""):
        export_blob = str(match.group(1) or "").strip()
        module_ref = str(match.group(2) or "").strip()
        if not export_blob or not module_ref:
            continue
        for raw_name in export_blob.split(","):
            name_part = str(raw_name or "").strip()
            if not name_part:
                continue
            name_part = re.sub(r"^\s*type\s+", "", name_part).strip()
            imported_name = name_part
            local_name = name_part
            if " as " in name_part:
                imported_name, local_name = [segment.strip() for segment in name_part.split(" as ", 1)]
            if local_name:
                aliases[local_name] = module_ref
            if imported_name:
                aliases[imported_name] = module_ref
    return aliases


def _extract_js_import_refs(text: str) -> set[str]:
    refs: set[str] = set()
    patterns = [
        r"import\s+[^'\"]+?\s+from\s+['\"]([^'\"]+)['\"]",
        r"export\s+[^'\"]+?\s+from\s+['\"]([^'\"]+)['\"]",
        r"require\(\s*['\"]([^'\"]+)['\"]\s*\)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            ref = str(match.group(1) or "").strip()
            if ref:
                refs.add(ref)
    return refs


def _extract_js_defined_symbols(text: str) -> set[str]:
    symbols: set[str] = set()
    patterns = [
        r"^\s*export\s+(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*(?:async\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*export\s+const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
        r"^\s*const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
        r"^\s*export\s+class\s+([A-Za-z_][A-Za-z0-9_]*)",
        r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or "", re.MULTILINE):
            symbol = str(match.group(1) or "").strip()
            if symbol:
                symbols.add(symbol)
    return symbols


def _extract_route_refs(text: str) -> list[set[str]]:
    route_refs: list[set[str]] = []
    for match in re.finditer(r"['\"](/[^'\"]{3,})['\"]", text or ""):
        route = str(match.group(1) or "").strip()
        if not route or route == "/":
            continue
        tokens = tokenize_path(route)
        if len(tokens) >= 2:
            route_refs.append(tokens)
    return route_refs


def _extract_router_symbols(text: str) -> set[str]:
    symbols: set[str] = set()
    for match in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*APIRouter\(", text or "", re.MULTILINE):
        symbol = str(match.group(1) or "").strip()
        if symbol:
            symbols.add(symbol)
    return symbols


def _extract_python_defined_symbols(text: str) -> set[str]:
    symbols: set[str] = set()
    for match in re.finditer(r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_][A-Za-z0-9_]*)", text or "", re.MULTILINE):
        symbol = str(match.group(1) or "").strip()
        if symbol:
            symbols.add(symbol)
    for match in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*Depends\(", text or "", re.MULTILINE):
        symbol = str(match.group(1) or "").strip()
        if symbol:
            symbols.add(symbol)
    return symbols


def _extract_dependency_symbol_refs(text: str) -> set[str]:
    refs: set[str] = set()
    patterns = [
        r"Depends\(\s*([A-Za-z_][A-Za-z0-9_\.]*)",
        r"Security\(\s*([A-Za-z_][A-Za-z0-9_\.]*)",
        r"Annotated\[[^\]]+,\s*Depends\(\s*([A-Za-z_][A-Za-z0-9_\.]*)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, text or ""):
            ref = str(match.group(1) or "").strip()
            if ref:
                refs.add(ref.split(".")[-1])
    for token in ("permission", "auth", "depend", "dependauth", "dependpermisson", "permissioncontrol", "authcontrol"):
        if token in tokenize_text(text):
            refs.add(token)
    return refs


def _extract_route_definitions(text: str) -> list[set[str]]:
    route_defs: list[set[str]] = []
    for match in re.finditer(
        r"@\s*[A-Za-z_][A-Za-z0-9_]*\.(?:get|post|put|patch|delete|options|head)\(\s*['\"]([^'\"]+)['\"]",
        text or "",
    ):
        route = str(match.group(1) or "").strip()
        if not route:
            continue
        tokens = tokenize_path(route)
        if tokens:
            route_defs.append(tokens)
    return route_defs


def _extract_call_chunks(text: str, marker: str) -> list[str]:
    chunks: list[str] = []
    search_from = 0
    while True:
        position = (text or "").find(marker, search_from)
        if position < 0:
            break
        start = position + len(marker) - 1
        depth = 0
        in_string = False
        string_char = ""
        escaped = False
        for index in range(start, len(text or "")):
            char = text[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == string_char:
                    in_string = False
                continue
            if char in {"'", '"', "`"}:
                in_string = True
                string_char = char
                continue
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
                if depth == 0:
                    chunks.append(text[start : index + 1])
                    search_from = index + 1
                    break
        else:
            break
    return chunks


def _extract_cli_command_specs(text: str) -> list[dict[str, object]]:
    specs: list[dict[str, object]] = []
    for chunk in _extract_call_chunks(text or "", ".command("):
        command_match = re.match(r"\(\s*['\"]([^'\"]+)['\"]", chunk)
        if not command_match:
            continue
        raw_command = str(command_match.group(1) or "").strip()
        if not raw_command:
            continue
        command_head = raw_command.split()[0].strip()
        command_head = re.sub(r"[\[\]<].*$", "", command_head).strip()
        if not command_head:
            continue
        command_tokens = tokenize_path(command_head) | tokenize_text(command_head)
        handler_refs = [
            str(item).strip()
            for item in re.findall(r"commandWrapper\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\)", chunk)
            if str(item).strip()
        ]
        if not handler_refs:
            continue
        specs.append(
            {
                "command": command_head,
                "command_tokens": sorted(command_tokens),
                "handler_refs": list(dict.fromkeys(handler_refs)),
            }
        )
    return specs


def _extract_router_include_calls(text: str) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    for match in re.finditer(r"include_router\((.*?)\)", text or "", re.DOTALL):
        blob = str(match.group(1) or "").strip()
        if not blob:
            continue
        router_match = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)", blob)
        router_ref = str(router_match.group(1) or "").strip() if router_match else ""
        if not router_ref:
            continue
        prefix_match = re.search(r"prefix\s*=\s*['\"]([^'\"]+)['\"]", blob)
        prefix_tokens = tokenize_path(str(prefix_match.group(1) or "").strip()) if prefix_match else set()
        dependency_refs: list[str] = []
        dep_match = re.search(r"dependencies\s*=\s*\[([^\]]+)\]", blob, re.DOTALL)
        if dep_match:
            dep_blob = str(dep_match.group(1) or "")
            dependency_refs = [
                str(item).strip()
                for item in re.findall(r"[A-Za-z_][A-Za-z0-9_\.]*", dep_blob)
                if str(item).strip()
            ]
        calls.append(
            {
                "router_ref": router_ref,
                "prefix_tokens": prefix_tokens,
                "dependency_refs": dependency_refs,
            }
        )
    return calls


def _topology_hub_penalty(path: str, *, degree: int = 0) -> float:
    clean = _normalize_search_path(path)
    stem = Path(clean).stem.lower()
    penalty = 0.0
    if stem in {"__init__", "conftest"}:
        penalty += 0.45
    if stem in {"schemas", "schema", "models", "types", "common", "helpers"}:
        penalty += 0.14
    if clean.endswith("/__init__.py"):
        penalty += 0.18
    if degree >= 6:
        penalty += min(0.24, (degree - 5) * 0.03)
    return penalty


def _route_target_score(
    route_tokens: set[str],
    target_path: str,
    *,
    target_route_defs: list[set[str]] | None = None,
    target_roles: set[str] | None = None,
) -> float:
    path_tokens = tokenize_path(target_path)
    path_overlap = len(route_tokens & path_tokens)
    route_def_overlap = 0
    for route_def in target_route_defs or []:
        route_def_overlap = max(route_def_overlap, len(route_tokens & route_def))
    score = 0.0
    if path_overlap >= 2:
        score += 0.34 + (path_overlap * 0.14)
    if route_def_overlap >= 1:
        score += 0.24 + (route_def_overlap * 0.17)
    if path_overlap >= 2 and route_def_overlap >= 1:
        score += 0.16
    if {"service_boundary", "contract_boundary"} & set(target_roles or set()):
        score += 0.08
    return score


def _resolve_relative_import(ref: str, source_rel: str, file_set: set[str]) -> set[str]:
    clean_ref = str(ref or "").strip()
    if not clean_ref.startswith("."):
        return set()
    source_clean = _normalize_search_path(source_rel)
    source_parent = posixpath.dirname(source_clean)
    base = _normalize_search_path(posixpath.join(source_parent, clean_ref))
    if not base:
        return set()
    candidates: set[str] = set()
    suffix = Path(base).suffix.lower()
    stem = base[: -len(suffix)] if suffix else base
    raw_candidates = {
        base,
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.js",
        f"{base}.jsx",
        f"{base}.mjs",
        f"{base}.cjs",
        f"{base}.py",
        f"{base}/index.ts",
        f"{base}/index.tsx",
        f"{base}/index.js",
        f"{base}/index.jsx",
        f"{base}/__init__.py",
    }
    if suffix in {".js", ".jsx", ".mjs", ".cjs"}:
        raw_candidates.update(
            {
                f"{stem}.ts",
                f"{stem}.tsx",
                f"{stem}.mts",
                f"{stem}.cts",
            }
        )
    elif suffix in {".ts", ".tsx", ".mts", ".cts"}:
        raw_candidates.update(
            {
                f"{stem}.js",
                f"{stem}.jsx",
                f"{stem}.mjs",
                f"{stem}.cjs",
            }
        )
    for candidate in raw_candidates:
        normalized = _normalize_search_path(candidate)
        if normalized in file_set:
            candidates.add(normalized)
    return candidates


def _resolve_python_relative_module_ref(ref: str, source_rel: str, file_set: set[str]) -> set[str]:
    clean_ref = str(ref or "").strip()
    if not clean_ref.startswith("."):
        return set()
    dots = len(clean_ref) - len(clean_ref.lstrip("."))
    remainder = clean_ref[dots:]
    source_parts = [part for part in Path(_normalize_search_path(source_rel)).parts if part]
    if source_parts and Path(source_rel).suffix:
        source_parts = source_parts[:-1]
    if dots > 1:
        source_parts = source_parts[: max(len(source_parts) - (dots - 1), 0)]
    module_parts = list(source_parts)
    if remainder:
        module_parts.extend(part for part in remainder.split(".") if part)
    if not module_parts:
        return set()
    module_path = "/".join(module_parts)
    candidates: set[str] = set()
    for candidate in (
        f"{module_path}.py",
        f"{module_path}/__init__.py",
    ):
        normalized = _normalize_search_path(candidate)
        if normalized in file_set:
            candidates.add(normalized)
    return candidates


def _resolve_python_name_targets(
    name: str,
    *,
    source_rel: str,
    import_aliases: dict[str, str],
    module_index: dict[str, set[str]],
    symbol_index: dict[str, set[str]],
    file_set: set[str],
) -> set[str]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return set()
    targets: set[str] = set()
    ref = import_aliases.get(clean_name, clean_name)
    if ref.startswith("."):
        targets.update(_resolve_python_relative_module_ref(ref, source_rel, file_set))
    else:
        targets.update(module_index.get(ref, set()))
    targets.update(symbol_index.get(clean_name, set()) | symbol_index.get(clean_name.lower(), set()))
    return targets


def _resolve_js_name_targets(
    name: str,
    *,
    source_rel: str,
    import_aliases: dict[str, str],
    module_index: dict[str, set[str]],
    symbol_index: dict[str, set[str]],
    file_set: set[str],
) -> set[str]:
    clean_name = str(name or "").strip()
    if not clean_name:
        return set()
    targets: set[str] = set()
    ref = import_aliases.get(clean_name, clean_name)
    if ref.startswith("."):
        targets.update(_resolve_relative_import(ref, source_rel, file_set))
    else:
        targets.update(module_index.get(ref, set()))
    targets.update(symbol_index.get(clean_name, set()) | symbol_index.get(clean_name.lower(), set()))
    return targets


def _append_route_tokens(route_defs_by_file: dict[str, list[set[str]]], path: str, route_tokens: set[str]) -> bool:
    clean_path = _normalize_search_path(path)
    clean_tokens = {str(token).strip() for token in (route_tokens or set()) if str(token).strip()}
    if not clean_path or not clean_tokens:
        return False
    bucket = route_defs_by_file.setdefault(clean_path, [])
    if any(existing == clean_tokens for existing in bucket):
        return False
    bucket.append(clean_tokens)
    return True


def _add_topology_edge(
    adjacency: dict[str, dict[str, dict[str, object]]],
    left: str,
    right: str,
    *,
    weight: float,
    reason: str,
    extra: dict[str, object] | None = None,
) -> None:
    left_clean = _normalize_search_path(left)
    right_clean = _normalize_search_path(right)
    if not left_clean or not right_clean or left_clean == right_clean:
        return
    for source, target in ((left_clean, right_clean), (right_clean, left_clean)):
        bucket = adjacency.setdefault(source, {})
        previous = bucket.get(target)
        if previous is None or float(previous.get("weight") or 0.0) < float(weight):
            payload = {
                "path": target,
                "weight": round(float(weight), 4),
                "reason": reason,
            }
            if extra:
                payload.update({str(key): value for key, value in extra.items()})
            bucket[target] = payload


def build_repo_topology_graph(
    repo_root: str,
    *,
    prompt: str = "",
    desired_roles: set[str] | None = None,
    limit: int = 120,
    neighbor_limit: int = 6,
) -> list[dict[str, object]]:
    repo = Path(repo_root)
    if not repo.exists():
        return []

    ignored_dirs = {
        "node_modules",
        ".git",
        "dist",
        "build",
        "memla_reports",
        ".memla",
        "proof",
        "frozen",
        ".next",
        ".turbo",
        ".venv",
        "venv",
        ".pytest_cache",
        "coverage",
        "logs",
    }
    prompt_tokens = tokenize_text(prompt)
    desired_role_set = set(desired_roles or set())
    file_texts: dict[str, str] = {}
    file_roles: dict[str, set[str]] = {}
    file_tokens: dict[str, set[str]] = {}
    file_content_tokens: dict[str, set[str]] = {}
    file_set: set[str] = set()
    module_index: dict[str, set[str]] = {}
    symbol_index: dict[str, set[str]] = {}
    route_defs_by_file: dict[str, list[set[str]]] = {}
    import_aliases_by_file: dict[str, dict[str, str]] = {}
    js_import_aliases_by_file: dict[str, dict[str, str]] = {}
    include_calls_by_file: dict[str, list[dict[str, object]]] = {}
    command_specs_by_file: dict[str, list[dict[str, object]]] = {}
    command_tokens_by_file: dict[str, set[str]] = {}

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        lowered_rel = rel.lower()
        if _should_skip_repo_index_file(path, rel):
            continue
        if "examples/testing/results/" in lowered_rel:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 120_000:
            text = text[:120_000]
        clean_rel = _normalize_search_path(rel)
        file_set.add(clean_rel)
        file_texts[clean_rel] = text
        file_roles[clean_rel] = infer_file_roles(clean_rel)
        file_tokens[clean_rel] = tokenize_path(clean_rel)
        file_content_tokens[clean_rel] = tokenize_text(text)
        route_defs_by_file[clean_rel] = _extract_route_definitions(text)
        import_aliases_by_file[clean_rel] = _extract_python_import_aliases(text)
        js_import_aliases_by_file[clean_rel] = _extract_js_import_aliases(text)
        include_calls_by_file[clean_rel] = _extract_router_include_calls(text)
        command_specs_by_file[clean_rel] = _extract_cli_command_specs(text)
        for alias in _module_aliases_for_path(clean_rel):
            module_index.setdefault(alias, set()).add(clean_rel)
        for router_symbol in _extract_router_symbols(text):
            symbol_index.setdefault(router_symbol, set()).add(clean_rel)
            symbol_index.setdefault(router_symbol.lower(), set()).add(clean_rel)
        for symbol in _extract_python_defined_symbols(text):
            symbol_index.setdefault(symbol, set()).add(clean_rel)
            symbol_index.setdefault(symbol.lower(), set()).add(clean_rel)
        for symbol in _extract_js_defined_symbols(text):
            symbol_index.setdefault(symbol, set()).add(clean_rel)
            symbol_index.setdefault(symbol.lower(), set()).add(clean_rel)

    effective_route_defs_by_file: dict[str, list[set[str]]] = {
        path: [set(route_def) for route_def in route_defs]
        for path, route_defs in route_defs_by_file.items()
    }
    effective_router_dependency_refs: dict[str, set[str]] = {path: set() for path in file_set}

    for _ in range(3):
        changed = False
        for rel, include_calls in include_calls_by_file.items():
            import_aliases = import_aliases_by_file.get(rel, {})
            for include_call in include_calls:
                router_ref = str(include_call.get("router_ref") or "").strip()
                prefix_tokens = {
                    str(token).strip()
                    for token in (include_call.get("prefix_tokens") or set())
                    if str(token).strip()
                }
                dependency_refs = {
                    str(token).strip()
                    for token in (include_call.get("dependency_refs") or [])
                    if str(token).strip()
                }
                target_files = _resolve_python_name_targets(
                    router_ref,
                    source_rel=rel,
                    import_aliases=import_aliases,
                    module_index=module_index,
                    symbol_index=symbol_index,
                    file_set=file_set,
                )
                if dependency_refs:
                    effective_router_dependency_refs.setdefault(rel, set()).update(dependency_refs)
                for target in target_files:
                    if dependency_refs:
                        effective_router_dependency_refs.setdefault(target, set()).update(dependency_refs)
                    target_defs = effective_route_defs_by_file.get(target, [])
                    combined_defs = [prefix_tokens | set(route_def) for route_def in target_defs] if target_defs else [set(prefix_tokens)]
                    for combined_def in combined_defs:
                        if _append_route_tokens(effective_route_defs_by_file, rel, combined_def):
                            changed = True
                        if _append_route_tokens(effective_route_defs_by_file, target, combined_def):
                            changed = True
        if not changed:
            break

    adjacency: dict[str, dict[str, dict[str, object]]] = {}
    source_files = [path for path, roles in file_roles.items() if "test_surface" not in roles]

    for rel, text in file_texts.items():
        roles = file_roles.get(rel, set())
        import_aliases = import_aliases_by_file.get(rel, {})
        js_import_aliases = js_import_aliases_by_file.get(rel, {})

        for include_call in include_calls_by_file.get(rel, []):
            router_ref = str(include_call.get("router_ref") or "").strip()
            prefix_tokens = {
                str(token).strip()
                for token in (include_call.get("prefix_tokens") or set())
                if str(token).strip()
            }
            dependency_refs = {
                str(token).strip()
                for token in (include_call.get("dependency_refs") or [])
                if str(token).strip()
            }
            target_files = _resolve_python_name_targets(
                router_ref,
                source_rel=rel,
                import_aliases=import_aliases,
                module_index=module_index,
                symbol_index=symbol_index,
                file_set=file_set,
            )
            for target in target_files:
                include_weight = 0.94 + (min(len(prefix_tokens), 4) * 0.04) + (0.08 if dependency_refs else 0.0)
                _add_topology_edge(adjacency, rel, target, weight=include_weight, reason="router_include")

        for ref in _extract_python_import_refs(text):
            for target in module_index.get(ref, set()):
                _add_topology_edge(adjacency, rel, target, weight=0.96, reason="python_import")

        for ref in _extract_dependency_symbol_refs(text):
            for target in symbol_index.get(ref, set()) | symbol_index.get(ref.lower(), set()):
                _add_topology_edge(adjacency, rel, target, weight=0.88, reason="dependency_symbol")

        for ref in effective_router_dependency_refs.get(rel, set()):
            for target in _resolve_python_name_targets(
                ref,
                source_rel=rel,
                import_aliases=import_aliases,
                module_index=module_index,
                symbol_index=symbol_index,
                file_set=file_set,
            ):
                _add_topology_edge(adjacency, rel, target, weight=1.06, reason="router_dependency")

        for ref in _extract_js_import_refs(text):
            targets = set()
            if ref.startswith("."):
                targets.update(_resolve_relative_import(ref, rel, file_set))
            else:
                targets.update(module_index.get(ref, set()))
            for target in targets:
                _add_topology_edge(adjacency, rel, target, weight=0.92, reason="module_import")

        for command_spec in command_specs_by_file.get(rel, []):
            command_tokens = {
                str(token).strip()
                for token in (command_spec.get("command_tokens") or [])
                if str(token).strip()
            }
            if command_tokens:
                command_tokens_by_file.setdefault(rel, set()).update(command_tokens)
            for handler_ref in command_spec.get("handler_refs") or []:
                targets = _resolve_js_name_targets(
                    str(handler_ref).strip(),
                    source_rel=rel,
                    import_aliases=js_import_aliases,
                    module_index=module_index,
                    symbol_index=symbol_index,
                    file_set=file_set,
                )
                for target in targets:
                    if command_tokens:
                        command_tokens_by_file.setdefault(target, set()).update(command_tokens)
                    command_overlap = len(command_tokens & prompt_tokens)
                    _add_topology_edge(
                        adjacency,
                        rel,
                        target,
                        weight=1.02 + min(command_overlap, 3) * 0.11,
                        reason="command_handler",
                        extra={
                            "command_tokens": sorted(command_tokens),
                            "command": str(command_spec.get("command") or "").strip(),
                        },
                    )

        for route_tokens in _extract_route_refs(text):
            ranked_routes: list[tuple[float, str]] = []
            for target in source_files:
                score = _route_target_score(
                    route_tokens,
                    target,
                    target_route_defs=effective_route_defs_by_file.get(target, []),
                    target_roles=file_roles.get(target, set()),
                )
                if score <= 0.0:
                    continue
                ranked_routes.append((score, target))
            ranked_routes.sort(key=lambda item: (item[0], item[1]), reverse=True)
            for score, target in ranked_routes[:3]:
                _add_topology_edge(adjacency, rel, target, weight=score, reason="route_owner")

        if "test_surface" in roles:
            stem_tokens = tokenize_text(Path(rel).stem) - {"test", "spec", "tests"}
            if stem_tokens:
                ranked_sources: list[tuple[float, str]] = []
                for target in source_files:
                    target_tokens = file_tokens.get(target, set())
                    overlap = len(stem_tokens & target_tokens)
                    if overlap <= 0:
                        continue
                    score = 0.34 + (overlap * 0.2)
                    if {"security_surface", "service_boundary", "contract_boundary"} & file_roles.get(target, set()):
                        score += 0.06
                    ranked_sources.append((score, target))
                ranked_sources.sort(key=lambda item: (item[0], item[1]), reverse=True)
                for score, target in ranked_sources[:3]:
                    _add_topology_edge(adjacency, rel, target, weight=score, reason="test_source_link")

    nodes: list[dict[str, object]] = []
    for path, neighbors in adjacency.items():
        sorted_neighbors = sorted(
            neighbors.values(),
            key=lambda item: (float(item.get("weight") or 0.0), str(item.get("reason") or ""), str(item.get("path") or "")),
            reverse=True,
        )[: max(int(neighbor_limit), 0)]
        if not sorted_neighbors:
            continue
        node_roles = sorted(file_roles.get(path, set()))
        content_overlap = len((file_content_tokens.get(path, set()) - _STOPWORDS) & prompt_tokens)
        command_token_overlap = len(command_tokens_by_file.get(path, set()) & prompt_tokens)
        hub_penalty = _topology_hub_penalty(path, degree=len(sorted_neighbors))
        score = sum(float(item.get("weight") or 0.0) for item in sorted_neighbors[:3])
        score += len((file_tokens.get(path, set()) & prompt_tokens)) * 0.08
        score += len((file_roles.get(path, set()) & desired_role_set)) * 0.18
        score += content_overlap * 0.03
        score += command_token_overlap * 0.22
        score -= hub_penalty
        nodes.append(
            {
                "path": path,
                "roles": node_roles,
                "neighbors": sorted_neighbors,
                "command_tokens": sorted(command_tokens_by_file.get(path, set())),
                "content_overlap": content_overlap,
                "hub_penalty": round(float(hub_penalty), 4),
                "score": round(float(score), 4),
            }
        )

    nodes.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            len(item.get("neighbors") or []),
            str(item.get("path") or ""),
        ),
        reverse=True,
    )
    return nodes[: max(int(limit), 0)]


def score_repo_topology_path(
    path: str,
    repo_topology_graph: list[dict[str, object]] | None,
    *,
    anchor_paths: list[str] | None = None,
    prompt_tokens: set[str] | None = None,
    prompt_roles: set[str] | None = None,
    max_hops: int = 2,
) -> dict[str, object]:
    clean_path = _normalize_search_path(path)
    if not clean_path:
        return {"score": 0.0, "edge_hits": [], "best_walk": []}

    graph_index = {
        str(item.get("path") or "").strip().replace("\\", "/"): item
        for item in (repo_topology_graph or [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    }
    anchor_list = [_normalize_search_path(item) for item in (anchor_paths or []) if _normalize_search_path(item)]
    prompt_role_set = {str(role).strip() for role in (prompt_roles or set()) if str(role).strip()}
    prompt_token_set = set(prompt_tokens or set())
    file_roles = infer_file_roles(clean_path)
    role_alignment = len(file_roles & prompt_role_set)
    token_alignment = len((tokenize_path(clean_path) - _GENERIC_FILE_HINT_TOKENS) & prompt_token_set)
    score = 0.0
    edge_hits: list[str] = []
    best_walk: list[str] = []

    for anchor in anchor_list[:4]:
        if anchor == clean_path:
            continue
        frontier: list[tuple[str, float, list[str]]] = [(anchor, 1.0, [anchor])]
        best_seen: dict[str, float] = {anchor: 1.0}
        for depth in range(max(int(max_hops), 1)):
            next_frontier: list[tuple[str, float, list[str]]] = []
            for current, current_score, walk in frontier:
                current_node = graph_index.get(current) or {}
                neighbors = [
                    dict(item)
                    for item in (current_node.get("neighbors") or [])
                    if isinstance(item, dict)
                ]
                for neighbor in neighbors:
                    target = _normalize_search_path(neighbor.get("path") or "")
                    edge_weight = float(neighbor.get("weight") or 0.0)
                    reason = str(neighbor.get("reason") or "").strip()
                    if not target or edge_weight <= 0.0:
                        continue
                    if target in walk:
                        continue
                    multiplier = 1.0
                    current_roles = infer_file_roles(current)
                    target_roles = infer_file_roles(target)
                    if "test_surface" in current_roles and "test_surface" not in target_roles:
                        multiplier += 0.22
                    if reason in {"python_import", "module_import", "route_owner", "dependency_symbol", "router_include", "router_dependency"}:
                        multiplier += 0.08
                    if reason == "command_handler":
                        multiplier += 0.18
                    if reason == "route_owner" and depth == 0:
                        multiplier += 0.08
                    if reason == "router_dependency":
                        multiplier += 0.16
                    elif reason == "router_include":
                        multiplier += 0.12
                    elif reason == "command_handler":
                        multiplier += 0.1
                    candidate_score = current_score * edge_weight * multiplier * (0.96 - (depth * 0.1))
                    target_hub_penalty = float((graph_index.get(target) or {}).get("hub_penalty") or 0.0)
                    candidate_score = max(candidate_score - target_hub_penalty, 0.0)
                    if candidate_score <= best_seen.get(target, 0.0):
                        continue
                    best_seen[target] = candidate_score
                    next_walk = walk + [target]
                    if target == clean_path:
                        if candidate_score > score:
                            score = candidate_score
                            best_walk = next_walk
                        edge_hits.append(f"{current}:{reason}")
                    if depth + 1 < max(int(max_hops), 1) and candidate_score >= 0.18:
                        next_frontier.append((target, candidate_score, next_walk))
            frontier = next_frontier
            if not frontier:
                break

    score += role_alignment * 0.14
    score += token_alignment * 0.06
    return {
        "score": round(float(score), 4),
        "edge_hits": list(dict.fromkeys(edge_hits)),
        "best_walk": best_walk,
    }


def build_repo_topology_walk_node(
    *,
    repo_family: str,
    repo_topology_graph: list[dict[str, object]] | None = None,
    touched_files: list[str] | None = None,
    prompt: str = "",
    diagnostic_commands: list[str] | None = None,
    realized_constraints: list[str] | set[str] | None = None,
    winning_trades: list[str] | set[str] | None = None,
) -> dict[str, object]:
    touched = _dedupe_preserve([_normalize_search_path(path) for path in (touched_files or []) if _normalize_search_path(path)])
    touched_roles = {path: infer_file_roles(path) for path in touched}
    anchor_files = [path for path in touched if "test_surface" in touched_roles.get(path, set())]
    if not anchor_files:
        anchor_files = touched[:1]
    winning_walks: list[dict[str, object]] = []
    prompt_tokens = tokenize_text(prompt)
    prompt_roles = {
        role
        for path in touched
        for role in touched_roles.get(path, set())
    }
    for anchor in anchor_files[:4]:
        for target in touched[:8]:
            if target == anchor:
                continue
            topology_score = score_repo_topology_path(
                target,
                repo_topology_graph,
                anchor_paths=[anchor],
                prompt_tokens=prompt_tokens,
                prompt_roles=prompt_roles,
                max_hops=2,
            )
            if float(topology_score.get("score") or 0.0) <= 0.0:
                continue
            walk = list(topology_score.get("best_walk") or [])
            if len(walk) < 2:
                continue
            winning_walks.append(
                {
                    "anchor": anchor,
                    "target": target,
                    "score": round(float(topology_score.get("score") or 0.0), 4),
                    "walk": walk,
                    "edge_hits": list(topology_score.get("edge_hits") or []),
                }
            )
    winning_walks.sort(
        key=lambda item: (float(item.get("score") or 0.0), len(item.get("walk") or []), str(item.get("target") or "")),
        reverse=True,
    )
    return {
        "repo_family": str(repo_family or "").strip() or "unknown",
        "prompt": str(prompt or "").strip(),
        "diagnostic_commands": _dedupe_preserve(list(diagnostic_commands or [])),
        "realized_constraints": _dedupe_preserve(list(realized_constraints or [])),
        "winning_trades": _dedupe_preserve(list(winning_trades or [])),
        "anchor_files": anchor_files[:4],
        "target_files": touched[:8],
        "winning_walks": winning_walks[:8],
    }


def score_repo_topology_walk(
    path: str,
    topology_walk_node: dict[str, object] | None,
    *,
    prompt_tokens: set[str] | None = None,
    prompt_roles: set[str] | None = None,
) -> dict[str, object]:
    clean_path = _normalize_search_path(path)
    if not clean_path:
        return {"score": 0.0, "walk_hits": []}
    node = dict(topology_walk_node or {})
    prompt_token_set = set(prompt_tokens or set())
    prompt_role_set = {str(role).strip() for role in (prompt_roles or set()) if str(role).strip()}
    file_roles = infer_file_roles(clean_path)
    best_score = 0.0
    walk_hits: list[str] = []
    for walk in node.get("winning_walks") or []:
        if not isinstance(walk, dict):
            continue
        target = _normalize_search_path(walk.get("target") or "")
        if target != clean_path:
            continue
        score = float(walk.get("score") or 0.0)
        score += len((tokenize_path(clean_path) - _GENERIC_FILE_HINT_TOKENS) & prompt_token_set) * 0.04
        score += len(file_roles & prompt_role_set) * 0.08
        best_score = max(best_score, score)
        walk_hits.extend(str(item) for item in (walk.get("edge_hits") or []) if str(item).strip())
    return {
        "score": round(float(best_score), 4),
        "walk_hits": list(dict.fromkeys(walk_hits)),
    }


def build_repo_map(
    repo_root: str,
    *,
    prompt: str = "",
    predicted_constraints: list[str] | set[str] | None = None,
    desired_roles: set[str] | None = None,
    limit: int = 10,
) -> list[dict[str, object]]:
    repo = Path(repo_root)
    if not repo.exists():
        return []

    prompt_tokens = tokenize_text(prompt)
    predicted_constraint_set = {str(tag).strip() for tag in (predicted_constraints or []) if str(tag).strip()}
    desired_role_set = set(desired_roles or set()) | infer_roles_from_constraints(predicted_constraint_set)
    ignored_dirs = {
        "node_modules",
        ".git",
        "dist",
        "build",
        "memla_reports",
        ".memla",
        "proof",
        "frozen",
        ".next",
        ".turbo",
        ".venv",
        "venv",
        ".pytest_cache",
        "coverage",
        "logs",
    }
    regions: dict[str, dict[str, object]] = {}

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        lowered_rel = rel.lower()
        if _should_skip_repo_index_file(path, rel):
            continue
        if "examples/testing/results/" in lowered_rel:
            continue
        region = _region_key(rel)
        if not region:
            continue
        bucket = regions.setdefault(
            region,
            {
                "region": region,
                "file_count": 0,
                "roles": set(),
                "tokens": set(),
                "sample_files": [],
            },
        )
        bucket["file_count"] = int(bucket.get("file_count") or 0) + 1
        file_roles = infer_file_roles(rel)
        cast_roles = bucket["roles"]
        if isinstance(cast_roles, set):
            cast_roles.update(file_roles)
        cast_tokens = bucket["tokens"]
        if isinstance(cast_tokens, set):
            cast_tokens.update(tokenize_path(rel))
        sample_files = bucket["sample_files"]
        if isinstance(sample_files, list) and rel not in sample_files and len(sample_files) < 4:
            sample_files.append(rel)

    ranked: list[dict[str, object]] = []
    for bucket in regions.values():
        region = str(bucket.get("region") or "")
        file_count = int(bucket.get("file_count") or 0)
        region_roles = {str(role).strip() for role in (bucket.get("roles") or set()) if str(role).strip()}
        region_tokens = {str(token).strip() for token in (bucket.get("tokens") or set()) if str(token).strip()}
        non_supporting_roles = region_roles - _PRECISE_SUPPORTING_ROLES
        desired_non_supporting_roles = desired_role_set - _PRECISE_SUPPORTING_ROLES
        role_overlap = len(non_supporting_roles & desired_non_supporting_roles)
        supporting_role_overlap = len((region_roles & _PRECISE_SUPPORTING_ROLES) & desired_role_set)
        token_overlap = len(region_tokens & prompt_tokens)
        security_bonus = 0.0
        if "auth_session_integrity" in predicted_constraint_set and (
            "security_surface" in region_roles or "/auth" in region or "/security" in region
        ):
            security_bonus += 0.72
        if "middleware_interception" in predicted_constraint_set and (
            "service_boundary" in region_roles or "middleware" in region_tokens or "handler" in region_tokens
        ):
            security_bonus += 0.48
        if "verification_gate" in predicted_constraint_set and (
            region.startswith("tests") or region.startswith("test") or "test_surface" in region_roles
        ):
            security_bonus += 0.62
        if "cli_command_flow" in predicted_constraint_set and "cli_surface" in region_roles:
            security_bonus += 0.7
        if {"api_contract_preservation", "schema_validation"} & predicted_constraint_set and (
            "contract_boundary" in region_roles or "openapi" in region_tokens or "schema" in region_tokens
        ):
            security_bonus += 0.58
        score = (
            (role_overlap * 1.7)
            + (supporting_role_overlap * 0.45)
            + (token_overlap * 0.42)
            + (min(file_count, 8) * 0.08)
            + security_bonus
        )
        if region_roles and region_roles <= _PRECISE_SUPPORTING_ROLES and role_overlap == 0 and supporting_role_overlap == 0 and token_overlap == 0:
            score -= 1.2
        if (
            "cli_surface" in region_roles
            and "cli_surface" not in desired_role_set
            and "cli_command_flow" not in predicted_constraint_set
            and token_overlap == 0
        ):
            score -= 1.4
        if (
            "dependency_manifest" in region_roles
            and "dependency_manifest" not in desired_role_set
            and token_overlap == 0
        ):
            score -= 1.05
        if (
            "test_surface" in region_roles
            and "test_surface" not in desired_role_set
            and "verification_gate" not in predicted_constraint_set
            and token_overlap == 0
        ):
            score -= 0.65
        ranked.append(
            {
                "region": region,
                "file_count": file_count,
                "roles": sorted(region_roles),
                "sample_files": list(bucket.get("sample_files") or []),
                "score": round(float(score), 4),
            }
        )

    ranked.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            int(item.get("file_count") or 0),
            len(item.get("roles") or []),
            str(item.get("region") or ""),
        ),
        reverse=True,
    )
    return ranked[: max(int(limit), 0)]


def build_repo_search_path_node(
    *,
    repo_family: str,
    prompt: str,
    repo_map: list[dict[str, object]] | None = None,
    diagnostic_commands: list[str] | None = None,
    realized_constraints: list[str] | set[str] | None = None,
    winning_trades: list[str] | set[str] | None = None,
    touched_files: list[str] | None = None,
) -> dict[str, object]:
    repo_regions = [dict(item) for item in (repo_map or []) if isinstance(item, dict)]
    selected_regions = repo_regions[:4]
    selected_region_names = [str(item.get("region") or "").strip() for item in selected_regions if str(item.get("region") or "").strip()]
    selected_roles = sorted(
        {
            str(role).strip()
            for item in selected_regions
            for role in (item.get("roles") or [])
            if str(role).strip()
        }
    )
    final_files = _dedupe_preserve([_normalize_search_path(path) for path in (touched_files or []) if _normalize_search_path(path)])
    final_regions = _dedupe_preserve([_region_key(path) for path in final_files if _region_key(path)])
    hit_regions = [region for region in final_regions if region in selected_region_names]
    region_recall = round(len(hit_regions) / max(len(final_regions), 1), 4) if final_regions else 0.0
    diagnostic_command_list = _dedupe_preserve(list(diagnostic_commands or []))
    realized_constraint_list = _dedupe_preserve(list(realized_constraints or []))
    winning_trade_list = _dedupe_preserve(list(winning_trades or []))
    return {
        "repo_family": str(repo_family or "").strip() or "unknown",
        "prompt": str(prompt or "").strip(),
        "diagnostic_commands": diagnostic_command_list,
        "realized_constraints": realized_constraint_list,
        "winning_trades": winning_trade_list,
        "selected_regions": selected_regions,
        "selected_region_names": selected_region_names,
        "selected_roles": selected_roles,
        "final_regions": final_regions,
        "final_files": final_files,
        "hit_regions": hit_regions,
        "region_recall": region_recall,
    }


def score_repo_search_path(
    path: str,
    repo_search_path_node: dict[str, object] | None,
    *,
    prompt_roles: set[str] | None = None,
    prompt_constraints: set[str] | None = None,
) -> dict[str, object]:
    node = dict(repo_search_path_node or {})
    clean_path = _normalize_search_path(path)
    if not clean_path:
        return {"score": 0.0, "stage_hits": []}
    file_roles = infer_file_roles(clean_path)
    region_key = _region_key(clean_path)
    selected_regions = [dict(item) for item in (node.get("selected_regions") or []) if isinstance(item, dict)]
    selected_roles = {str(role).strip() for role in (node.get("selected_roles") or []) if str(role).strip()}
    realized_constraints = {str(tag).strip() for tag in (node.get("realized_constraints") or []) if str(tag).strip()}
    prompt_role_set = {str(role).strip() for role in (prompt_roles or set()) if str(role).strip()}
    prompt_constraint_set = {str(tag).strip() for tag in (prompt_constraints or set()) if str(tag).strip()}

    region_bonus = 0.0
    stage_hits: list[str] = []
    for index, region in enumerate(selected_regions[:4]):
        region_name = str(region.get("region") or "").strip()
        if not region_name:
            continue
        if clean_path == region_name or clean_path.startswith(region_name.rstrip("/") + "/"):
            region_bonus = max(
                region_bonus,
                max(float(region.get("score") or 0.0), 0.0) * max(0.42, 1.0 - (index * 0.14)),
            )
            stage_hits.append(f"region:{region_name}")
    role_overlap = len(file_roles & (selected_roles | prompt_role_set))
    if role_overlap:
        stage_hits.append("role")
    constraint_alignment = len(prompt_constraint_set & realized_constraints)
    if constraint_alignment:
        stage_hits.append("constraint")
    score = region_bonus + (role_overlap * 0.28) + (constraint_alignment * 0.12)
    return {"score": round(float(score), 4), "stage_hits": list(dict.fromkeys(stage_hits))}


def score_file_search_warmth(
    path: str,
    file_search_node: dict[str, object] | None,
    *,
    prompt_roles: set[str] | None = None,
    prompt_constraints: set[str] | None = None,
    prompt_transmutations: set[str] | None = None,
) -> dict[str, object]:
    node = dict(file_search_node or {})
    clean_path = _normalize_search_path(path)
    if not clean_path:
        return {"score": 0.0, "stage_hits": []}
    exact_files = {str(item).strip() for item in (node.get("resolved_files") or []) if str(item).strip()}
    resolved_roles = {str(item).strip() for item in (node.get("resolved_roles") or []) if str(item).strip()}
    diagnostic_signals = {str(item).strip() for item in (node.get("diagnostic_signals") or []) if str(item).strip()}
    realized_constraints = {str(item).strip() for item in (node.get("realized_constraints") or []) if str(item).strip()}
    winning_trades = {str(item).strip() for item in (node.get("winning_trades") or []) if str(item).strip()}
    prompt_role_set = {str(item).strip() for item in (prompt_roles or set()) if str(item).strip()}
    prompt_constraint_set = {str(item).strip() for item in (prompt_constraints or set()) if str(item).strip()}
    prompt_transmutation_set = {str(item).strip() for item in (prompt_transmutations or set()) if str(item).strip()}
    file_roles = infer_file_roles(clean_path)
    role_hit = len(file_roles & resolved_roles) / max(len(resolved_roles), 1) if resolved_roles else 0.0
    directory_weights = {
        str(item.get("path") or "").strip().replace("\\", "/"): float(item.get("weight") or 0.0)
        for item in (node.get("directory_hints") or [])
        if str(item.get("path") or "").strip()
    }
    token_weights = {
        str(item.get("token") or "").strip(): float(item.get("weight") or 0.0)
        for item in (node.get("token_hints") or [])
        if str(item.get("token") or "").strip()
    }
    exact_hit = 1.0 if clean_path in exact_files else 0.0
    directory_hit = 0.0
    for prefix in _path_prefixes(clean_path):
        directory_hit = max(directory_hit, float(directory_weights.get(prefix, 0.0)))
    basename_tokens = tokenize_text(Path(clean_path).stem) | tokenize_text(_expand_identifier(Path(clean_path).stem))
    path_tokens = _path_hint_tokens(clean_path)
    token_hit = min(
        1.0,
        sum(token_weights.get(token, 0.0) for token in basename_tokens)
        + (sum(token_weights.get(token, 0.0) for token in (path_tokens - basename_tokens)) * 0.45),
    )
    relevance = 0.18
    if prompt_role_set & resolved_roles:
        relevance += 0.2
    if prompt_constraint_set & (diagnostic_signals | realized_constraints):
        relevance += 0.24
    if prompt_transmutation_set & winning_trades:
        relevance += 0.24
    if exact_hit == 0.0 and directory_hit == 0.0 and token_hit == 0.0 and role_hit == 0.0:
        return {"score": 0.0, "stage_hits": []}
    warmth = (role_hit * 0.34) + (directory_hit * 0.42) + (token_hit * 0.28) + (exact_hit * 1.05)
    score = max(relevance, 0.18) * warmth
    stage_hits: list[str] = []
    if role_hit > 0:
        stage_hits.append("role")
    if directory_hit > 0:
        stage_hits.append("directory")
    if token_hit > 0:
        stage_hits.append("token")
    if exact_hit > 0:
        stage_hits.append("exact")
    return {
        "score": round(float(score), 4),
        "stage_hits": stage_hits,
        "components": {
            "role": round(float(role_hit), 4),
            "directory": round(float(directory_hit), 4),
            "token": round(float(token_hit), 4),
            "exact": round(float(exact_hit), 4),
            "relevance": round(float(relevance), 4),
        },
    }


def build_constraint_trade_node(
    *,
    repo_family: str,
    predicted_constraints: list[str] | set[str],
    realized_constraints: list[str] | set[str],
    predicted_transmutations: list[str] | None = None,
    diagnostic_commands: list[str] | None = None,
    touched_files: list[str] | None = None,
    role_targets: list[str] | None = None,
) -> dict[str, object]:
    trade_learning = attribute_trade_success(
        predicted_constraints=predicted_constraints,
        realized_constraints=realized_constraints,
        predicted_transmutations=predicted_transmutations,
        diagnostic_commands=diagnostic_commands,
        touched_files=touched_files,
        role_targets=role_targets,
    )
    predicted_tags = _dedupe_preserve(list(predicted_constraints or []))
    realized_tags = _dedupe_preserve(list(realized_constraints or []))
    return {
        "repo_family": str(repo_family or "").strip() or "unknown",
        "predicted_constraints": list(predicted_tags),
        "realized_constraints": list(realized_tags),
        "predicted_constraint_tensions": infer_constraint_tensions(predicted_tags),
        "realized_constraint_tensions": infer_constraint_tensions(realized_tags),
        "diagnostic_commands": list(trade_learning["diagnostic_commands"]),
        "diagnostic_signals": list(trade_learning["diagnostic_signals"]),
        "predicted_transmutations": list(trade_learning["predicted_transmutations"]),
        "winning_trades": list(trade_learning["winning_trades"]),
        "confirmed_trade_predictions": list(trade_learning["confirmed_trade_predictions"]),
        "missed_trade_predictions": list(trade_learning["missed_trade_predictions"]),
        "false_trade_predictions": list(trade_learning["false_trade_predictions"]),
        "resolved_files": _dedupe_preserve(list(touched_files or [])),
        "resolved_roles": list(trade_learning["resolved_roles"]),
        "trade_success_attribution": list(trade_learning["trade_success_attribution"]),
    }


def build_hypothesis_swarm(
    text: str,
    *,
    repo_family: str = "",
    paths: list[str] | None = None,
    commands: list[str] | None = None,
    candidate_constraints: list[str] | None = None,
    candidate_transmutations: list[str] | None = None,
    limit: int = 5,
) -> list[dict[str, object]]:
    repo_family_clean = str(repo_family or "").strip() or "unknown"
    base_constraints = predict_constraint_tags(
        text,
        repo_family=repo_family_clean,
        paths=paths,
        commands=commands,
        candidate_constraints=candidate_constraints,
    )
    base_constraint_set = {str(tag).strip() for tag in base_constraints if str(tag).strip()}
    base_roles = infer_prompt_roles(text) | infer_roles_from_constraints(base_constraint_set)
    diagnostic_signals = infer_constraint_tags("", [], commands or [])
    candidate_constraint_set = {str(tag).strip() for tag in (candidate_constraints or []) if str(tag).strip()}
    candidate_transmutation_set = {
        str(item).strip() for item in (candidate_transmutations or summarize_transmutations(base_constraints)) if str(item).strip()
    }

    hypotheses: list[dict[str, object]] = []
    for spec in _HYPOTHESIS_AGENT_SPECS:
        families = {str(item).strip() for item in (spec.get("repo_families") or set()) if str(item).strip()}
        favored_constraints = {str(item).strip() for item in (spec.get("constraints") or set()) if str(item).strip()}
        favored_roles = {str(item).strip() for item in (spec.get("roles") or set()) if str(item).strip()}
        diagnostic_focus = {str(item).strip() for item in (spec.get("diagnostic_focus") or set()) if str(item).strip()}
        excluded_constraints = {
            str(item).strip() for item in (spec.get("exclude_constraints") or set()) if str(item).strip()
        }
        excluded_roles = {str(item).strip() for item in (spec.get("exclude_roles") or set()) if str(item).strip()}

        family_fit = repo_family_clean in families or ("general" in families and repo_family_clean == "unknown")
        constraint_overlap = sorted(favored_constraints & (base_constraint_set | candidate_constraint_set))
        role_overlap = sorted(favored_roles & base_roles)
        diagnostic_overlap = sorted(diagnostic_focus & diagnostic_signals)
        score = 0.12
        if family_fit:
            score += 0.55
        score += len(constraint_overlap) * 0.42
        score += len(role_overlap) * 0.2
        score += len(diagnostic_overlap) * 0.18

        predicted_constraints = constraint_overlap
        if not predicted_constraints and family_fit:
            predicted_constraints = sorted(favored_constraints & (base_constraint_set or candidate_constraint_set))[:2]
        if not predicted_constraints and family_fit and favored_constraints:
            predicted_constraints = sorted(favored_constraints)[:1]
        predicted_roles = sorted(favored_roles | infer_roles_from_constraints(predicted_constraints))
        predicted_negative_constraints = sorted(
            tag for tag in excluded_constraints if tag not in predicted_constraints
        )[:3]
        predicted_negative_roles = sorted(
            role
            for role in (excluded_roles | infer_roles_from_constraints(predicted_negative_constraints))
            if role not in predicted_roles
        )[:4]
        predicted_transmutations = [
            text for text in summarize_transmutations(predicted_constraints) if text in candidate_transmutation_set or not candidate_transmutation_set
        ] or summarize_transmutations(predicted_constraints)
        if not predicted_constraints and not role_overlap and not diagnostic_overlap and not family_fit:
            continue
        hypotheses.append(
            {
                "id": str(spec["id"]),
                "label": str(spec["label"]),
                "style": str(spec.get("style") or "structural"),
                "score": round(float(score), 4),
                "repo_family_fit": bool(family_fit),
                "predicted_constraints": list(predicted_constraints),
                "predicted_roles": list(predicted_roles),
                "negative_constraints": list(predicted_negative_constraints),
                "negative_roles": list(predicted_negative_roles),
                "predicted_transmutations": list(predicted_transmutations[:4]),
                "diagnostic_focus": list(sorted(diagnostic_focus)),
                "target_paths": [],
                "lifecycle_status": "candidate",
                "fitness": 0.0,
            }
        )

    hypotheses.extend(
        _build_precise_file_hypotheses(
            text,
            paths=paths,
            commands=commands,
            base_constraints=base_constraints,
            candidate_transmutations=candidate_transmutation_set,
            limit=min(max(int(limit), 0), 3),
        )
    )

    return _diversify_hypotheses(hypotheses, limit=max(int(limit), 0))


def _discover_repo_probe_commands(repo_root: str) -> list[str]:
    repo = Path(repo_root)
    if not repo.exists():
        return []

    commands: list[str] = []
    package_json = repo / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        scripts = payload.get("scripts") or {}
        if isinstance(scripts, dict):
            for script_name in ("test", "build", "lint"):
                if script_name in scripts:
                    commands.append(f"npm run {script_name}" if script_name != "test" else "npm test")

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        project = payload.get("project") or {}
        scripts = project.get("scripts") or {}
        if isinstance(scripts, dict) and scripts:
            if "pytest" not in commands:
                commands.append("pytest")
        if (repo / "tests").exists() or (repo / "test").exists():
            if "pytest" not in commands:
                commands.append("pytest")
    elif (repo / "tests").exists() or (repo / "test").exists():
        if any(path.suffix == ".py" for path in repo.rglob("*.py")) and "pytest" not in commands:
            commands.append("pytest")

    return commands


def _hypothesis_probe_commands(
    *,
    hypothesis: dict[str, object],
    available_commands: list[str],
) -> list[str]:
    predicted_constraints = {str(tag).strip() for tag in (hypothesis.get("predicted_constraints") or []) if str(tag).strip()}
    predicted_roles = {str(role).strip() for role in (hypothesis.get("predicted_roles") or []) if str(role).strip()}
    commands_lower = {command.lower(): command for command in available_commands}
    selected: list[str] = []

    def _maybe_add(name: str) -> None:
        lowered = name.lower()
        if lowered in commands_lower:
            command = commands_lower[lowered]
            if command not in selected:
                selected.append(command)

    if "verification_gate" in predicted_constraints or "test_surface" in predicted_roles:
        _maybe_add("npm test")
        _maybe_add("pytest")
    if {
        "dependency_upgrade",
        "api_contract_preservation",
        "schema_validation",
        "middleware_interception",
    } & predicted_constraints:
        _maybe_add("npm run build")
        _maybe_add("npm run lint")
    if "cli_command_flow" in predicted_constraints and not selected:
        _maybe_add("npm test")
        _maybe_add("pytest")

    return selected[:3]


def calibrate_hypothesis_swarm(
    hypotheses: list[dict[str, object]] | None,
    *,
    repo_root: str,
    prompt: str,
    repo_family: str = "",
    paths: list[str] | None = None,
    commands: list[str] | None = None,
) -> list[dict[str, object]]:
    source = [dict(item) for item in (hypotheses or []) if isinstance(item, dict)]
    if not source:
        return []

    repo_root_clean = str(repo_root or "").strip()
    repo_family_clean = str(repo_family or infer_repo_family(repo_root_clean)).strip() or "unknown"
    prompt_text = str(prompt or "")
    provided_paths = [_normalize_search_path(path) for path in (paths or []) if _normalize_search_path(path)]
    available_commands = _dedupe_preserve(list(commands or []) + _discover_repo_probe_commands(repo_root_clean))
    role_probe_cache: dict[str, float] = {}
    negative_role_probe_cache: dict[str, float] = {}

    def _role_support(role: str) -> float:
        clean_role = str(role or "").strip()
        if not clean_role:
            return 0.0
        if clean_role in role_probe_cache:
            return role_probe_cache[clean_role]
        support = 0.0
        for path in provided_paths:
            if clean_role in infer_file_roles(path):
                support = 1.0
                break
        if support == 0.0 and repo_root_clean:
            matches = scan_repo_role_matches(repo_root_clean, prompt_text, {clean_role}, limit=4)
            if matches:
                support = min(1.0, 0.42 + (float(matches[0].score) * 0.12))
        role_probe_cache[clean_role] = round(float(support), 4)
        return role_probe_cache[clean_role]

    def _negative_role_support(role: str) -> float:
        clean_role = str(role or "").strip()
        if not clean_role:
            return 0.0
        if clean_role in negative_role_probe_cache:
            return negative_role_probe_cache[clean_role]
        presence = _role_support(clean_role)
        score = max(0.0, 1.0 - presence)
        negative_role_probe_cache[clean_role] = round(float(score), 4)
        return negative_role_probe_cache[clean_role]

    calibrated: list[dict[str, object]] = []
    for raw in source:
        predicted_roles = {str(role).strip() for role in (raw.get("predicted_roles") or []) if str(role).strip()}
        negative_roles = {str(role).strip() for role in (raw.get("negative_roles") or []) if str(role).strip()}
        target_paths = {_normalize_search_path(path) for path in (raw.get("target_paths") or []) if _normalize_search_path(path)}
        probe_commands = _hypothesis_probe_commands(hypothesis=raw, available_commands=available_commands)

        family_probe = 1.0 if (bool(raw.get("repo_family_fit")) or repo_family_clean == "unknown") else 0.0
        role_probe = (
            sum(_role_support(role) for role in predicted_roles) / max(len(predicted_roles), 1)
            if predicted_roles
            else 0.0
        )
        negative_role_probe = (
            sum(_negative_role_support(role) for role in negative_roles) / max(len(negative_roles), 1)
            if negative_roles
            else 0.0
        )
        path_probe = (
            sum(1.0 for path in target_paths if (Path(repo_root_clean) / path).exists()) / max(len(target_paths), 1)
            if target_paths and repo_root_clean
            else 0.0
        )
        command_probe = len(probe_commands) / max(min(len(available_commands), 2), 1) if probe_commands else 0.0

        probe_score = (
            family_probe * 0.14
            + role_probe * 0.42
            + negative_role_probe * 0.12
            + path_probe * 0.16
            + command_probe * 0.24
        )
        calibrated_score = float(raw.get("score") or 0.0) + (probe_score * 0.95)
        probe_summary = {
            "family_probe": round(float(family_probe), 4),
            "role_probe": round(float(role_probe), 4),
            "negative_role_probe": round(float(negative_role_probe), 4),
            "path_probe": round(float(path_probe), 4),
            "command_probe": round(float(command_probe), 4),
        }
        probe_plan = {
            "probe_commands": list(probe_commands),
            "available_commands": list(available_commands[:4]),
            "probe_summary": probe_summary,
        }

        calibrated.append(
            {
                **raw,
                "probe_plan": probe_plan,
                "probe_commands": list(probe_commands),
                "probe_score": round(float(probe_score), 4),
                "calibrated_score": round(float(calibrated_score), 4),
            }
        )

    calibrated.sort(
        key=lambda item: (
            float(item.get("calibrated_score") or 0.0),
            float(item.get("selection_score") or item.get("score") or 0.0),
            float(item.get("novelty_score") or 0.0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return calibrated


def evaluate_hypothesis_swarm(
    hypotheses: list[dict[str, object]] | None,
    *,
    realized_constraints: list[str] | set[str],
    winning_trades: list[str] | set[str] | None = None,
    touched_files: list[str] | None = None,
) -> list[dict[str, object]]:
    realized_constraint_set = {str(tag).strip() for tag in realized_constraints if str(tag).strip()}
    winning_trade_set = {str(item).strip() for item in (winning_trades or []) if str(item).strip()}
    resolved_roles = {role for path in (touched_files or []) for role in infer_file_roles(path)}
    touched_path_set = {str(path).strip().replace("\\", "/") for path in (touched_files or []) if str(path).strip()}
    evaluated: list[dict[str, object]] = []

    for raw in hypotheses or []:
        predicted_constraints = {
            str(tag).strip() for tag in (raw.get("predicted_constraints") or []) if str(tag).strip()
        }
        predicted_trades = {
            str(item).strip() for item in (raw.get("predicted_transmutations") or []) if str(item).strip()
        }
        predicted_roles = {
            str(role).strip() for role in (raw.get("predicted_roles") or []) if str(role).strip()
        }
        negative_constraints = {
            str(tag).strip() for tag in (raw.get("negative_constraints") or []) if str(tag).strip()
        }
        negative_roles = {
            str(role).strip() for role in (raw.get("negative_roles") or []) if str(role).strip()
        }
        target_paths = {
            str(path).strip().replace("\\", "/") for path in (raw.get("target_paths") or []) if str(path).strip()
        }
        assessment = assess_constraint_predictions(predicted_constraints, realized_constraint_set)
        confirmed_trades = sorted(predicted_trades & winning_trade_set)
        confirmed_roles = sorted(predicted_roles & resolved_roles)
        confirmed_paths = sorted(target_paths & touched_path_set)
        confirmed_negative_constraints = sorted(negative_constraints - realized_constraint_set)
        violated_negative_constraints = sorted(negative_constraints & realized_constraint_set)
        confirmed_negative_roles = sorted(negative_roles - resolved_roles)
        violated_negative_roles = sorted(negative_roles & resolved_roles)
        trade_precision = len(confirmed_trades) / max(len(predicted_trades), 1) if predicted_trades else 0.0
        role_precision = len(confirmed_roles) / max(len(predicted_roles), 1) if predicted_roles else 0.0
        path_precision = len(confirmed_paths) / max(len(target_paths), 1) if target_paths else 0.0
        negative_constraint_precision = (
            len(confirmed_negative_constraints) / max(len(negative_constraints), 1) if negative_constraints else 0.0
        )
        negative_role_precision = len(confirmed_negative_roles) / max(len(negative_roles), 1) if negative_roles else 0.0
        fitness = (
            float(assessment["f1"]) * 0.5
            + float(trade_precision) * 0.2
            + float(role_precision) * 0.1
            + float(path_precision) * 0.15
            + float(negative_constraint_precision) * 0.15
            + float(negative_role_precision) * 0.05
        )
        alive = bool(
            assessment["confirmed"]
            or confirmed_trades
            or confirmed_paths
            or confirmed_negative_constraints
            or fitness >= 0.35
        )
        evaluated.append(
            {
                **raw,
                "lifecycle_status": "alive" if alive else "dead",
                "fitness": round(float(fitness), 4),
                "confirmed_constraints": list(assessment["confirmed"]),
                "missed_constraints": list(assessment["missed"]),
                "false_constraints": list(assessment["false_positives"]),
                "confirmed_negative_constraints": list(confirmed_negative_constraints),
                "violated_negative_constraints": list(violated_negative_constraints),
                "confirmed_trades": list(confirmed_trades),
                "confirmed_roles": list(confirmed_roles),
                "confirmed_paths": list(confirmed_paths),
                "confirmed_negative_roles": list(confirmed_negative_roles),
                "violated_negative_roles": list(violated_negative_roles),
            }
        )

    evaluated.sort(
        key=lambda item: (
            item.get("lifecycle_status") == "alive",
            float(item.get("fitness") or 0.0),
            float(item.get("score") or 0.0),
        ),
        reverse=True,
    )
    return evaluated


def _collect_hypothesis_values(
    hypotheses: list[dict[str, object]],
    key: str,
) -> list[str]:
    return sorted(
        {
            str(value).strip()
            for hypothesis in hypotheses
            for value in (hypothesis.get(key) or [])
            if str(value).strip()
        }
    )


def build_hypothesis_coalitions(
    hypotheses: list[dict[str, object]] | None,
    *,
    realized_constraints: list[str] | set[str] | None = None,
    winning_trades: list[str] | set[str] | None = None,
    touched_files: list[str] | None = None,
    max_agents: int = 3,
    max_coalitions: int = 4,
) -> list[dict[str, object]]:
    realized_constraint_set = {str(tag).strip() for tag in (realized_constraints or []) if str(tag).strip()}
    winning_trade_set = {str(item).strip() for item in (winning_trades or []) if str(item).strip()}
    touched_files_clean = _dedupe_preserve(list(touched_files or []))
    resolved_roles = sorted({role for path in touched_files_clean for role in infer_file_roles(path)})

    source = [
        hypothesis
        for hypothesis in (hypotheses or [])
        if str(hypothesis.get("id") or "").strip()
    ]
    if not source:
        return []

    alive = [item for item in source if str(item.get("lifecycle_status") or "").strip().lower() == "alive"]
    viable = alive or source
    viable.sort(
        key=lambda item: (
            float(item.get("fitness") or 0.0),
            float(item.get("score") or 0.0),
            len(item.get("predicted_constraints") or []),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    top_members = viable[: max(int(max_agents), 1)]
    if not top_members:
        return []

    coalition_sizes = [1] if len(top_members) == 1 else list(range(2, min(len(top_members), max(int(max_agents), 1)) + 1))
    coalitions: list[dict[str, object]] = []
    for size in coalition_sizes:
        for combo in combinations(top_members, size):
            members = list(combo)
            agent_ids = [str(item.get("id") or "").strip() for item in members if str(item.get("id") or "").strip()]
            if not agent_ids:
                continue
            predicted_constraints = _collect_hypothesis_values(members, "predicted_constraints")
            predicted_roles = _collect_hypothesis_values(members, "predicted_roles")
            predicted_transmutations = _collect_hypothesis_values(members, "predicted_transmutations")
            target_paths = _collect_hypothesis_values(members, "target_paths")
            styles = _collect_hypothesis_values(members, "style")
            negative_constraints = [
                tag
                for tag in _collect_hypothesis_values(members, "negative_constraints")
                if tag not in predicted_constraints
            ]
            negative_roles = [
                role
                for role in _collect_hypothesis_values(members, "negative_roles")
                if role not in predicted_roles
            ]
            confirmed_constraints = _collect_hypothesis_values(members, "confirmed_constraints") or sorted(
                set(predicted_constraints) & realized_constraint_set
            )
            confirmed_trades = _collect_hypothesis_values(members, "confirmed_trades") or sorted(
                set(predicted_transmutations) & winning_trade_set
            )
            confirmed_roles = _collect_hypothesis_values(members, "confirmed_roles") or sorted(
                set(predicted_roles) & set(resolved_roles)
            )
            confirmed_negative_constraints = _collect_hypothesis_values(members, "confirmed_negative_constraints")
            confirmed_negative_roles = _collect_hypothesis_values(members, "confirmed_negative_roles")
            confirmed_paths = _collect_hypothesis_values(members, "confirmed_paths")
            shared_constraints = sorted(
                set.intersection(
                    *[
                        {str(tag).strip() for tag in (item.get("predicted_constraints") or []) if str(tag).strip()}
                        for item in members
                    ]
                )
            ) if len(members) > 1 else list(predicted_constraints)
            shared_roles = sorted(
                set.intersection(
                    *[
                        {str(role).strip() for role in (item.get("predicted_roles") or []) if str(role).strip()}
                        for item in members
                    ]
                )
            ) if len(members) > 1 else list(predicted_roles)
            avg_fitness = sum(float(item.get("fitness") or 0.0) for item in members) / max(len(members), 1)
            avg_score = sum(float(item.get("score") or 0.0) for item in members) / max(len(members), 1)
            normalized_signal = min(max(avg_fitness, avg_score / 1.6), 1.0)
            constraint_coverage = len(confirmed_constraints) / max(len(realized_constraint_set), 1) if realized_constraint_set else 0.0
            trade_coverage = len(confirmed_trades) / max(len(winning_trade_set), 1) if winning_trade_set else 0.0
            role_coverage = len(confirmed_roles) / max(len(resolved_roles), 1) if resolved_roles else 0.0
            support_score = (
                (normalized_signal * 0.52)
                + (constraint_coverage * 0.18)
                + (trade_coverage * 0.14)
                + (role_coverage * 0.08)
                + (min(len(shared_constraints), 2) * 0.04)
                + (min(len(shared_roles), 2) * 0.02)
                + (max(len(agent_ids) - 1, 0) * 0.05)
            )
            coalitions.append(
                {
                    "id": "+".join(sorted(agent_ids)),
                    "label": " + ".join(
                        str(item.get("label") or item.get("id") or "").strip() for item in members if str(item.get("label") or item.get("id") or "").strip()
                    ),
                    "member_count": len(agent_ids),
                    "agent_ids": list(sorted(agent_ids)),
                    "styles": list(styles),
                    "avg_fitness": round(float(avg_fitness), 4),
                    "avg_score": round(float(avg_score), 4),
                    "support_score": round(float(support_score), 4),
                    "predicted_constraints": list(predicted_constraints),
                    "shared_constraints": list(shared_constraints),
                    "predicted_roles": list(predicted_roles),
                    "shared_roles": list(shared_roles),
                    "target_paths": list(target_paths),
                    "negative_constraints": list(negative_constraints),
                    "negative_roles": list(negative_roles),
                    "predicted_transmutations": list(predicted_transmutations),
                    "confirmed_constraints": list(confirmed_constraints),
                    "confirmed_negative_constraints": list(confirmed_negative_constraints),
                    "confirmed_trades": list(confirmed_trades),
                    "confirmed_roles": list(confirmed_roles),
                    "confirmed_paths": list(confirmed_paths),
                    "confirmed_negative_roles": list(confirmed_negative_roles),
                    "resolved_files": list(touched_files_clean),
                    "resolved_roles": list(resolved_roles),
                }
            )

    coalitions.sort(
        key=lambda item: (
            float(item.get("support_score") or 0.0),
            int(item.get("member_count") or 0),
            float(item.get("avg_fitness") or 0.0),
            str(item.get("id") or ""),
        ),
        reverse=True,
    )
    return coalitions[: max(int(max_coalitions), 0)]


def build_hypothesis_swarm_node(
    *,
    repo_family: str,
    hypotheses: list[dict[str, object]] | None,
    realized_constraints: list[str] | set[str],
    winning_trades: list[str] | set[str] | None = None,
    touched_files: list[str] | None = None,
) -> dict[str, object]:
    evaluated = evaluate_hypothesis_swarm(
        hypotheses,
        realized_constraints=realized_constraints,
        winning_trades=winning_trades,
        touched_files=touched_files,
    )
    survivors = [item for item in evaluated if item.get("lifecycle_status") == "alive"]
    dead = [item for item in evaluated if item.get("lifecycle_status") == "dead"]
    coalitions = build_hypothesis_coalitions(
        evaluated,
        realized_constraints=realized_constraints,
        winning_trades=winning_trades,
        touched_files=touched_files,
        max_agents=3,
        max_coalitions=4,
    )
    top_coalitions = coalitions[:2]
    return {
        "repo_family": str(repo_family or "").strip() or "unknown",
        "survivors": survivors,
        "dead_agents": dead,
        "survivor_ids": [str(item.get("id") or "") for item in survivors],
        "dead_agent_ids": [str(item.get("id") or "") for item in dead],
        "coalitions": coalitions,
        "top_coalitions": top_coalitions,
        "top_coalition_ids": [str(item.get("id") or "") for item in top_coalitions],
        "avg_fitness": round(
            sum(float(item.get("fitness") or 0.0) for item in evaluated) / max(len(evaluated), 1),
            4,
        ),
    }


def transmutation_specificity(text: str) -> float:
    tokens = tokenize_text(text)
    if not tokens:
        return 0.1
    specific_tokens = tokens - _GENERIC_TRANSFORMATION_TOKENS
    score = 0.2 + min(len(specific_tokens), 6) * 0.09
    if {"payment", "redirect", "booking", "session", "auth", "oauth", "middleware", "schema", "cli", "openapi"} & tokens:
        score += 0.18
    if "trade one implementation constraint for a more stable verified constraint." in str(text or "").strip().lower():
        score *= 0.45
    return max(0.1, min(score, 1.0))


def infer_repo_family(repo_root: str) -> str:
    repo = Path(repo_root)
    if not repo.exists():
        return "unknown"

    pyproject = repo / "pyproject.toml"
    if pyproject.exists():
        try:
            payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            payload = {}
        deps = " ".join(
            str(item)
            for section in (
                (payload.get("project") or {}).get("dependencies") or [],
                *(((payload.get("project") or {}).get("optional-dependencies") or {}).values()),
            )
            for item in (section if isinstance(section, list) else [section])
        ).lower()
        if any(token in deps for token in ("fastapi", "starlette", "uvicorn", "sqlalchemy")):
            return "python_api"
        if any(token in deps for token in ("click", "typer", "rich", "textual", "prompt_toolkit")):
            return "python_cli"

    package_json = repo / "package.json"
    if package_json.exists():
        try:
            payload = json.loads(package_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        deps = payload.get("dependencies") or {}
        dev_deps = payload.get("devDependencies") or {}
        dep_blob = " ".join(list(deps.keys()) + list(dev_deps.keys())).lower()
        if any(token in dep_blob for token in ("next", "react", "trpc", "prisma", "supabase")):
            return "ts_web_app"
        if any(token in dep_blob for token in ("express", "helmet", "oauth", "passport", "rate-limit", "koa", "nest")):
            return "ts_backend_security"
        if any(token in dep_blob for token in ("commander", "oclif", "yargs", "openapi", "swagger")):
            return "ts_cli_tooling"

    file_blob = " ".join(path.as_posix().lower() for path in repo.rglob("*") if path.is_file())
    if any(token in file_blob for token in ("/middleware", "/routers", "/api/", "openapi", "swagger", "oauth", "auth", "guard")):
        return "backend_security"
    if any(token in file_blob for token in ("/commands", "/cli", "/prompt", "/terminal")):
        return "cli_tooling"
    if any(token in file_blob for token in ("/pages", "/app/", "components", "src/app", "src/pages")):
        return "web_app"
    return "general"


def scan_repo_role_matches(repo_root: str, prompt: str, desired_roles: set[str], *, limit: int = 8) -> list[RepoRoleCandidate]:
    repo = Path(repo_root)
    if not repo.exists():
        return []
    prompt_tokens = tokenize_text(prompt)
    candidates: list[RepoRoleCandidate] = []
    ignored_dirs = {
        "node_modules",
        ".git",
        "dist",
        "build",
        "memla_reports",
        ".memla",
        "proof",
        "frozen",
        ".next",
        ".turbo",
        ".venv",
        "venv",
        ".pytest_cache",
        "coverage",
        "logs",
    }
    asset_words = {"image", "icon", "logo", "asset", "photo", "picture", "tracking", "script"}

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        lowered_rel = rel.lower()
        if _should_skip_repo_index_file(path, rel):
            continue
        if "examples/testing/results/" in lowered_rel:
            continue
        roles = infer_file_roles(rel)
        path_tokens = tokenize_path(rel)
        role_overlap = len(desired_roles & roles)
        prompt_overlap = len(prompt_tokens & path_tokens)
        if role_overlap == 0 and prompt_overlap == 0:
            continue
        score = (role_overlap * 2.2) + (prompt_overlap * 0.9)
        if lowered_rel.endswith(".json") and not lowered_rel.endswith(("package.json", "pyproject.toml", "tsconfig.json", "context7.json", "versions.json")):
            score -= 0.9
        if lowered_rel.startswith("docs/") and "doc" not in prompt_tokens and "documentation" not in prompt_tokens and "version" not in prompt_tokens:
            score -= 0.35
        if lowered_rel.startswith("examples/") and "example" not in prompt_tokens:
            score -= 0.2
        if path.suffix.lower() in _ASSET_SUFFIXES and not (prompt_tokens & asset_words):
            score -= 1.1
        if "public" in {part.lower() for part in path.parts} and not (prompt_tokens & asset_words):
            score -= 0.55
        if "test_surface" in roles and "test" not in prompt_tokens and "verify" not in prompt_tokens:
            score -= 0.45
        candidates.append(RepoRoleCandidate(path=rel, roles=sorted(roles), score=float(score)))

    candidates.sort(key=lambda item: (item.score, len(item.roles), item.path), reverse=True)
    return candidates[: max(int(limit), 0)]
