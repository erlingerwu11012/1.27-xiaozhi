#include "face_config_store.h"

#ifdef FACE_CONFIG_HOST_TEST
#include "face_config_host_hooks.h"
#endif

#include "settings.h"
#include "task_diagnostics.h"

#include <esp_heap_caps.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/idf_additions.h>
#include <freertos/queue.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <atomic>
#include <mutex>
#include <new>
#include <utility>

namespace face_config {
namespace {

constexpr const char* kTag = "FaceCfg";
constexpr UBaseType_t kQueueLength = 4;
constexpr uint32_t kStackBytes = 6144;
constexpr UBaseType_t kPriority = 4;
constexpr TickType_t kSubmitTimeout = pdMS_TO_TICKS(3000);

#ifdef FACE_CONFIG_HOST_TEST
TickType_t SubmitTimeoutTicks() {
    const uint32_t ms = face_config_host::SubmitTimeoutMs();
    return ms == 0 ? kSubmitTimeout : pdMS_TO_TICKS(ms);
}
#define FACE_CFG_SUBMIT_TIMEOUT SubmitTimeoutTicks()
#else
#define FACE_CFG_SUBMIT_TIMEOUT kSubmitTimeout
#endif

// NVS namespace/key names must stay <= 15 chars (NVS_KEY_NAME_MAX_SIZE-1).
constexpr const char* kFaceNs = "face_enrollment";
constexpr const char* kKeyProtoVer = "proto_ver";
constexpr const char* kKeyGuidedBurst = "guided_burst";
constexpr const char* kKeySessionTimeout = "session_timeout";
// NVS keys must stay <= 15 chars. Defaults missing => unsupported (false).
constexpr const char* kKeySupFrontOnly = "sup_front_only";
constexpr const char* kKeySupUserRel = "sup_user_rel";
constexpr const char* kWebsocketNs = "websocket";
constexpr const char* kKeyToken = "token";

enum class Op : uint8_t {
    LoadToken,
    LoadWebsocketUrl,
    LoadCapability,
    SaveCapability,
    ClearCapability,
};

struct Request {
    std::atomic<int> refs{1};
    Op op = Op::LoadToken;
    FaceEnrollmentClient::CapabilityConfig in;
    FaceEnrollmentClient::CapabilityConfig out;
    std::string token;
    bool ok = false;
    bool valid = false;
    IoResult result = IoResult::Transient;
    SemaphoreHandle_t done = nullptr;
};

QueueHandle_t s_queue = nullptr;
TaskHandle_t s_task = nullptr;
std::atomic<bool> s_ready{false};
std::mutex s_init_mu;

void Release(Request* req) {
    if (req == nullptr) return;
    if (req->refs.fetch_sub(1, std::memory_order_acq_rel) != 1) return;
    if (req->done != nullptr) {
        vSemaphoreDelete(req->done);
        req->done = nullptr;
    }
#ifdef FACE_CONFIG_HOST_TEST
    face_config_host::OnRequestDeleted();
#endif
    delete req;
}

void EraseCapabilityKeys(Settings& settings) {
    settings.EraseKey("session_url");
    settings.EraseKey(kKeyProtoVer);
    settings.EraseKey(kKeyGuidedBurst);
    settings.EraseKey(kKeySessionTimeout);
    settings.EraseKey("required_frames");
    settings.EraseKey("max_frames");
    settings.EraseKey("max_frame_bytes");
    settings.EraseKey(kKeySupFrontOnly);
    settings.EraseKey(kKeySupUserRel);
    // Never persist session_id / upload_token / pairing token.
}

void RunLoadString(Request* req, const char* ns, const char* key) {
    req->ok = false;
    req->valid = false;
    req->result = IoResult::Transient;
    req->token.clear();

    Settings settings(ns, false);
    if (!settings.IsValid()) {
        if (settings.IsNotFound()) {
            req->ok = true;
            req->result = IoResult::NotFound;
            return;
        }
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load");
        return;
    }
    const auto status = settings.TryGetString(key, &req->token);
    if (status == Settings::ReadStatus::Error) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load");
        req->token.clear();
        return;
    }
    if (status == Settings::ReadStatus::NotFound || req->token.empty()) {
        req->token.clear();
        req->ok = true;
        req->result = IoResult::NotFound;
        return;
    }
    req->ok = true;
    req->result = IoResult::Ok;
}

void RunLoadToken(Request* req) {
    RunLoadString(req, kWebsocketNs, kKeyToken);
}

void RunLoadWebsocketUrl(Request* req) {
    RunLoadString(req, kWebsocketNs, "url");
}

void RunLoadCapability(Request* req) {
    req->ok = false;
    req->valid = false;
    req->result = IoResult::Transient;
    req->out = FaceEnrollmentClient::CapabilityConfig{};

    Settings settings(kFaceNs, false);
    if (!settings.IsValid()) {
        if (settings.IsNotFound()) {
            req->ok = true;
            req->result = IoResult::NotFound;
            return;
        }
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load");
        return;
    }

    auto read_int = [&](const char* key, int32_t fallback, int* out) {
        int32_t value = 0;
        const auto status = settings.TryGetInt(key, &value);
        if (status == Settings::ReadStatus::Error) return false;
        *out = static_cast<int>(status == Settings::ReadStatus::Ok ? value
                                                                   : fallback);
        return true;
    };
    auto read_bool = [&](const char* key, bool fallback, bool* out) {
        bool value = false;
        const auto status = settings.TryGetBool(key, &value);
        if (status == Settings::ReadStatus::Error) return false;
        *out = status == Settings::ReadStatus::Ok ? value : fallback;
        return true;
    };

    FaceEnrollmentClient::CapabilityConfig cfg;
    const auto url_status = settings.TryGetString("session_url", &cfg.session_url);
    if (url_status == Settings::ReadStatus::Error) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load");
        return;
    }
    if (url_status == Settings::ReadStatus::NotFound || cfg.session_url.empty()) {
        req->ok = true;
        req->result = IoResult::NotFound;
        return;
    }

