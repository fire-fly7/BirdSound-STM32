#!/usr/bin/env python3
"""Build and package every strict-INT8 Model_train experiment for STM32."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


TENSOR_ARENA_BYTES = 98_304

GROUPS = (
    ("01_zero_shot_strict", "INT8_quantization_8class", "zero_shot"),
    ("02_db3v_strict", "DB3V_strict_INT8_quantization_8class", None),
    ("03_birdset_strict", "BirdSet_strict_INT8_quantization_8class", None),
)

BUILD_INPUT_EXCLUDED_PREFIXES = ("docs/", "evidence/", "firmware/")
BUILD_INPUT_EXCLUDED_FILES = {".gitignore", "README.md"}

CORE_EXPERIMENTS = {
    "zero_shot_mfcc": "零样本特征对比：MFCC",
    "zero_shot_logmel": "零样本特征对比：LogMel（默认基准）",
    "zero_shot_pcen": "零样本特征对比：PCEN/PTQ退化对照",
    "db3v_strict_10shot_logmel_head_only_seed_42": "DB3V推荐链路 seed 42",
    "db3v_strict_10shot_logmel_head_only_seed_123": "DB3V推荐链路 seed 123",
    "db3v_strict_10shot_logmel_head_only_seed_2026": "DB3V推荐链路 seed 2026",
    "birdset_strict_20shot_logmel_head_only_seed_42": "BirdSet均衡链路 seed 42",
    "birdset_strict_20shot_logmel_head_only_seed_123": "BirdSet均衡链路 seed 123",
    "birdset_strict_20shot_logmel_head_only_seed_2026": "BirdSet均衡链路 seed 2026",
    "birdset_strict_20shot_mfcc_bn_head_replay_seed_42": "BirdSet量化稳定链路 seed 42",
    "birdset_strict_20shot_mfcc_bn_head_replay_seed_123": "BirdSet量化稳定链路 seed 123",
    "birdset_strict_20shot_mfcc_bn_head_replay_seed_2026": "BirdSet量化稳定链路 seed 2026",
}


class PackageError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-train", required=True, type=Path)
    parser.add_argument("--source-dir", type=Path, default=Path(__file__).resolve().parent.parent)
    parser.add_argument("--build-dir", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--jobs", type=int, default=min(os.cpu_count() or 2, 4))
    parser.add_argument("--include-elf", action="store_true")
    parser.add_argument(
        "--chain",
        action="append",
        dest="chains",
        help="build only an exact chain_id; may be repeated",
    )
    return parser.parse_args()


def run(
    command: list[str],
    cwd: Path,
    *,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.STDOUT if capture else None,
    )


def git_value(repo: Path, *arguments: str) -> str:
    result = run(["git", *arguments], repo)
    if result.returncode != 0:
        raise PackageError(f"git {' '.join(arguments)} failed:\n{result.stdout}")
    return result.stdout.strip()


def git_bytes(repo: Path, *arguments: str) -> bytes:
    result = subprocess.run(
        ["git", *arguments],
        cwd=repo,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    if result.returncode != 0:
        raise PackageError(
            f"git {' '.join(arguments)} failed:\n"
            f"{result.stdout.decode('utf-8', errors='replace')}"
        )
    return result.stdout


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_inputs_sha256(repo: Path) -> tuple[str, list[dict[str, str]]]:
    """Hash tracked build inputs by Git object ID, including gitlinks."""
    records: list[dict[str, str]] = []
    for entry in git_bytes(repo, "ls-files", "-s", "-z").split(b"\0"):
        if not entry:
            continue
        metadata, raw_path = entry.split(b"\t", 1)
        mode, object_id, stage = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        if stage != "0":
            raise PackageError(f"unmerged build input in Git index: {path}")
        if path in BUILD_INPUT_EXCLUDED_FILES or path.startswith(
            BUILD_INPUT_EXCLUDED_PREFIXES
        ):
            continue
        records.append({"path": path, "mode": mode, "object_id": object_id})
    digest = hashlib.sha256()
    for record in records:
        digest.update(record["path"].encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(record["mode"].encode("ascii"))
        digest.update(b"\0")
        digest.update(record["object_id"].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest(), records


def checked_submodules(repo: Path) -> list[dict[str, str]]:
    output = git_bytes(repo, "submodule", "status", "--recursive").decode(
        "utf-8", errors="replace"
    )
    submodules: list[dict[str, str]] = []
    for line in output.splitlines():
        if not line:
            continue
        state = line[0]
        fields = line[1:].split()
        if state != " " or len(fields) < 2:
            raise PackageError(
                "all submodules must be initialized at the recorded commit; "
                f"got {line!r}"
            )
        submodules.append({"path": fields[1], "commit": fields[0]})
    if not any(item["path"] == "Drivers/tflite-micro" for item in submodules):
        raise PackageError("Drivers/tflite-micro is not an initialized submodule")
    return submodules


def command_version(command: list[str], cwd: Path) -> str:
    result = run(command, cwd)
    if result.returncode != 0 or not result.stdout.strip():
        raise PackageError(
            f"cannot record tool version for {' '.join(command)}:\n{result.stdout}"
        )
    return result.stdout.strip().splitlines()[0]


def coerce(value: str) -> Any:
    if value == "":
        return None
    if value == "True":
        return True
    if value == "False":
        return False
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def load_experiments(model_train: Path) -> list[dict[str, Any]]:
    experiments_root = model_train / "src" / "experiments"
    experiments: list[dict[str, Any]] = []
    seen: set[str] = set()
    for package_group, source_group, family_filter in GROUPS:
        summary_path = experiments_root / source_group / "summary.csv"
        try:
            with summary_path.open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
        except OSError as exc:
            raise PackageError(f"cannot read {summary_path}: {exc}") from exc
        if family_filter is not None:
            rows = [row for row in rows if row.get("family") == family_filter]
        summary_chains = {row.get("chain_id", "") for row in rows}
        exported_chains = {
            path.parent.name
            for path in (experiments_root / source_group / "models").glob(
                "*/DS_CNN_Model.int8.tflite"
            )
        }
        if family_filter is not None:
            exported_chains = {
                chain_id
                for chain_id in exported_chains
                if chain_id.startswith(f"{family_filter}_")
            }
        if summary_chains != exported_chains:
            raise PackageError(
                f"summary/model mismatch in {source_group}: "
                f"summary_only={sorted(summary_chains - exported_chains)}, "
                f"model_only={sorted(exported_chains - summary_chains)}"
            )
        for raw_row in rows:
            chain_id = raw_row.get("chain_id", "")
            if not chain_id or chain_id in seen:
                raise PackageError(f"invalid or duplicate chain_id {chain_id!r}")
            seen.add(chain_id)
            model_dir = experiments_root / source_group / "models" / chain_id
            tflite = model_dir / "DS_CNN_Model.int8.tflite"
            metadata = model_dir / "DS_CNN_Model.int8_metadata.json"
            if not tflite.is_file() or not metadata.is_file():
                raise PackageError(f"missing model export for {chain_id}: {model_dir}")
            experiments.append(
                {
                    "chain_id": chain_id,
                    "package_group": package_group,
                    "source_group": source_group,
                    "tflite": tflite,
                    "metadata": metadata,
                    "metrics": {key: coerce(value) for key, value in raw_row.items()},
                }
            )
    return experiments


def copy_with_record(
    source: Path,
    destination: Path,
    records: dict[str, dict[str, Any]],
) -> None:
    shutil.copy2(source, destination)
    records[destination.name] = {
        "bytes": destination.stat().st_size,
        "sha256": sha256(destination),
    }


def metric_percent(metrics: dict[str, Any], name: str) -> str:
    value = metrics.get(name)
    return "" if not isinstance(value, (int, float)) else f"{100.0 * value:.2f}"


def write_json(path: Path, value: Any) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def package_one(
    experiment: dict[str, Any],
    *,
    source_dir: Path,
    build_dir: Path,
    staging_dir: Path,
    label_map: Path,
    model_train_commit: str,
    firmware_commit: str,
    firmware_tree: str,
    firmware_build_inputs: str,
    submodules: list[dict[str, str]],
    toolchain: dict[str, str],
    jobs: int,
    include_elf: bool,
) -> dict[str, Any]:
    chain_id = experiment["chain_id"]
    destination = (
        staging_dir / "experiments" / experiment["package_group"] / chain_id
    )
    destination.mkdir(parents=True)

    configure = [
        "cmake",
        "-S",
        str(source_dir),
        "-B",
        str(build_dir),
        "-DCMAKE_BUILD_TYPE=Release",
        f"-DSTM32_MODEL_TFLITE={experiment['tflite']}",
        f"-DSTM32_MODEL_LABEL_MAP={label_map}",
        f"-DSTM32_MODEL_SOURCE_COMMIT={model_train_commit}",
        f"-DSTM32_MODEL_ARENA_BYTES={TENSOR_ARENA_BYTES}",
    ]
    configured = run(configure, source_dir)
    if configured.returncode != 0:
        raise PackageError(f"CMake configure failed for {chain_id}:\n{configured.stdout}")
    built = run(["cmake", "--build", str(build_dir), f"-j{jobs}"], source_dir)
    if built.returncode != 0:
        raise PackageError(f"build failed for {chain_id}:\n{built.stdout}")

    bundle_path = build_dir / "generated" / "model" / "model_bundle.json"
    try:
        bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError(f"cannot read generated bundle for {chain_id}: {exc}") from exc
    model_digest = sha256(experiment["tflite"])
    if bundle.get("sha256") != model_digest:
        raise PackageError(f"generated model hash mismatch for {chain_id}")

    files: dict[str, dict[str, Any]] = {}
    copy_with_record(build_dir / "STM32_deploy.hex", destination / "STM32_deploy.hex", files)
    copy_with_record(build_dir / "STM32_deploy.bin", destination / "STM32_deploy.bin", files)
    if include_elf:
        copy_with_record(build_dir / "STM32_deploy.elf", destination / "STM32_deploy.elf", files)
    copy_with_record(experiment["tflite"], destination / "model.tflite", files)
    copy_with_record(experiment["metadata"], destination / "model_metadata.json", files)

    bundle["source_tflite"] = (
        f"Model_train/src/experiments/{experiment['source_group']}/models/"
        f"{chain_id}/DS_CNN_Model.int8.tflite"
    )
    bundle["source_metadata"] = (
        f"Model_train/src/experiments/{experiment['source_group']}/models/"
        f"{chain_id}/DS_CNN_Model.int8_metadata.json"
    )
    portable_bundle_path = destination / "model_bundle.json"
    write_json(portable_bundle_path, bundle)
    files[portable_bundle_path.name] = {
        "bytes": portable_bundle_path.stat().st_size,
        "sha256": sha256(portable_bundle_path),
    }

    manifest = {
        "schema_version": 2,
        "chain_id": chain_id,
        "group": experiment["package_group"],
        "source_group": experiment["source_group"],
        "core_experiment": chain_id in CORE_EXPERIMENTS,
        "core_reason": CORE_EXPERIMENTS.get(chain_id),
        "feature": bundle["feature"],
        "activation": bundle["activation"],
        "input_shape": bundle["input_shape"],
        "input_scale": bundle["input_scale"],
        "input_zero_point": bundle["input_zero_point"],
        "output_scale": bundle["output_scale"],
        "output_zero_point": bundle["output_zero_point"],
        "model_sha256": model_digest,
        "model_train_commit": model_train_commit,
        "firmware_source_commit": firmware_commit,
        "firmware_source_tree": firmware_tree,
        "firmware_source_dirty": False,
        "firmware_build_inputs_sha256": firmware_build_inputs,
        "submodules": submodules,
        "toolchain": toolchain,
        "build_type": "Release",
        "metrics": experiment["metrics"],
        "files": files,
    }
    write_json(destination / "experiment.json", manifest)
    return manifest


def render_readme(index: list[dict[str, Any]], model_train_commit: str) -> str:
    core = [entry for entry in index if entry["core_experiment"]]
    rows = []
    for entry in core:
        metrics = entry["metrics"]
        rows.append(
            "| `{}` | {} | {} | {} | {} | {} |".format(
                entry["chain_id"],
                entry["feature"],
                entry["activation"],
                metric_percent(metrics, "xeno_int8_macro_f1"),
                metric_percent(metrics, "birdset_int8_top1"),
                metric_percent(metrics, "db3v_int8_macro_f1"),
            )
        )
    core_table = "\n".join(rows)
    return f"""# STM32_deploy 可烧录实验固件包

