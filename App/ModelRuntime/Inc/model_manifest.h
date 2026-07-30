#ifndef MODEL_MANIFEST_H
#define MODEL_MANIFEST_H

/*
 * Generated from:
 * fire-fly7/Model_train@42ead2e614e3f40afc7da29e660fc94609d10817
 * src/experiments/ZeroShot_strict_INT8_quantization_8class/models/zero_shot_logmel/
 * DS_CNN_Model.int8.tflite
 */
#define MODEL_NAME                  "zero_shot_logmel_DS_CNN_int8"
#define MODEL_SOURCE_COMMIT         "42ead2e614e3f40afc7da29e660fc94609d10817"
#define MODEL_SHA256                "b1e0a736841d9dff7d35b35eca451bed01eaabf9cfb818d7d7cb4b89dafd13e7"
#define MODEL_DATA_BYTES            49984U
#define MODEL_FEATURE_TYPE          "LogMel"
#define MODEL_FEATURE_ID            2U
#define MODEL_FEATURE_FRAMES        32U
#define MODEL_FEATURE_BINS          40U
#define MODEL_FEATURE_CHANNELS      1U
#define MODEL_INPUT_SIZE            1280U
#define MODEL_OUTPUT_SIZE           8U
#define MODEL_OUTPUT_ACTIVATION     "softmax"
#define MODEL_OUTPUT_ACTIVATION_ID  1U
#define MODEL_OUTPUT_THRESHOLD      0.5f
#define MODEL_INPUT_SCALE           0.3137255012989044f
#define MODEL_INPUT_ZERO_POINT      127
#define MODEL_OUTPUT_SCALE          0.00390625f
#define MODEL_OUTPUT_ZERO_POINT     (-128)
#define MODEL_TENSOR_ARENA_BYTES    (96U * 1024U)

#define MODEL_LABEL_0               "Agelaius_phoeniceus"
#define MODEL_LABEL_1               "Cardinalis_cardinalis"
#define MODEL_LABEL_2               "Certhia_americana"
#define MODEL_LABEL_3               "Corvus_brachyrhynchos"
#define MODEL_LABEL_4               "Setophaga_aestiva"
#define MODEL_LABEL_5               "Setophaga_ruticilla"
#define MODEL_LABEL_6               "Spinus_tristis"
#define MODEL_LABEL_7               "Turdus_migratorius"

#endif /* MODEL_MANIFEST_H */