    if (!read_int(kKeyProtoVer, 1, &cfg.protocol_version) ||
        !read_bool(kKeyGuidedBurst, false, &cfg.guided_burst_v1) ||
        !read_int(kKeySessionTimeout, 120, &cfg.session_timeout_seconds) ||
        !read_int("required_frames", 3, &cfg.required_frames) ||
        !read_int("max_frames", 5, &cfg.max_frames) ||
        !read_int("max_frame_bytes", 307200, &cfg.max_frame_bytes) ||
        !read_bool(kKeySupFrontOnly, false, &cfg.supports_front_only_v1) ||
        !read_bool(kKeySupUserRel, false, &cfg.supports_user_relative_v1)) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load");
        return;
    }

    std::string main_url;
    {
        Settings ws(kWebsocketNs, false);
        if (!ws.IsValid()) {
            if (!ws.IsNotFound()) {
                ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load_ws");
                return;
            }
        } else {
            const auto ws_status = ws.TryGetString("url", &main_url);
            if (ws_status == Settings::ReadStatus::Error) {
                ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=load_ws");
                return;
            }
        }
    }

    std::string reason;
    if (!FaceEnrollmentClient::ValidateCapability(cfg, main_url, &reason)) {
        Settings writable(kFaceNs, true);
        if (!writable.IsValid()) {
            ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=erase");
        } else {
            EraseCapabilityKeys(writable);
        }
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=config_updated status=cleared "
                 "reason=persisted_%s",
                 reason.c_str());
        req->ok = true;
        req->result = IoResult::Invalid;
        req->valid = false;
        return;
    }
    req->out = std::move(cfg);
    req->ok = true;
    req->valid = true;
    req->result = IoResult::Ok;
}

