#ifndef MODEL_INFERENCE_H
#define MODEL_INFERENCE_H

#include <stdbool.h>
#include <stdint.h>

#include "model_config.h"

#ifdef __cplusplus
extern "C" {
#endif

typedef enum
{
    MODEL_STATUS_OK = 0,
    MODEL_STATUS_NOT_INITIALIZED = -1,
    MODEL_STATUS_SCHEMA_MISMATCH = -2,
    MODEL_STATUS_OP_REGISTRATION = -3,
    MODEL_STATUS_ARENA_ALLOCATION = -4,
    MODEL_STATUS_SHAPE_MISMATCH = -5,
    MODEL_STATUS_UNSUPPORTED_TYPE = -6,
    MODEL_STATUS_BAD_INPUT = -7,
    MODEL_STATUS_INVOKE_FAILED = -8,
    MODEL_STATUS_METADATA_MISMATCH = -9
} model_status_t;

model_status_t model_init(void);
model_status_t model_inference(const float *input_data,
                               uint32_t element_count,
                               int32_t *predicted_index);
model_status_t model_inference_native(const void *input_data,
                                      uint32_t byte_count,
                                      int32_t *predicted_index);
const float* model_get_output(void);
const void* model_get_output_raw(void);
uint32_t model_get_output_raw_size(void);
uint32_t model_get_input_size(void);
uint32_t model_get_output_count(void);
uint32_t model_get_arena_used(void);
uint32_t model_get_input_byte_count(void);
uint8_t model_get_input_type(void);
uint8_t model_get_output_type(void);
float model_get_input_scale(void);
int32_t model_get_input_zero_point(void);
float model_get_output_scale(void);
int32_t model_get_output_zero_point(void);
bool model_is_compatible(void);
const char* model_get_label(uint32_t index);

#ifdef __cplusplus
}
#endif

#endif
