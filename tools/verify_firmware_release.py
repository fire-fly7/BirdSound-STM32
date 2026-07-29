#!/usr/bin/env python3
"""Verify firmware package hashes and reproducible-source provenance."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from build_experiment_firmwares import (
    PARITY_REFERENCE,
    PackageError,
    build_inputs_sha256,
    checked_submodules,
    git_value,
    sha256,
)


class VerificationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", required=True, type=Path)
    parser.add_argument(
        "--source-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
    )
    parser.add_argument("--model-train", type=Path)
    return parser.parse_args()


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise VerificationError(f"cannot read {path}: {exc}") from exc


def verify_checksum_list(pack: Path) -> int:
    checksum_path = pack / "SHA256SUMS"
    try:
        lines = checksum_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise VerificationError(f"cannot read {checksum_path}: {exc}") from exc
    checked = 0
    for number, line in enumerate(lines, start=1):
        try:
            expected, relative = line.split("  ", 1)
        except ValueError as exc:
            raise VerificationError(
                f"{checksum_path}:{number}: invalid checksum line"
            ) from exc
        path = (pack / relative).resolve()
        try:
            path.relative_to(pack)
        except ValueError as exc:
            raise VerificationError(f"checksum path escapes package: {relative}") from exc
        if not path.is_file() or sha256(path) != expected:
            raise VerificationError(f"checksum mismatch: {relative}")
        checked += 1
    return checked


def verify_experiments(pack: Path, provenance: dict[str, Any]) -> int:
    index = load_json(pack / "index.json")
    if not isinstance(index, list) or len(index) != provenance.get("firmwares"):
        raise VerificationError("index/provenance firmware count mismatch")
    expected_provenance = {
        key: provenance.get(key)
        for key in (
            "firmware_source_commit",
            "firmware_source_tree",
            "firmware_source_dirty",
            "firmware_build_inputs_sha256",
            "model_train_commit",
            "desktop_parity_reference",
            "submodules",
            "toolchain",
        )
    }
    for entry in index:
        if not isinstance(entry, dict):
            raise VerificationError("index contains a non-object entry")
        experiment_path = (
            pack
            / "experiments"
            / str(entry.get("group"))
            / str(entry.get("chain_id"))
            / "experiment.json"
        )
        experiment = load_json(experiment_path)
        actual = {key: experiment.get(key) for key in expected_provenance}
        if actual != expected_provenance:
            raise VerificationError(
                f"provenance mismatch in {entry.get('chain_id')}"
            )
        if experiment.get("firmware_source_dirty") is not False:
            raise VerificationError(
                f"dirty firmware source in {entry.get('chain_id')}"
            )
        if experiment.get("desktop_parity_reference") != PARITY_REFERENCE:
            raise VerificationError(
                f"unpinned desktop parity runtime in {entry.get('chain_id')}"
            )
        for name, record in experiment.get("files", {}).items():
            path = experiment_path.parent / name
            if (
                not isinstance(record, dict)
                or not path.is_file()
                or path.stat().st_size != record.get("bytes")
                or sha256(path) != record.get("sha256")
            ):
                raise VerificationError(
                    f"artifact record mismatch: {entry.get('chain_id')}/{name}"
                )
    return len(index)


def verify_source(source: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    if git_value(source, "status", "--porcelain"):
        raise VerificationError(f"source worktree is dirty: {source}")
    digest, records = build_inputs_sha256(source)
    if digest != provenance.get("firmware_build_inputs_sha256"):
        raise VerificationError(
            "current source build-input digest does not match the package"
        )
    if records != provenance.get("firmware_build_inputs"):
        raise VerificationError("current source build-input records do not match")
    submodules = checked_submodules(source)
    if submodules != provenance.get("submodules"):
        raise VerificationError("current submodule revisions do not match")
    head = git_value(source, "rev-parse", "HEAD")
    tree = git_value(source, "rev-parse", "HEAD^{tree}")
    return {
        "head": head,
        "head_matches": head == provenance.get("firmware_source_commit"),
        "tree": tree,
        "tree_matches": tree == provenance.get("firmware_source_tree"),
        "build_inputs_sha256": digest,
        "build_inputs_match": True,
    }


def main() -> int:
    args = parse_args()
    pack = args.pack.resolve()
    source = args.source_dir.resolve()
    try:
        provenance = load_json(pack / "provenance.json")
        if not isinstance(provenance, dict):
            raise VerificationError("provenance.json is not an object")
        checksum_files = verify_checksum_list(pack)
        firmwares = verify_experiments(pack, provenance)
        source_result = verify_source(source, provenance)
        model_train_result: dict[str, Any] | None = None
        if args.model_train is not None:
            model_train = args.model_train.resolve()
            if git_value(model_train, "status", "--porcelain"):
                raise VerificationError(f"Model_train worktree is dirty: {model_train}")
            head = git_value(model_train, "rev-parse", "HEAD")
            expected = provenance.get("model_train_commit")
            if head != expected:
                raise VerificationError(
                    f"Model_train HEAD {head} does not match {expected}"
                )
            model_train_result = {"head": head, "matches": True}
        print(
            json.dumps(
                {
                    "valid": True,
                    "pack": str(pack),
                    "firmwares": firmwares,
                    "checksum_files": checksum_files,
                    "source": source_result,
                    "model_train": model_train_result,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    except (VerificationError, PackageError, OSError) as exc:
        print(f"firmware release verification error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