void RunSaveCapability(Request* req) {
    req->result = IoResult::Transient;
    Settings settings(kFaceNs, true);
    if (!settings.IsValid()) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=persist");
        req->ok = false;
        return;
    }
    settings.SetString("session_url", req->in.session_url);
    settings.SetInt(kKeyProtoVer, req->in.protocol_version);
    settings.SetBool(kKeyGuidedBurst, req->in.guided_burst_v1);
    settings.SetInt(kKeySessionTimeout, req->in.session_timeout_seconds);
    settings.SetInt("required_frames", req->in.required_frames);
    settings.SetInt("max_frames", req->in.max_frames);
    settings.SetInt("max_frame_bytes", req->in.max_frame_bytes);
    settings.SetBool(kKeySupFrontOnly, req->in.supports_front_only_v1);
    settings.SetBool(kKeySupUserRel, req->in.supports_user_relative_v1);
    req->ok = true;
    req->result = IoResult::Ok;
}

void RunClearCapability(Request* req) {
    req->result = IoResult::Transient;
    Settings settings(kFaceNs, true);
    if (!settings.IsValid()) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=erase");
        req->ok = false;
        return;
    }
    EraseCapabilityKeys(settings);
    req->ok = true;
    req->result = IoResult::Ok;
}

void Worker(void*) {
    for (;;) {
#ifdef FACE_CONFIG_HOST_TEST
        if (face_config_host::WorkerShouldStop()) {
            break;
        }
#endif
        Request* req = nullptr;
        if (xQueueReceive(s_queue, &req, portMAX_DELAY) != pdTRUE || req == nullptr) {
            continue;
        }
#ifdef FACE_CONFIG_HOST_TEST
        if (face_config_host::WorkerShouldStop()) {
            Release(req);
            break;
        }
#endif
        task_diag::LogMemoryStage(kTag, "nvs_begin");
        switch (req->op) {
            case Op::LoadToken:
                RunLoadToken(req);
                break;
            case Op::LoadWebsocketUrl:
                RunLoadWebsocketUrl(req);
                break;
            case Op::LoadCapability:
                RunLoadCapability(req);
                break;
            case Op::SaveCapability:
                RunSaveCapability(req);
                break;
            case Op::ClearCapability:
                RunClearCapability(req);
                break;
        }
        task_diag::LogMemoryStage(kTag, "nvs_end");
        if (req->done != nullptr) {
            xSemaphoreGive(req->done);
        }
        Release(req);
    }
}

bool Submit(Op op, Request* req) {
    if (req == nullptr) return false;
    if (!EnsureReady() || s_queue == nullptr) {
        Release(req);
        return false;
    }
    req->op = op;
    req->refs.store(2, std::memory_order_relaxed);
    if (xQueueSend(s_queue, &req, FACE_CFG_SUBMIT_TIMEOUT) != pdTRUE) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=queue_full");
        req->refs.store(1, std::memory_order_relaxed);
        Release(req);
        return false;
    }
    if (xSemaphoreTake(req->done, FACE_CFG_SUBMIT_TIMEOUT) != pdTRUE) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=timeout");
        // Drop the caller reference only. The worker still owns the heap
        // Request and must not write any caller stack slot.
        Release(req);
        return false;
    }
    return true;
}

Request* NewRequest() {
#ifdef FACE_CONFIG_HOST_TEST
    if (face_config_host::ShouldFailAlloc()) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=alloc_failed");
        return nullptr;
    }
#endif
    auto* req = new (std::nothrow) Request();
    if (req == nullptr) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=alloc_failed");
        return nullptr;
    }
#ifdef FACE_CONFIG_HOST_TEST
    face_config_host::OnRequestAllocated();
#endif
    req->done = xSemaphoreCreateBinary();
    if (req->done == nullptr) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=alloc_failed");
#ifdef FACE_CONFIG_HOST_TEST
        face_config_host::OnRequestDeleted();
#endif
        delete req;
        return nullptr;
    }
    return req;
}

}  // namespace

