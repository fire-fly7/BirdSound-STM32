#!/usr/bin/env python3
"""Generate the firmware model source and manifest from a Model_train export."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path
from typing import Any



sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from shared.deployment_contract import CONTRACT, CONTRACT_SHA256, LEGACY_CONTRACT_SHA256, render_c_header

DEFAULT_LABELS = tuple(CONTRACT["labels"])

SUPPORTED_OPERATORS = {
    "ADD",
    "CONV_2D",
    "DEPTHWISE_CONV_2D",
    "FULLY_CONNECTED",
    "LOGISTIC",
    "MAX_POOL_2D",
    "MEAN",
    "MUL",
    "SOFTMAX",
}

FEATURES = {
    "MFCC": (1, CONTRACT["mfcc"]["coefficients"]),
    "LOGMEL": (2, CONTRACT["mel"]["spectral_bands"]),
    "PCEN": (3, CONTRACT["mel"]["spectral_bands"]),
}

ACTIVATIONS = {
    "softmax": (1, "SOFTMAX"),
    "sigmoid": (2, "LOGISTIC"),
}


class BundleError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tflite", required=True, type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--label-map", type=Path)
    parser.add_argument("--feature", choices=tuple(FEATURES))
    parser.add_argument("--model-name")
    parser.add_argument("--source-commit", default="unknown")
    parser.add_argument("--arena-bytes", type=int, default=CONTRACT["model"]["arena_bytes"])
    parser.add_argument("--threshold", type=float, default=CONTRACT["model"]["output_threshold"])
    parser.add_argument("--output-dir", required=True, type=Path)
    return parser.parse_args()


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BundleError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"expected a JSON object in {path}")
    return value


def derive_metadata_path(tflite_path: Path) -> Path:
    name = tflite_path.name
    if name.endswith(".int8.tflite"):
        return tflite_path.with_name(name.removesuffix(".int8.tflite") + ".int8_metadata.json")
    return tflite_path.with_suffix(".int8_metadata.json")


def require(mapping: dict[str, Any], key: str, expected: type) -> Any:
    value = mapping.get(key)
    if not isinstance(value, expected):
        raise BundleError(f"metadata field {key!r} must be {expected.__name__}")
    return value


def parse_shape(value: Any, field: str, dimensions: int) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != dimensions
        or not all(isinstance(item, int) for item in value)
    ):
        raise BundleError(
            f"metadata field {field!r} must contain {dimensions} integer dimensions"
        )
    return value


def quantization(metadata: dict[str, Any], prefix: str) -> tuple[float, int]:
    section = metadata.get(prefix)
    if not isinstance(section, dict):
        raise BundleError(f"metadata field {prefix!r} must be an object")
    scale = section.get("scale")
    zero_point = section.get("zero_point")
    if not isinstance(scale, (int, float)) or not math.isfinite(scale) or scale <= 0:
        raise BundleError(f"{prefix} quantization scale must be finite and positive")
    if not isinstance(zero_point, int) or not -128 <= zero_point <= 127:
        raise BundleError(f"{prefix} quantization zero point must be in int8 range")
    return float(scale), zero_point


def read_labels(path: Path | None) -> tuple[str, ...]:
    if path is None:
        return DEFAULT_LABELS
    mapping = load_json(path)
    indexed: dict[int, str] = {}
    for name, index in mapping.items():
        if not isinstance(name, str) or not isinstance(index, int):
            raise BundleError("label map must have string keys and integer values")
        if index in indexed:
            raise BundleError(f"duplicate label index {index}")
        indexed[index] = name
    expected = set(range(len(DEFAULT_LABELS)))
    if set(indexed) != expected:
        raise BundleError(f"label indices must be exactly {sorted(expected)}")
    labels = tuple(indexed[index] for index in range(len(DEFAULT_LABELS)))
    if any(len(label.encode("utf-8")) >= 32 for label in labels):
        raise BundleError("firmware protocol permits at most 31 UTF-8 bytes per label")
    if labels != DEFAULT_LABELS:
        raise BundleError("label ordering does not match the shared deployment contract")
    return labels


def infer_feature(
    explicit: str | None,
    input_bins: int,
    tflite_path: Path,
    metadata: dict[str, Any],
) -> str:
    if explicit is not None:
        feature = explicit
    elif input_bins == CONTRACT["mfcc"]["coefficients"]:
        feature = "MFCC"
    else:
        clues = " ".join(
            (
                str(tflite_path),
                str(metadata.get("model_path", "")),
                json.dumps(metadata.get("representative_sources", [])),
            )
        ).lower()
        has_logmel = "logmel" in clues or "log_mel" in clues
        has_pcen = "pcen" in clues
        if has_logmel == has_pcen:
            raise BundleError(
                "cannot infer the 40-bin frontend; pass --feature LOGMEL or --feature PCEN"
            )
        feature = "LOGMEL" if has_logmel else "PCEN"

    expected_bins = FEATURES[feature][1]
    if input_bins != expected_bins:
        raise BundleError(
            f"{feature} expects {expected_bins} bins, but the model input has {input_bins}"
        )
    return feature


def c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def c_float(value: float) -> str:
    text = format(value, ".17g")
    if "e" not in text.lower() and "." not in text:
        text += ".0"
    return text + "f"


def protocol_model_name(full_name: str, sha256: str) -> str:
    if len(full_name.encode("utf-8")) < 48:
        return full_name
    short = f"{full_name[:30]}_{sha256[:12]}"
    while len(short.encode("utf-8")) >= 48:
        short = short[:-1]
    return short


def atomic_write(path: Path, content: str) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def render_model_data(model: bytes) -> str:
    lines = []
    for offset in range(0, len(model), 12):
        chunk = ", ".join(f"0x{byte:02x}" for byte in model[offset : offset + 12])
        lines.append(f"    {chunk},")
    body = "\n".join(lines)
    return f"""/* Generated by tools/generate_model_bundle.py. Do not edit. */
