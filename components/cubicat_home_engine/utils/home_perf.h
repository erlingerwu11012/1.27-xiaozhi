#pragma once
#include <cstdint>
#include "esp_cpu.h"
#include "esp_timer.h"

namespace cubicat {
// Render-task-only counters; nested measurements must not be added together.
struct HomePerfStage {
    uint64_t total_us = 0;
    uint32_t calls = 0, max_us = 0;
    void Add(uint32_t us) {
        total_us += us;
        ++calls;
        if (us > max_us) max_us = us;
    }
    uint32_t Average() const { return calls ? total_us / calls : 0; }
};
struct HomePerfCounters {
    HomePerfStage frame, engine, animation, mesh, prepare, draw, polygon;
    HomePerfStage submit, copy, swap, wait, queue;
    HomePerfStage core0_draw, core1_draw, join_wait, packet_prepare;
    // Nested stages: never add these to their enclosing engine/prepare stages.
    HomePerfStage traversal, drawable_collect, edges, edge_schedule;
    uint32_t dual_frames=0, dual_timeouts=0, fast_quads=0, active_edge_draws=0;
    uint64_t alpha_pixels = 0, alpha_cycles = 0;
    uint32_t alpha_samples = 0, alpha_frames = 0, cycle_read_overhead = 0;
    bool alpha_enabled = false;
    void Calibrate() {
        cycle_read_overhead = UINT32_MAX;
        for (unsigned i = 0; i < 64; ++i) {
            const uint32_t start = esp_cpu_get_cycle_count();
            const uint32_t elapsed = esp_cpu_get_cycle_count() - start;
            if (elapsed < cycle_read_overhead) cycle_read_overhead = elapsed;
        }
    }
    void BeginDraw() {
        // Sample one in 16 rendered frames, one in 256 half-transparent pixels.
        alpha_enabled = (draw.calls & 15U) == 0;
        if (alpha_enabled) ++alpha_frames;
    }
    uint32_t BeginAlphaSample() {
        if (!alpha_enabled) return 0;
        ++alpha_pixels;
        return (alpha_pixels & 255U) == 0 ? esp_cpu_get_cycle_count() : 0;
    }
    void EndAlphaSample(uint32_t start, uint32_t result) {
        if (!alpha_enabled || (alpha_pixels & 255U) != 0) return;
        // Keep the blend result inside the sampled interval under optimization.
        asm volatile("" : : "r"(result) : "memory");
        const uint32_t elapsed = esp_cpu_get_cycle_count() - start;
        alpha_cycles += elapsed > cycle_read_overhead ? elapsed - cycle_read_overhead : 0;
        ++alpha_samples;
    }
    uint32_t AlphaEstimateUs(uint32_t cpu_mhz) const {
        if (!alpha_samples || !alpha_frames || !cpu_mhz) return 0;
        return static_cast<uint32_t>(alpha_cycles * alpha_pixels /
                                    alpha_samples / cpu_mhz / alpha_frames);
    }
    void Reset() {
        const uint32_t overhead = cycle_read_overhead;
        *this = HomePerfCounters{};
        cycle_read_overhead = overhead;
    }
};
inline HomePerfCounters& HomePerf() {
    static HomePerfCounters counters;
    return counters;
}
class HomePerfScope {
public:
    explicit HomePerfScope(HomePerfStage& stage)
        : stage_(stage), start_(esp_timer_get_time()) {}
    ~HomePerfScope() {
        stage_.Add(static_cast<uint32_t>(esp_timer_get_time() - start_));
    }
private:
    HomePerfStage& stage_;
    int64_t start_;
};
}  // namespace cubicat
