"""Reality Compiler Fortress v0: intent-to-law-to-proof contract."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def reality_compiler_fortress_v0_spec() -> dict[str, Any]:
    return {
        "fortress_id": "reality_compiler_fortress_v0",
        "intent": "Compile natural-language world laws into deterministic executable checks with proof.",
        "compiler_contract": {
            "input": "plain_language_world_law",
            "output": [
                "normalized_law_id",
                "event_schema_extensions",
                "constraint_function_spec",
                "failure_counterexample_path",
                "passing_proof_artifact",
            ],
        },
        "suites": [
            {
                "suite_id": "law_compilation_suite",
                "target": "Natural-language law compiles to explicit deterministic check spec.",
                "checks": [
                    "lc_parse_determinism",
                    "lc_schema_extension_validity",
                    "lc_constraint_emission_completeness",
                ],
                "required_artifacts": ["compiled_laws.json", "schema_patch.json"],
            },
            {
                "suite_id": "violation_witness_suite",
                "target": "Failing worlds produce concrete counterexample traces.",
                "checks": [
                    "vw_minimal_counterexample_trace",
                    "vw_violation_localization",
                    "vw_replayable_failure_path",
                ],
                "required_artifacts": ["violation_witnesses.json", "failure_replay_trace.json"],
            },
            {
                "suite_id": "proof_of_compliance_suite",
                "target": "Passing worlds emit signed deterministic proof bundles.",
                "checks": [
                    "pc_proof_bundle_integrity",
                    "pc_replay_equivalence",
                    "pc_proof_hash_stability",
                ],
                "required_artifacts": ["proof_bundles.json", "proof_hashes.json"],
            },
            {
                "suite_id": "law_mutation_regression_suite",
                "target": "Small law edits trigger expected constraint deltas only.",
                "checks": [
                    "lm_diff_scoping",
                    "lm_backward_compatibility_report",
                    "lm_regression_guard_coverage",
                ],
                "required_artifacts": ["law_diffs.json", "compatibility_report.json"],
            },
            {
                "suite_id": "diegetic_law_explanation_suite",
                "target": "NPC/world explanations cite law clauses and event evidence in-world.",
                "checks": [
                    "dl_clause_citation_integrity",
                    "dl_event_evidence_alignment",
                    "dl_role_voice_consistency",
                ],
                "required_artifacts": ["diegetic_law_explanations.json", "law_citation_map.json"],
            },
        ],
        "gate_policy": {
            "minimum_suite_pass_rate": 1.0,
            "critical_checks_must_pass": [
                "lc_parse_determinism",
                "vw_replayable_failure_path",
                "pc_replay_equivalence",
                "pc_proof_hash_stability",
                "dl_clause_citation_integrity",
            ],
        },
    }


def write_reality_compiler_seed(*, output_dir: str) -> dict[str, str]:
    out = Path(output_dir).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = reality_compiler_fortress_v0_spec()
    spec_path = out / "reality_compiler_fortress_v0_spec.json"
    manifest_path = out / "reality_compiler_run_manifest.json"
    spec_path.write_text(json.dumps(spec, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    manifest = {
        "fortress_id": spec["fortress_id"],
        "status": "seed_ready",
        "next_step": "run_32b_law_compiler_dossier",
        "required_outputs": [suite["required_artifacts"] for suite in spec["suites"]],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"spec_path": str(spec_path), "manifest_path": str(manifest_path)}
