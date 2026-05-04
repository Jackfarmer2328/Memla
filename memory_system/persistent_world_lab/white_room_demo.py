"""Build and record white-room demo artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .white_room_director import build_director_bundle, record_white_room_artifacts, white_room_director_suite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="White room demo artifact recorder")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--seed", type=int, default=777)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("proof/white_room"),
        help="Directory to write bundle + fortress outputs",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result")
    args = parser.parse_args(argv)

    paths = record_white_room_artifacts(output_dir=str(args.out_dir), days=args.days, seed=args.seed)
    bundle = build_director_bundle(days=args.days, seed=args.seed)
    suite = white_room_director_suite(days=args.days, seed=args.seed)
    payload = {
        "ok": bool(suite["passed"]),
        "days": args.days,
        "seed": args.seed,
        "event_count": int(bundle["proof"]["event_count"]),
        "bundle_path": paths["bundle_path"],
        "fortress_path": paths["fortress_path"],
        "counterfactual_path": paths["counterfactual_path"],
        "studio_path": paths["studio_path"],
        "suite_passed": bool(suite["passed"]),
    }
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print("=== White Room Demo Recorder ===")
        print(f"days: {args.days} | seed: {args.seed}")
        print(f"event_count: {payload['event_count']}")
        print(f"bundle: {payload['bundle_path']}")
        print(f"fortress: {payload['fortress_path']}")
        print(f"counterfactual: {payload['counterfactual_path']}")
        print(f"studio: {payload['studio_path']}")
        print(f"suite_passed: {'YES' if payload['suite_passed'] else 'NO'}")
    return 0 if suite["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
