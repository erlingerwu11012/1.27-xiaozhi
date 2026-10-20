#pragma once
#include <cstdint>
#include <mutex>

// Used by the real UVC callback and worker. No hardware call runs in a USB
// callback; stop/reconfigure must finish before another action can be issued.
class UsbCameraRecovery {
public:
    enum class Action { kNone, kStop, kStart };
    void OnDisconnected(int64_t now_ms) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_ || in_flight_ || attempts_ >= 3) return;
        ready_ = false; pending_ = true; next_ms_ = now_ms + 5000;
    }
    void OnFrame() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_ || in_flight_) return;
        ready_ = true; pending_ = false; attempts_ = 0; error_ = nullptr;
    }
    Action Poll(int64_t now_ms) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (closed_ || ready_ || in_flight_ || !pending_ || now_ms < next_ms_) return Action::kNone;
        if (need_start_) { in_flight_ = true; return Action::kStart; }
        if (attempts_ >= 3) { pending_ = false; error_ = "usb_recovery_exhausted"; return Action::kNone; }
        ++attempts_; in_flight_ = true; return Action::kStop;
    }
    void Stopped(bool ok, int64_t now_ms) {
        std::lock_guard<std::mutex> lock(mutex_);
        in_flight_ = false;
        if (!ok) { pending_ = false; error_ = "usb_stop_failed"; return; }
        need_start_ = true; next_ms_ = now_ms + 250;
    }
    void Started(bool ok, int64_t now_ms) {
        std::lock_guard<std::mutex> lock(mutex_);
        in_flight_ = false; need_start_ = false;
        error_ = ok ? "usb_waiting_for_frames" : "usb_reconfigure_failed";
        next_ms_ = now_ms + 5000;
        if (attempts_ >= 3 && !ok) { pending_ = false; error_ = "usb_recovery_exhausted"; }
    }
    void Close() { std::lock_guard<std::mutex> lock(mutex_); closed_ = true; pending_ = false; }
    const char* Error() const { std::lock_guard<std::mutex> lock(mutex_); return error_; }
private:
    mutable std::mutex mutex_;
    bool pending_ = false, ready_ = false, in_flight_ = false, need_start_ = false, closed_ = false;
    unsigned attempts_ = 0;
    int64_t next_ms_ = 0;
    const char* error_ = nullptr;
};
