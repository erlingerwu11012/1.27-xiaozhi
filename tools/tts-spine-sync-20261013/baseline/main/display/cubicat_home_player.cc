#include "cubicat_home_player.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <mutex>
#include <string>
#include <vector>

#include "application.h"
#include "assets.h"
#include "cubicat_lvgl_overlay.h"
#include "device_state.h"
#include "spine_assets.h"
#include "wallpaper_assets.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "mcp_card.h"
#include "mcp_card_layout.h"

#include "cubicat-port/spine_extension.h"
#include "cubicat-port/spine_node.h"
#include "cubicat-port/texture_loader.h"
#include "graphic_engine/drawable/texture.h"
#include "graphic_engine/embed_game_engine.h"
#include "graphic_engine/resource_manager.h"
#include "graphic_engine/renderer/renderer.h"
#include "utils/home_perf.h"
#include "utils/home_render_options.h"
#include "graphic_engine/widgets/text_label.h"

namespace {
constexpr const char* kTag = "CubicatHome";
constexpr int kTargetFps = 30;
constexpr int kReferenceSceneHeight = 240;
// Latest nvhai export already has 1.3x scale in its upper "bone".
// Do not apply the previous additional 1.3x display scale again.
// Reference right coat/table junction: screen (273,268).
// The latest sleeve pose differs from the old parent-scale-only estimate.
// Photo calibration (2026-10-13): move left 5 px and screen-up 3 px.
// Cubicat world Y points up: node origin (170.764,42.510) on 320x320.
// Keep the authored size; confirm the contact point after flashing.
constexpr float kSpineDisplayScale = 1.0f;
constexpr float kSpinePositionOffsetX = 10.764f;
constexpr float kSpinePositionOffsetY = 2.510f;
constexpr int kCardWidth = mcp_card_layout::kWidth;
// 320x320: summary y=64..180, expanded y=42..250, bottom safe >=50px.
constexpr int kCardSummaryHeight = mcp_card_layout::kSummaryHeight;
constexpr int kCardExpandedHeight = mcp_card_layout::kExpandedHeight;
constexpr int kCardSummaryTop = 64;
constexpr int kCardExpandedTop = 42;
constexpr int kCardBottomInset = 50;
constexpr int kCardTopMargin = 28;
constexpr int64_t kHomePerfLogIntervalUs = 30 * 1000 * 1000;
// Conversation state is conveyed by the character and subtitle dock.  Do not
// add a separate animated line/dot/bar indicator on top of that UI.
constexpr bool kEnableNativeText = true;
constexpr bool kEnableStatusIcons = true;
constexpr bool kEnableMcpCard = true;

constexpr int kDialogueW = 296;
// Conversation subtitles are a low-profile bottom dock, not a reminder card.
constexpr int kDialogueH = 28;
constexpr int kDialogueX = 12;
constexpr int kDialogueShownY = 284;
constexpr int kDialogueHiddenY = 326;
constexpr int kDialogueSlideInMs = 280;
constexpr int kDialogueSlideOutMs = 220;
constexpr int kDialogueHideDelayMs = 800;
constexpr int kDialogueTextViewportW = 226;
constexpr uint32_t kDialogueScrollDelayMs = 700;
constexpr uint32_t kDialogueScrollFrameMs = 100;
constexpr int kDialogueScrollStepPx = 2;
constexpr uint32_t kDialogueScrollEndPauseMs = 1600;

constexpr int kStatusIconSize = 20;
constexpr int kStatusIconGap = 4;
constexpr int kStatusIconY = 12;

float EaseOutCubic(float t) {
    float u = 1.0f - t;
    return 1.0f - u * u * u;
}

float EaseInCubic(float t) {
    return t * t * t;
}

void LogHomeInitStage(const char* stage) {
    ESP_LOGI(
        kTag,
        "[HOMEINIT] stage=%s sram_free=%u sram_largest=%u "
        "psram_free=%u psram_largest=%u",
        stage,
        static_cast<unsigned>(
            heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
        static_cast<unsigned>(
            heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)),
        static_cast<unsigned>(
            heap_caps_get_free_size(MALLOC_CAP_SPIRAM)),
        static_cast<unsigned>(
            heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM)));
}

uint16_t Rgb565(uint8_t red, uint8_t green, uint8_t blue) {
    return static_cast<uint16_t>(
        ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3));
}

std::string Safe(const char* value) {
    return value == nullptr ? std::string() : std::string(value);
}

std::string SingleLineText(const std::string& text) {
    // Provisioning instructions and other notifications can contain several
    // lines. Preserve every word in the single-line scrolling viewport.
    std::string out;
    out.reserve(text.size());
    bool pending_space = false;
    for (char ch : text) {
        if (ch == '\n' || ch == '\r' || ch == '\t' || ch == ' ') {
            pending_space = !out.empty();
            continue;
        }
        if (pending_space) out += ' ';
        out += ch;
        pending_space = false;
    }
    return out;
}


std::vector<std::string> Utf8Characters(const std::string& text) {
    std::vector<std::string> characters;
    const char* cursor = text.c_str();
    const char* end = cursor + text.size();
    while (cursor < end) {
        const uint8_t lead = static_cast<uint8_t>(*cursor);
        size_t length = 1;
        if ((lead & 0xE0) == 0xC0) length = 2;
        else if ((lead & 0xF0) == 0xE0) length = 3;
        else if ((lead & 0xF8) == 0xF0) length = 4;
        if (cursor + length > end) {
            characters.emplace_back("\xEF\xBF\xBD");  // U+FFFD
            break;
        }
        characters.emplace_back(cursor, length);
        cursor += length;
    }
    return characters;
}

// Single-pass UTF-8 safe wrapping. Does NOT re-wrap already-wrapped output.
std::string WrapText(const std::string& text,
                     size_t columns,
                     size_t max_lines,
                     bool ellipsis) {
    if (text.empty() || columns == 0 || max_lines == 0) return "";
    if (max_lines > 10) max_lines = 10;

    size_t line = 0;
    size_t col = 0;
    size_t total_chars = 0;

    const auto characters = Utf8Characters(text);
    size_t index = 0;
    for (; index < characters.size() && line < max_lines; ++index) {
        const auto& ch = characters[index];
        if (ch == "\n") {
            if (line + 1 >= max_lines) {
                break;
            }
            line++;
            col = 0;
            total_chars++;
            continue;
        }
        if (col >= columns) {
            if (line + 1 >= max_lines) {
                break;
            }
            line++;
            col = 0;
        }
        col++;
        total_chars++;
    }

    // If we stopped before consuming all characters, truncation happened
    const bool truncated = (index < characters.size());

    // Build output from first `index` characters
    std::string out;
    for (size_t i = 0; i < index; ++i) {
        out += characters[i];
        if (i < index - 1 && characters[i] == "\n") {
            // natural newline preserved
        }
    }

    // Remove trailing newline chars if they make a blank line
    while (!out.empty()) {
        const auto last_chars = out.substr(
            out.size() >= 3 ? out.size() - 3 : 0);
        bool is_newline = false;
        if (!out.empty()) {
            const size_t sz = out.size();
            // Check for UTF-8 encoded \n which is a single byte 0x0A
            if (out.back() == '\n') {
                out.pop_back();
                is_newline = true;
            } else if (sz >= 3 &&
                       static_cast<uint8_t>(out[sz - 3]) == 0xE2 &&
                       static_cast<uint8_t>(out[sz - 2]) == 0x80 &&
                       static_cast<uint8_t>(out[sz - 1]) == 0xA6) {
                // ellipsis at end, don't strip
                break;
            } else if (sz >= 1 &&
                       (static_cast<uint8_t>(out.back()) & 0xC0) == 0x80) {
                // mid-codepoint, strip continuation bytes
                while (!out.empty() &&
                       (static_cast<uint8_t>(out.back()) & 0xC0) == 0x80) {
                    out.pop_back();
                }
                if (!out.empty()) out.pop_back();
                continue;
            } else {
                break;
            }
        }
        if (!is_newline) break;
    }

    if (ellipsis && truncated && !out.empty()) {
        out += "\xE2\x80\xA6";  // U+2026 HORIZONTAL ELLIPSIS
    }
    return out;
}

ImageData g_spine_image{};

const ImageData& GetSpineImage(const char*) {
    return g_spine_image;
}

class NativeSurface final : public cubicat::DisplayInterface,
                            public cubicat::DrawStageListener {
public:
    uint16_t* pixels = nullptr;
    int width = 0;
    int height = 0;
    CubicatHomePlayer::FrameSubmitter submitter;

    cubicat::RenderBuffer getRenderBuffer() override {
        return {pixels, static_cast<uint16_t>(width),
                static_cast<uint16_t>(height)};
    }

    uint16_t getBackgroundColor() override {
        return Rgb565(32, 25, 20);
    }

    void onDrawStart(const Region&) override {}

    void onDrawFinish(const Region& dirty_region) override {
        if (!dirty_region.valid() || pixels == nullptr) return;

        const int x1 = std::max(0, static_cast<int>(dirty_region.x));
        const int y1 = std::max(0, static_cast<int>(dirty_region.y));
        const int x2 = std::min(
            width, static_cast<int>(dirty_region.x) + dirty_region.w);
        const int y2 = std::min(
            height, static_cast<int>(dirty_region.y) + dirty_region.h);
        if (x2 <= x1 || y2 <= y1) return;

        if (!pending_dirty_) {
            pending_x1_ = x1;
            pending_y1_ = y1;
            pending_x2_ = x2;
            pending_y2_ = y2;
            pending_dirty_ = true;
            return;
        }
        pending_x1_ = std::min(pending_x1_, x1);
        pending_y1_ = std::min(pending_y1_, y1);
        pending_x2_ = std::max(pending_x2_, x2);
        pending_y2_ = std::max(pending_y2_, y2);
    }

    bool Present() {
        const bool recovery=cubicat::HomeLcdRecoveryRequested();
        if (!pending_dirty_ && !recovery) return true;
        if (pixels == nullptr || !submitter) return false;

        int submit_x1 = pending_x1_;
        int submit_y1 = pending_y1_;
        int submit_x2 = pending_x2_;
        int submit_y2 = pending_y2_;
        if (!first_frame_submitted_ || recovery) {
            // The framebuffer starts cleared, then the engine draws the first
            // scene.  Commit the whole surface once so the backlight is never
            // revealed while GRAM still contains the panel's reset contents.
            submit_x1 = 0;
            submit_y1 = 0;
            submit_x2 = width;
            submit_y2 = height;
        }

        const int64_t start = esp_timer_get_time();
        const bool submitted = submitter(
            pixels, width,
            submit_x1, submit_y1, submit_x2, submit_y2, !first_frame_submitted_ || recovery);
        const int64_t elapsed = esp_timer_get_time() - start;
        if (!submitted) {
            ESP_LOGW(kTag, "Native dirty frame submission failed");
            return false;
        }
        first_frame_submitted_ = true;
        frame_count++;
        dirty_pixels += static_cast<uint32_t>(
            (submit_x2 - submit_x1) * (submit_y2 - submit_y1));
        spi_time_us += static_cast<uint64_t>(elapsed);
        pending_dirty_ = false;
        return true;
    }

    bool PresentFullFrame() {
        if (pixels == nullptr || !submitter) return false;
        const int64_t start = esp_timer_get_time();
        const bool submitted = submitter(
            pixels, width, 0, 0, width, height, true);
        if (!submitted) {
            ESP_LOGW(kTag, "Native full frame submission failed");
            return false;
        }
        first_frame_submitted_ = true;
        frame_count++;
        dirty_pixels += static_cast<uint32_t>(width * height);
        spi_time_us += static_cast<uint64_t>(esp_timer_get_time() - start);
        pending_dirty_ = false;
        return true;
    }

    void ResetStats() {
        frame_count = 0;
        dirty_pixels = 0;
        spi_time_us = 0;
    }

    uint32_t frame_count = 0;
    uint64_t dirty_pixels = 0;
    uint64_t spi_time_us = 0;

private:
    bool first_frame_submitted_ = false;
    bool pending_dirty_ = false;
    int pending_x1_ = 0;
    int pending_y1_ = 0;
    int pending_x2_ = 0;
    int pending_y2_ = 0;
};

