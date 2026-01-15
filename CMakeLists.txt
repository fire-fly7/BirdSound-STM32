cmake_minimum_required(VERSION 3.22)

#
# This file is generated only once,
# and is not re-generated if converter is called multiple times.
#
# User is free to modify the file as much as necessary
#

# Setup compiler settings
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)

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
enable_language(C ASM)

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})


# Add STM32CubeMX generated sources and CMSIS-DSP library
add_subdirectory(cmake/stm32cubemx)
add_subdirectory(Drivers/CMSIS-DSP)

set(TFLM_ROOT "${CMAKE_SOURCE_DIR}/Drivers/tflite-micro")
# set(CMSISDSP_ROOT "${CMAKE_SOURCE_DIR}/Drivers/CMSIS-DSP/Source")

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    ARM_MATH_CM33
    # Add user defined symbols
)

# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx

    # Add user defined libraries
    CMSISDSP
)
# Add sources to executable


target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    Core/Src/main.c
    Core/Src/mfcc.c
    Core/Src/audio_capture.c
    Core/Src/model_inference.cpp
    Core/Src/ds_cnn_model_data.c
    Core/Src/debug_log.c

    ${TFLM_ROOT}/tensorflow/lite/micro/micro_interpreter_graph.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_interpreter_context.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_allocator.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_context.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_op_resolver.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_interpreter.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_log.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/flatbuffer_utils.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/memory_helpers.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/micro_resource_variable.cc
    ${TFLM_ROOT}/tensorflow/compiler/mlir/lite/schema/schema_utils.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/tflite_bridge/micro_error_reporter.cc
    ${TFLM_ROOT}/tensorflow/lite/micro/tflite_bridge/flatbuffer_conversions_bridge.cc
)
# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    ${CMSISCORE}/Include
    ${PROJECT_SOURCE_DIR}/Drivers/tflite-micro
    ${PROJECT_SOURCE_DIR}/Drivers/tflite-micro/tensorflow/lite/micro/tools/make/downloads/flatbuffers/include
    ${PROJECT_SOURCE_DIR}/Drivers/tflite-micro/tensorflow/lite/micro/tools/make/downloads/gemmlowp
    ${PROJECT_SOURCE_DIR}/Drivers/tflite-micro
)


