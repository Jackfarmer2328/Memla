from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _even_sample(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0 or not items:
        return []
    if count >= len(items):
        return list(items)
    if count == 1:
        return [items[len(items) // 2]]

    selected: list[dict[str, Any]] = []
    used: set[int] = set()
    span = len(items) - 1
    for i in range(count):
        idx = round((i * span) / (count - 1))
        while idx in used and idx + 1 < len(items):
            idx += 1
        while idx in used and idx - 1 >= 0:
            idx -= 1
        if idx in used:
            continue
        used.add(idx)
        selected.append(items[idx])
    return selected


def _pick_from_bucket(
    bucket: list[dict[str, Any]],
    *,
    count: int,
    selected_keys: set[tuple[int, int]],
) -> list[dict[str, Any]]:
    if count <= 0:
        return []
    available = [
        qa
        for qa in bucket
        if (int(qa["__conversation_index"]), int(qa["__question_index"])) not in selected_keys
    ]
    return _even_sample(available, count)


def build_holdout(
    *,
    input_file: Path,
    output_file: Path,
    summary_file: Path,
    total_questions: int,
) -> None:
    samples = json.loads(input_file.read_text(encoding="utf-8"))
    categories = sorted(
        {
            int(qa.get("category") or 0)
            for sample in samples
            for qa in list(sample.get("qa") or [])
            if int(qa.get("category") or 0) > 0
        }
    )
    if not categories:
        raise ValueError("No LoCoMo categories found in input file")

    indexed_samples: list[dict[str, Any]] = []
    buckets: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for conv_index, sample in enumerate(samples):
        cloned = json.loads(json.dumps(sample))
        cloned["qa"] = []
        indexed_samples.append(cloned)
        for question_index, qa in enumerate(list(sample.get("qa") or [])):
            qa_copy = json.loads(json.dumps(qa))
            qa_copy["__conversation_index"] = conv_index
            qa_copy["__question_index"] = question_index
            category = int(qa.get("category") or 0)
            buckets.setdefault((conv_index, category), []).append(qa_copy)

    conv_count = len(samples)
    target_per_cell = max(1, total_questions // max(1, conv_count * len(categories)))
    selected_keys: set[tuple[int, int]] = set()
    selected_items: list[dict[str, Any]] = []

    for conv_index in range(conv_count):
        for category in categories:
            picks = _pick_from_bucket(
                buckets.get((conv_index, category), []),
                count=target_per_cell,
                selected_keys=selected_keys,
            )
            for qa in picks:
                key = (int(qa["__conversation_index"]), int(qa["__question_index"]))
                if key in selected_keys:
                    continue
                selected_keys.add(key)
                selected_items.append(qa)

    remaining_needed = max(0, total_questions - len(selected_items))
    if remaining_needed:
        all_buckets = [
            ((conv_index, category), buckets.get((conv_index, category), []))
            for conv_index in range(conv_count)
            for category in categories
        ]
        bucket_index = 0
        while remaining_needed > 0 and all_buckets:
            (_, bucket) = all_buckets[bucket_index % len(all_buckets)]
            picks = _pick_from_bucket(bucket, count=1, selected_keys=selected_keys)
            if picks:
                qa = picks[0]
                key = (int(qa["__conversation_index"]), int(qa["__question_index"]))
                if key not in selected_keys:
                    selected_keys.add(key)
                    selected_items.append(qa)
                    remaining_needed -= 1
            bucket_index += 1
            if bucket_index > len(all_buckets) * max(10, total_questions):
                break

    if len(selected_items) < total_questions:
        leftovers: list[dict[str, Any]] = []
        for conv_index, sample in enumerate(samples):
            for question_index, qa in enumerate(list(sample.get("qa") or [])):
                if (conv_index, question_index) in selected_keys:
                    continue
                qa_copy = json.loads(json.dumps(qa))
                qa_copy["__conversation_index"] = conv_index
                qa_copy["__question_index"] = question_index
                leftovers.append(qa_copy)
        for qa in _even_sample(leftovers, total_questions - len(selected_items)):
            key = (int(qa["__conversation_index"]), int(qa["__question_index"]))
            if key in selected_keys:
                continue
            selected_keys.add(key)
            selected_items.append(qa)

    selected_items = sorted(
        selected_items,
        key=lambda qa: (int(qa["__conversation_index"]), int(qa["__question_index"])),
    )[:total_questions]

    for qa in selected_items:
        conv_index = int(qa.pop("__conversation_index"))
        qa.pop("__question_index", None)
        indexed_samples[conv_index]["qa"].append(qa)

    holdout_samples = [sample for sample in indexed_samples if sample.get("qa")]
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(holdout_samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "input_file": str(input_file),
        "output_file": str(output_file),
        "total_questions": sum(len(sample.get("qa") or []) for sample in holdout_samples),
        "conversation_count": len(holdout_samples),
        "category_counts": {},
        "conversation_counts": {},
    }
    for conv_index, sample in enumerate(holdout_samples):
        summary["conversation_counts"][str(sample.get("sample_id") or conv_index)] = len(sample.get("qa") or [])
        for qa in list(sample.get("qa") or []):
            category = str(int(qa.get("category") or 0))
            summary["category_counts"][category] = summary["category_counts"].get(category, 0) + 1

    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def parse_args() -> argparse.Namespace:
    repo_root = Path(__file__).resolve().parents[2]
    default_locomo = repo_root.parent / "external" / "locomo" / "data" / "locomo10.json"
    default_output = repo_root / "benchmarks" / "locomo" / "results" / "locomo_holdout_200.json"
    default_summary = repo_root / "benchmarks" / "locomo" / "results" / "locomo_holdout_200_summary.json"
    parser = argparse.ArgumentParser(description="Build a stratified LoCoMo holdout file.")
    parser.add_argument("--input-file", type=Path, default=default_locomo)
    parser.add_argument("--output-file", type=Path, default=default_output)
    parser.add_argument("--summary-file", type=Path, default=default_summary)
    parser.add_argument("--total-questions", type=int, default=200)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_holdout(
        input_file=args.input_file,
        output_file=args.output_file,
        summary_file=args.summary_file,
        total_questions=max(1, int(args.total_questions)),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
