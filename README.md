# Memla

**The memory layer for AI — for humans and agents.**

Every LLM session starts from zero. Every agent forgets what it learned yesterday. Every multi-agent system has agents that can't share what they know. This fixes all three. Persistently. Locally.

**For humans:** A spatial prompt interface — select memories on a live knowledge graph, draw connections, then type. The model receives both your text and the relational structure you explicitly chose. Not a chat interface with a sidebar. A new interaction paradigm.

**For agents:** An MCP server that gives any agent on any framework (CrewAI, LangGraph, AutoGen, Claude Desktop, Cursor) persistent memory that learns. Four tool calls: retrieve, store, link, merge. Drop it into any agent. It stops being amnesiac.

**For multi-agent systems:** Each agent gets its own retrieval adapter. Periodic merges distill shared knowledge across all agents via PCA + EWC weight protection. Agents get collectively smarter without overwriting what they individually specialized in.

Works with **Ollama** (local), **Anthropic** (Claude), or **OpenAI-compatible APIs**. Your memory is **SQLite on your machine**. Your retrieval model trains locally via LoRA.

## What makes this different

1. **You prompt with a graph, not just text.** Click memory nodes to pin them as context. The model answers through the lens you selected — not the lens it guessed.

2. **Drawing connections trains retrieval.** When you link two memories, the system fires a contrastive training signal that pulls their embeddings closer. Your act of organizing knowledge teaches the retriever how to retrieve.

3. **The learning loop is closed properly.** Training signal comes from whether the LLM *actually used* a retrieved memory in its response — not from the retriever scoring itself. This prevents the system from calcifying on its own biases.

4. **Generation is untouched.** Only the retrieval model (MiniLM) gets fine-tuned via LoRA. The generation LLM (Ollama/Claude/GPT) stays as a black box. No risk of degrading output quality.

5. **Agents get the same memory humans get.** Via MCP, any agent on any framework connects to the same memory system. Retrieval adapts to each agent individually. Cross-agent merge distills shared knowledge without catastrophic forgetting.

## Quick start

**Prerequisites:** Python 3.11+, Ollama running locally

```bash
git clone https://github.com/Jackfarmer2328/Memla.git
cd Memla
pip install -r requirements.txt
```

### Web UI (recommended)

```bash
ollama serve
python app.py --model qwen3.5:4b
```

Opens `http://localhost:8765` in your browser. Pick any local Ollama model from the dropdown.

**Flags:**
- `--port 8765` — server port
- `--model qwen3.5:4b` — default model (any Ollama model)
- `--db ./memory.sqlite` — database path
- `--user_id default` — user identity for multi-user setups

### MCP Server (for agents)

```bash
# stdio transport (Claude Desktop, Cursor, local frameworks)
python mcp_server.py

# HTTP transport (remote agents, multi-machine setups)
python mcp_server.py --transport http --port 8766

# Custom agent identity (each agent gets its own LoRA adapter)
python mcp_server.py --agent_id researcher --db ./memory.sqlite
python mcp_server.py --agent_id coder --db ./memory.sqlite
```

Any MCP-compatible client connects and gets 7 tools:

| Tool | What it does |
|------|-------------|
| `memory_retrieve` | Semantic + keyword search over memories |
| `memory_store` | Persist a fact, decision, entity, or note |
| `memory_link` | Connect two chunks (fires LoRA training signal) |
| `memory_unlink` | Remove a connection |
| `memory_chat` | Full pipeline: retrieve + inject + LLM + train |
| `memory_feedback` | Positive/negative signal on last interaction |
| `memory_merge` | Cross-agent adapter merge (PCA + EWC) |

