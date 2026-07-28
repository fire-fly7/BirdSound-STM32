#!/usr/bin/env python3
"""Verify and flash one packaged STM32_deploy experiment firmware."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


class FlashError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("firmware", type=Path, help=".hex, .bin, or .elf firmware file")
    parser.add_argument(
        "--config",
        type=Path,
        help="OpenOCD config; defaults to flash.cfg beside the package tools directory",
    )
    parser.add_argument("--openocd", default="openocd", help="OpenOCD executable")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def load_experiment(path: Path) -> dict[str, Any]:
    manifest_path = path.parent / "experiment.json"
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FlashError(f"cannot read {manifest_path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FlashError(f"{manifest_path} must contain a JSON object")
    return value


def verify_firmware(path: Path, experiment: dict[str, Any]) -> None:
    files = experiment.get("files")
    entry = files.get(path.name) if isinstance(files, dict) else None
    expected = entry.get("sha256") if isinstance(entry, dict) else None
    if not isinstance(expected, str):
        raise FlashError(f"{path.name} is not listed in experiment.json")
    try:
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise FlashError(f"cannot read {path}: {exc}") from exc
    if actual != expected:
        raise FlashError(f"{path.name} SHA-256 mismatch: expected {expected}, got {actual}")


def main() -> int:
    args = parse_args()
    try:
        firmware = args.firmware.resolve()
        if firmware.suffix.lower() not in {".hex", ".bin", ".elf"}:
            raise FlashError("firmware extension must be .hex, .bin, or .elf")
        experiment = load_experiment(firmware)
        verify_firmware(firmware, experiment)

        default_config = Path(__file__).resolve().parent.parent / "flash.cfg"
        config = (args.config or default_config).resolve()
        if not config.is_file():
            raise FlashError(f"OpenOCD config does not exist: {config}")
        if "}" in str(firmware):
            raise FlashError("firmware path cannot contain '}'")
        address = " 0x08000000" if firmware.suffix.lower() == ".bin" else ""
        program = f"program {{{firmware}}}{address} verify reset exit"
        command = [args.openocd, "-f", str(config), "-c", program]
        print("model:", experiment.get("chain_id", "unknown"))
        print("feature:", experiment.get("feature", "unknown"))
        print("firmware SHA-256 verified:", firmware.name)
        print("command:", " ".join(command))
        if args.dry_run:
            return 0
        if shutil.which(args.openocd) is None:
            raise FlashError(f"OpenOCD executable not found: {args.openocd}")
        return subprocess.run(command, check=False).returncode
    except FlashError as exc:
        print(f"flash experiment error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
