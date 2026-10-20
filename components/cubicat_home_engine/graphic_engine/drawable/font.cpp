#include "font.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <string>
#include <vector>

#include "gb2312font_20.h"
#include "utils/helper.h"

FontData DefaultFontData = {
    .glyphData = GB2312_GlyphData_20,
    .fontSize = GB2312_FontSize_20,
    .charCount = GB2312_CharCount_20,
    .charSet = GB2312_CharSet_20,
};

int getCharIndex(const char* str, const char* target) {
    if (str == nullptr || target == nullptr || target[0] == '\0') return -1;

    const size_t target_len = std::strlen(target);
    int char_count = 0;
    while (*str != '\0') {
        const auto lead = static_cast<uint8_t>(*str);
        size_t char_len = 1;
        if ((lead & 0xE0U) == 0xC0U) {
            char_len = 2;
        } else if ((lead & 0xF0U) == 0xE0U) {
            char_len = 3;
        } else if ((lead & 0xF8U) == 0xF0U) {
            char_len = 4;
        }

        if (char_len == target_len &&
            std::memcmp(str, target, char_len) == 0) {
            return char_count;
        }
        str += char_len;
        ++char_count;
    }
    return -1;
}

std::vector<std::string> splitUTF8(const char* text) {
    std::vector<std::string> characters;
    if (text == nullptr) return characters;

    const char* cursor = text;
    while (*cursor != '\0') {
        const auto lead = static_cast<uint8_t>(*cursor);
        size_t length = 1;
        if ((lead & 0xE0U) == 0xC0U && cursor[1] != '\0') {
            length = 2;
        } else if ((lead & 0xF0U) == 0xE0U &&
                   cursor[1] != '\0' && cursor[2] != '\0') {
            length = 3;
        } else if ((lead & 0xF8U) == 0xF0U &&
                   cursor[1] != '\0' && cursor[2] != '\0' &&
                   cursor[3] != '\0') {
            length = 4;
        }

        characters.emplace_back(cursor, length);
        cursor += length;
    }
    return characters;
}

void calculateUTFStringSize(const char* text,
                            uint16_t* width,
                            uint16_t* height) {
    if (width == nullptr || height == nullptr) return;
    *width = 0;
    *height = 0;
    if (DefaultFontData.glyphData == nullptr ||
        DefaultFontData.charSet == nullptr) {
        return;
    }

    const uint16_t glyph_data_length = static_cast<uint16_t>(
        4U + std::ceil(DefaultFontData.fontSize *
                       DefaultFontData.fontSize / 8.0f));
    const auto lines = splitString(text == nullptr ? "" : text, "\n");
    *height = static_cast<uint16_t>(
        DefaultFontData.fontSize * 3U / 2U * lines.size());

    for (const auto& line : lines) {
        uint16_t line_width = 0;
        for (const auto& character : splitUTF8(line.c_str())) {
            const int index =
                getCharIndex(DefaultFontData.charSet, character.c_str());
            if (index < 0 ||
                index >= static_cast<int>(DefaultFontData.charCount)) {
                continue;
            }
            const uint8_t* glyph =
                DefaultFontData.glyphData + index * glyph_data_length;
            line_width = static_cast<uint16_t>(
                line_width + glyph[2] - glyph[0]);
        }
        *width = std::max(*width, line_width);
    }
}
