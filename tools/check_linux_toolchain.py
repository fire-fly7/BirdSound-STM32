#!/usr/bin/env python3
"""Check the host, source checkout, and Python dependencies before building."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable


SOURCE_DIR = Path(__file__).resolve().parent.parent


@dataclass
class Check:
    name: str
    status: str
    detail: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=SOURCE_DIR,
        help="LED_TEST checkout (default: directory above this script)",
    )
    parser.add_argument(
        "--profile",
        choices=("build", "serial", "hardware", "all"),
        default="build",
        help="dependency set to validate",
    )
    parser.add_argument(
        "--strict-toolchain",
        action="store_true",
        help="require GCC 14.2.1, the Arm GNU 14.2.Rel1 baseline version",
    )
    parser.add_argument("--json", action="store_true", help="emit a JSON report")
    return parser.parse_args()


def version_tuple(value: str) -> tuple[int, ...]:
    match = re.search(r"(\d+(?:\.\d+)+)", value)
    return tuple(int(part) for part in match.group(1).split(".")) if match else ()


def command_output(command: list[str], cwd: Path) -> tuple[int, str]:
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
        )
    except OSError as error:
        return 127, str(error)
    return result.returncode, result.stdout.rstrip()


def add(checks: list[Check], name: str, ok: bool, detail: str) -> None:
    checks.append(Check(name, "PASS" if ok else "FAIL", detail))


def add_warning(checks: list[Check], name: str, detail: str) -> None:
    checks.append(Check(name, "WARN", detail))


def find_arm_tool(name: str) -> str | None:
    root = os.environ.get("ARM_GNU_TOOLCHAIN_ROOT")
    if root:
        candidate = Path(root).expanduser() / "bin" / name
        return str(candidate) if candidate.is_file() and os.access(candidate, os.X_OK) else None
    return shutil.which(name)


def check_command(
    checks: list[Check],
    source: Path,
    name: str,
    command: list[str],
    minimum: tuple[int, ...] | None = None,
) -> str:
    executable = shutil.which(command[0])
    if not executable:
        add(checks, name, False, f"{command[0]} is not on PATH")
        return ""
    code, output = command_output([executable, *command[1:]], source)
    first_line = output.splitlines()[0] if output else "no version output"
    ok = code == 0
    if minimum is not None:
        found = version_tuple(first_line)
        ok = ok and found >= minimum
        first_line += f" (required >= {'.'.join(map(str, minimum))})"
    add(checks, name, ok, first_line)
    return output


def installed_distribution(name: str) -> str | None:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_python_distribution(
    checks: list[Check],
    name: str,
    predicate: Callable[[tuple[int, ...]], bool],
    requirement: str,
) -> None:
    installed = installed_distribution(name)
    ok = installed is not None and predicate(version_tuple(installed))
    detail = f"{installed or 'not installed'} (required {requirement})"
    add(checks, f"python:{name}", ok, detail)


def check_submodule(checks: list[Check], source: Path) -> None:
    required = source / "Drivers/tflite-micro/tensorflow/lite/kernels/kernel_util.cc"
    add(
        checks,
        "tflite-micro sources",
        required.is_file(),
        str(required.relative_to(source)) if required.is_file() else "submodule content is missing",
    )
    code, output = command_output(["git", "submodule", "status", "--recursive"], source)
    lines = [line for line in output.splitlines() if line.strip()]
    clean = code == 0 and bool(lines) and all(line[0] == " " for line in lines)
    detail = "; ".join(line.strip() for line in lines) if lines else "no initialized submodule"
    add(checks, "submodule commit", clean, detail)


def main() -> int:
    args = parse_args()
    source = args.source_dir.resolve()
    checks: list[Check] = []

    add(checks, "host OS", sys.platform.startswith("linux"), platform.platform())
    machine = platform.machine().lower()
    add(
        checks,
        "host architecture",
        machine in ("x86_64", "amd64", "aarch64", "arm64"),
        f"{machine} (supported: x86_64, aarch64)",
    )
    add(
        checks,
        "Python",
        sys.version_info >= (3, 10),
        f"{platform.python_version()} (required >= 3.10)",
    )
    add(checks, "source directory", (source / "CMakeLists.txt").is_file(), str(source))
    check_command(checks, source, "Git", ["git", "--version"], (2, 20))
    check_command(checks, source, "CMake", ["cmake", "--version"], (3, 22))
    check_command(checks, source, "GNU Make", ["make", "--version"])

    compiler = find_arm_tool("arm-none-eabi-gcc")
    if compiler:
        code, output = command_output([compiler, "--version"], source)
        first_line = output.splitlines()[0] if output else "no version output"
        version_code, version_output = command_output(
            [compiler, "-dumpfullversion"], source
        )
        compiler_version = version_tuple(version_output)
        compiler_ok = code == 0 and version_code == 0 and bool(compiler_version)
        first_line += f" [GCC {version_output or 'unknown'}]"
        if args.strict_toolchain:
            compiler_ok = compiler_ok and compiler_version[:3] == (14, 2, 1)
            first_line += " (required GCC 14.2.1; releases use Arm 14.2.Rel1)"
        elif compiler_version[:3] != (14, 2, 1):
            add_warning(
                checks,
                "reproducible compiler",
                f"{first_line}; release evidence is standardized on 14.2.Rel1",
            )
        add(checks, "Arm C compiler", compiler_ok, first_line)
    else:
        add(
            checks,
            "Arm C compiler",
            False,
            "arm-none-eabi-gcc is missing from PATH/ARM_GNU_TOOLCHAIN_ROOT",
        )
    for tool in ("arm-none-eabi-g++", "arm-none-eabi-objcopy", "arm-none-eabi-size"):
        add(checks, tool, find_arm_tool(tool) is not None, find_arm_tool(tool) or "not found")

    if args.profile in ("build", "serial", "all"):
        check_submodule(checks, source)
        check_python_distribution(
            checks, "numpy", lambda value: value == (1, 26, 4), "== 1.26.4"
        )

    if args.profile in ("serial", "hardware", "all"):
        check_python_distribution(checks, "pyserial", lambda value: value >= (3, 5), ">= 3.5")
    if args.profile in ("serial", "all"):
        tensorflow_distribution = (
            "tensorflow" if machine in ("aarch64", "arm64") else "tensorflow-cpu"
        )
        check_python_distribution(
            checks,
            tensorflow_distribution,
            lambda value: value == (2, 19, 0),
            "== 2.19.0",
        )
    if args.profile in ("hardware", "all"):
        openocd = shutil.which("openocd")
        add(checks, "OpenOCD", openocd is not None, openocd or "not found on PATH")

    failures = sum(check.status == "FAIL" for check in checks)
    warnings = sum(check.status == "WARN" for check in checks)
    if args.json:
        print(
            json.dumps(
                {
                    "source_dir": str(source),
                    "profile": args.profile,
                    "ok": failures == 0,
                    "failures": failures,
                    "warnings": warnings,
                    "checks": [asdict(check) for check in checks],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        for check in checks:
            print(f"[{check.status:4}] {check.name}: {check.detail}")
        passes = sum(check.status == "PASS" for check in checks)
        print(f"summary: {passes} pass, {warnings} warning(s), {failures} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
