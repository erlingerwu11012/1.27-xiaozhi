file(GLOB_RECURSE CUBICAT_HOME_SPINE_SRCS
    "cubicat-port/*.cpp"
    "spine-cpp_4.2/src/spine/*.cpp")

list(APPEND CUBICAT_HOME_SPINE_SRCS "spine_role_preflight.cpp" "${CMAKE_CURRENT_LIST_DIR}/spine_role_preflight.cpp")

idf_component_register(
    SRCS ${CUBICAT_HOME_SPINE_SRCS}
    REQUIRES cubicat_home_engine
    PRIV_REQUIRES esp_psram heap esp_timer esp_hw_support
    INCLUDE_DIRS "." "spine-cpp_4.2/include")

target_compile_options(${COMPONENT_LIB} PRIVATE -O2 -fexceptions -Wno-error=reorder -Wno-error=parentheses)
target_compile_definitions(${COMPONENT_LIB} PRIVATE CONFIG_SPINE_VERSION_42=1)
