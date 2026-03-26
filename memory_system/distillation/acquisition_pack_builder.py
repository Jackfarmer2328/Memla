from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def _load_json(path: str) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _fmt(value: float) -> str:
    return f"{float(value):.4f}".rstrip("0").rstrip(".")


def _curriculum_summary(curriculum: dict[str, Any] | None) -> str:
    if not curriculum:
        return "No public curriculum loaded."
    return f"{curriculum.get('repos_with_holdouts', 0)}/{curriculum.get('repos_attempted', 0)} public repos reached holdout"


def render_acquisition_pitch(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_frontier: dict[str, Any] | None = None,
    curriculum: dict[str, Any] | None = None,
) -> str:
    text = (
        "Memla turns frontier-model coding usage into transferable intelligence: "
        f"it reaches {_fmt(showcase.get('final_report', {}).get('avg_file_recall', 0.0))}/"
        f"{_fmt(showcase.get('final_report', {}).get('avg_command_recall', 0.0))} on the home-repo coding holdout, "
        f"improves empty-memory second-repo planning from {_fmt(transfer.get('avg_baseline_file_recall', 0.0))} "
        f"to {_fmt(transfer.get('avg_memla_file_recall', 0.0))} file recall and from "
        f"{_fmt(transfer.get('avg_baseline_command_recall', 0.0))} to {_fmt(transfer.get('avg_memla_command_recall', 0.0))} "
        f"command recall, and shifts a Claude head-to-head from {_fmt(frontier.get('avg_raw_file_recall', 0.0))} "
        f"to {_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))} file recall on unseen second-repo tasks."
    )
    if public_frontier:
        text += (
            f" On a seeded public OSS repo, it moves file recall from {_fmt(public_frontier.get('avg_raw_file_recall', 0.0))} "
            f"to {_fmt(public_frontier.get('avg_memla_combined_file_recall', 0.0))}."
        )
    if curriculum:
        text += f" The public curriculum rerun reached holdout on {curriculum.get('repos_with_holdouts', 0)}/{curriculum.get('repos_attempted', 0)} repos."
    return text


def render_acquisition_demo_flow(*, transfer: dict[str, Any], frontier: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Memla Demo Flow",
            "",
            "## Thesis",
            "",
            "Memla does not just remember file names. It stores role, constraint, and transmutation structure from accepted coding work, then reuses that structure on future tasks and even on a different repo.",
            "",
            "## 90-Second Sequence",
            "",
            "1. Open the second-repo head-to-head result.",
            f"   Raw Claude file recall: `{_fmt(frontier.get('avg_raw_file_recall', 0.0))}`.",
            f"   Memla-assisted file recall: `{_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}`.",
            "2. Open one case where raw Claude guessed the wrong architecture and Memla routed it into the local repo shape.",
            "3. Point at the Memla plan: files, tests, roles, and transmutations.",
            "4. Open the free transfer report to show this is not just a prompting trick.",
            f"   Empty-memory file recall: `{_fmt(transfer.get('avg_baseline_file_recall', 0.0))}` -> Memla transfer file recall: `{_fmt(transfer.get('avg_memla_file_recall', 0.0))}`.",
            f"   Empty-memory command recall: `{_fmt(transfer.get('avg_baseline_command_recall', 0.0))}` -> Memla transfer command recall: `{_fmt(transfer.get('avg_memla_command_recall', 0.0))}`.",
            "5. Close with the core line: frontier models are strong but stateless; Memla turns their usage into owned, compounding coding intelligence.",
            "",
        ]
    )


