from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _maybe_json(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    return _load_json(path)


def _fmt(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _slug_to_title(slug: str) -> str:
    return slug.replace("_", " ").replace("-", " ").strip()


def _infer_public_support_label(
    public_frontier: dict[str, Any] | None,
    public_seed: dict[str, Any] | None = None,
) -> str:
    if not public_frontier:
        return "Public seeded support"

    repo_root = str(public_frontier.get("repo_root", "")).strip()
    if repo_root:
        return _slug_to_title(Path(repo_root).name)

    cases_path = str(public_frontier.get("cases_path", "")).strip()
    if cases_path:
        try:
            pack_dir = Path(cases_path).resolve().parent.name
        except OSError:
            pack_dir = Path(cases_path).parent.name
        if pack_dir:
            trimmed = pack_dir
            for prefix in ("public_repo_", "public_", "second_repo_"):
                if trimmed.startswith(prefix):
                    trimmed = trimmed[len(prefix) :]
                    break
            return _slug_to_title(trimmed)

    if public_seed:
        return "Public seeded support"
    return "Public support"


def _curriculum_completed_rows(curriculum_batch: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not curriculum_batch:
        return []
    return [row for row in (curriculum_batch.get("results") or []) if row.get("status") == "completed"]


def _render_curriculum_highlights(curriculum_batch: dict[str, Any] | None) -> str:
    rows = _curriculum_completed_rows(curriculum_batch)
    if not rows:
        return ""
    best_command = sorted(
        rows,
        key=lambda row: float(row.get("avg_memla_combined_command_recall", 0.0)) - float(row.get("avg_raw_command_recall", 0.0)),
        reverse=True,
    )[:3]
    snippets: list[str] = []
    for row in best_command:
        raw = _fmt(row.get("avg_raw_command_recall", 0.0))
        memla = _fmt(row.get("avg_memla_combined_command_recall", 0.0))
        snippets.append(f"{row.get('id', 'repo')}: `{raw}` -> `{memla}`")
    return ", ".join(snippets)


def render_diligence_summary(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_seed: dict[str, Any] | None = None,
    public_frontier: dict[str, Any] | None = None,
    curriculum_batch: dict[str, Any] | None = None,
) -> str:
    public_label = _infer_public_support_label(public_frontier, public_seed)
    summary = [
        "# Memla Diligence Summary",
        "",
        "Memla is a coding-intelligence layer that sits in front of a model, captures accepted work, and reuses the role / constraint / transmutation structure behind that work on future coding tasks.",
        "",
        "## Current Headline",
        "",
        f"- Home repo holdout: `{_fmt(showcase.get('final_report', {}).get('avg_file_recall', 0.0))}` file recall / `{_fmt(showcase.get('final_report', {}).get('avg_command_recall', 0.0))}` command recall",
        f"- Second-repo transfer: `{_fmt(transfer.get('avg_baseline_file_recall', 0.0))}` -> `{_fmt(transfer.get('avg_memla_file_recall', 0.0))}` file recall",
        f"- Second-repo same-model head-to-head: `{_fmt(frontier.get('avg_raw_file_recall', 0.0))}` -> `{_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}` file recall and `{_fmt(frontier.get('avg_raw_command_recall', 0.0))}` -> `{_fmt(frontier.get('avg_memla_combined_command_recall', 0.0))}` command recall",
    ]
    if public_frontier:
        line = (
            f"- Public seeded support (`{public_label}`, local `{public_frontier.get('teacher_model', 'qwen3.5:9b')}`): "
            f"`{_fmt(public_frontier.get('avg_raw_file_recall', 0.0))}` -> "
            f"`{_fmt(public_frontier.get('avg_memla_combined_file_recall', 0.0))}` file recall and "
            f"`{_fmt(public_frontier.get('avg_raw_command_recall', 0.0))}` -> "
            f"`{_fmt(public_frontier.get('avg_memla_combined_command_recall', 0.0))}` command recall"
        )
        if public_seed:
            line += f"; seed bootstrap accepted `{public_seed.get('accepted', 0)}/{public_seed.get('cases', 0)}` cases"
        summary.append(line)
    if curriculum_batch:
        completed = _curriculum_completed_rows(curriculum_batch)
        summary.append(
            f"- Multi-family curriculum rerun: `{len(completed)}/{curriculum_batch.get('repos_attempted', 0)}` repos reached holdout; combined with the earlier web-app support row, Memla now has seeded proof across web app, Python backend API, auth/security, and CLI/tooling"
        )
    summary.extend(
        [
            "",
            "## Positioning",
            "",
            "Use the second-repo same-model result as the headline proof. Use the public seeded support rows and the multi-family curriculum rerun as diligence evidence that the bootstrap path works outside the internal repo cluster and across multiple repo families.",
            "",
        ]
    )
    return "\n".join(summary)


def render_diligence_faq(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_seed: dict[str, Any] | None = None,
    public_frontier: dict[str, Any] | None = None,
    curriculum_batch: dict[str, Any] | None = None,
) -> str:
    public_label = _infer_public_support_label(public_frontier, public_seed)
    lines = [
        "# Memla Diligence FAQ",
        "",
        "## What does Memla store?",
        "",
        "Memla stores accepted and rejected coding traces plus derived structure: likely files, likely commands, likely tests, file-role hints, constraint tags, and transmutations. In the current prototype it can also attach workspace evidence such as touched files and diff snapshots when feedback is recorded.",
        "",
        "## What makes it different from naive RAG?",
        "",
        "Naive RAG retrieves similar text. Memla stores why a fix worked: the role a file played, the constraint that was being resolved, the transmutation that traded one constraint for another, and the verification ritual that closed the loop. That lets it shape the next coding task instead of only adding snippets to context.",
        "",
        "## What is the strongest supported claim today?",
        "",
        "Memla can materially improve coding-task routing and verification for the same model by reusing accepted coding structure, and that improvement can transfer across repos once there is enough foothold.",
        "",
        "## What is not yet supported?",
        "",
        "Universal coding superiority is not supported. Cold-start dominance on arbitrary repos is not supported. The public-repo proof is supportive, not yet the main headline.",
        "",
        "## Does Memla modify the evaluated repo?",
        "",
        "No. The git-history eval packs are generated read-only from commit history and diffs. The target repos used in these evaluations were not edited by Memla during benchmarking.",
        "",
        "## What proof exists right now?",
        "",
        f"- Home repo holdout: `{_fmt(showcase.get('final_report', {}).get('avg_file_recall', 0.0))}` / `{_fmt(showcase.get('final_report', {}).get('avg_command_recall', 0.0))}`",
        f"- Second-repo transfer eval: `{_fmt(transfer.get('avg_baseline_file_recall', 0.0))}` -> `{_fmt(transfer.get('avg_memla_file_recall', 0.0))}`",
        f"- Second-repo same-model head-to-head: `{_fmt(frontier.get('avg_raw_file_recall', 0.0))}` -> `{_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}`",
    ]
    if public_frontier:
        extra = (
            f"- Public seeded support (`{public_label}`): `{_fmt(public_frontier.get('avg_raw_file_recall', 0.0))}` -> "
            f"`{_fmt(public_frontier.get('avg_memla_combined_file_recall', 0.0))}` file recall and "
            f"`{_fmt(public_frontier.get('avg_raw_command_recall', 0.0))}` -> "
            f"`{_fmt(public_frontier.get('avg_memla_combined_command_recall', 0.0))}` command recall"
        )
        if public_seed:
            extra += f"; seed accept rate `{_fmt(public_seed.get('accept_rate', 0.0))}`"
        lines.append(extra)
    if curriculum_batch:
        completed = _curriculum_completed_rows(curriculum_batch)
        lines.append(
            f"- Multi-family curriculum rerun: `{len(completed)}/{curriculum_batch.get('repos_attempted', 0)}` repos reached holdout, with best command lifts including {_render_curriculum_highlights(curriculum_batch)}"
        )
    lines.extend(
        [
            "",
            "## Why is the public proof weaker?",
            "",
            "The public backend tasks come from git history, are broader, and are scored against the full changed-file set. That makes the overlap metric much harsher than the focused second-repo proof, but it is still valuable because it shows the bootstrap mechanism works outside the internal repo cluster.",
            "",
            "## Best next diligence step",
            "",
            "Rerun the exact public seeded protocol on a stronger frontier model once credits are back, then repeat the same workflow on one outside-user repo.",
            "",
        ]
    )
    return "\n".join(lines)


def render_proof_table(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_seed: dict[str, Any] | None = None,
    public_frontier: dict[str, Any] | None = None,
    curriculum_batch: dict[str, Any] | None = None,
) -> str:
    public_label = _infer_public_support_label(public_frontier, public_seed)
    rows = [
        "# Memla Proof Table",
        "",
        "| Proof Layer | Repo Type | Setup | Model | File Recall | Command Recall | Notes |",
        "| --- | --- | --- | --- | --- | --- | --- |",
        (
            "| Home repo holdout | Internal | Seeded holdout | Mixed internal pipeline | "
            f"{_fmt(showcase.get('final_report', {}).get('avg_file_recall', 0.0))} | "
            f"{_fmt(showcase.get('final_report', {}).get('avg_command_recall', 0.0))} | "
            "Best repo-local compounding proof |"
        ),
        (
            "| Second-repo transfer eval | Local/private | Empty-memory vs Memla planner | Local planner stack | "
            f"{_fmt(transfer.get('avg_baseline_file_recall', 0.0))} -> {_fmt(transfer.get('avg_memla_file_recall', 0.0))} | "
            f"{_fmt(transfer.get('avg_baseline_command_recall', 0.0))} -> {_fmt(transfer.get('avg_memla_command_recall', 0.0))} | "
            "Shows transfer without changing the teacher model |"
        ),
        (
            "| Second-repo same-model head-to-head | Local/private | Same-model comparison | Frontier model | "
            f"{_fmt(frontier.get('avg_raw_file_recall', 0.0))} -> {_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))} | "
            f"{_fmt(frontier.get('avg_raw_command_recall', 0.0))} -> {_fmt(frontier.get('avg_memla_combined_command_recall', 0.0))} | "
            "Headline proof for buyer outreach |"
        ),
    ]
    if public_frontier:
        note = f"Supporting public proof ({public_label})"
        if public_seed:
            note += f"; accepted `{public_seed.get('accepted', 0)}/{public_seed.get('cases', 0)}` seed cases"
        rows.append(
            (
                "| Public seeded head-to-head | Public OSS | 8 seed + 12 unseen | Local qwen3.5:9b | "
                f"{_fmt(public_frontier.get('avg_raw_file_recall', 0.0))} -> {_fmt(public_frontier.get('avg_memla_combined_file_recall', 0.0))} | "
                f"{_fmt(public_frontier.get('avg_raw_command_recall', 0.0))} -> {_fmt(public_frontier.get('avg_memla_combined_command_recall', 0.0))} | "
                f"{note} |"
            )
        )
    if curriculum_batch:
        completed = _curriculum_completed_rows(curriculum_batch)
        rows.append(
            (
                "| Public curriculum rerun | Public OSS multi-family | Focused family-aware rerun | Local qwen3.5:9b | "
                f"`{len(completed)}/{curriculum_batch.get('repos_attempted', 0)}` repos reached holdout | "
                f"{_render_curriculum_highlights(curriculum_batch) or 'mixed'} | "
                "Shows seeded transfer across backend API, auth/security, and CLI/tooling families |"
            )
        )
    rows.extend(["", "Use the second-repo same-model row as the headline proof and the public seeded row as supporting diligence material."])
    return "\n".join(rows)


def render_technical_diligence(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_seed: dict[str, Any] | None = None,
    public_frontier: dict[str, Any] | None = None,
    curriculum_batch: dict[str, Any] | None = None,
) -> str:
    public_label = _infer_public_support_label(public_frontier, public_seed)
    lines = [
        "# Memla Technical Diligence",
        "",
        "## Core Loop",
        "",
        "1. A user asks a coding question through Memla.",
        "2. Memla retrieves accepted traces, role matches, and transmutations relevant to the task.",
        "3. Memla predicts likely files, commands, tests, and patch steps before the teacher answers.",
        "4. The teacher answers with that repo-shaped context in front of it.",
        "5. Accepted outcomes feed back into the trace log and become future priors.",
        "",
        "## Why this is more than RAG",
        "",
        "RAG mostly returns similar text. Memla stores reusable structure that survives repo changes:",
        "- roles: what a file does in the workflow",
        "- constraints: what is broken or blocked",
        "- transmutations: what constraint trade solved the task",
        "- verification rituals: which commands and tests close the loop",
        "",
        "That structure is what allowed the same-model comparison on the second repo to move from "
        f"`{_fmt(frontier.get('avg_raw_file_recall', 0.0))}` to `{_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}` file recall.",
        "",
        "## What the current proof supports",
        "",
        "- Strong repo-local compounding",
        "- Real cross-repo transfer once there is enough structural foothold",
        "- Same-model improvement without modifying the target repo",
        "",
        "## What the current proof does not support",
        "",
        "- Universal coding superiority",
        "- Reliable cold-start dominance on arbitrary repos",
        "- Production-complete governance and retention guarantees",
    ]
    if public_frontier:
        lines.extend(
            [
                "",
                "## Public Seeded Support",
                "",
                f"The public seeded run uses `{public_label}` and a git-history holdout. After the seeding-policy fix, the bootstrap accepted enough traces to create a real compounding test instead of another cold start.",
                "",
            ]
        )
        if public_seed:
            lines.append(f"- Seed accept count: `{public_seed.get('accepted', 0)}/{public_seed.get('cases', 0)}`")
        lines.extend(
            [
                f"- Raw file recall: `{_fmt(public_frontier.get('avg_raw_file_recall', 0.0))}`",
                f"- Memla combined file recall: `{_fmt(public_frontier.get('avg_memla_combined_file_recall', 0.0))}`",
                f"- Raw command recall: `{_fmt(public_frontier.get('avg_raw_command_recall', 0.0))}`",
                f"- Memla combined command recall: `{_fmt(public_frontier.get('avg_memla_combined_command_recall', 0.0))}`",
                "",
                "This is supporting evidence because the tasks are noisier and the overlap metric is harsher, but it still matters because it shows the bootstrap pipeline is not limited to the internal repo cluster.",
            ]
        )
    if curriculum_batch:
        completed = _curriculum_completed_rows(curriculum_batch)
        lines.extend(
            [
                "",
                "## Multi-Family Curriculum Rerun",
                "",
                f"A focused family-aware rerun pushed `{len(completed)}/{curriculum_batch.get('repos_attempted', 0)}` public repos into holdout. Combined with the existing web-app support row, this gives Memla seeded public support across web app, Python backend API, auth/security, and CLI/tooling families.",
                "",
                f"Best command lifts in that rerun: {_render_curriculum_highlights(curriculum_batch)}.",
            ]
        )
    lines.extend(
        [
            "",
            "## Most defensible next step",
            "",
            "Run the exact same public seeded protocol on a stronger frontier model once credits return, then repeat the workflow on one outside-user repo.",
            "",
        ]
    )
    return "\n".join(lines)


def render_diligence_packet_html(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_seed: dict[str, Any] | None = None,
    public_frontier: dict[str, Any] | None = None,
    curriculum_batch: dict[str, Any] | None = None,
) -> str:
    public_label = _infer_public_support_label(public_frontier, public_seed)
    payload = json.dumps(
        {
            "showcase": showcase,
            "transfer": transfer,
            "frontier": frontier,
            "public_seed": public_seed,
            "public_frontier": public_frontier,
            "curriculum_batch": curriculum_batch,
            "public_label": public_label,
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memla Diligence Packet</title>
  <style>
    :root {{
      --bg: #f5f1ea;
      --ink: #1f1b17;
      --muted: #6c635a;
      --line: #dacdbe;
      --card: rgba(255,255,255,.75);
      --accent: #176f5e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Avenir Next", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(23,111,94,.10), transparent 28%),
        radial-gradient(circle at top right, rgba(18,76,124,.08), transparent 30%),
        linear-gradient(180deg, #fcfaf7, var(--bg));
    }}
    .wrap {{ width: min(1120px, calc(100vw - 32px)); margin: 0 auto; padding: 28px 0 56px; }}
    .hero, .section {{
      border: 1px solid var(--line);
      border-radius: 24px;
      background: var(--card);
      backdrop-filter: blur(10px);
      box-shadow: 0 10px 36px rgba(46,36,28,.08);
    }}
    .hero {{ padding: 28px; display: grid; gap: 14px; }}
    .section {{ margin-top: 18px; padding: 22px; }}
    .eyebrow {{ color: var(--accent); font-size: 12px; letter-spacing: .18em; text-transform: uppercase; }}
    h1 {{ margin: 0; font-size: clamp(32px, 6vw, 56px); line-height: 1.03; max-width: 920px; }}
    .sub {{ color: var(--muted); font-size: 18px; line-height: 1.55; max-width: 860px; }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
      gap: 14px;
      margin-top: 10px;
    }}
    .metric {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,.7);
    }}
    .metric .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; }}
    .metric .value {{ font-size: 28px; font-weight: 700; margin-top: 8px; }}
    .metric .note {{ color: var(--muted); font-size: 14px; line-height: 1.4; margin-top: 8px; }}
    ul {{ color: var(--muted); line-height: 1.5; }}
    .proof-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 14px;
    }}
    .proof {{
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 16px;
      background: rgba(255,255,255,.7);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Memla Diligence Packet</div>
      <h1>Async proof for transferable coding intelligence.</h1>
      <div class="sub">Use the second-repo same-model proof as the headline. Use the public seeded backend run as support that the bootstrap path works outside the internal repo cluster.</div>
      <div class="metrics" id="metrics"></div>
    </section>
    <section class="section">
      <h2>Claim Boundary</h2>
      <ul>
        <li>Supported: Memla improves coding-task routing and verification for the same model by reusing accepted coding structure.</li>
        <li>Supported: that structure can transfer across repos once there is enough foothold.</li>
        <li>Not supported: universal coding superiority or instant cold-start dominance on arbitrary repos.</li>
      </ul>
    </section>
    <section class="section">
      <h2>Proof Stack</h2>
      <div class="proof-grid" id="proof-grid"></div>
    </section>
  </div>
  <script>
    const PACK = {payload};
    function metric(label, value, note) {{
      return `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value}}</div><div class="note">${{note}}</div></div>`;
    }}
    function proof(title, body) {{
      return `<div class="proof"><strong>${{title}}</strong><div style="color:#6c635a;margin-top:8px;line-height:1.5">${{body}}</div></div>`;
    }}
    const metrics = [
      metric("Home Repo", `${{PACK.showcase.final_report.avg_file_recall.toFixed(1)}} / ${{PACK.showcase.final_report.avg_command_recall.toFixed(1)}}`, "Seeded internal coding holdout"),
      metric("Transfer Eval", `${{PACK.transfer.avg_baseline_file_recall.toFixed(4)}} -> ${{PACK.transfer.avg_memla_file_recall.toFixed(4)}}`, "Planner-only second-repo transfer"),
      metric("Same-Model H2H", `${{PACK.frontier.avg_raw_file_recall.toFixed(4)}} -> ${{PACK.frontier.avg_memla_combined_file_recall.toFixed(4)}}`, "Headline proof"),
    ];
    if (PACK.public_frontier) {{
      metrics.push(metric("Public Seeded", `${{PACK.public_frontier.avg_raw_file_recall.toFixed(4)}} -> ${{PACK.public_frontier.avg_memla_combined_file_recall.toFixed(4)}}`, PACK.public_label));
    }}
    if (PACK.curriculum_batch) {{
      const completed = (PACK.curriculum_batch.results || []).filter(row => row.status === "completed").length;
      metrics.push(metric("Curriculum Rerun", `${{completed}}/${{PACK.curriculum_batch.repos_attempted}}`, "Public multi-family holdouts"));
    }}
    document.getElementById("metrics").innerHTML = metrics.join("");

    const proofs = [
      proof("Home repo holdout", `Repo-local compounding: ${{PACK.showcase.final_report.avg_file_recall.toFixed(1)}} / ${{PACK.showcase.final_report.avg_command_recall.toFixed(1)}}.`),
      proof("Second-repo transfer", `Empty-memory vs Memla planner: ${{PACK.transfer.avg_baseline_file_recall.toFixed(4)}} -> ${{PACK.transfer.avg_memla_file_recall.toFixed(4)}} file recall.`),
      proof("Second-repo same-model head-to-head", `Raw model vs Memla in front: ${{PACK.frontier.avg_raw_file_recall.toFixed(4)}} -> ${{PACK.frontier.avg_memla_combined_file_recall.toFixed(4)}} file recall and ${{PACK.frontier.avg_raw_command_recall.toFixed(1)}} -> ${{PACK.frontier.avg_memla_combined_command_recall.toFixed(1)}} command recall.`),
    ];
    if (PACK.public_frontier) {{
      const seedNote = PACK.public_seed ? ` Bootstrap accepted ${{PACK.public_seed.accepted}}/${{PACK.public_seed.cases}} seed cases first.` : "";
      proofs.push(proof("Public seeded support", `${{PACK.public_label}} local run: ${{PACK.public_frontier.avg_raw_file_recall.toFixed(4)}} -> ${{PACK.public_frontier.avg_memla_combined_file_recall.toFixed(4)}} file recall and ${{PACK.public_frontier.avg_raw_command_recall.toFixed(1)}} -> ${{PACK.public_frontier.avg_memla_combined_command_recall.toFixed(4)}} command recall.${{seedNote}}`));
    }}
    if (PACK.curriculum_batch) {{
      const completed = (PACK.curriculum_batch.results || []).filter(row => row.status === "completed");
      proofs.push(proof("Multi-family curriculum rerun", `${{completed.length}}/${{PACK.curriculum_batch.repos_attempted}} public repos reached holdout after family-aware gating. This adds backend API, auth/security, and CLI/tooling support on top of the existing web-app public row.`));
    }}
    document.getElementById("proof-grid").innerHTML = proofs.join("");
  </script>
</body>
</html>
"""


def build_diligence_packet(
    *,
    showcase_path: str,
    transfer_path: str,
    frontier_path: str,
    out_dir: str,
    public_seed_path: str | None = None,
    public_frontier_path: str | None = None,
    curriculum_batch_path: str | None = None,
) -> dict[str, str]:
    showcase = _load_json(showcase_path)
    transfer = _load_json(transfer_path)
    frontier = _load_json(frontier_path)
    public_seed = _maybe_json(public_seed_path)
    public_frontier = _maybe_json(public_frontier_path)
    curriculum_batch = _maybe_json(curriculum_batch_path)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frozen = out / "frozen"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen.mkdir(parents=True, exist_ok=True)

    frozen_showcase = frozen / "showcase_demo_summary.json"
    frozen_transfer = frozen / "transfer_report.json"
    frozen_frontier = frozen / "frontier_head_to_head_report.json"
    shutil.copy2(showcase_path, frozen_showcase)
    shutil.copy2(transfer_path, frozen_transfer)
    shutil.copy2(frontier_path, frozen_frontier)

    frozen_public_seed = ""
    frozen_public_frontier = ""
    frozen_curriculum_batch = ""
    if public_seed_path:
        frozen_public_seed = str(frozen / "public_seed_report.json")
        shutil.copy2(public_seed_path, frozen_public_seed)
    if public_frontier_path:
        frozen_public_frontier = str(frozen / "public_frontier_report.json")
        shutil.copy2(public_frontier_path, frozen_public_frontier)
    if curriculum_batch_path:
        frozen_curriculum_batch = str(frozen / "public_curriculum_batch.json")
        shutil.copy2(curriculum_batch_path, frozen_curriculum_batch)

    summary_path = out / "diligence_summary.md"
    faq_path = out / "diligence_faq.md"
    proof_table_path = out / "proof_table.md"
    technical_path = out / "technical_diligence.md"
    html_path = out / "index.html"

    summary_path.write_text(
        render_diligence_summary(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_seed=public_seed,
            public_frontier=public_frontier,
            curriculum_batch=curriculum_batch,
        ),
        encoding="utf-8",
    )
    faq_path.write_text(
        render_diligence_faq(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_seed=public_seed,
            public_frontier=public_frontier,
            curriculum_batch=curriculum_batch,
        ),
        encoding="utf-8",
    )
    proof_table_path.write_text(
        render_proof_table(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_seed=public_seed,
            public_frontier=public_frontier,
            curriculum_batch=curriculum_batch,
        ),
        encoding="utf-8",
    )
    technical_path.write_text(
        render_technical_diligence(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_seed=public_seed,
            public_frontier=public_frontier,
            curriculum_batch=curriculum_batch,
        ),
        encoding="utf-8",
    )
    html_path.write_text(
        render_diligence_packet_html(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_seed=public_seed,
            public_frontier=public_frontier,
            curriculum_batch=curriculum_batch,
        ),
        encoding="utf-8",
    )

    return {
        "summary": str(summary_path),
        "faq": str(faq_path),
        "proof_table": str(proof_table_path),
        "technical": str(technical_path),
        "html": str(html_path),
        "frozen_showcase": str(frozen_showcase),
        "frozen_transfer": str(frozen_transfer),
        "frozen_frontier": str(frozen_frontier),
        "frozen_public_seed": frozen_public_seed,
        "frozen_public_frontier": frozen_public_frontier,
        "frozen_curriculum_batch": frozen_curriculum_batch,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build an async diligence packet from Memla proof artifacts.")
    parser.add_argument("--showcase", required=True)
    parser.add_argument("--transfer", required=True)
    parser.add_argument("--frontier", required=True)
    parser.add_argument("--public_seed")
    parser.add_argument("--public_frontier")
    parser.add_argument("--curriculum_batch")
    parser.add_argument("--out_dir", default="./distill/diligence_packet")
    args = parser.parse_args(argv)

    outputs = build_diligence_packet(
        showcase_path=args.showcase,
        transfer_path=args.transfer,
        frontier_path=args.frontier,
        public_seed_path=args.public_seed,
        public_frontier_path=args.public_frontier,
        curriculum_batch_path=args.curriculum_batch,
        out_dir=args.out_dir,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
