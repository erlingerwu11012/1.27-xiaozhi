#include "host_runtime.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "freertos/semphr.h"
#include "esp_heap_caps.h"
#include <condition_variable>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <memory>
#include <thread>
#include <vector>
std::atomic<bool> HostFailPsram{false}, HostFailHeap{false};
std::string HostFailTask;
std::atomic<unsigned> HostNotifyDelay{0};
std::atomic<size_t> HostInternalFree{512 * 1024};
struct HostSemaphore {
    std::mutex m;
    std::condition_variable cv;
    unsigned value, max;
};
struct HostQueue {
    std::mutex m;
    std::condition_variable cv;
    unsigned capacity, size;
    std::deque<std::vector<unsigned char>> q;
};
struct HostTask {
    std::thread thread;
    std::mutex m;
    std::condition_variable cv;
    uint32_t notifications = 0;
};
struct TaskExit {};
thread_local HostTask *current = nullptr;
std::vector<std::unique_ptr<HostTask>> tasks;
template <class F>
bool Wait(std::condition_variable &cv, std::unique_lock<std::mutex> &lock, TickType_t timeout,
          F f) {
    if (timeout == portMAX_DELAY) {
        cv.wait(lock, f);
        return true;
    }
    return cv.wait_for(lock, std::chrono::milliseconds(timeout), f);
}
SemaphoreHandle_t xSemaphoreCreateCounting(unsigned max, unsigned init) {
    auto *s = new HostSemaphore;
    s->max = max;
    s->value = init;
    return s;
}
SemaphoreHandle_t xSemaphoreCreateBinary() { return xSemaphoreCreateCounting(1, 0); }
SemaphoreHandle_t xSemaphoreCreateMutex() { return xSemaphoreCreateCounting(1, 1); }
BaseType_t xSemaphoreTake(SemaphoreHandle_t s, TickType_t timeout) {
    std::unique_lock<std::mutex> lock(s->m);
    if (!Wait(s->cv, lock, timeout, [&] { return s->value > 0; }))
        return pdFALSE;
    --s->value;
    return pdTRUE;
}
BaseType_t xSemaphoreGive(SemaphoreHandle_t s) {
    std::lock_guard<std::mutex> lock(s->m);
    if (s->value >= s->max)
        return pdFALSE;
    ++s->value;
    s->cv.notify_all();
    return pdTRUE;
}
void vSemaphoreDelete(SemaphoreHandle_t s) { delete s; }
QueueHandle_t xQueueCreate(unsigned capacity, unsigned size) {
    auto *q = new HostQueue;
    q->capacity = capacity;
    q->size = size;
    return q;
}
BaseType_t xQueueReceive(QueueHandle_t q, void *item, TickType_t timeout) {
    std::unique_lock<std::mutex> lock(q->m);
    if (!Wait(q->cv, lock, timeout, [&] { return !q->q.empty(); }))
        return pdFALSE;
    memcpy(item, q->q.front().data(), q->size);
    q->q.pop_front();
    q->cv.notify_all();
    return pdTRUE;
}
BaseType_t xQueueSend(QueueHandle_t q, const void *item, TickType_t timeout) {
    std::unique_lock<std::mutex> lock(q->m);
    if (!Wait(q->cv, lock, timeout, [&] { return q->q.size() < q->capacity; }))
        return pdFALSE;
    q->q.emplace_back(q->size);
    memcpy(q->q.back().data(), item, q->size);
    q->cv.notify_all();
    return pdTRUE;
}
void vQueueDelete(QueueHandle_t q) { delete q; }
BaseType_t xTaskCreatePinnedToCore(void (*fn)(void *), const char *name, uint32_t, void *arg,
                                   unsigned, TaskHandle_t *out, int) {
    if (HostFailTask == name)
        return pdFAIL;
    auto task = std::make_unique<HostTask>();
    *out = task.get();
    tasks.push_back(std::move(task));
    (*out)->thread = std::thread([=] {
        current = *out;
        try {
            fn(arg);
        } catch (TaskExit &) {
        };
    });
    return pdPASS;
}
void vTaskDelete(TaskHandle_t task) {
    if (task)
        std::abort();
    throw TaskExit{};
}
void xTaskNotifyGive(TaskHandle_t task) {
    std::lock_guard<std::mutex> lock(task->m);
    ++task->notifications;
    task->cv.notify_all();
}
uint32_t ulTaskNotifyTake(BaseType_t clear, TickType_t timeout) {
    std::unique_lock<std::mutex> lock(current->m);
    if (!Wait(current->cv, lock, timeout, [] { return current->notifications > 0; }))
        return 0;
    auto n = current->notifications;
    if (clear)
        current->notifications = 0;
    else
        --current->notifications;
    lock.unlock();
    auto delay = HostNotifyDelay.exchange(0);
    if (delay)
        std::this_thread::sleep_for(std::chrono::milliseconds(delay));
    return n;
}
UBaseType_t uxTaskGetStackHighWaterMark(TaskHandle_t) { return 2048; }
void vTaskDelay(TickType_t ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
void taskYIELD() { std::this_thread::yield(); }
void HostJoinTasks() {
    for (auto &task : tasks)
        if (task->thread.joinable())
            task->thread.join();
    tasks.clear();
}
extern "C" void *psram_prefered_malloc(unsigned int n) {
    if (HostFailPsram.exchange(false))
        return nullptr;
    return malloc(n);
}
extern "C" void *psram_malloc(unsigned int n) { return psram_prefered_malloc(n); }
extern "C" void *psram_prefered_realloc(void *p, unsigned int n) { return realloc(p, n); }
void *heap_caps_malloc(size_t n, unsigned) {
    if (HostFailHeap.exchange(false))
        return nullptr;
    return malloc(n);
}
void heap_caps_free(void *p) { free(p); }
size_t heap_caps_get_free_size(unsigned caps) {
    return caps & MALLOC_CAP_INTERNAL ? HostInternalFree.load() : 8 * 1024 * 1024;
}
