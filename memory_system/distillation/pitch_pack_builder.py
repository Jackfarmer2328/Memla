from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_one_sentence_pitch(*, showcase: dict[str, Any], head_to_head: dict[str, Any], unseen: dict[str, Any]) -> str:
    showcase_file = showcase.get("final_report", {}).get("avg_file_recall", showcase.get("avg_file_recall", 0.0))
    showcase_cmd = showcase.get("final_report", {}).get("avg_command_recall", showcase.get("avg_command_recall", 0.0))
    h2h_raw = head_to_head.get("avg_raw_file_recall", 0.0)
    h2h_memla = head_to_head.get("avg_memla_combined_file_recall", 0.0)
    unseen_file = unseen.get("avg_memla_combined_file_recall", 0.0)
    unseen_cmd = unseen.get("avg_memla_combined_command_recall", 0.0)
    return (
        "Memla turns frontier-model coding usage into owned repo-specific intelligence, "
        f"with current internal coding recall at {showcase_file:.1f}/{showcase_cmd:.1f}, "
        f"a live raw-teacher versus Memla swing from {h2h_raw:.1f} to {h2h_memla:.1f} on seen buyer-demo tasks, "
        f"and {unseen_file:.1f}/{unseen_cmd:.1f} on a second unseen validation set."
    )


def render_demo_flow(*, head_to_head: dict[str, Any], unseen: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# 90-Second Demo Flow",
            "",
            "## Positioning",
            "",
            "Memla sits in front of the teacher model, reuses accepted repo-specific wins, and predicts files, commands, tests, and patch shape before the teacher answers.",
            "",
            "## Flow",
            "",
            "1. Show the raw teacher baseline from the head-to-head report.",
            f"   Raw teacher recall on the buyer set: file `{head_to_head.get('avg_raw_file_recall', 0.0)}`, command `{head_to_head.get('avg_raw_command_recall', 0.0)}`.",
            "2. Show the same prompt with Memla in front.",
            f"   Memla combined recall on the buyer set: file `{head_to_head.get('avg_memla_combined_file_recall', 0.0)}`, command `{head_to_head.get('avg_memla_combined_command_recall', 0.0)}`.",
            "3. Open one case and point at the prior trace ids, predicted files, predicted test command, and answer excerpt.",
            "4. Show that the behavior also generalizes to the unseen validation set.",
            f"   Memla combined recall on unseen set: file `{unseen.get('avg_memla_combined_file_recall', 0.0)}`, command `{unseen.get('avg_memla_combined_command_recall', 0.0)}`.",
            "5. Close with the product thesis: every accepted teacher interaction becomes owned repo intelligence instead of disappearing into chat history.",
            "",
            "## Closing Line",
            "",
            "\"Raw frontier models are strong but stateless. Memla turns that spend into compounding coding intelligence.\"",
            "",
        ]
    )