cubicat::TexturePtr MakeTransparentTexture(int width, int height) {
    auto* pixels = static_cast<uint32_t*>(
        heap_caps_malloc(static_cast<size_t>(width) * height * sizeof(uint32_t),
                         MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (pixels == nullptr) return cubicat::TexturePtr();
    std::memset(pixels, 0,
                static_cast<size_t>(width) * height * sizeof(uint32_t));
    return cubicat::Texture::create(
        width, height, pixels, true, 1, 1, nullptr, 32, true);
}
}  // namespace

extern "C" char* cubicat_home_read_asset(const char* name, int* length) {
    if (name == nullptr || length == nullptr) return nullptr;

    void* source = nullptr;
    size_t size = 0;
    // Spine skel/atlas are read only from the active spine_* partition.
    if (!SpineAssets::GetInstance().GetAssetData(name, source, size) ||
        source == nullptr || size == 0) {
        ESP_LOGE(kTag, "Missing Spine asset in active role slot: %s", name);
        return nullptr;
    }

    auto* copy = static_cast<char*>(
        heap_caps_malloc(size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (copy == nullptr) {
        ESP_LOGE(kTag, "No PSRAM for Spine asset: %s", name);
        return nullptr;
    }
    std::memcpy(copy, source, size);
    *length = static_cast<int>(size);
    ESP_LOGI(kTag, "Asset read: %s (%u bytes)",
             name, static_cast<unsigned>(size));
    return copy;
}

class CubicatHomePlayer::Impl {
public:
    enum class DialoguePhase {
        Hidden,
        Showing,
        Shown,
        Hiding,
    };

    struct TouchSnapshot {
        std::string instance_id;
        uint32_t revision = 0;
        bool card_visible = false;
        bool card_expanded = false;
        bool card_actionable = false;
        bool card_has_tertiary = false;
        bool animating_out = false;
        float left = 13.0f;
        float right = 13.0f + kCardWidth;
        float top = 0.0f;
        float bottom = 0.0f;
    };

    struct CardView {
        std::string instance_id;
        uint32_t revision = 0;
        std::string title;
        std::vector<std::string> items;
        std::string status;
        std::string priority;
        std::string primary_label;
        std::string secondary_label;
        std::string tertiary_label;
        int queue_count = 0;
        bool privacy_mode = false;
        bool actionable = false;
        bool expanded = false;
        bool visible = false;
    };

    struct PendingSnapshot {
        bool dirty_state = false;
        std::string state;
        bool dirty_emotion = false;
        std::string emotion;
        bool dirty_subtitle = false;
        std::string subtitle_role;
        std::string subtitle_text;
        bool dirty_notification = false;
        std::string notification_text;
        uint32_t notification_duration_ms = 0;
        bool dirty_status_text = false;
        std::string status_text;
        bool dirty_level = false;
        std::string level_type;
        int level_value = 0;
        uint32_t level_duration_ms = 1500;
        bool dirty_network = false;
        NetworkUiState network_state = NetworkUiState::kDisconnected;
        bool dirty_muted = false;
        bool muted = false;
        bool dirty_mcp_show = false;
        bool dirty_mcp_dismiss = false;
        bool dirty_card_action = false;
        std::string card_action_instance_id;
        uint32_t card_action_revision = 0;
        std::string card_action;
        CardView mcp_card;
        bool dirty_background = false;
        std::string background_id;
        bool dirty_spine_ota = false;
        bool spine_ota_dismiss = false;
        std::string spine_ota_title;
        std::string spine_ota_detail;
        int spine_ota_progress = -1;
    };

    void LogQueueEvent(const char* event) {
        // Ordinary render-queue transitions are expected for every speech
        // state update. Card lifecycle has its own REMINDER_CARD events.
        (void)event;
    }

    PendingSnapshot TakePendingSnapshot() {
        PendingSnapshot snap;
        if (dirty_state) {
            snap.dirty_state = true;
            snap.state = pending_state;
            dirty_state = false;
        }
        if (dirty_emotion) {
            snap.dirty_emotion = true;
            snap.emotion = pending_emotion;
            dirty_emotion = false;
        }
        if (dirty_subtitle) {
            snap.dirty_subtitle = true;
            snap.subtitle_role = pending_subtitle_role;
            snap.subtitle_text = pending_subtitle_text;
            dirty_subtitle = false;
        }
        if (dirty_notification) {
            snap.dirty_notification = true;
            snap.notification_text = pending_notification_text;
            snap.notification_duration_ms = pending_notification_duration_ms;
            dirty_notification = false;
        }
        if (dirty_status_text) {
            snap.dirty_status_text = true;
            snap.status_text = pending_status_text;
            dirty_status_text = false;
        }
        if (dirty_level) {
            snap.dirty_level = true;
            snap.level_type = pending_level_type;
            snap.level_value = pending_level_value;
            snap.level_duration_ms = pending_level_duration_ms;
            dirty_level = false;
        }
        if (dirty_network) {
            snap.dirty_network = true;
            snap.network_state = pending_network_state;
            dirty_network = false;
        }
        if (dirty_muted) {
            snap.dirty_muted = true;
            snap.muted = pending_muted;
            dirty_muted = false;
        }
        if (dirty_mcp_show) {
            snap.dirty_mcp_show = true;
            snap.mcp_card = pending_mcp_card;
            dirty_mcp_show = false;
        }
        if (dirty_mcp_dismiss) {
            snap.dirty_mcp_dismiss = true;
            dirty_mcp_dismiss = false;
        }
        if (dirty_card_action) {
            snap.dirty_card_action = true;
            snap.card_action_instance_id =
                pending_card_action_instance_id;
            snap.card_action_revision =
                pending_card_action_revision;
            snap.card_action = pending_card_action;
            dirty_card_action = false;
        }
        if (dirty_background) {
            snap.dirty_background = true;
            snap.background_id = pending_background_id;
            dirty_background = false;
        }
        if (dirty_spine_ota) {
            snap.dirty_spine_ota = true;
            snap.spine_ota_dismiss = pending_spine_ota_dismiss;
            snap.spine_ota_title = pending_spine_ota_title;
            snap.spine_ota_detail = pending_spine_ota_detail;
            snap.spine_ota_progress = pending_spine_ota_progress;
            dirty_spine_ota = false;
        }
        return snap;
    }

    ~Impl() {
        spine.reset();
        engine.reset();
        g_spine_image = {};
        if (surface.pixels != nullptr) heap_caps_free(surface.pixels);
    }

    bool LoadBackground() {
        if (resource_manager == nullptr || scene == nullptr) {
            ESP_LOGE(kTag, "Background requested before engine setup");
            return false;
        }

        if (background_node) {
            scene->deleteObject(background_node->getId());
            background_node.reset();
        }
        background_texture.reset();

        void* source = nullptr;
        size_t source_size = 0;
        std::string source_name = "room.png";
        std::string wallpaper_id;
        auto& wallpapers = WallpaperAssets::GetInstance();
        const bool online_wallpaper = wallpapers.Initialize() &&
            wallpapers.GetSelectedAssetData(source, source_size, &wallpaper_id);
        if (online_wallpaper) {
            source_name = "wallpaper/" + wallpaper_id;
            ESP_LOGI(kTag, "Loading online wallpaper id=%s", wallpaper_id.c_str());
        } else if (!Assets::GetInstance().GetAssetData("room.png", source, source_size) ||
                   source == nullptr || source_size == 0) {
            ESP_LOGE(kTag, "Missing Cubicat room background");
            return false;
        }

        auto decoded_texture = resource_manager->loadTextureFromMemory(
            source_name.c_str(), source, source_size);
        if (!decoded_texture) {
            ESP_LOGE(kTag, "Cubicat background decode failed: %s", source_name.c_str());
            return false;
        }
        const auto texture_size =
            decoded_texture->getTextureSize();
        const int source_width = texture_size.x;
        const int source_height = texture_size.y;
        if (source_width <= 0 || source_height <= 0) {
            ESP_LOGE(kTag, "Invalid background dimensions");
            return false;
        }

        constexpr int kReferenceBgWidth = 360;
        constexpr int kReferenceBgHeight = 240;
        constexpr int kCropLeft = 20;
        constexpr int kCropWidth = 320;
        constexpr int kCropHeight = 240;
        constexpr int kDstTop = (320 - kCropHeight) / 2;  // 40

        if (source_width == kReferenceBgWidth &&
            source_height == kReferenceBgHeight) {
            const uint8_t color_depth = decoded_texture->getColorDepth();
            const size_t bytes_per_pixel = color_depth == 32 ? 4U : 2U;
            const size_t output_size =
                static_cast<size_t>(width) * height * bytes_per_pixel;
            auto* padded = static_cast<uint8_t*>(
                heap_caps_malloc(
                    output_size, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
            if (padded == nullptr) {
                ESP_LOGE(kTag, "No PSRAM for room background padding");
                return false;
            }

            const auto* src = static_cast<const uint8_t*>(
                decoded_texture->getFrameData());
            const size_t src_stride =
                static_cast<size_t>(source_width) * bytes_per_pixel;
            const size_t dst_stride =
                static_cast<size_t>(width) * bytes_per_pixel;
            const size_t crop_bytes =
                static_cast<size_t>(kCropWidth) * bytes_per_pixel;

            for (int dst_y = 0; dst_y < height; ++dst_y) {
                int crop_y;
                if (dst_y < kDstTop) {
                    crop_y = 0;
                } else if (dst_y >= kDstTop + kCropHeight) {
                    crop_y = kCropHeight - 1;
                } else {
                    crop_y = dst_y - kDstTop;
                }
                const auto* row_src =
                    src + static_cast<size_t>(crop_y) * src_stride +
                    static_cast<size_t>(kCropLeft) * bytes_per_pixel;
                auto* row_dst =
                    padded + static_cast<size_t>(dst_y) * dst_stride;
                std::memcpy(row_dst, row_src, crop_bytes);
            }

            background_texture = cubicat::Texture::create(
                width, height, padded, true, 1, 1,
                nullptr, color_depth, decoded_texture->hasAlpha());
            if (!background_texture) {
                heap_caps_free(padded);
                ESP_LOGE(kTag, "Room background texture creation failed");
                return false;
            }

        } else {
            background_texture = decoded_texture;
        }

        background_node = scene->createSpriteNode(
            background_texture,
            cubicat::Vector2f(0.5f, 0.5f),
            BACKGROUND);
        if (!background_node) {
            ESP_LOGE(kTag, "Cubicat room background node creation failed");
            return false;
        }

        background_node->setPosition(
            cubicat::Vector2f(width / 2.0f, height / 2.0f));
        background_node->setScale(cubicat::Vector2f(1.0f, 1.0f));
        background_node->setZ(-100);
        if (lvgl_overlay_) {
            lvgl_overlay_->SetMcpWallpaper(background_texture);
            if (card.visible && mcp_ui_enabled) ApplyCardLayout();
        }
        return true;
    }

    bool DecodeSpineTexture() {
        if (resource_manager == nullptr) {
            ESP_LOGE(kTag, "Spine texture requested before engine setup");
            return false;
        }
        auto& spine_assets = SpineAssets::GetInstance();
        if (!spine_assets.ready()) {
            ESP_LOGE(kTag, "Spine assets not ready");
            return false;
        }
        const auto& meta = spine_assets.meta();

        void* source = nullptr;
        size_t source_size = 0;
        if (!spine_assets.GetAssetData(meta.png, source, source_size) ||
            source == nullptr || source_size == 0) {
            ESP_LOGE(kTag, "Missing Spine texture asset: %s", meta.png.c_str());
            return false;
        }

        spine_texture = resource_manager->loadTextureFromMemory(
            meta.png.c_str(), source, source_size);
        if (!spine_texture) {
            ESP_LOGE(kTag, "Spine texture decode failed");
            return false;
        }
        if (spine_texture->getColorDepth() != 32 ||
            !spine_texture->hasAlpha()) {
            ESP_LOGE(kTag,
                     "Spine texture must decode as RGBA8888");
            return false;
        }

        const auto texture_size = spine_texture->getTextureSize();
        const uint16_t texture_width = texture_size.x;
        const uint16_t texture_height = texture_size.y;
        g_spine_image = {
            texture_width, texture_height, 1, 1, false, true, 0,
            spine_texture.get(), nullptr, 32};
        ESP_LOGI(kTag, "Texture ready: %ux%u, %u bytes",
                 texture_width, texture_height,
                 static_cast<unsigned>(
                     static_cast<uint32_t>(texture_width) *
                     texture_height * sizeof(uint32_t)));
        return true;
    }

    cubicat::Node2DPtr CreateSolid(int width,
                                   int height,
                                   uint16_t color,
                                   int screen_x,
                                   int screen_y,
                                   int z) {
        if (scene == nullptr) return cubicat::Node2DPtr(nullptr);
        auto texture = cubicat::TexturePtr(NEW cubicat::SolidTexture(color));
        if (!texture) return cubicat::Node2DPtr(nullptr);
        auto node = scene->createQuad(
            texture, cubicat::Vector2f(0.0f, 0.0f), FOREGROUND);
        if (!node) return cubicat::Node2DPtr(nullptr);
        node->setScale(cubicat::Vector2f(width, height));
        SetScreenPosition(node.get(), screen_x, screen_y, height);
        node->setZ(z);
        return node;
    }

    cubicat::TextLabelPtr CreateLabel(int width,
                                      int height,
                                      uint16_t color,
                                      int screen_x,
                                      int screen_y,
                                      int z) {
        if (scene == nullptr) return cubicat::TextLabelPtr(nullptr);
        auto label = cubicat::TextLabel::create(
            width, height, color, "", false);
        if (!label) return cubicat::TextLabelPtr(nullptr);
        scene->addNode(label);
        SetScreenPosition(label.get(), screen_x, screen_y, height);
        label->setZ(z);
        return label;
    }

    void SetScreenPosition(cubicat::Node2D* node,
                           int screen_x,
                           int screen_y,
                           int object_height) {
        node->setPosition(
            static_cast<float>(screen_x),
            static_cast<float>(height - screen_y - object_height));
    }

    int CardLeft() const { return (width - kCardWidth) / 2; }

    void SetCardTop(int screen_y) {
        if (!mcp_ui_enabled || !card_node) return;
        const int card_height =
            card.expanded ? kCardExpandedHeight : kCardSummaryHeight;
        SetScreenPosition(card_node.get(), CardLeft(), screen_y, card_height);
    }

    int CardShownTop(bool expanded) const {
        const int preferred = expanded ? kCardExpandedTop : kCardSummaryTop;
        const int card_height =
            expanded ? kCardExpandedHeight : kCardSummaryHeight;
        const int max_top =
            std::max(kCardTopMargin, height - card_height - kCardBottomInset);
        return std::min(preferred, max_top);
    }

    void LogCardLifecycle(const char* event, const char* reason) const {
        const char* item0 = card.items.empty() ? "" : card.items[0].c_str();
        ESP_LOGI(kTag,
                 "[REMINDER_CARD] event=%s reason=%s instance=%s rev=%u "
                 "visible=%d expanded=%d actionable=%d rect=%d,%d,%d,%d "
                 "title=\"%s\" item0=\"%s\" actions=\"%s|%s|%s\"",
                 event == nullptr ? "unknown" : event,
                 reason == nullptr ? "" : reason,
                 card.instance_id.c_str(),
                 static_cast<unsigned>(card.revision),
                 card.visible ? 1 : 0, card.expanded ? 1 : 0,
                 card.actionable ? 1 : 0,
                 CardLeft(), card_screen_top, kCardWidth,
                 card.expanded ? kCardExpandedHeight : kCardSummaryHeight,
                 card.title.c_str(), item0,
                 card.primary_label.c_str(), card.secondary_label.c_str(),
                 card.tertiary_label.c_str());
    }

    bool HasSpineAnimation(const char* name) {
        if (!spine || !spine->isLoaded() || name == nullptr) return false;
        const auto& names = spine->getAnimationNames();
        return std::find(names.begin(), names.end(), name) != names.end();
    }

    bool CreateDialogueUi() {
        ESP_LOGI(kTag, "[HOMEINIT] dialogue begin");

        dialogue_placeholder_tex =
            MakeTransparentTexture(kDialogueW, kDialogueH);
        if (!dialogue_placeholder_tex) {
            ESP_LOGE(kTag, "Dialogue placeholder texture creation failed");
            return false;
        }
        level_placeholder_tex =
            MakeTransparentTexture(200, 64);
        if (!level_placeholder_tex) {
            ESP_LOGE(kTag, "Level overlay placeholder texture creation failed");
            return false;
        }

        dialogue_node = scene->createSpriteNode(
            dialogue_placeholder_tex, cubicat::Vector2f(0.0f, 0.0f), FOREGROUND);
        if (!dialogue_node) {
            ESP_LOGE(kTag, "Dialogue node creation failed");
            return false;
        }
        dialogue_node->setScale(cubicat::Vector2f(1.0f, 1.0f));
        SetScreenPosition(dialogue_node.get(), kDialogueX, kDialogueHiddenY,
                          kDialogueH);
        dialogue_node->setZ(60);
        dialogue_node->setVisible(false);
        dialogue_screen_y = kDialogueHiddenY;

        level_overlay_node = scene->createSpriteNode(
            level_placeholder_tex, cubicat::Vector2f(0.0f, 0.0f), FOREGROUND);
        if (!level_overlay_node) {
            ESP_LOGE(kTag, "Level overlay node creation failed");
            return false;
        }
        level_overlay_node->setScale(cubicat::Vector2f(1.0f, 1.0f));
        SetScreenPosition(level_overlay_node.get(),
                          (width - 200) / 2, (height - 64) / 2, 64);
        level_overlay_node->setZ(90);
        level_overlay_node->setVisible(false);

        spine_ota_placeholder_tex = MakeTransparentTexture(280, 120);
        if (spine_ota_placeholder_tex) {
            spine_ota_node = scene->createSpriteNode(
                spine_ota_placeholder_tex, cubicat::Vector2f(0.0f, 0.0f),
                FOREGROUND);
            if (spine_ota_node) {
                spine_ota_node->setScale(cubicat::Vector2f(1.0f, 1.0f));
                SetScreenPosition(spine_ota_node.get(),
                                  (width - 280) / 2, (height - 120) / 2, 120);
                spine_ota_node->setZ(95);
                spine_ota_node->setVisible(false);
            }
        }

        ESP_LOGI(kTag, "[HOMEUI] dialogue=ready size=%dx%d default=hidden",
                 kDialogueW, kDialogueH);
        ESP_LOGI(kTag, "[LVOVINIT] stage=dialogue_ready result=ok");
        ESP_LOGI(kTag, "[LVOVINIT] stage=level_overlay_ready result=ok");
        return true;
    }

    bool CreateSubtitleUi() {
        // Subtitle label kept for backward compatibility but hidden.
        ESP_LOGI(kTag, "[HOMEINIT] subtitle begin");
        subtitle = CreateLabel(
            284, 60, Rgb565(255, 248, 236), 18, 226, 60);
        if (!subtitle) {
            ESP_LOGE(kTag, "Subtitle label creation failed");
            return false;
        }
        subtitle->setVisible(false);
        ESP_LOGI(kTag, "[HOMEUI] native_text=ready font=gb2312_20 utf8=1");
        return true;
    }

    bool CreateStatusIconUi() {
        ESP_LOGI(kTag, "[HOMEINIT] status icons begin");

        // Load all four icon textures
        struct IconAsset {
            const char* name;
            cubicat::TexturePtr* target;
        };
        const IconAsset assets[] = {
            {"wifi_connected.png", &wifi_connected_tex},
            {"wifi_config.png", &wifi_config_tex},
            {"wifi_off.png", &wifi_off_tex},
            {"muted.png", &muted_tex},
        };
        for (const auto& asset : assets) {
            void* src = nullptr;
            size_t sz = 0;
            if (!Assets::GetInstance().GetAssetData(
                    asset.name, src, sz) ||
                src == nullptr || sz == 0) {
                ESP_LOGE(kTag, "Missing status icon: %s", asset.name);
                return false;
            }
            auto tex = resource_manager->loadTextureFromMemory(
                asset.name, src, sz);
            if (!tex) {
                ESP_LOGE(kTag, "Status icon decode failed: %s", asset.name);
                return false;
            }
            *asset.target = tex;
        }

        // Right safety margin 8px => right edge max x=312 on 320-wide screen.
        constexpr int kIconSize = kStatusIconSize;
        const int right_edge = width - 8;
        const int muted_x = right_edge - kIconSize;
        const int wifi_x = muted_x - kStatusIconGap - kIconSize;

        network_icon = scene->createSpriteNode(
            wifi_off_tex, cubicat::Vector2f(0.0f, 0.0f), FOREGROUND);
        if (!network_icon) {
            ESP_LOGE(kTag, "[LVOVERR] stage=icons code=network_node");
            return false;
        }
        SetScreenPosition(network_icon.get(), wifi_x, kStatusIconY, kIconSize);
        network_icon->setZ(80);
        network_icon->setVisible(true);

        muted_icon = scene->createSpriteNode(
            muted_tex, cubicat::Vector2f(0.0f, 0.0f), FOREGROUND);
        if (!muted_icon) {
            ESP_LOGE(kTag, "[LVOVERR] stage=icons code=muted_node");
            return false;
        }
        SetScreenPosition(muted_icon.get(), muted_x, kStatusIconY, kIconSize);
        muted_icon->setZ(80);
        muted_icon->setVisible(muted_state);

        const auto tex_size = wifi_connected_tex->getTextureSize();
        ESP_LOGI(kTag,
                 "[HOMEUI] network_icons=ready connected=%dx%d configuring=%dx%d offline=%dx%d",
                 static_cast<int>(tex_size.x), static_cast<int>(tex_size.y),
                 static_cast<int>(tex_size.x), static_cast<int>(tex_size.y),
                 static_cast<int>(tex_size.x), static_cast<int>(tex_size.y));
        ESP_LOGI(kTag, "[HOMEUI] muted_icon=ready size=20x20");
        return true;
    }

    bool CreateMcpCardUi() {
        mcp_ui_enabled = false;
        ESP_LOGI(kTag,
                 "[HOMEINIT] stage=mcp_begin internal=%u largest=%u "
                 "psram=%u",
                 static_cast<unsigned>(
                     heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                 static_cast<unsigned>(
                     heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL)),
                 static_cast<unsigned>(
                     heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));

        const bool heap_ok_before =
            heap_caps_check_integrity_all(true);
        ESP_LOGI(kTag,
                 "[HOMEINIT] stage=mcp_heap_check_before result=%s",
                 heap_ok_before ? "ok" : "fail");
        if (!heap_ok_before) {
            ESP_LOGE(kTag, "[LVOVERR] stage=mcp code=heap_before");
            return true;
        }

        // Hidden until its real texture exists; avoid a 239 KiB placeholder.
        constexpr unsigned placeholder_bytes = 4;
        card_placeholder_texture = MakeTransparentTexture(1, 1);
        if (!card_placeholder_texture) {
            ESP_LOGE(kTag,
                     "[LVOVERR] stage=mcp code=placeholder bytes=%u",
                     placeholder_bytes);
            return true;
        }
        ESP_LOGI(kTag,
                 "[HOMEINIT] stage=mcp_placeholder_ready bytes=%u",
                 placeholder_bytes);

        card_node = scene->createSpriteNode(
            card_placeholder_texture,
            cubicat::Vector2f(0.0f, 0.0f),
            FOREGROUND);
        if (!card_node) {
            ESP_LOGE(kTag, "[LVOVERR] stage=mcp code=node");
            card_placeholder_texture.reset();
            ESP_LOGI(kTag,
                     "[HOMEINIT] stage=mcp_node_ready result=fail");
            return true;
        }
        card_node->setZ(100);
        card_node->setVisible(false);
        SetScreenPosition(card_node.get(), CardLeft(), height + 6,
                          kCardExpandedHeight);
        ESP_LOGI(kTag, "[HOMEINIT] stage=mcp_node_ready result=ok");
        ESP_LOGI(kTag, "[HOMEINIT] stage=mcp_hidden result=ok");

        const bool heap_ok_after =
            heap_caps_check_integrity_all(true);
        ESP_LOGI(kTag,
                 "[HOMEINIT] stage=mcp_heap_check_after result=%s",
                 heap_ok_after ? "ok" : "fail");
        if (!heap_ok_after) {
            ESP_LOGE(kTag, "[LVOVERR] stage=mcp code=heap_after");
            card_node.reset();
            card_placeholder_texture.reset();
            return true;
        }

        ESP_LOGI(kTag,
                 "[HOMEUI] mcp_card=enabled mode=lvgl_lazy_single_sprite");
        mcp_ui_enabled = true;
        return true;
    }

    bool Initialize(int requested_width,
                    int requested_height,
                    CubicatHomePlayer::FrameSubmitter frame_submitter,
                    CubicatHomePlayer::UiActionHandler ui_action_handler) {
        ESP_LOGI(kTag, "[BOOT] reset_reason=%d",
                 static_cast<int>(esp_reset_reason()));

        width = requested_width;
        height = requested_height;
        submitter = std::move(frame_submitter);
        action_handler = std::move(ui_action_handler);
        if (width != 320 || height != 320) {
            ESP_LOGE(kTag, "Native Home requires 320x320, got %dx%d",
                     width, height);
            return false;
        }

        surface.width = width;
        surface.height = height;
        surface.submitter = submitter;
        surface.pixels = static_cast<uint16_t*>(
            heap_caps_malloc(
                static_cast<size_t>(width) * height * sizeof(uint16_t),
                MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (surface.pixels == nullptr) {
            ESP_LOGE(kTag, "No PSRAM for native Home framebuffer");
            return false;
        }
        std::memset(
            surface.pixels, 0,
            static_cast<size_t>(width) * height * sizeof(uint16_t));
        LogHomeInitStage("framebuffer_ready");

        engine = std::make_unique<EmbedGameEngine>();
        if (!engine) {
            ESP_LOGE(kTag, "Cubicat engine allocation failed");
            return false;
        }
        resource_manager = engine->createResourceManager();
        scene = engine->createSceneManager();
        auto ui_canvas = scene == nullptr
            ? cubicat::WidgetPtr()
            : scene->createUICanvas(width, height);
        renderer = engine->createRenderer(&surface);
        auto* tick_manager = engine->createTickManager();
        auto* schedule_manager = engine->createScheduleManager();
        if (resource_manager == nullptr ||
            scene == nullptr ||
            !ui_canvas ||
            renderer == nullptr ||
            tick_manager == nullptr ||
            schedule_manager == nullptr) {
            ESP_LOGE(kTag, "Cubicat engine subsystem initialization failed");
            return false;
        }
        renderer->addDrawStageListener(&surface);
        engine->setFPS(kTargetFps);
        LogHomeInitStage("engine_ready");

        if (!LoadBackground()) return false;
        LogHomeInitStage("background_ready");

        // Character role comes from spine_a/spine_b (must be preloaded before Home Start).
        // Failure must not brick home: keep room background / fonts / dialogue (safe mode).
        bool spine_ok = false;
        if (!SpineAssets::GetInstance().ready()) {
            ESP_LOGW(kTag,
                     "[SPINEBOOT] no valid role; starting background-only safe mode");
        } else if (!DecodeSpineTexture()) {
            ESP_LOGW(kTag, "Spine texture decode failed; home continues without character");
        } else {
            CubicatSpineExtension::init();
            CubicatTextureLoader::init(MEMORY, GetSpineImage);
            LogHomeInitStage("spine_runtime_ready");

            spine = SpineNode::create();
            if (!spine) {
                ESP_LOGE(kTag, "Spine node allocation failed");
            } else {
                scene->addNode(spine);
                const auto& meta = SpineAssets::GetInstance().meta();
                if (!spine->loadWithBinaryFile(
                        meta.skel, meta.atlas, meta.scale) ||
                    !spine->isLoaded()) {
                    ESP_LOGE(kTag, "Spine skeleton did not load");
                    spine.reset();
                } else {
                    LogHomeInitStage("spine_skeleton_ready");
                    spine->setScale(cubicat::Vector2f(
                        kSpineDisplayScale, kSpineDisplayScale));
                    spine->setSkinByName(meta.skin.c_str());
                    LogHomeInitStage("spine_skin_ready");
                    spine->useBilinearFilter(true);
                    LogHomeInitStage("spine_reference_sampling_ready");
                    spine->setAnimation(0, "idle", true);
                    LogHomeInitStage("spine_animation_ready");
                    const float reference_offset_y =
                        std::max(0, height - kReferenceSceneHeight) / 2.0f;
                    spine->setPosition(
                        cubicat::Vector2f(
                            width / 2.0f + kSpinePositionOffsetX,
                            reference_offset_y +
                                kSpinePositionOffsetY));
                    // Only rear clothing belongs behind the tabletop. Keep
                    // xiaobir/xiaobil (foreground forearms and hands) uncut.
                    if (meta.role_id == "nvhai_builtin" && width == 320 && height == 320) {
                        constexpr int kTableBackScreenY = 268;
                        const int table_world_y = height - kTableBackScreenY;
                        for (const char* slot : {"shenti", "dabir", "dabil", "yiling"}) {
                            if (!spine->setSlotMinWorldY(slot, table_world_y)) {
                                ESP_LOGW(kTag, "[TABLECLIP] missing rear slot=%s", slot);
                            }
                        }
                        ESP_LOGI(kTag, "[TABLECLIP] rear_clothes screen_y=%d foreground_arms=preserved",
                                 kTableBackScreenY);
                    }
                    spine_ok = true;
                    ESP_LOGI(kTag, "Spine role ready id=%s ver=%s slot=%s "
                                   "position=(%.2f,%.2f) scale=%.3f filter=bilinear",
                             meta.role_id.c_str(), meta.version.c_str(),
                             SpineAssets::GetInstance().active_label(),
                             width / 2.0f + kSpinePositionOffsetX,
                             reference_offset_y + kSpinePositionOffsetY,
                             meta.scale * kSpineDisplayScale);
                }
            }
        }
        if (!spine_ok) {
            LogHomeInitStage("spine_safe_mode");
        }
        // Initialize LVGL off-screen overlay (failure must not abort Home)
        lvgl_overlay_ = std::make_unique<CubicatLvglOverlay>();
        if (!lvgl_overlay_->Initialize(width, height)) {
            ESP_LOGW(kTag,
                     "[LVOVINIT] overlay disabled, continuing without LVGL");
            lvgl_overlay_.reset();
        } else {
            LogHomeInitStage("lvgl_overlay");
            lvgl_overlay_->SetMcpWallpaper(background_texture);
            ESP_LOGI(kTag, "[LVOVINIT] stage=texture_bind result=ok");
        }

        if (kEnableNativeText) {
            if (!CreateSubtitleUi()) return false;
        }
        if (!CreateDialogueUi()) {
            ESP_LOGW(kTag,
                     "[LVOVERR] stage=dialogue code=init_failed "
                     "continuing_without_dialogue");
        }
        if (kEnableStatusIcons) {
            if (!CreateStatusIconUi()) {
                ESP_LOGW(kTag,
                         "[LVOVERR] stage=icons code=init_failed "
                         "continuing_without_icons");
            }
        }
        if (kEnableMcpCard) {
            CreateMcpCardUi();
        }


        pending_state = "idle";
        dirty_state = true;

        stats_started_us = esp_timer_get_time();
        active.store(true, std::memory_order_relaxed);
        ESP_LOGI(kTag,
                 "Native Cubicat Home ready: %dx%d target=%dfps",
                 width, height, kTargetFps);
        return true;
    }

    const std::string& CurrentDialogueText() const {
        // Audio is asynchronous: tts.stop may already have changed the UI
        // state while the codec still owns buffered samples.  The application
        // explicitly clears this text once local playback is drained.
        // Notifications wait for active speech, then use the same bottom
        // dock. Retained text from finished speech must not block them.
        return IsNotificationDialogue()
            ? notification_text : speaking_subtitle_text;
    }

    bool IsNotificationDialogue() const {
        return !notification_text.empty() && !notification_deferred;
    }

    bool ShouldShowDialogue() const {
        return !CurrentDialogueText().empty();
    }

    const char* DialoguePhaseName(DialoguePhase phase) const {
        switch (phase) {
            case DialoguePhase::Showing: return "showing";
            case DialoguePhase::Shown: return "shown";
            case DialoguePhase::Hiding: return "hiding";
            default: return "hidden";
        }
    }

    void ResetDialogueScroll(const std::string& text, uint32_t now_ms) {
        dialogue_scroll_text = text;
        dialogue_scroll_is_notification = IsNotificationDialogue();
        dialogue_scroll_offset_px = 0;
        dialogue_scroll_started_ms = now_ms + kDialogueScrollDelayMs;
        dialogue_scroll_last_render_ms = 0;
        dialogue_text_width =
            lvgl_overlay_ && lvgl_overlay_->IsReady()
                ? lvgl_overlay_->MeasureDialogueTextWidth(text.c_str())
                : 0;
        // Force the first frame of a new sentence to begin at its start.
        dialogue_rendered_text.clear();
        dialogue_rendered_offset_px = -1;
    }

    uint32_t DialogueScrollTravelMs() const {
        const int travel =
            std::max(0, dialogue_text_width - kDialogueTextViewportW);
        return static_cast<uint32_t>(
            (travel + kDialogueScrollStepPx - 1) / kDialogueScrollStepPx) *
            kDialogueScrollFrameMs;
    }

    int DialogueScrollOffset(uint32_t now_ms) const {
        if (dialogue_text_width <= kDialogueTextViewportW ||
            static_cast<int32_t>(now_ms - dialogue_scroll_started_ms) < 0) {
            return 0;
        }
        const int travel = dialogue_text_width - kDialogueTextViewportW;
        if (travel <= 0) return 0;
        uint32_t elapsed = now_ms - dialogue_scroll_started_ms;
        if (IsNotificationDialogue()) {
            // Long-lived instructions repeat with pauses at both ends.
            const uint32_t travel_ms = DialogueScrollTravelMs();
            elapsed %= travel_ms + kDialogueScrollEndPauseMs +
                       kDialogueScrollDelayMs;
            if (elapsed >= travel_ms + kDialogueScrollEndPauseMs) return 0;
        }
        // Spoken subtitles scroll once and hold at the tail until the
        // application clears them at the local audio playback boundary.
        const uint32_t steps = elapsed / kDialogueScrollFrameMs;
        return std::min(travel, static_cast<int>(
            steps * kDialogueScrollStepPx));
    }

    void BindDialogueTexture(const std::string& text, int scroll_offset_px,
                             const char* action) {
        if (!dialogue_node || text.empty()) return;
        if (text == dialogue_rendered_text &&
            scroll_offset_px == dialogue_rendered_offset_px) {
            return;
        }

        dialogue_rendered_text = text;
        dialogue_rendered_offset_px = scroll_offset_px;
        if (lvgl_overlay_ && lvgl_overlay_->IsReady()) {
            auto tex = lvgl_overlay_->RenderDialogue(text.c_str(),
                                                      scroll_offset_px);
            if (tex) {
                auto drawable = dialogue_node->getDrawable(0);
                if (drawable) {
                    drawable->getMaterial()->setTexture(tex);
                }
            }
        }
        if (std::strcmp(action, "scroll") != 0) {
            ESP_LOGI(kTag,
                     "[LVOVDIALOG] action=%s text_bytes=%u scroll_width=%d "
                     "anim=%s",
                     action, static_cast<unsigned>(text.size()),
                     dialogue_text_width, DialoguePhaseName(dialogue_phase));
        }
    }

    void UpdateDialogueScroll(uint32_t now_ms) {
        if (!ShouldShowDialogue() ||
            dialogue_text_width <= kDialogueTextViewportW ||
            static_cast<int32_t>(now_ms - dialogue_scroll_started_ms) < 0) {
            return;
        }
        if (dialogue_scroll_last_render_ms != 0 &&
            now_ms - dialogue_scroll_last_render_ms <
                kDialogueScrollFrameMs) {
            return;
        }
        const int offset = DialogueScrollOffset(now_ms);
        if (offset == dialogue_scroll_offset_px) return;
        dialogue_scroll_offset_px = offset;
        dialogue_scroll_last_render_ms = now_ms;
        BindDialogueTexture(CurrentDialogueText(), offset, "scroll");
    }

    void StartDialogueSlide(bool show) {
        if (!dialogue_node) return;
        animation_from_y = dialogue_screen_y;
        animation_to_y = show ? kDialogueShownY : kDialogueHiddenY;
        dialogue_phase = show ? DialoguePhase::Showing : DialoguePhase::Hiding;
        dialogue_animation_started_ms =
            static_cast<uint32_t>(esp_timer_get_time() / 1000);
        if (show) {
            dialogue_node->setVisible(true);
            dialogue_pending_hide_ms = 0;
        }
    }

    void ScheduleDialogueHide(uint32_t now_ms) {
        dialogue_pending_hide_ms = now_ms + kDialogueHideDelayMs;
    }

    void CancelDialogueHide() {
        dialogue_pending_hide_ms = 0;
    }

    void UpdateDialogueVisibility(uint32_t now_ms) {
        notification_deferred = false;
        if (!notification_text.empty() && !speaking_subtitle_text.empty()) {
            auto& app = Application::GetInstance();
            notification_deferred =
                app.GetDeviceState() == kDeviceStateSpeaking ||
                !app.GetAudioService().IsPlaybackDrained();
        }
        if (notification_deferred) {
            // Restart the notification's reading time after an interruption.
            notification_until_ms = 0;
        }
        if (!ShouldShowDialogue()) {
            dialogue_scroll_text.clear();
            dialogue_rendered_text.clear();
            dialogue_text_width = 0;
            dialogue_scroll_offset_px = 0;
            dialogue_rendered_offset_px = -1;
            if (dialogue_phase != DialoguePhase::Hidden &&
                dialogue_phase != DialoguePhase::Hiding) {
                if (dialogue_pending_hide_ms == 0) {
                    ScheduleDialogueHide(now_ms);
                }
            }
            return;
        }

        CancelDialogueHide();
        const auto& text = CurrentDialogueText();
        if (dialogue_scroll_text != text ||
            dialogue_scroll_is_notification != IsNotificationDialogue()) {
            ResetDialogueScroll(text, now_ms);
        }
        if (IsNotificationDialogue() && notification_until_ms == 0) {
            const uint32_t reading_ms = kDialogueScrollDelayMs +
                DialogueScrollTravelMs() + kDialogueScrollEndPauseMs;
            notification_until_ms = now_ms +
                std::max(notification_duration_ms, reading_ms);
        }
        BindDialogueTexture(
            text,
            dialogue_scroll_offset_px,
            dialogue_phase == DialoguePhase::Shown ? "update" : "show");
        if (dialogue_phase == DialoguePhase::Hidden) {
            StartDialogueSlide(true);
        } else if (dialogue_phase == DialoguePhase::Hiding) {
            StartDialogueSlide(true);
        } else if (dialogue_phase == DialoguePhase::Shown &&
                   dialogue_screen_y != kDialogueShownY) {
            StartDialogueSlide(true);
        }
    }

    void HideDialogueImmediate(uint32_t now_ms) {
        (void)now_ms;
        CancelDialogueHide();
        if (dialogue_phase == DialoguePhase::Hidden) return;
        if (dialogue_phase == DialoguePhase::Hiding) return;
        StartDialogueSlide(false);
        ESP_LOGI(kTag,
                 "[LVOVDIALOG] action=hide text_bytes=%u anim=out",
                 static_cast<unsigned>(CurrentDialogueText().size()));
    }

    void ApplyNotification(const std::string& text, uint32_t duration_ms,
                           uint32_t now_ms) {
        notification_text = SingleLineText(text);
        notification_duration_ms = duration_ms == 0 ? 3000 :
            std::min(duration_ms, uint32_t{0x7FFFFFFF});
        notification_until_ms = 0;
        UpdateDialogueVisibility(now_ms);
    }

    void HideLevelOverlay() {
        level_overlay_visible = false;
        if (level_overlay_node) level_overlay_node->setVisible(false);
    }

    void ApplyLevelOverlay(const std::string& type, int value,
                           uint32_t duration_ms) {
        if (!level_overlay_node) return;
        if (lvgl_overlay_ && lvgl_overlay_->IsReady()) {
            const int64_t t0 = esp_timer_get_time();
            auto tex = lvgl_overlay_->RenderLevelOverlay(type.c_str(), value);
            const int64_t render_us = esp_timer_get_time() - t0;
            if (tex) {
                auto drawable = level_overlay_node->getDrawable(0);
                if (drawable) {
                    const auto tsz = tex->getTextureSize();
                    drawable->getMaterial()->setTexture(tex);
                    level_overlay_node->setVisible(true);
                    level_overlay_visible = true;
                    level_overlay_hide_ms =
                        static_cast<uint32_t>(esp_timer_get_time() / 1000) +
                        duration_ms;
                    ESP_LOGI(kTag,
                             "[LVOVLEVEL] type=%s value=%d visible=1 "
                             "texture=%dx%d render_us=%lld",
                             type.c_str(), value,
                             static_cast<int>(tsz.x), static_cast<int>(tsz.y),
                             render_us);
                }
            }
        }
    }

    const char* NetworkIconName(NetworkUiState state) const {
        switch (state) {
            case NetworkUiState::kConnected:
                return "connected";
            case NetworkUiState::kConfiguring:
                return "configuring";
            default:
                return "disconnected";
        }
    }

    void ApplyStatusIcons() {
        // LVGL renders status icons at 20x20; layout from right margin width-8.
        const bool wifi_visible =
            network_state == NetworkUiState::kConfiguring ||
            network_state == NetworkUiState::kDisconnected;

        int right = width - 8;
        if (muted_state && muted_icon) {
            const int muted_x = right - kStatusIconSize;
            SetScreenPosition(muted_icon.get(), muted_x, kStatusIconY,
                              kStatusIconSize);
            muted_icon->setVisible(true);
            if (lvgl_overlay_ && lvgl_overlay_->IsReady()) {
                auto tex = lvgl_overlay_->RenderStatusIcon("muted", true);
                if (tex) {
                    auto drawable = muted_icon->getDrawable(0);
                    if (drawable) {
                        drawable->getMaterial()->setTexture(tex);
                    }
                }
            } else if (muted_tex) {
                auto drawable = muted_icon->getDrawable(0);
                if (drawable) {
                    drawable->getMaterial()->setTexture(muted_tex);
                }
            }
            right = muted_x - kStatusIconGap;
        } else if (muted_icon) {
            muted_icon->setVisible(false);
        }

        if (wifi_visible && network_icon) {
            const int wifi_x = right - kStatusIconSize;
            SetScreenPosition(network_icon.get(), wifi_x, kStatusIconY,
                              kStatusIconSize);
            network_icon->setVisible(true);
            if (lvgl_overlay_ && lvgl_overlay_->IsReady()) {
                auto tex = lvgl_overlay_->RenderStatusIcon(
                    NetworkIconName(network_state), true);
                if (tex) {
                    auto drawable = network_icon->getDrawable(0);
                    if (drawable) {
                        drawable->getMaterial()->setTexture(tex);
                    }
                }
            } else {
                cubicat::TexturePtr target_tex;
                switch (network_state) {
                    case NetworkUiState::kConnected:
                        target_tex = wifi_connected_tex;
                        break;
                    case NetworkUiState::kConfiguring:
                        target_tex = wifi_config_tex;
                        break;
                    default:
                        target_tex = wifi_off_tex;
                        break;
                }
                if (target_tex) {
                    auto drawable = network_icon->getDrawable(0);
                    if (drawable) {
                        drawable->getMaterial()->setTexture(target_tex);
                    }
                }
            }
        } else if (network_icon) {
            network_icon->setVisible(false);
        }

        icons_synced = true;
        icons_enqueued_once = true;
        ESP_LOGI(kTag,
                 "[LVOVICON] network=%s wifi_visible=%d muted_visible=%d",
                 NetworkIconName(network_state),
                 wifi_visible ? 1 : 0,
                 muted_state ? 1 : 0);
    }

    void ApplyState(const std::string& state, uint32_t now_ms) {
        static const char* kValidStates[] = {
            "absent", "idle", "prewake",
            "listening", "thinking", "speaking", "reminder"};
        std::string normalized;
        for (const auto& s : kValidStates) {
            if (state == s) { normalized = s; break; }
        }
        if (normalized.empty()) {
            ESP_LOGW(kTag, "ApplyState unknown '%s' -> idle",
                     state.c_str());
            normalized = "idle";
        }
        if (normalized == current_state) {
            UpdateDialogueVisibility(now_ms);
            return;
        }

        const std::string prev = current_state;
        current_state = normalized;
        ESP_LOGI(kTag, "[HOMESTATE] %s -> %s",
                 prev.c_str(), normalized.c_str());

        ESP_LOGI(kTag, "[LVOVSTATE] home=%s network=%s muted=%d",
                 normalized.c_str(), NetworkIconName(network_state),
                 muted_state ? 1 : 0);

        const bool idle_like =
            normalized == "idle" || normalized == "absent" ||
            normalized == "prewake" || normalized == "reminder";
        const bool speaking = normalized == "speaking";

        if (subtitle) subtitle->setVisible(false);

        if (spine) {
            if (speaking && HasSpineAnimation("talk_start")) {
                spine->setAnimation(1, "talk_start", true);
            } else if (!speaking) {
                spine->clearTrack(1);
            }
            if (idle_like && prev != "idle" && prev != "absent" &&
                prev != "prewake" && prev != "reminder") {
                spine->setAnimation(0, "idle", true);
            }
        }

        UpdateDialogueVisibility(now_ms);
    }

    void ApplyEmotion(const std::string& emotion) {
        std::string animation;
        if (emotion == "happy" || emotion == "delight") {
            animation = "delight";
        } else if (emotion == "surprised" || emotion == "surprise") {
            animation = "suprise";
        } else if (emotion == "action" || emotion == "excited" ||
                   emotion == "reminder_attention") {
            animation = "action";
        }
        if (animation.empty() || !spine) return;
        // Character packs are allowed to omit the optional reminder/action
        // animation.  Fall back to an existing calm reaction rather than
        // logging an error and leaving the reminder visually inert.
        if (!HasSpineAnimation(animation.c_str())) {
            if (HasSpineAnimation("delight")) {
                animation = "delight";
            } else if (HasSpineAnimation("idle")) {
                animation = "idle";
            } else {
                return;
            }
            ESP_LOGW(kTag, "[SPINE] action_fallback emotion=%s animation=%s",
                     emotion.c_str(), animation.c_str());
        }
        if (spine->setAnimation(0, animation, false) != nullptr) {
            spine->addAnimation(0, "idle", true, 0.0f);
        }
    }

    void ApplySubtitle(const std::string&,
                       const std::string& text,
                       uint32_t now_ms) {
        speaking_subtitle_text = SingleLineText(text);
        if (subtitle) subtitle->setVisible(false);
        UpdateDialogueVisibility(now_ms);
    }

    void ApplyBackground(const std::string& background_id) {
        auto& wallpapers = WallpaperAssets::GetInstance();
        // These are the established home-page identifiers for the stock room.
        // Persisting the choice is important: otherwise a later bg_idle event
        // would leave the previously selected online wallpaper on screen.
        const bool factory_room = background_id == "room" ||
                                  background_id == "default" ||
                                  background_id == "bg_idle" ||
                                  background_id == "sunny_day";
        if (factory_room && wallpapers.UseFactoryWallpaper()) {
            if (!LoadBackground()) {
                ESP_LOGW(kTag, "Failed to apply factory room wallpaper");
            }
            return;
        }
        if (wallpapers.ready() && wallpapers.Select(background_id)) {
            if (!LoadBackground()) {
                ESP_LOGW(kTag, "Failed to apply selected wallpaper '%s'", background_id.c_str());
            }
            return;
        }
        // Existing UI ids still mean the fixed room when no matching online
        // package item is installed. This preserves the previous JS behavior.
        ESP_LOGW(kTag, "Unknown online wallpaper id '%s'", background_id.c_str());
    }

    void ApplyCardVisible(bool visible) {
        if (!mcp_ui_enabled || !card_node) return;
        card.visible = visible;
        card_animating = true;
        card_animation_started_ms =
            static_cast<uint32_t>(esp_timer_get_time() / 1000);
        card_animation_showing = visible;
        if (visible) {
            card_node->setVisible(true);
            SetCardTop(height + 6);
            card_screen_top = height + 6;
            const uint32_t now_ms =
                static_cast<uint32_t>(esp_timer_get_time() / 1000);
            UpdateDialogueVisibility(now_ms);
            ESP_LOGI(kTag,
                     "[LVOVCARD] phase=%s visible=1 action=show",
                     card.expanded ? "expanded" : "summary");
            LogCardLifecycle("ui_show_begin", "queued");
        } else {
            ESP_LOGI(kTag,
                     "[LVOVCARD] phase=%s visible=0 action=dismiss",
                     card.expanded ? "expanded" : "summary");
            LogCardLifecycle("ui_dismiss_begin", "display_request");
        }
    }

    cubicat::TexturePtr RenderCardTexture(bool expanded) {
        if (!lvgl_overlay_ || !lvgl_overlay_->IsReady()) {
            ESP_LOGW(kTag, "[LVOVERR] mcp_render skipped overlay_unready");
            return cubicat::TexturePtr();
        }
        CubicatLvglOverlay::McpCardContent content{};
        content.title = card.title.empty()
            ? "\xE5\xAE\xB6\xE4\xBA\xBA\xE6\x8F\x90\xE9\x86\x92"
            : card.title.c_str();
        content.item_count =
            static_cast<int>(std::min(card.items.size(), size_t(4)));
        for (int i = 0; i < content.item_count; ++i) {
            content.items[i] = card.items[static_cast<size_t>(i)].c_str();
        }
        content.status = card.status.c_str();
        content.priority = card.priority.c_str();
        content.primary_label = card.primary_label.c_str();
        content.secondary_label = card.secondary_label.c_str();
        content.tertiary_label = card.tertiary_label.c_str();
        content.queue_count = card.queue_count;
        content.privacy_mode = card.privacy_mode;
        content.actionable = card.actionable;
        content.expanded = expanded;
        auto tex = lvgl_overlay_->RenderMcpCard(&content, CardLeft(), CardShownTop(expanded));
        if (!tex) {
            ESP_LOGW(kTag, "[LVOVERR] mcp_render failed expanded=%d",
                     expanded ? 1 : 0);
        }
        return tex;
    }

    bool ApplyCardLayout() {
        if (!mcp_ui_enabled || !card_node) {
            ESP_LOGW(kTag, "[LVOVERR] mcp_layout skipped ui_disabled");
            return false;
        }
        auto card_tex = RenderCardTexture(card.expanded);
        if (!card_tex) {
            ESP_LOGW(kTag, "[LVOVERR] mcp_layout texture_failed");
            return false;
        }
        auto drawable = card_node->getDrawable(0);
        if (!drawable) {
            ESP_LOGW(kTag, "[LVOVERR] mcp_layout setTexture_failed");
            return false;
        }
        drawable->getMaterial()->setTexture(card_tex);
        card_placeholder_texture.reset();
        ESP_LOGI(kTag,
                 "[LVOVCARD] phase=%s visible=%d action=layout",
                 card.expanded ? "expanded" : "summary",
                 card.visible ? 1 : 0);
        return true;
    }

    void ApplyAction(const std::string& instance_id,
                     uint32_t revision,
                     const std::string& action) {
        if (card.instance_id != instance_id ||
            card.revision != revision) {
            ESP_LOGW(kTag,
                     "Rejected stale UI action: %s rev=%u",
                     instance_id.c_str(),
                     static_cast<unsigned>(revision));
            return;
        }
        if (action == "expand") {
            const bool prev_expanded = card.expanded;
            card.expanded = true;
            if (!ApplyCardLayout()) {
                card.expanded = prev_expanded;
                ESP_LOGW(kTag,
                         "[LVOVERR] mcp_expand layout_failed keep_expanded=%d",
                         prev_expanded ? 1 : 0);
                return;
            }
            SetCardTop(CardShownTop(true));
            card_screen_top = CardShownTop(true);
            ESP_LOGI(kTag,
                     "[LVOVCARD] phase=expanded visible=1 action=expand");
            LogCardLifecycle("ui_expand", "touch_or_js");
            return;
        }
        if (action == "collapse") {
            const bool prev_expanded = card.expanded;
            card.expanded = false;
            if (!ApplyCardLayout()) {
                card.expanded = prev_expanded;
                ESP_LOGW(kTag,
                         "[LVOVERR] mcp_collapse layout_failed "
                         "keep_expanded=%d",
                         prev_expanded ? 1 : 0);
                return;
            }
            SetCardTop(CardShownTop(false));
            card_screen_top = CardShownTop(false);
            ESP_LOGI(kTag,
                     "[LVOVCARD] phase=summary visible=1 action=collapse");
            LogCardLifecycle("ui_collapse", "touch_or_js");
            return;
        }
        if (action == "dismiss") {
            ApplyCardVisible(false);
        } else if (action != "primary" &&
                   action != "secondary" &&
                   action != "tertiary") {
            ESP_LOGW(kTag, "Rejected unsupported UI action: %s",
                     action.c_str());
            return;
        }
        if (action_handler) {
            action_handler(instance_id.c_str(), revision, action.c_str());
        }
    }

    void ProcessPending(const PendingSnapshot& snap) {
        const uint32_t now_ms =
            static_cast<uint32_t>(esp_timer_get_time() / 1000);

        if (snap.dirty_background) {
            ApplyBackground(snap.background_id);
        }
        if (snap.dirty_state) {
            ApplyState(snap.state, now_ms);
        }
        if (snap.dirty_emotion) {
            ApplyEmotion(snap.emotion);
        }
        if (snap.dirty_subtitle) {
            ApplySubtitle(snap.subtitle_role, snap.subtitle_text, now_ms);
        }
        if (snap.dirty_status_text) {
            persistent_status_text = snap.status_text;
            if (!persistent_status_text.empty()) {
                persistent_status_text =
                    WrapText(persistent_status_text, 14, 1, true);
            }
        }
        if (snap.dirty_notification) {
            ApplyNotification(snap.notification_text,
                              snap.notification_duration_ms, now_ms);
        }
        if (snap.dirty_level) {
            ApplyLevelOverlay(snap.level_type, snap.level_value,
                              snap.level_duration_ms);
        }
        if (snap.dirty_spine_ota) {
            pending_spine_ota_dismiss = snap.spine_ota_dismiss;
            pending_spine_ota_title = snap.spine_ota_title;
            pending_spine_ota_detail = snap.spine_ota_detail;
            pending_spine_ota_progress = snap.spine_ota_progress;
            ApplySpineOtaUi();
        }
        if (snap.dirty_network) {
            network_state = snap.network_state;
            const char* state_names[] = {
                "connected", "configuring", "disconnected"};
            const int idx = static_cast<int>(network_state);
            ESP_LOGI(kTag, "[HOMESTATUS] network=%s",
                     idx >= 0 && idx < 3 ? state_names[idx] : "unknown");
            ApplyStatusIcons();
        }
        if (snap.dirty_muted) {
            muted_state = snap.muted;
            ESP_LOGI(kTag, "[HOMESTATUS] muted=%d", muted_state ? 1 : 0);
            ApplyStatusIcons();
        }
        if (snap.dirty_mcp_show) {
            card = snap.mcp_card;
            card.visible = false;
            if (card_node) card_node->setVisible(false);
            if (ApplyCardLayout()) {
                ApplyCardVisible(true);
            } else {
                card.visible = false;
                if (card_node) card_node->setVisible(false);
                ESP_LOGW(kTag,
                         "[LVOVERR] mcp_show layout_failed keep_hidden=1");
            }
        }
        if (snap.dirty_mcp_dismiss) {
            ApplyCardVisible(false);
        }
        if (snap.dirty_card_action) {
            ApplyAction(snap.card_action_instance_id,
                        snap.card_action_revision,
                        snap.card_action);
        }
    }

    void ApplyUiAnimations(uint32_t now_ms) {
        if (!notification_text.empty()) {
            // Local prompts may finish without clearing their subtitle or
            // producing a state event. Release waiting notifications then.
            UpdateDialogueVisibility(now_ms);
        }
        if (notification_until_ms != 0 && IsNotificationDialogue() &&
            static_cast<int32_t>(now_ms - notification_until_ms) >= 0) {
            notification_until_ms = 0;
            notification_text.clear();
            UpdateDialogueVisibility(now_ms);
        }

        if (dialogue_pending_hide_ms != 0 &&
            static_cast<int32_t>(now_ms - dialogue_pending_hide_ms) >= 0) {
            dialogue_pending_hide_ms = 0;
            HideDialogueImmediate(now_ms);
        }

        if (dialogue_phase == DialoguePhase::Showing ||
            dialogue_phase == DialoguePhase::Hiding) {
            if (!dialogue_node) {
                dialogue_phase = DialoguePhase::Hidden;
            } else {
                const uint32_t elapsed =
                    now_ms - dialogue_animation_started_ms;
                const uint32_t duration =
                    dialogue_phase == DialoguePhase::Showing
                        ? kDialogueSlideInMs
                        : kDialogueSlideOutMs;
                const float progress = std::min(
                    1.0f,
                    static_cast<float>(elapsed) /
                        static_cast<float>(duration));
                const float eased =
                    dialogue_phase == DialoguePhase::Showing
                        ? EaseOutCubic(progress)
                        : EaseInCubic(progress);
                dialogue_screen_y = static_cast<int>(
                    animation_from_y +
                    (animation_to_y - animation_from_y) * eased);
                SetScreenPosition(dialogue_node.get(), kDialogueX,
                                  dialogue_screen_y, kDialogueH);
                if (progress >= 1.0f) {
                    dialogue_screen_y = animation_to_y;
                    if (dialogue_phase == DialoguePhase::Showing) {
                        dialogue_phase = DialoguePhase::Shown;
                    } else {
                        dialogue_phase = DialoguePhase::Hidden;
                        dialogue_node->setVisible(false);
                    }
                }
            }
        }

        // Render only long subtitles and only at 10 fps.  The normal home
        // render loop remains at 30 fps, so this keeps text motion smooth
        // without rebuilding a subtitle texture for every scene frame.
        UpdateDialogueScroll(now_ms);

        if (level_overlay_visible &&
            level_overlay_hide_ms != 0 &&
            static_cast<int32_t>(now_ms - level_overlay_hide_ms) >= 0) {
            HideLevelOverlay();
        }

        if (kEnableMcpCard && mcp_ui_enabled &&
            card_animating && card_node) {
            const uint32_t elapsed = now_ms - card_animation_started_ms;
            const float progress =
                std::min(1.0f, static_cast<float>(elapsed) / 360.0f);
            const float eased = 1.0f - (1.0f - progress) *
                                           (1.0f - progress);
            const int shown_top = CardShownTop(card.expanded);
            const int hidden_top = height + 6;
            const int top = card_animation_showing
                ? static_cast<int>(hidden_top +
                                   (shown_top - hidden_top) * eased)
                : static_cast<int>(shown_top +
                                   (hidden_top - shown_top) * eased);
            card_screen_top = top;
            SetCardTop(top);
            if (progress >= 1.0f) {
                card_animating = false;
                if (card_animation_showing) {
                    LogCardLifecycle("ui_shown", "animation_complete");
                } else {
                    card_node->setVisible(false);
                    card.visible = false;
                    UpdateDialogueVisibility(now_ms);
                    LogCardLifecycle("ui_hidden", "animation_complete");
                }
            }
        }
    }

    void PublishTouchSnapshot() {
        touch_snap_.instance_id = card.instance_id;
        touch_snap_.revision = card.revision;
        touch_snap_.card_visible = card.visible;
        touch_snap_.card_expanded = card.expanded;
        touch_snap_.card_actionable = card.actionable;
        touch_snap_.card_has_tertiary = !card.tertiary_label.empty();
        touch_snap_.animating_out =
            card_animating && !card_animation_showing;
        touch_snap_.left = static_cast<float>(CardLeft());
        touch_snap_.right = touch_snap_.left + static_cast<float>(kCardWidth);
        const int card_height =
            card.expanded ? kCardExpandedHeight : kCardSummaryHeight;
        touch_snap_.top = static_cast<float>(card_screen_top);
        touch_snap_.bottom = touch_snap_.top + static_cast<float>(card_height);
    }

    void TickRender() {
        if (!active.load(std::memory_order_relaxed) || engine == nullptr) return;
        const int64_t render_start = esp_timer_get_time();
        if (cubicat::HomePerf().cycle_read_overhead == 0) {
            cubicat::HomePerf().Calibrate();
            cubicat::HomePerf().Reset();
        }
        const uint32_t prepare_calls_before = cubicat::HomePerf().prepare.calls;
        const uint32_t draws_before=cubicat::HomePerf().draw.calls;
        engine->update();
        const uint32_t frame_render_us = static_cast<uint32_t>(esp_timer_get_time() - render_start);
        if (cubicat::HomePerf().prepare.calls != prepare_calls_before) {
            cubicat::HomePerf().engine.Add(frame_render_us);
        }
        render_time_us += frame_render_us;
        max_render_us = std::max(max_render_us, frame_render_us);
        surface.Present();
        if(cubicat::HomePerf().draw.calls!=draws_before)
            cubicat::HomePerf().frame.Add(esp_timer_get_time()-render_start);
        tick_count++;

        if (!first_frame_logged && spine != nullptr &&
            !spine->getDrawables().empty()) {
            first_frame_logged = true;
            ESP_LOGI(kTag, "Spine first frame: %u drawables",
                     static_cast<unsigned>(spine->getDrawables().size()));
        }

        const int64_t now = esp_timer_get_time();
        const int64_t elapsed = now - stats_started_us;
        if (elapsed >= kHomePerfLogIntervalUs) {
            const auto lcd = cubicat::TakeHomeLcdPerfWindow();
            const auto status = cubicat::GetHomeRenderStatus();
            const auto &perf = cubicat::HomePerf();
            const uint32_t fps = static_cast<uint32_t>(lcd.completed * 1000000ULL / elapsed);
            const double display_fps = lcd.completed * 1000000.0 / elapsed;
            const double draw_fps = perf.draw.calls * 1000000.0 / elapsed;
            const uint32_t average_dirty =
                surface.frame_count == 0
                    ? 0
                    : static_cast<uint32_t>(surface.dirty_pixels / surface.frame_count);
            const uint32_t average_render =
                tick_count == 0 ? 0 : static_cast<uint32_t>(render_time_us / tick_count);
            const uint32_t max_render = max_render_us;
            const uint32_t render_budget_pct = average_render * 100U / 41666U;
            const uint32_t average_spi =
                surface.frame_count == 0 ? 0
                                         : static_cast<uint32_t>(surface.spi_time_us / surface.frame_count);
            ESP_LOGI(kTag,
                     "[HOMEPERF] fps=%u dirty=%u(%u%%) render=%uus render_max=%uus "
                     "render_budget_pct=%u spi=%uus "
                     "sram=%u psram=%u display_fps=%.2f draw_fps=%.2f accepted=%u completed=%u mode=%s",
                     static_cast<unsigned>(fps), static_cast<unsigned>(average_dirty),
                     static_cast<unsigned>(average_dirty * 100U / static_cast<uint32_t>(width * height)),
                     static_cast<unsigned>(average_render), static_cast<unsigned>(max_render),
                     static_cast<unsigned>(render_budget_pct), static_cast<unsigned>(average_spi),
                     static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                     static_cast<unsigned>(heap_caps_get_free_size(MALLOC_CAP_SPIRAM)), display_fps,
                     draw_fps, static_cast<unsigned>(lcd.accepted), static_cast<unsigned>(lcd.completed),
                     cubicat::HomeRenderModeName(status.mode));
            const uint32_t frames = perf.draw.calls;
            const uint64_t measured_us = perf.animation.total_us + perf.mesh.total_us +
                                         perf.prepare.total_us + perf.packet_prepare.total_us +
                                         perf.draw.total_us;
            const uint64_t other_us =
                perf.engine.total_us > measured_us ? perf.engine.total_us - measured_us : 0;
            ESP_LOGI(
                kTag,
                "[SPINEPERF] engine_us=%u other_us=%u anim_us=%u anim_max_us=%u anim_calls=%u "
                "mesh_update_us=%u mesh_max_us=%u prepare_us=%u "
                "draw_us=%u draw_max_us=%u draw_frames=%u "
                "polygon_total_per_frame_us=%u alpha_est_us=%u "
                "alpha_frames=%u alpha_samples=%u blend_pixels_per_sampled_frame=%u",
                static_cast<unsigned>(perf.engine.Average()),
                static_cast<unsigned>(perf.engine.calls ? other_us / perf.engine.calls : 0),
                static_cast<unsigned>(perf.animation.Average()),
                static_cast<unsigned>(perf.animation.max_us), static_cast<unsigned>(perf.animation.calls),
                static_cast<unsigned>(perf.mesh.Average()), static_cast<unsigned>(perf.mesh.max_us),
                static_cast<unsigned>(perf.prepare.Average()), static_cast<unsigned>(perf.draw.Average()),
                static_cast<unsigned>(perf.draw.max_us), static_cast<unsigned>(frames),
                static_cast<unsigned>(frames ? perf.polygon.total_us / frames : 0),
                static_cast<unsigned>(perf.AlphaEstimateUs(CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ)),
                static_cast<unsigned>(perf.alpha_frames), static_cast<unsigned>(perf.alpha_samples),
                static_cast<unsigned>(perf.alpha_frames ? perf.alpha_pixels / perf.alpha_frames : 0));
            const uint32_t transfers = lcd.transfer.calls;
            ESP_LOGI(kTag,
                     "[LCDPERF] accept_us=%u accept_max_us=%u accepted=%u completed=%u "
                     "snapshot_copy_us=%u snapshot_wait_us=%u transfer_us=%u transfer_max_us=%u "
                     "copy_per_frame_us=%u swap_per_frame_us=%u wait_per_frame_us=%u "
                     "queue_per_frame_us=%u queue_blocks=%u failures=%u rejected=%u timeouts=%u "
                     "pipeline=%d reason=%s lcd_stack_free=%u",
                     unsigned(lcd.accept.Average()), unsigned(lcd.accept.max_us), unsigned(lcd.accepted),
                     unsigned(lcd.completed), unsigned(lcd.snapshot_copy.Average()),
                     unsigned(lcd.snapshot_wait.Average()), unsigned(lcd.transfer.Average()),
                     unsigned(lcd.transfer.max_us), unsigned(transfers ? lcd.copy_us / transfers : 0),
                     unsigned(transfers ? lcd.swap_us / transfers : 0),
                     unsigned(transfers ? lcd.wait_us / transfers : 0),
                     unsigned(transfers ? lcd.queue_us / transfers : 0), unsigned(lcd.queue_blocks),
                     unsigned(lcd.failures), unsigned(lcd.rejected), unsigned(lcd.timeouts),
                     status.pipeline_enabled, status.pipeline_reason, unsigned(status.lcd_stack_free));
            ESP_LOGI(kTag,
                     "[DUALPERF] dual=%d reason=%s dual_frames=%u packet_prepare_us=%u "
                     "core0_work_us=%u core1_work_us=%u draw_wall_us=%u polygon_work_us=%u "
                     "join_wait_us=%u core0_share_pct=%u worker_timeouts=%u fallbacks=%u "
                     "fast_quads=%u active_edge_draws=%u raster_stack_free=%u main_stack_free=%u",
                     status.dual_enabled, status.dual_reason, unsigned(perf.dual_frames),
                     unsigned(perf.packet_prepare.Average()), unsigned(perf.core0_draw.Average()),
                     unsigned(perf.core1_draw.Average()), unsigned(perf.draw.Average()),
                     unsigned(frames ? perf.polygon.total_us / frames : 0),
                     unsigned(perf.join_wait.Average()), unsigned(status.core0_share_pct),
                     unsigned(perf.dual_timeouts), unsigned(status.fallback_count),
                     unsigned(perf.fast_quads), unsigned(perf.active_edge_draws),
                     unsigned(status.raster_stack_free), unsigned(uxTaskGetStackHighWaterMark(nullptr)));
            ESP_LOGI(kTag,
                     "[FRAMEPERF] frame_work_us=%u frame_work_max_us=%u frames=%u "
                     "display_period_us=%u window_ms=%u optimized=%d drawing_reason=%s "
                     "alpha_est_is_sampled=1",
                     unsigned(perf.frame.Average()), unsigned(perf.frame.max_us),
                     unsigned(perf.frame.calls), unsigned(lcd.completed ? elapsed / lcd.completed : 0),
                     unsigned(elapsed / 1000), status.optimized_enabled, status.drawing_reason);
            const uint32_t processed = lcd.completed + lcd.unchanged;
            ESP_LOGI(kTag,
                "[RENDER2] profile=%s spi_mhz=%u stream=%d stream_reason=%s pixel_diff=%d diff_reason=%s "
                "unchanged=%u original_pixels=%u sent_pixels=%u compare_us=%u copy_swap_us=%u "
                "traversal_us=%u collect_us=%u edge_calc_total_us=%u edge_schedule_us=%u "
                "sram_min=%u psram_min=%u",
                cubicat::HomeRenderProfileName(status.profile), unsigned(status.spi_mhz),
                status.stream_enabled, status.stream_reason, status.pixel_diff_enabled, status.pixel_diff_reason,
                unsigned(lcd.unchanged), unsigned(processed ? lcd.original_pixels / processed : 0),
                unsigned(processed ? lcd.pixels / processed : 0), unsigned(lcd.compare.Average()),
                unsigned(transfers ? lcd.copy_swap_us / transfers : 0),
                unsigned(perf.traversal.Average()), unsigned(perf.drawable_collect.Average()),
                unsigned(perf.engine.calls ? perf.edges.total_us / perf.engine.calls : 0),
                unsigned(frames ? perf.edge_schedule.total_us / frames : 0),
                unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL)),
                unsigned(heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM)));
            cubicat::HomePerf().Reset();
            stats_started_us = now;
            tick_count = 0;
            render_time_us = 0;
            max_render_us = 0;
            surface.ResetStats();

            if (lvgl_overlay_ && lvgl_overlay_->update_count() > 0) {
                const uint32_t updates = lvgl_overlay_->update_count();
                const uint32_t avg_render = updates > 0 ? lvgl_overlay_->total_render_us() / updates : 0;
                const uint32_t avg_convert = updates > 0 ? lvgl_overlay_->total_convert_us() / updates : 0;
                ESP_LOGI(kTag,
                         "[LVOVPERF] updates=%u avg_render_us=%u "
                         "avg_convert_us=%u",
                         static_cast<unsigned>(updates), static_cast<unsigned>(avg_render),
                         static_cast<unsigned>(avg_convert));
                lvgl_overlay_->ResetPerfCounters();
            }
        }

        taskYIELD();
    }

    void SetCard(const McpCardData* data, CardView& out) {
        out = {};
        if (data != nullptr) {
            // Show the reference design and actions immediately.
            out.expanded = true;
            out.instance_id = Safe(data->instance_id);
            out.revision = data->revision;
            out.title = Safe(data->title);
            out.status = Safe(data->status);
            out.priority = Safe(data->priority);
            out.primary_label = Safe(data->primary_label);
            out.secondary_label = Safe(data->secondary_label);
            out.tertiary_label = Safe(data->tertiary_label);
            out.queue_count = std::max(0, data->queue_count);
            out.privacy_mode = data->privacy_mode;
            out.actionable =
                (!out.instance_id.empty() && !out.primary_label.empty()) ||
                (data->action_key != nullptr && data->action_key[0] != '\0');
            const int count = std::clamp(data->item_count, 0, 4);
            for (int index = 0; index < count; ++index) {
                if (data->items[index] != nullptr) {
                    out.items.emplace_back(data->items[index]);
                }
            }
        }
    }

    CardView card;
    int width = 0;
    int height = 0;
    std::atomic<bool> active{false};
    std::atomic<bool> foreground_ui{false};
    mutable std::mutex state_mutex;
    NativeSurface surface;
    CubicatHomePlayer::FrameSubmitter submitter;
    CubicatHomePlayer::UiActionHandler action_handler;
    cubicat::ResourceManager* resource_manager = nullptr;
    cubicat::TexturePtr background_texture;
    cubicat::TexturePtr spine_texture;
    std::unique_ptr<EmbedGameEngine> engine;
    SceneManager* scene = nullptr;
    cubicat::Renderer* renderer = nullptr;
    cubicat::Node2DPtr background_node;
    SpineAnimationPtr spine;

    cubicat::TextLabelPtr subtitle;
    cubicat::Node2DPtr network_icon;
    cubicat::Node2DPtr muted_icon;
    cubicat::TexturePtr wifi_connected_tex;
    cubicat::TexturePtr wifi_config_tex;
    cubicat::TexturePtr wifi_off_tex;
    cubicat::TexturePtr muted_tex;
    cubicat::Node2DPtr card_node;
    cubicat::TexturePtr card_placeholder_texture;
    bool mcp_ui_enabled = false;
    TouchSnapshot touch_snap_;

    std::string current_state = "idle";
    std::string persistent_status_text;
    std::string speaking_subtitle_text;
    std::string notification_text;
    NetworkUiState network_state = NetworkUiState::kDisconnected;
    bool muted_state = false;
    bool icons_synced = false;
    bool icons_enqueued_once = false;
    bool network_pending_valid = false;
    bool muted_pending_valid = false;
    bool status_pending_valid = false;
    bool card_animating = false;
    bool card_animation_showing = false;
    uint32_t card_animation_started_ms = 0;
    int card_screen_top = 0;
    uint32_t notification_until_ms = 0;
    uint32_t notification_duration_ms = 3000;
    bool notification_deferred = false;
    DialoguePhase dialogue_phase = DialoguePhase::Hidden;
    int animation_from_y = kDialogueHiddenY;
    int animation_to_y = kDialogueHiddenY;
    uint32_t dialogue_animation_started_ms = 0;
    uint32_t dialogue_pending_hide_ms = 0;
    int dialogue_screen_y = kDialogueHiddenY;
    std::string dialogue_rendered_text;
    std::string dialogue_scroll_text;
    bool dialogue_scroll_is_notification = false;
    int dialogue_text_width = 0;
    int dialogue_scroll_offset_px = 0;
    int dialogue_rendered_offset_px = -1;
    uint32_t dialogue_scroll_started_ms = 0;
    uint32_t dialogue_scroll_last_render_ms = 0;
    bool first_frame_logged = false;
    int64_t stats_started_us = 0;
    uint32_t tick_count = 0;
    uint64_t render_time_us = 0;
    uint32_t max_render_us = 0;

    std::string pending_state;
    std::string pending_emotion;
    std::string pending_subtitle_role;
    std::string pending_subtitle_text;
    std::string pending_notification_text;
    uint32_t pending_notification_duration_ms = 0;
    std::string pending_status_text;
    std::string pending_level_type;
    int pending_level_value = 0;
    uint32_t pending_level_duration_ms = 1500;
    NetworkUiState pending_network_state = NetworkUiState::kDisconnected;
    bool pending_muted = false;
    CardView pending_mcp_card;
    std::string pending_background_id;

    bool dirty_state = false;
    bool dirty_emotion = false;
    bool dirty_subtitle = false;
    bool dirty_notification = false;
    bool dirty_status_text = false;
    bool dirty_level = false;
    bool dirty_network = false;
    bool dirty_muted = false;
    bool dirty_mcp_show = false;
    bool dirty_mcp_dismiss = false;
    bool dirty_card_action = false;
    std::string pending_card_action_instance_id;
    uint32_t pending_card_action_revision = 0;
    std::string pending_card_action;
    bool dirty_background = false;

    std::unique_ptr<CubicatLvglOverlay> lvgl_overlay_;
    cubicat::Node2DPtr dialogue_node;
    cubicat::TexturePtr dialogue_placeholder_tex;
    cubicat::Node2DPtr level_overlay_node;
    cubicat::TexturePtr level_placeholder_tex;
    bool level_overlay_visible = false;
    uint32_t level_overlay_hide_ms = 0;

    cubicat::Node2DPtr spine_ota_node;
    cubicat::TexturePtr spine_ota_placeholder_tex;
    bool spine_ota_visible = false;
    bool dirty_spine_ota = false;
    bool pending_spine_ota_dismiss = false;
    std::string pending_spine_ota_title;
    std::string pending_spine_ota_detail;
    int pending_spine_ota_progress = -1;

    void ApplySpineOtaUi() {
        if (!spine_ota_node) return;
        if (pending_spine_ota_dismiss) {
            spine_ota_node->setVisible(false);
            spine_ota_visible = false;
            pending_spine_ota_dismiss = false;
            return;
        }
        if (lvgl_overlay_ && lvgl_overlay_->IsReady()) {
            auto tex = lvgl_overlay_->RenderSpineOta(
                pending_spine_ota_title.c_str(),
                pending_spine_ota_detail.c_str(),
                pending_spine_ota_progress);
            if (tex) {
                auto drawable = spine_ota_node->getDrawable(0);
                if (drawable) {
                    drawable->getMaterial()->setTexture(tex);
                    spine_ota_node->setVisible(true);
                    spine_ota_visible = true;
                }
            }
        } else {
            // UI optional — OTA logic must still proceed without overlay.
            ESP_LOGW(kTag, "Spine OTA UI unavailable; status title=%s",
                     pending_spine_ota_title.c_str());
        }
    }
};

CubicatHomePlayer::CubicatHomePlayer() = default;
CubicatHomePlayer::~CubicatHomePlayer() = default;

bool CubicatHomePlayer::Start(int width,
                              int height,
                              FrameSubmitter submitter,
                              UiActionHandler action_handler) {
    impl_ = std::make_unique<Impl>();
    if (impl_->Initialize(
            width, height, std::move(submitter),
            std::move(action_handler))) {
        return true;
    }
    impl_.reset();
    return false;
}

void CubicatHomePlayer::Stop() {
    impl_.reset();
}

void CubicatHomePlayer::SetActive(bool active) {
    if (impl_ == nullptr) return;
    impl_->active.store(active, std::memory_order_relaxed);
}

bool CubicatHomePlayer::IsActive() const {
    if (impl_ == nullptr) return false;
    return impl_->active.load(std::memory_order_relaxed);
}

void CubicatHomePlayer::Tick() {
    if (impl_ == nullptr) return;
    if (!impl_->active.load(std::memory_order_relaxed)) return;

    Impl::PendingSnapshot snap;
    {
        std::lock_guard<std::mutex> lock(impl_->state_mutex);
        snap = impl_->TakePendingSnapshot();
    }
    const uint32_t now_ms =
        static_cast<uint32_t>(esp_timer_get_time() / 1000);
    impl_->ProcessPending(snap);
    impl_->ApplyUiAnimations(now_ms);
    {
        std::lock_guard<std::mutex> lock(impl_->state_mutex);
        impl_->PublishTouchSnapshot();
    }
    impl_->foreground_ui.store(
        impl_->card.visible || impl_->card_animating ||
        impl_->dialogue_phase != Impl::DialoguePhase::Hidden ||
        !impl_->notification_text.empty() || impl_->level_overlay_visible ||
        impl_->spine_ota_visible, std::memory_order_relaxed);
    impl_->TickRender();
}

void CubicatHomePlayer::ResumeAfterStandby() {
    if (!impl_) return;
    impl_->engine->resetTiming();
    // Reset existing perf window as well: standby must not look like slow frames.
    impl_->stats_started_us = esp_timer_get_time();
    impl_->tick_count = 0;
    impl_->render_time_us = 0;
    impl_->max_render_us = 0;
    impl_->surface.ResetStats();
    impl_->active.store(true, std::memory_order_relaxed);
}

bool CubicatHomePlayer::HasForegroundUi() const {
    if (!impl_) return false;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    // Pending messages must block standby even before the render task sees them.
    return impl_->foreground_ui.load(std::memory_order_relaxed) ||
        impl_->dirty_mcp_show || impl_->dirty_level || impl_->dirty_spine_ota ||
        (impl_->dirty_subtitle && !impl_->pending_subtitle_text.empty()) ||
        (impl_->dirty_notification && !impl_->pending_notification_text.empty());
}

bool CubicatHomePlayer::PresentFullFrame() {
    if (impl_ == nullptr) return false;
    return impl_->surface.PresentFullFrame();
}

void CubicatHomePlayer::SetState(const char* state) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    const char* value = state == nullptr ? "idle" : state;
    impl_->pending_state = value;
    impl_->dirty_state = true;
    impl_->LogQueueEvent("state");
}

void CubicatHomePlayer::SetEmotion(const char* emotion) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    const char* value = emotion == nullptr ? "neutral" : emotion;
    impl_->pending_emotion = value;
    impl_->dirty_emotion = true;
    impl_->LogQueueEvent("emotion");
}

void CubicatHomePlayer::SetSubtitle(const char* role, const char* text) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->pending_subtitle_role = Safe(role);
    impl_->pending_subtitle_text = Safe(text);
    impl_->dirty_subtitle = true;
    impl_->LogQueueEvent("subtitle");
}

void CubicatHomePlayer::ShowNotification(const char* text,
                                         uint32_t duration_ms) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->pending_notification_text = Safe(text);
    if (duration_ms == 0) duration_ms = 3000;
    impl_->pending_notification_duration_ms = duration_ms;
    impl_->dirty_notification = true;
    impl_->LogQueueEvent("notification");
}

