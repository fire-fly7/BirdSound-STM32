extern "C" {
#include "model_inference.h"
}
#include "ds_cnn_model_data.h"
#include "cnn_model_data.h"
#include "bc_resnet_data.h"
#include "mobilenetv2_data.h"
#include "stddef.h"

#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/micro/tflite_bridge/micro_error_reporter.h"
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/schema/schema_generated.h"
#include "tensorflow/lite/core/c/common.h"

constexpr int kTensorArenaSize = 20 * 1024;
static uint8_t tensor_arena[kTensorArenaSize];
using Feature = int8_t[][kTensorArenaSize];

static tflite::MicroInterpreter* interpreter = nullptr;
static TfLiteTensor* input = nullptr;
static TfLiteTensor* output = nullptr;

static tflite::MicroErrorReporter micro_error_reporter;
static tflite::ErrorReporter* error_reporter = &micro_error_reporter;

#define MODEL_INPUT_SIZE  (32 * 13)
#define MODEL_OUTPUT_SIZE  3

using Micro_Voice_OpResolver = tflite::MicroMutableOpResolver<5>;

extern "C" {

TfLiteStatus RegisterOps(Micro_Voice_OpResolver& op_resolver) {
    TF_LITE_ENSURE_STATUS(op_resolver.AddReshape());
    TF_LITE_ENSURE_STATUS(op_resolver.AddFullyConnected());
    TF_LITE_ENSURE_STATUS(op_resolver.AddDepthwiseConv2D());
    TF_LITE_ENSURE_STATUS(op_resolver.AddConv2D());
    TF_LITE_ENSURE_STATUS(op_resolver.AddSoftmax());
    
    // only for quantized model
    TF_LITE_ENSURE_STATUS(op_resolver.AddAdd());
    TF_LITE_ENSURE_STATUS(op_resolver.AddAveragePool2D());
    TF_LITE_ENSURE_STATUS(op_resolver.AddQuantize());
    TF_LITE_ENSURE_STATUS(op_resolver.AddDequantize());
  return kTfLiteOk;
}

void model_init(void) {   

    const tflite::Model* model = tflite::GetModel(model_data);
    if (model->version() != TFLITE_SCHEMA_VERSION) {
        TF_LITE_REPORT_ERROR(error_reporter, "Model schema mismatch!");
        while (1);
    }

    static Micro_Voice_OpResolver resolver;
    if (RegisterOps(resolver) != kTfLiteOk) {
        TF_LITE_REPORT_ERROR(error_reporter, "Op registration failed!");
        while (1);
    }

    static tflite::MicroInterpreter static_interpreter(
            model, resolver,tensor_arena, kTensorArenaSize);

    interpreter = &static_interpreter;

    if (interpreter->AllocateTensors() != kTfLiteOk) {
        TF_LITE_REPORT_ERROR(error_reporter, "AllocateTensors failed!");
        while (1);
    }

    input = interpreter->input(0);
    output = interpreter->output(0);
    }

void DWT_Init()
{
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    DWT->CYCCNT = 0;
    DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

// int model_predict(const float *input_data) {
//     for (int i = 0; i < MODEL_INPUT_SIZE; ++i) {
//         input->data.f[i] = input_data[i];
//     }

//     if (interpreter->Invoke() != kTfLiteOk) {
//         return -1;
//     }

//     // 找最大概率的类别索引
//     int max_index = 0;
//     float max_score = output->data.f[0];
//     for (int i = 1; i < MODEL_OUTPUT_SIZE; i++) {
//         if (output->data.f[i] > max_score) {
//             max_score = output->data.f[i];
//             max_index = i;
//         }
//     }
//     return max_index;
// }

// const float* model_get_output(void) {
//     return output->data.f;
// }
}