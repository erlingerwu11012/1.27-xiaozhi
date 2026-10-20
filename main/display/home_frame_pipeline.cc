#include "home_frame_pipeline.h"
#include <algorithm>
#include <cstring>
#include "esp_heap_caps.h"
#include "esp_log.h"
#include "esp_timer.h"
namespace {
constexpr const char *kTag = "HomePipeline";
}
HomeFramePipeline::HomeFramePipeline(int width, int height, Transfer transfer, void *context)
    : width_(width), height_(height), transfer_(transfer), context_(context) {}
bool HomeFramePipeline::Initialize() {
    if (task_)
        return true;
    const char *failure = "buffer_or_queue_allocation_failed";
    producer_mutex_ = xSemaphoreCreateMutex();
    stopped_ = xSemaphoreCreateBinary();
    for (int i = 0; i < 2; ++i) {
        snapshots_[i] = static_cast<uint16_t *>(heap_caps_malloc(
            size_t(width_) * height_ * sizeof(uint16_t), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
        done_[i] = xSemaphoreCreateBinary();
    }
    free_slots_ = xQueueCreate(2, sizeof(int));
    jobs_ = xQueueCreate(1, sizeof(Job));
    if (producer_mutex_ && stopped_ && snapshots_[0] && snapshots_[1] && done_[0] && done_[1] &&
        free_slots_ && jobs_) {
        if (heap_caps_get_free_size(MALLOC_CAP_INTERNAL) < 4096 + 16 * 1024)
            failure = "internal_ram_headroom";
        else {
            for (int i = 0; i < 2; ++i)
                xQueueSend(free_slots_, &i, portMAX_DELAY);
            if (xTaskCreatePinnedToCore(TaskEntry, "home_lcd0", 4096, this, 1, &task_, 0) ==
                pdPASS) {
                enabled_.store(true);
                cubicat::SetHomePixelDiffStatus(cubicat::HomePixelDiffRequested(),
                    cubicat::HomePixelDiffRequested() ? "enabled" : "disabled_by_mode");
                cubicat::SetHomePipelineStatus(true, "enabled", uxTaskGetStackHighWaterMark(task_));
                return true;
            }
            failure = "task_allocation_failed";
        }
    }
    Cleanup();
    cubicat::SetHomePixelDiffStatus(false, failure);
    cubicat::SetHomePipelineStatus(false, failure);
    ESP_LOGW(kTag, "[RENDERFALLBACK] pipeline=%s; synchronous submission", failure);
    return false;
}
void HomeFramePipeline::Cleanup() {
    for (int i = 0; i < 2; ++i) {
        if (snapshots_[i]) {
            heap_caps_free(snapshots_[i]);
        }
        snapshots_[i] = nullptr;
        if (done_[i]) {
            vSemaphoreDelete(done_[i]);
        }
        done_[i] = nullptr;
    }
    if (free_slots_) {
        vQueueDelete(free_slots_);
    }
    free_slots_ = nullptr;
    if (jobs_) {
        vQueueDelete(jobs_);
    }
    jobs_ = nullptr;
    if (stopped_) {
        vSemaphoreDelete(stopped_);
    }
    stopped_ = nullptr;
    if (producer_mutex_) {
        vSemaphoreDelete(producer_mutex_);
    }
    producer_mutex_ = nullptr;
}
HomeFramePipeline::~HomeFramePipeline() {
    if (task_) {
        xSemaphoreTake(producer_mutex_, portMAX_DELAY);
        DrainLocked();
        Job stop{};
        stop.slot = -1;
        xQueueSend(jobs_, &stop, portMAX_DELAY);
        while (xSemaphoreTake(stopped_, pdMS_TO_TICKS(1000)) != pdTRUE)
            ESP_LOGW(kTag, "Waiting for transfer task shutdown; buffers retained");
        cubicat::SetHomePipelineStatus(false, "stopped");
        task_ = nullptr;
        xSemaphoreGive(producer_mutex_);
    }
    Cleanup();
}
void HomeFramePipeline::DrainLocked() {
    int slots[2];
    // Holding both free tokens proves no worker owns any snapshot or DMA data.
    for (int i = 0; i < 2; ++i)
        while (xQueueReceive(free_slots_, &slots[i], pdMS_TO_TICKS(1000)) != pdTRUE)
            ESP_LOGW(kTag, "Waiting for frame completion; buffers retained");
    for (int i = 0; i < 2; ++i)
        xQueueSend(free_slots_, &slots[i], portMAX_DELAY);
}
void HomeFramePipeline::Drain() {
    if (!task_)
        return;
    xSemaphoreTake(producer_mutex_, portMAX_DELAY);
    DrainLocked();
    previous_slot_ = -1; // Pause/resource reload may change the entire framebuffer.
    xSemaphoreGive(producer_mutex_);
}
bool HomeFramePipeline::Submit(const Frame &input, bool synchronous, bool record_perf) {
    if (!task_ || !input.pixels || input.stride < width_ || input.x1 < 0 || input.y1 < 0 ||
        input.x2 > width_ || input.y2 > height_ || input.x2 <= input.x1 || input.y2 <= input.y1)
        return false;
    xSemaphoreTake(producer_mutex_, portMAX_DELAY);
    const int64_t start = esp_timer_get_time();
    Frame f = input;
    int slot;
    const int64_t wait_start = esp_timer_get_time();
    bool blocked = xQueueReceive(free_slots_, &slot, 0) != pdTRUE;
    if (blocked)
        while (xQueueReceive(free_slots_, &slot, pdMS_TO_TICKS(1000)) != pdTRUE)
            ESP_LOGW(kTag, "Snapshot queue full; waiting without overwriting frames");
    uint32_t wait_us = esp_timer_get_time() - wait_start;
    bool recovering = force_full_.load() || cubicat::HomeLcdRecoveryRequested();
    if (recovering) {
        // We currently own a free slot: return it BEFORE draining both tokens.
        xQueueSend(free_slots_, &slot, portMAX_DELAY);
        DrainLocked();
        xQueueReceive(free_slots_, &slot, portMAX_DELAY);
        f.x1 = 0; f.y1 = 0; f.x2 = width_; f.y2 = height_;
        synchronous = true;
        previous_slot_ = -1;
    }
    const uint32_t epoch = epoch_.load();
    const HomePixelRect original{f.x1, f.y1, f.x2, f.y2};
    HomePixelRect transmit = original;
    uint32_t compare_us = 0;
    if (enabled_.load() && cubicat::HomePixelDiffRequested() && !synchronous && !recovering &&
        previous_slot_ >= 0 && previous_epoch_ == epoch) {
        const int64_t compare_start = esp_timer_get_time();
        transmit = HomeChangedPixels(f.pixels, f.stride, snapshots_[previous_slot_], width_,
                                     original, previous_valid_);
        compare_us = esp_timer_get_time() - compare_start;
    }
    xSemaphoreTake(done_[slot], 0);
    const int64_t copy_start = esp_timer_get_time();
    // Preserve the ORIGINAL window even when only a smaller area is transmitted.
    for (int y = f.y1; y < f.y2; ++y)
        std::memcpy(snapshots_[slot] + y * width_ + f.x1, f.pixels + y * f.stride + f.x1,
                    size_t(f.x2 - f.x1) * sizeof(uint16_t));
    const uint32_t copy_us = esp_timer_get_time() - copy_start;
    const Job job{slot, f.x1, f.y1, f.x2, f.y2, record_perf, transmit, epoch, compare_us};
    const int64_t queue_start = esp_timer_get_time();
    if (xQueueSend(jobs_, &job, 0) != pdTRUE) {
        blocked = true;
        xQueueSend(jobs_, &job, portMAX_DELAY);
    }
    wait_us += esp_timer_get_time() - queue_start;
    previous_slot_ = slot;
    previous_valid_ = original;
    previous_epoch_ = epoch;
    bool ok = true;
    if (synchronous || !enabled_.load()) {
        while (xSemaphoreTake(done_[slot], pdMS_TO_TICKS(1000)) != pdTRUE)
            ESP_LOGW(kTag, "Waiting for synchronous frame completion; snapshot retained");
        ok = results_[slot];
    }
    if (record_perf)
        cubicat::RecordHomeLcdAccept(esp_timer_get_time() - start, copy_us, wait_us, ok, blocked);
    xSemaphoreGive(producer_mutex_);
    return ok;
}
void HomeFramePipeline::TaskEntry(void *arg) { static_cast<HomeFramePipeline *>(arg)->Run(); }
void HomeFramePipeline::Run() {
    for (;;) {
        Job job{};
        xQueueReceive(jobs_, &job, portMAX_DELAY);
        if (job.slot < 0)
            break;
        cubicat::HomeLcdFramePerf perf;
        const bool stale = job.epoch != epoch_.load();
        if (stale) {
            // An earlier accepted frame failed. Dependent deltas are invalid.
            results_[job.slot] = false;
            perf.ok = false;
        } else if (job.transmit.Empty()) {
            results_[job.slot] = true;
            perf.ok = true;
            perf.unchanged = true;
        } else {
            const Frame frame{snapshots_[job.slot], width_, job.transmit.x1, job.transmit.y1,
                              job.transmit.x2, job.transmit.y2};
            results_[job.slot] = transfer_(context_, frame, perf);
        }
        perf.original_pixels = uint32_t(job.x2 - job.x1) * (job.y2 - job.y1);
        perf.compare_us = job.compare_us;
        if (!results_[job.slot]) {
            if (!stale) epoch_.fetch_add(1);
            cubicat::SetHomePixelDiffStatus(false, "transfer_failed");
            // Transfer has drained its DMA buffers before returning failure.
            // The next producer sends the whole latest framebuffer synchronously.
            force_full_.store(true);
            cubicat::RequestHomeLcdRecovery();
            enabled_.store(false);
            cubicat::SetHomePipelineStatus(false, "transfer_failed",
                                           uxTaskGetStackHighWaterMark(nullptr));
            ESP_LOGE(kTag, "[RENDERFALLBACK] transfer failed; full-frame synchronous recovery");
        } else {
            if (!perf.unchanged && job.transmit.x1 == 0 && job.transmit.y1 == 0 &&
                job.transmit.x2 == width_ && job.transmit.y2 == height_) {
                force_full_.store(false);
                cubicat::ClearHomeLcdRecovery();
            }
            if (enabled_.load())
                cubicat::SetHomePipelineStatus(true, "enabled",
                                               uxTaskGetStackHighWaterMark(nullptr));
        }
        if (job.record_perf)
            cubicat::RecordHomeLcdTransfer(perf);
        xSemaphoreGive(done_[job.slot]);
        xQueueSend(free_slots_, &job.slot, portMAX_DELAY);
    }
    xSemaphoreGive(stopped_);
    vTaskDelete(nullptr);
}
