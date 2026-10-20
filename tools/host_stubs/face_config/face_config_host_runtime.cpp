#include "face_config_host_hooks.h"

#include "nvs_flash.h"
#include "task_diagnostics.h"

#include <freertos/FreeRTOS.h>
#include <freertos/idf_additions.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <functional>
#include <map>
#include <mutex>
#include <string>
#include <thread>
#include <utility>
#include <vector>

struct HostQueue {
    std::mutex mu;
    std::condition_variable cv;
    std::deque<void*> items;
    UBaseType_t length = 0;
};

struct HostSem {
    std::mutex mu;
    std::condition_variable cv;
    bool given = false;
};

namespace {

std::mutex g_mu;
std::condition_variable g_cv;
int g_fail_alloc = 0;
int g_fail_queue = 0;
int g_fail_task = 0;
int g_queue_attempts = 0;
int g_queue_success = 0;
int g_task_attempts = 0;
int g_task_success = 0;
uint32_t g_submit_timeout_ms = 3000;
bool g_block_worker = false;
std::atomic<int> g_live_requests{0};
std::atomic<bool> g_stop_worker{false};
HostQueue* g_last_queue = nullptr;

std::map<std::string, bool> g_open_error;
std::map<std::string, std::map<std::string, bool>> g_get_error;
std::map<std::string, bool> g_ns_exists;
std::map<std::string, std::map<std::string, std::string>> g_str;
std::map<std::string, std::map<std::string, int32_t>> g_i32;
std::map<std::string, std::map<std::string, uint8_t>> g_u8;
std::map<std::string, std::map<std::string, int>> g_get_i32_calls;
std::map<std::string, std::map<std::string, int>> g_get_u8_calls;
std::map<std::string, std::map<std::string, int>> g_get_str_calls;

struct NvsHandle {
    std::string ns;
    bool read_write = false;
};
std::vector<NvsHandle> g_handles;

}  // namespace

namespace face_config_host {

void ResetHooks() {
    std::lock_guard<std::mutex> lock(g_mu);
    g_fail_alloc = 0;
    g_fail_queue = 0;
    g_fail_task = 0;
    g_queue_attempts = 0;
    g_queue_success = 0;
    g_task_attempts = 0;
    g_task_success = 0;
    g_submit_timeout_ms = 3000;
    g_block_worker = false;
    g_stop_worker.store(false);
    g_open_error.clear();
    g_get_error.clear();
    g_get_i32_calls.clear();
    g_get_u8_calls.clear();
    g_get_str_calls.clear();
    g_last_queue = nullptr;
}

bool ShouldFailAlloc() {
    std::lock_guard<std::mutex> lock(g_mu);
    if (g_fail_alloc <= 0) return false;
    --g_fail_alloc;
    return true;
}

void SetFailNextAllocs(int n) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_fail_alloc = n;
}

void SetFailNextQueueCreates(int n) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_fail_queue = n;
}

void SetFailNextTaskCreates(int n) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_fail_task = n;
}

int QueueCreateAttempts() {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_queue_attempts;
}

int QueueCreateSuccesses() {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_queue_success;
}

int TaskCreateAttempts() {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_task_attempts;
}

int TaskCreateSuccesses() {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_task_success;
}

void SetSubmitTimeoutMs(uint32_t ms) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_submit_timeout_ms = ms == 0 ? 3000 : ms;
}

uint32_t SubmitTimeoutMs() {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_submit_timeout_ms;
}

void BlockWorker(bool block) {
    {
        std::lock_guard<std::mutex> lock(g_mu);
        g_block_worker = block;
    }
    g_cv.notify_all();
    if (g_last_queue != nullptr) {
        g_last_queue->cv.notify_all();
    }
}

int QueueDepth() {
    HostQueue* q = g_last_queue;
    if (q == nullptr) return 0;
    std::lock_guard<std::mutex> lock(q->mu);
    return static_cast<int>(q->items.size());
}

int LiveRequestCount() { return g_live_requests.load(); }
void OnRequestAllocated() { g_live_requests.fetch_add(1); }
void OnRequestDeleted() { g_live_requests.fetch_sub(1); }

bool WorkerShouldStop() { return g_stop_worker.load(); }

