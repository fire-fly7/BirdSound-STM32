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
set(CMAKE_PROJECT_NAME STM32_deploy)

# Include toolchain file
include("cmake/gcc-arm-none-eabi.cmake")

# Enable compile command to ease indexing with e.g. clangd
set(CMAKE_EXPORT_COMPILE_COMMANDS TRUE)

# Core project settings
project(${CMAKE_PROJECT_NAME})
message("Build type: " ${CMAKE_BUILD_TYPE})

# Enable CMake support for ASM and C languages
enable_language(C CXX ASM)

# The microphone capture frontend is intentionally not part of the serial
# application. It receives PCM16 recordings over UART, then runs the shared
# feature frontend and model inference entirely on the board.
set(STM32_DEPLOY_APP "serial" CACHE STRING "Firmware application")
set_property(CACHE STM32_DEPLOY_APP PROPERTY STRINGS serial)
if(STM32_DEPLOY_APP STREQUAL "serial")
    set(STM32_DEPLOY_APP_DEFINITIONS
        STM32_DEPLOY_SERIAL_APP=1)
    set(STM32_DEPLOY_APP_INCLUDE_DIRS
        App/Serial/Inc)
    set(STM32_DEPLOY_APP_SOURCES
        App/Serial/Src/stm32_deploy_serial_app.c
        App/Serial/Src/serial_model_app.c)
else()
    message(FATAL_ERROR "Only STM32_DEPLOY_APP=serial is currently implemented")
endif()

# Leave STM32_MODEL_TFLITE empty to use the checked-in default bundle. Point it
# at any strict-int8 Model_train export to generate a matching bundle at
# configure time.
set(STM32_MODEL_TFLITE "" CACHE FILEPATH "Model_train strict-int8 .tflite export")
set(STM32_MODEL_METADATA "" CACHE FILEPATH "Optional Model_train metadata JSON")
set(STM32_MODEL_LABEL_MAP "" CACHE FILEPATH "Optional Model_train label map JSON")
set(STM32_MODEL_FEATURE "" CACHE STRING "Optional frontend override: MFCC, LOGMEL, or PCEN")
set_property(CACHE STM32_MODEL_FEATURE PROPERTY STRINGS "" MFCC LOGMEL PCEN)
set(STM32_MODEL_SOURCE_COMMIT "unknown" CACHE STRING "Model_train source commit")
set(STM32_MODEL_ARENA_BYTES "98304" CACHE STRING "Tensor arena size")

set(STM32_MODEL_DATA_SOURCE
    "${CMAKE_CURRENT_SOURCE_DIR}/App/ModelRuntime/Src/model_data.c")
set(STM32_MODEL_INCLUDE_DIR
    "${CMAKE_CURRENT_SOURCE_DIR}/App/ModelRuntime/Inc")

find_package(Python3 REQUIRED COMPONENTS Interpreter)
execute_process(
    COMMAND "${Python3_EXECUTABLE}" -c "import numpy"
    RESULT_VARIABLE STM32_PYTHON_BUILD_DEPS_RESULT
    OUTPUT_QUIET
    ERROR_QUIET)
if(NOT STM32_PYTHON_BUILD_DEPS_RESULT EQUAL 0)
    message(FATAL_ERROR
            "Python build dependencies are missing. Create/activate a virtual "
            "environment, then run:\n"
            "  python -m pip install -r "
            "${CMAKE_CURRENT_SOURCE_DIR}/tools/requirements-build.txt")
endif()

