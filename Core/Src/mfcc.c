#include "mfcc.h"
#include "arm_math.h"
#include "arm_const_structs.h"
#include <math.h>
#include <string.h>

static float audio_ring[MFCC_FRAME_LEN];
static uint32_t ring_index = 0;

static float frame[MFCC_FRAME_LEN];
static float window[MFCC_FRAME_LEN];

static float fft_in[MFCC_FRAME_LEN];
static float fft_out[MFCC_FRAME_LEN];

static float mel_energies[MFCC_NUM_MEL];
static float mfcc_buffer[MFCC_NUM_FRAMES][MFCC_NUM_COEFF];

static uint32_t mfcc_index = 0;
static bool mfcc_ready = false;

static arm_rfft_fast_instance_f32 fft;

static void pre_emphasis(const float *in, float *out)
{
    const float alpha = 0.97f;
    out[0] = in[0];
    for (int i = 1; i < MFCC_FRAME_LEN; i++)
        out[i] = in[i] - alpha * in[i - 1];
}
static void apply_window(float *buf)
{
    for (int i = 0; i < MFCC_FRAME_LEN; i++)
        buf[i] *= window[i];
}
static float hz_to_mel(float hz)
{
    return 2595.0f * log10f(1.0f + hz / 700.0f);
}

static float mel_to_hz(float mel)
{
    return 700.0f * (powf(10.0f, mel / 2595.0f) - 1.0f);
}

static void apply_mel_filterbank(const float *power_spectrum,
                           float *mel_out)
{
    float mel_low = hz_to_mel(0);
    float mel_high = hz_to_mel(MFCC_SAMPLE_RATE / 2);

    float mel_step = (mel_high - mel_low) / (MFCC_NUM_MEL + 1);

    for (int m = 0; m < MFCC_NUM_MEL; m++)
    {
        float mel_center = mel_low + (m + 1) * mel_step;
        float f_center = mel_to_hz(mel_center);
        int bin = (int)(f_center * MFCC_FRAME_LEN / MFCC_SAMPLE_RATE);

        mel_out[m] = power_spectrum[bin] + 1e-6f;
    }
}
static void dct(const float *in, float *out)
{
    for (int k = 0; k < MFCC_NUM_COEFF; k++)
    {
        float sum = 0.0f;
        for (int n = 0; n < MFCC_NUM_MEL; n++)
        {
            sum += in[n] *
                   cosf(M_PI * k * (n + 0.5f) / MFCC_NUM_MEL);
        }
        out[k] = sum;
    }
}
static void compute_mfcc_frame(const float *audio, float *out_mfcc)
{
    pre_emphasis(audio, frame);
    apply_window(frame);

    memcpy(fft_in, frame, sizeof(frame));
    arm_rfft_fast_f32(&fft, fft_in, fft_out, 0);

    /* 功率谱 */
    for (int i = 0; i < MFCC_FRAME_LEN / 2; i++)
    {
        float re = fft_out[2 * i];
        float im = fft_out[2 * i + 1];
        fft_in[i] = re * re + im * im;
    }

    apply_mel_filterbank(fft_in, mel_energies);

    for (int i = 0; i < MFCC_NUM_MEL; i++)
        mel_energies[i] = logf(mel_energies[i]);

    dct(mel_energies, out_mfcc);
}
void MFCC_Init(void)
{
    arm_rfft_fast_init_f32(&fft, MFCC_FRAME_LEN);

    for (int i = 0; i < MFCC_FRAME_LEN; i++)
        window[i] = 0.54f - 0.46f *
                    cosf(2 * M_PI * i / (MFCC_FRAME_LEN - 1));

    MFCC_Reset();
}

void MFCC_Reset(void)
{
    memset(audio_ring, 0, sizeof(audio_ring));
    mfcc_index = 0;
    ring_index = 0;
    mfcc_ready = false;
}
void MFCC_Stream_PushSamples(const float *samples_512)
{
    /* 移动旧数据 */
    memmove(audio_ring,
            &audio_ring[MFCC_FRAME_STEP],
            sizeof(float) * MFCC_FRAME_STEP);

    /* 拷贝新数据 */
    memcpy(&audio_ring[MFCC_FRAME_STEP],
           samples_512,
           sizeof(float) * MFCC_FRAME_STEP);

    /* 计算 MFCC */
    compute_mfcc_frame(audio_ring,
                       mfcc_buffer[mfcc_index]);

    mfcc_index++;

    if (mfcc_index >= MFCC_NUM_FRAMES)
    {
        mfcc_ready = true;
        mfcc_index = 0;
    }
}
bool MFCC_Stream_Ready(void)
{
    return mfcc_ready;
}

void MFCC_Stream_Get(float *out_32x13)
{
    memcpy(out_32x13,
           mfcc_buffer,
           sizeof(mfcc_buffer));

    mfcc_ready = false;
}