#include "model_data.h"

const unsigned char model_data[] __attribute__((aligned(16))) = {{
{body}
}};

const unsigned int model_data_len = sizeof(model_data);
"""


def render_manifest(bundle: dict[str, Any]) -> str:
    labels = bundle["labels"]
    label_macros = "\n".join(
        f"#define MODEL_LABEL_{index} {c_string(label)}"
        for index, label in enumerate(labels)
    )
    return f"""/* Generated by tools/generate_model_bundle.py. Do not edit. */
#ifndef MODEL_MANIFEST_H
#define MODEL_MANIFEST_H

#define MODEL_NAME {c_string(bundle["protocol_model_name"])}
#define MODEL_FULL_NAME {c_string(bundle["model_name"])}
#define MODEL_SOURCE_COMMIT {c_string(bundle["source_commit"])}
#define MODEL_FRONTEND_CONTRACT_SHA256 {c_string(bundle["frontend_contract_sha256"])}
#define MODEL_SHA256 {c_string(bundle["sha256"])}
#define MODEL_DATA_BYTES {bundle["model_bytes"]}U

#define MODEL_FEATURE_ID {FEATURES[bundle["feature"]][0]}U
#define MODEL_FEATURE_TYPE {c_string(bundle["feature"])}
#define MODEL_OUTPUT_ACTIVATION_ID {ACTIVATIONS[bundle["activation"]][0]}U
#define MODEL_OUTPUT_ACTIVATION {c_string(bundle["activation"])}
#define MODEL_OUTPUT_THRESHOLD {c_float(bundle["threshold"])}

#define MODEL_FEATURE_FRAMES {bundle["input_shape"][1]}U
#define MODEL_FEATURE_BINS {bundle["input_shape"][2]}U
#define MODEL_FEATURE_CHANNELS {bundle["input_shape"][3]}U
#define MODEL_INPUT_SIZE {bundle["input_elements"]}U
#define MODEL_OUTPUT_SIZE {bundle["output_shape"][1]}U

#define MODEL_INPUT_SCALE {c_float(bundle["input_scale"])}
#define MODEL_INPUT_ZERO_POINT {bundle["input_zero_point"]}
#define MODEL_OUTPUT_SCALE {c_float(bundle["output_scale"])}
#define MODEL_OUTPUT_ZERO_POINT {bundle["output_zero_point"]}

#define MODEL_TENSOR_ARENA_BYTES {bundle["arena_bytes"]}U
{label_macros}

