#include "home_render_config.h"
#include "utils/home_render_options.h"
#include "settings.h"
#include "esp_log.h"
#include "esp_heap_caps.h"
#include <mutex>
namespace {
std::once_flag initialized;
}
void InitializeHomeRenderConfig() {
    std::call_once(initialized, [] {
        Settings settings("render_diag");
        const auto selected = settings.GetString("mode", "combined");
        cubicat::HomeRenderMode mode = cubicat::HomeRenderMode::Combined;
        if (!cubicat::ParseHomeRenderMode(selected.c_str(), mode))
            ESP_LOGW("RenderConfig", "Invalid saved mode; use combined");
        cubicat::ConfigureHomeRenderMode(mode);
        auto options = settings.GetString("options", "v2:30:1");
        if (options != "v1:30:0" && options != "v1:30:1" &&
            options != "v1:40:0" && options != "v1:40:1" &&
            options != "v2:30:0" && options != "v2:30:1" &&
            options != "v2:40:0" && options != "v2:40:1") {
            ESP_LOGW("RenderConfig", "Invalid saved options; use v2:30:1");
            options = "v2:30:1";
        }
        const auto profile = options.substr(0, 2);
        const int mhz = options.size() == 7 && options.substr(3, 2) == "40" ? 40 : 30;
        cubicat::ConfigureHomeRenderOptions(
            profile == "v1" ? cubicat::HomeRenderProfile::V1 : cubicat::HomeRenderProfile::V2,
            mhz, options.size() == 7 ? options[6] == '1' : true);
        ESP_LOGI("RenderConfig", "[RENDERMODE] mode=%s profile=%s filter=preserve lcd_spi_hz=%u pixel_diff_requested=%d",
                 cubicat::HomeRenderModeName(mode),
                 cubicat::HomeRenderProfileName(cubicat::GetHomeRenderProfile()),
                 unsigned(cubicat::HomeLcdSpiMHz() * 1000000), cubicat::HomePixelDiffRequested());
    });
}
bool SaveHomeRenderMode(const std::string &name, std::string &error) {
    cubicat::HomeRenderMode mode;
    if (!cubicat::ParseHomeRenderMode(name.c_str(), mode)) {
        error = "mode must be baseline, render, pipeline, dual or combined";
        return false;
    }
    Settings settings("render_diag", true);
    auto result = settings.SetString("mode", name);
    if (result == ESP_OK)
        result = settings.Commit();
    if (result != ESP_OK) {
        error = "failed to persist render mode";
        return false;
    }
    return true;
}
bool SaveHomeRenderOptions(const std::string &profile, int spi_mhz, bool pixel_diff,
                           std::string &error) {
    if ((profile != "v1" && profile != "v2") || (spi_mhz != 30 && spi_mhz != 40)) {
        error = "profile must be v1/v2 and spi_mhz must be 30/40";
        return false;
    }
    Settings settings("render_diag", true);
    // One serialized value publishes all three fields together.
    const std::string value = profile + ":" + std::to_string(spi_mhz) + ":" + (pixel_diff ? "1" : "0");
    auto result = settings.SetString("options", value);
    if (result == ESP_OK) result = settings.Commit();
    if (result != ESP_OK) {
        error = "failed to persist render options";
        return false;
    }
    return true;
}
cJSON *HomeRenderStatusJson() {
    auto s = cubicat::GetHomeRenderStatus();
    Settings settings("render_diag");
    auto selected = settings.GetString("mode", "combined");
    cJSON *out = cJSON_CreateObject();
    cJSON_AddStringToObject(out, "mode", cubicat::HomeRenderModeName(s.mode));
    cJSON_AddStringToObject(out, "next_boot_mode", selected.c_str());
    cJSON_AddStringToObject(out, "profile", cubicat::HomeRenderProfileName(s.profile));
    const auto options = settings.GetString("options", "v2:30:1");
    cJSON_AddStringToObject(out, "next_boot_options", options.c_str());
    cJSON_AddStringToObject(out, "next_boot_profile", options.substr(0, 2).c_str());
    cJSON_AddNumberToObject(out, "next_boot_spi_mhz", options.size() == 7 && options.substr(3, 2) == "40" ? 40 : 30);
    cJSON_AddBoolToObject(out, "next_boot_pixel_diff", options.size() == 7 && options[6] == '1');
    cJSON_AddNumberToObject(out, "lcd_spi_mhz", s.spi_mhz);
    cJSON_AddBoolToObject(out, "stream_enabled", s.stream_enabled);
    cJSON_AddStringToObject(out, "stream_reason", s.stream_reason);
    cJSON_AddBoolToObject(out, "pixel_diff_enabled", s.pixel_diff_enabled);
    cJSON_AddStringToObject(out, "pixel_diff_reason", s.pixel_diff_reason);
    cJSON_AddBoolToObject(out, "optimized_drawing", s.optimized_enabled);
    cJSON_AddBoolToObject(out, "dual_enabled", s.dual_enabled);
    cJSON_AddBoolToObject(out, "pipeline_enabled", s.pipeline_enabled);
    cJSON_AddStringToObject(out, "drawing_reason", s.drawing_reason);
    cJSON_AddNumberToObject(out, "fallback_count", s.fallback_count);
    cJSON_AddNumberToObject(out, "core0_share_pct", s.core0_share_pct);
    cJSON_AddStringToObject(out, "dual_reason", s.dual_reason);
    cJSON_AddStringToObject(out, "pipeline_reason", s.pipeline_reason);
    cJSON_AddNumberToObject(out, "raster_stack_free", s.raster_stack_free);
    cJSON_AddNumberToObject(out, "lcd_stack_free", s.lcd_stack_free);
    cJSON_AddNumberToObject(out, "internal_free", heap_caps_get_free_size(MALLOC_CAP_INTERNAL));
    cJSON_AddNumberToObject(out, "psram_free", heap_caps_get_free_size(MALLOC_CAP_SPIRAM));
    cJSON_AddStringToObject(out, "filter", "preserve");
    return out;
}