def render_strategic_memo(*, showcase: dict[str, Any], transfer: dict[str, Any], frontier: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Memla Strategic Memo",
            "",
            "## What Memla Is",
            "",
            "Memla is a coding intelligence layer that sits in front of a frontier model, captures accepted coding work, and distills that work into reusable structure.",
            "",
            "The critical step is not just memory. Memla stores:",
            "- file-role structure",
            "- constraint tags",
            "- transmutations",
            "- verification rituals like the tests or commands that close the loop",
            "",
            "## Proof",
            "",
            f"- Home repo coding holdout: `{_fmt(showcase.get('final_report', {}).get('avg_file_recall', 0.0))}` / `{_fmt(showcase.get('final_report', {}).get('avg_command_recall', 0.0))}`",
            f"- Free second-repo transfer eval: `{_fmt(transfer.get('avg_baseline_file_recall', 0.0))}` -> `{_fmt(transfer.get('avg_memla_file_recall', 0.0))}`",
            f"- Paid Claude second-repo head-to-head: `{_fmt(frontier.get('avg_raw_file_recall', 0.0))}` -> `{_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}`",
            "",
        ]
    )


def render_buyer_targets() -> str:
    return "\n".join(
        [
            "# Target Buyers",
            "",
            "- LangChain",
            "- Mem0",
            "- Coding assistant / agent companies",
            "- Developer workflow platforms with IDE or CLI surface area",
            "- Enterprise AI tool builders who want org-specific coding memory",
            "",
        ]
    )


def render_outreach_email() -> str:
    return "\n".join(
        [
            "Subject: Memla turns coding-model usage into transferable intelligence",
            "",
            "We built a layer called Memla that sits in front of a frontier coding model. Memla turns accepted coding work into transferable intelligence.",
            "",
            "In our latest second-repo eval, raw Claude reached 0.1667 file recall on unseen tasks, while Memla in front of the same model reached 0.9167 combined file recall and 1.0 command recall.",
            "",
            "The mechanism is not just retrieval. Memla stores role, constraint, and transmutation structure from successful coding work, then maps that onto the next repo's local files and verification rituals.",
            "",
            "If this is relevant to your roadmap, I can send a 90-second demo and the underlying reports.",
            "",
            "Samat",
            "",
        ]
    )


def render_og_card(*, frontier: dict[str, Any], curriculum: dict[str, Any] | None = None) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="630" viewBox="0 0 1200 630" fill="none">
  <rect width="1200" height="630" rx="28" fill="#10211E"/>
  <circle cx="140" cy="120" r="180" fill="#0F766E" fill-opacity="0.18"/>
  <circle cx="1080" cy="110" r="220" fill="#C58C3A" fill-opacity="0.16"/>
  <rect x="54" y="54" width="1092" height="522" rx="24" fill="rgba(255,255,255,0.04)" stroke="rgba(255,255,255,0.18)"/>
  <text x="88" y="122" fill="#C9E9E3" font-family="Segoe UI, Arial, sans-serif" font-size="18" letter-spacing="4">MEMLA / TRANSFERABLE CODING INTELLIGENCE</text>
  <text x="88" y="212" fill="#FFF7EA" font-family="Georgia, serif" font-size="62" font-weight="700">Same model. New repo.</text>
  <text x="88" y="282" fill="#FFF7EA" font-family="Georgia, serif" font-size="62" font-weight="700">Much better routing.</text>
  <text x="88" y="370" fill="#F0D7B0" font-family="Segoe UI, Arial, sans-serif" font-size="24">Second-repo file recall</text>
  <text x="88" y="448" fill="#FFFFFF" font-family="Segoe UI, Arial, sans-serif" font-size="84" font-weight="700">{_fmt(frontier.get('avg_raw_file_recall', 0.0))} -&gt; {_fmt(frontier.get('avg_memla_combined_file_recall', 0.0))}</text>
  <text x="88" y="520" fill="#C9E9E3" font-family="Segoe UI, Arial, sans-serif" font-size="24">{_curriculum_summary(curriculum)}</text>
