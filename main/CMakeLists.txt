# Define source files
set(SOURCES "audio/audio_codec.cc"
            "audio/audio_service.cc"
            "audio/codecs/box_audio_codec.cc"
            "audio/processors/audio_debugger.cc"
            "display/display.cc"
            "display/lcd_display.cc"
            "display/standby_clock.cc"
            "display/home_render_config.cc"
            "display/home_frame_pipeline.cc"
            "display/boot_animation_player.cc"
            "display/cubicat_home_player.cc"
            "display/cubicat_lvgl_overlay.cc"
            "protocols/protocol.cc"
            "protocols/mqtt_protocol.cc"
            "protocols/websocket_protocol.cc"
            "protocols/websocket_connection_gate.cc"
            "mcp_server.cc"
            "mcp_card_action.cc"
            "reminder_coordinator.cc"
            "reminder_voice_service.cc"
            "reminder_control_client.cc"
            "presence_context.cc"
            "identity_client.cc"
            "vision_credentials.cc"
            "reminder_identity_verifier.cc"
            "face_enrollment_client.cc"
            "face_config_store.cc"
            "face_enrollment_manager.cc"
            "face_enrollment_prompt_catalog.cc"
            "face_roster.cc"
            "proactive_wake_coordinator.cc"
            "main_ws_open_arbiter.cc"
            "main_ws_submit_policy.cc"
            "mcp_tools/mcp_tools_device.cc"
            "mcp_tools/mcp_tools_alarm.cc"
            "mcp_tools/mcp_tools_note.cc"
            "mcp_tools/mcp_tools_habit.cc"
            "mcp_tools/mcp_tools_card.cc"
            "mcp_tools/mcp_tools_camera.cc"
            "mcp_tools/mcp_permission.cc"
            "alarm_manager.cc"
            "note_manager.cc"
            "habit_manager.cc"
            "behavior_logger.cc"
            "person_directory.cc"
            "proactive_manager.cc"
            "identity_manager.cc"

            "system_info.cc"
            "task_diagnostics.cc"
            "test_observability.cc"
            "application.cc"
            "ota.cc"
            "auth_connection.cc"
            "ota_tls_diag.cc"
            "settings.cc"
            "device_state_event.cc"
            "assets.cc"
            "mmap_asset_bundle.cc"
            "spine_assets.cc"
            "spine_ota_crypto.cc"
            "spine_ota.cc"
            "wallpaper_assets.cc"
            "wallpaper_ota.cc"
            "touch/touch_manager.cc"
            "touch/gesture_engine.cc"
            "touch/gesture_handler.cc"
            "main.cc"
            )

# 添加驱动头文件路径

set(INCLUDE_DIRS "." "display" "audio" "protocols" "touch" "mcp_tools")

