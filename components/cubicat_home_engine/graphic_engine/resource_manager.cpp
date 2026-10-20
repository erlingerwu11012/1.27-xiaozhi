#include "resource_manager.h"

#include "core/memory_allocator.h"
#include "libpng/png.h"
#include "utils/logger.h"

#include <algorithm>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

namespace cubicat {
namespace {

struct MemoryReader {
    const uint8_t* data = nullptr;
    size_t size = 0;
    size_t offset = 0;
};

png_voidp PNGCBAPI PngMalloc(png_structp, png_alloc_size_t size) {
    if (size == 0) return nullptr;
    return psram_prefered_malloc(static_cast<unsigned int>(size));
}

void PNGCBAPI PngFree(png_structp, png_voidp pointer) {
    free(pointer);
}

void PNGCBAPI ReadPngMemory(png_structp png,
                            png_bytep output,
                            png_size_t bytes) {
    auto* reader =
        static_cast<MemoryReader*>(png_get_io_ptr(png));
    if (reader == nullptr ||
        bytes > reader->size - std::min(reader->offset, reader->size)) {
        png_error(png, "PNG memory read overflow");
        return;
    }
    std::memcpy(output, reader->data + reader->offset, bytes);
    reader->offset += bytes;
}

TexturePtr DecodePng(png_structp png, png_infop info) {
    png_read_info(png, info);
    const png_uint_32 width = png_get_image_width(png, info);
    const png_uint_32 height = png_get_image_height(png, info);
    int color_type = png_get_color_type(png, info);
    const int bit_depth = png_get_bit_depth(png, info);
    const bool has_transparency =
        (color_type & PNG_COLOR_MASK_ALPHA) != 0 ||
        png_get_valid(png, info, PNG_INFO_tRNS);

    if (bit_depth == 16) png_set_strip_16(png);
    if (color_type == PNG_COLOR_TYPE_PALETTE) {
        png_set_palette_to_rgb(png);
    }
    if (color_type == PNG_COLOR_TYPE_GRAY && bit_depth < 8) {
        png_set_expand_gray_1_2_4_to_8(png);
    }
    if (png_get_valid(png, info, PNG_INFO_tRNS)) {
        png_set_tRNS_to_alpha(png);
    }
    if (color_type == PNG_COLOR_TYPE_GRAY ||
        color_type == PNG_COLOR_TYPE_GRAY_ALPHA) {
        png_set_gray_to_rgb(png);
    }

    png_read_update_info(png, info);
    const int channels = png_get_channels(png, info);
    const size_t row_bytes = png_get_rowbytes(png, info);
    if (width == 0 || height == 0 ||
        (channels != 3 && channels != 4)) {
        LOGW("unsupported PNG layout %ux%u channels=%d",
             static_cast<unsigned>(width),
             static_cast<unsigned>(height),
             channels);
        return TexturePtr();
    }

    auto* decoded = static_cast<uint8_t*>(
        psram_prefered_malloc(
            static_cast<unsigned int>(row_bytes * height)));
    if (decoded == nullptr) return TexturePtr();

    std::vector<png_bytep> rows(height);
    for (png_uint_32 y = 0; y < height; ++y) {
        rows[y] = decoded + static_cast<size_t>(y) * row_bytes;
    }
    png_read_image(png, rows.data());
    png_read_end(png, nullptr);

    const bool output_alpha = has_transparency || channels == 4;
    if (!output_alpha) {
        auto* rgb565 = static_cast<uint16_t*>(
            psram_prefered_malloc(
                static_cast<unsigned int>(
                    width * height * sizeof(uint16_t))));
        if (rgb565 == nullptr) {
            free(decoded);
            return TexturePtr();
        }
        for (png_uint_32 y = 0; y < height; ++y) {
            const uint8_t* row = rows[y];
            for (png_uint_32 x = 0; x < width; ++x) {
                const uint8_t* pixel = row + x * channels;
                rgb565[y * width + x] = static_cast<uint16_t>(
                    ((pixel[0] >> 3) << 11) |
                    ((pixel[1] >> 2) << 5) |
                    (pixel[2] >> 3));
            }
        }
        free(decoded);
        return Texture::create(
            static_cast<uint16_t>(width),
            static_cast<uint16_t>(height),
            rgb565,
            true,
            1,
            1,
            nullptr,
            16,
            false);
    }

    auto* rgba = static_cast<uint32_t*>(
        psram_prefered_malloc(
            static_cast<unsigned int>(
                width * height * sizeof(uint32_t))));
    if (rgba == nullptr) {
        free(decoded);
        return TexturePtr();
    }
    for (png_uint_32 y = 0; y < height; ++y) {
        const uint8_t* row = rows[y];
        for (png_uint_32 x = 0; x < width; ++x) {
            const uint8_t* pixel = row + x * channels;
            const uint8_t alpha = channels == 4 ? pixel[3] : 0xFF;
            rgba[y * width + x] =
                (static_cast<uint32_t>(pixel[0]) << 24) |
                (static_cast<uint32_t>(pixel[1]) << 16) |
                (static_cast<uint32_t>(pixel[2]) << 8) |
                alpha;
        }
    }
    free(decoded);
    return Texture::create(
        static_cast<uint16_t>(width),
        static_cast<uint16_t>(height),
        rgba,
        true,
        1,
        1,
        nullptr,
        32,
        true);
}

TexturePtr LoadPngFile(FILE* file) {
    TexturePtr texture;
    if (file == nullptr) return texture;
    png_structp png = png_create_read_struct_2(
        PNG_LIBPNG_VER_STRING,
        nullptr,
        nullptr,
        nullptr,
        nullptr,
        PngMalloc,
        PngFree);
    if (png == nullptr) return texture;
    png_infop info = png_create_info_struct(png);
    if (info == nullptr) {
        png_destroy_read_struct(&png, nullptr, nullptr);
        return texture;
    }
    if (setjmp(png_jmpbuf(png)) == 0) {
        png_init_io(png, file);
        texture = DecodePng(png, info);
    }
    png_destroy_read_struct(&png, &info, nullptr);
    return texture;
}

TexturePtr LoadPngMemory(const void* data, size_t size) {
    TexturePtr texture;
    if (data == nullptr || size == 0) return texture;
    png_structp png = png_create_read_struct_2(
        PNG_LIBPNG_VER_STRING,
        nullptr,
        nullptr,
        nullptr,
        nullptr,
        PngMalloc,
        PngFree);
    if (png == nullptr) return texture;
    png_infop info = png_create_info_struct(png);
    if (info == nullptr) {
        png_destroy_read_struct(&png, nullptr, nullptr);
        return texture;
    }

    MemoryReader reader{
        static_cast<const uint8_t*>(data),
        size,
        0,
    };
    if (setjmp(png_jmpbuf(png)) == 0) {
        png_set_read_fn(png, &reader, ReadPngMemory);
        texture = DecodePng(png, info);
    }
    png_destroy_read_struct(&png, &info, nullptr);
    return texture;
}
}  // namespace

TexturePtr ResourceManager::loadTexture(const std::string& name,
                                        bool from_flash) {
    const auto cached = m_textures.find(name);
    if (cached != m_textures.end()) return cached->second;

    FILE* file = from_flash
        ? openFileFlash(name.c_str(), true)
        : openFileSD(name.c_str(), true);
    if (file == nullptr) {
        LOGW("load texture %s fail", name.c_str());
        return TexturePtr();
    }
    TexturePtr texture = LoadPngFile(file);
    fclose(file);
    if (texture) m_textures[name] = texture;
    return texture;
}

TexturePtr ResourceManager::loadTextureFromMemory(
    const std::string& name,
    const void* data,
    size_t size) {
    const auto cached = m_textures.find(name);
    if (cached != m_textures.end()) return cached->second;
    TexturePtr texture = LoadPngMemory(data, size);
    if (texture) {
        m_textures[name] = texture;
    } else {
        LOGW("load memory texture %s fail", name.c_str());
    }
    return texture;
}

void ResourceManager::removeTexture(const std::string& name) {
    const auto item = m_textures.find(name);
    if (item != m_textures.end() &&
        item->second.use_count() == 1) {
        m_textures.erase(item);
    }
}

TexturePtr ResourceManager::getTexture(const std::string& name) {
    const auto item = m_textures.find(name);
    return item == m_textures.end()
        ? TexturePtr()
        : item->second;
}

void ResourceManager::purge() {
    m_textures.clear();
}

}  // namespace cubicat