</svg>
"""


def render_acquisition_html(
    *,
    showcase: dict[str, Any],
    transfer: dict[str, Any],
    frontier: dict[str, Any],
    public_frontier: dict[str, Any] | None = None,
    curriculum: dict[str, Any] | None = None,
    site_url: str = "https://memla.vercel.app",
    contact_email: str = "salahsalad100@gmail.com",
) -> str:
    payload = json.dumps(
        {
            "showcase": showcase,
            "transfer": transfer,
            "frontier": frontier,
            "publicFrontier": public_frontier,
            "curriculum": curriculum,
        },
        ensure_ascii=False,
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Memla | Transferable Coding Intelligence</title>
  <meta name="description" content="Memla turns accepted coding work into transferable intelligence. Same model, new repo, materially better file routing and command prediction.">
  <meta property="og:title" content="Memla | Transferable Coding Intelligence">
  <meta property="og:description" content="Memla stores roles, constraints, transmutations, and verification rituals, then uses them to improve coding performance on new repos.">
  <meta property="og:type" content="website">
  <meta property="og:url" content="{site_url}">
  <meta property="og:image" content="{site_url.rstrip('/')}/og-card.svg">
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Fraunces:wght@500;600;700&family=Space+Grotesk:wght@400;500;700&display=swap');
    :root {{ --bg:#f6efe3; --ink:#15201e; --muted:#5c645d; --line:rgba(21,32,30,.12); --card:rgba(255,255,255,.8); --accent:#0f766e; --gold:#c58c3a; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; font-family:"Space Grotesk","Segoe UI",sans-serif; color:var(--ink); background:radial-gradient(circle at top left, rgba(15,118,110,.16), transparent 26%),radial-gradient(circle at top right, rgba(197,140,58,.18), transparent 24%),linear-gradient(180deg,#fbf7f1,var(--bg)); }}
    .wrap {{ width:min(1160px, calc(100vw - 32px)); margin:0 auto; padding:28px 0 64px; }}
    .hero,.section,.card {{ border:1px solid var(--line); background:var(--card); backdrop-filter:blur(14px); box-shadow:0 26px 80px rgba(16,33,30,.08); }}
    .hero {{ border-radius:30px; padding:28px; display:grid; gap:18px; }}
    .eyebrow {{ color:var(--accent); font-size:12px; text-transform:uppercase; letter-spacing:.22em; font-weight:700; }}
    h1 {{ margin:0; font-family:"Fraunces",Georgia,serif; font-size:clamp(40px,7vw,78px); line-height:.95; letter-spacing:-.04em; max-width:920px; }}
    .sub {{ color:var(--muted); font-size:18px; line-height:1.6; max-width:820px; }}
    .hero-grid {{ display:grid; grid-template-columns:1.45fr .9fr; gap:16px; }}
    .proof-card {{ border-radius:24px; padding:20px; background:linear-gradient(180deg, rgba(15,118,110,.08), rgba(255,255,255,.78)); border:1px solid rgba(15,118,110,.16); }}
    .proof-kicker {{ color:var(--accent); font-size:12px; text-transform:uppercase; letter-spacing:.16em; font-weight:700; }}
    .jump {{ display:flex; gap:14px; align-items:baseline; flex-wrap:wrap; margin-top:12px; }}
    .raw,.memla {{ font-size:clamp(42px,8vw,84px); line-height:.9; font-weight:700; }}
    .raw {{ color:#7b7064; }}
    .arrow {{ color:var(--gold); font-size:clamp(28px,6vw,56px); font-weight:700; }}
    .memla {{ color:var(--accent); }}
    .mini-stack {{ display:grid; gap:12px; }}
    .mini {{ border-radius:18px; padding:16px; background:linear-gradient(180deg, rgba(255,255,255,.78), rgba(247,242,234,.92)); border:1px solid var(--line); }}
    .mini .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.12em; }}
    .mini .value {{ margin-top:8px; font-size:32px; font-weight:700; letter-spacing:-.03em; }}
    .mini .body {{ color:var(--muted); font-size:14px; line-height:1.5; margin-top:8px; }}
    .actions {{ display:flex; gap:12px; flex-wrap:wrap; }}
    .button {{ display:inline-flex; align-items:center; justify-content:center; min-height:46px; padding:0 18px; border-radius:999px; font-weight:700; text-decoration:none; }}
    .button.primary {{ color:white; background:linear-gradient(135deg,var(--accent),#0b5650); }}
    .button.secondary {{ color:var(--ink); background:rgba(255,255,255,.72); border:1px solid var(--line); }}
    .metrics {{ display:grid; grid-template-columns:repeat(4, minmax(0, 1fr)); gap:14px; }}
    .metric {{ border-radius:20px; padding:18px; border:1px solid var(--line); background:linear-gradient(180deg, rgba(255,255,255,.82), rgba(249,244,238,.9)); }}
    .metric .label {{ color:var(--muted); text-transform:uppercase; letter-spacing:.08em; font-size:12px; }}
    .metric .value {{ font-size:30px; font-weight:700; margin-top:8px; }}
    .metric .note {{ color:var(--muted); font-size:14px; margin-top:8px; line-height:1.4; }}
    .section {{ margin-top:18px; border-radius:26px; padding:22px; }}
    .section h2 {{ margin:0 0 8px; font-family:"Fraunces",Georgia,serif; font-size:clamp(26px,4vw,38px); letter-spacing:-.03em; }}
    .section-intro {{ color:var(--muted); max-width:780px; line-height:1.6; margin-bottom:16px; }}
    .grid2,.chart-grid,.compare-row {{ display:grid; gap:14px; }}
    .grid2 {{ grid-template-columns:repeat(2, minmax(0, 1fr)); }}
    .chart-grid {{ grid-template-columns:1.2fr .8fr; }}
    .compare-row {{ grid-template-columns:1fr 1fr; }}
    .card {{ border-radius:20px; padding:18px; }}
    .bars {{ display:grid; gap:14px; margin-top:12px; }}
    .bar-row {{ display:grid; gap:8px; }}
    .bar-head {{ display:flex; justify-content:space-between; gap:10px; font-size:14px; align-items:baseline; }}
    .bar-label {{ font-weight:700; }}
    .track {{ position:relative; height:13px; border-radius:999px; background:rgba(21,32,30,.08); overflow:hidden; }}
    .fill {{ position:absolute; top:0; bottom:0; left:0; border-radius:999px; }}
    .fill.raw {{ background:linear-gradient(90deg, rgba(111,111,111,.56), rgba(86,86,86,.82)); }}
    .fill.memla {{ background:linear-gradient(90deg,var(--accent),var(--gold)); opacity:.95; }}
    .legend {{ display:flex; gap:14px; flex-wrap:wrap; color:var(--muted); font-size:13px; margin-top:14px; }}
    .legend span {{ display:inline-flex; gap:8px; align-items:center; }}
    .legend i {{ width:12px; height:12px; border-radius:999px; display:inline-block; }}
    .compare-cell {{ padding:14px; border-radius:16px; border:1px solid var(--line); background:rgba(255,255,255,.58); color:var(--muted); line-height:1.55; }}
    .compare-cell strong {{ display:block; color:var(--ink); margin-bottom:6px; font-size:16px; }}
    .trans-grid {{ display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }}
    .trans-chip {{ padding:10px 14px; border-radius:16px; background:linear-gradient(180deg, rgba(197,140,58,.12), rgba(255,255,255,.72)); border:1px solid rgba(197,140,58,.18); color:#65451d; font-size:14px; }}
    .case-list {{ display:grid; gap:14px; margin-top:12px; }}
    .case {{ border-radius:20px; padding:18px; border:1px solid var(--line); background:rgba(255,255,255,.72); }}
    .pill {{ display:inline-block; padding:6px 10px; border-radius:999px; margin-right:8px; margin-top:8px; font-size:13px; background:rgba(15,118,110,.1); color:var(--accent); }}
    .transmutation {{ display:inline-block; margin-top:8px; padding:8px 12px; border-radius:12px; background:#f2dfbd; color:#523d26; font-size:14px; margin-right:8px; }}
    .cta {{ background:linear-gradient(135deg, rgba(15,118,110,.92), rgba(11,83,79,.96)); color:white; }}
    .cta p {{ margin:0; color:rgba(255,255,255,.82); line-height:1.58; }}
    pre {{ white-space:pre-wrap; background:rgba(255,255,255,.68); border:1px solid var(--line); border-radius:18px; padding:16px; color:var(--muted); font-family:"IBM Plex Mono",Consolas,monospace; font-size:12px; line-height:1.55; }}
    .footer {{ margin-top:18px; color:var(--muted); font-size:13px; display:flex; justify-content:space-between; gap:12px; flex-wrap:wrap; }}
    @media (max-width:960px) {{ .hero-grid,.chart-grid,.metrics,.grid2,.compare-row {{ grid-template-columns:1fr; }} }}
    @media (max-width:640px) {{ .wrap {{ width:min(100vw - 20px, 1160px); }} .hero,.section {{ padding:18px; }} h1 {{ font-size:42px; }} }}
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <div class="eyebrow">Memla / Acquisition Preview</div>
      <h1>Memla turns accepted coding work into owned transfer.</h1>
      <div class="sub">Instead of only retrieving similar text, Memla stores roles, constraints, transmutations, and verification rituals from accepted work, then uses that structure to improve the same model on future coding tasks and on new repos.</div>
      <div class="hero-grid">
        <div class="proof-card">
          <div class="proof-kicker">Headline proof / same model, unseen second repo</div>
          <div class="jump"><span class="raw" id="hero-raw">0.1667</span><span class="arrow">-&gt;</span><span class="memla" id="hero-memla">0.9167</span></div>
          <p style="margin:16px 0 0;color:var(--muted);line-height:1.58;">Raw file recall to Memla-assisted file recall on unseen tasks, with no target-repo modification.</p>
          <div class="actions" style="margin-top:14px;">
            <a class="button primary" href="mailto:{contact_email}?subject=Memla%20diligence%20request">Request diligence packet</a>
            <a class="button secondary" href="#proof">See proof layers</a>
          </div>
        </div>
        <div class="mini-stack">
          <div class="mini"><div class="label">Public curriculum</div><div class="value" id="curriculum-summary">6 / 7</div><div class="body">Public repos reached holdout across web app, backend API, auth/security, and CLI/tooling families.</div></div>
          <div class="mini"><div class="label">Transfer unit</div><div class="value">Transmutations</div><div class="body">Memla stores the constraint trade behind a successful fix, not just the file path that changed.</div></div>
          <div class="mini"><div class="label">Why buyers care</div><div class="body">This converts expensive frontier-model usage into owned repo intelligence that compounds instead of evaporating between tasks.</div></div>
        </div>
      </div>
      <div class="metrics" id="metrics"></div>
    </section>
    <section class="section" id="proof">
      <h2>Proof Layers</h2>
      <div class="section-intro">The headline is the same-model second-repo jump. The support layers show that the bootstrap path also survives public seeded runs and a broader multi-family curriculum.</div>
      <div class="chart-grid">
        <div class="card">
          <div class="label">Recall graph</div>
          <div class="bars" id="proof-bars"></div>
          <div class="legend"><span><i style="background:linear-gradient(90deg, rgba(111,111,111,.56), rgba(86,86,86,.82));"></i>Baseline / raw</span><span><i style="background:linear-gradient(90deg, var(--accent), var(--gold));"></i>Memla</span></div>
        </div>
        <div class="card" id="proof-summary"></div>
      </div>
    </section>
    <section class="section">
      <h2>Why This Is More Than RAG</h2>
      <div class="section-intro">The difference is not "more context." The difference is that Memla stores reusable problem structure and then maps it onto the next repo.</div>
      <div class="compare-row">
        <div class="compare-cell"><strong>Naive retrieval</strong>Pulls similar text chunks and hopes the model can reconstruct the workflow.</div>
        <div class="compare-cell"><strong>Memla</strong>Stores role targets, constraint tags, transmutations, and verification rituals from accepted work.</div>
      </div>
      <div class="compare-row" style="margin-top:10px;">
        <div class="compare-cell"><strong>Failure mode</strong>Looks smart inside one prompt, then relearns too much on the next repo.</div>
        <div class="compare-cell"><strong>Advantage</strong>Enters new repos with a stronger first structural prior and compounds faster after foothold.</div>
      </div>
    </section>
    <section class="section">
      <h2>What Memla Actually Stores</h2>
      <div class="grid2">
        <pre>Accepted trace
|- likely files
|- commands / tests
|- workflow steps
|- repo family
\\- acceptance outcome</pre>
        <pre>Transmutation layer
|- role targets
|- constraint tags
|- transmutations
\\- verification rituals</pre>
      </div>
    </section>
    <section class="section">
      <h2>Transmutation Bank</h2>
      <div class="section-intro">These are the recurring constraint trades Memla now reuses across public repo families.</div>
      <div class="trans-grid" id="transmutations"></div>
    </section>
    <section class="section">
      <h2>Selected Proof Cases</h2>
      <div class="section-intro">These examples show how Memla steers the same model toward the local repo shape instead of generic architecture guesses.</div>
      <div class="case-list" id="frontier-cases"></div>
    </section>
    <section class="section">
      <h2>Multi-Family Support</h2>
      <div class="section-intro">The new curriculum rerun matters because it shows seeded support outside the original repo cluster and across more than one architecture family.</div>
      <div class="chart-grid">
        <div class="card">
          <div class="label">Completed public holdouts</div>
          <div class="bars" id="family-bars"></div>
        </div>
        <div class="card cta">
          <div class="label" style="color:rgba(255,255,255,.72);">Async diligence friendly</div>
          <h3 style="margin:0;font-size:28px;font-family:'Fraunces', Georgia, serif;">Ready to send, not just ready to explain.</h3>
          <p>Memla already has the full diligence packet, proof table, and frozen reports. If this is relevant to your roadmap, the fastest next step is an async diligence exchange on email.</p>
          <div class="actions" style="margin-top:14px;">
            <a class="button secondary" style="background:rgba(255,255,255,.16);color:white;border-color:rgba(255,255,255,.18);" href="mailto:{contact_email}?subject=Memla%20proof%20request">Email for the packet</a>
          </div>
        </div>
      </div>
      <div class="footer"><span>Built from frozen Memla proof artifacts on March 26, 2026.</span><span>Contact: {contact_email}</span></div>
    </section>
  </div>
  <script>
    const PACK = {payload};
    function format(value, digits = 4) {{
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "n/a";
      return Number(value).toFixed(digits).replace(/0+$/, "").replace(/\\.$/, "");
    }}
    function metric(label, value, note) {{
      return `<div class="metric"><div class="label">${{label}}</div><div class="value">${{value}}</div><div class="note">${{note}}</div></div>`;
    }}
    function barRow(label, raw, memla, detail) {{
      const rawPct = Math.max(0, Math.min(100, Number(raw || 0) * 100));
      const memlaPct = Math.max(0, Math.min(100, Number(memla || 0) * 100));
      return `<div class="bar-row"><div class="bar-head"><span class="bar-label">${{label}}</span><span>${{format(raw)}} -> <strong>${{format(memla)}}</strong> / ${{detail}}</span></div><div class="track"><div class="fill raw" style="width:${{rawPct}}%"></div><div class="fill memla" style="width:${{memlaPct}}%"></div></div></div>`;
    }}
    function trans(list) {{ return (list || []).map(item => `<span class="transmutation">${{item}}</span>`).join(""); }}
    function pills(list) {{ return (list || []).map(item => `<span class="pill">${{item}}</span>`).join(""); }}
    function frontierCase(row) {{
      return `<article class="case"><div class="label">Second repo, same model</div><h3 style="margin:8px 0 0">${{row.prompt}}</h3><div style="margin-top:10px">${{pills([`Raw files ${{format(row.raw_file_recall)}}`, `Memla files ${{format(row.memla_combined_file_recall)}}`, `Memla cmds ${{format(row.memla_combined_command_recall)}}`])}}</div><div style="margin-top:10px;color:#5c645d">Plan files: ${{(row.memla_plan_files || []).join(", ")}}</div><div style="margin-top:6px;color:#5c645d">Tests: ${{(row.memla_plan_tests || []).join(", ")}}</div><div style="margin-top:8px">${{trans(row.memla_transmutations || [])}}</div></article>`;
    }}
    function mini(title, value, body) {{
      return `<div class="mini"><div class="label">${{title}}</div><div class="value">${{value}}</div><div class="body">${{body}}</div></div>`;
    }}
    const curriculum = PACK.curriculum || {{}};
    const supportRows = (curriculum.results || []).filter(row => row.status === "completed").slice(0, 6);
    const proofLayers = [
      ["Second-repo same-model", PACK.frontier.avg_raw_file_recall, PACK.frontier.avg_memla_combined_file_recall, "file recall"],
      ["Second-repo planner transfer", PACK.transfer.avg_baseline_file_recall, PACK.transfer.avg_memla_file_recall, "file recall"],
      ...(PACK.publicFrontier ? [["Public seeded head-to-head", PACK.publicFrontier.avg_raw_file_recall, PACK.publicFrontier.avg_memla_combined_file_recall, "file recall"]] : []),
      ["Second-repo command lift", PACK.frontier.avg_raw_command_recall, PACK.frontier.avg_memla_combined_command_recall, "command recall"],
    ];
    document.getElementById("hero-raw").textContent = format(PACK.frontier.avg_raw_file_recall);
    document.getElementById("hero-memla").textContent = format(PACK.frontier.avg_memla_combined_file_recall);
    document.getElementById("curriculum-summary").textContent = `${{curriculum.repos_with_holdouts || 0}} / ${{curriculum.repos_attempted || 0}}`;
    document.getElementById("metrics").innerHTML = [
      metric("Home repo holdout", `${{format(PACK.showcase.final_report.avg_file_recall, 1)}} / ${{format(PACK.showcase.final_report.avg_command_recall, 1)}}`, "Seeded internal coding holdout"),
      metric("Second-repo file recall", `${{format(PACK.frontier.avg_raw_file_recall)}} -> ${{format(PACK.frontier.avg_memla_combined_file_recall)}}`, "Same model, Memla in front"),
      metric("Second-repo command recall", `${{format(PACK.frontier.avg_raw_command_recall, 1)}} -> ${{format(PACK.frontier.avg_memla_combined_command_recall, 1)}}`, "Raw to Memla-assisted"),
      metric("Public curriculum", `${{curriculum.repos_with_holdouts || 0}} / ${{curriculum.repos_attempted || 0}}`, "Public repos reached holdout"),
    ].join("");
    document.getElementById("proof-bars").innerHTML = proofLayers.map(row => barRow(row[0], row[1], row[2], row[3])).join("");
    document.getElementById("proof-summary").innerHTML = [
      mini("Second-repo planner", `${{format(PACK.transfer.avg_baseline_file_recall)}} -> ${{format(PACK.transfer.avg_memla_file_recall)}}`, "Empty-memory to Memla planner transfer on the same unseen second repo."),
      mini("Public seeded support", PACK.publicFrontier ? `${{format(PACK.publicFrontier.avg_raw_file_recall)}} -> ${{format(PACK.publicFrontier.avg_memla_combined_file_recall)}}` : "Not loaded", "Public OSS seeded head-to-head using the same local model stack."),
      mini("Transfer bank", `${{(curriculum.top_transmutations || []).length}} recurring motifs`, "Constraint trades are now repeating across backend API, auth/security, CLI, and web app families."),
    ].join("");
    document.getElementById("transmutations").innerHTML = (curriculum.top_transmutations || []).slice(0, 8).map(item => `<span class="trans-chip">${{item.text || item}}</span>`).join("");
    document.getElementById("frontier-cases").innerHTML = (PACK.frontier.rows || []).slice(0, 3).map(frontierCase).join("");
    document.getElementById("family-bars").innerHTML = supportRows.map(row => barRow(row.repo_label, row.avg_raw_command_recall || row.avg_raw_file_recall || 0, row.avg_memla_combined_command_recall || row.avg_memla_combined_file_recall || 0, row.avg_memla_combined_command_recall ? "command recall" : "file recall")).join("");
  </script>
</body>
</html>
"""


