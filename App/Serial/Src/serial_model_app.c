#include "serial_model_app.h"

#include "audio_frontend.h"
#include "model_data.h"
#include "model_inference.h"
#include "model_test.h"
#include "serial_model_protocol.h"
#include "stm32l5xx_nucleo.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

#define SERIAL_HEADER_TIMEOUT_MS  2000U
#define SERIAL_PAYLOAD_TIMEOUT_MS 5000U
#define SERIAL_AUDIO_MAX_WINDOWS  120U

typedef union
{
  uint32_t alignment;
  uint8_t bytes[SERIAL_MODEL_MAX_PAYLOAD];
} serial_payload_buffer_t;

static serial_payload_buffer_t rx_payload;

typedef struct
{
  bool active;
  bool feature_valid;
  uint32_t expected_samples;
  uint32_t expected_crc32;
  uint32_t rolling_crc32;
  uint32_t received_samples;
  uint32_t window_fill;
  uint32_t completed_windows;
  uint64_t frontend_cycles;
  uint64_t inference_cycles;
  int32_t frontend_status;
  model_status_t model_status;
  int16_t window[AUDIO_FRONTEND_WINDOW_SAMPLES];
  float score_sums[MODEL_MAX_OUTPUT_ELEMENTS];
} serial_audio_state_t;

static serial_audio_state_t audio_state;
static float last_audio_features[AUDIO_FRONTEND_MAX_OUTPUT_ELEMENTS];

_Static_assert(sizeof(serial_model_header_t) == 20U,
               "Unexpected serial protocol header size");
_Static_assert(sizeof(serial_audio_begin_t) == 16U,
               "Unexpected AUDIO_BEGIN payload size");
_Static_assert(MODEL_INPUT_SIZE <= MODEL_MAX_INPUT_ELEMENTS,
               "Serial receive buffer is smaller than the model input");
_Static_assert(MODEL_OUTPUT_SIZE <= 32U,
               "Class mask supports at most 32 outputs");
_Static_assert(sizeof(MODEL_NAME) <= SERIAL_MODEL_NAME_BYTES,
               "Model name does not fit the info response");
_Static_assert(sizeof(MODEL_SHA256) == SERIAL_MODEL_SHA256_BYTES,
               "SHA-256 text field must contain 64 hex digits and a terminator");

static uint32_t Crc32Update(uint32_t crc,
                            const uint8_t *data,
                            uint32_t length)
{
  for (uint32_t i = 0; i < length; ++i)
  {
    crc ^= data[i];
    for (uint32_t bit = 0; bit < 8U; ++bit)
    {
      uint32_t mask = 0U - (crc & 1U);
      crc = (crc >> 1U) ^ (0xEDB88320UL & mask);
    }
  }

  return crc;
}

static uint32_t Crc32(const uint8_t *data, uint32_t length)
{
  return Crc32Update(0xFFFFFFFFUL, data, length) ^ 0xFFFFFFFFUL;
}

static uint32_t SaturateUint64(uint64_t value)
{
  return value > UINT32_MAX ? UINT32_MAX : (uint32_t)value;
}

static HAL_StatusTypeDef SendPacket(UART_HandleTypeDef *uart,
                                    uint8_t command,
                                    uint32_t sequence,
                                    const void *payload,
                                    uint32_t payload_length)
{
  serial_model_header_t header;

  header.magic = SERIAL_MODEL_MAGIC;
  header.version = SERIAL_MODEL_PROTOCOL_VERSION;
  header.command = command;
  header.flags = 0U;
  header.sequence = sequence;
  header.payload_length = payload_length;
  header.payload_crc32 =
      Crc32((const uint8_t *)payload, payload_length);

  HAL_StatusTypeDef status =
      HAL_UART_Transmit(uart,
                        (uint8_t *)&header,
                        (uint16_t)sizeof(header),
                        SERIAL_HEADER_TIMEOUT_MS);
  if (status != HAL_OK || payload_length == 0U)
  {
    return status;
  }

  return HAL_UART_Transmit(uart,
                           (uint8_t *)payload,
                           (uint16_t)payload_length,
                           SERIAL_PAYLOAD_TIMEOUT_MS);
}

