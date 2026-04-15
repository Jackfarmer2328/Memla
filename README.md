# Memla CLI

Memla is a bounded runtime that helps smaller models make better technical decisions inside verifier-backed loops.

Install from PyPI:

```bash
pip install memla
```

PyPI:
- [memla on PyPI](https://pypi.org/project/memla/)

This repo is the public, CLI-first version of Memla. It is intentionally narrower than the internal research repo and keeps the public snapshot focused on the tool, not every generated artifact.

## What this repo contains

- `memla.py`
  - thin top-level entry point
- `memory_system/`
  - CLI runtime, coding loop, finance pre-trade backtester, pure coding C2A benchmark, math benchmark, and pack builder
- `cases/`
  - bundled case files for quick local runs
- `proof/`
  - lightweight public proof summary and a small site template
- `tests/`
  - focused coverage for the CLI and benchmark surfaces

## Current bounded claim

Public proof summary:
- `proof/summary.md`

Current strongest public result:
- on coding, local `qwen3.5:9b + Memla` beat hosted `Meta-Llama-3.1-405B-Instruct` raw on execution outcome in the primary patch benchmark
- on coding, the same `qwen3.5:9b` base model moved from `0.0` apply / `0.0` semantic success raw to `1.0` apply / `0.6667` semantic success with Memla on the same OAuth slice
- after loading a `405b`-only self-transmutation bank, same-model `qwen3.5:9b + Memla` on the OAuth slice improved from `0.6667` apply / `0.6667` semantic success with the bank disabled to `1.0` apply / `0.6667` semantic success with the bank enabled
- on pure coding C2A, the same `405b`-only self-transmutation bank lifted same-model `qwen3.5:9b + Memla` utility from the earlier `0.4908` baseline to `0.5058`, and that repeated across `3` runs with average uplift `+0.015`
- on coding, hosted `Grok-3` raw also stayed at `0.0` apply / `0.0` semantic success on the OAuth slice while local `qwen3.5:9b + Memla` reached `0.6667` apply / `0.6667` semantic success
- on two small coding C2A slices, hosted `DeepSeek-R1` raw scored `0.2` and `0.35` utility while local `qwen3.5:9b + Memla` reached `0.7` and `0.55`
- on a small healthcare denial replay slice, hosted `DeepSeek-R1` raw tied local `qwen3.5:9b + Memla` at `1.0` utility on the completed cases
- on a second repo family, hosted `meta/Llama-3.3-70B-Instruct` raw again stayed at `0.0` apply while local `qwen3.5:9b + Memla` reached `0.3333` apply on the FastAPI slice
- on a second repo family against hosted `Grok-3` raw, local `qwen3.5:9b + Memla` reached `0.5` apply on `2` completed FastAPI cases while the raw lane stayed at `0.0` apply and one raw-lane case failed with `HTTPError`
- on math, `qwen3.5:4b + Memla` matched `qwen2.5:32b` raw on the harder bounded pack
- on ambiguous math decision states, Memla lifted both `4b` and `9b` to perfect choice accuracy on the tested slice

This is a bounded-runtime claim, not a universal model-parity claim.

## Quick start

Prerequisites:
- Python 3.11+
- either Ollama running locally or a hosted chat model reachable through the shared LLM client
- one or more models already available

Install:

```bash
pip install memla
```

For local editable development instead:

```bash
py -3 -m pip install -e .
```

Smoke-check the CLI:

```bash
memla --help
```

Run a local environment check:

```bash
memla doctor --repo-root . --model qwen3.5:9b
```

Use a hosted GitHub Models endpoint instead of Ollama:

```powershell
$env:LLM_PROVIDER="github_models"
$env:GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
$env:LLM_BASE_URL="https://models.github.ai/inference"
memla coding run --prompt "Repair the failing auth tests" --repo-root . --model "meta/Llama-3.3-70B-Instruct"
```

If you prefer, `LLM_API_KEY` also works in place of `GITHUB_TOKEN`.

## Main commands

Run the customer-facing research eval harness:

```bash
memla research eval-harness --input historical_decision_logs.jsonl --normalize-capture --frontier-use-logged-decisions --memla-provider openai --memla-base-url https://internal-llm-api.example/v1 --memla-model qwen2.5-14b-instruct --pricing-profile perplexity_public_sonar
```

Build a workflow plan inside a repo:

```bash
memla coding plan --prompt "Fix the auth regression" --repo-root .
```

Run a bounded coding turn with optional verification:

```bash
memla coding run --prompt "Repair the failing auth tests" --repo-root . --test-command "pytest -q"
```

Run the patch execution benchmark:

```bash
memla coding benchmark-patch --pack path\\to\\git_history_case_pack.json --raw-model qwen2.5:32b --memla-model qwen3.5:9b
```

Mix a hosted raw lane with a local Memla lane:

```bash
memla coding benchmark-patch --pack path\\to\\git_history_case_pack.json --raw-model meta/Llama-3.3-70B-Instruct --memla-model qwen3.5:9b --raw-provider github_models --raw-base-url https://models.github.ai/inference --memla-provider ollama --memla-base-url http://127.0.0.1:11435
```

Run the compile-loop benchmark:

```bash
memla coding benchmark-compile --cases cases\\coding_eval_cases.jsonl --repo-root . --model qwen3.5:9b
```

Run the pure next-move coding C2A benchmark:

```bash
memla coding benchmark-c2a --cases cases\\coding_eval_cases.jsonl --repo-root . --raw-model qwen3.5:9b --memla-model qwen3.5:9b
```

Run the finance pre-trade compliance backtester:

```bash
memla finance benchmark-pretrade --cases cases\\finance_pretrade_eval_cases.jsonl --raw-model meta/Llama-3.3-70B-Instruct --memla-model qwen3.5:9b
```

Run the public-rule-grounded finance pack built from SEC and FINRA control categories:

```bash
memla finance benchmark-pretrade --cases cases\\finance_pretrade_public_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
```

Public provenance for that pack:
- `cases/finance_pretrade_public_sources.md`

Run the healthcare denied-claim replay benchmark:

```bash
memla healthcare benchmark-denials --cases cases\\healthcare_denial_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
```

Public provenance for the bundled healthcare pack:
- `cases/healthcare_denial_public_sources.md`

Run the policy-as-code authz replay benchmark:

```bash
memla policy benchmark-authz --cases cases\\policy_authz_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
```

Extract a policy teacher trace bank and distill it into the live primitive-aware policy bank:

```bash
memla policy extract-authz --report memla_reports\\policy_deepseek_change_window_vs_9bmemla\\policy_authz_benchmark_report.json
memla policy distill-authz --trace-bank memla_reports\\policy_trace_bank_deepseek_change_window\\policy_trace_bank_summary.json --repo-root .
```

Public provenance for the bundled policy pack:
- `cases/policy_authz_public_sources.md`

Run the bounded natural-language terminal assistant on a weak local machine:

```bash
memla terminal benchmark --model phi3
memla terminal benchmark-browser --model phi3
memla terminal benchmark-browser-v2 --model phi3
memla terminal benchmark-browser-v3 --model phi3
memla terminal benchmark-browser-v4 --model phi3
memla terminal benchmark-browser-v5 --model phi3
memla terminal benchmark-browser-v6 --model phi3
memla terminal benchmark-browser-v7 --model phi3
memla terminal benchmark-browser-v8 --model phi3
memla terminal compare "open chrome and spotify"
memla scout "find the top 10 github repos for local llms and tell me which best fits weak hardware"
memla "find the top 10 github repos for local llms and tell me which best fits weak hardware"
memla serve --host 0.0.0.0 --port 8080 --model phi3:mini
memla terminal plan "open chrome and spotify" --heuristic-only
memla terminal run "open chrome and spotify" --heuristic-only
memla terminal run "open chrome" --without-memla --model phi3:mini
memla terminal run "open youtube and search lo fi hip hop"
memla terminal run "click the first video"
memla terminal run "open github and search llama.cpp"
memla terminal run "click the first repo"
memla terminal run "what is this repo"
memla terminal run "find the best repo for c++ llm inference on cpu then find a youtube video about it then open the first one and summarize it then find a reddit post about it then open the first one and explain it" --heuristic-only
memla terminal run "find the best repo for c++ llm inference on cpu then find a youtube video about it then open the first one and summarize it then if the first one seems weak open a better one and summarize it then find a reddit post about it then open the first one and explain it" --heuristic-only
memla terminal run "find the best repo for c++ llm inference on cpu then find a youtube video about it then open the first one and summarize it then if the first one seems weak open a better one and summarize it then find a reddit post about it then open the first one and explain it then tell me which source best explains cpu inference on weak hardware" --heuristic-only
memla terminal step "now click the first vid" --heuristic-only
memla terminal step "now click the first vid" --heuristic-only --choice 1
memla terminal run "open youtube and search lo fi hip hop" --without-memla --model phi3:mini
memla terminal run "open downloads folder" --model phi3:mini
```

The terminal surface is intentionally bounded:
- it launches known apps, opens URLs or folders, lists directories, and answers a few local status questions
- it does not generate arbitrary shell or privileged commands
- for common launch/open prompts, the built-in heuristic parser often avoids the model entirely
- `memla scout ...` adds a bounded autonomy layer on top of the browser ontology, so Memla can search GitHub, rank repo candidates, inspect the best few, and bring back a report in one shot
- `memla serve ...` exposes the same bounded runtime over HTTP for thin clients like a SwiftUI iPhone app or Shortcuts bridge
- the locked browser surface for benchmark/backtest work is documented in `proof/browser_ontology_v1.md`
- the ranking/comparison extension is documented in `proof/browser_ontology_v2.md`
- the multi-step browser research handoff layer is documented in `proof/browser_ontology_v3.md`
- the research-completion chain that opens the follow-on result is documented in `proof/browser_ontology_v4.md`
- the bounded research-explanation layer that opens and reads the follow-on result is documented in `proof/browser_ontology_v5.md`

The HTTP layer is intentionally thin so the product seam stays stable:

```bash
memla serve --host 0.0.0.0 --port 8080 --model phi3:mini
```

Available routes:
- `GET /health`
- `GET /state`
- `GET /memory`
- `GET /actions`
- `GET /missions`
- `POST /missions`
- `GET /missions/{mission_id}`
- `POST /missions/{mission_id}/decision`
- `POST /actions/plan`
- `POST /actions/draft`
- `POST /actions/capsule`
- `POST /run`
- `POST /scout`
- `POST /followup`

Example scout request:

```bash
curl -X POST http://127.0.0.1:8080/scout ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"find the top 10 github repos for local llms and tell me which best fits weak hardware\"}"
```

Example follow-up request:

```bash
curl -X POST http://127.0.0.1:8080/followup ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"find a youtube video about it then open the first one and summarize it\"}"
```

There is also a root `server.py`, so `uvicorn server:app --host 0.0.0.0 --port 8080` works if you want a plain FastAPI entrypoint for iPhone or Apple Shortcuts prototyping.

Extract a normalized finance trace bank from one or more pre-trade benchmark reports:

```bash
memla finance extract-pretrade --report memla_reports\\finance_pretrade_benchmark_20260404_161024\\finance_pretrade_benchmark_report.json
```

Distill a finance self-transmutation policy bank Memla can load from `.memla`:

```bash
memla finance distill-pretrade --trace-bank memla_reports\\finance_pretrade_extract\\finance_trace_bank_summary.json --repo-root .
```

Extract a normalized C2A trace bank from one or more benchmark reports:

```bash
memla coding extract-c2a --report memla_reports\\coding_c2a_9braw_vs_9bmemla\\coding_c2a_benchmark_report.json --report memla_reports\\coding_c2a_405braw_vs_9bmemla\\coding_c2a_benchmark_report.json
```

Distill a self-transmutation policy bank Memla can load from `.memla`:

```bash
memla coding distill-c2a --trace-bank memla_reports\\c2a_trace_bank_seed\\c2a_trace_bank_summary.json --repo-root .
```

Use `--disable-c2a-policy` or `--disable-memla-c2a-policy` on planning, run, compile, C2A, or patch benchmark commands to ablate the learned bank for a clean before/after comparison.

Validate the current self-transmutation bank against the same-model C2A harness:

```bash
memla coding benchmark-c2a --cases cases\\coding_eval_cases.jsonl --repo-root . --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
```

Run the bounded math benchmark:

```bash
memla math benchmark --cases cases\\math_linear_c2a_v2_harder.jsonl --teacher-model qwen2.5:32b --student-models qwen3.5:4b qwen3.5:9b --executor-mode stepwise_rerank --teacher-trace-source hybrid
```

Build a proof pack from generated report JSONs:

```bash
memla pack thesis --coding path\\to\\coding_patch_execution_report.json --math-rerank path\\to\\math_step_rerank_report.json --math-progress path\\to\\math_progress_report.json
```

Benchmark commands write report bundles under `./memla_reports/` by default.

## Public proof note

This repo intentionally omits bulky raw benchmark dumps from version control so the public snapshot stays product-shaped.

If you want the underlying artifacts, generate them locally with:
- `memla coding benchmark-patch`
- `memla coding benchmark-compile`
- `memla math benchmark`
- `memla pack thesis`

## Tests

Focused verification:

```bash
py -3 -m pytest -q tests\\test_step13_coding_compile_loop.py tests\\test_step14_compile_loop_benchmark.py tests\\test_step15_patch_execution_benchmark.py tests\\test_step16_math_c2a_benchmark.py tests\\test_step17_memla_cli.py
```

## Product direction

Memla is being packaged as:
- a local/private coding runtime for smaller models
- a CLI first, not a chat app first
- a verifier-backed system, not a prompt wrapper

The wedge is:

**make local 9b/14b/32b coding models more execution-capable than their raw form.**
