#pragma once

#include <cstdint>
#include <memory>
#include <string>

#include "graphic_engine/drawable/texture.h"

// Off-screen LVGL texture generator. Never owns panel_io / SPI / LCD DMA.

class CubicatLvglOverlay {
public:
    CubicatLvglOverlay();
    ~CubicatLvglOverlay();

    bool Initialize(int screen_width, int screen_height);
    bool IsReady() const;

    // Subtitle dock: 296x28, cool translucent background, one-line text.
    // The home player supplies the current horizontal offset because this
    // overlay is snapshotted into a Spine texture rather than LVGL's live UI.
    cubicat::TexturePtr RenderDialogue(const char* text,
                                       int scroll_offset_px = 0);
    int MeasureDialogueTextWidth(const char* text) const;

    // Volume/brightness floating pill: 200x64
    cubicat::TexturePtr RenderLevelOverlay(const char* type, int value);

    // Status icons rendered as 20x20 (or with dark pill)
    cubicat::TexturePtr RenderStatusIcon(const char* icon_name, bool dark_bg);

    struct McpCardContent {
        const char* title;
        const char* items[4];
        int item_count;
        const char* status;
        const char* priority;
        const char* primary_label;
        const char* secondary_label;
        const char* tertiary_label;
        int queue_count;
        bool privacy_mode;
        bool actionable;
        bool expanded;
    };
    // Static wallpaper only: never sample the animated character/framebuffer.
    void SetMcpWallpaper(const cubicat::TexturePtr& wallpaper);
    cubicat::TexturePtr RenderMcpCard(const McpCardContent* content,
                                    int screen_x, int screen_y);

    // Role update status panel (remote update_spine only; not a shop)
    cubicat::TexturePtr RenderSpineOta(const char* title,
                                       const char* detail,
                                       int progress);

    uint32_t total_render_us() const { return total_render_us_; }
    uint32_t total_convert_us() const { return total_convert_us_; }
    uint32_t update_count() const { return update_count_; }
    void ResetPerfCounters();

private:
    struct Impl;
    std::unique_ptr<Impl> impl_;

    uint32_t total_render_us_ = 0;
    uint32_t total_convert_us_ = 0;
    uint32_t update_count_ = 0;
};
