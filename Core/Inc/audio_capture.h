#ifndef AUDIO_CAPTURE_H
#define AUDIO_CAPTURE_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#define AUDIO_SAMPLE_RATE         16000U
#define AUDIO_FRAME_STEP          512U
#define AUDIO_I2S_SLOTS_PER_FRAME 2U
#define AUDIO_DMA_FRAMES          (AUDIO_FRAME_STEP * 2U)
#define AUDIO_DMA_SAMPLES         (AUDIO_DMA_FRAMES * AUDIO_I2S_SLOTS_PER_FRAME)

#define AUDIO_I2S_LEFT_SLOT       0U
#define AUDIO_I2S_RIGHT_SLOT      1U

#ifdef __cplusplus
extern "C" {
#endif

void Audio_Init(void);
void Audio_Start(void);

/* 是否有新的 512 点音频 */
bool Audio_FrameReady(void);

/* 拷贝最新的 512 点 float 音频 */
void Audio_GetFrame(float *out_512);

/* 清除标志 */
void Audio_ClearFlag(void);

/* ===== SAI DMA 回调 ===== */
void Audio_SAI_HalfCallback(void);
void Audio_SAI_FullCallback(void);

#ifdef __cplusplus
}


#endif

#endif // AUDIO_CAPTURE_H
