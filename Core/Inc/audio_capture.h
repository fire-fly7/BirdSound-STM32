#ifndef AUDIO_CAPTURE_H
#define AUDIO_CAPTURE_H

#include <stdint.h>
#include <stdbool.h>
#include <string.h>

#define AUDIO_SAMPLE_RATE     16000
#define AUDIO_DMA_SAMPLES     1024      // DMA 一次采集
#define AUDIO_FRAME_STEP      512       // 每次对外提供 512

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

/* ===== DFSDM DMA 回调（只能有一个定义） ===== */
void Audio_DFSDM_HalfCallback(void);
void Audio_DFSDM_FullCallback(void);

#ifdef __cplusplus
}


#endif

#endif // AUDIO_CAPTURE_H