static HAL_StatusTypeDef ReceiveHeader(UART_HandleTypeDef *uart,
                                       serial_model_header_t *header)
{
  const uint8_t magic[4] = {
      (uint8_t)(SERIAL_MODEL_MAGIC & 0xFFU),
      (uint8_t)((SERIAL_MODEL_MAGIC >> 8U) & 0xFFU),
      (uint8_t)((SERIAL_MODEL_MAGIC >> 16U) & 0xFFU),
      (uint8_t)((SERIAL_MODEL_MAGIC >> 24U) & 0xFFU),
  };
  uint32_t matched = 0U;

  while (matched < sizeof(magic))
  {
    uint8_t byte = 0U;
    HAL_StatusTypeDef status =
        HAL_UART_Receive(uart, &byte, 1U, HAL_MAX_DELAY);
    if (status != HAL_OK)
    {
      return status;
    }

    if (byte == magic[matched])
    {
      ((uint8_t *)header)[matched++] = byte;
    }
    else
    {
      matched = byte == magic[0] ? 1U : 0U;
      if (matched == 1U)
      {
        ((uint8_t *)header)[0] = byte;
      }
    }
  }

  return HAL_UART_Receive(uart,
                          ((uint8_t *)header) + sizeof(magic),
                          (uint16_t)(sizeof(*header) - sizeof(magic)),
                          SERIAL_HEADER_TIMEOUT_MS);
}

static void SendError(UART_HandleTypeDef *uart,
                      uint32_t sequence,
                      int32_t error_code,
                      const char *message)
{
  serial_model_error_payload_t payload;

  memset(&payload, 0, sizeof(payload));
  payload.error_code = error_code;
  if (message != NULL)
  {
    strncpy(payload.message, message, sizeof(payload.message) - 1U);
  }
  (void)SendPacket(uart,
                   SERIAL_RSP_ERROR,
                   sequence,
                   &payload,
                   sizeof(payload));
}

static void SendInfo(UART_HandleTypeDef *uart,
                     uint32_t sequence,
                     model_status_t model_status)
{
  serial_model_info_t info;

  memset(&info, 0, sizeof(info));
  info.model_status = model_status;
  info.feature_id = MODEL_FEATURE_ID;
  info.output_activation_id = MODEL_OUTPUT_ACTIVATION_ID;
  info.input_type = model_get_input_type();
  info.output_type = model_get_output_type();
  info.input_dims[0] = 1U;
  info.input_dims[1] = MODEL_FEATURE_FRAMES;
  info.input_dims[2] = MODEL_FEATURE_BINS;
  info.input_dims[3] = MODEL_FEATURE_CHANNELS;
  info.output_count = MODEL_OUTPUT_SIZE;
  info.label_count = MODEL_OUTPUT_SIZE;
  info.input_elements =
      model_get_input_size() == 0U ? MODEL_INPUT_SIZE : model_get_input_size();
  info.model_bytes = model_data_len;
  info.arena_bytes = MODEL_TENSOR_ARENA_BYTES;
  info.arena_used = model_get_arena_used();
  info.input_scale = model_get_input_scale();
  info.input_zero_point = model_get_input_zero_point();
  info.output_scale = model_get_output_scale();
  info.output_zero_point = model_get_output_zero_point();
  strncpy(info.model_name, MODEL_NAME, sizeof(info.model_name) - 1U);
  memcpy(info.model_sha256, MODEL_SHA256, sizeof(MODEL_SHA256));

  for (uint32_t i = 0; i < MODEL_OUTPUT_SIZE; ++i)
  {
    strncpy(info.labels[i],
            model_get_label(i),
            sizeof(info.labels[i]) - 1U);
  }

  (void)SendPacket(uart,
                   SERIAL_RSP_INFO,
                   sequence,
                   &info,
                   sizeof(info));
}

