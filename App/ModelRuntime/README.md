# Model runtime

This module owns the model-independent TFLite Micro interface and the active
model bundle. `Inc/model_manifest.h` and `Src/model_data.c` are the checked-in
default bundle; CMake replaces them with generated files when
`STM32_MODEL_TFLITE` is set.

`Legacy/` contains historical embedded model headers that are not compiled.
They are retained only as migration references and must not be included by a
firmware target.