void CubicatHomePlayer::ShowMcpCard(const McpCardData* card) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->SetCard(card, impl_->pending_mcp_card);
    // Log the immutable pending snapshot, not the previously visible card.
    const auto& view = impl_->pending_mcp_card;
    ESP_LOGI(kTag,
             "[REMINDER_CARD] event=ui_show_queued reason=display_show "
             "instance=%s rev=%u visible=0 expanded=%d actionable=%d "
             "rect=%d,%d,%d,%d title=\"%s\" item0=\"%s\" actions=\"%s|%s|%s\"",
             view.instance_id.c_str(),
             static_cast<unsigned>(view.revision),
             view.expanded ? 1 : 0, view.actionable ? 1 : 0,
             impl_->CardLeft(), impl_->CardShownTop(view.expanded), kCardWidth,
             mcp_card_layout::Height(view.expanded), view.title.c_str(),
             view.items.empty() ? "" : view.items[0].c_str(),
             view.primary_label.c_str(), view.secondary_label.c_str(),
             view.tertiary_label.c_str());
    impl_->dirty_mcp_show = true;
    impl_->LogQueueEvent("mcp_show");
}

void CubicatHomePlayer::DismissMcpCard() {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->dirty_mcp_dismiss = true;
    impl_->LogCardLifecycle("ui_dismiss_queued", "display_dismiss");
    impl_->LogQueueEvent("mcp_dismiss");
}