static void RunInference(UART_HandleTypeDef *uart,
                         const serial_model_header_t *header,
                         bool native_input,
                         model_status_t init_status)
{
  serial_model_result_t result;
  model_status_t status;
  int32_t predicted_index = -1;
  uint32_t start_cycles;
  uint32_t end_cycles;

  memset(&result, 0, sizeof(result));
  result.predicted_index = -1;

  if (init_status != MODEL_STATUS_OK)
  {
    result.model_status = init_status;
    (void)SendPacket(uart,
                     SERIAL_RSP_RESULT,
                     header->sequence,
                     &result,
                     sizeof(result));
    return;
  }

  uint32_t expected_length =
      native_input ? model_get_input_byte_count()
                   : model_get_input_size() * sizeof(float);
  if (header->payload_length != expected_length)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_LENGTH,
              "Input payload length does not match the model tensor");
    return;
  }

  BSP_LED_On(LED_BLUE);
  start_cycles = DWT->CYCCNT;
  if (native_input)
  {
    status = model_inference_native(rx_payload.bytes,
                                    header->payload_length,
                                    &predicted_index);
  }
  else
  {
    status = model_inference((const float *)rx_payload.bytes,
                             model_get_input_size(),
                             &predicted_index);
  }
  end_cycles = DWT->CYCCNT;
  BSP_LED_Off(LED_BLUE);

  result.model_status = status;
  result.predicted_index = predicted_index;
  result.cycles = end_cycles - start_cycles;
  uint32_t cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000U;
  result.elapsed_us =
      cycles_per_us == 0U ? 0U : result.cycles / cycles_per_us;

  if (status == MODEL_STATUS_OK)
  {
    const float *scores = model_get_output();
    result.output_count = model_get_output_count();
    for (uint32_t i = 0; i < result.output_count; ++i)
    {
      result.scores[i] = scores[i];
      if (MODEL_OUTPUT_ACTIVATION_ID == MODEL_ACTIVATION_SIGMOID &&
          scores[i] >= MODEL_OUTPUT_THRESHOLD)
      {
        result.active_class_mask |= (1UL << i);
      }
    }

    result.raw_output_bytes = model_get_output_raw_size();
    if (result.raw_output_bytes > sizeof(result.raw_output))
    {
      result.raw_output_bytes = sizeof(result.raw_output);
    }
    memcpy(result.raw_output,
           model_get_output_raw(),
           result.raw_output_bytes);
  }

  (void)SendPacket(uart,
                   SERIAL_RSP_RESULT,
                   header->sequence,
                   &result,
                   sizeof(result));
}

static void SendAudioAck(UART_HandleTypeDef *uart,
                         uint32_t sequence,
                         int32_t status)
{
  serial_audio_ack_t acknowledgement;

  acknowledgement.status = status;
  acknowledgement.received_samples = audio_state.received_samples;
  acknowledgement.completed_windows = audio_state.completed_windows;
  (void)SendPacket(uart,
                   SERIAL_RSP_AUDIO_ACK,
                   sequence,
                   &acknowledgement,
                   sizeof(acknowledgement));
}

static int32_t ProcessAudioWindow(void)
{
  uint32_t start_cycles;
  uint32_t end_cycles;

  start_cycles = DWT->CYCCNT;
  audio_frontend_status_t frontend_status = AudioFrontend_Compute(
      audio_state.window,
      AUDIO_FRONTEND_WINDOW_SAMPLES,
      last_audio_features,
      model_get_input_size());
  end_cycles = DWT->CYCCNT;
  audio_state.frontend_cycles += end_cycles - start_cycles;
  audio_state.frontend_status = frontend_status;
  if (frontend_status != AUDIO_FRONTEND_STATUS_OK)
  {
    audio_state.active = false;
    return frontend_status;
  }
  audio_state.feature_valid = true;

  int32_t predicted_index = -1;
  BSP_LED_On(LED_BLUE);
  start_cycles = DWT->CYCCNT;
  model_status_t model_status =
      model_inference(last_audio_features,
                      model_get_input_size(),
                      &predicted_index);
  end_cycles = DWT->CYCCNT;
  BSP_LED_Off(LED_BLUE);
  audio_state.inference_cycles += end_cycles - start_cycles;
  audio_state.model_status = model_status;
  if (model_status != MODEL_STATUS_OK)
  {
    audio_state.active = false;
    return model_status;
  }

  const float *scores = model_get_output();
  uint32_t output_count = model_get_output_count();
  for (uint32_t index = 0U; index < output_count; ++index)
  {
    audio_state.score_sums[index] += scores[index];
  }
  ++audio_state.completed_windows;
  audio_state.window_fill = 0U;
  return 0;
}

