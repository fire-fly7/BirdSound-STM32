extern "C" {
#include "model_inference.h"
#include "model_test.h"
}

#include "stm32l5xx_hal.h"
#include "core_cm33.h"

// ===== 可选：功耗测试 GPIO =====
#define PERF_GPIO_PORT GPIOA
#define PERF_GPIO_PIN  GPIO_PIN_5

// ===== DWT 初始化 =====
void ModelTest_Init(void)
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

// ===== 获取 CPU 频率 =====
static inline float get_cpu_freq(void)
{
    return (float)HAL_RCC_GetHCLKFreq();
}

// ===== 单次测试 =====
uint32_t ModelTest_RunSingle(const float *input)
{
    uint32_t start, end;

    start = DWT->CYCCNT;
    model_inference(input);
    end = DWT->CYCCNT;

    uint32_t cycles = end - start;
    
    return cycles;
}

// ===== 多次平均测试 =====
model_perf_result_t ModelTest_RunAverage(const float *input,
                                         uint32_t rounds)
{
    model_perf_result_t result;
    uint64_t total_cycles = 0;

    for (uint32_t i = 0; i < rounds; i++)
    {
        uint32_t start = DWT->CYCCNT;

        HAL_GPIO_WritePin(PERF_GPIO_PORT, PERF_GPIO_PIN, GPIO_PIN_SET);
        model_inference(input);
        HAL_GPIO_WritePin(PERF_GPIO_PORT, PERF_GPIO_PIN, GPIO_PIN_RESET);

        uint32_t end = DWT->CYCCNT;
        total_cycles += (end - start);
    }

    uint32_t avg_cycles = total_cycles / rounds;

    result.cycles_per_inference = avg_cycles;
    result.average_inference_ms =
        (float)avg_cycles / get_cpu_freq() * 1000.0f;

    result.single_inference_ms =
        result.average_inference_ms;

    return result;
}
