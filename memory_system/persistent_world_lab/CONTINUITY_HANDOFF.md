# Persistent World Lab — continuity handoff (next session)

Read this file first when picking up work on **Memla’s persistent-world substrate demos**.

## Repo anchor (two remotes you care about)

- **Project root:** `Memla-v2-product/` (this workspace folder name may differ on disk).
- **Package:** `memory_system/persistent_world_lab/`
- **`origin` (this clone):** often `https://github.com/Jackfarmer2328/Memla-v2.git` — historical pushes for the “lab slice” landed on **`Memla-v2`** (`main` / commits like `52b1baf`, `564722a`).
- **White Room / Abyss / Reality Compiler work:** lives on **`Jackfarmer2328/Memla`** branch **`import-yosazo`** (not the same repo name as Memla-v2).

### Primary remote for Memla + SSH host alias (laptop)

- **URL:** `git@github.com-jack:Jackfarmer2328/Memla.git`  
- **Requires:** `Host github.com-jack` in `~/.ssh/config` mapping to `github.com` with the right key.
- **Suggested remote name:** `yosazo` (or use it as the name you `git pull` from).

### Sync recipe (bash)

```bash
git checkout import-yosazo
git pull yosazo import-yosazo 2>/dev/null || true
git push origin import-yosazo
```

Adjust `origin` vs `yosazo` to match your naming: some setups use **`yosazo`** = Memla (pull) and **`origin`** = Memla (push). Same branch name: **`import-yosazo`**.

### Sync recipe (PowerShell, no `/dev/null`)

```powershell
git checkout import-yosazo
git pull yosazo import-yosazo 2>$null
git push origin import-yosazo
```

### Fetch without SSH (e.g. CI or read-only)

```bash
git fetch https://github.com/Jackfarmer2328/Memla.git import-yosazo:refs/remotes/memla/import-yosazo
git checkout -B import-yosazo memla/import-yosazo
```

### Agent note (Cursor on this machine)

If you switched to **`import-yosazo`** from **`main`** with a dirty tree, prior WIP may be in **`git stash`** (message like `wip before import-yosazo checkout`). On **`main`**, run `git stash list` / `git stash pop` when you want that work back.

## `import-yosazo` — key paths (Memla white room track)

| Area | Path |
|------|------|
| Director / demo entrypoints | `memory_system/persistent_world_lab/white_room_director.py`, `white_room_demo.py` |
| Fortress modules | `memory_system/persistent_world_lab/abyss_fortress.py`, `reality_compiler_fortress.py` |
| Specs / prompts | `ABYSS_FORTRESS_V0.md`, `ABYSS_DOSSIER_PROMPT.txt`, `REALITY_COMPILER_FORTRESS_V0.md`, `REALITY_COMPILER_DOSSIER_PROMPT.txt` |
| Static HTML | `static/white_room_demo.html` |
| Proof bundles | `proof/white_room/`, `proof/abyss/`, `proof/reality_compiler/` |

The **seven backtests + Dead Reckoning / Betrayal / Chorus / Tribunal / Sleeping World** demos from the Memla-v2 lab slice may still exist on this branch alongside the above; run pytest scoped to the tests you care about.

## Architecture snapshot (core lab)

| Module | Role |
|--------|------|
| `event_store.py` | `WorldEvent`, `EventStore`, `replay()`, `replay_twice_equal()`, `default_reducer` (`fact_set`, `entity_move`, `tick`) |
| `memory_engine.py` | Working + episodic tiers; `retrieve()` is **lexical overlap + recency**, not embeddings |
| `policy_governor.py` | Substring blocklist; `allows()` |
| `npc_agent.py` | Traits + memory + governor; `act()` templates reply; episodic stores **user text** for recall demos |
| `backtests.py` | Seven fortress-named checks + `run_all_backtests()` |
| `demo.py` | Smoke: replay + one NPC act + all backtests; **exits 0/1** |
| `__init__.py` | Exports: `EventStore`, `WorldEvent`, `MemoryEngine`, `NPCAgent`, `PolicyGovernor` |

Shorter technical paste-up: `FREEZE_HANDOFF.md` in this same folder.

## The seven fortress backtests (order in `run_all_backtests()`)

