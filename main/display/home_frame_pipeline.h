#pragma once
#include <atomic>
#include <cstdint>
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "utils/home_render_options.h"
#include "home_pixel_diff.h"

// Two owned snapshots: at most one transmitting and one waiting. Only the
// producer copies pixels; only the transfer task touches the LCD/DMA buffers.
class HomeFramePipeline {
  public:
    struct Frame {
        const uint16_t *pixels;
        int stride, x1, y1, x2, y2;
    };
    using Transfer = bool (*)(void *, const Frame &, cubicat::HomeLcdFramePerf &);
    HomeFramePipeline(int width, int height, Transfer transfer, void *context);
    ~HomeFramePipeline();
    bool Initialize();
    // true means accepted for async calls; sync calls wait for DMA completion.
    bool Submit(const Frame &frame, bool synchronous, bool record_perf);
    void Drain();

  private:
    struct Job {
        int slot;
        int x1, y1, x2, y2;
        bool record_perf;
        HomePixelRect transmit;
        uint32_t epoch, compare_us;
    };
    static void TaskEntry(void *arg);
    void Run();
    void DrainLocked();
    void Cleanup();
    int width_, height_;
    Transfer transfer_;
    void *context_;
    uint16_t *snapshots_[2]{};
    SemaphoreHandle_t producer_mutex_ = nullptr, done_[2]{}, stopped_ = nullptr;
    QueueHandle_t free_slots_ = nullptr, jobs_ = nullptr;
    TaskHandle_t task_ = nullptr;
    std::atomic<bool> enabled_{false}, force_full_{false};
    std::atomic<uint32_t> epoch_{0};
    int previous_slot_ = -1; // producer mutex protects this and the valid rectangle.
    HomePixelRect previous_valid_;
    uint32_t previous_epoch_ = 0;
    bool results_[2]{}; // Published by done_[slot]; slot cannot be reused earlier.
};
