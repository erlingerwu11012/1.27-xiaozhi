#include "bmfont.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <string>

#include "core/memory_allocator.h"

using namespace cubicat;

FontData BMFont::m_sFontData = DefaultFontData;

namespace {
uint32_t RgbaFromRgb565(uint16_t color, uint8_t alpha) {
    const uint32_t red = color >> 11;
    const uint32_t green = (color >> 5) & 0x3FU;
    const uint32_t blue = color & 0x1FU;
    return (red << 27) | (green << 18) | (blue << 11) | alpha;
}

uint16_t GlyphDataLength(const FontData& font) {
    return static_cast<uint16_t>(
        4U + std::ceil(font.fontSize * font.fontSize / 8.0f));
}

int FindGlyph(const FontData& font, const std::string& character) {
    if (font.charSet == nullptr || character.empty()) return -1;
    int index = getCharIndex(font.charSet, character.c_str());
    if (index < 0) {
        index = getCharIndex(font.charSet, "\xE2\x96\xA1");
    }
    return index;
}
}  // namespace

BMFont::BMFont(const Vector2us& size, const char* text, uint16_t color)
    : Drawable(), m_Color(color) {
    setPivot(0.0f, 0.0f);

    m_PixelCount =
        std::max<uint32_t>(1, static_cast<uint32_t>(size.x) * size.y);
    m_pData = static_cast<uint32_t*>(
        psram_prefered_malloc(m_PixelCount * sizeof(uint32_t)));
    if (m_pData == nullptr) return;
    std::memset(m_pData, 0, m_PixelCount * sizeof(uint32_t));

    const FontData& font = m_sFontData;
    if (font.glyphData == nullptr || font.charSet == nullptr) return;

    const uint16_t glyph_data_length = GlyphDataLength(font);
    const int line_height = font.fontSize * 3 / 2;
    int cursor_x = 0;
    int line_top = 0;

    for (const auto& character : splitUTF8(text == nullptr ? "" : text)) {
        if (character == "\n") {
            cursor_x = 0;
            line_top += line_height;
            continue;
        }

        const int glyph_index = FindGlyph(font, character);
        if (glyph_index < 0 ||
            glyph_index >= static_cast<int>(font.charCount)) {
            cursor_x += font.fontSize;
            continue;
        }

        const uint8_t* glyph =
            font.glyphData + glyph_index * glyph_data_length;
        const uint8_t x_offset = glyph[0];
        const uint8_t y_offset = glyph[1];
        const uint8_t glyph_width = glyph[2] - glyph[0];
        const uint8_t glyph_height = glyph[3] - glyph[1];
        const uint8_t* bitmap = glyph + 4;

        for (uint8_t y = 0; y < glyph_height; ++y) {
            for (uint8_t x = 0; x < glyph_width; ++x) {
                const uint32_t source_index =
                    static_cast<uint32_t>(y) * glyph_width + x;
                const bool set =
                    (bitmap[source_index / 8U] &
                     (0x80U >> (source_index % 8U))) != 0;
                if (!set) continue;

                const int target_x = cursor_x + x_offset + x;
                const int target_y = line_top + y_offset + y;
                if (target_x >= 0 && target_y >= 0 &&
                    target_x < size.x && target_y < size.y) {
                    m_pData[static_cast<uint32_t>(target_y) * size.x +
                            target_x] = RgbaFromRgb565(color, 255);
                }
            }
        }
        cursor_x += glyph_width;
    }

    auto texture = Texture::create(
        size.x, size.y, m_pData, true, 1, 1, nullptr, 32, true);
    m_DataManagedByTexture = true;
    getMaterial()->setTexture(texture);
}

BMFont::~BMFont() {
    if (m_pData != nullptr && !m_DataManagedByTexture) free(m_pData);
}

void BMFont::setColor(uint16_t color) {
    if (m_pData == nullptr || color == m_Color) return;
    m_Color = color;
    for (uint32_t i = 0; i < m_PixelCount; ++i) {
        const uint8_t alpha = static_cast<uint8_t>(m_pData[i]);
        if (alpha != 0) m_pData[i] = RgbaFromRgb565(color, alpha);
    }
    markDirty();
}

Vector2f BMFont::calculateUTFStringRect(const char* text) {
    const FontData& font = m_sFontData;
    if (font.glyphData == nullptr || font.charSet == nullptr) {
        return Vector2f(0, 0);
    }

    const uint16_t glyph_data_length = GlyphDataLength(font);
    uint16_t max_width = 0;
    uint16_t line_width = 0;
    uint16_t line_count = 1;

    for (const auto& character : splitUTF8(text == nullptr ? "" : text)) {
        if (character == "\n") {
            max_width = std::max(max_width, line_width);
            line_width = 0;
            ++line_count;
            continue;
        }

        const int glyph_index = FindGlyph(font, character);
        if (glyph_index < 0 ||
            glyph_index >= static_cast<int>(font.charCount)) {
            continue;
        }
        const uint8_t* glyph =
            font.glyphData + glyph_index * glyph_data_length;
        line_width = static_cast<uint16_t>(
            line_width + glyph[2] - glyph[0]);
    }
    max_width = std::max(max_width, line_width);
    return Vector2f(max_width, line_count * font.fontSize * 3U / 2U);
}
