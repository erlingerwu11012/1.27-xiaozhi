#include "task_diagnostics.h"

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <esp_timer.h>
#include <sdkconfig.h>
#include <freertos/idf_additions.h>
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>

namespace task_diag {
namespace {

constexpr const char* TAG = "TaskDiag";
constexpr uint32_t kInitialDelayMs = 8000;
constexpr uint32_t kIntervalMs = 15000;
#if CONFIG_TASK_DIAGNOSTICS_PERIODIC
constexpr UBaseType_t kMaxRuntimeTasks = 48;
constexpr size_t kMaxTaskCpuLogs = 32;
#endif
constexpr size_t kPsramBenchmarkBytes = 256 * 1024;
constexpr size_t kPsramBenchmarkChunkBytes = 32 * 1024;
constexpr int kPsramBenchmarkIterations = 4;

bool s_periodic_logger_started = false;
TaskHandle_t s_periodic_task = nullptr;

struct FailedAllocRecord {
    std::atomic<uint32_t> pending{0};
    std::atomic<uint32_t> size{0};
    std::atomic<uint32_t> caps{0};
};

FailedAllocRecord s_failed_alloc;

void AllocFailedHook(size_t size, uint32_t caps, const char*) {
    // Must not allocate, block, or call into ESP_LOG from this callback.
    s_failed_alloc.size.store(static_cast<uint32_t>(size), std::memory_order_relaxed);
    s_failed_alloc.caps.store(caps, std::memory_order_relaxed);
    s_failed_alloc.pending.store(1, std::memory_order_release);
}

void DrainFailedAlloc() {
    if (s_failed_alloc.pending.load(std::memory_order_acquire) == 0) return;
    const uint32_t size = s_failed_alloc.size.load(std::memory_order_relaxed);
    const uint32_t caps = s_failed_alloc.caps.load(std::memory_order_relaxed);
    s_failed_alloc.pending.store(0, std::memory_order_release);
    ESP_LOGW(TAG, "[ALLOCFAIL] size=%u caps=0x%x",
             (unsigned)size, (unsigned)caps);
}

#if CONFIG_TASK_DIAGNOSTICS_PERIODIC
struct CpuSnapshot {
    bool valid = false;
    configRUN_TIME_COUNTER_TYPE total_runtime = 0;
    configRUN_TIME_COUNTER_TYPE idle_runtime[CONFIG_FREERTOS_NUMBER_OF_CORES] = {};
    struct TaskRuntime {
        UBaseType_t task_number = 0;
        configRUN_TIME_COUNTER_TYPE runtime = 0;
    } tasks[kMaxRuntimeTasks];
    UBaseType_t task_count = 0;
    int64_t sampled_at_us = 0;
};

CpuSnapshot s_cpu_snapshot;
#endif

const char* CoreText(BaseType_t core) {
    if (core == 0) return "0";
    if (core == 1) return "1";
    if (core == tskNO_AFFINITY) return "any";
    return "?";
}

void LogHeap(const char* owner, const char* reason) {
    const size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    const size_t internal_largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
    const size_t dma_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    const size_t dma_largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL | MALLOC_CAP_DMA);
    ESP_LOGI(TAG,
             "[TASKHEAP] owner=%s reason=%s internal_free=%u internal_largest=%u dma_free=%u dma_largest=%u",
             owner ? owner : "-", reason ? reason : "-",
             (unsigned)internal_free, (unsigned)internal_largest,
             (unsigned)dma_free, (unsigned)dma_largest);
}

double MiBPerSecond(size_t bytes, int64_t elapsed_us) {
    if (elapsed_us <= 0) return 0.0;
    return (static_cast<double>(bytes) * 1000000.0) /
           (static_cast<double>(elapsed_us) * 1024.0 * 1024.0);
}
#if CONFIG_TASK_DIAGNOSTICS_PERIODIC
void LogCpuAndMemory(const char* owner, const char* reason) {
#if CONFIG_FREERTOS_GENERATE_RUN_TIME_STATS && CONFIG_FREERTOS_USE_TRACE_FACILITY
    struct CpuWork {
        TaskStatus_t tasks[kMaxRuntimeTasks];
        struct TaskCpuUsage {
            const TaskStatus_t* task = nullptr;
            uint32_t percent = 0;
        } usage[kMaxRuntimeTasks];
    };
    CpuWork* work = static_cast<CpuWork*>(heap_caps_malloc(
        sizeof(CpuWork), MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (work == nullptr) {
        ESP_LOGW(TAG,
                 "[TASKPERF] owner=%s reason=%s cpu workspace allocation failed "
                 "bytes=%u",
                 owner ? owner : "-", reason ? reason : "-",
                 (unsigned)sizeof(CpuWork));
        const size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
        const size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
        ESP_LOGI(TAG,
                 "[TASKPERF] owner=%s reason=%s internal_free=%u psram_free=%u",
                 owner ? owner : "-", reason ? reason : "-",
                 (unsigned)internal_free, (unsigned)psram_free);
        return;
    }
    memset(work, 0, sizeof(*work));

    configRUN_TIME_COUNTER_TYPE total_runtime = 0;
    const UBaseType_t task_count =
        uxTaskGetSystemState(work->tasks, kMaxRuntimeTasks, &total_runtime);
    if (task_count == 0) {
        ESP_LOGW(TAG, "[TASKPERF] owner=%s reason=%s runtime stats unavailable",
                 owner ? owner : "-", reason ? reason : "-");
        heap_caps_free(work);
        return;
    }
    if (task_count == kMaxRuntimeTasks) {
        ESP_LOGW(TAG,
                 "[TASKPERF] owner=%s reason=%s task table truncated capacity=%u",
                 owner ? owner : "-", reason ? reason : "-",
                 (unsigned)kMaxRuntimeTasks);
        heap_caps_free(work);
        return;
    }

    configRUN_TIME_COUNTER_TYPE idle_runtime[CONFIG_FREERTOS_NUMBER_OF_CORES] = {};
    bool idle_found[CONFIG_FREERTOS_NUMBER_OF_CORES] = {};
    for (UBaseType_t i = 0; i < task_count; ++i) {
        for (int core = 0; core < CONFIG_FREERTOS_NUMBER_OF_CORES; ++core) {
            char idle_name[8] = {};
            snprintf(idle_name, sizeof(idle_name), "IDLE%d", core);
            if (strcmp(work->tasks[i].pcTaskName, idle_name) == 0) {
                idle_runtime[core] = work->tasks[i].ulRunTimeCounter;
                idle_found[core] = true;
            }
        }
    }

    const int64_t sampled_at_us = esp_timer_get_time();
    if (!s_cpu_snapshot.valid) {
        s_cpu_snapshot.valid = true;
        s_cpu_snapshot.total_runtime = total_runtime;
        memcpy(s_cpu_snapshot.idle_runtime, idle_runtime, sizeof(idle_runtime));
        s_cpu_snapshot.task_count = task_count;
        for (UBaseType_t i = 0; i < task_count; ++i) {
            s_cpu_snapshot.tasks[i] = {work->tasks[i].xTaskNumber,
                                       work->tasks[i].ulRunTimeCounter};
        }
        s_cpu_snapshot.sampled_at_us = sampled_at_us;
        ESP_LOGI(TAG, "[TASKPERF] owner=%s reason=%s CPU sampler primed",
                 owner ? owner : "-", reason ? reason : "-");
        heap_caps_free(work);
        return;
    }

    const configRUN_TIME_COUNTER_TYPE elapsed_runtime = total_runtime - s_cpu_snapshot.total_runtime;
    const uint32_t elapsed_ms = static_cast<uint32_t>((sampled_at_us - s_cpu_snapshot.sampled_at_us) / 1000);
    if (elapsed_runtime == 0) {
        ESP_LOGW(TAG, "[TASKPERF] owner=%s reason=%s runtime clock did not advance",
                 owner ? owner : "-", reason ? reason : "-");
        heap_caps_free(work);
        return;
    }
    int cpu_percent[CONFIG_FREERTOS_NUMBER_OF_CORES] = {};
    for (int core = 0; core < CONFIG_FREERTOS_NUMBER_OF_CORES; ++core) {
        if (!idle_found[core] || elapsed_runtime == 0) {
            cpu_percent[core] = -1;
            continue;
        }
        const configRUN_TIME_COUNTER_TYPE idle_elapsed = idle_runtime[core] - s_cpu_snapshot.idle_runtime[core];
        const uint32_t idle_percent = static_cast<uint32_t>((idle_elapsed * 100U) / elapsed_runtime);
        cpu_percent[core] = 100 - static_cast<int>(idle_percent > 100 ? 100 : idle_percent);
    }

    const size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    const size_t internal_minimum = heap_caps_get_minimum_free_size(MALLOC_CAP_INTERNAL);
    const size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    const size_t psram_minimum = heap_caps_get_minimum_free_size(MALLOC_CAP_SPIRAM);
    const size_t psram_largest = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
    const int cpu_average = (cpu_percent[0] >= 0 && cpu_percent[1] >= 0)
                                ? (cpu_percent[0] + cpu_percent[1]) / 2
                                : -1;
    ESP_LOGI(TAG,
             "[TASKPERF] owner=%s reason=%s window_ms=%u cpu_mhz=%d cpu_core0=%d%% cpu_core1=%d%% cpu_avg=%d%% internal_free=%u internal_min=%u psram_free=%u psram_min=%u psram_largest=%u",
             owner ? owner : "-", reason ? reason : "-", (unsigned)elapsed_ms,
             CONFIG_ESP_DEFAULT_CPU_FREQ_MHZ,
             cpu_percent[0], cpu_percent[1], cpu_average,
             (unsigned)internal_free, (unsigned)internal_minimum,
             (unsigned)psram_free, (unsigned)psram_minimum,
             (unsigned)psram_largest);

    size_t usage_count = 0;
    for (UBaseType_t i = 0; i < task_count; ++i) {
        configRUN_TIME_COUNTER_TYPE previous_runtime = 0;
        bool previous_found = false;
        for (UBaseType_t j = 0; j < s_cpu_snapshot.task_count; ++j) {
            if (s_cpu_snapshot.tasks[j].task_number == work->tasks[i].xTaskNumber) {
                previous_runtime = s_cpu_snapshot.tasks[j].runtime;
                previous_found = true;
                break;
            }
        }
        if (!previous_found || strncmp(work->tasks[i].pcTaskName, "IDLE", 4) == 0) continue;

        const configRUN_TIME_COUNTER_TYPE runtime_delta = work->tasks[i].ulRunTimeCounter - previous_runtime;
        const uint32_t percent = static_cast<uint32_t>((runtime_delta * 100U) / elapsed_runtime);
        if (percent == 0) continue;
        work->usage[usage_count++] = {&work->tasks[i], percent};
    }
    std::sort(work->usage, work->usage + usage_count,
              [](const CpuWork::TaskCpuUsage& left, const CpuWork::TaskCpuUsage& right) {
                  return left.percent > right.percent;
              });
    for (size_t i = 0; i < std::min(usage_count, kMaxTaskCpuLogs); ++i) {
        const TaskStatus_t* task = work->usage[i].task;
        ESP_LOGI(TAG, "[TASKCPU] task=%-16s cpu=%u%% prio=%u core=%s",
                 task->pcTaskName, (unsigned)work->usage[i].percent,
                 (unsigned)task->uxCurrentPriority, CoreText(xTaskGetCoreID(task->xHandle)));
    }

    s_cpu_snapshot.total_runtime = total_runtime;
    memcpy(s_cpu_snapshot.idle_runtime, idle_runtime, sizeof(idle_runtime));
    s_cpu_snapshot.task_count = task_count;
    for (UBaseType_t i = 0; i < task_count; ++i) {
        s_cpu_snapshot.tasks[i] = {work->tasks[i].xTaskNumber, work->tasks[i].ulRunTimeCounter};
    }
    s_cpu_snapshot.sampled_at_us = sampled_at_us;
    heap_caps_free(work);
#else
    ESP_LOGW(TAG, "[TASKPERF] owner=%s reason=%s runtime stats disabled",
             owner ? owner : "-", reason ? reason : "-");
#endif
}

#endif

void PeriodicLoggerTask(void*) {
    vTaskDelay(pdMS_TO_TICKS(kInitialDelayMs));
#if CONFIG_TASK_DIAGNOSTICS_PERIODIC && defined(CONFIG_TASK_DIAGNOSTICS_PSRAM_BENCHMARK)
    RunPsramBenchmark("periodic", "boot_benchmark");
#endif
    while (true) {
        DrainFailedAlloc();
#if CONFIG_TASK_DIAGNOSTICS_PERIODIC
        LogCpuAndMemory("periodic", "watch");
        LogNamedTasks("periodic", "watch");
        LogTaskList("periodic", "watch");
#endif
        vTaskDelay(pdMS_TO_TICKS(kIntervalMs));
    }
}

}  // namespace

void LogCurrentTask(const char* owner, const char* phase, int expected_priority, int expected_core) {
    LogTaskHandle(owner, phase, xTaskGetCurrentTaskHandle(), expected_priority, expected_core);
}

void LogTaskHandle(const char* owner, const char* label, TaskHandle_t handle,
                   int expected_priority, int expected_core) {
    if (handle == nullptr) {
        ESP_LOGW(TAG, "[TASKCFG] owner=%s label=%s handle=null expected_prio=%d expected_core=%d",
                 owner ? owner : "-", label ? label : "-", expected_priority, expected_core);
        return;
    }

    const UBaseType_t actual_priority = uxTaskPriorityGet(handle);
    const BaseType_t actual_core = xTaskGetCoreID(handle);
#if INCLUDE_uxTaskGetStackHighWaterMark
    const UBaseType_t stack_hwm_raw = uxTaskGetStackHighWaterMark(handle);
#else
    const UBaseType_t stack_hwm_raw = 0;
#endif
    const size_t stack_hwm_bytes =
        static_cast<size_t>(stack_hwm_raw) * sizeof(StackType_t);

    const char* task_name = "?";
#if INCLUDE_pcTaskGetName
    task_name = pcTaskGetName(handle);
#endif

    ESP_LOGI(TAG,
             "[TASKCFG] owner=%s label=%s task=%s prio=%u expected_prio=%d core=%s expected_core=%d stack_hwm_bytes=%u",
             owner ? owner : "-", label ? label : "-", task_name,
             (unsigned)actual_priority, expected_priority, CoreText(actual_core),
             expected_core, (unsigned)stack_hwm_bytes);
}

void LogNamedTasks(const char* owner, const char* reason) {
    LogHeap(owner, reason);

#if INCLUDE_xTaskGetHandle
    struct ExpectedTask {
        const char* label;
        const char* lookup_name;
        int priority;
        int core;
        bool required;
    };

    static constexpr ExpectedTask kTasks[] = {
        {"usb_proc", "usb_proc", 10, 1, false},
        {"usb_stream_proc", "usb_stream_proc", 9, 1, false},
        {"sample_proc", "sample_proc", 8, 1, false},
        {"opus_codec", "opus_codec", 12, -1, true},
        {"audio_input", "audio_input", 8, 0, true},
        {"main_event_loop", "main_event_loop", 6, -1, true},
        {"udp_rx", "udp_rx", 5, -1, false},
        {"audio_output", "audio_output", 4, -1, true},
        {"capture_task", "capture_task", 4, -1, false},
        {"audio_detection", "audio_detection", 3, -1, false},
        {"audio_communication", "audio_communica", 3, -1, false},
        {"usb_cam_init", "usb_cam_init", 3, -1, false},
        {"preview_task", "preview_task", 3, -1, false},
        {"presence_notify", "presence_notify", 3, -1, false},
        {"touch", "touch", 3, -1, false},
        {"encode_wake_word", "encode_wake_wor", 2, -1, false},
        {"presence_absence", "presence_absenc", 2, -1, false},
        {"face_enroll", "face_enroll", 3, -1, false},
        {"face_enroll_cln", "face_enroll_cln", 2, -1, false},
        {"face_cfg", "face_cfg", 4, -1, false},
        {"task_diag", "task_diag", 1, -1, false},
        {"Tmr Svc", "Tmr Svc", 1, -1, true},
    };

    for (const auto& task : kTasks) {
        TaskHandle_t handle = xTaskGetHandle(task.lookup_name);
        if (handle == nullptr) {
            if (task.required) {
                ESP_LOGW(TAG, "[TASKMISS] owner=%s reason=%s task=%s lookup=%s expected_prio=%d expected_core=%d",
                         owner ? owner : "-", reason ? reason : "-", task.label, task.lookup_name,
                         task.priority, task.core);
            } else {
                ESP_LOGD(TAG, "[TASKOPT] owner=%s reason=%s task=%s lookup=%s expected_prio=%d expected_core=%d",
                         owner ? owner : "-", reason ? reason : "-", task.label, task.lookup_name,
                         task.priority, task.core);
            }
            continue;
        }
        LogTaskHandle(owner, task.label, handle, task.priority, task.core);
    }
#else
    ESP_LOGW(TAG, "[TASKCFG] xTaskGetHandle disabled; use TASKLIST snapshot only");
#endif
}

void LogTaskList(const char* owner, const char* reason) {
#if CONFIG_FREERTOS_USE_TRACE_FACILITY && CONFIG_FREERTOS_USE_STATS_FORMATTING_FUNCTIONS
    constexpr size_t kTaskListBufferSize = 8192;
    char* buffer = static_cast<char*>(heap_caps_malloc(kTaskListBufferSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    if (buffer == nullptr) {
        ESP_LOGE(TAG, "[TASKLIST] owner=%s reason=%s allocation failed",
                 owner ? owner : "-", reason ? reason : "-");
        return;
    }

    memset(buffer, 0, kTaskListBufferSize);
    vTaskList(buffer);
    ESP_LOGI(TAG, "[TASKLIST] owner=%s reason=%s name\\tstate\\tprio\\tstack\\tnum\\tcore",
             owner ? owner : "-", reason ? reason : "-");

    char* save = nullptr;
    for (char* line = strtok_r(buffer, "\r\n", &save);
         line != nullptr;
         line = strtok_r(nullptr, "\r\n", &save)) {
        ESP_LOGI(TAG, "[TASKLIST] %s", line);
    }

    heap_caps_free(buffer);
#else
    ESP_LOGW(TAG, "[TASKLIST] FreeRTOS task list formatting is disabled");
#endif
}

void RunPsramBenchmark(const char* owner, const char* reason) {
    uint8_t* psram = static_cast<uint8_t*>(heap_caps_malloc(
        kPsramBenchmarkBytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT));
    uint8_t* scratch = static_cast<uint8_t*>(heap_caps_malloc(
        kPsramBenchmarkChunkBytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT));
    if (psram == nullptr || scratch == nullptr) {
        ESP_LOGW(TAG,
                 "[PSRAMPERF] owner=%s reason=%s allocation_failed bytes=%u chunk=%u free=%u largest=%u",
                 owner ? owner : "-", reason ? reason : "-",
                 (unsigned)kPsramBenchmarkBytes, (unsigned)kPsramBenchmarkChunkBytes,
                 (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                 (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
        if (psram != nullptr) heap_caps_free(psram);
        if (scratch != nullptr) heap_caps_free(scratch);
        return;
    }
    for (size_t i = 0; i < kPsramBenchmarkChunkBytes; ++i) {
        scratch[i] = static_cast<uint8_t>(i * 31U + 17U);
    }
    const size_t free_before = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    volatile uint32_t checksum = 0;
    int64_t start = esp_timer_get_time();
    for (int iteration = 0; iteration < kPsramBenchmarkIterations; ++iteration) {
        for (size_t offset = 0; offset < kPsramBenchmarkBytes;
             offset += kPsramBenchmarkChunkBytes) {
            memcpy(psram + offset, scratch, kPsramBenchmarkChunkBytes);
        }
    }
    const int64_t write_us = esp_timer_get_time() - start;
    start = esp_timer_get_time();
    for (int iteration = 0; iteration < kPsramBenchmarkIterations; ++iteration) {
        for (size_t offset = 0; offset < kPsramBenchmarkBytes;
             offset += kPsramBenchmarkChunkBytes) {
            memcpy(scratch, psram + offset, kPsramBenchmarkChunkBytes);
            checksum += scratch[(offset / kPsramBenchmarkChunkBytes + iteration) %
                                kPsramBenchmarkChunkBytes];
        }
    }
    const int64_t read_us = esp_timer_get_time() - start;
    ESP_LOGI(TAG,
             "[PSRAMPERF] owner=%s reason=%s bytes=%u iterations=%d "
             "write_mib_s=%.2f read_mib_s=%.2f write_us=%lld read_us=%lld "
             "free_before=%u free_after=%u checksum=%u",
             owner ? owner : "-", reason ? reason : "-",
             (unsigned)kPsramBenchmarkBytes, kPsramBenchmarkIterations,
             MiBPerSecond(kPsramBenchmarkBytes * kPsramBenchmarkIterations, write_us),
             MiBPerSecond(kPsramBenchmarkBytes * kPsramBenchmarkIterations, read_us),
             static_cast<long long>(write_us), static_cast<long long>(read_us),
             (unsigned)free_before,
             (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
             static_cast<unsigned>(checksum));
    heap_caps_free(psram);
    heap_caps_free(scratch);
}
void LogMemoryStage(const char* owner, const char* phase) {
    const size_t internal_free = heap_caps_get_free_size(MALLOC_CAP_INTERNAL);
    const size_t internal_largest = heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL);
    const size_t psram_free = heap_caps_get_free_size(MALLOC_CAP_SPIRAM);
    const size_t psram_largest = heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM);
    const char* task_name = "?";
#if INCLUDE_pcTaskGetName
    task_name = pcTaskGetName(xTaskGetCurrentTaskHandle());
#endif
#if INCLUDE_uxTaskGetStackHighWaterMark
    const size_t stack_hwm_bytes =
        static_cast<size_t>(uxTaskGetStackHighWaterMark(nullptr)) * sizeof(StackType_t);
#else
    const size_t stack_hwm_bytes = 0;
#endif
    ESP_LOGI(TAG,
             "[MEMSTAGE] owner=%s phase=%s task=%s internal_free=%u "
             "internal_largest=%u psram_free=%u psram_largest=%u "
             "stack_hwm_bytes=%u",
             owner ? owner : "-", phase ? phase : "-", task_name ? task_name : "?",
             (unsigned)internal_free, (unsigned)internal_largest,
             (unsigned)psram_free, (unsigned)psram_largest,
             (unsigned)stack_hwm_bytes);
}

void StartPeriodicTaskLogger() {
    if (s_periodic_logger_started) {
        return;
    }
    s_periodic_logger_started = true;
    heap_caps_register_failed_alloc_callback(AllocFailedHook);
    BaseType_t ok = xTaskCreateWithCaps(
        PeriodicLoggerTask, "task_diag", 8192, nullptr, 1, &s_periodic_task,
        MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
    if (ok != pdPASS) {
        s_periodic_logger_started = false;
        s_periodic_task = nullptr;
        ESP_LOGE(TAG, "[TASKCFG] failed to create periodic logger");
    }
}

}  // namespace task_diag
