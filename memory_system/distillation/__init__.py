"""Distillation substrate for coding and workflow traces."""

from .acquisition_pack_builder import (
    build_acquisition_pack,
    render_acquisition_demo_flow,
    render_acquisition_pitch,
    render_buyer_targets,
    render_outreach_email,
    render_strategic_memo,
)
from .batch_runner import (
    CurriculumRepoSpec,
    load_repo_curriculum,
    render_batch_markdown,
    run_repo_curriculum,
)
from .coding_log import CodingTrace, CodingTraceLog, SimilarCodingTrace
from .comparison_runner import render_head_to_head_markdown, run_head_to_head
from .constraint_graph import (
    infer_constraint_tags,
    infer_file_roles,
    infer_prompt_roles,
    infer_repo_family,
    scan_repo_role_matches,
    summarize_constraint_trades,
    summarize_transmutations,
    transmutation_specificity,
)
from .diligence_packet_builder import (
    build_diligence_packet,
    render_diligence_faq,
    render_diligence_summary,
    render_proof_table,
    render_technical_diligence,
)
from .demo_runner import render_demo_markdown, run_bootstrap_demo, run_showcase_demo
from .exporter import export_accepted_traces_to_jsonl, trace_to_training_record
from .eval_harness import evaluate_workflow_plans, load_eval_cases
from .git_history_cases import build_git_eval_cases, load_commit_records
from .pitch_pack_builder import build_pitch_pack, render_demo_flow, render_one_sentence_pitch
from .seed_runner import load_seed_cases, run_seed_cases
from .transfer_eval import render_transfer_markdown, run_transfer_eval
from .workflow_planner import WorkflowPlan, build_workflow_plan, render_workflow_plan_block

__all__ = [
    "CodingTrace",
    "CodingTraceLog",
    "CurriculumRepoSpec",
    "SimilarCodingTrace",
    "build_acquisition_pack",
    "build_diligence_packet",
    "WorkflowPlan",
    "build_workflow_plan",
    "infer_constraint_tags",
    "infer_file_roles",
    "infer_prompt_roles",
    "infer_repo_family",
    "scan_repo_role_matches",
    "summarize_constraint_trades",
    "summarize_transmutations",
    "transmutation_specificity",
    "run_head_to_head",
    "render_head_to_head_markdown",
    "run_showcase_demo",
    "run_bootstrap_demo",
    "render_demo_markdown",
    "evaluate_workflow_plans",
    "load_eval_cases",
    "build_git_eval_cases",
    "load_commit_records",
    "build_pitch_pack",
    "render_acquisition_demo_flow",
    "render_acquisition_pitch",
    "render_buyer_targets",
    "render_batch_markdown",
    "render_diligence_faq",
    "render_diligence_summary",
    "render_demo_flow",
    "render_outreach_email",
    "render_one_sentence_pitch",
    "render_proof_table",
    "render_strategic_memo",
    "render_technical_diligence",
    "load_repo_curriculum",
    "load_seed_cases",
    "run_repo_curriculum",
    "run_seed_cases",
    "run_transfer_eval",
    "render_transfer_markdown",
    "render_workflow_plan_block",
    "export_accepted_traces_to_jsonl",
    "trace_to_training_record",
]
