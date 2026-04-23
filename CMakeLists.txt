cmake_minimum_required(VERSION 3.22)

# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Define the build type
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE "Debug")
endif()

# Set the project name
set(CMAKE_PROJECT_NAME LED_TEST)

# Include toolchain file
include("cmake/gcc-arm-none-eabi.cmake")

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM and C languages
enable_language(C CXX ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})


# Add STM32CubeMX generated sources and CMSIS-DSP library and definded sflm static library
add_subdirectory(cmake/stm32cubemx)
add_subdirectory(Drivers/CMSIS-DSP)
add_library(tflm STATIC)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    ARM_MATH_CM33
    # Add user defined symbols
)


# Add TensorFlow Lite Micro sources
target_sources(tflm PRIVATE
    # ===== Kernel =====
    Drivers/tflite-micro/tensorflow/lite/kernels/kernel_util.cc
    Drivers/tflite-micro/tensorflow/lite/kernels/internal/common.cc
    Drivers/tflite-micro/tensorflow/lite/kernels/internal/portable_tensor_utils.cc
    Drivers/tflite-micro/tensorflow/lite/kernels/internal/quantization_util.cc
    Drivers/tflite-micro/tensorflow/lite/kernels/internal/tensor_ctypes.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/conv.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/conv_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/depthwise_conv.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/depthwise_conv_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/fully_connected.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/fully_connected_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/softmax.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/softmax_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/add.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/add_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/pooling.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/pooling_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/reshape.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/reshape_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/quantize.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/quantize_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/dequantize.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/dequantize_common.cc

    # ===== Memory =====
    Drivers/tflite-micro/tensorflow/lite/micro/memory_planner/linear_memory_planner.cc
    Drivers/tflite-micro/tensorflow/lite/micro/memory_planner/greedy_memory_planner.cc
    Drivers/tflite-micro/tensorflow/lite/micro/memory_planner/non_persistent_buffer_planner_shim.cc
    Drivers/tflite-micro/tensorflow/lite/micro/arena_allocator/single_arena_buffer_allocator.cc
    Drivers/tflite-micro/tensorflow/lite/micro/arena_allocator/persistent_arena_buffer_allocator.cc
    Drivers/tflite-micro/tensorflow/lite/micro/arena_allocator/non_persistent_arena_buffer_allocator.cc

    # ===== Runtime =====
    Drivers/tflite-micro/tensorflow/lite/core/c/common.cc
    Drivers/tflite-micro/tensorflow/compiler/mlir/lite/core/api/error_reporter.cc
    Drivers/tflite-micro/tensorflow/lite/core/api/flatbuffer_conversions.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_interpreter_graph.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_interpreter_context.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_allocator.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_allocation_info.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_context.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_op_resolver.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_interpreter.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_log.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_utils.cc
    Drivers/tflite-micro/tensorflow/lite/micro/flatbuffer_utils.cc
    Drivers/tflite-micro/tensorflow/lite/micro/memory_helpers.cc
    Drivers/tflite-micro/tensorflow/lite/micro/micro_resource_variable.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/kernel_util.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/micro_tensor_utils.cc
    Drivers/tflite-micro/tensorflow/compiler/mlir/lite/schema/schema_utils.cc
    Drivers/tflite-micro/tensorflow/lite/micro/tflite_bridge/micro_error_reporter.cc
    Drivers/tflite-micro/tensorflow/lite/micro/tflite_bridge/flatbuffer_conversions_bridge.cc
)

target_include_directories(tflm PUBLIC
    Drivers/tflite-micro
    Drivers/tflite-micro/tensorflow/lite/micro
    Drivers/tflite-micro/tensorflow/lite/core/api
    Drivers/tflite-micro/tensorflow/lite/schema
    Drivers/tflite-micro/tensorflow/lite/micro/tools/make/downloads/flatbuffers/include
    Drivers/tflite-micro/tensorflow/lite/micro/tools/make/downloads/gemmlowp
    Drivers/tflite-micro/tensorflow/lite/micro/tools/make/downloads/ruy
)

target_compile_definitions(tflm PUBLIC
    TF_LITE_STATIC_MEMORY
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE

    Drivers/CMSIS/Include
    Drivers/CMSIS/DSP/Include
    Drivers/CMSIS/Core/Include
    Drivers/CMSIS-DSP/Includes

)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/main.c
    Core/Src/mfcc.c
    Core/Src/audio_capture.c
    Core/Src/model_data.c
    Core/Src/model_inference.cpp
    Core/Src/model_test.cpp
    Core/Src/debug_log.c



)



# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx
    # Add user defined libraries
    CMSISDSP
    tflm
)
