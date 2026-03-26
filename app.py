"""
Web UI for Memla.

Usage:
    python app.py [--port 8765] [--model qwen3.5:4b]

Opens http://localhost:8765 in your browser.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import threading
import time
import webbrowser
from collections import defaultdict
from pathlib import Path
from typing import Optional

import requests as http_req
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from memory_system.memory.episode_log import EpisodeLog
from memory_system.memory.chunk_manager import ChunkManager
from memory_system.memory.llm_extractor import LLMChunkExtractor
from memory_system.memory.lazy_import import LazyImporter
from memory_system.middleware.ttt_layer import TTTLayer
from memory_system.ollama_client import ChatMessage, UniversalLLMClient
from memory_system.distillation.coding_log import CodingTraceLog
from memory_system.distillation.workspace_capture import capture_workspace_state
from memory_system.sync import pull_if_enabled, push_if_enabled
from memory_system.reasoning.trajectory import (
    TrajectoryLog, Trajectory, TrajectoryStep,
    inject_reasoning_prompt, parse_trajectory, has_trajectory_format,
    extract_output_text,
)

BASE_SYSTEM = (
    "You are a helpful assistant running locally.\n\n"
    "You may be given retrieved memory snippets about the user. Use them when relevant.\n"
    "If the user asks about specific details from prior context, answer using retrieved memory.\n"
    "If you do not know, say so and ask a precise question to resolve ambiguity."
)

_STOP = frozenset({
    "a","an","and","are","as","at","be","but","by","for","from","has","have",
    "he","her","his","i","in","is","it","its","me","my","not","of","on","or",
    "our","she","that","the","their","them","they","this","to","was","we",
    "were","with","you","your",
})


def _tok(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(t) >= 2 and t not in _STOP}


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


class State:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.db_path = "./memory.sqlite"
        self.user_id = "default"
        self.ollama_url = "http://127.0.0.1:11434"
        self.model = "qwen3.5:4b"
        self.session_id = ""
        self.history: list[ChatMessage] = []
        self.log: Optional[EpisodeLog] = None
        self.client: Optional[UniversalLLMClient] = None
        self.ttt: Optional[TTTLayer] = None
        self.traj_log: Optional[TrajectoryLog] = None
        self.lazy: Optional[LazyImporter] = None
        self.last_trajectory_id: Optional[int] = None
        self.coding_log: Optional[CodingTraceLog] = None
        self.last_coding_trace_id: Optional[int] = None

    def init(self, *, model: str, db: str, user_id: str, ollama_url: str) -> None:
        self.model = model
        self.db_path = db
        self.user_id = user_id
        url = ollama_url.rstrip("/")
        if not url.startswith("http"):
            url = "http://" + url
        self.ollama_url = url
        self.session_id = f"sess_{int(time.time())}_{secrets.token_hex(3)}"
        self.history = []

        pulled = pull_if_enabled()
        if pulled is not None:
            print(f"[sync] pulled {pulled} files from cloud")

        self.log = EpisodeLog(db)
        self.client = UniversalLLMClient(provider="ollama", base_url=self.ollama_url)
        ext = LLMChunkExtractor(client=self.client, model=model, temperature=0.0)
        cm = ChunkManager(self.log, llm_extractor=ext.extract)
        self.ttt = TTTLayer(episode_log=self.log, chunk_manager=cm)

        self.log._conn.execute(_USER_LINKS_DDL)
        self.log._conn.commit()
        self.traj_log = TrajectoryLog(self.log._conn)
        self.coding_log = CodingTraceLog(self.log._conn)
        self.lazy = LazyImporter(self.log)

    def set_model(self, model: str) -> None:
        self.model = model
        if self.client and self.ttt:
            ext = LLMChunkExtractor(client=self.client, model=model, temperature=0.0)
            self.ttt.chunks._llm_extractor = ext.extract

    def new_session(self) -> None:
        self.session_id = f"sess_{int(time.time())}_{secrets.token_hex(3)}"
        self.history.clear()
        if self.ttt:
            self.ttt.clear_turn_state()

    def fetch_user_links(self) -> list[dict]:
        if not self.log:
            return []
        rows = self.log._conn.execute(
            "SELECT chunk_a_id, chunk_b_id FROM user_links WHERE user_id=?",
            (self.user_id,),
        ).fetchall()
        return [{"source": r[0], "target": r[1]} for r in rows]

    def chunk_by_id(self, cid: int):
        all_c = self.log.fetch_recent_chunks(user_id=self.user_id, limit=9999)
        return next((c for c in all_c if c.id == cid), None)


S = State()

# ── Pydantic models ──────────────────────────────────────────────


class ChatReq(BaseModel):
    message: str
    model: str = ""
    pinned_ids: list[int] = []


class FeedbackReq(BaseModel):
    is_positive: bool


class LinkReq(BaseModel):
    chunk_a: int
    chunk_b: int


class TraceTestReq(BaseModel):
    trace_id: int
    command: str = ""
    status: str
    summary: str = ""


# ── FastAPI ──────────────────────────────────────────────────────

app = FastAPI(title="Memla")
STATIC = Path(__file__).parent / "static"


@app.get("/")
def index():
    return HTMLResponse((STATIC / "index.html").read_text("utf-8"))


@app.get("/api/models")
def models():
    try:
        r = http_req.get(f"{S.ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        ms = r.json().get("models", [])
        return {
            "models": [{"name": m["name"], "size": m.get("size", 0)} for m in ms],
            "current": S.model,
        }
    except Exception as e:
        return {"models": [], "current": S.model, "error": str(e)}


@app.get("/api/state")
def app_state():
    n = 0
    if S.log:
        try:
            n = len(S.log.fetch_recent_chunks(user_id=S.user_id, limit=9999))
        except Exception:
            pass
    return {
        "session_id": S.session_id,
        "user_id": S.user_id,
        "model": S.model,
        "chunks": n,
        "turns": len(S.history) // 2,
    }


@app.post("/api/chat")
def chat(req: ChatReq):
    if not S.ttt or not S.client:
        return JSONResponse({"error": "System not initialized"}, 500)
    if req.model and req.model != S.model:
        S.set_model(req.model)

    msg = req.message.strip()
    if not msg:
        return JSONResponse({"error": "Empty message"}, 400)

    if S.lazy:
        S.lazy.on_demand_extract(query=msg, user_id=S.user_id, session_id=S.session_id)

    with S.lock:
        artifacts = S.ttt.on_user_message(
            session_id=S.session_id, user_id=S.user_id,
            user_text=msg, base_system=BASE_SYSTEM, top_k=12,
        )

    retrieved = [
        {"id": c.id, "type": c.chunk_type, "key": c.key,
         "text": c.text, "freq": c.frequency_count}
        for c in artifacts.retrieved
    ]

    system_prompt = inject_reasoning_prompt(artifacts.built.system_prompt)
    if req.pinned_ids:
        all_chunks = S.log.fetch_recent_chunks(user_id=S.user_id, limit=9999)
        pinned = [c for c in all_chunks if c.id in set(req.pinned_ids)]
        if pinned:
            sec = "\n\n=== USER-PINNED CONTEXT (highest priority) ===\n"
            sec += (
                "The user explicitly selected these memories as the lens "
                "for their question. Ground your response primarily in them:\n\n"
            )
            for c in pinned:
                sec += f"[{c.chunk_type}] {c.key}: {c.text}\n"
            sec += "\n=== END PINNED CONTEXT ===\n"
            system_prompt += sec

    messages = [
        ChatMessage(role="system", content=system_prompt),
        *S.history[-(20 * 2):],
        ChatMessage(role="user", content=msg),
    ]

    def generate():
        yield f"data: {json.dumps({'type': 'retrieved', 'chunks': retrieved})}\n\n"
        full = ""
        try:
            payload = {
                "model": S.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": True,
                "options": {"temperature": 0.2},
            }
            with http_req.post(
                f"{S.ollama_url}/api/chat", json=payload, stream=True, timeout=600,
            ) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    chunk = (data.get("message") or {}).get("content", "")
                    if chunk:
                        full += chunk
                        yield f"data: {json.dumps({'type': 'chunk', 'text': chunk})}\n\n"
                    if data.get("done"):
                        break
        except Exception as e:
            if not full:
                yield f"data: {json.dumps({'type': 'error', 'text': str(e)})}\n\n"
                return

        S.history.append(ChatMessage(role="user", content=msg))
        S.history.append(ChatMessage(role="assistant", content=full.strip()))

        with S.lock:
            S.ttt.on_assistant_message(
                session_id=S.session_id, user_id=S.user_id,
                assistant_text=full,
                meta={"retrieved_chunk_ids": [c.id for c in artifacts.retrieved]},
            )

        traj_data = None
        if has_trajectory_format(full) and S.traj_log:
            steps = parse_trajectory(full)
            if steps:
                traj = Trajectory(
                    session_id=S.session_id,
                    user_id=S.user_id,
                    user_query=msg,
                    steps=steps,
                    ts=int(time.time()),
                )
                traj_id = S.traj_log.save(traj)
                S.last_trajectory_id = traj_id
                traj_data = {"id": traj_id, "steps": [
                    {"type": s.step_type, "content": s.content,
                     "tool": s.tool_name, "index": s.index}
                    for s in steps
                ]}

        done_payload = {"type": "done"}
        if traj_data:
            done_payload["trajectory"] = traj_data
        if S.coding_log and S.client:
            try:
                S.last_coding_trace_id = S.coding_log.save_trace(
                    session_id=S.session_id,
                    user_id=S.user_id,
                    provider=S.client.provider,
                    model=S.model,
                    repo_root=str(Path.cwd()),
                    task_text=msg,
                    system_prompt=system_prompt,
                    messages=[{"role": m.role, "content": m.content} for m in messages],
                    retrieved_chunk_ids=[c.id for c in artifacts.retrieved],
                    trajectory_id=S.last_trajectory_id,
                    assistant_text=full.strip(),
                    meta={"surface": "web_app"},
                )
                done_payload["coding_trace_id"] = S.last_coding_trace_id
            except Exception:
                pass
        yield f"data: {json.dumps(done_payload)}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/feedback")
def feedback(req: FeedbackReq):
    if not S.ttt:
        return {"ok": False}
    ok = S.ttt.explicit_feedback(is_positive=req.is_positive)
    if ok and S.coding_log and S.last_coding_trace_id is not None:
        try:
            snapshot = capture_workspace_state(Path.cwd())
            S.coding_log.update_trace_artifacts(
                trace_id=S.last_coding_trace_id,
                touched_files=snapshot["touched_files"],
                patch_text=snapshot["patch_text"],
                meta={"workspace_vcs": snapshot["vcs"]},
            )
            S.coding_log.mark_feedback(
                trace_id=S.last_coding_trace_id,
                is_positive=req.is_positive,
                meta={"surface": "web_app"},
            )
        except Exception:
            pass
    return {"ok": ok}


@app.get("/api/coding_traces/candidates")
def coding_trace_candidates():
    if not S.coding_log:
        return {"traces": []}
    traces = S.coding_log.fetch_training_candidates(user_id=S.user_id, limit=50)
    return {
        "traces": [
            {
                "id": trace.id,
                "task_text": trace.task_text,
                "provider": trace.provider,
                "model": trace.model,
                "repo_root": trace.repo_root,
                "status": trace.status,
                "acceptance_score": trace.acceptance_score,
                "touched_files": trace.touched_files,
                "tests": trace.tests,
                "trajectory_id": trace.trajectory_id,
            }
            for trace in traces
        ]
    }


@app.post("/api/coding_traces/test_result")
def attach_trace_test_result(req: TraceTestReq):
    if not S.coding_log:
        return JSONResponse({"error": "Not initialized"}, 500)
    traces = S.coding_log.fetch_recent(user_id=S.user_id, limit=200)
    trace = next((item for item in traces if item.id == req.trace_id), None)
    if trace is None:
        return JSONResponse({"error": "Trace not found"}, 404)
    tests = list(trace.tests)
    tests.append(
        {
            "command": req.command.strip(),
            "status": req.status.strip(),
            "summary": req.summary.strip(),
            "ts": int(time.time()),
        }
    )
    S.coding_log.update_trace_artifacts(trace_id=req.trace_id, tests=tests)
    return {"ok": True, "trace_id": req.trace_id, "tests_count": len(tests)}


@app.post("/api/link")
def create_link(req: LinkReq):
    """User drew a connection between two memory nodes — persist + train."""
    if not S.log:
        return {"ok": False}
    a, b = min(req.chunk_a, req.chunk_b), max(req.chunk_a, req.chunk_b)
    S.log._conn.execute(
        "INSERT OR IGNORE INTO user_links "
        "(user_id, chunk_a_id, chunk_b_id, created_ts) VALUES (?,?,?,?)",
        (S.user_id, a, b, int(time.time())),
    )
    S.log._conn.commit()

    def _bg_train():
        try:
            from memory_system.adapters.gradient_pass import micro_gradient_pass
            from memory_system.middleware.context_builder import _get_lora_manager
            mgr = _get_lora_manager()
            if mgr is None:
                return
            ca, cb = S.chunk_by_id(a), S.chunk_by_id(b)
            if not ca or not cb:
                return
            micro_gradient_pass(
                manager=mgr, user_id=S.user_id, query=ca.text,
                retrieved_texts=[cb.text], candidate_texts=[ca.text, cb.text],
                quality_signal=1.0,
            )
            micro_gradient_pass(
                manager=mgr, user_id=S.user_id, query=cb.text,
                retrieved_texts=[ca.text], candidate_texts=[ca.text, cb.text],
                quality_signal=1.0,
            )
        except Exception:
            pass
    threading.Thread(target=_bg_train, daemon=True).start()
    return {"ok": True}


@app.post("/api/unlink")
def delete_link(req: LinkReq):
    """User removed a connection."""
    if not S.log:
        return {"ok": False}
    a, b = min(req.chunk_a, req.chunk_b), max(req.chunk_a, req.chunk_b)
    S.log._conn.execute(
        "DELETE FROM user_links WHERE user_id=? AND chunk_a_id=? AND chunk_b_id=?",
        (S.user_id, a, b),
    )
    S.log._conn.commit()
    return {"ok": True}


@app.post("/api/session")
def new_session():
    S.new_session()
    return {"session_id": S.session_id}


@app.get("/api/expand/{node_id}")
def expand_node(node_id: int):
    if not S.log:
        return {"children": []}
    children = S.log.fetch_children(node_id)
    return {
        "node_id": node_id,
        "children": [
            {"id": c.id, "type": c.chunk_type, "key": c.key,
             "text": c.text, "freq": c.frequency_count}
            for c in children
        ],
    }


@app.post("/api/consolidate")
def consolidate_memories():
    if not S.log:
        return JSONResponse({"error": "Not initialized"}, 500)
    from memory_system.memory.consolidator import consolidate
    summary_ids = consolidate(S.log, user_id=S.user_id)
    return {"summary_nodes_created": len(summary_ids), "summary_ids": summary_ids}


@app.post("/api/clear_memory")
def clear_memory():
    if not S.log:
        return JSONResponse({"error": "Not initialized"}, 500)
    conn = S.log._conn
    conn.execute("DELETE FROM chunks")
    conn.execute("DELETE FROM episodes")
    conn.execute("DELETE FROM user_links")
    conn.commit()
    S.new_session()
    return {"cleared": True, "session_id": S.session_id}


@app.get("/api/memories")
def get_memories():
    if not S.log:
        return {"nodes": [], "edges": [], "user_links": []}
    chunks = S.log.fetch_recent_chunks(user_id=S.user_id, limit=200)
    if not chunks:
        return {"nodes": [], "edges": [], "user_links": S.fetch_user_links()}

    nodes = []
    ti: dict[str, set[int]] = defaultdict(set)
    for i, c in enumerate(chunks):
        for t in _tok(c.text + " " + c.key):
            ti[t].add(i)
        nodes.append({
            "id": c.id, "type": c.chunk_type, "key": c.key,
            "text": c.text[:120], "freq": c.frequency_count,
        })

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
    return {"nodes": nodes, "edges": edges, "user_links": S.fetch_user_links()}


class LazyImportReq(BaseModel):
    path: str
    title: str = ""


@app.post("/api/lazy/import")
def lazy_import(req: LazyImportReq):
    """Register a file for lazy import — metadata only, no heavy extraction."""
    if not S.lazy:
        return JSONResponse({"error": "Not initialized"}, 500)
    sid = S.lazy.register_source(req.path, user_id=S.user_id, title=req.title)
    return {"status": "registered", "source_id": sid}


@app.get("/api/lazy/sources")
def lazy_sources():
    if not S.lazy:
        return {"sources": []}
    srcs = S.lazy.list_sources(S.user_id)
    return {"sources": [
        {"id": s.id, "title": s.title, "path": s.source_path,
         "words": s.word_count, "extracted": s.extracted_ts is not None,
         "tombstoned": s.tombstoned}
        for s in srcs
    ]}


@app.post("/api/lazy/gc")
def lazy_gc():
    """Behavioral GC — tombstone stale never-recalled imported chunks."""
    if not S.lazy:
        return JSONResponse({"error": "Not initialized"}, 500)
    count = S.lazy.gc(user_id=S.user_id)
    return {"tombstoned": count}


@app.post("/api/sync/push")
def sync_push():
    """Manually push to cloud storage."""
    count = push_if_enabled()
    if count is None:
        return {"status": "disabled", "message": "Set MEMLA_SYNC_BACKEND env var to enable"}
    return {"status": "ok", "files_pushed": count}


@app.post("/api/sync/pull")
def sync_pull():
    """Manually pull from cloud storage."""
    count = pull_if_enabled()
    if count is None:
        return {"status": "disabled", "message": "Set MEMLA_SYNC_BACKEND env var to enable"}
    return {"status": "ok", "files_pulled": count}


class PreflightReq(BaseModel):
    text: str


@app.post("/api/preflight")
def preflight(req: PreflightReq):
    """Live pre-flight: as user types, return which memory node IDs are being targeted.

    Debounced from the frontend (300ms). Returns top node IDs + scores so the
    graph can highlight them in real-time before the user hits Enter.
    """
    if not S.log or not req.text.strip():
        return {"hits": []}
    try:
        from memory_system.middleware.context_builder import _get_lora_manager
        mgr = _get_lora_manager()
        if mgr is None:
            return {"hits": []}
        chunks = S.log.fetch_top_level_chunks(user_id=S.user_id, limit=200)
        if not chunks:
            return {"hits": []}
        q_emb = mgr.embed_query(req.text.strip())
        c_embs = mgr.embed_many([c.text for c in chunks])
        if not q_emb or not c_embs:
            return {"hits": []}
        scored = []
        for i, c_emb in enumerate(c_embs):
            dot = sum(a * b for a, b in zip(q_emb, c_emb))
            scored.append((chunks[i].id, float(dot)))
        scored.sort(key=lambda x: x[1], reverse=True)
        top = scored[:8]
        if top and top[0][1] < 0.2:
            return {"hits": []}
        return {"hits": [{"id": nid, "score": round(s, 3)} for nid, s in top if s > 0.15]}
    except Exception:
        return {"hits": []}


class TrajectoryCorrection(BaseModel):
    trajectory_id: int
    steps: list[dict]


@app.get("/api/trajectory/{traj_id}")
def get_trajectory(traj_id: int):
    if not S.traj_log:
        return {"error": "Not initialized"}
    trajs = S.traj_log.fetch_recent(user_id=S.user_id, limit=100)
    traj = next((t for t in trajs if t.id == traj_id), None)
    if not traj:
        return JSONResponse({"error": "Trajectory not found"}, 404)
    return traj.to_dict()


@app.post("/api/trajectory/correct")
def correct_trajectory(req: TrajectoryCorrection):
    """User rewired the reasoning graph — save correction as CPO training pair."""
    if not S.traj_log:
        return JSONResponse({"error": "Not initialized"}, 500)
    corrected_steps = [
        TrajectoryStep(
            step_type=s.get("type", s.get("step_type", "thought")),
            content=s.get("content", ""),
            tool_name=s.get("tool", s.get("tool_name", "")),
            index=s.get("index", i),
        )
        for i, s in enumerate(req.steps)
    ]
    S.traj_log.save_correction(req.trajectory_id, corrected_steps)
    return {"ok": True, "trajectory_id": req.trajectory_id}


@app.get("/api/trajectory/pending_pairs")
def pending_cpo_pairs():
    """Get corrected trajectory pairs for CPO training (sleep phase)."""
    if not S.traj_log:
        return {"pairs": []}
    pairs = S.traj_log.fetch_uncorrected_pairs(user_id=S.user_id, limit=50)
    return {"pairs": [t.to_dict() for t in pairs]}


@app.get("/api/recall")
def recall():
    if not S.ttt:
        return {"chunks": []}
    return {
        "chunks": [
            {"id": c.id, "type": c.chunk_type, "key": c.key,
             "text": c.text, "freq": c.frequency_count}
            for c in S.ttt.last_retrieved
        ],
    }


@app.on_event("shutdown")
def _on_shutdown():
    pushed = push_if_enabled()
    if pushed is not None:
        print(f"[sync] pushed {pushed} files to cloud")


# ── Entry point ──────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Memla Web UI")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--model", default="qwen3.5:4b")
    p.add_argument("--db", default=os.environ.get("MEMORY_DB", "./memory.sqlite"))
    p.add_argument("--user_id", default=os.environ.get("USER_ID", "default"))
    p.add_argument("--ollama_url", default=os.environ.get(
        "OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    ))
    a = p.parse_args()

    S.init(model=a.model, db=a.db, user_id=a.user_id, ollama_url=a.ollama_url)

    url = f"http://127.0.0.1:{a.port}"
    print(f"\n  Memla  ->  {url}\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
