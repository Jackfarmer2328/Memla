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

## Early self-transmutation support
- Pure coding C2A baseline: qwen3.5:9b raw `0.2742`, qwen3.5:9b + Memla `0.4908`.
- 405b-only teacher bank: raw `0.1417`, Memla `0.4825`, utility index `3.4051` on the captured upper-rung C2A benchmark.
- Same-model OAuth patch transfer after loading the 405b-only bank: apply `0.6667` -> `1.0`, semantic success held at `0.6667`.
- Distilled same-model repeats after loading the 405b-only bank:
  - run 1: raw `0.2917`, Memla `0.5058`, index `1.734`
  - run 2: raw `0.2767`, Memla `0.5058`, index `1.828`
  - run 3: raw `0.3017`, Memla `0.5058`, index `1.6765`
- Average distilled Memla utility: `0.5058`, uplift over the earlier `0.4908` baseline: `+0.015`.

## Honest limit
- This is bounded-runtime evidence, not universal proof complete.
- The hosted 405b headline currently comes from a 3-case OAuth patch slice.
- The FastAPI repeat confirms the apply-rate shape on a second family, but not the same semantic-success jump.
- The self-transmutation lift is currently small, and the patch-transfer signal is still one bounded OAuth slice rather than a broad family repeat.
- Coding still benefits from more repo-family repeats and cleaner execution metrics.

## Why this matters
- Memla is looking more like a real runtime layer, not just retrieval.
- It makes capable local models more useful under bounded executors.
- It is a natural fit for a CLI or harness with plug-in domain executors.
