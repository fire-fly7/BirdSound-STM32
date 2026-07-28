#!/usr/bin/env python3
"""Drive STM32_deploy inference over UART without a microphone."""

from __future__ import annotations

import argparse
import csv
import dataclasses
import hashlib
import json
import statistics
import struct
import sys
import time
import wave
import zlib
from pathlib import Path
from typing import Any


MAGIC = 0x31544D53
MAGIC_BYTES = struct.pack("<I", MAGIC)
VERSION = 1

CMD_GET_INFO = 0x01
CMD_RUN_F32 = 0x02
CMD_RUN_NATIVE = 0x03
CMD_AUDIO_BEGIN = 0x10
CMD_AUDIO_CHUNK = 0x11
CMD_AUDIO_RUN = 0x12
CMD_AUDIO_GET_FEATURE = 0x13
RSP_INFO = 0x81
RSP_RESULT = 0x82
RSP_AUDIO_ACK = 0x90
RSP_AUDIO_FEATURE = 0x91
RSP_AUDIO_RESULT = 0x92
RSP_ERROR = 0xFF

HEADER = struct.Struct("<IBBHIII")
INFO = struct.Struct("<iBBBB4H2H4Ififi48s65s256s")
RESULT = struct.Struct("<iiIIIII8f32s")
ERROR = struct.Struct("<i96s")
AUDIO_BEGIN = struct.Struct("<IIHHI")
AUDIO_ACK = struct.Struct("<iII")
AUDIO_TIMING = struct.Struct("<i6I")
AUDIO_FEATURE_HEADER = struct.Struct("<iI")

AUDIO_SAMPLE_RATE = 16_000
AUDIO_FORMAT_PCM_S16_LE = 1

FEATURE_NAMES = {1: "MFCC", 2: "LOGMEL", 3: "PCEN"}
ACTIVATION_NAMES = {1: "softmax", 2: "sigmoid"}


class ProtocolError(RuntimeError):
    pass


@dataclasses.dataclass(frozen=True)
class ModelInfo:
    model_status: int
    feature_id: int
    activation_id: int
    input_type: int
    output_type: int
    input_dims: tuple[int, int, int, int]
    output_count: int
    label_count: int
    input_elements: int
    model_bytes: int
    arena_bytes: int
    arena_used: int
    input_scale: float
    input_zero_point: int
    output_scale: float
    output_zero_point: int
    model_name: str
    model_sha256: str
    labels: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        value = dataclasses.asdict(self)
        value["feature"] = FEATURE_NAMES.get(self.feature_id, f"unknown:{self.feature_id}")
        value["activation"] = ACTIVATION_NAMES.get(
            self.activation_id, f"unknown:{self.activation_id}"
        )
        return value


@dataclasses.dataclass(frozen=True)
class InferenceResult:
    model_status: int
    predicted_index: int
    cycles: int
    elapsed_us: int
    active_class_mask: int
    output_count: int
    raw_output: bytes
    scores: tuple[float, ...]


@dataclasses.dataclass(frozen=True)
class AudioResult:
    inference: InferenceResult
    frontend_status: int
    audio_samples: int
    windows: int
    frontend_cycles: int
    frontend_elapsed_us: int
    inference_cycles: int
    inference_elapsed_us: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True, help="serial device, for example /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115_200)
    parser.add_argument("--timeout", type=float, default=8.0)
    subparsers = parser.add_subparsers(dest="action", required=True)

    subparsers.add_parser("info", help="print the model manifest reported by the board")

    run = subparsers.add_parser("run", help="run one feature tensor")
    add_input_arguments(run)
    run.add_argument("--index", type=int, default=0)

    smoke = subparsers.add_parser(
        "smoke", help="run deterministic generated tensors without a .npy dataset"
    )
    add_mode_arguments(smoke)
    smoke.add_argument(
        "--max-lsb-error",
        type=int,
        default=1,
        help="maximum permitted int8 output difference from desktop TFLite",
    )
    smoke.add_argument(
        "--output",
        type=Path,
        help="optional CSV containing every generated-tensor parity result",
    )

    sweep = subparsers.add_parser("sweep", help="run a range of tensors and summarize parity")
    add_input_arguments(sweep)
    sweep.add_argument("--start", type=int, default=0)
    sweep.add_argument("--count", type=int, default=0, help="0 means all remaining samples")
    sweep.add_argument(
        "--output",
        type=Path,
        help="optional CSV containing every board prediction, score, raw output, and latency",
    )
    sweep.add_argument(
        "--max-lsb-error",
        type=int,
        default=1,
        help="maximum permitted int8 output difference from desktop TFLite",
    )

    audio_run = subparsers.add_parser(
        "audio-run",
        help="send a complete PCM16 WAV; segmentation, MFCC, and inference run on-board",
    )
    add_audio_arguments(audio_run)
    audio_run.add_argument(
        "--dump-feature",
        type=Path,
        help="save the board-generated MFCC tensor for the final one-second window",
    )

    audio_sweep = subparsers.add_parser(
        "audio-sweep",
        help="run raw PCM16 WAV files listed in a CSV manifest",
    )
    audio_sweep.add_argument("--manifest", required=True, type=Path)
    audio_sweep.add_argument(
        "--root",
        type=Path,
        help="root for manifest 'file' paths (default: manifest directory)",
    )
    audio_sweep.add_argument("--start", type=int, default=0)
    audio_sweep.add_argument(
        "--stride",
        type=int,
        default=1,
        help="positive manifest row stride",
    )
    audio_sweep.add_argument(
        "--count",
        type=int,
        default=0,
        help="0 means all remaining manifest rows",
    )
    audio_sweep.add_argument("--chunk-samples", type=int, default=2048)
    audio_sweep.add_argument(
        "--output",
        type=Path,
        help="optional per-recording board result CSV",
    )
    return parser.parse_args()


