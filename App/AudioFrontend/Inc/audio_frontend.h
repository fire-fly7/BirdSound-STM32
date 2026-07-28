#ifndef STM32_DEPLOY_AUDIO_FRONTEND_H
#define STM32_DEPLOY_AUDIO_FRONTEND_H

#include <stdint.h>

#define AUDIO_FRONTEND_SAMPLE_RATE       16000U
#define AUDIO_FRONTEND_WINDOW_SAMPLES    16000U
#define AUDIO_FRONTEND_FRAME_COUNT       32U
#define AUDIO_FRONTEND_MFCC_COEFFICIENTS 13U
#define AUDIO_FRONTEND_OUTPUT_ELEMENTS   \
  (AUDIO_FRONTEND_FRAME_COUNT * AUDIO_FRONTEND_MFCC_COEFFICIENTS)
#define AUDIO_FRONTEND_MAX_OUTPUT_ELEMENTS (AUDIO_FRONTEND_FRAME_COUNT * 40U)

typedef enum
{
  AUDIO_FRONTEND_STATUS_OK = 0,
  AUDIO_FRONTEND_STATUS_BAD_ARGUMENT = -200,
  AUDIO_FRONTEND_STATUS_UNSUPPORTED_MODEL = -201,
  AUDIO_FRONTEND_STATUS_NUMERIC_ERROR = -202
} audio_frontend_status_t;

audio_frontend_status_t AudioFrontend_ValidateModel(void);

audio_frontend_status_t AudioFrontend_Compute(
    const int16_t *pcm_samples,
    uint32_t sample_count,
    float *features,
    uint32_t feature_count);

#endif /* STM32_DEPLOY_AUDIO_FRONTEND_H */
