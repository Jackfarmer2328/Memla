from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
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


@dataclass(frozen=True)
class RepoRoleCandidate:
    path: str
    roles: list[str]
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
    if {"oauth", "auth", "security", "guard", "token", "session"} & tokens:
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


def summarize_constraint_trades(tags: list[str]) -> list[str]:
    tag_set = set(tags)
    trades: list[str] = []
    if {"payment_confirmation", "redirect_return_flow"} <= tag_set:
        trades.append("Trade embedded payment state for redirect-safe confirmation recovery.")
    if {"state_persistence", "booking_state_handshake"} & tag_set:
        trades.append("Trade transient UI state for recoverable session-backed booking state.")
    if "deployment_routing" in tag_set:
        trades.append("Trade strict server routing for client-side SPA fallback.")
    if "dependency_upgrade" in tag_set:
        trades.append("Trade stale dependency stability for updated compatibility plus verification.")
    if "api_contract_preservation" in tag_set:
        trades.append("Trade local implementation freedom for a preserved external contract.")
    if "auth_session_integrity" in tag_set:
        trades.append("Trade permissive request flow for stricter authentication and session integrity.")
    if "middleware_interception" in tag_set:
        trades.append("Trade downstream flexibility for earlier middleware enforcement and validation.")
    if "cli_command_flow" in tag_set:
        trades.append("Trade shell flexibility for a repeatable command-line workflow.")
    if "schema_validation" in tag_set:
        trades.append("Trade loose input handling for stricter schema-driven validation.")
    if "layout_adjustment" in tag_set:
        trades.append("Trade visual compactness for clearer interaction space.")
    if "loading_state_cleanup" in tag_set:
        trades.append("Trade temporary user feedback scaffolding for a cleaner steady-state flow.")
    if not trades and tag_set:
        trades.append("Trade one implementation constraint for a more stable verified constraint.")
    return trades[:4]


def summarize_transmutations(tags: list[str]) -> list[str]:
    return summarize_constraint_trades(tags)


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
    ignored_dirs = {"node_modules", ".git", "dist", "build", ".next", ".turbo", ".venv", "venv", ".pytest_cache", "coverage", "logs"}
    asset_words = {"image", "icon", "logo", "asset", "photo", "picture", "tracking", "script"}

    for path in repo.rglob("*"):
        if not path.is_file():
            continue
        if any(part in ignored_dirs for part in path.parts):
            continue
        rel = path.relative_to(repo).as_posix()
        lowered_rel = rel.lower()
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