static void BeginAudio(UART_HandleTypeDef *uart,
                       const serial_model_header_t *header,
                       model_status_t init_status)
{
  serial_audio_begin_t request;
  if (header->payload_length != sizeof(request))
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_LENGTH,
              "AUDIO_BEGIN requires a 16-byte descriptor");
    return;
  }
  memcpy(&request, rx_payload.bytes, sizeof(request));
  memset(&audio_state, 0, sizeof(audio_state));

  if (init_status != MODEL_STATUS_OK)
  {
    SendAudioAck(uart, header->sequence, init_status);
    return;
  }
  audio_frontend_status_t frontend_status =
      AudioFrontend_ValidateModel();
  if (frontend_status != AUDIO_FRONTEND_STATUS_OK)
  {
    SendAudioAck(uart, header->sequence, frontend_status);
    return;
  }
  if (request.sample_rate != AUDIO_FRONTEND_SAMPLE_RATE ||
      request.format != SERIAL_AUDIO_FORMAT_PCM_S16_LE ||
      request.reserved != 0U)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_FORMAT,
              "Expected mono 16000-Hz PCM_S16_LE audio");
    return;
  }
  if (request.sample_count == 0U ||
      request.sample_count % AUDIO_FRONTEND_WINDOW_SAMPLES != 0U ||
      request.sample_count / AUDIO_FRONTEND_WINDOW_SAMPLES >
          SERIAL_AUDIO_MAX_WINDOWS)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_FORMAT,
              "Audio must contain 1..120 complete one-second windows");
    return;
  }

  audio_state.active = true;
  audio_state.expected_samples = request.sample_count;
  audio_state.expected_crc32 = request.pcm_crc32;
  audio_state.rolling_crc32 = 0xFFFFFFFFUL;
  audio_state.frontend_status = AUDIO_FRONTEND_STATUS_OK;
  audio_state.model_status = MODEL_STATUS_OK;
  SendAudioAck(uart, header->sequence, 0);
}

static void ReceiveAudioChunk(UART_HandleTypeDef *uart,
                              const serial_model_header_t *header)
{
  if (!audio_state.active)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_STATE,
              "AUDIO_BEGIN is required before AUDIO_CHUNK");
    return;
  }
  if (header->payload_length <= sizeof(uint32_t) ||
      (header->payload_length - sizeof(uint32_t)) % sizeof(int16_t) != 0U)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_LENGTH,
              "AUDIO_CHUNK requires offset plus PCM16 samples");
    return;
  }

  uint32_t offset;
  memcpy(&offset, rx_payload.bytes, sizeof(offset));
  uint32_t sample_count =
      (header->payload_length - sizeof(offset)) / sizeof(int16_t);
  if (offset != audio_state.received_samples ||
      sample_count >
          audio_state.expected_samples - audio_state.received_samples)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_STATE,
              "AUDIO_CHUNK offset or sample range is invalid");
    return;
  }

  const uint8_t *pcm_bytes = rx_payload.bytes + sizeof(offset);
  audio_state.rolling_crc32 =
      Crc32Update(audio_state.rolling_crc32,
                  pcm_bytes,
                  sample_count * sizeof(int16_t));
  for (uint32_t index = 0U; index < sample_count; ++index)
  {
    uint16_t raw_sample =
        (uint16_t)pcm_bytes[2U * index] |
        ((uint16_t)pcm_bytes[2U * index + 1U] << 8U);
    audio_state.window[audio_state.window_fill++] =
        (int16_t)raw_sample;
    ++audio_state.received_samples;

    if (audio_state.window_fill == AUDIO_FRONTEND_WINDOW_SAMPLES)
    {
      int32_t status = ProcessAudioWindow();
      if (status != 0)
      {
        SendAudioAck(uart, header->sequence, status);
        return;
      }
    }
  }
  SendAudioAck(uart, header->sequence, 0);
}

