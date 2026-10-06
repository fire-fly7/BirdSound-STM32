extern "C" {
#include "model_inference.h"
}

#include "model_data.h"
#include "shared_frontend_contract.h"

#include "tensorflow/lite/core/c/common.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include <math.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>

namespace {

alignas(16) static uint8_t tensor_arena[MODEL_TENSOR_ARENA_BYTES];
static tflite::MicroInterpreter *interpreter = nullptr;
static TfLiteTensor *input = nullptr;
static TfLiteTensor *output = nullptr;
static float output_scores[MODEL_MAX_OUTPUT_ELEMENTS];
static uint32_t input_element_count = 0;
static uint32_t output_element_count = 0;
static uint32_t arena_used = 0;
static model_status_t init_status = MODEL_STATUS_NOT_INITIALIZED;

using ModelOpResolver = tflite::MicroMutableOpResolver<9>;

constexpr int kExpectedInputDims[] = {
    1,
    static_cast<int>(MODEL_FEATURE_FRAMES),
    static_cast<int>(MODEL_FEATURE_BINS),
    static_cast<int>(MODEL_FEATURE_CHANNELS),
};
constexpr int kExpectedOutputDims[] = {
    1,
    static_cast<int>(MODEL_OUTPUT_SIZE),
};

uint32_t TensorElementCount(const TfLiteTensor *tensor)
{
    if (tensor == nullptr || tensor->dims == nullptr) {
        return 0;
    }

    uint32_t count = 1;
    for (int i = 0; i < tensor->dims->size; ++i) {
        if (tensor->dims->data[i] <= 0) {
            return 0;
        }
        count *= static_cast<uint32_t>(tensor->dims->data[i]);
    }
    return count;
}

uint32_t TensorTypeSize(TfLiteType type)
{
    switch (type) {
        case kTfLiteFloat32:
            return sizeof(float);
        case kTfLiteInt8:
        case kTfLiteUInt8:
            return sizeof(uint8_t);
        default:
            return 0;
    }
}

bool TensorTypeSupported(TfLiteType type)
{
    return type == kTfLiteFloat32 || type == kTfLiteInt8 || type == kTfLiteUInt8;
}

template <size_t N>
bool TensorShapeMatches(const TfLiteTensor *tensor, const int (&expected)[N])
{
    if (tensor == nullptr || tensor->dims == nullptr ||
        tensor->dims->size != static_cast<int>(N)) {
        return false;
    }

    for (size_t i = 0; i < N; ++i) {
        if (tensor->dims->data[i] != expected[i]) {
            return false;
        }
    }
    return true;
}

bool QuantizationMatches(const TfLiteTensor *tensor,
                         float expected_scale,
                         int32_t expected_zero_point)
{
    if (tensor == nullptr || tensor->params.scale <= 0.0f) {
        return false;
    }

    return fabsf(tensor->params.scale - expected_scale) <= 1.0e-7f &&
           tensor->params.zero_point == expected_zero_point;
}

int8_t QuantizeInt8(float value, const TfLiteQuantizationParams &params)
{
    return SharedQuantizeInt8(value, params.scale, params.zero_point);
}

uint8_t QuantizeUInt8(float value, const TfLiteQuantizationParams &params)
{
    int32_t quantized = static_cast<int32_t>(lrintf(value / params.scale)) +
                        params.zero_point;
    if (quantized > 255) {
        quantized = 255;
    } else if (quantized < 0) {
        quantized = 0;
    }
    return static_cast<uint8_t>(quantized);
}

float ReadOutputScore(uint32_t index)
{
    switch (output->type) {
        case kTfLiteFloat32:
            return output->data.f[index];
        case kTfLiteInt8:
            return (static_cast<int32_t>(output->data.int8[index]) -
                    output->params.zero_point) * output->params.scale;
        case kTfLiteUInt8:
            return (static_cast<int32_t>(output->data.uint8[index]) -
                    output->params.zero_point) * output->params.scale;
        default:
            return -INFINITY;
    }
}

bool WriteFloatInput(const float *input_data, uint32_t element_count)
{
    if (input_data == nullptr || element_count != input_element_count) {
        return false;
    }

    switch (input->type) {
        case kTfLiteFloat32:
            memcpy(input->data.f, input_data, element_count * sizeof(float));
            return true;
        case kTfLiteInt8:
            if (input->params.scale <= 0.0f) {
                return false;
            }
            for (uint32_t i = 0; i < element_count; ++i) {
                if (!isfinite(input_data[i])) {
                    return false;
                }
                input->data.int8[i] = QuantizeInt8(input_data[i], input->params);
            }
            return true;
        case kTfLiteUInt8:
            if (input->params.scale <= 0.0f) {
                return false;
            }
            for (uint32_t i = 0; i < element_count; ++i) {
                if (!isfinite(input_data[i])) {
                    return false;
                }
                input->data.uint8[i] = QuantizeUInt8(input_data[i], input->params);
            }
            return true;
        default:
            return false;
    }
}

model_status_t InvokeAndRead(int32_t *predicted_index)
{
    if (interpreter->Invoke() != kTfLiteOk) {
        return MODEL_STATUS_INVOKE_FAILED;
    }

    uint32_t max_index = 0;
    float max_score = ReadOutputScore(0);
    output_scores[0] = max_score;
    for (uint32_t i = 1; i < output_element_count; ++i) {
        output_scores[i] = ReadOutputScore(i);
        if (output_scores[i] > max_score) {
            max_score = output_scores[i];
            max_index = i;
        }
    }

    if (predicted_index != nullptr) {
        *predicted_index = static_cast<int32_t>(max_index);
    }
    return MODEL_STATUS_OK;
}

TfLiteStatus RegisterOps(ModelOpResolver &resolver)
{
    TF_LITE_ENSURE_STATUS(resolver.AddAdd());
    TF_LITE_ENSURE_STATUS(resolver.AddConv2D());
    TF_LITE_ENSURE_STATUS(resolver.AddDepthwiseConv2D());
    TF_LITE_ENSURE_STATUS(resolver.AddFullyConnected());
    TF_LITE_ENSURE_STATUS(resolver.AddLogistic());
    TF_LITE_ENSURE_STATUS(resolver.AddMaxPool2D());
    TF_LITE_ENSURE_STATUS(resolver.AddMean());
    TF_LITE_ENSURE_STATUS(resolver.AddMul());
    TF_LITE_ENSURE_STATUS(resolver.AddSoftmax());
    return kTfLiteOk;
}

}  // namespace