# TFLite Micro keeps FlatBuffers, gemmlowp, and ruy outside its source tree.
# Fetch the versions locked and checksum-verified by the pinned TFLM commit on
# the first clean-clone configure. The downloads directory is ignored by the
# submodule, so this does not make the recorded source revision dirty.
set(TFLM_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/Drivers/tflite-micro")
set(TFLM_MAKEFILE
    "${TFLM_ROOT}/tensorflow/lite/micro/tools/make/Makefile")
set(TFLM_DOWNLOADS_DIR
    "${TFLM_ROOT}/tensorflow/lite/micro/tools/make/downloads")
set(TFLM_REQUIRED_DEPENDENCIES
    "${TFLM_DOWNLOADS_DIR}/flatbuffers/include/flatbuffers/flatbuffers.h"
    "${TFLM_DOWNLOADS_DIR}/gemmlowp/fixedpoint/fixedpoint.h"
    "${TFLM_DOWNLOADS_DIR}/ruy/ruy/profiler/instrumentation.h")

if(NOT EXISTS "${TFLM_ROOT}/tensorflow/lite/kernels/kernel_util.cc")
    message(FATAL_ERROR
            "TFLite Micro submodule is missing. Run:\n"
            "  git submodule update --init --recursive")
endif()

set(TFLM_DEPENDENCIES_MISSING FALSE)
foreach(TFLM_DEPENDENCY IN LISTS TFLM_REQUIRED_DEPENDENCIES)
    if(NOT EXISTS "${TFLM_DEPENDENCY}")
        set(TFLM_DEPENDENCIES_MISSING TRUE)
    endif()
endforeach()
if(TFLM_DEPENDENCIES_MISSING)
    message(STATUS "Fetching checksum-locked TFLite Micro dependencies")

    # Do not invoke TFLM's top-level Makefile here. Parsing that Makefile also
    # downloads unrelated example assets and imports NumPy, even though this
    # firmware only needs these three header dependencies. Call the download
    # helpers from the pinned submodule directly; NumPy remains an explicit,
    # pinned dependency of this project's frontend table generator.
    set(TFLM_MAKE_TOOLS
        "${TFLM_ROOT}/tensorflow/lite/micro/tools/make")
    file(MAKE_DIRECTORY "${TFLM_DOWNLOADS_DIR}")
    if(NOT EXISTS
       "${TFLM_DOWNLOADS_DIR}/flatbuffers/include/flatbuffers/flatbuffers.h")
        file(REMOVE_RECURSE "${TFLM_DOWNLOADS_DIR}/flatbuffers")
        execute_process(
            COMMAND "${TFLM_MAKE_TOOLS}/flatbuffers_download.sh"
                    "${TFLM_DOWNLOADS_DIR}" "${TFLM_ROOT}/"
            WORKING_DIRECTORY "${TFLM_ROOT}"
            RESULT_VARIABLE TFLM_FLATBUFFERS_RESULT)
    else()
        set(TFLM_FLATBUFFERS_RESULT 0)
    endif()
    if(NOT EXISTS "${TFLM_DOWNLOADS_DIR}/gemmlowp/fixedpoint/fixedpoint.h")
        file(REMOVE_RECURSE "${TFLM_DOWNLOADS_DIR}/gemmlowp")
        execute_process(
            COMMAND "${TFLM_MAKE_TOOLS}/download_and_extract.sh"
                    "https://github.com/google/gemmlowp/archive/719139ce755a0f31cbf1c37f7f98adcc7fc9f425.zip"
                    "7e8191b24853d75de2af87622ad293ba"
                    "${TFLM_DOWNLOADS_DIR}/gemmlowp"
            WORKING_DIRECTORY "${TFLM_ROOT}"
            RESULT_VARIABLE TFLM_GEMMLOWP_RESULT)
    else()
        set(TFLM_GEMMLOWP_RESULT 0)
    endif()
    if(NOT EXISTS
       "${TFLM_DOWNLOADS_DIR}/ruy/ruy/profiler/instrumentation.h")
        file(REMOVE_RECURSE "${TFLM_DOWNLOADS_DIR}/ruy")
        execute_process(
            COMMAND "${TFLM_MAKE_TOOLS}/download_and_extract.sh"
                    "https://github.com/google/ruy/archive/d37128311b445e758136b8602d1bbd2a755e115d.zip"
                    "abf7a91eb90d195f016ebe0be885bb6e"
                    "${TFLM_DOWNLOADS_DIR}/ruy"
            WORKING_DIRECTORY "${TFLM_ROOT}"
            RESULT_VARIABLE TFLM_RUY_RESULT)
    else()
        set(TFLM_RUY_RESULT 0)
    endif()

    math(EXPR TFLM_DOWNLOAD_RESULT
         "${TFLM_FLATBUFFERS_RESULT} + ${TFLM_GEMMLOWP_RESULT} + ${TFLM_RUY_RESULT}")
    foreach(TFLM_DEPENDENCY IN LISTS TFLM_REQUIRED_DEPENDENCIES)
        if(NOT EXISTS "${TFLM_DEPENDENCY}")
            message(FATAL_ERROR
                    "TFLite Micro dependency bootstrap did not create "
                    "${TFLM_DEPENDENCY}")
        endif()
    endforeach()
    if(NOT TFLM_DOWNLOAD_RESULT EQUAL 0)
        message(FATAL_ERROR
                "TFLite Micro dependency bootstrap failed with "
                "exit code ${TFLM_DOWNLOAD_RESULT}")
    endif()
endif()

if(STM32_MODEL_TFLITE)
    get_filename_component(STM32_MODEL_TFLITE_ABSOLUTE
                           "${STM32_MODEL_TFLITE}" ABSOLUTE
                           BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
    set(STM32_MODEL_GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated/model")
    set(STM32_MODEL_GENERATOR
        "${CMAKE_CURRENT_SOURCE_DIR}/tools/generate_model_bundle.py")
    set(STM32_MODEL_GENERATOR_COMMAND
        "${Python3_EXECUTABLE}"
        "${STM32_MODEL_GENERATOR}"
        --tflite "${STM32_MODEL_TFLITE_ABSOLUTE}"
        --source-commit "${STM32_MODEL_SOURCE_COMMIT}"
        --arena-bytes "${STM32_MODEL_ARENA_BYTES}"
        --output-dir "${STM32_MODEL_GENERATED_DIR}")

    set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
                 "${STM32_MODEL_GENERATOR}"
                 "${STM32_MODEL_TFLITE_ABSOLUTE}")

    if(STM32_MODEL_METADATA)
        get_filename_component(STM32_MODEL_METADATA_ABSOLUTE
                               "${STM32_MODEL_METADATA}" ABSOLUTE
                               BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND STM32_MODEL_GENERATOR_COMMAND
             --metadata "${STM32_MODEL_METADATA_ABSOLUTE}")
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
                     "${STM32_MODEL_METADATA_ABSOLUTE}")
    endif()
    if(STM32_MODEL_LABEL_MAP)
        get_filename_component(STM32_MODEL_LABEL_MAP_ABSOLUTE
                               "${STM32_MODEL_LABEL_MAP}" ABSOLUTE
                               BASE_DIR "${CMAKE_CURRENT_SOURCE_DIR}")
        list(APPEND STM32_MODEL_GENERATOR_COMMAND
             --label-map "${STM32_MODEL_LABEL_MAP_ABSOLUTE}")
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
                     "${STM32_MODEL_LABEL_MAP_ABSOLUTE}")
    endif()
    if(STM32_MODEL_FEATURE)
        list(APPEND STM32_MODEL_GENERATOR_COMMAND
             --feature "${STM32_MODEL_FEATURE}")
    endif()

    execute_process(
        COMMAND ${STM32_MODEL_GENERATOR_COMMAND}
        RESULT_VARIABLE STM32_MODEL_GENERATOR_RESULT
        OUTPUT_VARIABLE STM32_MODEL_GENERATOR_OUTPUT
        ERROR_VARIABLE STM32_MODEL_GENERATOR_ERROR
        OUTPUT_STRIP_TRAILING_WHITESPACE
        ERROR_STRIP_TRAILING_WHITESPACE)
    if(NOT STM32_MODEL_GENERATOR_RESULT EQUAL 0)
        message(FATAL_ERROR
                "Model bundle generation failed:\n${STM32_MODEL_GENERATOR_ERROR}")
    endif()
    message(STATUS "${STM32_MODEL_GENERATOR_OUTPUT}")
    set(STM32_MODEL_DATA_SOURCE
        "${STM32_MODEL_GENERATED_DIR}/model_data.c")
    set(STM32_MODEL_INCLUDE_DIR "${STM32_MODEL_GENERATED_DIR}")
