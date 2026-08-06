#include "stm32_deploy_app.h"

#include "stm32l5xx_hal.h"
#include "stm32l5xx_nucleo.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * ICS-43434 diagnostic wiring on NUCLEO-L552ZE-Q:
 *   SCK/BCLK -> PB3  (SAI1_SCK_B, AF13)
 *   WS/LRCLK -> PA4  (SAI1_FS_B,  AF13)
 *   SD/DOUT  -> PB5  (SAI1_SD_B,  AF13)
 *   VDD      -> 3V3
 *   GND      -> GND
 *   L/R      -> GND for left channel, or 3V3 for right channel
 */
#define MIC_SCK_PORT GPIOB
#define MIC_SCK_PIN GPIO_PIN_3
#define MIC_WS_PORT GPIOA
#define MIC_WS_PIN GPIO_PIN_4
#define MIC_SD_PORT GPIOB
#define MIC_SD_PIN GPIO_PIN_5
#define MIC_GPIO_AF GPIO_AF13_SAI1

#define MIC_SAMPLE_RATE_HZ STM32_MIC_SAMPLE_RATE_HZ
#define MIC_FRAME_BITS 64U
#define MIC_CAPTURE_FRAMES 1024U
#define MIC_SLOT_COUNT 2U
#define MIC_CAPTURE_WORDS (MIC_CAPTURE_FRAMES * MIC_SLOT_COUNT)
#define MIC_CAPTURE_TIMEOUT_MS 500U
#define MIC_REPORT_PERIOD_MS 750U

typedef enum
{
  SAMPLE_ALIGNMENT_LSB24 = 0,
  SAMPLE_ALIGNMENT_MSB24 = 1,
} SampleAlignment;

typedef struct
{
  int32_t minimum;
  int32_t maximum;
  int32_t mean;
  uint32_t mean_absolute;
  uint32_t rms;
  uint32_t peak;
  uint32_t peak_to_peak;
  uint32_t nonzero_count;
  uint32_t change_count;
  uint32_t low_byte_nonzero_count;
  SampleAlignment alignment;
} SlotStatistics;

static SAI_HandleTypeDef g_mic_sai;
static uint32_t g_capture[MIC_CAPTURE_WORDS];
static volatile HAL_StatusTypeDef g_sai_msp_status = HAL_OK;

static void SerialWrite(const char *text)
{
  if (text == NULL)
  {
    return;
  }

  size_t length = strlen(text);
  if (length > UINT16_MAX)
  {
    length = UINT16_MAX;
  }
  (void)HAL_UART_Transmit(&hcom_uart[COM1], (uint8_t *)text,
                          (uint16_t)length, 1000U);
}

static void SerialPrintf(const char *format, ...)
{
  char buffer[256];
  va_list arguments;

  va_start(arguments, format);
  int length = vsnprintf(buffer, sizeof(buffer), format, arguments);
  va_end(arguments);

  if (length <= 0)
  {
    return;
  }
  buffer[sizeof(buffer) - 1U] = '\0';
  SerialWrite(buffer);
}

static int InitializeStatusLeds(void)
{
  if (BSP_LED_Init(LED_GREEN) != BSP_ERROR_NONE ||
      BSP_LED_Init(LED_BLUE) != BSP_ERROR_NONE ||
      BSP_LED_Init(LED_RED) != BSP_ERROR_NONE)
  {
    return -1;
  }

  BSP_LED_Off(LED_GREEN);
  BSP_LED_Off(LED_BLUE);
  BSP_LED_Off(LED_RED);
  return 0;
}

static int InitializeSerialPort(void)
{
  COM_InitTypeDef config = {
      .BaudRate = 115200,
      .WordLength = COM_WORDLENGTH_8B,
      .StopBits = COM_STOPBITS_1,
      .Parity = COM_PARITY_NONE,
      .HwFlowCtl = COM_HWCONTROL_NONE,
  };

  return (BSP_COM_Init(COM1, &config) == BSP_ERROR_NONE) ? 0 : -1;
}

