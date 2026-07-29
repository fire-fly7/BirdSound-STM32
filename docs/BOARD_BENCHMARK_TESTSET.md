# STM32 全模型板端对标测试集规格

## 1. 对标边界

测试链路固定为：

```text
磁盘中的最终 PCM16 WAV
  → PC 校验 RIFF/哈希并剥离 data chunk
  → UART 115200 发送原始 PCM
  → STM32 一秒窗口
  → STM32 MFCC / LogMel / PCEN
  → STM32 输入量化和 TFLite Micro INT8 推理
  → PC 保存分数、INT8 原始输出、预测和耗时
```

测试集不得包含 MFCC、LogMel、PCEN 或其他预计算特征。PC 端不得在发送时重采样、
归一化、预加重、降噪或修改采样值。麦克风采集不参与本实验。

## 2. 目录结构

测试集统一放在项目根目录的 `board_testset/`：

```text
board_testset/
├── manifest.csv
├── label_map.json
└── audio/
    ├── Agelaius_phoeniceus/
    ├── Cardinalis_cardinalis/
    ├── Certhia_americana/
    ├── Corvus_brachyrhynchos/
    ├── Setophaga_aestiva/
    ├── Setophaga_ruticilla/
    ├── Spinus_tristis/
    └── Turdus_migratorius/
```

`board_testset/` 是本地数据目录，已由 Git 忽略，不要提交音频或标签清单。

## 3. 标签顺序

`label_map.json` 必须与全部板端模型完全一致：

```json
{
  "Agelaius_phoeniceus": 0,
  "Cardinalis_cardinalis": 1,
  "Certhia_americana": 2,
  "Corvus_brachyrhynchos": 3,
  "Setophaga_aestiva": 4,
  "Setophaga_ruticilla": 5,
  "Spinus_tristis": 6,
  "Turdus_migratorius": 7
}
```

不得调整类别顺序或使用目录名自动推断标签。

## 4. WAV 硬性规格

每个测试项必须是一个独立的一秒 WAV：

| 项目 | 要求 |
| --- | --- |
| 容器 | RIFF/WAVE |
| 编码 | 未压缩 PCM16，小端有符号整数 |
| 通道 | 单声道 |
| 采样率 | 16,000 Hz |
| 帧数 | 恰好 16,000 |
| PCM payload | 恰好 32,000 bytes |
| 时长 | 恰好 1.000 秒 |
| 数值处理 | 最终文件不再做归一化、预加重、降噪或增益 |

不接受浮点 WAV、24/32-bit PCM、MP3、FLAC、立体声或非整秒数据。源录音如需
离线重采样，只能在数据集制作阶段完成一次；清单和哈希必须针对最终 16-kHz
PCM16 文件。

每条音频应由人工确认目标物种在这一秒内清晰可听，不能是静音，且不能同时包含
其他七类目标物种。环境噪声可以保留，因为它属于真实部署条件。

## 5. `manifest.csv`

文件编码为 UTF-8，首行必须至少包含以下列：

```csv
sample_id,file,label,species,source_dataset,source_recording_id,start_sample,duration_samples,split,annotation_status,mixed_species,leakage_check,pcm_sha256,wav_sha256
```

字段规则：

| 字段 | 规则 |
| --- | --- |
| `sample_id` | 全局唯一，只允许字母、数字、点、下划线和短横线 |
| `file` | 相对 `board_testset/` 的 POSIX 路径，不允许绝对路径和 `..` |
| `label` | `0..7`，必须与 `species` 和 `label_map.json` 一致 |
| `species` | 上述八个拉丁学名之一 |
| `source_dataset` | 来源数据集的稳定名称 |
| `source_recording_id` | 来源完整录音的稳定 ID |
| `start_sample` | 该一秒窗口在来源标准化录音中的起始采样点，非负整数 |
| `duration_samples` | 固定为 `16000` |
| `split` | 固定为 `board_test` |
| `annotation_status` | 固定为 `verified`，表示已人工复核 |
| `mixed_species` | 固定为 `none` |
| `leakage_check` | 固定为 `passed` |
| `pcm_sha256` | WAV `data` chunk 的 32,000 字节 SHA-256，小写十六进制 |
| `wav_sha256` | 完整 WAV 文件 SHA-256，小写十六进制 |

建议增加但不强制的审计字段包括：`source_sample_rate`、`source_start_sample`、
`region`、`recorded_at`、`device_id`、`snr_db`、`reviewer` 和 `notes`。

## 6. 独立性与排列要求

这是全部 Model_train 模型共用的最终板端对标集，因此：

1. 所有来源录音都必须与 ZeroShot、DB3V、BirdSet 的训练、few-shot support、
   replay、量化校准和模型选择数据无交集；
2. 不得从同一来源录音切出相邻窗口后分别放入不同类别；
3. 推荐每条来源录音只选一个窗口；如果重复使用，验证报告会单独统计；
4. 八类样本数必须完全相同；
5. `manifest.csv` 每连续 8 行必须恰好包含标签 `0..7` 各一条。

第 5 条保证清单前缀可以作为固定、平衡的实验层级：

| 层级 | `--count` | 用途 | 57 模型预计耗时 |
| --- | ---: | --- | ---: |
| 链路冒烟 | 8 | 每类 1 条，验证烧录和 UART | 约 25 分钟 |
| 全模型对标 | 64 | 每类 8 条，比较全部链路 | 约 3.4 小时 |
| 最终效果 | 至少 320 | 每类至少 40 条 | 约 17 小时起 |

