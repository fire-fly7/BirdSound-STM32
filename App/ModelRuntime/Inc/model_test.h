#ifndef MODEL_TEST_H
#define MODEL_TEST_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct
{
    float single_inference_ms;
    float average_inference_ms;
    uint32_t cycles_per_inference;
} model_perf_result_t;

/**
 * @brief Initialize DWT cycle counter
 */
void ModelTest_Init(void);

/**
 * @brief Measure single inference latency
 */
uint32_t ModelTest_RunSingle(const float *input);

/**
 * @brief Measure average inference latency
 */
model_perf_result_t ModelTest_RunAverage(const float *input,
                                         uint32_t rounds);

#ifdef __cplusplus
}
#endif

#endif
