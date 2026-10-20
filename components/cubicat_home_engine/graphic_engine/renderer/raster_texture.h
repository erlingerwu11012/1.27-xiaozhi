#pragma once
#include "graphic_engine/drawable/texture.h"
#include <cstdint>

namespace cubicat {
// Snapshot once on the owner thread. Workers never access dirty-notify wrappers.
struct RasterTexture {
    Texture *texture = nullptr;
    const uint16_t *rgb = nullptr;
    const uint32_t *rgba = nullptr;
    int width = 0, height = 0;
    bool alpha = false, has_palette = false;
    void Init(Texture *value, bool direct) {
        texture = value;
        if (!value)
            return;
        auto size = value->getTextureSize();
        width = size.x;
        height = size.y;
        alpha = value->hasAlpha();
        has_palette = value->getPalette() != nullptr;
        if (direct && value->isA<Texture>() && !has_palette) {
            if (value->getColorDepth() == 16)
                rgb = static_cast<const uint16_t *>(value->getFrameData());
            if (value->getColorDepth() == 32)
                rgba = static_cast<const uint32_t *>(value->getFrameData());
        }
    }
    inline uint32_t ReadUnsafe(uint32_t x, uint32_t y) const {
        const uint32_t index = y * width + x;
        if (rgba)
            return rgba[index];
        if (rgb)
            return rgb[index];
        return texture->readPixelUnsafe(x, y);
    }
    inline bool Read(int x, int y, uint32_t &color) const {
        if (!rgb && !rgba)
            return texture->readPixel(x, y, &color);
        if (x < 0 || y < 0 || x >= width || y >= height)
            return false;
        color = ReadUnsafe(x, y);
        return true;
    }
    // Matches the original bilinear arithmetic, including partial-edge fallback.
    inline bool Bilinear(float x, float y, uint32_t &color) const {
        const int16_t x0 = static_cast<int16_t>(x), y0 = static_cast<int16_t>(y);
        const int x1 = x0 + 1, y1 = y0 + 1;
        const float dx = x - x0, dy = y - y0;
        const float d = dx * dy, c = dy - d, b = dx - d, a = 1 - dx - c;
        uint32_t colors[4] = {};
        int count = 0;
        if ((rgba || rgb) && x0 >= 0 && y0 >= 0 && x1 < width && y1 < height) {
            const uint32_t index = static_cast<uint32_t>(y0) * width + x0;
            if (rgba) {
                colors[0] = rgba[index];
                colors[1] = rgba[index + 1];
                colors[2] = rgba[index + width];
                colors[3] = rgba[index + width + 1];
            } else {
                colors[0] = rgb[index];
                colors[1] = rgb[index + 1];
                colors[2] = rgb[index + width];
                colors[3] = rgb[index + width + 1];
            }
            count = 4;
        } else {
            count += Read(x0, y0, colors[0]);
            count += Read(x1, y0, colors[1]);
            count += Read(x0, y1, colors[2]);
            count += Read(x1, y1, colors[3]);
        }
        if (count == 0)
            return false;
        if (count != 4) {
            color = colors[0];
            return true;
        }
        if (alpha) {
            auto *out = reinterpret_cast<uint8_t *>(&color);
            const auto *p0 = reinterpret_cast<const uint8_t *>(&colors[0]);
            const auto *p1 = reinterpret_cast<const uint8_t *>(&colors[1]);
            const auto *p2 = reinterpret_cast<const uint8_t *>(&colors[2]);
            const auto *p3 = reinterpret_cast<const uint8_t *>(&colors[3]);
            for (int i = 0; i < 4; ++i)
                out[i] = p0[i] * a + p1[i] * b + p2[i] * c + p3[i] * d;
        } else {
            const uint16_t r = (colors[0] >> 11) * a + (colors[1] >> 11) * b +
                               (colors[2] >> 11) * c + (colors[3] >> 11) * d;
            const uint16_t g = ((colors[0] >> 5) & 63) * a + ((colors[1] >> 5) & 63) * b +
                               ((colors[2] >> 5) & 63) * c + ((colors[3] >> 5) & 63) * d;
            const uint16_t blue = (colors[0] & 31) * a + (colors[1] & 31) * b +
                                  (colors[2] & 31) * c + (colors[3] & 31) * d;
            color = (r << 11) | (g << 5) | blue;
        }
        return true;
    }
};
} // namespace cubicat
