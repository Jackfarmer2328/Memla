"""Abyss Fortress v0: full-dive aligned software-only constraint contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def abyss_fortress_v0_spec() -> dict[str, Any]:
    return {
        "fortress_id": "abyss_fortress_v0",
        "intent": "Software-only continuity physics for full-dive worlds.",
        "suites": [
            {
                "suite_id": "identity_continuity_suite",
                "target": "Detect identity drift, impersonation, and coercion over replay windows.",
                "checks": [
                    "ic_signature_stability",
                    "ic_drift_alarm_recall",
                    "ic_impersonation_detection",
                ],
                "required_artifacts": ["identity_signatures.json", "identity_alerts.json"],
            },
            {
                "suite_id": "subjective_time_reconciliation_suite",
                "target": "Reconcile per-agent subjective time into canonical timeline without contradiction.",
                "checks": [
                    "st_clock_merge_determinism",
                    "st_reentry_equivalence",
                    "st_latency_budget",
                ],
                "required_artifacts": ["subjective_timeline.json", "merge_trace.json"],
            },
            {
                "suite_id": "belief_contagion_suite",
                "target": "Track rumor propagation/mutation and contamination paths with provenance.",
                "checks": [
                    "bc_origin_traceability",
                    "bc_mutation_chain_integrity",
                    "bc_falsehood_containment",
                ],
                "required_artifacts": ["belief_graph.json", "contagion_paths.json"],
            },
            {
                "suite_id": "social_phase_transition_suite",
                "target": "Model social gravity and phase transitions (peace->conflict->recovery).",
                "checks": [
                    "sp_transition_trigger_trace",
                    "sp_hysteresis_consistency",
                    "sp_recovery_window_bounds",
                ],
                "required_artifacts": ["social_field_state.json", "transition_events.json"],
            },
            {
                "suite_id": "counterfactual_search_validity_suite",
                "target": "Rank plausible forks and keep deterministic causal divergence accounting.",
                "checks": [
                    "cs_rank_stability",
                    "cs_plausibility_floor",
                    "cs_delta_explainability",
                ],
                "required_artifacts": ["counterfactual_rankings.json", "fork_deltas.json"],
            },
            {
                "suite_id": "diegetic_explainability_suite",
                "target": "Ensure in-world explanations cite valid history and remain role-consistent.",
                "checks": [
                    "de_citation_integrity",
                    "de_role_voice_consistency",
                    "de_explanation_completeness",
                ],
                "required_artifacts": ["diegetic_explanations.json", "citation_map.json"],
            },
        ],
        "gate_policy": {
            "minimum_suite_pass_rate": 1.0,
            "critical_checks_must_pass": [
                "ic_signature_stability",
                "st_clock_merge_determinism",
                "bc_origin_traceability",
                "cs_rank_stability",
                "de_citation_integrity",
            ],
        },
    }


def write_abyss_fortress_seed(*, output_dir: str) -> dict[str, str]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = abyss_fortress_v0_spec()
    spec_path = out / "abyss_fortress_v0_spec.json"
    run_path = out / "abyss_run_manifest.json"
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    run_manifest = {
        "fortress_id": spec["fortress_id"],
        "status": "seed_ready",
        "next_step": "run_32b_dossier_generation",
        "required_outputs": [suite["required_artifacts"] for suite in spec["suites"]],
    }
    run_path.write_text(json.dumps(run_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"spec_path": str(spec_path), "manifest_path": str(run_path)}
