#include "audio_frontend.h"

#include "arm_math.h"
#include "mfcc_frontend_tables.h"
#include "model_config.h"
#include "model_manifest.h"

#include <math.h>
#include <stdbool.h>
#include <stddef.h>

#define AUDIO_FRONTEND_FFT_SIZE       2048U
#define AUDIO_FRONTEND_HOP_LENGTH     512U
#define AUDIO_FRONTEND_CENTER_PADDING (AUDIO_FRONTEND_FFT_SIZE / 2U)
#define AUDIO_FRONTEND_SPECTRUM_BINS  (AUDIO_FRONTEND_FFT_SIZE / 2U + 1U)
#define AUDIO_FRONTEND_MEL_BANDS      128U
#define AUDIO_FRONTEND_POWER_FLOOR    1.0e-10f
#define AUDIO_FRONTEND_TOP_DB         80.0f
#define AUDIO_FRONTEND_SPECTRAL_BANDS 40U

/*
 * Workspaces are static so the frontend never consumes the application stack.
 * fft_output is converted in place from CMSIS' packed complex spectrum to
 * power/magnitude bins. spectral_frames holds Mel energies and is reused by
 * the selected MFCC, LogMel, or PCEN post-transform.
 */
static float fft_input[AUDIO_FRONTEND_FFT_SIZE];
static float fft_output[AUDIO_FRONTEND_FFT_SIZE];
static float
    spectral_frames[AUDIO_FRONTEND_FRAME_COUNT][AUDIO_FRONTEND_MEL_BANDS];
static arm_rfft_fast_instance_f32 rfft_instance;
static bool rfft_ready;

_Static_assert(MFCC_TABLE_FFT_SIZE == AUDIO_FRONTEND_FFT_SIZE,
               "Generated Hann table does not match the frontend FFT");
_Static_assert(MFCC_TABLE_MEL_BANDS == AUDIO_FRONTEND_MEL_BANDS,
               "Generated Mel table does not match the frontend");
_Static_assert(MFCC_TABLE_COEFFICIENTS ==
                   AUDIO_FRONTEND_MFCC_COEFFICIENTS,
               "Generated DCT table does not match the frontend");
_Static_assert(SPECTRAL_TABLE_MEL_BANDS == AUDIO_FRONTEND_SPECTRAL_BANDS,
               "Generated 40-band Mel table does not match the frontend");

static audio_frontend_status_t EnsureRfftReady(void)
{
  if (!rfft_ready)
  {
    if (arm_rfft_2048_fast_init_f32(&rfft_instance) != ARM_MATH_SUCCESS)
    {
      return AUDIO_FRONTEND_STATUS_NUMERIC_ERROR;
    }
    rfft_ready = true;
  }
  return AUDIO_FRONTEND_STATUS_OK;
}

audio_frontend_status_t AudioFrontend_ValidateModel(void)
{
  if (MODEL_FEATURE_FRAMES != AUDIO_FRONTEND_FRAME_COUNT ||
      MODEL_FEATURE_CHANNELS != 1U)
  {
    return AUDIO_FRONTEND_STATUS_UNSUPPORTED_MODEL;
  }
  if (MODEL_FEATURE_ID == MODEL_FEATURE_MFCC)
  {
    if (MODEL_FEATURE_BINS != AUDIO_FRONTEND_MFCC_COEFFICIENTS ||
        MODEL_INPUT_SIZE != AUDIO_FRONTEND_OUTPUT_ELEMENTS)
    {
      return AUDIO_FRONTEND_STATUS_UNSUPPORTED_MODEL;
    }
  }
  else if (MODEL_FEATURE_ID == MODEL_FEATURE_LOGMEL ||
           MODEL_FEATURE_ID == MODEL_FEATURE_PCEN)
  {
    if (MODEL_FEATURE_BINS != AUDIO_FRONTEND_SPECTRAL_BANDS ||
        MODEL_INPUT_SIZE != AUDIO_FRONTEND_MAX_OUTPUT_ELEMENTS)
    {
      return AUDIO_FRONTEND_STATUS_UNSUPPORTED_MODEL;
    }
  }
  else
  {
    return AUDIO_FRONTEND_STATUS_UNSUPPORTED_MODEL;
  }
  return AUDIO_FRONTEND_STATUS_OK;
}

