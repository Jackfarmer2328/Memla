# Abyss Fortress v0 — full-dive continuity physics contract

This fortress defines the next novelty floor beyond white-room. It is software-only and focuses on continuity physics needed for eventual full-dive worlds.

## Goal

Build a deterministic, auditable runtime where:

- identity survives over long horizons without silent drift
- subjective timelines reconcile into canonical history
- belief contamination paths are explicitly traceable
- social phase shifts are causally attributable
- counterfactual futures are ranked, reproducible, and explainable
- in-world explanations cite valid history and preserve role voice

## Suites

1) `identity_continuity_suite`
- `ic_signature_stability`
- `ic_drift_alarm_recall`
- `ic_impersonation_detection`

2) `subjective_time_reconciliation_suite`
- `st_clock_merge_determinism`
- `st_reentry_equivalence`
- `st_latency_budget`

3) `belief_contagion_suite`
- `bc_origin_traceability`
- `bc_mutation_chain_integrity`
- `bc_falsehood_containment`

4) `social_phase_transition_suite`
- `sp_transition_trigger_trace`
- `sp_hysteresis_consistency`
- `sp_recovery_window_bounds`

5) `counterfactual_search_validity_suite`
- `cs_rank_stability`
- `cs_plausibility_floor`
- `cs_delta_explainability`

6) `diegetic_explainability_suite`
- `de_citation_integrity`
- `de_role_voice_consistency`
- `de_explanation_completeness`

## Gate policy

- 100% suites pass required for "green".
- Critical checks cannot fail:
  - `ic_signature_stability`
  - `st_clock_merge_determinism`
  - `bc_origin_traceability`
  - `cs_rank_stability`
  - `de_citation_integrity`

## Required artifact pack

- `identity_signatures.json`
- `identity_alerts.json`
- `subjective_timeline.json`
- `merge_trace.json`
- `belief_graph.json`
- `contagion_paths.json`
- `social_field_state.json`
- `transition_events.json`
- `counterfactual_rankings.json`
- `fork_deltas.json`
- `diegetic_explanations.json`
- `citation_map.json`

## Run order

1. Seed artifact contract from code: `abyss_fortress_v0_spec.json`.
2. Run 32b dossier generation against this contract.
3. Implement first failing suite in isolation.
4. Add new reality constraints discovered during implementation back into this fortress.
5. Re-run until gate policy is green.

## Positioning

White-room demonstrates deterministic persistent world substrate.

Abyss fortress targets continuity physics novelty:

- not just memory retention
- but identity proof, subjective-time reconciliation, contagion traceability, and diegetic explainability under replay.