bool Start() {
    if (s_ready.load(std::memory_order_acquire)) return true;

    std::lock_guard<std::mutex> lock(s_init_mu);
    if (s_ready.load(std::memory_order_acquire)) return true;

    if (s_queue == nullptr) {
        QueueHandle_t queue = xQueueCreate(kQueueLength, sizeof(Request*));
        if (queue == nullptr) {
            ESP_LOGE(kTag, "[FACE_ENROLL] event=config_store status=failed "
                           "code=resource_exhausted reason=queue");
            return false;
        }
        s_queue = queue;
    }
    if (s_task == nullptr) {
        TaskHandle_t task = nullptr;
        const BaseType_t created = xTaskCreateWithCaps(
            Worker, "face_cfg", kStackBytes, nullptr, kPriority, &task,
            MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
        if (created != pdPASS || task == nullptr) {
            s_task = nullptr;
            ESP_LOGE(kTag, "[FACE_ENROLL] event=config_store status=failed "
                           "code=resource_exhausted reason=task");
            return false;
        }
        s_task = task;
    }
    if (s_queue == nullptr || s_task == nullptr) return false;
    s_ready.store(true, std::memory_order_release);
    ESP_LOGI(kTag,
             "[FACE_TASK] event=create task=face_cfg stack_bytes=%u "
             "caps=internal|8bit result=ok",
             static_cast<unsigned>(kStackBytes));
    return true;
}

bool EnsureReady() {
    return s_ready.load(std::memory_order_acquire) || Start();
}

IoResult LoadPairingToken(std::string* out) {
    if (out == nullptr) return IoResult::Transient;
    out->clear();
    Request* req = NewRequest();
    if (req == nullptr) return IoResult::Transient;
    if (!Submit(Op::LoadToken, req)) return IoResult::Transient;
    *out = std::move(req->token);
    const IoResult result = req->result;
    Release(req);
    return result;
}

IoResult LoadWebsocketUrl(std::string* out) {
    if (out == nullptr) return IoResult::Transient;
    out->clear();
    Request* req = NewRequest();
    if (req == nullptr) return IoResult::Transient;
    if (!Submit(Op::LoadWebsocketUrl, req)) return IoResult::Transient;
    *out = std::move(req->token);
    const IoResult result = req->result;
    Release(req);
    return result;
}

IoResult LoadCapability(CapabilitySnapshot* out) {
    if (out == nullptr) return IoResult::Transient;
    *out = CapabilitySnapshot{};
    Request* req = NewRequest();
    if (req == nullptr) return IoResult::Transient;
    if (!Submit(Op::LoadCapability, req)) return IoResult::Transient;
    out->config = std::move(req->out);
    out->valid = req->valid;
    out->result = req->result;
    const IoResult result = req->result;
    Release(req);
    return result;
}

bool SaveCapability(const FaceEnrollmentClient::CapabilityConfig& config) {
    Request* req = NewRequest();
    if (req == nullptr) return false;
    req->in = config;
    if (!Submit(Op::SaveCapability, req)) return false;
    const bool ok = req->ok;
    Release(req);
    return ok;
}

bool ClearCapability() {
    Request* req = NewRequest();
    if (req == nullptr) return false;
    if (!Submit(Op::ClearCapability, req)) return false;
    const bool ok = req->ok;
    Release(req);
    return ok;
}

#ifdef FACE_CONFIG_HOST_TEST
void ResetStoreForTest() {
    {
        std::lock_guard<std::mutex> lock(s_init_mu);
        s_ready.store(false, std::memory_order_release);
        face_config_host::RequestWorkerStop();
        if (s_queue != nullptr) {
            Request* wake = nullptr;
            xQueueSend(s_queue, &wake, 0);
        }
    }
    face_config_host::JoinWorker(s_task);
    std::lock_guard<std::mutex> lock(s_init_mu);
    if (s_queue != nullptr) {
        Request* leftover = nullptr;
        while (xQueueReceive(s_queue, &leftover, 0) == pdTRUE) {
            if (leftover != nullptr) {
                leftover->refs.store(1, std::memory_order_relaxed);
                Release(leftover);
            }
        }
        vQueueDelete(s_queue);
        s_queue = nullptr;
    }
    s_task = nullptr;
    face_config_host::ClearWorkerStop();
}

bool IsStoreReadyForTest() {
    return s_ready.load(std::memory_order_acquire) && s_queue != nullptr &&
           s_task != nullptr;
}
#endif

}  // namespace face_config
