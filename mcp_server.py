"""
MCP server for Memla.

Exposes the memory system as MCP tools so any agent framework
(CrewAI, LangGraph, AutoGen, Claude Desktop, Cursor) can connect.

Usage:
    python mcp_server.py                                  # stdio (default)
    python mcp_server.py --transport http --port 8766     # HTTP
    python mcp_server.py --agent_id researcher            # custom identity
"""
from __future__ import annotations

import json
import os
import re
import secrets
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from fastmcp import FastMCP

from memory_system.memory.episode_log import EpisodeLog
from memory_system.memory.chunk_manager import ChunkManager
from memory_system.memory.llm_extractor import LLMChunkExtractor
from memory_system.middleware.ttt_layer import TTTLayer
from memory_system.ollama_client import ChatMessage, UniversalLLMClient

# ── Configuration (env vars or CLI args) ─────────────────────────

DB_PATH = os.environ.get("MEMORY_DB", "./memory.sqlite")
AGENT_ID = os.environ.get("MEMORY_AGENT_ID", "default")
OLLAMA_URL = os.environ.get(
    "OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
)
MODEL = os.environ.get("MEMORY_MODEL", "qwen3.5:4b")
ADAPTERS_DIR = os.environ.get("MEMORY_ADAPTERS_DIR", "./adapters")

BASE_SYSTEM = (
    "You are a helpful assistant with persistent memory.\n\n"
    "You may be given retrieved memory snippets. Use them when relevant.\n"
    "If you do not know, say so."
)

_USER_LINKS_DDL = """
CREATE TABLE IF NOT EXISTS user_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL,
    chunk_a_id INTEGER NOT NULL,
    chunk_b_id INTEGER NOT NULL,
    created_ts INTEGER NOT NULL,
    UNIQUE(user_id, chunk_a_id, chunk_b_id)
)
"""

_STOP = frozenset({
    "a","an","and","are","as","at","be","but","by","for","from","has","have",
    "he","her","his","i","in","is","it","its","me","my","not","of","on","or",
    "our","she","that","the","their","them","they","this","to","was","we",
    "were","with","you","your",
})


def _tok(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(t) >= 2 and t not in _STOP}


# ── Shared state ─────────────────────────────────────────────────

class _State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.log: EpisodeLog | None = None
        self.client: UniversalLLMClient | None = None
        self.ttt: TTTLayer | None = None
        self.agent_id = AGENT_ID
        self.model = MODEL
        self.session_id = ""
        self.history: list[ChatMessage] = []

    def ensure_init(self) -> None:
        if self.log is not None:
            return
        url = OLLAMA_URL.rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url

        self.session_id = f"sess_{int(time.time())}_{secrets.token_hex(3)}"
        self.log = EpisodeLog(DB_PATH)
        self.client = UniversalLLMClient(provider="ollama", base_url=url)
        ext = LLMChunkExtractor(client=self.client, model=self.model, temperature=0.0)
        cm = ChunkManager(self.log, llm_extractor=ext.extract)
        self.ttt = TTTLayer(episode_log=self.log, chunk_manager=cm)
        self.log._conn.execute(_USER_LINKS_DDL)
        self.log._conn.commit()


S = _State()


def _chunk_to_dict(c: Any) -> dict:
    return {
        "id": c.id, "type": c.chunk_type, "key": c.key,
        "text": c.text, "frequency": c.frequency_count,
    }


# ── MCP Server ───────────────────────────────────────────────────

mcp = FastMCP("Memla")


# ── Tools ────────────────────────────────────────────────────────

@mcp.tool()
def memory_retrieve(query: str, top_k: int = 12) -> str:
    """Search memories by semantic + keyword query.

    Returns the top-k most relevant memory chunks for this agent.
    Use this before responding to check what you already know.
    """
    S.ensure_init()
    chunks = S.ttt.chunks.retrieve(
        user_id=S.agent_id, query_text=query, k=top_k,
    )
    S.ttt.chunks.mark_recalled(chunks)
    return json.dumps([_chunk_to_dict(c) for c in chunks], indent=2)


