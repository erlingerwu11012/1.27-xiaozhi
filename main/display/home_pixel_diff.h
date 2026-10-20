#pragma once
#include <algorithm>
#include <cstdint>

struct HomePixelRect {
    int x1 = 0, y1 = 0, x2 = 0, y2 = 0;
    bool Empty() const { return x2 <= x1 || y2 <= y1; }
    uint32_t Pixels() const { return Empty() ? 0 : uint32_t(x2 - x1) * (y2 - y1); }
};
// Only the producer writes snapshots. The previous accepted snapshot can be
// read while DMA also reads it. Compare finishes BEFORE reusing that same slot.
// Unknown pixels outside its saved rectangle are ALWAYS treated as changed.
inline HomePixelRect HomeChangedPixels(const uint16_t *current, int stride,
                                        const uint16_t *previous, int previous_stride,
                                        HomePixelRect input, HomePixelRect valid) {
    if (!previous) return input;
    HomePixelRect changed{input.x2, input.y2, input.x1, input.y1};
    auto include = [&](int x1, int y, int x2) {
        if (x2 <= x1) return;
        changed.x1 = std::min(changed.x1, x1);
        changed.x2 = std::max(changed.x2, x2);
        changed.y1 = std::min(changed.y1, y);
        changed.y2 = std::max(changed.y2, y + 1);
    };
    for (int y = input.y1; y < input.y2; ++y) {
        if (y < valid.y1 || y >= valid.y2) {
            include(input.x1, y, input.x2);
        } else {
            int left = std::max(input.x1, valid.x1), right = std::min(input.x2, valid.x2);
            if (right <= left) {
                include(input.x1, y, input.x2);
            } else {
                include(input.x1, y, left);
                include(right, y, input.x2);
                const auto *a = current + y * stride;
                const auto *b = previous + y * previous_stride;
                for (int x = left; x < right; ++x)
                    if (a[x] != b[x]) include(x, y, x + 1);
            }
        }
        // A full-size bounding rectangle cannot shrink; avoid scanning the rest.
        if (changed.x1 == input.x1 && changed.y1 == input.y1 &&
            changed.x2 == input.x2 && changed.y2 == input.y2) return input;
    }
    return changed.Empty() ? HomePixelRect{} : changed;
}