训练模型来源：`fire-fly7/Model_train@{model_train_commit}`。
本包包含 {len(index)} 个 strict-INT8 实验固件；每个实验目录均带有可直接烧录的
`STM32_deploy.hex`/`STM32_deploy.bin`、对应的桌面 `model.tflite`、量化 metadata、
模型 bundle 和包含文件哈希的 `experiment.json`。

固件 Tensor Arena 配置为 96 KiB。`provenance.json` 记录干净源码提交、源码树、
构建输入摘要、TFLM 子模块提交和工具链版本；板端实际 Arena 用量必须以配套验证
结果中的原始 `info.json`/`info.log` 为准。

## 目录

- `experiments/01_zero_shot_strict/`：3 个当前零样本严格 INT8 基准；
- `experiments/02_db3v_strict/`：27 个 DB3V 严格多种子实验；
- `experiments/03_birdset_strict/`：27 个 BirdSet 严格多种子实验；
- `INDEX.csv`/`index.json`：全部固件接口、指标、路径与哈希；
- `provenance.json`：可机器核验的源码、子模块和工具链来源；
- `CORE_EXPERIMENTS.txt`：建议优先烧录的实验路径；
- `SHA256SUMS`：整个包的文件校验值。

本包只读取 Model_train 当前三个正式 strict INT8 目录，不包含已删除的旧单种子、
旧 few-shot 或旧混合 INT8 链路。

