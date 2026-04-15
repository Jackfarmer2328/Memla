# Research Loop Trace Cleanup Report

- Source file: `jsons`
- Output cleaned JSONL: `cases/research_loop_traces_cleaned_v1.jsonl`
- session_id starts found: 77
- candidate objects extracted by brace matching: 76
- cleaned objects written: 66
- repaired malformed objects: 0
- dropped/unparsed objects: 10
- unique sessions: 19
- sessions with converge: 17/19

## Extraction failures
- offset 59320: unclosed object

## Dropped objects
- offset 103721: `Expecting ',' delimiter: line 1 column 1307 (char 1306)` · preview: `{"session_id":"local_code_completion_2026_1","step_index":1,"prompt":"Search for recent (2025–2026) information on local/offline code completion stacks and self-hosted AI coding assistants (Tabby, Con`
- offset 107264: `Expecting ',' delimiter: line 1 column 2066 (char 2065)` · preview: `{"session_id":"local_code_completion_2026_1","step_index":2,"prompt":"Search for technical reports and benchmarks of modern open-source code LLMs (Qwen2.5-Coder, DeepSeek-Coder-V2, StarCoder2) and any`
- offset 111558: `Expecting ',' delimiter: line 1 column 542 (char 541)` · preview: `{"session_id":"local_code_completion_2026_1","step_index":3,"prompt":"Search for 2025–2026 comparisons and opinion pieces on self-hosted AI coding assistants (Tabby, Continue) and local coding setups `
- offset 197545: `Expecting ',' delimiter: line 1 column 754 (char 753)` · preview: `{"session_id":"wf-orch-2026-001","step_index":1,"prompt":"Map the 2025–2026 open-source workflow orchestration landscape for data and ML; identify main candidates and broad positioning.","user_goal":"`
- offset 199783: `Expecting ',' delimiter: line 1 column 720 (char 719)` · preview: `{"session_id":"wf-orch-2026-001","step_index":2,"prompt":"Deep-dive into Airflow, Dagster, and Prefect as data orchestrators; extract features, DX, pros/cons, and any data+ML positioning from 2024–202`
- offset 202572: `Expecting ',' delimiter: line 1 column 868 (char 867)` · preview: `{"session_id":"wf-orch-2026-001","step_index":3,"prompt":"Deep-dive into Flyte, Metaflow, Kubeflow Pipelines, and ZenML as ML-centric orchestrators; gather architecture, scale case studies, and how th`
- offset 205598: `Expecting ',' delimiter: line 1 column 848 (char 847)` · preview: `{"session_id":"wf-orch-2026-001","step_index":4,"prompt":"Gather independent benchmarks/adoption signals (CNCF radar, surveys, case studies) and community sentiment (Reddit, blogs) to compare maturity`
- offset 208529: `Expecting ',' delimiter: line 1 column 1521 (char 1520)` · preview: `{"session_id":"wf-orch-2026-001","step_index":5,"prompt":"Synthesize all evidence to pick a 2026 default orchestrator for mixed data+ML pipelines and specify when alternatives (Flyte, Airflow, Prefect`
- offset 218721: `Expecting ',' delimiter: line 1 column 682 (char 681)` · preview: `{"session_id":"ai-gateway-20260414-1","step_index":3,"prompt":"Deep-dive into Bifrost and Helicone (features, performance, observability) and look for meta-comparisons of open-source AI gateways in 20`
- offset 221718: `Expecting ',' delimiter: line 1 column 806 (char 805)` · preview: `{"session_id":"ai-gateway-20260414-1","step_index":4,"prompt":"Verify APISIX AI Gateway’s AI-specific plugins (ai-proxy, ai-proxy-multi, ai-rate-limiting, observability) and gather evidence on rate li`

## Session summary

| session_id | steps | min_step | max_step | has_converge |
|---|---:|---:|---:|:---:|
| agent-frameworks-2026-prod-rel | 4 | 0 | 3 | yes |
| ai-gateway-20260414-1 | 2 | 1 | 2 | no |
| browser-qa-2026-01 | 3 | 1 | 3 | yes |
| cpu-llm-2026-weak-hw | 3 | 1 | 3 | yes |
| financial_legal_pdfs_2026_1 | 5 | 0 | 4 | yes |
| fs-research-2026-01 | 3 | 1 | 3 | yes |
| k8s-serving-2026 | 3 | 0 | 2 | yes |
| local_code_completion_2026_1 | 1 | 0 | 0 | no |
| ocr-research-2026-04-14-1 | 4 | 1 | 4 | yes |
| open_lakehouse_2026 | 4 | 1 | 4 | yes |
| oss-secrets-2026-01 | 3 | 0 | 2 | yes |
| rag-stack-small-team-2026 | 4 | 0 | 3 | yes |
| sess-guardrails-20260414 | 4 | 1 | 4 | yes |
| session-llm-observability-2026-001 | 3 | 0 | 2 | yes |
| session_vector_db_hw_2026 | 3 | 0 | 2 | yes |
| siem-cloud-native-2026-13 | 5 | 0 | 4 | yes |
| stream-engines-2026-01 | 4 | 1 | 4 | yes |
| stt-lowresource-2026-04-14-01 | 5 | 0 | 5 | yes |
| tsdb-high-card-2026-01 | 3 | 0 | 2 | yes |
