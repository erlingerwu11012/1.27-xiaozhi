#include "vision_credentials.h"

#include <cstdio>
#include <ctime>

#include <esp_log.h>

namespace {
constexpr const char* kTag = "VisionCred";

std::string MaskSession(const std::string& session_id) {
    if (session_id.size() <= 8) return "****";
    return session_id.substr(0, 4) + "…" +
           session_id.substr(session_id.size() - 4);
}

std::string TokenFingerprint(const std::string& token) {
    if (token.empty()) return "-";
    uint32_t hash = 2166136261u;
    for (unsigned char c : token) {
        hash ^= c;
        hash *= 16777619u;
    }
    char buf[16];
    std::snprintf(buf, sizeof(buf), "%08x", static_cast<unsigned>(hash));
    return buf;
}

bool StartsWithHttps(const std::string& value) {
    return value.size() >= 8 && value.compare(0, 8, "https://") == 0;
}
}  // namespace

VisionCredentialStore& VisionCredentialStore::GetInstance() {
    static VisionCredentialStore instance;
    return instance;
}

uint32_t VisionCredentialStore::BeginConnection() {
    std::lock_guard<std::mutex> lock(mutex_);
    ++active_generation_;
    if (active_generation_ == 0) {
        active_generation_ = 1;
    }
    generation_accepting_ = true;
    ClearPendingLocked();
    ClearPublishedLocked();
    ESP_LOGI(kTag,
             "event=begin_connection generation=%u ready=0 accepting=1",
             static_cast<unsigned>(active_generation_));
    return active_generation_;
}

void VisionCredentialStore::EndConnection(uint32_t generation) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (generation == 0 || generation != active_generation_) {
        ESP_LOGI(kTag,
                 "event=end_connection_ignored closed_gen=%u active_gen=%u",
                 static_cast<unsigned>(generation),
                 static_cast<unsigned>(active_generation_));
        return;
    }
    ClearPendingLocked();
    ClearPublishedLocked();
    generation_accepting_ = false;
    ESP_LOGI(kTag,
             "event=end_connection generation=%u ready=0 accepting=0",
             static_cast<unsigned>(generation));
}

bool VisionCredentialStore::AcceptsGenerationLocked(uint32_t generation) const {
    return generation != 0 && generation == active_generation_ &&
           generation_accepting_;
}

void VisionCredentialStore::ApplyHelloSession(uint32_t generation,
                                              const std::string& session_id) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!AcceptsGenerationLocked(generation)) {
        ESP_LOGW(kTag,
                 "event=hello_ignored source_gen=%u active_gen=%u "
                 "accepting=%d session=%s",
                 static_cast<unsigned>(generation),
                 static_cast<unsigned>(active_generation_),
                 generation_accepting_ ? 1 : 0,
                 MaskSession(session_id).c_str());
        return;
    }
    if (session_id.empty() || session_id.size() > 256) {
        last_reject_reason_ = "bad_hello_session";
        ClearPublishedLocked();
        ESP_LOGW(kTag, "event=hello_rejected reason=bad_hello_session gen=%u",
                 static_cast<unsigned>(generation));
        return;
    }
    pending_session_id_ = session_id;
    pending_hello_seen_ = true;
    TryPublishLocked();
    ESP_LOGI(kTag,
             "event=hello_applied generation=%u session=%s explain_ready=%d "
             "identity_ready=%d",
             static_cast<unsigned>(generation),
             MaskSession(session_id).c_str(),
             published_.explain_ready ? 1 : 0,
             published_.identity_ready ? 1 : 0);
}

void VisionCredentialStore::ApplyInitializeVision(
    uint32_t generation, const std::string& explain_url,
    const std::string& identity_url, const std::string& token,
    const std::string& vision_session_id, int64_t expires_at) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!AcceptsGenerationLocked(generation)) {
        ESP_LOGW(kTag,
                 "event=initialize_ignored source_gen=%u active_gen=%u "
                 "accepting=%d token_fp=%s",
                 static_cast<unsigned>(generation),
                 static_cast<unsigned>(active_generation_),
                 generation_accepting_ ? 1 : 0,
                 TokenFingerprint(token).c_str());
        return;
    }

    pending_initialize_seen_ = true;
    pending_explain_url_.clear();
    pending_identity_url_.clear();
    pending_token_.clear();
    pending_vision_session_id_.clear();
    pending_expires_at_ = 0;
    last_reject_reason_.clear();

    if (token.empty() || explain_url.empty() || !StartsWithHttps(explain_url)) {
        last_reject_reason_ = "invalid_vision_initialize";
        ClearPublishedLocked();
        ESP_LOGW(kTag,
                 "event=initialize_rejected reason=%s gen=%u",
                 last_reject_reason_.c_str(),
                 static_cast<unsigned>(generation));
        return;
    }
    if (!identity_url.empty() && !StartsWithHttps(identity_url)) {
        last_reject_reason_ = "identity_not_https";
        ClearPublishedLocked();
        ESP_LOGW(kTag,
                 "event=initialize_rejected reason=%s gen=%u",
                 last_reject_reason_.c_str(),
                 static_cast<unsigned>(generation));
        return;
    }
    if (!vision_session_id.empty() && vision_session_id.size() > 256) {
        last_reject_reason_ = "bad_vision_session_id";
        ClearPublishedLocked();
        ESP_LOGW(kTag,
                 "event=initialize_rejected reason=%s gen=%u",
                 last_reject_reason_.c_str(),
                 static_cast<unsigned>(generation));
        return;
    }

    pending_explain_url_ = explain_url;
    pending_identity_url_ = identity_url;
    pending_token_ = token;
    pending_vision_session_id_ = vision_session_id;
    pending_expires_at_ = expires_at;
    TryPublishLocked();
    // CONFIG_LIBC_NEWLIB_NANO_FORMAT=y: %lld is unsupported. Using it here
    // shifts va_list so reject=%s can read an integer as a pointer → panic
    // right after TryPublishLocked()'s "published" log on first wake.
    ESP_LOGI(kTag,
             "event=initialize_applied generation=%u session_field=%s "
             "token_fp=%s expires_at=%d explain_ready=%d identity_ready=%d "
             "reject=%s",
             static_cast<unsigned>(generation),
             vision_session_id.empty() ? "absent" : "present",
             TokenFingerprint(token).c_str(),
             static_cast<int>(expires_at),
             published_.explain_ready ? 1 : 0,
             published_.identity_ready ? 1 : 0,
             last_reject_reason_.empty() ? "-" : last_reject_reason_.c_str());
}