## 推荐优先测试

指标为 Model_train 报告中的 INT8 百分比，不是本地实板测量值。

| chain_id | 特征 | 激活 | Xeno Macro-F1 | BirdSet Top-1 | DB3V Macro-F1 |
| --- | --- | --- | ---: | ---: | ---: |
{core_table}

## 烧录

以某个实验为例：

```sh
python3 tools/flash_experiment.py \\
  experiments/01_zero_shot_strict/zero_shot_logmel/STM32_deploy.hex
```

也可直接使用 OpenOCD：

```sh
openocd -f flash.cfg -c \\
  "program experiments/01_zero_shot_strict/zero_shot_logmel/STM32_deploy.hex verify reset exit"
```

## 原始录音板端全链路

烧录后查询模型：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 info
```

发送单声道 16-kHz PCM16 WAV。PC 只传输原始 PCM；一秒切窗、MFCC/LogMel/PCEN、
输入量化、逐窗 INT8 推理和录音级平均分全部由板端完成：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 --timeout 20 audio-run \\
  --input /path/to/recording.wav
```

全部模型批量烧录和原始 WAV 板端对标：

```sh
python3 tools/run_board_benchmark.py validate-testset \\
  --testset /path/to/board_testset

python3 tools/run_board_benchmark.py run \\
  --testset /path/to/board_testset \\
  --scope all --count 64 --port /dev/ttyACM0 \\
  --run-id all_models_64 --continue-on-error
```