void RequestWorkerStop() {
    g_stop_worker.store(true);
    {
        std::lock_guard<std::mutex> lock(g_mu);
        g_block_worker = false;
    }
    g_cv.notify_all();
    if (g_last_queue != nullptr) {
        g_last_queue->cv.notify_all();
    }
}

void ClearWorkerStop() { g_stop_worker.store(false); }

void JoinWorker(void* task) {
    if (task == nullptr) return;
    auto* thread = static_cast<std::thread*>(task);
    if (thread->joinable()) thread->join();
    delete thread;
}

void SetNvsOpenError(const char* ns, bool error) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_open_error[ns] = error;
}

void SetNvsGetError(const char* ns, const char* key, bool error) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_get_error[ns][key] = error;
}

void ClearNvs() {
    std::lock_guard<std::mutex> lock(g_mu);
    g_open_error.clear();
    g_get_error.clear();
    g_ns_exists.clear();
    g_str.clear();
    g_i32.clear();
    g_u8.clear();
    g_get_i32_calls.clear();
    g_get_u8_calls.clear();
    g_get_str_calls.clear();
    g_handles.clear();
}

void HostSetString(const char* ns, const char* key, const char* value) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_ns_exists[ns] = true;
    g_str[ns][key] = value ? value : "";
}

void HostSetInt(const char* ns, const char* key, int32_t value) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_ns_exists[ns] = true;
    g_i32[ns][key] = value;
}

void HostSetBool(const char* ns, const char* key, bool value) {
    std::lock_guard<std::mutex> lock(g_mu);
    g_ns_exists[ns] = true;
    g_u8[ns][key] = value ? 1 : 0;
}

std::string HostGetString(const char* ns, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto ns_it = g_str.find(ns);
    if (ns_it == g_str.end()) return {};
    auto it = ns_it->second.find(key);
    if (it == ns_it->second.end()) return {};
    return it->second;
}

int32_t HostGetInt(const char* ns, const char* key, int32_t default_value) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto ns_it = g_i32.find(ns);
    if (ns_it == g_i32.end()) return default_value;
    auto it = ns_it->second.find(key);
    if (it == ns_it->second.end()) return default_value;
    return it->second;
}

bool HostGetBool(const char* ns, const char* key, bool default_value) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto ns_it = g_u8.find(ns);
    if (ns_it == g_u8.end()) return default_value;
    auto it = ns_it->second.find(key);
    if (it == ns_it->second.end()) return default_value;
    return it->second != 0;
}

bool HostHasKey(const char* ns, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto has = [&](const auto& store) {
        auto ns_it = store.find(ns);
        return ns_it != store.end() && ns_it->second.find(key) != ns_it->second.end();
    };
    return has(g_str) || has(g_i32) || has(g_u8);
}

int HostNvsGetI32Calls(const char* ns, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_get_i32_calls[ns][key];
}

int HostNvsGetU8Calls(const char* ns, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_get_u8_calls[ns][key];
}

int HostNvsGetStrCalls(const char* ns, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    return g_get_str_calls[ns][key];
}

}  // namespace face_config_host

namespace {

bool WaitFor(std::unique_lock<std::mutex>& lock, std::condition_variable& cv,
             TickType_t ticks, const std::function<bool()>& ready) {
    if (ticks == portMAX_DELAY) {
        cv.wait(lock, ready);
        return true;
    }
    return cv.wait_for(lock, std::chrono::milliseconds(ticks), ready);
}

}  // namespace

QueueHandle_t xQueueCreate(UBaseType_t length, UBaseType_t) {
    std::lock_guard<std::mutex> lock(g_mu);
    ++g_queue_attempts;
    if (g_fail_queue > 0) {
        --g_fail_queue;
        return nullptr;
    }
    auto* q = new HostQueue();
    q->length = length;
    ++g_queue_success;
    g_last_queue = q;
    return q;
}

BaseType_t xQueueSend(QueueHandle_t queue, const void* item, TickType_t ticks) {
    if (queue == nullptr || item == nullptr) return pdFALSE;
    void* ptr = *reinterpret_cast<void* const*>(item);
    std::unique_lock<std::mutex> lock(queue->mu);
    const auto ready = [&] {
        return face_config_host::WorkerShouldStop() ||
               queue->items.size() < queue->length;
    };
    if (!WaitFor(lock, queue->cv, ticks, ready)) return pdFALSE;
    if (queue->items.size() >= queue->length) return pdFALSE;
    queue->items.push_back(ptr);
    queue->cv.notify_all();
    return pdTRUE;
}

