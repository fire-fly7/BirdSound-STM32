#include "audio_capture.h"
#include "stm32l5xx_hal.h"

extern DFSDM_Filter_HandleTypeDef hdfsdm1_filter0;

static int32_t dma_buffer[AUDIO_DMA_SAMPLES];

static float ring_buffer[AUDIO_SAMPLE_RATE];
static volatile uint32_t ring_index = 0;

static volatile bool half_ready = false;
static volatile bool full_ready = false;
static volatile bool frame_ready = false;

void Audio_Init(void) {
    memset(dma_buffer, 0, sizeof(dma_buffer));
    memset(ring_buffer, 0, sizeof(ring_buffer));

    ring_index = 0;
    half_ready = false;
    full_ready = false;
    frame_ready = false;
}

bool Audio_Start(void) {

    HAL_StatusTypeDef status =
        HAL_DFSDM_FilterRegularStart_DMA(&hdfsdm1_filter0,
                                          dma_buffer,
                                          AUDIO_DMA_SAMPLES);

    if (status != HAL_OK) {
        return false;
    }

    return true;
}

void Audio_DFSDM_HalfCallback(void)
{
    half_ready = true;
}

void Audio_DFSDM_FullCallback(void)
{
    full_ready = true;
}

static float convert_dfsdm_sample(int32_t raw_sample)
{
    return (float)raw_sample / 8388608.0f;
}

static void push_samples(const int32_t *src, uint32_t sample_count)
{
    for (uint32_t i = 0; i < sample_count; i++)
    {
        ring_buffer[ring_index++] = convert_dfsdm_sample(src[i]);

        if (ring_index >= AUDIO_SAMPLE_RATE)
            ring_index = 0;
    }
}

bool Audio_FrameReady(void)
{
    if (half_ready || full_ready)
    {
        frame_ready = true;
        return true;
    }
    return false;
}

void Audio_GetFrame(float *out_512)
{
    if (half_ready)
    {
        push_samples(&dma_buffer[0], AUDIO_FRAME_STEP);
        half_ready = false;
    }

    if (full_ready)
    {
        push_samples(&dma_buffer[AUDIO_FRAME_STEP], AUDIO_FRAME_STEP);
        full_ready = false;
    }

    /* 从 ring buffer 取最近 512 */
    uint32_t idx =
        (ring_index + AUDIO_SAMPLE_RATE - AUDIO_FRAME_STEP)
        % AUDIO_SAMPLE_RATE;

    for (uint32_t i = 0; i < AUDIO_FRAME_STEP; i++)
    {
        out_512[i] = ring_buffer[idx++];
        if (idx >= AUDIO_SAMPLE_RATE)
            idx = 0;
    }

    frame_ready = false;
}

void Audio_ClearFlag(void)
{
    frame_ready = false;
}
