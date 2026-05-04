"""
1000-NPC Chorus: isolated histories, one shared question, live consistency score.

Run:

  py -3 -m memory_system.persistent_world_lab.chorus_demo
"""

from __future__ import annotations

import argparse
import json
import sys

from .chorus_engine import consistency_ratio, run_chorus


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="1000-NPC isolation + recall chorus")
    parser.add_argument("--population", type=int, default=1000)
    parser.add_argument("--noise", type=int, default=20, help="Episodic noise lines after turn-1 oath")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.population < 1:
        print("population must be >= 1", file=sys.stderr)
        return 2

    result = run_chorus(population=args.population, noise_lines=args.noise, top_k=args.top_k)
    ratio = consistency_ratio(result)

    if args.json:
        print(
            json.dumps(
                {
                    "population": result.population,
                    "correct": result.correct,
                    "consistency_ratio": ratio,
                    "wrong_sample": result.wrong_ids[:20],
                    "total_ms": round(result.total_ms, 3),
                    "noise_lines_per_npc": result.noise_lines_per_npc,
                },
                indent=2,
            )
        )
    else:
        print("=== 1000-NPC Chorus (isolated MemoryEngine per NPC) ===\n")
        print(f"Population: {result.population}")
        print(f"Noise lines per NPC (after turn-1 oath): {result.noise_lines_per_npc}")
        print(f"Correct recall: {result.correct} / {result.population}")
        print(f"Consistency score: {ratio:.4f} ({100.0 * ratio:.2f}%)")
        print(f"Wall time: {result.total_ms:.2f} ms")
        if result.wrong_ids:
            print(f"First wrong NPC ids (sample): {result.wrong_ids[:15]} ...")
        else:
            print("Wrong NPC ids: none")

    passed = result.correct == result.population
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
