#!/usr/bin/env python3
"""
Extract failed task inputs from a JSONL result log and infer input image paths.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

DEFAULT_JSONL = "/mnt/data/Project/qwen-image/批量测试/output/round_woman_results.jsonl"
DEFAULT_INPUT_DIR = "/mnt/data/Project/qwen-image/批量测试/input/woman"
DEFAULT_OUTPUT_DIR = "/mnt/data/Project/qwen-image/批量测试/output/round_woman"

RUN_SUFFIX_PATTERN = re.compile(r"_run\d+$")
TASK_RUN_PATTERN = re.compile(r"^(?P<base>.+?)_run\d+$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract failed task parameters and infer original input image paths."
    )
    parser.add_argument(
        "--jsonl",
        default=DEFAULT_JSONL,
        help=f"Result JSONL path (default: {DEFAULT_JSONL})",
    )
    parser.add_argument(
        "--input-dir",
        default=DEFAULT_INPUT_DIR,
        help=f"Input image directory (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Generated output image directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--print-all-failed",
        action="store_true",
        help="Include full raw failed records in output JSON.",
    )
    return parser.parse_args()


def base_task_id(task_id: str) -> str:
    match = TASK_RUN_PATTERN.match(task_id)
    if match:
        return match.group("base")
    return task_id


def png_base_name(path: Path) -> str:
    return RUN_SUFFIX_PATTERN.sub("", path.stem)


def load_failed_records(jsonl_path: Path) -> tuple[list[dict[str, Any]], int]:
    failed: list[dict[str, Any]] = []
    total = 0

    with jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            record = json.loads(line)
            if record.get("status") != "success" and record.get("status") != "skipped":
                failed.append(record)
    return failed, total


def collect_input_stem_to_path(input_dir: Path) -> dict[str, str]:
    if not input_dir.exists() or not input_dir.is_dir():
        return {}
    return {p.stem: str(p.resolve()) for p in input_dir.iterdir() if p.is_file()}


def collect_output_png_base_names(output_dir: Path) -> set[str]:
    if not output_dir.exists() or not output_dir.is_dir():
        return set()
    return {png_base_name(p) for p in output_dir.glob("*.png")}


def infer_base_task_to_input_path(
    failed_records: list[dict[str, Any]],
    input_stem_to_path: dict[str, str],
    output_png_bases: set[str],
) -> dict[str, str | None]:
    failed_base_ids = sorted(
        {base_task_id(str(r.get("task_id", ""))) for r in failed_records}
    )
    missing_input_stems = sorted(set(input_stem_to_path.keys()) - output_png_bases)

    mapping: dict[str, str | None] = {base_id: None for base_id in failed_base_ids}
    if not failed_base_ids:
        return mapping

    # Most reliable heuristic for repeated runs:
    # one missing input stem and one failed base task group.
    if len(failed_base_ids) == 1 and len(missing_input_stems) == 1:
        mapping[failed_base_ids[0]] = input_stem_to_path[missing_input_stems[0]]
        return mapping

    # Fallback: if params.image is already a local path, trust it.
    for record in failed_records:
        task_id = str(record.get("task_id", ""))
        base_id = base_task_id(task_id)
        if mapping.get(base_id):
            continue
        image_value = (record.get("params") or {}).get("image")
        if (
            isinstance(image_value, str)
            and image_value
            and not image_value.startswith("data:")
        ):
            path = Path(image_value)
            if path.exists():
                mapping[base_id] = str(path.resolve())

    return mapping


def build_failed_output(
    failed_records: list[dict[str, Any]],
    base_task_to_input: dict[str, str | None],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for record in failed_records:
        task_id = str(record.get("task_id", ""))
        base_id = base_task_id(task_id)
        result.append(
            {
                "task_id": task_id,
                "status": record.get("status"),
                "error": record.get("error"),
                "params": record.get("params"),
                "input_image_path": base_task_to_input.get(base_id),
            }
        )
    return result


def main() -> None:
    args = parse_args()
    jsonl_path = Path(args.jsonl)
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)

    if not jsonl_path.exists():
        raise FileNotFoundError(f"JSONL file not found: {jsonl_path}")

    failed_records, total_records = load_failed_records(jsonl_path)
    input_stem_to_path = collect_input_stem_to_path(input_dir)
    output_png_bases = collect_output_png_base_names(output_dir)
    base_task_to_input = infer_base_task_to_input_path(
        failed_records, input_stem_to_path, output_png_bases
    )
    failed_items = build_failed_output(failed_records, base_task_to_input)

    out: dict[str, Any] = {
        "jsonl_path": str(jsonl_path.resolve()),
        "input_dir": str(input_dir.resolve()) if input_dir.exists() else str(input_dir),
        "output_dir": str(output_dir.resolve())
        if output_dir.exists()
        else str(output_dir),
        "total_records": total_records,
        "failed_count": len(failed_items),
        "failed_tasks": failed_items,
    }
    if args.print_all_failed:
        out["raw_failed_records"] = failed_records

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