def render_pitch_html(*, showcase: dict[str, Any], head_to_head: dict[str, Any], unseen: dict[str, Any]) -> str:
    payload = json.dumps(
        {
            "showcase": showcase,
            "head_to_head": head_to_head,
            "unseen": unseen,
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memla Coding Distillation Pitch</title>
  <style>
    :root {{
      --bg: #0b1117;
      --panel: #101922;
      --panel-2: #142231;
      --ink: #eef5ff;
      --muted: #9db0c7;
      --accent: #57d8a6;
      --accent-2: #6fb6ff;
      --line: #23364b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "IBM Plex Sans", sans-serif;
      background:
        radial-gradient(circle at top left, rgba(87,216,166,.12), transparent 28%),
        radial-gradient(circle at top right, rgba(111,182,255,.12), transparent 30%),
        linear-gradient(180deg, #081018, var(--bg));
      color: var(--ink);
    }}
    .wrap {{
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 32px 0 56px;
    }}
    .hero {{
      display: grid;
      gap: 16px;
      padding: 28px;
      border: 1px solid var(--line);
      border-radius: 24px;
      background: linear-gradient(180deg, rgba(16,25,34,.92), rgba(11,17,23,.95));
      box-shadow: 0 20px 70px rgba(0,0,0,.35);
    }}
    .eyebrow {{
      color: var(--accent);
      font-size: 12px;
      letter-spacing: .18em;
      text-transform: uppercase;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(32px, 6vw, 56px);
      line-height: 1.02;
    }}
    .sub {{
      color: var(--muted);
      font-size: 18px;
      max-width: 860px;
      line-height: 1.5;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 16px;
      margin-top: 20px;
    }}
    .card {{
      border: 1px solid var(--line);
      border-radius: 20px;
      padding: 18px;
      background: linear-gradient(180deg, rgba(20,34,49,.9), rgba(16,25,34,.88));
    }}
    .metric {{
      font-size: 32px;
      font-weight: 700;
      margin-top: 8px;
    }}
    .label {{
      color: var(--muted);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: .08em;
    }}
    .section {{
      margin-top: 24px;
      display: grid;
      gap: 16px;
    }}
    .section h2 {{
      margin: 0;
      font-size: 24px;
    }}
    .case-list {{
      display: grid;
      gap: 14px;
    }}
    .case {{
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(16,25,34,.9);
      padding: 18px;
    }}
    .row {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 12px;
    }}
    .mini {{
      padding: 14px;
      border-radius: 14px;
      background: rgba(8,16,24,.75);
      border: 1px solid rgba(35,54,75,.8);
    }}
    .mini strong {{
      display: block;
      margin-bottom: 8px;
    }}
    .pill {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: rgba(87,216,166,.12);
      color: var(--accent);
      margin-right: 8px;
      margin-top: 8px;
      font-size: 13px;
    }}
    code {{ color: var(--accent-2); }}
    ul {{ margin: 8px 0 0; padding-left: 18px; color: var(--muted); }}
    @media (max-width: 900px) {{
      .grid, .row {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Memla Pitch Pack</div>
      <h1>Memla turns frontier-model coding usage into owned intelligence.</h1>
      <div class="sub">A repo-specific coding distillation layer that predicts files, commands, tests, and patch shape before the teacher answers, then compounds those wins into future coding sessions.</div>
      <div class="grid" id="top-metrics"></div>
    </section>
    <section class="section">
      <h2>Seen Buyer Demo</h2>
      <div class="case-list" id="seen-cases"></div>
    </section>
    <section class="section">
      <h2>Unseen Validation</h2>
      <div class="case-list" id="unseen-cases"></div>
    </section>
  </div>
  <script>
    const PACK = {payload};

    function metricCard(label, value, note) {{
      return `<div class="card"><div class="label">${{label}}</div><div class="metric">${{value}}</div><div class="sub" style="font-size:14px">${{note}}</div></div>`;
    }}

    function caseCard(row, mode) {{
      const prior = (row.prior_trace_ids || []).join(", ");
      const patch = (row.memla_patch_steps || row.patch_steps || []).slice(0, 4).map(step => `<li>${{step}}</li>`).join("");
      return `
        <article class="case">
          <div class="label">${{mode}}</div>
          <h3 style="margin:8px 0 0">${{row.prompt}}</h3>
          <div class="row">
            <div class="mini">
              <strong>Raw Teacher</strong>
              <div class="pill">Files: ${{row.raw_file_recall ?? row.file_recall}}</div>
              <div class="pill">Commands: ${{row.raw_command_recall ?? row.command_recall}}</div>
              ${{row.raw_answer ? `<p style="color:var(--muted)">${{row.raw_answer.slice(0, 260)}}...</p>` : `<p style="color:var(--muted)">Planner-only validation case.</p>`}}
            </div>
            <div class="mini">
              <strong>Memla In Front</strong>
              <div class="pill">Files: ${{row.memla_combined_file_recall ?? row.file_recall}}</div>
              <div class="pill">Commands: ${{row.memla_combined_command_recall ?? row.command_recall}}</div>
              ${{prior ? `<div style="color:var(--muted); margin-top:8px">Prior traces: ${{prior}}</div>` : ""}}
              <div style="color:var(--muted); margin-top:8px">Predicted files: ${{(row.memla_plan_files || row.predicted_files || []).join(", ")}}</div>
              <div style="color:var(--muted); margin-top:6px">Predicted command: ${{(row.memla_combined_commands || row.predicted_commands || []).join(", ")}}</div>
            </div>
          </div>
          ${{patch ? `<ul>${{patch}}</ul>` : ""}}
        </article>
      `;
    }}

    const top = document.getElementById("top-metrics");
    top.innerHTML = [
      metricCard("Current Showcase", `${{PACK.showcase.final_report.avg_file_recall.toFixed(1)}} / ${{PACK.showcase.final_report.avg_command_recall.toFixed(1)}}`, "Repo-local coding holdout after seeding"),
      metricCard("Seen Head-to-Head", `${{PACK.head_to_head.avg_raw_file_recall.toFixed(1)}} -> ${{PACK.head_to_head.avg_memla_combined_file_recall.toFixed(1)}}`, "Raw teacher file recall to Memla-assisted file recall"),
      metricCard("Unseen Head-to-Head", `${{PACK.unseen.avg_raw_file_recall.toFixed(1)}} -> ${{PACK.unseen.avg_memla_combined_file_recall.toFixed(1)}}`, "Second unseen coding eval set"),
    ].join("");

    document.getElementById("seen-cases").innerHTML = (PACK.head_to_head.rows || []).map(row => caseCard(row, "Seen buyer demo")).join("");
    document.getElementById("unseen-cases").innerHTML = (PACK.unseen.rows || []).map(row => caseCard(row, "Unseen validation")).join("");
  </script>
</body>
</html>
"""


def build_pitch_pack(
    *,
    showcase_path: str,
    head_to_head_path: str,
    unseen_path: str,
    out_dir: str,
) -> dict[str, str]:
    showcase = _load_json(showcase_path)
    head_to_head = _load_json(head_to_head_path)
    unseen = _load_json(unseen_path)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frozen = out / "frozen"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen.mkdir(parents=True, exist_ok=True)

    frozen_showcase = frozen / "showcase_demo_summary.json"
    frozen_head = frozen / "seen_head_to_head_report.json"
    frozen_unseen = frozen / "unseen_head_to_head_report.json"
    shutil.copy2(showcase_path, frozen_showcase)
    shutil.copy2(head_to_head_path, frozen_head)
    shutil.copy2(unseen_path, frozen_unseen)

    pitch_path = out / "one_sentence_pitch.txt"
    demo_flow_path = out / "90_second_demo.md"
    html_path = out / "index.html"

    pitch_path.write_text(
        render_one_sentence_pitch(showcase=showcase, head_to_head=head_to_head, unseen=unseen),
        encoding="utf-8",
    )
    demo_flow_path.write_text(
        render_demo_flow(head_to_head=head_to_head, unseen=unseen),
        encoding="utf-8",
    )
    html_path.write_text(
        render_pitch_html(showcase=showcase, head_to_head=head_to_head, unseen=unseen),
        encoding="utf-8",
    )

    return {
        "pitch": str(pitch_path),
        "demo_flow": str(demo_flow_path),
        "html": str(html_path),
        "frozen_showcase": str(frozen_showcase),
        "frozen_head_to_head": str(frozen_head),
        "frozen_unseen": str(frozen_unseen),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a buyer-facing pitch pack from Memla demo artifacts.")
    parser.add_argument("--showcase", required=True)
    parser.add_argument("--head_to_head", required=True)
    parser.add_argument("--unseen", required=True)
    parser.add_argument("--out_dir", default="./distill/pitch_pack")
    args = parser.parse_args(argv)

    outputs = build_pitch_pack(
        showcase_path=args.showcase,
        head_to_head_path=args.head_to_head,
        unseen_path=args.unseen,
        out_dir=args.out_dir,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
