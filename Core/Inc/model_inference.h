#ifndef MODEL_INFERENCE_H
#define MODEL_INFERENCE_H

#include <stdint.h>

#define MODEL_INPUT_SIZE  (32 * 13)
#define MODEL_OUTPUT_SIZE 3  //分类数

#ifdef __cplusplus
extern "C" {
#endif

void model_init(void);
int model_predict(const float *input_data);
const float* model_get_output(void);

#ifdef __cplusplus
}
#endif

#endif