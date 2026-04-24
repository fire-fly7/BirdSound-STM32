/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file           : main.c
  * @brief          : Main program body
  ******************************************************************************
  * @attention
  *
  * Copyright (c) 2025 STMicroelectronics.
  * All rights reserved.
  *
  * This software is licensed under terms that can be found in the LICENSE file
  * in the root directory of this software component.
  * If no LICENSE file comes with this software, it is provided AS-IS.
  *
  ******************************************************************************
  */
/* USER CODE END Header */
/* Includes ------------------------------------------------------------------*/
#include "main.h"

/* Private includes ----------------------------------------------------------*/
/* USER CODE BEGIN Includes */
#include <string.h>


/* USER CODE END Includes */

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN PTD */
typedef enum
{
  TEST_STAGE_BOOT = 0,
  TEST_STAGE_AUDIO_CAPTURE,
  TEST_STAGE_MFCC_READY,
  TEST_STAGE_UART_TX,
  TEST_STAGE_FAULT
} test_stage_t;

/* USER CODE END PTD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN PD */
static float audio_512[AUDIO_FRAME_STEP];
static float mfcc_32x13[MFCC_NUM_FRAMES * MFCC_NUM_COEFF];
#define DEBUG_UART_TIMEOUT_MS 100U


/* USER CODE END PD */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN PM */

/* USER CODE END PM */

/* Private variables ---------------------------------------------------------*/

COM_InitTypeDef BspCOMInit;
DMA_HandleTypeDef hdma_dma_generator0;
SAI_HandleTypeDef hsai_BlockB1;
DFSDM_Filter_HandleTypeDef hdfsdm1_filter0;
DFSDM_Channel_HandleTypeDef hdfsdm1_channel0;
DMA_HandleTypeDef hdma_dfsdm1_flt0;
DMA_HandleTypeDef hdma_sai1_b;
/* USER CODE BEGIN PV */
static test_stage_t g_test_stage = TEST_STAGE_BOOT;
static uint32_t audio_frame_count = 0;
static uint32_t mfcc_capture_count = 0;
static uint32_t last_frame_peak_milli = 0;

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
void SystemClock_Config(void);
static void MX_GPIO_Init(void);
static void MX_DMA_Init(void);
static void MX_ICACHE_Init(void);
static void MX_DFSDM1_Init(void);
/* USER CODE BEGIN PFP */
static void Debug_Print(const char *message);
static void SetTestStage(test_stage_t stage);
static uint32_t ComputeFramePeakMilli(const float *samples, uint32_t sample_count);
static int32_t FloatToMilli(float value);
static void TransmitMfccSnapshot(void);

/* USER CODE END PFP */

/* Private user code ---------------------------------------------------------*/
/* USER CODE BEGIN 0 */
static void Debug_Print(const char *message)
{
  HAL_UART_Transmit(&hcom_uart[COM1],
                    (uint8_t *)message,
                    (uint16_t)strlen(message),
                    DEBUG_UART_TIMEOUT_MS);
}

static void SetTestStage(test_stage_t stage)
{
  g_test_stage = stage;

  BSP_LED_Off(LED_GREEN);
  BSP_LED_Off(LED_BLUE);
  BSP_LED_Off(LED_RED);

  switch (stage)
  {
    case TEST_STAGE_AUDIO_CAPTURE:
      BSP_LED_On(LED_GREEN);
      break;

    case TEST_STAGE_MFCC_READY:
      BSP_LED_On(LED_BLUE);
      break;

    case TEST_STAGE_UART_TX:
      BSP_LED_On(LED_RED);
      break;

    case TEST_STAGE_FAULT:
      BSP_LED_On(LED_RED);
      break;

    case TEST_STAGE_BOOT:
    default:
      break;
  }
}

