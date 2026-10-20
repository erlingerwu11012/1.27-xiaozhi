#pragma once
#include <cstdint>
#include "home_perf.h"

namespace cubicat {
enum class HomeRenderMode : uint8_t { Baseline, Render, Pipeline, Dual, Combined };
const char *HomeRenderModeName(HomeRenderMode mode);
bool ParseHomeRenderMode(const char *name, HomeRenderMode &mode);
void ConfigureHomeRenderMode(HomeRenderMode mode);
HomeRenderMode GetHomeRenderMode();
bool HomeOptimizedDrawing();
bool HomePipelineRequested();
bool HomeDualRequested();
enum class HomeRenderProfile : uint8_t { V1, V2 };
void ConfigureHomeRenderOptions(HomeRenderProfile profile, uint32_t spi_mhz, bool pixel_diff);
HomeRenderProfile GetHomeRenderProfile();
const char *HomeRenderProfileName(HomeRenderProfile profile);
uint32_t HomeLcdSpiMHz();
bool HomeV2Drawing();
bool HomeV2TransmissionRequested();
bool HomePixelDiffRequested();
void SetHomeStreamStatus(bool enabled, const char *reason);
void SetHomePixelDiffStatus(bool enabled, const char *reason);
// Independent status counters are safe to read from the MCP thread.
void SetHomeDrawingStatus(bool enabled, const char *reason);
void SetHomeDualSplit(uint32_t percent);
void SetHomeDualStatus(bool enabled, const char *reason, uint32_t stack_free = UINT32_MAX);
void SetHomePipelineStatus(bool enabled, const char *reason, uint32_t stack_free = UINT32_MAX);
struct HomeRenderStatus {
    HomeRenderMode mode;
    bool dual_enabled, pipeline_enabled, optimized_enabled;
    const char *dual_reason;
    const char *pipeline_reason;
    const char *drawing_reason;
    uint32_t fallback_count, core0_share_pct;
    uint32_t raster_stack_free, lcd_stack_free;
    HomeRenderProfile profile;
    uint32_t spi_mhz;
    bool stream_enabled, pixel_diff_enabled;
    const char *stream_reason, *pixel_diff_reason;
};
HomeRenderStatus GetHomeRenderStatus();

// Producer/transfer task measurements are merged only at frame boundaries.
struct HomeLcdFramePerf {
    uint32_t copy_us = 0, swap_us = 0, wait_us = 0, queue_us = 0, transfer_us = 0;
    uint32_t pixels = 0, timeouts = 0;
    uint32_t original_pixels = 0, compare_us = 0, copy_swap_us = 0;
    bool unchanged = false;
    bool ok = false;
};
struct HomeLcdPerfWindow {
    HomePerfStage accept, snapshot_copy, snapshot_wait, transfer, compare;
    uint64_t copy_us = 0, swap_us = 0, wait_us = 0, queue_us = 0, pixels = 0;
    uint64_t original_pixels = 0, copy_swap_us = 0;
    uint32_t unchanged = 0;
    uint32_t accepted = 0, completed = 0, failures = 0, rejected = 0, timeouts = 0,
             queue_blocks = 0;
};
void RecordHomeLcdAccept(uint32_t elapsed_us, uint32_t snapshot_us, uint32_t wait_us, bool ok,
                         bool blocked);
void RecordHomeLcdTransfer(const HomeLcdFramePerf &frame);
HomeLcdPerfWindow TakeHomeLcdPerfWindow();
bool HomeLcdRecoveryRequested();
void RequestHomeLcdRecovery();
void ClearHomeLcdRecovery();
} // namespace cubicat