audio_frontend_status_t AudioFrontend_Compute(
    const int16_t *pcm_samples,
    uint32_t sample_count,
    float *features,
    uint32_t feature_count)
{
  if (pcm_samples == NULL || features == NULL ||
      sample_count != AUDIO_FRONTEND_WINDOW_SAMPLES ||
      feature_count != MODEL_INPUT_SIZE)
  {
    return AUDIO_FRONTEND_STATUS_BAD_ARGUMENT;
  }
  audio_frontend_status_t validation = AudioFrontend_ValidateModel();
  if (validation != AUDIO_FRONTEND_STATUS_OK)
  {
    return validation;
  }

  if (EnsureRfftReady() != AUDIO_FRONTEND_STATUS_OK)
  {
    return AUDIO_FRONTEND_STATUS_NUMERIC_ERROR;
  }
  uint32_t mel_bands = MODEL_FEATURE_ID == MODEL_FEATURE_MFCC
                           ? AUDIO_FRONTEND_MEL_BANDS
                           : AUDIO_FRONTEND_SPECTRAL_BANDS;
  const uint16_t *mel_starts = MODEL_FEATURE_ID == MODEL_FEATURE_MFCC
                                   ? mfcc_mel_starts
                                   : spectral_mel_starts;
  const uint16_t *mel_offsets = MODEL_FEATURE_ID == MODEL_FEATURE_MFCC
                                    ? mfcc_mel_offsets
                                    : spectral_mel_offsets;
  const float *mel_weights = MODEL_FEATURE_ID == MODEL_FEATURE_MFCC
                                 ? mfcc_mel_weights
                                 : spectral_mel_weights;
  bool use_magnitude = MODEL_FEATURE_ID == MODEL_FEATURE_PCEN;

  for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
  {
    int32_t first_sample =
        (int32_t)(frame * AUDIO_FRONTEND_HOP_LENGTH) -
        (int32_t)AUDIO_FRONTEND_CENTER_PADDING;
    for (uint32_t index = 0U; index < AUDIO_FRONTEND_FFT_SIZE; ++index)
    {
      int32_t audio_index = first_sample + (int32_t)index;
      float sample = 0.0f;
      if (audio_index >= 0 &&
          audio_index < (int32_t)AUDIO_FRONTEND_WINDOW_SAMPLES)
      {
        sample = (float)pcm_samples[audio_index] / 32768.0f;
      }
      fft_input[index] = sample * mfcc_hann_window[index];
    }

    arm_rfft_fast_f32(&rfft_instance, fft_input, fft_output, 0U);

    float nyquist = fft_output[1];
    fft_output[0] *= fft_output[0];
    for (uint32_t bin = 1U;
         bin < AUDIO_FRONTEND_SPECTRUM_BINS - 1U;
         ++bin)
    {
      float real = fft_output[2U * bin];
      float imaginary = fft_output[2U * bin + 1U];
      fft_output[bin] = real * real + imaginary * imaginary;
    }
    fft_output[AUDIO_FRONTEND_SPECTRUM_BINS - 1U] =
        nyquist * nyquist;
    if (use_magnitude)
    {
      for (uint32_t bin = 0U;
           bin < AUDIO_FRONTEND_SPECTRUM_BINS;
           ++bin)
      {
        fft_output[bin] = sqrtf(fft_output[bin]);
      }
    }

    for (uint32_t band = 0U; band < mel_bands; ++band)
    {
      uint32_t weight_begin = mel_offsets[band];
      uint32_t weight_end = mel_offsets[band + 1U];
      uint32_t spectrum_bin = mel_starts[band];
      float mel_power = 0.0f;
      for (uint32_t weight = weight_begin;
           weight < weight_end;
           ++weight, ++spectrum_bin)
      {
        mel_power +=
            fft_output[spectrum_bin] * mel_weights[weight];
      }
      spectral_frames[frame][band] = mel_power;
    }
  }

  if (MODEL_FEATURE_ID == MODEL_FEATURE_MFCC)
  {
    float maximum_db = -INFINITY;
    for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
    {
      for (uint32_t band = 0U; band < AUDIO_FRONTEND_MEL_BANDS; ++band)
      {
        float power = spectral_frames[frame][band];
        if (power < AUDIO_FRONTEND_POWER_FLOOR)
        {
          power = AUDIO_FRONTEND_POWER_FLOOR;
        }
        float decibels = 10.0f * log10f(power);
        spectral_frames[frame][band] = decibels;
        if (decibels > maximum_db)
        {
          maximum_db = decibels;
        }
      }
    }

    float minimum_db = maximum_db - AUDIO_FRONTEND_TOP_DB;
    for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
    {
      for (uint32_t coefficient = 0U;
           coefficient < AUDIO_FRONTEND_MFCC_COEFFICIENTS;
           ++coefficient)
      {
        float value = 0.0f;
        const float *dct_row =
            &mfcc_dct_matrix[coefficient * AUDIO_FRONTEND_MEL_BANDS];
        for (uint32_t band = 0U; band < AUDIO_FRONTEND_MEL_BANDS; ++band)
        {
          float decibels = spectral_frames[frame][band];
          if (decibels < minimum_db)
          {
            decibels = minimum_db;
          }
          value += dct_row[band] * decibels;
        }
        if (!isfinite(value))
        {
          return AUDIO_FRONTEND_STATUS_NUMERIC_ERROR;
        }
        features[frame * AUDIO_FRONTEND_MFCC_COEFFICIENTS + coefficient] =
            value;
      }
    }
  }
  else if (MODEL_FEATURE_ID == MODEL_FEATURE_LOGMEL)
  {
    float reference_db = -INFINITY;
    for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
    {
      for (uint32_t band = 0U; band < AUDIO_FRONTEND_SPECTRAL_BANDS; ++band)
      {
        float power = spectral_frames[frame][band];
        if (power < AUDIO_FRONTEND_POWER_FLOOR)
        {
          power = AUDIO_FRONTEND_POWER_FLOOR;
        }
        float decibels = 10.0f * log10f(power);
        spectral_frames[frame][band] = decibels;
        if (decibels > reference_db)
        {
          reference_db = decibels;
        }
      }
    }
    for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
    {
      for (uint32_t band = 0U; band < AUDIO_FRONTEND_SPECTRAL_BANDS; ++band)
      {
        float value = spectral_frames[frame][band] - reference_db;
        if (value < -AUDIO_FRONTEND_TOP_DB)
        {
          value = -AUDIO_FRONTEND_TOP_DB;
        }
        features[frame * AUDIO_FRONTEND_SPECTRAL_BANDS + band] = value;
      }
    }
  }
  else
  {
    const double scale = 2147483648.0;
    const double gain = 0.98;
    const double bias = 2.0;
    const double power = 0.5;
    const double epsilon = 1.0e-6;
    const double time_frames =
        0.4 * (double)AUDIO_FRONTEND_SAMPLE_RATE /
        (double)AUDIO_FRONTEND_HOP_LENGTH;
    const double smoothing =
        (sqrt(1.0 + 4.0 * time_frames * time_frames) - 1.0) /
        (2.0 * time_frames * time_frames);
    const double compressed_bias = sqrt(bias);

    for (uint32_t band = 0U; band < AUDIO_FRONTEND_SPECTRAL_BANDS; ++band)
    {
      /*
       * scipy.signal.lfilter_zi([b], [1, b - 1]) is 1-b, which
       * corresponds to a previous smoothed output of 1 for this recurrence.
       */
      double smoothed = 1.0;
      for (uint32_t frame = 0U; frame < AUDIO_FRONTEND_FRAME_COUNT; ++frame)
      {
        double energy = (double)spectral_frames[frame][band] * scale;
        smoothed =
            smoothing * energy + (1.0 - smoothing) * smoothed;
        double automatic_gain =
            exp(-gain * (log(epsilon) + log1p(smoothed / epsilon)));
        double value =
            compressed_bias *
            expm1(power * log1p(energy * automatic_gain / bias));
        if (!isfinite(value))
        {
          return AUDIO_FRONTEND_STATUS_NUMERIC_ERROR;
        }
        features[frame * AUDIO_FRONTEND_SPECTRAL_BANDS + band] =
            (float)value;
      }
    }
  }

  return AUDIO_FRONTEND_STATUS_OK;
}
