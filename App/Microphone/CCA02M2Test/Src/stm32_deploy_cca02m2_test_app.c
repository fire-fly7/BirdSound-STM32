#include "stm32_deploy_app.h"

#include "stm32l5xx_hal.h"
#include "stm32l5xx_nucleo.h"

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

/*
 * X-NUCLEO-CCA02M2 jumper diagnostic on NUCLEO-L552ZE-Q:
 *   CCA02M2 CN10-29 (MIC_CLK_NUCLEO) -> Nucleo CN10-9 (A7/PC2)
 *   CCA02M2 CN10-26 (MIC_PDM12)      -> Nucleo CN10-7 (A6/PB1)
 *   CCA02M2 3V3/GND                  -> Nucleo 3V3/GND
 *
 * Required CCA02M2 routing: SB7 and SB11 closed, J2 at 1-2, J3 open.
 * PC2 is DFSDM1_CKOUT and PB1 is DFSDM1_DATIN0 (AF6).
 */
#define PDM_CLOCK_PORT GPIOC
#define PDM_CLOCK_PIN GPIO_PIN_2
#define PDM_DATA_PORT GPIOB
#define PDM_DATA_PIN GPIO_PIN_1
#define PDM_GPIO_AF GPIO_AF6_DFSDM1

#define PDM_CLOCK_DIVIDER 55U
#define PDM_CLOCK_HZ 2000000U
#define PCM_SAMPLE_RATE_HZ 16000U
#define DFSDM_FILTER_OVERSAMPLING 125U
#define DFSDM_RIGHT_BIT_SHIFT 5U
#define CAPTURE_SAMPLES 1024U
#define WARMUP_SAMPLES 256U
#define RAW_PIN_READS 200000U
#define SAMPLE_TIMEOUT_MS 20U
#define REPORT_PERIOD_MS 750U

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
} CaptureStatistics;

typedef struct
{
  uint32_t clock_high_count;
  uint32_t clock_change_count;
  uint32_t data_high_count;
  uint32_t data_change_count;
} RawPinStatistics;

static DFSDM_Channel_HandleTypeDef g_dfsdm_channel;
static DFSDM_Filter_HandleTypeDef g_dfsdm_filter;
static int32_t g_rising_samples[CAPTURE_SAMPLES];
static int32_t g_falling_samples[CAPTURE_SAMPLES];
static RawPinStatistics g_rising_pins;
static RawPinStatistics g_falling_pins;

