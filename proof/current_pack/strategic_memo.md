# Memla Strategic Memo

## Strong current claim
- Coding upper-rung proof: hosted Meta-Llama-3.1-405B-Instruct raw apply `0` -> local qwen3.5:9b + Memla apply `1` and semantic success `0` -> `1`.
- Same-model coding control: qwen3.5:9b raw apply `0` -> qwen3.5:9b + Memla apply `1` and semantic success `0` -> `0.6667`.
- Math decision proof: 4b ambiguous-step choice `0.5455` -> `1` and 9b `0.4545` -> `1` with the same candidate hands.
- End-to-end bounded math proof: 4b solve accuracy `0.875` -> `1`, matching teacher raw at `1`.

## Extra coding support
- Earlier hosted upper rung: meta/Llama-3.3-70B-Instruct raw apply `0` -> qwen3.5:9b + Memla apply `1`.
- Grok OAuth rung: Grok-3 raw apply `0` and semantic success `0` -> qwen3.5:9b + Memla apply `0.6667` and semantic success `0.6667`.
- Second repo-family repeat against hosted 70b raw: apply `0` -> `0.3333`.
- Second repo-family repeat against hosted Grok raw: apply `0` -> `0.5` on 2 completed FastAPI cases, with one raw-lane HTTP error.
- Earlier larger-local baseline: qwen2.5:32b raw apply `0` -> qwen3.5:9b + Memla apply `0.6667`.

## Honest limit
- This is bounded-runtime evidence, not universal proof complete.
- The hosted 405b headline currently comes from a 3-case OAuth patch slice.
- The FastAPI repeat confirms the apply-rate shape on a second family, but not the same semantic-success jump.
- Coding still benefits from more repo-family repeats and cleaner execution metrics.

## Why this matters
- Memla is looking more like a real runtime layer, not just retrieval.
- It makes capable local models more useful under bounded executors.
- It is a natural fit for a CLI or harness with plug-in domain executors.
