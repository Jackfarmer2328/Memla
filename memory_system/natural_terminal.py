from __future__ import annotations

from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher
import html as html_lib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from typing import Any
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib import request as urllib_request
from urllib.error import URLError

from .distillation.web_policy_bank import (
    distill_web_policy_bank,
    render_web_policy_bank_markdown,
    suggest_web_policy_priors,
)
from .memory.ontology import (
    adjudicate_memory_trace,
    promote_memory_rule,
    record_memory_trace,
)
from .ollama_client import ChatMessage, UniversalLLMClient


SUPPORTED_ACTION_KINDS = {
    "launch_app",
    "open_url",
    "browser_answer_query",
    "browser_new_tab",
    "browser_close_tab",
    "browser_switch_tab",
    "open_search_result",
    "browser_click_index",
    "browser_click_text",
    "browser_read_page",
    "browser_extract_page",
    "browser_extract_cards",
    "browser_rank_cards",
    "browser_compare_cards",
    "browser_search_subject",
    "browser_retry_subject_result",
    "browser_synthesize_evidence",
    "open_path",
    "browser_back",
    "browser_forward",
    "browser_scroll",
    "browser_type_text",
    "browser_submit",
    "browser_wait",
    "browser_screenshot",
    "browser_media_pause",
    "browser_media_play",
    "list_directory",
    "system_info",
    "unsupported",
}

SUPPORTED_SYSTEM_INFO_TOPICS = {"battery", "cpu", "disk", "memory"}

RISKY_TOKENS = {
    "apt",
    "chown",
    "chmod",
    "delete",
    "format",
    "install",
    "kill",
    "pacman",
    "poweroff",
    "reboot",
    "remove",
    "rm ",
    "shutdown",
    "sudo",
    "uninstall",
}

LINUX_OPEN_COMMAND = ["xdg-open"]
MACOS_OPEN_COMMAND = ["open"]
BROWSER_STATE_ENV = "MEMLA_TERMINAL_STATE_PATH"
BROWSER_STATE_FILENAME = "terminal_browser_state.json"
TERMINAL_TRACE_FILENAME = "terminal_transmutation_traces.jsonl"
TERMINAL_LANGUAGE_MEMORY_FILENAME = "terminal_language_memory.jsonl"
TERMINAL_LANGUAGE_RULE_FILENAME = "terminal_language_rules.json"
TERMINAL_MEMORY_ONTOLOGY_FILENAME = "terminal_memory_ontology.json"
DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; MemlaTerminal/1.0; +https://github.com/Jackfarmer2328/Memla-v2)"
GOOGLE_SEARCH_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"
)
PREFERRED_BROWSER_ENV = "MEMLA_BROWSER_APP"


@dataclass(frozen=True)
class TerminalAction:
    kind: str
    target: str
    resolved_target: str = ""
    safe: bool = True
    note: str = ""


@dataclass(frozen=True)
class TerminalPlan:
    prompt: str
    source: str
    actions: list[TerminalAction] = field(default_factory=list)
    needs_confirmation: bool = False
    clarification: str = ""
    residual_constraints: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TerminalExecutionRecord:
    kind: str
    target: str
    status: str
    message: str
    command: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalExecutionResult:
    prompt: str
    plan_source: str
    ok: bool
    records: list[TerminalExecutionRecord] = field(default_factory=list)
    residual_constraints: list[str] = field(default_factory=list)
    browser_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalScoutStep:
    transmutation: str
    status: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalScoutResult:
    prompt: str
    scout_kind: str
    source: str
    ok: bool
    query: str = ""
    goal: str = ""
    requested_limit: int = 0
    inspected_limit: int = 0
    steps: list[TerminalScoutStep] = field(default_factory=list)
    top_results: list[dict[str, Any]] = field(default_factory=list)
    inspected_results: list[dict[str, Any]] = field(default_factory=list)
    best_match: dict[str, Any] = field(default_factory=dict)
    summary: str = ""
    residual_constraints: list[str] = field(default_factory=list)
    browser_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TerminalBenchmarkCase:
    case_id: str
    prompt: str
    expected_actions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BrowserSessionState:
    current_url: str = ""
    page_kind: str = ""
    browser_app: str = ""
    search_engine: str = ""
    search_query: str = ""
    result_urls: list[str] = field(default_factory=list)
    result_cards: list[dict[str, Any]] = field(default_factory=list)
    subject_title: str = ""
    subject_url: str = ""
    subject_summary: str = ""
    research_subject_title: str = ""
    research_subject_url: str = ""
    research_subject_summary: str = ""
    evidence_items: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class TerminalTransmutationCandidate:
    candidate_id: str
    label: str
    rationale: str
    origin: str
    recommended: bool = False
    plan: TerminalPlan = field(default_factory=lambda: TerminalPlan(prompt="", source="candidate"))
    target_preview: str = ""
    expected_outcome: str = ""
    expected_fields: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TerminalStepReport:
    prompt: str
    constraints: dict[str, Any]
    candidates: list[TerminalTransmutationCandidate] = field(default_factory=list)


@dataclass(frozen=True)
class TerminalStepExecution:
    report: TerminalStepReport
    chosen_candidate: TerminalTransmutationCandidate
    result: TerminalExecutionResult
    trace_path: str


APP_SPECS: dict[str, dict[str, Any]] = {
    "brave": {
        "aliases": ("brave", "brave browser"),
        "linux": ("brave-browser", "brave"),
        "darwin": ("Brave Browser", "Brave"),
        "win32": ("brave.exe",),
    },
    "chrome": {
        "aliases": ("chrome", "google chrome", "chromium", "chromium browser"),
        "linux": ("google-chrome-stable", "google-chrome", "chromium", "chromium-browser"),
        "darwin": ("Google Chrome",),
        "win32": ("chrome.exe",),
    },
    "edge": {
        "aliases": ("edge", "microsoft edge"),
        "linux": ("microsoft-edge", "microsoft-edge-stable"),
        "darwin": ("Microsoft Edge",),
        "win32": ("msedge.exe",),
    },
    "firefox": {
        "aliases": ("firefox", "mozilla firefox"),
        "linux": ("firefox",),
        "darwin": ("Firefox",),
        "win32": ("firefox.exe",),
    },
    "spotify": {
        "aliases": ("spotify",),
        "linux": ("spotify",),
        "darwin": ("Spotify",),
        "win32": ("spotify.exe",),
    },
    "vscode": {
        "aliases": ("vscode", "visual studio code"),
        "linux": ("code", "code-insiders"),
        "darwin": ("Visual Studio Code",),
        "win32": ("code.exe",),
    },
    "files": {
        "aliases": ("files", "file manager", "nautilus", "dolphin", "thunar"),
        "linux": ("xdg-open", "nautilus", "dolphin", "thunar"),
        "darwin": ("Finder",),
        "win32": ("explorer.exe",),
    },
    "discord": {
        "aliases": ("discord",),
        "linux": ("discord",),
        "darwin": ("Discord",),
        "win32": ("discord.exe",),
    },
    "slack": {
        "aliases": ("slack",),
        "linux": ("slack",),
        "darwin": ("Slack",),
        "win32": ("slack.exe",),
    },
    "steam": {
        "aliases": ("steam",),
        "linux": ("steam",),
        "darwin": ("Steam",),
        "win32": ("steam.exe",),
    },
    "terminal": {
        "aliases": ("terminal", "console"),
        "linux": ("kitty", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"),
        "darwin": ("Terminal", "iTerm"),
        "win32": ("wt.exe", "powershell.exe", "cmd.exe"),
    },
}


PATH_ALIASES = {
    "home": str(Path.home()),
    "desktop": str(Path.home() / "Desktop"),
    "downloads": str(Path.home() / "Downloads"),
    "documents": str(Path.home() / "Documents"),
    "music": str(Path.home() / "Music"),
    "pictures": str(Path.home() / "Pictures"),
    "videos": str(Path.home() / "Videos"),
}


SEARCH_ENGINE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(r"\bsearch\s+(?P<engine>google|web|youtube|github|reddit|amazon)\s+for\s+(?P<query>.+)$", flags=re.IGNORECASE),
        "engine_first",
    ),
    (
        re.compile(r"\b(?:search|find)\s+(?P<query>.+?)\s+on\s+(?P<engine>google|web|youtube|github|reddit|amazon)\b", flags=re.IGNORECASE),
        "query_first",
    ),
    (
        re.compile(r"\bopen\s+(?P<engine>youtube|github|google|reddit|amazon)\s+and\s+search\s+(?P<query>.+)$", flags=re.IGNORECASE),
        "engine_first",
    ),
    (
        re.compile(r"\bopen\s+(?P<engine>youtube|github|google|reddit|amazon)\b(?:.*?\b)?search\s+(?P<query>.+)$", flags=re.IGNORECASE),
        "engine_first",
    ),
    (
        re.compile(r"\b(?:put|go to|visit)\s+(?P<engine>youtube|github|google|reddit|amazon)\b(?:.*?\b)?search\s+(?P<query>.+)$", flags=re.IGNORECASE),
        "engine_first",
    ),
    (
        re.compile(r"\b(?:look up|lookup|pull up|check out)\s+(?P<query>.+?)\s+on\s+(?P<engine>google|web|youtube|github|reddit|amazon)\b", flags=re.IGNORECASE),
        "query_first",
    ),
)

FILLER_PHRASES: tuple[str, ...] = (
    "i want you to",
    "can you",
    "could you",
    "would you",
    "for me",
    "please",
    "bro",
    "now",
    "just",
    "hey memla",
    "you see",
)

LANGUAGE_REWRITE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\blook up\b", " search "),
    (r"\blookup\b", " search "),
    (r"\bpull up\b", " open "),
    (r"\bcheck out\b", " open "),
    (r"\bcrack open\b", " open "),
    (r"\bgrab\b", " find "),
    (r"\bsnag\b", " find "),
    (r"\bpeep\b", " find "),
    (r"\bpop\b", " open "),
    (r"\bvids\b", " videos "),
    (r"\bvid\b", " video "),
    (r"\bthreads\b", " posts "),
    (r"\bthread\b", " post "),
    (r"\byt\b", " youtube "),
    (r"\bnewbie\b", " beginner "),
    (r"\bopener\b", " first "),
    (r"\bbunk\b", " weak "),
    (r"\bopen a tab\b", " open new tab "),
    (r"\bopen tab\b", " open new tab "),
    (r"\bhe first\b", " first "),
    (r"\bhe second\b", " second "),
    (r"\bhe third\b", " third "),
)

INFERRED_SEARCH_ENGINE_HINTS: dict[str, tuple[str, ...]] = {
    "youtube": ("youtube", "video", "videos", "music", "song", "watch"),
    "github": ("github", "repo", "repos", "repository", "repositories", "codebase", "project"),
    "reddit": ("reddit", "post", "posts", "thread", "threads", "discussion", "discussions"),
    "google": ("google", "web"),
    "amazon": ("amazon", "product", "products"),
}

SEARCH_QUERY_LEAD_INS: tuple[str, ...] = (
    "search",
    "find",
    "put",
    "open",
    "show",
)

SEARCH_QUERY_TRAILING_CUES: tuple[str, ...] = (
    "click",
    "open",
    "watch",
    "play",
    "pick",
    "select",
    "press",
    "read",
    "summarize",
    "summarise",
    "explain",
    "tell me",
)

GOAL_STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "align",
    "aligned",
    "any",
    "are",
    "best",
    "browser",
    "card",
    "cards",
    "compare",
    "current",
    "does",
    "fit",
    "for",
    "from",
    "good",
    "is",
    "match",
    "matches",
    "most",
    "of",
    "page",
    "repo",
    "repos",
    "repository",
    "result",
    "results",
    "show",
    "source",
    "sources",
    "tell",
    "that",
    "the",
    "these",
    "this",
    "to",
    "what",
    "which",
    "with",
}

LOW_SIGNAL_GOAL_TOKENS: set[str] = {
    "local",
    "workflow",
    "setup",
    "project",
    "repo",
    "repos",
    "repository",
    "repositories",
    "result",
    "results",
    "card",
    "cards",
}

LANGUAGE_MEMORY_STOPWORDS: set[str] = {
    "a",
    "an",
    "and",
    "about",
    "all",
    "any",
    "at",
    "best",
    "but",
    "figure",
    "find",
    "for",
    "from",
    "get",
    "go",
    "grab",
    "hey",
    "i",
    "if",
    "in",
    "into",
    "it",
    "just",
    "me",
    "memla",
    "my",
    "now",
    "of",
    "on",
    "open",
    "or",
    "over",
    "please",
    "pull",
    "search",
    "show",
    "snag",
    "some",
    "tell",
    "that",
    "the",
    "then",
    "this",
    "to",
    "up",
    "yo",
    "you",
}

COMPILER_REWRITE_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"\bscope out some youtube coverage on\b", " find a youtube video about "),
    (r"\bscope out youtube coverage on\b", " find a youtube video about "),
    (r"\bscope out a reddit thread on\b", " find a reddit thread about "),
    (r"\bscope out some reddit coverage on\b", " find a reddit thread about "),
    (r"\bscope out\b", " find "),
    (r"\bsuss out\b", " find "),
    (r"\bline up\b", " find "),
    (r"\bhunt down\b", " find "),
    (r"\btrack down\b", " find "),
    (r"\bround up\b", " find "),
    (r"\bpeel open\b", " open "),
    (r"\bclip\b", " video "),
    (r"\bcrack a stronger one\b", " open a better one "),
    (r"\bcrack stronger one\b", " open a better one "),
    (r"\bcrack a better one\b", " open a better one "),
    (r"\btop one\b", " first one "),
    (r"\btop result\b", " first result "),
    (r"\btop repo\b", " first repo "),
    (r"\btop video\b", " first video "),
    (r"\bsort out the repo that suits\b", " find whatever repo best fits "),
    (r"\bsort out which repo suits\b", " find whatever repo best fits "),
    (r"\bbest fits\b", " fits best "),
    (r"\bweigh the first two repos\b", " compare the first two repos "),
    (r"\blands the clearest\b", " best explains "),
)

GOAL_CONCEPT_PATTERNS: dict[str, tuple[float, tuple[str, ...]]] = {
    "cpp": (
        2.0,
        (
            r"\bc\+\+\b",
            r"\bcpp\b",
            r"\bc plus plus\b",
            r"\bcxx\b",
        ),
    ),
    "inference": (
        1.5,
        (
            r"\binference\b",
            r"\bruntime\b",
        ),
    ),
    "resource_constrained": (
        1.5,
        (
            r"\bweak hardware\b",
            r"\bweak laptop\b",
            r"\blaptop\b",
            r"\blaptops\b",
            r"\bcpu\b",
            r"\bportable\b",
            r"\bportability\b",
        ),
    ),
    "beginner": (
        2.0,
        (
            r"\bbeginner\b",
            r"\bgetting started\b",
            r"\bget started\b",
            r"\bsimple cli\b",
            r"\bsimple\b",
            r"\beasy\b",
            r"\bquickly\b",
        ),
    ),
}


def terminal_model_default() -> str:
    return os.environ.get("MEMLA_TERMINAL_MODEL") or os.environ.get("OLLAMA_MODEL") or "phi3:mini"


def terminal_browser_state_path() -> Path:
    configured = str(os.environ.get(BROWSER_STATE_ENV, "") or "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return (Path.home() / ".memla" / BROWSER_STATE_FILENAME).resolve()


def terminal_trace_log_path() -> Path:
    return (terminal_browser_state_path().parent / TERMINAL_TRACE_FILENAME).resolve()


def terminal_language_memory_path() -> Path:
    return (terminal_browser_state_path().parent / TERMINAL_LANGUAGE_MEMORY_FILENAME).resolve()


def terminal_language_rule_path() -> Path:
    return (terminal_browser_state_path().parent / TERMINAL_LANGUAGE_RULE_FILENAME).resolve()


def terminal_memory_ontology_path() -> Path:
    return (terminal_browser_state_path().parent / TERMINAL_MEMORY_ONTOLOGY_FILENAME).resolve()


def _terminal_memory_ontology_path_for_state(state_path: str | Path | None = None) -> Path:
    if state_path:
        return (Path(state_path).expanduser().resolve().parent / TERMINAL_MEMORY_ONTOLOGY_FILENAME).resolve()
    return terminal_memory_ontology_path()


def load_browser_session_state(path: str | Path | None = None) -> BrowserSessionState:
    state_path = Path(path).expanduser().resolve() if path else terminal_browser_state_path()
    if not state_path.exists():
        return BrowserSessionState()
    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return BrowserSessionState()
    if not isinstance(payload, dict):
        return BrowserSessionState()
    result_urls = [str(item).strip() for item in list(payload.get("result_urls") or []) if str(item).strip()]
    result_cards = [dict(item) for item in list(payload.get("result_cards") or []) if isinstance(item, dict)]
    evidence_items = [dict(item) for item in list(payload.get("evidence_items") or []) if isinstance(item, dict)]
    return BrowserSessionState(
        current_url=str(payload.get("current_url") or "").strip(),
        page_kind=str(payload.get("page_kind") or "").strip(),
        browser_app=str(payload.get("browser_app") or "").strip(),
        search_engine=str(payload.get("search_engine") or "").strip(),
        search_query=str(payload.get("search_query") or "").strip(),
        result_urls=result_urls,
        result_cards=result_cards,
        subject_title=str(payload.get("subject_title") or "").strip(),
        subject_url=str(payload.get("subject_url") or "").strip(),
        subject_summary=str(payload.get("subject_summary") or "").strip(),
        research_subject_title=str(payload.get("research_subject_title") or "").strip(),
        research_subject_url=str(payload.get("research_subject_url") or "").strip(),
        research_subject_summary=str(payload.get("research_subject_summary") or "").strip(),
        evidence_items=evidence_items,
    )


def save_browser_session_state(state: BrowserSessionState, path: str | Path | None = None) -> Path:
    state_path = Path(path).expanduser().resolve() if path else terminal_browser_state_path()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    return state_path


def _normalize_label(value: str) -> str:
    text = str(value or "").strip().lower()
    for source, target in (
        ("what's", "what is"),
        ("whats", "what is"),
        ("who's", "who is"),
        ("whos", "who is"),
        ("where's", "where is"),
        ("wheres", "where is"),
        ("when's", "when is"),
        ("whens", "when is"),
        ("why's", "why is"),
        ("whys", "why is"),
        ("how's", "how is"),
        ("hows", "how is"),
    ):
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _clone_evidence_items(items: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(item) for item in list(items or []) if isinstance(item, dict)]


def _browser_state_payload(browser_state: BrowserSessionState) -> dict[str, Any]:
    return {
        "current_url": browser_state.current_url,
        "page_kind": browser_state.page_kind,
        "browser_app": browser_state.browser_app,
        "search_engine": browser_state.search_engine,
        "search_query": browser_state.search_query,
        "result_urls": [str(item).strip() for item in list(browser_state.result_urls or []) if str(item).strip()],
        "result_cards": [dict(item) for item in list(browser_state.result_cards or []) if isinstance(item, dict)],
        "subject_title": browser_state.subject_title,
        "subject_url": browser_state.subject_url,
        "subject_summary": browser_state.subject_summary,
        "research_subject_title": browser_state.research_subject_title,
        "research_subject_url": browser_state.research_subject_url,
        "research_subject_summary": browser_state.research_subject_summary,
        "evidence_items": _clone_evidence_items(browser_state.evidence_items),
    }


def _browser_state_copy(browser_state: BrowserSessionState, **updates: Any) -> BrowserSessionState:
    payload = _browser_state_payload(browser_state)
    payload.update(updates)
    payload["result_urls"] = [str(item).strip() for item in list(payload.get("result_urls") or []) if str(item).strip()]
    payload["result_cards"] = [dict(item) for item in list(payload.get("result_cards") or []) if isinstance(item, dict)]
    payload["evidence_items"] = _clone_evidence_items(payload.get("evidence_items"))
    return BrowserSessionState(**payload)


def _normalize_goal_text(value: str) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"\bc\+\+\b", " cpp ", text)
    text = re.sub(r"\bc plus plus\b", " cpp ", text)
    text = re.sub(r"\bcxx\b", " cpp ", text)
    for source, target in (
        ("what's", "what is"),
        ("whats", "what is"),
        ("who's", "who is"),
        ("whos", "who is"),
        ("where's", "where is"),
        ("wheres", "where is"),
        ("when's", "when is"),
        ("whens", "when is"),
        ("why's", "why is"),
        ("whys", "why is"),
        ("how's", "how is"),
        ("hows", "how is"),
    ):
        text = text.replace(source, target)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    for pattern, replacement in LANGUAGE_REWRITE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    return " ".join(text.split())


def _intent_text(value: str) -> str:
    text = _normalize_label(value)
    for pattern, replacement in LANGUAGE_REWRITE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    for phrase in FILLER_PHRASES:
        text = re.sub(rf"\b{re.escape(phrase)}\b", " ", text)
    text = re.sub(r"\bthen\b", " ", text)
    return " ".join(text.split())


def _compiler_surface_text(value: str) -> str:
    text = _normalize_goal_text(value)
    for pattern, replacement in LANGUAGE_REWRITE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    for pattern, replacement in COMPILER_REWRITE_PATTERNS:
        text = re.sub(pattern, replacement, text)
    text = re.sub(r"\bwinner\b", " winner ", text)
    return " ".join(text.split())


def _infer_search_engine_from_text(text: str) -> str:
    normalized = _intent_text(text)
    if not normalized:
        return ""
    for engine, hints in INFERRED_SEARCH_ENGINE_HINTS.items():
        if any(re.search(rf"\b{re.escape(hint)}\b", normalized) for hint in hints):
            return engine
    return ""


def _trim_inferred_query_tail(text: str) -> str:
    clean = str(text or "").strip()
    if not clean:
        return ""
    for cue in SEARCH_QUERY_TRAILING_CUES:
        pattern = rf"\b{re.escape(_normalize_goal_text(cue))}\b"
        match = re.search(pattern, clean)
        if match:
            clean = clean[: match.start()].strip()
            break
    return clean


def _clean_inferred_query(text: str, *, engine: str = "") -> str:
    clean = _normalize_goal_text(text)
    if not clean:
        return ""
    clean = _trim_inferred_query_tail(clean)
    if engine:
        clean = re.sub(rf"\b{re.escape(_normalize_goal_text(engine))}\b", " ", clean)
    engine_hints = INFERRED_SEARCH_ENGINE_HINTS.get(engine, ())
    for hint in engine_hints:
        clean = re.sub(rf"\b{re.escape(_normalize_goal_text(hint))}\b", " ", clean)
    clean = re.sub(r"\b(?:on|about|for|with|of|the|a|an|me|this|that|it)\b", " ", clean)
    return " ".join(clean.split())


def _explicit_search_hits_from_text(text: str) -> list[dict[str, str]]:
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    intent_text = _intent_text(text)
    if not intent_text:
        return hits
    for pattern, _ordering in SEARCH_ENGINE_PATTERNS:
        for match in pattern.finditer(intent_text):
            engine = str(match.groupdict().get("engine") or "").strip()
            query = str(match.groupdict().get("query") or "").strip().rstrip(".!?")
            url = _search_url(engine, query)
            if not url or url.lower() in seen:
                continue
            seen.add(url.lower())
            hits.append(
                {
                    "engine": _normalize_label(engine),
                    "query": " ".join(query.split()),
                    "url": url,
                }
            )
    return hits


def _search_hits_from_text(text: str) -> list[dict[str, str]]:
    hits = _explicit_search_hits_from_text(text)
    if hits:
        return hits
    intent_text = _intent_text(text)
    inferred_engine = _infer_search_engine_from_text(intent_text)
    if not inferred_engine:
        return hits
    inferred_query = ""
    for lead_in in SEARCH_QUERY_LEAD_INS:
        match = re.search(rf"\b{re.escape(_normalize_goal_text(lead_in))}\s+(?P<query>.+)$", intent_text)
        if match:
            inferred_query = _clean_inferred_query(str(match.group("query") or "").strip(), engine=inferred_engine)
            if inferred_query:
                break
    if not inferred_query:
        return hits
    url = _search_url(inferred_engine, inferred_query)
    if not url:
        return hits
    hits.append({"engine": inferred_engine, "query": inferred_query, "url": url})
    return hits


def _alias_hits(prompt: str, alias_map: dict[str, tuple[str, ...]]) -> list[str]:
    normalized = _normalize_label(prompt)
    hits: list[tuple[int, int, str]] = []
    for canonical, aliases in alias_map.items():
        for alias in aliases:
            pattern = rf"(?<![a-z0-9]){re.escape(_normalize_label(alias))}(?![a-z0-9])"
            match = re.search(pattern, normalized)
            if match:
                hits.append((match.start(), -(match.end() - match.start()), canonical))
                break
    ordered: list[str] = []
    seen: set[str] = set()
    for _, _, canonical in sorted(hits):
        if canonical in seen:
            continue
        seen.add(canonical)
        ordered.append(canonical)
    return ordered


def _url_hits(prompt: str) -> list[str]:
    urls = re.findall(r"https?://[^\s]+", prompt, flags=re.IGNORECASE)
    bare_domains = re.findall(r"(?<!@)\b[a-z0-9.-]+\.(?:com|org|net|io|dev|app|ai)\b", prompt, flags=re.IGNORECASE)
    out: list[str] = []
    seen: set[str] = set()
    for raw in list(urls) + [f"https://{item}" for item in bare_domains]:
        clean = str(raw or "").strip().rstrip(".,)")
        if not clean or clean.lower() in seen:
            continue
        seen.add(clean.lower())
        out.append(clean)
    return out


def _contains_risky_intent(prompt: str) -> bool:
    lower = str(prompt or "").strip().lower()
    for token in RISKY_TOKENS:
        clean = str(token or "").strip().lower()
        if not clean:
            continue
        if re.search(rf"\b{re.escape(clean)}\b", lower):
            return True
    return False


def _search_url(engine: str, query: str) -> str:
    clean_engine = _normalize_label(engine)
    clean_query = " ".join(str(query or "").strip().split())
    if not clean_query:
        return ""
    encoded = quote_plus(clean_query)
    if clean_engine in {"google", "web"}:
        return f"https://www.google.com/search?q={encoded}"
    if clean_engine == "youtube":
        return f"https://www.youtube.com/results?search_query={encoded}"
    if clean_engine == "github":
        return f"https://github.com/search?q={encoded}&type=repositories"
    if clean_engine == "reddit":
        return f"https://www.reddit.com/search/?q={encoded}"
    if clean_engine == "amazon":
        return f"https://www.amazon.com/s?k={encoded}"
    return ""


def _web_backend_search_url(query: str) -> str:
    clean_query = " ".join(str(query or "").strip().split())
    if not clean_query:
        return ""
    return f"https://html.duckduckgo.com/html/?q={quote_plus(clean_query)}"


def _google_search_url(query: str) -> str:
    clean_query = " ".join(str(query or "").strip().split())
    if not clean_query:
        return ""
    return f"https://www.google.com/search?hl=en&gl=us&q={quote_plus(clean_query)}"


def _fetch_google_search_html(query: str) -> str:
    url = _google_search_url(query)
    if not url:
        return ""
    req = urllib_request.Request(
        url,
        headers={
            "User-Agent": GOOGLE_SEARCH_USER_AGENT,
            "Accept": "text/html",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    with urllib_request.urlopen(req, timeout=8.0) as response:
        return response.read().decode("utf-8", errors="ignore")


def _decode_search_result_href(raw: str) -> str:
    text = _html_unescape(str(raw or "").strip())
    if not text:
        return ""
    if text.startswith("//"):
        text = f"https:{text}"
    parsed = urlparse(text)
    if "duckduckgo.com" in parsed.netloc.lower():
        query = parse_qs(parsed.query)
        uddg = query.get("uddg") or []
        if uddg:
            return unquote(str(uddg[0] or "").strip())
    if parsed.path == "/url":
        query = parse_qs(parsed.query)
        target = query.get("q") or []
        if target:
            return unquote(str(target[0] or "").strip())
    return text if _normalize_url(text) else ""


def _extract_external_links_from_html(fragment: str, *, limit: int = 3) -> list[dict[str, str]]:
    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for href, inner in re.findall(r'(?is)<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', str(fragment or "")):
        url = _decode_search_result_href(href)
        if not url:
            continue
        netloc = urlparse(url).netloc.lower()
        if not netloc or "google." in netloc:
            continue
        key = url.lower()
        if key in seen:
            continue
        seen.add(key)
        title = _strip_html(inner)
        cards.append(
            {
                "title": title or _preview_label_for_url(url) or url,
                "url": url,
                "summary": "",
            }
        )
        if len(cards) >= max(int(limit), 0):
            break
    return cards


def _cut_google_surface_html(fragment: str, *, stop_patterns: tuple[str, ...]) -> str:
    window = str(fragment or "")
    stops: list[int] = []
    for pattern in stop_patterns:
        match = re.search(pattern, window)
        if match:
            stops.append(match.start())
    if stops:
        window = window[: min(stops)]
    return window


def _clean_google_answer_text(text: str, *, answer_kind: str = "") -> str:
    clean = _normalize_google_surface_text(_strip_html(text))
    clean = re.sub(r"^\s*Press / to jump to the search box\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"^\s*AI Mode\b.*?\bSearch Results\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bAI Overview\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bShow more\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bOverview generated by AI\b", " ", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bThese are results for\b.*$", " ", clean, flags=re.IGNORECASE)
    for marker in (
        "Explore more",
        "People also ask",
        "Web results",
        "Top stories",
        "Sponsored result",
        "Search tools",
        "Search Results",
        "Related questions",
    ):
        clean = re.split(rf"\b{re.escape(marker)}\b", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    if answer_kind == "google_ai_overview":
        clean = re.sub(r"\b[A-Z][A-Za-z0-9.&()'/-]+(?:\s+[A-Z][A-Za-z0-9.&()'/-]+){0,4}\s+\+\d+\b", " ", clean)
    clean = " ".join(clean.split()).strip()
    if not clean:
        return ""
    return _first_sentences(clean, max_sentences=3, max_chars=520)


def _extract_google_ai_overview_from_html(html: str, *, query: str = "") -> dict[str, Any]:
    match = re.search(r"AI Overview", str(html or ""), flags=re.IGNORECASE)
    if not match:
        return {}
    window = str(html or "")[match.start() : match.start() + 12000]
    source_cards = _extract_external_links_from_html(window, limit=4)
    answer_window = _cut_google_surface_html(
        window,
        stop_patterns=(
            r"(?is)<a[^>]+href=\"https?://",
            r"(?i)Explore more",
            r"(?i)People also ask",
            r"(?i)Web results",
            r"(?i)Top stories",
            r"(?is)<h3\b",
            r"(?is)<g-card\b",
        ),
    )
    answer = _clean_google_answer_text(answer_window, answer_kind="google_ai_overview")
    if not answer or _looks_like_low_signal_web_text(answer):
        return {}
    return {
        "answer": answer,
        "answer_kind": "google_ai_overview",
        "source_cards": source_cards,
    }


def _extract_google_weather_from_html(html: str, *, query: str = "") -> dict[str, Any]:
    normalized_query = _normalize_goal_text(query)
    if normalized_query and not any(
        token in normalized_query
        for token in ("weather", "forecast", "rain", "raining", "snow", "humidity", "temperature", "hot", "cold")
    ):
        return {}
    raw = str(html or "")
    if not raw or not re.search(r"(?i)\bWeather\b", raw):
        return {}
    anchor = re.search(r"(?i)\bWeather\b", raw)
    if not anchor:
        return {}
    window = raw[max(anchor.start() - 2000, 0) : anchor.start() + 16000]
    source_cards = _extract_external_links_from_html(window, limit=3)
    clean = _normalize_google_surface_text(_strip_html(window))
    clean = re.sub(r"^\s*AI Mode\b.*?\bSearch Results\b", " ", clean, flags=re.IGNORECASE)
    clean = re.split(r"\b(?:Sponsored result|People also ask|Top stories|Web results)\b", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    if "Precipitation" not in clean and not re.search(r"\d+\s*°\s*/\s*\d+\s*°", clean):
        return {}
    location = ""
    location_match = re.search(r"([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})\s*(?:•\s*Choose area\s*)?Weather\b", clean)
    if location_match:
        location = " ".join(location_match.group(1).split()).strip()
    period = ""
    period_match = re.search(r"\bWeather\s+([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2})\b", clean)
    if period_match:
        period = " ".join(period_match.group(1).split()).strip()
    high_low = ""
    high_low_match = re.search(r"(\d+\s*°\s*/\s*\d+\s*°)", clean)
    if high_low_match:
        high_low = re.sub(r"\s+", "", high_low_match.group(1))
    condition = ""
    condition_match = re.search(
        r"\d+\s*°\s*/\s*\d+\s*°\s+([A-Za-z][A-Za-z /-]{1,24})\s+\d+\s*°\s+\d{1,2}\s*(?:AM|PM)",
        clean,
        flags=re.IGNORECASE,
    )
    if condition_match:
        condition = " ".join(condition_match.group(1).split()).strip()
    precipitation = ""
    precipitation_match = re.search(r"\bPrecipitation\b\s*[•·]?\s*(\d{1,3})%", clean, flags=re.IGNORECASE)
    if precipitation_match:
        precipitation = str(precipitation_match.group(1)).strip()
    if not any([location, period, high_low, condition, precipitation]):
        return {}
    condition_lower = str(condition or "").strip().lower()
    question_mentions_rain = any(token in normalized_query for token in ("rain", "raining", "shower", "storm"))
    precip_value = int(precipitation or 0) if str(precipitation or "").isdigit() else None
    looks_rainy = any(token in condition_lower for token in ("rain", "shower", "storm", "drizzle"))
    rain_likely = looks_rainy or (precip_value is not None and precip_value >= 40)
    if question_mentions_rain:
        if rain_likely:
            answer = f"Yes, rain looks likely tomorrow in {location or 'the area'}."
        else:
            answer = f"No, it doesn't look like rain tomorrow in {location or 'the area'}."
        details: list[str] = []
        if condition:
            details.append(f"Google shows {condition_lower} conditions")
        if precipitation:
            details.append(f"a {precipitation}% precipitation chance")
        if high_low:
            details.append(f"a high/low of {high_low}")
        if period:
            details.append(period)
        if details:
            answer = f"{answer} {' with '.join(details[:2])}.".replace(" with ", " ")
            answer = re.sub(r"\.\.", ".", answer)
    else:
        detail_parts: list[str] = []
        if condition:
            detail_parts.append(f"{condition_lower} conditions")
        if high_low:
            detail_parts.append(f"a high/low of {high_low}")
        if precipitation:
            detail_parts.append(f"{precipitation}% precipitation")
        intro = f"{period or 'Tomorrow'} in {location or 'the area'}"
        answer = f"{intro}, Google shows {' with '.join(detail_parts[:2])}."
    answer = _ensure_terminal_sentence(_normalize_google_surface_text(answer))
    if not answer or _looks_like_low_signal_web_text(answer):
        return {}
    return {
        "answer": answer,
        "answer_kind": "google_weather",
        "source_cards": source_cards,
    }


def _extract_google_weather_answer_from_html(html: str, *, query: str = "") -> dict[str, Any]:
    normalized_query = _normalize_goal_text(query)
    if normalized_query and not any(
        token in normalized_query
        for token in ("weather", "forecast", "rain", "raining", "snow", "humidity", "temperature", "hot", "cold")
    ):
        return {}
    raw = str(html or "")
    if not raw or not re.search(r"(?i)\bWeather\b", raw):
        return {}
    anchor = re.search(r"(?i)\bWeather\b", raw)
    if not anchor:
        return {}
    window = raw[max(anchor.start() - 2000, 0) : anchor.start() + 16000]
    source_cards = _extract_external_links_from_html(window, limit=3)
    clean = _normalize_google_surface_text(_strip_html(window))
    clean = re.sub(r"^\s*AI Mode\b.*?\bSearch Results\b", " ", clean, flags=re.IGNORECASE)
    clean = re.split(r"\b(?:Sponsored result|People also ask|Top stories|Web results)\b", clean, maxsplit=1, flags=re.IGNORECASE)[0]
    if "Precipitation" not in clean and not re.search(r"\d{1,3}\D{0,2}/\d{1,3}\D{0,2}", clean):
        return {}

    location = ""
    location_match = re.search(r"([A-Z][A-Za-z .'-]+,\s*[A-Z]{2})\s*(?:\W+\s*Choose area\s*)?Weather\b", clean)
    if location_match:
        location = " ".join(location_match.group(1).split()).strip()

    period = ""
    period_match = re.search(r"\bWeather\s+([A-Z][a-z]+,\s+[A-Z][a-z]+\s+\d{1,2})\b", clean)
    if period_match:
        period = " ".join(period_match.group(1).split()).strip()

    high_low = ""
    high_low_match = re.search(r"(\d{1,3}\D{0,2}/\d{1,3}\D{0,2})", clean)
    if high_low_match:
        high_low = re.sub(r"\s+", "", high_low_match.group(1))

    condition = ""
    condition_match = re.search(
        r"\d{1,3}\D{0,2}/\d{1,3}\D{0,2}\s+([A-Za-z][A-Za-z /-]{1,24})\s+\d{1,3}\D{0,2}\s+\d{1,2}\s*(?:AM|PM)",
        clean,
        flags=re.IGNORECASE,
    )
    if condition_match:
        condition = " ".join(condition_match.group(1).split()).strip()

    precipitation = ""
    precipitation_match = re.search(r"\bPrecipitation\b\s*\W?\s*(\d{1,3})%", clean, flags=re.IGNORECASE)
    if precipitation_match:
        precipitation = str(precipitation_match.group(1)).strip()

    if not any([location, period, high_low, condition, precipitation]):
        return {}

    condition_lower = str(condition or "").strip().lower()
    question_mentions_rain = any(token in normalized_query for token in ("rain", "raining", "shower", "storm"))
    precip_value = int(precipitation or 0) if str(precipitation or "").isdigit() else None
    looks_rainy = any(token in condition_lower for token in ("rain", "shower", "storm", "drizzle"))
    rain_likely = looks_rainy or (precip_value is not None and precip_value >= 40)

    if question_mentions_rain:
        if rain_likely:
            answer = f"Yes, rain looks likely tomorrow in {location or 'the area'}."
        else:
            answer = f"No, it doesn't look like rain tomorrow in {location or 'the area'}."
        details: list[str] = []
        if condition:
            details.append(f"Google shows {condition_lower} conditions")
        if precipitation:
            details.append(f"a {precipitation}% precipitation chance")
        if high_low:
            details.append(f"a high/low of {high_low}")
        if details:
            answer = f"{answer} {'; '.join(details[:2])}."
    else:
        detail_parts: list[str] = []
        if condition:
            detail_parts.append(f"{condition_lower} conditions")
        if high_low:
            detail_parts.append(f"a high/low of {high_low}")
        if precipitation:
            detail_parts.append(f"{precipitation}% precipitation")
        intro = f"{period or 'Tomorrow'} in {location or 'the area'}"
        answer = f"{intro}, Google shows {' with '.join(detail_parts[:2])}."

    answer = _ensure_terminal_sentence(_normalize_google_surface_text(answer))
    if not answer or _looks_like_low_signal_web_text(answer):
        return {}
    return {
        "answer": answer,
        "answer_kind": "google_weather",
        "source_cards": source_cards,
    }


def _extract_google_role_holder_answer_from_html(html: str, *, query: str = "") -> dict[str, Any]:
    requirements = _web_answer_requirements(query, query, _web_question_slice(query, query))
    if str(requirements.get("question_type") or "").strip() != "role_holder":
        return {}
    clean = _normalize_google_surface_text(_strip_html(html))
    if not clean:
        return {}
    breadcrumb_match = re.search(
        r"\b([A-Z][A-Za-z0-9&'-]+(?:\s+[A-Z][A-Za-z0-9&'-]+){0,4})\s*(?:›|>|/)\s*(CEO|Chief Executive Officer|President)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3})\b",
        clean,
    )
    if not breadcrumb_match:
        return {}
    organization = " ".join(breadcrumb_match.group(1).split()).strip()
    role = " ".join(breadcrumb_match.group(2).split()).strip()
    person = " ".join(breadcrumb_match.group(3).split()).strip()
    person_tokens = person.split()
    trailing_noise = {
        "jan",
        "january",
        "feb",
        "february",
        "mar",
        "march",
        "apr",
        "april",
        "may",
        "jun",
        "june",
        "jul",
        "july",
        "aug",
        "august",
        "sep",
        "sept",
        "september",
        "oct",
        "october",
        "nov",
        "november",
        "dec",
        "december",
    }
    while person_tokens and (
        person_tokens[-1].lower().rstrip(".,") in trailing_noise
        or re.fullmatch(r"\d{1,4}[.,]?", person_tokens[-1])
    ):
        person_tokens.pop()
    person = " ".join(person_tokens).strip()
    answer = f"{person} is the {role} of {organization}."
    if _answer_fails_question_type(answer, "role_holder"):
        return {}
    window_start = max(breadcrumb_match.start() - 400, 0)
    window_end = breadcrumb_match.end() + 1600
    window = str(html or "")[window_start:window_end]
    return {
        "answer": answer,
        "answer_kind": "google_role_holder",
        "source_cards": _extract_external_links_from_html(window, limit=3),
    }


def _extract_google_featured_snippet_from_html(html: str, *, query: str = "") -> dict[str, Any]:
    requirements = _web_answer_requirements(query, query, _web_question_slice(query, query))
    question_type = str(requirements.get("question_type") or "").strip()
    patterns = (
        r'(?is)<div[^>]*data-attrid="wa:/description"[^>]*>(.*?)</div>',
        r'(?is)<div[^>]*class="[^"]*\bkno-rdesc\b[^"]*"[^>]*>(.*?)</div>',
    )
    for pattern in patterns:
        for raw in re.findall(pattern, str(html or "")):
            answer = _clean_google_answer_text(raw, answer_kind="google_featured_snippet")
            if not answer or _looks_like_low_signal_web_text(answer):
                continue
            if _answer_fails_question_type(answer, question_type):
                continue
            window = raw if isinstance(raw, str) else str(raw)
            return {
                "answer": answer,
                "answer_kind": "google_featured_snippet",
                "source_cards": _extract_external_links_from_html(window, limit=3),
            }
    return {}


def _fetch_google_answer_surface(query: str) -> dict[str, Any]:
    try:
        html = _fetch_google_search_html(query)
    except Exception:
        return {}
    if not html:
        return {}
    normalized_query = _normalize_goal_text(query)
    extractors: list[Any] = []
    if any(
        token in normalized_query
        for token in ("weather", "forecast", "rain", "raining", "snow", "humidity", "temperature", "hot", "cold")
    ):
        extractors.append(_extract_google_weather_answer_from_html)
    extractors.extend(
        (
            _extract_google_role_holder_answer_from_html,
            _extract_google_ai_overview_from_html,
            _extract_google_featured_snippet_from_html,
        )
    )
    for extractor in extractors:
        payload = extractor(html, query=query)
        if payload:
            payload["search_url"] = _google_search_url(query)
            return payload
    return {}


def _fetch_web_search_cards(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    html = _fetch_url_text(_web_backend_search_url(query))
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    pattern = re.compile(
        r'(?is)<a(?=[^>]*class="[^"]*result__a[^"]*")(?=[^>]*href="([^"]+)")[^>]*>(.*?)</a>(.*?)(?=<a(?=[^>]*class="[^"]*result__a[^"]*")|$)'
    )
    for match in pattern.finditer(html):
        url = _decode_search_result_href(match.group(1))
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        title = _strip_html(match.group(2))
        tail = str(match.group(3) or "")
        snippet_match = re.search(r'(?is)class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</', tail)
        snippet = _strip_html(snippet_match.group(1)) if snippet_match else ""
        cards.append(
            {
                "index": len(cards) + 1,
                "title": title or _preview_label_for_url(url) or url,
                "url": url,
                "summary": snippet,
            }
        )
        if len(cards) >= limit:
            break
    return cards


def _fetch_web_search_result_urls(query: str, *, limit: int = 5) -> list[str]:
    html = _fetch_url_text(_web_backend_search_url(query))
    results: list[str] = []
    seen: set[str] = set()
    for match in re.findall(r'(?is)<a(?=[^>]*class="[^"]*result__a[^"]*")(?=[^>]*href="([^"]+)")[^>]*>', html):
        url = _decode_search_result_href(match)
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        results.append(url)
        if len(results) >= limit:
            break
    return results[:limit]


def _html_unescape(text: str) -> str:
    clean = str(text or "")
    return html_lib.unescape(clean)


def _normalize_google_surface_text(text: str) -> str:
    clean = str(text or "")
    replacements = {
        "Â°": "°",
        "âˆ™": " • ",
        "â€“": " - ",
        "â€”": " - ",
        "â€º": " › ",
        "â€™": "'",
        "â€œ": '"',
        "â€": '"',
        "â€¦": "...",
    }
    for needle, value in replacements.items():
        clean = clean.replace(needle, value)
    for needle, value in (
        ("Â°", "°"),
        ("â€¢", " • "),
        ("â€“", " - "),
        ("â€”", " - "),
        ("â€º", " › "),
        ("â€™", "'"),
        ("â€œ", '"'),
        ("â€", '"'),
        ("â€¦", "..."),
    ):
        clean = clean.replace(needle, value)
    return " ".join(clean.split()).strip()


def _strip_html(text: str) -> str:
    clean = re.sub(r"(?is)<script.*?>.*?</script>", " ", str(text or ""))
    clean = re.sub(r"(?is)<style.*?>.*?</style>", " ", clean)
    clean = re.sub(r"(?s)<[^>]+>", " ", clean)
    clean = _html_unescape(clean)
    return _normalize_google_surface_text(clean)


def _body_text_from_html(html: str) -> str:
    clean = str(html or "")
    body_match = re.search(r"(?is)<body[^>]*>(.*?)</body>", clean)
    body = body_match.group(1) if body_match else clean
    body = re.sub(r"(?is)<head.*?>.*?</head>", " ", body)
    body = re.sub(r"(?is)<script.*?>.*?</script>", " ", body)
    body = re.sub(r"(?is)<style.*?>.*?</style>", " ", body)
    body = re.sub(r"(?is)<noscript.*?>.*?</noscript>", " ", body)
    body = _strip_html(body)
    return " ".join(body.split())


def _first_sentences(text: str, *, max_sentences: int = 2, max_chars: int = 320) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    pieces = re.split(r"(?<=[.!?])\s+", clean)
    kept: list[str] = []
    for piece in pieces:
        sentence = " ".join(piece.split()).strip()
        if not sentence:
            continue
        kept.append(sentence)
        if len(kept) >= max_sentences:
            break
    candidate = " ".join(kept).strip() or clean[:max_chars].strip()
    if len(candidate) > max_chars:
        candidate = candidate[: max_chars - 3].rstrip() + "..."
    return candidate


def _looks_like_low_signal_web_text(text: str) -> bool:
    normalized = _normalize_goal_text(text)
    if not normalized:
        return True
    low_signal_phrases = {
        "read full articles",
        "watch videos",
        "browse thousands of titles",
        "comprehensive coverage",
        "stay informed",
        "latest updates",
        "get accurate hourly forecasts",
        "latest hourly weather updates",
        "detailed forecast including",
        "weather forecast and conditions",
        "today tonight and tomorrow",
        "today s and tonight s",
        "search for a location",
        "complete list of",
        "explore the forefront",
        "keep you ahead",
        "latest agentic ai news today",
        "history key dates and facts",
        "summarized in one timeline",
        "what the source covers",
    }
    return any(phrase in normalized for phrase in low_signal_phrases)


def _query_focus_tokens(text: str) -> list[str]:
    source = _normalize_goal_text(text)
    if not source:
        return []
    stopwords = {
        "a",
        "an",
        "and",
        "about",
        "are",
        "be",
        "did",
        "for",
        "from",
        "how",
        "in",
        "is",
        "latest",
        "news",
        "of",
        "on",
        "or",
        "the",
        "this",
        "today",
        "weather",
        "what",
        "when",
        "where",
        "who",
        "why",
    }
    tokens = [token for token in re.findall(r"[a-z0-9]+", source) if len(token) >= 3 and token not in stopwords]
    return list(dict.fromkeys(tokens))


def _query_focused_snippet(text: str, focus_text: str) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    tokens = _query_focus_tokens(focus_text)
    sentences = re.split(r"(?<=[.!?])\s+", clean)
    scored: list[tuple[int, str]] = []
    for sentence in sentences:
        candidate = " ".join(sentence.split()).strip()
        if len(candidate) < 24:
            continue
        normalized = _normalize_goal_text(candidate)
        if _looks_like_low_signal_web_text(candidate):
            continue
        score = sum(1 for token in tokens if token in normalized)
        if score <= 0 and tokens:
            continue
        scored.append((score, candidate))
    if not scored:
        fallback = _first_sentences(clean, max_sentences=2)
        return "" if _looks_like_low_signal_web_text(fallback) else fallback
    scored.sort(key=lambda item: (-item[0], len(item[1])))
    return _first_sentences(scored[0][1], max_sentences=2)


def _web_answer_requirements(prompt: str, query: str, slice_kind: str) -> dict[str, Any]:
    normalized = _normalize_goal_text(prompt or query)
    question_type = str(slice_kind or "general").strip().lower() or "general"
    needed_fields: list[str] = []
    if slice_kind == "weather":
        question_type = "weather_forecast"
        needed_fields = ["target_place", "target_period", "condition", "temperature_or_precipitation"]
        if "rain" in normalized or "raining" in normalized:
            question_type = "weather_precipitation"
            needed_fields = ["target_place", "target_period", "precipitation_chance", "rain_condition"]
        elif any(token in normalized for token in {"temperature", "high", "low", "hot", "cold"}):
            question_type = "weather_temperature"
            needed_fields = ["target_place", "target_period", "temperature", "condition"]
    elif "how old" in normalized:
        question_type = "derived_age_at_event"
        needed_fields = ["person_name", "birth_year_or_date", "event_year_or_date", "computed_age"]
    elif re.search(r"\bwho (?:created|invented|founded|built|made|designed)\b", normalized):
        question_type = "creator_identity"
        needed_fields = ["creator_name", "thing_name", "role_or_context"]
    elif re.search(r"\bwho (?:is|was) the ceo\b", normalized) or " chief executive " in f" {normalized} ":
        question_type = "role_holder"
        needed_fields = ["person_name", "organization", "role"]
    elif slice_kind == "news":
        question_type = "news_highlights"
        needed_fields = ["topic", "recent_developments", "named_entities_or_numbers"]
    elif slice_kind == "fact":
        question_type = "direct_fact"
        needed_fields = ["direct_answer"]
    return {
        "question_type": question_type,
        "needed_fields": needed_fields,
    }


def _looks_like_web_caption_or_headline(text: str) -> bool:
    clean = " ".join(str(text or "").split()).strip()
    normalized = _normalize_goal_text(clean)
    if not normalized:
        return True
    if clean.endswith("..."):
        return True
    if _looks_like_low_signal_web_text(clean):
        return True
    caption_patterns = (
        r"^meet the\b",
        r"^who (?:created|invented|founded|built|made|designed)\b",
        r"\bhistory\b.*\bkey dates\b.*\bfacts\b",
        r"\blargely forgotten pioneers\b",
        r"\bstarted creating\b",
        r"\bin a world forever revolutionized\b",
        r"\bwhat the source covers\b",
    )
    return any(re.search(pattern, normalized) for pattern in caption_patterns)


def _answer_fails_question_type(answer: str, question_type: str) -> bool:
    clean = " ".join(str(answer or "").split()).strip()
    if not clean:
        return True
    normalized = _normalize_goal_text(clean)
    normalized_question_type = str(question_type or "").strip().lower()
    if normalized_question_type in {"creator_identity", "derived_age_at_event"} and _looks_like_web_caption_or_headline(clean):
        return True
    if normalized_question_type == "role_holder":
        if _looks_like_web_caption_or_headline(clean):
            return True
        if not _has_name_like_fact_signal(clean, []):
            return True
        if not any(token in normalized for token in ("ceo", "chief executive", "president", "founder", "leader")):
            return True
    return False


def _has_name_like_fact_signal(answer: str, extracted_facts: list[str]) -> bool:
    text = " ".join([str(answer or "").strip()] + [str(item).strip() for item in list(extracted_facts or []) if str(item).strip()]).strip()
    if not text:
        return False
    if re.search(r"\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,3}\b", text):
        return True
    normalized = _normalize_goal_text(text)
    org_tokens = ("apple", "openai", "anthropic", "microsoft", "wikipedia", "rocketdyne", "tesla", "amazon")
    return any(token in normalized for token in org_tokens)


def _hard_check_web_answer(
    *,
    prompt: str,
    question_type: str,
    answer: str,
    extracted_facts: list[str],
    missing_fields: list[str],
) -> dict[str, Any]:
    normalized_question_type = str(question_type or "").strip().lower()
    clean_answer = " ".join(str(answer or "").split()).strip()
    extracted = [str(item).strip() for item in list(extracted_facts or []) if str(item).strip()]
    missing = {str(item).strip() for item in list(missing_fields or []) if str(item).strip()}
    applicable = normalized_question_type in {"creator_identity", "derived_age_at_event"}
    if not applicable:
        return {
            "applicable": False,
            "passed": False,
            "score": 0.0,
            "reasons": [],
        }

    reasons: list[str] = []
    checks: list[bool] = []
    not_low_signal = bool(clean_answer) and not _looks_like_low_signal_web_text(clean_answer)
    checks.append(not_low_signal)
    if not not_low_signal:
        reasons.append("answer_looks_like_page_junk")

    not_caption = not _looks_like_web_caption_or_headline(clean_answer)
    checks.append(not_caption)
    if not not_caption:
        reasons.append("answer_looks_like_caption_or_headline")

    has_name_signal = _has_name_like_fact_signal(clean_answer, extracted)
    checks.append(has_name_signal)
    if not has_name_signal:
        reasons.append("missing_named_entity")

    if normalized_question_type == "creator_identity":
        has_identity_fact = bool(extracted) or bool(
            re.search(
                r"\b(created|invented|founded|built|made|designed|developed|credited|co-founded|cofounded)\b",
                _normalize_goal_text(clean_answer),
            )
        )
        checks.append(has_identity_fact)
        if not has_identity_fact:
            reasons.append("missing_creator_fact")
        missing_creator = "creator_name" in missing
        checks.append(not missing_creator)
        if missing_creator:
            reasons.append("missing_creator_name")
    elif normalized_question_type == "derived_age_at_event":
        has_age = bool(re.search(r"\b(?:about|around|roughly|age)\s*\d{1,3}\b|\b\d{1,3}\s+years?\s+old\b", clean_answer, flags=re.IGNORECASE))
        checks.append(has_age)
        if not has_age:
            reasons.append("missing_computed_age")
        combined_fact_text = " ".join(extracted + [clean_answer])
        has_timing = bool(re.search(r"\b(?:18|19|20)\d{2}\b", combined_fact_text))
        checks.append(has_timing)
        if not has_timing:
            reasons.append("missing_event_timing")
        missing_critical = bool({"computed_age", "birth_year_or_date", "event_year_or_date"} & missing)
        checks.append(not missing_critical)
        if missing_critical:
            reasons.append("missing_required_age_fields")

    passed = all(checks)
    score = round(sum(1.0 for check in checks if check) / max(len(checks), 1), 4)
    return {
        "applicable": True,
        "passed": passed,
        "score": score,
        "reasons": reasons,
    }


def _split_text_into_web_chunks(text: str, *, max_chars: int = 420) -> list[str]:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return []
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", clean) if segment.strip()]
    if not sentences:
        return []
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(sentence) > max_chars:
            sentence = sentence[: max_chars - 3].rstrip() + "..."
        candidate = f"{current} {sentence}".strip() if current else sentence
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = sentence
            continue
        current = candidate
    if current:
        chunks.append(current)
    return chunks


def _score_web_evidence_chunk(
    text: str,
    *,
    focus_text: str,
    slice_kind: str,
    question_type: str,
) -> int:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return -999
    normalized = _normalize_goal_text(clean)
    score = 0
    query_tokens = _query_focus_tokens(focus_text)
    score += sum(4 for token in query_tokens if token in normalized)
    if not _looks_like_low_signal_web_text(clean):
        score += 2
    if re.search(r"\b\d{1,4}\b", clean):
        score += 1
    if slice_kind == "weather":
        for token in ("rain", "snow", "forecast", "temperature", "high", "low", "humid", "cloud", "sun", "storm", "percent", "chance"):
            if token in normalized:
                score += 2
    if question_type == "role_holder":
        for token in ("ceo", "chief executive", "serves as", "is the ceo", "leads"):
            if token in normalized:
                score += 3
    if question_type == "creator_identity":
        for token in ("invented", "created", "founded", "designed", "built by", "developed by"):
            if token in normalized:
                score += 3
    if question_type == "derived_age_at_event":
        if any(token in normalized for token in ("born", "aged", "years old", "at age")):
            score += 4
        if re.search(r"\b(18|19|20)\d{2}\b", clean):
            score += 2
    return score


def _build_web_evidence_chunks(
    *,
    prompt: str,
    query: str,
    slice_kind: str,
    source_index: int,
    card: dict[str, Any],
    details: dict[str, Any],
    max_chunks: int = 4,
) -> list[dict[str, Any]]:
    requirements = _web_answer_requirements(prompt, query, slice_kind)
    question_type = str(requirements.get("question_type") or slice_kind or "general").strip()
    title = str(details.get("title") or card.get("title") or "").strip()
    url = str(details.get("url") or card.get("url") or "").strip()
    candidates: list[tuple[str, str]] = []
    summary = str(details.get("summary") or card.get("summary") or "").strip()
    if summary:
        candidates.append(("summary", summary))
    body_text = str(details.get("body_text") or "").strip()
    for chunk in _split_text_into_web_chunks(body_text):
        candidates.append(("body", chunk))
    ranked: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, (kind, text) in enumerate(candidates, start=1):
        normalized = _normalize_goal_text(text)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if len(text) < 28:
            continue
        score = _score_web_evidence_chunk(
            text,
            focus_text=prompt or query,
            slice_kind=slice_kind,
            question_type=question_type,
        )
        if score < 1 and kind != "summary":
            continue
        ranked.append(
            {
                "chunk_id": f"s{source_index}c{idx}",
                "source_index": int(source_index),
                "kind": kind,
                "title": title,
                "url": url,
                "text": text,
                "score": score,
            }
        )
    ranked.sort(key=lambda item: (int(item.get("score") or 0), len(str(item.get("text") or ""))), reverse=True)
    return ranked[: max(int(max_chunks), 0)]


def _prefer_content_summary(description: str, content_preview: str) -> str:
    direct_content = _query_focused_snippet(content_preview, content_preview)
    if description and not _looks_like_low_signal_web_text(description):
        return description
    if direct_content:
        return direct_content
    if description:
        return description
    return _first_sentences(content_preview, max_sentences=2)


def _meta_content(html: str, key: str, *, attr: str = "name") -> str:
    pattern = re.compile(
        rf'<meta[^>]+{attr}=["\']{re.escape(key)}["\'][^>]+content=["\']([^"\']+)["\']',
        flags=re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        return _html_unescape(match.group(1)).strip()
    pattern = re.compile(
        rf'<meta[^>]+content=["\']([^"\']+)["\'][^>]+{attr}=["\']{re.escape(key)}["\']',
        flags=re.IGNORECASE,
    )
    match = pattern.search(html)
    if match:
        return _html_unescape(match.group(1)).strip()
    return ""


def _title_from_html(html: str) -> str:
    for key, attr in (("og:title", "property"), ("twitter:title", "name"), ("title", "name")):
        value = _meta_content(html, key, attr=attr)
        if value:
            return value
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", html)
    if match:
        return _strip_html(match.group(1))
    return ""


def _fetch_page_html(url: str) -> str:
    return _fetch_url_text(url)


def _fetch_url_text(url: str, *, accept: str = "text/html") -> str:
    req = urllib_request.Request(
        url,
        headers={
            "User-Agent": DEFAULT_USER_AGENT,
            "Accept": accept,
        },
    )
    with urllib_request.urlopen(req, timeout=8.0) as response:
        return response.read().decode("utf-8", errors="ignore")


def _encode_action_note(payload: dict[str, Any]) -> str:
    if not payload:
        return ""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _decode_action_note(note: str) -> dict[str, Any]:
    text = str(note or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _search_hits(prompt: str) -> list[dict[str, str]]:
    explicit_hits = _explicit_search_hits_from_text(prompt)
    if explicit_hits:
        return explicit_hits
    hits: list[dict[str, str]] = []
    seen: set[str] = set()
    clauses = _split_prompt_clauses(prompt)
    if not clauses:
        clauses = [_intent_text(prompt)]
    for clause in clauses:
        for hit in _search_hits_from_text(clause):
            url = str(hit.get("url") or "").strip()
            if not url or url.lower() in seen:
                continue
            seen.add(url.lower())
            hits.append(hit)
    if hits:
        return hits
    return _search_hits_from_text(prompt)


def _result_index_from_prompt(prompt: str) -> int:
    normalized = _intent_text(prompt)
    if any(token in normalized for token in {"first", "1st", "one", "top one", "top result", "top repo", "top video", "the video", "the vid", "the repo", "the result"}):
        return 1
    if any(token in normalized for token in {"second", "2nd", "two"}):
        return 2
    if any(token in normalized for token in {"third", "3rd", "three"}):
        return 3
    match = re.search(r"\b(\d+)(?:st|nd|rd|th)?\b", normalized)
    if match:
        try:
            return max(int(match.group(1)), 1)
        except ValueError:
            return 1
    return 1


def _text_target_from_prompt(prompt: str) -> str:
    intent = _intent_text(prompt)
    match = re.search(r"\b(?:click|select|pick)\s+(?:on\s+)?(?:the\s+)?(?P<target>.+)$", intent)
    if not match:
        return ""
    target = str(match.group("target") or "").strip()
    for prefix in ("text ", "label ", "button ", "link "):
        if target.startswith(prefix):
            target = target[len(prefix):].strip()
    target = target.strip("\"' ")
    if any(token in target for token in {"first", "second", "third", "result", "repo", "video", "vid", "item", "card"}):
        return ""
    return target


def _wants_browser_read(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    page_phrase_hit = any(
        token in normalized
        for token in {
            "read this page",
            "summarize this page",
            "summarise this page",
            "summary on this",
            "summary of this",
            "read this post",
            "read this repo",
            "what is this page",
            "what is this repo",
            "what is this post",
            "what is this video",
            "tell me about this",
            "tell me more about this",
            "what am i looking at",
            "extract repo info",
            "extract page info",
            "repo info",
        }
    )
    verb_hit = any(token in normalized for token in {"read", "summarize", "summarise", "extract"})
    noun_hit = any(token in normalized for token in {"page", "repo", "repository", "post", "video"})
    return page_phrase_hit or (verb_hit and noun_hit)


def _general_web_query_from_prompt(prompt: str) -> str:
    normalized = " ".join(_normalize_goal_text(prompt).split()).strip(" ?.!")
    if not normalized:
        return ""
    news_match = re.search(
        r"\b(?:what(?:s|\s+s|\s+is)?\s+(?:happening|new)\s+in\s+the\s+news\s+about|what(?:s|\s+s|\s+is)?\s+the\s+news\s+on|news\s+about)\s+(.+?)(?:\s+today)?$",
        normalized,
    )
    if news_match:
        topic = str(news_match.group(1) or "").strip()
        if topic:
            return f"{topic} news today"
    if re.search(r"\bwhat(?:s|\s+s|\s+is)?\s+(?:on|in)\s+the\s+news(?:\s+today)?$", normalized) or re.search(
        r"\b(?:top|latest)\s+news(?:\s+today)?$",
        normalized,
    ):
        return "top news today"
    weather_match = re.search(r"\bweather(?:\s+today)?(?:\s+in\s+|\s+for\s+)(.+)$", normalized)
    if weather_match:
        location = str(weather_match.group(1) or "").strip()
        if location:
            return f"weather today {location}"
    if re.search(r"\bwhat(?:s|\s+s|\s+is)?\s+the\s+weather(?:\s+today)?$", normalized) or re.search(
        r"\bweather(?:\s+today)?$",
        normalized,
    ):
        return "weather today"
    return normalized


def _looks_like_general_web_question(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    if not normalized:
        return False
    if any(
        token in normalized
        for token in {
            "open ",
            "click ",
            "launch ",
            "search ",
            "watch ",
            "play ",
            "type ",
            "submit",
            "go back",
            "go forward",
            "scroll ",
            "close tab",
        }
    ):
        return False
    question_start = bool(
        re.match(
            r"^(?:what|who|when|where|why|how|which)\b",
            normalized,
        )
    )
    info_signals = {
        "news",
        "weather",
        "forecast",
        "latest",
        "today",
        "currently",
        "happening",
        "changed",
        "release",
        "tell me about",
    }
    return question_start or "?" in str(prompt or "") or any(signal in normalized for signal in info_signals)


def _general_web_answer_action(prompt: str) -> TerminalAction | None:
    if not _looks_like_general_web_question(prompt):
        return None
    query = _general_web_query_from_prompt(prompt)
    if not query:
        return None
    return TerminalAction(
        kind="browser_answer_query",
        target=query,
        resolved_target=query,
        note=_encode_action_note({"goal": str(prompt or "").strip(), "query": query, "engine": "web"}),
    )


def _looks_like_contextual_browser_followup(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    if not normalized:
        return False
    contextual_cues = {
        "this",
        "that",
        "it",
        "these",
        "those",
        "current page",
        "current result",
        "first source",
        "second source",
        "third source",
        "first result",
        "second result",
        "third result",
        "winner",
        "that source",
        "this source",
        "open the second source",
        "compare the first and second source",
        "which repo",
        "best repo",
        "which result",
        "best result",
        "rank these",
        "compare the first",
        "compare the second",
        "matches a beginner",
        "fits best",
    }
    return any(cue in normalized for cue in contextual_cues)


def _cached_cards(browser_state: BrowserSessionState) -> list[dict[str, Any]]:
    cards = [dict(item) for item in list(browser_state.result_cards or []) if isinstance(item, dict)]
    if cards:
        return cards
    return _fallback_cards_from_urls(list(browser_state.result_urls or []))


def _has_cached_result_context(browser_state: BrowserSessionState) -> bool:
    return bool(_cached_cards(browser_state))


def _has_result_resolution_context(browser_state: BrowserSessionState) -> bool:
    return _has_cached_result_context(browser_state) or bool(
        str(browser_state.search_engine or "").strip() and str(browser_state.search_query or "").strip()
    )


def _resolve_card_by_index(browser_state: BrowserSessionState, index: int) -> dict[str, Any]:
    cards = _cached_cards(browser_state)
    if 1 <= index <= len(cards):
        return dict(cards[index - 1])
    return {}


def _resolve_card_by_text(browser_state: BrowserSessionState, text: str) -> dict[str, Any]:
    needle = _normalize_label(text)
    if not needle:
        return {}
    best: dict[str, Any] = {}
    for card in _cached_cards(browser_state):
        haystacks = [
            _normalize_label(card.get("title", "")),
            _normalize_label(card.get("summary", "")),
            _normalize_label(card.get("url", "")),
        ]
        if any(needle and needle in hay for hay in haystacks):
            best = dict(card)
            break
    return best


def _browser_state_with_subject(browser_state: BrowserSessionState, subject: dict[str, Any] | None) -> BrowserSessionState:
    payload = dict(subject or {})
    return _browser_state_copy(
        browser_state,
        subject_title=str(payload.get("title") or "").strip(),
        subject_url=str(payload.get("url") or "").strip(),
        subject_summary=str(payload.get("summary") or "").strip(),
    )


def _browser_state_with_research_subject(browser_state: BrowserSessionState, subject: dict[str, Any] | None) -> BrowserSessionState:
    payload = dict(subject or {})
    return _browser_state_copy(
        browser_state,
        research_subject_title=str(payload.get("title") or "").strip(),
        research_subject_url=str(payload.get("url") or "").strip(),
        research_subject_summary=str(payload.get("summary") or "").strip(),
    )


def _goal_text_from_prompt(prompt: str) -> str:
    intent = _intent_text(prompt)
    compact = " ".join(intent.split()).strip()
    if not compact:
        return ""
    for pattern in (
        r"\b(?:rank|compare)\s+(?:these\s+)?(?:repos|repositories|results|cards)\s+for\s+(.+)$",
        r"\bfind\s+the\s+best\s+(?:repo|repository|result|card)\s+for\s+(.+)$",
        r"\bwhich\s+(?:repo|repository|result|card)\s+(?:best\s+)?(?:aligns|matches|fits)\s+(?:most\s+)?with\s+(.+)$",
        r"\bwhat\s+is\s+the\s+best\s+(?:repo|repository|result|card)\s+for\s+(.+)$",
        r"\bcompare\s+.+?\s+for\s+(.+)$",
    ):
        match = re.search(pattern, compact)
        if match:
            text = str(match.group(1) or "").strip()
            if text:
                return text
    return compact


def _leading_clause_text(prompt: str) -> str:
    compact = " ".join(_intent_text(prompt).split()).strip()
    if not compact:
        return ""
    for separator in (" and then ", " then ", " after that ", " afterwards ", " next "):
        if separator in compact:
            return compact.split(separator, 1)[0].strip()
    return compact


def _goal_tokens(text: str) -> list[str]:
    normalized = _normalize_goal_text(text)
    if not normalized:
        return []
    return [
        token
        for token in normalized.split()
        if token and token not in GOAL_STOPWORDS and not token.isdigit() and len(token) > 1
    ]


def _card_goal_text(card: dict[str, Any]) -> str:
    parts = [
        str(card.get("title") or "").strip(),
        str(card.get("summary") or "").strip(),
        str(card.get("meta") or "").strip(),
        str(card.get("url") or "").strip(),
    ]
    return " ".join(part for part in parts if part)


def _goal_concepts(text: str) -> set[str]:
    source = str(text or "").strip().lower()
    if not source:
        return set()
    out: set[str] = set()
    for name, (_, patterns) in GOAL_CONCEPT_PATTERNS.items():
        if any(re.search(pattern, source) for pattern in patterns):
            out.add(name)
    return out


def _score_text_against_goal(text: str, goal: str) -> tuple[float, list[str]]:
    text_tokens = set(_goal_tokens(text))
    goal_tokens = _goal_tokens(goal)
    if not goal_tokens:
        return 0.0, []
    overlap = [token for token in goal_tokens if token in text_tokens]
    score = 0.0
    for token in overlap:
        score += 0.5 if token in LOW_SIGNAL_GOAL_TOKENS else 1.0
    goal_concepts = _goal_concepts(goal)
    text_concepts = _goal_concepts(text)
    concept_overlap = sorted(goal_concepts & text_concepts)
    for concept in concept_overlap:
        score += float(GOAL_CONCEPT_PATTERNS[concept][0])
    normalized_text = _normalize_goal_text(text)
    normalized_goal = _normalize_goal_text(goal)
    if normalized_goal and normalized_goal in normalized_text:
        score += 1.0
    matching_terms = overlap + [f"concept:{concept}" for concept in concept_overlap]
    deduped_terms: list[str] = []
    seen: set[str] = set()
    for term in matching_terms:
        if term in seen:
            continue
        seen.add(term)
        deduped_terms.append(term)
    return score, deduped_terms[:6]


def _rank_cards_against_goal(cards: list[dict[str, Any]], goal: str) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for index, card in enumerate(list(cards or []), start=1):
        payload = dict(card)
        score, matches = _score_text_against_goal(_card_goal_text(payload), goal)
        payload["index"] = int(payload.get("index") or index)
        payload["score"] = round(score, 4)
        payload["matching_terms"] = matches
        ranked.append(payload)
    ranked.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            int(item.get("index") or 0),
            str(item.get("title") or ""),
        )
    )
    return ranked


def _compare_cards_against_goal(cards: list[dict[str, Any]], goal: str) -> dict[str, Any]:
    ranked = _rank_cards_against_goal(cards, goal)
    winner = dict(ranked[0]) if ranked else {}
    runner_up = dict(ranked[1]) if len(ranked) > 1 else {}
    return {
        "goal": goal,
        "winner_title": str(winner.get("title") or "").strip(),
        "winner_url": str(winner.get("url") or "").strip(),
        "winner_score": float(winner.get("score") or 0.0),
        "winner_matching_terms": list(winner.get("matching_terms") or []),
        "runner_up_title": str(runner_up.get("title") or "").strip(),
        "runner_up_score": float(runner_up.get("score") or 0.0),
        "comparison": ranked,
    }


def _select_better_cached_result(browser_state: BrowserSessionState, goal: str) -> dict[str, Any]:
    cards = _cached_cards(browser_state)
    if not cards:
        return {}
    ranked = _rank_cards_against_goal(cards, goal)
    current_url = _normalize_url(browser_state.current_url)
    current_title = _normalize_label(browser_state.subject_title)
    selected: dict[str, Any] = {}
    for candidate in ranked:
        candidate_url = _normalize_url(str(candidate.get("url") or "").strip())
        candidate_title = _normalize_label(str(candidate.get("title") or "").strip())
        same_url = bool(current_url and candidate_url and candidate_url == current_url)
        same_title = bool(current_title and candidate_title and candidate_title == current_title)
        if same_url or same_title:
            continue
        selected = dict(candidate)
        break
    if not selected and len(ranked) > 1:
        selected = dict(ranked[1])
    if selected and not selected.get("index"):
        for idx, card in enumerate(cards, start=1):
            if _normalize_url(str(card.get("url") or "").strip()) == _normalize_url(str(selected.get("url") or "").strip()):
                selected["index"] = idx
                break
    if ranked:
        selected["ranking"] = ranked
    return selected


def _subject_from_browser_state(browser_state: BrowserSessionState | None) -> dict[str, str]:
    if browser_state is None:
        return {}
    if browser_state.subject_title or browser_state.subject_url:
        return {
            "title": str(browser_state.subject_title or "").strip(),
            "url": str(browser_state.subject_url or "").strip(),
            "summary": str(browser_state.subject_summary or "").strip(),
        }
    if browser_state.page_kind == "repo_page" and browser_state.current_url:
        repo_title = _preview_label_for_url(browser_state.current_url) or browser_state.current_url
        return {
            "title": repo_title,
            "url": str(browser_state.current_url or "").strip(),
            "summary": "",
        }
    return {}


def _research_subject_from_browser_state(browser_state: BrowserSessionState | None) -> dict[str, str]:
    if browser_state is None:
        return {}
    if browser_state.research_subject_title or browser_state.research_subject_url:
        return {
            "title": str(browser_state.research_subject_title or "").strip(),
            "url": str(browser_state.research_subject_url or "").strip(),
            "summary": str(browser_state.research_subject_summary or "").strip(),
        }
    return _subject_from_browser_state(browser_state)


def _subject_query_from_browser_state(browser_state: BrowserSessionState | None) -> str:
    subject = _subject_from_browser_state(browser_state)
    title = str(subject.get("title") or "").strip()
    if not title:
        return ""
    return " ".join(_normalize_goal_text(title).split())


def _research_subject_query_from_browser_state(browser_state: BrowserSessionState | None) -> str:
    subject = _research_subject_from_browser_state(browser_state)
    title = str(subject.get("title") or "").strip()
    if not title:
        return ""
    return " ".join(_normalize_goal_text(title).split())


def _evidence_item_from_details(browser_state: BrowserSessionState, details: dict[str, Any]) -> dict[str, Any]:
    payload = dict(details or {})
    source_kind = str(payload.get("page_kind") or browser_state.page_kind or "web_page").strip()
    title = str(payload.get("title") or payload.get("repo") or browser_state.subject_title or browser_state.current_url).strip()
    url = str(payload.get("url") or browser_state.current_url or browser_state.subject_url).strip()
    summary = str(payload.get("summary") or payload.get("description") or browser_state.subject_summary or title).strip()
    content_preview = str(payload.get("content_preview") or "").strip()
    meta_parts = [source_kind.replace("_", " ")]
    for key in ("channel", "subreddit", "author", "language", "topics"):
        value = str(payload.get(key) or "").strip()
        if value:
            meta_parts.append(value)
    evidence = {
        "source_kind": source_kind,
        "title": title,
        "url": url,
        "summary": summary,
        "meta": " | ".join(part for part in meta_parts if part),
    }
    if content_preview:
        evidence["content_preview"] = content_preview
    return evidence


def _evidence_item_from_subject(
    subject: dict[str, Any] | None,
    *,
    source_kind: str,
    fallback_url: str = "",
    meta: str = "",
) -> dict[str, Any]:
    payload = dict(subject or {})
    title = str(payload.get("title") or "").strip()
    url = str(payload.get("url") or fallback_url or "").strip()
    summary = str(payload.get("summary") or title).strip()
    meta_text = " | ".join(part for part in [source_kind.replace("_", " "), meta] if part)
    return {
        "source_kind": source_kind,
        "title": title,
        "url": url,
        "summary": summary,
        "meta": meta_text,
    }


def _append_browser_evidence(browser_state: BrowserSessionState, evidence_item: dict[str, Any] | None) -> BrowserSessionState:
    payload = dict(evidence_item or {})
    if not any(str(payload.get(field) or "").strip() for field in ("title", "url", "summary")):
        return browser_state
    items = _clone_evidence_items(browser_state.evidence_items)
    candidate_url = _normalize_url(str(payload.get("url") or "").strip())
    candidate_title = _normalize_label(str(payload.get("title") or "").strip())
    candidate_kind = _normalize_label(str(payload.get("source_kind") or "").strip())
    replaced = False
    for index, item in enumerate(items):
        existing_url = _normalize_url(str(item.get("url") or "").strip())
        existing_title = _normalize_label(str(item.get("title") or "").strip())
        existing_kind = _normalize_label(str(item.get("source_kind") or "").strip())
        same_url = bool(candidate_url and existing_url and candidate_url == existing_url)
        same_title = bool(candidate_title and existing_title and candidate_title == existing_title and candidate_kind == existing_kind)
        if not same_url and not same_title:
            continue
        merged = dict(item)
        for key, value in payload.items():
            if value not in ("", None, [], {}):
                merged[key] = value
        items[index] = merged
        replaced = True
        break
    if not replaced:
        items.append(payload)
    return _browser_state_copy(browser_state, evidence_items=items)


def _synthesize_browser_evidence(
    evidence_items: list[dict[str, Any]],
    goal: str,
    research_subject: dict[str, str] | None = None,
) -> dict[str, Any]:
    cleaned = [dict(item) for item in list(evidence_items or []) if isinstance(item, dict)]
    if not cleaned:
        return {}
    subject_title = str((research_subject or {}).get("title") or "").strip()
    goal_text = str(goal or "").strip()
    synthesis_goal = " ".join(part for part in [goal_text, subject_title] if part).strip()
    if not synthesis_goal:
        synthesis_goal = subject_title
    ranked = _rank_cards_against_goal(cleaned, synthesis_goal)
    normalized_goal = _normalize_goal_text(goal_text)
    reranked: list[dict[str, Any]] = []
    for item in ranked:
        candidate = dict(item)
        source_kind = str(candidate.get("source_kind") or candidate.get("page_kind") or "").strip()
        candidate_text = _normalize_goal_text(_card_goal_text(candidate))
        bonus = 0.0
        if len(cleaned) > 1 and any(needle in normalized_goal for needle in {"which source", "best source", "what source", "best explains"}):
            if source_kind == "repo_page":
                bonus -= 2.0
        if any(needle in normalized_goal for needle in {"why people choose", "why people pick", "discussion", "thread"}):
            if source_kind == "post_page":
                bonus += 1.5
            elif source_kind == "video_page":
                bonus += 0.35
        if any(needle in normalized_goal for needle in {"what this repo is for", "what it is for", "overview", "best explains", "explain"}):
            if source_kind == "video_page":
                bonus += 1.0
            elif source_kind == "repo_page":
                bonus += 0.6
            elif source_kind == "post_page":
                bonus += 0.2
            if any(needle in candidate_text for needle in {"overview", "what it is for", "why people use it"}):
                bonus += 0.75
        if any(needle in normalized_goal for needle in {"setup", "walkthrough", "guide", "how to", "beginner"}):
            if source_kind == "video_page":
                bonus += 1.0
            elif source_kind == "post_page":
                bonus += 0.3
        candidate["score"] = round(float(candidate.get("score") or 0.0) + bonus, 4)
        reranked.append(candidate)
    reranked.sort(
        key=lambda item: (
            -float(item.get("score") or 0.0),
            int(item.get("index") or 0),
            str(item.get("title") or ""),
        )
    )
    ranked = reranked
    best = dict(ranked[0]) if ranked else {}
    if not best:
        return {}
    source_kind = str(best.get("source_kind") or best.get("page_kind") or "web_page").strip()
    source_label_map = {
        "repo_page": "GitHub repo",
        "video_page": "YouTube video",
        "post_page": "Reddit post",
        "web_page": "web page",
    }
    source_label = source_label_map.get(source_kind, source_kind.replace("_", " ") or "source")
    explanation_goal = goal_text or subject_title or "the current goal"
    summary = str(best.get("summary") or best.get("title") or "").strip()
    focused_summary = _query_focused_snippet(
        " ".join(
            part
            for part in [
                str(best.get("content_preview") or "").strip(),
                summary,
            ]
            if part
        ),
        explanation_goal or goal_text or subject_title,
    )
    if focused_summary and (
        _looks_like_low_signal_web_text(summary)
        or len(summary) < 40
        or source_kind == "web_page"
    ):
        summary = focused_summary
    best_title = str(best.get("title") or "").strip()
    if source_kind == "web_page":
        if summary and best_title and best_title not in summary:
            synthesis = f"{summary} Source: {best_title}".strip()
        else:
            synthesis = summary or best_title
    elif subject_title:
        synthesis = f"{source_label} \"{best_title}\" best explains {subject_title} for \"{explanation_goal}\". {summary}".strip()
    else:
        synthesis = f"{source_label} \"{best_title}\" best explains \"{explanation_goal}\". {summary}".strip()
    return {
        "goal": explanation_goal,
        "best_source_title": str(best.get("title") or "").strip(),
        "best_source_url": str(best.get("url") or "").strip(),
        "best_source_kind": source_kind,
        "best_source_score": float(best.get("score") or 0.0),
        "best_source_matching_terms": list(best.get("matching_terms") or []),
        "evidence_titles": [str(item.get("title") or "").strip() for item in ranked if str(item.get("title") or "").strip()],
        "source_count": len(cleaned),
        "research_subject_title": subject_title,
        "synthesis": synthesis,
        "ranking": ranked,
    }


def _subject_search_engine_from_prompt(prompt: str) -> str:
    normalized = _intent_text(prompt)
    if any(
        token in normalized
        for token in {
            "search youtube",
            "youtube video",
            "video about it",
            "video about this repo",
            "video about the repo",
            "video about the winner",
            "find a youtube video",
            "find youtube video",
            "find a video about",
            "grab a youtube video",
            "youtube vid",
        }
    ):
        return "youtube"
    if any(
        token in normalized
        for token in {
            "search reddit",
            "reddit post",
            "reddit discussion",
            "find a reddit post",
            "find reddit discussion",
            "discussion about it",
            "post about it",
            "reddit thread",
            "thread about it",
        }
    ):
        return "reddit"
    if any(token in normalized for token in {"search google", "search web", "look it up", "look this up on google"}):
        return "google"
    return ""


def _split_prompt_clauses(prompt: str) -> list[str]:
    text = _normalize_goal_text(prompt)
    for phrase in FILLER_PHRASES:
        text = re.sub(rf"\b{re.escape(_normalize_goal_text(phrase))}\b", " ", text)
    parts = re.split(r"\b(?:and then|then|after that|afterwards|next)\b", text)
    return [part.strip(" ,") for part in parts if part and part.strip(" ,")]


def _wants_open_subject_search_result(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    explicit_tokens = {
        "open the first",
        "open first",
        "click the first",
        "click first",
        "open the video",
        "open the vid",
        "open the repo",
        "open the result",
        "click the video",
        "click the vid",
        "click the repo",
        "click the result",
        "watch it",
        "watch the first",
        "play it",
        "open it",
    }
    if any(token in normalized for token in explicit_tokens):
        return True
    verb_hit = any(token in normalized for token in {"click", "open", "watch", "play", "pick", "select"})
    ordinal_hit = any(token in normalized for token in {"first", "1st", "second", "2nd", "third", "3rd"})
    return verb_hit and ordinal_hit


def _wants_explain_opened_result(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    return any(
        token in normalized
        for token in {
            "tell me what it is",
            "tell me about it",
            "what is it",
            "summarize it",
            "summarise it",
            "sum it up",
            "explain it",
            "what is this video",
            "summarize this video",
            "summarise this video",
            "what is this post",
            "summarize this post",
            "summarise this post",
        }
    )


def _clause_wants_new_tab(prompt: str) -> bool:
    normalized = _intent_text(prompt)
    return any(token in normalized for token in {"new tab", "another tab", "open a tab", "open tab"})


def _rank_or_compare_actions_from_clause(clause: str, browser_state: BrowserSessionState) -> list[TerminalAction]:
    if not _has_cached_result_context(browser_state):
        return []
    normalized = _intent_text(clause)
    compare_hit = "compare" in normalized
    indexes = _comparison_indexes_from_prompt(clause)
    if not compare_hit and "stack rank" in normalized and len(indexes) >= 2:
        compare_hit = True
    rank_hit = any(
        token in normalized
        for token in {
            "rank ",
            "rank these",
            "which repo",
            "which result",
            "best repo",
            "best result",
            "find the best repo",
            "aligns most",
            "matches most",
            "fits best",
        }
    )
    if not rank_hit and "best" in normalized and any(token in normalized for token in {"fit ", "fits ", "matching", "match "}):
        rank_hit = True
    if compare_hit:
        if len(indexes) < 2:
            indexes = [1, 2]
        indexes = indexes[:2]
        goal = _goal_text_from_prompt(clause)
        return [
            TerminalAction(
                kind="browser_compare_cards",
                target=",".join(str(index) for index in indexes),
                resolved_target=",".join(str(index) for index in indexes),
                note=_encode_action_note({"goal": goal, "indexes": indexes}),
            )
        ]
    if rank_hit:
        goal = _goal_text_from_prompt(clause)
        return [
            TerminalAction(
                kind="browser_rank_cards",
                target="current_cards",
                resolved_target="current_cards",
                note=_encode_action_note({"goal": goal}),
            )
        ]
    return []


def _subject_search_actions_from_clause(clause: str) -> list[TerminalAction]:
    engine = _subject_search_engine_from_prompt(clause)
    if not engine:
        return []
    actions = [
        TerminalAction(
            kind="browser_search_subject",
            target=engine,
            resolved_target=engine,
            note=_encode_action_note({"engine": engine}),
        )
    ]
    if _wants_open_subject_search_result(clause):
        result_index = _result_index_from_prompt(clause)
        actions.append(
            TerminalAction(
                kind="open_search_result",
                target=str(result_index),
                resolved_target=str(result_index),
            )
        )
        if _wants_explain_opened_result(clause):
            actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
    return actions


def _wants_retry_subject_result(clause: str) -> bool:
    normalized = _intent_text(clause)
    if not normalized:
        return False
    strong_signals = {
        "if it seems weak",
        "if the first one seems weak",
        "if it is weak",
        "if the first one is weak",
        "if it looks weak",
        "if the first one looks weak",
        "if it seems off topic",
        "if it is off topic",
        "if it feels off topic",
        "if that one seems weak",
        "open a better one",
        "open a stronger one",
        "open a more relevant one",
        "try a better one",
        "try another one",
        "pick a better one",
    }
    if any(signal in normalized for signal in strong_signals):
        return True
    weak_hit = any(token in normalized for token in {"weak", "off topic", "more relevant", "better one", "another one", "stronger one"})
    retry_hit = any(token in normalized for token in {"if ", "instead", "retry", "try another", "pick another", "open another", "open a better", "try a better"})
    return weak_hit and retry_hit


def _retry_subject_actions_from_clause(clause: str) -> list[TerminalAction]:
    if not _wants_retry_subject_result(clause):
        return []
    goal = _goal_text_from_prompt(clause)
    note_payload: dict[str, Any] = {}
    if goal:
        note_payload["goal"] = goal
    actions = [
        TerminalAction(
            kind="browser_retry_subject_result",
            target="better_result",
            resolved_target="better_result",
            note=_encode_action_note(note_payload),
        )
    ]
    if _wants_explain_opened_result(clause):
        actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
    return actions


def _wants_synthesize_evidence(clause: str) -> bool:
    normalized = _intent_text(clause)
    if not normalized:
        return False
    if any(
        signal in normalized
        for signal in {
            "which source best",
            "what source best",
            "best source",
            "best explains",
            "best explanation",
            "most useful source",
            "pull it together",
            "synthesize",
            "sum it up across",
            "across the sources",
            "across youtube and reddit",
        }
    ):
        return True
    return (
        "source" in normalized
        and "best" in normalized
        and any(token in normalized for token in {"explain", "explains", "explained"})
    )


def _synthesis_actions_from_clause(clause: str) -> list[TerminalAction]:
    if not _wants_synthesize_evidence(clause):
        return []
    goal = _goal_text_from_prompt(clause) or clause
    return [
        TerminalAction(
            kind="browser_synthesize_evidence",
            target="current_evidence",
            resolved_target="current_evidence",
            note=_encode_action_note({"goal": goal}),
        )
    ]


def _initial_sequenced_browser_actions(prompt: str) -> list[TerminalAction]:
    clauses = _split_prompt_clauses(prompt)
    if not clauses:
        return []
    actions: list[TerminalAction] = []
    state = BrowserSessionState()
    used_sequence = False
    for clause in clauses:
        clause_actions: list[TerminalAction] = []
        clause_hit = _search_hits_from_text(clause)
        if _clause_wants_new_tab(clause):
            clause_actions.append(TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab"))
            used_sequence = True
        if clause_hit:
            hit = clause_hit[0]
            clause_actions.append(
                TerminalAction(
                    kind="open_url",
                    target=hit["url"],
                    resolved_target=hit["url"],
                    note=_encode_action_note(
                        {
                            "search_engine": hit["engine"],
                            "search_query": hit["query"],
                            "page_kind": "search_results",
                            "tab_mode": "new_tab" if _clause_wants_new_tab(clause) else "",
                        }
                    ),
                )
            )
            state = _browser_state_for_url(
                hit["url"],
                search_engine=hit["engine"],
                search_query=hit["query"],
            )
            used_sequence = True
        if state.page_kind == "search_results" and _wants_open_subject_search_result(clause):
            result_index = _result_index_from_prompt(clause)
            clause_actions.append(
                TerminalAction(
                    kind="open_search_result",
                    target=str(result_index),
                    resolved_target=str(result_index),
                    note=_encode_action_note(
                        {
                            "search_engine": state.search_engine,
                            "search_query": state.search_query,
                            "page_kind": state.page_kind,
                        }
                    ),
                )
            )
            if state.search_engine == "youtube":
                state = _browser_state_for_url("https://www.youtube.com/watch?v=placeholder")
            elif state.search_engine == "github":
                state = _browser_state_for_url("https://github.com/example/repo")
            elif state.search_engine == "reddit":
                state = _browser_state_for_url("https://www.reddit.com/r/example/comments/post")
            else:
                state = BrowserSessionState(current_url="about:blank", page_kind="web_page")
            used_sequence = True
            if _wants_explain_opened_result(clause):
                clause_actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
        elif state.current_url and _wants_browser_read(clause):
            clause_actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
            used_sequence = True
        actions.extend(clause_actions)
    return actions if used_sequence and len(actions) >= 2 else []


def _sequenced_browser_actions(prompt: str, browser_state: BrowserSessionState) -> list[TerminalAction]:
    clauses = _split_prompt_clauses(prompt)
    if len(clauses) < 2:
        return []
    actions: list[TerminalAction] = []
    has_subject = bool(_research_subject_from_browser_state(browser_state) or _subject_from_browser_state(browser_state) or browser_state.page_kind == "repo_page")
    search_results_available = _has_cached_result_context(browser_state)
    pending_search_result = False
    opened_subject_result = False
    evidence_available = bool(browser_state.evidence_items)
    for index, clause in enumerate(clauses):
        next_clause = clauses[index + 1] if index + 1 < len(clauses) else ""
        clause_actions: list[TerminalAction] = []
        if search_results_available:
            clause_actions = _rank_or_compare_actions_from_clause(clause, browser_state)
            if clause_actions:
                actions.extend(clause_actions)
                has_subject = True
                search_results_available = False
                pending_search_result = False
                evidence_available = True
                continue
        clause_actions = _retry_subject_actions_from_clause(clause)
        if clause_actions and opened_subject_result:
            actions.extend(clause_actions)
            pending_search_result = False
            opened_subject_result = any(action.kind == "browser_retry_subject_result" for action in clause_actions) or opened_subject_result
            if any(action.kind == "browser_read_page" for action in clause_actions):
                evidence_available = True
            continue
        clause_actions = _subject_search_actions_from_clause(clause)
        if clause_actions and has_subject:
            if (
                any(action.kind == "open_search_result" for action in clause_actions)
                and not any(action.kind == "browser_read_page" for action in clause_actions)
                and (_wants_synthesize_evidence(next_clause) or _wants_retry_subject_result(next_clause))
            ):
                clause_actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
            actions.extend(clause_actions)
            has_subject = True
            pending_search_result = any(action.kind == "browser_search_subject" for action in clause_actions)
            if any(action.kind == "open_search_result" for action in clause_actions):
                pending_search_result = False
                opened_subject_result = True
            if any(action.kind == "browser_read_page" for action in clause_actions):
                evidence_available = True
            continue
        if pending_search_result and _wants_open_subject_search_result(clause):
            result_index = _result_index_from_prompt(clause)
            actions.append(
                TerminalAction(
                    kind="open_search_result",
                    target=str(result_index),
                    resolved_target=str(result_index),
                )
            )
            if _wants_explain_opened_result(clause):
                actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
                evidence_available = True
            elif _wants_synthesize_evidence(next_clause) or _wants_retry_subject_result(next_clause):
                actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
                evidence_available = True
            pending_search_result = False
            opened_subject_result = True
            continue
        clause_actions = _synthesis_actions_from_clause(clause)
        if clause_actions and evidence_available:
            actions.extend(clause_actions)
    search_subject_steps = sum(1 for action in actions if action.kind == "browser_search_subject")
    if any(action.kind == "browser_synthesize_evidence" for action in actions):
        return actions if search_subject_steps >= 2 else []
    return actions if search_subject_steps >= 2 else []


def _comparison_indexes_from_prompt(prompt: str) -> list[int]:
    normalized = _intent_text(prompt)
    hits: list[int] = []
    for token, value in (
        ("first", 1),
        ("1st", 1),
        ("one", 1),
        ("second", 2),
        ("2nd", 2),
        ("two", 2),
        ("third", 3),
        ("3rd", 3),
        ("three", 3),
    ):
        if token in normalized and value not in hits:
            hits.append(value)
    for match in re.findall(r"\b(\d+)(?:st|nd|rd|th)?\b", normalized):
        try:
            value = max(int(match), 1)
        except ValueError:
            continue
        if value not in hits:
            hits.append(value)
    return hits[:3]


def _follow_up_browser_actions(prompt: str, browser_state: BrowserSessionState | None) -> list[TerminalAction]:
    if browser_state is None:
        return []
    normalized = _intent_text(prompt)
    actions: list[TerminalAction] = []
    sequenced_actions = _sequenced_browser_actions(prompt, browser_state)
    if sequenced_actions:
        return sequenced_actions
    if browser_state.evidence_items:
        synthesis_actions = _synthesis_actions_from_clause(prompt)
        if synthesis_actions:
            return synthesis_actions
    related_engine = _subject_search_engine_from_prompt(prompt)
    open_related_result = _wants_open_subject_search_result(prompt)
    explain_related_result = _wants_explain_opened_result(prompt)
    if browser_state.current_url and any(token in normalized for token in {"take screenshot", "capture screenshot", "screenshot"}):
        actions.append(TerminalAction(kind="browser_screenshot", target="current_page", resolved_target="current_page"))
        return actions
    if browser_state.current_url and any(token in normalized for token in {"wait "}):
        seconds_match = re.search(r"\bwait(?: for)?\s+(\d+(?:\.\d+)?)", normalized)
        seconds = seconds_match.group(1) if seconds_match else "1"
        actions.append(TerminalAction(kind="browser_wait", target=seconds, resolved_target=seconds))
        return actions
    wants_new_tab = browser_state.current_url and _clause_wants_new_tab(prompt)
    if wants_new_tab:
        search_hits = _search_hits(prompt)
        if search_hits:
            hit = search_hits[0]
            actions.append(TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab"))
            actions.append(
                TerminalAction(
                    kind="open_url",
                    target=hit["url"],
                    resolved_target=hit["url"],
                    note=_encode_action_note(
                        {
                            "search_engine": hit["engine"],
                            "search_query": hit["query"],
                            "page_kind": "search_results",
                            "tab_mode": "new_tab",
                        }
                    ),
                )
            )
            if _wants_open_subject_search_result(prompt):
                result_index = _result_index_from_prompt(prompt)
                actions.append(
                    TerminalAction(
                        kind="open_search_result",
                        target=str(result_index),
                        resolved_target=str(result_index),
                    )
                )
                if _wants_explain_opened_result(prompt):
                    actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
            return actions
        actions.append(TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab"))
        return actions
    if browser_state.current_url and any(
        token in normalized
        for token in {"close tab", "close this tab", "close the tab", "close current tab"}
    ):
        actions.append(TerminalAction(kind="browser_close_tab", target="current_tab", resolved_target="current_tab"))
        return actions
    if browser_state.current_url and any(token in normalized for token in {"next tab", "previous tab", "prev tab", "switch tab", "switch to tab"}):
        target = "next"
        if any(token in normalized for token in {"previous tab", "prev tab"}):
            target = "previous"
        else:
            match = re.search(r"\btab\s+(\d+)\b", normalized)
            if match:
                target = match.group(1)
        actions.append(TerminalAction(kind="browser_switch_tab", target=target, resolved_target=target))
        return actions
    if browser_state.current_url and not related_engine and any(
        token in normalized for token in {"extract page", "extract this page", "extract current page"}
    ):
        actions.append(TerminalAction(kind="browser_extract_page", target="current_page", resolved_target="current_page"))
        return actions
    if browser_state.current_url and not related_engine and _wants_browser_read(prompt):
        actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
        return actions
    if _has_cached_result_context(browser_state):
        compare_hit = "compare" in normalized
        rank_hit = any(
            token in normalized
            for token in {
                "rank ",
                "rank these",
                "which repo",
                "which result",
                "best repo",
                "best result",
                "aligns most",
                "matches most",
                "fits best",
            }
        )
        if related_engine and compare_hit:
            indexes = _comparison_indexes_from_prompt(prompt)
            if len(indexes) < 2:
                indexes = [1, 2]
            indexes = indexes[:2]
            goal = _goal_text_from_prompt(_leading_clause_text(prompt))
            actions.append(
                TerminalAction(
                    kind="browser_compare_cards",
                    target=",".join(str(index) for index in indexes),
                    resolved_target=",".join(str(index) for index in indexes),
                    note=_encode_action_note({"goal": goal, "indexes": indexes}),
                )
            )
            actions.append(
                TerminalAction(
                    kind="browser_search_subject",
                    target=related_engine,
                    resolved_target=related_engine,
                    note=_encode_action_note({"engine": related_engine}),
                )
            )
            if open_related_result:
                result_index = _result_index_from_prompt(prompt)
                actions.append(
                    TerminalAction(
                        kind="open_search_result",
                        target=str(result_index),
                        resolved_target=str(result_index),
                    )
                )
                if explain_related_result:
                    actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
            return actions
        if related_engine and rank_hit:
            goal = _goal_text_from_prompt(_leading_clause_text(prompt))
            actions.append(
                TerminalAction(
                    kind="browser_rank_cards",
                    target="current_cards",
                    resolved_target="current_cards",
                    note=_encode_action_note({"goal": goal}),
                )
            )
            actions.append(
                TerminalAction(
                    kind="browser_search_subject",
                    target=related_engine,
                    resolved_target=related_engine,
                    note=_encode_action_note({"engine": related_engine}),
                )
            )
            if open_related_result:
                result_index = _result_index_from_prompt(prompt)
                actions.append(
                    TerminalAction(
                        kind="open_search_result",
                        target=str(result_index),
                        resolved_target=str(result_index),
                    )
                )
                if explain_related_result:
                    actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
            return actions
        if compare_hit:
            indexes = _comparison_indexes_from_prompt(prompt)
            if len(indexes) < 2:
                indexes = [1, 2]
            indexes = indexes[:2]
            goal = _goal_text_from_prompt(prompt)
            actions.append(
                TerminalAction(
                    kind="browser_compare_cards",
                    target=",".join(str(index) for index in indexes),
                    resolved_target=",".join(str(index) for index in indexes),
                    note=_encode_action_note({"goal": goal, "indexes": indexes}),
                )
            )
            return actions
        if rank_hit:
            goal = _goal_text_from_prompt(prompt)
            actions.append(
                TerminalAction(
                    kind="browser_rank_cards",
                    target="current_cards",
                    resolved_target="current_cards",
                    note=_encode_action_note({"goal": goal}),
                )
            )
            return actions
    if related_engine and (_subject_from_browser_state(browser_state) or browser_state.page_kind == "repo_page"):
        actions.append(
            TerminalAction(
                kind="browser_search_subject",
                target=related_engine,
                resolved_target=related_engine,
                note=_encode_action_note({"engine": related_engine}),
            )
        )
        if open_related_result:
            result_index = _result_index_from_prompt(prompt)
            actions.append(
                TerminalAction(
                    kind="open_search_result",
                    target=str(result_index),
                    resolved_target=str(result_index),
                )
            )
            if explain_related_result:
                actions.append(TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page"))
        return actions
    if browser_state.current_url and any(
        token in normalized
        for token in {"extract cards", "extract results", "show results", "show top results", "list results", "top 5", "top five"}
    ):
        actions.append(TerminalAction(kind="browser_extract_cards", target="current_cards", resolved_target="current_cards"))
        return actions
    if any(token in normalized for token in {"go back", "back"}):
        actions.append(TerminalAction(kind="browser_back", target="back", resolved_target="back"))
        return actions
    if any(token in normalized for token in {"go forward", "forward"}):
        actions.append(TerminalAction(kind="browser_forward", target="forward", resolved_target="forward"))
        return actions
    if browser_state.current_url and any(token in normalized for token in {"scroll down", "page down", "scroll up", "page up"}):
        direction = "down" if any(token in normalized for token in {"scroll down", "page down"}) else "up"
        actions.append(TerminalAction(kind="browser_scroll", target=direction, resolved_target=direction))
        return actions
    if browser_state.current_url and any(token in normalized for token in {"type ", "enter ", "fill "}):
        match = re.search(r"\b(?:type|enter|fill)\s+(.+)$", normalized)
        if match:
            text = str(match.group(1) or "").strip().strip("\"'")
            if text:
                actions.append(TerminalAction(kind="browser_type_text", target=text, resolved_target=text))
                return actions
    if browser_state.current_url and any(token in normalized for token in {"submit", "press enter", "hit enter"}):
        actions.append(TerminalAction(kind="browser_submit", target="submit", resolved_target="submit"))
        return actions
    if any(token in normalized for token in {"pause", "stop"}):
        actions.append(TerminalAction(kind="browser_media_pause", target="media", resolved_target="media"))
        return actions
    if any(token in normalized for token in {"resume", "continue playing", "play it", "play"}):
        actions.append(TerminalAction(kind="browser_media_play", target="media", resolved_target="media"))
        return actions
    if not _has_result_resolution_context(browser_state):
        return actions
    verb_hit = any(token in normalized for token in {"click", "open", "press", "select", "pick"})
    noun_hit = any(token in normalized for token in {"video", "vid", "repo", "result"})
    ordinal_hit = any(token in normalized for token in {"first", "1st", "second", "2nd", "third", "3rd"})
    wants_result = any(
        token in normalized
        for token in {
            "click first",
            "click the first",
            "open first",
            "open the first",
            "press on",
            "click on",
            "open the video",
            "open the vid",
            "open the repo",
            "click the video",
            "click the vid",
            "click the repo",
            "click result",
            "open result",
        }
    ) or (verb_hit and noun_hit) or (verb_hit and ordinal_hit)
    if wants_result:
        index = _result_index_from_prompt(prompt)
        actions.append(
            TerminalAction(
                kind="open_search_result",
                target=str(index),
                resolved_target=str(index),
                note=_encode_action_note(
                    {
                        "search_engine": browser_state.search_engine,
                        "search_query": browser_state.search_query,
                        "page_kind": browser_state.page_kind,
                    }
                ),
            )
        )
        return actions
    if browser_state.current_url:
        explicit_index = re.search(r"\b(?:click|open|select)\s+(?:item|card|result)\s+(\d+)\b", normalized)
        if explicit_index:
            value = explicit_index.group(1)
            actions.append(TerminalAction(kind="browser_click_index", target=value, resolved_target=value))
            return actions
    click_text = _text_target_from_prompt(prompt)
    if browser_state.current_url and click_text and _cached_cards(browser_state):
        actions.append(TerminalAction(kind="browser_click_text", target=click_text, resolved_target=click_text))
        return actions
    return actions


def _heuristic_plan(prompt: str, *, browser_state: BrowserSessionState | None = None) -> TerminalPlan | None:
    if _contains_risky_intent(prompt):
        return TerminalPlan(
            prompt=prompt,
            source="heuristic",
            clarification="This V1 terminal only supports safe launch/open/status tasks.",
            residual_constraints=["unsupported_risky_action"],
        )
    standalone_web_answer = _general_web_answer_action(prompt)
    if standalone_web_answer is not None and not _looks_like_contextual_browser_followup(prompt):
        return TerminalPlan(prompt=prompt, source="heuristic", actions=[standalone_web_answer])
    follow_up_actions = _follow_up_browser_actions(prompt, browser_state)
    if follow_up_actions:
        return TerminalPlan(prompt=prompt, source="heuristic", actions=follow_up_actions)
    initial_sequenced_actions = _initial_sequenced_browser_actions(prompt)
    if initial_sequenced_actions:
        return TerminalPlan(prompt=prompt, source="heuristic", actions=initial_sequenced_actions)
    app_alias_map = {key: tuple(spec.get("aliases") or ()) for key, spec in APP_SPECS.items()}
    path_alias_map = {key: (key,) for key in PATH_ALIASES}
    app_hits = _alias_hits(prompt, app_alias_map)
    path_hits = _alias_hits(prompt, path_alias_map)
    search_hits = _search_hits(prompt)
    url_hits = _url_hits(prompt)
    normalized = _normalize_label(prompt)

    actions: list[TerminalAction] = []
    if search_hits:
        actions.extend(
            TerminalAction(
                kind="open_url",
                target=hit["url"],
                resolved_target=hit["url"],
                note=_encode_action_note(
                    {
                        "search_engine": hit["engine"],
                        "search_query": hit["query"],
                        "page_kind": "search_results",
                    }
                ),
            )
            for hit in search_hits
        )
    if url_hits:
        actions.extend(TerminalAction(kind="open_url", target=url, resolved_target=url) for url in url_hits)
    if app_hits:
        actions.extend(TerminalAction(kind="launch_app", target=app, resolved_target=app) for app in app_hits)
    if not actions and path_hits and any(token in normalized for token in {"open", "show", "browse"}):
        actions.extend(
            TerminalAction(kind="open_path", target=key, resolved_target=PATH_ALIASES[key])
            for key in path_hits
        )
    if not actions and path_hits and any(token in normalized for token in {"list", "ls", "what s in", "what is in"}):
        actions.extend(
            TerminalAction(kind="list_directory", target=key, resolved_target=PATH_ALIASES[key])
            for key in path_hits
        )
    if not actions:
        for topic in SUPPORTED_SYSTEM_INFO_TOPICS:
            if topic in normalized and any(token in normalized for token in {"show", "check", "status", "usage", "what s", "what is"}):
                actions.append(TerminalAction(kind="system_info", target=topic, resolved_target=topic))
                break
    if not actions:
        if standalone_web_answer is not None:
            actions.append(standalone_web_answer)

    if not actions:
        return None
    return TerminalPlan(prompt=prompt, source="heuristic", actions=actions)


def _extract_json_object(response: str) -> dict[str, Any]:
    text = str(response or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _llm_prompt(prompt: str, *, browser_state: BrowserSessionState | None = None) -> list[ChatMessage]:
    app_ids = ", ".join(sorted(APP_SPECS))
    path_ids = ", ".join(sorted(PATH_ALIASES))
    topics = ", ".join(sorted(SUPPORTED_SYSTEM_INFO_TOPICS))
    schema = {
        "actions": [{"kind": "launch_app", "target": "chrome"}],
        "needs_confirmation": False,
        "clarification": "",
    }
    context_lines: list[str] = []
    if browser_state is not None:
        if browser_state.current_url:
            context_lines.append(f"Current browser URL: {browser_state.current_url}")
        if browser_state.page_kind:
            context_lines.append(f"Current browser page kind: {browser_state.page_kind}")
        if browser_state.search_engine and browser_state.search_query:
            context_lines.append(
                "Current browser search context: "
                f"engine={browser_state.search_engine}; query={browser_state.search_query}"
            )
        if browser_state.subject_title:
            context_lines.append(
                "Current browser subject: "
                f"title={browser_state.subject_title}; url={browser_state.subject_url or '(none)'}"
            )
        if browser_state.research_subject_title:
            context_lines.append(
                "Current browser research subject: "
                f"title={browser_state.research_subject_title}; url={browser_state.research_subject_url or '(none)'}"
            )
        if browser_state.result_urls:
            context_lines.append(f"Cached browser results: {len(browser_state.result_urls)}")
        if context_lines:
            context_lines.append(
                "If the user refers to the current browser page or asks to click a result/video/repo, "
                "use open_search_result or browser_click_index with a 1-based result index, browser_click_text for a known visible label, "
                "browser_read_page/browser_extract_page for reading the current page, browser_extract_cards for current result cards, "
                "browser_rank_cards for ranking current cached cards against a goal, browser_compare_cards for comparing cached cards against a goal, browser_search_subject for searching another site about the active subject, browser_retry_subject_result for reopening a stronger cached result, "
                "browser_synthesize_evidence for choosing the best current source from accumulated evidence, browser_answer_query for bounded live web questions, "
                "browser_new_tab/browser_close_tab/browser_switch_tab for tab control, browser_back/browser_forward/browser_scroll/browser_type_text/browser_submit/browser_wait/browser_screenshot for browser control, "
                "or browser_media_* when appropriate."
            )
    context_block = ""
    if context_lines:
        context_block = "\nBrowser session context:\n- " + "\n- ".join(context_lines) + "\n"
    return [
        ChatMessage(
            role="system",
            content=(
                "You translate natural terminal requests into a tiny safe JSON action plan.\n"
                "Allowed action kinds: launch_app, open_url, browser_answer_query, browser_new_tab, browser_close_tab, browser_switch_tab, open_search_result, browser_click_index, browser_click_text, browser_read_page, browser_extract_page, browser_extract_cards, browser_rank_cards, browser_compare_cards, browser_search_subject, browser_retry_subject_result, browser_synthesize_evidence, open_path, browser_back, browser_forward, browser_scroll, browser_type_text, browser_submit, browser_wait, browser_screenshot, browser_media_pause, browser_media_play, list_directory, system_info, unsupported.\n"
                f"Allowed app ids: {app_ids}.\n"
                f"Allowed path ids: {path_ids}.\n"
                f"Allowed system_info targets: {topics}.\n"
                "Never emit shell commands. Never suggest destructive or privileged actions. "
                "If the request is risky or unsupported, return a single unsupported action.\n"
                f"{context_block}"
                f"Return JSON only in this shape: {json.dumps(schema)}"
            ),
        ),
        ChatMessage(role="user", content=prompt),
    ]


def _language_llm_prompt(prompt: str, *, browser_state: BrowserSessionState | None = None) -> list[ChatMessage]:
    app_ids = ", ".join(sorted(APP_SPECS))
    path_ids = ", ".join(sorted(PATH_ALIASES))
    topics = ", ".join(sorted(SUPPORTED_SYSTEM_INFO_TOPICS))
    schema = {
        "actions": [{"kind": "open_search_result", "target": "1"}],
        "needs_confirmation": False,
        "clarification": "",
    }
    context_lines: list[str] = []
    if browser_state is not None:
        if browser_state.current_url:
            context_lines.append(f"Current browser URL: {browser_state.current_url}")
        if browser_state.page_kind:
            context_lines.append(f"Current browser page kind: {browser_state.page_kind}")
        if browser_state.search_engine and browser_state.search_query:
            context_lines.append(
                "Current browser search context: "
                f"engine={browser_state.search_engine}; query={browser_state.search_query}"
            )
        if browser_state.subject_title:
            context_lines.append(
                "Current browser subject: "
                f"title={browser_state.subject_title}; url={browser_state.subject_url or '(none)'}"
            )
        if browser_state.research_subject_title:
            context_lines.append(
                "Current browser research subject: "
                f"title={browser_state.research_subject_title}; url={browser_state.research_subject_url or '(none)'}"
            )
        if browser_state.result_urls:
            context_lines.append(f"Cached browser results: {len(browser_state.result_urls)}")
        if browser_state.evidence_items:
            context_lines.append(f"Cached evidence items: {len(browser_state.evidence_items)}")
    context_block = ""
    if context_lines:
        context_block = "\nBrowser session context:\n- " + "\n- ".join(context_lines) + "\n"
    compiler_surface = _compiler_surface_text(prompt)
    examples = [
        {
            "user": "yo open a tab and toss nine vicious on youtube",
            "assistant": {"actions": [{"kind": "browser_new_tab", "target": "new_tab"}, {"kind": "open_url", "target": "https://www.youtube.com/results?search_query=nine+vicious"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "click he first vid you see",
            "assistant": {"actions": [{"kind": "open_search_result", "target": "1"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "peep a youtube vid on this repo and open the first one",
            "assistant": {"actions": [{"kind": "browser_search_subject", "target": "youtube"}, {"kind": "open_search_result", "target": "1"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "if that first one is bunk grab a better one and sum it up",
            "assistant": {"actions": [{"kind": "browser_retry_subject_result", "target": "better_result"}, {"kind": "browser_read_page", "target": "current_page"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "find whatever repo best fits beginner weak laptop local llm",
            "assistant": {"actions": [{"kind": "browser_rank_cards", "target": "beginner weak laptop local llm"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "compare the first two repos for cpp cpu inference",
            "assistant": {"actions": [{"kind": "browser_compare_cards", "target": "1,2"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "find a youtube video about the winner and open the first one",
            "assistant": {"actions": [{"kind": "browser_search_subject", "target": "youtube"}, {"kind": "open_search_result", "target": "1"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "tell me which source best explains what this repo is for",
            "assistant": {"actions": [{"kind": "browser_synthesize_evidence", "target": "what this repo is for"}], "needs_confirmation": False, "clarification": ""},
        },
        {
            "user": "what's happening in the news about ai agents today?",
            "assistant": {"actions": [{"kind": "browser_answer_query", "target": "ai agents news today"}], "needs_confirmation": False, "clarification": ""},
        },
    ]
    example_lines = []
    for example in examples:
        example_lines.append(f"User: {example['user']}")
        example_lines.append(f"JSON: {json.dumps(example['assistant'], separators=(',', ':'))}")
    return [
        ChatMessage(
            role="system",
            content=(
                "You are Memla Language Ontology V2.\n"
                "Your job is only to compile messy human language into a tiny legal JSON action plan inside Memla's existing bounded world.\n"
                "Do not solve the task yourself. Do not invent new capabilities. Do not emit shell commands.\n"
                "Prefer canonical actions over free-form behavior.\n"
                "If the wording is messy but the intent is recoverable, compile it.\n"
                "If the request is still ambiguous or unsupported, return a single unsupported action with a short clarification.\n"
                "Allowed action kinds: launch_app, open_url, browser_answer_query, browser_new_tab, browser_close_tab, browser_switch_tab, open_search_result, browser_click_index, browser_click_text, browser_read_page, browser_extract_page, browser_extract_cards, browser_rank_cards, browser_compare_cards, browser_search_subject, browser_retry_subject_result, browser_synthesize_evidence, open_path, browser_back, browser_forward, browser_scroll, browser_type_text, browser_submit, browser_wait, browser_screenshot, browser_media_pause, browser_media_play, list_directory, system_info, unsupported.\n"
                f"Allowed app ids: {app_ids}.\n"
                f"Allowed path ids: {path_ids}.\n"
                f"Allowed system_info targets: {topics}.\n"
                "Canonical conventions:\n"
                "- use open_search_result with a 1-based index for first/second/third result language\n"
                "- use browser_search_subject for 'video/post/thread about this repo/winner/it'\n"
                "- use browser_rank_cards or browser_compare_cards only when the user is judging current search cards\n"
                "- use browser_retry_subject_result when the user wants a better follow-on result because the first one is weak/off-topic\n"
                "- use browser_synthesize_evidence when the user asks which source best explains something across already-read sources\n"
                "- use browser_answer_query for bounded live web questions like news, weather, latest changes, or factual lookups that need current web retrieval\n"
                "- use open_url with a full URL only for direct page opens or direct site searches\n"
                "- if a normalized translation surface is provided, use it as the main intent signal and only use the raw wording for nuance\n"
                f"{context_block}"
                "Examples:\n"
                + "\n".join(example_lines)
                + "\nReturn JSON only in this shape: "
                + json.dumps(schema)
            ),
        ),
        ChatMessage(
            role="user",
            content=(
                "Raw request:\n"
                f"{prompt}\n\n"
                "Normalized translation surface:\n"
                f"{compiler_surface}"
            ),
        ),
    ]


def _plan_from_model_response(*, prompt: str, response: str, source: str) -> TerminalPlan:
    payload = _extract_json_object(response)
    actions = _normalize_model_actions(payload)
    clarification = str(payload.get("clarification") or "").strip()
    needs_confirmation = bool(payload.get("needs_confirmation"))
    if not actions:
        return TerminalPlan(
            prompt=prompt,
            source=source,
            clarification=clarification or "I could not map that request to a safe bounded terminal action.",
            residual_constraints=["unsupported_or_ambiguous_request"],
        )
    return TerminalPlan(
        prompt=prompt,
        source=source,
        actions=actions,
        needs_confirmation=needs_confirmation,
        clarification=clarification,
        residual_constraints=[],
    )


def _validate_language_actions(
    actions: list[TerminalAction],
    *,
    browser_state: BrowserSessionState | None = None,
) -> tuple[bool, list[str]]:
    state = _browser_state_copy(browser_state or BrowserSessionState())
    has_subject = bool(_research_subject_from_browser_state(state) or _subject_from_browser_state(state) or state.page_kind == "repo_page")
    evidence_available = bool(state.evidence_items)
    for action in actions:
        if action.kind == "unsupported":
            return True, []
        if action.kind == "browser_answer_query":
            continue
        if action.kind in {"browser_rank_cards", "browser_compare_cards"}:
            if not _has_result_resolution_context(state):
                return False, ["browser_state_missing_search_results"]
            has_subject = True
            evidence_available = True
            continue
        if action.kind == "browser_search_subject":
            if not has_subject:
                return False, ["browser_subject_missing"]
            note = _decode_action_note(action.note)
            engine = str(note.get("engine") or action.resolved_target or action.target or "").strip()
            query = _research_subject_query_from_browser_state(state) or _subject_query_from_browser_state(state) or "subject"
            state = _browser_state_for_url(_search_url(engine, query), search_engine=engine, search_query=query)
            continue
        if action.kind == "open_url":
            note = _decode_action_note(action.note)
            state = _browser_state_for_url(
                action.resolved_target or action.target,
                search_engine=str(note.get("search_engine") or "").strip(),
                search_query=str(note.get("search_query") or "").strip(),
                research_subject_title=state.research_subject_title,
                research_subject_url=state.research_subject_url,
                research_subject_summary=state.research_subject_summary,
            )
            continue
        if action.kind == "open_search_result":
            if not _has_result_resolution_context(state):
                return False, ["browser_state_missing_search_results"]
            engine = state.search_engine
            subject_url = state.current_url or "https://example.com"
            if _cached_cards(state):
                try:
                    result_index = max(int(action.resolved_target or action.target), 1)
                except ValueError:
                    result_index = 1
                chosen_card = _resolve_card_by_index(state, result_index)
                if chosen_card:
                    subject_url = str(chosen_card.get("url") or subject_url).strip() or subject_url
            if engine == "youtube":
                state = _browser_state_for_url("https://www.youtube.com/watch?v=placeholder")
            elif engine == "github":
                state = _browser_state_for_url("https://github.com/example/repo")
            elif engine == "reddit":
                state = _browser_state_for_url("https://www.reddit.com/r/example/comments/post")
            else:
                state = _browser_state_for_url(subject_url)
            state = _browser_state_copy(
                state,
                search_engine=browser_state.search_engine if browser_state else state.search_engine,
                search_query=browser_state.search_query if browser_state else state.search_query,
                result_urls=list(browser_state.result_urls or []) if browser_state else list(state.result_urls or []),
                result_cards=[dict(item) for item in list(browser_state.result_cards or []) if isinstance(item, dict)] if browser_state else [dict(item) for item in list(state.result_cards or []) if isinstance(item, dict)],
            )
            evidence_available = evidence_available or state.page_kind in {"repo_page", "video_page", "post_page", "web_page"}
            continue
        if action.kind == "browser_retry_subject_result":
            if not has_subject:
                return False, ["browser_subject_missing"]
            evidence_available = True
            continue
        if action.kind in {"browser_read_page", "browser_extract_page", "browser_screenshot"}:
            if not state.current_url and state.page_kind not in {"repo_page", "video_page", "post_page", "web_page"}:
                return False, ["browser_state_missing_page"]
            evidence_available = True
            continue
        if action.kind == "browser_extract_cards":
            if not _has_result_resolution_context(state):
                return False, ["browser_state_missing_search_results"]
            continue
        if action.kind == "browser_synthesize_evidence":
            if not evidence_available:
                return False, ["browser_evidence_missing"]
            continue
        if action.kind in {"browser_new_tab", "browser_close_tab", "browser_switch_tab", "browser_back", "browser_forward", "browser_scroll", "browser_type_text", "browser_submit", "browser_wait", "browser_media_pause", "browser_media_play", "browser_click_index", "browser_click_text", "launch_app", "open_path", "list_directory", "system_info"}:
            continue
    return True, []


def _surface_language_actions(prompt: str, *, browser_state: BrowserSessionState | None = None) -> list[TerminalAction]:
    surface = _compiler_surface_text(prompt)
    state = browser_state or BrowserSessionState()
    if browser_state is not None:
        sequenced = _sequenced_browser_actions(surface, state)
        if sequenced:
            return sequenced
        follow_up = _follow_up_browser_actions(surface, state)
        if follow_up:
            return follow_up
    initial = _initial_sequenced_browser_actions(surface)
    if initial:
        return initial
    heuristic = _heuristic_plan(surface, browser_state=browser_state)
    if heuristic is not None:
        return list(heuristic.actions)
    return []


def _merge_language_actions(
    current_actions: list[TerminalAction],
    *,
    prompt: str,
    browser_state: BrowserSessionState | None = None,
) -> list[TerminalAction]:
    surface_actions = _surface_language_actions(prompt, browser_state=browser_state)
    if not surface_actions:
        return list(current_actions)
    if not current_actions:
        return surface_actions
    current_signatures = {_action_signature(action) for action in current_actions}
    surface_signatures = [_action_signature(action) for action in surface_actions]
    if current_signatures.issubset(set(surface_signatures)) and len(surface_actions) > len(current_actions):
        return surface_actions
    return list(current_actions)


def _language_prompt_tokens(prompt: str) -> list[str]:
    normalized = _intent_text(prompt)
    return [
        token
        for token in normalized.split()
        if token and token not in LANGUAGE_MEMORY_STOPWORDS and len(token) > 1
    ]


def _language_context_profile(browser_state: BrowserSessionState | None) -> dict[str, Any]:
    state = browser_state or BrowserSessionState()
    return {
        "page_kind": state.page_kind,
        "search_engine": state.search_engine,
        "has_search_results": _has_result_resolution_context(state),
        "has_subject": bool(_research_subject_from_browser_state(state) or _subject_from_browser_state(state) or state.page_kind == "repo_page"),
        "has_evidence": bool(state.evidence_items),
    }


def _browser_state_from_mapping(payload: dict[str, Any] | None) -> BrowserSessionState:
    item = dict(payload or {})
    return BrowserSessionState(
        current_url=str(item.get("current_url") or "").strip(),
        page_kind=str(item.get("page_kind") or "").strip(),
        browser_app=str(item.get("browser_app") or "").strip(),
        search_engine=str(item.get("search_engine") or "").strip(),
        search_query=str(item.get("search_query") or "").strip(),
        result_urls=[str(value).strip() for value in list(item.get("result_urls") or []) if str(value).strip()],
        result_cards=[dict(value) for value in list(item.get("result_cards") or []) if isinstance(value, dict)],
        subject_title=str(item.get("subject_title") or "").strip(),
        subject_url=str(item.get("subject_url") or "").strip(),
        subject_summary=str(item.get("subject_summary") or "").strip(),
        research_subject_title=str(item.get("research_subject_title") or "").strip(),
        research_subject_url=str(item.get("research_subject_url") or "").strip(),
        research_subject_summary=str(item.get("research_subject_summary") or "").strip(),
        evidence_items=[dict(value) for value in list(item.get("evidence_items") or []) if isinstance(value, dict)],
    )


def _scout_memory_signatures(result: TerminalScoutResult) -> list[str]:
    signatures: list[str] = [f"scout_kind:{_normalize_label(result.scout_kind)}"]
    read_count = 0
    rank_count = 0
    for step in result.steps:
        transmutation = _normalize_label(step.transmutation).replace(" ", "_")
        if not transmutation:
            continue
        if transmutation == "browser_extract_cards":
            signatures.append("browser_extract_cards:github")
            continue
        if transmutation == "browser_rank_cards":
            rank_count += 1
            signatures.append(f"browser_rank_cards:{'rerank' if rank_count > 1 else 'initial'}")
            continue
        if transmutation == "browser_read_page":
            read_count += 1
            signatures.append("browser_read_page:top_candidate")
            continue
        signatures.append(f"{transmutation}:scout")
    return signatures


def _record_scout_autonomy_memory(
    result: TerminalScoutResult,
    *,
    state_path: str | Path | None = None,
) -> None:
    if not result.ok:
        return
    signatures = _scout_memory_signatures(result)
    if not signatures:
        return
    state = _browser_state_from_mapping(result.browser_state)
    canonical_clauses = [
        "scout github repositories",
        "rank candidates against the goal",
        "inspect top candidates",
        "rerank and return a report",
    ]
    if result.goal:
        canonical_clauses.append(f"best match for {result.goal}")
    adjudicate_memory_trace(
        prompt=result.prompt,
        normalized_prompt=_intent_text(" ".join(part for part in [result.prompt, result.query, result.goal] if part)),
        tokens=_language_prompt_tokens(" ".join(part for part in [result.prompt, result.query, result.goal] if part)),
        context_profile=_language_context_profile(state),
        action_signatures=signatures,
        source="autonomy_scout",
        success=True,
        path=_terminal_memory_ontology_path_for_state(state_path),
        memory_kind=f"autonomy_{result.scout_kind}",
        canonical_clauses=canonical_clauses,
    )


def _restore_terminal_actions(items: list[dict[str, Any]] | None) -> list[TerminalAction]:
    actions: list[TerminalAction] = []
    for item in list(items or []):
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip()
        target = str(item.get("target") or "").strip()
        if not kind or not target:
            continue
        actions.append(
            TerminalAction(
                kind=kind,
                target=target,
                resolved_target=str(item.get("resolved_target") or "").strip(),
                safe=bool(item.get("safe", True)),
                note=str(item.get("note") or "").strip(),
            )
        )
    return actions


def _load_language_memory(path: str | Path | None = None, *, limit: int = 256) -> list[dict[str, Any]]:
    memory_path = Path(path).expanduser().resolve() if path else terminal_language_memory_path()
    if not memory_path.exists():
        return []
    try:
        lines = memory_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in reversed(lines):
        clean = str(line or "").strip()
        if not clean:
            continue
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
        if len(rows) >= limit:
            break
    return rows


def _language_context_compatible(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    stored_page = str(stored.get("page_kind") or "").strip()
    current_page = str(current.get("page_kind") or "").strip()
    if stored_page and current_page and stored_page != current_page:
        return False
    stored_engine = str(stored.get("search_engine") or "").strip()
    current_engine = str(current.get("search_engine") or "").strip()
    if stored_engine and current_engine and stored_engine != current_engine:
        return False
    if bool(stored.get("has_search_results")) and not bool(current.get("has_search_results")):
        return False
    if bool(stored.get("has_subject")) and not bool(current.get("has_subject")):
        return False
    if bool(stored.get("has_evidence")) and not bool(current.get("has_evidence")):
        return False
    return True


def _language_memory_match_score(
    entry: dict[str, Any],
    *,
    prompt: str,
    browser_state: BrowserSessionState | None = None,
) -> float:
    current_profile = _language_context_profile(browser_state)
    stored_profile = dict(entry.get("context_profile") or {})
    if not _language_context_compatible(stored_profile, current_profile):
        return 0.0
    current_norm = _intent_text(prompt)
    stored_norm = str(entry.get("normalized_prompt") or "").strip()
    seq_score = SequenceMatcher(None, stored_norm, current_norm).ratio() if stored_norm and current_norm else 0.0
    current_tokens = set(_language_prompt_tokens(prompt))
    stored_tokens = {str(token).strip() for token in list(entry.get("tokens") or []) if str(token).strip()}
    union = current_tokens | stored_tokens
    token_score = (len(current_tokens & stored_tokens) / len(union)) if union else 0.0
    score = max(seq_score, token_score)
    if stored_profile.get("page_kind") and stored_profile.get("page_kind") == current_profile.get("page_kind"):
        score += 0.05
    if stored_profile.get("search_engine") and stored_profile.get("search_engine") == current_profile.get("search_engine"):
        score += 0.05
    return round(min(score, 1.0), 4)


def _language_memory_plan(
    prompt: str,
    *,
    browser_state: BrowserSessionState | None = None,
    path: str | Path | None = None,
) -> TerminalPlan | None:
    best_score = 0.0
    best_entry: dict[str, Any] | None = None
    for entry in _load_language_memory(path):
        score = _language_memory_match_score(entry, prompt=prompt, browser_state=browser_state)
        if score > best_score:
            best_score = score
            best_entry = entry
    if best_entry is None or best_score < 0.78:
        return None
    actions = _restore_terminal_actions(best_entry.get("actions"))
    if not actions:
        return None
    valid, residuals = _validate_language_actions(actions, browser_state=browser_state)
    if not valid:
        return None
    return TerminalPlan(
        prompt=prompt,
        source="language_memory",
        actions=actions,
        clarification=f"Reused a prior validated language compilation (similarity {best_score}).",
        residual_constraints=residuals,
    )


def remember_language_compile(
    *,
    prompt: str,
    browser_state: BrowserSessionState | None,
    plan: TerminalPlan,
    path: str | Path | None = None,
) -> Path | None:
    if plan.source not in {"language_model", "language_memory"} or not plan.actions:
        return None
    memory_path = Path(path).expanduser().resolve() if path else terminal_language_memory_path()
    memory_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_ts": int(time.time()),
        "prompt": prompt,
        "memory_source": plan.source,
        "normalized_prompt": _intent_text(prompt),
        "tokens": _language_prompt_tokens(prompt),
        "context_profile": _language_context_profile(browser_state),
        "action_signatures": [_action_signature(action) for action in plan.actions],
        "actions": [asdict(action) for action in plan.actions],
    }
    with memory_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    record_memory_trace(
        prompt=prompt,
        normalized_prompt=_intent_text(prompt),
        tokens=_language_prompt_tokens(prompt),
        context_profile=_language_context_profile(browser_state),
        action_signatures=[_action_signature(action) for action in plan.actions],
        source=plan.source,
        path=terminal_memory_ontology_path(),
        canonical_clauses=_canonical_clauses_from_actions(plan.actions),
    )
    return memory_path


def _load_language_rules(path: str | Path | None = None) -> list[dict[str, Any]]:
    rule_path = Path(path).expanduser().resolve() if path else terminal_language_rule_path()
    if not rule_path.exists():
        return []
    try:
        payload = json.loads(rule_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [dict(item) for item in payload if isinstance(item, dict)]


def _save_language_rules(entries: list[dict[str, Any]], path: str | Path | None = None) -> Path:
    rule_path = Path(path).expanduser().resolve() if path else terminal_language_rule_path()
    rule_path.parent.mkdir(parents=True, exist_ok=True)
    clean_entries = [dict(entry) for entry in entries if isinstance(entry, dict)]
    rule_path.write_text(json.dumps(clean_entries, ensure_ascii=True, indent=2), encoding="utf-8")
    return rule_path


def _canonical_clause_from_action_group(group: list[TerminalAction]) -> str:
    if not group:
        return ""
    first = group[0]
    if first.kind == "browser_rank_cards":
        note = _decode_action_note(first.note)
        goal = str(note.get("goal") or "").strip()
        return f"find whatever repo fits best {goal}".strip()
    if first.kind == "browser_compare_cards":
        note = _decode_action_note(first.note)
        goal = str(note.get("goal") or "").strip()
        indexes = [int(item) for item in list(note.get("indexes") or []) if str(item).isdigit()]
        if indexes:
            label = " and ".join(
                "first" if idx == 1 else "second" if idx == 2 else "third" if idx == 3 else str(idx)
                for idx in indexes[:2]
            )
        else:
            label = "first and second"
        return f"compare the {label} repos for {goal}".strip()
    if first.kind == "browser_search_subject":
        note = _decode_action_note(first.note)
        engine = str(note.get("engine") or first.resolved_target or first.target or "").strip() or "youtube"
        subject_ref = "the winner" if any(token in engine for token in ()) else "this repo"
        clause = f"find a {engine} result about {subject_ref}"
        if engine == "youtube":
            clause = "find a youtube video about the winner or this repo"
        elif engine == "reddit":
            clause = "find a reddit thread about the winner or this repo"
        if any(action.kind == "open_search_result" for action in group):
            clause += " and open the first one"
        if any(action.kind == "browser_read_page" for action in group):
            clause += " and tell me what it is"
        return clause.strip()
    if first.kind == "browser_retry_subject_result":
        clause = "if the first one is weak open a better one"
        if any(action.kind == "browser_read_page" for action in group):
            clause += " and summarize it"
        return clause
    if first.kind == "browser_synthesize_evidence":
        note = _decode_action_note(first.note)
        goal = str(note.get("goal") or "").strip()
        return f"tell me which source best explains {goal}".strip()
    return ""


def _canonical_clauses_from_actions(actions: list[TerminalAction]) -> list[str]:
    clauses: list[str] = []
    index = 0
    while index < len(actions):
        action = actions[index]
        if action.kind in {"browser_rank_cards", "browser_compare_cards", "browser_synthesize_evidence"}:
            clause = _canonical_clause_from_action_group([action])
            if clause:
                clauses.append(clause)
            index += 1
            continue
        if action.kind == "browser_search_subject":
            group = [action]
            index += 1
            if index < len(actions) and actions[index].kind == "open_search_result":
                group.append(actions[index])
                index += 1
            if index < len(actions) and actions[index].kind == "browser_read_page":
                group.append(actions[index])
                index += 1
            clause = _canonical_clause_from_action_group(group)
            if clause:
                clauses.append(clause)
            continue
        if action.kind == "browser_retry_subject_result":
            group = [action]
            index += 1
            if index < len(actions) and actions[index].kind == "browser_read_page":
                group.append(actions[index])
                index += 1
            clause = _canonical_clause_from_action_group(group)
            if clause:
                clauses.append(clause)
            continue
        index += 1
    return clauses


def _rule_context_compatible(stored: dict[str, Any], current: dict[str, Any]) -> bool:
    stored_page = str(stored.get("page_kind") or "").strip()
    current_page = str(current.get("page_kind") or "").strip()
    if stored_page and current_page and stored_page != current_page:
        return False
    stored_engine = str(stored.get("search_engine") or "").strip()
    current_engine = str(current.get("search_engine") or "").strip()
    if stored_engine and current_engine and stored_engine != current_engine:
        return False
    return True


def _promote_language_rules(
    *,
    prompt: str,
    browser_state: BrowserSessionState | None,
    plan: TerminalPlan,
    path: str | Path | None = None,
    threshold: int = 2,
) -> Path | None:
    if plan.source != "language_memory" or not plan.actions:
        return None
    raw_clauses = _split_prompt_clauses(prompt)
    canonical_clauses = _canonical_clauses_from_actions(plan.actions)
    if not raw_clauses or len(raw_clauses) != len(canonical_clauses):
        return None
    entries = _load_language_rules(path)
    profile = _language_context_profile(browser_state)
    changed = False
    activated_rule = False
    for raw_clause, canonical_clause in zip(raw_clauses, canonical_clauses):
        normalized_raw = _intent_text(raw_clause)
        normalized_canonical = _intent_text(canonical_clause)
        if not normalized_raw or not normalized_canonical:
            continue
        existing: dict[str, Any] | None = None
        for entry in entries:
            if (
                str(entry.get("normalized_raw_clause") or "").strip() == normalized_raw
                and str(entry.get("normalized_canonical_clause") or "").strip() == normalized_canonical
                and _rule_context_compatible(dict(entry.get("context_profile") or {}), profile)
            ):
                existing = entry
                break
        if existing is None:
            existing = {
                "raw_clause": raw_clause,
                "normalized_raw_clause": normalized_raw,
                "canonical_clause": canonical_clause,
                "normalized_canonical_clause": normalized_canonical,
                "context_profile": profile,
                "hit_count": 0,
                "active": False,
                "last_promoted_ts": 0,
            }
            entries.append(existing)
        existing["hit_count"] = int(existing.get("hit_count") or 0) + 1
        if int(existing["hit_count"]) >= max(int(threshold), 1):
            existing["active"] = True
            existing["last_promoted_ts"] = int(time.time())
            activated_rule = True
        changed = True
    if not changed:
        return None
    saved_path = _save_language_rules(entries, path)
    if activated_rule:
        promote_memory_rule(
            prompt=prompt,
            normalized_prompt=_intent_text(prompt),
            tokens=_language_prompt_tokens(prompt),
            context_profile=profile,
            action_signatures=[_action_signature(action) for action in plan.actions],
            source="language_rule",
            path=terminal_memory_ontology_path(),
            canonical_clauses=canonical_clauses,
        )
    return saved_path


def _rule_match_score(
    entry: dict[str, Any],
    *,
    clause: str,
    browser_state: BrowserSessionState | None = None,
) -> float:
    profile = _language_context_profile(browser_state)
    if not _rule_context_compatible(dict(entry.get("context_profile") or {}), profile):
        return 0.0
    normalized = _intent_text(clause)
    stored = str(entry.get("normalized_raw_clause") or "").strip()
    if not normalized or not stored:
        return 0.0
    seq_score = SequenceMatcher(None, stored, normalized).ratio()
    current_tokens = {token for token in _language_prompt_tokens(clause)}
    stored_tokens = {str(token).strip() for token in stored.split() if str(token).strip()}
    union = current_tokens | stored_tokens
    token_score = (len(current_tokens & stored_tokens) / len(union)) if union else 0.0
    return round(max(seq_score, token_score), 4)


def _rewrite_with_language_rules(
    prompt: str,
    *,
    browser_state: BrowserSessionState | None = None,
    path: str | Path | None = None,
) -> str:
    entries = [entry for entry in _load_language_rules(path) if bool(entry.get("active"))]
    if not entries:
        return ""
    clauses = _split_prompt_clauses(prompt)
    if not clauses:
        return ""
    rewritten: list[str] = []
    changed = False
    for clause in clauses:
        best_score = 0.0
        best_entry: dict[str, Any] | None = None
        for entry in entries:
            score = _rule_match_score(entry, clause=clause, browser_state=browser_state)
            if score > best_score:
                best_score = score
                best_entry = entry
        if best_entry is not None and best_score >= 0.84:
            rewritten.append(str(best_entry.get("canonical_clause") or clause).strip())
            changed = True
        else:
            rewritten.append(clause.strip())
    if not changed:
        return ""
    return " then ".join(part for part in rewritten if part)


def _language_rule_plan(
    prompt: str,
    *,
    browser_state: BrowserSessionState | None = None,
    path: str | Path | None = None,
) -> TerminalPlan | None:
    rewritten = _rewrite_with_language_rules(prompt, browser_state=browser_state, path=path)
    if not rewritten:
        return None
    actions = _surface_language_actions(rewritten, browser_state=browser_state)
    if not actions:
        return None
    valid, residuals = _validate_language_actions(actions, browser_state=browser_state)
    if not valid:
        return None
    return TerminalPlan(
        prompt=prompt,
        source="language_rule",
        actions=actions,
        clarification="Reused promoted language rewrite rules before language memory/model fallback.",
        residual_constraints=residuals,
    )


def _normalize_model_actions(payload: dict[str, Any]) -> list[TerminalAction]:
    actions: list[TerminalAction] = []
    for raw in list(payload.get("actions") or []):
        if not isinstance(raw, dict):
            continue
        kind = str(raw.get("kind") or "").strip().lower()
        target = str(raw.get("target") or "").strip()
        if kind not in SUPPORTED_ACTION_KINDS or not target:
            continue
        url_target = _normalize_url(target)
        if kind == "open_path" and url_target:
            actions.append(TerminalAction(kind="open_url", target=target, resolved_target=url_target))
            continue
        if kind == "launch_app":
            app_key = _resolve_app_key(target)
            if app_key:
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=app_key))
            continue
        if kind == "browser_read_page":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target or "current_page"))
            continue
        if kind == "browser_answer_query":
            query = " ".join(str(target or "").split()).strip()
            if query:
                actions.append(
                    TerminalAction(
                        kind=kind,
                        target=query,
                        resolved_target=query,
                        note=_encode_action_note({"goal": query, "query": query, "engine": "web"}),
                    )
                )
            continue
        if kind in {"browser_extract_page", "browser_extract_cards", "browser_screenshot"}:
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target or "current_page"))
            continue
        if kind == "browser_rank_cards":
            note = _encode_action_note({"goal": target})
            actions.append(TerminalAction(kind=kind, target="current_cards", resolved_target="current_cards", note=note))
            continue
        if kind == "browser_compare_cards":
            compare_target = "1,2"
            goal = target
            indexes = _comparison_indexes_from_prompt(target)
            if len(indexes) >= 2:
                compare_target = ",".join(str(index) for index in indexes[:2])
            note = _encode_action_note({"goal": goal, "indexes": [int(part) for part in compare_target.split(",") if part.isdigit()]})
            actions.append(TerminalAction(kind=kind, target=compare_target, resolved_target=compare_target, note=note))
            continue
        if kind == "browser_search_subject":
            engine = _normalize_label(target)
            if engine in {"youtube", "reddit", "google", "web"}:
                resolved_engine = "google" if engine == "web" else engine
                note = _encode_action_note({"engine": resolved_engine})
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=resolved_engine, note=note))
            continue
        if kind == "browser_retry_subject_result":
            note = _encode_action_note({"goal": target} if target else {})
            actions.append(TerminalAction(kind=kind, target="better_result", resolved_target="better_result", note=note))
            continue
        if kind == "browser_synthesize_evidence":
            note = _encode_action_note({"goal": target} if target else {})
            actions.append(TerminalAction(kind=kind, target="current_evidence", resolved_target="current_evidence", note=note))
            continue
        if kind == "browser_new_tab":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target or "new_tab"))
            continue
        if kind == "browser_close_tab":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target or "current_tab"))
            continue
        if kind == "browser_switch_tab":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target or "next"))
            continue
        if kind == "open_search_result":
            if target.isdigit():
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=target))
            continue
        if kind == "browser_click_index":
            if target.isdigit():
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=target))
            continue
        if kind == "browser_click_text":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target))
            continue
        if kind in {"open_path", "list_directory"}:
            path_value = _resolve_path_target(target)
            if path_value:
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=path_value))
            continue
        if kind == "open_url":
            url = _normalize_url(target)
            if url:
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=url))
            continue
        if kind == "system_info":
            topic = _normalize_label(target)
            if topic in SUPPORTED_SYSTEM_INFO_TOPICS:
                actions.append(TerminalAction(kind=kind, target=target, resolved_target=topic))
            continue
        if kind in {"browser_back", "browser_forward", "browser_media_pause", "browser_media_play", "browser_submit"}:
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target))
            continue
        if kind in {"browser_scroll", "browser_type_text", "browser_wait"}:
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target))
            continue
        if kind == "unsupported":
            actions.append(TerminalAction(kind=kind, target=target, resolved_target=target, safe=False))
    return actions


def _resolve_app_key(raw: str) -> str:
    normalized = _normalize_label(raw)
    for app_key, spec in APP_SPECS.items():
        aliases = {_normalize_label(app_key), *(_normalize_label(alias) for alias in spec.get("aliases") or ())}
        if normalized in aliases:
            return app_key
    return ""


def _resolve_path_target(raw: str) -> str:
    normalized = _normalize_label(raw)
    if normalized in PATH_ALIASES:
        return PATH_ALIASES[normalized]
    path = Path(str(raw or "").strip()).expanduser()
    if str(path).strip():
        return str(path)
    return ""


def _normalize_url(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if re.match(r"^https?://", text, flags=re.IGNORECASE):
        return text
    if re.match(r"^[a-z0-9.-]+\.(?:com|org|net|io|dev|app|ai)(?:/.*)?$", text, flags=re.IGNORECASE):
        return f"https://{text}"
    return ""


def _canonical_expected_action(value: str) -> str:
    text = str(value or "").strip()
    if not text or ":" not in text:
        return _normalize_label(text)
    kind, target = text.split(":", 1)
    normalized_kind = str(kind or "").strip().lower().replace(" ", "_")
    normalized_target = str(target or "").strip()
    if normalized_kind == "open_url":
        normalized_target = _normalize_url(normalized_target)
    else:
        normalized_target = _normalize_label(normalized_target)
    return f"{normalized_kind}:{normalized_target}"


def _action_signature(action: TerminalAction) -> str:
    kind = str(action.kind or "").strip().lower().replace(" ", "_")
    if kind in {"open_path", "list_directory"}:
        alias_key = _normalize_label(action.target)
        if alias_key in PATH_ALIASES:
            return f"{kind}:{alias_key}"
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    if kind == "launch_app":
        app_key = _resolve_app_key(action.resolved_target or action.target)
        return f"{kind}:{app_key or _normalize_label(action.resolved_target or action.target)}"
    if kind == "browser_read_page":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'current_page')}"
    if kind == "browser_answer_query":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    if kind in {"browser_extract_page", "browser_extract_cards", "browser_screenshot"}:
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'current_page')}"
    if kind == "browser_rank_cards":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'current_cards')}"
    if kind == "browser_compare_cards":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or '1,2')}"
    if kind == "browser_search_subject":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'youtube')}"
    if kind == "browser_retry_subject_result":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'better_result')}"
    if kind == "browser_synthesize_evidence":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target or 'current_evidence')}"
    if kind == "open_search_result":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    if kind in {"browser_click_index", "browser_switch_tab"}:
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    if kind == "browser_click_text":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    if kind == "open_url":
        return f"{kind}:{_normalize_url(action.resolved_target or action.target)}"
    if kind == "system_info":
        return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"
    return f"{kind}:{_normalize_label(action.resolved_target or action.target)}"


def _autonomy_memory_kind_from_actions(actions: list[TerminalAction]) -> str:
    kinds = [str(action.kind or "").strip() for action in actions]
    if not kinds:
        return ""
    if "browser_answer_query" in kinds:
        return "autonomy_web_answer"
    if "browser_synthesize_evidence" in kinds:
        return "autonomy_evidence_synthesis"
    if "browser_search_subject" in kinds:
        engines = [
            _normalize_label(action.resolved_target or action.target or _decode_action_note(action.note).get("engine", ""))
            for action in actions
            if action.kind == "browser_search_subject"
        ]
        engines = [engine for engine in engines if engine]
        if len(set(engines)) > 1:
            return "autonomy_multi_source_followup"
        if engines:
            return f"autonomy_subject_followup_{engines[0]}"
        return "autonomy_subject_followup"
    if "browser_rank_cards" in kinds or "browser_compare_cards" in kinds:
        return "autonomy_result_selection"
    return ""


def _autonomy_canonical_clauses(actions: list[TerminalAction]) -> list[str]:
    clauses = _canonical_clauses_from_actions(actions)
    if clauses:
        return clauses
    labels: list[str] = []
    for action in actions:
        if action.kind == "browser_synthesize_evidence":
            labels.append("synthesize evidence and return the best source")
        elif action.kind == "browser_search_subject":
            labels.append(f"search {action.resolved_target or action.target} for the current subject")
        elif action.kind == "open_search_result":
            labels.append("open the selected search result")
        elif action.kind == "browser_read_page":
            labels.append("read the current page")
        elif action.kind == "browser_rank_cards":
            labels.append("rank current result cards")
    return labels


def _record_autonomy_plan_memory(
    *,
    plan: TerminalPlan,
    browser_state: BrowserSessionState,
    ok: bool,
    state_path: str | Path | None,
) -> None:
    if plan.source in {"language_model", "language_memory", "language_rule"}:
        return
    memory_kind = _autonomy_memory_kind_from_actions(plan.actions)
    if not memory_kind:
        return
    adjudicate_memory_trace(
        prompt=plan.prompt,
        normalized_prompt=_intent_text(plan.prompt),
        tokens=_language_prompt_tokens(plan.prompt),
        context_profile=_language_context_profile(browser_state),
        action_signatures=[_action_signature(action) for action in plan.actions],
        source="autonomy_trace",
        success=ok,
        path=_terminal_memory_ontology_path_for_state(state_path),
        memory_kind=memory_kind,
        canonical_clauses=_autonomy_canonical_clauses(plan.actions),
    )


def _action_recall(plan: TerminalPlan, expected_actions: list[str]) -> float:
    expected = [_canonical_expected_action(item) for item in expected_actions if str(item or "").strip()]
    if not expected:
        return 1.0 if not plan.actions else 0.0
    predicted = {_action_signature(action) for action in plan.actions}
    hits = sum(1 for item in expected if item in predicted)
    return round(hits / len(expected), 4)


def _terminal_utility(plan: TerminalPlan, expected_actions: list[str]) -> float:
    recall = _action_recall(plan, expected_actions)
    support = 1.0 if plan.actions else 0.0
    return round((0.3 * support) + (0.7 * recall), 4)


def load_terminal_benchmark_cases(path: str) -> list[TerminalBenchmarkCase]:
    cases: list[TerminalBenchmarkCase] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        clean = line.strip()
        if not clean:
            continue
        payload = json.loads(clean)
        case_id = str(payload.get("case_id") or "").strip()
        prompt = str(payload.get("prompt") or "").strip()
        if not case_id or not prompt:
            continue
        expected_actions = [str(item).strip() for item in list(payload.get("expected_actions") or []) if str(item).strip()]
        cases.append(TerminalBenchmarkCase(case_id=case_id, prompt=prompt, expected_actions=expected_actions))
    return cases


def build_terminal_plan(
    *,
    prompt: str,
    model: str = "",
    client: UniversalLLMClient | None = None,
    heuristic_only: bool = False,
    temperature: float = 0.1,
    browser_state: BrowserSessionState | None = None,
) -> TerminalPlan:
    heuristic = _heuristic_plan(prompt, browser_state=browser_state)
    if heuristic is not None:
        return heuristic
    return build_language_learning_plan(
        prompt=prompt,
        model=model,
        client=client,
        heuristic_only=heuristic_only,
        temperature=temperature,
        browser_state=browser_state,
    )


def build_language_learning_plan(
    *,
    prompt: str,
    model: str = "",
    client: UniversalLLMClient | None = None,
    heuristic_only: bool = False,
    temperature: float = 0.1,
    browser_state: BrowserSessionState | None = None,
) -> TerminalPlan:
    rule_plan = _language_rule_plan(prompt, browser_state=browser_state)
    if rule_plan is not None:
        return rule_plan
    memory_plan = _language_memory_plan(prompt, browser_state=browser_state)
    if memory_plan is not None:
        return memory_plan
    if heuristic_only or client is None or not str(model or "").strip():
        return TerminalPlan(
            prompt=prompt,
            source="fallback",
            clarification="I could not map that request to a safe bounded terminal action.",
            residual_constraints=["unsupported_or_ambiguous_request"],
        )
    try:
        response = client.chat(model=model, messages=_language_llm_prompt(prompt, browser_state=browser_state), temperature=temperature)
    except Exception as exc:
        return TerminalPlan(
            prompt=prompt,
            source="model_error",
            clarification=f"Model fallback unavailable: {str(exc).strip() or 'unknown error'}",
            residual_constraints=["llm_fallback_unavailable"],
        )
    plan = _plan_from_model_response(prompt=prompt, response=response, source="language_model")
    augmented_actions = _merge_language_actions(plan.actions, prompt=prompt, browser_state=browser_state)
    if augmented_actions != plan.actions:
        plan = TerminalPlan(
            prompt=plan.prompt,
            source=plan.source,
            actions=augmented_actions,
            needs_confirmation=plan.needs_confirmation,
            clarification=plan.clarification,
            residual_constraints=list(plan.residual_constraints),
        )
    if plan.actions:
        valid, residuals = _validate_language_actions(plan.actions, browser_state=browser_state)
        if not valid:
            return TerminalPlan(
                prompt=prompt,
                source="language_model",
                clarification="Language fallback produced a plan that did not fit the current Memla browser state.",
                residual_constraints=residuals or ["invalid_language_compile"],
            )
    return plan


def build_raw_terminal_plan(
    *,
    prompt: str,
    model: str,
    client: UniversalLLMClient | None,
    temperature: float = 0.1,
    browser_state: BrowserSessionState | None = None,
) -> TerminalPlan:
    if client is None or not str(model or "").strip():
        return TerminalPlan(
            prompt=prompt,
            source="raw_model",
            clarification="Raw terminal mode requires a model client.",
            residual_constraints=["llm_fallback_unavailable"],
        )
    try:
        response = client.chat(
            model=model,
            messages=_llm_prompt(prompt, browser_state=browser_state),
            temperature=temperature,
        )
    except Exception as exc:
        return TerminalPlan(
            prompt=prompt,
            source="raw_model",
            clarification=f"Raw model unavailable: {str(exc).strip() or 'unknown error'}",
            residual_constraints=["llm_fallback_unavailable"],
        )
    return _plan_from_model_response(prompt=prompt, response=response, source="raw_model")


def _platform_key(platform_name: str) -> str:
    lower = str(platform_name or sys.platform).lower()
    if lower.startswith("linux"):
        return "linux"
    if lower.startswith("darwin"):
        return "darwin"
    if lower.startswith("win"):
        return "win32"
    return lower


def _resolve_launch_command(app_key: str, *, platform_name: str) -> list[str]:
    spec = APP_SPECS.get(app_key) or {}
    key = _platform_key(platform_name)
    for candidate in spec.get(key) or ():
        binary = shutil.which(str(candidate))
        if binary:
            return [binary]
    return []


def _open_command_for_platform(platform_name: str) -> list[str]:
    key = _platform_key(platform_name)
    if key == "linux":
        return list(LINUX_OPEN_COMMAND)
    if key == "darwin":
        return list(MACOS_OPEN_COMMAND)
    if key == "win32":
        return ["cmd", "/c", "start", ""]
    return []


def _system_info_record(topic: str) -> TerminalExecutionRecord:
    if topic == "disk":
        usage = shutil.disk_usage(Path.home())
        message = (
            f"Home disk usage: total={round(usage.total / (1024**3), 1)} GiB, "
            f"used={round(usage.used / (1024**3), 1)} GiB, free={round(usage.free / (1024**3), 1)} GiB"
        )
        return TerminalExecutionRecord(kind="system_info", target=topic, status="ok", message=message)
    if topic == "cpu":
        load = os.getloadavg() if hasattr(os, "getloadavg") else (0.0, 0.0, 0.0)
        message = f"CPU load averages: {load[0]:.2f}, {load[1]:.2f}, {load[2]:.2f}"
        return TerminalExecutionRecord(kind="system_info", target=topic, status="ok", message=message)
    if topic == "memory":
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            rows = {line.split(":", 1)[0]: line.split(":", 1)[1].strip() for line in meminfo.read_text(encoding="utf-8").splitlines() if ":" in line}
            total_kib = int(rows.get("MemTotal", "0 kB").split()[0] or 0)
            available_kib = int(rows.get("MemAvailable", "0 kB").split()[0] or 0)
            used_gib = (total_kib - available_kib) / (1024**2)
            total_gib = total_kib / (1024**2)
            return TerminalExecutionRecord(
                kind="system_info",
                target=topic,
                status="ok",
                message=f"Memory usage: used={used_gib:.1f} GiB, total={total_gib:.1f} GiB",
            )
        return TerminalExecutionRecord(kind="system_info", target=topic, status="failed", message="Memory info unavailable on this platform.")
    if topic == "battery":
        power_root = Path("/sys/class/power_supply")
        if power_root.exists():
            for candidate in power_root.iterdir():
                capacity = candidate / "capacity"
                status_file = candidate / "status"
                if capacity.exists():
                    level = capacity.read_text(encoding="utf-8").strip()
                    status = status_file.read_text(encoding="utf-8").strip() if status_file.exists() else "unknown"
                    return TerminalExecutionRecord(
                        kind="system_info",
                        target=topic,
                        status="ok",
                        message=f"Battery: {level}% ({status})",
                    )
        return TerminalExecutionRecord(kind="system_info", target=topic, status="failed", message="Battery info unavailable on this platform.")
    return TerminalExecutionRecord(kind="system_info", target=topic, status="failed", message="Unsupported system info topic.")


def _browser_state_for_url(
    url: str,
    *,
    browser_app: str = "",
    search_engine: str = "",
    search_query: str = "",
    result_urls: list[str] | None = None,
    result_cards: list[dict[str, Any]] | None = None,
    subject_title: str = "",
    subject_url: str = "",
    subject_summary: str = "",
    research_subject_title: str = "",
    research_subject_url: str = "",
    research_subject_summary: str = "",
    evidence_items: list[dict[str, Any]] | None = None,
) -> BrowserSessionState:
    normalized_url = str(url or "").strip()
    lower_url = normalized_url.lower()
    page_kind = "web_page"
    if "youtube.com/results" in lower_url:
        page_kind = "search_results"
    elif "youtube.com/watch" in lower_url:
        page_kind = "video_page"
    elif "github.com/search" in lower_url:
        page_kind = "search_results"
    elif re.match(r"^https?://github\.com/[^/\s]+/[^/\s?#]+/?$", lower_url):
        page_kind = "repo_page"
    elif "reddit.com/search" in lower_url:
        page_kind = "search_results"
    elif "/comments/" in lower_url and "reddit.com/" in lower_url:
        page_kind = "post_page"
    elif "amazon.com/s?" in lower_url:
        page_kind = "search_results"
    elif re.match(r"^https?://(?:www\.)?google\.[^/\s]+/search", lower_url):
        page_kind = "search_results"
    return BrowserSessionState(
        current_url=normalized_url,
        page_kind=page_kind,
        browser_app=str(browser_app or "").strip(),
        search_engine=str(search_engine or "").strip(),
        search_query=str(search_query or "").strip(),
        result_urls=list(result_urls or []),
        result_cards=[dict(item) for item in list(result_cards or []) if isinstance(item, dict)],
        subject_title=str(subject_title or "").strip(),
        subject_url=str(subject_url or "").strip(),
        subject_summary=str(subject_summary or "").strip(),
        research_subject_title=str(research_subject_title or "").strip(),
        research_subject_url=str(research_subject_url or "").strip(),
        research_subject_summary=str(research_subject_summary or "").strip(),
        evidence_items=_clone_evidence_items(evidence_items),
    )


def _open_in_browser(target: str, *, platform_name: str) -> list[str]:
    launcher = _open_command_for_platform(platform_name)
    if not launcher:
        return []
    return list(launcher) + [target]


def _fetch_github_search_result_urls(query: str, *, limit: int = 5) -> list[str]:
    api_url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page={max(int(limit), 1)}"
    try:
        payload = json.loads(_fetch_url_text(api_url, accept="application/vnd.github+json"))
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return []
    items = list(payload.get("items") or []) if isinstance(payload, dict) else []
    results: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("html_url") or "").strip()
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        results.append(url)
        if len(results) >= limit:
            break
    return results


def _fallback_cards_from_urls(urls: list[str]) -> list[dict[str, Any]]:
    cards: list[dict[str, Any]] = []
    for index, url in enumerate(list(urls or []), start=1):
        preview = _preview_label_for_url(url) or url
        cards.append(
            {
                "index": index,
                "title": preview,
                "url": url,
                "summary": "",
            }
        )
    return cards


def _format_compact_count(value: int | float | str) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value or "").strip()
    if number >= 1_000_000:
        compact = f"{number / 1_000_000:.1f}".rstrip("0").rstrip(".")
        return f"{compact}M"
    if number >= 1_000:
        compact = f"{number / 1_000:.1f}".rstrip("0").rstrip(".")
        return f"{compact}k"
    if number.is_integer():
        return str(int(number))
    return str(round(number, 1))


def _fetch_github_repo_snapshot(owner: str, repo: str) -> dict[str, Any]:
    api_url = f"https://api.github.com/repos/{quote_plus(owner)}/{quote_plus(repo)}"
    try:
        payload = json.loads(_fetch_url_text(api_url, accept="application/vnd.github+json"))
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    snapshot: dict[str, Any] = {}
    full_name = str(payload.get("full_name") or f"{owner}/{repo}").strip()
    if full_name:
        snapshot["repo"] = full_name
    description = str(payload.get("description") or "").strip()
    if description:
        snapshot["summary"] = f"{full_name}: {description}" if full_name else description
        snapshot["description"] = description
    stars = payload.get("stargazers_count")
    forks = payload.get("forks_count")
    language = str(payload.get("language") or "").strip()
    homepage = str(payload.get("homepage") or "").strip()
    topics = [str(item).strip() for item in list(payload.get("topics") or []) if str(item).strip()]
    if stars is not None:
        snapshot["stars"] = _format_compact_count(stars)
    if forks is not None:
        snapshot["forks"] = _format_compact_count(forks)
    if language:
        snapshot["language"] = language
    if homepage:
        snapshot["homepage"] = homepage
    if topics:
        snapshot["topics"] = ", ".join(topics[:6])
    return snapshot


def _fetch_github_search_cards(query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    api_url = f"https://api.github.com/search/repositories?q={quote_plus(query)}&per_page={max(int(limit), 1)}"
    try:
        payload = json.loads(_fetch_url_text(api_url, accept="application/vnd.github+json"))
    except (OSError, URLError, json.JSONDecodeError, ValueError):
        return []
    items = list(payload.get("items") or []) if isinstance(payload, dict) else []
    cards: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        url = str(item.get("html_url") or "").strip()
        if not url or url.lower() in seen:
            continue
        seen.add(url.lower())
        stars = item.get("stargazers_count")
        language = str(item.get("language") or "").strip()
        meta_parts = []
        if stars is not None:
            meta_parts.append(f"stars {_format_compact_count(stars)}")
        if language:
            meta_parts.append(language)
        cards.append(
            {
                "index": len(cards) + 1,
                "title": str(item.get("full_name") or url).strip(),
                "url": url,
                "summary": str(item.get("description") or "").strip(),
                "meta": " | ".join(meta_parts),
            }
        )
        if len(cards) >= limit:
            break
    return cards


def _fetch_search_result_cards(engine: str, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    normalized_engine = _normalize_label(engine)
    if normalized_engine in {"google", "web"}:
        cards = _fetch_web_search_cards(query, limit=limit)
        if cards:
            return cards
    if normalized_engine == "github":
        cards = _fetch_github_search_cards(query, limit=limit)
        if cards:
            return cards
    urls = _fetch_search_result_urls(engine, query, limit=limit)
    return _fallback_cards_from_urls(urls[:limit])


def _fetch_search_result_urls(engine: str, query: str, *, limit: int = 5) -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    def _append(candidate: str) -> None:
        clean = str(candidate or "").strip()
        if not clean or clean.lower() in seen:
            return
        seen.add(clean.lower())
        results.append(clean)

    normalized_engine = _normalize_label(engine)
    if normalized_engine in {"google", "web"}:
        web_results = _fetch_web_search_result_urls(query, limit=limit)
        if web_results:
            return web_results[:limit]
    if normalized_engine == "github":
        api_results = _fetch_github_search_result_urls(query, limit=limit)
        if api_results:
            return api_results[:limit]

    url = _search_url(engine, query)
    if not url:
        return []
    html = _fetch_url_text(url)

    if normalized_engine == "youtube":
        for video_id in re.findall(r'"videoId":"([A-Za-z0-9_-]{11})"', html):
            _append(f"https://www.youtube.com/watch?v={video_id}")
            if len(results) >= limit:
                break
    elif normalized_engine == "github":
        patterns = (
            re.compile(r'class="v-align-middle"[^>]*href="(/[^"/\s]+/[^"/\s?#]+)"', flags=re.IGNORECASE),
            re.compile(r'href="(/[^"/\s]+/[^"/\s?#]+)"[^>]*class="v-align-middle"', flags=re.IGNORECASE),
        )
        for pattern in patterns:
            for match in pattern.findall(html):
                _append(f"https://github.com{match}")
                if len(results) >= limit:
                    break
            if len(results) >= limit:
                break
    elif normalized_engine == "reddit":
        for match in re.findall(r'href="(https://www\.reddit\.com/r/[^"]+/comments/[^"]+)"', html, flags=re.IGNORECASE):
            _append(match.replace("&amp;", "&"))
            if len(results) >= limit:
                break
    elif normalized_engine == "amazon":
        for match in re.findall(r'href="(/[^"]*/dp/[A-Z0-9]{10}[^"]*)"', html, flags=re.IGNORECASE):
            _append(f"https://www.amazon.com{match.replace('&amp;', '&')}")
            if len(results) >= limit:
                break
    return results[:limit]


def _github_metric(html: str, owner: str, repo: str, suffix: str) -> str:
    patterns = (
        re.compile(
            rf'href="/{re.escape(owner)}/{re.escape(repo)}/{re.escape(suffix)}"[^>]*>\s*<span[^>]*>([^<]+)</span>',
            flags=re.IGNORECASE,
        ),
        re.compile(
            rf'href="/{re.escape(owner)}/{re.escape(repo)}/{re.escape(suffix)}"[^>]*aria-label="([^"]+)"',
            flags=re.IGNORECASE,
        ),
    )
    for pattern in patterns:
        match = pattern.search(html)
        if match:
            raw = _strip_html(match.group(1))
            if raw:
                return raw
    return ""


def _extract_page_snapshot(state: BrowserSessionState, html: str) -> dict[str, Any]:
    url = str(state.current_url or "").strip()
    title = _title_from_html(html)
    body_text = _body_text_from_html(html)
    description = (
        _meta_content(html, "og:description", attr="property")
        or _meta_content(html, "twitter:description", attr="name")
        or _meta_content(html, "description", attr="name")
    )
    snapshot: dict[str, Any] = {
        "url": url,
        "page_kind": state.page_kind or "web_page",
        "title": title,
        "summary": _prefer_content_summary(description, body_text) or title,
        "content_preview": _first_sentences(body_text, max_sentences=3, max_chars=500),
        "body_text": body_text[:4000].strip(),
    }
    if state.page_kind == "repo_page":
        match = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s?#]+)", url, flags=re.IGNORECASE)
        if match:
            owner = match.group(1)
            repo = match.group(2)
            snapshot.update(_fetch_github_repo_snapshot(owner, repo))
            snapshot.setdefault("repo", f"{owner}/{repo}")
            snapshot.setdefault("stars", _github_metric(html, owner, repo, "stargazers"))
            snapshot.setdefault("forks", _github_metric(html, owner, repo, "forks") or _github_metric(html, owner, repo, "network/members"))
            if description:
                snapshot["summary"] = snapshot.get("summary") or f"{owner}/{repo}: {description}"
    elif state.page_kind == "video_page":
        channel = _meta_content(html, "og:video:tag", attr="property")
        if channel:
            snapshot["channel"] = channel
    elif state.page_kind == "post_page":
        if description:
            snapshot["summary"] = description
    return {key: value for key, value in snapshot.items() if str(value or "").strip()}


def _browser_read_message(details: dict[str, Any], current_url: str) -> str:
    page_kind = str(details.get("page_kind") or "").strip()
    if page_kind == "repo_page":
        repo = str(details.get("repo") or "").strip()
        description = str(details.get("description") or details.get("summary") or "").strip()
        stars = str(details.get("stars") or "").strip()
        forks = str(details.get("forks") or "").strip()
        language = str(details.get("language") or "").strip()
        topics = str(details.get("topics") or "").strip()
        parts: list[str] = []
        if repo:
            parts.append(repo)
        if description:
            parts.append(description)
        metrics: list[str] = []
        if stars:
            metrics.append(f"stars {stars}")
        if forks:
            metrics.append(f"forks {forks}")
        if language:
            metrics.append(f"language {language}")
        if metrics:
            parts.append(", ".join(metrics))
        if topics:
            parts.append(f"topics {topics}")
        if parts:
            return "Repo summary: " + ". ".join(parts)
    summary = str(details.get("summary") or details.get("title") or current_url).strip()
    return f"Read current page: {summary}"


def _best_web_answer_summary(*, prompt: str, card: dict[str, Any], details: dict[str, Any]) -> str:
    focused_body = _query_focused_snippet(str(details.get("body_text") or "").strip(), prompt)
    summary_candidates = [
        focused_body,
        str(details.get("summary") or "").strip(),
        str(card.get("summary") or "").strip(),
        str(details.get("description") or "").strip(),
        str(details.get("title") or "").strip(),
        str(card.get("title") or "").strip(),
    ]
    answer = next((item for item in summary_candidates if item), "")
    return answer


def _web_question_slice(prompt: str, query: str) -> str:
    text = _normalize_goal_text(prompt or query)
    if not text:
        return "general"
    if "weather" in text or any(token in text for token in {"temperature", "forecast", "rain", "snow", "humidity"}):
        return "weather"
    if any(token in text for token in {"news", "latest", "today", "breaking", "headlines", "what changed", "what's happening"}):
        return "news"
    if re.search(r"\b(who|what|when|where|why|how)\b", text):
        return "fact"
    return "general"


def _ensure_terminal_sentence(text: str) -> str:
    clean = " ".join(str(text or "").split()).strip()
    if not clean:
        return ""
    if clean[-1] not in ".!?":
        clean += "."
    return clean


def _render_memla_web_answer(
    *,
    prompt: str,
    query: str,
    answer: str,
    source_title: str,
    source_count: int,
    source_kind: str = "",
) -> tuple[str, dict[str, Any]]:
    slice_kind = _web_question_slice(prompt, query)
    direct = _ensure_terminal_sentence(answer)
    clean_source = " ".join(str(source_title or "").split()).strip()
    follow_up = ""
    direct_lower = direct.lower()
    source_lower = clean_source.lower()
    if str(source_kind or "").strip() in {"google_ai_overview", "google_featured_snippet", "google_answer_box", "google_weather", "google_role_holder"}:
        follow_up = ""
    elif clean_source and source_lower not in direct_lower:
        if slice_kind == "news":
            if source_count > 1:
                follow_up = f"I checked {source_count} sources and {clean_source} was the clearest one."
            else:
                follow_up = f"I pulled that from {clean_source}."
        elif slice_kind == "weather":
            follow_up = f"I pulled the latest read from {clean_source}."
        elif slice_kind == "fact":
            follow_up = f"I pulled that from {clean_source}."
        elif source_count > 1:
            follow_up = f"I checked {source_count} sources and {clean_source} was the strongest one."
        else:
            follow_up = f"I pulled that from {clean_source}."
    elif source_count > 1 and slice_kind in {"news", "general"}:
        follow_up = f"I checked {source_count} sources to keep it grounded."

    rendered = direct
    if follow_up:
        rendered = f"{direct} {follow_up}".strip()
    return rendered, {
        "voice": "memla_web_friend_v1",
        "slice": slice_kind,
        "source_note": follow_up,
        "source_count": int(source_count),
        "source_kind": str(source_kind or "").strip(),
    }


def _looks_like_limitation_answer(answer: str) -> bool:
    normalized = _normalize_goal_text(answer)
    if not normalized:
        return True
    limitation_cues = (
        "cannot provide",
        "can not provide",
        "cannot determine",
        "do not have access",
        "don't have access",
        "limited information",
        "only show",
        "only shows",
        "without actual",
        "lack concrete",
        "not clearly documented",
        "not included in the evidence",
    )
    return any(cue in normalized for cue in limitation_cues)


def _extract_concrete_detail_from_evidence(
    *,
    prompt: str,
    query: str,
    evidence_items: list[dict[str, Any]],
) -> str:
    seen: set[str] = set()
    for item in list(evidence_items or [])[:3]:
        combined = " ".join(
            part
            for part in [
                str(item.get("summary") or "").strip(),
                str(item.get("content_preview") or "").strip(),
                str(item.get("title") or "").strip(),
            ]
            if part
        )
        snippet = _query_focused_snippet(combined, prompt or query)
        snippet = _ensure_terminal_sentence(snippet)
        normalized = _normalize_goal_text(snippet)
        if not snippet or not normalized or normalized in seen or _looks_like_low_signal_web_text(snippet):
            continue
        seen.add(normalized)
        return snippet
    return ""


def _source_titles_for_guidance(cards: list[dict[str, Any]], *, exclude: str, limit: int = 3) -> list[str]:
    titles: list[str] = []
    seen: set[str] = set()
    exclude_key = _normalize_goal_text(exclude)
    for card in list(cards or [])[:5]:
        title = " ".join(str(card.get("title") or "").split()).strip()
        if not title:
            continue
        key = _normalize_goal_text(title)
        if not key or key in seen or (exclude_key and key == exclude_key):
            continue
        seen.add(key)
        titles.append(title)
        if len(titles) >= max(int(limit), 0):
            break
    return titles


def _apply_web_policy_priors(
    *,
    prompt: str,
    query: str,
    slice_kind: str,
    answer: str,
    source_title: str,
    source_url: str,
    source_count: int,
    cards: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    priors: dict[str, Any],
) -> str:
    behaviors = [str(item).strip() for item in list(priors.get("behaviors") or []) if str(item).strip()]
    if not behaviors:
        return answer
    adjusted = _ensure_terminal_sentence(answer)
    limited = _looks_like_limitation_answer(adjusted) or _looks_like_low_signal_web_text(adjusted)
    detail = ""
    if "extract_concrete_detail" in behaviors:
        detail = _extract_concrete_detail_from_evidence(prompt=prompt, query=query, evidence_items=evidence_items)
    if limited and detail:
        if slice_kind == "news":
            adjusted = f"I found limited coverage, but one concrete update is {detail}".strip()
        elif slice_kind == "fact":
            adjusted = detail
        elif slice_kind == "general":
            adjusted = f"I found one concrete detail: {detail}".strip()
    elif limited and "direct_to_found_source" in behaviors:
        if slice_kind == "weather":
            adjusted = "I don't have current weather conditions in the evidence right now."
        elif slice_kind == "news":
            adjusted = "I found limited specific coverage in the evidence right now."
        elif slice_kind == "fact":
            adjusted = "I found limited direct evidence for that right now."
        else:
            adjusted = "I found limited direct detail in the evidence right now."
    source_sentence = ""
    if limited and source_title and "direct_to_found_source" in behaviors and _normalize_goal_text(source_title) not in _normalize_goal_text(adjusted):
        if slice_kind == "weather":
            source_sentence = f"For today's weather, you can check {source_title} directly."
        elif slice_kind == "news":
            source_sentence = f"For the latest details, you can check {source_title} directly."
        else:
            source_sentence = f"You can check {source_title} directly for the latest details."
    next_step_sentence = ""
    if "offer_actionable_next_step" in behaviors and limited:
        alternates = _source_titles_for_guidance(cards, exclude=source_title, limit=2)
        if alternates and slice_kind == "news":
            next_step_sentence = f"If you want to keep digging, {', '.join(alternates)} look like the best next places to check."
        elif not source_sentence and source_url:
            next_step_sentence = "If you want, I can open the source I found next."
    parts = [adjusted]
    if source_sentence:
        parts.append(_ensure_terminal_sentence(source_sentence))
    if next_step_sentence:
        parts.append(_ensure_terminal_sentence(next_step_sentence))
    if "tight_direct_answer" in behaviors and slice_kind == "fact" and len(parts) > 1:
        parts = parts[:2]
    return " ".join(part.strip() for part in parts if part.strip()).strip()


def _web_answer_needs_model_rescue(slice_kind: str, answer: str, *, question_type: str = "") -> bool:
    clean = " ".join(str(answer or "").split()).strip()
    if not clean:
        return True
    normalized = _normalize_goal_text(clean)
    if len(clean) < 32:
        return True
    if _looks_like_low_signal_web_text(clean):
        return True
    if _answer_fails_question_type(clean, question_type):
        return True
    if slice_kind == "weather":
        return not bool(re.search(r"\b\d{1,3}\b", clean))
    if slice_kind == "fact":
        return bool(
            normalized.startswith(("in the shadow of", "saw a wave of", "anthropic s"))
            or normalized.endswith(("source", "source today", "source now"))
        )
    return False


def _render_web_answer_via_model(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    query: str,
    slice_kind: str,
    evidence_items: list[dict[str, Any]],
    result_cards: list[dict[str, Any]],
    evidence_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    requirements = _web_answer_requirements(prompt, query, slice_kind)
    evidence_lines: list[str] = []
    for index, item in enumerate(list(evidence_items or [])[:3], start=1):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        preview = str(item.get("content_preview") or "").strip()
        source_kind = str(item.get("source_kind") or "").strip()
        evidence_lines.append(
            "\n".join(
                part
                for part in [
                    f"{index}. {title} ({source_kind})",
                    f"summary: {summary}" if summary else "",
                    f"preview: {preview}" if preview else "",
                ]
                if part
            )
        )
    card_lines: list[str] = []
    for index, card in enumerate(list(result_cards or [])[:3], start=1):
        title = str(card.get("title") or "").strip()
        summary = str(card.get("summary") or "").strip()
        url = str(card.get("url") or "").strip()
        card_lines.append(f"{index}. {title} | {summary} | {url}")
    chunk_lines: list[str] = []
    for chunk in list(evidence_chunks or [])[:10]:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        title = str(chunk.get("title") or "").strip()
        text = str(chunk.get("text") or "").strip()
        chunk_lines.append(f"{chunk_id} | {title} | {text}")
    response = client.chat(
        model=model,
        temperature=0.1,
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You are Memla's bounded web answer renderer and evidence selector. "
                    "Answer like a smart, calm friend. "
                    "Use only the evidence provided. "
                    "First decide which evidence chunks actually answer the question. "
                    "Ignore site chrome, slogans, navigation text, SEO blurbs, and article-summary filler. "
                    "Give the direct answer first. "
                    "For news, give 1-3 short concrete highlights. "
                    "For weather, include actual conditions or temperature if present. "
                    "For factual questions, state the fact plainly in the first sentence. "
                    "For questions like 'how old were they when they did it', compute the age if the evidence includes both birth timing and event timing. "
                    "Do not describe what a source page covers. "
                    "Do not mention browsing, SEO, or marketing language. "
                    "If the evidence is weak or incomplete, say that plainly. "
                    "Return JSON only with keys: "
                    "answer, question_type, relevant_chunk_ids, extracted_facts, missing_fields. "
                    "relevant_chunk_ids and extracted_facts and missing_fields must be JSON arrays."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Prompt: {prompt}\n"
                    f"Query: {query}\n"
                    f"Slice: {slice_kind}\n"
                    f"Question type: {requirements.get('question_type', '')}\n"
                    f"Needed fields: {json.dumps(list(requirements.get('needed_fields') or []))}\n"
                    "Top result cards:\n"
                    + ("\n".join(card_lines) if card_lines else "(none)")
                    + "\n\nEvidence chunks:\n"
                    + ("\n".join(chunk_lines) if chunk_lines else "(none)")
                    + "\n\nSupporting evidence summaries:\n"
                    + ("\n\n".join(evidence_lines) if evidence_lines else "(none)")
                ),
            ),
        ],
    )
    payload = _extract_first_json_object(response)
    answer = str(payload.get("answer") or "").strip()
    return {
        "answer": " ".join(answer.split()).strip(),
        "question_type": str(payload.get("question_type") or requirements.get("question_type") or "").strip(),
        "relevant_chunk_ids": [
            str(item).strip()
            for item in list(payload.get("relevant_chunk_ids") or [])
            if str(item).strip()
        ],
        "extracted_facts": [
            str(item).strip()
            for item in list(payload.get("extracted_facts") or [])
            if str(item).strip()
        ],
        "missing_fields": [
            str(item).strip()
            for item in list(payload.get("missing_fields") or [])
            if str(item).strip()
        ],
    }


def _goal_subject_for_web(prompt: str, query: str) -> dict[str, str]:
    title = str(prompt or "").strip() or str(query or "").strip()
    return {
        "title": title,
        "url": "",
        "summary": "",
    }


def _resolve_web_answer(
    *,
    prompt: str,
    query: str,
    limit: int = 5,
    client: UniversalLLMClient | None = None,
    model: str = "",
) -> dict[str, Any]:
    slice_kind = _web_question_slice(prompt, query)
    requirements = _web_answer_requirements(prompt, query, slice_kind)
    policy_priors = suggest_web_policy_priors(
        prompt=prompt,
        query=query,
        slice_kind=slice_kind,
        repo_root=os.getcwd(),
    )
    google_surface = _fetch_google_answer_surface(query)
    google_surface_hit = bool(google_surface.get("answer"))
    evidence_items: list[dict[str, Any]] = []
    evidence_chunks: list[dict[str, Any]] = []
    enriched_cards: list[dict[str, Any]] = []
    best_card: dict[str, Any] = {}
    best_details: dict[str, Any] = {}
    answer = ""
    fallback_answer = ""
    model_render_payload: dict[str, Any] = {}
    synthesis: dict[str, Any] = {}
    if google_surface_hit:
        answer = str(google_surface.get("answer") or "").strip()
        source_cards = [dict(item) for item in list(google_surface.get("source_cards") or []) if isinstance(item, dict)]
        enriched_cards = source_cards
        if source_cards:
            best_card = dict(source_cards[0])
            best_details = {
                "title": str(best_card.get("title") or "").strip(),
                "url": str(best_card.get("url") or "").strip(),
                "summary": str(answer or "").strip(),
                "page_kind": str(google_surface.get("answer_kind") or "google_answer_box").strip(),
            }
            for index, card in enumerate(source_cards, start=1):
                evidence_items.append(
                    {
                        "title": str(card.get("title") or "").strip(),
                        "url": str(card.get("url") or "").strip(),
                        "summary": str(answer or "").strip(),
                        "content_preview": str(answer or "").strip(),
                        "source_kind": str(google_surface.get("answer_kind") or "google_answer_box").strip(),
                        "score": float(max(100 - index, 1)),
                    }
                )
        else:
            best_details = {
                "title": "",
                "url": str(google_surface.get("search_url") or "").strip(),
                "summary": str(answer or "").strip(),
                "page_kind": str(google_surface.get("answer_kind") or "google_answer_box").strip(),
            }
            evidence_items.append(
                {
                    "title": "Google answer surface",
                    "url": str(google_surface.get("search_url") or "").strip(),
                    "summary": str(answer or "").strip(),
                    "content_preview": str(answer or "").strip(),
                    "source_kind": str(google_surface.get("answer_kind") or "google_answer_box").strip(),
                    "score": 100.0,
                }
            )
        evidence_chunks.append(
            {
                "chunk_id": "g1",
                "source_index": 1,
                "kind": str(google_surface.get("answer_kind") or "google_answer_box").strip(),
                "title": str(best_details.get("title") or "Google answer surface").strip(),
                "url": str(best_details.get("url") or "").strip(),
                "text": str(answer or "").strip(),
                "score": 100,
            }
        )

    cards = _fetch_search_result_cards("web", query, limit=limit)
    if not cards:
        urls = _fetch_search_result_urls("web", query, limit=limit)
        cards = _fallback_cards_from_urls(urls[:limit])
    ranked_cards = _rank_cards_against_goal(cards, prompt or query) if cards else []
    top_candidates = [dict(item) for item in ranked_cards[: min(3, len(ranked_cards))]]
    if not google_surface_hit:
        best_card = dict(top_candidates[0]) if top_candidates else (dict(cards[0]) if cards else {})
        for source_index, card in enumerate(top_candidates or cards[:3], start=1):
            url = str(card.get("url") or "").strip()
            if not url:
                continue
            try:
                html = _fetch_page_html(url)
                details = _extract_page_snapshot(_browser_state_for_url(url, search_engine="web", search_query=query), html)
            except Exception:
                details = {
                    "url": url,
                    "page_kind": _browser_state_for_url(url).page_kind or "web_page",
                    "title": str(card.get("title") or url).strip(),
                    "summary": str(card.get("summary") or card.get("title") or url).strip(),
                }
            focused_summary = _query_focused_snippet(
                " ".join(
                    part
                    for part in [
                        str(details.get("summary") or "").strip(),
                        str(details.get("content_preview") or "").strip(),
                    ]
                    if part
                ),
                prompt or query,
            )
            if focused_summary and (
                _looks_like_low_signal_web_text(str(details.get("summary") or "").strip())
                or len(str(details.get("summary") or "").strip()) < 40
            ):
                details["summary"] = focused_summary
            merged_card = dict(card)
            if str(details.get("title") or "").strip():
                merged_card["title"] = str(details.get("title") or "").strip()
            if str(details.get("summary") or "").strip():
                merged_card["summary"] = str(details.get("summary") or "").strip()
            if str(details.get("url") or "").strip():
                merged_card["url"] = str(details.get("url") or "").strip()
            enriched_cards.append(merged_card)
            evidence_item = _evidence_item_from_details(
                BrowserSessionState(
                    current_url=url,
                    page_kind=str(details.get("page_kind") or _browser_state_for_url(url).page_kind or "web_page").strip(),
                    search_engine="web",
                    search_query=query,
                    subject_summary=str(details.get("summary") or "").strip(),
                ),
                details,
            )
            if "score" in card:
                evidence_item["score"] = float(card.get("score") or 0.0)
            if "matching_terms" in card:
                evidence_item["matching_terms"] = list(card.get("matching_terms") or [])
            evidence_items.append(evidence_item)
            evidence_chunks.extend(
                _build_web_evidence_chunks(
                    prompt=prompt,
                    query=query,
                    slice_kind=slice_kind,
                    source_index=source_index,
                    card=merged_card,
                    details=details,
                )
            )
            if not fallback_answer:
                fallback_answer = _best_web_answer_summary(prompt=prompt, card=merged_card, details=details)
                best_card = dict(merged_card)
                best_details = dict(details)
        synthesis = _synthesize_browser_evidence(evidence_items, prompt or query, _goal_subject_for_web(prompt, query))
        if synthesis:
            best_title = str(synthesis.get("best_source_title") or "").strip()
            best_url = str(synthesis.get("best_source_url") or "").strip()
            answer = str(synthesis.get("synthesis") or "").strip()
            for item in evidence_items:
                if str(item.get("url") or "").strip() == best_url or str(item.get("title") or "").strip() == best_title:
                    best_card = {
                        "title": str(item.get("title") or best_title).strip(),
                        "url": str(item.get("url") or best_url).strip(),
                        "summary": str(item.get("summary") or "").strip(),
                        "score": float(item.get("score") or 0.0),
                    }
                    best_details = {
                        "title": str(item.get("title") or best_title).strip(),
                        "url": str(item.get("url") or best_url).strip(),
                        "summary": str(item.get("summary") or "").strip(),
                        "page_kind": str(item.get("source_kind") or item.get("page_kind") or "web_page").strip(),
                    }
                    break
        else:
            answer = fallback_answer
        if not answer and best_card:
            best_details = {
                "url": str(best_card.get("url") or "").strip(),
                "page_kind": _browser_state_for_url(str(best_card.get("url") or "").strip()).page_kind or "web_page",
                "title": str(best_card.get("title") or best_card.get("url") or "").strip(),
                "summary": str(best_card.get("summary") or best_card.get("title") or best_card.get("url") or "").strip(),
            }
            answer = _best_web_answer_summary(prompt=prompt, card=best_card, details=best_details)
    model_rendered_answer = ""
    relevant_chunk_ids: list[str] = []
    extracted_facts: list[str] = []
    missing_fields: list[str] = []
    resolved_question_type = str(requirements.get("question_type") or slice_kind).strip()
    if client is not None and model and evidence_items:
        should_attempt_model = _web_answer_needs_model_rescue(
            slice_kind,
            answer,
            question_type=resolved_question_type,
        )
        if not google_surface_hit and slice_kind in {"fact", "news", "weather"}:
            should_attempt_model = True
        if should_attempt_model:
            try:
                model_render_payload = _render_web_answer_via_model(
                    client=client,
                    model=model,
                    prompt=prompt,
                    query=query,
                    slice_kind=slice_kind,
                    evidence_items=evidence_items,
                    result_cards=enriched_cards or top_candidates or cards,
                    evidence_chunks=evidence_chunks,
                )
                model_rendered_answer = str(model_render_payload.get("answer") or "").strip()
                relevant_chunk_ids = [str(item).strip() for item in list(model_render_payload.get("relevant_chunk_ids") or []) if str(item).strip()]
                extracted_facts = [str(item).strip() for item in list(model_render_payload.get("extracted_facts") or []) if str(item).strip()]
                missing_fields = [str(item).strip() for item in list(model_render_payload.get("missing_fields") or []) if str(item).strip()]
                resolved_question_type = str(model_render_payload.get("question_type") or resolved_question_type).strip()
            except Exception:
                model_rendered_answer = ""
                model_render_payload = {}
    if model_rendered_answer:
        answer = model_rendered_answer
    answer = _apply_web_policy_priors(
        prompt=prompt,
        query=query,
        slice_kind=slice_kind,
        answer=answer,
        source_title=str(best_details.get("title") or best_card.get("title") or "").strip(),
        source_url=str(best_details.get("url") or best_card.get("url") or "").strip(),
        source_count=len(evidence_items) or len(enriched_cards or top_candidates or cards),
        cards=enriched_cards or top_candidates or cards,
        evidence_items=evidence_items,
        priors=policy_priors,
    )
    raw_answer = str(answer or "").strip()
    rendered_answer, answer_style = _render_memla_web_answer(
        prompt=prompt,
        query=query,
        answer=raw_answer,
        source_title=str(best_details.get("title") or best_card.get("title") or "").strip(),
        source_count=len(evidence_items) or len(enriched_cards or top_candidates or cards),
        source_kind=str(best_details.get("page_kind") or "").strip(),
    )
    return {
        "query": query,
        "cards": enriched_cards or top_candidates or cards,
        "source_count": len(evidence_items),
        "answer": rendered_answer or raw_answer,
        "raw_answer": raw_answer,
        "answer_style": {
            **answer_style,
            "generator": "model" if model_rendered_answer else "heuristic",
            "policy_behaviors": list(policy_priors.get("behaviors") or []),
        },
        "question_type": resolved_question_type,
        "needed_fields": list(requirements.get("needed_fields") or []),
        "relevant_chunk_ids": relevant_chunk_ids,
        "extracted_facts": extracted_facts,
        "missing_fields": missing_fields,
        "best_card": best_card,
        "best_details": best_details,
        "synthesis": synthesis,
        "evidence_items": evidence_items,
        "evidence_chunks": evidence_chunks,
    }


_SCOUT_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
}


def _looks_like_repo_scout_prompt(prompt: str, browser_state: BrowserSessionState | None = None) -> bool:
    normalized = _intent_text(prompt)
    if not normalized:
        return False
    if not re.search(r"\b(?:github|repo|repos|repository|repositories)\b", normalized):
        return bool(
            browser_state
            and browser_state.page_kind == "search_results"
            and browser_state.search_engine == "github"
            and browser_state.result_cards
            and any(token in normalized for token in {"top", "best", "align", "match", "fit", "bring back", "show me", "list"})
        )
    strong_signals = {
        "top ",
        "best repo",
        "best repositories",
        "aligns",
        "matches",
        "fits",
        "bring back",
        "show me",
        "list the",
        "list me",
        "scout",
        "what aligns",
        "which aligns",
    }
    return any(signal in normalized for signal in strong_signals)


def _scout_limit_from_prompt(prompt: str) -> int:
    normalized = _normalize_goal_text(prompt)
    for pattern in (r"\btop\s+(\d+)\b", r"\bfirst\s+(\d+)\b", r"\bshow\s+me\s+(\d+)\b", r"\blist\s+(\d+)\b"):
        match = re.search(pattern, normalized)
        if match:
            try:
                return max(1, min(int(match.group(1)), 20))
            except ValueError:
                continue
    for word, value in _SCOUT_NUMBER_WORDS.items():
        if re.search(rf"\btop\s+{word}\b", normalized):
            return value
        if re.search(rf"\bfirst\s+{word}\b", normalized):
            return value
    if any(token in normalized for token in {"top repo", "top repos", "top repository", "top repositories"}):
        return 10
    return 5


def _strip_scout_tail(text: str) -> str:
    clean = _normalize_goal_text(text)
    for marker in (
        " and tell me ",
        " and bring ",
        " and show me ",
        " and explain ",
        " and summarize ",
        " and sum it up ",
        " then ",
        " after that ",
        " afterwards ",
        " next ",
    ):
        if marker in clean:
            clean = clean.split(marker, 1)[0].strip()
            break
    return " ".join(clean.split())


def _scout_query_from_prompt(prompt: str, browser_state: BrowserSessionState | None = None) -> str:
    clause = _strip_scout_tail(prompt)
    normalized = _intent_text(clause)
    for pattern in (
        r"\b(?:find|get|show|list|bring back|scout|see)\s+(?:me\s+)?(?:the\s+)?(?:top\s+\d+\s+)?(?:github\s+)?(?:repo|repos|repository|repositories)\s+(?:about|for|on)\s+(.+)$",
        r"\b(?:find|get|show|tell me)\s+(?:me\s+)?(?:the\s+)?best\s+(?:github\s+)?(?:repo|repos|repository|repositories)\s+for\s+(.+)$",
        r"\bwhat\s+is\s+the\s+best\s+(?:github\s+)?(?:repo|repos|repository|repositories)\s+for\s+(.+)$",
        r"\b(?:top\s+\d+\s+)?(?:github\s+)?(?:repo|repos|repository|repositories)\s+(?:about|for|on)\s+(.+)$",
        r"\b(?:find|get|show|list|bring back|scout)\s+(?:me\s+)?(?:a\s+|the\s+)?(?:cool|good|best\s+)?github\s+(?:repo|repos|repository|repositories)\s+(?:about|for|on)\s+(.+)$",
        r"\bopen\s+github\b(?:.*?\b)?search\s+(.+)$",
    ):
        match = re.search(pattern, normalized)
        if not match:
            continue
        query = _clean_inferred_query(str(match.group(1) or "").strip(), engine="github")
        if query:
            return query
    if browser_state and browser_state.search_engine == "github" and browser_state.search_query:
        return str(browser_state.search_query).strip()
    return ""


def _scout_goal_from_prompt(prompt: str, query: str) -> str:
    normalized = _intent_text(prompt)
    for pattern in (
        r"\b(?:tell me|show me)\s+which\s+(?:repo|repository|one|result)\s+(?:best\s+)?(?:aligns|matches|fits)(?:\s+most)?\s+with\s+(.+)$",
        r"\bwhich\s+(?:repo|repository|one|result)\s+(?:best\s+)?(?:aligns|matches|fits)(?:\s+most)?\s+with\s+(.+)$",
        r"\b(?:tell me|show me)\s+the\s+best\s+(?:repo|repository|one|result)\s+for\s+(.+)$",
        r"\b(?:best|winner)\s+(?:repo|repository|one|result)\s+for\s+(.+)$",
        r"\b(?:best\s+)?fits\s+(.+)$",
        r"\b(?:aligns|matches|fits)(?:\s+most)?\s+with\s+(.+)$",
    ):
        match = re.search(pattern, normalized)
        if match:
            goal = str(match.group(1) or "").strip()
            if goal:
                return goal
    return query


def _github_owner_repo_from_url(url: str) -> tuple[str, str]:
    match = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s?#]+)", str(url or "").strip(), flags=re.IGNORECASE)
    if not match:
        return "", ""
    return match.group(1), match.group(2)


def _enrich_github_repo_card(card: dict[str, Any]) -> dict[str, Any]:
    payload = dict(card or {})
    owner, repo = _github_owner_repo_from_url(str(payload.get("url") or "").strip())
    if not owner or not repo:
        return payload
    snapshot = _fetch_github_repo_snapshot(owner, repo)
    if not snapshot:
        return payload
    description = str(snapshot.get("description") or payload.get("summary") or "").strip()
    stars = str(snapshot.get("stars") or "").strip()
    forks = str(snapshot.get("forks") or "").strip()
    language = str(snapshot.get("language") or "").strip()
    topics = str(snapshot.get("topics") or "").strip()
    meta_parts: list[str] = []
    if stars:
        meta_parts.append(f"stars {stars}")
    if forks:
        meta_parts.append(f"forks {forks}")
    if language:
        meta_parts.append(language)
    if topics:
        meta_parts.append(topics)
    payload.update(snapshot)
    payload["title"] = str(snapshot.get("repo") or payload.get("title") or "").strip()
    if description:
        payload["summary"] = description
    if meta_parts:
        payload["meta"] = " | ".join(meta_parts)
    return payload


def _scout_result_payload(card: dict[str, Any]) -> dict[str, Any]:
    payload = dict(card or {})
    return {
        key: value
        for key, value in {
            "index": int(payload.get("index") or 0),
            "title": str(payload.get("title") or "").strip(),
            "url": str(payload.get("url") or "").strip(),
            "summary": str(payload.get("summary") or "").strip(),
            "meta": str(payload.get("meta") or "").strip(),
            "score": float(payload.get("score") or 0.0),
            "matching_terms": list(payload.get("matching_terms") or []),
            "repo": str(payload.get("repo") or "").strip(),
            "stars": str(payload.get("stars") or "").strip(),
            "forks": str(payload.get("forks") or "").strip(),
            "language": str(payload.get("language") or "").strip(),
            "topics": str(payload.get("topics") or "").strip(),
        }.items()
        if value not in ("", None, [], 0) or key == "index"
    }


def _scout_summary_text(*, query: str, goal: str, total: int, best: dict[str, Any]) -> str:
    title = str(best.get("title") or best.get("repo") or best.get("url") or "none").strip()
    description = str(best.get("summary") or "").strip()
    stars = str(best.get("stars") or "").strip()
    language = str(best.get("language") or "").strip()
    terms = list(best.get("matching_terms") or [])
    reason_parts: list[str] = []
    if terms:
        reason_parts.append(f"matched {', '.join(str(term) for term in terms[:4])}")
    if stars:
        reason_parts.append(f"stars {stars}")
    if language:
        reason_parts.append(f"language {language}")
    reason_text = f" ({'; '.join(reason_parts)})" if reason_parts else ""
    if goal and goal != query:
        lead = f"Scouted {total} GitHub repos for \"{query}\". Best match for \"{goal}\": {title}{reason_text}."
    else:
        lead = f"Scouted {total} GitHub repos for \"{query}\". Top pick: {title}{reason_text}."
    if description:
        return f"{lead} {description}".strip()
    return lead


def run_terminal_scout(
    prompt: str,
    *,
    browser_state: BrowserSessionState | None = None,
    state_path: str | Path | None = None,
    save_state: bool = False,
) -> TerminalScoutResult:
    current_browser_state = browser_state or load_browser_session_state(state_path)
    if not _looks_like_repo_scout_prompt(prompt, current_browser_state):
        return TerminalScoutResult(
            prompt=prompt,
            scout_kind="github_repo_scout",
            source="unsupported",
            ok=False,
            residual_constraints=["unsupported_scout_request"],
            summary="Memla scout currently covers bounded GitHub repo scouting prompts.",
            browser_state=asdict(current_browser_state),
        )

    requested_limit = _scout_limit_from_prompt(prompt)
    query = _scout_query_from_prompt(prompt, current_browser_state)
    goal = _scout_goal_from_prompt(prompt, query)
    inspected_limit = min(max(requested_limit, 1), 3)
    residuals: list[str] = []
    steps: list[TerminalScoutStep] = []

    if not query:
        residuals.append("scout_query_missing")
        return TerminalScoutResult(
            prompt=prompt,
            scout_kind="github_repo_scout",
            source="heuristic",
            ok=False,
            goal=goal,
            requested_limit=requested_limit,
            inspected_limit=inspected_limit,
            residual_constraints=residuals,
            summary="Memla scout needs a GitHub repo query, or an active GitHub search-results page to reuse.",
            browser_state=asdict(current_browser_state),
        )

    if (
        current_browser_state.page_kind == "search_results"
        and current_browser_state.search_engine == "github"
        and current_browser_state.result_cards
        and _normalize_goal_text(current_browser_state.search_query) == _normalize_goal_text(query)
    ):
        cards = [dict(card) for card in _cached_cards(current_browser_state)[:requested_limit]]
        scout_state = _browser_state_for_url(
            current_browser_state.current_url or _search_url("github", query),
            browser_app=current_browser_state.browser_app,
            search_engine="github",
            search_query=query,
            result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
            result_cards=cards,
            evidence_items=[],
        )
        steps.append(
            TerminalScoutStep(
                transmutation="browser_extract_cards",
                status="ok",
                message=f"Reused {len(cards)} cached GitHub repo results for \"{query}\".",
                details={"query": query, "result_count": len(cards)},
            )
        )
    else:
        cards = _fetch_github_search_cards(query, limit=requested_limit)
        if not cards:
            residuals.append("search_result_unavailable")
            return TerminalScoutResult(
                prompt=prompt,
                scout_kind="github_repo_scout",
                source="heuristic",
                ok=False,
                query=query,
                goal=goal,
                requested_limit=requested_limit,
                inspected_limit=inspected_limit,
                residual_constraints=residuals,
                summary=f"Memla scout could not fetch GitHub repo results for \"{query}\".",
                browser_state=asdict(current_browser_state),
            )
        scout_state = _browser_state_for_url(
            _search_url("github", query),
            browser_app=current_browser_state.browser_app,
            search_engine="github",
            search_query=query,
            result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
            result_cards=cards,
            evidence_items=[],
        )
        steps.append(
            TerminalScoutStep(
                transmutation="browser_extract_cards",
                status="ok",
                message=f"Fetched {len(cards)} GitHub repo results for \"{query}\".",
                details={"query": query, "result_count": len(cards)},
            )
        )

    ranked = _rank_cards_against_goal(cards, goal)
    top_results = ranked[:requested_limit]
    steps.append(
        TerminalScoutStep(
            transmutation="browser_rank_cards",
            status="ok",
            message=(
                f"Ranked {len(top_results)} repo candidates against \"{goal}\"."
                if goal
                else f"Ranked {len(top_results)} repo candidates."
            ),
            details={
                "goal": goal,
                "top_titles": [str(item.get("title") or "").strip() for item in top_results[: min(5, len(top_results))]],
            },
        )
    )

    enriched_by_url: dict[str, dict[str, Any]] = {}
    for candidate in top_results[:inspected_limit]:
        enriched = _enrich_github_repo_card(candidate)
        url = str(enriched.get("url") or "").strip()
        if url:
            enriched_by_url[url.lower()] = enriched
        scout_state = _append_browser_evidence(
            scout_state,
            _evidence_item_from_subject(
                {
                    "title": str(enriched.get("title") or "").strip(),
                    "url": url,
                    "summary": str(enriched.get("summary") or "").strip(),
                },
                source_kind="repo_page",
                meta="github repo",
            ),
        )
        steps.append(
            TerminalScoutStep(
                transmutation="browser_read_page",
                status="ok",
                message=f"Inspected repo: {str(enriched.get('title') or url or 'unknown').strip()}",
                details={"url": url, "stars": str(enriched.get("stars") or "").strip(), "language": str(enriched.get("language") or "").strip()},
            )
        )

    reranked_candidates: list[dict[str, Any]] = []
    for candidate in top_results:
        url = str(candidate.get("url") or "").strip().lower()
        reranked_candidates.append(dict(enriched_by_url.get(url) or candidate))
    reranked = _rank_cards_against_goal(reranked_candidates, goal)
    top_results = reranked[:requested_limit]
    inspected_results = [
        _scout_result_payload(enriched_by_url[url])
        for url in list(enriched_by_url)
    ]
    best_match = dict(top_results[0]) if top_results else {}
    if best_match:
        scout_state = _browser_state_with_subject(scout_state, best_match)
        scout_state = _browser_state_with_research_subject(scout_state, best_match)
    scout_state = _browser_state_copy(
        scout_state,
        result_urls=[str(item.get("url") or "").strip() for item in top_results if str(item.get("url") or "").strip()],
        result_cards=[dict(item) for item in top_results],
    )
    if inspected_results:
        steps.append(
            TerminalScoutStep(
                transmutation="browser_rank_cards",
                status="ok",
                message=f"Reranked the top {len(top_results)} repos after inspecting {len(inspected_results)} candidates.",
                details={"best_title": str(best_match.get("title") or "").strip(), "goal": goal},
            )
        )

    summary = _scout_summary_text(query=query, goal=goal, total=len(top_results), best=best_match) if best_match else ""
    if save_state:
        save_browser_session_state(scout_state, path=state_path)
    result = TerminalScoutResult(
        prompt=prompt,
        scout_kind="github_repo_scout",
        source="heuristic",
        ok=bool(best_match),
        query=query,
        goal=goal,
        requested_limit=requested_limit,
        inspected_limit=inspected_limit,
        steps=steps,
        top_results=[_scout_result_payload(item) for item in top_results],
        inspected_results=inspected_results,
        best_match=_scout_result_payload(best_match),
        summary=summary,
        residual_constraints=residuals,
        browser_state=asdict(scout_state),
    )
    try:
        _record_scout_autonomy_memory(result, state_path=state_path)
    except OSError:
        pass
    return result


def _is_browser_app(app_key: str) -> bool:
    return _normalize_label(app_key) in {"brave", "chrome", "edge", "firefox"}


def _powershell_single_quoted(value: str) -> str:
    return str(value or "").replace("'", "''")


def _preferred_browser_app(browser_app: str = "") -> str:
    explicit = str(browser_app or "").strip()
    if explicit:
        return explicit
    return str(os.environ.get(PREFERRED_BROWSER_ENV, "") or "").strip()


def _windows_browser_window_titles(browser_app: str = "") -> list[str]:
    preferred = _normalize_label(_preferred_browser_app(browser_app))
    title_map = {
        "brave": ["Brave"],
        "chrome": ["Google Chrome", "Chrome"],
        "edge": ["Microsoft Edge", "Edge"],
        "firefox": ["Firefox"],
    }
    ordered: list[str] = []
    for title in title_map.get(preferred, []):
        if title not in ordered:
            ordered.append(title)
    for title in ["Brave", "Google Chrome", "Chrome", "Firefox", "Microsoft Edge", "Edge"]:
        if title not in ordered:
            ordered.append(title)
    return ordered


def _windows_browser_sendkeys_command(*, keys: list[str], clipboard_value: str = "", browser_app: str = "") -> list[str]:
    titles = _windows_browser_window_titles(browser_app)
    if not titles or not keys:
        return []
    titles_literal = ", ".join(f"'{_powershell_single_quoted(title)}'" for title in titles)
    statements = [
        "$wshell = New-Object -ComObject WScript.Shell",
        f"$titles = @({titles_literal})",
        "$activated = $false",
        "foreach ($title in $titles) { if ($wshell.AppActivate($title)) { $activated = $true; break } }",
        "if (-not $activated) { exit 17 }",
        "Start-Sleep -Milliseconds 150",
    ]
    if clipboard_value:
        statements.append(f"Set-Clipboard -Value '{_powershell_single_quoted(clipboard_value)}'")
        statements.append("Start-Sleep -Milliseconds 75")
    for key in keys:
        statements.append(f"$wshell.SendKeys('{_powershell_single_quoted(key)}')")
        statements.append("Start-Sleep -Milliseconds 75")
    return [
        "powershell.exe",
        "-NoProfile",
        "-Command",
        "; ".join(statements),
    ]


def _run_command(command: list[str], *, wait: bool = False, timeout: float = 8.0) -> int | None:
    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    if not wait:
        return None
    try:
        return process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        return None


def _browser_new_tab_command(*, platform_name: str, browser_app: str = "") -> list[str]:
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        return [xdotool, "key", "ctrl+t"] if xdotool else []
    if platform_key == "darwin":
        return ["osascript", "-e", 'tell application "System Events" to keystroke "t" using command down']
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["^t"], browser_app=browser_app)
    return []


def _browser_close_tab_command(*, platform_name: str, browser_app: str = "") -> list[str]:
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        return [xdotool, "key", "ctrl+w"] if xdotool else []
    if platform_key == "darwin":
        return ["osascript", "-e", 'tell application "System Events" to keystroke "w" using command down']
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["^w"], browser_app=browser_app)
    return []


def _browser_switch_tab_command(target: str, *, platform_name: str, browser_app: str = "") -> list[str]:
    normalized = _normalize_label(target)
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return []
        if normalized in {"previous", "prev"}:
            return [xdotool, "key", "ctrl+shift+Tab"]
        if normalized.isdigit():
            return [xdotool, "key", f"ctrl+{normalized}"]
        return [xdotool, "key", "ctrl+Tab"]
    if platform_key == "darwin":
        if normalized in {"previous", "prev"}:
            return ["osascript", "-e", 'tell application "System Events" to keystroke tab using {command down, shift down}']
        if normalized.isdigit():
            return ["osascript", "-e", f'tell application "System Events" to keystroke "{normalized}" using command down']
        return ["osascript", "-e", 'tell application "System Events" to keystroke tab using control down']
    if platform_key == "win32":
        key = "^+{TAB}" if normalized in {"previous", "prev"} else "^{TAB}"
        if normalized.isdigit():
            key = f"^{normalized}"
        return _windows_browser_sendkeys_command(keys=[key], browser_app=browser_app)
    return []


def _browser_forward_command(*, platform_name: str, browser_app: str = "") -> list[str]:
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        return [xdotool, "key", "alt+Right"] if xdotool else []
    if platform_key == "darwin":
        return ["osascript", "-e", 'tell application "System Events" to keystroke "]" using command down']
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["%{RIGHT}"], browser_app=browser_app)
    return []


def _browser_scroll_command(direction: str, *, platform_name: str, browser_app: str = "") -> list[str]:
    normalized = _normalize_label(direction)
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return []
        return [xdotool, "key", "Page_Up" if normalized == "up" else "Page_Down"]
    if platform_key == "darwin":
        key = "page up" if normalized == "up" else "page down"
        return ["osascript", "-e", f'tell application "System Events" to key code {"116" if normalized == "up" else "121"}']
    if platform_key == "win32":
        key = "{PGUP}" if normalized == "up" else "{PGDN}"
        return _windows_browser_sendkeys_command(keys=[key], browser_app=browser_app)
    return []


def _browser_type_text_command(text: str, *, platform_name: str, browser_app: str = "") -> list[str]:
    clean = str(text or "")
    if not clean:
        return []
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        return [xdotool, "type", "--delay", "0", clean] if xdotool else []
    if platform_key == "darwin":
        escaped = clean.replace("\\", "\\\\").replace('"', '\\"')
        return ["osascript", "-e", f'tell application "System Events" to keystroke "{escaped}"']
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["^v"], clipboard_value=clean, browser_app=browser_app)
    return []


def _browser_submit_command(*, platform_name: str, browser_app: str = "") -> list[str]:
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        return [xdotool, "key", "Return"] if xdotool else []
    if platform_key == "darwin":
        return ["osascript", "-e", 'tell application "System Events" to key code 36']
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["~"], browser_app=browser_app)
    return []


def _browser_screenshot_command(output_path: Path, *, platform_name: str) -> list[str]:
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        for tool in ("gnome-screenshot", "scrot", "import"):
            resolved = shutil.which(tool)
            if not resolved:
                continue
            if tool == "gnome-screenshot":
                return [resolved, "-f", str(output_path)]
            if tool == "scrot":
                return [resolved, str(output_path)]
            return [resolved, str(output_path)]
        return []
    if platform_key == "darwin":
        return ["screencapture", "-x", str(output_path)]
    if platform_key == "win32":
        escaped = str(output_path).replace("'", "''")
        return [
            "powershell.exe",
            "-NoProfile",
            "-Command",
            (
                "Add-Type -AssemblyName System.Windows.Forms; "
                "Add-Type -AssemblyName System.Drawing; "
                "$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds; "
                "$bitmap = New-Object System.Drawing.Bitmap $bounds.Width, $bounds.Height; "
                "$graphics = [System.Drawing.Graphics]::FromImage($bitmap); "
                "$graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size); "
                f"$bitmap.Save('{escaped}', [System.Drawing.Imaging.ImageFormat]::Png); "
                "$graphics.Dispose(); $bitmap.Dispose()"
            ),
        ]
    return []


def _navigate_active_browser_command(url: str, *, platform_name: str, browser_app: str = "") -> list[str]:
    clean_url = str(url or "").strip()
    if not clean_url:
        return []
    platform_key = _platform_key(platform_name)
    if platform_key == "linux":
        xdotool = shutil.which("xdotool")
        if not xdotool:
            return []
        return [xdotool, "key", "ctrl+l", "type", "--delay", "0", clean_url, "key", "Return"]
    if platform_key == "darwin":
        return [
            "osascript",
            "-e",
            'tell application "System Events" to keystroke "l" using command down',
            "-e",
            f'tell application "System Events" to keystroke "{clean_url}"',
            "-e",
            'tell application "System Events" to key code 36',
        ]
    if platform_key == "win32":
        return _windows_browser_sendkeys_command(keys=["^l", "^v", "~"], clipboard_value=clean_url, browser_app=browser_app)
    return []


def _browser_media_command(action_kind: str, *, platform_name: str) -> list[str]:
    if _platform_key(platform_name) != "linux":
        return []
    playerctl = shutil.which("playerctl")
    if not playerctl:
        return []
    if action_kind == "browser_media_pause":
        return [playerctl, "pause"]
    if action_kind == "browser_media_play":
        return [playerctl, "play"]
    return []


def execute_terminal_plan(
    plan: TerminalPlan,
    *,
    platform_name: str | None = None,
    browser_state: BrowserSessionState | None = None,
    state_path: str | Path | None = None,
    client: UniversalLLMClient | None = None,
    model: str = "",
) -> TerminalExecutionResult:
    platform_key = _platform_key(platform_name or sys.platform)
    records: list[TerminalExecutionRecord] = []
    residuals = list(plan.residual_constraints)
    current_browser_state = browser_state or load_browser_session_state(state_path)
    initial_browser_state = _browser_state_copy(current_browser_state)
    for index, action in enumerate(plan.actions):
        next_action = plan.actions[index + 1] if index + 1 < len(plan.actions) else None
        if action.kind == "launch_app":
            command = _resolve_launch_command(action.resolved_target or action.target, platform_name=platform_key)
            if not command:
                residuals.append(f"app_not_found:{action.resolved_target or action.target}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Could not find an installed launcher for {action.resolved_target or action.target}.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Launched {action.resolved_target or action.target}.",
                    command=command,
                )
            )
            app_key = _resolve_app_key(action.resolved_target or action.target)
            if _is_browser_app(app_key):
                current_browser_state = _browser_state_copy(current_browser_state, browser_app=app_key)
            continue
        if action.kind == "browser_answer_query":
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            query = str(note_payload.get("query") or action.resolved_target or action.target or goal).strip()
            try:
                answer_payload = _resolve_web_answer(
                    prompt=goal or plan.prompt,
                    query=query,
                    client=client,
                    model=model,
                )
            except Exception as exc:
                residuals.append("browser_web_answer_failed")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Memla could not answer that web question yet: {str(exc).strip() or 'unknown error'}.",
                    )
                )
                continue
            answer = str(answer_payload.get("answer") or "").strip()
            cards = [dict(item) for item in list(answer_payload.get("cards") or []) if isinstance(item, dict)]
            best_card = dict(answer_payload.get("best_card") or {})
            best_details = dict(answer_payload.get("best_details") or {})
            synthesis = dict(answer_payload.get("synthesis") or {})
            evidence_items = [dict(item) for item in list(answer_payload.get("evidence_items") or []) if isinstance(item, dict)]
            source_count = int(answer_payload.get("source_count") or len(evidence_items) or len(cards) or 0)
            best_url = str(best_details.get("url") or best_card.get("url") or "").strip()
            if not answer:
                residuals.append("browser_web_answer_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Memla could not resolve a strong web answer from the current query yet.",
                        details={
                            "goal": goal,
                            "query": query,
                            "top_results": cards,
                        },
                    )
                )
                continue
            current_browser_state = BrowserSessionState(
                current_url=best_url,
                page_kind=str(best_details.get("page_kind") or _browser_state_for_url(best_url).page_kind or "web_page").strip(),
                browser_app=current_browser_state.browser_app,
                search_engine="web",
                search_query=query,
                result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
                result_cards=cards,
                subject_title=str(best_details.get("title") or best_card.get("title") or "").strip(),
                subject_url=best_url,
                subject_summary=answer,
                research_subject_title=goal,
                research_subject_url=best_url,
                research_subject_summary=answer,
                evidence_items=_clone_evidence_items(current_browser_state.evidence_items),
            )
            for evidence_item in evidence_items:
                current_browser_state = _append_browser_evidence(current_browser_state, evidence_item)
            if not evidence_items:
                current_browser_state = _append_browser_evidence(
                    current_browser_state,
                    _evidence_item_from_details(current_browser_state, best_details or {
                        "url": best_url,
                        "title": str(best_card.get("title") or best_url).strip(),
                        "summary": answer,
                        "page_kind": str(best_details.get("page_kind") or "web_page").strip(),
                    }),
                )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=answer,
                    details={
                        "goal": goal,
                        "query": query,
                        "best_source_title": str(best_details.get("title") or best_card.get("title") or "").strip(),
                        "best_source_url": best_url,
                        "best_source_kind": str(best_details.get("page_kind") or synthesis.get("best_source_kind") or "web_page").strip(),
                        "source_count": source_count,
                        "synthesis": str(synthesis.get("synthesis") or answer).strip(),
                        "top_results": cards,
                    },
                )
            )
            continue
        if action.kind in {"open_url", "open_path"}:
            target = action.resolved_target or action.target
            if action.kind == "open_path":
                path_target = Path(target).expanduser()
                if not path_target.exists():
                    residuals.append(f"path_not_found:{path_target}")
                    records.append(
                        TerminalExecutionRecord(
                            kind=action.kind,
                            target=action.target,
                            status="failed",
                            message=f"{path_target} does not exist.",
                        )
                    )
                    continue
            note_payload = _decode_action_note(action.note)
            tab_mode = str(note_payload.get("tab_mode") or "").strip().lower()
            use_active_tab = action.kind == "open_url" and tab_mode == "new_tab" and current_browser_state.page_kind == "blank_tab"
            command = (
                _navigate_active_browser_command(
                    target,
                    platform_name=platform_key,
                    browser_app=current_browser_state.browser_app,
                )
                if use_active_tab
                else _open_in_browser(target, platform_name=platform_key)
            )
            if not command:
                residuals.append(f"open_command_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"No opener command is configured for platform {platform_key}.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=use_active_tab and platform_key == "win32")
            fallback_used = False
            if use_active_tab and platform_key == "win32" and exit_code not in (None, 0):
                command = _open_in_browser(target, platform_name=platform_key)
                if not command:
                    residuals.append("browser_focus_unavailable")
                    records.append(
                        TerminalExecutionRecord(
                            kind=action.kind,
                            target=action.target,
                            status="failed",
                            message="Could not activate a browser window safely, so Memla skipped typing into the terminal.",
                        )
                    )
                    continue
                _run_command(command)
                use_active_tab = False
                fallback_used = True
            search_engine = str(note_payload.get("search_engine") or "").strip()
            search_query = str(note_payload.get("search_query") or "").strip()
            if search_engine and search_query:
                result_urls: list[str] = []
                result_cards: list[dict[str, Any]] = []
                try:
                    result_cards = _fetch_search_result_cards(search_engine, search_query, limit=5)
                    result_urls = [str(card.get("url") or "").strip() for card in result_cards if str(card.get("url") or "").strip()]
                    if not result_urls:
                        result_urls = _fetch_search_result_urls(search_engine, search_query, limit=5)
                        result_cards = _fallback_cards_from_urls(result_urls)
                except Exception:
                    result_urls = []
                    result_cards = []
                current_browser_state = _browser_state_for_url(
                    target,
                    browser_app=current_browser_state.browser_app,
                    search_engine=search_engine,
                    search_query=search_query,
                    result_urls=result_urls,
                    result_cards=result_cards,
                )
            else:
                current_browser_state = _browser_state_for_url(target, browser_app=current_browser_state.browser_app)
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=(
                        "Could not safely target the active browser tab, so opened "
                        if fallback_used
                        else ("Navigated the active browser tab to " if use_active_tab else "Opened ")
                    )
                    + f"{target}.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_new_tab":
            command = _browser_new_tab_command(platform_name=platform_key, browser_app=current_browser_state.browser_app)
            if not command:
                residuals.append(f"browser_new_tab_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Opening a new browser tab is not wired for platform {platform_key}.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                if next_action is not None and next_action.kind == "open_url":
                    records.append(
                        TerminalExecutionRecord(
                            kind=action.kind,
                            target=action.target,
                            status="ok",
                            message="Skipped the raw new-tab shortcut because no browser window could be activated safely; Memla will open the requested page directly instead.",
                            command=command,
                        )
                    )
                    continue
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the new-tab shortcut instead of typing into the terminal.",
                        command=command,
                    )
                )
                continue
            current_browser_state = BrowserSessionState(
                current_url="browser://new-tab",
                page_kind="blank_tab",
                browser_app=current_browser_state.browser_app,
                research_subject_title=current_browser_state.research_subject_title,
                research_subject_url=current_browser_state.research_subject_url,
                research_subject_summary=current_browser_state.research_subject_summary,
                evidence_items=_clone_evidence_items(current_browser_state.evidence_items),
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser new-tab shortcut.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_close_tab":
            command = _browser_close_tab_command(platform_name=platform_key, browser_app=current_browser_state.browser_app)
            if not command:
                residuals.append(f"browser_close_tab_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Closing the browser tab is not wired for platform {platform_key}.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the close-tab shortcut.",
                        command=command,
                    )
                )
                continue
            current_browser_state = BrowserSessionState()
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser close-tab shortcut.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_switch_tab":
            command = _browser_switch_tab_command(
                action.resolved_target or action.target,
                platform_name=platform_key,
                browser_app=current_browser_state.browser_app,
            )
            if not command:
                residuals.append(f"browser_switch_tab_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Switching browser tabs is not wired for platform {platform_key}.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the switch-tab shortcut.",
                        command=command,
                    )
                )
                continue
            current_browser_state = BrowserSessionState()
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Sent browser switch-tab shortcut ({action.resolved_target or action.target}).",
                    command=command,
                )
            )
            continue
        if action.kind == "open_search_result":
            if not _has_result_resolution_context(current_browser_state):
                residuals.append("browser_state_missing_search_results")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no saved browser search state to continue from.",
                    )
                )
                continue
            try:
                result_index = max(int(action.resolved_target or action.target), 1)
            except ValueError:
                result_index = 1
            result_urls = list(current_browser_state.result_urls or [])
            result_cards = [dict(item) for item in list(current_browser_state.result_cards or []) if isinstance(item, dict)]
            if not result_urls and result_cards:
                result_urls = [str(card.get("url") or "").strip() for card in result_cards if str(card.get("url") or "").strip()]
            if len(result_urls) < result_index:
                if current_browser_state.search_engine and current_browser_state.search_query:
                    try:
                        result_cards = _fetch_search_result_cards(
                            current_browser_state.search_engine,
                            current_browser_state.search_query,
                            limit=max(result_index, 5),
                        )
                        result_urls = [str(card.get("url") or "").strip() for card in result_cards if str(card.get("url") or "").strip()]
                        if len(result_urls) < result_index:
                            result_urls = _fetch_search_result_urls(
                                current_browser_state.search_engine,
                                current_browser_state.search_query,
                                limit=max(result_index, 5),
                            )
                            result_cards = _fallback_cards_from_urls(result_urls)
                    except Exception as exc:
                        residuals.append("search_result_fetch_failed")
                        records.append(
                            TerminalExecutionRecord(
                                kind=action.kind,
                                target=action.target,
                                status="failed",
                                message=f"Could not resolve browser search results: {str(exc).strip() or 'unknown error'}.",
                            )
                        )
                        continue
            if len(result_urls) < result_index:
                residuals.append("search_result_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Could not find search result #{result_index} for {current_browser_state.search_engine}.",
                    )
                )
                continue
            target_url = result_urls[result_index - 1]
            chosen_card = _resolve_card_by_index(
                BrowserSessionState(
                    current_url=current_browser_state.current_url,
                    page_kind=current_browser_state.page_kind,
                    search_engine=current_browser_state.search_engine,
                    search_query=current_browser_state.search_query,
                    result_urls=result_urls,
                    result_cards=result_cards,
                ),
                result_index,
            )
            command = _open_in_browser(target_url, platform_name=platform_key)
            if not command:
                residuals.append(f"open_command_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"No opener command is configured for platform {platform_key}.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            current_browser_state = _browser_state_for_url(
                target_url,
                browser_app=current_browser_state.browser_app,
                search_engine=current_browser_state.search_engine,
                search_query=current_browser_state.search_query,
                result_urls=result_urls,
                result_cards=result_cards,
                subject_title=str(chosen_card.get("title") or "").strip(),
                subject_url=str(chosen_card.get("url") or target_url).strip(),
                subject_summary=str(chosen_card.get("summary") or "").strip(),
                research_subject_title=current_browser_state.research_subject_title,
                research_subject_url=current_browser_state.research_subject_url,
                research_subject_summary=current_browser_state.research_subject_summary,
                evidence_items=current_browser_state.evidence_items,
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Opened result #{result_index}: {target_url}",
                    command=command,
                )
            )
            continue
        if action.kind in {"browser_click_index", "browser_click_text"}:
            card: dict[str, Any] = {}
            if action.kind == "browser_click_index":
                try:
                    card = _resolve_card_by_index(current_browser_state, max(int(action.resolved_target or action.target), 1))
                except ValueError:
                    card = {}
            else:
                card = _resolve_card_by_text(current_browser_state, action.resolved_target or action.target)
            target_url = str(card.get("url") or "").strip()
            if not target_url:
                residuals.append("click_target_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not resolve a clickable card for that target in the current browser state.",
                    )
                )
                continue
            command = _open_in_browser(target_url, platform_name=platform_key)
            if not command:
                residuals.append(f"open_command_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"No opener command is configured for platform {platform_key}.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            current_browser_state = _browser_state_for_url(
                target_url,
                browser_app=current_browser_state.browser_app,
                subject_title=str(card.get("title") or "").strip(),
                subject_url=str(card.get("url") or target_url).strip(),
                subject_summary=str(card.get("summary") or "").strip(),
                research_subject_title=current_browser_state.research_subject_title,
                research_subject_url=current_browser_state.research_subject_url,
                research_subject_summary=current_browser_state.research_subject_summary,
                evidence_items=current_browser_state.evidence_items,
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Opened {card.get('title') or target_url}.",
                    command=command,
                    details=card,
                )
            )
            continue
        if action.kind in {"browser_read_page", "browser_extract_page"}:
            if not current_browser_state.current_url:
                residuals.append("browser_state_missing_current_url")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no current browser page to read.",
                    )
                )
                continue
            try:
                html = _fetch_page_html(current_browser_state.current_url)
                details = _extract_page_snapshot(current_browser_state, html)
            except Exception as exc:
                residuals.append("browser_page_fetch_failed")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Could not read the current browser page: {str(exc).strip() or 'unknown error'}.",
                    )
                )
                continue
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=(
                        _browser_read_message(details, current_browser_state.current_url)
                        if action.kind == "browser_read_page"
                        else f"Extracted current page: {str(details.get('summary') or details.get('title') or current_browser_state.current_url).strip()}"
                    ),
                    details=details,
                )
            )
            current_browser_state = _append_browser_evidence(
                current_browser_state,
                _evidence_item_from_details(current_browser_state, details),
            )
            continue
        if action.kind == "browser_extract_cards":
            if not _has_result_resolution_context(current_browser_state):
                residuals.append("browser_state_missing_search_results")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no active search-results page to extract cards from.",
                    )
                )
                continue
            cards = _cached_cards(current_browser_state)
            if not cards and current_browser_state.search_engine and current_browser_state.search_query:
                try:
                    cards = _fetch_search_result_cards(current_browser_state.search_engine, current_browser_state.search_query, limit=5)
                except Exception:
                    cards = []
            current_browser_state = BrowserSessionState(
                current_url=current_browser_state.current_url,
                page_kind=current_browser_state.page_kind,
                browser_app=current_browser_state.browser_app,
                search_engine=current_browser_state.search_engine,
                search_query=current_browser_state.search_query,
                result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
                result_cards=cards,
                subject_title=current_browser_state.subject_title,
                subject_url=current_browser_state.subject_url,
                subject_summary=current_browser_state.subject_summary,
                research_subject_title=current_browser_state.research_subject_title,
                research_subject_url=current_browser_state.research_subject_url,
                research_subject_summary=current_browser_state.research_subject_summary,
                evidence_items=_clone_evidence_items(current_browser_state.evidence_items),
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Extracted {len(cards)} source cards from the current browser context.",
                    details={"cards": cards},
                )
            )
            continue
        if action.kind == "browser_rank_cards":
            if not _has_result_resolution_context(current_browser_state):
                residuals.append("browser_state_missing_search_results")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no active search-results page to rank.",
                    )
                )
                continue
            cards = _cached_cards(current_browser_state)
            if not cards and current_browser_state.search_engine and current_browser_state.search_query:
                try:
                    cards = _fetch_search_result_cards(current_browser_state.search_engine, current_browser_state.search_query, limit=5)
                except Exception:
                    cards = []
            if not cards:
                residuals.append("browser_cards_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There are no cached browser cards to rank yet.",
                    )
                )
                continue
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            ranked = _rank_cards_against_goal(cards, goal)
            best = dict(ranked[0]) if ranked else {}
            current_browser_state = _browser_state_with_subject(current_browser_state, best)
            current_browser_state = _browser_state_with_research_subject(current_browser_state, best)
            current_browser_state = _append_browser_evidence(
                current_browser_state,
                _evidence_item_from_subject(best, source_kind="repo_page", meta="github repo"),
            )
            message = (
                f"Best match for \"{goal}\": {str(best.get('title') or best.get('url') or 'none').strip()}"
                if goal
                else f"Best available result: {str(best.get('title') or best.get('url') or 'none').strip()}"
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=message,
                    details={
                        "goal": goal,
                        "best_title": str(best.get("title") or "").strip(),
                        "best_url": str(best.get("url") or "").strip(),
                        "best_score": float(best.get("score") or 0.0),
                        "best_matching_terms": list(best.get("matching_terms") or []),
                        "ranking": ranked,
                    },
                )
            )
            continue
        if action.kind == "browser_compare_cards":
            if not _has_result_resolution_context(current_browser_state):
                residuals.append("browser_state_missing_search_results")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no active search-results page to compare cards from.",
                    )
                )
                continue
            cards = _cached_cards(current_browser_state)
            if not cards and current_browser_state.search_engine and current_browser_state.search_query:
                try:
                    cards = _fetch_search_result_cards(current_browser_state.search_engine, current_browser_state.search_query, limit=5)
                except Exception:
                    cards = []
            if not cards:
                residuals.append("browser_cards_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There are no cached browser cards to compare yet.",
                    )
                )
                continue
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            requested_indexes = [int(item) for item in list(note_payload.get("indexes") or []) if str(item).isdigit()]
            if not requested_indexes:
                requested_indexes = [int(part) for part in re.findall(r"\d+", action.resolved_target or action.target or "")][:2]
            if not requested_indexes:
                requested_indexes = [1, 2]
            selected_cards = []
            for index in requested_indexes[:2]:
                card = _resolve_card_by_index(current_browser_state, index)
                if card:
                    selected_cards.append(card)
            if len(selected_cards) < 2:
                residuals.append("compare_target_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not resolve two cached cards to compare.",
                    )
                )
                continue
            comparison = _compare_cards_against_goal(selected_cards, goal)
            winner_subject = {
                "title": comparison.get("winner_title"),
                "url": comparison.get("winner_url"),
                "summary": "",
            }
            current_browser_state = _browser_state_with_subject(current_browser_state, winner_subject)
            current_browser_state = _browser_state_with_research_subject(current_browser_state, winner_subject)
            current_browser_state = _append_browser_evidence(
                current_browser_state,
                _evidence_item_from_subject(winner_subject, source_kind="repo_page", meta="github repo"),
            )
            winner = str(comparison.get("winner_title") or comparison.get("winner_url") or "none").strip()
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Comparison winner for \"{goal}\": {winner}" if goal else f"Comparison winner: {winner}",
                    details=comparison,
                )
            )
            continue
        if action.kind == "browser_search_subject":
            note_payload = _decode_action_note(action.note)
            engine = str(note_payload.get("engine") or action.resolved_target or action.target or "").strip()
            if current_browser_state.page_kind == "repo_page":
                current_browser_state = _append_browser_evidence(
                    current_browser_state,
                    _evidence_item_from_subject(
                        _research_subject_from_browser_state(current_browser_state),
                        source_kind="repo_page",
                        fallback_url=current_browser_state.current_url,
                        meta="github repo",
                    ),
                )
            subject = _research_subject_from_browser_state(current_browser_state)
            subject_query = _research_subject_query_from_browser_state(current_browser_state)
            subject_title = str(subject.get("title") or "").strip()
            subject_url = str(subject.get("url") or "").strip()
            if not engine:
                residuals.append("browser_subject_search_engine_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="No target search engine was provided for the active subject search.",
                    )
                )
                continue
            if not subject_query:
                residuals.append("browser_subject_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no active subject in browser state to search for yet.",
                    )
                )
                continue
            target_url = _search_url(engine, subject_query)
            if not target_url:
                residuals.append("browser_subject_search_url_invalid")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Could not build a {engine} search URL for the active subject.",
                    )
                )
                continue
            command = _open_in_browser(target_url, platform_name=platform_key)
            if not command:
                residuals.append(f"open_command_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"No opener command is configured for platform {platform_key}.",
                    )
                )
                continue
            result_cards: list[dict[str, Any]] = []
            result_urls: list[str] = []
            try:
                result_cards = _fetch_search_result_cards(engine, subject_query, limit=5)
                result_urls = [str(card.get("url") or "").strip() for card in result_cards if str(card.get("url") or "").strip()]
                if not result_urls:
                    result_urls = _fetch_search_result_urls(engine, subject_query, limit=5)
                    result_cards = _fallback_cards_from_urls(result_urls)
            except Exception:
                result_cards = []
                result_urls = []
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            current_browser_state = _browser_state_for_url(
                target_url,
                search_engine=engine,
                search_query=subject_query,
                result_urls=result_urls,
                result_cards=result_cards,
                subject_title=current_browser_state.subject_title,
                subject_url=current_browser_state.subject_url,
                subject_summary=current_browser_state.subject_summary,
                research_subject_title=subject_title,
                research_subject_url=subject_url,
                research_subject_summary=str(subject.get("summary") or "").strip(),
                evidence_items=current_browser_state.evidence_items,
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Searched {engine} for {subject_title or subject_query}.",
                    command=command,
                    details={
                        "subject_title": subject_title,
                        "subject_url": subject_url,
                        "search_engine": engine,
                        "search_query": subject_query,
                        "search_url": target_url,
                    },
                )
            )
            continue
        if action.kind == "browser_retry_subject_result":
            cards = _cached_cards(current_browser_state)
            if not cards:
                residuals.append("browser_cards_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There are no cached results to recover from yet.",
                    )
                )
                continue
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or "").strip()
            if not goal:
                goal = _research_subject_query_from_browser_state(current_browser_state) or current_browser_state.search_query or plan.prompt
            selected = _select_better_cached_result(current_browser_state, goal)
            target_url = str(selected.get("url") or "").strip()
            if not target_url:
                residuals.append("browser_retry_result_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not find a stronger cached alternative result to open.",
                    )
                )
                continue
            command = _open_in_browser(target_url, platform_name=platform_key)
            if not command:
                residuals.append(f"open_command_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"No opener command is configured for platform {platform_key}.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            current_browser_state = _browser_state_for_url(
                target_url,
                search_engine=current_browser_state.search_engine,
                search_query=current_browser_state.search_query,
                result_urls=[str(card.get("url") or "").strip() for card in cards if str(card.get("url") or "").strip()],
                result_cards=cards,
                subject_title=str(selected.get("title") or "").strip(),
                subject_url=str(selected.get("url") or target_url).strip(),
                subject_summary=str(selected.get("summary") or "").strip(),
                research_subject_title=current_browser_state.research_subject_title,
                research_subject_url=current_browser_state.research_subject_url,
                research_subject_summary=current_browser_state.research_subject_summary,
                evidence_items=current_browser_state.evidence_items,
            )
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Recovered to a stronger result: {str(selected.get('title') or target_url).strip()}",
                    command=command,
                    details={
                        "goal": goal,
                        "selected_index": int(selected.get("index") or 0),
                        "selected_title": str(selected.get("title") or "").strip(),
                        "selected_url": target_url,
                        "ranking": list(selected.get("ranking") or []),
                    },
                )
            )
            continue
        if action.kind == "browser_synthesize_evidence":
            if not current_browser_state.evidence_items:
                residuals.append("browser_evidence_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="There is no accumulated browser evidence to synthesize yet.",
                    )
                )
                continue
            note_payload = _decode_action_note(action.note)
            goal = str(note_payload.get("goal") or plan.prompt or "").strip()
            synthesis = _synthesize_browser_evidence(
                current_browser_state.evidence_items,
                goal,
                _research_subject_from_browser_state(current_browser_state),
            )
            if not synthesis:
                residuals.append("browser_evidence_missing")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Memla could not resolve a best source from the current evidence set.",
                    )
                )
                continue
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=(
                        f"Best source for \"{goal}\": {str(synthesis.get('best_source_title') or 'unknown').strip()}"
                        if goal
                        else f"Best source: {str(synthesis.get('best_source_title') or 'unknown').strip()}"
                    ),
                    details=synthesis,
                )
            )
            current_browser_state = _browser_state_copy(
                current_browser_state,
                subject_title=str(synthesis.get("best_source_title") or current_browser_state.subject_title).strip(),
                subject_url=str(synthesis.get("best_source_url") or current_browser_state.subject_url).strip(),
                subject_summary=str(synthesis.get("synthesis") or current_browser_state.subject_summary).strip(),
            )
            continue
        if action.kind == "list_directory":
            target = Path(action.resolved_target or action.target).expanduser()
            if not target.exists() or not target.is_dir():
                residuals.append(f"path_not_found:{target}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"{target} is not an existing directory.",
                    )
                )
                continue
            entries = [item.name + ("/" if item.is_dir() else "") for item in sorted(target.iterdir(), key=lambda item: item.name.lower())[:20]]
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"{target}: {', '.join(entries) if entries else '(empty)'}",
                )
            )
            continue
        if action.kind == "system_info":
            record = _system_info_record(action.resolved_target or action.target)
            if record.status != "ok":
                residuals.append(f"system_info_unavailable:{action.resolved_target or action.target}")
            records.append(record)
            continue
        if action.kind == "browser_back":
            if platform_key != "linux":
                if platform_key == "win32":
                    command = _windows_browser_sendkeys_command(keys=["%{LEFT}"], browser_app=current_browser_state.browser_app)
                    if not command:
                        residuals.append(f"browser_back_unavailable:{platform_key}")
                        records.append(
                            TerminalExecutionRecord(
                                kind=action.kind,
                                target=action.target,
                                status="failed",
                                message="Browser back is unavailable on this platform.",
                            )
                        )
                        continue
                    exit_code = _run_command(command, wait=True)
                    if exit_code not in (None, 0):
                        residuals.append("browser_focus_unavailable")
                        records.append(
                            TerminalExecutionRecord(
                                kind=action.kind,
                                target=action.target,
                                status="failed",
                                message="Could not activate a browser window safely, so Memla skipped the back shortcut.",
                                command=command,
                            )
                        )
                        continue
                    records.append(
                        TerminalExecutionRecord(
                            kind=action.kind,
                            target=action.target,
                            status="ok",
                            message="Sent browser back shortcut.",
                            command=command,
                        )
                    )
                    continue
                residuals.append(f"browser_back_unsupported:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message=f"Browser back is only wired for linux right now.",
                    )
                )
                continue
            xdotool = shutil.which("xdotool")
            if not xdotool:
                residuals.append("browser_back_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="xdotool is not installed, so browser back is unavailable.",
                    )
                )
                continue
            command = [xdotool, "key", "alt+Left"]
            _run_command(command)
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser back shortcut.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_forward":
            command = _browser_forward_command(platform_name=platform_key, browser_app=current_browser_state.browser_app)
            if not command:
                residuals.append(f"browser_forward_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Browser forward is unavailable on this platform.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the forward shortcut.",
                        command=command,
                    )
                )
                continue
            current_browser_state = BrowserSessionState()
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser forward shortcut.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_scroll":
            command = _browser_scroll_command(
                action.resolved_target or action.target,
                platform_name=platform_key,
                browser_app=current_browser_state.browser_app,
            )
            if not command:
                residuals.append(f"browser_scroll_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Browser scroll is unavailable on this platform.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the scroll shortcut.",
                        command=command,
                    )
                )
                continue
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Scrolled browser {action.resolved_target or action.target}.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_type_text":
            command = _browser_type_text_command(
                action.resolved_target or action.target,
                platform_name=platform_key,
                browser_app=current_browser_state.browser_app,
            )
            if not command:
                residuals.append(f"browser_type_text_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Typing into the active browser is unavailable on this platform.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped typing instead of pasting into the terminal.",
                        command=command,
                    )
                )
                continue
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Typed text into the active browser: {action.resolved_target or action.target}",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_submit":
            command = _browser_submit_command(platform_name=platform_key, browser_app=current_browser_state.browser_app)
            if not command:
                residuals.append(f"browser_submit_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Submitting the active browser form is unavailable on this platform.",
                    )
                )
                continue
            exit_code = _run_command(command, wait=platform_key == "win32")
            if platform_key == "win32" and exit_code not in (None, 0):
                residuals.append("browser_focus_unavailable")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Could not activate a browser window safely, so Memla skipped the submit shortcut.",
                        command=command,
                    )
                )
                continue
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser submit/enter shortcut.",
                    command=command,
                )
            )
            continue
        if action.kind == "browser_wait":
            try:
                seconds = max(float(action.resolved_target or action.target), 0.0)
            except ValueError:
                seconds = 1.0
            time.sleep(min(seconds, 10.0))
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Waited {round(min(seconds, 10.0), 2)} seconds.",
                )
            )
            continue
        if action.kind == "browser_screenshot":
            screenshot_path = terminal_browser_state_path().parent / f"browser_screenshot_{int(time.time())}.png"
            command = _browser_screenshot_command(screenshot_path, platform_name=platform_key)
            if not command:
                residuals.append(f"browser_screenshot_unavailable:{platform_key}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Screenshot capture is unavailable on this platform.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).wait(timeout=8)
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message=f"Captured a screenshot to {screenshot_path}.",
                    command=command,
                    details={"path": str(screenshot_path)},
                )
            )
            continue
        if action.kind in {"browser_media_pause", "browser_media_play"}:
            command = _browser_media_command(action.kind, platform_name=platform_key)
            if not command:
                residuals.append(f"browser_media_unavailable:{action.kind}")
                records.append(
                    TerminalExecutionRecord(
                        kind=action.kind,
                        target=action.target,
                        status="failed",
                        message="Media controls require playerctl on linux.",
                    )
                )
                continue
            subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            records.append(
                TerminalExecutionRecord(
                    kind=action.kind,
                    target=action.target,
                    status="ok",
                    message="Sent browser media control.",
                    command=command,
                )
            )
            continue
        residuals.append(f"unsupported_action:{action.kind}")
        records.append(
            TerminalExecutionRecord(
                kind=action.kind,
                target=action.target,
                status="failed",
                message=f"Unsupported action kind: {action.kind}",
            )
        )
    ok = bool(records) and all(record.status == "ok" for record in records)
    if current_browser_state.current_url or current_browser_state.search_engine or current_browser_state.page_kind:
        try:
            save_browser_session_state(current_browser_state, state_path)
        except OSError:
            residuals.append("browser_state_persist_failed")
    if ok:
        try:
            remember_language_compile(
                prompt=plan.prompt,
                browser_state=initial_browser_state,
                plan=plan,
            )
        except OSError:
            residuals.append("language_memory_persist_failed")
        try:
            _promote_language_rules(
                prompt=plan.prompt,
                browser_state=initial_browser_state,
                plan=plan,
            )
        except OSError:
            residuals.append("language_rule_persist_failed")
    if plan.source in {"language_model", "language_memory", "language_rule"} and plan.actions:
        try:
            adjudicate_memory_trace(
                prompt=plan.prompt,
                normalized_prompt=_intent_text(plan.prompt),
                tokens=_language_prompt_tokens(plan.prompt),
                context_profile=_language_context_profile(initial_browser_state),
                action_signatures=[_action_signature(action) for action in plan.actions],
                source=plan.source,
                success=ok,
                path=_terminal_memory_ontology_path_for_state(state_path),
                canonical_clauses=_canonical_clauses_from_actions(plan.actions),
            )
        except OSError:
            residuals.append("memory_ontology_persist_failed")
    if plan.actions:
        try:
            _record_autonomy_plan_memory(
                plan=plan,
                browser_state=initial_browser_state,
                ok=ok,
                state_path=state_path,
            )
        except OSError:
            residuals.append("autonomy_memory_ontology_persist_failed")
    return TerminalExecutionResult(
        prompt=plan.prompt,
        plan_source=plan.source,
        ok=ok,
        records=records,
        residual_constraints=residuals,
        browser_state=asdict(current_browser_state),
    )


def _terminal_available_transmutations(browser_state: BrowserSessionState) -> list[str]:
    actions: list[str] = []
    if browser_state.current_url:
        actions.extend(
            [
                "browser_read_page",
                "browser_extract_page",
                "browser_new_tab",
                "browser_close_tab",
                "browser_switch_tab",
                "browser_back",
                "browser_forward",
                "browser_scroll",
                "browser_type_text",
                "browser_submit",
                "browser_wait",
                "browser_screenshot",
            ]
        )
        if _cached_cards(browser_state):
            actions.append("browser_retry_subject_result")
        if browser_state.evidence_items:
            actions.append("browser_synthesize_evidence")
    if _has_result_resolution_context(browser_state):
        actions.extend(
            [
                "open_search_result",
                "browser_click_index",
                "browser_click_text",
                "browser_extract_cards",
                "browser_rank_cards",
                "browser_compare_cards",
            ]
        )
    if browser_state.subject_title or browser_state.research_subject_title or browser_state.page_kind == "repo_page":
        actions.append("browser_search_subject")
    if browser_state.page_kind == "video_page":
        actions.extend(["browser_media_pause", "browser_media_play"])
    return actions


def _terminal_constraints_snapshot(prompt: str, browser_state: BrowserSessionState) -> dict[str, Any]:
    return {
        "prompt": prompt,
        "intent_text": _intent_text(prompt),
        "current_url": browser_state.current_url,
        "page_kind": browser_state.page_kind,
        "search_engine": browser_state.search_engine,
        "search_query": browser_state.search_query,
        "cached_result_count": len(browser_state.result_urls or []),
        "cached_card_count": len(browser_state.result_cards or []),
        "subject_title": browser_state.subject_title,
        "subject_url": browser_state.subject_url,
        "research_subject_title": browser_state.research_subject_title,
        "research_subject_url": browser_state.research_subject_url,
        "evidence_count": len(browser_state.evidence_items or []),
        "available_transmutations": _terminal_available_transmutations(browser_state),
    }


def _plan_signature(plan: TerminalPlan) -> tuple[str, ...]:
    return tuple(_action_signature(action) for action in plan.actions)


def _plan_label(plan: TerminalPlan) -> str:
    if not plan.actions:
        return "No actionable transmutation"
    if len(plan.actions) > 1:
        labels = [
            _plan_label(TerminalPlan(prompt=plan.prompt, source=plan.source, actions=[action]))
            for action in plan.actions[:4]
        ]
        return " + ".join(labels)
    action = plan.actions[0]
    target = str(action.resolved_target or action.target).strip()
    if action.kind == "launch_app":
        return f"Launch {target}"
    if action.kind == "open_url":
        note = _decode_action_note(action.note)
        engine = str(note.get("search_engine") or "").strip()
        query = str(note.get("search_query") or "").strip()
        if engine and query:
            return f"Open {engine} search for \"{query}\""
        return f"Open {target}"
    if action.kind == "browser_new_tab":
        return "Open a new tab"
    if action.kind == "browser_close_tab":
        return "Close the current tab"
    if action.kind == "browser_switch_tab":
        target_text = target or "next"
        return f"Switch to {target_text} tab"
    if action.kind == "open_search_result":
        return f"Open search result #{target or '1'}"
    if action.kind == "browser_click_index":
        return f"Click card #{target or '1'}"
    if action.kind == "browser_click_text":
        return f"Click \"{target}\""
    if action.kind == "browser_answer_query":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or target).strip()
        return f"Answer the web question \"{goal}\""
    if action.kind == "browser_read_page":
        return "Read the current page"
    if action.kind == "browser_extract_page":
        return "Extract the current page"
    if action.kind == "browser_extract_cards":
        return "Extract visible result cards"
    if action.kind == "browser_rank_cards":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or "").strip()
        return f"Rank current cards for \"{goal}\"" if goal else "Rank current cards"
    if action.kind == "browser_compare_cards":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or "").strip()
        return f"Compare selected cards for \"{goal}\"" if goal else "Compare selected cards"
    if action.kind == "browser_search_subject":
        engine = target or str(_decode_action_note(action.note).get("engine") or "google").strip()
        return f"Search {engine} for the active subject"
    if action.kind == "browser_retry_subject_result":
        return "Recover to a better result"
    if action.kind == "browser_synthesize_evidence":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or "").strip()
        return f"Synthesize sources for \"{goal}\"" if goal else "Synthesize the current evidence"
    if action.kind == "browser_back":
        return "Go back"
    if action.kind == "browser_forward":
        return "Go forward"
    if action.kind == "browser_scroll":
        return f"Scroll {target or 'down'}"
    if action.kind == "browser_type_text":
        preview = target if len(target) <= 24 else target[:21] + "..."
        return f"Type \"{preview}\""
    if action.kind == "browser_submit":
        return "Submit the current form"
    if action.kind == "browser_wait":
        return f"Wait {target or '1'} seconds"
    if action.kind == "browser_screenshot":
        return "Take a screenshot"
    if action.kind == "browser_media_pause":
        return "Pause media"
    if action.kind == "browser_media_play":
        return "Play media"
    if action.kind == "open_path":
        return f"Open {target}"
    if action.kind == "list_directory":
        return f"List {target}"
    if action.kind == "system_info":
        return f"Check {target}"
    return f"{action.kind}: {target}"


def _preview_label_for_url(url: str) -> str:
    clean = str(url or "").strip()
    if not clean:
        return ""
    repo_match = re.match(r"^https?://github\.com/([^/\s]+)/([^/\s?#]+)", clean, flags=re.IGNORECASE)
    if repo_match:
        return f"{repo_match.group(1)}/{repo_match.group(2)}"
    if "youtube.com/watch" in clean.lower():
        return f"YouTube video ({clean})"
    if "reddit.com/" in clean.lower():
        return f"Reddit post ({clean})"
    return clean


def _preview_result_url(browser_state: BrowserSessionState, index: int) -> str:
    result_urls = list(browser_state.result_urls or [])
    return result_urls[index - 1] if len(result_urls) >= index else ""


def _read_page_expected_fields(browser_state: BrowserSessionState) -> list[str]:
    if browser_state.page_kind == "repo_page":
        return ["repo", "description", "stars", "forks", "language", "topics"]
    if browser_state.page_kind == "video_page":
        return ["title", "summary", "channel", "url"]
    if browser_state.page_kind == "post_page":
        return ["title", "summary", "url"]
    if browser_state.page_kind == "search_results":
        return ["title", "summary", "url"]
    return ["title", "summary", "url"]


def _candidate_preview_from_plan(plan: TerminalPlan, browser_state: BrowserSessionState) -> tuple[str, str, list[str]]:
    if not plan.actions:
        return "", "", []
    if len(plan.actions) > 1:
        first, second = plan.actions[0], plan.actions[1]
        third = plan.actions[2] if len(plan.actions) > 2 else None
        fourth = plan.actions[3] if len(plan.actions) > 3 else None
        if first.kind == "browser_new_tab" and second.kind == "open_url":
            note = _decode_action_note(second.note)
            engine = str(note.get("search_engine") or "").strip()
            query = str(note.get("search_query") or "").strip()
            if engine and query:
                return (
                    f"Active browser -> {engine.title()} search for \"{query}\"",
                    "Open a fresh tab, then navigate it to the requested search results.",
                    [],
                )
        if (
            first.kind in {"browser_rank_cards", "browser_compare_cards"}
            and second.kind == "browser_search_subject"
            and third
            and third.kind == "open_search_result"
            and fourth
            and fourth.kind == "browser_read_page"
        ):
            note = _decode_action_note(second.note)
            engine = str(note.get("engine") or second.resolved_target or second.target or "google").strip()
            index = str(third.resolved_target or third.target or "1").strip()
            return (
                f"Best subject -> {engine.title()} -> result #{index} -> read",
                f"Judge the strongest current subject, search {engine.title()} for it, open result #{index}, then read the resulting page.",
                ["subject_title", "search_engine", "search_query", "title", "summary", "url"],
            )
        if first.kind == "browser_search_subject" and second.kind == "open_search_result" and third and third.kind == "browser_read_page":
            note = _decode_action_note(first.note)
            engine = str(note.get("engine") or first.resolved_target or first.target or "google").strip()
            index = str(second.resolved_target or second.target or "1").strip()
            subject = _subject_from_browser_state(browser_state)
            subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
            return (
                f"{subject_title} -> {engine.title()} -> result #{index} -> read",
                f"Search {engine.title()} for the active subject, open result #{index}, then read the resulting page.",
                ["subject_title", "search_engine", "search_query", "title", "summary", "url"],
            )
        if (
            first.kind == "browser_search_subject"
            and second.kind == "open_search_result"
            and third
            and third.kind == "browser_read_page"
            and fourth
            and fourth.kind == "browser_retry_subject_result"
        ):
            note = _decode_action_note(first.note)
            engine = str(note.get("engine") or first.resolved_target or first.target or "google").strip()
            subject = _research_subject_from_browser_state(browser_state) or _subject_from_browser_state(browser_state)
            subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
            return (
                f"{subject_title} -> {engine.title()} -> recover",
                f"Search {engine.title()} for the active subject, inspect the first result, then reopen a stronger cached result if needed.",
                ["research_subject_title", "search_engine", "search_query", "subject_title", "current_url"],
            )
        if any(action.kind == "browser_synthesize_evidence" for action in plan.actions):
            synth_action = next(action for action in plan.actions if action.kind == "browser_synthesize_evidence")
            note = _decode_action_note(synth_action.note)
            goal = str(note.get("goal") or plan.prompt or "").strip()
            return (
                "Cross-source evidence -> answer",
                f"Carry the subject across multiple sources, then choose the best source for \"{goal}\" and synthesize a grounded answer.",
                ["best_source_title", "best_source_kind", "source_count", "synthesis"],
            )
        if first.kind in {"browser_rank_cards", "browser_compare_cards"} and second.kind == "browser_search_subject" and third and third.kind == "open_search_result":
            note = _decode_action_note(second.note)
            engine = str(note.get("engine") or second.resolved_target or second.target or "google").strip()
            index = str(third.resolved_target or third.target or "1").strip()
            return (
                f"Best subject -> {engine.title()} -> result #{index}",
                f"Judge the strongest current subject, search {engine.title()} for it, then open result #{index}.",
                ["subject_title", "search_engine", "search_query", "current_url"],
            )
        if first.kind == "browser_search_subject" and second.kind == "open_search_result":
            note = _decode_action_note(first.note)
            engine = str(note.get("engine") or first.resolved_target or first.target or "google").strip()
            index = str(second.resolved_target or second.target or "1").strip()
            subject = _subject_from_browser_state(browser_state)
            subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
            return (
                f"{subject_title} -> {engine.title()} -> result #{index}",
                f"Search {engine.title()} for the active subject, then open result #{index}.",
                ["subject_title", "search_engine", "search_query", "current_url"],
            )
        if first.kind in {"browser_rank_cards", "browser_compare_cards"} and second.kind == "browser_search_subject":
            note = _decode_action_note(second.note)
            engine = str(note.get("engine") or second.resolved_target or second.target or "google").strip()
            subject = _subject_from_browser_state(browser_state)
            subject_title = str(subject.get("title") or "best match").strip()
            return (
                f"{subject_title} -> {engine.title()}",
                f"Judge the strongest current subject, then search {engine.title()} for related coverage.",
                ["subject_title", "search_engine", "search_query"],
            )
        labels = [_plan_label(TerminalPlan(prompt=plan.prompt, source=plan.source, actions=[action])) for action in plan.actions[:4]]
        return ", then ".join(labels), "Run the proposed transmutations in sequence.", []
    action = plan.actions[0]
    target = str(action.resolved_target or action.target).strip()
    if action.kind == "open_url":
        note = _decode_action_note(action.note)
        engine = str(note.get("search_engine") or "").strip()
        query = str(note.get("search_query") or "").strip()
        if engine and query:
            return (
                f"{engine.title()} search results for \"{query}\"",
                "Open a fresh browser search-results page for this query.",
                [],
            )
        return target, "Open the target URL in the browser.", []
    if action.kind == "browser_new_tab":
        return "Active browser", "Open a fresh blank tab in the current browser.", []
    if action.kind == "browser_close_tab":
        return browser_state.current_url or "Active browser", "Close the active browser tab.", []
    if action.kind == "browser_switch_tab":
        return "Active browser", f"Switch the active browser tab to {target or 'next'}.", []
    if action.kind == "open_search_result":
        try:
            index = max(int(target or "1"), 1)
        except ValueError:
            index = 1
        target_url = _preview_result_url(browser_state, index)
        target_preview = _preview_label_for_url(target_url) or f"Search result #{index}"
        search_engine = str(browser_state.search_engine or "").strip()
        outcome = "Open the selected search result in the browser."
        if search_engine:
            outcome = f"Open result #{index} from the current {search_engine} search."
        return target_preview, outcome, []
    if action.kind == "browser_click_index":
        try:
            index = max(int(target or "1"), 1)
        except ValueError:
            index = 1
        card = _resolve_card_by_index(browser_state, index)
        target_preview = str(card.get("title") or card.get("url") or f"Card #{index}").strip()
        return target_preview, f"Open card #{index} from the cached browser results.", []
    if action.kind == "browser_click_text":
        card = _resolve_card_by_text(browser_state, target)
        target_preview = str(card.get("title") or target or "matching card").strip()
        return target_preview, f"Open the visible card that matches \"{target}\".", []
    if action.kind == "browser_answer_query":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or target or plan.prompt).strip()
        query = str(note.get("query") or target or goal).strip()
        return (
            goal or query or "web question",
            f"Search the live web for \"{query}\" and return the strongest bounded answer with a source.",
            ["answer", "best_source_title", "best_source_url", "top_results"],
        )
    if action.kind == "browser_read_page":
        page_kind = str(browser_state.page_kind or "web_page").strip()
        current_target = browser_state.current_url or "current page"
        target_preview = _preview_label_for_url(current_target) or current_target
        if page_kind == "repo_page":
            outcome = "Extract a structured repo summary from the current GitHub repository page."
        elif page_kind == "video_page":
            outcome = "Extract structured metadata from the current video page."
        else:
            outcome = "Read the current page and build a concise structured summary."
        return target_preview, outcome, _read_page_expected_fields(browser_state)
    if action.kind == "browser_extract_page":
        current_target = browser_state.current_url or "current page"
        target_preview = _preview_label_for_url(current_target) or current_target
        return target_preview, "Extract structured fields from the current browser page.", _read_page_expected_fields(browser_state)
    if action.kind == "browser_extract_cards":
        cards = _cached_cards(browser_state)
        return (
            f"{len(cards)} cached result cards" if cards else "current search results",
            "Extract the visible result cards from the current search page.",
            ["cards[index]", "cards.title", "cards.url", "cards.summary"],
        )
    if action.kind == "browser_rank_cards":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or plan.prompt or "").strip()
        cards = _cached_cards(browser_state)
        return (
            f"{len(cards)} cached result cards" if cards else "current search results",
            f"Rank the current result cards against \"{goal}\"." if goal else "Rank the current result cards against the current goal.",
            ["goal", "best_title", "best_url", "best_score", "ranking"],
        )
    if action.kind == "browser_compare_cards":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or plan.prompt or "").strip()
        indexes = [int(item) for item in list(note.get("indexes") or []) if str(item).isdigit()]
        if not indexes:
            indexes = [int(part) for part in re.findall(r"\d+", target)][:2]
        label = " vs ".join(f"card #{index}" for index in indexes[:2]) if indexes else "selected cards"
        return (
            label,
            f"Compare the selected cards against \"{goal}\" and return the stronger match." if goal else "Compare the selected cards and return the stronger match.",
            ["goal", "winner_title", "winner_score", "comparison"],
        )
    if action.kind == "browser_search_subject":
        note = _decode_action_note(action.note)
        engine = str(note.get("engine") or target or "google").strip()
        subject = _research_subject_from_browser_state(browser_state)
        subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
        return (
            f"{subject_title} -> {engine.title()}",
            f"Search {engine.title()} for content about the active subject.",
            ["subject_title", "subject_url", "search_engine", "search_query"],
        )
    if action.kind == "browser_retry_subject_result":
        subject = _research_subject_from_browser_state(browser_state) or _subject_from_browser_state(browser_state)
        subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
        return (
            subject_title,
            "Re-rank the cached follow-on results and open a stronger alternative than the current page.",
            ["research_subject_title", "selected_title", "selected_url", "ranking"],
        )
    if action.kind == "browser_synthesize_evidence":
        note = _decode_action_note(action.note)
        goal = str(note.get("goal") or plan.prompt or "").strip()
        subject = _research_subject_from_browser_state(browser_state) or _subject_from_browser_state(browser_state)
        subject_title = str(subject.get("title") or browser_state.current_url or "active subject").strip()
        evidence_count = len(browser_state.evidence_items or [])
        return (
            f"{evidence_count} evidence sources for {subject_title}",
            f"Choose the strongest current source for \"{goal}\" and synthesize a grounded answer." if goal else "Choose the strongest current source and synthesize a grounded answer.",
            ["best_source_title", "best_source_kind", "source_count", "synthesis"],
        )
    if action.kind == "browser_back":
        return browser_state.current_url or "browser history", "Return to the previous browser page.", []
    if action.kind == "browser_forward":
        return browser_state.current_url or "browser history", "Move forward in browser history.", []
    if action.kind == "browser_scroll":
        return browser_state.current_url or "current page", f"Scroll the current page {target or 'down'}.", []
    if action.kind == "browser_type_text":
        preview = target if len(target) <= 40 else target[:37] + "..."
        return "active input", f"Type \"{preview}\" into the active browser field.", []
    if action.kind == "browser_submit":
        return "active form", "Submit the active browser form or press enter.", []
    if action.kind == "browser_wait":
        return "browser runtime", f"Pause briefly for {target or '1'} seconds before the next action.", []
    if action.kind == "browser_screenshot":
        return browser_state.current_url or "desktop", "Capture a screenshot of the current desktop/browser view.", ["path"]
    if action.kind == "browser_media_pause":
        return browser_state.current_url or "current media page", "Pause the current browser media playback.", []
    if action.kind == "browser_media_play":
        return browser_state.current_url or "current media page", "Resume the current browser media playback.", []
    if action.kind == "launch_app":
        return target, f"Launch the {target} application.", []
    if action.kind == "open_path":
        return target, "Open this folder or file path in the system file browser.", []
    if action.kind == "list_directory":
        return target, "List the visible entries in this directory.", ["entries"]
    if action.kind == "system_info":
        return target, f"Read the current {target} status from the local machine.", [target]
    return target, "", []


def _candidate_from_plan(
    *,
    candidate_id: str,
    plan: TerminalPlan,
    origin: str,
    rationale: str,
    recommended: bool = False,
    browser_state: BrowserSessionState | None = None,
) -> TerminalTransmutationCandidate | None:
    if not plan.actions:
        return None
    target_preview, expected_outcome, expected_fields = _candidate_preview_from_plan(plan, browser_state or BrowserSessionState())
    return TerminalTransmutationCandidate(
        candidate_id=candidate_id,
        label=_plan_label(plan),
        rationale=rationale,
        origin=origin,
        recommended=recommended,
        plan=plan,
        target_preview=target_preview,
        expected_outcome=expected_outcome,
        expected_fields=expected_fields,
    )


def _contextual_terminal_candidates(browser_state: BrowserSessionState, prompt: str) -> list[TerminalTransmutationCandidate]:
    if not browser_state.current_url and browser_state.page_kind != "search_results":
        return []
    prompt_text = str(prompt or "").strip()
    candidates: list[TerminalTransmutationCandidate] = []
    if browser_state.page_kind == "search_results":
        first = _candidate_from_plan(
            candidate_id="result_1",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="open_search_result", target="1", resolved_target="1")],
            ),
            rationale="The current page is a search-results page, so opening the first result is a strong next transmutation.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if first is not None:
            candidates.append(first)
        second = _candidate_from_plan(
            candidate_id="result_2",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="open_search_result", target="2", resolved_target="2")],
            ),
            rationale="Opening the second result is a useful alternate branch when the first result is not ideal.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if second is not None:
            candidates.append(second)
        extract_cards = _candidate_from_plan(
            candidate_id="extract_cards",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_extract_cards", target="current_cards", resolved_target="current_cards")],
            ),
            rationale="Extracting the current cards gives Memla structured results to compare, click by text, or rank.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if extract_cards is not None:
            candidates.append(extract_cards)
        rank_cards = _candidate_from_plan(
            candidate_id="rank_cards",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[
                    TerminalAction(
                        kind="browser_rank_cards",
                        target="current_cards",
                        resolved_target="current_cards",
                        note=_encode_action_note({"goal": _goal_text_from_prompt(prompt_text) or prompt_text}),
                    )
                ],
            ),
            rationale="Ranking the current cards turns extracted browser state into a best-match judgment for the active goal.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if rank_cards is not None:
            candidates.append(rank_cards)
        compare_cards = _candidate_from_plan(
            candidate_id="compare_cards",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[
                    TerminalAction(
                        kind="browser_compare_cards",
                        target="1,2",
                        resolved_target="1,2",
                        note=_encode_action_note({"goal": _goal_text_from_prompt(prompt_text) or prompt_text, "indexes": [1, 2]}),
                    )
                ],
            ),
            rationale="Comparing the strongest visible candidates is a useful next move when you want Memla to judge fit rather than navigate immediately.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if compare_cards is not None:
            candidates.append(compare_cards)
    if browser_state.current_url:
        new_tab = _candidate_from_plan(
            candidate_id="new_tab",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_new_tab", target="new_tab", resolved_target="new_tab")],
            ),
            rationale="Opening a fresh tab is a useful branch when you want to keep the current page and start a new path.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if new_tab is not None:
            candidates.append(new_tab)
        close_tab = _candidate_from_plan(
            candidate_id="close_tab",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_close_tab", target="current_tab", resolved_target="current_tab")],
            ),
            rationale="Closing the current tab is a useful cleanup transmutation when you are done with this branch.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if close_tab is not None:
            candidates.append(close_tab)
        search_subject_youtube = _candidate_from_plan(
            candidate_id="search_subject_youtube",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[
                    TerminalAction(
                        kind="browser_search_subject",
                        target="youtube",
                        resolved_target="youtube",
                        note=_encode_action_note({"engine": "youtube"}),
                    )
                ],
            ),
            rationale="Searching YouTube for the active subject is a strong next transmutation when you want a related video or walkthrough.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if search_subject_youtube is not None and (_subject_from_browser_state(browser_state) or browser_state.page_kind == "repo_page"):
            candidates.append(search_subject_youtube)
        retry_subject_result = _candidate_from_plan(
            candidate_id="retry_subject_result",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[
                    TerminalAction(
                        kind="browser_retry_subject_result",
                        target="better_result",
                        resolved_target="better_result",
                        note=_encode_action_note({"goal": _research_subject_query_from_browser_state(browser_state) or prompt_text}),
                    )
                ],
            ),
            rationale="If the current opened result is weak, Memla can recover by reopening a stronger cached result for the same subject.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if retry_subject_result is not None and _cached_cards(browser_state):
            candidates.append(retry_subject_result)
        synthesize_evidence = _candidate_from_plan(
            candidate_id="synthesize_evidence",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[
                    TerminalAction(
                        kind="browser_synthesize_evidence",
                        target="current_evidence",
                        resolved_target="current_evidence",
                        note=_encode_action_note({"goal": _goal_text_from_prompt(prompt_text) or prompt_text}),
                    )
                ],
            ),
            rationale="Once Memla has evidence from multiple sources, it can choose the strongest one and answer from that bounded evidence set.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if synthesize_evidence is not None and browser_state.evidence_items:
            candidates.append(synthesize_evidence)
        read_page = _candidate_from_plan(
            candidate_id="read_page",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_read_page", target="current_page", resolved_target="current_page")],
            ),
            rationale="Reading the current page extracts structured evidence before another navigation step.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if read_page is not None:
            candidates.append(read_page)
        go_back = _candidate_from_plan(
            candidate_id="go_back",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_back", target="back", resolved_target="back")],
            ),
            rationale="Going back is a safe recovery transmutation when you want to explore a different branch.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if go_back is not None:
            candidates.append(go_back)
    if browser_state.page_kind == "video_page":
        pause_media = _candidate_from_plan(
            candidate_id="pause_media",
            plan=TerminalPlan(
                prompt=prompt_text,
                source="state_candidate",
                actions=[TerminalAction(kind="browser_media_pause", target="media", resolved_target="media")],
            ),
            rationale="The current page looks like a video page, so pausing media is a relevant continuation.",
            origin="browser_state",
            browser_state=browser_state,
        )
        if pause_media is not None:
            candidates.append(pause_media)
    return candidates


def _plan_starts_new_terminal_branch(plan: TerminalPlan) -> bool:
    if not plan.actions:
        return False
    return any(
        action.kind
        in {
            "open_url",
            "browser_new_tab",
            "browser_close_tab",
            "browser_switch_tab",
            "browser_click_index",
            "browser_click_text",
            "browser_extract_page",
            "browser_extract_cards",
            "browser_rank_cards",
            "browser_compare_cards",
            "browser_search_subject",
            "browser_retry_subject_result",
            "browser_synthesize_evidence",
            "browser_forward",
            "browser_scroll",
            "browser_type_text",
            "browser_submit",
            "browser_wait",
            "browser_screenshot",
            "launch_app",
            "open_path",
            "list_directory",
            "system_info",
        }
        for action in plan.actions
    )


def _should_offer_contextual_candidates(prompt: str, prompt_plan: TerminalPlan, browser_state: BrowserSessionState) -> bool:
    if _plan_starts_new_terminal_branch(prompt_plan):
        return False
    if prompt_plan.actions:
        return True
    return bool(_follow_up_browser_actions(prompt, browser_state))


def build_terminal_step_report(
    *,
    prompt: str,
    model: str = "",
    client: UniversalLLMClient | None = None,
    heuristic_only: bool = False,
    temperature: float = 0.1,
    browser_state: BrowserSessionState | None = None,
) -> TerminalStepReport:
    current_state = browser_state or BrowserSessionState()
    constraints = _terminal_constraints_snapshot(prompt, current_state)
    candidates: list[TerminalTransmutationCandidate] = []
    seen: set[tuple[str, ...]] = set()

    prompt_plan = build_terminal_plan(
        prompt=prompt,
        model=model,
        client=client,
        heuristic_only=heuristic_only,
        temperature=temperature,
        browser_state=current_state,
    )
    prompt_candidate = _candidate_from_plan(
        candidate_id="prompt_plan",
        plan=prompt_plan,
        origin=prompt_plan.source,
        rationale="Best next transmutation inferred from your prompt under the current browser and terminal constraints.",
        recommended=True,
        browser_state=current_state,
    )
    if prompt_candidate is not None:
        signature = _plan_signature(prompt_candidate.plan)
        if signature and signature not in seen:
            seen.add(signature)
            candidates.append(prompt_candidate)

    if not prompt_plan.actions and prompt_plan.clarification:
        constraints["planner_clarification"] = prompt_plan.clarification
    if _should_offer_contextual_candidates(prompt, prompt_plan, current_state):
        for candidate in _contextual_terminal_candidates(current_state, prompt):
            signature = _plan_signature(candidate.plan)
            if not signature or signature in seen:
                continue
            seen.add(signature)
            candidates.append(candidate)

    return TerminalStepReport(
        prompt=prompt,
        constraints=constraints,
        candidates=candidates,
    )


def _resolve_terminal_step_candidate(report: TerminalStepReport, choice: str | int) -> TerminalTransmutationCandidate:
    text = str(choice or "").strip()
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(report.candidates):
            return report.candidates[index - 1]
    for candidate in report.candidates:
        if candidate.candidate_id == text:
            return candidate
    raise ValueError(f"Unknown candidate choice: {choice}")


def append_terminal_trace(
    *,
    report: TerminalStepReport,
    chosen_candidate: TerminalTransmutationCandidate,
    result: TerminalExecutionResult,
    path: str | Path | None = None,
) -> Path:
    trace_path = Path(path).expanduser().resolve() if path else terminal_trace_log_path()
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_ts": int(time.time()),
        "prompt": report.prompt,
        "constraints": report.constraints,
        "chosen_candidate_id": chosen_candidate.candidate_id,
        "chosen_label": chosen_candidate.label,
        "chosen_origin": chosen_candidate.origin,
        "chosen_rationale": chosen_candidate.rationale,
        "chosen_plan": asdict(chosen_candidate.plan),
        "execution": asdict(result),
    }
    with trace_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=True) + "\n")
    return trace_path


def execute_terminal_step(
    report: TerminalStepReport,
    *,
    choice: str | int,
    platform_name: str | None = None,
    browser_state: BrowserSessionState | None = None,
    state_path: str | Path | None = None,
    trace_path: str | Path | None = None,
) -> TerminalStepExecution:
    chosen_candidate = _resolve_terminal_step_candidate(report, choice)
    result = execute_terminal_plan(
        chosen_candidate.plan,
        platform_name=platform_name,
        browser_state=browser_state,
        state_path=state_path,
    )
    written_trace = append_terminal_trace(
        report=report,
        chosen_candidate=chosen_candidate,
        result=result,
        path=trace_path,
    )
    return TerminalStepExecution(
        report=report,
        chosen_candidate=chosen_candidate,
        result=result,
        trace_path=str(written_trace),
    )


def run_terminal_benchmark(
    *,
    cases_path: str,
    raw_model: str,
    memla_model: str,
    raw_provider: str = "",
    raw_base_url: str = "",
    memla_provider: str = "",
    memla_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    heuristic_only: bool = False,
) -> dict[str, Any]:
    cases = load_terminal_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    raw_client = build_llm_client(provider=raw_provider or None, base_url=raw_base_url or None)
    memla_client = build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    raw_model_calls = 0
    memla_model_calls = 0
    memla_heuristic_hits = 0

    for case in cases:
        try:
            raw_start = time.perf_counter()
            raw_plan = build_raw_terminal_plan(
                prompt=case.prompt,
                model=raw_model,
                client=raw_client,
                temperature=temperature,
            )
            raw_latency_ms = round((time.perf_counter() - raw_start) * 1000.0, 2)

            memla_start = time.perf_counter()
            memla_plan = build_terminal_plan(
                prompt=case.prompt,
                model=memla_model,
                client=memla_client,
                heuristic_only=heuristic_only,
                temperature=temperature,
            )
            memla_latency_ms = round((time.perf_counter() - memla_start) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        if raw_plan.source == "raw_model":
            raw_model_calls += 1
        if memla_plan.source == "model":
            memla_model_calls += 1
        if memla_plan.source == "heuristic":
            memla_heuristic_hits += 1

        raw_recall = _action_recall(raw_plan, case.expected_actions)
        memla_recall = _action_recall(memla_plan, case.expected_actions)
        raw_utility = _terminal_utility(raw_plan, case.expected_actions)
        memla_utility = _terminal_utility(memla_plan, case.expected_actions)

        rows.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "expected_actions": list(case.expected_actions),
                "raw_source": raw_plan.source,
                "raw_latency_ms": raw_latency_ms,
                "raw_actions": [_action_signature(action) for action in raw_plan.actions],
                "raw_action_recall": raw_recall,
                "raw_supported": bool(raw_plan.actions),
                "raw_terminal_utility": raw_utility,
                "raw_residual_constraints": list(raw_plan.residual_constraints),
                "memla_source": memla_plan.source,
                "memla_latency_ms": memla_latency_ms,
                "memla_actions": [_action_signature(action) for action in memla_plan.actions],
                "memla_action_recall": memla_recall,
                "memla_supported": bool(memla_plan.actions),
                "memla_terminal_utility": memla_utility,
                "memla_residual_constraints": list(memla_plan.residual_constraints),
                "latency_delta_ms": round(raw_latency_ms - memla_latency_ms, 2),
            }
        )

    count = len(rows) or 1
    avg_raw_latency_ms = round(sum(float(row["raw_latency_ms"]) for row in rows) / count, 2)
    avg_memla_latency_ms = round(sum(float(row["memla_latency_ms"]) for row in rows) / count, 2)
    avg_raw_recall = round(sum(float(row["raw_action_recall"]) for row in rows) / count, 4)
    avg_memla_recall = round(sum(float(row["memla_action_recall"]) for row in rows) / count, 4)
    avg_raw_utility = round(sum(float(row["raw_terminal_utility"]) for row in rows) / count, 4)
    avg_memla_utility = round(sum(float(row["memla_terminal_utility"]) for row in rows) / count, 4)
    raw_support_rate = round(sum(1.0 for row in rows if row["raw_supported"]) / count, 4)
    memla_support_rate = round(sum(1.0 for row in rows if row["memla_supported"]) / count, 4)
    speedup = round(avg_raw_latency_ms / avg_memla_latency_ms, 4) if avg_memla_latency_ms > 0 else None

    return {
        "generated_ts": int(time.time()),
        "cases_path": str(Path(cases_path).resolve()),
        "case_ids": [case.case_id for case in cases],
        "limit": limit,
        "raw_model": raw_model,
        "memla_model": memla_model,
        "raw_provider": raw_client.provider,
        "memla_provider": memla_client.provider,
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "avg_raw_latency_ms": avg_raw_latency_ms,
        "avg_memla_latency_ms": avg_memla_latency_ms,
        "memla_vs_raw_speedup": speedup,
        "avg_raw_action_recall": avg_raw_recall,
        "avg_memla_action_recall": avg_memla_recall,
        "avg_raw_terminal_utility": avg_raw_utility,
        "avg_memla_terminal_utility": avg_memla_utility,
        "raw_support_rate": raw_support_rate,
        "memla_support_rate": memla_support_rate,
        "raw_model_call_count": raw_model_calls,
        "memla_model_call_count": memla_model_calls,
        "memla_heuristic_hit_count": memla_heuristic_hits,
        "rows": rows,
        "failed_cases": failed_cases,
    }


def render_terminal_benchmark_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Terminal Benchmark",
        "",
        f"- Raw provider: `{report.get('raw_provider', '')}`",
        f"- Memla provider: `{report.get('memla_provider', '')}`",
        f"- Raw model: `{report.get('raw_model', '')}`",
        f"- Memla model: `{report.get('memla_model', '')}`",
        f"- Cases completed: `{report.get('cases', 0)}` / `{report.get('cases_requested', 0)}`",
        "",
        "## Lane summary",
        "",
        "| Metric | Raw | Memla |",
        "| --- | --- | --- |",
        f"| Avg latency (ms) | `{report.get('avg_raw_latency_ms', 0.0)}` | `{report.get('avg_memla_latency_ms', 0.0)}` |",
        f"| Action recall | `{report.get('avg_raw_action_recall', 0.0)}` | `{report.get('avg_memla_action_recall', 0.0)}` |",
        f"| Support rate | `{report.get('raw_support_rate', 0.0)}` | `{report.get('memla_support_rate', 0.0)}` |",
        f"| Terminal utility | `{report.get('avg_raw_terminal_utility', 0.0)}` | `{report.get('avg_memla_terminal_utility', 0.0)}` |",
        "",
        f"- Raw model calls: `{report.get('raw_model_call_count', 0)}`",
        f"- Memla model calls: `{report.get('memla_model_call_count', 0)}`",
        f"- Memla heuristic hits: `{report.get('memla_heuristic_hit_count', 0)}`",
    ]
    speedup = report.get("memla_vs_raw_speedup")
    if speedup:
        lines.extend(["", f"- Raw-vs-Memla latency speedup: `{speedup}x`"])
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for failure in report["failed_cases"]:
            lines.append(f"- `{failure.get('case_id', '')}` [{failure.get('error_type', '')}] {failure.get('message', '')}".rstrip())
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        lines.extend(
            [
                f"### {row.get('case_id', '')}",
                "",
                f"- Prompt: `{row.get('prompt', '')}`",
                f"- Expected actions: `{', '.join(row.get('expected_actions', []))}`",
                f"- Raw source/actions: `{row.get('raw_source', '')}` / `{', '.join(row.get('raw_actions', []))}`",
                f"- Memla source/actions: `{row.get('memla_source', '')}` / `{', '.join(row.get('memla_actions', []))}`",
                f"- Raw latency: `{row.get('raw_latency_ms', 0.0)} ms`",
                f"- Memla latency: `{row.get('memla_latency_ms', 0.0)} ms`",
                f"- Raw utility: `{row.get('raw_terminal_utility', 0.0)}`",
                f"- Memla utility: `{row.get('memla_terminal_utility', 0.0)}`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def render_terminal_plan_text(plan: TerminalPlan) -> str:
    lines = [f"Prompt: {plan.prompt}", f"Plan source: {plan.source}"]
    if plan.actions:
        lines.append("Actions:")
        for action in plan.actions:
            target = action.resolved_target or action.target
            lines.append(f"- {action.kind}: {target}")
    if plan.clarification:
        lines.append(f"Clarification: {plan.clarification}")
    if plan.residual_constraints:
        lines.append(f"Residual constraints: {', '.join(plan.residual_constraints)}")
    return "\n".join(lines)


def render_terminal_step_report_text(report: TerminalStepReport) -> str:
    lines = [f"Prompt: {report.prompt}", "Constraints:"]
    for key, value in report.constraints.items():
        if value in ("", [], None):
            continue
        lines.append(f"- {key}: {value}")
    if report.candidates:
        lines.append("Candidate transmutations:")
        for idx, candidate in enumerate(report.candidates, start=1):
            marker = " [recommended]" if candidate.recommended else ""
            lines.append(f"{idx}. {candidate.label}{marker}")
            lines.append(f"   rationale: {candidate.rationale}")
            lines.append(f"   origin: {candidate.origin}")
            if candidate.target_preview:
                lines.append(f"   will act on: {candidate.target_preview}")
            if candidate.expected_outcome:
                lines.append(f"   expected outcome: {candidate.expected_outcome}")
            if candidate.expected_fields:
                lines.append(f"   will extract: {', '.join(candidate.expected_fields)}")
            plan_actions = ", ".join(_action_signature(action) for action in candidate.plan.actions)
            if plan_actions:
                lines.append(f"   actions: {plan_actions}")
    else:
        lines.append("Candidate transmutations: none")
    return "\n".join(lines)


def render_terminal_execution_text(result: TerminalExecutionResult) -> str:
    lines = [f"Prompt: {result.prompt}", f"Plan source: {result.plan_source}", f"Execution: {'OK' if result.ok else 'FAILED'}"]
    for record in result.records:
        lines.append(f"- {record.kind} {record.target}: {record.status.upper()} {record.message}".rstrip())
        if record.details:
            for key, value in record.details.items():
                lines.append(f"  {key}: {value}")
    if result.residual_constraints:
        lines.append(f"Residual constraints: {', '.join(result.residual_constraints)}")
    return "\n".join(lines)


def render_terminal_scout_text(result: TerminalScoutResult) -> str:
    lines = [
        f"Prompt: {result.prompt}",
        f"Scout kind: {result.scout_kind}",
        f"Scout source: {result.source}",
        f"Execution: {'OK' if result.ok else 'FAILED'}",
    ]
    if result.query:
        lines.append(f"Query: {result.query}")
    if result.goal:
        lines.append(f"Goal: {result.goal}")
    if result.summary:
        lines.append(f"Summary: {result.summary}")
    if result.top_results:
        lines.append("Top results:")
        for item in result.top_results:
            title = str(item.get("title") or item.get("repo") or item.get("url") or "unknown").strip()
            summary = str(item.get("summary") or "").strip()
            meta = str(item.get("meta") or "").strip()
            score = item.get("score")
            line = f"- {int(item.get('index') or 0)}. {title}"
            if score not in (None, ""):
                line += f" [score {score}]"
            if meta:
                line += f" ({meta})"
            lines.append(line)
            if summary:
                lines.append(f"  {summary}")
    if result.steps:
        lines.append("Scout loop:")
        for step in result.steps:
            lines.append(f"- {step.transmutation}: {step.status.upper()} {step.message}")
    if result.residual_constraints:
        lines.append(f"Residual constraints: {', '.join(result.residual_constraints)}")
    return "\n".join(lines)


def render_terminal_step_execution_text(execution: TerminalStepExecution) -> str:
    lines = [
        render_terminal_step_report_text(execution.report),
        "",
        f"Chosen transmutation: {execution.chosen_candidate.label}",
        f"Trace log: {execution.trace_path}",
        "",
        render_terminal_execution_text(execution.result),
    ]
    return "\n".join(lines).strip()


def terminal_plan_to_dict(plan: TerminalPlan) -> dict[str, Any]:
    return asdict(plan)


def terminal_execution_to_dict(result: TerminalExecutionResult) -> dict[str, Any]:
    return asdict(result)


def terminal_scout_to_dict(result: TerminalScoutResult) -> dict[str, Any]:
    return asdict(result)


def terminal_step_report_to_dict(report: TerminalStepReport) -> dict[str, Any]:
    return asdict(report)


def terminal_step_execution_to_dict(execution: TerminalStepExecution) -> dict[str, Any]:
    return {
        "report": asdict(execution.report),
        "chosen_candidate": asdict(execution.chosen_candidate),
        "result": asdict(execution.result),
        "trace_path": execution.trace_path,
    }


def build_llm_client(
    *,
    provider: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
) -> UniversalLLMClient:
    if not any(value for value in (provider, base_url, api_key)):
        return UniversalLLMClient.from_env()
    resolved_provider = str(provider or os.environ.get("LLM_PROVIDER", "ollama")).strip()
    normalized_provider = UniversalLLMClient._normalize_provider(resolved_provider)
    resolved_base_url = str(base_url or "").strip()
    if not resolved_base_url and normalized_provider == "ollama":
        candidates: list[str] = []
        for raw in (
            os.environ.get("OLLAMA_URL", ""),
            os.environ.get("LLM_BASE_URL", ""),
            "http://127.0.0.1:11434",
            "http://127.0.0.1:11435",
        ):
            clean = str(raw or "").strip().rstrip("/")
            if clean and clean not in candidates:
                candidates.append(clean)
        selected = ""
        for candidate in candidates:
            try:
                req = urllib_request.Request(f"{candidate}/api/tags", headers={"Accept": "application/json"})
                with urllib_request.urlopen(req, timeout=0.35):
                    selected = candidate
                    break
            except Exception:
                continue
        resolved_base_url = selected or (candidates[0] if candidates else "http://127.0.0.1:11434")
    if not resolved_base_url:
        resolved_base_url = str(os.environ.get("LLM_BASE_URL", "http://127.0.0.1:11434")).strip()
    resolved_api_key = api_key or os.environ.get("LLM_API_KEY")
    if normalized_provider == "github_models" and not resolved_api_key:
        resolved_api_key = os.environ.get("GITHUB_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
    return UniversalLLMClient(
        provider=normalized_provider,
        base_url=resolved_base_url,
        api_key=resolved_api_key,
    )


def _demo_request_supported(prompt: str) -> bool:
    return build_terminal_plan(prompt=prompt, heuristic_only=True).actions != []


def _extract_first_json_object(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if not raw:
        return {}
    try:
        return dict(json.loads(raw))
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end <= start:
        return {}
    try:
        return dict(json.loads(raw[start : end + 1]))
    except Exception:
        return {}


def _judge_web_answer_with_teacher(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    query: str,
    answer: str,
    source_title: str,
    source_url: str,
    source_count: int,
    result_cards: list[dict[str, Any]],
) -> dict[str, Any]:
    card_lines = []
    for index, card in enumerate(list(result_cards or [])[:3], start=1):
        title = str(card.get("title") or "").strip()
        summary = str(card.get("summary") or "").strip()
        url = str(card.get("url") or "").strip()
        card_lines.append(f"{index}. {title} | {summary} | {url}")
    response = client.chat(
        model=model,
        temperature=0.0,
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You grade Memla web answers for consumer assistant quality. "
                    "Return JSON only with keys directness, warmth, groundedness, helpfulness, overall, verdict, coaching. "
                    "Scores must be integers from 1 to 5. Coaching must be one short sentence."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Prompt: {prompt}\n"
                    f"Resolved query: {query}\n"
                    f"Memla answer: {answer}\n"
                    f"Best source title: {source_title}\n"
                    f"Best source url: {source_url}\n"
                    f"Source count: {source_count}\n"
                    "Top result cards:\n"
                    + ("\n".join(card_lines) if card_lines else "(none)")
                ),
            ),
        ],
    )
    payload = _extract_first_json_object(response)
    if not payload:
        return {
            "directness": 0,
            "warmth": 0,
            "groundedness": 0,
            "helpfulness": 0,
            "overall": 0,
            "verdict": "",
            "coaching": "",
            "raw_response": response,
        }
    judged: dict[str, Any] = {
        "directness": int(payload.get("directness") or 0),
        "warmth": int(payload.get("warmth") or 0),
        "groundedness": int(payload.get("groundedness") or 0),
        "helpfulness": int(payload.get("helpfulness") or 0),
        "overall": int(payload.get("overall") or 0),
        "verdict": str(payload.get("verdict") or "").strip(),
        "coaching": str(payload.get("coaching") or "").strip(),
    }
    return judged


def _rescue_web_answer_with_teacher(
    *,
    client: UniversalLLMClient,
    model: str,
    prompt: str,
    query: str,
    slice_kind: str,
    current_answer: str,
    source_title: str,
    source_url: str,
    source_count: int,
    result_cards: list[dict[str, Any]],
    evidence_items: list[dict[str, Any]],
    evidence_chunks: list[dict[str, Any]],
    coaching: str = "",
) -> dict[str, Any]:
    requirements = _web_answer_requirements(prompt, query, slice_kind)
    card_lines: list[str] = []
    for index, card in enumerate(list(result_cards or [])[:3], start=1):
        title = str(card.get("title") or "").strip()
        summary = str(card.get("summary") or "").strip()
        url = str(card.get("url") or "").strip()
        card_lines.append(f"{index}. {title} | {summary} | {url}")
    evidence_lines: list[str] = []
    for index, item in enumerate(list(evidence_items or [])[:3], start=1):
        title = str(item.get("title") or "").strip()
        summary = str(item.get("summary") or "").strip()
        preview = str(item.get("content_preview") or "").strip()
        url = str(item.get("url") or "").strip()
        evidence_lines.append(
            "\n".join(
                part
                for part in [
                    f"{index}. {title} | {url}",
                    f"summary: {summary}" if summary else "",
                    f"preview: {preview}" if preview else "",
                ]
                if part
            )
        )
    chunk_lines: list[str] = []
    for chunk in list(evidence_chunks or [])[:10]:
        chunk_id = str(chunk.get("chunk_id") or "").strip()
        title = str(chunk.get("title") or "").strip()
        text = str(chunk.get("text") or "").strip()
        chunk_lines.append(f"{chunk_id} | {title} | {text}")
    response = client.chat(
        model=model,
        temperature=0.0,
        messages=[
            ChatMessage(
                role="system",
                content=(
                    "You are Memla's web-answer teacher. "
                    "Improve weak consumer-facing answers using only the supplied evidence. "
                    "Answer like a smart, calm friend. "
                    "Give the direct answer first. "
                    "For news, give 1-3 short concrete highlights. "
                    "For weather, include actual conditions or temperature if present. "
                    "For factual questions, state the fact plainly in the first sentence. "
                    "If the question needs a derived answer like an age-at-event, compute it when the evidence supports it. "
                    "Tell Memla which chunk ids actually mattered. "
                    "Do not talk about SEO, web pages, or what an article covers. "
                    "If evidence is weak, say that plainly. "
                    "Return JSON only with keys answer, why_better, promotion_notes, question_type, relevant_chunk_ids, extracted_facts, missing_fields. "
                    "promotion_notes, relevant_chunk_ids, extracted_facts, and missing_fields must be JSON arrays of short strings."
                ),
            ),
            ChatMessage(
                role="user",
                content=(
                    f"Prompt: {prompt}\n"
                    f"Resolved query: {query}\n"
                    f"Slice: {slice_kind}\n"
                    f"Question type: {requirements.get('question_type', '')}\n"
                    f"Needed fields: {json.dumps(list(requirements.get('needed_fields') or []))}\n"
                    f"Current Memla answer: {current_answer}\n"
                    f"Current best source title: {source_title}\n"
                    f"Current best source url: {source_url}\n"
                    f"Current source count: {source_count}\n"
                    f"Teacher coaching so far: {coaching}\n"
                    "Top result cards:\n"
                    + ("\n".join(card_lines) if card_lines else "(none)")
                    + "\n\nEvidence chunks:\n"
                    + ("\n".join(chunk_lines) if chunk_lines else "(none)")
                    + "\n\nEvidence:\n"
                    + ("\n\n".join(evidence_lines) if evidence_lines else "(none)")
                ),
            ),
        ],
    )
    payload = _extract_first_json_object(response)
    answer = " ".join(str(payload.get("answer") or "").split()).strip()
    why_better = str(payload.get("why_better") or "").strip()
    promotion_notes_raw = payload.get("promotion_notes") or []
    promotion_notes = [
        str(item).strip()
        for item in (promotion_notes_raw if isinstance(promotion_notes_raw, list) else [promotion_notes_raw])
        if str(item).strip()
    ]
    relevant_chunk_ids = [
        str(item).strip()
        for item in list(payload.get("relevant_chunk_ids") or [])
        if str(item).strip()
    ]
    extracted_facts = [
        str(item).strip()
        for item in list(payload.get("extracted_facts") or [])
        if str(item).strip()
    ]
    missing_fields = [
        str(item).strip()
        for item in list(payload.get("missing_fields") or [])
        if str(item).strip()
    ]
    return {
        "answer": answer,
        "why_better": why_better,
        "promotion_notes": promotion_notes,
        "question_type": str(payload.get("question_type") or requirements.get("question_type") or "").strip(),
        "relevant_chunk_ids": relevant_chunk_ids,
        "extracted_facts": extracted_facts,
        "missing_fields": missing_fields,
        "raw_response": response,
    }


def _web_teacher_overall(judgement: dict[str, Any]) -> int:
    try:
        return int(dict(judgement or {}).get("overall") or 0)
    except Exception:
        return 0


def _should_rescue_web_answer(
    *,
    answer: str,
    slice_kind: str,
    baseline_judgement: dict[str, Any],
    rescue_threshold: int,
) -> bool:
    if not str(answer or "").strip():
        return True
    overall = _web_teacher_overall(baseline_judgement)
    if overall and overall < max(int(rescue_threshold), 1):
        return True
    return _web_answer_needs_model_rescue(slice_kind, answer, question_type=question_type)


def _build_web_teacher_trace_row(row: dict[str, Any]) -> dict[str, Any]:
    baseline_judgement = dict(row.get("baseline_judgement") or {})
    rescued_judgement = dict(row.get("rescued_judgement") or {})
    baseline_hard_check = dict(row.get("baseline_hard_check") or {})
    promoted_hard_check = dict(row.get("promoted_hard_check") or {})
    return {
        "case_id": str(row.get("case_id") or "").strip(),
        "prompt": str(row.get("prompt") or "").strip(),
        "query": str(row.get("query") or "").strip(),
        "slice": str(row.get("answer_slice") or "").strip(),
        "question_type": str(row.get("question_type") or "").strip(),
        "needed_fields": [str(item).strip() for item in list(row.get("needed_fields") or []) if str(item).strip()],
        "baseline_answer": str(row.get("baseline_answer") or "").strip(),
        "baseline_overall": _web_teacher_overall(baseline_judgement),
        "baseline_relevant_chunk_ids": [str(item).strip() for item in list(row.get("baseline_relevant_chunk_ids") or []) if str(item).strip()],
        "baseline_extracted_facts": [str(item).strip() for item in list(row.get("baseline_extracted_facts") or []) if str(item).strip()],
        "baseline_hard_passed": bool(baseline_hard_check.get("passed")),
        "baseline_hard_reasons": [str(item).strip() for item in list(baseline_hard_check.get("reasons") or []) if str(item).strip()],
        "rescued_answer": str(row.get("rescued_answer") or "").strip(),
        "rescued_overall": _web_teacher_overall(rescued_judgement),
        "rescued_relevant_chunk_ids": [str(item).strip() for item in list(row.get("rescued_relevant_chunk_ids") or []) if str(item).strip()],
        "rescued_extracted_facts": [str(item).strip() for item in list(row.get("rescued_extracted_facts") or []) if str(item).strip()],
        "promoted_answer": str(row.get("promoted_answer") or "").strip(),
        "promoted_lane": str(row.get("promoted_lane") or "").strip(),
        "promoted_hard_passed": bool(promoted_hard_check.get("passed")),
        "promoted_hard_reasons": [str(item).strip() for item in list(promoted_hard_check.get("reasons") or []) if str(item).strip()],
        "improvement_delta": float(row.get("improvement_delta") or 0.0),
        "teacher_coaching": str(baseline_judgement.get("coaching") or "").strip(),
        "rescue_why_better": str(row.get("rescue_why_better") or "").strip(),
        "promotion_notes": [str(item).strip() for item in list(row.get("promotion_notes") or []) if str(item).strip()],
        "source_title": str(row.get("baseline_source_title") or "").strip(),
        "source_url": str(row.get("baseline_source_url") or "").strip(),
        "source_count": int(row.get("baseline_source_count") or 0),
        "evidence_chunk_count": int(row.get("evidence_chunk_count") or 0),
    }


def run_web_answer_benchmark(
    *,
    cases_path: str,
    memla_model: str,
    memla_provider: str = "",
    memla_base_url: str = "",
    judge_model: str = "",
    judge_provider: str = "",
    judge_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    heuristic_only: bool = False,
) -> dict[str, Any]:
    cases = load_terminal_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    memla_client = None if heuristic_only else build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    judge_client = build_llm_client(
        provider=judge_provider or memla_provider or None,
        base_url=judge_base_url or None,
    ) if judge_model else None

    rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    memla_model_calls = 0
    memla_heuristic_hits = 0
    judged_count = 0
    model_answer_count = 0

    for case in cases:
        try:
            plan_started = time.perf_counter()
            memla_plan = build_terminal_plan(
                prompt=case.prompt,
                model=memla_model,
                client=memla_client,
                heuristic_only=heuristic_only,
                temperature=temperature,
            )
            plan_latency_ms = round((time.perf_counter() - plan_started) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        if memla_plan.source == "model":
            memla_model_calls += 1
        if memla_plan.source == "heuristic":
            memla_heuristic_hits += 1

        web_action = next((action for action in memla_plan.actions if action.kind == "browser_answer_query"), None)
        if web_action is None:
            rows.append(
                {
                    "case_id": case.case_id,
                    "prompt": case.prompt,
                    "plan_source": memla_plan.source,
                    "plan_actions": [_action_signature(action) for action in memla_plan.actions],
                    "plan_latency_ms": plan_latency_ms,
                    "answer_latency_ms": 0.0,
                    "answered": False,
                    "query": "",
                    "answer": "",
                    "raw_answer": "",
                    "answer_voice": "",
                    "answer_slice": "",
                    "source_title": "",
                    "source_url": "",
                    "source_count": 0,
                    "teacher_judgement": {},
                }
            )
            continue

        note_payload = _decode_action_note(web_action.note)
        goal = str(note_payload.get("goal") or case.prompt).strip()
        query = str(note_payload.get("query") or web_action.resolved_target or web_action.target or case.prompt).strip()
        try:
            answer_started = time.perf_counter()
            answer_payload = _resolve_web_answer(
                prompt=goal or case.prompt,
                query=query,
                client=memla_client,
                model=memla_model,
            )
            answer_latency_ms = round((time.perf_counter() - answer_started) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        answer = str(answer_payload.get("answer") or "").strip()
        raw_answer = str(answer_payload.get("raw_answer") or answer).strip()
        best_card = dict(answer_payload.get("best_card") or {})
        best_details = dict(answer_payload.get("best_details") or {})
        cards = [dict(item) for item in list(answer_payload.get("cards") or []) if isinstance(item, dict)]
        answer_style = dict(answer_payload.get("answer_style") or {})
        evidence_chunks = [dict(item) for item in list(answer_payload.get("evidence_chunks") or []) if isinstance(item, dict)]
        source_title = str(best_details.get("title") or best_card.get("title") or "").strip()
        source_url = str(best_details.get("url") or best_card.get("url") or "").strip()
        source_count = int(answer_payload.get("source_count") or len(cards) or 0)
        hard_check = _hard_check_web_answer(
            prompt=case.prompt,
            question_type=str(answer_payload.get("question_type") or "").strip(),
            answer=answer,
            extracted_facts=[str(item).strip() for item in list(answer_payload.get("extracted_facts") or []) if str(item).strip()],
            missing_fields=[str(item).strip() for item in list(answer_payload.get("missing_fields") or []) if str(item).strip()],
        )

        teacher_judgement: dict[str, Any] = {}
        if judge_client is not None and answer:
            try:
                teacher_judgement = _judge_web_answer_with_teacher(
                    client=judge_client,
                    model=judge_model,
                    prompt=case.prompt,
                    query=query,
                    answer=answer,
                    source_title=source_title,
                    source_url=source_url,
                    source_count=source_count,
                    result_cards=cards,
                )
                judged_count += 1
            except Exception as exc:
                teacher_judgement = {"error_type": type(exc).__name__, "message": str(exc)}

        rows.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "plan_source": memla_plan.source,
                "plan_actions": [_action_signature(action) for action in memla_plan.actions],
                "plan_latency_ms": plan_latency_ms,
                "answer_latency_ms": answer_latency_ms,
                "answered": bool(answer),
                "query": query,
                "answer": answer,
                "raw_answer": raw_answer,
                "answer_voice": str(answer_style.get("voice") or "").strip(),
                "answer_slice": str(answer_style.get("slice") or "").strip(),
                "question_type": str(answer_payload.get("question_type") or "").strip(),
                "needed_fields": [str(item).strip() for item in list(answer_payload.get("needed_fields") or []) if str(item).strip()],
                "relevant_chunk_ids": [str(item).strip() for item in list(answer_payload.get("relevant_chunk_ids") or []) if str(item).strip()],
                "extracted_facts": [str(item).strip() for item in list(answer_payload.get("extracted_facts") or []) if str(item).strip()],
                "source_title": source_title,
                "source_url": source_url,
                "source_count": source_count,
                "evidence_chunk_count": len(evidence_chunks),
                "hard_check": hard_check,
                "teacher_judgement": teacher_judgement,
            }
        )
        if str(answer_style.get("generator") or "").strip() == "model":
            model_answer_count += 1

    count = len(rows) or 1
    answered_count = sum(1 for row in rows if row.get("answered"))
    avg_plan_latency_ms = round(sum(float(row.get("plan_latency_ms") or 0.0) for row in rows) / count, 2)
    avg_answer_latency_ms = round(sum(float(row.get("answer_latency_ms") or 0.0) for row in rows) / count, 2)
    avg_source_count = round(sum(float(row.get("source_count") or 0.0) for row in rows) / count, 2)
    answer_rate = round(answered_count / count, 4)
    teacher_overall_scores = [
        float(dict(row.get("teacher_judgement") or {}).get("overall") or 0.0)
        for row in rows
        if dict(row.get("teacher_judgement") or {}).get("overall")
    ]
    avg_teacher_overall = round(sum(teacher_overall_scores) / len(teacher_overall_scores), 4) if teacher_overall_scores else 0.0
    hard_applicable_rows = [row for row in rows if bool(dict(row.get("hard_check") or {}).get("applicable"))]
    hard_passed_count = sum(1 for row in hard_applicable_rows if bool(dict(row.get("hard_check") or {}).get("passed")))
    hard_pass_rate = round(hard_passed_count / len(hard_applicable_rows), 4) if hard_applicable_rows else 0.0

    return {
        "generated_ts": int(time.time()),
        "cases_path": str(Path(cases_path).resolve()),
        "case_ids": [case.case_id for case in cases],
        "limit": limit,
        "memla_model": memla_model,
        "memla_provider": "" if memla_client is None else str(getattr(memla_client, "provider", "") or ""),
        "judge_model": judge_model,
        "judge_provider": "" if judge_client is None else str(getattr(judge_client, "provider", "") or ""),
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "answered_count": answered_count,
        "answer_rate": answer_rate,
        "avg_plan_latency_ms": avg_plan_latency_ms,
        "avg_answer_latency_ms": avg_answer_latency_ms,
        "avg_source_count": avg_source_count,
        "avg_teacher_overall": avg_teacher_overall,
        "hard_applicable_count": len(hard_applicable_rows),
        "hard_passed_count": hard_passed_count,
        "hard_pass_rate": hard_pass_rate,
        "memla_model_call_count": memla_model_calls,
        "memla_heuristic_hit_count": memla_heuristic_hits,
        "model_answer_count": model_answer_count,
        "judged_count": judged_count,
        "rows": rows,
        "failed_cases": failed_cases,
    }


def run_web_teacher_loop(
    *,
    cases_path: str,
    memla_model: str,
    memla_provider: str = "",
    memla_base_url: str = "",
    teacher_model: str = "",
    teacher_provider: str = "",
    teacher_base_url: str = "",
    judge_model: str = "",
    judge_provider: str = "",
    judge_base_url: str = "",
    temperature: float = 0.1,
    case_ids: list[str] | None = None,
    limit: int | None = None,
    heuristic_only: bool = False,
    rescue_threshold: int = 4,
) -> dict[str, Any]:
    cases = load_terminal_benchmark_cases(cases_path)
    selected_ids = {str(item).strip() for item in list(case_ids or []) if str(item).strip()}
    if selected_ids:
        cases = [case for case in cases if case.case_id in selected_ids]
    if limit is not None:
        cases = cases[: max(int(limit), 0)]

    memla_client = None if heuristic_only else build_llm_client(provider=memla_provider or None, base_url=memla_base_url or None)
    teacher_client = build_llm_client(
        provider=teacher_provider or memla_provider or None,
        base_url=teacher_base_url or None,
    ) if teacher_model else None
    resolved_judge_model = judge_model or teacher_model
    judge_client = build_llm_client(
        provider=judge_provider or teacher_provider or memla_provider or None,
        base_url=judge_base_url or teacher_base_url or None,
    ) if resolved_judge_model else None

    rows: list[dict[str, Any]] = []
    trace_rows: list[dict[str, Any]] = []
    failed_cases: list[dict[str, Any]] = []
    memla_model_calls = 0
    memla_heuristic_hits = 0
    judged_count = 0
    rescued_count = 0
    improved_count = 0
    promoted_rescue_count = 0

    for case in cases:
        try:
            plan_started = time.perf_counter()
            memla_plan = build_terminal_plan(
                prompt=case.prompt,
                model=memla_model,
                client=memla_client,
                heuristic_only=heuristic_only,
                temperature=temperature,
            )
            plan_latency_ms = round((time.perf_counter() - plan_started) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        if memla_plan.source == "model":
            memla_model_calls += 1
        if memla_plan.source == "heuristic":
            memla_heuristic_hits += 1

        web_action = next((action for action in memla_plan.actions if action.kind == "browser_answer_query"), None)
        if web_action is None:
            rows.append(
                {
                    "case_id": case.case_id,
                    "prompt": case.prompt,
                    "plan_source": memla_plan.source,
                    "plan_actions": [_action_signature(action) for action in memla_plan.actions],
                    "plan_latency_ms": plan_latency_ms,
                    "answered": False,
                    "query": "",
                    "baseline_answer": "",
                    "rescued_answer": "",
                    "promoted_answer": "",
                    "promoted_lane": "",
                    "improvement_delta": 0.0,
                    "baseline_judgement": {},
                    "rescued_judgement": {},
                    "promotion_notes": [],
                }
            )
            continue

        note_payload = _decode_action_note(web_action.note)
        goal = str(note_payload.get("goal") or case.prompt).strip()
        query = str(note_payload.get("query") or web_action.resolved_target or web_action.target or case.prompt).strip()
        try:
            answer_started = time.perf_counter()
            answer_payload = _resolve_web_answer(
                prompt=goal or case.prompt,
                query=query,
                client=memla_client,
                model=memla_model,
            )
            baseline_answer_latency_ms = round((time.perf_counter() - answer_started) * 1000.0, 2)
        except Exception as exc:
            failed_cases.append({"case_id": case.case_id, "error_type": type(exc).__name__, "message": str(exc)})
            continue

        baseline_answer = str(answer_payload.get("answer") or "").strip()
        baseline_raw_answer = str(answer_payload.get("raw_answer") or baseline_answer).strip()
        best_card = dict(answer_payload.get("best_card") or {})
        best_details = dict(answer_payload.get("best_details") or {})
        cards = [dict(item) for item in list(answer_payload.get("cards") or []) if isinstance(item, dict)]
        evidence_items = [dict(item) for item in list(answer_payload.get("evidence_items") or []) if isinstance(item, dict)]
        evidence_chunks = [dict(item) for item in list(answer_payload.get("evidence_chunks") or []) if isinstance(item, dict)]
        answer_style = dict(answer_payload.get("answer_style") or {})
        source_title = str(best_details.get("title") or best_card.get("title") or "").strip()
        source_url = str(best_details.get("url") or best_card.get("url") or "").strip()
        source_count = int(answer_payload.get("source_count") or len(cards) or 0)
        slice_kind = str(answer_style.get("slice") or _web_question_slice(goal or case.prompt, query)).strip()
        question_type = str(answer_payload.get("question_type") or "").strip()
        needed_fields = [str(item).strip() for item in list(answer_payload.get("needed_fields") or []) if str(item).strip()]
        baseline_relevant_chunk_ids = [str(item).strip() for item in list(answer_payload.get("relevant_chunk_ids") or []) if str(item).strip()]
        baseline_extracted_facts = [str(item).strip() for item in list(answer_payload.get("extracted_facts") or []) if str(item).strip()]
        baseline_missing_fields = [str(item).strip() for item in list(answer_payload.get("missing_fields") or []) if str(item).strip()]
        baseline_hard_check = _hard_check_web_answer(
            prompt=case.prompt,
            question_type=question_type,
            answer=baseline_answer,
            extracted_facts=baseline_extracted_facts,
            missing_fields=baseline_missing_fields,
        )

        baseline_judgement: dict[str, Any] = {}
        if judge_client is not None and baseline_answer:
            try:
                baseline_judgement = _judge_web_answer_with_teacher(
                    client=judge_client,
                    model=resolved_judge_model,
                    prompt=case.prompt,
                    query=query,
                    answer=baseline_answer,
                    source_title=source_title,
                    source_url=source_url,
                    source_count=source_count,
                    result_cards=cards,
                )
                judged_count += 1
            except Exception as exc:
                baseline_judgement = {"error_type": type(exc).__name__, "message": str(exc)}

        needs_rescue = teacher_client is not None and _should_rescue_web_answer(
            answer=baseline_raw_answer,
            slice_kind=slice_kind,
            baseline_judgement=baseline_judgement,
            rescue_threshold=rescue_threshold,
        )

        rescue_payload: dict[str, Any] = {}
        rescued_answer = ""
        rescue_latency_ms = 0.0
        rescued_judgement: dict[str, Any] = {}
        rescued_hard_check: dict[str, Any] = {"applicable": False, "passed": False, "score": 0.0, "reasons": []}
        rescue_attempted = False
        if needs_rescue and teacher_client is not None and teacher_model:
            rescue_attempted = True
            try:
                rescue_started = time.perf_counter()
                rescue_payload = _rescue_web_answer_with_teacher(
                    client=teacher_client,
                    model=teacher_model,
                    prompt=case.prompt,
                    query=query,
                    slice_kind=slice_kind,
                    current_answer=baseline_answer or baseline_raw_answer,
                    source_title=source_title,
                    source_url=source_url,
                    source_count=source_count,
                    result_cards=cards,
                    evidence_items=evidence_items,
                    evidence_chunks=evidence_chunks,
                    coaching=str(baseline_judgement.get("coaching") or "").strip(),
                )
                rescue_latency_ms = round((time.perf_counter() - rescue_started) * 1000.0, 2)
                rescued_answer = str(rescue_payload.get("answer") or "").strip()
                if rescued_answer:
                    rescued_count += 1
                    rescued_hard_check = _hard_check_web_answer(
                        prompt=case.prompt,
                        question_type=str(rescue_payload.get("question_type") or question_type).strip(),
                        answer=rescued_answer,
                        extracted_facts=[str(item).strip() for item in list(rescue_payload.get("extracted_facts") or []) if str(item).strip()],
                        missing_fields=[str(item).strip() for item in list(rescue_payload.get("missing_fields") or []) if str(item).strip()],
                    )
            except Exception as exc:
                rescue_payload = {"error_type": type(exc).__name__, "message": str(exc)}

        if judge_client is not None and rescued_answer:
            try:
                rescued_judgement = _judge_web_answer_with_teacher(
                    client=judge_client,
                    model=resolved_judge_model,
                    prompt=case.prompt,
                    query=query,
                    answer=rescued_answer,
                    source_title=source_title,
                    source_url=source_url,
                    source_count=source_count,
                    result_cards=cards,
                )
                judged_count += 1
            except Exception as exc:
                rescued_judgement = {"error_type": type(exc).__name__, "message": str(exc)}

        baseline_overall = _web_teacher_overall(baseline_judgement)
        rescued_overall = _web_teacher_overall(rescued_judgement)
        promoted_lane = "baseline"
        promoted_answer = baseline_answer
        promoted_overall = baseline_overall
        baseline_hard_pass = bool(baseline_hard_check.get("passed"))
        rescued_hard_pass = bool(rescued_hard_check.get("passed"))
        if rescued_answer and rescued_hard_pass and not baseline_hard_pass:
            promoted_lane = "teacher_rescue"
            promoted_answer = rescued_answer
            promoted_overall = rescued_overall or baseline_overall
        elif rescued_answer and (not baseline_answer or rescued_overall >= baseline_overall or judge_client is None):
            promoted_lane = "teacher_rescue"
            promoted_answer = rescued_answer
            promoted_overall = rescued_overall or baseline_overall
        improvement_delta = float(promoted_overall - baseline_overall)
        if promoted_lane == "teacher_rescue":
            promoted_rescue_count += 1
        promoted_hard_check = rescued_hard_check if promoted_lane == "teacher_rescue" else baseline_hard_check
        if improvement_delta > 0:
            improved_count += 1

        row = {
            "case_id": case.case_id,
            "prompt": case.prompt,
            "plan_source": memla_plan.source,
            "plan_actions": [_action_signature(action) for action in memla_plan.actions],
            "plan_latency_ms": plan_latency_ms,
            "answered": bool(baseline_answer),
            "query": query,
            "answer_voice": str(answer_style.get("voice") or "").strip(),
            "answer_slice": slice_kind,
            "question_type": question_type,
            "needed_fields": needed_fields,
            "baseline_answer_latency_ms": baseline_answer_latency_ms,
            "baseline_answer": baseline_answer,
            "baseline_raw_answer": baseline_raw_answer,
            "baseline_generator": str(answer_style.get("generator") or "").strip(),
            "baseline_source_title": source_title,
            "baseline_source_url": source_url,
            "baseline_source_count": source_count,
            "baseline_relevant_chunk_ids": baseline_relevant_chunk_ids,
            "baseline_extracted_facts": baseline_extracted_facts,
            "baseline_missing_fields": baseline_missing_fields,
            "baseline_hard_check": baseline_hard_check,
            "evidence_chunk_count": len(evidence_chunks),
            "baseline_judgement": baseline_judgement,
            "needs_rescue": bool(needs_rescue),
            "rescue_attempted": rescue_attempted,
            "rescue_latency_ms": rescue_latency_ms,
            "rescued_answer": rescued_answer,
            "rescued_judgement": rescued_judgement,
            "rescue_why_better": str(rescue_payload.get("why_better") or "").strip(),
            "promotion_notes": [str(item).strip() for item in list(rescue_payload.get("promotion_notes") or []) if str(item).strip()],
            "rescued_relevant_chunk_ids": [str(item).strip() for item in list(rescue_payload.get("relevant_chunk_ids") or []) if str(item).strip()],
            "rescued_extracted_facts": [str(item).strip() for item in list(rescue_payload.get("extracted_facts") or []) if str(item).strip()],
            "missing_fields": [str(item).strip() for item in list(rescue_payload.get("missing_fields") or []) if str(item).strip()],
            "rescued_hard_check": rescued_hard_check,
            "promoted_lane": promoted_lane,
            "promoted_answer": promoted_answer,
            "promoted_overall": promoted_overall,
            "promoted_hard_check": promoted_hard_check,
            "improvement_delta": improvement_delta,
        }
        rows.append(row)
        if promoted_lane == "teacher_rescue":
            trace_rows.append(_build_web_teacher_trace_row(row))

    count = len(rows) or 1
    answered_count = sum(1 for row in rows if row.get("answered"))
    avg_plan_latency_ms = round(sum(float(row.get("plan_latency_ms") or 0.0) for row in rows) / count, 2)
    avg_answer_latency_ms = round(sum(float(row.get("baseline_answer_latency_ms") or 0.0) for row in rows) / count, 2)
    avg_rescue_latency_ms = round(sum(float(row.get("rescue_latency_ms") or 0.0) for row in rows) / count, 2)
    baseline_scores = [
        float(dict(row.get("baseline_judgement") or {}).get("overall") or 0.0)
        for row in rows
        if dict(row.get("baseline_judgement") or {}).get("overall")
    ]
    promoted_scores = [float(row.get("promoted_overall") or 0.0) for row in rows if float(row.get("promoted_overall") or 0.0) > 0.0]
    avg_baseline_overall = round(sum(baseline_scores) / len(baseline_scores), 4) if baseline_scores else 0.0
    avg_promoted_overall = round(sum(promoted_scores) / len(promoted_scores), 4) if promoted_scores else 0.0
    avg_improvement = round(sum(float(row.get("improvement_delta") or 0.0) for row in rows) / count, 4)
    hard_applicable_rows = [row for row in rows if bool(dict(row.get("promoted_hard_check") or {}).get("applicable"))]
    baseline_hard_pass_count = sum(1 for row in rows if bool(dict(row.get("baseline_hard_check") or {}).get("passed")))
    promoted_hard_pass_count = sum(1 for row in rows if bool(dict(row.get("promoted_hard_check") or {}).get("passed")))
    hard_pass_rate = round(promoted_hard_pass_count / len(hard_applicable_rows), 4) if hard_applicable_rows else 0.0

    return {
        "generated_ts": int(time.time()),
        "cases_path": str(Path(cases_path).resolve()),
        "case_ids": [case.case_id for case in cases],
        "limit": limit,
        "memla_model": memla_model,
        "memla_provider": "" if memla_client is None else str(getattr(memla_client, "provider", "") or ""),
        "teacher_model": teacher_model,
        "teacher_provider": "" if teacher_client is None else str(getattr(teacher_client, "provider", "") or ""),
        "judge_model": resolved_judge_model,
        "judge_provider": "" if judge_client is None else str(getattr(judge_client, "provider", "") or ""),
        "cases": len(rows),
        "cases_requested": len(cases),
        "failed_case_count": len(failed_cases),
        "answered_count": answered_count,
        "avg_plan_latency_ms": avg_plan_latency_ms,
        "avg_answer_latency_ms": avg_answer_latency_ms,
        "avg_rescue_latency_ms": avg_rescue_latency_ms,
        "avg_baseline_overall": avg_baseline_overall,
        "avg_promoted_overall": avg_promoted_overall,
        "avg_improvement": avg_improvement,
        "hard_applicable_count": len(hard_applicable_rows),
        "baseline_hard_pass_count": baseline_hard_pass_count,
        "promoted_hard_pass_count": promoted_hard_pass_count,
        "hard_pass_rate": hard_pass_rate,
        "rescue_threshold": int(rescue_threshold),
        "rescued_count": rescued_count,
        "improved_count": improved_count,
        "promoted_rescue_count": promoted_rescue_count,
        "trace_row_count": len(trace_rows),
        "judged_count": judged_count,
        "memla_model_call_count": memla_model_calls,
        "memla_heuristic_hit_count": memla_heuristic_hits,
        "rows": rows,
        "trace_rows": trace_rows,
        "failed_cases": failed_cases,
    }


def render_web_answer_benchmark_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Web Answer Benchmark",
        "",
        f"- Memla provider: `{report.get('memla_provider', '')}`",
        f"- Memla model: `{report.get('memla_model', '')}`",
        f"- Teacher judge: `{report.get('judge_model', '') or 'disabled'}`",
        f"- Cases completed: `{report.get('cases', 0)}` / `{report.get('cases_requested', 0)}`",
        "",
        "## Summary",
        "",
        f"- Answer rate: `{report.get('answer_rate', 0.0)}`",
        f"- Avg plan latency: `{report.get('avg_plan_latency_ms', 0.0)} ms`",
        f"- Avg answer latency: `{report.get('avg_answer_latency_ms', 0.0)} ms`",
        f"- Avg source count: `{report.get('avg_source_count', 0.0)}`",
        f"- Avg teacher overall: `{report.get('avg_teacher_overall', 0.0)}`",
        f"- Hard pass rate: `{report.get('hard_pass_rate', 0.0)}` ({report.get('hard_passed_count', 0)}/{report.get('hard_applicable_count', 0)})",
        f"- Memla model calls: `{report.get('memla_model_call_count', 0)}`",
        f"- Memla heuristic hits: `{report.get('memla_heuristic_hit_count', 0)}`",
        f"- Model-rendered answers: `{report.get('model_answer_count', 0)}`",
    ]
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for failure in report["failed_cases"]:
            lines.append(f"- `{failure.get('case_id', '')}` [{failure.get('error_type', '')}] {failure.get('message', '')}".rstrip())
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        teacher = dict(row.get("teacher_judgement") or {})
        lines.extend(
            [
                f"### {row.get('case_id', '')}",
                "",
                f"- Prompt: `{row.get('prompt', '')}`",
                f"- Query: `{row.get('query', '')}`",
                f"- Answered: `{row.get('answered', False)}`",
                f"- Voice/slice: `{row.get('answer_voice', '')}` / `{row.get('answer_slice', '')}`",
                f"- Plan source/actions: `{row.get('plan_source', '')}` / `{', '.join(row.get('plan_actions', []))}`",
                f"- Source: `{row.get('source_title', '')}`",
                f"- Answer: {row.get('answer', '')}",
            ]
        )
        if teacher:
            lines.extend(
                [
                    f"- Teacher overall: `{teacher.get('overall', 0)}`",
                    f"- Teacher coaching: {teacher.get('coaching', '')}",
                ]
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def render_web_teacher_loop_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Web Teacher Loop V1",
        "",
        f"- Memla provider: `{report.get('memla_provider', '')}`",
        f"- Memla model: `{report.get('memla_model', '')}`",
        f"- Teacher model: `{report.get('teacher_model', '') or 'disabled'}`",
        f"- Judge model: `{report.get('judge_model', '') or 'disabled'}`",
        f"- Cases completed: `{report.get('cases', 0)}` / `{report.get('cases_requested', 0)}`",
        "",
        "## Summary",
        "",
        f"- Avg plan latency: `{report.get('avg_plan_latency_ms', 0.0)} ms`",
        f"- Avg baseline answer latency: `{report.get('avg_answer_latency_ms', 0.0)} ms`",
        f"- Avg rescue latency: `{report.get('avg_rescue_latency_ms', 0.0)} ms`",
        f"- Avg baseline overall: `{report.get('avg_baseline_overall', 0.0)}`",
                f"- Avg promoted overall: `{report.get('avg_promoted_overall', 0.0)}`",
                f"- Avg improvement: `{report.get('avg_improvement', 0.0)}`",
                f"- Hard pass rate: `{report.get('hard_pass_rate', 0.0)}` ({report.get('promoted_hard_pass_count', 0)}/{report.get('hard_applicable_count', 0)})",
                f"- Rescued answers: `{report.get('rescued_count', 0)}`",
                f"- Improved answers: `{report.get('improved_count', 0)}`",
                f"- Promoted rescue rows: `{report.get('promoted_rescue_count', 0)}`",
        f"- Trace rows ready: `{report.get('trace_row_count', 0)}`",
    ]
    if report.get("failed_cases"):
        lines.extend(["", "## Failed cases", ""])
        for failure in report["failed_cases"]:
            lines.append(f"- `{failure.get('case_id', '')}` [{failure.get('error_type', '')}] {failure.get('message', '')}".rstrip())
    lines.extend(["", "## Case rows", ""])
    for row in report.get("rows", []):
        baseline_judgement = dict(row.get("baseline_judgement") or {})
        rescued_judgement = dict(row.get("rescued_judgement") or {})
        lines.extend(
            [
                f"### {row.get('case_id', '')}",
                "",
                f"- Prompt: `{row.get('prompt', '')}`",
                f"- Query: `{row.get('query', '')}`",
                f"- Slice: `{row.get('answer_slice', '')}`",
                f"- Hard pass: `{dict(row.get('promoted_hard_check') or {}).get('passed', False)}`",
                f"- Plan source/actions: `{row.get('plan_source', '')}` / `{', '.join(row.get('plan_actions', []))}`",
                f"- Baseline overall: `{baseline_judgement.get('overall', 0)}`",
                f"- Baseline answer: {row.get('baseline_answer', '')}",
                f"- Promoted lane: `{row.get('promoted_lane', '')}`",
                f"- Promoted answer: {row.get('promoted_answer', '')}",
            ]
        )
        if rescued_judgement or row.get("rescued_answer"):
            lines.extend(
                [
                    f"- Rescue overall: `{rescued_judgement.get('overall', 0)}`",
                    f"- Rescue why better: {row.get('rescue_why_better', '')}",
                ]
            )
        if baseline_judgement.get("coaching"):
            lines.append(f"- Teacher coaching: {baseline_judgement.get('coaching', '')}")
        if row.get("promotion_notes"):
            lines.append(f"- Promotion notes: {', '.join(row.get('promotion_notes', []))}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _fallback_web_training_rows() -> list[dict[str, Any]]:
    prompts = [
        ("weather", "whats the weather today"),
        ("weather", "what's the weather today in minneapolis"),
        ("weather", "is it raining tomorrow in minneapolis"),
        ("weather", "do i need an umbrella tomorrow in chicago"),
        ("weather", "what will the high be tomorrow in seattle"),
        ("news", "whats on the news"),
        ("news", "what's happening in the news about AI agents today?"),
        ("news", "what happened in the news today about OpenAI"),
        ("news", "what changed today in the tech world"),
        ("news", "what's the latest on electric cars today"),
        ("fact", "who is the ceo of openai"),
        ("fact", "who is the ceo of anthropic"),
        ("fact", "who created the iphone"),
        ("fact", "who invented the light bulb"),
        ("fact", "who built the saturn v rocket engines"),
        ("fact", "who founded apple"),
        ("fact", "who founded anthropic"),
        ("fact", "who created wikipedia"),
        ("fact", "when did wikipedia launch"),
        ("fact", "when was the iphone released"),
        ("fact", "why did humane ai pin fail"),
        ("fact", "what does stagflation mean"),
        ("fact", "what is agentic ai"),
        ("fact", "what is the difference between lcd and oled"),
        ("derived", "who created the iphone and how old were they"),
        ("derived", "who invented the light bulb and how old were they when they did it"),
        ("derived", "who founded apple and how old was steve jobs then"),
        ("derived", "who built the saturn v rocket engines and when was that"),
        ("compare", "which weather site is best for tomorrow's rain forecast"),
        ("compare", "what source best explains why humane ai pin failed"),
        ("compare", "which source best explains ai agents today"),
    ]
    rows: list[dict[str, Any]] = []
    for index, (category, prompt) in enumerate(prompts, start=1):
        rows.append(
            {
                "case_id": f"web_{category}_{index:03d}",
                "prompt": prompt,
                "expected_actions": [],
                "category": category,
                "source": "fallback",
            }
        )
    return rows


def _normalize_web_prompt_key(prompt: str) -> str:
    return " ".join(_normalize_goal_text(prompt).split())


def _safe_case_slug(text: str, *, limit: int = 36) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", _normalize_goal_text(text or "")).strip("_")
    return slug[:limit] or "web_case"


def _generate_web_questions_with_teacher(
    *,
    client: UniversalLLMClient,
    model: str,
    target_count: int,
    existing_prompts: list[str],
) -> list[dict[str, Any]]:
    generated: list[dict[str, Any]] = []
    seen = {_normalize_web_prompt_key(prompt) for prompt in existing_prompts if str(prompt).strip()}
    attempts = 0
    while len(generated) < max(int(target_count), 0) and attempts < 6:
        attempts += 1
        batch_size = min(24, max(int(target_count), 0) - len(generated))
        response = client.chat(
            model=model,
            temperature=0.6,
            messages=[
                ChatMessage(
                    role="system",
                    content=(
                        "You are generating everyday web questions for Memla's overnight web teacher loop. "
                        "These should sound like normal questions a person might ask Siri or a chat assistant on their phone. "
                        "Focus on bounded web-answer questions only. "
                        "Categories to cover: weather, news, people/companies, history/science, explainers, comparisons, and derived facts. "
                        "Avoid coding tasks, unsafe topics, medical diagnosis, legal advice, or requests that need app actions. "
                        "Return JSON only with key questions, where questions is an array of objects with keys prompt and category."
                    ),
                ),
                ChatMessage(
                    role="user",
                    content=(
                        f"Generate {batch_size} varied everyday web questions.\n"
                        "Avoid duplicates and avoid these prompts:\n"
                        + "\n".join(f"- {prompt}" for prompt in existing_prompts[:80])
                    ),
                ),
            ],
        )
        payload = _extract_first_json_object(response)
        items = payload.get("questions") or []
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            prompt = " ".join(str(item.get("prompt") or "").split()).strip()
            if not prompt:
                continue
            key = _normalize_web_prompt_key(prompt)
            if not key or key in seen:
                continue
            seen.add(key)
            generated.append(
                {
                    "prompt": prompt,
                    "category": " ".join(str(item.get("category") or "everyday").split()).strip().lower() or "everyday",
                    "source": "teacher_generated",
                }
            )
            if len(generated) >= max(int(target_count), 0):
                break
    return generated


def _compose_web_training_case_rows(
    *,
    seed_cases_path: str,
    question_count: int,
    teacher_client: UniversalLLMClient | None = None,
    teacher_model: str = "",
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    try:
        seed_cases = load_terminal_benchmark_cases(seed_cases_path)
    except Exception:
        seed_cases = []
    for case in seed_cases:
        key = _normalize_web_prompt_key(case.prompt)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "case_id": case.case_id,
                "prompt": case.prompt,
                "expected_actions": list(case.expected_actions),
                "category": "seed",
                "source": "seed",
            }
        )
    if teacher_client is not None and teacher_model and len(rows) < question_count:
        generated = _generate_web_questions_with_teacher(
            client=teacher_client,
            model=teacher_model,
            target_count=max(int(question_count), 0) - len(rows),
            existing_prompts=[str(row.get("prompt") or "").strip() for row in rows],
        )
        for item in generated:
            prompt = str(item.get("prompt") or "").strip()
            key = _normalize_web_prompt_key(prompt)
            if not key or key in seen:
                continue
            seen.add(key)
            rows.append(
                {
                    "case_id": f"web_teacher_{len(rows)+1:03d}_{_safe_case_slug(prompt)}",
                    "prompt": prompt,
                    "expected_actions": [],
                    "category": str(item.get("category") or "everyday").strip(),
                    "source": "teacher_generated",
                }
            )
    fallback_rows = _fallback_web_training_rows()
    for item in fallback_rows:
        if len(rows) >= max(int(question_count), 0):
            break
        prompt = str(item.get("prompt") or "").strip()
        key = _normalize_web_prompt_key(prompt)
        if not key or key in seen:
            continue
        seen.add(key)
        rows.append(dict(item))
    return rows[: max(int(question_count), 0)]


def _write_web_training_cases(path: str, rows: list[dict[str, Any]]) -> None:
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for row in rows:
        payload = {
            "case_id": str(row.get("case_id") or "").strip(),
            "prompt": str(row.get("prompt") or "").strip(),
            "expected_actions": [str(item).strip() for item in list(row.get("expected_actions") or []) if str(item).strip()],
            "category": str(row.get("category") or "").strip(),
            "source": str(row.get("source") or "").strip(),
        }
        lines.append(json.dumps(payload, ensure_ascii=True))
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def run_web_overnight_loop(
    *,
    out_dir: str,
    seed_cases_path: str,
    question_count: int,
    memla_model: str,
    memla_provider: str = "",
    memla_base_url: str = "",
    teacher_model: str = "",
    teacher_provider: str = "",
    teacher_base_url: str = "",
    judge_model: str = "",
    judge_provider: str = "",
    judge_base_url: str = "",
    temperature: float = 0.1,
    heuristic_only: bool = False,
    max_rounds: int = 4,
    benchmark_every: int = 1,
    target_overall: float = 4.25,
    target_hard_pass_rate: float = 0.0,
    allowed_rescues: int = 2,
    patience: int = 2,
    min_delta: float = 0.05,
    rescue_threshold: int = 4,
    repo_root: str = "",
) -> dict[str, Any]:
    root = Path(repo_root or os.getcwd()).resolve()
    output_root = Path(out_dir).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    teacher_client = build_llm_client(
        provider=teacher_provider or memla_provider or None,
        base_url=teacher_base_url or memla_base_url or None,
    ) if teacher_model else None
    case_rows = _compose_web_training_case_rows(
        seed_cases_path=seed_cases_path,
        question_count=question_count,
        teacher_client=teacher_client,
        teacher_model=teacher_model,
    )
    cases_path = output_root / "web_everyday_cases.jsonl"
    _write_web_training_cases(str(cases_path), case_rows)

    initial_benchmark = run_web_answer_benchmark(
        cases_path=str(cases_path),
        memla_model=memla_model,
        memla_provider=memla_provider,
        memla_base_url=memla_base_url,
        judge_model=judge_model,
        judge_provider=judge_provider,
        judge_base_url=judge_base_url,
        temperature=temperature,
        heuristic_only=heuristic_only,
    )

    best_score = float(initial_benchmark.get("avg_teacher_overall") or 0.0)
    best_round = 0
    stale_rounds = 0
    stop_reason = "max_rounds"
    all_trace_rows: list[dict[str, Any]] = []
    rounds: list[dict[str, Any]] = []
    combined_trace_path = output_root / "web_teacher_trace_bank.jsonl"
    policy_bank_path = (root / ".memla" / "web_policy_bank.json").resolve()
    policy_bank_md_path = policy_bank_path.with_suffix(".md")
    latest_benchmark = initial_benchmark

    for round_index in range(1, max(int(max_rounds), 0) + 1):
        teacher_report = run_web_teacher_loop(
            cases_path=str(cases_path),
            memla_model=memla_model,
            memla_provider=memla_provider,
            memla_base_url=memla_base_url,
            teacher_model=teacher_model,
            teacher_provider=teacher_provider,
            teacher_base_url=teacher_base_url,
            judge_model=judge_model,
            judge_provider=judge_provider,
            judge_base_url=judge_base_url,
            temperature=temperature,
            heuristic_only=heuristic_only,
            rescue_threshold=rescue_threshold,
        )
        round_dir = output_root / f"round_{round_index:02d}"
        round_dir.mkdir(parents=True, exist_ok=True)
        (round_dir / "web_teacher_loop_report.json").write_text(json.dumps(teacher_report, indent=2), encoding="utf-8")
        (round_dir / "web_teacher_loop_report.md").write_text(render_web_teacher_loop_markdown(teacher_report), encoding="utf-8")
        trace_rows = [dict(row) for row in list(teacher_report.get("trace_rows") or []) if isinstance(row, dict)]
        if trace_rows:
            all_trace_rows.extend(trace_rows)
        combined_trace_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=True) for row in all_trace_rows) + ("\n" if all_trace_rows else ""),
            encoding="utf-8",
        )

        policy_rows_used = 0
        if all_trace_rows:
            policy_report = distill_web_policy_bank(trace_bank_path=str(combined_trace_path), min_improvement=0.0)
            policy_bank_path.parent.mkdir(parents=True, exist_ok=True)
            policy_bank_path.write_text(json.dumps(policy_report, indent=2), encoding="utf-8")
            policy_bank_md_path.write_text(render_web_policy_bank_markdown(policy_report), encoding="utf-8")
            policy_rows_used = int(policy_report.get("rows_used") or 0)

        benchmark_report: dict[str, Any] = {}
        if max(int(benchmark_every), 1) == 1 or round_index % max(int(benchmark_every), 1) == 0:
            benchmark_report = run_web_answer_benchmark(
                cases_path=str(cases_path),
                memla_model=memla_model,
                memla_provider=memla_provider,
                memla_base_url=memla_base_url,
                judge_model=judge_model,
                judge_provider=judge_provider,
                judge_base_url=judge_base_url,
                temperature=temperature,
                heuristic_only=heuristic_only,
            )
            latest_benchmark = benchmark_report
        current_score = float((benchmark_report or latest_benchmark).get("avg_teacher_overall") or 0.0)
        if current_score > best_score + float(min_delta):
            best_score = current_score
            best_round = round_index
            stale_rounds = 0
        else:
            stale_rounds += 1

        round_summary = {
            "round": round_index,
            "teacher_avg_promoted": float(teacher_report.get("avg_promoted_overall") or 0.0),
            "teacher_avg_baseline": float(teacher_report.get("avg_baseline_overall") or 0.0),
            "promoted_rescue_count": int(teacher_report.get("promoted_rescue_count") or 0),
            "trace_row_count": int(teacher_report.get("trace_row_count") or 0),
            "policy_rows_used": policy_rows_used,
            "benchmark_avg_teacher_overall": current_score,
            "benchmark_hard_pass_rate": float((benchmark_report or latest_benchmark).get("hard_pass_rate") or 0.0),
            "benchmark_answer_rate": float((benchmark_report or latest_benchmark).get("answer_rate") or 0.0),
            "benchmark_avg_answer_latency_ms": float((benchmark_report or latest_benchmark).get("avg_answer_latency_ms") or 0.0),
        }
        rounds.append(round_summary)

        current_hard_pass_rate = float((benchmark_report or latest_benchmark).get("hard_pass_rate") or 0.0)
        hard_target_met = float(target_hard_pass_rate) <= 0.0 or current_hard_pass_rate >= float(target_hard_pass_rate)
        if (
            current_score >= float(target_overall)
            and hard_target_met
            and int(teacher_report.get("promoted_rescue_count") or 0) <= int(allowed_rescues)
        ):
            stop_reason = "target_reached"
            break
        if int(teacher_report.get("trace_row_count") or 0) == 0 and current_score >= float(target_overall) and hard_target_met:
            stop_reason = "no_rescue_needed"
            break
        if stale_rounds >= max(int(patience), 1):
            stop_reason = "plateau"
            break

    return {
        "generated_ts": int(time.time()),
        "seed_cases_path": str(Path(seed_cases_path).resolve()),
        "cases_path": str(cases_path),
        "question_count_requested": int(question_count),
        "question_count_actual": len(case_rows),
        "memla_model": memla_model,
        "memla_provider": memla_provider,
        "teacher_model": teacher_model,
        "teacher_provider": teacher_provider or memla_provider,
        "judge_model": judge_model,
        "judge_provider": judge_provider or teacher_provider or memla_provider,
        "target_overall": float(target_overall),
        "target_hard_pass_rate": float(target_hard_pass_rate),
        "allowed_rescues": int(allowed_rescues),
        "max_rounds": int(max_rounds),
        "benchmark_every": int(benchmark_every),
        "rescue_threshold": int(rescue_threshold),
        "initial_benchmark": initial_benchmark,
        "latest_benchmark": latest_benchmark,
        "best_score": best_score,
        "best_round": best_round,
        "stop_reason": stop_reason,
        "rounds": rounds,
        "combined_trace_bank": str(combined_trace_path),
        "policy_bank_path": str(policy_bank_path),
        "policy_bank_markdown_path": str(policy_bank_md_path),
    }


def render_web_overnight_loop_markdown(report: dict[str, Any]) -> str:
    initial = dict(report.get("initial_benchmark") or {})
    latest = dict(report.get("latest_benchmark") or {})
    lines = [
        "# Web Overnight Loop V1",
        "",
        f"- Cases path: `{report.get('cases_path', '')}`",
        f"- Questions requested/actual: `{report.get('question_count_requested', 0)}` / `{report.get('question_count_actual', 0)}`",
        f"- Memla model: `{report.get('memla_model', '')}`",
        f"- Teacher model: `{report.get('teacher_model', '')}`",
        f"- Judge model: `{report.get('judge_model', '')}`",
        f"- Stop reason: `{report.get('stop_reason', '')}`",
        f"- Best score: `{report.get('best_score', 0.0)}` at round `{report.get('best_round', 0)}`",
        f"- Target hard pass rate: `{report.get('target_hard_pass_rate', 0.0)}`",
        "",
        "## Initial benchmark",
        "",
        f"- Avg teacher overall: `{initial.get('avg_teacher_overall', 0.0)}`",
        f"- Hard pass rate: `{initial.get('hard_pass_rate', 0.0)}`",
        f"- Avg answer latency: `{initial.get('avg_answer_latency_ms', 0.0)} ms`",
        f"- Answer rate: `{initial.get('answer_rate', 0.0)}`",
        "",
        "## Latest benchmark",
        "",
        f"- Avg teacher overall: `{latest.get('avg_teacher_overall', 0.0)}`",
        f"- Hard pass rate: `{latest.get('hard_pass_rate', 0.0)}`",
        f"- Avg answer latency: `{latest.get('avg_answer_latency_ms', 0.0)} ms`",
        f"- Answer rate: `{latest.get('answer_rate', 0.0)}`",
        "",
        "## Rounds",
        "",
    ]
    for round_summary in list(report.get("rounds") or []):
        lines.extend(
            [
                f"### Round {round_summary.get('round', 0)}",
                "",
                f"- Teacher promoted overall: `{round_summary.get('teacher_avg_promoted', 0.0)}`",
                f"- Teacher rescue count: `{round_summary.get('promoted_rescue_count', 0)}`",
                f"- Trace rows: `{round_summary.get('trace_row_count', 0)}`",
                f"- Policy rows used: `{round_summary.get('policy_rows_used', 0)}`",
                f"- Benchmark overall: `{round_summary.get('benchmark_avg_teacher_overall', 0.0)}`",
                f"- Benchmark hard pass rate: `{round_summary.get('benchmark_hard_pass_rate', 0.0)}`",
                f"- Benchmark answer latency: `{round_summary.get('benchmark_avg_answer_latency_ms', 0.0)} ms`",
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


__all__ = [
    "BrowserSessionState",
    "TerminalAction",
    "TerminalPlan",
    "TerminalExecutionRecord",
    "TerminalExecutionResult",
    "TerminalScoutResult",
    "TerminalScoutStep",
    "TerminalStepExecution",
    "TerminalStepReport",
    "TerminalTransmutationCandidate",
    "build_llm_client",
    "build_raw_terminal_plan",
    "build_terminal_step_report",
    "build_terminal_plan",
    "execute_terminal_step",
    "execute_terminal_plan",
    "load_browser_session_state",
    "load_terminal_benchmark_cases",
    "render_terminal_benchmark_markdown",
    "render_terminal_execution_text",
    "render_terminal_plan_text",
    "render_terminal_scout_text",
    "render_terminal_step_execution_text",
    "render_terminal_step_report_text",
    "render_web_answer_benchmark_markdown",
    "render_web_overnight_loop_markdown",
    "render_web_teacher_loop_markdown",
    "run_terminal_benchmark",
    "run_terminal_scout",
    "run_web_answer_benchmark",
    "run_web_overnight_loop",
    "run_web_teacher_loop",
    "save_browser_session_state",
    "terminal_browser_state_path",
    "terminal_execution_to_dict",
    "terminal_model_default",
    "terminal_plan_to_dict",
    "terminal_scout_to_dict",
    "terminal_step_execution_to_dict",
    "terminal_step_report_to_dict",
    "terminal_trace_log_path",
]
