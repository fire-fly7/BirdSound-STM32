set(CMAKE_SYSTEM_NAME               Generic)
set(CMAKE_SYSTEM_PROCESSOR          arm)

set(CMAKE_C_COMPILER_ID GNU)
set(CMAKE_CXX_COMPILER_ID GNU)

# By default, resolve arm-none-eabi-* from PATH.  A portable/toolchain archive
# installation can instead be selected without changing PATH:
#
#   ARM_GNU_TOOLCHAIN_ROOT=/opt/arm-gnu-toolchain-14.2.rel1 \
#     cmake --preset release
#
set(ARM_GNU_TOOLCHAIN_ROOT "" CACHE PATH
    "Arm GNU Toolchain root containing bin/arm-none-eabi-gcc")

if(NOT ARM_GNU_TOOLCHAIN_ROOT AND DEFINED ENV{ARM_GNU_TOOLCHAIN_ROOT})
    file(TO_CMAKE_PATH "$ENV{ARM_GNU_TOOLCHAIN_ROOT}" ARM_GNU_TOOLCHAIN_ROOT)
endif()

if(ARM_GNU_TOOLCHAIN_ROOT)
    set(TOOLCHAIN_PREFIX "${ARM_GNU_TOOLCHAIN_ROOT}/bin/arm-none-eabi-")
else()
    find_program(ARM_NONE_EABI_GCC NAMES arm-none-eabi-gcc)
    if(NOT ARM_NONE_EABI_GCC)
        message(FATAL_ERROR
            "arm-none-eabi-gcc was not found. Add the Arm GNU Toolchain bin "
            "directory to PATH or set ARM_GNU_TOOLCHAIN_ROOT.")
    endif()
    get_filename_component(ARM_NONE_EABI_BIN_DIR "${ARM_NONE_EABI_GCC}" DIRECTORY)
    set(TOOLCHAIN_PREFIX "${ARM_NONE_EABI_BIN_DIR}/arm-none-eabi-")
endif()

foreach(TOOL gcc g++ objcopy size)
    if(NOT EXISTS "${TOOLCHAIN_PREFIX}${TOOL}")
        message(FATAL_ERROR "Missing required tool: ${TOOLCHAIN_PREFIX}${TOOL}")
    endif()
endforeach()

set(CMAKE_C_COMPILER                "${TOOLCHAIN_PREFIX}gcc")
set(CMAKE_ASM_COMPILER              "${CMAKE_C_COMPILER}")
set(CMAKE_CXX_COMPILER              "${TOOLCHAIN_PREFIX}g++")
set(CMAKE_LINKER                    "${TOOLCHAIN_PREFIX}g++")
set(CMAKE_OBJCOPY                   "${TOOLCHAIN_PREFIX}objcopy")
set(CMAKE_SIZE                      "${TOOLCHAIN_PREFIX}size")

set(CMAKE_EXECUTABLE_SUFFIX_ASM     ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_C       ".elf")
set(CMAKE_EXECUTABLE_SUFFIX_CXX     ".elf")

set(CMAKE_TRY_COMPILE_TARGET_TYPE STATIC_LIBRARY)

# MCU specific flags
set(TARGET_FLAGS "-mcpu=cortex-m33 -mfpu=fpv4-sp-d16 -mfloat-abi=hard ")

set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} ${TARGET_FLAGS}")
set(CMAKE_ASM_FLAGS "${CMAKE_C_FLAGS} -x assembler-with-cpp -MMD -MP")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -Wall -Wextra -Wpedantic -fdata-sections -ffunction-sections")

set(CMAKE_C_FLAGS_DEBUG "-O0 -g3")
set(CMAKE_C_FLAGS_RELEASE "-Os -g0")
set(CMAKE_CXX_FLAGS_DEBUG "-O0 -g3")
set(CMAKE_CXX_FLAGS_RELEASE "-Os -g0")

set(CMAKE_CXX_FLAGS "${CMAKE_C_FLAGS} -fno-rtti -fno-exceptions -fno-threadsafe-statics")

set(CMAKE_C_LINK_FLAGS "${TARGET_FLAGS}")
set(CMAKE_C_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} -T \"${CMAKE_SOURCE_DIR}/STM32L552xE_FLASH.ld\"")
set(CMAKE_C_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} --specs=nano.specs")
set(CMAKE_C_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} -Wl,-Map=${CMAKE_PROJECT_NAME}.map -Wl,--gc-sections")
set(CMAKE_C_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} -Wl,--start-group -lc -lm -Wl,--end-group")
set(CMAKE_C_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} -Wl,--print-memory-usage")

set(CMAKE_CXX_LINK_FLAGS "${CMAKE_C_LINK_FLAGS} -Wl,--start-group -lstdc++ -lsupc++ -Wl,--end-group")
