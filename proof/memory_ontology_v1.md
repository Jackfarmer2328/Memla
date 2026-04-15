# Memory Ontology V1

Memory Ontology V1 turns Memla's learned language traces into governed memory objects instead of treating them as loose retrieval artifacts.

## Goal

Move memory from:

- raw trace storage
- retrieval hits
- ad-hoc promotion

into:

- canonical memory objects
- explicit lifecycle stages
- reuse adjudication
- stale / invalid memory handling

## V1 scope

V1 governs the language-learning stack first:

1. successful `language_model` compilations are stored as `episodic` memory objects
2. repeated successful `language_memory` reuse promotes those objects to `semantic`
3. repeated rule promotion promotes those objects to `rule`
4. failed reuse can invalidate misleading memory
5. old non-rule memory can decay to `stale`

## Canonical memory object

Each object now carries:

- `memory_kind`
- `promotion_stage`
- `status`
- `trust`
- `reuse_count`
- `successful_reuse_count`
- `failed_reuse_count`
- `freshness_ts`
- `transfer_scope`
- `action_signatures`
- prompt examples and canonical clauses

## Why this matters

This means Memla memory is no longer just:

- "have I seen something like this?"

It becomes:

- what kind of memory is this?
- how trustworthy is it?
- did it actually transfer?
- should it stay episodic, become semantic, decay, or be invalidated?

## Runtime effect

The current hot path now does:

1. store frontier language wins as ontology objects
2. adjudicate warm reuse success or failure
3. promote repeated wins to `semantic`
4. promote rule-backed wins to `rule`

So Memory Ontology V1 is the first real shift from retrieval memory toward governed reusable knowledge.

## Benchmark

Run:

```powershell
py -3 memla.py terminal benchmark-memory-v1 --model phi3:mini --raw-base-url http://127.0.0.1:11435 --memla-base-url http://127.0.0.1:11435
```

The benchmark uses a small memory-focused pack where the cold prompt is intentionally canonical and the warm/rule prompts are messy paraphrases. This keeps the proof focused on memory lifecycle transitions rather than frontier language compilation difficulty.