@mcp.tool()
def memory_store(
    content: str,
    chunk_type: str = "fact",
    key: str = "",
) -> str:
    """Store a memory: a fact, decision, entity, or note.

    Use this to persist discoveries, conclusions, or important context
    so you (or other agents) can retrieve it later.

    chunk_type: one of "fact", "decision", "entity", "note"
    key: short identifier for deduplication (auto-generated if empty)
    """
    S.ensure_init()
    if not key:
        key = content[:80].lower().strip()
    cid = S.log.add_or_bump_chunk(
        session_id=S.session_id,
        user_id=S.agent_id,
        chunk_type=chunk_type,
        key=key,
        text=content,
        source_episode_id=None,
    )
    return json.dumps({"stored": True, "chunk_id": cid, "type": chunk_type, "key": key})


@mcp.tool()
def memory_link(chunk_a: int, chunk_b: int) -> str:
    """Connect two memory chunks — declares they are related.

    This persists the connection and fires a training signal that pulls
    the two chunks' embeddings closer, so future retrieval of one is
    more likely to also surface the other.

    Use this when you discover that two pieces of information are related
    but the system might not know it yet.
    """
    S.ensure_init()
    a, b = min(chunk_a, chunk_b), max(chunk_a, chunk_b)
    S.log._conn.execute(
        "INSERT OR IGNORE INTO user_links "
        "(user_id, chunk_a_id, chunk_b_id, created_ts) VALUES (?,?,?,?)",
        (S.agent_id, a, b, int(time.time())),
    )
    S.log._conn.commit()

    def _bg_train():
        try:
            from memory_system.adapters.gradient_pass import micro_gradient_pass
            from memory_system.middleware.context_builder import _get_lora_manager
            mgr = _get_lora_manager()
            if mgr is None:
                return
            all_c = S.log.fetch_recent_chunks(user_id=S.agent_id, limit=9999)
            ca = next((c for c in all_c if c.id == a), None)
            cb = next((c for c in all_c if c.id == b), None)
            if ca and cb:
                micro_gradient_pass(
                    manager=mgr, user_id=S.agent_id, query=ca.text,
                    retrieved_texts=[cb.text], candidate_texts=[ca.text, cb.text],
                    quality_signal=1.0,
                )
                micro_gradient_pass(
                    manager=mgr, user_id=S.agent_id, query=cb.text,
                    retrieved_texts=[ca.text], candidate_texts=[ca.text, cb.text],
                    quality_signal=1.0,
                )
        except Exception:
            pass
    threading.Thread(target=_bg_train, daemon=True).start()
    return json.dumps({"linked": True, "chunk_a": a, "chunk_b": b})


@mcp.tool()
def memory_unlink(chunk_a: int, chunk_b: int) -> str:
    """Remove a connection between two memory chunks."""
    S.ensure_init()
    a, b = min(chunk_a, chunk_b), max(chunk_a, chunk_b)
    S.log._conn.execute(
        "DELETE FROM user_links WHERE user_id=? AND chunk_a_id=? AND chunk_b_id=?",
        (S.agent_id, a, b),
    )
    S.log._conn.commit()
    return json.dumps({"unlinked": True, "chunk_a": a, "chunk_b": b})


