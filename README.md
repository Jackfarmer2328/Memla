# The AI that never forgets you

Every LLM session starts from zero. You re-explain your stack, your context, your decisions — every single time.

This fixes that. **Persistently. Locally.**

Works with **Claude** (Anthropic), **OpenAI-compatible APIs**, or **any local model via Ollama**. Your memory store is **SQLite on your machine**.

## Install

Prereqs: **Python 3.11+**

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (one command)

### Local (Ollama)

```bash
ollama serve
ollama pull llama3.2
python -m memory_system.main --model llama3.2 --db ./memory.sqlite --user_id default
```

### Anthropic (Claude) — native API

```bash
export LLM_PROVIDER=anthropic
export LLM_API_KEY="sk-ant-..."
export LLM_BASE_URL="https://api.anthropic.com"
python -m memory_system.main --model claude-sonnet-4-6 --db ./memory.sqlite --user_id default
```

### OpenAI-compatible (any vendor that implements `/v1/chat/completions`)

```bash
export LLM_PROVIDER=openai
export LLM_API_KEY="YOUR_KEY"
export LLM_BASE_URL="https://api.openai.com"
python -m memory_system.main --model gpt-4o-mini --db ./memory.sqlite --user_id default
```

## One working demo (persistence)

1. Paste a long document into the chat.
2. Exit with `/exit`.
3. Restart the program.
4. Ask a question about a detail that was only in the pasted document.

If it answers correctly, it’s using **retrieved memories injected into the prompt**, not the original document.

## Commands

- `/new_session` — new session id (memory still persists in SQLite)
- `/recall` — print retrieved memory chunks from last turn
- `/merge_adapters` — manual multi-user merge into shared base (Steps 4–5)
- `/update_subspace` — recompute safe subspace (debug)
- `/exit` — quit

## How it works (for the curious)

- **Step 1 (Memory loop)**: logs episodes + chunks to SQLite; injects top memories into the system prompt.
- **Step 2 (Train retrieval, not generation)**: LoRA trains a tiny retrieval model that reranks memory chunks; generation model is untouched.
- **Step 3 (EWC bolding)**: Fisher information protects important retrieval weights so new updates don’t overwrite identity.
- **Step 4 (Multi-user merge)**: PCA extracts shared directions and writes a shared base update without blending personal adapters.
- **Step 5 (Safe subspace)**: shared updates are projected into a “safe” agreement subspace to prevent contradictory users tearing the shared base.