else()
    message(STATUS "Using checked-in default model bundle")
endif()

set(STM32_FRONTEND_GENERATED_DIR
    "${CMAKE_CURRENT_BINARY_DIR}/generated/frontend")
set(STM32_FRONTEND_GENERATOR
    "${CMAKE_CURRENT_SOURCE_DIR}/tools/generate_mfcc_frontend_tables.py")
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
             "${STM32_FRONTEND_GENERATOR}")
execute_process(
    COMMAND "${Python3_EXECUTABLE}"
            "${STM32_FRONTEND_GENERATOR}"
            --output-dir "${STM32_FRONTEND_GENERATED_DIR}"
    RESULT_VARIABLE STM32_FRONTEND_GENERATOR_RESULT
    OUTPUT_VARIABLE STM32_FRONTEND_GENERATOR_OUTPUT
    ERROR_VARIABLE STM32_FRONTEND_GENERATOR_ERROR
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_STRIP_TRAILING_WHITESPACE)
if(NOT STM32_FRONTEND_GENERATOR_RESULT EQUAL 0)
    message(FATAL_ERROR
            "MFCC frontend table generation failed:\n"
            "${STM32_FRONTEND_GENERATOR_ERROR}")
endif()
message(STATUS "${STM32_FRONTEND_GENERATOR_OUTPUT}")

