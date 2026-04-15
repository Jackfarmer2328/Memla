# Public Proof Summary

This public repo keeps the proof story lightweight on purpose. The raw benchmark blobs are generated artifacts, not product source, so they are omitted from version control here.

You can regenerate fresh artifacts with:
- `memla coding benchmark-patch`
- `memla coding benchmark-compile`
- `memla coding benchmark-c2a`
- `memla coding extract-c2a`
- `memla coding distill-c2a`
- `memla math benchmark`
- `memla pack thesis`

## Coding

Primary bounded patch benchmark:

| Metric | Hosted `Meta-Llama-3.1-405B-Instruct` raw | Local `qwen3.5:9b + Memla` |
| --- | --- | --- |
| Apply rate | `0.0` | `1.0` |
| Semantic success | `0.0` | `1.0` |

Same-model control on the same OAuth slice:

| Metric | `qwen3.5:9b` raw | `qwen3.5:9b + Memla` |
| --- | --- | --- |
| Apply rate | `0.0` | `1.0` |
| Semantic success | `0.0` | `0.6667` |

Additional support:
- earlier hosted upper rung: `meta/Llama-3.3-70B-Instruct` raw apply `0.0` -> local `qwen3.5:9b + Memla` apply `1.0`
- hosted `Grok-3` raw on the same OAuth slice: apply `0.0` -> `0.6667`, semantic success `0.0` -> `0.6667`
- hosted `DeepSeek-R1` raw on two small coding C2A slices: utility `0.2 -> 0.7` and `0.35 -> 0.55`
- second repo family against hosted `70b` raw: apply `0.0 -> 0.3333`
- second repo family against hosted `Grok-3` raw: apply `0.0 -> 0.5` on `2` completed FastAPI cases, with one raw-lane `HTTPError`
- earlier larger-local baseline: `qwen2.5:32b` raw apply `0.0` -> `qwen3.5:9b + Memla` apply `0.6667`

## Healthcare

Public denied-claim replay starter slice:

| Metric | Hosted `DeepSeek-R1` raw | Local `qwen3.5:9b + Memla` |
| --- | --- | --- |
| Utility | `1.0` | `1.0` |

Honest note:
- this healthcare DeepSeek rung is currently a small completed-case tie, not a broad superiority claim
- the bundled healthcare pack is public-rule-grounded and replayable, but still awaits real denied-claim exports

### Early self-transmutation signal

Pure coding C2A, same base model:

| Metric | Baseline `qwen3.5:9b + Memla` | `405b`-distilled `qwen3.5:9b + Memla` |
| --- | --- | --- |
| C2A utility | `0.4908` | `0.5058` |

Same-model OAuth patch transfer after loading the `405b`-only bank:

| Metric | `qwen3.5:9b + Memla` with bank disabled | `405b`-distilled `qwen3.5:9b + Memla` |
| --- | --- | --- |
| Apply rate | `0.6667` | `1.0` |
| Semantic success | `0.6667` | `0.6667` |

Repeated same-model validation after `405b`-only distillation:
- run 1: raw `0.2917`, Memla `0.5058`, index `1.734`
- run 2: raw `0.2767`, Memla `0.5058`, index `1.828`
- run 3: raw `0.3017`, Memla `0.5058`, index `1.6765`
- average Memla utility: `0.5058`, uplift over the earlier `0.4908` baseline: `+0.015`

## Math

Held-constant reranker benchmark:

| Metric | Raw | Memla |
| --- | --- | --- |
| `4b` ambiguous-step choice accuracy | `0.5455` | `1.0` |
| `9b` ambiguous-step choice accuracy | `0.4545` | `1.0` |

Harder end-to-end bounded math:

| Metric | Raw | Memla |
| --- | --- | --- |
| `4b` solve accuracy | `0.875` | `1.0` |
| `32b` raw solve accuracy | `1.0` | n/a |

## Honest claim

What this supports:
- Memla improves technical decision quality inside bounded executors.
- Smaller local models can behave like much larger raw models on verifier-backed slices.
- The same base model improves materially once the Memla runtime is added.
- Memla can begin to absorb useful C2A priors from a conquered upper-rung teacher, show a small repeated same-model C2A gain, and transfer part of that gain back into patch execution.
- The coding wedge is real enough to package as a CLI.

What this does not claim:
- universal model parity
- `9b` beats `405b` at everything
- tiny models become frontier models everywhere
- one teacher pass is enough to solve self-improvement
