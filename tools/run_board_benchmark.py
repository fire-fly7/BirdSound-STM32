#!/usr/bin/env python3
"""Validate a raw-WAV test set and benchmark packaged models on STM32."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import struct
import subprocess
import sys
import time
import wave
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


EXPECTED_LABEL_MAP = {
    "Agelaius_phoeniceus": 0,
    "Cardinalis_cardinalis": 1,
    "Certhia_americana": 2,
    "Corvus_brachyrhynchos": 3,
    "Setophaga_aestiva": 4,
    "Setophaga_ruticilla": 5,
    "Spinus_tristis": 6,
    "Turdus_migratorius": 7,
}
EXPECTED_LABELS = tuple(
    name for name, _ in sorted(EXPECTED_LABEL_MAP.items(), key=lambda item: item[1])
)
REQUIRED_MANIFEST_FIELDS = (
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
SAMPLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
PARITY_MAX_LSB_ERROR = 2


class BenchmarkError(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def default_pack() -> Path:
    if (PROJECT_ROOT / "INDEX.csv").is_file():
        return PROJECT_ROOT
    firmware_dir = PROJECT_ROOT / "firmware"
    candidates = tuple(
        path
        for path in firmware_dir.glob("STM32_deploy_raw_audio_experiment_pack_*")
        if path.is_dir() and (path / "INDEX.csv").is_file()
    )
    if candidates:
        return max(candidates, key=lambda path: path.stat().st_mtime)
    return firmware_dir / "STM32_deploy_raw_audio_experiment_pack_<commit>"


def add_testset_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--testset",
        type=Path,
        default=PROJECT_ROOT / "board_testset",
        help="test-set root containing manifest.csv, label_map.json, and audio/",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="manifest path (default: TESTSET/manifest.csv)",
    )
    parser.add_argument("--start", type=int, default=0)
    parser.add_argument("--stride", type=int, default=1)
    parser.add_argument(
        "--count",
        type=int,
        default=0,
        help="selected rows after start/stride; 0 selects all remaining rows",
    )
    parser.add_argument(
        "--annotation-policy",
        choices=("strict", "source-label"),
        default="strict",
        help=(
            "strict requires manual verification/no mixed species/leakage passed; "
            "source-label permits transparent preliminary transport benchmarks"
        ),
    )


def add_model_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--pack", type=Path, default=default_pack())
    parser.add_argument(
        "--scope",
        choices=("all", "core"),
        default="all",
        help="all 57 packaged models or the curated core subset",
    )
    parser.add_argument(
        "--chain",
        action="append",
        default=[],
        help="exact chain_id; may be repeated",
    )
    parser.add_argument(
        "--group",
        action="append",
        default=[],
        help="exact INDEX.csv group; may be repeated",
    )
    parser.add_argument(
        "--feature",
        action="append",
        choices=("MFCC", "LOGMEL", "PCEN"),
        default=[],
    )
    parser.add_argument(
        "--activation",
        action="append",
        choices=("softmax", "sigmoid"),
        default=[],
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)

    validate = subparsers.add_parser(
        "validate-testset",
        help="strictly validate manifest, label map, WAV format, and hashes",
    )
    add_testset_arguments(validate)
    validate.add_argument(
        "--report",
        type=Path,
        help="optional JSON validation report",
    )

    list_models = subparsers.add_parser(
        "list-models",
        help="list models selected from a firmware package INDEX.csv",
    )
    add_model_arguments(list_models)
    list_models.add_argument("--json", action="store_true")

    run = subparsers.add_parser(
        "run",
        help="flash selected models, stream raw WAVs, and write benchmark results",
    )
    add_testset_arguments(run)
    add_model_arguments(run)
    run.add_argument("--port", default="/dev/ttyACM0")
    run.add_argument("--baud", type=int, default=115200)
    run.add_argument("--timeout", type=float, default=12.0)
    run.add_argument("--serial-wait", type=float, default=30.0)
    run.add_argument("--chunk-samples", type=int, default=2048)
    run.add_argument(
        "--results",
        type=Path,
        default=PROJECT_ROOT / "board_results",
    )
    run.add_argument("--run-id", default="all_models")
    run.add_argument(
        "--resume",
        action="store_true",
        help="skip models already marked complete in a matching run",
    )
    run.add_argument(
        "--continue-on-error",
        action="store_true",
        help="record a failed model and continue with the next firmware",
    )
    run.add_argument(
        "--no-flash",
        action="store_true",
        help="use the already-loaded board model; requires exactly one selected chain",
    )
    run.add_argument("--openocd", default="openocd")
    run.add_argument("--flash-config", type=Path)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="validate everything and print the plan without touching the board",
    )
    run.add_argument(
        "--skip-parity",
        action="store_true",
        help="skip generated-tensor LiteRT/TFLM parity (not recommended for evidence runs)",
    )
    return parser.parse_args()


def resolve_manifest(testset: Path, manifest: Path | None) -> tuple[Path, Path]:
    root = testset.resolve()
    path = (manifest if manifest is not None else root / "manifest.csv").resolve()
    if not root.is_dir():
        raise BenchmarkError(f"test-set directory does not exist: {root}")
    if not path.is_file():
        raise BenchmarkError(f"manifest does not exist: {path}")
    return root, path


def load_label_map(root: Path) -> dict[str, int]:
    path = root / "label_map.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BenchmarkError(f"cannot read {path}: {exc}") from exc
    if value != EXPECTED_LABEL_MAP:
        raise BenchmarkError(
            f"{path} must exactly match the firmware label order: "
            f"{json.dumps(EXPECTED_LABEL_MAP, ensure_ascii=False)}"
        )
    return value


def safe_audio_path(root: Path, raw_value: str, row_number: int) -> Path:
    relative = Path(raw_value)
    if relative.is_absolute() or "\\" in raw_value:
        raise BenchmarkError(
            f"manifest row {row_number}: file must be a POSIX-style relative path"
        )
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise BenchmarkError(
            f"manifest row {row_number}: file escapes test-set root: {raw_value}"
        ) from exc
    if not path.is_file():
        raise BenchmarkError(
            f"manifest row {row_number}: WAV does not exist: {raw_value}"
        )
    return path


def validate_audio(
    path: Path,
    row: dict[str, str],
    row_number: int,
) -> tuple[int, float]:
    try:
        with wave.open(str(path), "rb") as wav:
            actual = (
                wav.getnchannels(),
                wav.getsampwidth(),
                wav.getframerate(),
                wav.getnframes(),
                wav.getcomptype(),
            )
            expected = (1, 2, 16000, 16000, "NONE")
            if actual != expected:
                raise BenchmarkError(
                    f"manifest row {row_number}: {row['file']} WAV parameters "
                    f"{actual!r}, expected {expected!r}"
                )
            pcm = wav.readframes(wav.getnframes())
    except (OSError, EOFError, wave.Error) as exc:
        raise BenchmarkError(
            f"manifest row {row_number}: cannot read {row['file']}: {exc}"
        ) from exc
    if len(pcm) != 32000:
        raise BenchmarkError(
            f"manifest row {row_number}: {row['file']} PCM payload is "
            f"{len(pcm)} bytes, expected 32000"
        )
    wav_hash = sha256_file(path)
    pcm_hash = hashlib.sha256(pcm).hexdigest()
    if row["wav_sha256"] != wav_hash:
        raise BenchmarkError(
            f"manifest row {row_number}: WAV SHA-256 mismatch for {row['file']}"
        )
    if row["pcm_sha256"] != pcm_hash:
        raise BenchmarkError(
            f"manifest row {row_number}: PCM SHA-256 mismatch for {row['file']}"
        )
    samples = struct.unpack("<16000h", pcm)
    peak = max(abs(value) for value in samples)
    rms = math.sqrt(sum(value * value for value in samples) / len(samples))
    if peak == 0:
        raise BenchmarkError(
            f"manifest row {row_number}: {row['file']} contains digital silence"
        )
    return peak, rms


def validate_testset(
    testset: Path,
    manifest: Path | None,
    annotation_policy: str = "strict",
) -> tuple[dict[str, Any], list[dict[str, str]], tuple[str, ...], Path, Path]:
    root, manifest_path = resolve_manifest(testset, manifest)
    load_label_map(root)
    try:
        with manifest_path.open("r", encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            fieldnames = tuple(reader.fieldnames or ())
            rows = list(reader)
    except OSError as exc:
        raise BenchmarkError(f"cannot read {manifest_path}: {exc}") from exc
    missing_fields = [
        field for field in REQUIRED_MANIFEST_FIELDS if field not in fieldnames
    ]
    if missing_fields:
        raise BenchmarkError(
            f"manifest is missing required columns: {', '.join(missing_fields)}"
        )
    if not rows:
        raise BenchmarkError("manifest contains no samples")

    sample_ids: set[str] = set()
    files: set[str] = set()
    source_windows: set[tuple[str, str, int]] = set()
    source_counts: Counter[tuple[str, str]] = Counter()
    class_counts: Counter[int] = Counter()
    warning_samples: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        row_number = index + 2
        sample_id = row["sample_id"].strip()
        if not SAMPLE_ID_RE.fullmatch(sample_id):
            raise BenchmarkError(
                f"manifest row {row_number}: invalid sample_id {sample_id!r}"
            )
        if sample_id in sample_ids:
            raise BenchmarkError(
                f"manifest row {row_number}: duplicate sample_id {sample_id!r}"
            )
        sample_ids.add(sample_id)
        if row["file"] in files:
            raise BenchmarkError(
                f"manifest row {row_number}: duplicate file {row['file']!r}"
            )
        files.add(row["file"])
        try:
            label = int(row["label"])
            start_sample = int(row["start_sample"])
            duration_samples = int(row["duration_samples"])
        except ValueError as exc:
            raise BenchmarkError(
                f"manifest row {row_number}: label/start/duration must be integers"
            ) from exc
        if label not in range(len(EXPECTED_LABELS)):
            raise BenchmarkError(
                f"manifest row {row_number}: label {label} is outside 0..7"
            )
        if row["species"] != EXPECTED_LABELS[label]:
            raise BenchmarkError(
                f"manifest row {row_number}: species {row['species']!r} does not "
                f"match label {label} ({EXPECTED_LABELS[label]})"
            )
        if start_sample < 0 or duration_samples != 16000:
            raise BenchmarkError(
                f"manifest row {row_number}: start_sample must be nonnegative and "
                "duration_samples must be 16000"
            )
        if row["split"] != "board_test":
            raise BenchmarkError(
                f"manifest row {row_number}: split must be 'board_test'"
            )
        if annotation_policy == "strict":
            if row["annotation_status"] != "verified":
                raise BenchmarkError(
                    f"manifest row {row_number}: annotation_status must be 'verified'"
                )
            if row["mixed_species"] != "none":
                raise BenchmarkError(
                    f"manifest row {row_number}: mixed_species must be 'none'"
                )
            if row["leakage_check"] != "passed":
                raise BenchmarkError(
                    f"manifest row {row_number}: leakage_check must be 'passed'"
                )
        else:
            if row["annotation_status"] not in {
                "verified",
                "source_label",
                "unreviewed",
            }:
                raise BenchmarkError(
                    f"manifest row {row_number}: invalid source-label "
                    f"annotation_status {row['annotation_status']!r}"
                )
            if row["mixed_species"] not in {"none", "unknown"}:
                raise BenchmarkError(
                    f"manifest row {row_number}: invalid mixed_species "
                    f"{row['mixed_species']!r}"
                )
            if row["leakage_check"] not in {"passed", "unknown"}:
                raise BenchmarkError(
                    f"manifest row {row_number}: invalid leakage_check "
                    f"{row['leakage_check']!r}"
                )
        for hash_field in ("pcm_sha256", "wav_sha256"):
            if not SHA256_RE.fullmatch(row[hash_field]):
                raise BenchmarkError(
                    f"manifest row {row_number}: {hash_field} must be lowercase SHA-256"
                )
        if not row["source_dataset"] or not row["source_recording_id"]:
            raise BenchmarkError(
                f"manifest row {row_number}: source lineage fields cannot be empty"
            )
        source_window = (
            row["source_dataset"],
            row["source_recording_id"],
            start_sample,
        )
        if source_window in source_windows:
            raise BenchmarkError(
                f"manifest row {row_number}: duplicate source window {source_window!r}"
            )
        source_windows.add(source_window)
        source_key = (row["source_dataset"], row["source_recording_id"])
        source_counts[source_key] += 1
        class_counts[label] += 1
        path = safe_audio_path(root, row["file"], row_number)
        peak, rms = validate_audio(path, row, row_number)
        if rms < 32.0:
            warning_samples.append(
                {
                    "sample_id": sample_id,
                    "warning": "very_low_rms",
                    "peak": peak,
                    "rms": round(rms, 3),
                }
            )

    if set(class_counts) != set(range(8)) or len(set(class_counts.values())) != 1:
        raise BenchmarkError(
            f"manifest must be class-balanced; counts={dict(sorted(class_counts.items()))}"
        )
    if len(rows) % 8 != 0:
        raise BenchmarkError("manifest row count must be a multiple of 8")
    for block_start in range(0, len(rows), 8):
        labels = sorted(int(row["label"]) for row in rows[block_start : block_start + 8])
        if labels != list(range(8)):
            raise BenchmarkError(
                f"manifest rows {block_start + 2}..{block_start + 9} must contain "
                "exactly one sample from each label 0..7"
            )
    reused_sources = sum(count > 1 for count in source_counts.values())
    report = {
        "schema_version": 1,
        "valid": True,
        "annotation_policy": annotation_policy,
        "scientific_metrics_valid": annotation_policy == "strict",
        "testset": str(root),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "samples": len(rows),
        "classes": len(class_counts),
        "class_counts": {
            EXPECTED_LABELS[label]: class_counts[label] for label in range(8)
        },
        "source_recordings": len(source_counts),
        "source_recordings_with_multiple_windows": reused_sources,
        "wav_spec": {
            "encoding": "PCM16 little-endian signed",
            "sample_rate": 16000,
            "channels": 1,
            "frames": 16000,
            "pcm_bytes": 32000,
        },
        "low_rms_warnings": warning_samples,
    }
    return report, rows, fieldnames, root, manifest_path


def select_rows(
    rows: list[dict[str, str]],
    start: int,
    stride: int,
    count: int,
) -> list[dict[str, str]]:
    if start < 0 or start >= len(rows):
        raise BenchmarkError(f"--start must be in 0..{len(rows) - 1}")
    if stride <= 0:
        raise BenchmarkError("--stride must be positive")
    if count < 0:
        raise BenchmarkError("--count cannot be negative")
    selected = rows[start::stride]
    if count:
        selected = selected[:count]
    if not selected:
        raise BenchmarkError("sample selection is empty")
    return selected


def load_models(pack: Path) -> tuple[Path, list[dict[str, str]]]:
    root = pack.resolve()
    index_path = root / "INDEX.csv"
    if not index_path.is_file():
        raise BenchmarkError(f"firmware package INDEX.csv does not exist: {index_path}")
    try:
        with index_path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise BenchmarkError(f"cannot read {index_path}: {exc}") from exc
    required = {
        "chain_id",
        "group",
        "core_experiment",
        "feature",
        "activation",
        "model_sha256",
        "hex_path",
    }
    if not rows or not required.issubset(rows[0]):
        raise BenchmarkError("firmware INDEX.csv is empty or missing required columns")
    seen: set[str] = set()
    for row in rows:
        chain_id = row["chain_id"]
        if not chain_id or chain_id in seen:
            raise BenchmarkError(f"invalid or duplicate chain_id {chain_id!r}")
        seen.add(chain_id)
        firmware = (root / row["hex_path"]).resolve()
        try:
            firmware.relative_to(root)
        except ValueError as exc:
            raise BenchmarkError(
                f"firmware path escapes package: {row['hex_path']}"
            ) from exc
        if not firmware.is_file():
            raise BenchmarkError(f"firmware does not exist: {firmware}")
        if not SHA256_RE.fullmatch(row["model_sha256"]):
            raise BenchmarkError(f"invalid model SHA-256 for {chain_id}")
    return root, rows


def select_models(args: argparse.Namespace) -> tuple[Path, list[dict[str, str]]]:
    pack, rows = load_models(args.pack)
    known_chains = {row["chain_id"] for row in rows}
    missing_chains = set(args.chain) - known_chains
    if missing_chains:
        raise BenchmarkError(f"unknown chain_id values: {sorted(missing_chains)}")
    selected = []
    for row in rows:
        if args.scope == "core" and row["core_experiment"] != "True":
            continue
        if args.chain and row["chain_id"] not in args.chain:
            continue
        if args.group and row["group"] not in args.group:
            continue
        if args.feature and row["feature"].upper() not in args.feature:
            continue
        if args.activation and row["activation"] not in args.activation:
            continue
        selected.append(row)
    if not selected:
        raise BenchmarkError("model selection is empty")
    return pack, selected


def write_selected_manifest(
    path: Path,
    rows: list[dict[str, str]],
    fieldnames: tuple[str, ...],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_logged(command: list[str], log_path: Path, prefix: str) -> int:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + " ".join(command) + "\n")
        log.flush()
        process = subprocess.Popen(
            command,
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(f"[{prefix}] {line}", end="", flush=True)
            log.write(line)
            log.flush()
        return process.wait()


def wait_for_board_info(
    command: list[str],
    wait_seconds: float,
    attempt_timeout: float,
    log_path: Path,
) -> dict[str, Any]:
    if wait_seconds <= 0:
        raise BenchmarkError("--serial-wait must be positive")
    deadline = time.monotonic() + wait_seconds
    attempts: list[str] = []
    while True:
        try:
            result = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                check=False,
                text=True,
                encoding="utf-8",
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=max(attempt_timeout + 2.0, 5.0),
            )
            attempts.append(
                f"$ {' '.join(command)}\nexit={result.returncode}\n{result.stdout}\n"
            )
            if result.returncode == 0:
                try:
                    value = json.loads(result.stdout)
                except json.JSONDecodeError:
                    value = None
                if isinstance(value, dict):
                    log_path.parent.mkdir(parents=True, exist_ok=True)
                    log_path.write_text("\n".join(attempts), encoding="utf-8")
                    return value
        except subprocess.TimeoutExpired as exc:
            attempts.append(f"$ {' '.join(command)}\ntimeout={exc}\n")
        if time.monotonic() >= deadline:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text("\n".join(attempts), encoding="utf-8")
            raise BenchmarkError(
                f"board did not return valid INFO within {wait_seconds:.1f} seconds"
            )
        time.sleep(0.5)


def validate_board_info(info: dict[str, Any], model: dict[str, str]) -> None:
    if info.get("model_status") != 0:
        raise BenchmarkError(f"board model_status is {info.get('model_status')!r}")
    if info.get("model_sha256") != model["model_sha256"]:
        raise BenchmarkError(
            f"board model SHA-256 {info.get('model_sha256')!r} does not match "
            f"INDEX.csv {model['model_sha256']!r}"
        )
    if str(info.get("feature", "")).upper() != model["feature"].upper():
        raise BenchmarkError(
            f"board feature {info.get('feature')!r} does not match {model['feature']!r}"
        )
    if str(info.get("activation", "")).lower() != model["activation"].lower():
        raise BenchmarkError(
            f"board activation {info.get('activation')!r} does not match "
            f"{model['activation']!r}"
        )
    if tuple(info.get("labels", ())) != EXPECTED_LABELS:
        raise BenchmarkError("board label order does not match the benchmark label map")


def prediction_metrics(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise BenchmarkError(f"cannot read predictions {path}: {exc}") from exc
    if not rows:
        raise BenchmarkError(f"predictions file is empty: {path}")
    confusion = [[0 for _ in range(8)] for _ in range(8)]
    frontend_times: list[int] = []
    inference_times: list[int] = []
    for index, row in enumerate(rows, start=2):
        try:
            expected = int(row["expected_label"])
            predicted = int(row["predicted_index"])
            frontend_times.append(int(row["frontend_elapsed_us"]))
            inference_times.append(int(row["inference_elapsed_us"]))
        except (KeyError, ValueError) as exc:
            raise BenchmarkError(
                f"invalid prediction row {index} in {path}"
            ) from exc
        if expected not in range(8) or predicted not in range(8):
            raise BenchmarkError(f"prediction row {index} has an invalid class index")
        confusion[expected][predicted] += 1
    correct = sum(confusion[label][label] for label in range(8))
    recalls: list[float] = []
    f1_values: list[float] = []
    for label in range(8):
        true_positive = confusion[label][label]
        false_negative = sum(confusion[label]) - true_positive
        false_positive = (
            sum(confusion[expected][label] for expected in range(8)) - true_positive
        )
        recall_denominator = true_positive + false_negative
        recalls.append(
            true_positive / recall_denominator if recall_denominator else 0.0
        )
        f1_denominator = 2 * true_positive + false_positive + false_negative
        f1_values.append(
            2 * true_positive / f1_denominator if f1_denominator else 0.0
        )
    return {
        "samples": len(rows),
        "correct": correct,
        "accuracy": correct / len(rows),
        "balanced_accuracy": statistics.mean(recalls),
        "macro_f1": statistics.mean(f1_values),
        "frontend_elapsed_us_median": statistics.median(frontend_times),
        "inference_elapsed_us_median": statistics.median(inference_times),
        "confusion_matrix": confusion,
    }


def parity_metrics(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise BenchmarkError(f"cannot read parity predictions {path}: {exc}") from exc
    if not rows:
        raise BenchmarkError(f"parity predictions file is empty: {path}")
    maximum = 0
    prediction_mismatches = 0
    by_sample: dict[int, dict[str, list[int]]] = {}
    for number, row in enumerate(rows, start=2):
        try:
            sample_index = int(row["sample_index"])
            mode = row["mode"]
            board = [int(value) for value in json.loads(row["raw_output_int8"])]
            reference = [
                int(value) for value in json.loads(row["reference_raw_int8"])
            ]
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise BenchmarkError(
                f"invalid parity row {number} in {path}"
            ) from exc
        if mode not in {"f32", "native"} or len(board) != 8 or len(reference) != 8:
            raise BenchmarkError(f"invalid parity payload at row {number} in {path}")
        maximum = max(
            maximum,
            max(abs(actual - expected) for actual, expected in zip(board, reference)),
        )
        board_argmax = max(range(8), key=board.__getitem__)
        reference_argmax = max(range(8), key=reference.__getitem__)
        prediction_mismatches += int(board_argmax != reference_argmax)
        by_sample.setdefault(sample_index, {})[mode] = board
    cross_mode_maximum = 0
    cross_mode_mismatches = 0
    for sample_index, modes in by_sample.items():
        if set(modes) != {"f32", "native"}:
            raise BenchmarkError(
                f"parity sample {sample_index} does not contain both wire modes"
            )
        f32_values = modes["f32"]
        native_values = modes["native"]
        cross_mode_maximum = max(
            cross_mode_maximum,
            max(
                abs(f32_value - native_value)
                for f32_value, native_value in zip(f32_values, native_values)
            ),
        )
        cross_mode_mismatches += int(
            max(range(8), key=f32_values.__getitem__)
            != max(range(8), key=native_values.__getitem__)
        )
    return {
        "generated_tensors": len(by_sample),
        "reference_comparisons": len(rows),
        "prediction_mismatches": prediction_mismatches,
        "max_lsb_error": maximum,
        "max_lsb_error_limit": PARITY_MAX_LSB_ERROR,
        "f32_vs_native_prediction_mismatches": cross_mode_mismatches,
        "f32_vs_native_max_lsb_error": cross_mode_maximum,
        "passed": (
            prediction_mismatches == 0
            and maximum <= PARITY_MAX_LSB_ERROR
            and cross_mode_mismatches == 0
            and cross_mode_maximum == 0
        ),
    }


SUMMARY_FIELDS = (
    "chain_id",
    "status",
    "group",
    "feature",
    "activation",
    "model_sha256",
    "samples",
    "correct",
    "accuracy",
    "balanced_accuracy",
    "macro_f1",
    "frontend_elapsed_us_median",
    "inference_elapsed_us_median",
    "tensor_arena_used",
    "tensor_arena_size",
    "parity_reference_comparisons",
    "parity_prediction_mismatches",
    "parity_max_lsb_error",
    "parity_f32_vs_native_max_lsb_error",
    "error",
)


def write_summary(
    run_dir: Path,
    models: list[dict[str, str]],
) -> None:
    rows: list[dict[str, Any]] = []
    for model in models:
        status_path = run_dir / "models" / model["chain_id"] / "status.json"
        status: dict[str, Any] = {}
        if status_path.is_file():
            try:
                value = json.loads(status_path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    status = value
            except (OSError, json.JSONDecodeError):
                status = {"status": "invalid_status", "error": str(status_path)}
        metrics = status.get("metrics")
        if not isinstance(metrics, dict):
            metrics = {}
        parity = metrics.get("parity")
        if not isinstance(parity, dict):
            parity = {}
        info: dict[str, Any] = {}
        info_path = status_path.parent / "info.json"
        if info_path.is_file():
            try:
                value = json.loads(info_path.read_text(encoding="utf-8"))
                if isinstance(value, dict):
                    info = value
            except (OSError, json.JSONDecodeError):
                info = {}
        rows.append(
            {
                "chain_id": model["chain_id"],
                "status": status.get("status", "pending"),
                "group": model["group"],
                "feature": model["feature"],
                "activation": model["activation"],
                "model_sha256": model["model_sha256"],
                "samples": metrics.get("samples", ""),
                "correct": metrics.get("correct", ""),
                "accuracy": metrics.get("accuracy", ""),
                "balanced_accuracy": metrics.get("balanced_accuracy", ""),
                "macro_f1": metrics.get("macro_f1", ""),
                "frontend_elapsed_us_median": metrics.get(
                    "frontend_elapsed_us_median", ""
                ),
                "inference_elapsed_us_median": metrics.get(
                    "inference_elapsed_us_median", ""
                ),
                "tensor_arena_used": info.get("arena_used", ""),
                "tensor_arena_size": info.get("arena_bytes", ""),
                "parity_reference_comparisons": parity.get(
                    "reference_comparisons", ""
                ),
                "parity_prediction_mismatches": parity.get(
                    "prediction_mismatches", ""
                ),
                "parity_max_lsb_error": parity.get("max_lsb_error", ""),
                "parity_f32_vs_native_max_lsb_error": parity.get(
                    "f32_vs_native_max_lsb_error", ""
                ),
                "error": status.get("error", ""),
            }
        )
    with (run_dir / "summary.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.DictWriter(stream, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def normalized_run_config(
    args: argparse.Namespace,
    pack: Path,
    manifest_path: Path,
    selected_rows: list[dict[str, str]],
    models: list[dict[str, str]],
) -> dict[str, Any]:
    selection_identity = [
        {
            "sample_id": row["sample_id"],
            "file": row["file"],
            "label": row["label"],
            "pcm_sha256": row["pcm_sha256"],
        }
        for row in selected_rows
    ]
    return {
        "schema_version": 1,
        "pack": str(pack),
        "pack_index_sha256": sha256_file(pack / "INDEX.csv"),
        "manifest": str(manifest_path),
        "manifest_sha256": sha256_file(manifest_path),
        "selection_sha256": sha256_json(selection_identity),
        "samples": len(selected_rows),
        "models": [model["chain_id"] for model in models],
        "annotation_policy": args.annotation_policy,
        "parity": not args.skip_parity,
        "selection": {
            "start": args.start,
            "stride": args.stride,
            "count": args.count,
        },
        "transport": {
            "port": args.port,
            "baud": args.baud,
            "timeout": args.timeout,
            "chunk_samples": args.chunk_samples,
        },
    }


def print_dry_run(
    args: argparse.Namespace,
    pack: Path,
    rows: list[dict[str, str]],
    models: list[dict[str, str]],
) -> None:
    wire_seconds = len(rows) * len(models) * 32000 * 10 / args.baud
    compute_seconds = len(rows) * len(models) * 0.55
    print(
        json.dumps(
            {
                "dry_run": True,
                "pack": str(pack),
                "models": len(models),
                "model_ids": [model["chain_id"] for model in models],
                "samples_per_model": len(rows),
                "board_runs": len(rows) * len(models),
                "generated_tensor_parity_per_model": (
                    0 if args.skip_parity else 10
                ),
                "estimated_hours": round((wire_seconds + compute_seconds) / 3600, 3),
                "results": str((args.results / args.run_id).resolve()),
                "no_flash": args.no_flash,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def run_one_model(
    args: argparse.Namespace,
    pack: Path,
    testset: Path,
    selected_manifest: Path,
    run_dir: Path,
    model: dict[str, str],
) -> dict[str, Any]:
    chain_id = model["chain_id"]
    model_dir = run_dir / "models" / chain_id
    model_dir.mkdir(parents=True, exist_ok=True)
    status_path = model_dir / "status.json"
    status: dict[str, Any] = {
        "chain_id": chain_id,
        "status": "running",
        "started_at": utc_now(),
        "model_sha256": model["model_sha256"],
    }
    write_json(status_path, status)
    flash_script = SCRIPT_DIR / "flash_experiment.py"
    serial_client = SCRIPT_DIR / "serial_model_client.py"
    firmware = pack / model["hex_path"]
    flash_config = (
        args.flash_config.resolve()
        if args.flash_config is not None
        else pack / "flash.cfg"
    )
    try:
        if not args.no_flash:
            flash_command = [
                sys.executable,
                str(flash_script),
                str(firmware),
                "--config",
                str(flash_config),
                "--openocd",
                args.openocd,
            ]
            return_code = run_logged(
                flash_command, model_dir / "flash.log", f"{chain_id}:flash"
            )
            if return_code != 0:
                raise BenchmarkError(f"flashing failed with exit code {return_code}")

        info_command = [
            sys.executable,
            str(serial_client),
            "--port",
            args.port,
            "--baud",
            str(args.baud),
            "--timeout",
            str(args.timeout),
            "info",
        ]
        info = wait_for_board_info(
            info_command,
            args.serial_wait,
            args.timeout,
            model_dir / "info.log",
        )
        validate_board_info(info, model)
        write_json(model_dir / "info.json", info)

        parity: dict[str, Any] | None = None
        if not args.skip_parity:
            tflite = firmware.parent / "model.tflite"
            if not tflite.is_file():
                raise BenchmarkError(f"desktop TFLite model does not exist: {tflite}")
            parity_predictions = model_dir / "parity_predictions.csv"
            parity_command = [
                sys.executable,
                str(serial_client),
                "--port",
                args.port,
                "--baud",
                str(args.baud),
                "--timeout",
                str(args.timeout),
                "smoke",
                "--mode",
                "both",
                "--tflite",
                str(tflite),
                "--max-lsb-error",
                str(PARITY_MAX_LSB_ERROR),
                "--output",
                str(parity_predictions),
            ]
            return_code = run_logged(
                parity_command, model_dir / "parity.log", f"{chain_id}:parity"
            )
            if return_code != 0:
                raise BenchmarkError(
                    f"LiteRT/TFLM parity failed with exit code {return_code}"
                )
            parity = parity_metrics(parity_predictions)
            if not parity["passed"]:
                raise BenchmarkError("LiteRT/TFLM parity metrics did not pass")

        predictions = model_dir / "predictions.csv"
        audio_command = [
            sys.executable,
            str(serial_client),
            "--port",
            args.port,
            "--baud",
            str(args.baud),
            "--timeout",
            str(args.timeout),
            "audio-sweep",
            "--manifest",
            str(selected_manifest),
            "--root",
            str(testset),
            "--chunk-samples",
            str(args.chunk_samples),
            "--output",
            str(predictions),
        ]
        return_code = run_logged(
            audio_command, model_dir / "audio_sweep.log", f"{chain_id}:audio"
        )
        if return_code != 0:
            raise BenchmarkError(
                f"raw-audio sweep failed with exit code {return_code}"
            )
        metrics = prediction_metrics(predictions)
        metrics["parity"] = parity
        status.update(
            {
                "status": "complete",
                "completed_at": utc_now(),
                "metrics": metrics,
            }
        )
        write_json(status_path, status)
        return status
    except (BenchmarkError, OSError, subprocess.SubprocessError) as exc:
        status.update(
            {
                "status": "failed",
                "completed_at": utc_now(),
                "error": str(exc),
            }
        )
        write_json(status_path, status)
        return status


def execute_run(args: argparse.Namespace) -> int:
    if args.baud <= 0 or args.timeout <= 0:
        raise BenchmarkError("--baud and --timeout must be positive")
    if args.chunk_samples <= 0 or args.chunk_samples > 2558:
        raise BenchmarkError("--chunk-samples must be in 1..2558")
    if not RUN_ID_RE.fullmatch(args.run_id):
        raise BenchmarkError("--run-id may contain only letters, digits, dot, dash, underscore")
    report, rows, fieldnames, testset, manifest_path = validate_testset(
        args.testset, args.manifest, args.annotation_policy
    )
    selected_rows = select_rows(rows, args.start, args.stride, args.count)
    pack, models = select_models(args)
    if args.no_flash and len(models) != 1:
        raise BenchmarkError("--no-flash requires exactly one selected model")
    if args.dry_run:
        print_dry_run(args, pack, selected_rows, models)
        return 0

    run_dir = (args.results / args.run_id).resolve()
    config = normalized_run_config(
        args, pack, manifest_path, selected_rows, models
    )
    config_path = run_dir / "run_config.json"
    if run_dir.exists():
        if not args.resume:
            raise BenchmarkError(
                f"run directory already exists; pass --resume or choose another "
                f"--run-id: {run_dir}"
            )
        try:
            existing = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BenchmarkError(f"cannot resume without valid {config_path}: {exc}") from exc
        if not isinstance(existing, dict):
            raise BenchmarkError(f"cannot resume: {config_path} is not a JSON object")
        comparable = dict(existing)
        comparable.pop("created_at", None)
        if comparable != config:
            raise BenchmarkError(
                "resume configuration differs from the existing run; use a new --run-id"
            )
    else:
        run_dir.mkdir(parents=True)
        write_json(config_path, {**config, "created_at": utc_now()})
        write_json(run_dir / "testset_validation.json", report)
        write_json(run_dir / "label_map.json", EXPECTED_LABEL_MAP)
        write_selected_manifest(
            run_dir / "selected_manifest.csv", selected_rows, fieldnames
        )
    selected_manifest = run_dir / "selected_manifest.csv"
    if not selected_manifest.is_file():
        write_selected_manifest(selected_manifest, selected_rows, fieldnames)
    write_summary(run_dir, models)

    failures = 0
    for index, model in enumerate(models, start=1):
        chain_id = model["chain_id"]
        status_path = run_dir / "models" / chain_id / "status.json"
        if args.resume and status_path.is_file():
            try:
                previous = json.loads(status_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                previous = None
            if (
                isinstance(previous, dict)
                and previous.get("status") == "complete"
                and (status_path.parent / "predictions.csv").is_file()
            ):
                print(f"[{index}/{len(models)}] resume skip complete: {chain_id}")
                continue
        print(f"[{index}/{len(models)}] run: {chain_id}", flush=True)
        status = run_one_model(
            args,
            pack,
            testset,
            selected_manifest,
            run_dir,
            model,
        )
        write_summary(run_dir, models)
        if status["status"] != "complete":
            failures += 1
            print(f"[{chain_id}] FAILED: {status.get('error', 'unknown error')}", file=sys.stderr)
            if not args.continue_on_error:
                break
    write_summary(run_dir, models)
    print(f"results: {run_dir}")
    print(f"summary: {run_dir / 'summary.csv'}")
    return 1 if failures else 0


def main() -> int:
    args = parse_args()
    try:
        if args.action == "validate-testset":
            report, rows, _, _, _ = validate_testset(
                args.testset, args.manifest, args.annotation_policy
            )
            selected = select_rows(rows, args.start, args.stride, args.count)
            report["selected_samples"] = len(selected)
            report["selection"] = {
                "start": args.start,
                "stride": args.stride,
                "count": args.count,
            }
            if args.report is not None:
                write_json(args.report.resolve(), report)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.action == "list-models":
            _, models = select_models(args)
            if args.json:
                print(json.dumps(models, ensure_ascii=False, indent=2))
            else:
                print("chain_id\tgroup\tfeature\tactivation\tcore")
                for model in models:
                    print(
                        f"{model['chain_id']}\t{model['group']}\t"
                        f"{model['feature']}\t{model['activation']}\t"
                        f"{model['core_experiment']}"
                    )
            print(f"models: {len(models)}", file=sys.stderr)
            return 0
        return execute_run(args)
    except (BenchmarkError, OSError) as exc:
        print(f"board benchmark error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