# Add board common files
file(GLOB BOARD_COMMON_SOURCES ${CMAKE_CURRENT_SOURCE_DIR}/boards/common/*.cc)
list(APPEND SOURCES ${BOARD_COMMON_SOURCES})
list(APPEND INCLUDE_DIRS ${CMAKE_CURRENT_SOURCE_DIR}/boards/common)

idf_build_get_property(build_components BUILD_COMPONENTS)
# Function to find component dynamically by pattern
function(find_component_by_pattern PATTERN COMPONENT_VAR PATH_VAR)
    foreach(COMPONENT ${build_components})
        if(COMPONENT MATCHES "${PATTERN}")
            set(${COMPONENT_VAR} ${COMPONENT} PARENT_SCOPE)
            idf_component_get_property(COMPONENT_PATH ${COMPONENT} COMPONENT_DIR)
            set(${PATH_VAR} "${COMPONENT_PATH}" PARENT_SCOPE)
            break()
        endif()
    endforeach()
endfunction()

# Board type: ESP-BOX-3 only (other boards removed)
set(BOARD_TYPE "esp-box-3")

file(GLOB BOARD_SOURCES
    ${CMAKE_CURRENT_SOURCE_DIR}/boards/${BOARD_TYPE}/*.cc
    ${CMAKE_CURRENT_SOURCE_DIR}/boards/${BOARD_TYPE}/*.c
)
list(APPEND SOURCES ${BOARD_SOURCES})

# Select audio processor according to Kconfig
# no_audio_processor is also used as the ESP-BOX-3 listening passthrough path,
# while AFE remains available for wake-word detection.
list(APPEND SOURCES "audio/processors/no_audio_processor.cc")
if(CONFIG_IDF_TARGET_ESP32S3 OR CONFIG_IDF_TARGET_ESP32P4)
    list(APPEND SOURCES "audio/wake_words/afe_wake_word.cc")
    list(APPEND SOURCES "audio/wake_words/custom_wake_word.cc")
endif()

# Select language directory according to Kconfig
if(CONFIG_LANGUAGE_ZH_CN)
    set(LANG_DIR "zh-CN")
elseif(CONFIG_LANGUAGE_ZH_TW)
    set(LANG_DIR "zh-TW")
elseif(CONFIG_LANGUAGE_EN_US)
    set(LANG_DIR "en-US")
elseif(CONFIG_LANGUAGE_JA_JP)
    set(LANG_DIR "ja-JP")
elseif(CONFIG_LANGUAGE_KO_KR)
    set(LANG_DIR "ko-KR")
elseif(CONFIG_LANGUAGE_VI_VN)
    set(LANG_DIR "vi-VN")
elseif(CONFIG_LANGUAGE_TH_TH)
    set(LANG_DIR "th-TH")
elseif(CONFIG_LANGUAGE_DE_DE)
    set(LANG_DIR "de-DE")
elseif(CONFIG_LANGUAGE_FR_FR)
    set(LANG_DIR "fr-FR")
elseif(CONFIG_LANGUAGE_ES_ES)
    set(LANG_DIR "es-ES")
elseif(CONFIG_LANGUAGE_IT_IT)
    set(LANG_DIR "it-IT")
elseif(CONFIG_LANGUAGE_RU_RU)
    set(LANG_DIR "ru-RU")
elseif(CONFIG_LANGUAGE_AR_SA)
    set(LANG_DIR "ar-SA")
elseif(CONFIG_LANGUAGE_HI_IN)
    set(LANG_DIR "hi-IN")
elseif(CONFIG_LANGUAGE_PT_PT)
    set(LANG_DIR "pt-PT")
elseif(CONFIG_LANGUAGE_PL_PL)
    set(LANG_DIR "pl-PL")
elseif(CONFIG_LANGUAGE_CS_CZ)
    set(LANG_DIR "cs-CZ")
elseif(CONFIG_LANGUAGE_FI_FI)
    set(LANG_DIR "fi-FI")
elseif(CONFIG_LANGUAGE_TR_TR)
    set(LANG_DIR "tr-TR")
elseif(CONFIG_LANGUAGE_ID_ID)
    set(LANG_DIR "id-ID")
elseif(CONFIG_LANGUAGE_UK_UA)
    set(LANG_DIR "uk-UA")
elseif(CONFIG_LANGUAGE_RO_RO)
    set(LANG_DIR "ro-RO")
elseif(CONFIG_LANGUAGE_BG_BG)
    set(LANG_DIR "bg-BG")
elseif(CONFIG_LANGUAGE_CA_ES)
    set(LANG_DIR "ca-ES")
elseif(CONFIG_LANGUAGE_DA_DK)
    set(LANG_DIR "da-DK")
elseif(CONFIG_LANGUAGE_EL_GR)
    set(LANG_DIR "el-GR")
elseif(CONFIG_LANGUAGE_FA_IR)
    set(LANG_DIR "fa-IR")
elseif(CONFIG_LANGUAGE_FIL_PH)
    set(LANG_DIR "fil-PH")
elseif(CONFIG_LANGUAGE_HE_IL)
    set(LANG_DIR "he-IL")
elseif(CONFIG_LANGUAGE_HR_HR)
    set(LANG_DIR "hr-HR")
elseif(CONFIG_LANGUAGE_HU_HU)
    set(LANG_DIR "hu-HU")
elseif(CONFIG_LANGUAGE_MS_MY)
    set(LANG_DIR "ms-MY")
elseif(CONFIG_LANGUAGE_NB_NO)
    set(LANG_DIR "nb-NO")
elseif(CONFIG_LANGUAGE_NL_NL)
    set(LANG_DIR "nl-NL")
elseif(CONFIG_LANGUAGE_SK_SK)
    set(LANG_DIR "sk-SK")
elseif(CONFIG_LANGUAGE_SL_SI)
    set(LANG_DIR "sl-SI")
elseif(CONFIG_LANGUAGE_SV_SE)
    set(LANG_DIR "sv-SE")
elseif(CONFIG_LANGUAGE_SR_RS)
    set(LANG_DIR "sr-RS")
endif()

# Define generation path
set(LANG_JSON "${CMAKE_CURRENT_SOURCE_DIR}/assets/locales/${LANG_DIR}/language.json")
set(LANG_HEADER "${CMAKE_CURRENT_SOURCE_DIR}/assets/lang_config.h")

# Collect current language audio files
file(GLOB LANG_SOUNDS ${CMAKE_CURRENT_SOURCE_DIR}/assets/locales/${LANG_DIR}/*.ogg)

# If not en-US, collect en-US audio files as fallback for missing files
if(NOT LANG_DIR STREQUAL "en-US")
    file(GLOB EN_US_SOUNDS ${CMAKE_CURRENT_SOURCE_DIR}/assets/locales/en-US/*.ogg)
    
    # Extract filenames (without path) from current language
    set(EXISTING_NAMES "")
    foreach(SOUND_FILE ${LANG_SOUNDS})
        get_filename_component(FILENAME ${SOUND_FILE} NAME)
        list(APPEND EXISTING_NAMES ${FILENAME})
    endforeach()
    
    # Only add en-US audio files that are missing in current language
    foreach(EN_SOUND ${EN_US_SOUNDS})
        get_filename_component(FILENAME ${EN_SOUND} NAME)
        if(NOT ${FILENAME} IN_LIST EXISTING_NAMES)
            list(APPEND LANG_SOUNDS ${EN_SOUND})
            message(STATUS "Using en-US fallback for missing audio: ${FILENAME}")
        endif()
    endforeach()
endif()

file(GLOB COMMON_SOUNDS ${CMAKE_CURRENT_SOURCE_DIR}/assets/common/*.ogg)
# Product-owned guided enrollment prompts.  These Ogg-container Opus files are
# embedded alongside existing local sound assets and are never fetched from the
# service.
file(GLOB FACE_ENROLLMENT_SOUNDS
          ${CMAKE_CURRENT_SOURCE_DIR}/assets/face_enrollment/*.ogg)

# ==============================================================================


idf_component_register(
    SRCS ${SOURCES}
    EMBED_FILES ${LANG_SOUNDS} ${COMMON_SOUNDS} ${FACE_ENROLLMENT_SOUNDS}
    
    # 保持原有的 INCLUDE_DIRS
    INCLUDE_DIRS ${INCLUDE_DIRS}
    
    WHOLE_ARCHIVE
    PRIV_REQUIRES 
        # 蓝牙已改为 SoftAP 配网，不再需要 bt 组件
        # esp_hid 
        # bt
        # 系统与内存
        esp_psram 
        esp_timer 
        esp_event 
        esp_system
        esp_driver_usb_serial_jtag
        efuse
        # OTA 与 分区
        app_update 
        esp_app_format 
        esp_partition 
        spi_flash  
        # 存储与配置
        nvs_flash 
        # 网络相关
        esp_http_client 
        esp_wifi 
        esp_netif 
        lwip 
        mqtt
        # wifi_provisioning 已改用 esp-wifi-connect WifiConfigurationAp（含 captive portal）
        # wifi_provisioning
        protocomm 
        # 硬件驱动
        driver 
        esp_lcd
        # 工具库
        json 
        log
        mbedtls
        cubicat_home_engine
        cubicat_home_spine
        lvgl
        xiaozhi-fonts
)
# Use target_compile_definitions to define BOARD_TYPE, BOARD_NAME
# If BOARD_NAME is empty, use BOARD_TYPE
if(NOT BOARD_NAME)
    set(BOARD_NAME ${BOARD_TYPE})
endif()
target_compile_definitions(${COMPONENT_LIB}
                    PRIVATE BOARD_TYPE=\"${BOARD_TYPE}\" BOARD_NAME=\"${BOARD_NAME}\"
                    )
target_compile_options(${COMPONENT_LIB} PRIVATE -fexceptions -Wno-error=parentheses)

if(CONFIG_USE_USB_STREAM)
    target_link_options(${COMPONENT_LIB} INTERFACE
        "-Wl,--wrap=jpeg_calloc"
        "-Wl,--wrap=jpeg_calloc_inner"
        "-Wl,--wrap=jpeg_calloc_align"
        "-Wl,--wrap=jpeg_calloc_align_inner")
endif()

# Add generation rules
add_custom_command(
    OUTPUT ${LANG_HEADER}
    COMMAND python ${PROJECT_DIR}/scripts/gen_lang.py
            --language "${LANG_DIR}"
            --output "${LANG_HEADER}"
    DEPENDS
        ${LANG_JSON}
        ${LANG_SOUNDS}
        ${COMMON_SOUNDS}
        ${PROJECT_DIR}/scripts/gen_lang.py
    COMMENT "Generating ${LANG_DIR} language config"
)

# Force build generation dependencies
add_custom_target(lang_header ALL
    DEPENDS ${LANG_HEADER}
)

# Find ESP-SR component dynamically
find_component_by_pattern("espressif__esp-sr" ESP_SR_COMPONENT ESP_SR_COMPONENT_PATH)
if(ESP_SR_COMPONENT_PATH)
    set(ESP_SR_MODEL_PATH "${ESP_SR_COMPONENT_PATH}/model")
endif()

# The factory Spine role is a fixed part of assets, alongside room.png. Online
# role updates go only to the separate single-slot "spine" partition.
set(CUBICAT_SPINE_ASSETS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_spine_default_42/skeleton.skel"
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_spine_default_42/skeleton.atlas"
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_spine_default_42/texture.png"
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_spine_default_42/role.json")

file(GLOB_RECURSE CUBICAT_HOME_ASSETS CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_home/*")

# Function to build default assets based on configuration
function(build_default_assets_bin)
    # Set output path for generated assets.bin
    set(GENERATED_ASSETS_BIN "${CMAKE_BINARY_DIR}/generated_assets.bin")
    
    # Prepare arguments for build script
    set(BUILD_ARGS
        "--sdkconfig" "${SDKCONFIG}"
        "--output" "${GENERATED_ASSETS_BIN}"
    )
    
    # Add default assets extra files if defined
    if(DEFAULT_ASSETS_EXTRA_FILES)
        list(APPEND BUILD_ARGS "--extra_files" "${DEFAULT_ASSETS_EXTRA_FILES}")
    endif()
    # Factory UI, room.png and the default Spine role all stay in assets.
    list(APPEND BUILD_ARGS "--extra_files" "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_home")
    list(APPEND BUILD_ARGS "--extra_files" "${CMAKE_CURRENT_SOURCE_DIR}/assets/cubicat_spine_default_42")
    
    list(APPEND BUILD_ARGS "--esp_sr_model_path" "${ESP_SR_MODEL_PATH}")
    # Map font_puhui_basic_* -> font_puhui_common_*.bin into assets for cbin_font.
    list(APPEND BUILD_ARGS "--builtin_text_font" "font_puhui_basic_20_4")
    find_component_by_pattern("xiaozhi-fonts" XIAOZHI_FONTS_COMPONENT XIAOZHI_FONTS_PATH)
    if(XIAOZHI_FONTS_PATH)
        list(APPEND BUILD_ARGS "--xiaozhi_fonts_path" "${XIAOZHI_FONTS_PATH}")
        # Keep the main UI at 20px, while the bottom subtitle dock uses a
        # compact 16px CJK font from the same mmap assets bundle.
        list(APPEND BUILD_ARGS "--extra_files"
             "${XIAOZHI_FONTS_PATH}/cbin/font_puhui_common_16_4.bin")
    endif()
    # Create custom command to build assets
    add_custom_command(
        OUTPUT ${GENERATED_ASSETS_BIN}
        COMMAND python ${PROJECT_DIR}/scripts/build_default_assets.py ${BUILD_ARGS}
        DEPENDS
            ${SDKCONFIG}
            ${PROJECT_DIR}/scripts/build_default_assets.py
            ${CUBICAT_HOME_ASSETS}
            ${CUBICAT_SPINE_ASSETS}
        COMMENT "Building default assets.bin based on configuration"
        VERBATIM
    )
    
    # Create target for generated assets
    add_custom_target(generated_default_assets ALL
        DEPENDS ${GENERATED_ASSETS_BIN}
    )
    
    # Set the generated file path in parent scope
    set(GENERATED_ASSETS_LOCAL_FILE ${GENERATED_ASSETS_BIN} PARENT_SCOPE)
    
    message(STATUS "Default assets build configured: ${GENERATED_ASSETS_BIN}")
endfunction()

# Function to get local assets file path (handles both URL and local file)
function(get_assets_local_file assets_source assets_local_file_var)
    # Check if it's a URL (starts with http:// or https://)
    if(assets_source MATCHES "^https?://")
        # It's a URL, download it
        get_filename_component(ASSETS_FILENAME "${assets_source}" NAME)
        set(ASSETS_LOCAL_FILE "${CMAKE_BINARY_DIR}/${ASSETS_FILENAME}")
        set(ASSETS_TEMP_FILE "${CMAKE_BINARY_DIR}/${ASSETS_FILENAME}.tmp")
        
        # Check if local file exists
        if(EXISTS ${ASSETS_LOCAL_FILE})
            message(STATUS "Assets file ${ASSETS_FILENAME} already exists, skipping download")
        else()
            message(STATUS "Downloading ${ASSETS_FILENAME}")
            
            # Clean up any existing temp file
            if(EXISTS ${ASSETS_TEMP_FILE})
                file(REMOVE ${ASSETS_TEMP_FILE})
            endif()
            
            # Download to temporary file first
            file(DOWNLOAD ${assets_source} ${ASSETS_TEMP_FILE}
                 STATUS DOWNLOAD_STATUS)
            list(GET DOWNLOAD_STATUS 0 STATUS_CODE)
            if(NOT STATUS_CODE EQUAL 0)
                # Clean up temp file on failure
                if(EXISTS ${ASSETS_TEMP_FILE})
                    file(REMOVE ${ASSETS_TEMP_FILE})
                endif()
                message(FATAL_ERROR "Failed to download ${ASSETS_FILENAME} from ${assets_source}")
            endif()
            
            # Move temp file to final location (atomic operation)
            file(RENAME ${ASSETS_TEMP_FILE} ${ASSETS_LOCAL_FILE})
            message(STATUS "Successfully downloaded ${ASSETS_FILENAME}")
        endif()
    else()
        # It's a local file path
        if(IS_ABSOLUTE "${assets_source}")
            set(ASSETS_LOCAL_FILE "${assets_source}")
        else()
            set(ASSETS_LOCAL_FILE "${CMAKE_CURRENT_SOURCE_DIR}/${assets_source}")
        endif()
        
        # Check if local file exists
        if(NOT EXISTS ${ASSETS_LOCAL_FILE})
            message(FATAL_ERROR "Assets file not found: ${ASSETS_LOCAL_FILE}")
        endif()
        
        message(STATUS "Using assets file: ${ASSETS_LOCAL_FILE}")
    endif()
    
    set(${assets_local_file_var} ${ASSETS_LOCAL_FILE} PARENT_SCOPE)
endfunction()


partition_table_get_partition_info(size "--partition-name assets" "size")
partition_table_get_partition_info(offset "--partition-name assets" "offset")
if ("${size}" AND "${offset}")
    # Flash assets based on configuration
    if(CONFIG_FLASH_DEFAULT_ASSETS)
        # Build default assets based on configuration
        build_default_assets_bin()
        esptool_py_flash_to_partition(flash "assets" "${GENERATED_ASSETS_LOCAL_FILE}")
        message(STATUS "Generated default assets flash configured: ${GENERATED_ASSETS_LOCAL_FILE} -> assets partition")
    elseif(CONFIG_FLASH_CUSTOM_ASSETS)
        # Flash custom assets
        get_assets_local_file("${CONFIG_CUSTOM_ASSETS_FILE}" ASSETS_LOCAL_FILE)
        esptool_py_flash_to_partition(flash "assets" "${ASSETS_LOCAL_FILE}")
        message(STATUS "Custom assets flash configured: ${ASSETS_LOCAL_FILE} -> assets partition")
    elseif(CONFIG_FLASH_NONE_ASSETS)
        message(STATUS "Assets flashing disabled (FLASH_NONE_ASSETS)")
    endif()
else()
    message(STATUS "Assets partition not found, using v1 partition table")
endif()

# "spine" and "wallpaper" are intentionally left blank at factory. Their
# valid online packages override the factory assets after a reboot.
partition_table_get_partition_info(SPINE_SIZE "--partition-name spine" "size")
partition_table_get_partition_info(WALLPAPER_SIZE "--partition-name wallpaper" "size")
if(NOT "${SPINE_SIZE}" OR NOT "${WALLPAPER_SIZE}")
    message(FATAL_ERROR "single-slot spine/wallpaper OTA partitions missing; use partitions/v2/16m.csv and full USB flash")
endif()
