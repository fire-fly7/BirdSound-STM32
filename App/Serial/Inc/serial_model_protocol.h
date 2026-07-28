#ifndef STM32_DEPLOY_SERIAL_MODEL_PROTOCOL_H
#define STM32_DEPLOY_SERIAL_MODEL_PROTOCOL_H

#include <stdint.h>

#include "model_config.h"

#define SERIAL_MODEL_MAGIC            0x31544D53UL
#define SERIAL_MODEL_PROTOCOL_VERSION 1U
#define SERIAL_MODEL_NAME_BYTES       48U
#define SERIAL_MODEL_SHA256_BYTES     65U
#define SERIAL_MODEL_LABEL_BYTES      32U
#define SERIAL_MODEL_MAX_PAYLOAD      \
  (8U + MODEL_MAX_INPUT_ELEMENTS * sizeof(float))
#define SERIAL_AUDIO_FORMAT_PCM_S16_LE 1U

typedef enum
{
  SERIAL_CMD_GET_INFO = 0x01,
  SERIAL_CMD_RUN_F32 = 0x02,
  SERIAL_CMD_RUN_NATIVE = 0x03,
  SERIAL_CMD_AUDIO_BEGIN = 0x10,
  SERIAL_CMD_AUDIO_CHUNK = 0x11,
  SERIAL_CMD_AUDIO_RUN = 0x12,
  SERIAL_CMD_AUDIO_GET_FEATURE = 0x13,
  SERIAL_RSP_INFO = 0x81,
  SERIAL_RSP_RESULT = 0x82,
  SERIAL_RSP_AUDIO_ACK = 0x90,
  SERIAL_RSP_AUDIO_FEATURE = 0x91,
  SERIAL_RSP_AUDIO_RESULT = 0x92,
  SERIAL_RSP_ERROR = 0xFF
} serial_model_command_t;

typedef enum
{
  SERIAL_ERROR_BAD_HEADER = -100,
  SERIAL_ERROR_BAD_LENGTH = -101,
  SERIAL_ERROR_BAD_CRC = -102,
  SERIAL_ERROR_BAD_COMMAND = -103,
  SERIAL_ERROR_UART = -104,
  SERIAL_ERROR_AUDIO_FORMAT = -105,
  SERIAL_ERROR_AUDIO_STATE = -106
} serial_model_error_t;

#if defined(__GNUC__)
#define SERIAL_PACKED __attribute__((packed))
#else
#define SERIAL_PACKED
#endif

typedef struct SERIAL_PACKED
{
  uint32_t magic;
  uint8_t version;
  uint8_t command;
  uint16_t flags;
  uint32_t sequence;
  uint32_t payload_length;
  uint32_t payload_crc32;
} serial_model_header_t;

typedef struct SERIAL_PACKED
{
  int32_t model_status;
  uint8_t feature_id;
  uint8_t output_activation_id;
  uint8_t input_type;
  uint8_t output_type;
  uint16_t input_dims[4];
  uint16_t output_count;
  uint16_t label_count;
  uint32_t input_elements;
  uint32_t model_bytes;
  uint32_t arena_bytes;
  uint32_t arena_used;
  float input_scale;
  int32_t input_zero_point;
  float output_scale;
  int32_t output_zero_point;
  char model_name[SERIAL_MODEL_NAME_BYTES];
  char model_sha256[SERIAL_MODEL_SHA256_BYTES];
  char labels[MODEL_MAX_OUTPUT_ELEMENTS][SERIAL_MODEL_LABEL_BYTES];
} serial_model_info_t;

typedef struct SERIAL_PACKED
{
  int32_t model_status;
  int32_t predicted_index;
  uint32_t cycles;
  uint32_t elapsed_us;
  uint32_t active_class_mask;
  uint32_t output_count;
  uint32_t raw_output_bytes;
  float scores[MODEL_MAX_OUTPUT_ELEMENTS];
  uint8_t raw_output[MODEL_MAX_OUTPUT_ELEMENTS * sizeof(float)];
} serial_model_result_t;

typedef struct SERIAL_PACKED
{
  uint32_t sample_rate;
  uint32_t sample_count;
  uint16_t format;
  uint16_t reserved;
  uint32_t pcm_crc32;
} serial_audio_begin_t;

typedef struct SERIAL_PACKED
{
  int32_t status;
  uint32_t received_samples;
  uint32_t completed_windows;
} serial_audio_ack_t;

typedef struct SERIAL_PACKED
{
  serial_model_result_t inference;
  int32_t frontend_status;
  uint32_t audio_samples;
  uint32_t windows;
  uint32_t frontend_cycles;
  uint32_t frontend_elapsed_us;
  uint32_t inference_cycles;
  uint32_t inference_elapsed_us;
} serial_audio_result_t;

typedef struct SERIAL_PACKED
{
  int32_t frontend_status;
  uint32_t feature_elements;
  float features[MODEL_MAX_INPUT_ELEMENTS];
} serial_audio_feature_t;

typedef struct SERIAL_PACKED
{
  int32_t error_code;
  char message[96];
} serial_model_error_payload_t;

#endif /* STM32_DEPLOY_SERIAL_MODEL_PROTOCOL_H */
