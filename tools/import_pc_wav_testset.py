#!/usr/bin/env python3
"""Create a transparent source-label benchmark manifest from pc_wav_only."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


FIELDS = (
    "sample_id",
    "file",
    "label",
    "species",
    "source_dataset",
    "source_recording_id",
    "start_sample",
    "duration_samples",
    "split",
    "annotation_status",
    "mixed_species",
    "leakage_check",
    "pcm_sha256",
    "wav_sha256",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pc-wav", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--per-class",
        type=int,
        default=1,
        help="number of source-labelled samples per class",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = args.pc_wav.resolve()
    source = root / "send_manifest.csv"
    output = args.output.resolve()
    if args.per_class <= 0:
        raise SystemExit("--per-class must be positive")
    with source.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    by_label: dict[int, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_label[int(row["label"])].append(row)
    if set(by_label) != set(range(8)):
        raise SystemExit(f"expected labels 0..7, got {sorted(by_label)}")
    for label in range(8):
        if len(by_label[label]) < args.per_class:
            raise SystemExit(
                f"label {label} has only {len(by_label[label])} samples"
            )
    selected: list[dict[str, str]] = []
    for offset in range(args.per_class):
        for label in range(8):
            row = by_label[label][offset]
            source_start_second = int(row["source_start_second"])
            selected.append(
                {
                    "sample_id": (
                        f"{row['packet_id']}_{Path(row['file']).stem}"
                    ),
                    "file": row["file"],
                    "label": row["label"],
                    "species": row["species"],
                    "source_dataset": "DB3V",
                    "source_recording_id": row["source_recording_id"],
                    "start_sample": str(source_start_second * 16000),
                    "duration_samples": "16000",
                    "split": "board_test",
                    "annotation_status": "source_label",
                    "mixed_species": row["mixed_species"],
                    "leakage_check": "unknown",
                    "pcm_sha256": row["pcm_sha256"],
                    "wav_sha256": row["wav_sha256"],
                }
            )
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(selected)
    report = {
        "manifest": str(output),
        "samples": len(selected),
        "samples_per_class": args.per_class,
        "annotation_policy": "source-label",
        "scientific_metrics_valid": False,
        "limitations": [
            "DB3V focal source labels were not manually re-verified",
            "mixed_species is unknown",
            "training/support leakage was not re-audited for this legacy corpus",
        ],
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
