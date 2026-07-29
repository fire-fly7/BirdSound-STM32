# STM32_deploy 板端核心链路烧录测试

## 结论

- 测试时间：2026-07-29 15:08:34–15:20:57（Asia/Tokyo），耗时 12 分 23 秒。
- 开发板：STM32L5x2xx，ST-LINK `0668FF363355373043133655`，串口 `/dev/ttyACM0`。
- 固件包包含 57 个模型；本轮按 `core` 范围逐个烧录并测试 12 个代表模型。
- 烧录验证：12/12 `Verified OK`，失败 0。
- TensorFlow 2.19.0 与板端 TFLM 对拍：120/120 完成，预测不一致 0，最大量化误差 0 LSB。
- 原始录音链路：96/96 次完成（12 个模型 × 8 条 WAV）。每条 WAV 均由串口发送原始 PCM，特征提取、量化和推理全部在板端执行。
- 机器证据校验：通过，共检查 101 个配置、日志、板端信息、逐样本预测和状态文件。

本轮结束后，开发板保留的固件为
`birdset_strict_20shot_logmel_head_only_seed_2026`。

## 固件与测试数据

- 板端源码提交：`073a1f1a40d689448b332bac717961475315bebf`，构建时工作树干净。
- Model_train 提交：`42ead2e614e3f40afc7da29e660fc94609d10817`，导出时工作树干净。
- TFLite Micro 子模块：`bbf70db4993618bcabc01cf2f02cd9eb089d5dca`。
- 测试集清单 SHA-256：`3a0d5053fa214c44900393b3856771b3bf72a2606a5b33503c06adbb6c05d406`。
- 本轮从 192 条合规 WAV 中选择前 8 条，每类 1 条；格式均为 16 kHz、单声道、PCM16、16000 帧。

## 各模型结果

延迟为每个模型 8 条录音的板端中位数，单位 ms；Arena 单位 byte。

| 模型 | 特征 | 正确数 | Accuracy | Macro-F1 | 前端 | 推理 | Arena |
|---|---:|---:|---:|---:|---:|---:|---:|
| `zero_shot_mfcc` | MFCC | 4/8 | 0.500 | 0.354 | 80.37 | 422.90 | 27332 |
| `zero_shot_logmel` | LOGMEL | 4/8 | 0.500 | 0.375 | 66.79 | 2112.67 | 79172 |
| `zero_shot_pcen` | PCEN | 3/8 | 0.375 | 0.300 | 252.81 | 2106.26 | 79172 |
| `db3v_strict_10shot_logmel_head_only_seed_42` | LOGMEL | 4/8 | 0.500 | 0.417 | 67.29 | 2112.66 | 79172 |
| `db3v_strict_10shot_logmel_head_only_seed_123` | LOGMEL | 4/8 | 0.500 | 0.438 | 67.29 | 2112.66 | 79172 |
| `db3v_strict_10shot_logmel_head_only_seed_2026` | LOGMEL | 4/8 | 0.500 | 0.438 | 66.80 | 2112.66 | 79172 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_42` | MFCC | 4/8 | 0.500 | 0.417 | 82.69 | 422.79 | 27284 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_123` | MFCC | 4/8 | 0.500 | 0.375 | 82.69 | 422.79 | 27284 |
| `birdset_strict_20shot_mfcc_bn_head_replay_seed_2026` | MFCC | 4/8 | 0.500 | 0.375 | 82.69 | 422.79 | 27284 |
| `birdset_strict_20shot_logmel_head_only_seed_42` | LOGMEL | 3/8 | 0.375 | 0.271 | 67.49 | 2112.35 | 79124 |
| `birdset_strict_20shot_logmel_head_only_seed_123` | LOGMEL | 3/8 | 0.375 | 0.271 | 67.49 | 2112.36 | 79124 |
| `birdset_strict_20shot_logmel_head_only_seed_2026` | LOGMEL | 3/8 | 0.375 | 0.271 | 67.53 | 2112.42 | 79124 |

汇总范围：

- Accuracy：0.375–0.500，中位数 0.500。
- Macro-F1：0.271–0.438，中位数 0.375。
- 板端前端中位延迟：66.79–252.81 ms。
- 板端推理中位延迟：422.79–2112.67 ms。
- Arena 实际占用：27284–79172 / 98304 byte。

## 结果解释

本数据包的标签策略是 `source-label`，且未完成人工逐段复核、混合物种确认和
训练泄漏审计，因此验证记录中的 `scientific_metrics_valid` 为 `false`。本轮
Accuracy 和 Macro-F1 只能用于链路冒烟与迁移一致性检查，不能作为论文最终性能
指标。链路结论不受此限制：烧录、串口原始录音传输、板端特征、板端推理及
TensorFlow/TFLM 精确对拍均已通过。

57 个模型 × 192 条录音的完整运行共需 10944 次板端推理，干运行估算约 10.116
小时；本轮未执行该全量长测。

## 可复核证据

- `summary.csv`：逐模型汇总。
- `models/<chain_id>/flash.log`：每个固件的烧录验证日志。
- `models/<chain_id>/info.json`：板端模型哈希、特征类型及 Arena 原始值。
- `models/<chain_id>/parity_predictions.csv`：桌面端/板端逐张量对拍数据。
- `models/<chain_id>/predictions.csv`：逐录音预测、分数和延迟。
- `evidence_verification.json`：机器完整性校验结论。
- `artifact_hashes.csv`：101 个证据文件的大小和 SHA-256。
