# STM32_deploy

面向 `NUCLEO-L552ZE-Q / STM32L552ZE-Q` 的鸟声分类模型部署与板端对拍工程。
训练端为 [fire-fly7/Model_train](https://github.com/fire-fly7/Model_train)，当前核对基线是
提交 `42ead2e614e3f40afc7da29e660fc94609d10817`。

当前无麦克风实验的主链路为“原始 PCM16 录音 → 串口 → 板端切窗 → 板端
MFCC/LogMel/PCEN → 板端量化与 INT8 推理 → 录音级结果”。PC 只读取 WAV、
校验格式和分块传输，不生成特征。原有 `.npy` 特征张量命令保留为数值回归接口。

## 已生成的可烧录实验包

完整的 57 模型固件包从
[GitHub Releases](https://github.com/fire-fly7/LED_TEST/releases) 下载。生成包不再
提交到 Git 树；包内 `provenance.json` 和每个 `experiment.json` 均记录干净的
LED_TEST/Model_train 提交、源码树、构建输入摘要、TFLM 子模块提交和工具链版本。

包内每条实验链路都包含独立的 HEX/BIN、对应 TFLite、量化 metadata、论文指标、
SHA-256 和烧录/原始 WAV 串口测试工具。所有固件均支持板端 MFCC、LogMel 或
PCEN；优先实验列表、烧录命令和效果测试顺序见包内 `README.md` 与
`CORE_EXPERIMENTS.txt`。

该包只包含 Model_train 当前正式的 `ZeroShot_strict`、`DB3V_strict` 和
`BirdSet_strict` 三组实验；已删除的旧单种子、旧 few-shot 和旧混合 INT8 链路
不会进入板端清单或固件包。

固件配置 96 KiB Tensor Arena。实际占用、推理延迟、烧录状态和分类指标只引用
`evidence/` 中提交的原始 `info.json`、串口日志、`predictions.csv` 与汇总，不再
把无原始记录的人工数值当作实板结果。

干净克隆会初始化官方 TFLite Micro 子模块；首次 CMake 配置自动下载该 TFLM
提交锁定且校验过的 FlatBuffers、gemmlowp 和 ruy 版本：

```sh
git clone --recurse-submodules https://github.com/fire-fly7/LED_TEST.git
cd LED_TEST
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release -j
```

从干净的 LED_TEST 和 Model_train 工作树重新生成 57 模型固件包。输出应放在
源码树外或被忽略的位置：

```sh
python3 tools/build_experiment_firmwares.py \
  --model-train /path/to/Model_train \
  --output-dir /tmp/STM32_deploy_raw_audio_experiment_pack_<commit前8位>
```

构建器核对 3 个零样本、27 个 DB3V 和 27 个 BirdSet 导出；任一工作树有未提交
改动、子模块未初始化或偏离记录提交时都会拒绝打包。下载后可机器核验：

```sh
python3 tools/verify_firmware_release.py \
  --pack /path/to/unpacked-package \
  --source-dir . \
  --model-train /path/to/Model_train
```

## 软件边界

```text
mono 16-kHz PCM16 WAV
          |
          v
tools/serial_model_client.py
          |  UART 115200 8N1
          v
App/Serial/serial_model_app
          |
          v
App/AudioFrontend
  split 1-second windows
  MFCC / LogMel / PCEN
          |
          v
Core/model_inference + TFLite Micro
          |
          v
window inference + recording mean scores

Core/audio_capture + legacy Core/mfcc
          ^
          |
    麦克风采集（独立，当前目标不编译、不启动）
```

串口固件使用 CMSIS-DSP 做 2048 点 RFFT，但不编译 `audio_capture.c` 和历史
`Core/Src/mfcc.c`；`main.c` 也不会调用 SAI/DMA 初始化。SAI 中断回调只有定义
`STM32_DEPLOY_MICROPHONE_FRONTEND` 时才会连接麦克风采集代码。因此串口录音实验
与麦克风采集之间没有运行时依赖。

## Model_train 模型覆盖

已审计该提交中三个正式 strict 目录的 57 个 `DS_CNN_Model.int8.tflite` 导出。
固件注册了它们所需算子集合：

```text
ADD, CONV_2D, DEPTHWISE_CONV_2D, FULLY_CONNECTED,
MAX_POOL_2D, MEAN, MUL, LOGISTIC, SOFTMAX
```

支持的接口组合如下：

| 特征 | 输入 | 输出 | 激活 |
| --- | --- | --- | --- |
| MFCC | `int8 [1,32,13,1]` | `int8 [1,8]` | softmax 或 sigmoid |
| LogMel | `int8 [1,32,40,1]` | `int8 [1,8]` | softmax 或 sigmoid |
| PCEN | `int8 [1,32,40,1]` | `int8 [1,8]` | softmax 或 sigmoid |

不同模型的输入 scale/zero-point 并不相同。构建时的模型生成器会从同目录
`*.int8_metadata.json` 读取形状、激活、量化参数和算子，不使用硬编码的 LogMel
参数；不兼容或缺少信息的导出会在 CMake 配置阶段直接报错。

标签顺序为：

```text
0 Agelaius_phoeniceus
1 Cardinalis_cardinalis
2 Certhia_americana
3 Corvus_brachyrhynchos
4 Setophaga_aestiva
5 Setophaga_ruticilla
6 Spinus_tristis
7 Turdus_migratorius
```

## 选择并构建任意模型

不传模型路径时，使用仓库内置的 `zero_shot_logmel` 默认模型：

```sh
cmake --preset Debug
cmake --build --preset Debug -j
```

选择 Model_train 的任意导出：

```sh
MODEL_TRAIN=/path/to/Model_train
MODEL_DIR="$MODEL_TRAIN/src/experiments/ZeroShot_strict_INT8_quantization_8class/models/zero_shot_mfcc"

cmake -S . -B build/zero_shot_mfcc \
  -DCMAKE_BUILD_TYPE=Debug \
  -DSTM32_MODEL_TFLITE="$MODEL_DIR/DS_CNN_Model.int8.tflite" \
  -DSTM32_MODEL_LABEL_MAP="$MODEL_TRAIN/src/dataset_processing/label_map_8class.json" \
  -DSTM32_MODEL_SOURCE_COMMIT=42ead2e614e3f40afc7da29e660fc94609d10817
cmake --build build/zero_shot_mfcc -j
```

生成物位于构建目录：

```text
STM32_deploy.elf
STM32_deploy.bin
STM32_deploy.hex
generated/model/model_data.c
generated/model/model_manifest.h
generated/model/model_bundle.json
```

40-bin 模型通常可由路径和 metadata 自动判定 LogMel/PCEN。如果自定义导出的路径
没有特征类型线索，需显式添加 `-DSTM32_MODEL_FEATURE=LOGMEL` 或
`-DSTM32_MODEL_FEATURE=PCEN`。

连接板载 ST-LINK 后烧录默认 Debug 固件：

```sh
openocd -f flash.cfg -c \
  "program build/Debug/STM32_deploy.hex verify reset exit"
```

## 无麦克风串口实验

安装 PC 客户端依赖：

```sh
python3 -m pip install -r tools/requirements-serial.txt
```

其中 LiteRT 桌面解释器固定使用 `BUILTIN_REF` resolver，与板端 TFLite Micro
reference kernels 做数值对拍；不能把可能自动启用 XNNPACK 的 `AUTO` 输出当成
逐 LSB 基准。

查询板端实际加载的模型、形状、量化参数、哈希、arena 用量和标签：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 info
```

发送整段原始录音。WAV 必须是单声道、16 kHz、无压缩 PCM16，长度为整秒；
切窗、所选特征前端、输入量化、逐窗推理和录音级平均分全部在 STM32 上完成：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 --timeout 20 \
  audio-run \
  --input /path/to/recording.wav \
  --dump-feature /tmp/last_window_feature.npy
```

新的全模型测试集统一放在 `board_testset/`。硬性 WAV、标签、清单、数据独立性
和样本排列要求见
[`docs/BOARD_BENCHMARK_TESTSET.md`](docs/BOARD_BENCHMARK_TESTSET.md)。
准备完成后先严格校验全部 WAV 和哈希：

```sh
python3 tools/run_board_benchmark.py validate-testset \
  --testset board_testset
```

批量烧录并测试固件包中的全部模型：

```sh
python3 tools/run_board_benchmark.py run \
  --testset board_testset \
  --scope all \
  --count 64 \
  --port /dev/ttyACM0 \
  --run-id all_models_64 \
  --continue-on-error
```

相同参数增加 `--resume` 可跳过已完成模型。`--dry-run` 只验证数据、模型选择和
预计耗时，不操作开发板。每个模型在原始 WAV 测试前还会用 5 个确定性张量、两种
串口输入模式执行共 10 次 LiteRT/TFLM 对拍；只有诊断时才应使用
`--skip-parity`。结果统一写入 `board_results/<run-id>/`。

全量完成后核验 57 个模型的烧录、info、对拍、预测和汇总一致性，并生成原始证据
文件哈希表：

```sh
python3 tools/verify_board_evidence.py \
  --run board_results/all_models_64 \
  --pack /path/to/unpacked-package \
  --output board_results/all_models_64/evidence_verification.json \
  --hashes-output board_results/all_models_64/artifact_hashes.csv
```

如果只有尚未人工复核的 `pc_wav_only/send_manifest.csv`，可生成一个明确标记为
“仅源标签、不能作为论文最终指标”的平衡链路冒烟清单：

```sh
python3 tools/import_pc_wav_testset.py \
  --pc-wav pc_wav_only \
  --output pc_wav_only/board_manifest_source_label_8.csv \
  --per-class 1

python3 tools/run_board_benchmark.py validate-testset \
  --testset pc_wav_only \
  --manifest pc_wav_only/board_manifest_source_label_8.csv \
  --annotation-policy source-label
```

严格论文测试仍必须使用
[`docs/BOARD_BENCHMARK_TESTSET.md`](docs/BOARD_BENCHMARK_TESTSET.md) 规定的人工
复核、无混合目标种、通过数据泄漏审计的 `board_testset/`。

对齐训练数组与板端返回的最后一个一秒窗后，可固化 MFCC/LogMel/PCEN 浮点误差
及模型输入量化后的 LSB 误差：

```sh
python3 tools/compare_frontend_features.py \
  --board /tmp/last_window_feature.npy \
  --reference /path/to/test_data.npy \
  --reference-index 7 \
  --info /path/to/info.json \
  --max-abs-limit 0.0002 \
  --output /tmp/frontend_comparison.json
```

以下 `.npy` 接口只用于前端/推理回归。客户端接受 `[32,bins]`、`[32,bins,1]`、
`[N,32,bins]` 或 `[N,32,bins,1]` 的 `.npy`：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 run \
  --input /path/to/test_data.npy \
  --index 0 \
  --mode both \
  --tflite "$MODEL_DIR/DS_CNN_Model.int8.tflite"
```

批量回归：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 sweep \
  --input /path/to/test_data.npy \
  --start 0 \
  --count 100 \
  --mode both \
  --tflite "$MODEL_DIR/DS_CNN_Model.int8.tflite" \
  --max-lsb-error 1
```

`f32` 模式发送训练端浮点特征，由 STM32 量化；`native` 模式由 PC 按板端上报的
scale/zero-point 量化后直接发送 INT8。`both` 会分别走两条路径。提供 `--tflite`
时，客户端用同一量化输入运行桌面解释器，统计预测不一致数、最大 INT8 LSB 误差
以及板端最小/中位/最大推理耗时；超过阈值时返回非零退出码。

建议实验顺序：

1. `info`：确认 SHA-256、形状、激活、scale/zero-point 与所选导出一致；
2. 单样本 `both`：确认 PC 量化与板端量化得到相同输出；
3. 100 个样本 `sweep`：检查 TFLite 与 TFLM 数值一致性；
4. 全测试集 `sweep`：记录预测一致率和延迟分布；
5. 至少各测一个 MFCC、LogMel、PCEN，以及一个 softmax、一个 sigmoid 模型。

LED 状态：

| LED | 含义 |
| --- | --- |
| 绿灯 | 模型初始化及 metadata 校验成功 |
| 红灯 | schema、内存、形状、类型或量化参数不匹配 |
| 蓝灯 | 正在执行推理 |

## 串口二进制协议

COM1 为 `115200 8N1`。所有字段 little-endian，每包包含 20 字节头：

```c
uint32_t magic;          /* 0x31544D53，线上的字节为 "SMT1" */
uint8_t  version;        /* 1 */
uint8_t  command;
uint16_t flags;          /* 当前必须为 0 */
uint32_t sequence;
uint32_t payload_length;
uint32_t payload_crc32;  /* CRC-32/ISO-HDLC */
```

| 命令 | 值 | payload |
| --- | ---: | --- |
| `GET_INFO` | `0x01` | 空 |
| `RUN_F32` | `0x02` | `input_elements` 个 little-endian float32 |
| `RUN_NATIVE` | `0x03` | `input_elements` 个 int8 |
| `AUDIO_BEGIN` | `0x10` | 采样率、样本数、PCM16 格式、整段 PCM CRC32 |
| `AUDIO_CHUNK` | `0x11` | 连续样本偏移和 little-endian PCM16 |
| `AUDIO_RUN` | `0x12` | 空；校验完整流并返回录音级结果 |
| `AUDIO_GET_FEATURE` | `0x13` | 空；调试读取最后完整窗口的板端特征 |
| `INFO` 响应 | `0x81` | 状态、张量、量化、哈希、标签、arena |
| `RESULT` 响应 | `0x82` | 分类、周期、耗时、阈值 mask、分数、原始输出 |
| `AUDIO_ACK` 响应 | `0x90` | 状态、累计样本数、已完成窗口数 |
| `AUDIO_FEATURE` 响应 | `0x91` | 板端生成的最后窗口 float32 特征 |
| `AUDIO_RESULT` 响应 | `0x92` | 录音级平均分及前端/推理分项耗时 |
| `ERROR` 响应 | `0xFF` | 错误码和消息 |

浮点输入量化公式：

```text
q = clip(round(x / input_scale) + input_zero_point, -128, 127)
```

softmax 输出取 argmax；sigmoid 输出除 argmax 外还按阈值生成
`active_class_mask`，默认阈值为 0.5。

## 麦克风前端后续工作

`App/AudioFrontend` 已实现与 Model_train 对齐的 MFCC、LogMel、PCEN，串口原始
录音链路可用于全部 57 个模型。`Core/Src/audio_capture.c` 与
`Core/Src/mfcc.c` 仍作为历史麦克风代码保留，但不属于串口目标；旧 MFCC 使用
1024 点 FFT、Hamming、预加重和近似 Mel 采样，不能接入当前模型。

恢复实时麦克风时，应让新的采集目标只负责把连续 PCM16 送入
`App/AudioFrontend` 的窗口接口，不复制或修改特征算法。这样串口实验与麦克风
实验只有“PCM 来源”不同，后续板端处理完全共用。

CubeMX 文件仍保留 SAI1 Block B 与 DMA 硬件配置，便于后续建立独立
`App/Microphone` 目标；当前串口固件不会启动这些外设。