# Create an executable object type
add_executable(${CMAKE_PROJECT_NAME})


# Add STM32CubeMX generated sources and the TFLite Micro runtime.
add_subdirectory(cmake/stm32cubemx)
add_library(tflm STATIC)
add_library(cmsis_dsp_frontend STATIC)

# Add project symbols (macros)
target_compile_definitions(${CMAKE_PROJECT_NAME} PRIVATE
    ${STM32_DEPLOY_APP_DEFINITIONS}
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
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/logistic.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/logistic_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/softmax.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/softmax_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/add.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/add_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/pooling.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/pooling_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/mul.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/mul_common.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/reduce.cc
    Drivers/tflite-micro/tensorflow/lite/micro/kernels/reduce_common.cc

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

target_sources(cmsis_dsp_frontend PRIVATE
    Drivers/CMSIS/DSP/Source/TransformFunctions/arm_rfft_fast_f32.c
    Drivers/CMSIS/DSP/Source/TransformFunctions/arm_rfft_fast_init_f32.c
    Drivers/CMSIS/DSP/Source/TransformFunctions/arm_cfft_f32.c
    Drivers/CMSIS/DSP/Source/TransformFunctions/arm_cfft_radix8_f32.c
    Drivers/CMSIS/DSP/Source/TransformFunctions/arm_bitreversal2.c
    Drivers/CMSIS/DSP/Source/CommonTables/arm_common_tables.c
)
target_include_directories(cmsis_dsp_frontend PUBLIC
    Drivers/CMSIS/DSP/Include
    Drivers/CMSIS/Include
    Drivers/CMSIS/Core/Include
)
target_compile_definitions(cmsis_dsp_frontend PUBLIC
    ARM_MATH_CM33
    ARM_DSP_CONFIG_TABLES
    ARM_FFT_ALLOW_TABLES
    ARM_TABLE_TWIDDLECOEF_F32_1024
    ARM_TABLE_BITREVIDX_FLT_1024
    ARM_TABLE_TWIDDLECOEF_RFFT_F32_2048
)

# Add include paths
target_include_directories(${CMAKE_PROJECT_NAME} PRIVATE
    ${STM32_MODEL_INCLUDE_DIR}
    ${STM32_FRONTEND_GENERATED_DIR}
    App/Inc
    App/AudioFrontend/Inc
    App/ModelRuntime/Inc
    ${STM32_DEPLOY_APP_INCLUDE_DIRS}
    Drivers/CMSIS/DSP/Include
    Drivers/CMSIS/Include
    Drivers/CMSIS/Core/Include

)

# Add sources to executable
target_sources(${CMAKE_PROJECT_NAME} PRIVATE
    ${STM32_MODEL_DATA_SOURCE}
    ${STM32_FRONTEND_GENERATED_DIR}/mfcc_frontend_tables.c
    App/ModelRuntime/Src/model_debug_log.c
    App/ModelRuntime/Src/model_inference.cpp
    App/ModelRuntime/Src/model_test.cpp
    App/AudioFrontend/Src/audio_frontend.c
    ${STM32_DEPLOY_APP_SOURCES}
)



# Add linked libraries
target_link_libraries(${CMAKE_PROJECT_NAME}
    stm32cubemx
    # Add user defined libraries
    tflm
    cmsis_dsp_frontend
    m
)

add_custom_command(TARGET ${CMAKE_PROJECT_NAME} POST_BUILD
    COMMAND ${CMAKE_OBJCOPY} -O ihex
            $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
            ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_PROJECT_NAME}.hex
    COMMAND ${CMAKE_OBJCOPY} -O binary
            $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
            ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_PROJECT_NAME}.bin
    BYPRODUCTS
            ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_PROJECT_NAME}.hex
            ${CMAKE_CURRENT_BINARY_DIR}/${CMAKE_PROJECT_NAME}.bin
    COMMENT "Generating ${CMAKE_PROJECT_NAME}.hex and ${CMAKE_PROJECT_NAME}.bin"
)
