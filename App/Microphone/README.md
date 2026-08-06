# Microphone frontend boundary

此目录保留给后续实时麦克风应用。当前 `STM32_deploy` 的 `serial` 目标不会编译或
调用麦克风采集、SAI/DMA 初始化和 MFCC/LogMel/PCEN 前端。

接入实时音频时，应在这里建立独立应用入口，并只通过稳定的“完整特征张量”接口调用
`App/ModelRuntime`。不要把采集状态、DMA 回调或滑窗状态放入
`App/Serial`/`App/ModelRuntime`，以保持串口回归测试可独立复现。

`Legacy/` 中的旧采集和 MFCC 代码仅供硬件配置参考，不属于任何构建目标；其特征
定义尚未与 Model_train 的所有导出对齐。新的麦克风目标应独立提供 SAI/DMA
初始化和中断适配，并把 PCM16 窗口送入共享的 `App/AudioFrontend`。

## ICS-43434 实板诊断固件

`microphone_test` 是独立于模型和串口回放实验的诊断目标。它以 16 kHz、24-bit、
64 bit/帧的标准 I²S 连续采集，通过 ST-LINK VCP 输出左右槽位的幅度和变化统计。

| ICS-43434 模块 | NUCLEO-L552ZE-Q | 功能 |
| --- | --- | --- |
| VDD | 3V3 | 仅使用 3.3 V，不要接 5 V |
| GND | GND | 共地 |
| SCK / BCLK | PB3 | SAI1_SCK_B, AF13 |
| WS / LRCLK | PA4 | SAI1_FS_B, AF13 |
| SD / DOUT | PB5 | SAI1_SD_B, AF13 |
| L/R | GND 或 3V3 | GND=左声道，3V3=右声道 |

构建与烧录：

```bash
cmake -S . -B build/microphone_test \
  -DSTM32_DEPLOY_APP=microphone_test \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build/microphone_test --parallel 4
openocd -f flash.cfg -c \
  "program build/microphone_test/STM32_deploy.hex verify reset exit"
```

默认的 `STM32_MIC_SAMPLE_RATE_HZ=16000` 用于与模型输入对齐。若要排查模块的高性能模式，
可在独立构建目录增加 `-DSTM32_MIC_SAMPLE_RATE_HZ=48000`。

串口为 115200 8N1。`verdict=PASS` 时绿灯亮，`verdict=FAIL` 时红灯亮，蓝灯每次完成
一段采集后翻转。固件会自动识别 L/R 选择的有效槽位；未接麦克风时 SD 内部下拉，
应稳定报告 `FAIL`。

## X-NUCLEO-CCA02M2 跳线诊断固件

`cca02m2_test` 是独立的 PDM/DFSDM 诊断目标，不替换 ICS-43434 的标准 I2S
目标。它在 PC2 输出 2 MHz PDM 时钟，从 PB1 读取数据，并分别检查上升沿和下降沿，
因此可覆盖 CCA02M2 两个板载麦克风的左右沿选择。

| NUCLEO-L552ZE-Q | X-NUCLEO-CCA02M2 | 功能 |
| --- | --- | --- |
| CN8-7 (3V3) | CN7-12 (3V3) | 3.3 V 供电 |
| CN8-11 (GND) | CN7-20 (GND) | 共地 |
| CN10-9 (A7/PC2) | CN10-29 (MIC_CLK_NUCLEO) | PDM 时钟 |
| CN10-7 (A6/PB1) | CN10-26 (MIC_PDM12) | PDM 数据 |

CCA02M2 应设置为 `J1=open`、`J2=1-2`、`J3=open`、`SB7=closed`、
`SB11=closed`。构建和烧录：

```bash
cmake -S . -B build/cca02m2_test \
  -DSTM32_DEPLOY_APP=cca02m2_test \
  -DCMAKE_BUILD_TYPE=Release
cmake --build build/cca02m2_test --parallel 4
openocd -f flash.cfg -c \
  "program build/cca02m2_test/STM32_deploy.hex verify reset exit"
```