void HAL_SAI_MspInit(SAI_HandleTypeDef *hsai)
{
  if (hsai == NULL || hsai->Instance != SAI1_Block_B)
  {
    return;
  }

  RCC_PeriphCLKInitTypeDef peripheral_clock = {0};
  peripheral_clock.PeriphClockSelection = RCC_PERIPHCLK_SAI1;
  peripheral_clock.Sai1ClockSelection = RCC_SAI1CLKSOURCE_PLLSAI1;
  peripheral_clock.PLLSAI1.PLLSAI1Source = RCC_PLLSOURCE_MSI;
  peripheral_clock.PLLSAI1.PLLSAI1M = 1U;
  peripheral_clock.PLLSAI1.PLLSAI1N = 43U;
  peripheral_clock.PLLSAI1.PLLSAI1P = RCC_PLLP_DIV14;
  peripheral_clock.PLLSAI1.PLLSAI1Q = RCC_PLLQ_DIV2;
  peripheral_clock.PLLSAI1.PLLSAI1R = RCC_PLLR_DIV2;
  peripheral_clock.PLLSAI1.PLLSAI1ClockOut = RCC_PLLSAI1_SAI1CLK;

  g_sai_msp_status = HAL_RCCEx_PeriphCLKConfig(&peripheral_clock);
  if (g_sai_msp_status != HAL_OK)
  {
    return;
  }

  __HAL_RCC_SAI1_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {0};
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = MIC_GPIO_AF;

  gpio.Pull = GPIO_NOPULL;
  gpio.Pin = MIC_SCK_PIN;
  HAL_GPIO_Init(MIC_SCK_PORT, &gpio);

  gpio.Pin = MIC_WS_PIN;
  HAL_GPIO_Init(MIC_WS_PORT, &gpio);

  /* Pull SD low so an absent or tri-stated microphone reads as zero. */
  gpio.Pull = GPIO_PULLDOWN;
  gpio.Pin = MIC_SD_PIN;
  HAL_GPIO_Init(MIC_SD_PORT, &gpio);
}

void HAL_SAI_MspDeInit(SAI_HandleTypeDef *hsai)
{
  if (hsai == NULL || hsai->Instance != SAI1_Block_B)
  {
    return;
  }

  HAL_GPIO_DeInit(MIC_SCK_PORT, MIC_SCK_PIN);
  HAL_GPIO_DeInit(MIC_WS_PORT, MIC_WS_PIN);
  HAL_GPIO_DeInit(MIC_SD_PORT, MIC_SD_PIN);
  __HAL_RCC_SAI1_CLK_DISABLE();
}

static int InitializeMicrophoneSai(void)
{
  memset(&g_mic_sai, 0, sizeof(g_mic_sai));
  g_sai_msp_status = HAL_OK;

  g_mic_sai.Instance = SAI1_Block_B;
  g_mic_sai.Init.AudioMode = SAI_MODEMASTER_RX;
  g_mic_sai.Init.Synchro = SAI_ASYNCHRONOUS;
  g_mic_sai.Init.OutputDrive = SAI_OUTPUTDRIVE_ENABLE;
  /* Derive BCLK directly from the 64-bit I2S frame. */
  g_mic_sai.Init.NoDivider = SAI_MASTERDIVIDER_DISABLE;
  g_mic_sai.Init.FIFOThreshold = SAI_FIFOTHRESHOLD_1QF;
  g_mic_sai.Init.AudioFrequency = MIC_SAMPLE_RATE_HZ;
  g_mic_sai.Init.SynchroExt = SAI_SYNCEXT_DISABLE;
  g_mic_sai.Init.MckOutput = SAI_MCK_OUTPUT_DISABLE;
  g_mic_sai.Init.Mckdiv = 0U;
  g_mic_sai.Init.MckOverSampling = SAI_MCK_OVERSAMPLING_DISABLE;
  g_mic_sai.Init.MonoStereoMode = SAI_STEREOMODE;
  g_mic_sai.Init.CompandingMode = SAI_NOCOMPANDING;
  g_mic_sai.Init.TriState = SAI_OUTPUT_NOTRELEASED;

  HAL_StatusTypeDef status = HAL_SAI_InitProtocol(
      &g_mic_sai, SAI_I2S_STANDARD, SAI_PROTOCOL_DATASIZE_24BIT,
      MIC_SLOT_COUNT);
  if (status != HAL_OK || g_sai_msp_status != HAL_OK)
  {
    return -1;
  }
  return 0;
}

static uint32_t AbsoluteSample(int32_t sample)
{
  return (sample < 0) ? (uint32_t)(-(int64_t)sample) : (uint32_t)sample;
}

static uint32_t IntegerSqrt64(uint64_t value)
{
  uint64_t bit = UINT64_C(1) << 62;
  uint64_t result = 0U;

  while (bit > value)
  {
    bit >>= 2U;
  }
  while (bit != 0U)
  {
    if (value >= result + bit)
    {
      value -= result + bit;
      result = (result >> 1U) + bit;
    }
    else
    {
      result >>= 1U;
    }
    bit >>= 2U;
  }
  return (uint32_t)result;
}