static void SerialWrite(const char *message)
{
  if (message == NULL)
  {
    return;
  }

  size_t length = strlen(message);
  if (length > UINT16_MAX)
  {
    length = UINT16_MAX;
  }
  (void)HAL_UART_Transmit(&hcom_uart[COM1], (uint8_t *)message,
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

static int InitializeSerialPort(void)
{
  COM_InitTypeDef configuration = {
      .BaudRate = 115200,
      .WordLength = COM_WORDLENGTH_8B,
      .StopBits = COM_STOPBITS_1,
      .Parity = COM_PARITY_NONE,
      .HwFlowCtl = COM_HWCONTROL_NONE,
  };

  return (BSP_COM_Init(COM1, &configuration) == BSP_ERROR_NONE) ? 0 : -1;
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

void HAL_DFSDM_ChannelMspInit(DFSDM_Channel_HandleTypeDef *channel)
{
  if (channel == NULL || channel->Instance != DFSDM1_Channel0)
  {
    return;
  }

  __HAL_RCC_DFSDM1_CLK_ENABLE();
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();

  GPIO_InitTypeDef gpio = {0};
  gpio.Mode = GPIO_MODE_AF_PP;
  gpio.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
  gpio.Alternate = PDM_GPIO_AF;

  gpio.Pull = GPIO_NOPULL;
  gpio.Pin = PDM_CLOCK_PIN;
  HAL_GPIO_Init(PDM_CLOCK_PORT, &gpio);

  /* A disconnected PDM input becomes a stable zero-level diagnostic failure. */
  gpio.Pull = GPIO_PULLDOWN;
  gpio.Pin = PDM_DATA_PIN;
  HAL_GPIO_Init(PDM_DATA_PORT, &gpio);
}

void HAL_DFSDM_ChannelMspDeInit(DFSDM_Channel_HandleTypeDef *channel)
{
  if (channel == NULL || channel->Instance != DFSDM1_Channel0)
  {
    return;
  }

  HAL_GPIO_DeInit(PDM_CLOCK_PORT, PDM_CLOCK_PIN);
  HAL_GPIO_DeInit(PDM_DATA_PORT, PDM_DATA_PIN);
  __HAL_RCC_DFSDM1_CLK_DISABLE();
}

static int InitializeDfsdm(uint32_t edge)
{
  memset(&g_dfsdm_channel, 0, sizeof(g_dfsdm_channel));
  memset(&g_dfsdm_filter, 0, sizeof(g_dfsdm_filter));

  __HAL_DFSDM_CHANNEL_RESET_HANDLE_STATE(&g_dfsdm_channel);
  g_dfsdm_channel.Instance = DFSDM1_Channel0;
  g_dfsdm_channel.Init.OutputClock.Activation = ENABLE;
  g_dfsdm_channel.Init.OutputClock.Selection =
      DFSDM_CHANNEL_OUTPUT_CLOCK_SYSTEM;
  g_dfsdm_channel.Init.OutputClock.Divider = PDM_CLOCK_DIVIDER;
  g_dfsdm_channel.Init.Input.Multiplexer = DFSDM_CHANNEL_EXTERNAL_INPUTS;
  g_dfsdm_channel.Init.Input.DataPacking = DFSDM_CHANNEL_STANDARD_MODE;
  g_dfsdm_channel.Init.Input.Pins = DFSDM_CHANNEL_SAME_CHANNEL_PINS;
  g_dfsdm_channel.Init.SerialInterface.Type = edge;
  g_dfsdm_channel.Init.SerialInterface.SpiClock =
      DFSDM_CHANNEL_SPI_CLOCK_INTERNAL;
  g_dfsdm_channel.Init.Awd.FilterOrder = DFSDM_CHANNEL_FASTSINC_ORDER;
  g_dfsdm_channel.Init.Awd.Oversampling = 1U;
  g_dfsdm_channel.Init.Offset = 0;
  g_dfsdm_channel.Init.RightBitShift = DFSDM_RIGHT_BIT_SHIFT;
  if (HAL_DFSDM_ChannelInit(&g_dfsdm_channel) != HAL_OK)
  {
    return -1;
  }

  __HAL_DFSDM_FILTER_RESET_HANDLE_STATE(&g_dfsdm_filter);
  g_dfsdm_filter.Instance = DFSDM1_Filter0;
  g_dfsdm_filter.Init.RegularParam.Trigger = DFSDM_FILTER_SW_TRIGGER;
  g_dfsdm_filter.Init.RegularParam.FastMode = ENABLE;
  g_dfsdm_filter.Init.RegularParam.DmaMode = DISABLE;
  g_dfsdm_filter.Init.InjectedParam.Trigger = DFSDM_FILTER_SW_TRIGGER;
  g_dfsdm_filter.Init.InjectedParam.ScanMode = DISABLE;
  g_dfsdm_filter.Init.InjectedParam.DmaMode = DISABLE;
  g_dfsdm_filter.Init.InjectedParam.ExtTrigger =
      DFSDM_FILTER_EXT_TRIG_TIM1_TRGO;
  g_dfsdm_filter.Init.InjectedParam.ExtTriggerEdge =
      DFSDM_FILTER_EXT_TRIG_RISING_EDGE;
  g_dfsdm_filter.Init.FilterParam.SincOrder = DFSDM_FILTER_SINC3_ORDER;
  g_dfsdm_filter.Init.FilterParam.Oversampling =
      DFSDM_FILTER_OVERSAMPLING;
  g_dfsdm_filter.Init.FilterParam.IntOversampling = 1U;
  if (HAL_DFSDM_FilterInit(&g_dfsdm_filter) != HAL_OK)
  {
    (void)HAL_DFSDM_ChannelDeInit(&g_dfsdm_channel);
    return -1;
  }

  if (HAL_DFSDM_FilterConfigRegChannel(
          &g_dfsdm_filter, DFSDM_CHANNEL_0,
          DFSDM_CONTINUOUS_CONV_ON) != HAL_OK)
  {
    (void)HAL_DFSDM_FilterDeInit(&g_dfsdm_filter);
    (void)HAL_DFSDM_ChannelDeInit(&g_dfsdm_channel);
    return -1;
  }
  return 0;
}

static void DeinitializeDfsdm(void)
{
  (void)HAL_DFSDM_FilterDeInit(&g_dfsdm_filter);
  (void)HAL_DFSDM_ChannelDeInit(&g_dfsdm_channel);
}

static int ReadOneSample(int32_t *sample)
{
  uint32_t channel = 0U;
  HAL_StatusTypeDef status = HAL_DFSDM_FilterPollForRegConversion(
      &g_dfsdm_filter, SAMPLE_TIMEOUT_MS);
  if (status != HAL_OK)
  {
    return -1;
  }

  *sample = HAL_DFSDM_FilterGetRegularValue(&g_dfsdm_filter, &channel);
  return (channel == 0U) ? 0 : -1;
}

static RawPinStatistics SampleRawPins(void)
{
  RawPinStatistics statistics = {0};
  uint32_t previous_clock =
      ((PDM_CLOCK_PORT->IDR & PDM_CLOCK_PIN) != 0U) ? 1U : 0U;
  uint32_t previous_data =
      ((PDM_DATA_PORT->IDR & PDM_DATA_PIN) != 0U) ? 1U : 0U;

  for (uint32_t index = 0U; index < RAW_PIN_READS; ++index)
  {
    uint32_t clock =
        ((PDM_CLOCK_PORT->IDR & PDM_CLOCK_PIN) != 0U) ? 1U : 0U;
    uint32_t data =
        ((PDM_DATA_PORT->IDR & PDM_DATA_PIN) != 0U) ? 1U : 0U;
    statistics.clock_high_count += clock;
    statistics.data_high_count += data;
    if (clock != previous_clock)
    {
      ++statistics.clock_change_count;
    }
    if (data != previous_data)
    {
      ++statistics.data_change_count;
    }
    previous_clock = clock;
    previous_data = data;
  }
  return statistics;
}

static int CaptureEdge(uint32_t edge, int32_t *samples,
                       RawPinStatistics *pin_statistics)
{
  if (InitializeDfsdm(edge) != 0)
  {
    return -1;
  }
  *pin_statistics = SampleRawPins();
  if (HAL_DFSDM_FilterRegularStart(&g_dfsdm_filter) != HAL_OK)
  {
    DeinitializeDfsdm();
    return -1;
  }

  int32_t discarded = 0;
  for (uint32_t index = 0U; index < WARMUP_SAMPLES; ++index)
  {
    if (ReadOneSample(&discarded) != 0)
    {
      (void)HAL_DFSDM_FilterRegularStop(&g_dfsdm_filter);
      DeinitializeDfsdm();
      return -1;
    }
  }
  for (uint32_t index = 0U; index < CAPTURE_SAMPLES; ++index)
  {
    if (ReadOneSample(&samples[index]) != 0)
    {
      (void)HAL_DFSDM_FilterRegularStop(&g_dfsdm_filter);
      DeinitializeDfsdm();
      return -1;
    }
  }

  (void)HAL_DFSDM_FilterRegularStop(&g_dfsdm_filter);
  DeinitializeDfsdm();
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

static CaptureStatistics AnalyzeCapture(const int32_t *samples)
{
  CaptureStatistics statistics = {0};
  statistics.minimum = INT32_MAX;
  statistics.maximum = INT32_MIN;
  int64_t sum = 0;
  uint64_t sum_absolute = 0U;
  uint64_t sum_square = 0U;
  int32_t previous = 0;

  for (uint32_t index = 0U; index < CAPTURE_SAMPLES; ++index)
  {
    int32_t sample = samples[index];
    uint32_t absolute = AbsoluteSample(sample);
    if (sample < statistics.minimum)
    {
      statistics.minimum = sample;
    }
    if (sample > statistics.maximum)
    {
      statistics.maximum = sample;
    }
    if (sample != 0)
    {
      ++statistics.nonzero_count;
    }
    if (index != 0U && sample != previous)
    {
      ++statistics.change_count;
    }
    sum += sample;
    sum_absolute += absolute;
    sum_square += (uint64_t)absolute * (uint64_t)absolute;
    previous = sample;
  }

  statistics.mean = (int32_t)(sum / (int64_t)CAPTURE_SAMPLES);
  statistics.mean_absolute = (uint32_t)(sum_absolute / CAPTURE_SAMPLES);
  statistics.rms = IntegerSqrt64(sum_square / CAPTURE_SAMPLES);
  statistics.peak =
      (AbsoluteSample(statistics.minimum) > AbsoluteSample(statistics.maximum))
          ? AbsoluteSample(statistics.minimum)
          : AbsoluteSample(statistics.maximum);
  statistics.peak_to_peak =
      (uint32_t)((int64_t)statistics.maximum - statistics.minimum);
  return statistics;
}

static int CaptureLooksValid(const CaptureStatistics *statistics)
{
  return statistics->nonzero_count >= (CAPTURE_SAMPLES / 8U) &&
         statistics->change_count >= (CAPTURE_SAMPLES / 8U) &&
         statistics->peak_to_peak >= 16U;
}

static void PrintCapture(const char *edge, const CaptureStatistics *statistics,
                         const int32_t *samples,
                         const RawPinStatistics *pin_statistics)
{
  SerialPrintf(
      "%s_raw reads=%lu clk_high=%lu clk_changes=%lu data_high=%lu "
      "data_changes=%lu\r\n",
      edge, (unsigned long)RAW_PIN_READS,
      (unsigned long)pin_statistics->clock_high_count,
      (unsigned long)pin_statistics->clock_change_count,
      (unsigned long)pin_statistics->data_high_count,
      (unsigned long)pin_statistics->data_change_count);
  SerialPrintf(
      "%s min=%ld max=%ld mean=%ld mean_abs=%lu rms=%lu peak=%lu "
      "p2p=%lu nonzero=%lu changes=%lu valid=%s\r\n",
      edge, (long)statistics->minimum, (long)statistics->maximum,
      (long)statistics->mean, (unsigned long)statistics->mean_absolute,
      (unsigned long)statistics->rms, (unsigned long)statistics->peak,
      (unsigned long)statistics->peak_to_peak,
      (unsigned long)statistics->nonzero_count,
      (unsigned long)statistics->change_count,
      CaptureLooksValid(statistics) ? "YES" : "NO");

  SerialPrintf("%s_samples=", edge);
  for (uint32_t index = 0U; index < 12U; ++index)
  {
    SerialPrintf("%s%ld", (index == 0U) ? "" : ",", (long)samples[index]);
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

  SerialWrite("\r\nSTM32_deploy X-NUCLEO-CCA02M2 PDM diagnostic\r\n");
  SerialPrintf("UART=115200 8N1 | CKOUT=PC2/%luHz DATA=PB1 "
               "PCM~%luHz\r\n",
               (unsigned long)PDM_CLOCK_HZ,
               (unsigned long)PCM_SAMPLE_RATE_HZ);
  SerialWrite("wire: Nucleo A7/PC2->CCA CN10-29, "
              "Nucleo A6/PB1<-CCA CN10-26, 3V3, GND\r\n");
  SerialWrite("board: J1=open J2=1-2 J3=open SB7=closed SB11=closed\r\n");

  uint32_t sequence = 0U;
  for (;;)
  {
    int rising_ok = CaptureEdge(DFSDM_CHANNEL_SPI_RISING,
                                g_rising_samples, &g_rising_pins) == 0;
    int falling_ok = CaptureEdge(DFSDM_CHANNEL_SPI_FALLING,
                                 g_falling_samples, &g_falling_pins) == 0;

    if (rising_ok != 0 && falling_ok != 0)
    {
      CaptureStatistics rising = AnalyzeCapture(g_rising_samples);
      CaptureStatistics falling = AnalyzeCapture(g_falling_samples);
      int passed = CaptureLooksValid(&rising) || CaptureLooksValid(&falling);

      SerialPrintf("\r\nCCA02M2_TEST seq=%lu capture=OK verdict=%s\r\n",
                   (unsigned long)++sequence, passed ? "PASS" : "FAIL");
      PrintCapture("RISING ", &rising, g_rising_samples, &g_rising_pins);
      PrintCapture("FALLING", &falling, g_falling_samples, &g_falling_pins);
      if (passed == 0)
      {
        SerialWrite("hint=No changing PDM detected; check 3V3/GND, "
                    "PC2/CN10-29, PB1/CN10-26, SB7/SB11 and J2.\r\n");
      }
      SetVerdictLeds(passed);
    }
    else
    {
      SerialPrintf("\r\nCCA02M2_TEST seq=%lu capture=FAIL rising=%s "
                   "falling=%s filter_error=0x%08lx\r\n",
                   (unsigned long)++sequence,
                   rising_ok ? "OK" : "ERROR",
                   falling_ok ? "OK" : "ERROR",
                   (unsigned long)g_dfsdm_filter.ErrorCode);
      SetVerdictLeds(0);
    }
    HAL_Delay(REPORT_PERIOD_MS);
  }
}