def add_input_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=Path, help=".npy feature tensor(s)")
    add_mode_arguments(parser)


def add_mode_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--mode",
        choices=("f32", "native", "both"),
        default="both",
        help="wire representation sent to the board",
    )
    parser.add_argument(
        "--tflite",
        type=Path,
        help="optional desktop TFLite model used for output parity checks",
    )


def add_audio_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--input", required=True, type=Path, help="mono PCM16 WAV")
    parser.add_argument(
        "--chunk-samples",
        type=int,
        default=2048,
        help="PCM samples per UART packet (maximum 2558)",
    )


def decode_c_string(value: bytes) -> str:
    return value.split(b"\0", 1)[0].decode("utf-8", errors="replace")


def require_dependencies() -> tuple[Any, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise ProtocolError("NumPy is required: python -m pip install numpy") from exc
    try:
        import serial
    except ImportError as exc:
        raise ProtocolError("pyserial is required: python -m pip install pyserial") from exc
    return np, serial


def read_exact(port: Any, length: int, deadline: float) -> bytes:
    chunks = bytearray()
    while len(chunks) < length:
        if time.monotonic() >= deadline:
            raise ProtocolError(f"UART timeout while waiting for {length} bytes")
        chunk = port.read(length - len(chunks))
        if chunk:
            chunks.extend(chunk)
    return bytes(chunks)


def read_packet(port: Any, timeout: float) -> tuple[int, int, bytes]:
    deadline = time.monotonic() + timeout
    matched = 0
    while matched < len(MAGIC_BYTES):
        byte = read_exact(port, 1, deadline)[0]
        if byte == MAGIC_BYTES[matched]:
            matched += 1
        else:
            matched = 1 if byte == MAGIC_BYTES[0] else 0
    remainder = read_exact(port, HEADER.size - len(MAGIC_BYTES), deadline)
    magic, version, command, flags, sequence, payload_length, expected_crc = HEADER.unpack(
        MAGIC_BYTES + remainder
    )
    if magic != MAGIC or version != VERSION or flags != 0:
        raise ProtocolError("invalid UART response header")
    if payload_length > 1_048_576:
        raise ProtocolError(f"unreasonable UART response payload: {payload_length} bytes")
    payload = read_exact(port, payload_length, deadline)
    actual_crc = zlib.crc32(payload) & 0xFFFFFFFF
    if actual_crc != expected_crc:
        raise ProtocolError(
            f"UART response CRC mismatch: expected {expected_crc:08x}, got {actual_crc:08x}"
        )
    return command, sequence, payload


def send_packet(port: Any, command: int, sequence: int, payload: bytes = b"") -> None:
    header = HEADER.pack(
        MAGIC,
        VERSION,
        command,
        0,
        sequence,
        len(payload),
        zlib.crc32(payload) & 0xFFFFFFFF,
    )
    port.write(header + payload)
    port.flush()


def exchange(
    port: Any, command: int, sequence: int, payload: bytes, timeout: float
) -> tuple[int, bytes]:
    send_packet(port, command, sequence, payload)
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise ProtocolError(f"no response for sequence {sequence}")
        response_command, response_sequence, response_payload = read_packet(port, remaining)
        if response_sequence != sequence:
            # The firmware sends an unsolicited INFO packet with sequence 0 at boot.
            continue
        if response_command == RSP_ERROR:
            if len(response_payload) != ERROR.size:
                raise ProtocolError("malformed error response")
            error_code, message = ERROR.unpack(response_payload)
            raise ProtocolError(f"firmware error {error_code}: {decode_c_string(message)}")
        return response_command, response_payload


def parse_info(payload: bytes) -> ModelInfo:
    if len(payload) != INFO.size:
        raise ProtocolError(f"INFO payload is {len(payload)} bytes; expected {INFO.size}")
    values = INFO.unpack(payload)
    packed_labels = values[21]
    labels = tuple(
        decode_c_string(packed_labels[index * 32 : (index + 1) * 32])
        for index in range(8)
    )
    return ModelInfo(
        model_status=values[0],
        feature_id=values[1],
        activation_id=values[2],
        input_type=values[3],
        output_type=values[4],
        input_dims=tuple(values[5:9]),
        output_count=values[9],
        label_count=values[10],
        input_elements=values[11],
        model_bytes=values[12],
        arena_bytes=values[13],
        arena_used=values[14],
        input_scale=values[15],
        input_zero_point=values[16],
        output_scale=values[17],
        output_zero_point=values[18],
        model_name=decode_c_string(values[19]),
        model_sha256=decode_c_string(values[20]),
        labels=labels,
    )


def parse_result(payload: bytes) -> InferenceResult:
    if len(payload) != RESULT.size:
        raise ProtocolError(f"RESULT payload is {len(payload)} bytes; expected {RESULT.size}")
    values = RESULT.unpack(payload)
    output_count = values[5]
    raw_bytes = values[6]
    if output_count > 8 or raw_bytes > 32:
        raise ProtocolError("firmware result exceeds protocol capacity")
    return InferenceResult(
        model_status=values[0],
        predicted_index=values[1],
        cycles=values[2],
        elapsed_us=values[3],
        active_class_mask=values[4],
        output_count=output_count,
        scores=tuple(values[7 : 7 + output_count]),
        raw_output=values[15][:raw_bytes],
    )


def parse_audio_ack(payload: bytes) -> tuple[int, int, int]:
    if len(payload) != AUDIO_ACK.size:
        raise ProtocolError(
            f"AUDIO_ACK payload is {len(payload)} bytes; expected {AUDIO_ACK.size}"
        )
    return AUDIO_ACK.unpack(payload)


def parse_audio_result(payload: bytes) -> AudioResult:
    expected_size = RESULT.size + AUDIO_TIMING.size
    if len(payload) != expected_size:
        raise ProtocolError(
            f"AUDIO_RESULT payload is {len(payload)} bytes; expected {expected_size}"
        )
    inference = parse_result(payload[: RESULT.size])
    timing = AUDIO_TIMING.unpack(payload[RESULT.size :])
    return AudioResult(
        inference=inference,
        frontend_status=timing[0],
        audio_samples=timing[1],
        windows=timing[2],
        frontend_cycles=timing[3],
        frontend_elapsed_us=timing[4],
        inference_cycles=timing[5],
        inference_elapsed_us=timing[6],
    )


def parse_audio_feature(np: Any, payload: bytes, info: ModelInfo) -> Any:
    if len(payload) < AUDIO_FEATURE_HEADER.size:
        raise ProtocolError("AUDIO_FEATURE response is truncated")
    frontend_status, elements = AUDIO_FEATURE_HEADER.unpack(
        payload[: AUDIO_FEATURE_HEADER.size]
    )
    if frontend_status != 0:
        raise ProtocolError(f"board audio frontend failed: {frontend_status}")
    expected_bytes = AUDIO_FEATURE_HEADER.size + elements * 4
    if len(payload) != expected_bytes:
        raise ProtocolError(
            f"AUDIO_FEATURE payload is {len(payload)} bytes; expected {expected_bytes}"
        )
    if elements != info.input_elements:
        raise ProtocolError(
            f"board returned {elements} features; model expects {info.input_elements}"
        )
    features = np.frombuffer(
        payload[AUDIO_FEATURE_HEADER.size :], dtype="<f4"
    ).copy()
    return features.reshape(tuple(info.input_dims[1:]))


def get_info(port: Any, timeout: float, sequence: int) -> ModelInfo:
    command, payload = exchange(port, CMD_GET_INFO, sequence, b"", timeout)
    if command != RSP_INFO:
        raise ProtocolError(f"expected INFO response, received command 0x{command:02x}")
    info = parse_info(payload)
    if info.model_status != 0:
        raise ProtocolError(f"firmware model initialization failed: {info.model_status}")
    if info.input_type != 9 or info.output_type != 9:
        raise ProtocolError(
            f"only strict int8 tensors are supported, board reported types "
            f"{info.input_type}/{info.output_type}"
        )
    return info


def load_samples(np: Any, path: Path, info: ModelInfo) -> Any:
    try:
        data = np.load(path, allow_pickle=False)
    except (OSError, ValueError) as exc:
        raise ProtocolError(f"cannot load {path}: {exc}") from exc
    sample_shape = tuple(info.input_dims[1:])
    if tuple(data.shape) == sample_shape:
        data = data[np.newaxis, ...]
    elif tuple(data.shape) == sample_shape[:-1]:
        data = data[np.newaxis, ..., np.newaxis]
    elif data.ndim == 3 and tuple(data.shape[1:]) == sample_shape[:-1]:
        data = data[..., np.newaxis]
    elif data.ndim != 4 or tuple(data.shape[1:]) != sample_shape:
        raise ProtocolError(
            f"{path} shape {tuple(data.shape)} is incompatible with board input "
            f"(N, {sample_shape[0]}, {sample_shape[1]}, {sample_shape[2]})"
        )
    data = np.asarray(data, dtype=np.float32)
    if not np.isfinite(data).all():
        raise ProtocolError(f"{path} contains NaN or infinity")
    return data


def quantize_sample(np: Any, sample: Any, info: ModelInfo) -> Any:
    scaled = np.rint(
        sample.astype(np.float32, copy=False) / np.float32(info.input_scale)
    ).astype(np.int32)
    scaled += info.input_zero_point
    return np.clip(scaled, -128, 127).astype(np.int8)


def make_smoke_samples(np: Any, info: ModelInfo) -> Any:
    """Create deterministic tensors that exercise zero, range, and clipping paths."""
    shape = tuple(info.input_dims[1:])
    count = info.input_elements
    quantized_ramp = np.linspace(-128, 127, count, dtype=np.float32).reshape(shape)
    real_ramp = (quantized_ramp - info.input_zero_point) * np.float32(info.input_scale)
    phase = np.linspace(0.0, 8.0 * np.pi, count, dtype=np.float32).reshape(shape)
    sine = np.sin(phase).astype(np.float32) * np.float32(16.0 * info.input_scale)
    clip_low = np.full(
        shape,
        np.float32((-160 - info.input_zero_point) * info.input_scale),
        dtype=np.float32,
    )
    clip_high = np.full(
        shape,
        np.float32((160 - info.input_zero_point) * info.input_scale),
        dtype=np.float32,
    )
    return np.stack(
        (
            np.zeros(shape, dtype=np.float32),
            real_ramp.astype(np.float32),
            sine,
            clip_low,
            clip_high,
        )
    )


def run_board(
    np: Any,
    port: Any,
    sample: Any,
    info: ModelInfo,
    mode: str,
    sequence: int,
    timeout: float,
) -> InferenceResult:
    if mode == "native":
        command = CMD_RUN_NATIVE
        payload = quantize_sample(np, sample, info).tobytes(order="C")
    else:
        command = CMD_RUN_F32
        payload = np.asarray(sample, dtype="<f4").tobytes(order="C")
    response_command, response_payload = exchange(port, command, sequence, payload, timeout)
    if response_command != RSP_RESULT:
        raise ProtocolError(
            f"expected RESULT response, received command 0x{response_command:02x}"
        )
    result = parse_result(response_payload)
    if result.model_status != 0:
        raise ProtocolError(f"firmware inference failed: {result.model_status}")
    return result


def create_reference_interpreter(tflite_path: Path, info: ModelInfo) -> Any:
    try:
        digest = hashlib.sha256(tflite_path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ProtocolError(f"cannot read desktop TFLite model {tflite_path}: {exc}") from exc
    if digest != info.model_sha256:
        raise ProtocolError(
            f"desktop TFLite SHA-256 {digest} does not match board {info.model_sha256}"
        )
    try:
        import tensorflow as tf

        interpreter_class = tf.lite.Interpreter
        resolver_type = tf.lite.experimental.OpResolverType.BUILTIN_REF
    except ImportError:
        try:
            from tflite_runtime.interpreter import Interpreter, OpResolverType

            interpreter_class = Interpreter
            resolver_type = OpResolverType.BUILTIN_REF
        except ImportError:
            try:
                from ai_edge_litert.interpreter import Interpreter, OpResolverType

                interpreter_class = Interpreter
                resolver_type = OpResolverType.BUILTIN_REF
            except ImportError as exc:
                raise ProtocolError(
                    "TFLite parity needs tensorflow, tflite-runtime, or "
                    "ai-edge-litert installed"
                ) from exc
    # Compare TFLM reference kernels with the desktop reference resolver.
    # AUTO may silently enable XNNPACK, whose optimized quantized kernels are
    # valid but can differ by many output LSBs and even change near-tie argmax.
    interpreter = interpreter_class(
        model_path=str(tflite_path),
        experimental_op_resolver_type=resolver_type,
    )
    interpreter.allocate_tensors()
    return interpreter


def reference_output(np: Any, interpreter: Any, sample: Any, info: ModelInfo) -> Any:
    input_detail = interpreter.get_input_details()[0]
    output_detail = interpreter.get_output_details()[0]
    expected_shape = tuple(info.input_dims)
    if tuple(input_detail["shape"]) != expected_shape:
        raise ProtocolError(
            f"desktop TFLite input {tuple(input_detail['shape'])} != board {expected_shape}"
        )
    if input_detail["dtype"] != np.int8 or output_detail["dtype"] != np.int8:
        raise ProtocolError("desktop TFLite model is not strict int8")
    input_quant = input_detail["quantization"]
    output_quant = output_detail["quantization"]
    if (
        abs(float(input_quant[0]) - info.input_scale) > 1.0e-7
        or int(input_quant[1]) != info.input_zero_point
        or abs(float(output_quant[0]) - info.output_scale) > 1.0e-7
        or int(output_quant[1]) != info.output_zero_point
    ):
        raise ProtocolError("desktop TFLite quantization does not match the board manifest")
    quantized = quantize_sample(np, sample, info)[np.newaxis, ...]
    interpreter.set_tensor(input_detail["index"], quantized)
    interpreter.invoke()
    return np.asarray(interpreter.get_tensor(output_detail["index"])[0], dtype=np.int8)


def raw_int8(np: Any, result: InferenceResult) -> Any:
    if len(result.raw_output) != result.output_count:
        raise ProtocolError(
            f"board returned {len(result.raw_output)} raw bytes for "
            f"{result.output_count} int8 outputs"
        )
    return np.frombuffer(result.raw_output, dtype=np.int8)


def result_dict(result: InferenceResult, info: ModelInfo) -> dict[str, Any]:
    return {
        "model_status": result.model_status,
        "predicted_index": result.predicted_index,
        "predicted_label": (
            info.labels[result.predicted_index]
            if 0 <= result.predicted_index < len(info.labels)
            else None
        ),
        "elapsed_us": result.elapsed_us,
        "cycles": result.cycles,
        "active_class_mask": f"0x{result.active_class_mask:08x}",
        "scores": list(result.scores),
        "raw_output_int8": list(struct.unpack(f"<{len(result.raw_output)}b", result.raw_output)),
    }


def load_pcm16_wav(path: Path) -> tuple[bytes, int]:
    try:
        with wave.open(str(path), "rb") as source:
            channels = source.getnchannels()
            sample_width = source.getsampwidth()
            sample_rate = source.getframerate()
            frame_count = source.getnframes()
            compression = source.getcomptype()
            pcm = source.readframes(frame_count)
    except (OSError, wave.Error) as exc:
        raise ProtocolError(f"cannot read WAV {path}: {exc}") from exc
    if (
        channels != 1
        or sample_width != 2
        or sample_rate != AUDIO_SAMPLE_RATE
        or compression != "NONE"
    ):
        raise ProtocolError(
            f"{path} must be mono, 16000 Hz, uncompressed PCM16; got "
            f"{channels} channel(s), {sample_rate} Hz, {sample_width * 8}-bit, "
            f"compression={compression}"
        )
    if len(pcm) != frame_count * sample_width:
        raise ProtocolError(
            f"{path} PCM payload is truncated: {len(pcm)} bytes for {frame_count} frames"
        )
    if frame_count == 0 or frame_count % AUDIO_SAMPLE_RATE != 0:
        raise ProtocolError(
            f"{path} must contain a whole number of one-second windows"
        )
    return pcm, frame_count


def require_audio_ack(command: int, payload: bytes) -> tuple[int, int]:
    if command != RSP_AUDIO_ACK:
        raise ProtocolError(
            f"expected AUDIO_ACK response, received command 0x{command:02x}"
        )
    status, received_samples, completed_windows = parse_audio_ack(payload)
    if status != 0:
        raise ProtocolError(f"board audio processing failed: {status}")
    return received_samples, completed_windows


def run_audio_board(
    np: Any,
    port: Any,
    path: Path,
    info: ModelInfo,
    sequence: int,
    timeout: float,
    chunk_samples: int,
    *,
    get_feature: bool,
) -> tuple[AudioResult, Any | None, int]:
    supported_shape = (
        info.feature_id == 1 and tuple(info.input_dims) == (1, 32, 13, 1)
    ) or (
        info.feature_id in (2, 3)
        and tuple(info.input_dims) == (1, 32, 40, 1)
    )
    if not supported_shape:
        raise ProtocolError(
            "raw-audio firmware supports MFCC [1,32,13,1] and "
            "LogMel/PCEN [1,32,40,1] models"
        )
    if chunk_samples <= 0 or chunk_samples > 2558:
        raise ProtocolError("--chunk-samples must be in 1..2558")

    pcm, sample_count = load_pcm16_wav(path)
    descriptor = AUDIO_BEGIN.pack(
        AUDIO_SAMPLE_RATE,
        sample_count,
        AUDIO_FORMAT_PCM_S16_LE,
        0,
        zlib.crc32(pcm) & 0xFFFFFFFF,
    )
    command, payload = exchange(
        port, CMD_AUDIO_BEGIN, sequence, descriptor, timeout
    )
    received, windows = require_audio_ack(command, payload)
    if received != 0 or windows != 0:
        raise ProtocolError("board did not reset its audio upload state")
    sequence += 1

    chunk_bytes = chunk_samples * 2
    for byte_offset in range(0, len(pcm), chunk_bytes):
        sample_offset = byte_offset // 2
        chunk = pcm[byte_offset : byte_offset + chunk_bytes]
        command, payload = exchange(
            port,
            CMD_AUDIO_CHUNK,
            sequence,
            struct.pack("<I", sample_offset) + chunk,
            timeout,
        )
        received, windows = require_audio_ack(command, payload)
        expected_received = sample_offset + len(chunk) // 2
        if received != expected_received or windows != received // AUDIO_SAMPLE_RATE:
            raise ProtocolError(
                f"board acknowledged {received} samples/{windows} windows; "
                f"expected {expected_received}/{expected_received // AUDIO_SAMPLE_RATE}"
            )
        sequence += 1

    command, payload = exchange(port, CMD_AUDIO_RUN, sequence, b"", timeout)
    if command != RSP_AUDIO_RESULT:
        raise ProtocolError(
            f"expected AUDIO_RESULT response, received command 0x{command:02x}"
        )
    result = parse_audio_result(payload)
    if result.frontend_status != 0:
        raise ProtocolError(
            f"firmware audio frontend failed: {result.frontend_status}"
        )
    if result.inference.model_status != 0:
        raise ProtocolError(
            f"firmware inference failed: {result.inference.model_status}"
        )
    if result.audio_samples != sample_count:
        raise ProtocolError(
            f"board processed {result.audio_samples} of {sample_count} samples"
        )
    sequence += 1

    features = None
    if get_feature:
        command, payload = exchange(
            port, CMD_AUDIO_GET_FEATURE, sequence, b"", timeout
        )
        if command != RSP_AUDIO_FEATURE:
            raise ProtocolError(
                f"expected AUDIO_FEATURE response, received command 0x{command:02x}"
            )
        features = parse_audio_feature(np, payload, info)
        sequence += 1
    return result, features, sequence


def audio_result_dict(
    result: AudioResult, info: ModelInfo, path: Path
) -> dict[str, Any]:
    return {
        "input_wav": str(path),
        "pipeline": (
            "raw PCM16 -> board segmentation -> board "
            f"{FEATURE_NAMES.get(info.feature_id, 'frontend')} -> board int8 inference"
        ),
        "audio_samples": result.audio_samples,
        "windows": result.windows,
        "predicted_index": result.inference.predicted_index,
        "predicted_label": (
            info.labels[result.inference.predicted_index]
            if 0 <= result.inference.predicted_index < len(info.labels)
            else None
        ),
        "scores": list(result.inference.scores),
        "raw_output_int8": list(
            struct.unpack(
                f"<{len(result.inference.raw_output)}b",
                result.inference.raw_output,
            )
        ),
        "frontend_elapsed_us": result.frontend_elapsed_us,
        "inference_elapsed_us": result.inference_elapsed_us,
        "total_compute_elapsed_us": result.inference.elapsed_us,
        "frontend_cycles": result.frontend_cycles,
        "inference_cycles": result.inference_cycles,
        "total_compute_cycles": result.inference.cycles,
    }


def run_audio_sweep(
    np: Any,
    port: Any,
    args: argparse.Namespace,
    info: ModelInfo,
    sequence: int,
) -> bool:
    try:
        with args.manifest.open("r", encoding="utf-8", newline="") as stream:
            manifest_rows = list(csv.DictReader(stream))
    except OSError as exc:
        raise ProtocolError(f"cannot read manifest {args.manifest}: {exc}") from exc
    if not manifest_rows or "file" not in manifest_rows[0]:
        raise ProtocolError("audio manifest must contain at least one row and a 'file' column")
    if args.start < 0 or args.start >= len(manifest_rows):
        raise ProtocolError(
            f"--start {args.start} is outside 0..{len(manifest_rows) - 1}"
        )
    if args.count < 0:
        raise ProtocolError("--count cannot be negative")
    if args.stride <= 0:
        raise ProtocolError("--stride must be positive")
    selected_indices = list(range(args.start, len(manifest_rows), args.stride))
    if args.count != 0:
        selected_indices = selected_indices[: args.count]
    root = args.root if args.root is not None else args.manifest.parent

    output_rows: list[dict[str, Any]] = []
    correct = 0
    labelled = 0
    frontend_times: list[int] = []
    inference_times: list[int] = []
    for selection_index, manifest_index in enumerate(selected_indices):
        manifest_row = manifest_rows[manifest_index]
        wav_path = root / manifest_row["file"]
        result, _, sequence = run_audio_board(
            np,
            port,
            wav_path,
            info,
            sequence,
            args.timeout,
            args.chunk_samples,
            get_feature=False,
        )
        expected_label = manifest_row.get("label", "")
        is_correct: bool | None = None
        if expected_label != "":
            try:
                expected_index = int(expected_label)
            except ValueError as exc:
                raise ProtocolError(
                    f"manifest row {manifest_index} has invalid label {expected_label!r}"
                ) from exc
            labelled += 1
            is_correct = result.inference.predicted_index == expected_index
            correct += int(is_correct)
        frontend_times.append(result.frontend_elapsed_us)
        inference_times.append(result.inference_elapsed_us)
        output_rows.append(
            {
                "manifest_index": manifest_index,
                "sample_id": manifest_row.get(
                    "sample_id", manifest_row.get("packet_id", "")
                ),
                "recording_index": manifest_row.get("recording_index", ""),
                "recording_id": manifest_row.get("recording_id", ""),
                "source_dataset": manifest_row.get("source_dataset", ""),
                "source_recording_id": manifest_row.get(
                    "source_recording_id", ""
                ),
                "file": manifest_row["file"],
                "expected_label": expected_label,
                "expected_species": manifest_row.get("species", ""),
                "predicted_index": result.inference.predicted_index,
                "predicted_label": info.labels[result.inference.predicted_index],
                "activation": ACTIVATION_NAMES.get(
                    info.activation_id, f"unknown_{info.activation_id}"
                ),
                "active_class_mask": f"0x{result.inference.active_class_mask:08x}",
                "correct": "" if is_correct is None else int(is_correct),
                "windows": result.windows,
                "frontend_elapsed_us": result.frontend_elapsed_us,
                "inference_elapsed_us": result.inference_elapsed_us,
                "total_compute_elapsed_us": result.inference.elapsed_us,
                "scores": json.dumps(list(result.inference.scores), separators=(",", ":")),
                "raw_output_int8": json.dumps(
                    list(
                        struct.unpack(
                            f"<{len(result.inference.raw_output)}b",
                            result.inference.raw_output,
                        )
                    ),
                    separators=(",", ":"),
                ),
            }
        )
        print(
            f"[{selection_index + 1}/{len(selected_indices)}] "
            f"row {manifest_index} {wav_path.name}: "
            f"{result.inference.predicted_index} "
            f"{info.labels[result.inference.predicted_index]}",
            file=sys.stderr,
        )

    report = {
        "manifest_indices": selected_indices,
        "recordings": len(output_rows),
        "labelled_recordings": labelled,
        "correct_recordings": correct,
        "accuracy": correct / labelled if labelled else None,
        "frontend_elapsed_us_median": statistics.median(frontend_times),
        "inference_elapsed_us_median": statistics.median(inference_times),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=tuple(output_rows[0]))
            writer.writeheader()
            writer.writerows(output_rows)
        print(f"wrote per-recording results: {args.output}")
    return True


def selected_modes(mode: str) -> tuple[str, ...]:
    return ("f32", "native") if mode == "both" else (mode,)


def run_one(
    np: Any,
    port: Any,
    args: argparse.Namespace,
    info: ModelInfo,
    samples: Any,
    sequence: int,
) -> None:
    if args.index < 0 or args.index >= len(samples):
        raise ProtocolError(f"--index {args.index} is outside 0..{len(samples) - 1}")
    sample = samples[args.index]
    reference = (
        reference_output(np, create_reference_interpreter(args.tflite, info), sample, info)
        if args.tflite
        else None
    )
    output: dict[str, Any] = {"sample_index": args.index}
    for offset, mode in enumerate(selected_modes(args.mode)):
        result = run_board(np, port, sample, info, mode, sequence + offset, args.timeout)
        value = result_dict(result, info)
        if reference is not None:
            board_raw = raw_int8(np, result)
            difference = np.abs(board_raw.astype(np.int16) - reference.astype(np.int16))
            value["reference_raw_int8"] = reference.tolist()
            value["max_lsb_error"] = int(difference.max(initial=0))
            value["reference_argmax"] = int(np.argmax(reference))
        output[mode] = value
    print(json.dumps(output, ensure_ascii=False, indent=2))


def run_sweep(
    np: Any,
    port: Any,
    args: argparse.Namespace,
    info: ModelInfo,
    samples: Any,
    sequence: int,
) -> bool:
    if args.start < 0 or args.start >= len(samples):
        raise ProtocolError(f"--start {args.start} is outside 0..{len(samples) - 1}")
    stop = len(samples) if args.count == 0 else min(len(samples), args.start + args.count)
    if args.count < 0:
        raise ProtocolError("--count cannot be negative")
    modes = selected_modes(args.mode)
    interpreter = create_reference_interpreter(args.tflite, info) if args.tflite else None
    summary = {
        mode: {
            "samples": 0,
            "prediction_mismatches": 0,
            "max_lsb_error": 0,
            "elapsed_us": [],
        }
        for mode in modes
    }
    cross_mode = (
        {
            "samples": 0,
            "prediction_mismatches": 0,
            "max_lsb_error": 0,
        }
        if modes == ("f32", "native")
        else None
    )
    result_rows: list[dict[str, Any]] = []
    request_sequence = sequence
    for index in range(args.start, stop):
        sample = samples[index]
        board_results: dict[str, InferenceResult] = {}
        reference = (
            reference_output(np, interpreter, sample, info) if interpreter is not None else None
        )
        for mode in modes:
            result = run_board(
                np, port, sample, info, mode, request_sequence, args.timeout
            )
            board_results[mode] = result
            request_sequence += 1
            stats = summary[mode]
            stats["samples"] += 1
            stats["elapsed_us"].append(result.elapsed_us)
            result_rows.append(
                {
                    "sample_index": index,
                    "mode": mode,
                    "predicted_index": result.predicted_index,
                    "predicted_label": (
                        info.labels[result.predicted_index]
                        if 0 <= result.predicted_index < len(info.labels)
                        else ""
                    ),
                    "active_class_mask": f"0x{result.active_class_mask:08x}",
                    "cycles": result.cycles,
                    "elapsed_us": result.elapsed_us,
                    "scores": json.dumps(list(result.scores), separators=(",", ":")),
                    "raw_output_int8": json.dumps(
                        raw_int8(np, result).tolist(), separators=(",", ":")
                    ),
                    "reference_raw_int8": (
                        json.dumps(reference.tolist(), separators=(",", ":"))
                        if reference is not None
                        else ""
                    ),
                }
            )
            if reference is not None:
                board_raw = raw_int8(np, result)
                difference = np.abs(board_raw.astype(np.int16) - reference.astype(np.int16))
                stats["max_lsb_error"] = max(
                    stats["max_lsb_error"], int(difference.max(initial=0))
                )
                if result.predicted_index != int(np.argmax(reference)):
                    stats["prediction_mismatches"] += 1
        if cross_mode is not None:
            f32_result = board_results["f32"]
            native_result = board_results["native"]
            difference = np.abs(
                raw_int8(np, f32_result).astype(np.int16)
                - raw_int8(np, native_result).astype(np.int16)
            )
            cross_mode["samples"] += 1
            cross_mode["max_lsb_error"] = max(
                cross_mode["max_lsb_error"], int(difference.max(initial=0))
            )
            if f32_result.predicted_index != native_result.predicted_index:
                cross_mode["prediction_mismatches"] += 1

    passed = True
    report: dict[str, Any] = {
        "range": [args.start, stop],
        "reference_checked": interpreter is not None,
        "modes": {},
    }
    for mode, stats in summary.items():
        latencies = stats.pop("elapsed_us")
        mode_passed = (
            stats["prediction_mismatches"] == 0
            and stats["max_lsb_error"] <= args.max_lsb_error
        )
        if interpreter is None:
            mode_passed = True
        passed = passed and mode_passed
        report["modes"][mode] = {
            **stats,
            "elapsed_us_min": min(latencies),
            "elapsed_us_median": statistics.median(latencies),
            "elapsed_us_max": max(latencies),
            "passed": mode_passed,
        }
    if cross_mode is not None:
        cross_mode["passed"] = (
            cross_mode["prediction_mismatches"] == 0
            and cross_mode["max_lsb_error"] == 0
        )
        passed = passed and cross_mode["passed"]
        report["f32_vs_native"] = cross_mode
    print(json.dumps(report, ensure_ascii=False, indent=2))
    output_path = getattr(args, "output", None)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=tuple(result_rows[0]))
            writer.writeheader()
            writer.writerows(result_rows)
        print(f"wrote per-sample results: {output_path}")
    return passed


def main() -> int:
    args = parse_args()
    try:
        np, serial = require_dependencies()
        with serial.Serial(
            args.port,
            baudrate=args.baud,
            timeout=min(max(args.timeout / 10.0, 0.05), 0.5),
            write_timeout=args.timeout,
        ) as port:
            sequence = (time.monotonic_ns() & 0x7FFFFFFF) or 1
            info = get_info(port, args.timeout, sequence)
            if args.action == "info":
                print(json.dumps(info.as_dict(), ensure_ascii=False, indent=2))
                return 0
            if args.action == "audio-run":
                result, features, _ = run_audio_board(
                    np,
                    port,
                    args.input,
                    info,
                    sequence + 1,
                    args.timeout,
                    args.chunk_samples,
                    get_feature=args.dump_feature is not None,
                )
                if args.dump_feature is not None:
                    args.dump_feature.parent.mkdir(parents=True, exist_ok=True)
                    np.save(args.dump_feature, features)
                output = audio_result_dict(result, info, args.input)
                if args.dump_feature is not None:
                    output["dump_feature"] = str(args.dump_feature)
                print(json.dumps(output, ensure_ascii=False, indent=2))
                return 0
            if args.action == "audio-sweep":
                passed = run_audio_sweep(
                    np, port, args, info, sequence + 1
                )
                return 0 if passed else 1
            if args.action == "smoke":
                samples = make_smoke_samples(np, info)
                args.start = 0
                args.count = 0
                passed = run_sweep(np, port, args, info, samples, sequence + 1)
                return 0 if passed else 1
            samples = load_samples(np, args.input, info)
            if args.action == "run":
                run_one(np, port, args, info, samples, sequence + 1)
                return 0
            passed = run_sweep(np, port, args, info, samples, sequence + 1)
            return 0 if passed else 1
    except (ProtocolError, OSError) as exc:
        print(f"serial model client error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