估时基于 UART 115200、每条一秒 PCM 约 2.8 秒传输及约 0.55 秒板端计算。最终论文
效果应报告完整平衡测试集，而不是只报告 8 条冒烟结果。

## 7. 验证和运行接口

测试集准备完成后，先做严格校验：

```sh
python3 tools/run_board_benchmark.py validate-testset \
  --testset board_testset
```

列出固件包中的全部模型或核心模型：

```sh
python3 tools/run_board_benchmark.py list-models --scope all
python3 tools/run_board_benchmark.py list-models --scope core
```

在不烧录开发板的情况下核对 57 模型、64 样本计划和预计耗时：

```sh
python3 tools/run_board_benchmark.py run \
  --testset board_testset \
  --scope all \
  --count 64 \
  --port /dev/ttyACM0 \
  --run-id all_models_64 \
  --dry-run
```

正式运行：

```sh
python3 tools/run_board_benchmark.py run \
  --testset board_testset \
  --scope all \
  --count 64 \
  --port /dev/ttyACM0 \
  --run-id all_models_64 \
  --continue-on-error
```

每个模型默认先运行 5 个确定性张量的 `f32`/`native` 两种串口输入，共 10 次
`tensorflow-cpu==2.19.0`、`BUILTIN_REF` 与 TFLite Micro 的逐 LSB 对拍；随后
才发送原始 WAV。该版本必须与全部模型 metadata 中的转换版本一致。
`--skip-parity` 只用于临时诊断，不应用于可提交的证据运行。

中断后使用完全相同的参数并增加 `--resume`，已完成模型不会重新烧录或测试：

```sh
python3 tools/run_board_benchmark.py run \
  --testset board_testset \
  --scope all \
  --count 64 \
  --port /dev/ttyACM0 \
  --run-id all_models_64 \
  --continue-on-error \
  --resume
```

如果仅需用锁定的桌面运行时替换已有对拍证据，不重复原始 WAV：

```sh
python3 tools/run_board_benchmark.py refresh-parity \
  --run-dir board_results/all_models_64 \
  --pack /path/to/unpacked-package \
  --scope all \
  --port /dev/ttyACM0 \
  --continue-on-error
```

## 8. 结果接口

结果默认写入 `board_results/<run-id>/`：

```text
board_results/<run-id>/
├── run_config.json
├── testset_validation.json
├── label_map.json
├── selected_manifest.csv
├── summary.csv
└── models/<chain_id>/
    ├── flash.log
    ├── info.log
    ├── info.json
    ├── parity.log
    ├── parity_predictions.csv
    ├── audio_sweep.log
    ├── predictions.csv
    └── status.json
```

`predictions.csv` 保存 8 类浮点分数、量化 INT8 原始输出、预测类别、板端前端与
推理耗时。sigmoid 模型额外保存 `active_class_mask`；为了与 softmax 模型使用
同一单标签指标，`summary.csv` 的 accuracy、balanced accuracy 和 macro-F1
统一基于 argmax 计算。`info.json` 是每个固件实际模型哈希、Arena 配置及占用的
原始记录；`parity_predictions.csv` 保存逐张量、逐输入模式的板端与桌面 INT8
输出。`summary.csv` 聚合烧录/运行状态、Arena、对拍、指标和延迟。

完整运行后执行机器核验并生成所有原始证据文件的 SHA-256：

```sh
python3 tools/verify_board_evidence.py \
  --run board_results/all_models_64 \
  --pack /path/to/unpacked-package \
  --expected-models 57 \
  --output board_results/all_models_64/evidence_verification.json \
  --hashes-output board_results/all_models_64/artifact_hashes.csv
```

核验 `--scope core` 或 `--chain` 生成的阶段性运行时省略
`--expected-models`；校验器将使用 `run_config.json` 中的实际模型集合，并以
`complete_pack: false` 标记非全量结果。

## 9. 仅源标签的链路冒烟

未人工复核的历史数据只能使用显式的宽松策略，结果中的
`scientific_metrics_valid` 固定为 `false`：

```sh
python3 tools/import_pc_wav_testset.py \
  --pc-wav pc_wav_only \
  --output pc_wav_only/board_manifest_source_label_8.csv \
  --per-class 1

python3 tools/run_board_benchmark.py run \
  --testset pc_wav_only \
  --manifest pc_wav_only/board_manifest_source_label_8.csv \
  --annotation-policy source-label \
  --scope all \
  --count 8 \
  --run-id all57_source_label_8 \
  --continue-on-error
```

该模式可验证烧录、串口传输、板端前端、TFLM 对拍和结果文件接口，但其
accuracy/macro-F1 只能作为带局限声明的初步值，不能替代第 4～6 节规定的最终
严格测试集。

## 10. 板端前端与训练端误差

`audio-run --dump-feature` 返回整段录音最后一个完整一秒窗的板端浮点特征。比较时
必须使用同一个源窗；例如 8 秒录音应对应训练数组中的第 8 窗（索引 7），不能误
与索引 0 比较：

```sh
python3 tools/compare_frontend_features.py \
  --board /tmp/recording_000_last_mfcc.npy \
  --reference /path/to/mfcc/test_data.npy \
  --reference-index 7 \
  --info /path/to/zero_shot_mfcc/info.json \
  --max-abs-limit 0.0002 \
  --output /tmp/mfcc_frontend_comparison.json
```

输出同时记录两个 `.npy` 的 SHA-256、浮点 max/MAE/RMSE、板端上报的输入
scale/zero-point，以及量化后最大 LSB 误差和不一致元素数。
