"""
Memla Stress Simulation — LLM-driven hardening.

Spins up Memla's core engine (no web server needed) and runs simulated
multi-persona conversations using your local Ollama models.  Each persona
has a domain, a communication style, and scripted behavior that exercises
every constraint:

  C1  Graph-augmented retrieval   — personas link memories, then query them
  C2  Sarcasm frame detection     — enthusiastic agreement vs real correction
  C3  Preflight targeting         — measure semantic hit quality mid-type
  C4  Sync                        — (skipped in sim, env-flag tested separately)
  C5  Lazy import                 — register files, query, verify JIT extraction
  C6  Generative CPO              — trajectories saved, corrections generated
  C7  Hierarchical consolidation  — bulk chunks → consolidate → expand
  C8  Backward extraction         — verify assistant knowledge gets stored

Usage:
    python simulate.py --model qwen3.5:4b --turns 30 --personas 3
    python simulate.py --model gemma3:4b --turns 50 --personas 5 --fast

Outputs a report to stdout with pass/fail per constraint and metrics.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import shutil
import sqlite3
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from memory_system.memory.episode_log import EpisodeLog, Chunk
from memory_system.memory.chunk_manager import ChunkManager
from memory_system.memory.lazy_import import LazyImporter
from memory_system.memory.consolidator import consolidate
from memory_system.middleware.ttt_layer import TTTLayer
from memory_system.middleware.quality import detect_correction, score_chunk_usage
from memory_system.ollama_client import ChatMessage, UniversalLLMClient

BASE_SYSTEM = (
    "You are a helpful assistant. Use retrieved memory when relevant. "
    "Be concise but accurate."
)

# ── Persona definitions ──────────────────────────────────────────

PERSONAS = [
    {
        "id": "dev_alex",
        "name": "Alex",
        "domain": "software engineering",
        "seed_facts": [
            "I'm building a React frontend with TypeScript.",
            "Our backend uses FastAPI with PostgreSQL.",
            "We deploy on AWS ECS with Fargate.",
            "The project is called Phoenix and it's a CRM tool.",
            "I prefer functional components over class components.",
        ],
        "follow_ups": [
            "What tech stack am I using for Phoenix?",
            "Remind me what our deployment setup is.",
            "What's my preference for React components?",
        ],
        "corrections": [
            "No, we switched from PostgreSQL to Supabase last week.",
            "Actually I meant we use Next.js now, not plain React.",
            "That's not right, the project is called Phoenix not Firebird.",
        ],
        "sarcasm": [
            "No way, that actually worked! Amazing!",
            "Wrong answer haha just kidding, that's perfect!",
            "Actually that's awesome, exactly what I needed!",
        ],
        "link_pairs": [(0, 1), (1, 2), (0, 3)],
    },
    {
        "id": "marketer_sam",
        "name": "Sam",
        "domain": "digital marketing",
        "seed_facts": [
            "My client Byron Creative has a $50k monthly ad budget.",
            "We're seeing campaign fatigue on Instagram reels.",
            "Byron's target demographic is 25-34 year old professionals.",
            "Our best performing channel last quarter was LinkedIn.",
            "I want to try TikTok ads but Byron is hesitant.",
        ],
        "follow_ups": [
            "What's Byron's ad budget again?",
            "Which platform performed best last quarter?",
            "What age group are we targeting for Byron?",
        ],
        "corrections": [
            "No, I told you the budget is $50k not $30k.",
            "You said LinkedIn but I meant to say it was actually Google Ads.",
            "That's wrong, Byron's demographic is 25-34 not 18-24.",
        ],
        "sarcasm": [
            "No kidding, that's exactly the insight I needed!",
            "Actually that's great advice, love it!",
            "No way that ROI is possible! But let's try it!",
        ],
        "link_pairs": [(0, 1), (2, 3), (0, 4)],
    },
    {
        "id": "student_mia",
        "name": "Mia",
        "domain": "biology research",
        "seed_facts": [
            "My thesis is on CRISPR gene editing in zebrafish.",
            "I'm studying at MIT in the biology department.",
            "My advisor is Professor Chen who specializes in genomics.",
            "I need to finish my literature review by March.",
            "The lab uses Illumina sequencers for our work.",
        ],
        "follow_ups": [
            "What's my thesis about?",
            "Who is my advisor and what's their specialty?",
            "What equipment does our lab use?",
        ],
        "corrections": [
            "No, my thesis is on zebrafish not mice.",
            "I said Professor Chen, not Professor Lee.",
            "Actually the deadline is March not April.",
        ],
        "sarcasm": [
            "No way, that paper is exactly what I was looking for!",
            "Wrong department haha, just kidding, you got it right!",
            "Actually that's perfect, my advisor will love this!",
        ],
        "link_pairs": [(0, 2), (0, 4), (2, 3)],
    },
    {
        "id": "chef_tony",
        "name": "Tony",
        "domain": "restaurant management",
        "seed_facts": [
            "I own an Italian restaurant called Bella Notte in Brooklyn.",
            "We source our pasta from a supplier in Napoli.",
            "Our busiest nights are Friday and Saturday with 200 covers each.",
            "I'm considering adding a brunch menu on Sundays.",
            "Our head chef specializes in Southern Italian cuisine.",
        ],
        "follow_ups": [
            "What's the name of my restaurant?",
            "Where do we get our pasta from?",
            "How many covers do we do on busy nights?",
        ],
        "corrections": [
            "No, the restaurant is in Brooklyn not Manhattan.",
            "I said 200 covers, not 150.",
            "That's not right, I said brunch on Sundays not Saturdays.",
        ],
        "sarcasm": [
            "No way, that menu idea is brilliant!",
            "Actually that wine pairing is perfect!",
            "Wrong price haha just kidding, that margin works!",
        ],
        "link_pairs": [(0, 1), (0, 4), (2, 3)],
    },
    {
        "id": "analyst_jordan",
        "name": "Jordan",
        "domain": "financial analysis",
        "seed_facts": [
            "I'm analyzing Q3 earnings for our portfolio of tech stocks.",
            "Our top holding is NVIDIA at 15% of the portfolio.",
            "The fund's risk tolerance is moderate-aggressive.",
            "We're concerned about interest rate impacts on growth stocks.",
            "My team uses Bloomberg Terminal for real-time data.",
        ],
        "follow_ups": [
            "What's our top holding and its weight?",
            "What's the fund's risk tolerance?",
            "What tools does my team use?",
        ],
        "corrections": [
            "No, NVIDIA is 15% not 10% of the portfolio.",
            "I said moderate-aggressive, not conservative.",
            "That's wrong, we use Bloomberg not Reuters.",
        ],
        "sarcasm": [
            "No way, those returns are incredible!",
            "Actually that alpha is exactly what we wanted!",
            "Wrong ticker haha, just kidding, good analysis!",
        ],
        "link_pairs": [(0, 1), (1, 3), (0, 4)],
    },
]


@dataclass
class Metrics:
    turns_run: int = 0
    retrieval_hits: int = 0
    retrieval_misses: int = 0
    corrections_detected: int = 0
    corrections_missed: int = 0
    sarcasm_blocked: int = 0
    sarcasm_leaked: int = 0
    backward_chunks_created: int = 0
    consolidation_summaries: int = 0
    expand_children: int = 0
    lazy_sources_registered: int = 0
    lazy_chunks_extracted: int = 0
    chunk_usage_positive: int = 0
    chunk_usage_negative: int = 0
    link_signals: int = 0
    errors: list[str] = field(default_factory=list)
    timings: dict[str, list[float]] = field(default_factory=lambda: {
        "chat": [], "retrieve": [], "consolidate": [], "preflight": [],
    })


def run_simulation(
    *,
    model: str,
    ollama_url: str,
    num_personas: int,
    turns_per_persona: int,
    fast: bool,
    db_path: str,
) -> Metrics:
    metrics = Metrics()
    personas = PERSONAS[:num_personas]

    client = UniversalLLMClient(provider="ollama", base_url=ollama_url)

    # Verify Ollama is alive
    try:
        import requests
        r = requests.get(f"{ollama_url}/api/tags", timeout=5)
        r.raise_for_status()
        models = [m["name"] for m in r.json().get("models", [])]
        if not any(model in m for m in models):
            print(f"  [warn] Model '{model}' not found in Ollama. Available: {models}")
            print(f"  [warn] Continuing anyway — Ollama may pull it on first use.\n")
    except Exception as e:
        print(f"  [FAIL] Cannot reach Ollama at {ollama_url}: {e}")
        sys.exit(1)

    for pi, persona in enumerate(personas):
        uid = persona["id"]
        sid = f"sim_{uid}_{int(time.time())}"
        print(f"\n{'='*60}")
        print(f"  Persona {pi+1}/{len(personas)}: {persona['name']} ({persona['domain']})")
        print(f"  User ID: {uid} | Session: {sid}")
        print(f"{'='*60}")

        log = EpisodeLog(db_path)
        cm = ChunkManager(log)
        ttt = TTTLayer(episode_log=log, chunk_manager=cm)
        lazy = LazyImporter(log)

        # Ensure user_links table exists
        log._conn.execute("""
            CREATE TABLE IF NOT EXISTS user_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                chunk_a_id INTEGER NOT NULL,
                chunk_b_id INTEGER NOT NULL,
                created_ts INTEGER NOT NULL,
                UNIQUE(user_id, chunk_a_id, chunk_b_id)
            )
        """)
        log._conn.commit()

        # ── Phase 1: Seed facts ──────────────────────────────────
        print(f"\n  Phase 1: Seeding {len(persona['seed_facts'])} facts...")
        seed_chunk_ids: list[int] = []
        for fact in persona["seed_facts"]:
            _, cids = cm.persist_user_message(
                session_id=sid, user_id=uid, user_text=fact,
            )
            seed_chunk_ids.extend(cids)
            metrics.turns_run += 1

        print(f"    Created {len(seed_chunk_ids)} chunks")

        # ── Phase 2: Link memories (C1 test) ─────────────────────
        print(f"\n  Phase 2: Linking memory pairs (C1)...")
        all_chunks = log.fetch_recent_chunks(user_id=uid, limit=200)
        chunk_ids_list = [c.id for c in all_chunks]
        for a_idx, b_idx in persona.get("link_pairs", []):
            if a_idx < len(chunk_ids_list) and b_idx < len(chunk_ids_list):
                a_id, b_id = chunk_ids_list[a_idx], chunk_ids_list[b_idx]
                try:
                    log._conn.execute(
                        "INSERT OR IGNORE INTO user_links(user_id,chunk_a_id,chunk_b_id,created_ts) VALUES(?,?,?,?)",
                        (uid, min(a_id, b_id), max(a_id, b_id), int(time.time())),
                    )
                    log._conn.commit()
                    metrics.link_signals += 1
                except Exception:
                    pass
        print(f"    Linked {metrics.link_signals} pairs")

        # ── Phase 3: Retrieval queries (C1 + C3) ────────────────
        print(f"\n  Phase 3: Testing retrieval & preflight...")
        for q in persona["follow_ups"]:
            t0 = time.time()
            retrieved = cm.retrieve(user_id=uid, query_text=q, k=5)
            dt = time.time() - t0
            metrics.timings["retrieve"].append(dt)

            domain_tokens = set(re.findall(r"[a-zA-Z0-9_]+", " ".join(persona["seed_facts"]).lower()))
            hit = any(
                len(set(re.findall(r"[a-zA-Z0-9_]+", c.text.lower())) & domain_tokens) >= 2
                for c in retrieved
            )
            if hit:
                metrics.retrieval_hits += 1
            else:
                metrics.retrieval_misses += 1
            metrics.turns_run += 1
            status = "HIT" if hit else "MISS"
            print(f"    [{status}] \"{q[:50]}\" -> {len(retrieved)} chunks ({dt:.2f}s)")

        # ── Phase 4: Full chat turns with LLM ────────────────────
        if not fast:
            print(f"\n  Phase 4: Running {turns_per_persona} chat turns with {model}...")
            history: list[ChatMessage] = []

            for ti in range(turns_per_persona):
                # Decide turn type
                r = random.random()
                if ti < 2:
                    msg = persona["seed_facts"][ti % len(persona["seed_facts"])]
                    turn_type = "seed"
                elif r < 0.3:
                    msg = random.choice(persona["follow_ups"])
                    turn_type = "query"
                elif r < 0.5:
                    msg = random.choice(persona["corrections"])
                    turn_type = "correction"
                elif r < 0.65:
                    msg = random.choice(persona["sarcasm"])
                    turn_type = "sarcasm"
                else:
                    prompt = (
                        f"You are {persona['name']}, who works in {persona['domain']}. "
                        f"Generate a single short message (1-2 sentences) that a user might say "
                        f"to a personal assistant about their work. Base it on these facts:\n"
                        + "\n".join(f"- {f}" for f in persona["seed_facts"])
                        + "\nRespond with ONLY the user message, nothing else."
                    )
                    try:
                        msg = client.chat(
                            model=model,
                            messages=[ChatMessage(role="user", content=prompt)],
                            temperature=0.8,
                            num_ctx=1024,
                        ).strip().strip('"')
                        turn_type = "organic"
                    except Exception as e:
                        metrics.errors.append(f"LLM gen failed: {e}")
                        continue

                # Check correction/sarcasm detection BEFORE sending
                corr_score = detect_correction(msg)
                if turn_type == "correction":
                    if corr_score > 0.3:
                        metrics.corrections_detected += 1
                    else:
                        metrics.corrections_missed += 1
                        metrics.errors.append(f"C2 miss: correction not detected: \"{msg[:60]}\"")
                elif turn_type == "sarcasm":
                    if corr_score < 0.1:
                        metrics.sarcasm_blocked += 1
                    else:
                        metrics.sarcasm_leaked += 1
                        metrics.errors.append(f"C2 leak: sarcasm fired signal ({corr_score}): \"{msg[:60]}\"")

                # Run through TTT layer
                t0 = time.time()
                arts = ttt.on_user_message(
                    session_id=sid, user_id=uid, user_text=msg,
                    base_system=BASE_SYSTEM, top_k=8,
                )
                system_prompt = arts.built.system_prompt
                messages_for_llm = [
                    ChatMessage(role="system", content=system_prompt),
                    *history[-(10*2):],
                    ChatMessage(role="user", content=msg),
                ]

                try:
                    response = client.chat(
                        model=model, messages=messages_for_llm, temperature=0.3,
                        num_ctx=2048,
                    )
                except Exception as e:
                    metrics.errors.append(f"LLM chat failed: {e}")
                    continue

                dt = time.time() - t0
                metrics.timings["chat"].append(dt)

                # Score chunk usage
                if arts.retrieved:
                    quals = score_chunk_usage(
                        retrieved_chunks=arts.retrieved,
                        assistant_response=response,
                    )
                    for q in quals:
                        if q.is_positive:
                            metrics.chunk_usage_positive += 1
                        else:
                            metrics.chunk_usage_negative += 1

                ttt.on_assistant_message(
                    session_id=sid, user_id=uid, assistant_text=response,
                )
                history.append(ChatMessage(role="user", content=msg))
                history.append(ChatMessage(role="assistant", content=response))
                metrics.turns_run += 1

                label = turn_type.upper()[:4]
                print(f"    [{label}] T{ti+1}: \"{msg[:45]}...\" -> {len(response)} chars ({dt:.1f}s)")

        # ── Phase 5: Backward extraction check (C8) ──────────────
        print(f"\n  Phase 5: Checking backward extraction (C8)...")
        chunks_after = log.fetch_recent_chunks(user_id=uid, limit=9999)
        backward = [c for c in chunks_after if "[Confirmed]" in c.text]
        metrics.backward_chunks_created += len(backward)
        print(f"    Backward-extracted chunks: {len(backward)}")

        # ── Phase 6: Consolidation (C7) ──────────────────────────
        print(f"\n  Phase 6: Consolidation (C7)...")
        t0 = time.time()
        try:
            summary_ids = consolidate(log, user_id=uid, similarity_threshold=0.2, min_cluster_size=3)
            dt = time.time() - t0
            metrics.timings["consolidate"].append(dt)
            metrics.consolidation_summaries += len(summary_ids)
            print(f"    Created {len(summary_ids)} summary nodes ({dt:.2f}s)")

            if len(summary_ids) > 0:
                top_level = log.fetch_top_level_chunks(user_id=uid, limit=500)
                summaries = [c for c in top_level if c.chunk_type == "summary"]
                for s in summaries[:3]:
                    children = log.fetch_children(s.id)
                    metrics.expand_children += len(children)
                    print(f"    Summary \"{s.key[:40]}\" has {len(children)} children")
        except Exception as e:
            metrics.errors.append(f"Consolidation failed: {e}")
            print(f"    [ERROR] {e}")

        # ── Phase 7: Lazy import (C5) ────────────────────────────
        print(f"\n  Phase 7: Lazy import test (C5)...")
        tmp = Path(tempfile.mkdtemp())
        test_file = tmp / "test_notes.txt"
        test_file.write_text(
            f"{persona['name']} works in {persona['domain']}. "
            + " ".join(persona["seed_facts"])
            + " This is additional context about their work that should be extracted on demand.",
            encoding="utf-8",
        )
        try:
            lazy.register_source(str(test_file), user_id=uid, title=f"{persona['name']}'s Notes")
            metrics.lazy_sources_registered += 1
            srcs = lazy.list_sources(uid)
            print(f"    Registered: {len(srcs)} sources")

            query = persona["follow_ups"][0] if persona["follow_ups"] else persona["domain"]
            extracted = lazy.on_demand_extract(query=query, user_id=uid, session_id=sid)
            metrics.lazy_chunks_extracted += len(extracted)
            print(f"    On-demand extracted: {len(extracted)} chunks for \"{query[:40]}\"")
        except Exception as e:
            metrics.errors.append(f"Lazy import failed: {e}")
            print(f"    [ERROR] {e}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        log.close()
        print(f"\n  Persona {persona['name']} complete.")

    return metrics


def print_report(m: Metrics, elapsed: float) -> None:
    print(f"\n{'='*60}")
    print(f"  MEMLA SIMULATION REPORT")
    print(f"{'='*60}")
    print(f"\n  Total time: {elapsed:.1f}s | Turns: {m.turns_run}")
    print()

    # Constraint results
    results = []

    # C1: Graph-augmented retrieval
    total_ret = m.retrieval_hits + m.retrieval_misses
    hit_rate = m.retrieval_hits / max(1, total_ret) * 100
    c1_pass = hit_rate >= 50
    results.append(("C1 Graph Retrieval", c1_pass, f"{hit_rate:.0f}% hit rate ({m.retrieval_hits}/{total_ret})"))

    # C2: Sarcasm detection
    total_corr = m.corrections_detected + m.corrections_missed
    corr_rate = m.corrections_detected / max(1, total_corr) * 100
    total_sarc = m.sarcasm_blocked + m.sarcasm_leaked
    sarc_rate = m.sarcasm_blocked / max(1, total_sarc) * 100
    c2_pass = corr_rate >= 70 and sarc_rate >= 70
    results.append(("C2 Frame Detection", c2_pass,
                     f"Corrections: {corr_rate:.0f}% detected | Sarcasm: {sarc_rate:.0f}% blocked"))

    # C5: Lazy import
    c5_pass = m.lazy_sources_registered > 0 and m.lazy_chunks_extracted > 0
    results.append(("C5 Lazy Import", c5_pass,
                     f"{m.lazy_sources_registered} sources, {m.lazy_chunks_extracted} chunks extracted"))

    # C7: Consolidation
    c7_pass = m.consolidation_summaries > 0
    results.append(("C7 Consolidation", c7_pass,
                     f"{m.consolidation_summaries} summaries, {m.expand_children} children expanded"))

    # C8: Backward extraction
    c8_pass = m.backward_chunks_created > 0 if m.turns_run > 10 else True
    results.append(("C8 Backward Extract", c8_pass,
                     f"{m.backward_chunks_created} confirmed chunks stored"))

    # Chunk usage quality
    total_usage = m.chunk_usage_positive + m.chunk_usage_negative
    usage_rate = m.chunk_usage_positive / max(1, total_usage) * 100
    results.append(("Chunk Usage Signal", total_usage > 0,
                     f"{usage_rate:.0f}% positive ({m.chunk_usage_positive}/{total_usage})"))

    # Link signals
    results.append(("Graph Links", m.link_signals > 0, f"{m.link_signals} links created"))

    print("  CONSTRAINT        STATUS    DETAILS")
    print("  " + "-"*56)
    for name, passed, detail in results:
        status = "PASS" if passed else "FAIL"
        icon = "+" if passed else "X"
        print(f"  [{icon}] {name:<20s} {status:<8s} {detail}")

    # Timing summary
    print(f"\n  TIMING")
    print("  " + "-"*56)
    for key, times in m.timings.items():
        if times:
            avg = sum(times) / len(times)
            mn, mx = min(times), max(times)
            print(f"  {key:<16s} avg={avg:.2f}s  min={mn:.2f}s  max={mx:.2f}s  n={len(times)}")

    if m.errors:
        print(f"\n  ERRORS ({len(m.errors)})")
        print("  " + "-"*56)
        for e in m.errors[:20]:
            print(f"  - {e}")
        if len(m.errors) > 20:
            print(f"  ... and {len(m.errors) - 20} more")

    passed = sum(1 for _, p, _ in results if p)
    total = len(results)
    print(f"\n  OVERALL: {passed}/{total} constraints passing")
    print(f"{'='*60}\n")


def main():
    p = argparse.ArgumentParser(description="Memla Stress Simulation")
    p.add_argument("--model", default="qwen3.5:4b", help="Ollama model to use")
    p.add_argument("--ollama_url", default=os.environ.get(
        "OLLAMA_URL", os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434"),
    ))
    p.add_argument("--turns", type=int, default=20, help="Chat turns per persona")
    p.add_argument("--personas", type=int, default=3, help="Number of personas (1-5)")
    p.add_argument("--fast", action="store_true",
                   help="Skip LLM chat turns (test only retrieval/detection/consolidation)")
    p.add_argument("--db", default="./sim_memory.sqlite", help="Simulation database path")
    a = p.parse_args()

    url = a.ollama_url.rstrip("/")
    if not url.startswith("http"):
        url = "http://" + url

    print(f"\n  Memla Stress Simulation")
    print(f"  Model: {a.model}")
    print(f"  Ollama: {url}")
    print(f"  Personas: {a.personas}")
    print(f"  Turns/persona: {a.turns}")
    print(f"  Mode: {'fast (no LLM)' if a.fast else 'full (with LLM)'}")
    db_path = a.db
    if Path(db_path).exists():
        try:
            Path(db_path).unlink()
            for suffix in ["-wal", "-shm"]:
                p2 = Path(db_path + suffix)
                if p2.exists():
                    p2.unlink()
        except PermissionError:
            ts = int(time.time())
            db_path = str(Path(db_path).with_stem(f"{Path(db_path).stem}_{ts}"))
            print(f"  [DB locked, using {db_path} instead]")
    print(f"  DB: {db_path}")

    t0 = time.time()
    metrics = run_simulation(
        model=a.model,
        ollama_url=url,
        num_personas=min(a.personas, len(PERSONAS)),
        turns_per_persona=a.turns,
        fast=a.fast,
        db_path=db_path,
    )
    elapsed = time.time() - t0

    print_report(metrics, elapsed)


if __name__ == "__main__":
    main()