BaseType_t xQueueReceive(QueueHandle_t queue, void* item, TickType_t ticks) {
    if (queue == nullptr || item == nullptr) return pdFALSE;
    std::unique_lock<std::mutex> lock(queue->mu);
    const auto ready = [&] {
        if (face_config_host::WorkerShouldStop()) return true;
        bool blocked = false;
        {
            std::lock_guard<std::mutex> hook_lock(g_mu);
            blocked = g_block_worker;
        }
        return !blocked && !queue->items.empty();
    };
    if (!WaitFor(lock, queue->cv, ticks, ready)) return pdFALSE;
    if (face_config_host::WorkerShouldStop() && queue->items.empty()) {
        return pdFALSE;
    }
    if (queue->items.empty()) return pdFALSE;
    *reinterpret_cast<void**>(item) = queue->items.front();
    queue->items.pop_front();
    queue->cv.notify_all();
    return pdTRUE;
}

void vQueueDelete(QueueHandle_t queue) {
    if (queue == nullptr) return;
    if (g_last_queue == queue) g_last_queue = nullptr;
    delete queue;
}

SemaphoreHandle_t xSemaphoreCreateBinary() { return new HostSem(); }

BaseType_t xSemaphoreTake(SemaphoreHandle_t sem, TickType_t ticks) {
    if (sem == nullptr) return pdFALSE;
    std::unique_lock<std::mutex> lock(sem->mu);
    const auto ready = [&] {
        return sem->given || face_config_host::WorkerShouldStop();
    };
    if (!WaitFor(lock, sem->cv, ticks, ready)) return pdFALSE;
    if (!sem->given) return pdFALSE;
    sem->given = false;
    return pdTRUE;
}

BaseType_t xSemaphoreGive(SemaphoreHandle_t sem) {
    if (sem == nullptr) return pdFALSE;
    {
        std::lock_guard<std::mutex> lock(sem->mu);
        sem->given = true;
    }
    sem->cv.notify_all();
    return pdTRUE;
}

void vSemaphoreDelete(SemaphoreHandle_t sem) { delete sem; }

BaseType_t xTaskCreateWithCaps(TaskFunction_t fn, const char*, uint32_t, void* arg,
                               UBaseType_t, TaskHandle_t* handle, UBaseType_t) {
    {
        std::lock_guard<std::mutex> lock(g_mu);
        ++g_task_attempts;
        if (fn == nullptr) return pdFAIL;
        if (g_fail_task > 0) {
            --g_fail_task;
            if (handle) *handle = nullptr;
            return pdFAIL;
        }
        ++g_task_success;
    }
    auto* thread = new std::thread(fn, arg);
    if (handle) *handle = thread;
    return pdPASS;
}

namespace {

NvsHandle* LookupHandle(nvs_handle_t handle) {
    if (handle == 0 || handle > g_handles.size()) return nullptr;
    return &g_handles[handle - 1];
}

bool KeyGetErrorLocked(const std::string& ns, const char* key) {
    auto ns_it = g_get_error.find(ns);
    if (ns_it == g_get_error.end()) return false;
    auto it = ns_it->second.find(key);
    return it != ns_it->second.end() && it->second;
}

}  // namespace

esp_err_t nvs_open(const char* ns, nvs_open_mode_t mode, nvs_handle_t* out_handle) {
    if (ns == nullptr || out_handle == nullptr) return ESP_ERR_INVALID_ARG;
    std::lock_guard<std::mutex> lock(g_mu);
    if (g_open_error[ns]) return ESP_FAIL;
    if (mode == NVS_READONLY && !g_ns_exists[ns]) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    g_ns_exists[ns] = true;
    g_handles.push_back(NvsHandle{ns, mode == NVS_READWRITE});
    *out_handle = static_cast<nvs_handle_t>(g_handles.size());
    return ESP_OK;
}

void nvs_close(nvs_handle_t) {}

