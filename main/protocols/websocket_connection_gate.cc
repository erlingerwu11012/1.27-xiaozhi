#include "websocket_connection_gate.h"

#include <cstring>
#include <string>

#include <esp_log.h>

namespace {
constexpr const char* kTag = "WsRxGate";
}

void WebsocketConnectionGate::Begin(uint32_t generation,
                                    std::string* session_id_to_clear) {
    std::lock_guard<std::mutex> lock(mutex_);
    generation_ = generation;
    accepting_ = generation != 0;
    if (session_id_to_clear) {
        session_id_to_clear->clear();
    }
}

bool WebsocketConnectionGate::End(uint32_t generation,
                                  std::string* session_id_storage,
                                  std::string* closed_session_out) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (generation == 0 || generation != generation_) {
        return false;
    }
    accepting_ = false;
    if (session_id_storage) {
        if (closed_session_out) {
            *closed_session_out = *session_id_storage;
        }
        session_id_storage->clear();
    }
    return true;
}

uint32_t WebsocketConnectionGate::current_generation() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return generation_;
}

bool WebsocketConnectionGate::IsAccepting(uint32_t generation) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return generation != 0 && generation == generation_ && accepting_;
}

WebsocketConnectionGate::Admission WebsocketConnectionGate::TryAdmit(
    uint32_t source_generation) {
    std::unique_lock<std::mutex> lock(mutex_);
    if (source_generation == 0 || source_generation != generation_ ||
        !accepting_) {
        return Admission{};
    }
    return Admission(std::move(lock), source_generation);
}

WebsocketTextDispatchResult DispatchWebsocketTextFrame(
    WebsocketConnectionGate& gate,
    uint32_t source_generation,
    const char* text_bytes,
    size_t len,
    const WebsocketTextDispatchHandlers& handlers) {
    auto admission = gate.TryAdmit(source_generation);
    if (!admission) {
        ESP_LOGI(kTag,
                 "event=rx_discarded reason=stale_or_ended source_gen=%u",
                 static_cast<unsigned>(source_generation));
        return WebsocketTextDispatchResult::kDiscardedStale;
    }

    if (!text_bytes || len == 0) {
        return WebsocketTextDispatchResult::kParseError;
    }

    cJSON* root = nullptr;
    {
        std::string text(text_bytes, len);
        root = cJSON_Parse(text.c_str());
    }
    if (!root) {
        return WebsocketTextDispatchResult::kParseError;
    }

    WebsocketTextDispatchResult result = WebsocketTextDispatchResult::kIgnored;
    const cJSON* type = cJSON_GetObjectItem(root, "type");
    if (!cJSON_IsString(type) || !type->valuestring) {
        cJSON_Delete(root);
        return WebsocketTextDispatchResult::kIgnored;
    }

    if (strcmp(type->valuestring, "hello") == 0) {
        // Keep admission across hello so session_id_ / ready bits cannot race End.
        if (handlers.on_hello) {
            handlers.on_hello(root);
        }
        result = WebsocketTextDispatchResult::kHelloApplied;
    } else if (handlers.on_terminal_auth && handlers.on_terminal_auth(root)) {
        result = WebsocketTextDispatchResult::kTerminalAuth;
    } else if (handlers.on_other) {
        // NEVER hold the gate across MCP / TTS / SendText: those take ws_mutex_
        // and can deadlock with SendAudio / CloseAudioChannel → WDT reboot.
        const uint32_t admitted_gen = admission.generation();
        admission.Release();
        handlers.on_other(root, admitted_gen);
        result = WebsocketTextDispatchResult::kForwarded;
    }

    cJSON_Delete(root);
    return result;
}
