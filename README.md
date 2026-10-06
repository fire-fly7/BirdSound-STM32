# BirdSound-STM32 · STM32 鸟声分类部署

面向 NUCLEO-L552ZE-Q / STM32L552ZE-Q 的 INT8 鸟声分类固件，使用 CMSIS-DSP 和 TensorFlow Lite Micro。配套训练项目：[BirdSound-TinyML](https://github.com/fire-fly7/BirdSound-TinyML)。

当前入口为 `main`。主链路为 **PCM16 录音 → UART → 板端切窗 → MFCC/LogMel/PCEN → INT8 推理 → 录音级结果**。训练端负责模型和共享配置，固件端负责前端运算及推理。

## 目录

| 路径 | 内容 |
|---|---|
| `App/AudioFrontend/` | 当前三种音频前端 |
| `App/ModelRuntime/` | 模型校验、量化及 TFLM 推理 |
| `App/Serial/` | 原始音频和张量串口协议 |
| `App/Microphone/` | 麦克风诊断与历史参考实现 |
| `shared/` | 训练端同步的共享配置与校验接口 |
| `tools/` | 生成、构建、串口测试及证据核验 |
| `docs/` | 构建、协议及实验指南 |
| `evidence/`、`board_results/` | 已提交的历史实板证据 |

## 构建

```sh
git clone --recurse-submodules https://github.com/fire-fly7/BirdSound-STM32.git
cd BirdSound-STM32
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r tools/requirements-build.txt
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel 4
```

需要 CMake、构建工具和 Arm GNU Toolchain。工具链不在 PATH 时，添加 `-DARM_GNU_TOOLCHAIN_ROOT=/path/to/toolchain`。子模块及其锁定依赖的首次获取需要网络。详细环境检查见[Linux 构建指南](docs/LINUX_PORTABILITY.md)。

默认构建串口应用与内置 LogMel 模型。使用训练端生成的部署包：

```sh
cmake -S . -B build/shared-logmel \
  -DCMAKE_BUILD_TYPE=Release \
  -DSTM32_DEPLOY_APP=serial \
  -DSTM32_MODEL_TFLITE=/tmp/deployment/zero_shot_logmel/model/model.tflite \
  -DSTM32_MODEL_METADATA=/tmp/deployment/zero_shot_logmel/model/metadata.json \
  -DSTM32_MODEL_LABEL_MAP=/tmp/deployment/zero_shot_logmel/model/label_map.json \
  -DSTM32_MODEL_FEATURE=LOGMEL
cmake --build build/shared-logmel --parallel 4
```

共享配置来自 BirdSound-TinyML 的 `shared/deployment_contract.json`。修改配置后需同步两端；旧模型缺少配置哈希时，仅允许已冻结的基线配置兼容模式，不应据此宣称重新训练或重新验证。

## 接口

| 特征 | INT8 输入 | 输出 |
|---|---|---|
| MFCC | `[1,32,13,1]` | `[1,8]` |
| LogMel / PCEN | `[1,32,40,1]` | `[1,8]` |

WAV 输入须为单声道、16 kHz、PCM16，长度为整秒。串口默认 115200 8N1：

```sh
python3 -m pip install -r tools/requirements-serial.txt
python3 tools/serial_model_client.py --port /dev/ttyACM0 info
python3 tools/serial_model_client.py --port /dev/ttyACM0 --timeout 20 \
  audio-run --input /path/to/recording.wav
```

烧录、完整协议、批量对拍和实验包生成见[部署指南](docs/DEPLOYMENT_GUIDE.md)；论文测试语料要求见[板端测试集规范](docs/BOARD_BENCHMARK_TESTSET.md)。

## 当前验证状态

2026-10-06 共享配置改造后，三个零样本 Release 固件均编译成功：

| 特征 | Flash（text + data） | 静态 RAM（data + bss） |
|---|---:|---:|
| MFCC | 179,344 B | 176,784 B |
| LogMel | 172,056 B | 176,784 B |
| PCEN | 175,856 B | 176,784 B |

静态 RAM 已包含 96 KiB tensor arena；仍需关注运行时栈和余量。C/Python 量化验证通过 50,820 个用例。第三方 CMSIS/TFLM 编译警告仍存在。

历史 57 模型实验保留 10,944 条 PCM 预测与 570 次零 LSB 对拍，属于旧固件链路；来源标签冒烟数据不作为论文正式指标。新版尚未烧录对拍，当前串口查询超时问题仍待排查。实时麦克风与功耗实验尚未闭环。

## 版本

仅维护当前 `main`，保留提交历史和原始实验依据。旧开发分支及旧固件标签从远端移除，旧发布包不作为当前版本入口。构建产物输出到忽略目录或仓库外，由部署清单记录源码、模型、配置及其哈希。
