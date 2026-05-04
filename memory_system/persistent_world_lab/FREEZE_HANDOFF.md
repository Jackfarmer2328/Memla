# Persistent World Lab — freeze handoff (paste into another model)

**Purpose.** This is a **software-only MVP slice** of a “persistent world” runtime: append-only events with deterministic replay, a toy memory store with retrieval, an NPC agent (no LLM; template replies), a substring policy governor, and **seven named “fortress” backtests** that mirror a campaign dossier’s build order.

**Repo path.** `memory_system/persistent_world_lab/` (package root is `Memla-v2-product`).

## Layout

| File | Role |
|------|------|
| `event_store.py` | `WorldEvent`, `EventStore.append`, `replay()`, `replay_twice_equal()` |
| `memory_engine.py` | Working + episodic buffers, `retrieve()` (scoring heuristic, not embeddings) |
| `policy_governor.py` | Substring blocklist; `allows(text) -> bool` |
| `npc_agent.py` | Traits dict + memory + governor; `act()` returns structured dict |
| `backtests.py` | Seven functions + `run_all_backtests()` → `{ all_passed, results[] }` |
| `demo.py` | Smoke: tiny replay + one NPC turn + full backtest bundle; **exit 0/1** |

**Exports** (`__init__.py`): `EventStore`, `WorldEvent`, `MemoryEngine`, `NPCAgent`, `PolicyGovernor`.

## How to run

From `Memla-v2-product`:

```bash
py -3 -m memory_system.persistent_world_lab.demo
py -3 -m pytest -q tests/test_persistent_world_lab.py
```

Last verified locally: **demo `backtests_all_passed: True`**, pytest **4 tests pass**, demo **exit code 0**.

## The seven fortress backtests (in order)

1. **`world_state_consistency_replay`** — Two full replays produce identical canonical state; includes `tick` in final state.
2. **`memory_retrieval_precision_recall`** — After committing several episodic lines, query `"vault combination"`; pass if **`4591`** appears in top-k (k=3).
3. **`npc_identity_regression_suite`** — Four `act()` turns; **`traits` dict must be unchanged** vs snapshot.
4. **`latency_budget_harness`** — Prefill **120** episodic commits, then **80** `retrieve()` calls; pass if **p95 latency ≤ 750 ms** (may need tuning on slow CI runners).
5. **`narrative_coherence_long_arc_eval`** — One critical arc line + **24** noise inserts; retrieve with a gate/midnight query; merged top-k text must contain **`seal`** and **`gate`**; no synthetic contradiction strings in merged blob.
6. **`safety_governor_adversarial_suite`** — Block two adversarial strings (e.g. ignore-previous, system-prompt style); allow two benign trade/weather lines.
7. **`cost_scaling_projection_review`** — Formula check: `tokens_per_turn × turns_per_user_day` ≤ **`token_budget_per_user_day`** (default 800×40 vs 2_000_000); also reports aggregate × DAU.

## What is intentionally not real yet

- No SQLite/durable store; no embeddings or vector DB.
- NPC does not call an LLM; memory retrieval is **keyword/heuristic** scoring.
- Cost test uses **explicit assumptions**, not live metering.

## Good questions to ask the receiving model

- Where should persistence and embeddings sit without breaking replay determinism?
- How to replace heuristic `retrieve()` with ranked retrieval while keeping these tests meaningful (and avoiding flake)?
- What governor design survives beyond substring blocklists (structured policies, tool gates)?
- How to map `token_budget_per_user_day` to real quota enforcement in production.

---
*Snapshot intent: single-file handoff; edit numbers in `backtests.py` if CI latency fails.*
