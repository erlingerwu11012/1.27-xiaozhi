#include "home_render_options.h"
#include <atomic>
#include <cstring>
#include <initializer_list>
#include "freertos/FreeRTOS.h"
namespace cubicat {
namespace {
std::atomic<bool> recovery{false};
std::atomic<HomeRenderMode> mode{HomeRenderMode::Combined};
std::atomic<HomeRenderProfile> profile{HomeRenderProfile::V2};
std::atomic<uint32_t> spi_mhz{30};
std::atomic<bool> pixel_diff{true}, stream_enabled{false}, diff_enabled{false};
std::atomic<const char *> stream_reason{"not_initialized"}, diff_reason{"not_initialized"};
std::atomic<bool> dual{false}, pipeline{false}, optimized{false};
std::atomic<const char *> drawing_reason{"not_initialized"};
std::atomic<uint32_t> fallbacks{0}, share_pct{33};
std::atomic<const char *> dual_reason{"not_initialized"}, pipeline_reason{"not_initialized"};
std::atomic<uint32_t> raster_stack{0}, lcd_stack{0};
portMUX_TYPE lcd_mux = portMUX_INITIALIZER_UNLOCKED;
HomeLcdPerfWindow lcd_window;
} // namespace
const char *HomeRenderModeName(HomeRenderMode value) {
    switch (value) {
    case HomeRenderMode::Baseline:
        return "baseline";
    case HomeRenderMode::Render:
        return "render";
    case HomeRenderMode::Pipeline:
        return "pipeline";
    case HomeRenderMode::Dual:
        return "dual";
    default:
        return "combined";
    }
}
bool ParseHomeRenderMode(const char *name, HomeRenderMode &result) {
    if (!name)
        return false;
    for (auto candidate :
         {HomeRenderMode::Baseline, HomeRenderMode::Render, HomeRenderMode::Pipeline,
          HomeRenderMode::Dual, HomeRenderMode::Combined}) {
        if (!strcmp(name, HomeRenderModeName(candidate))) {
            result = candidate;
            return true;
        }
    }
    return false;
}
void ConfigureHomeRenderMode(HomeRenderMode value) { mode.store(value); }
HomeRenderMode GetHomeRenderMode() { return mode.load(); }
bool HomeOptimizedDrawing() { return GetHomeRenderMode() != HomeRenderMode::Baseline; }
bool HomePipelineRequested() {
    auto v = GetHomeRenderMode();
    return v == HomeRenderMode::Pipeline || v == HomeRenderMode::Combined;
}
bool HomeDualRequested() {
    auto v = GetHomeRenderMode();
    return v == HomeRenderMode::Dual || v == HomeRenderMode::Combined;
}
void ConfigureHomeRenderOptions(HomeRenderProfile p, uint32_t mhz, bool diff) {
    profile.store(p);
    spi_mhz.store(mhz == 40 ? 40 : 30);
    pixel_diff.store(diff);
}
HomeRenderProfile GetHomeRenderProfile() { return profile.load(); }
const char *HomeRenderProfileName(HomeRenderProfile p) { return p == HomeRenderProfile::V1 ? "v1" : "v2"; }
uint32_t HomeLcdSpiMHz() {
    return GetHomeRenderMode() == HomeRenderMode::Baseline ? 30 : spi_mhz.load();
}
bool HomeV2Drawing() { return HomeOptimizedDrawing() && profile.load() == HomeRenderProfile::V2; }
bool HomeV2TransmissionRequested() { return HomePipelineRequested() && profile.load() == HomeRenderProfile::V2; }
bool HomePixelDiffRequested() { return HomeV2TransmissionRequested() && pixel_diff.load(); }
void CountFallback(std::atomic<const char *> &state, const char *reason) {
    const char *previous = state.exchange(reason);
    if (strcmp(previous, reason) && strcmp(reason, "enabled") &&
        strcmp(reason, "disabled_by_mode") && strcmp(reason, "stopped"))
        ++fallbacks;
}
void SetHomeStreamStatus(bool v, const char *reason) {
    stream_enabled.store(v);
    CountFallback(stream_reason, reason);
}
void SetHomePixelDiffStatus(bool v, const char *reason) {
    diff_enabled.store(v);
    CountFallback(diff_reason, reason);
}
void SetHomeDrawingStatus(bool v, const char *reason) {
    optimized.store(v);
    CountFallback(drawing_reason, reason);
}
void SetHomeDualSplit(uint32_t percent) { share_pct.store(percent); }
void SetHomeDualStatus(bool v, const char *reason, uint32_t stack) {
    dual.store(v);
    CountFallback(dual_reason, reason);
    if (stack != UINT32_MAX)
        raster_stack.store(stack);
}
void SetHomePipelineStatus(bool v, const char *reason, uint32_t stack) {
    pipeline.store(v);
    CountFallback(pipeline_reason, reason);
    if (stack != UINT32_MAX)
        lcd_stack.store(stack);
}
HomeRenderStatus GetHomeRenderStatus() {
    return {GetHomeRenderMode(),   dual.load(),        pipeline.load(),
            optimized.load(),      dual_reason.load(), pipeline_reason.load(),
            drawing_reason.load(), fallbacks.load(),   share_pct.load(),
            raster_stack.load(),   lcd_stack.load(), profile.load(), HomeLcdSpiMHz(),
            stream_enabled.load(), diff_enabled.load(), stream_reason.load(), diff_reason.load()};
}
void RecordHomeLcdAccept(uint32_t us, uint32_t copy, uint32_t wait, bool ok, bool blocked) {
    portENTER_CRITICAL(&lcd_mux);
    lcd_window.accept.Add(us);
    lcd_window.snapshot_copy.Add(copy);
    lcd_window.snapshot_wait.Add(wait);
    if (ok)
        ++lcd_window.accepted;
    else
        ++lcd_window.rejected;
    if (blocked)
        ++lcd_window.queue_blocks;
    portEXIT_CRITICAL(&lcd_mux);
}
void RecordHomeLcdTransfer(const HomeLcdFramePerf &f) {
    portENTER_CRITICAL(&lcd_mux);
    if (f.pixels) lcd_window.transfer.Add(f.transfer_us);
    lcd_window.compare.Add(f.compare_us);
    lcd_window.copy_swap_us += f.copy_swap_us;
    lcd_window.copy_us += f.copy_us;
    lcd_window.swap_us += f.swap_us;
    lcd_window.wait_us += f.wait_us;
    lcd_window.queue_us += f.queue_us;
    lcd_window.timeouts += f.timeouts;
    if (f.ok) {
        if (f.unchanged) ++lcd_window.unchanged;
        else if (f.pixels) ++lcd_window.completed;
        lcd_window.original_pixels += f.original_pixels ? f.original_pixels : f.pixels;
        lcd_window.pixels += f.pixels;
    } else
        ++lcd_window.failures;
    portEXIT_CRITICAL(&lcd_mux);
}
bool HomeLcdRecoveryRequested() { return recovery.load(); }
void RequestHomeLcdRecovery() { recovery.store(true); }
void ClearHomeLcdRecovery() { recovery.store(false); }
HomeLcdPerfWindow TakeHomeLcdPerfWindow() {
    portENTER_CRITICAL(&lcd_mux);
    auto result = lcd_window;
    lcd_window = {};
    portEXIT_CRITICAL(&lcd_mux);
    return result;
}
} // namespace cubicat
