# Linux 完整迁移与验收

本文给出从全新 Linux 主机到可构建、可烧录、可串口测试的唯一验收路径。仓库中
不使用 `/home/...` 等主机绝对路径；源码目录、构建目录、Arm 工具链根目录和
Model_train 目录均可移动。

## 支持边界

自动检查的宿主基线为：

- x86_64 或 AArch64 的 glibc Linux；
- Python 3.10 或更高版本；
- Git 2.20 或更高版本；
- CMake 3.22 或更高版本，以及 GNU Make；
- Arm GNU Toolchain 14.2.Rel1（GCC 14.2.1）用于严格复现；
- 具有网络访问权限，用于首次取得 Git 子模块和 TFLite Micro 锁定依赖。

Arm 的 14.2.Rel1 官方二进制支持 x86_64/AArch64 Linux，官方兼容基线是
Ubuntu 20.04 及以上或 RHEL 8 及以上。更老的 glibc、musl-only 发行版和其他 CPU
架构不能直接使用该官方二进制，应在受支持的容器中构建，或自行构建交叉编译器；
这类环境不属于仓库的可复现性保证范围。

## 1. 主机基础工具

Debian/Ubuntu 示例：

```sh
sudo apt update
sudo apt install git cmake build-essential python3 python3-venv python3-pip \
  ca-certificates openocd
```

Fedora/RHEL、Arch、openSUSE 使用本发行版的等价包即可。发行版仓库中的
`gcc-arm-none-eabi` 版本可能不同；论文/Release 证据统一使用 14.2.Rel1。

从 Arm 官方发布页解压工具链后，可以加入 `PATH`，也可以只设置根目录。后者不会
污染系统工具链：

```sh
export ARM_GNU_TOOLCHAIN_ROOT=/opt/arm-gnu-toolchain-14.2.rel1-x86_64-arm-none-eabi
"$ARM_GNU_TOOLCHAIN_ROOT/bin/arm-none-eabi-gcc" --version
```

CMake 和仓库预检脚本都会读取 `ARM_GNU_TOOLCHAIN_ROOT`。如果未设置，则从
`PATH` 查找 `arm-none-eabi-*`。

## 2. 干净克隆与 Python 环境

```sh
git clone --recurse-submodules https://github.com/fire-fly7/LED_TEST.git
cd LED_TEST
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r tools/requirements-build.txt
```

如果已经普通克隆，必须补齐子模块：

```sh
git submodule sync --recursive
git submodule update --init --recursive
```

不要复制另一台服务器的 `build/`、TFLM 工作目录或虚拟环境。首次配置串口模型
固件时，CMake 原生下载固定版本的 FlatBuffers、gemmlowp 和 ruy，校验 TFLM
提交所记录的摘要，并应用该提交自带的补丁；源码和构建路径可以包含空格。

## 3. 一键预检和全部固件构建

严格复现预检：

```sh
python tools/check_linux_toolchain.py --profile build --strict-toolchain
```

一次构建所有直接可烧录目标：

```sh
python tools/build_all_firmware.py \
  --build-root build/linux-all \
  --build-type Release \
  --jobs 4 \
  --strict-toolchain
```

脚本依次构建：

| 目标 | 输入链路 | 输出目录 |
| --- | --- | --- |
| `serial` | PC 串口发送原始 PCM16，板端完成特征与推理 | `build/linux-all/serial/` |
| `microphone_test` | ICS-43434 标准 I2S 硬件诊断 | `build/linux-all/microphone_test/` |
| `cca02m2_test` | X-NUCLEO-CCA02M2 PDM/DFSDM 硬件诊断 | `build/linux-all/cca02m2_test/` |

每个目录必须生成 `STM32_deploy.elf/.hex/.bin`。所有文件的字节数和 SHA-256 写入
`build/linux-all/build_manifest.json`。并行数默认最多为 4，避免低内存 Linux 主机
因 TFLite Micro 的 C++ 编译而耗尽内存。

编译器使用稳定的虚拟源码前缀，TFLM 的 `__FILE__` 诊断不会嵌入克隆目录。相同
源码、同一份 14.2.Rel1 工具链归档和 Release 参数在不同绝对目录下生成相同的
ELF/HEX/BIN；仅有相同 GCC 版本号但来自另一种打包发行时，必须以 manifest 中的
完整工具链标识和实际哈希为准。CI 还会拒绝固件中出现 runner 工作目录。

麦克风诊断目标不读取模型、NumPy 生成物或 TFLite Micro 源码；它们与 `serial`
目标在 CMake 源码和运行时上分离。完整构建仍会先做统一预检，因为其中包含
`serial` 目标。

## 4. 串口对拍与硬件依赖

仅做烧录、串口和麦克风诊断时安装轻量依赖：

```sh
python -m pip install -r tools/requirements-hardware.txt
python tools/check_linux_toolchain.py --profile hardware --strict-toolchain
```

需要 PC TFLite 逐 LSB 对拍和完整数据集实验时安装固定运行时：

```sh
python -m pip install -r tools/requirements-serial.txt
python tools/check_linux_toolchain.py --profile all --strict-toolchain
```

`requirements-serial.txt` 按架构选择 PyPI wheel：x86_64 使用
`tensorflow-cpu==2.19.0`，AArch64 使用 `tensorflow==2.19.0`。两者导入的模块均为
`tensorflow`，客户端继续强制检查 `tf.__version__ == 2.19.0` 和 `BUILTIN_REF`。
仓库已用 pip 的 AArch64 wheel 解析验证 Python 3.12 对应包存在；其他 CPU 架构不在
支持范围内。

Ubuntu/Debian 通常把 ST-LINK VCP 分配给 `dialout`，OpenOCD 的 USB 访问依赖发行版
提供的 udev 规则。安装 OpenOCD 后重新插拔开发板；若仍无权限，将当前用户加入相应
组并重新登录：

```sh
sudo usermod -aG dialout,plugdev "$USER"
```

设备名不是固定值。烧录前用 `openocd -f flash.cfg -c "init; targets; shutdown"`
探测 ST-LINK；串口端口通过 `/dev/serial/by-id/` 选择，不要在自动化中假定永远是
`/dev/ttyACM0`。

## 5. 烧录与验收

以串口模型固件为例：

```sh
openocd -f flash.cfg -c \
  "program build/linux-all/serial/STM32_deploy.hex verify reset exit"
python tools/serial_model_client.py --port /dev/serial/by-id/<ST-LINK-VCP> info
```

CCA02M2 和 ICS-43434 的接线、LED 与串口判定见
[`App/Microphone/README.md`](../App/Microphone/README.md)。烧录成功只证明 ELF/HEX、
ST-LINK 和 MCU 链路正常；模型准确率、麦克风数据有效性仍必须由串口原始日志和
`predictions.csv` 证明。

## 6. GitHub 干净克隆门禁

`.github/workflows/clean-clone-build.yml` 在独立 Ubuntu runner 上执行以下门禁：

1. 递归检出 `.gitmodules` 记录的 TFLite Micro 精确提交；
2. 安装 Arm GNU 14.2.Rel1 和固定的 Python 构建依赖；
3. 编译检查每个 Python 工具的入口；
4. 调用 `build_all_firmware.py` 构建三个固件目标；
5. 上传三个 HEX/BIN 和带 SHA-256 的 manifest。

只有该工作流在目标提交上通过，才能声称 GitHub 的干净克隆可重新编译。实板测试
不能在普通 GitHub runner 上伪造，仍由 `evidence/`、`board_results/` 中的原始串口
记录和哈希单独验收。