static uint32_t ComputeFramePeakMilli(const float *samples, uint32_t sample_count)
{
  float peak = 0.0f;

  for (uint32_t i = 0; i < sample_count; i++)
  {
    float value = samples[i];

    if (value < 0.0f)
    {
      value = -value;
    }

    if (value > peak)
    {
      peak = value;
    }
  }

  return (uint32_t)(peak * 1000.0f);
}

static int32_t FloatToMilli(float value)
{
  if (value >= 0.0f)
  {
    return (int32_t)(value * 1000.0f + 0.5f);
  }

  return (int32_t)(value * 1000.0f - 0.5f);
}

static void TransmitMfccSnapshot(void)
{
  char line[256];

  snprintf(line,
           sizeof(line),
           "MFCC_BEGIN,%lu,FRAMES=%lu,PEAK_MILLI=%lu,SCALE=1000\r\n",
           (unsigned long)mfcc_capture_count,
           (unsigned long)audio_frame_count,
           (unsigned long)last_frame_peak_milli);
  Debug_Print(line);

  for (uint32_t row = 0; row < MFCC_NUM_FRAMES; row++)
  {
    int length = snprintf(line,
                          sizeof(line),
                          "MFCC_ROW,%lu,%lu",
                          (unsigned long)mfcc_capture_count,
                          (unsigned long)row);

    for (uint32_t col = 0; col < MFCC_NUM_COEFF; col++)
    {
      int32_t value_milli =
          FloatToMilli(mfcc_32x13[row * MFCC_NUM_COEFF + col]);

      length += snprintf(line + length,
                         sizeof(line) - (size_t)length,
                         ",%ld",
                         (long)value_milli);
    }

    length += snprintf(line + length,
                       sizeof(line) - (size_t)length,
                       "\r\n");

    HAL_UART_Transmit(&hcom_uart[COM1],
                      (uint8_t *)line,
                      (uint16_t)length,
                      DEBUG_UART_TIMEOUT_MS);
  }

  snprintf(line,
           sizeof(line),
           "MFCC_END,%lu\r\n",
           (unsigned long)mfcc_capture_count);
  Debug_Print(line);
}

/* USER CODE END 0 */

/**
  * @brief  The application entry point.
  * @retval int
  */
int main(void)
{

  /* USER CODE BEGIN 1 */

  /* USER CODE END 1 */

  /* MCU Configuration--------------------------------------------------------*/

  /* Reset of all peripherals, Initializes the Flash interface and the Systick. */
  HAL_Init();

  /* USER CODE BEGIN Init */

  /* USER CODE END Init */

  /* Configure the system clock */
  SystemClock_Config();

  /* USER CODE BEGIN SysInit */

  /* USER CODE END SysInit */

  /* Initialize all configured peripherals */
  MX_GPIO_Init();
  MX_DMA_Init();
  MX_ICACHE_Init();
  MX_DFSDM1_Init();

  /* Initialize leds */
  BSP_LED_Init(LED_GREEN);
  BSP_LED_Init(LED_BLUE);
  BSP_LED_Init(LED_RED);

  /* Initialize USER push-button, will be used to trigger an interrupt each time it's pressed.*/
  BSP_PB_Init(BUTTON_USER, BUTTON_MODE_EXTI);

  /* Initialize COM1 port (115200, 8 bits (7-bit data + 1 stop bit), no parity */
  BspCOMInit.BaudRate   = 115200;
  BspCOMInit.WordLength = COM_WORDLENGTH_8B;
  BspCOMInit.StopBits   = COM_STOPBITS_1;
  BspCOMInit.Parity     = COM_PARITY_NONE;
  BspCOMInit.HwFlowCtl  = COM_HWCONTROL_NONE;
  if (BSP_COM_Init(COM1, &BspCOMInit) != BSP_ERROR_NONE)
  {
    Error_Handler();
  }

  /* USER CODE BEGIN 2 */
  Audio_Init();
  MFCC_Init();
  if (!Audio_Start())
  {
    SetTestStage(TEST_STAGE_FAULT);
    Error_Handler();
  }
  audio_frame_count = 0;
  mfcc_capture_count = 0;
  last_frame_peak_milli = 0;
  SetTestStage(TEST_STAGE_AUDIO_CAPTURE);
  Debug_Print("PDM DFSDM AUDIO+MFCC TEST INIT\r\n");
  /* USER CODE END 2 */

  /* Infinite loop */
  /* USER CODE BEGIN WHILE */
  while (1)
  {
    if(Audio_FrameReady())
    {
        char msg[96];

        Audio_GetFrame(audio_512);
        Audio_ClearFlag();
        audio_frame_count++;
        last_frame_peak_milli = ComputeFramePeakMilli(audio_512, AUDIO_FRAME_STEP);

        MFCC_Stream_PushSamples(audio_512);
        SetTestStage(TEST_STAGE_AUDIO_CAPTURE);

        if ((audio_frame_count % 16U) == 0U)
        {
          snprintf(msg,
                   sizeof(msg),
                   "AUDIO_FRAME,%lu,PEAK_MILLI=%lu\r\n",
                   (unsigned long)audio_frame_count,
                   (unsigned long)last_frame_peak_milli);
          Debug_Print(msg);
        }

        if (MFCC_Stream_Ready())
        {
          MFCC_Stream_Get(mfcc_32x13);
          mfcc_capture_count++;

          SetTestStage(TEST_STAGE_MFCC_READY);
          snprintf(msg,
                   sizeof(msg),
                   "MFCC READY,%lu\r\n",
                   (unsigned long)mfcc_capture_count);
          Debug_Print(msg);

          SetTestStage(TEST_STAGE_UART_TX);
          TransmitMfccSnapshot();
          SetTestStage(TEST_STAGE_AUDIO_CAPTURE);
        }
    }
    /* USER CODE END WHILE */
    /* USER CODE BEGIN 3 */
  }
  /* USER CODE END 3 */
}

