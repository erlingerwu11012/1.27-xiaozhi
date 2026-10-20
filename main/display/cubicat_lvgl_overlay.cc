#include "cubicat_lvgl_overlay.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <string>

#include "assets.h"
#include "cbin_font.h"
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "font_awesome.h"
#include "lvgl.h"
#include "mcp_card_layout.h"
#include "src/misc/cache/instance/lv_image_cache.h"
#include "src/misc/cache/instance/lv_image_header_cache.h"

namespace {
constexpr const char* kTag = "CubicatLvgl";
constexpr int64_t kRefrTimeoutUs = 500000;  // 500ms
constexpr const char* kCbinTextFontName = "font_puhui_common_20_4.bin";
constexpr const char* kCbinSubtitleFontName = "font_puhui_common_16_4.bin";
constexpr int kGlassDownsample = 4;
using PsramRgbBuffer = std::unique_ptr<uint32_t, decltype(&heap_caps_free)>;

uint32_t MixRgb(uint32_t background, uint32_t foreground, unsigned opacity) {
    const unsigned inverse = 255 - opacity;
    const uint32_t red = (((background >> 16) & 255) * inverse +
                          ((foreground >> 16) & 255) * opacity + 127) / 255;
    const uint32_t green = (((background >> 8) & 255) * inverse +
                            ((foreground >> 8) & 255) * opacity + 127) / 255;
    const uint32_t blue = ((background & 255) * inverse +
                           (foreground & 255) * opacity + 127) / 255;
    return (red << 16) | (green << 8) | blue;
}

// Two separable box passes on a quarter-resolution wallpaper. This is only
// called when the wallpaper changes, never during a character animation.
void BlurGlassRgb(uint32_t* pixels, uint32_t* scratch, int width, int height) {
    constexpr int radius = 2;
    constexpr int samples = radius * 2 + 1;
    for (int pass = 0; pass < 2; ++pass) {
        for (int axis = 0; axis < 2; ++axis) {
            const uint32_t* src = axis == 0 ? pixels : scratch;
            uint32_t* dst = axis == 0 ? scratch : pixels;
            const int length = axis == 0 ? width : height;
            const int lines = axis == 0 ? height : width;
            for (int line = 0; line < lines; ++line) {
                auto sample = [&](int position) {
                    position = std::clamp(position, 0, length - 1);
                    return src[axis == 0 ? line * width + position
                                         : position * width + line];
                };
                int red = 0, green = 0, blue = 0;
                auto accumulate = [&](uint32_t rgb, int sign) {
                    red += sign * static_cast<int>((rgb >> 16) & 255);
                    green += sign * static_cast<int>((rgb >> 8) & 255);
                    blue += sign * static_cast<int>(rgb & 255);
                };
                for (int offset = -radius; offset <= radius; ++offset) {
                    accumulate(sample(offset), 1);
                }
                for (int position = 0; position < length; ++position) {
                    dst[axis == 0 ? line * width + position
                                  : position * width + line] =
                        ((red / samples) << 16) | ((green / samples) << 8) |
                        (blue / samples);
                    accumulate(sample(position - radius), -1);
                    accumulate(sample(position + radius + 1), 1);
                }
            }
        }
    }
}

// LVGL ARGB8888 uint32 (0xAARRGGBB) -> Cubicat RRGGBBAA
inline uint32_t ToRrggbbaa(uint32_t argb) {
    return (argb >> 24) | (argb << 8);
}

extern "C" {
extern const lv_font_t font_puhui_basic_20_4;
extern const lv_font_t font_puhui_basic_16_4;
extern const lv_font_t font_awesome_20_4;
}

static void OffscreenFlushCb(lv_display_t* display,
                             const lv_area_t* /*area*/,
                             uint8_t* /*px_map*/) {
    // Off-screen only: never touch esp_lcd / SPI / ST7796.
    lv_display_flush_ready(display);
}

}  // namespace

class CubicatLvglOverlay::Impl {
public:
    ~Impl() {
        if (disp_ != nullptr) {
            if (screen_ != nullptr) {
                lv_obj_clean(screen_);
            }
            lv_display_delete(disp_);
            disp_ = nullptr;
            screen_ = nullptr;
        }
        if (draw_buf_ != nullptr) {
            delete draw_buf_;
            draw_buf_ = nullptr;
        }
        if (draw_buf_raw_ != nullptr) {
            heap_caps_free(draw_buf_raw_);
            draw_buf_raw_ = nullptr;
        }
        if (owned_text_font_ != nullptr) {
            cbin_font_delete(owned_text_font_);
            owned_text_font_ = nullptr;
        }
        if (owned_subtitle_font_ != nullptr) {
            cbin_font_delete(owned_subtitle_font_);
            owned_subtitle_font_ = nullptr;
        }
        text_font_ = nullptr;
        subtitle_font_ = nullptr;
    }

    void LoadTextFont() {
        void* ptr = nullptr;
        size_t size = 0;
        if (Assets::GetInstance().GetAssetData(kCbinTextFontName, ptr, size) &&
            ptr != nullptr && size > 0) {
            // Asset mmap pointer must remain valid for font lifetime.
            owned_text_font_ =
                cbin_font_create(static_cast<uint8_t*>(ptr));
            if (owned_text_font_ != nullptr) {
                text_font_ = owned_text_font_;
                ESP_LOGI(kTag,
                         "[LVOVFONT] source=assets_cbin name=%s bytes=%u "
                         "result=ok",
                         kCbinTextFontName,
                         static_cast<unsigned>(size));
                return;
            }
            ESP_LOGW(kTag,
                     "[LVOVERR] stage=font code=cbin_create_failed name=%s",
                     kCbinTextFontName);
        } else {
            ESP_LOGW(kTag,
                     "[LVOVERR] stage=font code=asset_missing name=%s",
                     kCbinTextFontName);
        }

        text_font_ = &font_puhui_basic_20_4;
        ESP_LOGW(kTag,
                 "[LVOVFONT] source=builtin_basic result=fallback "
                 "limited_glyphs=1");
    }

