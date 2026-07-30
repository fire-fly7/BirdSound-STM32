#include "stm32_deploy_app.h"

#include "serial_model_app.h"
#include "stm32l5xx_nucleo.h"

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

  if (BSP_COM_Init(COM1, &config) != BSP_ERROR_NONE)
  {
    BSP_LED_On(LED_RED);
    return -1;
  }
  return 0;
}

int STM32DeployApp_Run(void)
{
  if (InitializeStatusLeds() != 0 || InitializeSerialPort() != 0)
  {
    return -1;
  }

  SerialModelApp_Run(&hcom_uart[COM1]);
  return 0;
}