#endif /* MODEL_MANIFEST_H */
"""


def build_bundle(args: argparse.Namespace) -> dict[str, Any]:
    if args.arena_bytes <= 0:
        raise BundleError("--arena-bytes must be positive")
    if not math.isfinite(args.threshold):
        raise BundleError("--threshold must be finite")

    tflite_path = args.tflite.resolve()
    metadata_path = (args.metadata or derive_metadata_path(tflite_path)).resolve()
    try:
        model = tflite_path.read_bytes()
    except OSError as exc:
        raise BundleError(f"cannot read model {tflite_path}: {exc}") from exc
    metadata = load_json(metadata_path)
    if 'frontend_contract_sha256' not in metadata and CONTRACT_SHA256 != LEGACY_CONTRACT_SHA256:
        raise BundleError('legacy metadata cannot be used with changed frontend parameters; re-export the model')
    if metadata.get('frontend_contract_sha256', CONTRACT_SHA256) != CONTRACT_SHA256:
        raise BundleError('model metadata frontend contract hash mismatch')

    if metadata.get("strict_int8") is not True:
        raise BundleError("only strict_int8 Model_train exports are supported")
    input_metadata = metadata.get("input")
    output_metadata = metadata.get("output")
    if not isinstance(input_metadata, dict) or not isinstance(output_metadata, dict):
        raise BundleError("metadata must contain input and output objects")
    if input_metadata.get("dtype") != "int8" or output_metadata.get("dtype") != "int8":
        raise BundleError("model input and output tensors must both be int8")
    if metadata.get('tflite_sha256', hashlib.sha256(model).hexdigest()) != hashlib.sha256(model).hexdigest():
        raise BundleError('model bytes do not match metadata SHA-256')
    metadata_bytes = metadata.get("tflite_bytes")
    if metadata_bytes is not None and metadata_bytes != len(model):
        raise BundleError(
            f"metadata reports {metadata_bytes} bytes, but {tflite_path} has {len(model)}"
        )

    input_shape = parse_shape(
        input_metadata.get("shape_signature"), "input.shape_signature", dimensions=4
    )
    output_shape = parse_shape(
        output_metadata.get("shape_signature"), "output.shape_signature", dimensions=2
    )
    if input_shape[0] != -1 or input_shape[1] != CONTRACT["stft"]["frames"] or input_shape[3] != 1:
        raise BundleError(f"unsupported input signature {input_shape}; expected [-1, 32, bins, 1]")
    if input_shape[2] not in tuple(x[1] for x in FEATURES.values()):
        raise BundleError(f"unsupported feature-bin count {input_shape[2]}")
    if output_shape != [-1, len(DEFAULT_LABELS)]:
        raise BundleError(
            f"unsupported output signature {output_shape}; expected [-1, {len(DEFAULT_LABELS)}]"
        )

    activation = require(metadata, "output_activation", str).lower()
    if activation not in ACTIVATIONS:
        raise BundleError(f"unsupported output activation {activation!r}")
    operators_value = metadata.get("operators")
    if not isinstance(operators_value, list) or not all(
        isinstance(operator, str) for operator in operators_value
    ):
        raise BundleError("metadata field 'operators' must be a list of strings")
    operators = set(operators_value)
    unsupported = operators - SUPPORTED_OPERATORS - {"DELEGATE"}
    if unsupported:
        raise BundleError(f"unsupported TFLite operators: {sorted(unsupported)}")
    required_activation_operator = ACTIVATIONS[activation][1]
    if required_activation_operator not in operators:
        raise BundleError(
            f"{activation} model metadata does not list {required_activation_operator}"
        )
    forbidden_activation_operator = "LOGISTIC" if required_activation_operator == "SOFTMAX" else "SOFTMAX"
    if forbidden_activation_operator in operators:
        raise BundleError("model unexpectedly contains both LOGISTIC and SOFTMAX")
    conversion_ops = {"QUANTIZE", "DEQUANTIZE"} & operators
    if conversion_ops:
        raise BundleError(f"strict-int8 model contains conversion operators: {conversion_ops}")

    input_scale, input_zero_point = quantization(metadata, "input")
    output_scale, output_zero_point = quantization(metadata, "output")
    labels = read_labels(args.label_map.resolve() if args.label_map else None)
    feature = infer_feature(args.feature, input_shape[2], tflite_path, metadata)
    sha256 = hashlib.sha256(model).hexdigest()
    full_name = args.model_name or tflite_path.parent.name

    return {
        "schema_version": 1,
        "frontend_contract_sha256": CONTRACT_SHA256,
        "contract_provenance": "verified_metadata" if "frontend_contract_sha256" in metadata else "legacy_metadata_assumed_compatible",
        "model_name": full_name,
        "protocol_model_name": protocol_model_name(full_name, sha256),
        "source_commit": args.source_commit,
        "source_tflite": str(tflite_path),
        "source_metadata": str(metadata_path),
        "sha256": sha256,
        "model_bytes": len(model),
        "feature": feature,
        "activation": activation,
        "threshold": float(args.threshold),
        "input_shape": input_shape,
        "output_shape": output_shape,
        "input_elements": input_shape[1] * input_shape[2] * input_shape[3],
        "input_scale": input_scale,
        "input_zero_point": input_zero_point,
        "output_scale": output_scale,
        "output_zero_point": output_zero_point,
        "arena_bytes": args.arena_bytes,
        "operators": sorted(operators - {"DELEGATE"}),
        "labels": list(labels),
        "_model": model,
    }


def main() -> int:
    args = parse_args()
    try:
        bundle = build_bundle(args)
        model = bundle.pop("_model")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        atomic_write(args.output_dir / "model_data.c", render_model_data(model))
        atomic_write(args.output_dir / "model_manifest.h", render_manifest(bundle))
        atomic_write(
            args.output_dir / "model_bundle.json",
            json.dumps(bundle, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        )
    except BundleError as exc:
        print(f"model bundle error: {exc}", file=sys.stderr)
        return 2
    print(
        f"generated {bundle['model_name']} ({bundle['feature']}, "
        f"{bundle['activation']}, {bundle['model_bytes']} bytes)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
