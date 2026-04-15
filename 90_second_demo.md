# 90-Second Demo Flow

1. Open the current coding patch report.
   Hosted Meta-Llama-3.1-405B-Instruct raw apply rate: `0`. qwen3.5:9b + Memla apply rate: `1`.
   Raw semantic success: `0`. Memla semantic success: `1`.
2. Open the same-model control.
   qwen3.5:9b raw apply rate: `0`. qwen3.5:9b + Memla apply rate: `1`.
   Raw semantic success: `0`. Memla semantic success: `0.6667`.
3. Show the second repo-family repeat.
   Hosted Llama-3.3-70B raw apply rate: `0`. qwen3.5:9b + Memla apply rate: `0.3333`.
   Same shape on FastAPI, even though semantic success stayed flat there.
4. Show the Grok support rung.
   On OAuth, hosted Grok-3 raw stayed at `0` apply / `0` semantic success while qwen3.5:9b + Memla reached `0.6667` / `0.6667`.
   On FastAPI, hosted Grok-3 raw again stayed at `0` apply while qwen3.5:9b + Memla reached `0.5` apply on 2 completed cases.
5. Show the first self-transmutation rung.
   Earlier pure coding C2A baseline: qwen3.5:9b raw `0.2742`, qwen3.5:9b + Memla `0.4908`.
   After loading the 405b-only bank, same-model Memla utility repeated at `0.5058` across 3 runs, average uplift `+0.015`.
   That same bank also moved same-model OAuth patch apply from `0.6667` to `1.0` while semantic success held at `0.6667`.
6. Open the math reranker report with the executor held constant.
   4b ambiguous-step choice accuracy: `0.5455` -> `1`.
   9b ambiguous-step choice accuracy: `0.4545` -> `1`.
7. Open the harder end-to-end math report.
   4b raw solve accuracy: `0.875`. 4b + Memla: `1`. Teacher raw: `1`.
8. Close with the thesis: Memla improves the decisions that bounded executors turn into real work, and it can now start learning those decisions back into itself.
