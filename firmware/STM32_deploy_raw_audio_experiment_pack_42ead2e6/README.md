# STM32_deploy 可烧录实验固件包

训练模型来源：`fire-fly7/Model_train@42ead2e614e3f40afc7da29e660fc94609d10817`。
本包包含 57 个 strict-INT8 实验固件；每个实验目录均带有可直接烧录的
`STM32_deploy.hex`/`STM32_deploy.bin`、对应的桌面 `model.tflite`、量化 metadata、
模型 bundle 和包含文件哈希的 `experiment.json`。

固件 Tensor Arena 为 96 KiB。实板 `zero_shot_logmel` 测得使用量为 79,172 B；
不要使用早期 72 KiB 固件，它会返回模型初始化错误 `-4`。

## 目录

- `experiments/01_zero_shot_strict/`：3 个当前零样本严格 INT8 基准；
- `experiments/02_db3v_strict/`：27 个 DB3V 严格多种子实验；
- `experiments/03_birdset_strict/`：27 个 BirdSet 严格多种子实验；
- `INDEX.csv`/`index.json`：全部固件接口、指标、路径与哈希；
- `CORE_EXPERIMENTS.txt`：建议优先烧录的实验路径；
- `SHA256SUMS`：整个包的文件校验值。

本包只读取 Model_train 当前三个正式 strict INT8 目录，不包含已删除的旧单种子、
旧 few-shot 或旧混合 INT8 链路。

## 推荐优先测试

指标为 Model_train 报告中的 INT8 百分比，不是本地实板测量值。

| chain_id | 特征 | 激活 | Xeno Macro-F1 | BirdSet Top-1 | DB3V Macro-F1 |
| --- | --- | --- | ---: | ---: | ---: |
| `zero_shot_mfcc` | MFCC | softmax | 48.77 | 15.36 | 51.25 |
| `zero_shot_logmel` | LOGMEL | softmax | 59.01 | 18.42 | 65.94 |
| `zero_shot_pcen` | PCEN | softmax | 35.07 | 21.40 | 50.24 |
| `db3v_strict_10shot_logmel_head_only_seed_42` | LOGMEL | softmax | 58.13 | 23.19 | 68.09 |
| `db3v_strict_10shot_logmel_head_only_seed_123` | LOGMEL | softmax | 57.14 | 29.33 | 68.01 |
| `db3v_strict_10shot_logmel_head_only_seed_2026` | LOGMEL | softmax | 57.35 | 29.87 | 68.33 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_42` | MFCC | sigmoid | 46.70 | 24.24 | 49.15 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_123` | MFCC | sigmoid | 48.59 | 22.64 | 48.25 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_2026` | MFCC | sigmoid | 47.87 | 25.49 | 48.69 |
| `birdset_strict_20shot_logmel_head_only_seed_42` | LOGMEL | sigmoid | 56.86 | 22.16 | 64.09 |
| `birdset_strict_20shot_logmel_head_only_seed_123` | LOGMEL | sigmoid | 56.89 | 22.22 | 64.44 |
| `birdset_strict_20shot_logmel_head_only_seed_2026` | LOGMEL | sigmoid | 53.10 | 19.15 | 61.43 |

## 烧录

以某个实验为例：

```sh
python3 tools/flash_experiment.py \
  experiments/01_zero_shot_strict/zero_shot_logmel/STM32_deploy.hex
```

也可直接使用 OpenOCD：

```sh
openocd -f flash.cfg -c \
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
python3 tools/serial_model_client.py --port /dev/ttyACM0 --timeout 20 audio-run \
  --input /path/to/recording.wav
```

全部模型批量烧录和原始 WAV 板端对标接口位于包内
`tools/run_board_benchmark.py`，测试集硬性规格见
`BOARD_BENCHMARK_TESTSET.md`：

```sh
python3 tools/run_board_benchmark.py validate-testset \
  --testset /path/to/board_testset

python3 tools/run_board_benchmark.py run \
  --testset /path/to/board_testset \
  --scope all --count 64 --port /dev/ttyACM0 \
  --run-id all_models_64 --continue-on-error
```

三种特征前端均与 Model_train 定义绑定，固件根据自身 `feature` 自动选择。
麦克风/SAI/DMA 采集不在此固件中，串口原始录音实验与麦克风硬件保持分离。

## 无数据集张量冒烟对拍

无需 `.npy` 即可用 5 个确定性张量核对 PC TFLite 与板端 TFLM：

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 smoke \
  --mode both \
  --tflite experiments/01_zero_shot_strict/zero_shot_logmel/model.tflite
```

## 特征张量回归实验

使用与固件 `feature` 完全匹配的 Model_train 测试特征。LogMel 和 PCEN 即使形状
都是 `32×40×1` 也不能混用。

```sh
python3 tools/serial_model_client.py --port /dev/ttyACM0 sweep \
  --input /path/to/matching_test_data.npy \
  --mode both \
  --tflite /path/to/this/experiment/model.tflite \
  --output board_results.csv
```

同一特征链路之间使用相同样本索引，再比较 `board_results.csv`。softmax 链路主要
比较 `predicted_index`；sigmoid/BirdSet 链路还需比较 `active_class_mask`。跨特征
比较必须由同一批原始音频分别生成 MFCC、LogMel、PCEN，不能直接复用一个 `.npy`。