bool CubicatHomePlayer::HandleTouch(float x, float y) {
    if (impl_ == nullptr) return false;
    if (!impl_->active.load(std::memory_order_relaxed)) return false;

    const float screen_x = x <= 1.0f ? x * impl_->width : x;
    const float screen_y = y <= 1.0f ? y * impl_->height : y;

    // Block touch while role update status is visible.
    {
        std::lock_guard<std::mutex> lock(impl_->state_mutex);
        if (impl_->spine_ota_visible) {
            return true;
        }
    }

    // Never call JS on the touch thread; only read TouchSnapshot.
    Impl::TouchSnapshot snap;
    {
        std::lock_guard<std::mutex> lock(impl_->state_mutex);
        snap = impl_->touch_snap_;
    }

    if (!snap.card_visible || snap.animating_out) return false;

    if (screen_x < snap.left || screen_x > snap.right ||
        screen_y < snap.top || screen_y > snap.bottom) {
        ESP_LOGI(kTag,
                 "[REMINDER_CARD] event=touch_ignored reason=outside "
                 "instance=%s rev=%u raw=%.1f,%.1f screen=%.1f,%.1f "
                 "rect=%.1f,%.1f,%.1f,%.1f",
                 snap.instance_id.c_str(),
                 static_cast<unsigned>(snap.revision), x, y, screen_x, screen_y,
                 snap.left, snap.top, snap.right, snap.bottom);
        return false;
    }

    std::string action;
    if (snap.card_expanded) {
        const float local_x = screen_x - snap.left;
        const float local_y = screen_y - snap.top;
        if (snap.card_actionable &&
            local_y >= mcp_card_layout::ActionAreaTop(snap.card_has_tertiary)) {
            const int index = mcp_card_layout::HitButton(local_x, local_y, snap.card_has_tertiary);
            if (index < 0) return true;  // Gaps and bottom padding are inert.
            static constexpr const char* actions[] = {"primary", "secondary", "tertiary"};
            action = actions[index];
        } else {
            action = "collapse";
        }
    } else {
        action = "expand";
    }

    {
        std::lock_guard<std::mutex> lock(impl_->state_mutex);
        impl_->pending_card_action_instance_id = snap.instance_id;
        impl_->pending_card_action_revision = snap.revision;
        impl_->pending_card_action = action;
        impl_->dirty_card_action = true;
        impl_->LogQueueEvent("card_action");
    }
    ESP_LOGI(kTag,
             "[REMINDER_CARD] event=touch_action instance=%s rev=%u "
             "action=%s raw=%.1f,%.1f screen=%.1f,%.1f rect=%.1f,%.1f,%.1f,%.1f",
             snap.instance_id.c_str(), static_cast<unsigned>(snap.revision),
             action.c_str(), x, y, screen_x, screen_y,
             snap.left, snap.top, snap.right, snap.bottom);
    return true;
}

