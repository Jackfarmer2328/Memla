# Local LLM Memory System (Step 1)

This repository implements **Step 1: Core memory loop** for a local LLM using **Ollama**.

## What you get

- **SQLite append-only episode log**
- **Chunk extraction** (facts, decisions, entities) from each user message
- **Retrieval** by keyword overlap + recency
- **Prompt injection** of retrieved memories on every model call
- A simple **terminal chat loop** in `memory_system/main.py`

## Prereqs

- Python **3.11+**
- Ollama installed and running:
  - Start the daemon: `ollama serve`
  - Pull a model: `ollama pull llama3.2` (or `mistral`)

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python -m memory_system.main --model llama3.2 --db ./memory.sqlite --user_id default
```

### Commands inside the chat loop

- `/new_session` – start a new session id (memory persists in DB)
- `/recall` – print top retrieved chunks for your last message
- `/exit` – quit

## Persistence test (manual)

1. Paste a long document (or several pages) into the chat.
2. Ask it to extract key points (so memories get chunked).
3. Exit.
4. Restart the program and ask about a specific detail that was mentioned earlier.

If retrieval works, the answer should come from injected memories, not from the raw document being in-context.

