#!/usr/bin/env python3
"""Configure and build every directly flashable STM32_deploy application."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


SOURCE_DIR = Path(__file__).resolve().parent.parent
APPLICATIONS = ("serial", "microphone_test", "cca02m2_test")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=SOURCE_DIR)
    parser.add_argument("--build-root", type=Path, default=Path("build/linux-all"))
    parser.add_argument("--build-type", choices=("Debug", "Release"), default="Release")
    parser.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1))
    parser.add_argument(
        "--application",
        action="append",
        choices=APPLICATIONS,
        help="build only this application; repeat for more than one",
    )
    parser.add_argument(
        "--strict-toolchain",
        action="store_true",
        help="require GCC 14.2.1 (the Arm GNU 14.2.Rel1 baseline)",
    )
    return parser.parse_args()


def run(command: list[str], cwd: Path) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=cwd, check=True)


def capture(command: list[str], cwd: Path) -> str:
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    ).stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    args = parse_args()
    source = args.source_dir.resolve()
    build_root = args.build_root
    if not build_root.is_absolute():
        build_root = source / build_root
    build_root = build_root.resolve()
    applications = tuple(dict.fromkeys(args.application or APPLICATIONS))
    if args.jobs < 1:
        raise SystemExit("--jobs must be at least 1")

    preflight = [
        sys.executable,
        str(source / "tools/check_linux_toolchain.py"),
        "--source-dir",
        str(source),
        "--profile",
        "build",
    ]
    if args.strict_toolchain:
        preflight.append("--strict-toolchain")
    run(preflight, source)

    artifacts: list[dict[str, object]] = []
    for application in applications:
        build_dir = build_root / application
        run(
            [
                "cmake",
                "-S",
                str(source),
                "-B",
                str(build_dir),
                f"-DCMAKE_BUILD_TYPE={args.build_type}",
                f"-DSTM32_DEPLOY_APP={application}",
            ],
            source,
        )
        run(["cmake", "--build", str(build_dir), "--parallel", str(args.jobs)], source)
        for suffix in ("elf", "hex", "bin"):
            artifact = build_dir / f"STM32_deploy.{suffix}"
            if not artifact.is_file():
                raise RuntimeError(f"build did not produce {artifact}")
            artifacts.append(
                {
                    "application": application,
                    "format": suffix,
                    "path": str(artifact.relative_to(source)),
                    "bytes": artifact.stat().st_size,
                    "sha256": sha256(artifact),
                }
            )

    compiler = "arm-none-eabi-gcc"
    toolchain_root = os.environ.get("ARM_GNU_TOOLCHAIN_ROOT")
    if toolchain_root:
        compiler = str(Path(toolchain_root).expanduser() / "bin" / compiler)
    source_status = capture(
        ["git", "status", "--porcelain", "--untracked-files=normal"], source
    )
    manifest = {
        "schema_version": 1,
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source": {
            "commit": capture(["git", "rev-parse", "HEAD"], source),
            "dirty": bool(source_status),
            "tflite_micro_commit": capture(
                ["git", "rev-parse", "HEAD"], source / "Drivers/tflite-micro"
            ),
        },
        "toolchain": {
            "arm_gcc": capture([compiler, "--version"], source).splitlines()[0],
            "cmake": capture(["cmake", "--version"], source).splitlines()[0],
            "python": platform.python_version(),
        },
        "build_type": args.build_type,
        "applications": list(applications),
        "artifacts": artifacts,
    }
    manifest_path = build_root / "build_manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built {len(applications)} application(s); manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
