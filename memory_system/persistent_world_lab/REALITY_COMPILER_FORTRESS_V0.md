# Reality Compiler Fortress v0

This fortress is the next layer past Abyss. It treats world rules as compilable law.

## Core proposition

Given a plain-language world law, the system must:

1. compile it into deterministic constraint logic
2. produce replayable failure witnesses on violation
3. produce deterministic proof bundles on compliance

## Suites

1) `law_compilation_suite`
- `lc_parse_determinism`
- `lc_schema_extension_validity`
- `lc_constraint_emission_completeness`

2) `violation_witness_suite`
- `vw_minimal_counterexample_trace`
- `vw_violation_localization`
- `vw_replayable_failure_path`

3) `proof_of_compliance_suite`
- `pc_proof_bundle_integrity`
- `pc_replay_equivalence`
- `pc_proof_hash_stability`

4) `law_mutation_regression_suite`
- `lm_diff_scoping`
- `lm_backward_compatibility_report`
- `lm_regression_guard_coverage`

5) `diegetic_law_explanation_suite`
- `dl_clause_citation_integrity`
- `dl_event_evidence_alignment`
- `dl_role_voice_consistency`

## Gate policy

- 100% suite pass required.
- Critical checks:
  - `lc_parse_determinism`
  - `vw_replayable_failure_path`
  - `pc_replay_equivalence`
  - `pc_proof_hash_stability`
  - `dl_clause_citation_integrity`

## Required artifact pack

- `compiled_laws.json`
- `schema_patch.json`
- `violation_witnesses.json`
- `failure_replay_trace.json`
- `proof_bundles.json`
- `proof_hashes.json`
- `law_diffs.json`
- `compatibility_report.json`
- `diegetic_law_explanations.json`
- `law_citation_map.json`

## Run order

1. Seed `reality_compiler_fortress_v0_spec.json`.
2. Run 32b dossier generation with strict contract adherence.
3. Implement compilation + witness pipeline against first failing suite.
4. Feed discovered edge constraints back into this fortress.
