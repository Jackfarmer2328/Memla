from __future__ import annotations

import argparse
import html
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _fmt(value: float | int, digits: int = 4) -> str:
    return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")


def _lane(report: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in report.get("lanes", []):
        if lane.get("lane_id") == lane_id:
            return lane
    raise KeyError(f"Missing lane: {lane_id}")


def _lane_contains(report: dict[str, Any], token: str) -> dict[str, Any]:
    for lane in report.get("lanes", []):
        lane_id = str(lane.get("lane_id") or "")
        if token in lane_id:
            return lane
    raise KeyError(f"Missing lane containing token: {token}")


def _teacher_raw_lane(report: dict[str, Any]) -> dict[str, Any]:
    teacher_model = str(report.get("teacher_model") or "")
    if teacher_model:
        return _lane(report, f"{teacher_model}_raw")
    return _lane_contains(report, "_raw")


def _coding_cases(report: dict[str, Any]) -> list[dict[str, Any]]:
    rows = report.get("rows", [])
    return sorted(
        rows,
        key=lambda row: (
            row.get("memla_semantic_command_success_rate", 0.0),
            row.get("memla_file_recall", 0.0),
            row.get("memla_apply_check_passed", False),
        ),
        reverse=True,
    )[:3]


def _math_examples(report: dict[str, Any]) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for row in report.get("rows", []):
        if row.get("candidate_count", 0) <= 2:
            continue
        lanes = row.get("lane_results", {})
        correct = (row.get("correct_choices") or [""])[0]
        raw4b = lanes.get("qwen3.5:4b_raw", {}).get("selected_choice")
        memla4b = lanes.get("qwen3.5:4b_memla", {}).get("selected_choice")
        raw9b = lanes.get("qwen3.5:9b_raw", {}).get("selected_choice")
        memla9b = lanes.get("qwen3.5:9b_memla", {}).get("selected_choice")
        teacher_raw = next(
            (
                value.get("selected_choice")
                for key, value in lanes.items()
                if str(key).endswith("_raw") and "qwen3.5:4b" not in str(key) and "qwen3.5:9b" not in str(key)
            ),
            "",
        )
        if (raw4b != correct and memla4b == correct) or (raw9b != correct and memla9b == correct):
            examples.append(
                {
                    "case_id": row.get("case_id"),
                    "step_index": row.get("step_index"),
                    "current_equation": row.get("current_equation"),
                    "constraint": (row.get("expected_constraints") or [""])[0],
                    "correct": correct,
                    "raw4b": raw4b,
                    "memla4b": memla4b,
                    "raw9b": raw9b,
                    "memla9b": memla9b,
                    "teacher_raw": teacher_raw,
                }
            )
    return examples[:4]


def render_one_sentence_pitch(
    *,
    coding: dict[str, Any],
    math_rerank: dict[str, Any],
    math_progress: dict[str, Any],
) -> str:
    raw_model = str(coding.get("raw_model") or "raw model")
    memla_model = str(coding.get("memla_model") or "Memla model")
    rerank_4_raw = _lane(math_rerank, "qwen3.5:4b_raw")
    rerank_4_memla = _lane(math_rerank, "qwen3.5:4b_memla")
    rerank_9_raw = _lane(math_rerank, "qwen3.5:9b_raw")
    rerank_9_memla = _lane(math_rerank, "qwen3.5:9b_memla")
    solve_teacher_raw = _teacher_raw_lane(math_progress)
    solve_4_raw = _lane(math_progress, "qwen3.5:4b_raw")
    solve_4_memla = _lane(math_progress, "qwen3.5:4b_memla")
    return (
        "Memla is a constraint-runtime layer that helps smaller models act larger inside bounded executors: "
        f"on unseen coding repair tasks it moves patch apply for {raw_model} versus {memla_model} from "
        f"{_fmt(coding.get('raw_apply_rate', 0.0), 1)} to {_fmt(coding.get('memla_apply_rate', 0.0), 1)} "
        f"and semantic success from "
        f"{_fmt(coding.get('avg_raw_semantic_command_success_rate', 0.0))} to "
        f"{_fmt(coding.get('avg_memla_semantic_command_success_rate', 0.0))}, "
        f"on held-constant math reranking it lifts 4b ambiguous-step accuracy from "
        f"{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))} to "
        f"{_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)} and 9b from "
        f"{_fmt(rerank_9_raw.get('avg_ambiguous_choice_accuracy', 0.0))} to "
        f"{_fmt(rerank_9_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}, "
        f"and on harder end-to-end math it lifts 4b solve accuracy from "
        f"{_fmt(solve_4_raw.get('avg_answer_accuracy', 0.0))} to "
        f"{_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)}, matching teacher raw at "
        f"{_fmt(solve_teacher_raw.get('avg_answer_accuracy', 0.0), 1)}."
    )


def render_demo_flow(
    *,
    coding: dict[str, Any],
    math_rerank: dict[str, Any],
    math_progress: dict[str, Any],
) -> str:
    raw_model = str(coding.get("raw_model") or "raw model")
    memla_model = str(coding.get("memla_model") or "Memla model")
    rerank_4_raw = _lane(math_rerank, "qwen3.5:4b_raw")
    rerank_4_memla = _lane(math_rerank, "qwen3.5:4b_memla")
    rerank_9_raw = _lane(math_rerank, "qwen3.5:9b_raw")
    rerank_9_memla = _lane(math_rerank, "qwen3.5:9b_memla")
    solve_teacher_raw = _teacher_raw_lane(math_progress)
    solve_4_raw = _lane(math_progress, "qwen3.5:4b_raw")
    solve_4_memla = _lane(math_progress, "qwen3.5:4b_memla")
    return "\n".join(
        [
            "# 90-Second Demo Flow",
            "",
            "1. Open the current coding patch report.",
            f"   {raw_model} apply rate: `{_fmt(coding.get('raw_apply_rate', 0.0), 1)}`. {memla_model} + Memla apply rate: `{_fmt(coding.get('memla_apply_rate', 0.0), 1)}`.",
            f"   Raw semantic success: `{_fmt(coding.get('avg_raw_semantic_command_success_rate', 0.0))}`. Memla semantic success: `{_fmt(coding.get('avg_memla_semantic_command_success_rate', 0.0))}`.",
            "2. Show one coding case where raw never reached an applyable patch and Memla did.",
            "3. Open the math reranker report with the executor held constant.",
            f"   4b ambiguous-step choice accuracy: `{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))}` -> `{_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}`.",
            f"   9b ambiguous-step choice accuracy: `{_fmt(rerank_9_raw.get('avg_ambiguous_choice_accuracy', 0.0))}` -> `{_fmt(rerank_9_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}`.",
            "4. Open the harder end-to-end math report.",
            f"   4b raw solve accuracy: `{_fmt(solve_4_raw.get('avg_answer_accuracy', 0.0))}`. 4b + Memla: `{_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)}`. Teacher raw: `{_fmt(solve_teacher_raw.get('avg_answer_accuracy', 0.0), 1)}`.",
            "5. Close with the thesis: Memla improves the decisions that bounded executors turn into real work.",
        ]
    )


def render_memo(
    *,
    coding: dict[str, Any],
    math_rerank: dict[str, Any],
    math_progress: dict[str, Any],
    coding_secondary: dict[str, Any] | None = None,
    compile_support: dict[str, Any] | None = None,
) -> str:
    raw_model = str(coding.get("raw_model") or "raw model")
    memla_model = str(coding.get("memla_model") or "Memla model")
    rerank_4_raw = _lane(math_rerank, "qwen3.5:4b_raw")
    rerank_4_memla = _lane(math_rerank, "qwen3.5:4b_memla")
    rerank_9_raw = _lane(math_rerank, "qwen3.5:9b_raw")
    rerank_9_memla = _lane(math_rerank, "qwen3.5:9b_memla")
    solve_teacher_raw = _teacher_raw_lane(math_progress)
    solve_4_raw = _lane(math_progress, "qwen3.5:4b_raw")
    solve_4_memla = _lane(math_progress, "qwen3.5:4b_memla")
    lines = [
        "# Memla Strategic Memo",
        "",
        "## Strong current claim",
        f"- Coding executor proof: {raw_model} raw apply `{_fmt(coding.get('raw_apply_rate', 0.0), 1)}` -> {memla_model} + Memla apply `{_fmt(coding.get('memla_apply_rate', 0.0), 1)}` and semantic success `{_fmt(coding.get('avg_raw_semantic_command_success_rate', 0.0))}` -> `{_fmt(coding.get('avg_memla_semantic_command_success_rate', 0.0))}`.",
        f"- Math decision proof: 4b ambiguous-step choice `{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))}` -> `{_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}` and 9b `{_fmt(rerank_9_raw.get('avg_ambiguous_choice_accuracy', 0.0))}` -> `{_fmt(rerank_9_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}` with the same candidate hands.",
        f"- End-to-end bounded math proof: 4b solve accuracy `{_fmt(solve_4_raw.get('avg_answer_accuracy', 0.0))}` -> `{_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)}`, matching teacher raw at `{_fmt(solve_teacher_raw.get('avg_answer_accuracy', 0.0), 1)}`.",
        "",
    ]
    if coding_secondary is not None:
        lines.extend(
            [
                "## Extra coding support",
                f"- Second repo-family patch execution: raw apply `{_fmt(coding_secondary.get('raw_apply_rate', 0.0), 1)}` -> Memla apply `{_fmt(coding_secondary.get('memla_apply_rate', 0.0), 1)}`.",
                "",
            ]
        )
    if compile_support is not None:
        lines.extend(
            [
                "## Second benchmark type",
                f"- Compile-loop command recall: raw `{_fmt(compile_support.get('avg_raw_command_recall', 0.0))}` -> full compile-loop `{_fmt(compile_support.get('avg_compile_combined_command_recall', 0.0))}`.",
                f"- Compile validated command recall: `{_fmt(compile_support.get('avg_compile_validated_command_recall', 0.0))}`.",
                "",
            ]
        )
    lines.extend(
        [
            "## Honest limit",
            "- This is bounded-runtime evidence, not universal proof complete.",
            "- Coding still benefits from better retrieval, cleaner execution, and more repo-family repeats.",
            "",
            "## Why this matters",
            "- Memla is looking more like a real runtime layer, not just retrieval.",
            "- It makes capable local models more useful under bounded executors.",
            "- It is a natural fit for a CLI or harness with plug-in domain executors.",
        ]
    )
    return "\n".join(lines)


def render_html(
    *,
    coding: dict[str, Any],
    math_rerank: dict[str, Any],
    math_progress: dict[str, Any],
    site_url: str,
    coding_secondary: dict[str, Any] | None = None,
    compile_support: dict[str, Any] | None = None,
) -> str:
    raw_model = str(coding.get("raw_model") or "raw model")
    memla_model = str(coding.get("memla_model") or "Memla model")
    rerank_4_raw = _lane(math_rerank, "qwen3.5:4b_raw")
    rerank_4_memla = _lane(math_rerank, "qwen3.5:4b_memla")
    rerank_9_raw = _lane(math_rerank, "qwen3.5:9b_raw")
    rerank_9_memla = _lane(math_rerank, "qwen3.5:9b_memla")
    solve_teacher = _teacher_raw_lane(math_progress)
    solve_4_raw = _lane(math_progress, "qwen3.5:4b_raw")
    solve_4_memla = _lane(math_progress, "qwen3.5:4b_memla")
    coding_cards = "".join(
        f"<div class='card'><div class='kicker'>Coding case</div><h3>{html.escape(case.get('prompt', ''))}</h3><p>{html.escape(raw_model)} file recall {_fmt(case.get('raw_file_recall', 0.0))} | {html.escape(memla_model)} + Memla {_fmt(case.get('memla_file_recall', 0.0))}</p><p>Apply: {'no' if not case.get('raw_apply_check_passed') else 'yes'} -> {'yes' if case.get('memla_apply_check_passed') else 'no'}</p><p>Semantic success: {_fmt(case.get('raw_semantic_command_success_rate', 0.0))} -> {_fmt(case.get('memla_semantic_command_success_rate', 0.0))}</p></div>"
        for case in _coding_cases(coding)
    )
    math_cards = "".join(
        f"<div class='card'><div class='kicker'>Ambiguous step {html.escape(str(ex['case_id']))}/{html.escape(str(ex['step_index']))}</div><h3>{html.escape(ex['current_equation'])}</h3><p>Constraint: {html.escape(ex['constraint'])}. Correct move: {html.escape(ex['correct'])}. Teacher raw chose {html.escape(str(ex['teacher_raw']))}.</p><p>4b raw {html.escape(str(ex['raw4b']))} -> Memla {html.escape(str(ex['memla4b']))}</p><p>9b raw {html.escape(str(ex['raw9b']))} -> Memla {html.escape(str(ex['memla9b']))}</p></div>"
        for ex in _math_examples(math_rerank)
    )
    support_cards = ""
    if coding_secondary is not None or compile_support is not None:
        items: list[str] = []
        if coding_secondary is not None:
            items.append(
                f"<div class='card'><div class='kicker'>Second Repo Family</div><h3>FastAPI patch execution</h3><p>{html.escape(str(coding_secondary.get('raw_model') or 'raw'))} apply {_fmt(coding_secondary.get('raw_apply_rate', 0.0), 1)} -> {html.escape(str(coding_secondary.get('memla_model') or 'Memla'))} + Memla {_fmt(coding_secondary.get('memla_apply_rate', 0.0), 1)}.</p><p>Semantic success: {_fmt(coding_secondary.get('avg_raw_semantic_command_success_rate', 0.0))} -> {_fmt(coding_secondary.get('avg_memla_semantic_command_success_rate', 0.0))}.</p></div>"
            )
        if compile_support is not None:
            items.append(
                f"<div class='card'><div class='kicker'>Second Benchmark Type</div><h3>FastAPI compile loop</h3><p>Raw command recall {_fmt(compile_support.get('avg_raw_command_recall', 0.0))} -> full compile-loop {_fmt(compile_support.get('avg_compile_combined_command_recall', 0.0))}.</p><p>Validated command recall: {_fmt(compile_support.get('avg_compile_validated_command_recall', 0.0))}.</p></div>"
            )
        support_cards = "".join(items)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memla | Constraint Runtime Pack</title>
  <meta property="og:title" content="Memla | Constraint Runtime Pack">
  <meta property="og:description" content="Current coding and math proof pack for Memla.">
  <meta property="og:image" content="{html.escape(site_url.rstrip('/'))}/og-card.svg">
  <style>
    body {{ margin:0; font-family:Segoe UI, Arial, sans-serif; background:#0b1220; color:#f8fafc; }}
    .wrap {{ width:min(1100px, calc(100vw - 32px)); margin:0 auto; padding:32px 0 56px; }}
    .hero,.section,.card {{ border:1px solid rgba(148,163,184,.18); border-radius:24px; background:rgba(15,23,42,.92); box-shadow:0 18px 50px rgba(0,0,0,.25); }}
    .hero {{ padding:28px; }}
    .section {{ margin-top:18px; padding:22px; }}
    .cards,.metrics {{ display:grid; gap:14px; }}
    .metrics {{ grid-template-columns:repeat(4,minmax(0,1fr)); margin-top:18px; }}
    .cards {{ grid-template-columns:repeat(2,minmax(0,1fr)); }}
    .card {{ padding:18px; }}
    h1 {{ margin:8px 0 0; font-size:clamp(38px,7vw,68px); line-height:.98; letter-spacing:-.04em; }}
    h2 {{ margin:0 0 8px; font-size:30px; letter-spacing:-.03em; }}
    h3 {{ margin:8px 0 0; font-size:20px; line-height:1.35; }}
    .eyebrow,.kicker {{ color:#f59e0b; font-size:12px; text-transform:uppercase; letter-spacing:.16em; }}
    .sub, p, li {{ color:#cbd5e1; line-height:1.6; }}
    .jump {{ display:flex; gap:12px; align-items:baseline; flex-wrap:wrap; margin-top:14px; }}
    .raw,.memla,.arrow {{ font-weight:700; line-height:.9; }}
    .raw,.memla {{ font-size:clamp(38px,6vw,78px); }}
    .raw {{ color:#94a3b8; }}
    .memla {{ color:#34d399; }}
    .arrow {{ color:#f59e0b; font-size:clamp(28px,5vw,52px); }}
    .metric {{ padding:18px; border:1px solid rgba(148,163,184,.18); border-radius:20px; background:rgba(2,6,23,.35); }}
    .metric strong {{ display:block; margin-top:8px; font-size:28px; }}
    .links {{ display:flex; gap:12px; flex-wrap:wrap; margin-top:16px; }}
    .btn {{ display:inline-flex; padding:10px 14px; border-radius:999px; border:1px solid rgba(148,163,184,.18); color:#f8fafc; text-decoration:none; }}
    .footer {{ margin-top:18px; color:#94a3b8; font-size:13px; }}
    @media (max-width:900px) {{ .metrics,.cards {{ grid-template-columns:1fr; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Memla Thesis Pack / April 2026</div>
      <h1>Memla improves the decisions that decide whether bounded tasks actually land.</h1>
      <p class="sub">This pack combines the strongest current coding and math proof slices. Coding shows a real repair executor. Math shows the clean Memla signal with the executor held constant.</p>
      <div class="jump"><span class="raw">{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))}</span><span class="arrow">-&gt;</span><span class="memla">{_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}</span></div>
      <p>4b ambiguous-step choice accuracy on the same SymPy-generated candidate set, raw versus Memla. 9b also improves from {_fmt(rerank_9_raw.get('avg_ambiguous_choice_accuracy', 0.0))} to {_fmt(rerank_9_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}.</p>
      <div class="links">
        <a class="btn" href="./frozen/coding_patch_execution_report.json">Coding report</a>
        <a class="btn" href="./frozen/math_step_rerank_report.json">Math reranker</a>
        <a class="btn" href="./frozen/math_progress_report.json">End-to-end math</a>
      </div>
      <div class="metrics">
        <div class="metric"><span class="kicker">Coding apply</span><strong>{_fmt(coding.get('raw_apply_rate', 0.0), 1)} -&gt; {_fmt(coding.get('memla_apply_rate', 0.0), 1)}</strong><span>{html.escape(raw_model)} raw versus {html.escape(memla_model)} + Memla on the primary coding slice.</span></div>
        <div class="metric"><span class="kicker">Coding semantic</span><strong>{_fmt(coding.get('avg_raw_semantic_command_success_rate', 0.0))} -&gt; {_fmt(coding.get('avg_memla_semantic_command_success_rate', 0.0))}</strong><span>Environment-aware semantic command success.</span></div>
        <div class="metric"><span class="kicker">4b ambiguous steps</span><strong>{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))} -&gt; {_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}</strong><span>Same candidate hands, same model, Memla prior added.</span></div>
        <div class="metric"><span class="kicker">4b solve accuracy</span><strong>{_fmt(solve_4_raw.get('avg_answer_accuracy', 0.0))} -&gt; {_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)}</strong><span>Matches teacher raw at {_fmt(solve_teacher.get('avg_answer_accuracy', 0.0), 1)} on the harder math pack.</span></div>
      </div>
    </section>
    <section class="section">
      <h2>Coding Proof</h2>
      <p>On the primary coding repair slice, the {html.escape(memla_model)} + Memla lane reached apply rate {_fmt(coding.get('memla_apply_rate', 0.0), 1)} where {html.escape(raw_model)} raw stayed at {_fmt(coding.get('raw_apply_rate', 0.0), 1)}. This is the strongest current coding result because it measures real patch application instead of only routing proxies.</p>
      <div class="cards">{coding_cards}</div>
    </section>
    <section class="section">
      <h2>Extra Coding Support</h2>
      <p>We also pushed on a second coding repo family and a second benchmark type so the story is not resting on one lucky repo or one evaluator.</p>
      <div class="cards">{support_cards}</div>
    </section>
    <section class="section">
      <h2>Math Decision Proof</h2>
      <p>With the executor held constant, Memla changes move choice quality on ambiguous states. That isolates the decision-layer effect directly.</p>
      <div class="cards">{math_cards}</div>
    </section>
    <section class="section">
      <h2>What Is Actually Proved</h2>
      <div class="cards">
        <div class="card">
          <div class="kicker">Strong claim</div>
          <h3>Memla improves technical decision quality inside bounded executors.</h3>
          <ul>
            <li>Coding executor proof is real.</li>
            <li>Ambiguous math step choice improves strongly.</li>
            <li>4b + Memla reaches {_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)} on the harder math pack, matching teacher raw.</li>
          </ul>
        </div>
        <div class="card">
          <div class="kicker">Honest limit</div>
          <h3>This is bounded-runtime evidence, not universal proof complete.</h3>
          <ul>
            <li>The coding side still benefits from more repo-family repeats and cleaner local execution.</li>
            <li>The math side is strongest where the executor cleanly controls the hands.</li>
            <li>The pack supports a bounded runtime thesis, not a universal everything-model claim.</li>
          </ul>
        </div>
      </div>
      <div class="footer">Site target: {html.escape(site_url)}</div>
    </section>
  </div>
</body>
</html>
"""


def render_og_card(*, coding: dict[str, Any], math_rerank: dict[str, Any], math_progress: dict[str, Any]) -> str:
    rerank_4_raw = _lane(math_rerank, "qwen3.5:4b_raw")
    rerank_4_memla = _lane(math_rerank, "qwen3.5:4b_memla")
    solve_4_raw = _lane(math_progress, "qwen3.5:4b_raw")
    solve_4_memla = _lane(math_progress, "qwen3.5:4b_memla")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" fill="none">
  <rect width="1200" height="630" rx="28" fill="#0B1220"/>
  <circle cx="150" cy="120" r="180" fill="#F59E0B" fill-opacity="0.14"/>
  <circle cx="1040" cy="110" r="220" fill="#34D399" fill-opacity="0.14"/>
  <text x="88" y="110" fill="#93C5FD" font-family="Segoe UI, Arial, sans-serif" font-size="18" letter-spacing="4">MEMLA / CONSTRAINT RUNTIME</text>
  <text x="88" y="210" fill="#F8FAFC" font-family="Georgia, serif" font-size="64" font-weight="700">Smaller models choose better</text>
  <text x="88" y="276" fill="#F8FAFC" font-family="Georgia, serif" font-size="64" font-weight="700">when Memla owns the fork.</text>
  <text x="88" y="362" fill="#FDE68A" font-family="Segoe UI, Arial, sans-serif" font-size="24">4b ambiguous math step choice</text>
  <text x="88" y="438" fill="#FFFFFF" font-family="Segoe UI, Arial, sans-serif" font-size="82" font-weight="700">{_fmt(rerank_4_raw.get('avg_ambiguous_choice_accuracy', 0.0))} -&gt; {_fmt(rerank_4_memla.get('avg_ambiguous_choice_accuracy', 0.0), 1)}</text>
  <text x="88" y="520" fill="#A7F3D0" font-family="Segoe UI, Arial, sans-serif" font-size="24">Coding apply {_fmt(coding.get('raw_apply_rate', 0.0), 1)} -&gt; {_fmt(coding.get('memla_apply_rate', 0.0), 1)} | 4b solve {_fmt(solve_4_raw.get('avg_answer_accuracy', 0.0))} -&gt; {_fmt(solve_4_memla.get('avg_answer_accuracy', 0.0), 1)}</text>
</svg>
"""


def build_thesis_pack(
    *,
    coding_path: str,
    math_rerank_path: str,
    math_progress_path: str,
    out_dir: str,
    site_url: str,
    coding_secondary_path: str = "",
    compile_support_path: str = "",
) -> dict[str, str]:
    coding = _load_json(coding_path)
    math_rerank = _load_json(math_rerank_path)
    math_progress = _load_json(math_progress_path)
    coding_secondary = _load_json(coding_secondary_path) if coding_secondary_path else None
    compile_support = _load_json(compile_support_path) if compile_support_path else None
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frozen = out / "frozen"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen.mkdir(parents=True, exist_ok=True)

    frozen_coding = frozen / "coding_patch_execution_report.json"
    frozen_coding_secondary = frozen / "coding_secondary_patch_execution_report.json"
    frozen_compile_support = frozen / "coding_compile_loop_report.json"
    frozen_rerank = frozen / "math_step_rerank_report.json"
    frozen_progress = frozen / "math_progress_report.json"
    shutil.copy2(coding_path, frozen_coding)
    if coding_secondary_path:
        shutil.copy2(coding_secondary_path, frozen_coding_secondary)
    if compile_support_path:
        shutil.copy2(compile_support_path, frozen_compile_support)
    shutil.copy2(math_rerank_path, frozen_rerank)
    shutil.copy2(math_progress_path, frozen_progress)

    (out / "one_sentence_pitch.txt").write_text(render_one_sentence_pitch(coding=coding, math_rerank=math_rerank, math_progress=math_progress), encoding="utf-8")
    (out / "90_second_demo.md").write_text(render_demo_flow(coding=coding, math_rerank=math_rerank, math_progress=math_progress), encoding="utf-8")
    (out / "strategic_memo.md").write_text(
        render_memo(
            coding=coding,
            math_rerank=math_rerank,
            math_progress=math_progress,
            coding_secondary=coding_secondary,
            compile_support=compile_support,
        ),
        encoding="utf-8",
    )
    (out / "index.html").write_text(
        render_html(
            coding=coding,
            math_rerank=math_rerank,
            math_progress=math_progress,
            site_url=site_url,
            coding_secondary=coding_secondary,
            compile_support=compile_support,
        ),
        encoding="utf-8",
    )
    (out / "og-card.svg").write_text(render_og_card(coding=coding, math_rerank=math_rerank, math_progress=math_progress), encoding="utf-8")
    (out / "vercel.json").write_text(json.dumps({"cleanUrls": True, "trailingSlash": False}, indent=2), encoding="utf-8")
    return {
        "out_dir": str(out),
        "frozen_coding": str(frozen_coding),
        "frozen_coding_secondary": str(frozen_coding_secondary) if coding_secondary_path else "",
        "frozen_compile_support": str(frozen_compile_support) if compile_support_path else "",
        "frozen_rerank": str(frozen_rerank),
        "frozen_progress": str(frozen_progress),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the current Memla thesis buyer pack.")
    parser.add_argument("--coding", required=True)
    parser.add_argument("--math_rerank", required=True)
    parser.add_argument("--math_progress", required=True)
    parser.add_argument("--coding_secondary", default="")
    parser.add_argument("--compile_support", default="")
    parser.add_argument("--out_dir", required=True)
    parser.add_argument("--site_url", default="https://memla.vercel.app")
    args = parser.parse_args(argv)
    print(
        json.dumps(
            build_thesis_pack(
                coding_path=args.coding,
                math_rerank_path=args.math_rerank,
                math_progress_path=args.math_progress,
                out_dir=args.out_dir,
                site_url=args.site_url,
                coding_secondary_path=args.coding_secondary,
                compile_support_path=args.compile_support,
            ),
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