static void FinishAudio(UART_HandleTypeDef *uart,
                        const serial_model_header_t *header)
{
  if (header->payload_length != 0U)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_LENGTH,
              "AUDIO_RUN does not accept a payload");
    return;
  }
  if (!audio_state.active ||
      audio_state.received_samples != audio_state.expected_samples ||
      audio_state.window_fill != 0U ||
      audio_state.completed_windows == 0U)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_STATE,
              "Audio upload is incomplete");
    return;
  }
  uint32_t received_crc32 = audio_state.rolling_crc32 ^ 0xFFFFFFFFUL;
  if (received_crc32 != audio_state.expected_crc32)
  {
    audio_state.active = false;
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_CRC,
              "Complete PCM stream CRC32 mismatch");
    return;
  }

  serial_audio_result_t result;
  memset(&result, 0, sizeof(result));
  result.inference.predicted_index = -1;
  result.inference.model_status = audio_state.model_status;
  result.frontend_status = audio_state.frontend_status;
  result.audio_samples = audio_state.received_samples;
  result.windows = audio_state.completed_windows;
  uint64_t total_cycles =
      audio_state.frontend_cycles + audio_state.inference_cycles;
  result.frontend_cycles =
      SaturateUint64(audio_state.frontend_cycles);
  result.inference_cycles =
      SaturateUint64(audio_state.inference_cycles);
  result.inference.cycles = SaturateUint64(total_cycles);
  uint32_t cycles_per_us = HAL_RCC_GetHCLKFreq() / 1000000U;
  if (cycles_per_us != 0U)
  {
    result.frontend_elapsed_us =
        SaturateUint64(audio_state.frontend_cycles / cycles_per_us);
    result.inference_elapsed_us =
        SaturateUint64(audio_state.inference_cycles / cycles_per_us);
    result.inference.elapsed_us =
        SaturateUint64(total_cycles / cycles_per_us);
  }

  if (result.frontend_status == AUDIO_FRONTEND_STATUS_OK &&
      result.inference.model_status == MODEL_STATUS_OK)
  {
    result.inference.output_count = model_get_output_count();
    float highest_score = -INFINITY;
    for (uint32_t index = 0U;
         index < result.inference.output_count;
         ++index)
    {
      float score =
          audio_state.score_sums[index] /
          (float)audio_state.completed_windows;
      result.inference.scores[index] = score;
      if (score > highest_score)
      {
        highest_score = score;
        result.inference.predicted_index = (int32_t)index;
      }
      if (MODEL_OUTPUT_ACTIVATION_ID == MODEL_ACTIVATION_SIGMOID &&
          score >= MODEL_OUTPUT_THRESHOLD)
      {
        result.inference.active_class_mask |= (1UL << index);
      }

      float scale = model_get_output_scale();
      int32_t quantized = model_get_output_zero_point();
      if (scale > 0.0f)
      {
        quantized += (int32_t)lroundf(score / scale);
      }
      if (quantized < -128)
      {
        quantized = -128;
      }
      else if (quantized > 127)
      {
        quantized = 127;
      }
      result.inference.raw_output[index] = (uint8_t)(int8_t)quantized;
    }
    result.inference.raw_output_bytes = result.inference.output_count;
  }

  audio_state.active = false;
  (void)SendPacket(uart,
                   SERIAL_RSP_AUDIO_RESULT,
                   header->sequence,
                   &result,
                   sizeof(result));
}