@mcp.tool()
def memory_chat(
    message: str,
    pinned_ids: list[int] | None = None,
    model: str = "",
) -> str:
    """Full memory-augmented chat: retrieve context, call LLM, train retrieval.

    This runs the complete pipeline: retrieves relevant memories,
    builds a context-aware prompt, calls the LLM, scores which memories
    were actually used, and trains the retrieval model on the result.

    pinned_ids: optional list of chunk IDs to inject as highest-priority context
    model: override the default Ollama model for this call
    """
    S.ensure_init()
    import requests as http_req

    use_model = model or S.model
    if model and model != S.model:
        S.model = model
        ext = LLMChunkExtractor(client=S.client, model=model, temperature=0.0)
        S.ttt.chunks._llm_extractor = ext.extract

    with S.lock:
        artifacts = S.ttt.on_user_message(
            session_id=S.session_id, user_id=S.agent_id,
            user_text=message, base_system=BASE_SYSTEM, top_k=12,
        )

    system_prompt = artifacts.built.system_prompt
    if pinned_ids:
        all_chunks = S.log.fetch_recent_chunks(user_id=S.agent_id, limit=9999)
        pinned = [c for c in all_chunks if c.id in set(pinned_ids)]
        if pinned:
            sec = "\n\n=== PINNED CONTEXT (highest priority) ===\n"
            for c in pinned:
                sec += f"[{c.chunk_type}] {c.key}: {c.text}\n"
            sec += "=== END PINNED CONTEXT ===\n"
            system_prompt += sec

    messages = [
        ChatMessage(role="system", content=system_prompt),
        *S.history[-(20 * 2):],
        ChatMessage(role="user", content=message),
    ]

    url = OLLAMA_URL.rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url
    payload = {
        "model": use_model,
        "messages": [{"role": m.role, "content": m.content} for m in messages],
        "stream": False,
        "options": {"temperature": 0.2},
    }
    resp = http_req.post(f"{url}/api/chat", json=payload, timeout=600)
    resp.raise_for_status()
    assistant_text = resp.json().get("message", {}).get("content", "").strip()

    S.history.append(ChatMessage(role="user", content=message))
    S.history.append(ChatMessage(role="assistant", content=assistant_text))

    with S.lock:
        S.ttt.on_assistant_message(
            session_id=S.session_id, user_id=S.agent_id,
            assistant_text=assistant_text,
            meta={"retrieved_chunk_ids": [c.id for c in artifacts.retrieved]},
        )

    retrieved = [_chunk_to_dict(c) for c in artifacts.retrieved]
    return json.dumps({
        "response": assistant_text,
        "retrieved_chunks": retrieved,
        "model": use_model,
    }, indent=2)


@mcp.tool()
def memory_feedback(is_positive: bool) -> str:
    """Give feedback on the last memory_chat interaction.

    is_positive=true: the retrieved memories were helpful (reinforces retrieval)
    is_positive=false: the retrieved memories were wrong (corrects retrieval)
    """
    S.ensure_init()
    ok = S.ttt.explicit_feedback(is_positive=is_positive)
    return json.dumps({"feedback_applied": ok, "signal": "positive" if is_positive else "negative"})


@mcp.tool()
<<<<<<< HEAD
=======
def memory_expand(node_id: int) -> str:
    """Expand a summary node to see its child memories.

    When you retrieve a summary chunk and need the granular details
    it was consolidated from, call this with the summary's chunk ID.
    Returns the original detailed memories that were folded into it.
    """
    S.ensure_init()
    children = S.log.fetch_children(node_id)
    if not children:
        return json.dumps({"node_id": node_id, "children": [], "note": "Not a summary node."})
    return json.dumps({
        "node_id": node_id,
        "children": [_chunk_to_dict(c) for c in children],
        "count": len(children),
    }, indent=2)


@mcp.tool()
def memory_consolidate() -> str:
    """Consolidate similar memories into summary nodes.

    Clusters similar chunks, creates summary nodes, and demotes
    the originals so they don't clog the retrieval window.
    Call this when the memory store grows large.
    """
    S.ensure_init()
    from memory_system.memory.consolidator import consolidate
    summary_ids = consolidate(S.log, user_id=S.agent_id)
    return json.dumps({
        "consolidated": True,
        "summary_nodes_created": len(summary_ids),
        "summary_ids": summary_ids,
    })