    void LoadSubtitleFont() {
        void* ptr = nullptr;
        size_t size = 0;
        if (Assets::GetInstance().GetAssetData(kCbinSubtitleFontName, ptr, size) &&
            ptr != nullptr && size > 0) {
            // Asset mmap pointer must remain valid for font lifetime.
            owned_subtitle_font_ =
                cbin_font_create(static_cast<uint8_t*>(ptr));
            if (owned_subtitle_font_ != nullptr) {
                subtitle_font_ = owned_subtitle_font_;
                ESP_LOGI(kTag,
                         "[LVOVFONT] source=assets_cbin name=%s bytes=%u "
                         "result=ok",
                         kCbinSubtitleFontName,
                         static_cast<unsigned>(size));
                return;
            }
            ESP_LOGW(kTag,
                     "[LVOVERR] stage=subtitle_font code=cbin_create_failed "
                     "name=%s",
                     kCbinSubtitleFontName);
        } else {
            ESP_LOGW(kTag,
                     "[LVOVERR] stage=subtitle_font code=asset_missing name=%s",
                     kCbinSubtitleFontName);
        }

        subtitle_font_ = &font_puhui_basic_16_4;
        ESP_LOGW(kTag,
                 "[LVOVFONT] source=builtin_basic_16 result=fallback "
                 "limited_glyphs=1");
    }

