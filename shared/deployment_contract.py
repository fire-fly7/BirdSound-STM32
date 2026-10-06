"""Shared training/firmware contract. JSON is the only parameter source."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

# Historical models without a contract stamp are only valid for this frozen v1 configuration.
LEGACY_CONTRACT_SHA256 = "89fd9a92831115045ebba43b9ecb7b7aa7c7227674bc430e4f11822885d7b4c2"
CONTRACT_PATH = Path(__file__).with_name("deployment_contract.json")


def load_contract(path: Path = CONTRACT_PATH) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    validate_contract(value)
    return value


def validate_contract(c: dict) -> None:
    a, s, m, p = c["audio"], c["stft"], c["mel"], c["pcen"]
    expected = [(c["schema_version"] == 1, "schema"),
                (a["channels"] == c["model"]["channels"] == 1, "mono input"),
                (a["pcm_divisor"] == 32768, "PCM16 normalization"),
                (s["fft_size"] == 2048, "CMSIS 2048-point FFT"),
                (s["center"] is True and s["pad_mode"] == "constant" and s["window"] == "hann", "STFT convention"),
                (s["hop_length"] > 0 and a["window_samples"] == a["sample_rate_hz"], "one-second window"),
                (s["frames"] == 1 + a["window_samples"] // s["hop_length"], "frame count"),
                (m["norm"] == "slaney" and m["htk"] is False, "Mel convention"),
                (0 <= m["fmin"] < m["fmax"] <= a["sample_rate_hz"] / 2, "Mel frequency range"),
                (1 <= m["spectral_bands"] <= m["mfcc_bands"] <= 128, "Mel bands"),
                (1 <= c["mfcc"]["coefficients"] <= min(40, m["mfcc_bands"]), "MFCC coefficients"),
                (c["mfcc"]["coefficients"] <= m["spectral_bands"], "frontend buffer capacity"),
                (c["mfcc"]["dct_type"] == 2 and c["mfcc"]["dct_norm"] == "ortho", "DCT convention"),
                (c["mfcc"]["power"] == c["logmel"]["power"] == 2 and p["magnitude_power"] == 1, "spectral powers"),
                (c["mfcc"]["db_reference"] == 1 and c["logmel"]["db_reference"] == "max", "dB reference"),
                (p["max_size"] == 1 and p["reset"] == "per_window" and p["initial_smoothed"] == 1.0, "PCEN state convention"),
                (c["quantization"] == {"dtype": "int8", "rounding": "nearest_even", "order": "round_then_zero_point", "arithmetic": "float32"}, "quantization convention"),
                (len(c["labels"]) == len(set(c["labels"])) == 8 and all(len(x.encode()) < 32 for x in c["labels"]), "eight protocol labels"),
                (c["model"]["arena_bytes"] > 0 and 0 <= c["model"]["output_threshold"] <= 1, "model settings")]
    for ok, name in expected:
        if not ok:
            raise ValueError(f"Unsupported shared contract: {name}")
    def finite_values(obj):
        if isinstance(obj, dict):
            for item in obj.values(): finite_values(item)
        elif isinstance(obj, list):
            for item in obj: finite_values(item)
        elif isinstance(obj, (int, float)) and not math.isfinite(obj):
            raise ValueError("Non-finite contract value")
    finite_values(c)
    if min(c["db"]["amin"], c["db"]["top_db"], p["input_scale"], p["bias"], p["eps"], p["time_constant"], a["pcm_divisor"]) <= 0:
        raise ValueError("Positive frontend constants required")


def contract_sha256(c: dict) -> str:
    return hashlib.sha256(json.dumps(c, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()


def feature_shapes(c: dict) -> dict:
    frames = c["stft"]["frames"]
    return {"MFCC": (frames, c["mfcc"]["coefficients"]),
            "LogMel": (frames, c["mel"]["spectral_bands"]),
            "PCEN": (frames, c["mel"]["spectral_bands"])}


def quantize_int8(values, scale: float, zero_point: int):
    import numpy as np
    x = np.asarray(values, dtype=np.float32)
    scale32 = np.float32(scale)
    if not np.isfinite(scale32) or scale32 <= 0 or not -128 <= zero_point <= 127 or not np.isfinite(x).all():
        raise ValueError("Invalid INT8 quantization input")
    with np.errstate(over="ignore"):
        rounded = np.rint(x / scale32)
    # Bound before integer conversion; huge finite inputs must saturate safely.
    bounded = np.clip(rounded, -128 - zero_point, 127 - zero_point)
    return (bounded.astype(np.int32) + zero_point).astype(np.int8)


def render_c_header(c: dict) -> str:
    values = {
        "SHARED_SAMPLE_RATE": c["audio"]["sample_rate_hz"], "SHARED_WINDOW_SAMPLES": c["audio"]["window_samples"],
        "SHARED_PCM_DIVISOR": c["audio"]["pcm_divisor"], "SHARED_FFT_SIZE": c["stft"]["fft_size"],
        "SHARED_HOP_LENGTH": c["stft"]["hop_length"], "SHARED_FRAMES": c["stft"]["frames"],
        "SHARED_MFCC_BANDS": c["mel"]["mfcc_bands"], "SHARED_SPECTRAL_BANDS": c["mel"]["spectral_bands"],
        "SHARED_MFCC_COEFFICIENTS": c["mfcc"]["coefficients"], "SHARED_DB_AMIN": c["db"]["amin"],
        "SHARED_TOP_DB": c["db"]["top_db"], "SHARED_ARENA_BYTES": c["model"]["arena_bytes"],
        "SHARED_CLASS_COUNT": len(c["labels"]),
    }
    for name in ("input_scale", "gain", "bias", "power", "time_constant", "eps", "initial_smoothed"):
        values["SHARED_PCEN_" + name.upper()] = c["pcen"][name]
    lines = ["/* Generated from shared/deployment_contract.json. Do not edit. */", "#ifndef SHARED_FRONTEND_CONTRACT_H", "#define SHARED_FRONTEND_CONTRACT_H", "#include <math.h>", "#include <stdint.h>", f'#define SHARED_CONTRACT_SHA256 "{contract_sha256(c)}"']
    for name, value in values.items():
        text = str(value) + "U" if isinstance(value, int) else float(value).hex()
        lines.append(f"#define {name} {text}")
    lines.extend([
        "/* float32 divide, ties-to-even, then zero-point; independent of fenv. */",
        "static inline int8_t SharedQuantizeInt8(float value, float scale, int32_t zero_point)",
        "{", "  float x = value / scale;",
        "  if (x <= (float)(-128 - zero_point)) return -128;",
        "  if (x >= (float)(127 - zero_point)) return 127;",
        "  float lower = floorf(x);", "  float fraction = x - lower;",
        "  int32_t rounded = (int32_t)lower;",
        "  if (fraction > 0.5f || (fraction == 0.5f && (rounded % 2 != 0))) ++rounded;",
        "  return (int8_t)(rounded + zero_point);", "}", "#endif", ""])
    return "\n".join(lines)


CONTRACT = load_contract()
CONTRACT_SHA256 = contract_sha256(CONTRACT)
FEATURE_SHAPES = feature_shapes(CONTRACT)
