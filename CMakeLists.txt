# For more information about build system see
# https://docs.espressif.com/projects/esp-idf/en/latest/api-guides/build-system.html
# The following five lines of boilerplate have to be in your project's
# CMakeLists in this exact order for cmake to work correctly
cmake_minimum_required(VERSION 3.16)

set(PROJECT_VER "2.0.5")

# Add this line to disable the specific warning
add_compile_options(-Wno-missing-field-initializers)

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(xiaozhi)

if(NOT IDF_TARGET STREQUAL "esp32s3")
    message(FATAL_ERROR "This firmware supports ESP-BOX-3 / ESP32-S3 only. Run idf.py set-target esp32s3.")
endif()

# 变通：esp_adc/adc_continuous.c 在 xtensa-esp-elf esp-14.2.0 + -Werror=all 下可能因警告报错
# 对 esp_adc 放宽警告即错误，使构建通过
if(TARGET __idf_esp_adc)
    target_compile_options(__idf_esp_adc PRIVATE -Wno-error)
endif()