/**
  * @brief System Clock Configuration
  * @retval None
  */
void SystemClock_Config(void)
{
  RCC_OscInitTypeDef RCC_OscInitStruct = {0};
  RCC_ClkInitTypeDef RCC_ClkInitStruct = {0};

  /** Configure the main internal regulator output voltage
  */
  if (HAL_PWREx_ControlVoltageScaling(PWR_REGULATOR_VOLTAGE_SCALE0) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the RCC Oscillators according to the specified parameters
  * in the RCC_OscInitTypeDef structure.
  */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_MSI;
  RCC_OscInitStruct.MSIState = RCC_MSI_ON;
  RCC_OscInitStruct.MSICalibrationValue = RCC_MSICALIBRATION_DEFAULT;
  RCC_OscInitStruct.MSIClockRange = RCC_MSIRANGE_6;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_MSI;
  RCC_OscInitStruct.PLL.PLLM = 1;
  RCC_OscInitStruct.PLL.PLLN = 55;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV7;
  RCC_OscInitStruct.PLL.PLLQ = RCC_PLLQ_DIV2;
  RCC_OscInitStruct.PLL.PLLR = RCC_PLLR_DIV2;
  if (HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    Error_Handler();
  }

  /** Initializes the CPU, AHB and APB buses clocks
  */
  RCC_ClkInitStruct.ClockType = RCC_CLOCKTYPE_HCLK|RCC_CLOCKTYPE_SYSCLK
                              |RCC_CLOCKTYPE_PCLK1|RCC_CLOCKTYPE_PCLK2;
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV1;
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV1;

  if (HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    Error_Handler();
  }
}

/**
  * @brief DFSDM1 Initialization Function
  * @param None
  * @retval None
  */
static void MX_DFSDM1_Init(void)
{

  /* USER CODE BEGIN DFSDM1_Init 0 */

  /* USER CODE END DFSDM1_Init 0 */

  /* USER CODE BEGIN DFSDM1_Init 1 */

  /* USER CODE END DFSDM1_Init 1 */

  hdfsdm1_filter0.Instance = DFSDM1_Filter0;
  hdfsdm1_filter0.Init.RegularParam.Trigger = DFSDM_FILTER_SW_TRIGGER;
  hdfsdm1_filter0.Init.RegularParam.FastMode = ENABLE;
  hdfsdm1_filter0.Init.RegularParam.DmaMode = ENABLE;
  hdfsdm1_filter0.Init.InjectedParam.Trigger = DFSDM_FILTER_SW_TRIGGER;
  hdfsdm1_filter0.Init.InjectedParam.ScanMode = DISABLE;
  hdfsdm1_filter0.Init.InjectedParam.DmaMode = DISABLE;
  hdfsdm1_filter0.Init.InjectedParam.ExtTrigger = DFSDM_FILTER_EXT_TRIG_TIM1_TRGO;
  hdfsdm1_filter0.Init.InjectedParam.ExtTriggerEdge = DFSDM_FILTER_EXT_TRIG_RISING_EDGE;
  hdfsdm1_filter0.Init.FilterParam.SincOrder = DFSDM_FILTER_SINC3_ORDER;
  hdfsdm1_filter0.Init.FilterParam.Oversampling = 125;
  hdfsdm1_filter0.Init.FilterParam.IntOversampling = 1;
  if (HAL_DFSDM_FilterInit(&hdfsdm1_filter0) != HAL_OK)
  {
    Error_Handler();
  }

  hdfsdm1_channel0.Instance = DFSDM1_Channel0;
  hdfsdm1_channel0.Init.OutputClock.Activation = ENABLE;
  hdfsdm1_channel0.Init.OutputClock.Selection = DFSDM_CHANNEL_OUTPUT_CLOCK_SYSTEM;
  hdfsdm1_channel0.Init.OutputClock.Divider = 55;
  hdfsdm1_channel0.Init.Input.Multiplexer = DFSDM_CHANNEL_EXTERNAL_INPUTS;
  hdfsdm1_channel0.Init.Input.DataPacking = DFSDM_CHANNEL_STANDARD_MODE;
  hdfsdm1_channel0.Init.Input.Pins = DFSDM_CHANNEL_SAME_CHANNEL_PINS;
  hdfsdm1_channel0.Init.SerialInterface.Type = DFSDM_CHANNEL_SPI_RISING;
  hdfsdm1_channel0.Init.SerialInterface.SpiClock = DFSDM_CHANNEL_SPI_CLOCK_INTERNAL;
  hdfsdm1_channel0.Init.Awd.FilterOrder = DFSDM_CHANNEL_FASTSINC_ORDER;
  hdfsdm1_channel0.Init.Awd.Oversampling = 1;
  hdfsdm1_channel0.Init.Offset = 0;
  hdfsdm1_channel0.Init.RightBitShift = 8;
  if (HAL_DFSDM_ChannelInit(&hdfsdm1_channel0) != HAL_OK)
  {
    Error_Handler();
  }

  if (HAL_DFSDM_FilterConfigRegChannel(&hdfsdm1_filter0,
                                       DFSDM_CHANNEL_0,
                                       DFSDM_CONTINUOUS_CONV_ON) != HAL_OK)
  {
    Error_Handler();
  }

  /* USER CODE BEGIN DFSDM1_Init 2 */

  /* USER CODE END DFSDM1_Init 2 */

}

/**
  * @brief ICACHE Initialization Function
  * @param None
  * @retval None
  */
static void MX_ICACHE_Init(void)
{

  /* USER CODE BEGIN ICACHE_Init 0 */

  /* USER CODE END ICACHE_Init 0 */

  /* USER CODE BEGIN ICACHE_Init 1 */

  /* USER CODE END ICACHE_Init 1 */

  /** Enable instruction cache in 1-way (direct mapped cache)
  */
  if (HAL_ICACHE_ConfigAssociativityMode(ICACHE_1WAY) != HAL_OK)
  {
    Error_Handler();
  }
  if (HAL_ICACHE_Enable() != HAL_OK)
  {
    Error_Handler();
  }
  /* USER CODE BEGIN ICACHE_Init 2 */

  /* USER CODE END ICACHE_Init 2 */

}

/**
  * Enable DMA controller clock
  * Configure DMA for memory to memory transfers
  *   hdma_dma_generator0
  */
static void MX_DMA_Init(void)
{

  /* DMA controller clock enable */
  __HAL_RCC_DMAMUX1_CLK_ENABLE();
  __HAL_RCC_DMA1_CLK_ENABLE();
  __HAL_RCC_DMA2_CLK_ENABLE();

  /* Configure DMA request hdma_dma_generator0 on DMA1_Channel2 */
  hdma_dma_generator0.Instance = DMA1_Channel2;
  hdma_dma_generator0.Init.Request = DMA_REQUEST_GENERATOR0;
  hdma_dma_generator0.Init.Direction = DMA_PERIPH_TO_MEMORY;
  hdma_dma_generator0.Init.PeriphInc = DMA_PINC_DISABLE;
  hdma_dma_generator0.Init.MemInc = DMA_MINC_ENABLE;
  hdma_dma_generator0.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
  hdma_dma_generator0.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
  hdma_dma_generator0.Init.Mode = DMA_CIRCULAR;
  hdma_dma_generator0.Init.Priority = DMA_PRIORITY_HIGH;
  if (HAL_DMA_Init(&hdma_dma_generator0) != HAL_OK)
  {
    Error_Handler( );
  }

  /*  */
  if (HAL_DMA_ConfigChannelAttributes(&hdma_dma_generator0, DMA_CHANNEL_NPRIV) != HAL_OK)
  {
    Error_Handler( );
  }

  /* DMA interrupt init */
  /* DMAMUX1_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMAMUX1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMAMUX1_IRQn);
  /* DMA1_Channel1_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Channel1_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel1_IRQn);
  /* DMA1_Channel2_IRQn interrupt configuration */
  HAL_NVIC_SetPriority(DMA1_Channel2_IRQn, 0, 0);
  HAL_NVIC_EnableIRQ(DMA1_Channel2_IRQn);

}

/**
  * @brief GPIO Initialization Function
  * @param None
  * @retval None
  */
static void MX_GPIO_Init(void)
{
  /* USER CODE BEGIN MX_GPIO_Init_1 */

  /* USER CODE END MX_GPIO_Init_1 */

  /* GPIO Ports Clock Enable */
  __HAL_RCC_GPIOC_CLK_ENABLE();
  __HAL_RCC_GPIOF_CLK_ENABLE();
  __HAL_RCC_GPIOH_CLK_ENABLE();
  __HAL_RCC_GPIOB_CLK_ENABLE();
  __HAL_RCC_GPIOA_CLK_ENABLE();

  /* USER CODE BEGIN MX_GPIO_Init_2 */

  /* USER CODE END MX_GPIO_Init_2 */
}

/* USER CODE BEGIN 4 */


/* USER CODE END 4 */

/**
  * @brief  This function is executed in case of error occurrence.
  * @retval None
  */
void Error_Handler(void)
{
  /* USER CODE BEGIN Error_Handler_Debug */
  /* User can add his own implementation to report the HAL error return state */
  __disable_irq();
  while (1)
  {
  }
  /* USER CODE END Error_Handler_Debug */
}
#ifdef USE_FULL_ASSERT
/**
  * @brief  Reports the name of the source file and the source line number
  *         where the assert_param error has occurred.
  * @param  file: pointer to the source file name
  * @param  line: assert_param error line source number
  * @retval None
  */
void assert_failed(uint8_t *file, uint32_t line)
{
  /* USER CODE BEGIN 6 */
  /* User can add his own implementation to report the file name and line number,
     ex: printf("Wrong parameters value: file %s on line %d\r\n", file, line) */
  /* USER CODE END 6 */
}
#endif /* USE_FULL_ASSERT */
