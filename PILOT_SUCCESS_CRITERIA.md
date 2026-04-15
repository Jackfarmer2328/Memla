# Memla Pilot Success Criteria (Go / No-Go)

Last updated: 2026-04-14

This document defines the minimum acceptance gates for a production pilot of Memla’s bounded research-loop decision routing.

## 1) Scope of claim

Memla optimizes **only** the bounded Phase-3 decision fork (`search_more` vs `converge`).
It does **not** claim full-agent replacement.

## 2) Primary safety gate (must pass)

- **Metric:** False-converge rate delta vs frontier baseline
- **Definition:**
  - False-converge = model decides `converge` but required sub-topic evidence is absent in final report
- **Acceptance gate:**
  - Memla false-converge rate ≤ Frontier false-converge rate + agreed margin (default: +3.0pp)
- **Failure action:**
  - Auto-disable Memla routing for affected cohort
  - Immediate fallback to frontier-only decisioning

## 3) Quality non-regression gate (must pass)

- **Metric:** Coverage pass proxy (same rubric as baseline)
- **Acceptance gate:**
  - Non-inferior to baseline within agreed margin
- **Failure action:**
  - Freeze rollout expansion
  - Recalibrate threshold or revert lane

## 4) Economic gate (must pass)

- **Metric:** Estimated cost per 1,000 sessions
- **Acceptance gate:**
  - Positive savings vs frontier baseline after including fallback usage
- **Stress check:**
  - Recompute under alternate token pricing and fallback-rate assumptions
- **Benchmarking note:**
  - Public-facing benchmark pages may use modeled pricing assumptions from public provider docs.
  - Pilot go / no-go must be recomputed with customer-internal cost data and observed fallback inside the pilot environment.

## 5) Reliability and latency gates (must pass)

- **Metrics:**
  - Decision latency p50/p95/p99
  - Timeout rate
  - Fallback (escalation) rate
  - Error rate
- **Acceptance gates:**
  - No breach of agreed per-decision latency budget
  - Timeout/error rates below agreed threshold
- **Failure action:**
  - Shift traffic to fallback path
  - Investigate and patch before re-enabling

## 6) Causality and benchmarking integrity (must pass)

- Use paired replay where possible (same trace state, lane-only swap)
- Publish raw counts with percentages (not percentages alone)
- Publish confidence intervals once sample size is sufficient
- Include worst-slice performance (domain/task/complexity), not only aggregate average

## 7) Labeling and audit process (must pass)

- Label rubric documented and versioned
- Blinded second-pass audit slice performed on each benchmark refresh
- Disagreement rate disclosed

## 8) Security and data handling gates (must pass)

- Data flow for routing path documented
- Retention policy documented
- Redaction boundary documented
- No policy violations in pilot telemetry handling

## 9) Rollback protocol

- One-switch rollback to frontier-only routing must be available at all times
- Rollback condition examples:
  - False-converge gate breach
  - Latency SLO breach
  - Elevated timeout/error rate
  - Security/policy incident

## 10) Production decision rule

- **Go:** All mandatory gates pass for agreed pilot window and sample size.
- **No-Go:** Any mandatory safety/reliability/security gate fails.
- **Iterate:** Optional/economic gate misses with safety intact; recalibrate and rerun pilot segment.

---

## Pilot reporting template (minimum)

- Cohort size (sessions, decisions)
- False-converge rates (Memla vs frontier), with counts
- Delta vs acceptance margin
- Coverage pass proxy (Memla vs frontier)
- Cost per 1,000 sessions (Memla vs frontier)
- p50/p95/p99 decision latency
- Timeout/error/fallback rates
- Slice table (best/median/worst)
- Final verdict: Go / No-Go / Iterate