void CubicatHomePlayer::SetNetworkState(NetworkUiState state) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    if (state == impl_->pending_network_state &&
        impl_->network_pending_valid &&
        impl_->icons_enqueued_once) {
        return;
    }
    impl_->pending_network_state = state;
    impl_->network_pending_valid = true;
    impl_->dirty_network = true;
    impl_->LogQueueEvent("network");
}

void CubicatHomePlayer::SetMuted(bool muted) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    if (muted == impl_->pending_muted &&
        impl_->muted_pending_valid &&
        impl_->icons_enqueued_once) {
        return;
    }
    impl_->pending_muted = muted;
    impl_->muted_pending_valid = true;
    impl_->dirty_muted = true;
    impl_->LogQueueEvent("muted");
}

void CubicatHomePlayer::SetStatusText(const char* text) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    const std::string safe_text = Safe(text);
    if (impl_->status_pending_valid &&
        safe_text == impl_->pending_status_text) {
        return;
    }
    impl_->pending_status_text = safe_text;
    impl_->status_pending_valid = true;
    impl_->dirty_status_text = true;
    impl_->LogQueueEvent("status_text");
}

void CubicatHomePlayer::SetBackground(const char* background_id) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    const char* value = background_id == nullptr ? "room" : background_id;
    impl_->pending_background_id = value;
    impl_->dirty_background = true;
    impl_->LogQueueEvent("background");
}

void CubicatHomePlayer::ShowLevelOverlay(const char* type, int value,
                                          uint32_t duration_ms) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->pending_level_type = type == nullptr ? "volume" : type;
    impl_->pending_level_value = value;
    if (duration_ms == 0) duration_ms = 1500;
    impl_->pending_level_duration_ms = duration_ms;
    impl_->dirty_level = true;
    impl_->LogQueueEvent("level_overlay");
}

void CubicatHomePlayer::ShowSpineOtaStatus(const char* title,
                                           const char* detail,
                                           int progress) {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->pending_spine_ota_dismiss = false;
    impl_->pending_spine_ota_title = title == nullptr ? "" : title;
    impl_->pending_spine_ota_detail = detail == nullptr ? "" : detail;
    impl_->pending_spine_ota_progress = progress;
    impl_->dirty_spine_ota = true;
    impl_->LogQueueEvent("spine_ota");
}

void CubicatHomePlayer::DismissSpineOtaStatus() {
    if (impl_ == nullptr) return;
    std::lock_guard<std::mutex> lock(impl_->state_mutex);
    impl_->pending_spine_ota_dismiss = true;
    impl_->dirty_spine_ota = true;
    impl_->LogQueueEvent("spine_ota_dismiss");
}
