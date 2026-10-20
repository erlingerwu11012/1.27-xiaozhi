file(GLOB_RECURSE CUBICAT_HOME_ENGINE_SRCS
    "core/*.cpp"
    "graphic_engine/*.cpp"
    "utils/*.cpp")

file(GLOB CUBICAT_LIBPNG_SRCS "graphic_engine/3rd_party/libpng/*.c")
file(GLOB CUBICAT_ZLIB_SRCS "graphic_engine/3rd_party/zlib/*.c")
list(APPEND CUBICAT_HOME_ENGINE_SRCS
    ${CUBICAT_LIBPNG_SRCS}
    ${CUBICAT_ZLIB_SRCS})

# The ESP32 implementation only supplies PSRAM-aware allocators. It does not
# initialize a panel or any Cubicat board peripheral.
list(APPEND CUBICAT_HOME_ENGINE_SRCS
    "esp_helper.c"
    "esp_memory_allocator.c")

idf_component_register(
    SRCS ${CUBICAT_HOME_ENGINE_SRCS}
    PRIV_REQUIRES esp_psram heap esp_timer esp_hw_support
    INCLUDE_DIRS "." "graphic_engine/3rd_party" "graphic_engine/3rd_party/zlib")

# The Home renderer is a CPU-bound software rasterizer. Keep the rest of the
# firmware size-optimized, but build this isolated hot path for throughput.
target_compile_options(${COMPONENT_LIB} PRIVATE
    -O2
    -fexceptions
    -Wno-error=reorder
    -Wno-error=maybe-uninitialized)
target_compile_definitions(${COMPONENT_LIB} PRIVATE
    PPM_SUPPORTED HAVE_MATH_H HAVE_CTYPE_H HAVE_UNISTD_H HAVE_ERRNO_H)
