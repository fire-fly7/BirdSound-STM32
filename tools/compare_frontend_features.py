#!/usr/bin/env python3
"""Compare one STM32 audio-frontend dump with its aligned training tensor."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class ComparisonError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--board", required=True, type=Path)
    parser.add_argument("--reference", required=True, type=Path)
    parser.add_argument(
        "--reference-index",
        required=True,
        type=int,
        help="window index in the training array that produced the board dump",
    )
    parser.add_argument(
        "--info",
        required=True,
        type=Path,
        help="board info.json containing feature type and input quantization",
    )
    parser.add_argument(
        "--max-abs-limit",
        required=True,
        type=float,
        help="maximum permitted absolute float feature error",
    )
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def load_info(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ComparisonError(f"cannot read board info {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ComparisonError(f"board info is not a JSON object: {path}")
    required = ("feature", "input_dims", "input_scale", "input_zero_point")
    missing = [field for field in required if field not in value]
    if missing:
        raise ComparisonError(f"board info is missing fields: {', '.join(missing)}")
    return value


def sample_shape(input_dims: Any) -> tuple[int, ...]:
    try:
        dims = tuple(int(value) for value in input_dims)
    except (TypeError, ValueError) as exc:
        raise ComparisonError(f"invalid input_dims: {input_dims!r}") from exc
    if len(dims) != 4 or dims[0] != 1 or dims[-1] != 1:
        raise ComparisonError(f"expected board input [1,time,bins,1], got {dims}")
    return dims[1:-1]


def normalize_feature(np: Any, value: Any, expected: tuple[int, ...], name: str) -> Any:
    array = np.asarray(value)
    if array.shape == (*expected, 1):
        array = array[..., 0]
    if tuple(array.shape) != expected:
        raise ComparisonError(
            f"{name} shape {tuple(array.shape)} does not match {expected}"
        )
    array = np.asarray(array, dtype=np.float32)
    if not np.isfinite(array).all():
        raise ComparisonError(f"{name} contains NaN or infinity")
    return array


def quantize(np: Any, value: Any, scale: float, zero_point: int) -> Any:
    scaled = np.rint(value.astype(np.float32, copy=False) / np.float32(scale))
    scaled = scaled.astype(np.int32) + zero_point
    return np.clip(scaled, -128, 127).astype(np.int8)


def main() -> int:
    args = parse_args()
    if args.reference_index < 0:
        raise SystemExit("--reference-index must be nonnegative")
    if args.max_abs_limit < 0:
        raise SystemExit("--max-abs-limit must be nonnegative")
    try:
        import numpy as np
    except ImportError as exc:
        raise SystemExit("numpy is required") from exc

    try:
        info = load_info(args.info)
        expected_shape = sample_shape(info["input_dims"])
        board_all = np.load(args.board, allow_pickle=False)
        reference_all = np.load(args.reference, allow_pickle=False)
        if reference_all.ndim not in {3, 4}:
            raise ComparisonError(
                "reference must have shape [N,time,bins] or [N,time,bins,1]"
            )
        if args.reference_index >= len(reference_all):
            raise ComparisonError(
                f"reference index {args.reference_index} is outside "
                f"0..{len(reference_all) - 1}"
            )
        board = normalize_feature(np, board_all, expected_shape, "board feature")
        reference = normalize_feature(
            np,
            reference_all[args.reference_index],
            expected_shape,
            "reference feature",
        )
        scale = float(info["input_scale"])
        zero_point = int(info["input_zero_point"])
        if not np.isfinite(scale) or scale <= 0 or zero_point not in range(-128, 128):
            raise ComparisonError(
                f"invalid input quantization scale={scale}, zero_point={zero_point}"
            )

        difference = board.astype(np.float64) - reference.astype(np.float64)
        absolute = np.abs(difference)
        board_quantized = quantize(np, board, scale, zero_point)
        reference_quantized = quantize(np, reference, scale, zero_point)
        quantized_difference = np.abs(
            board_quantized.astype(np.int16) - reference_quantized.astype(np.int16)
        )
        max_abs_error = float(absolute.max(initial=0.0))
        quantized_mismatches = int(np.count_nonzero(quantized_difference))
        report = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "passed": (
                max_abs_error <= args.max_abs_limit and quantized_mismatches == 0
            ),
            "alignment": {
                "reference_index": args.reference_index,
                "board_dump_semantics": "final one-second window returned by AUDIO_GET_FEATURE",
            },
            "feature": str(info["feature"]).upper(),
            "shape": list(expected_shape),
            "elements": int(board.size),
            "board": {
                "path": str(args.board.resolve()),
                "sha256": sha256_file(args.board),
                "dtype": str(board_all.dtype),
            },
            "reference": {
                "path": str(args.reference.resolve()),
                "sha256": sha256_file(args.reference),
                "dtype": str(reference_all.dtype),
            },
            "float_error": {
                "max_abs": max_abs_error,
                "mean_abs": float(absolute.mean()),
                "rmse": float(np.sqrt(np.mean(difference * difference))),
                "mean_signed": float(difference.mean()),
                "max_abs_limit": args.max_abs_limit,
                "passed": max_abs_error <= args.max_abs_limit,
            },
            "input_quantization": {
                "scale": scale,
                "zero_point": zero_point,
                "max_lsb_error": int(quantized_difference.max(initial=0)),
                "mismatched_elements": quantized_mismatches,
                "passed": quantized_mismatches == 0,
            },
        }
        encoded = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(encoded, encoding="utf-8")
        print(encoded, end="")
        return 0 if report["passed"] else 1
    except (ComparisonError, OSError, ValueError) as exc:
        print(f"frontend comparison error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
