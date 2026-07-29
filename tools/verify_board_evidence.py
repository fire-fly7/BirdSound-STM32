#!/usr/bin/env python3
"""Verify completeness and consistency of an STM32 board benchmark run."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from run_board_benchmark import (
    BenchmarkError,
    PARITY_MAX_LSB_ERROR,
    PARITY_REFERENCE,
    PARITY_REFERENCE_RESOLVER,
    PARITY_REFERENCE_RUNTIME,
    parity_metrics,
    prediction_metrics,
)


REQUIRED_MODEL_FILES = (
    "flash.log",
    "info.log",
    "info.json",
    "parity.log",
    "parity_predictions.csv",
    "audio_sweep.log",
    "predictions.csv",
    "status.json",
)


class EvidenceError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument(
        "--expected-models",
        type=int,
        help="expected number of models in this run (defaults to run_config.json)",
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--hashes-output", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise EvidenceError(f"expected a JSON object: {path}")
    return value


def load_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            return list(csv.DictReader(stream))
    except OSError as exc:
        raise EvidenceError(f"cannot read CSV {path}: {exc}") from exc


def almost_equal(actual: str, expected: Any, field: str, chain_id: str) -> None:
    try:
        actual_value = float(actual)
        expected_value = float(expected)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(
            f"{chain_id}: invalid numeric summary field {field}"
        ) from exc
    if abs(actual_value - expected_value) > 1.0e-12:
        raise EvidenceError(
            f"{chain_id}: summary {field}={actual_value} does not match "
            f"predictions {expected_value}"
        )


def write_hashes(path: Path, run: Path, files: list[Path]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=("path", "bytes", "sha256"))
        writer.writeheader()
        for item in sorted(set(files)):
            writer.writerow(
                {
                    "path": item.relative_to(run).as_posix(),
                    "bytes": item.stat().st_size,
                    "sha256": sha256_file(item),
                }
            )


def main() -> int:
    args = parse_args()
    run = args.run.resolve()
    pack = args.pack.resolve()
    if args.expected_models is not None and args.expected_models <= 0:
        raise SystemExit("--expected-models must be positive")
    try:
        config = load_json(run / "run_config.json")
        validation = load_json(run / "testset_validation.json")
        provenance = load_json(pack / "provenance.json")
        pack_rows = load_csv(pack / "INDEX.csv")
        summary_rows = load_csv(run / "summary.csv")
        configured_ids = config.get("models")
        if not isinstance(configured_ids, list) or not configured_ids:
            raise EvidenceError("run_config models must be a non-empty list")
        if not all(isinstance(chain_id, str) and chain_id for chain_id in configured_ids):
            raise EvidenceError("run_config models contains an invalid chain_id")
        if len(set(configured_ids)) != len(configured_ids):
            raise EvidenceError("run_config models contains duplicate chain_id values")
        expected_count = (
            args.expected_models
            if args.expected_models is not None
            else len(configured_ids)
        )
        if len(configured_ids) != expected_count:
            raise EvidenceError(
                f"run_config has {len(configured_ids)} models, expected "
                f"{expected_count}"
            )
        if len(summary_rows) != expected_count:
            raise EvidenceError(
                f"summary has {len(summary_rows)} models, expected "
                f"{expected_count}"
            )
        pack_by_id = {row["chain_id"]: row for row in pack_rows}
        if len(pack_by_id) != len(pack_rows):
            raise EvidenceError("pack INDEX.csv contains duplicate chain_id values")
        missing_from_pack = [
            chain_id for chain_id in configured_ids if chain_id not in pack_by_id
        ]
        if missing_from_pack:
            raise EvidenceError(
                "run_config model IDs are missing from pack INDEX.csv: "
                + ", ".join(missing_from_pack)
            )
        summary_by_id = {row["chain_id"]: row for row in summary_rows}
        if len(summary_by_id) != len(summary_rows):
            raise EvidenceError("summary.csv contains duplicate chain_id values")
        configured_set = set(configured_ids)
        expected_ids = [
            row["chain_id"]
            for row in pack_rows
            if row["chain_id"] in configured_set
        ]
        if configured_ids != expected_ids:
            raise EvidenceError(
                "run_config model order does not match its selection from pack INDEX.csv"
            )
        if set(summary_by_id) != configured_set:
            raise EvidenceError("summary model IDs do not match run_config models")
        if config.get("pack_index_sha256") != sha256_file(pack / "INDEX.csv"):
            raise EvidenceError("run_config pack index SHA-256 does not match the pack")
        if not config.get("parity"):
            raise EvidenceError("evidence run disabled LiteRT/TFLM parity")
        if config.get("parity_reference") != PARITY_REFERENCE:
            raise EvidenceError("run_config parity reference is not exactly pinned")
        samples = int(config.get("samples", 0))
        if samples <= 0:
            raise EvidenceError("run_config samples must be positive")

        checked_files = [
            run / "run_config.json",
            run / "testset_validation.json",
            run / "label_map.json",
            run / "selected_manifest.csv",
            run / "summary.csv",
        ]
        arena_used: list[int] = []
        arena_sizes: list[int] = []
        frontend_us: list[float] = []
        inference_us: list[float] = []
        accuracies: list[float] = []
        macro_f1_values: list[float] = []
        parity_lsb: list[int] = []
        groups: Counter[str] = Counter()
        features: Counter[str] = Counter()
        activations: Counter[str] = Counter()
        total_parity_mismatches = 0
        total_parity_comparisons = 0
        total_predictions = 0
        for chain_id in expected_ids:
            model = pack_by_id[chain_id]
            summary = summary_by_id[chain_id]
            model_dir = run / "models" / chain_id
            paths = [model_dir / name for name in REQUIRED_MODEL_FILES]
            missing = [path.name for path in paths if not path.is_file()]
            if missing:
                raise EvidenceError(
                    f"{chain_id}: missing evidence files: {', '.join(missing)}"
                )
            checked_files.extend(paths)
            if summary.get("status") != "complete":
                raise EvidenceError(
                    f"{chain_id}: summary status is {summary.get('status')!r}"
                )
            for field, expected in (
                ("group", model["group"]),
                ("feature", model["feature"]),
                ("activation", model["activation"]),
                ("model_sha256", model["model_sha256"]),
            ):
                if summary.get(field) != expected:
                    raise EvidenceError(
                        f"{chain_id}: summary {field}={summary.get(field)!r}, "
                        f"expected {expected!r}"
                    )
            status = load_json(model_dir / "status.json")
            if status.get("status") != "complete":
                raise EvidenceError(
                    f"{chain_id}: status.json is {status.get('status')!r}"
                )
            if "** Verified OK **" not in (model_dir / "flash.log").read_text(
                encoding="utf-8", errors="replace"
            ):
                raise EvidenceError(f"{chain_id}: flash.log has no Verified OK marker")
            info = load_json(model_dir / "info.json")
            for field, expected in (
                ("model_sha256", model["model_sha256"]),
                ("feature", model["feature"].upper()),
                ("activation", model["activation"].lower()),
            ):
                actual = str(info.get(field, ""))
                if actual.lower() != str(expected).lower():
                    raise EvidenceError(
                        f"{chain_id}: board {field}={actual!r}, expected {expected!r}"
                    )
            if info.get("model_status") != 0:
                raise EvidenceError(
                    f"{chain_id}: board model_status={info.get('model_status')!r}"
                )
            used = int(info.get("arena_used", 0))
            size = int(info.get("arena_bytes", 0))
            if used <= 0 or used > size:
                raise EvidenceError(
                    f"{chain_id}: invalid Arena usage {used}/{size}"
                )
            if summary.get("tensor_arena_used") != str(used):
                raise EvidenceError(f"{chain_id}: summary Arena usage does not match info")
            if summary.get("tensor_arena_size") != str(size):
                raise EvidenceError(f"{chain_id}: summary Arena size does not match info")
            arena_used.append(used)
            arena_sizes.append(size)

            parity = parity_metrics(model_dir / "parity_predictions.csv")
            if parity["reference_comparisons"] != 10 or not parity["passed"]:
                raise EvidenceError(f"{chain_id}: parity evidence did not pass")
            for field, expected in (
                ("parity_reference_comparisons", parity["reference_comparisons"]),
                ("parity_prediction_mismatches", parity["prediction_mismatches"]),
                ("parity_max_lsb_error", parity["max_lsb_error"]),
                (
                    "parity_f32_vs_native_max_lsb_error",
                    parity["f32_vs_native_max_lsb_error"],
                ),
            ):
                if summary.get(field) != str(expected):
                    raise EvidenceError(
                        f"{chain_id}: summary {field} does not match parity evidence"
                    )
            parity_lsb.append(int(parity["max_lsb_error"]))
            total_parity_mismatches += int(parity["prediction_mismatches"])
            total_parity_comparisons += int(parity["reference_comparisons"])

            predictions = prediction_metrics(model_dir / "predictions.csv")
            if predictions["samples"] != samples:
                raise EvidenceError(
                    f"{chain_id}: {predictions['samples']} predictions, expected {samples}"
                )
            for field in (
                "samples",
                "correct",
                "accuracy",
                "balanced_accuracy",
                "macro_f1",
                "frontend_elapsed_us_median",
                "inference_elapsed_us_median",
            ):
                almost_equal(summary[field], predictions[field], field, chain_id)
            total_predictions += int(predictions["samples"])
            frontend_us.append(float(predictions["frontend_elapsed_us_median"]))
            inference_us.append(float(predictions["inference_elapsed_us_median"]))
            accuracies.append(float(predictions["accuracy"]))
            macro_f1_values.append(float(predictions["macro_f1"]))
            groups[model["group"]] += 1
            features[model["feature"].upper()] += 1
            activations[model["activation"].lower()] += 1

        report = {
            "schema_version": 1,
            "passed": True,
            "models": len(expected_ids),
            "pack_models": len(pack_rows),
            "complete_pack": len(expected_ids) == len(pack_rows),
            "model_status_counts": {"complete": len(expected_ids)},
            "groups": dict(sorted(groups.items())),
            "features": dict(sorted(features.items())),
            "activations": dict(sorted(activations.items())),
            "firmware_provenance": {
                key: provenance.get(key)
                for key in (
                    "firmware_source_commit",
                    "firmware_source_tree",
                    "firmware_source_dirty",
                    "firmware_build_inputs_sha256",
                    "model_train_commit",
                    "model_train_dirty",
                    "submodules",
                    "toolchain",
                )
            },
            "testset": {
                "annotation_policy": validation.get("annotation_policy"),
                "scientific_metrics_valid": validation.get(
                    "scientific_metrics_valid"
                ),
                "samples_per_model": samples,
                "manifest_sha256": validation.get("manifest_sha256"),
            },
            "flash": {
                "attempted": len(expected_ids),
                "verified_ok": len(expected_ids),
                "failed": 0,
            },
            "parity": {
                "reference_runtime": PARITY_REFERENCE_RUNTIME,
                "reference_resolver": PARITY_REFERENCE_RESOLVER,
                "comparisons": total_parity_comparisons,
                "prediction_mismatches": total_parity_mismatches,
                "max_lsb_error": max(parity_lsb),
                "max_lsb_error_limit": PARITY_MAX_LSB_ERROR,
            },
            "raw_audio": {
                "predictions": total_predictions,
                "accuracy_min": min(accuracies),
                "accuracy_median": statistics.median(accuracies),
                "accuracy_max": max(accuracies),
                "macro_f1_min": min(macro_f1_values),
                "macro_f1_median": statistics.median(macro_f1_values),
                "macro_f1_max": max(macro_f1_values),
            },
            "latency_us_median_per_model": {
                "frontend_min": min(frontend_us),
                "frontend_median": statistics.median(frontend_us),
                "frontend_max": max(frontend_us),
                "inference_min": min(inference_us),
                "inference_median": statistics.median(inference_us),
                "inference_max": max(inference_us),
            },
            "arena_used_bytes": {
                "min": min(arena_used),
                "median": statistics.median(arena_used),
                "max": max(arena_used),
                "configured": (
                    arena_sizes[0]
                    if len(set(arena_sizes)) == 1
                    else sorted(set(arena_sizes))
                ),
            },
            "checked_evidence_files": len(set(checked_files)),
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.hashes_output is not None:
            write_hashes(args.hashes_output.resolve(), run, checked_files)
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0
    except (BenchmarkError, EvidenceError, OSError, KeyError, ValueError) as exc:
        print(f"board evidence verification error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
