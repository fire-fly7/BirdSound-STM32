#ifndef MODEL_CONFIG_H
#define MODEL_CONFIG_H

#include <model_manifest.h>

#define MODEL_SAMPLE_RATE_HZ          16000U
#define MODEL_MAX_INPUT_ELEMENTS      (32U * 40U)
#define MODEL_MAX_OUTPUT_ELEMENTS     8U

#define MODEL_ACTIVATION_SOFTMAX      1U
#define MODEL_ACTIVATION_SIGMOID      2U

#define MODEL_FEATURE_MFCC            1U
#define MODEL_FEATURE_LOGMEL          2U
#define MODEL_FEATURE_PCEN            3U

#if MODEL_INPUT_SIZE > MODEL_MAX_INPUT_ELEMENTS
#error "MODEL_INPUT_SIZE exceeds the serial/test input capacity"
#endif

#if MODEL_OUTPUT_SIZE > MODEL_MAX_OUTPUT_ELEMENTS
#error "MODEL_OUTPUT_SIZE exceeds the output buffer capacity"
#endif

#endif /* MODEL_CONFIG_H */
