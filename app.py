"""
Web UI for Project Memory.

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
from memory_system.middleware.ttt_layer import TTTLayer
from memory_system.ollama_client import ChatMessage, UniversalLLMClient

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

        self.log = EpisodeLog(db)
        self.client = UniversalLLMClient(provider="ollama", base_url=self.ollama_url)
        ext = LLMChunkExtractor(client=self.client, model=model, temperature=0.0)
        cm = ChunkManager(self.log, llm_extractor=ext.extract)
        self.ttt = TTTLayer(episode_log=self.log, chunk_manager=cm)

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


S = State()

# ── Pydantic models ──────────────────────────────────────────────


class ChatReq(BaseModel):
    message: str
    model: str = ""


class FeedbackReq(BaseModel):
    is_positive: bool


# ── FastAPI ──────────────────────────────────────────────────────

app = FastAPI(title="Project Memory")
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
    messages = [
        ChatMessage(role="system", content=artifacts.built.system_prompt),
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
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.post("/api/feedback")
def feedback(req: FeedbackReq):
    if not S.ttt:
        return {"ok": False}
    return {"ok": S.ttt.explicit_feedback(is_positive=req.is_positive)}


@app.post("/api/session")
def new_session():
    S.new_session()
    return {"session_id": S.session_id}


@app.get("/api/memories")
def get_memories():
    if not S.log:
        return {"nodes": [], "edges": []}
    chunks = S.log.fetch_recent_chunks(user_id=S.user_id, limit=200)
    if not chunks:
        return {"nodes": [], "edges": []}

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
    return {"nodes": nodes, "edges": edges}


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


# ── Entry point ──────────────────────────────────────────────────

def main() -> None:
    p = argparse.ArgumentParser(description="Project Memory Web UI")
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
    print(f"\n  Project Memory  ->  {url}\n")
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