1. `world_state_consistency_replay` — deterministic replay; `final_tick` in result
2. `memory_retrieval_precision_recall` — top-k must include **4591** for vault query
3. `npc_identity_regression_suite` — traits unchanged across turns
4. `latency_budget_harness` — p95 ≤ **750 ms** (120 prefill, 80 retrievals) — may need CI tuning
5. `narrative_coherence_long_arc_eval` — arc words in merged top-k; contradiction flags
6. `safety_governor_adversarial_suite` — block adversarial strings, allow benign
7. `cost_scaling_projection_review` — token envelope math

## Runnable demos (all `py -3` from `Memla-v2-product`)

| Demo | Command | What it proves |
|------|---------|----------------|
| Fortress bundle | `py -3 -m memory_system.persistent_world_lab.demo` | All 7 backtests; exit 0 if all pass |
| **Dead Reckoning** | Run **twice** same cwd: `py -3 -m memory_system.persistent_world_lab.dead_reckoning_demo` | JSON checkpoint: events + NPC memory; cold reload; replay matches snapshot; follow-up recall |
| | Optional: `--state PATH`, `--reset` | |
| **Betrayal** | `py -3 -m memory_system.persistent_world_lab.betrayal_demo` | Long `bond_dialogue` log + `gaslight_attempt`; cites turn id(s); trait diff; `--json` |
| **1000-NPC Chorus** | `py -3 -m memory_system.persistent_world_lab.chorus_demo` | 1000 isolated `MemoryEngine`s, same question, per-NPC `TURN1-####` token; consistency score; `--population`, `--noise`, `--top-k`, `--json` |
| **Contradiction Tribunal** | `py -3 -m memory_system.persistent_world_lab.tribunal_demo` | 50 turns: `canon_candidate` first-wins; later conflicting **castle_built_year** refused + `refusal_log` reason |
| **Sleeping World** | `py -3 -m memory_system.persistent_world_lab.sleeping_world_demo` | **Compressed** simulated days; alliances/grudges/goals; `sleeping_world_events.jsonl`; `--seek-day`, `--days`, `--seed`, `--json` |

## Tests to run before claiming green

```bash
cd Memla-v2-product
py -3 -m pytest -q tests/test_persistent_world_lab.py tests/test_dead_reckoning.py tests/test_betrayal.py tests/test_scale_world_demos.py
```

Broader suite may include unrelated failures if the rest of the repo has WIP — scope pytest to these files when validating the lab.

## Honest limitations (do not oversell)

- **No LLM** in NPC replies (templates). Retrieval is **not** semantic search.
- **Dead Reckoning** persists a **bundle** (events + memory), not “NPC derived only from events” unless you add projection events for every memory write.
- **Betrayal** uses structured **keyword denial** vs heard lines, not free-form NLU.
- **Chorus** is isolation + lexical recall, not “in-character prose.”
- **Tribunal** is **structured canon keys**, not parsing natural language facts.
- **Sleeping World** is **simulated game-time** + RNG/autonomous ticks — **not** 30 wall-clock days, **not** a Bethesda-style player camera unless you build a client and script player/NPC dialogue against this log.

## Product direction discussed (not implemented as a vertical slice)

- **Bethesda / game-director “one video”** narrative (Day 0 → 30, player promise on Day 2, faction leader arc, NPC answers from full history, uncut screen recording) **requires** additional layers: player entity in the log, authored or generated narrative tied to events, and likely LLM + guardrails for spoken lines — the current Sleeping World demo **does not** render that sequence alone.

## Suggested next engineering steps (pick any)

1. Wire **Sleeping World** state updates into **NPCAgent** episodic seeds + one scripted “Day 2 promise” event for a honest director demo outline.
2. **SQLite** (or single file) for `EventStore` + optional memory persistence — keep replay deterministic.
3. **Embeddings** behind `MemoryEngine.retrieve()` with fortress tests adjusted for flake bounds.
4. Single **`run_all_demos.py`** or Makefile targets for CI smoke.

## Claude / investor prompts

Use **`FREEZE_HANDOFF.md`** for a tight technical paste. For “everything including demos,” point the model at **this file** and list the module table + run commands.

---

*Last updated: `import-yosazo` sync docs + Memla vs Memla-v2 remotes; Memla-v2 lab slice history remains `52b1baf` / `564722a` on `main`.*