static int32_t DecodeSample(uint32_t raw, SampleAlignment alignment)
{
  if (alignment == SAMPLE_ALIGNMENT_MSB24)
  {
    return ((int32_t)raw) >> 8;
  }
  return ((int32_t)(raw << 8)) >> 8;
}

static SlotStatistics AnalyzeSlot(uint32_t slot)
{
  SlotStatistics stats = {0};
  stats.minimum = INT32_MAX;
  stats.maximum = INT32_MIN;

  for (uint32_t frame = 0U; frame < MIC_CAPTURE_FRAMES; ++frame)
  {
    uint32_t raw = g_capture[(frame * MIC_SLOT_COUNT) + slot];
    if ((raw & 0xFFU) != 0U)
    {
      ++stats.low_byte_nonzero_count;
    }
  }

  stats.alignment =
      (stats.low_byte_nonzero_count < (MIC_CAPTURE_FRAMES / 32U))
          ? SAMPLE_ALIGNMENT_MSB24
          : SAMPLE_ALIGNMENT_LSB24;

  int64_t sum = 0;
  uint64_t sum_absolute = 0U;
  uint64_t sum_square = 0U;
  int32_t previous = 0;

  for (uint32_t frame = 0U; frame < MIC_CAPTURE_FRAMES; ++frame)
  {
    uint32_t raw = g_capture[(frame * MIC_SLOT_COUNT) + slot];
    int32_t sample = DecodeSample(raw, stats.alignment);
    uint32_t absolute = AbsoluteSample(sample);

    if (sample < stats.minimum)
    {
      stats.minimum = sample;
    }
    if (sample > stats.maximum)
    {
      stats.maximum = sample;
    }
    if (sample != 0)
    {
      ++stats.nonzero_count;
    }
    if (frame != 0U && sample != previous)
    {
      ++stats.change_count;
    }

    sum += sample;
    sum_absolute += absolute;
    sum_square += (uint64_t)absolute * (uint64_t)absolute;
    previous = sample;
  }

  stats.mean = (int32_t)(sum / (int64_t)MIC_CAPTURE_FRAMES);
  stats.mean_absolute = (uint32_t)(sum_absolute / MIC_CAPTURE_FRAMES);
  stats.rms = IntegerSqrt64(sum_square / MIC_CAPTURE_FRAMES);
  stats.peak = (AbsoluteSample(stats.minimum) > AbsoluteSample(stats.maximum))
                   ? AbsoluteSample(stats.minimum)
                   : AbsoluteSample(stats.maximum);
  stats.peak_to_peak = (uint32_t)((int64_t)stats.maximum - stats.minimum);
  return stats;
}

static uint64_t SlotActivity(const SlotStatistics *stats)
{
  return (uint64_t)stats->mean_absolute + stats->peak_to_peak +
         ((uint64_t)stats->change_count * 16U);
}

static int SlotLooksValid(const SlotStatistics *stats)
{
  return stats->nonzero_count >= (MIC_CAPTURE_FRAMES / 8U) &&
         stats->change_count >= (MIC_CAPTURE_FRAMES / 8U) &&
         stats->peak_to_peak >= 64U;
}

static void PrintSlot(const char *name, const SlotStatistics *stats)
{
  const char *alignment = (stats->alignment == SAMPLE_ALIGNMENT_MSB24)
                              ? "MSB24"
                              : "LSB24";
  SerialPrintf(
      "%s align=%s min=%ld max=%ld mean=%ld mean_abs=%lu rms=%lu "
      "peak=%lu p2p=%lu nonzero=%lu changes=%lu\r\n",
      name, alignment, (long)stats->minimum, (long)stats->maximum,
      (long)stats->mean, (unsigned long)stats->mean_absolute,
      (unsigned long)stats->rms, (unsigned long)stats->peak,
      (unsigned long)stats->peak_to_peak,
      (unsigned long)stats->nonzero_count,
      (unsigned long)stats->change_count);
}

static void PrintSamplePreview(uint32_t slot, SampleAlignment alignment)
{
  SerialWrite("samples=");
  for (uint32_t frame = 0U; frame < 12U; ++frame)
  {
    int32_t sample = DecodeSample(
        g_capture[(frame * MIC_SLOT_COUNT) + slot], alignment);
    SerialPrintf("%s%ld", (frame == 0U) ? "" : ",", (long)sample);
  }
  SerialWrite("\r\n");
}