static void SendLastAudioFeature(UART_HandleTypeDef *uart,
                                 const serial_model_header_t *header)
{
  if (header->payload_length != 0U)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_BAD_LENGTH,
              "AUDIO_GET_FEATURE does not accept a payload");
    return;
  }
  if (!audio_state.feature_valid)
  {
    SendError(uart,
              header->sequence,
              SERIAL_ERROR_AUDIO_STATE,
              "No completed audio window is available");
    return;
  }

  serial_audio_feature_t *response =
      (serial_audio_feature_t *)rx_payload.bytes;
  response->frontend_status = audio_state.frontend_status;
  response->feature_elements = model_get_input_size();
  memcpy(response->features,
         last_audio_features,
         model_get_input_size() * sizeof(float));
  uint32_t payload_length =
      offsetof(serial_audio_feature_t, features) +
      model_get_input_size() * sizeof(float);
  (void)SendPacket(uart,
                   SERIAL_RSP_AUDIO_FEATURE,
                   header->sequence,
                   response,
                   payload_length);
}

void SerialModelApp_Run(UART_HandleTypeDef *uart)
{
  model_status_t init_status = model_init();

  ModelTest_Init();
  BSP_LED_Off(LED_GREEN);
  BSP_LED_Off(LED_BLUE);
  BSP_LED_Off(LED_RED);
  if (init_status == MODEL_STATUS_OK)
  {
    BSP_LED_On(LED_GREEN);
  }
  else
  {
    BSP_LED_On(LED_RED);
  }

  SendInfo(uart, 0U, init_status);

  while (1)
  {
    serial_model_header_t header;
    HAL_StatusTypeDef uart_status = ReceiveHeader(uart, &header);
    if (uart_status != HAL_OK)
    {
      SendError(uart, 0U, SERIAL_ERROR_UART, "UART header receive failed");
      continue;
    }
    if (header.version != SERIAL_MODEL_PROTOCOL_VERSION)
    {
      SendError(uart,
                header.sequence,
                SERIAL_ERROR_BAD_HEADER,
                "Unsupported protocol version");
      continue;
    }
    if (header.flags != 0U)
    {
      SendError(uart,
                header.sequence,
                SERIAL_ERROR_BAD_HEADER,
                "Unsupported protocol flags");
      continue;
    }
    if (header.payload_length > sizeof(rx_payload.bytes))
    {
      SendError(uart,
                header.sequence,
                SERIAL_ERROR_BAD_LENGTH,
                "Payload exceeds firmware receive buffer");
      continue;
    }
    if (header.payload_length > 0U)
    {
      uart_status = HAL_UART_Receive(uart,
                                    rx_payload.bytes,
                                    (uint16_t)header.payload_length,
                                    SERIAL_PAYLOAD_TIMEOUT_MS);
      if (uart_status != HAL_OK)
      {
        SendError(uart,
                  header.sequence,
                  SERIAL_ERROR_UART,
                  "UART payload receive failed");
        continue;
      }
    }
    if (Crc32(rx_payload.bytes, header.payload_length) !=
        header.payload_crc32)
    {
      SendError(uart,
                header.sequence,
                SERIAL_ERROR_BAD_CRC,
                "Payload CRC32 mismatch");
      continue;
    }

    switch (header.command)
    {
      case SERIAL_CMD_GET_INFO:
        if (header.payload_length != 0U)
        {
          SendError(uart,
                    header.sequence,
                    SERIAL_ERROR_BAD_LENGTH,
                    "GET_INFO does not accept a payload");
        }
        else
        {
          SendInfo(uart, header.sequence, init_status);
        }
        break;

      case SERIAL_CMD_RUN_F32:
        RunInference(uart, &header, false, init_status);
        break;

      case SERIAL_CMD_RUN_NATIVE:
        RunInference(uart, &header, true, init_status);
        break;

      case SERIAL_CMD_AUDIO_BEGIN:
        BeginAudio(uart, &header, init_status);
        break;

      case SERIAL_CMD_AUDIO_CHUNK:
        ReceiveAudioChunk(uart, &header);
        break;

      case SERIAL_CMD_AUDIO_RUN:
        FinishAudio(uart, &header);
        break;

      case SERIAL_CMD_AUDIO_GET_FEATURE:
        SendLastAudioFeature(uart, &header);
        break;

      default:
        SendError(uart,
                  header.sequence,
                  SERIAL_ERROR_BAD_COMMAND,
                  "Unsupported serial model command");
        break;
    }
  }
}
