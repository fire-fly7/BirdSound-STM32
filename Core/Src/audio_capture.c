#include "audio_capture.h"
#include "stm32l5xx_hal.h"

extern SAI_HandleTypeDef hsai_BlockB1;

static uint32_t dma_buffer[AUDIO_DMA_SAMPLES];

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

void Audio_Start(void) {

    HAL_StatusTypeDef status = HAL_SAI_Receive_DMA(
        &hsai_BlockB1,
        (uint8_t*)dma_buffer,
        AUDIO_DMA_SAMPLES
    );

    if (status != HAL_OK) {
        //加个红灯
        while (1);
    }
}

void Audio_SAI_HalfCallback(void)
{
    half_ready = true;
}

void Audio_SAI_FullCallback(void)
{
    full_ready = true;
}

static float convert_i2s_sample(uint32_t raw_sample)
{
    int32_t sample_24;

    if ((raw_sample & 0xFFU) == 0U)
    {
        sample_24 = ((int32_t)raw_sample) >> 8;
    }
    else
    {
        sample_24 = ((int32_t)(raw_sample << 8)) >> 8;
    }

    return (float)sample_24 / 8388608.0f;
}

static uint32_t detect_active_slot(const uint32_t *src, uint32_t frame_count)
{
    float left_energy = 0.0f;
    float right_energy = 0.0f;

    for (uint32_t i = 0; i < frame_count; i++)
    {
        float left = convert_i2s_sample(
            src[(i * AUDIO_I2S_SLOTS_PER_FRAME) + AUDIO_I2S_LEFT_SLOT]);
        float right = convert_i2s_sample(
            src[(i * AUDIO_I2S_SLOTS_PER_FRAME) + AUDIO_I2S_RIGHT_SLOT]);

        left_energy += (left >= 0.0f) ? left : -left;
        right_energy += (right >= 0.0f) ? right : -right;
    }

    if (right_energy > left_energy)
    {
        return AUDIO_I2S_RIGHT_SLOT;
    }

    return AUDIO_I2S_LEFT_SLOT;
}

static void push_samples(const uint32_t *src, uint32_t frame_count)
{
    uint32_t active_slot = detect_active_slot(src, frame_count);

    for (uint32_t i = 0; i < frame_count; i++)
    {
        uint32_t raw_sample =
            src[(i * AUDIO_I2S_SLOTS_PER_FRAME) + active_slot];

        ring_buffer[ring_index++] = convert_i2s_sample(raw_sample);

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
        push_samples(&dma_buffer[AUDIO_FRAME_STEP * AUDIO_I2S_SLOTS_PER_FRAME],
                     AUDIO_FRAME_STEP);
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
