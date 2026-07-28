# 可烧录固件发布

生成的 57 模型固件不再提交到 Git 树中，而是作为 GitHub Release 附件发布。这样
固件可以指向一个已存在且干净的源码提交，避免“提交中包含的固件需要由该提交自身
生成”的循环来源问题。

每个 Release 固件包包含：

- 57 组可直接烧录的 `STM32_deploy.hex` / `STM32_deploy.bin`；
- 每组固件对应的 TFLite、metadata、`experiment.json` 和文件 SHA-256；
- 根目录 `provenance.json`，记录 LED_TEST/Model_train 提交、源码树、构建输入
  摘要、TFLM 子模块提交和工具链版本；
- `SHA256SUMS` 以及 `tools/verify_firmware_release.py`。

下载并解压后执行：

```sh
python3 tools/verify_firmware_release.py \
  --pack /path/to/unpacked-package \
  --source-dir /path/to/LED_TEST \
  --model-train /path/to/Model_train
```

构建器会拒绝 LED_TEST 或 Model_train 的脏工作树，也会拒绝未初始化、偏离记录
提交或冲突状态的子模块。