三种特征前端均与 Model_train 定义绑定，固件根据自身 `feature` 自动选择。
麦克风/SAI/DMA 采集不在此固件中，串口原始录音实验与麦克风硬件保持分离。

## 无数据集张量冒烟对拍

无需 `.npy` 即可用 5 个确定性张量核对 PC TFLite 与板端 TFLM：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 smoke \\
  --mode both \\
  --tflite experiments/01_zero_shot_strict/zero_shot_logmel/model.tflite
```

## 特征张量回归实验

使用与固件 `feature` 完全匹配的 Model_train 测试特征。LogMel 和 PCEN 即使形状
都是 `32×40×1` 也不能混用。

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 sweep \\
  --input /path/to/matching_test_data.npy \\
  --mode both \\
  --tflite /path/to/this/experiment/model.tflite \\
  --output board_results.csv
```

同一特征链路之间使用相同样本索引，再比较 `board_results.csv`。softmax 链路主要
比较 `predicted_index`；sigmoid/BirdSet 链路还需比较 `active_class_mask`。跨特征
比较必须由同一批原始音频分别生成 MFCC、LogMel、PCEN，不能直接复用一个 `.npy`。
"""


def write_indexes(
    staging_dir: Path,
    index: list[dict[str, Any]],
    model_train_commit: str,
    provenance: dict[str, Any],
) -> None:
    index_path = staging_dir / "index.json"
    write_json(index_path, index)
    write_json(staging_dir / "provenance.json", provenance)

    fields = (
        "chain_id",
        "group",
        "core_experiment",
        "core_reason",
        "feature",
        "activation",
        "input_shape",
        "model_sha256",
        "xeno_int8_macro_f1",
        "birdset_int8_top1",
        "birdset_int8_singleton_macro_f1",
        "db3v_int8_macro_f1",
        "hex_path",
    )
    with (staging_dir / "INDEX.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for entry in index:
            metrics = entry["metrics"]
            writer.writerow(
                {
                    "chain_id": entry["chain_id"],
                    "group": entry["group"],
                    "core_experiment": entry["core_experiment"],
                    "core_reason": entry["core_reason"] or "",
                    "feature": entry["feature"],
                    "activation": entry["activation"],
                    "input_shape": json.dumps(entry["input_shape"], separators=(",", ":")),
                    "model_sha256": entry["model_sha256"],
                    "xeno_int8_macro_f1": metrics.get("xeno_int8_macro_f1"),
                    "birdset_int8_top1": metrics.get("birdset_int8_top1"),
                    "birdset_int8_singleton_macro_f1": metrics.get(
                        "birdset_int8_singleton_macro_f1"
                    ),
                    "db3v_int8_macro_f1": metrics.get("db3v_int8_macro_f1"),
                    "hex_path": (
                        f"experiments/{entry['group']}/{entry['chain_id']}/"
                        "STM32_deploy.hex"
                    ),
                }
            )

    core_paths = [
        (
            f"experiments/{entry['group']}/{entry['chain_id']}/STM32_deploy.hex"
            f"\t{entry['core_reason']}"
        )
        for entry in index
        if entry["core_experiment"]
    ]
    (staging_dir / "CORE_EXPERIMENTS.txt").write_text(
        "\n".join(core_paths) + "\n", encoding="utf-8"
    )
    (staging_dir / "README.md").write_text(
        render_readme(index, model_train_commit),
        encoding="utf-8",
    )


def write_checksums(root: Path) -> None:
    checksum_path = root / "SHA256SUMS"
    lines = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path == checksum_path:
            continue
        lines.append(f"{sha256(path)}  {path.relative_to(root).as_posix()}")
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def create_zip(package_dir: Path) -> Path:
    zip_path = package_dir.with_suffix(".zip")
    if zip_path.exists():
        raise PackageError(f"refusing to replace existing archive: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in package_dir.rglob("*") if item.is_file()):
            archive.write(path, Path(package_dir.name) / path.relative_to(package_dir))
    return zip_path


def main() -> int:
    args = parse_args()
    source_dir = args.source_dir.resolve()
    model_train = args.model_train.resolve()
    output_dir = args.output_dir.resolve()
    build_dir = (
        args.build_dir.resolve()
        if args.build_dir
        else source_dir / "build" / "experiment-firmwares"
    )
    staging_dir = output_dir.with_name(output_dir.name + ".tmp")

    try:
        if args.jobs <= 0:
            raise PackageError("--jobs must be positive")
        if output_dir.exists() or staging_dir.exists():
            raise PackageError(
                f"refusing to replace existing package/staging directory: {output_dir}"
            )
        model_commit = git_value(model_train, "rev-parse", "HEAD")
        if git_value(model_train, "status", "--porcelain"):
            raise PackageError(
                "Model_train worktree is dirty; commit the exact model state before packaging"
            )
        firmware_commit = git_value(source_dir, "rev-parse", "HEAD")
        if git_value(source_dir, "status", "--porcelain"):
            raise PackageError(
                "firmware worktree is dirty; commit the exact source state "
                "before packaging"
            )
        firmware_tree = git_value(source_dir, "rev-parse", "HEAD^{tree}")
        firmware_build_inputs, build_input_records = build_inputs_sha256(source_dir)
        submodules = checked_submodules(source_dir)
        toolchain = {
            "python": sys.version.split()[0],
            "cmake": command_version(["cmake", "--version"], source_dir),
            "arm_none_eabi_gcc": command_version(
                ["arm-none-eabi-gcc", "--version"], source_dir
            ),
        }
        label_map = model_train / "src" / "dataset_processing" / "label_map_8class.json"
        if not label_map.is_file():
            raise PackageError(f"label map does not exist: {label_map}")

        experiments = load_experiments(model_train)
        if args.chains:
            requested = set(args.chains)
            experiments = [
                experiment
                for experiment in experiments
                if experiment["chain_id"] in requested
            ]
            missing = requested - {experiment["chain_id"] for experiment in experiments}
            if missing:
                raise PackageError(f"unknown chain_id values: {sorted(missing)}")
        provenance = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "firmware_source_commit": firmware_commit,
            "firmware_source_tree": firmware_tree,
            "firmware_source_dirty": False,
            "firmware_build_inputs_sha256": firmware_build_inputs,
            "firmware_build_inputs": build_input_records,
            "model_train_commit": model_commit,
            "model_train_dirty": False,
            "submodules": submodules,
            "toolchain": toolchain,
            "build_type": "Release",
            "tensor_arena_bytes": TENSOR_ARENA_BYTES,
        }
        staging_dir.mkdir(parents=True)
        (staging_dir / "tools").mkdir()
        shutil.copy2(source_dir / "flash.cfg", staging_dir / "flash.cfg")
        for name in (
            "build_experiment_firmwares.py",
            "flash_experiment.py",
            "run_board_benchmark.py",
            "serial_model_client.py",
            "verify_firmware_release.py",
            "requirements-serial.txt",
        ):
            shutil.copy2(source_dir / "tools" / name, staging_dir / "tools" / name)
        shutil.copy2(
            source_dir / "docs" / "BOARD_BENCHMARK_TESTSET.md",
            staging_dir / "BOARD_BENCHMARK_TESTSET.md",
        )

        index = []
        total = len(experiments)
        for number, experiment in enumerate(experiments, start=1):
            print(f"[{number:02d}/{total:02d}] {experiment['chain_id']}", flush=True)
            index.append(
                package_one(
                    experiment,
                    source_dir=source_dir,
                    build_dir=build_dir,
                    staging_dir=staging_dir,
                    label_map=label_map,
                    model_train_commit=model_commit,
                    firmware_commit=firmware_commit,
                    firmware_tree=firmware_tree,
                    firmware_build_inputs=firmware_build_inputs,
                    submodules=submodules,
                    toolchain=toolchain,
                    jobs=args.jobs,
                    include_elf=args.include_elf,
                )
            )

        provenance["firmwares"] = len(index)
        write_indexes(staging_dir, index, model_commit, provenance)
        write_checksums(staging_dir)
        staging_dir.replace(output_dir)
        zip_path = create_zip(output_dir)
        print(f"package: {output_dir}")
        print(f"archive: {zip_path}")
        print(f"firmwares: {len(index)}")
        return 0
    except PackageError as exc:
        print(f"experiment package error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
