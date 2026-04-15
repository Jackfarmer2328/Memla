"""Public Memla distillation surface used by the CLI and bundled tests."""

from .coding_log import CodingTrace, CodingTraceLog, SimilarCodingTrace
from .compile_loop_benchmark import (
    render_compile_loop_benchmark_markdown,
    run_compile_loop_benchmark,
)
from .exporter import export_accepted_traces_to_jsonl, trace_to_training_record
from .git_history_cases import build_git_eval_cases, load_commit_records
from .math_c2a_benchmark import (
    capture_hybrid_teacher_math_traces,
    capture_symbolic_teacher_math_traces,
    capture_teacher_math_traces,
    load_math_c2a_cases,
    render_math_c2a_teacher_student_markdown,
    run_math_c2a_teacher_student_benchmark,
)
from .patch_execution_benchmark import (
    load_patch_cases,
    render_patch_execution_markdown,
    run_patch_execution_benchmark,
)
from .thesis_pack_builder import build_thesis_pack
from .workflow_planner import WorkflowPlan, build_workflow_plan, render_workflow_plan_block

__all__ = [
    "CodingTrace",
    "CodingTraceLog",
    "SimilarCodingTrace",
    "WorkflowPlan",
    "build_git_eval_cases",
    "build_thesis_pack",
    "build_workflow_plan",
    "capture_hybrid_teacher_math_traces",
    "capture_symbolic_teacher_math_traces",
    "capture_teacher_math_traces",
    "export_accepted_traces_to_jsonl",
    "load_commit_records",
    "load_math_c2a_cases",
    "load_patch_cases",
    "render_compile_loop_benchmark_markdown",
    "render_math_c2a_teacher_student_markdown",
    "render_patch_execution_markdown",
    "render_workflow_plan_block",
    "run_compile_loop_benchmark",
    "run_math_c2a_teacher_student_benchmark",
    "run_patch_execution_benchmark",
    "trace_to_training_record",
]