static void SetVerdictLeds(int passed)
{
  if (passed != 0)
  {
    BSP_LED_On(LED_GREEN);
    BSP_LED_Off(LED_RED);
  }
  else
  {
    BSP_LED_Off(LED_GREEN);
    BSP_LED_On(LED_RED);
  }
  BSP_LED_Toggle(LED_BLUE);
}

static void ReportCapture(uint32_t sequence)
{
  SlotStatistics left = AnalyzeSlot(0U);
  SlotStatistics right = AnalyzeSlot(1U);
  uint32_t active_slot =
      (SlotActivity(&right) > SlotActivity(&left)) ? 1U : 0U;
  const SlotStatistics *active = (active_slot == 0U) ? &left : &right;
  int passed = SlotLooksValid(active);

  SerialPrintf("\r\nMIC_TEST seq=%lu capture=OK active=%s verdict=%s\r\n",
               (unsigned long)sequence,
               (active_slot == 0U) ? "LEFT" : "RIGHT",
               (passed != 0) ? "PASS" : "FAIL");
  PrintSlot("LEFT ", &left);
  PrintSlot("RIGHT", &right);
  PrintSamplePreview(active_slot, active->alignment);

  if (passed == 0)
  {
    SerialWrite(
        "hint=No changing I2S audio detected; check 3V3/GND, PB3/PA4/PB5, "
        "and tie L/R firmly to GND or 3V3.\r\n");
  }
  SetVerdictLeds(passed);
}

int STM32DeployApp_Run(void)
{
  if (InitializeStatusLeds() != 0)
  {
    return -1;
  }
  if (InitializeSerialPort() != 0)
  {
    BSP_LED_On(LED_RED);
    return -1;
  }

  SerialWrite("\r\nSTM32_deploy ICS-43434 microphone diagnostic\r\n");
  SerialPrintf("UART=115200 8N1 | I2S=%luHz/24-bit/2-slot\r\n",
               (unsigned long)MIC_SAMPLE_RATE_HZ);
  SerialWrite("wire: 3V3->VDD GND->GND PB3->SCK PA4->WS PB5->SD "
              "L/R->GND(left) or 3V3(right)\r\n");

  if (InitializeMicrophoneSai() != 0)
  {
    SerialPrintf("MIC_INIT FAIL hal=%lu msp=%lu\r\n",
                 (unsigned long)g_mic_sai.ErrorCode,
                 (unsigned long)g_sai_msp_status);
    BSP_LED_On(LED_RED);
    return -1;
  }

  uint32_t kernel_clock = HAL_RCCEx_GetPeriphCLKFreq(RCC_PERIPHCLK_SAI1);
  uint32_t divider = g_mic_sai.Init.Mckdiv;
  uint32_t actual_rate = (divider == 0U)
                             ? 0U
                             : kernel_clock / (divider * MIC_FRAME_BITS);
  SerialPrintf("MIC_INIT OK sai_clk=%luHz divider=%lu fs~%luHz\r\n",
               (unsigned long)kernel_clock, (unsigned long)divider,
               (unsigned long)actual_rate);

  /* Start clocks and discard the wake-up interval required by the microphone. */
  memset(g_capture, 0, sizeof(g_capture));
  HAL_StatusTypeDef status = HAL_SAI_Receive(
      &g_mic_sai, (uint8_t *)g_capture, MIC_CAPTURE_WORDS,
      MIC_CAPTURE_TIMEOUT_MS);
  if (status != HAL_OK)
  {
    SerialPrintf("MIC_WARMUP FAIL status=%lu error=0x%08lx\r\n",
                 (unsigned long)status,
                 (unsigned long)g_mic_sai.ErrorCode);
    BSP_LED_On(LED_RED);
    return -1;
  }

  uint32_t sequence = 0U;
  for (;;)
  {
    memset(g_capture, 0, sizeof(g_capture));
    status = HAL_SAI_Receive(&g_mic_sai, (uint8_t *)g_capture,
                             MIC_CAPTURE_WORDS, MIC_CAPTURE_TIMEOUT_MS);
    if (status == HAL_OK)
    {
      ReportCapture(++sequence);
    }
    else
    {
      SerialPrintf("MIC_CAPTURE FAIL status=%lu error=0x%08lx\r\n",
                   (unsigned long)status,
                   (unsigned long)g_mic_sai.ErrorCode);
      SetVerdictLeds(0);
    }
    HAL_Delay(MIC_REPORT_PERIOD_MS);
  }
}