uint32_t VisionCredentialStore::active_generation() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return active_generation_;
}

bool VisionCredentialStore::IsGenerationAccepting(uint32_t generation) const {
    std::lock_guard<std::mutex> lock(mutex_);
    return AcceptsGenerationLocked(generation);
}

bool VisionCredentialStore::TryAcquireExplainSnapshot(
    VisionCredentialSnapshot* out) const {
    if (!out) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    if (!published_.explain_ready ||
        IsExpiredLocked(published_.expires_at)) {
        return false;
    }
    *out = published_;
    return true;
}

bool VisionCredentialStore::TryAcquireIdentitySnapshot(
    VisionCredentialSnapshot* out) const {
    if (!out) return false;
    std::lock_guard<std::mutex> lock(mutex_);
    if (!published_.identity_ready ||
        IsExpiredLocked(published_.expires_at)) {
        return false;
    }
    *out = published_;
    return true;
}

bool VisionCredentialStore::IsExplainReady() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return published_.explain_ready && !IsExpiredLocked(published_.expires_at);
}

bool VisionCredentialStore::IsIdentityReady() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return published_.identity_ready && !IsExpiredLocked(published_.expires_at);
}

VisionCredentialSnapshot VisionCredentialStore::DebugCopy() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return published_;
}

void VisionCredentialStore::ClearPendingLocked() {
    pending_session_id_.clear();
    pending_explain_url_.clear();
    pending_identity_url_.clear();
    pending_token_.clear();
    pending_vision_session_id_.clear();
    pending_expires_at_ = 0;
    pending_initialize_seen_ = false;
    pending_hello_seen_ = false;
    last_reject_reason_.clear();
}

void VisionCredentialStore::ClearPublishedLocked() {
    published_ = VisionCredentialSnapshot{};
    published_.connection_generation = active_generation_;
}

bool VisionCredentialStore::IsExpiredLocked(int64_t expires_at) const {
    if (expires_at <= 0) return false;
    const std::time_t now = std::time(nullptr);
    if (now < 1700000000) return false;
    return static_cast<int64_t>(now) >= expires_at;
}

void VisionCredentialStore::TryPublishLocked() {
    ClearPublishedLocked();
    if (!generation_accepting_) {
        last_reject_reason_ = "connection_closed";
        return;
    }
    if (!pending_hello_seen_ || !pending_initialize_seen_) {
        return;
    }
    if (pending_session_id_.empty() || pending_token_.empty() ||
        pending_explain_url_.empty()) {
        last_reject_reason_ = "incomplete_pending";
        return;
    }
    if (!pending_vision_session_id_.empty() &&
        pending_vision_session_id_ != pending_session_id_) {
        last_reject_reason_ = "vision_session_mismatch";
        ESP_LOGW(kTag,
                 "event=publish_rejected reason=vision_session_mismatch "
                 "generation=%u hello=%s vision=%s",
                 static_cast<unsigned>(active_generation_),
                 MaskSession(pending_session_id_).c_str(),
                 MaskSession(pending_vision_session_id_).c_str());
        return;
    }
    if (IsExpiredLocked(pending_expires_at_)) {
        last_reject_reason_ = "expired";
        return;
    }

    published_.explain_url = pending_explain_url_;
    published_.identity_url = pending_identity_url_;
    published_.token = pending_token_;
    published_.session_id = pending_session_id_;
    published_.connection_generation = active_generation_;
    published_.expires_at = pending_expires_at_;
    published_.explain_ready = StartsWithHttps(published_.explain_url) &&
                               !published_.token.empty() &&
                               !published_.session_id.empty();
    published_.identity_ready = StartsWithHttps(published_.identity_url) &&
                                !published_.token.empty() &&
                                !published_.session_id.empty();
    last_reject_reason_.clear();
    ESP_LOGI(kTag,
             "event=published generation=%u session=%s token_fp=%s "
             "explain_ready=%d identity_ready=%d",
             static_cast<unsigned>(published_.connection_generation),
             MaskSession(published_.session_id).c_str(),
             TokenFingerprint(published_.token).c_str(),
             published_.explain_ready ? 1 : 0,
             published_.identity_ready ? 1 : 0);
}