esp_err_t nvs_commit(nvs_handle_t handle) {
    std::lock_guard<std::mutex> lock(g_mu);
    return LookupHandle(handle) == nullptr ? ESP_ERR_NVS_INVALID_HANDLE : ESP_OK;
}

esp_err_t nvs_get_str(nvs_handle_t handle, const char* key, char* out, size_t* length) {
    if (key == nullptr || length == nullptr) return ESP_ERR_INVALID_ARG;
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    ++g_get_str_calls[h->ns][key];
    if (KeyGetErrorLocked(h->ns, key)) return ESP_FAIL;
    auto ns_it = g_str.find(h->ns);
    if (ns_it == g_str.end() || ns_it->second.find(key) == ns_it->second.end()) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    const std::string& value = ns_it->second[key];
    const size_t need = value.size() + 1;
    if (out == nullptr) {
        *length = need;
        return ESP_OK;
    }
    if (*length < need) return ESP_ERR_NVS_INVALID_LENGTH;
    std::memcpy(out, value.c_str(), need);
    *length = need;
    return ESP_OK;
}

esp_err_t nvs_set_str(nvs_handle_t handle, const char* key, const char* value) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    if (!h->read_write) return ESP_ERR_NVS_READ_ONLY;
    g_str[h->ns][key] = value ? value : "";
    return ESP_OK;
}

esp_err_t nvs_get_i32(nvs_handle_t handle, const char* key, int32_t* out) {
    if (key == nullptr || out == nullptr) return ESP_ERR_INVALID_ARG;
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    ++g_get_i32_calls[h->ns][key];
    if (KeyGetErrorLocked(h->ns, key)) return ESP_FAIL;
    auto ns_it = g_i32.find(h->ns);
    if (ns_it == g_i32.end() || ns_it->second.find(key) == ns_it->second.end()) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    *out = ns_it->second[key];
    return ESP_OK;
}

esp_err_t nvs_set_i32(nvs_handle_t handle, const char* key, int32_t value) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    if (!h->read_write) return ESP_ERR_NVS_READ_ONLY;
    g_i32[h->ns][key] = value;
    return ESP_OK;
}

esp_err_t nvs_get_u8(nvs_handle_t handle, const char* key, uint8_t* out) {
    if (key == nullptr || out == nullptr) return ESP_ERR_INVALID_ARG;
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    ++g_get_u8_calls[h->ns][key];
    if (KeyGetErrorLocked(h->ns, key)) return ESP_FAIL;
    auto ns_it = g_u8.find(h->ns);
    if (ns_it == g_u8.end() || ns_it->second.find(key) == ns_it->second.end()) {
        return ESP_ERR_NVS_NOT_FOUND;
    }
    *out = ns_it->second[key];
    return ESP_OK;
}

esp_err_t nvs_set_u8(nvs_handle_t handle, const char* key, uint8_t value) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    if (!h->read_write) return ESP_ERR_NVS_READ_ONLY;
    g_u8[h->ns][key] = value;
    return ESP_OK;
}

esp_err_t nvs_erase_key(nvs_handle_t handle, const char* key) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    if (!h->read_write) return ESP_ERR_NVS_READ_ONLY;
    g_str[h->ns].erase(key);
    g_i32[h->ns].erase(key);
    g_u8[h->ns].erase(key);
    return ESP_OK;
}

esp_err_t nvs_erase_all(nvs_handle_t handle) {
    std::lock_guard<std::mutex> lock(g_mu);
    auto* h = LookupHandle(handle);
    if (h == nullptr) return ESP_ERR_NVS_INVALID_HANDLE;
    if (!h->read_write) return ESP_ERR_NVS_READ_ONLY;
    g_str[h->ns].clear();
    g_i32[h->ns].clear();
    g_u8[h->ns].clear();
    return ESP_OK;
}

namespace task_diag {

void LogCurrentTask(const char*, const char*, int, int) {}
void LogTaskHandle(const char*, const char*, TaskHandle_t, int, int) {}
void LogNamedTasks(const char*, const char*) {}
void LogTaskList(const char*, const char*) {}
void LogMemoryStage(const char*, const char*) {}
void RunPsramBenchmark(const char*, const char*) {}
void StartPeriodicTaskLogger() {}

}  // namespace task_diag

