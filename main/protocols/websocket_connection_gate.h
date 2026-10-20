#pragma once

#include <cJSON.h>

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>
#include <utility>

// Serializes WebSocket connection generation switches with RX admission so a
// stale socket callback cannot race a newer OpenAudioChannel and mutate
// session / hello-ready state. MQTT is intentionally out of scope.
class WebsocketConnectionGate {
public:
    class Admission {
    public:
        Admission() = default;
        Admission(Admission&& other) noexcept
            : lock_(std::move(other.lock_)),
              generation_(other.generation_),
              ok_(other.ok_) {
            other.ok_ = false;
            other.generation_ = 0;
        }
        Admission& operator=(Admission&& other) noexcept {
            if (this != &other) {
                lock_ = std::move(other.lock_);
                generation_ = other.generation_;
                ok_ = other.ok_;
                other.ok_ = false;
                other.generation_ = 0;
            }
            return *this;
        }
        Admission(const Admission&) = delete;
        Admission& operator=(const Admission&) = delete;

        explicit operator bool() const { return ok_; }
        uint32_t generation() const { return generation_; }

        // Drop the gate lock early. Required before any callback that may take
        // ws_mutex_ (SendText/SendAudio) or wait on Begin/End.
        void Release() {
            if (lock_.owns_lock()) {
                lock_.unlock();
            }
            ok_ = false;
            generation_ = 0;
        }

    private:
        friend class WebsocketConnectionGate;
        Admission(std::unique_lock<std::mutex> lock, uint32_t generation)
            : lock_(std::move(lock)), generation_(generation), ok_(true) {}

        std::unique_lock<std::mutex> lock_;
        uint32_t generation_ = 0;
        bool ok_ = false;
    };

    // Install a new generation and mark it accepting. Optionally clear the
    // protocol session id under the same lock.
    void Begin(uint32_t generation, std::string* session_id_to_clear = nullptr);

    // Seal this generation. Returns true when it still owned the slot.
    // When owned and session_id_storage is set, copies it to closed_session_out
    // (if provided) then clears the storage under the same lock.
    bool End(uint32_t generation,
             std::string* session_id_storage = nullptr,
             std::string* closed_session_out = nullptr);

    uint32_t current_generation() const;
    bool IsAccepting(uint32_t generation) const;

    // Blocks concurrent Begin/End only while the returned Admission is held.
    // Callers must Release() before MCP / audio / SendText callbacks.
    Admission TryAdmit(uint32_t source_generation);

private:
    mutable std::mutex mutex_;
    uint32_t generation_ = 0;
    bool accepting_ = false;
};

enum class WebsocketTextDispatchResult {
    kDiscardedStale,
    kParseError,
    kHelloApplied,
    kTerminalAuth,
    kForwarded,
    kIgnored,
};

struct WebsocketTextDispatchHandlers {
    std::function<void(const cJSON* root)> on_hello;
    std::function<bool(const cJSON* root)> on_terminal_auth;
    std::function<void(const cJSON* root, uint32_t source_generation)> on_other;
};

// Production WebSocket text-frame dispatch: admit first, then parse/fan-out.
WebsocketTextDispatchResult DispatchWebsocketTextFrame(
    WebsocketConnectionGate& gate,
    uint32_t source_generation,
    const char* text,
    size_t len,
    const WebsocketTextDispatchHandlers& handlers);