Plus 2 resources: `memory://graph` (full knowledge graph) and `memory://chunks/{agent_id}` (inspect any agent's memories).

### CLI mode

```bash
python -m memory_system.main --model qwen3.5:4b --db ./memory.sqlite --user_id default
```

### Anthropic / OpenAI

```bash
export LLM_PROVIDER=anthropic
export LLM_API_KEY="sk-ant-..."
python -m memory_system.main --model claude-sonnet-4-6 --db ./memory.sqlite
```

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY="YOUR_KEY"
export LLM_BASE_URL="https://api.openai.com"
python -m memory_system.main --model gpt-4o-mini --db ./memory.sqlite
```

## The interface

![Memla UI](assets/memla-ui.png)

**Graph interactions:**
- **Click** a node → pin it as context (purple glow, appears as chip above input)
- **Shift+Click** two nodes → connect/disconnect them (trains retrieval)
- **Shift+Drag** from one node to another → draw a connection
- **Drag** → move nodes
- **Scroll** → zoom
- **Search box** → filter/highlight by keyword
- **Esc** → clear all pins

## How it works

### The 5-step memory pipeline

1. **Episode + chunk logging** — Every message is logged to SQLite. Key facts, decisions, entities, and notes are extracted and stored as retrievable chunks.

2. **Hybrid retrieval + LoRA reranking** — Candidates are scored by semantic similarity (MiniLM embeddings) + keyword overlap + recency + frequency. A LoRA adapter on MiniLM reranks the top candidates.

3. **Closed-loop training** — After the LLM responds, the system measures which retrieved chunks were actually *used* in the response (token overlap). Used chunks = positive signal. Ignored chunks = negative signal. User corrections flip the signal. This trains the LoRA to surface what actually helps, not what scores highest.

4. **EWC weight protection** — Elastic Weight Consolidation uses Fisher information to protect important retrieval weights from catastrophic forgetting. Frequently-used retrieval pathways are "bolded" — harder to overwrite.

5. **Multi-user merge + safe subspace** — PCA extracts shared retrieval directions across users. Updates are projected into an agreement subspace so one user's adapter can't degrade another's.

### The spatial prompt layer (new)

On top of the pipeline, the web UI adds:

- **Pinned context injection** — Selected nodes bypass retrieval and get injected directly into the system prompt as highest-priority context.
- **User-drawn connections** — Persisted in SQLite (`user_links` table). Each link fires `micro_gradient_pass` bidirectionally — pulling the two chunks' embeddings closer in the LoRA's representation space.
- **Graph as training signal** — Every manual connection is a high-confidence contrastive pair. Over time, the retriever converges toward the user's mental model of how their knowledge is structured.

### Training signals (4 sources)

| Signal | Source | Confidence | Weight |
|--------|--------|------------|--------|
| Chunk usage | LLM referenced chunk in response | Medium | 1x |
| Correction | User's next message contradicts response | Medium | 0.6-0.8x |
| Explicit | `/good` or `/bad` command | High | 1x |
| Spatial | User drew a connection on the graph | Highest | 1x (bidirectional) |

## Multi-agent memory

Multiple agents share the same SQLite database with different `--agent_id` values. Each gets its own LoRA retrieval adapter that learns what *that* agent needs. Periodically, any agent calls `memory_merge` to distill shared knowledge.

```
┌─────────────┐  ┌─────────────┐  ┌─────────────┐
│  researcher  │  │    coder    │  │   writer    │
│  (LoRA A)    │  │  (LoRA B)   │  │  (LoRA C)   │
└──────┬───────┘  └──────┬──────┘  └──────┬──────┘
       │                 │                │
       └────────┬────────┴────────┬───────┘
                │                 │
         ┌──────▼──────┐  ┌──────▼──────┐
         │  PCA merge  │→ │ EWC protect │→ shared_base/
         └─────────────┘  └─────────────┘
```

The merge pipeline:
1. **PCA** extracts shared retrieval directions across all agent adapters via SVD
2. **EWC** protects important weights — frequently-used retrieval pathways can't be overwritten
3. **Safe subspace projection** ensures updates only go where all agents agree
4. The resulting `shared_base` adapter is loaded by all agents on next startup

This means a researcher agent's discoveries about API patterns strengthen the coder agent's retrieval of related code decisions — without overwriting the coder's specialized knowledge about implementation details.

## Commands (CLI mode)

- `/new_session` — new session (memory persists)
- `/recall` — show retrieved chunks from last turn
- `/good` — positive feedback on last response
- `/bad` — negative feedback on last response
- `/merge_adapters` — multi-user merge (Steps 4-5)
- `/exit` — quit

## Project structure

```
Project-Memory/
├── app.py                          # Web UI server (FastAPI + SSE streaming)
├── mcp_server.py                   # MCP server for agents (FastMCP, stdio/HTTP)
├── static/index.html               # Frontend (D3 graph + chat)
├── memory_system/
│   ├── main.py                     # CLI entry point
│   ├── ollama_client.py            # Universal LLM client (Ollama/OpenAI/Anthropic)
│   ├── memory/
│   │   ├── episode_log.py          # SQLite persistence (episodes, chunks, user_links)
│   │   ├── chunk_manager.py        # Hybrid retrieval (semantic + keyword + recency)
│   │   └── llm_extractor.py        # Chunk extraction from messages
│   ├── middleware/
│   │   ├── ttt_layer.py            # Turn-by-turn orchestration + learning loop
│   │   ├── context_builder.py      # System prompt assembly + deferred training
│   │   └── quality.py              # Chunk usage scoring + correction detection
│   ├── adapters/
│   │   ├── lora_manager.py         # MiniLM + LoRA loading/saving/embedding
│   │   ├── gradient_pass.py        # Micro gradient steps on retrieval LoRA
│   │   ├── ewc.py                  # Elastic Weight Consolidation
│   │   └── merge.py                # Multi-user PCA merge
│   └── projection/
│       └── gradient_filter.py      # Safe subspace projection
├── tests/                          # 13 tests covering all pipeline steps
├── requirements.txt
└── memory.sqlite                   # Your memory (local, yours)
```

## Requirements

```
requests>=2.31,<3
torch>=2.1
transformers>=4.40
peft>=0.7
safetensors>=0.4
sentence-transformers>=2.2
fastapi>=0.100
uvicorn>=0.20
fastmcp>=2.0
```
