## 一、汇报整体定位（你先在开头说清楚）

**汇报目标（1 页）**

* 本研究旨在构建一个**低功耗嵌入式鸟类声音识别系统**
* 基于 **STM32 微控制器 + 实时音频采集 + MFCC 特征 + TinyML 推理**
* 中期汇报重点：

  * 系统架构是否可行
  * 关键技术路线是否跑通
  * 已完成哪些核心模块
  * 当前主要问题与后续计划

> 关键词：**可行性验证（Proof of Feasibility）**

---

## 二、研究背景与研究意义（1–2 页）

### 2.1 研究背景

* 生态监测 / 生物多样性监测对**长期、低成本、自动化**设备需求强烈
* 传统方案问题：

  * 人工采样：成本高、连续性差
  * 云端识别：功耗高、通信成本高
* TinyML 提供可能：

  * 在 **MCU 上本地完成音频识别**
  * 低功耗、实时、可长期部署

### 2.2 研究意义

* 学术意义：

  * 探索 **TinyML 在生物声学（Bioacoustics）中的可行性**
  * 流式音频 + MFCC 在 MCU 上的实现方法
* 工程意义：

  * 可部署的嵌入式系统原型
  * 为后续野外节点部署提供基础

---

## 三、整体系统设计（重点，2–3 页）

### 3.1 系统总体架构（强烈建议画图）

**从左到右：**

```
MEMS Mic
   ↓
DFSDM + DMA
   ↓
Audio Ring Buffer（流式）
   ↓
MFCC（CMSIS-DSP）
   ↓
TinyML 推理（TFLite Micro）
   ↓
分类结果（LED / UART）
```

你可以强调一句：

> 本系统采用**完全流式（streaming）架构**，不依赖完整音频缓存。

---

### 3.2 软件模块划分

| 模块            | 功能              |
| ------------- | --------------- |
| Audio Capture | DFSDM + DMA 双缓冲 |
| Audio Stream  | 512 samples 流式帧 |
| MFCC Module   | CMSIS-DSP 实现    |
| Inference     | TFLite Micro    |
| Application   | LED / 状态控制      |

强调你做了**模块化封装**：

* `audio_capture.c`
* `mfcc.c`
* `model_inference.cpp`

---

## 四、关键技术路线（中期汇报核心）

### 4.1 实时音频采集（DFSDM + DMA）

**说明点：**

* 使用 DFSDM 采集数字麦克风
* DMA 双缓冲（Half / Full Callback）
* 中断只置位 flag，不做重计算（实时性保证）

可以说一句专业的话：

> 采用“**ISR 轻量化 + 主循环处理**”的实时架构。

---

### 4.2 流式音频设计（重点）

强调你不是一次性处理 1 秒音频：

* DMA → 512 samples
* 滑窗方式：

  * Frame Length：1024
  * Frame Step：512
* Ring Buffer 维护最近 1 秒音频

这是**TinyML 项目非常加分的点**。

---

### 4.3 MFCC 特征提取（CMSIS-DSP）

你可以按流程讲：

1. Pre-emphasis
2. Hamming Window
3. FFT（`arm_rfft_fast_f32`）
4. Power Spectrum
5. Mel Filterbank
6. Log
7. DCT

强调：

* **完全在 MCU 上运行**
* 使用 CMSIS-DSP 加速
* MFCC 输出维度：`32 × 13`

---

### 4.4 TinyML 推理（当前阶段）

中期可以这样说（很稳）：

* 已完成：

  * 模型从 TensorFlow 转换为 TFLite
  * 成功集成 TFLite Micro 框架
* 当前状态：

  * 推理链路已基本打通
  * 正在解决算子裁剪、内存占用与稳定性问题

不要说“已经全部完成”，中期这样反而危险。

---

## 五、阶段性成果（一定要有）

### 5.1 已完成内容（Checklist）

可以用表格：

* ✔ DFSDM 实时采集
* ✔ DMA 双缓冲
* ✔ 流式音频帧管理
* ✔ MFCC 特征在 STM32 上运行
* ✔ 模块化代码结构
* ✔ LED 结果指示（原型）

### 5.2 当前系统状态

* 实时运行
* 内存占用在可控范围内
* 无阻塞、无丢帧

---

## 六、当前问题与挑战（中期汇报必须有）

这是**导师最关心的部分**。

### 6.1 工程层面

* CMSIS / TFLite Micro 依赖复杂
* 链接错误与裁剪问题
* MCU RAM/Flash 限制

### 6.2 算法层面

* 嵌入式 MFCC 参数与 PC 训练一致性
* 现场噪声干扰
* 类别区分度

### 6.3 系统层面

* 实时性 vs 功耗权衡
* 连续运行稳定性测试尚未完成

---

## 七、下一阶段计划（非常重要）

### 7.1 短期（下一阶段）

* 完成 TinyML 推理稳定运行
* 输出 UART / LED 分类结果
* 简单准确率验证（离线对比）

### 7.2 中期

* 模型结构优化（DS-CNN）
* 降低 RAM / Flash 占用
* 噪声鲁棒性改进

### 7.3 长期

* 野外部署可行性验证
* 多物种扩展
* 低功耗休眠策略

---

## 八、总结（1 页）

模板句（你可以直接用）：

> 本研究在中期阶段已经完成了嵌入式端从音频采集、流式处理到 MFCC 特征提取的完整链路验证，证明了在资源受限的 STM32 平台上实现 TinyML 生物声音识别的可行性。后续工作将重点集中在模型推理稳定性、系统优化与实验验证上。

