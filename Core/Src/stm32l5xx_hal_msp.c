/* USER CODE BEGIN Header */
/**
  ******************************************************************************
  * @file         stm32l5xx_hal_msp.c
  * @brief        This file provides code for the MSP Initialization
  *               and de-Initialization codes.
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
/* USER CODE BEGIN Includes */

/* USER CODE END Includes */
#if defined(STM32_DEPLOY_MICROPHONE_FRONTEND)
extern DMA_HandleTypeDef hdma_sai1_b;
#endif

/* Private typedef -----------------------------------------------------------*/
/* USER CODE BEGIN TD */

/* USER CODE END TD */

/* Private define ------------------------------------------------------------*/
/* USER CODE BEGIN Define */

/* USER CODE END Define */

/* Private macro -------------------------------------------------------------*/
/* USER CODE BEGIN Macro */

/* USER CODE END Macro */

/* Private variables ---------------------------------------------------------*/
/* USER CODE BEGIN PV */

/* USER CODE END PV */

/* Private function prototypes -----------------------------------------------*/
/* USER CODE BEGIN PFP */

/* USER CODE END PFP */

/* External functions --------------------------------------------------------*/
/* USER CODE BEGIN ExternalFunctions */

/* USER CODE END ExternalFunctions */

/* USER CODE BEGIN 0 */

/* USER CODE END 0 */
/**
  * Initializes the Global MSP.
  */
void HAL_MspInit(void)
{

  /* USER CODE BEGIN MspInit 0 */

  /* USER CODE END MspInit 0 */

  __HAL_RCC_SYSCFG_CLK_ENABLE();
  __HAL_RCC_PWR_CLK_ENABLE();

  /* System interrupt init*/

    /** Disable the internal Pull-Up in Dead Battery pins of UCPD peripheral
  */
  HAL_PWREx_DisableUCPDDeadBattery();

  /* USER CODE BEGIN MspInit 1 */

  /* USER CODE END MspInit 1 */
}

#if defined(STM32_DEPLOY_MICROPHONE_FRONTEND)
static uint32_t SAI1_client = 0U;

void HAL_SAI_MspInit(SAI_HandleTypeDef* hsai)
{
  GPIO_InitTypeDef GPIO_InitStruct = {0};
  RCC_PeriphCLKInitTypeDef PeriphClkInit = {0};

  if (hsai->Instance == SAI1_Block_B)
  {
    PeriphClkInit.PeriphClockSelection = RCC_PERIPHCLK_SAI1;
    PeriphClkInit.Sai1ClockSelection = RCC_SAI1CLKSOURCE_PLLSAI1;
    PeriphClkInit.PLLSAI1.PLLSAI1Source = RCC_PLLSOURCE_MSI;
    PeriphClkInit.PLLSAI1.PLLSAI1M = 1;
    PeriphClkInit.PLLSAI1.PLLSAI1N = 24;
    PeriphClkInit.PLLSAI1.PLLSAI1P = RCC_PLLP_DIV7;
    PeriphClkInit.PLLSAI1.PLLSAI1Q = RCC_PLLQ_DIV2;
    PeriphClkInit.PLLSAI1.PLLSAI1R = RCC_PLLR_DIV2;
    PeriphClkInit.PLLSAI1.PLLSAI1ClockOut = RCC_PLLSAI1_SAI1CLK;
    if (HAL_RCCEx_PeriphCLKConfig(&PeriphClkInit) != HAL_OK)
    {
      Error_Handler();
    }

    if (SAI1_client == 0U)
    {
      __HAL_RCC_SAI1_CLK_ENABLE();
    }
    SAI1_client++;

    MIC_SD_GPIO_CLK_ENABLE();
    MIC_SCK_GPIO_CLK_ENABLE();
    MIC_WS_GPIO_CLK_ENABLE();

    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = MIC_GPIO_AF;

    GPIO_InitStruct.Pin = MIC_SD_PIN;
    HAL_GPIO_Init(MIC_SD_GPIO_PORT, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = MIC_SCK_PIN;
    HAL_GPIO_Init(MIC_SCK_GPIO_PORT, &GPIO_InitStruct);

    GPIO_InitStruct.Pin = MIC_WS_PIN;
    HAL_GPIO_Init(MIC_WS_GPIO_PORT, &GPIO_InitStruct);

    hdma_sai1_b.Instance = DMA2_Channel1;
    hdma_sai1_b.Init.Request = DMA_REQUEST_SAI1_B;
    hdma_sai1_b.Init.Direction = DMA_PERIPH_TO_MEMORY;
    hdma_sai1_b.Init.PeriphInc = DMA_PINC_DISABLE;
    hdma_sai1_b.Init.MemInc = DMA_MINC_ENABLE;
    hdma_sai1_b.Init.PeriphDataAlignment = DMA_PDATAALIGN_WORD;
    hdma_sai1_b.Init.MemDataAlignment = DMA_MDATAALIGN_WORD;
    hdma_sai1_b.Init.Mode = DMA_CIRCULAR;
    hdma_sai1_b.Init.Priority = DMA_PRIORITY_HIGH;
    if (HAL_DMA_Init(&hdma_sai1_b) != HAL_OK)
    {
      Error_Handler();
    }

    if (HAL_DMA_ConfigChannelAttributes(&hdma_sai1_b, DMA_CHANNEL_NPRIV) != HAL_OK)
    {
      Error_Handler();
    }

    __HAL_LINKDMA(hsai, hdmarx, hdma_sai1_b);
  }
}

void HAL_SAI_MspDeInit(SAI_HandleTypeDef* hsai)
{
  if (hsai->Instance == SAI1_Block_B)
  {
    if (SAI1_client > 0U)
    {
      SAI1_client--;
    }

    if (SAI1_client == 0U)
    {
      __HAL_RCC_SAI1_CLK_DISABLE();
    }

    HAL_GPIO_DeInit(MIC_SD_GPIO_PORT, MIC_SD_PIN);
    HAL_GPIO_DeInit(MIC_SCK_GPIO_PORT, MIC_SCK_PIN);
    HAL_GPIO_DeInit(MIC_WS_GPIO_PORT, MIC_WS_PIN);
    HAL_DMA_DeInit(hsai->hdmarx);
  }
}
#endif