extern "C" {

model_status_t model_init(void)
{
#ifdef MODEL_FRONTEND_CONTRACT_SHA256
    if (strcmp(MODEL_FRONTEND_CONTRACT_SHA256, SHARED_CONTRACT_SHA256) != 0) {
        init_status = MODEL_STATUS_METADATA_MISMATCH;
        return init_status;
    }
#endif
    if (model_data_len != MODEL_DATA_BYTES) {
        init_status = MODEL_STATUS_METADATA_MISMATCH;
        return init_status;
    }

    const tflite::Model *model = tflite::GetModel(model_data);
    if (model == nullptr || model->version() != TFLITE_SCHEMA_VERSION) {
        init_status = MODEL_STATUS_SCHEMA_MISMATCH;
        return init_status;
    }

    static ModelOpResolver resolver;
    if (RegisterOps(resolver) != kTfLiteOk) {
        init_status = MODEL_STATUS_OP_REGISTRATION;
        return init_status;
    }

    static tflite::MicroInterpreter static_interpreter(
        model, resolver, tensor_arena, sizeof(tensor_arena));
    interpreter = &static_interpreter;

    if (interpreter->AllocateTensors() != kTfLiteOk) {
        init_status = MODEL_STATUS_ARENA_ALLOCATION;
        return init_status;
    }

    input = interpreter->input(0);
    output = interpreter->output(0);
    input_element_count = TensorElementCount(input);
    output_element_count = TensorElementCount(output);
    arena_used = static_cast<uint32_t>(interpreter->arena_used_bytes());

    if (!TensorShapeMatches(input, kExpectedInputDims) ||
        !TensorShapeMatches(output, kExpectedOutputDims) ||
        input_element_count != MODEL_INPUT_SIZE ||
        output_element_count != MODEL_OUTPUT_SIZE) {
        init_status = MODEL_STATUS_SHAPE_MISMATCH;
        return init_status;
    }
    if (!TensorTypeSupported(input->type) || !TensorTypeSupported(output->type)) {
        init_status = MODEL_STATUS_UNSUPPORTED_TYPE;
        return init_status;
    }
    if (input->type != kTfLiteInt8 || output->type != kTfLiteInt8 ||
        !QuantizationMatches(input,
                             MODEL_INPUT_SCALE,
                             MODEL_INPUT_ZERO_POINT) ||
        !QuantizationMatches(output,
                             MODEL_OUTPUT_SCALE,
                             MODEL_OUTPUT_ZERO_POINT)) {
        init_status = MODEL_STATUS_METADATA_MISMATCH;
        return init_status;
    }

    init_status = MODEL_STATUS_OK;
    return init_status;
}

model_status_t model_inference(const float *input_data,
                               uint32_t element_count,
                               int32_t *predicted_index)
{
    if (init_status != MODEL_STATUS_OK) {
        return init_status;
    }
    if (!WriteFloatInput(input_data, element_count)) {
        return MODEL_STATUS_BAD_INPUT;
    }
    return InvokeAndRead(predicted_index);
}

model_status_t model_inference_native(const void *input_data,
                                      uint32_t byte_count,
                                      int32_t *predicted_index)
{
    if (init_status != MODEL_STATUS_OK) {
        return init_status;
    }
    if (input_data == nullptr || byte_count != model_get_input_byte_count()) {
        return MODEL_STATUS_BAD_INPUT;
    }

    memcpy(input->data.raw, input_data, byte_count);
    return InvokeAndRead(predicted_index);
}

const float *model_get_output(void)
{
    return output_scores;
}

const void *model_get_output_raw(void)
{
    return output == nullptr ? nullptr : output->data.raw_const;
}

uint32_t model_get_output_raw_size(void)
{
    if (output == nullptr) {
        return 0;
    }
    return output_element_count * TensorTypeSize(output->type);
}

uint32_t model_get_input_size(void)
{
    return input_element_count;
}

uint32_t model_get_output_count(void)
{
    return output_element_count;
}

uint32_t model_get_arena_used(void)
{
    return arena_used;
}

uint32_t model_get_input_byte_count(void)
{
    if (input == nullptr) {
        return 0;
    }
    return input_element_count * TensorTypeSize(input->type);
}

uint8_t model_get_input_type(void)
{
    return input == nullptr ? 0U : static_cast<uint8_t>(input->type);
}

uint8_t model_get_output_type(void)
{
    return output == nullptr ? 0U : static_cast<uint8_t>(output->type);
}

float model_get_input_scale(void)
{
    return input == nullptr ? 0.0f : input->params.scale;
}

int32_t model_get_input_zero_point(void)
{
    return input == nullptr ? 0 : input->params.zero_point;
}

float model_get_output_scale(void)
{
    return output == nullptr ? 0.0f : output->params.scale;
}

int32_t model_get_output_zero_point(void)
{
    return output == nullptr ? 0 : output->params.zero_point;
}

bool model_is_compatible(void)
{
    return init_status == MODEL_STATUS_OK;
}

const char *model_get_label(uint32_t index)
{
    static const char *const labels[MODEL_OUTPUT_SIZE] = {
        MODEL_LABEL_0,
        MODEL_LABEL_1,
        MODEL_LABEL_2,
        MODEL_LABEL_3,
        MODEL_LABEL_4,
        MODEL_LABEL_5,
        MODEL_LABEL_6,
        MODEL_LABEL_7,
    };
    return index < MODEL_OUTPUT_SIZE ? labels[index] : "";
}

}  // extern "C"
