# Microphone frontend boundary

此目录保留给后续实时麦克风应用。当前 `STM32_deploy` 的 `serial` 目标不会编译或
调用麦克风采集、SAI/DMA 初始化和 MFCC/LogMel/PCEN 前端。

接入实时音频时，应在这里建立独立应用入口，并只通过稳定的“完整特征张量”接口调用
`App/ModelRuntime`。不要把采集状态、DMA 回调或滑窗状态放入
`App/Serial`/`App/ModelRuntime`，以保持串口回归测试可独立复现。

`Legacy/` 中的旧采集和 MFCC 代码仅供硬件配置参考，不属于任何构建目标；其特征
定义尚未与 Model_train 的所有导出对齐。新的麦克风目标应独立提供 SAI/DMA
初始化和中断适配，并把 PCM16 窗口送入共享的 `App/AudioFrontend`。
