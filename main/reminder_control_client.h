#pragma once

#include "device_state.h"

#include <atomic>
#include <cstdint>
#include <memory>
#include <mutex>
#include <string>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>

struct cJSON;
class WebSocket;

// Independent short-lived WSS control channel for reminder AI voice when the
// primary conversation WebSocket is offline. Never owns or replaces the main
// WebsocketProtocol session and never opens mic/listening/audio uplink.
class ReminderControlClient {
public:
    static ReminderControlClient& GetInstance();

    void SetConfig(const std::string& url, int protocol_version,
                   int connect_timeout_ms, int asset_wait_timeout_ms);
    // Drop in-memory + NVS control config (e.g. MCP capability missing).
    void ClearConfig(const char* reason = "capability_missing");
    bool HasValidConfig() const;

    // payload must be a full reminder_voice_request JSON object.
    void EnqueueFromVoiceRequest(const std::string& payload_json);

    void Cancel(const char* reason);
    void OnMainChannelBecameAvailable();
    void OnDeviceStateChanged(DeviceState state);

    bool IsBusy() const;
    std::string UrlHostForLog() const;

private:
    enum class State : uint8_t {
        kIdle = 0,
        kConnecting,
        kSendingRequest,
        kWaitingAsset,
        kCompleted,
        kFailed,
        kCancelled,
        kClosed,
    };

    // Atomic cancel codes avoid unsynchronized std::string races between
    // Cancel(), WS callbacks, and the worker.
    enum class CancelCode : uint8_t {
        kNone = 0,
        kCancelled,
        kPreempted,
        kDisconnected,
        kVoiceError,
        kMainWsAvailable,
        kDeviceBusy,
        kAbsence,
        kUserAction,
        kConfigCleared,
        kGate,
    };

    struct Request {
        std::string payload_json;
        std::string instance_id;
        uint32_t revision = 0;
        uint32_t voice_revision = 0;
        uint32_t presence_generation = 0;
        std::string recipient_person_id;
        int priority_rank = 100;
    };

    ReminderControlClient() = default;

    static bool ParseRequest(const std::string& payload_json, Request* out);
    static bool ValidateConfig(const std::string& url, int protocol_version,
                               int connect_timeout_ms, int asset_wait_timeout_ms,
                               std::string* reason);
    static bool IsForbiddenHost(const std::string& host);
    static std::string ExtractHost(const std::string& url);
    static std::string NormalizeHost(const std::string& host);
    static int PriorityRankForInstance(const std::string& instance_id);
    static CancelCode CancelCodeFromReason(const char* reason);
    static const char* CancelCodeName(CancelCode code);

    bool PassesDeliveryGate(const Request& request, const char** reason) const;
    void PersistConfigLocked();
    void ErasePersistedConfigLocked();
    void LoadPersistedConfig();
    void RequestCancel(CancelCode code);
    CancelCode TakeCancelCode();
    void StartWorkerLocked();
    void WorkerLoop();
    static void WorkerEntry(void* arg);
    void HandleIncomingText(const std::string& text);
    void HandleAssetMessage(const cJSON* root);
    void HandleErrorMessage(const cJSON* root);
    void Finish(State terminal, const char* event, const char* reason);
    void CloseSocket();

    mutable std::mutex mutex_;
    std::string url_;
    int protocol_version_ = 1;
    int connect_timeout_ms_ = 3000;
    int asset_wait_timeout_ms_ = 8000;
    bool config_valid_ = false;
    bool loaded_persisted_ = false;

    Request active_;
    Request pending_;
    bool has_pending_ = false;
    State state_ = State::kIdle;
    std::atomic<bool> cancel_requested_{false};
    std::atomic<bool> asset_done_{false};
    std::atomic<CancelCode> cancel_code_{CancelCode::kNone};
    TaskHandle_t worker_ = nullptr;

    // Owned exclusively by the worker task while running.
    std::unique_ptr<WebSocket> socket_;
};