@mcp.tool()
>>>>>>> import-yosazo
def memory_merge() -> str:
    """Merge retrieval adapters across all agents sharing this database.

    Extracts shared retrieval directions via PCA, projects them into a
    safe subspace (EWC-protected), and writes a shared base update.
    Every agent benefits from what any agent learned.

    Call this periodically (e.g. after a batch of tasks completes).
    """
    S.ensure_init()
    try:
        from memory_system.adapters.lora_manager import RetrievalLoRAManager
        from memory_system.adapters.merge import AdapterMerger

        base = os.path.abspath(ADAPTERS_DIR)
        user_ids = []
        if os.path.isdir(base):
            for name in os.listdir(base):
                if name == "shared_base":
                    continue
                d = os.path.join(base, name, "retrieval_adapter")
                if os.path.isdir(d):
                    user_ids.append(name)

        if not user_ids:
            return json.dumps({"merged": False, "reason": "no agent adapters found"})

        mgr = RetrievalLoRAManager(adapters_dir=ADAPTERS_DIR)
        mgr.ensure_loaded()
        merger = AdapterMerger(adapters_dir=ADAPTERS_DIR)
        report = merger.run_merge(user_ids=user_ids, base_model=mgr._model)
        return json.dumps({"merged": True, "report": report.to_dict()}, indent=2)
    except Exception as e:
        return json.dumps({"merged": False, "error": str(e)})


# ── Resources ────────────────────────────────────────────────────

@mcp.resource("memory://graph")
def memory_graph() -> str:
    """The full memory graph: nodes, auto-computed edges, and user-drawn links.

    Agents can inspect the knowledge structure to understand
    what memories exist and how they relate.
    """
    S.ensure_init()
    chunks = S.log.fetch_recent_chunks(user_id=S.agent_id, limit=200)
    if not chunks:
        return json.dumps({"nodes": [], "edges": [], "user_links": []})

    nodes = []
    ti: dict[str, set[int]] = defaultdict(set)
    for i, c in enumerate(chunks):
        for t in _tok(c.text + " " + c.key):
            ti[t].add(i)
        nodes.append(_chunk_to_dict(c))

    ew: dict[tuple[int, int], int] = defaultdict(int)
    for tok, ids in ti.items():
        idx = list(ids)
        if len(idx) > 20:
            continue
        for j in range(len(idx)):
            for k in range(j + 1, len(idx)):
                pair = (min(idx[j], idx[k]), max(idx[j], idx[k]))
                ew[pair] += 1

    edges = [
        {"source": chunks[a].id, "target": chunks[b].id, "weight": w}
        for (a, b), w in ew.items() if w >= 2
    ]

    rows = S.log._conn.execute(
        "SELECT chunk_a_id, chunk_b_id FROM user_links WHERE user_id=?",
        (S.agent_id,),
    ).fetchall()
    user_links = [{"source": r[0], "target": r[1]} for r in rows]

    return json.dumps({"nodes": nodes, "edges": edges, "user_links": user_links}, indent=2)


@mcp.resource("memory://chunks/{agent_id}")
def memory_chunks_for_agent(agent_id: str) -> str:
    """All memory chunks for a specific agent.

    Lets agents inspect each other's memory stores to understand
    what another agent has learned.
    """
    S.ensure_init()
    chunks = S.log.fetch_recent_chunks(user_id=agent_id, limit=200)
    return json.dumps([_chunk_to_dict(c) for c in chunks], indent=2)


# ── Entry point ──────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="Memla MCP Server")
    p.add_argument("--transport", choices=["stdio", "http"], default="stdio")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--agent_id", default=os.environ.get("MEMORY_AGENT_ID", "default"))
    p.add_argument("--model", default=os.environ.get("MEMORY_MODEL", "qwen3.5:4b"))
    p.add_argument("--db", default=os.environ.get("MEMORY_DB", "./memory.sqlite"))
    p.add_argument("--ollama_url", default=os.environ.get(
        "OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    ))
    a = p.parse_args()

    # Override globals from CLI args
    globals()["DB_PATH"] = a.db
    globals()["AGENT_ID"] = a.agent_id
    globals()["MODEL"] = a.model
    globals()["OLLAMA_URL"] = a.ollama_url
    S.agent_id = a.agent_id
    S.model = a.model

    if a.transport == "http":
        mcp.run(transport="streamable-http", port=a.port)
    else:
        mcp.run()
