# 57 模型 × 192 条原始录音实板完整测试

## 结论

- 测试时间：2026-07-29 15:50:15 至 2026-07-30 06:07:07
  （Asia/Tokyo），耗时 14 小时 16 分 52 秒。
- 57 个模型均分别烧录到 STM32L552 开发板，OpenOCD 校验
  `Verified OK` 为 57/57，失败 0。
- 57 × 192 = 10944 条原始 PCM16 录音全部通过串口传输；切窗、
  MFCC/LogMel/PCEN、量化与 TFLite Micro 推理均在板端完成。
- TensorFlow 2.19.0 与板端 TFLM 完成 570 次输出对拍，预测不一致 0，
  最大量化误差 0 LSB。
- 机器证据核验通过，共检查 461 个配置、日志、板端信息、逐样本预测和
  状态文件。

本轮结束后，开发板保留的固件为
`birdset_strict_20shot_pcen_bn_head_seed_2026`。

## 固件与数据来源

- 板端源码提交：`073a1f1a40d689448b332bac717961475315bebf`
  （构建时工作树干净）。
- 板端源码树：`2ef16030091cd1b77060d63776bd3edab6a44e6a`。
- 固件构建输入 SHA-256：
  `45066718975daa062259b50d099c237324128007380cc9999f3f0d57bf65bf26`。
- Model_train 提交：`42ead2e614e3f40afc7da29e660fc94609d10817`
  （导出时工作树干净）。
- TFLite Micro 子模块：`bbf70db4993618bcabc01cf2f02cd9eb089d5dca`。
- 测试集清单 SHA-256：
  `3a0d5053fa214c44900393b3856771b3bf72a2606a5b33503c06adbb6c05d406`。
- 数据格式：16 kHz、单声道、PCM16 little-endian、每条 16000 帧。
- 类别数：8；每类 24 条，共 192 条。

该测试使用的是上述干净固件提交。测试结束后完成的 Core/App 源码重构不属于
本轮烧录固件，不能用本结果证明重构后固件的实板行为。

## 完整性与一致性

| 项目 | 结果 |
|---|---:|
| 固件包模型 | 57 |
| 完成模型 | 57 |
| 烧录并校验成功 | 57/57 |
| 原始录音预测 | 10944/10944 |
| TFLite/TFLM 对拍 | 570 |
| 对拍预测不一致 | 0 |
| 最大量化误差 | 0 LSB |
| 非零模型状态 | 0 |
| Arena 溢出 | 0 |
| 机器核验证据文件 | 461 |

## 诊断性结果

以下数值按 19 个同特征模型聚合。Accuracy 和 Macro-F1 是模型平均值；
前端、推理时延和 Arena 是逐模型中位数的中位数。

| 特征 | 模型数 | 平均 Accuracy | 平均 Macro-F1 | 前端时延 | 推理时延 | Arena |
|---|---:|---:|---:|---:|---:|---:|
| MFCC | 19 | 0.3805 | 0.3735 | 81.716 ms | 422.868 ms | 27332 B |
| LOGMEL | 19 | 0.4405 | 0.4397 | 67.291 ms | 2112.625 ms | 79172 B |
| PCEN | 19 | 0.3188 | 0.2951 | 252.825 ms | 2106.398 ms | 79172 B |

诊断集 Accuracy 范围为 0.2448–0.4740，中位数 0.3802；Macro-F1 范围为
0.2236–0.4633，中位数 0.3731。Arena 实际占用范围为
27284–79172 / 98304 byte。

诊断集上 Accuracy 最高的模型为
`db3v_strict_10shot_logmel_head_only_seed_123`：

- Accuracy：0.473958；
- Macro-F1：0.463309；
- 板端前端中位时延：67.291 ms；
- 板端推理中位时延：2112.626 ms；
- Arena 实际占用：79172 / 98304 byte。

## 指标适用范围

`testset_validation.json` 将 `scientific_metrics_valid` 明确标记为 `false`。
192 个窗口只来自 24 个源录音，每个源录音包含多个窗口，且源标签没有经过逐窗
人工物种复核、混合物种确认和训练泄漏审计；其中 5 个窗口还有极低 RMS 警告。

因此，本结果可以严格证明固件烧录、串口原始录音传输、板端特征、板端推理、
模型哈希、Arena 和 TFLite/TFLM 数值对拍链路正常。Accuracy、Macro-F1 和模型
排名仅为诊断值，不能直接作为论文最终性能指标。

## 可复核文件

- `summary.csv`：57 个模型的聚合状态、指标、时延、Arena 和对拍结果。
- `run_config.json`：测试选择、固件包、串口和参考运行时配置。
- `selected_manifest.csv`：192 条实际测试录音及内容哈希。
- `testset_validation.json`：格式、类别分布和科学指标有效性声明。
- `models/<chain_id>/flash.log`：逐模型烧录与校验日志。
- `models/<chain_id>/info.json`：板端返回的模型哈希、特征及 Arena 原始值。
- `models/<chain_id>/parity_predictions.csv`：桌面端/板端逐输入对拍数据。
- `models/<chain_id>/predictions.csv`：192 条录音的预测、分数和板端时延。
- `models/<chain_id>/status.json`：完成状态、混淆矩阵和聚合指标。
- `evidence_verification.json`：机器完整性与一致性校验结果。
- `artifact_hashes.csv`：461 个原始证据文件的大小和 SHA-256。

重新核验证据：

```sh
python3 tools/verify_board_evidence.py \
  --run board_results/board_replay_all57_all192_20260729 \
  --pack /path/to/STM32_deploy_raw_audio_experiment_pack_42ead2e6_073a1f1a \
  --expected-models 57 \
  --output /tmp/evidence_verification.json \
  --hashes-output /tmp/artifact_hashes.csv
```
