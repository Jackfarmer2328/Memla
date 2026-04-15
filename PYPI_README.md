# Memla

Memla is a CLI runtime for local or hosted models.

It helps smaller models make better technical decisions inside verifier-backed loops instead of using raw prompting alone.

Install:

```bash
pip install memla
```

Quick check:

```bash
memla --help
memla doctor --repo-root . --model qwen3.5:9b
```

Hosted GitHub Models example:

```powershell
$env:LLM_PROVIDER="github_models"
$env:GITHUB_TOKEN="YOUR_GITHUB_TOKEN"
$env:LLM_BASE_URL="https://models.github.ai/inference"
memla coding run --prompt "Repair the failing auth tests" --repo-root . --model "meta/Llama-3.3-70B-Instruct"
```

Core use cases:
- local coding workflow planning and repair
- finance pre-trade compliance replay and remediation backtesting
- coding patch-execution, compile-loop, and pure coding C2A benchmarks
- bounded math benchmarks for decision-layer evaluation
- proof-pack generation for static report sites

Current bounded public claim:
- on coding, local `qwen3.5:9b + Memla` beat hosted `Meta-Llama-3.1-405B-Instruct` raw on execution outcome in the primary patch benchmark
- on coding, the same `qwen3.5:9b` base model moved from `0.0` apply / `0.0` semantic success raw to `1.0` apply / `0.6667` semantic success with Memla on the same OAuth slice
- after loading a `405b`-only self-transmutation bank, same-model `qwen3.5:9b + Memla` on the OAuth slice improved from `0.6667` apply / `0.6667` semantic success with the bank disabled to `1.0` apply / `0.6667` semantic success with the bank enabled
- on pure coding C2A, the same `405b`-only self-transmutation bank lifted same-model `qwen3.5:9b + Memla` utility from the earlier `0.4908` baseline to `0.5058`, and that repeated across `3` runs with average uplift `+0.015`
- on coding, hosted `Grok-3` raw also stayed at `0.0` apply / `0.0` semantic success on the OAuth slice while local `qwen3.5:9b + Memla` reached `0.6667` apply / `0.6667` semantic success
- on a second repo family, hosted `meta/Llama-3.3-70B-Instruct` raw again stayed at `0.0` apply while local `qwen3.5:9b + Memla` reached `0.3333` apply on the FastAPI slice
- on a second repo family against hosted `Grok-3` raw, local `qwen3.5:9b + Memla` reached `0.5` apply on `2` completed FastAPI cases while the raw lane stayed at `0.0` apply and one raw-lane case failed with `HTTPError`
- on math, `qwen3.5:4b + Memla` matched `qwen2.5:32b` raw on a harder bounded pack
- on ambiguous math decision states, Memla lifted both `4b` and `9b` to perfect choice accuracy on the tested slice

This is not a claim of universal model parity. It is a claim about bounded runtimes with verifiers.

Useful commands:

```bash
memla research eval-harness --input historical_decision_logs.jsonl --normalize-capture --frontier-use-logged-decisions --memla-provider openai --memla-base-url https://internal-llm-api.example/v1 --memla-model qwen2.5-14b-instruct --pricing-profile perplexity_public_sonar
memla coding plan --prompt "Fix the auth regression" --repo-root .
memla coding run --prompt "Repair the failing auth tests" --repo-root . --test-command "pytest -q"
memla coding benchmark-compile --cases cases/coding_eval_cases.jsonl --repo-root . --model qwen3.5:9b
memla coding benchmark-c2a --cases cases/coding_eval_cases.jsonl --repo-root . --raw-model qwen3.5:9b --memla-model qwen3.5:9b
memla finance benchmark-pretrade --cases cases/finance_pretrade_eval_cases.jsonl --raw-model meta/Llama-3.3-70B-Instruct --memla-model qwen3.5:9b
memla finance benchmark-pretrade --cases cases/finance_pretrade_public_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
memla healthcare benchmark-denials --cases cases/healthcare_denial_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
memla policy benchmark-authz --cases cases/policy_authz_eval_cases.jsonl --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
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
memla policy extract-authz --report memla_reports/policy_deepseek_change_window_vs_9bmemla/policy_authz_benchmark_report.json
memla policy distill-authz --trace-bank memla_reports/policy_trace_bank_deepseek_change_window/policy_trace_bank_summary.json --repo-root .
memla finance extract-pretrade --report memla_reports/finance_pretrade_benchmark_20260404_161024/finance_pretrade_benchmark_report.json
memla finance distill-pretrade --trace-bank memla_reports/finance_pretrade_extract/finance_trace_bank_summary.json --repo-root .
memla coding extract-c2a --report memla_reports/coding_c2a_9braw_vs_9bmemla/coding_c2a_benchmark_report.json --report memla_reports/coding_c2a_405braw_vs_9bmemla/coding_c2a_benchmark_report.json
memla coding distill-c2a --trace-bank memla_reports/c2a_trace_bank_seed/c2a_trace_bank_summary.json --repo-root .
memla coding benchmark-c2a --cases cases/coding_eval_cases.jsonl --repo-root . --raw-model qwen3.5:9b --memla-model qwen3.5:9b --raw-provider ollama --raw-base-url http://127.0.0.1:11435 --memla-provider ollama --memla-base-url http://127.0.0.1:11435
memla math benchmark --cases cases/math_linear_c2a_v2_harder.jsonl --teacher-model qwen2.5:32b --student-models qwen3.5:4b qwen3.5:9b --executor-mode stepwise_rerank --teacher-trace-source hybrid
```

Thin-client HTTP bridge:
- `GET /health`
- `GET /state`
- `GET /memory`
- `GET /actions`
- `POST /actions/plan`
- `POST /actions/draft`
- `POST /actions/capsule`
- `POST /run`
- `POST /scout`
- `POST /followup`

Example:

```bash
curl -X POST http://127.0.0.1:8080/scout ^
  -H "Content-Type: application/json" ^
  -d "{\"prompt\":\"find the top 10 github repos for local llms and tell me which best fits weak hardware\"}"
```

Public provenance for the bundled finance demo pack lives in `cases/finance_pretrade_public_sources.md`.
Public provenance for the bundled healthcare demo pack lives in `cases/healthcare_denial_public_sources.md`.
Public provenance for the bundled policy demo pack lives in `cases/policy_authz_public_sources.md`.

Project links:
- GitHub: [Jackfarmer2328/Memla-v2](https://github.com/Jackfarmer2328/Memla-v2)
- Proof site: [memla.vercel.app](https://memla.vercel.app)