---

## 九、如果你需要，我还能帮你

接下来我可以直接帮你做的事情包括：

* 给你 **PPT 每一页的标题 + 要点**
* 帮你把这一套**改写成正式学术汇报英文**
* 帮你准备 **导师可能会问的问题与回答**
* 帮你把技术内容压缩成 **10 分钟 / 15 分钟版本**


下面是一份**面向导师/教授的英文中期汇报（Mid-term Presentation）英文汇报稿**，内容紧密围绕你当前的项目状态：**STM32 + DFSDM 音频采集 + 流式 MFCC + TinyML（TFLite Micro）推理**，重点突出**系统架构、已完成工作、技术难点与阶段性成果**，而非“最终性能”。

我按**可直接朗读的英文汇报稿**来写，你可以直接用在 PPT 演讲中；如需“更学术/更口语/缩短版”，我可以再给你改一版。

---

## Title Slide

**Title**
*A Streaming TinyML System for Embedded Animal Sound Recognition*

**Presenter**
Yin Chen

---

## 1. Background and Motivation

> In recent years, automatic animal sound recognition has attracted increasing attention in ecological monitoring and biodiversity research.
>
> Traditional approaches rely either on manual observation or on cloud-based deep learning systems, both of which suffer from high cost, latency, and limited scalability.
>
> Therefore, there is a strong motivation to deploy sound recognition systems directly on low-power embedded devices, enabling continuous, real-time, and low-cost monitoring in the field.

---

## 2. Research Objective

> The objective of this research is to design and implement a **real-time animal sound recognition system on a resource-constrained microcontroller**.
>
> Specifically, the system aims to:
>
> * Capture audio signals continuously using a digital microphone
> * Extract MFCC features in a streaming manner
> * Perform on-device inference using a TinyML model
> * Provide classification results in real time with minimal memory and power consumption

---

## 3. Overall System Architecture

> The overall system consists of three main components:
>
> 1. **Audio acquisition** using DFSDM and DMA on an STM32 microcontroller
> 2. **Feature extraction**, where streaming MFCC features are computed using CMSIS-DSP
> 3. **Inference**, where a TensorFlow Lite for Microcontrollers model performs classification on the extracted features
>
> These three components form a fully embedded, end-to-end pipeline without any external computation.

---

## 4. Hardware and Software Platform

> The current implementation is based on the **STM32L5 series microcontroller**, which provides a good balance between performance, power efficiency, and security features.
>
> On the software side:
>
> * STM32 HAL is used for peripheral control
> * CMSIS-DSP is used for FFT and signal processing
> * TensorFlow Lite for Microcontrollers is used for neural network inference
>
> All components are integrated and built using CMake under a GCC ARM toolchain.

---

## 5. Streaming Audio Capture Design

> For audio capture, the system uses a digital microphone connected via DFSDM.
>
> DMA is configured in circular mode, generating **half-complete and complete interrupts**.
>
> Instead of processing audio in large fixed buffers, the system adopts a **streaming design**, where audio samples are continuously pushed into a ring buffer.
>
> This approach reduces latency and allows real-time feature extraction.

---

## 6. Streaming MFCC Feature Extraction

> MFCC extraction is implemented in a streaming manner.
>
> Each time a new audio frame is available:
>
> * Pre-emphasis and windowing are applied
> * FFT is computed using CMSIS-DSP
> * Mel filterbank energies are calculated
> * Logarithm and DCT are applied to obtain MFCC coefficients
>
> Multiple MFCC frames are accumulated to form a 2D feature map, which matches the input format of the TinyML model.

---

## 7. Model Deployment on TinyML

> The trained neural network model is converted to a TensorFlow Lite format and then deployed using TensorFlow Lite for Microcontrollers.
>
> Due to memory constraints, only a limited number of operators are included in the operator resolver.
>
> The model is stored as a C array in flash memory and executed entirely on the microcontroller without an operating system.

---

## 8. Current Progress (Mid-term Status)

> At the current stage, the following components have been completed:
>
> * DFSDM-based real-time audio capture with DMA
> * Streaming MFCC feature extraction on STM32
> * Successful integration of CMSIS-DSP and TFLite Micro
> * End-to-end data flow from microphone to inference input
>
> The system is now capable of running continuously and producing inference-ready feature data.

---

## 9. Key Challenges Encountered

> Several challenges have been encountered during development:
>
> * Dependency management when integrating CMSIS-DSP and TFLite Micro
> * Memory limitations on the microcontroller
> * Symbol conflicts and missing implementations during static linking
> * Balancing real-time performance with computational cost
>
> These issues required careful build system configuration and modular software design.

---

## 10. Preliminary Results and Demonstration

> As a preliminary demonstration, different inference results are mapped to different LEDs on the development board.
>
> This allows real-time visualization of classification results and provides a simple but effective validation of system behavior.

---

## 11. Future Work

> In the next stage, the following work will be carried out:
>
> * Optimize MFCC parameters and model structure for higher accuracy
> * Extend the system to support multiple animal classes
> * Evaluate performance in real environmental conditions
> * Reduce power consumption for long-term deployment
>
> Ultimately, the goal is to deploy the system as a practical tool for ecological monitoring.

---

## 12. Conclusion

> In this work, a real-time, fully embedded animal sound recognition system based on TinyML has been designed and partially implemented.
>
> The mid-term results demonstrate the feasibility of streaming audio processing and on-device inference on resource-limited hardware.
>
> This lays a solid foundation for further optimization and real-world deployment.

---