#pragma once
#include <algorithm>
#include <cstring>
#include "utils/home_render_options.h"
#include "home_pixel_diff.h"

struct HomeLcdWindowBytes {
    uint8_t columns[4], rows[4];
    HomeLcdWindowBytes(HomePixelRect rect, int offset_x, int offset_y) {
        const int x1 = rect.x1 + offset_x, x2 = rect.x2 + offset_x - 1;
        const int y1 = rect.y1 + offset_y, y2 = rect.y2 + offset_y - 1;
        columns[0] = x1 >> 8; columns[1] = x1; columns[2] = x2 >> 8; columns[3] = x2;
        rows[0] = y1 >> 8; rows[1] = y1; rows[2] = y2 >> 8; rows[3] = y2;
    }
};
inline int HomeLcdStreamCommand(bool first) { return first ? 0x2c : -1; }
// Hardware calls are injectable so tests execute the PRODUCTION strip loop.
class HomeLcdTransport {
public:
    virtual ~HomeLcdTransport() = default;
    virtual bool Begin(HomePixelRect rect) = 0;
    virtual bool TakeSlot() = 0;
    virtual void GiveSlot() = 0;
    virtual bool Queue(const uint16_t *data, size_t pixels, bool first) = 0;
    virtual bool WaitAll() = 0; // success holds both tokens
    virtual void ReleaseAll() = 0;
};
inline void HomeCopySwap565(uint16_t *dst, const uint16_t *src, size_t count) {
    size_t i = 0;
    for (; i + 1 < count; i += 2) {
        uint32_t pair;
        std::memcpy(&pair, src + i, sizeof(pair));
        pair = ((pair & 0x00ff00ffU) << 8) | ((pair & 0xff00ff00U) >> 8);
        std::memcpy(dst + i, &pair, sizeof(pair));
    }
    if (i < count) dst[i] = uint16_t((src[i] << 8) | (src[i] >> 8));
}
inline bool HomeTransferLcdStream(HomeLcdTransport &io, const uint16_t *source, int stride,
                                  HomePixelRect rect, uint16_t **strips, uint8_t &next,
                                  int strip_rows, cubicat::HomeLcdFramePerf &perf,
                                  bool addressed_strips = false) {
    const int64_t started = esp_timer_get_time();
    const int width = rect.x2 - rect.x1;
    int64_t stage = esp_timer_get_time();
    bool ok = addressed_strips || io.Begin(rect);
    perf.queue_us += esp_timer_get_time() - stage;
    bool first = true;
    for (int y = rect.y1; ok && y < rect.y2; y += strip_rows) {
        const int rows = std::min(strip_rows, rect.y2 - y);
        stage = esp_timer_get_time();
        bool owned = io.TakeSlot();
        perf.wait_us += esp_timer_get_time() - stage;
        if (!owned) { ++perf.timeouts; ok = false; break; }
        auto *data = strips[next];
        next ^= 1U;
        stage = esp_timer_get_time();
        for (int row = 0; row < rows; ++row)
            HomeCopySwap565(data + row * width, source + (y + row) * stride + rect.x1, width);
        perf.copy_swap_us += esp_timer_get_time() - stage;
        stage = esp_timer_get_time();
        // Prepare the spare buffer while the preceding DMA transfer runs.
        // Begin drains that transfer before changing the panel's window.
        if (addressed_strips)
            ok = io.Begin({rect.x1, y, rect.x2, y + rows});
        if (ok)
            ok = io.Queue(data, size_t(width) * rows, addressed_strips || first);
        perf.queue_us += esp_timer_get_time() - stage;
        if (!ok) io.GiveSlot();
        first = false;
    }
    // Never recycle DMA-owned buffers on timeout, even on the failure path.
    stage = esp_timer_get_time();
    while (!io.WaitAll()) { ++perf.timeouts; ok = false; }
    perf.wait_us += esp_timer_get_time() - stage;
    io.ReleaseAll();
    perf.transfer_us = esp_timer_get_time() - started;
    perf.pixels = rect.Pixels();
    perf.original_pixels = perf.pixels;
    perf.ok = ok;
    return ok;
}