    bool Initialize(int width, int height) {
        lv_init();
        ESP_LOGI(kTag,
                 "[LVOVINIT] stage=lv_init result=ok sram=%u psram=%u",
                 static_cast<unsigned>(
                     heap_caps_get_free_size(MALLOC_CAP_INTERNAL)),
                 static_cast<unsigned>(
                     heap_caps_get_free_size(MALLOC_CAP_SPIRAM)));

        const size_t buf_bytes =
            static_cast<size_t>(width) * height * 4;
        draw_buf_raw_ = static_cast<uint8_t*>(heap_caps_malloc(
            buf_bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (draw_buf_raw_ == nullptr) {
            ESP_LOGE(kTag, "[LVOVERR] stage=buffer code=no_psram");
            return false;
        }
        std::memset(draw_buf_raw_, 0, buf_bytes);

        draw_buf_ = new lv_draw_buf_t;
        if (lv_draw_buf_init(draw_buf_,
                             static_cast<uint32_t>(width),
                             static_cast<uint32_t>(height),
                             LV_COLOR_FORMAT_ARGB8888,
                             LV_STRIDE_AUTO,
                             draw_buf_raw_,
                             buf_bytes) != LV_RESULT_OK) {
            ESP_LOGE(kTag, "[LVOVERR] stage=buffer code=init_failed");
            return false;
        }
        ESP_LOGI(kTag,
                 "[LVOVINIT] stage=buffer_ready location=psram bytes=%u",
                 static_cast<unsigned>(buf_bytes));

        disp_ = lv_display_create(width, height);
        if (disp_ == nullptr) {
            ESP_LOGE(kTag, "[LVOVERR] stage=display code=create_failed");
            return false;
        }
        lv_display_set_color_format(disp_, LV_COLOR_FORMAT_ARGB8888);
        lv_display_set_draw_buffers(disp_, draw_buf_, nullptr);
        lv_display_set_render_mode(disp_, LV_DISPLAY_RENDER_MODE_DIRECT);
        lv_display_set_flush_cb(disp_, OffscreenFlushCb);
        lv_display_set_default(disp_);

        screen_ = lv_display_get_screen_active(disp_);
        if (screen_ == nullptr) {
            ESP_LOGE(kTag, "[LVOVERR] stage=display code=no_screen");
            return false;
        }
        lv_obj_set_style_bg_color(screen_, lv_color_hex(0x000000), 0);
        lv_obj_set_style_bg_opa(screen_, LV_OPA_TRANSP, 0);
        lv_obj_set_style_pad_all(screen_, 0, 0);
        lv_obj_set_style_border_width(screen_, 0, 0);

        ESP_LOGI(kTag,
                 "[LVOVINIT] stage=display format=ARGB8888 flush=offscreen");

        LoadTextFont();
        LoadSubtitleFont();
        icon_font_ = &font_awesome_20_4;
        ESP_LOGI(kTag,
                 "[LVOVINIT] stage=font_ready icon_font=awesome_20_4");

        screen_w_ = width;
        screen_h_ = height;

        if (!DoColorTest()) {
            ESP_LOGE(kTag, "[LVOVERR] stage=color_test code=fail");
            return false;
        }

        ready_ = true;
        ESP_LOGI(kTag, "[LVOVINIT] stage=ready result=ok");
        return true;
    }

    bool IsReady() const { return ready_; }

    uint32_t total_convert_us() const { return total_convert_us_; }
    void ResetConvertUs() { total_convert_us_ = 0; }

    bool RefrNow() {
        if (disp_ == nullptr) return false;
        const int64_t t0 = esp_timer_get_time();
        lv_refr_now(disp_);
        const int64_t elapsed = esp_timer_get_time() - t0;
        if (elapsed > kRefrTimeoutUs) {
            ESP_LOGE(kTag,
                     "[LVOVERR] stage=refr code=timeout us=%lld",
                     static_cast<long long>(elapsed));
            return false;
        }
        return true;
    }

    void ClearScreen() {
        if (screen_ == nullptr) return;
        // Snapshot uses its own buffer; only clean screen objects.
        lv_obj_clean(screen_);
    }

    // Convert ARGB snapshot (with stride) into RRGGBBAA Cubicat texture.
    cubicat::TexturePtr ConvertDrawBuf(const lv_draw_buf_t* src,
                                       const char* kind) {
        if (src == nullptr || src->data == nullptr) {
            return cubicat::TexturePtr(nullptr);
        }
        const int w = static_cast<int>(src->header.w);
        const int h = static_cast<int>(src->header.h);
        const uint32_t stride = src->header.stride;
        if (w <= 0 || h <= 0 || stride < static_cast<uint32_t>(w) * 4) {
            ESP_LOGE(kTag,
                     "[LVOVERR] stage=convert code=bad_geom w=%d h=%d "
                     "stride=%u",
                     w, h, static_cast<unsigned>(stride));
            return cubicat::TexturePtr(nullptr);
        }

        const size_t pc = static_cast<size_t>(w) * h;
        auto* converted = static_cast<uint32_t*>(heap_caps_malloc(
            pc * sizeof(uint32_t),
            MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        if (converted == nullptr) {
            ESP_LOGE(kTag, "[LVOVERR] stage=convert code=no_psram");
            return cubicat::TexturePtr(nullptr);
        }

        const int64_t t0 = esp_timer_get_time();
        const uint8_t* base = static_cast<const uint8_t*>(src->data);
        for (int y = 0; y < h; ++y) {
            const auto* row =
                reinterpret_cast<const uint32_t*>(base + y * stride);
            uint32_t* dst = converted + static_cast<size_t>(y) * w;
            for (int x = 0; x < w; ++x) {
                dst[x] = ToRrggbbaa(row[x]);
            }
        }
        const uint32_t convert_us =
            static_cast<uint32_t>(esp_timer_get_time() - t0);
        total_convert_us_ += convert_us;

        auto tex = cubicat::Texture::create(
            static_cast<uint16_t>(w),
            static_cast<uint16_t>(h),
            converted, true, 1, 1, nullptr, 32, true);
        if (!tex) {
            heap_caps_free(converted);
            ESP_LOGE(kTag, "[LVOVERR] stage=convert code=texture_create");
            return cubicat::TexturePtr(nullptr);
        }
        if (std::strcmp(kind, "dialog") == 0) {
            ESP_LOGD(kTag,
                     "[LVOVRENDER] kind=%s w=%d h=%d stride=%u convert_us=%u",
                     kind, w, h, static_cast<unsigned>(stride),
                     static_cast<unsigned>(convert_us));
        } else {
            ESP_LOGI(kTag,
                     "[LVOVRENDER] kind=%s w=%d h=%d stride=%u convert_us=%u",
                     kind, w, h, static_cast<unsigned>(stride),
                     static_cast<unsigned>(convert_us));
        }
        return tex;
    }

    cubicat::TexturePtr SnapshotObj(lv_obj_t* obj, const char* kind) {
        if (obj == nullptr) return cubicat::TexturePtr(nullptr);
        lv_obj_update_layout(obj);
        lv_draw_buf_t* snap =
            lv_snapshot_take(obj, LV_COLOR_FORMAT_ARGB8888);
        if (snap == nullptr) {
            ESP_LOGE(kTag, "[LVOVERR] stage=snapshot code=take_failed");
            return cubicat::TexturePtr(nullptr);
        }
        auto tex = ConvertDrawBuf(snap, kind);
        lv_draw_buf_destroy(snap);
        return tex;
    }

    bool CheckPixel(const char* name,
                    uint32_t raw,
                    uint32_t expected_rrggbbaa) {
        const uint32_t actual = ToRrggbbaa(raw);
        const bool ok = (actual == expected_rrggbbaa);
        ESP_LOGI(kTag,
                 "[LVOVFMT] case=%s expected=0x%08lx actual=0x%08lx "
                 "raw=0x%08lx result=%s",
                 name,
                 static_cast<unsigned long>(expected_rrggbbaa),
                 static_cast<unsigned long>(actual),
                 static_cast<unsigned long>(raw),
                 ok ? "pass" : "fail");
        return ok;
    }

    bool DoColorTest() {
        struct Case {
            const char* name;
            uint32_t rgb;
            uint8_t alpha;
            uint32_t expected;  // RRGGBBAA
        };
        const Case cases[] = {
            {"red", 0xFF0000, 255, 0xFF0000FF},
            {"green", 0x00FF00, 255, 0x00FF00FF},
            {"blue", 0x0000FF, 255, 0x0000FFFF},
            {"alpha", 0x0C1014, 195, 0x0C1014C3},
        };

        bool all_ok = true;
        for (const auto& c : cases) {
            ClearScreen();
            // Color test reads draw_buf_raw_ at (0,0); clear a small region.
            if (draw_buf_raw_ != nullptr) {
                std::memset(draw_buf_raw_, 0, 8 * 8 * 4);
            }
            lv_obj_t* box = lv_obj_create(screen_);
            lv_obj_set_size(box, 8, 8);
            lv_obj_set_pos(box, 0, 0);
            lv_obj_set_style_radius(box, 0, 0);
            lv_obj_set_style_border_width(box, 0, 0);
            lv_obj_set_style_pad_all(box, 0, 0);
            lv_obj_set_style_bg_color(box, lv_color_hex(c.rgb), 0);
            lv_obj_set_style_bg_opa(box, c.alpha, 0);

            if (!RefrNow()) {
                all_ok = false;
                continue;
            }

            const auto* row0 =
                reinterpret_cast<const uint32_t*>(draw_buf_raw_);
            if (!CheckPixel(c.name, row0[0], c.expected)) {
                all_ok = false;
            }

            lv_draw_buf_t* snap =
                lv_snapshot_take(box, LV_COLOR_FORMAT_ARGB8888);
            if (snap != nullptr && snap->data != nullptr) {
                const auto* px =
                    reinterpret_cast<const uint32_t*>(snap->data);
                if (!CheckPixel(c.name, px[0], c.expected)) {
                    all_ok = false;
                }
                lv_draw_buf_destroy(snap);
            } else {
                ESP_LOGE(kTag,
                         "[LVOVERR] stage=color_test code=snapshot_%s",
                         c.name);
                all_ok = false;
            }
        }
        ClearScreen();
        return all_ok;
    }

    int MeasureDialogueTextWidth(const char* text) const {
        if (!ready_ || subtitle_font_ == nullptr || text == nullptr ||
            text[0] == '\0') {
            return 0;
        }
        lv_point_t text_size{};
        lv_text_get_size(&text_size, text, subtitle_font_, 0, 0,
                         LV_COORD_MAX, LV_TEXT_FLAG_NONE);
        return std::max(0, static_cast<int>(text_size.x));
    }

    cubicat::TexturePtr RenderDialogue(const char* text,
                                       int scroll_offset_px) {
        if (!ready_) return cubicat::TexturePtr(nullptr);
        constexpr int kW = 296;
        constexpr int kH = 28;
        constexpr int kTextPillW = 248;
        constexpr int kActivityPillW = 40;
        constexpr int kPillGap = 8;
        const int64_t t0 = esp_timer_get_time();
        ClearScreen();

        lv_obj_t* dock = lv_obj_create(screen_);
        lv_obj_set_size(dock, kW, kH);
        lv_obj_set_pos(dock, 0, 0);
        lv_obj_set_style_bg_opa(dock, LV_OPA_TRANSP, 0);
        lv_obj_set_style_border_width(dock, 0, 0);
        lv_obj_set_style_pad_all(dock, 0, 0);
        lv_obj_clear_flag(dock, LV_OBJ_FLAG_SCROLLABLE);

        // Main subtitle is deliberately compact and unobtrusive.
        lv_obj_t* subtitle_pill = lv_obj_create(dock);
        lv_obj_set_size(subtitle_pill, kTextPillW, kH);
        lv_obj_set_pos(subtitle_pill, 0, 0);
        lv_obj_set_style_radius(subtitle_pill, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(subtitle_pill, lv_color_hex(0x233C68), 0);
        lv_obj_set_style_bg_opa(subtitle_pill, 150, 0);
        lv_obj_set_style_border_width(subtitle_pill, 0, 0);
        lv_obj_set_style_pad_left(subtitle_pill, 12, 0);
        lv_obj_set_style_pad_right(subtitle_pill, 10, 0);
        lv_obj_set_style_pad_top(subtitle_pill, 0, 0);
        lv_obj_set_style_pad_bottom(subtitle_pill, 0, 0);
        lv_obj_clear_flag(subtitle_pill, LV_OBJ_FLAG_SCROLLABLE);
        // This is a viewport for a manually shifted, off-screen-rendered
        // label.  Children must stay clipped to the pill.
        lv_obj_clear_flag(subtitle_pill, LV_OBJ_FLAG_OVERFLOW_VISIBLE);

        lv_obj_t* label = lv_label_create(subtitle_pill);
        lv_obj_set_style_text_font(label, subtitle_font_, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(0xBFD5FF), 0);
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_LEFT, 0);
        // LVGL is rendered into a static texture here, so its own label
        // animation cannot advance after SnapshotObj.  Give the label its
        // full text width and let CubicatHomePlayer advance this offset.
        const char* visible_text = text == nullptr ? "" : text;
        const int text_width = MeasureDialogueTextWidth(visible_text);
        lv_label_set_long_mode(label, LV_LABEL_LONG_CLIP);
        lv_obj_set_width(label,
                         std::max(kTextPillW - 22, text_width));
        lv_label_set_text(label, visible_text);
        lv_obj_align(label, LV_ALIGN_LEFT_MID,
                     -std::max(0, scroll_offset_px), 0);

        // The separate three-dot pill communicates ongoing speech without
        // turning every line of dialogue into a reminder card.
        lv_obj_t* activity_pill = lv_obj_create(dock);
        lv_obj_set_size(activity_pill, kActivityPillW, kH);
        lv_obj_set_pos(activity_pill, kTextPillW + kPillGap, 0);
        lv_obj_set_style_radius(activity_pill, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_color(activity_pill, lv_color_hex(0x162846), 0);
        lv_obj_set_style_bg_opa(activity_pill, 150, 0);
        lv_obj_set_style_border_width(activity_pill, 0, 0);
        lv_obj_set_style_pad_all(activity_pill, 0, 0);
        lv_obj_clear_flag(activity_pill, LV_OBJ_FLAG_SCROLLABLE);
        for (int index = 0; index < 3; ++index) {
            lv_obj_t* dot = lv_obj_create(activity_pill);
            lv_obj_set_size(dot, 4, 4);
            lv_obj_set_pos(dot, 10 + index * 8, 12);
            lv_obj_set_style_radius(dot, LV_RADIUS_CIRCLE, 0);
            lv_obj_set_style_bg_color(dot, lv_color_hex(0x82AEF4), 0);
            lv_obj_set_style_bg_opa(dot, LV_OPA_COVER, 0);
            lv_obj_set_style_border_width(dot, 0, 0);
            lv_obj_clear_flag(dot, LV_OBJ_FLAG_SCROLLABLE);
        }

        auto tex = SnapshotObj(dock, "dialog");
        const uint32_t render_us =
            static_cast<uint32_t>(esp_timer_get_time() - t0);
        ESP_LOGD(kTag,
                 "[LVOVRENDER] kind=dialog w=%d h=%d offset=%d render_us=%u",
                 kW, kH, std::max(0, scroll_offset_px),
                 static_cast<unsigned>(render_us));
        ClearScreen();
        return tex;
    }

    cubicat::TexturePtr RenderSpineOta(const char* title,
                                       const char* detail,
                                       int progress) {
        if (!ready_) return cubicat::TexturePtr(nullptr);
        constexpr int kW = 280;
        constexpr int kH = 120;
        const int64_t t0 = esp_timer_get_time();
        ClearScreen();

        lv_obj_t* panel = lv_obj_create(screen_);
        lv_obj_set_size(panel, kW, kH);
        lv_obj_set_pos(panel, 0, 0);
        lv_obj_set_style_radius(panel, 10, 0);
        lv_obj_set_style_bg_color(panel, lv_color_hex(0x1A1510), 0);
        lv_obj_set_style_bg_opa(panel, 230, 0);
        lv_obj_set_style_border_width(panel, 1, 0);
        lv_obj_set_style_border_color(panel, lv_color_hex(0xFFE7C4), 0);
        lv_obj_set_style_pad_all(panel, 12, 0);
        lv_obj_clear_flag(panel, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_t* title_lbl = lv_label_create(panel);
        lv_obj_set_style_text_font(title_lbl, text_font_, 0);
        lv_obj_set_style_text_color(title_lbl, lv_color_hex(0xFFF8EC), 0);
        lv_label_set_long_mode(title_lbl, LV_LABEL_LONG_DOT);
        lv_obj_set_width(title_lbl, kW - 24);
        lv_label_set_text(title_lbl, title == nullptr ? "" : title);
        lv_obj_align(title_lbl, LV_ALIGN_TOP_LEFT, 0, 0);

        lv_obj_t* detail_lbl = lv_label_create(panel);
        lv_obj_set_style_text_font(detail_lbl, text_font_, 0);
        lv_obj_set_style_text_color(detail_lbl, lv_color_hex(0xFFE7C4), 0);
        lv_label_set_long_mode(detail_lbl, LV_LABEL_LONG_DOT);
        lv_obj_set_width(detail_lbl, kW - 24);
        lv_label_set_text(detail_lbl, detail == nullptr ? "" : detail);
        lv_obj_align(detail_lbl, LV_ALIGN_TOP_LEFT, 0, 28);

        if (progress >= 0) {
            lv_obj_t* bar = lv_bar_create(panel);
            lv_obj_set_size(bar, kW - 24, 12);
            lv_bar_set_range(bar, 0, 100);
            lv_bar_set_value(bar, progress > 100 ? 100 : progress, LV_ANIM_OFF);
            lv_obj_align(bar, LV_ALIGN_BOTTOM_MID, 0, -8);
        }

        auto tex = SnapshotObj(panel, "spine_ota");
        ESP_LOGI(kTag,
                 "[LVOVRENDER] kind=spine_ota w=%d h=%d progress=%d render_us=%u",
                 kW, kH, progress,
                 static_cast<unsigned>(esp_timer_get_time() - t0));
        ClearScreen();
        return tex;
    }

    cubicat::TexturePtr RenderLevel(const char* type, int value) {
        if (!ready_) return cubicat::TexturePtr(nullptr);
        constexpr int kW = 200;
        constexpr int kH = 64;
        const int64_t t0 = esp_timer_get_time();
        ClearScreen();

        const bool is_volume = (type != nullptr && strcmp(type, "volume") == 0);

        lv_obj_t* bg = lv_obj_create(screen_);
        lv_obj_set_size(bg, kW, kH);
        lv_obj_set_pos(bg, 0, 0);
        lv_obj_set_style_radius(bg, 8, 0);
        lv_obj_set_style_bg_color(bg, lv_color_hex(0x0C1014), 0);
        lv_obj_set_style_bg_opa(bg, 200, 0);
        lv_obj_set_style_border_width(bg, 1, 0);
        lv_obj_set_style_border_color(bg, lv_color_hex(0xFFE7C4), 0);
        lv_obj_set_style_border_opa(bg, 60, 0);
        lv_obj_set_style_pad_all(bg, 8, 0);
        lv_obj_clear_flag(bg, LV_OBJ_FLAG_SCROLLABLE);

        lv_obj_t* icon = lv_label_create(bg);
        lv_obj_set_style_text_font(icon, icon_font_, 0);
        lv_obj_set_style_text_color(icon, lv_color_hex(0xFFF8EC), 0);
        if (is_volume) {
            lv_label_set_text(icon,
                              value == 0 ? FONT_AWESOME_VOLUME_XMARK
                                         : FONT_AWESOME_VOLUME_HIGH);
        } else {
            lv_label_set_text(icon, FONT_AWESOME_SUN);
        }
        lv_obj_set_pos(icon, 12, 8);

        char text_buf[32];
        if (is_volume) {
            if (value == 0) {
                snprintf(text_buf, sizeof(text_buf),
                         "\xE5\xB7\xB2\xE9\x9D\x99\xE9\x9F\xB3");
            } else {
                snprintf(text_buf, sizeof(text_buf),
                         "\xE9\x9F\xB3\xE9\x87\x8F %d%%", value);
            }
        } else {
            snprintf(text_buf, sizeof(text_buf),
                     "\xE4\xBA\xAE\xE5\xBA\xA6 %d/11", value);
        }
        lv_obj_t* text = lv_label_create(bg);
        lv_obj_set_style_text_font(text, text_font_, 0);
        lv_obj_set_style_text_color(text, lv_color_hex(0xFFF8EC), 0);
        lv_label_set_text(text, text_buf);
        lv_obj_set_pos(text, 40, 8);

        lv_obj_t* bar = lv_bar_create(bg);
        lv_obj_set_size(bar, 160, 6);
        lv_obj_set_pos(bar, 20, kH - 18);
        lv_obj_set_style_bg_color(bar, lv_color_hex(0x2A2F35), 0);
        lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(bar, lv_color_hex(0xFFE7C4),
                                  LV_PART_INDICATOR);
        const int max_val = is_volume ? 100 : 11;
        lv_bar_set_range(bar, 0, max_val);
        lv_bar_set_value(bar, value, LV_ANIM_OFF);

        auto tex = SnapshotObj(bg, "level");
        ESP_LOGI(kTag,
                 "[LVOVRENDER] kind=level w=%d h=%d render_us=%u",
                 kW, kH,
                 static_cast<unsigned>(esp_timer_get_time() - t0));
        ClearScreen();
        return tex;
    }

    cubicat::TexturePtr RenderStatusIcon(const char* icon_name,
                                         bool dark_bg) {
        if (!ready_) return cubicat::TexturePtr(nullptr);
        constexpr int kSize = 20;
        const int64_t t0 = esp_timer_get_time();
        ClearScreen();

        lv_obj_t* root = lv_obj_create(screen_);
        lv_obj_set_size(root, kSize, kSize);
        lv_obj_set_pos(root, 0, 0);
        lv_obj_set_style_radius(root, 4, 0);
        lv_obj_set_style_border_width(root, 0, 0);
        lv_obj_set_style_pad_all(root, 0, 0);
        if (dark_bg) {
            lv_obj_set_style_bg_color(root, lv_color_hex(0x0C1014), 0);
            lv_obj_set_style_bg_opa(root, 195, 0);
        } else {
            lv_obj_set_style_bg_opa(root, LV_OPA_TRANSP, 0);
        }
        lv_obj_clear_flag(root, LV_OBJ_FLAG_SCROLLABLE);

        const char* glyph = FONT_AWESOME_WIFI;
        if (icon_name != nullptr) {
            if (strcmp(icon_name, "wifi_off") == 0 ||
                strcmp(icon_name, "disconnected") == 0) {
                glyph = FONT_AWESOME_WIFI_SLASH;
            } else if (strcmp(icon_name, "wifi_config") == 0 ||
                       strcmp(icon_name, "configuring") == 0) {
                glyph = FONT_AWESOME_WIFI_FAIR;
            } else if (strcmp(icon_name, "muted") == 0) {
                glyph = FONT_AWESOME_VOLUME_XMARK;
            } else {
                glyph = FONT_AWESOME_WIFI;
            }
        }

        lv_obj_t* label = lv_label_create(root);
        lv_obj_set_style_text_font(label, icon_font_, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(0xFFF8EC), 0);
        lv_label_set_text(label, glyph);
        lv_obj_center(label);

        auto tex = SnapshotObj(root, "icon");
        ESP_LOGI(kTag,
                 "[LVOVRENDER] kind=icon w=%d h=%d render_us=%u",
                 kSize, kSize,
                 static_cast<unsigned>(esp_timer_get_time() - t0));
        ClearScreen();
        return tex;
    }

    void SetMcpWallpaper(const cubicat::TexturePtr& wallpaper) {
        if (wallpaper_.get() == wallpaper.get()) return;
        wallpaper_ = wallpaper;
        glass_cache_.reset();
        glass_cache_attempted_ = false;
    }

    bool PrepareGlassCache() {
        if (glass_cache_) return true;
        if (glass_cache_attempted_ || !wallpaper_) return false;
        glass_cache_attempted_ = true;
        const int64_t started = esp_timer_get_time();
        glass_w_ = (screen_w_ + kGlassDownsample - 1) / kGlassDownsample;
        glass_h_ = (screen_h_ + kGlassDownsample - 1) / kGlassDownsample;
        const size_t bytes = static_cast<size_t>(glass_w_) * glass_h_ * 4;
        PsramRgbBuffer pixels(static_cast<uint32_t*>(heap_caps_malloc(
            bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)), &heap_caps_free);
        PsramRgbBuffer scratch(static_cast<uint32_t*>(heap_caps_malloc(
            bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)), &heap_caps_free);
        if (!pixels || !scratch) {
            ESP_LOGW(kTag, "[MCPGLASS] cache=no_memory fallback=solid bytes=%u",
                     static_cast<unsigned>(bytes));
            return false;
        }
        const auto size = wallpaper_->getTextureSize();
        if (size.x == 0 || size.y == 0) return false;
        // Match the centered, unscaled background sprite (including its crop).
        const int source_left = (static_cast<int>(size.x) - screen_w_) / 2;
        const int source_top = (static_cast<int>(size.y) - screen_h_) / 2;
        for (int y = 0; y < glass_h_; ++y) {
            for (int x = 0; x < glass_w_; ++x) {
                unsigned red = 0, green = 0, blue = 0;
                for (int dy = 0; dy < kGlassDownsample; ++dy) {
                    for (int dx = 0; dx < kGlassDownsample; ++dx) {
                        const int sx = std::clamp(source_left + x * kGlassDownsample + dx,
                                                  0, static_cast<int>(size.x) - 1);
                        const int sy = std::clamp(source_top + y * kGlassDownsample + dy,
                                                  0, static_cast<int>(size.y) - 1);
                        const uint32_t value = wallpaper_->readPixelUnsafe(sx, sy);
                        uint32_t rgb;
                        if (wallpaper_->getColorDepth() == 32) {
                            rgb = value >> 8;  // Cubicat RRGGBBAA
                            if (wallpaper_->hasAlpha()) {
                                rgb = MixRgb(0, rgb, value & 255);
                            }
                        } else {
                            rgb = (((value >> 11) & 31) * 255 / 31 << 16) |
                                  (((value >> 5) & 63) * 255 / 63 << 8) |
                                  ((value & 31) * 255 / 31);
                        }
                        red += (rgb >> 16) & 255;
                        green += (rgb >> 8) & 255;
                        blue += rgb & 255;
                    }
                }
                constexpr unsigned samples = kGlassDownsample * kGlassDownsample;
                pixels.get()[y * glass_w_ + x] =
                    ((red / samples) << 16) | ((green / samples) << 8) | (blue / samples);
            }
        }
        BlurGlassRgb(pixels.get(), scratch.get(), glass_w_, glass_h_);
        glass_cache_ = std::move(pixels);
        ESP_LOGI(kTag,
                 "[MCPGLASS] cache=ready source=wallpaper w=%d h=%d bytes=%u build_us=%lld",
                 glass_w_, glass_h_, static_cast<unsigned>(bytes),
                 static_cast<long long>(esp_timer_get_time() - started));
        return true;
    }

    uint32_t GlassColorAt(int x, int y) const {
        // Bilinear upsampling prevents a visible 4-pixel grid on soft gradients.
        x = std::clamp(x - kGlassDownsample / 2, 0, (glass_w_ - 1) * kGlassDownsample);
        y = std::clamp(y - kGlassDownsample / 2, 0, (glass_h_ - 1) * kGlassDownsample);
        const int left = x / kGlassDownsample;
        const int top = y / kGlassDownsample;
        const int right = std::min(left + 1, glass_w_ - 1);
        const int bottom = std::min(top + 1, glass_h_ - 1);
        const auto* pixels = glass_cache_.get();
        const unsigned ax = (x % kGlassDownsample) * 255 / kGlassDownsample;
        const unsigned ay = (y % kGlassDownsample) * 255 / kGlassDownsample;
        return MixRgb(MixRgb(pixels[top * glass_w_ + left], pixels[top * glass_w_ + right], ax),
                      MixRgb(pixels[bottom * glass_w_ + left], pixels[bottom * glass_w_ + right], ax), ay);
    }

    void StyleButton(lv_obj_t* btn, int width, bool primary,
                     const char* text) {
        lv_obj_remove_style_all(btn);
        lv_obj_set_size(btn, width, mcp_card_layout::kButtonHeight);
        lv_obj_set_style_radius(btn, 11, 0);
        lv_obj_set_style_bg_color(btn, lv_color_hex(primary ? 0x438AF7 : 0xFFFFFF), 0);
        lv_obj_set_style_bg_opa(btn, primary ? 205 : 65, 0);
        lv_obj_set_style_bg_grad_color(btn, lv_color_hex(primary ? 0x80B9FF : 0xEAF3FF), 0);
        lv_obj_set_style_bg_grad_dir(btn, LV_GRAD_DIR_VER, 0);
        lv_obj_set_style_border_width(btn, 1, 0);
        lv_obj_set_style_border_color(btn, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_border_opa(btn, 220, 0);
        lv_obj_set_style_pad_all(btn, 0, 0);
        lv_obj_clear_flag(btn, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_t* label = lv_label_create(btn);
        lv_obj_set_style_text_font(label, subtitle_font_, 0);
        lv_obj_set_style_text_color(label, lv_color_hex(primary ? 0xFFFFFF : 0x172B50), 0);
        lv_obj_set_style_text_align(label, LV_TEXT_ALIGN_CENTER, 0);
        lv_label_set_long_mode(label, LV_LABEL_LONG_DOT);
        lv_obj_set_width(label, width - 10);
        lv_obj_set_height(label, 24);
        lv_label_set_text(label, text == nullptr ? "" : text);
        lv_obj_center(label);
    }

    cubicat::TexturePtr RenderCard(const McpCardContent* content,
                                   int screen_x, int screen_y) {
        if (!ready_ || content == nullptr) {
            return cubicat::TexturePtr(nullptr);
        }
        using namespace mcp_card_layout;
        const int w = kWidth;
        const int h = Height(content->expanded);
        const int64_t t0 = esp_timer_get_time();
        ClearScreen();

        // Temporary RGB565 backing. Opaque interior hides the character;
        // LVGL clips the background image to the rounded card outline.
        std::unique_ptr<uint16_t, decltype(&heap_caps_free)> backing(nullptr, &heap_caps_free);
        lv_image_dsc_t background_image{};
        if (PrepareGlassCache()) {
            backing.reset(static_cast<uint16_t*>(heap_caps_malloc(
                static_cast<size_t>(w) * h * 2, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT)));
            if (!backing) {
                ESP_LOGW(kTag, "[MCPGLASS] backing=no_memory fallback=solid");
            }
        }
        if (backing) {
            for (int y = 0; y < h; ++y) {
                const unsigned tint = 108 + (h - 1 - y) * 38 / (h - 1);
                for (int x = 0; x < w; ++x) {
                    const uint32_t rgb = MixRgb(GlassColorAt(screen_x + x, screen_y + y),
                                                0xEEF7FF, tint);
                    backing.get()[y * w + x] =
                        ((rgb >> 8) & 0xF800) | ((rgb >> 5) & 0x07E0) | ((rgb >> 3) & 0x001F);
                }
            }
            background_image.header.magic = LV_IMAGE_HEADER_MAGIC;
            background_image.header.cf = LV_COLOR_FORMAT_RGB565;
            background_image.header.w = w;
            background_image.header.h = h;
            background_image.header.stride = w * 2;
            background_image.data_size = w * h * 2;
            background_image.data = reinterpret_cast<const uint8_t*>(backing.get());
        }

        lv_obj_t* card = lv_obj_create(screen_);
        lv_obj_remove_style_all(card);
        lv_obj_set_size(card, w, h);
        lv_obj_set_pos(card, 0, 0);
        lv_obj_set_style_radius(card, kRadius, 0);
        lv_obj_set_style_bg_color(card, lv_color_hex(0xE6F0FF), 0);
        lv_obj_set_style_bg_opa(card, LV_OPA_COVER, 0);
        if (backing) lv_obj_set_style_bg_image_src(card, &background_image, 0);
        lv_obj_set_style_border_color(card, lv_color_hex(0xFFFFFF), 0);
        lv_obj_set_style_border_opa(card, 230, 0);
        lv_obj_set_style_border_width(card, 1, 0);
        lv_obj_set_style_pad_all(card, 0, 0);
        lv_obj_clear_flag(card, LV_OBJ_FLAG_SCROLLABLE);

        auto label = [&](const char* text, const lv_font_t* font,
                         uint32_t color, int x, int y, int label_width, int label_height) {
            lv_obj_t* obj = lv_label_create(card);
            lv_obj_set_style_text_font(obj, font, 0);
            lv_obj_set_style_text_color(obj, lv_color_hex(color), 0);
            lv_obj_set_style_text_line_space(obj, 1, 0);
            lv_label_set_long_mode(obj, LV_LABEL_LONG_DOT);
            lv_obj_set_size(obj, label_width, label_height);
            lv_label_set_text(obj, text ? text : "");
            // Root border takes one pixel of the content origin.
            lv_obj_set_pos(obj, x - 1, y - 1);
            return obj;
        };

        label(content->privacy_mode ? FONT_AWESOME_LOCK : FONT_AWESOME_BELL,
              icon_font_, 0x398EFF, kInset, 14, 22, 22);
        const bool high_priority = content->priority &&
                                  std::strcmp(content->priority, "high") == 0;
        label(content->privacy_mode ? "隐私提醒" : (high_priority ? "重要提醒" : "事项提醒"),
              subtitle_font_, 0x244365, kInset + 28, 16, 116, 22);

        if (content->queue_count > 0) {
            char queue_text[40];
            std::snprintf(queue_text, sizeof(queue_text), "还有 %d 项", content->queue_count);
            lv_obj_t* queue = label(queue_text, subtitle_font_, 0x244365,
                                    w - kInset - 100, 16, 100, 22);
            lv_obj_set_style_text_align(queue, LV_TEXT_ALIGN_RIGHT, 0);
        }

        const char* title = content->title && content->title[0] != '\0'
                                ? content->title : "事项提醒";
        label(title, text_font_, 0x102040, kInset, content->expanded ? 46 : 40,
              w - 2 * kInset, 26);

        // Keep actual reminder details; internal state names are not UI copy.
        std::string body;
        if (content->status) {
            body = content->status;
            struct StatusLabel { const char* value; const char* text; };
            static constexpr StatusLabel states[] = {
                {"presenting", ""}, {"pending", ""}, {"queued", ""},
                {"waiting_presence", "等待接收人"},
                {"snoozed", "已稍后提醒"}, {"awaiting_undo", "已处理，可撤销"},
                {"completed", "已完成"}, {"expired", "已过期"},
                {"attention_silenced", "已停止提示"}, {"skipped", "已跳过"},
                {"dismissed", "已关闭"}, {"verifying_identity", "正在确认身份"},
                {"waiting_recipient", "等待接收人"},
                {"ok", ""}, {"error", "暂时未完成"}, {"loading", "正在处理"},
                {"alarm", ""}, {"remind", ""}, {"habit", ""},
            };
            for (const auto& state : states) {
                if (std::strcmp(content->status, state.value) == 0) body = state.text;
            }
        }
        const int used = std::clamp(content->item_count, 0, content->expanded ? 4 : 1);
        for (int index = 0; index < used; ++index) {
            if (!content->items[index] || content->items[index][0] == '\0') continue;
            if (!body.empty()) body += '\n';
            body += content->items[index];
        }
        const bool has_tertiary = content->tertiary_label && content->tertiary_label[0] != '\0';
        const int body_bottom = content->expanded
            ? (content->actionable ? ActionAreaTop(has_tertiary) - 8 : h - kInset)
            : (content->actionable ? h - 26 : h - kInset);
        const int body_top = content->expanded ? 76 : 70;
        label(body.c_str(), subtitle_font_, 0x325071, kInset, body_top,
              w - 2 * kInset, std::max(20, body_bottom - body_top));

        if (content->expanded && content->actionable) {
            const char* texts[] = {
                content->primary_label && content->primary_label[0] != '\0'
                    ? content->primary_label : "确认",
                content->secondary_label && content->secondary_label[0] != '\0'
                    ? content->secondary_label : "稍后",
                content->tertiary_label,
            };
            for (int index = 0; index < 2; ++index) {
                lv_obj_t* button = lv_obj_create(card);
                StyleButton(button, ButtonWidth(), index == 0, texts[index]);
                lv_obj_set_pos(button, ButtonLeft(index) - 1, ButtonTop() - 1);
            }
            if (has_tertiary) {
                lv_obj_t* tertiary = label(texts[2], subtitle_font_, 0x325071,
                    kTertiaryLeft, kTertiaryTop, kTertiaryWidth, kTertiaryHeight);
                lv_obj_set_style_text_align(tertiary, LV_TEXT_ALIGN_RIGHT, 0);
            }
        } else if (!content->expanded && content->actionable) {
            label("轻触展开", subtitle_font_, 0x365E91,
                  kInset, h - 23, w - 2 * kInset, 20);
        }

        auto tex = SnapshotObj(card, "card");
        ESP_LOGI(kTag,
                 "[LVOVRENDER] kind=card style=frosted wallpaper=%d w=%d h=%d render_us=%u",
                 backing ? 1 : 0, w, h,
                 static_cast<unsigned>(esp_timer_get_time() - t0));
        ClearScreen();
        if (backing) {
            // Stack image descriptor and PSRAM backing expire together here.
            lv_image_cache_drop(&background_image);
            lv_image_header_cache_drop(&background_image);
        }
        return tex;
    }

    lv_display_t* disp_ = nullptr;
    lv_obj_t* screen_ = nullptr;
    lv_draw_buf_t* draw_buf_ = nullptr;
    uint8_t* draw_buf_raw_ = nullptr;
    const lv_font_t* text_font_ = nullptr;
    lv_font_t* owned_text_font_ = nullptr;
    const lv_font_t* subtitle_font_ = nullptr;
    lv_font_t* owned_subtitle_font_ = nullptr;
    const lv_font_t* icon_font_ = nullptr;
    int screen_w_ = 0;
    int screen_h_ = 0;
    bool ready_ = false;
    uint32_t total_convert_us_ = 0;
    cubicat::TexturePtr wallpaper_;
    PsramRgbBuffer glass_cache_{nullptr, &heap_caps_free};
    bool glass_cache_attempted_ = false;
    int glass_w_ = 0;
    int glass_h_ = 0;
};

CubicatLvglOverlay::CubicatLvglOverlay()
    : impl_(std::make_unique<Impl>()) {}
CubicatLvglOverlay::~CubicatLvglOverlay() = default;

bool CubicatLvglOverlay::Initialize(int w, int h) {
    return impl_->Initialize(w, h);
}

bool CubicatLvglOverlay::IsReady() const {
    return impl_ && impl_->IsReady();
}

cubicat::TexturePtr CubicatLvglOverlay::RenderDialogue(
    const char* text, int scroll_offset_px) {
    const int64_t t0 = esp_timer_get_time();
    auto tex = impl_->RenderDialogue(text, scroll_offset_px);
    total_render_us_ += static_cast<uint32_t>(esp_timer_get_time() - t0);
    total_convert_us_ = impl_->total_convert_us();
    update_count_++;
    return tex;
}

int CubicatLvglOverlay::MeasureDialogueTextWidth(const char* text) const {
    return impl_ ? impl_->MeasureDialogueTextWidth(text) : 0;
}

cubicat::TexturePtr CubicatLvglOverlay::RenderLevelOverlay(
    const char* type, int value) {
    const int64_t t0 = esp_timer_get_time();
    auto tex = impl_->RenderLevel(type, value);
    total_render_us_ += static_cast<uint32_t>(esp_timer_get_time() - t0);
    total_convert_us_ = impl_->total_convert_us();
    update_count_++;
    return tex;
}

cubicat::TexturePtr CubicatLvglOverlay::RenderStatusIcon(
    const char* icon_name, bool dark_bg) {
    const int64_t t0 = esp_timer_get_time();
    auto tex = impl_->RenderStatusIcon(icon_name, dark_bg);
    total_render_us_ += static_cast<uint32_t>(esp_timer_get_time() - t0);
    total_convert_us_ = impl_->total_convert_us();
    update_count_++;
    return tex;
}

void CubicatLvglOverlay::SetMcpWallpaper(const cubicat::TexturePtr& wallpaper) {
    if (impl_) impl_->SetMcpWallpaper(wallpaper);
}

cubicat::TexturePtr CubicatLvglOverlay::RenderMcpCard(
    const McpCardContent* content, int screen_x, int screen_y) {
    const int64_t t0 = esp_timer_get_time();
    auto tex = impl_->RenderCard(content, screen_x, screen_y);
    total_render_us_ += static_cast<uint32_t>(esp_timer_get_time() - t0);
    total_convert_us_ = impl_->total_convert_us();
    update_count_++;
    return tex;
}

cubicat::TexturePtr CubicatLvglOverlay::RenderSpineOta(const char* title,
                                                       const char* detail,
                                                       int progress) {
    const int64_t t0 = esp_timer_get_time();
    auto tex = impl_->RenderSpineOta(title, detail, progress);
    total_render_us_ += static_cast<uint32_t>(esp_timer_get_time() - t0);
    total_convert_us_ = impl_->total_convert_us();
    update_count_++;
    return tex;
}

void CubicatLvglOverlay::ResetPerfCounters() {
    total_render_us_ = 0;
    total_convert_us_ = 0;
    update_count_ = 0;
    if (impl_) {
        impl_->ResetConvertUs();
    }
}
