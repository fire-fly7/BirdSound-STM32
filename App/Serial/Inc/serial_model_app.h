#ifndef SERIAL_MODEL_APP_H
#define SERIAL_MODEL_APP_H

#include "stm32l5xx_hal.h"

#ifdef __cplusplus
extern "C" {
#endif

void SerialModelApp_Run(UART_HandleTypeDef *uart);

#ifdef __cplusplus
}
#endif

#endif /* SERIAL_MODEL_APP_H */
