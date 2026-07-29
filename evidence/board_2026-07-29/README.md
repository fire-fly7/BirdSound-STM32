# 2026-07-29 STM32 全模型实板验证证据

本目录保存 NUCLEO-L552ZE-Q（STM32L552）上的原始、可复核实验记录，不只保存
人工摘录的结果。开发板身份和工具版本见 `hardware_identity.json`。

## 已完成的验证

- 57/57 个固件都由 OpenOCD 执行烧录、读回校验并得到 `Verified OK`。
- 57/57 个模型都保存了板端 `info.json`，包含模型哈希、输入输出量化参数、
  标签、实际 Tensor Arena 用量和配置上限。
- 每个模型使用 5 个确定性张量，分别走 `f32` 与 `native` 串口输入，共得到
  570 次 TensorFlow/TFLite 与 TFLite Micro 输出对拍。参考端严格固定为
  `tensorflow-cpu==2.19.0`、`BUILTIN_REF`；预测不一致数为 0，最大误差为
  0 LSB。
- 每个模型接收 8 条一秒 PCM16 原始 WAV，分帧、MFCC/LogMel/PCEN、量化和推理
  全部在板端完成，共保存 456 条 `predictions.csv` 记录。
- 三种零样本固件另外保存了与训练数组同一窗口的板端浮点特征：
  MFCC 最大绝对误差 `0.000152587890625`，LogMel 为
  `0.00000762939453125`，PCEN 为 `0.00000035762786865234375`；三者量化后
  都是 0 LSB 差异。

全量机器核验结果位于
`all57_source_label_8/evidence_verification.json`，文件级 SHA-256 清单位于
`all57_source_label_8/artifact_hashes.csv`。逐模型目录保留烧录日志、串口
`info` 日志、对拍日志、原始音频日志和逐样本 CSV。`frontend_parity/` 保存三种
前端的板端 `.npy`、对齐报告及原始日志。

## 测试结果边界

本次 8 条录音使用 `source-label` 自动来源标签，仅用于确认 57 条实验链路能完整
运行，不是论文最终测试集，因此
`all57_source_label_8/testset_validation.json` 明确记录
`scientific_metrics_valid=false`。当前 smoke 数据上的 accuracy 范围是
0.125–0.5，macro-F1 范围是 0.0277778–0.4375；不得将它们当作论文性能结论。
论文最终 accuracy/macro-F1 应在人工审核、类别平衡且来源独立的测试集上重新运行。

## 性能原始结果

57 个模型的板端 Tensor Arena 实际用量为 27,284–79,172 B（中位数
79,124 B），统一配置上限 98,304 B。每模型 8 条原始 WAV 的中位前端延迟范围为
66,792–254,790.5 μs，中位推理延迟范围为 422,787–2,112,712.5 μs。逐模型数值
在 `all57_source_label_8/summary.csv`，不是 README 手工估算。

## 溯源说明

本次实板执行使用的完整固件包由干净提交
`d36dd04abc8e367a4a586c2436f1636ece9689b7` 和干净 Model_train 提交
`fce2d285f2f8e6c3f22495e28a48734fef782a0c` 构建；两者及固定 TFLM 子模块信息
均记录在核验报告。发布流程会从最终 LED_TEST 提交和当前 Model_train
`42ead2e614e3f40afc7da29e660fc94609d10817` 再次干净构建 57 个固件，并将全部
HEX/BIN 与本次实测固件的逐文件等价报告作为 GitHub Release 附件。只有等价检查
全部通过才发布，以建立“最终源码 → 发布固件 → 本次实板原始记录”的可审计链路。