def build_acquisition_pack(
    *,
    showcase_path: str,
    transfer_path: str,
    frontier_path: str,
    out_dir: str,
    public_frontier_path: str | None = None,
    curriculum_batch_path: str | None = None,
    site_url: str = "https://memla.vercel.app",
    contact_email: str = "salahsalad100@gmail.com",
) -> dict[str, str]:
    showcase = _load_json(showcase_path)
    transfer = _load_json(transfer_path)
    frontier = _load_json(frontier_path)
    public_frontier = _load_json(public_frontier_path) if public_frontier_path else None
    curriculum = _load_json(curriculum_batch_path) if curriculum_batch_path else None

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

    outputs: dict[str, str] = {
        "frozen_showcase": str(frozen_showcase),
        "frozen_transfer": str(frozen_transfer),
        "frozen_frontier": str(frozen_frontier),
    }
    if public_frontier_path:
        frozen_public_frontier = frozen / "public_frontier_report.json"
        shutil.copy2(public_frontier_path, frozen_public_frontier)
        outputs["frozen_public_frontier"] = str(frozen_public_frontier)
    if curriculum_batch_path:
        frozen_curriculum = frozen / "public_curriculum_batch.json"
        shutil.copy2(curriculum_batch_path, frozen_curriculum)
        outputs["frozen_curriculum"] = str(frozen_curriculum)

    pitch_path = out / "one_sentence_pitch.txt"
    demo_flow_path = out / "90_second_demo.md"
    memo_path = out / "strategic_memo.md"
    targets_path = out / "buyer_targets.md"
    email_path = out / "outreach_email.txt"
    html_path = out / "index.html"
    og_card_path = out / "og-card.svg"
    vercel_path = out / "vercel.json"

    pitch_path.write_text(
        render_acquisition_pitch(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_frontier=public_frontier,
            curriculum=curriculum,
        ),
        encoding="utf-8",
    )
    demo_flow_path.write_text(render_acquisition_demo_flow(transfer=transfer, frontier=frontier), encoding="utf-8")
    memo_path.write_text(render_strategic_memo(showcase=showcase, transfer=transfer, frontier=frontier), encoding="utf-8")
    targets_path.write_text(render_buyer_targets(), encoding="utf-8")
    email_path.write_text(render_outreach_email(), encoding="utf-8")
    html_path.write_text(
        render_acquisition_html(
            showcase=showcase,
            transfer=transfer,
            frontier=frontier,
            public_frontier=public_frontier,
            curriculum=curriculum,
            site_url=site_url,
            contact_email=contact_email,
        ),
        encoding="utf-8",
    )
    og_card_path.write_text(render_og_card(frontier=frontier, curriculum=curriculum), encoding="utf-8")
    vercel_path.write_text(
        json.dumps({"cleanUrls": True, "trailingSlash": False}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    outputs.update(
        {
            "pitch": str(pitch_path),
            "demo_flow": str(demo_flow_path),
            "memo": str(memo_path),
            "targets": str(targets_path),
            "email": str(email_path),
            "html": str(html_path),
            "og_card": str(og_card_path),
            "vercel": str(vercel_path),
        }
    )
    return outputs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a buyer-facing acquisition pack from Memla proof artifacts.")
    parser.add_argument("--showcase", required=True)
    parser.add_argument("--transfer", required=True)
    parser.add_argument("--frontier", required=True)
    parser.add_argument("--public_frontier")
    parser.add_argument("--curriculum_batch")
    parser.add_argument("--site_url", default="https://memla.vercel.app")
    parser.add_argument("--contact_email", default="salahsalad100@gmail.com")
    parser.add_argument("--out_dir", default="./distill/acquisition_pack")
    args = parser.parse_args(argv)

    outputs = build_acquisition_pack(
        showcase_path=args.showcase,
        transfer_path=args.transfer,
        frontier_path=args.frontier,
        out_dir=args.out_dir,
        public_frontier_path=args.public_frontier,
        curriculum_batch_path=args.curriculum_batch,
        site_url=args.site_url,
        contact_email=args.contact_email,
    )
    print(json.dumps(outputs, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
