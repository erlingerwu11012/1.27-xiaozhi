#include "face_enrollment_client.h"

#include "face_config_store.h"
#include "task_diagnostics.h"

#include <esp_log.h>

#include <cctype>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <ctime>

#ifndef FACE_CONFIG_HOST_TEST
#include "board.h"
#include "http.h"
#include "system_info.h"

#include <cJSON.h>
#include <esp_timer.h>
#endif
#include "face_enrollment_prompt_catalog.h"

namespace {
constexpr const char* kTag = "FaceEnroll";
constexpr int kProtocolVersionV1 = 1;
constexpr int kProtocolVersionGuidedBurstV1 = 2;
constexpr int kGuidedMinimumSessionSeconds = 240;

bool StartsWith(const std::string& value, const char* prefix) {
    const size_t n = std::strlen(prefix);
    return value.size() >= n && value.compare(0, n, prefix) == 0;
}

bool ParseIpv4(const std::string& host, int out[4]) {
    int parts[4] = {};
    size_t pos = 0;
    for (int i = 0; i < 4; ++i) {
        if (pos >= host.size() ||
            !std::isdigit(static_cast<unsigned char>(host[pos]))) {
            return false;
        }
        int value = 0;
        size_t digits = 0;
        while (pos < host.size() &&
               std::isdigit(static_cast<unsigned char>(host[pos]))) {
            value = value * 10 + (host[pos] - '0');
            if (value > 255) return false;
            ++pos;
            ++digits;
        }
        if (digits == 0) return false;
        parts[i] = value;
        if (i < 3) {
            if (pos >= host.size() || host[pos] != '.') return false;
            ++pos;
        }
    }
    if (pos != host.size()) return false;
    for (int i = 0; i < 4; ++i) out[i] = parts[i];
    return true;
}

std::string MaskSessionId(const std::string& session_id) {
    if (session_id.size() <= 8) return "****";
    return session_id.substr(0, 4) + "…" +
           session_id.substr(session_id.size() - 4);
}

struct StageGuard {
    const char* owner;
    const char* end_phase;
    bool active = true;
    ~StageGuard() {
        if (active) task_diag::LogMemoryStage(owner, end_phase);
    }
};

bool IsSupportedProtocolVersion(int version) {
    return version == kProtocolVersionV1 ||
           version == kProtocolVersionGuidedBurstV1;
}

bool IsGuidedBurstConfig(const FaceEnrollmentClient::CapabilityConfig& cfg) {
    return cfg.protocol_version == kProtocolVersionGuidedBurstV1 &&
           cfg.guided_burst_v1;
}

constexpr const char* kCaptureModeFrontOnlyV1 = "front_only_v1";
constexpr const char* kGuidanceProfileUserRelativeV1 = "user_relative_v1";

bool IsSidePoseGuidanceCode(const std::string& guidance_code) {
    return guidance_code == "CAPTURE_LEFT" ||
           guidance_code == "CAPTURE_RIGHT" ||
           guidance_code == "RECAPTURE_LEFT" ||
           guidance_code == "RECAPTURE_RIGHT";
}

bool IsUserRelativeGuidanceCode(const std::string& guidance_code) {
    return guidance_code == "MOVE_USER_LEFT" ||
           guidance_code == "MOVE_USER_RIGHT";
}

bool IsGuidedTerminalGuidanceCode(const std::string& guidance_code) {
    return guidance_code == "POSE_FAILED" || guidance_code == "TIMEOUT" ||
           guidance_code == "CANCELLED" || guidance_code == "SERVICE_ERROR";
}

std::string BuildCreateSessionBody(
    const FaceEnrollmentClient::CapabilityConfig& cfg, bool* requested_front_only,
    bool* requested_user_relative) {
    const bool front_only =
        IsGuidedBurstConfig(cfg) && cfg.supports_front_only_v1;
    const bool user_relative =
        front_only && cfg.supports_user_relative_v1;
    if (requested_front_only) *requested_front_only = front_only;
    if (requested_user_relative) *requested_user_relative = user_relative;
    if (!front_only) return "{}";
    if (user_relative) {
        return "{\"capture_mode\":\"front_only_v1\","
               "\"guidance_profile\":\"user_relative_v1\"}";
    }
    return "{\"capture_mode\":\"front_only_v1\"}";
}

bool ValidateSamePublicHttpsUrl(
    const FaceEnrollmentClient::CapabilityConfig& cfg,
    const std::string& url, const char* invalid_reason,
    std::string* reason) {
    if (!StartsWith(url, "https://") || url.size() > 512) {
        if (reason) *reason = invalid_reason;
        return false;
    }
    const std::string expected =
        FaceEnrollmentClient::NormalizeHost(
            FaceEnrollmentClient::ExtractHost(cfg.session_url));
    const std::string host = FaceEnrollmentClient::NormalizeHost(
        FaceEnrollmentClient::ExtractHost(url));
    if (expected.empty() || host != expected) {
        if (reason) *reason = "host_mismatch";
        return false;
    }
    if (FaceEnrollmentClient::IsForbiddenHost(host)) {
        if (reason) *reason = "forbidden_host";
        return false;
    }
    return true;
}

void AppendMultipartText(CameraMultipartBody* body, const char* boundary,
                         const char* name, const std::string& value) {
    body->append("--");
    body->append(boundary);
    body->append("\r\nContent-Disposition: form-data; name=\"");
    body->append(name);
    body->append("\"\r\n\r\n");
    body->append(value);
    body->append("\r\n");
}

void AppendMultipartImage(CameraMultipartBody* body, const char* boundary,
                          const char* name,
                          const CameraJpegBuffer& jpeg) {
    body->append("--");
    body->append(boundary);
    body->append("\r\nContent-Disposition: form-data; name=\"");
    body->append(name);
    body->append("\"; filename=\"");
    body->append(name);
    body->append(".jpg\"\r\nContent-Type: image/jpeg\r\n\r\n");
    body->append(reinterpret_cast<const char*>(jpeg.data()), jpeg.size());
    body->append("\r\n");
}

bool IsJpeg(const CameraJpegBuffer& jpeg) {
    return jpeg.size() >= 3 && jpeg[0] == 0xFF && jpeg[1] == 0xD8 &&
           jpeg[2] == 0xFF;
}
}  // namespace

FaceEnrollmentClient& FaceEnrollmentClient::GetInstance() {
    static FaceEnrollmentClient instance;
    return instance;
}

bool FaceEnrollmentClient::IsForbiddenHost(const std::string& host) {
    if (host.empty()) return true;
    std::string lower = NormalizeHost(host);
    if (lower == "localhost" || lower == "127.0.0.1" || lower == "::1" ||
        lower == "0.0.0.0") {
        return true;
    }
    if (!lower.empty() && lower.front() == '[') {
        if (lower.find("::1") != std::string::npos) return true;
        if (StartsWith(lower, "[fc") || StartsWith(lower, "[fd") ||
            StartsWith(lower, "[fe80")) {
            return true;
        }
    }
    int ip[4] = {};
    if (ParseIpv4(lower, ip)) {
        if (ip[0] == 10 || ip[0] == 127 || ip[0] == 0) return true;
        if (ip[0] == 169 && ip[1] == 254) return true;
        if (ip[0] == 192 && ip[1] == 168) return true;
        if (ip[0] == 172 && ip[1] >= 16 && ip[1] <= 31) return true;
        return false;
    }
    return false;
}

std::string FaceEnrollmentClient::ExtractHost(const std::string& url) {
    size_t begin = 0;
    if (StartsWith(url, "https://")) {
        begin = 8;
    } else if (StartsWith(url, "http://")) {
        begin = 7;
    } else if (StartsWith(url, "wss://")) {
        begin = 6;
    } else if (StartsWith(url, "ws://")) {
        begin = 5;
    } else {
        return {};
    }
    size_t end = url.find_first_of("/?", begin);
    if (end == std::string::npos) end = url.size();
    if (end <= begin) return {};
    std::string host = url.substr(begin, end - begin);
    const size_t at = host.find('@');
    if (at != std::string::npos) host = host.substr(at + 1);
    if (!host.empty() && host.front() != '[') {
        const size_t colon = host.find(':');
        if (colon != std::string::npos) host = host.substr(0, colon);
    }
    return host;
}

std::string FaceEnrollmentClient::NormalizeHost(const std::string& host) {
    std::string out = host;
    for (char& c : out) {
        c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
    }
    return out;
}

bool FaceEnrollmentClient::ValidateCapability(const CapabilityConfig& config,
                                              std::string* reason) {
    std::string main_url;
    const auto url_io = face_config::LoadWebsocketUrl(&main_url);
    if (url_io == face_config::IoResult::Transient) {
        if (reason) *reason = "nvs_unavailable";
        return false;
    }
    if (url_io != face_config::IoResult::Ok || main_url.empty()) {
        if (reason) *reason = "main_ws_missing";
        return false;
    }
    return ValidateCapability(config, main_url, reason);
}

bool FaceEnrollmentClient::ValidateCapability(const CapabilityConfig& config,
                                              const std::string& main_url,
                                              std::string* reason) {
    if (config.session_url.empty()) {
        if (reason) *reason = "missing_url";
        return false;
    }
    if (StartsWith(config.session_url, "http://") ||
        StartsWith(config.session_url, "ws://") ||
        StartsWith(config.session_url, "wss://")) {
        if (reason) {
            *reason = StartsWith(config.session_url, "https://")
                          ? "bad_scheme"
                          : "not_https";
        }
        return false;
    }
    if (!StartsWith(config.session_url, "https://")) {
        if (reason) *reason = "not_https";
        return false;
    }
    if (config.session_url.size() > 512) {
        if (reason) *reason = "url_too_long";
        return false;
    }
    const std::string host = NormalizeHost(ExtractHost(config.session_url));
    if (host.empty()) {
        if (reason) *reason = "bad_host";
        return false;
    }
    if (IsForbiddenHost(host)) {
        if (reason) *reason = "forbidden_host";
        return false;
    }
    if (main_url.empty()) {
        if (reason) *reason = "main_ws_missing";
        return false;
    }
    if (!StartsWith(main_url, "wss://")) {
        if (reason) *reason = "main_ws_not_wss";
        return false;
    }
    const std::string main_host = NormalizeHost(ExtractHost(main_url));
    if (main_host.empty()) {
        if (reason) *reason = "main_ws_bad_host";
        return false;
    }
    if (main_host != host) {
        if (reason) *reason = "host_mismatch";
        return false;
    }
    if (!IsSupportedProtocolVersion(config.protocol_version)) {
        if (reason) *reason = "unsupported_version";
        return false;
    }
    if (config.protocol_version == kProtocolVersionV1 &&
        config.guided_burst_v1) {
        if (reason) *reason = "bad_guided_capability";
        return false;
    }
    if (config.protocol_version == kProtocolVersionGuidedBurstV1 &&
        !config.guided_burst_v1) {
        if (reason) *reason = "guided_capability_missing";
        return false;
    }
    if (config.session_timeout_seconds < 30 ||
        config.session_timeout_seconds > 600) {
        if (reason) *reason = "bad_timeout";
        return false;
    }
    if (IsGuidedBurstConfig(config) &&
        config.session_timeout_seconds < kGuidedMinimumSessionSeconds) {
        if (reason) *reason = "guided_timeout_too_short";
        return false;
    }
    if (config.required_frames < 1 || config.required_frames > 10) {
        if (reason) *reason = "bad_required_frames";
        return false;
    }
    // Guided V2 has exactly one retained best image for front/left/right.
    // The batch candidates are evaluation inputs, never extra enrolled faces.
    if (IsGuidedBurstConfig(config) && config.required_frames != 3) {
        if (reason) *reason = "guided_required_frames_must_be_3";
        return false;
    }
    if (config.max_frames < config.required_frames ||
        config.max_frames > 20) {
        if (reason) *reason = "bad_max_frames";
        return false;
    }
    if (IsGuidedBurstConfig(config) && config.max_frames != 3) {
        if (reason) *reason = "guided_max_frames_must_be_3";
        return false;
    }
    if (config.max_frame_bytes < 1024 ||
        config.max_frame_bytes > 512 * 1024) {
        if (reason) *reason = "bad_max_frame_bytes";
        return false;
    }
    return true;
}

bool FaceEnrollmentClient::EnsureCapabilityLoaded() const {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (loaded_persisted_) return config_valid_;
    }
    task_diag::LogMemoryStage("face_enroll", "config_read_begin");
    face_config::CapabilitySnapshot snap;
    const auto io = face_config::LoadCapability(&snap);
    task_diag::LogMemoryStage("face_enroll", "config_read_end");
    if (io == face_config::IoResult::Transient) {
        return false;
    }
    auto* self = const_cast<FaceEnrollmentClient*>(this);
    std::lock_guard<std::mutex> lock(self->mutex_);
    if (!self->loaded_persisted_) {
        self->loaded_persisted_ = true;
        if (snap.valid) {
            self->config_ = snap.config;
            self->config_valid_ = true;
        } else {
            self->config_ = CapabilityConfig{};
            self->config_valid_ = false;
        }
    }
    return self->config_valid_;
}

void FaceEnrollmentClient::SetCapability(const CapabilityConfig& config) {
    std::string reason;
    std::string main_url;
    const auto url_io = face_config::LoadWebsocketUrl(&main_url);
    if (url_io == face_config::IoResult::Transient) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=validate");
        return;
    }
    if (!ValidateCapability(config, main_url, &reason)) {
        ClearCapability(reason.c_str());
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=config_updated status=rejected "
                 "reason=%s",
                 reason.c_str());
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mutex_);
        loaded_persisted_ = true;
        config_ = config;
        config_valid_ = true;
    }
    if (!face_config::SaveCapability(config)) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=persist");
    }
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=config_updated status=accepted "
             "version=%d guided=%d front_only=%d user_rel=%d required=%d "
             "max=%d host=%s",
             config.protocol_version, config.guided_burst_v1 ? 1 : 0,
             config.supports_front_only_v1 ? 1 : 0,
             config.supports_user_relative_v1 ? 1 : 0, config.required_frames,
             config.max_frames,
             NormalizeHost(ExtractHost(config.session_url)).c_str());
}

void FaceEnrollmentClient::ClearCapability(const char* reason) {
    {
        std::lock_guard<std::mutex> lock(mutex_);
        loaded_persisted_ = true;
        config_ = CapabilityConfig{};
        config_valid_ = false;
    }
    if (!face_config::ClearCapability()) {
        ESP_LOGW(kTag, "[FACE_ENROLL] event=nvs_unavailable op=erase");
    }
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=config_updated status=cleared reason=%s",
             reason ? reason : "capability_missing");
}

bool FaceEnrollmentClient::HasValidCapability() const {
    EnsureCapabilityLoaded();
    std::lock_guard<std::mutex> lock(mutex_);
    return config_valid_;
}

FaceEnrollmentClient::CapabilityConfig
FaceEnrollmentClient::GetCapability() const {
    EnsureCapabilityLoaded();
    std::lock_guard<std::mutex> lock(mutex_);
    return config_;
}

bool FaceEnrollmentClient::IsGuidedBurstV1() const {
    EnsureCapabilityLoaded();
    std::lock_guard<std::mutex> lock(mutex_);
    return config_valid_ && IsGuidedBurstConfig(config_);
}

std::string FaceEnrollmentClient::LoadPairingToken() {
    std::string token;
    if (face_config::LoadPairingToken(&token) == face_config::IoResult::Transient ||
        token.empty()) {
        return {};
    }
    if (token.rfind("Bearer ", 0) == 0) return token;
    return "Bearer " + token;
}

#ifndef FACE_CONFIG_HOST_TEST
void FaceEnrollmentClient::ApplyAuthHeaders(Http* http,
                                            const std::string& pairing_token,
                                            const char* upload_token) {
    if (!http) return;
    if (!pairing_token.empty()) {
        http->SetHeader("Authorization", pairing_token.c_str());
    }
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    if (upload_token && upload_token[0] != '\0') {
        http->SetHeader("X-Enrollment-Token", upload_token);
    }
}
#endif  // FACE_CONFIG_HOST_TEST

bool FaceEnrollmentClient::ValidateCreateSessionResponse(
    const CapabilityConfig& cfg, bool ok_field, const std::string& session_id,
    const std::string& upload_url, const std::string& cancel_url,
    const std::string& upload_token, int64_t expires_at, int required_frames,
    int max_frames, int64_t now_unix, std::string* reason) {
    if (!ok_field) {
        if (reason) *reason = "missing_ok";
        return false;
    }
    if (session_id.empty() || session_id.size() > 128) {
        if (reason) *reason = "bad_session_id";
        return false;
    }
    if (upload_token.empty() || upload_token.size() > 512) {
        if (reason) *reason = "bad_upload_token";
        return false;
    }
    if (!StartsWith(upload_url, "https://") || upload_url.size() > 512) {
        if (reason) *reason = "bad_upload_url";
        return false;
    }
    if (!StartsWith(cancel_url, "https://") || cancel_url.size() > 512) {
        if (reason) *reason = "bad_cancel_url";
        return false;
    }
    const std::string expected = NormalizeHost(ExtractHost(cfg.session_url));
    const std::string upload_host = NormalizeHost(ExtractHost(upload_url));
    const std::string cancel_host = NormalizeHost(ExtractHost(cancel_url));
    if (expected.empty() || upload_host != expected ||
        cancel_host != expected) {
        if (reason) *reason = "host_mismatch";
        return false;
    }
    if (IsForbiddenHost(upload_host) || IsForbiddenHost(cancel_host)) {
        if (reason) *reason = "forbidden_host";
        return false;
    }
    if (expires_at <= now_unix) {
        if (reason) *reason = "expires_at_past";
        return false;
    }
    const int64_t max_expiry =
        now_unix + static_cast<int64_t>(cfg.session_timeout_seconds) + 120;
    if (expires_at > max_expiry) {
        if (reason) *reason = "expires_at_too_far";
        return false;
    }
    if (required_frames < 1 || required_frames > 10) {
        if (reason) *reason = "bad_required_frames";
        return false;
    }
    if (max_frames < required_frames || max_frames > 20) {
        if (reason) *reason = "bad_max_frames";
        return false;
    }
    return true;
}

bool FaceEnrollmentClient::ValidateCreateSessionModes(
    bool requested_front_only, bool requested_user_relative, bool guided,
    const std::string& capture_mode, const std::string& guidance_profile,
    int required_frames, int max_frames, std::string* reason) {
    if (requested_user_relative && !requested_front_only) {
        if (reason) *reason = "user_relative_requires_front_only";
        return false;
    }
    if (requested_front_only) {
        if (capture_mode != kCaptureModeFrontOnlyV1) {
            if (reason) *reason = "capture_mode_mismatch";
            return false;
        }
        if (required_frames != 1 || max_frames != 1) {
            if (reason) *reason = "front_only_frame_quota_mismatch";
            return false;
        }
    } else {
        if (!capture_mode.empty()) {
            if (reason) *reason = "unexpected_capture_mode";
            return false;
        }
        if (guided && (required_frames != 3 || max_frames != 3)) {
            if (reason) *reason = "guided_frame_quota_mismatch";
            return false;
        }
    }
    if (requested_user_relative) {
        if (guidance_profile != kGuidanceProfileUserRelativeV1) {
            if (reason) *reason = "guidance_profile_mismatch";
            return false;
        }
    } else if (!guidance_profile.empty()) {
        if (reason) *reason = "unexpected_guidance_profile";
        return false;
    }
    return true;
}

bool FaceEnrollmentClient::ValidateUploadSuccessResponse(
    const SessionInfo& session, bool ok_field,
    const std::string& response_session_id, int accepted_count,
    int required_frames, int max_frames, const std::string& status,
    bool draft_ready, int previous_accepted, std::string* reason) {
    if (!ok_field) {
        if (reason) *reason = "missing_ok";
        return false;
    }
    if (response_session_id != session.session_id) {
        if (reason) *reason = "session_id_mismatch";
        return false;
    }
    if (accepted_count < 0 || accepted_count > max_frames ||
        accepted_count > session.max_frames) {
        if (reason) *reason = "accepted_count_oob";
        return false;
    }
    if (accepted_count < previous_accepted) {
        if (reason) *reason = "accepted_count_regress";
        return false;
    }
    if (required_frames != session.required_frames ||
        max_frames != session.max_frames) {
        if (reason) *reason = "frame_quota_mismatch";
        return false;
    }
    if (status != "collecting" && status != "draft_ready") {
        if (reason) *reason = "bad_status";
        return false;
    }
    if (status == "draft_ready") {
        if (!draft_ready || accepted_count < required_frames) {
            if (reason) *reason = "draft_inconsistent";
            return false;
        }
    } else {
        // collecting
        if (draft_ready || accepted_count >= required_frames) {
            if (reason) *reason = "draft_inconsistent";
            return false;
        }
    }
    if (draft_ready &&
        (status != "draft_ready" || accepted_count < required_frames)) {
        if (reason) *reason = "draft_inconsistent";
        return false;
    }
    return true;
}

bool FaceEnrollmentClient::ValidateGuidedResponse(
    const SessionInfo& session, bool ok_field,
    const std::string& response_session_id,
    const std::string& guidance_code, int accepted_count, bool draft_ready,
    std::string* reason) {
    if (!session.guided_burst_v1) {
        if (reason) *reason = "guided_not_enabled";
        return false;
    }
    if (!ok_field) {
        if (reason) *reason = "missing_ok";
        return false;
    }
    if (response_session_id != session.session_id) {
        if (reason) *reason = "session_id_mismatch";
        return false;
    }
    // UNKNOWN_RESULT is a local fail-closed mapping.  A service must never
    // ask firmware to continue after an unknown action.
    if (guidance_code == "UNKNOWN_RESULT" ||
        FaceEnrollmentPromptCatalog::Find(guidance_code) == nullptr) {
        if (reason) *reason = "unknown_guidance_code";
        return false;
    }
    // Local-only completion asset key must never arrive on the wire.
    if (guidance_code == "DRAFT_READY_FRONT_ONLY") {
        if (reason) *reason = "unknown_guidance_code";
        return false;
    }
    if (IsUserRelativeGuidanceCode(guidance_code) &&
        !session.IsUserRelativeV1()) {
        if (reason) *reason = "user_relative_not_negotiated";
        return false;
    }
    if (session.IsFrontOnlyV1() && IsSidePoseGuidanceCode(guidance_code)) {
        if (reason) *reason = "front_only_side_pose_forbidden";
        return false;
    }
    if (accepted_count < 0 || accepted_count > session.required_frames) {
        if (reason) *reason = "accepted_count_oob";
        return false;
    }
    if (draft_ready) {
        // Exact quota match: never treat a partial count as complete.
        if (guidance_code != "DRAFT_READY" ||
            accepted_count != session.required_frames) {
            if (reason) *reason = "draft_inconsistent";
            return false;
        }
    } else if (guidance_code == "DRAFT_READY") {
        if (reason) *reason = "draft_inconsistent";
        return false;
    } else if (accepted_count >= session.required_frames &&
               !IsGuidedTerminalGuidanceCode(guidance_code)) {
        // Formal templates already filled but server still asks to continue
        // (or sends any non-terminal code).  POSE_FAILED/TIMEOUT/CANCELLED/
        // SERVICE_ERROR remain allowed.
        if (reason) *reason = "quota_full_continue_forbidden";
        return false;
    }
    return true;
}

bool FaceEnrollmentClient::IsGuidedEnrollmentComplete(
    const SessionInfo& session, const std::string& guidance_code,
    int accepted_count, bool draft_ready) {
    return draft_ready && guidance_code == "DRAFT_READY" &&
           accepted_count == session.required_frames;
}

#ifndef FACE_CONFIG_HOST_TEST
bool FaceEnrollmentClient::CreateSession(SessionInfo* out,
                                         std::string* error_code) {
    if (!out) {
        if (error_code) *error_code = "capability_invalid";
        return false;
    }
    *out = SessionInfo{};
    task_diag::LogMemoryStage("face_enroll", "create_session_begin");
    StageGuard create_guard{"face_enroll", "create_session_end"};
    if (!EnsureCapabilityLoaded()) {
        if (error_code) *error_code = "capability_invalid";
        return false;
    }
    CapabilityConfig cfg;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!config_valid_) {
            if (error_code) *error_code = "capability_invalid";
            return false;
        }
        cfg = config_;
    }
    task_diag::LogMemoryStage("face_enroll", "config_read_begin");
    const std::string auth = LoadPairingToken();
    task_diag::LogMemoryStage("face_enroll", "config_read_end");
    if (auth.empty()) {
        if (error_code) *error_code = "auth_invalid";
        return false;
    }
    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) {
        if (error_code) *error_code = "network_error";
        return false;
    }
    ApplyAuthHeaders(http.get(), auth, nullptr);
    http->SetHeader("Content-Type", "application/json");
    bool requested_front_only = false;
    bool requested_user_relative = false;
    std::string create_body =
        BuildCreateSessionBody(cfg, &requested_front_only,
                               &requested_user_relative);
    http->SetContent(std::move(create_body));
    task_diag::LogMemoryStage("face_enroll", "https_open_begin");
    if (!http->Open("POST", cfg.session_url)) {
        task_diag::LogMemoryStage("face_enroll", "https_open_end");
        if (error_code) *error_code = "network_error";
        return false;
    }
    task_diag::LogMemoryStage("face_enroll", "https_open_end");
    const int status = http->GetStatusCode();
    const std::string body = http->ReadAll();
    http->Close();
    cJSON* root = cJSON_Parse(body.c_str());
    if (status != 200) {
        std::string code = "network_error";
        if (status == 401 || status == 403) {
            code = "auth_invalid";
        } else if (root) {
            auto* err = cJSON_GetObjectItem(root, "error_code");
            if (cJSON_IsString(err) && err->valuestring) {
                code = err->valuestring;
            }
        }
        if (error_code) *error_code = code;
        if (root) cJSON_Delete(root);
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=session_create status=failed "
                 "http=%d code=%s",
                 status, code.c_str());
        return false;
    }
    if (!root) {
        if (error_code) *error_code = "capability_invalid";
        return false;
    }
    const bool guided = IsGuidedBurstConfig(cfg);
    auto* ok = cJSON_GetObjectItem(root, "ok");
    auto* session_id = cJSON_GetObjectItem(root, "session_id");
    auto* upload_url = cJSON_GetObjectItem(root, "upload_url");
    auto* assess_url = cJSON_GetObjectItem(root, "assess_url");
    auto* capture_url = cJSON_GetObjectItem(root, "capture_url");
    auto* cancel_url = cJSON_GetObjectItem(root, "cancel_url");
    auto* upload_token = cJSON_GetObjectItem(root, "upload_token");
    auto* expires_at = cJSON_GetObjectItem(root, "expires_at");
    auto* required = cJSON_GetObjectItem(root, "required_frames");
    auto* max_frames = cJSON_GetObjectItem(root, "max_frames");
    auto* capture_mode_item = cJSON_GetObjectItem(root, "capture_mode");
    auto* guidance_profile_item =
        cJSON_GetObjectItem(root, "guidance_profile");
    const bool ok_field = cJSON_IsTrue(ok);
    const bool common_fields_typed =
        cJSON_IsString(session_id) && session_id->valuestring &&
        cJSON_IsString(cancel_url) && cancel_url->valuestring &&
        cJSON_IsString(upload_token) && upload_token->valuestring &&
        cJSON_IsNumber(expires_at) &&
        std::floor(expires_at->valuedouble) == expires_at->valuedouble &&
        cJSON_IsNumber(required) &&
        std::floor(required->valuedouble) == required->valuedouble &&
        cJSON_IsNumber(max_frames) &&
        std::floor(max_frames->valuedouble) == max_frames->valuedouble;
    const bool endpoint_fields_typed = guided
        ? cJSON_IsString(assess_url) && assess_url->valuestring &&
              cJSON_IsString(capture_url) && capture_url->valuestring
        : cJSON_IsString(upload_url) && upload_url->valuestring;
    // Mode echoes: absent => empty string; present must be exact string type.
    // Never coerce non-strings.
    std::string capture_mode;
    std::string guidance_profile;
    bool mode_fields_typed = true;
    if (capture_mode_item != nullptr) {
        if (!cJSON_IsString(capture_mode_item) ||
            !capture_mode_item->valuestring) {
            mode_fields_typed = false;
        } else {
            capture_mode = capture_mode_item->valuestring;
        }
    }
    if (guidance_profile_item != nullptr) {
        if (!cJSON_IsString(guidance_profile_item) ||
            !guidance_profile_item->valuestring) {
            mode_fields_typed = false;
        } else {
            guidance_profile = guidance_profile_item->valuestring;
        }
    }
    const bool fields_typed =
        common_fields_typed && endpoint_fields_typed && mode_fields_typed;
    if (!fields_typed) {
        cJSON_Delete(root);
        if (error_code) *error_code = "capability_invalid";
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=session_create status=failed "
                 "reason=bad_response");
        return false;
    }
    std::string reason;
    const int64_t expires_at_val =
        static_cast<int64_t>(expires_at->valuedouble);
    const int64_t now_unix = static_cast<int64_t>(time(nullptr));
    const char* upload_or_capture_url = guided
        ? capture_url->valuestring : upload_url->valuestring;
    if (!ValidateCreateSessionResponse(
            cfg, ok_field, session_id->valuestring, upload_or_capture_url,
            cancel_url->valuestring, upload_token->valuestring, expires_at_val,
            required->valueint, max_frames->valueint, now_unix, &reason) ||
        (guided && !ValidateSamePublicHttpsUrl(
                       cfg, assess_url->valuestring, "bad_assess_url",
                       &reason)) ||
        (guided &&
         expires_at_val < now_unix + kGuidedMinimumSessionSeconds) ||
        !ValidateCreateSessionModes(
            requested_front_only, requested_user_relative, guided,
            capture_mode, guidance_profile, required->valueint,
            max_frames->valueint, &reason)) {
        if (guided &&
            expires_at_val < now_unix + kGuidedMinimumSessionSeconds &&
            reason.empty()) {
            reason = "expires_at_too_soon";
        }
        cJSON_Delete(root);
        if (error_code) *error_code = "capability_invalid";
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=session_create status=failed "
                 "reason=%s now_unix=%lld expires_at=%lld delta_s=%lld",
                 reason.c_str(), (long long)now_unix,
                 (long long)expires_at_val,
                 (long long)(expires_at_val - now_unix));
        return false;
    }
    out->session_id = session_id->valuestring;
    out->upload_url = guided ? "" : upload_url->valuestring;
    out->assess_url = guided ? assess_url->valuestring : "";
    out->capture_url = guided ? capture_url->valuestring : "";
    out->cancel_url = cancel_url->valuestring;
    out->upload_token = upload_token->valuestring;
    out->expires_at = expires_at_val;
    out->required_frames = required->valueint;
    out->max_frames = max_frames->valueint;
    out->guided_burst_v1 = guided;
    out->capture_mode = std::move(capture_mode);
    out->guidance_profile = std::move(guidance_profile);
    cJSON_Delete(root);
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=session_create status=ok session=%s "
             "guided=%d front_only=%d user_rel=%d required=%d max=%d "
             "now_unix=%lld expires_at=%lld delta_s=%lld",
             MaskSessionId(out->session_id).c_str(),
             out->guided_burst_v1 ? 1 : 0, out->IsFrontOnlyV1() ? 1 : 0,
             out->IsUserRelativeV1() ? 1 : 0, out->required_frames,
             out->max_frames, (long long)now_unix,
             (long long)expires_at_val,
             (long long)(expires_at_val - now_unix));
    return true;
}

bool FaceEnrollmentClient::UploadFrame(const SessionInfo& session,
                                       const CameraJpegBuffer& jpeg,
                                       int previous_accepted,
                                       UploadResult* out) {
    if (!out) return false;
    *out = UploadResult{};
    if (session.upload_url.empty() || session.upload_token.empty()) {
        out->error_code = "upload_token_invalid";
        return false;
    }
    CapabilityConfig cfg = GetCapability();
    if (jpeg.empty()) {
        out->error_code = "face_quality_low";
        out->retryable = true;
        return false;
    }
    if (static_cast<int>(jpeg.size()) > cfg.max_frame_bytes) {
        out->error_code = "payload_too_large";
        out->retryable = false;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed "
                 "code=payload_too_large");
        return false;
    }
    const std::string auth = LoadPairingToken();
    if (auth.empty()) {
        out->error_code = "auth_invalid";
        return false;
    }
    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) {
        out->error_code = "network_error";
        out->retryable = true;
        return false;
    }
    // EspHttp::Open writes SetContent() then fetch_headers. Streaming Write()
    // after Open with empty content_ sends Content-Length:0 — server then fails
    // multipart parse ("Could not find starting boundary"). Build full body first.
    constexpr const char* kContentType =
        "multipart/form-data; boundary=enrollframe";
    const std::string head =
        "--enrollframe\r\nContent-Disposition: form-data; name=\"image\"; "
        "filename=\"face.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    const std::string tail = "\r\n--enrollframe--\r\n";
    CameraMultipartBody multipart;
    multipart.reserve(head.size() + jpeg.size() + tail.size());
    multipart.append(head);
    multipart.append(reinterpret_cast<const char*>(jpeg.data()), jpeg.size());
    multipart.append(tail);

    const bool jpeg_magic =
        jpeg.size() >= 3 && jpeg[0] == 0xFF && jpeg[1] == 0xD8 &&
        jpeg[2] == 0xFF;
    char prefix_hex[129];
    const size_t prefix_n =
        multipart.size() < 64 ? multipart.size() : static_cast<size_t>(64);
    for (size_t i = 0; i < prefix_n; ++i) {
        snprintf(prefix_hex + i * 2, 3, "%02x",
                 static_cast<unsigned char>(multipart[i]));
    }
    prefix_hex[prefix_n * 2] = '\0';
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=frame_upload status=sending "
             "content_type=%s content_length=%u jpeg_magic=%d part=image "
             "body_prefix_hex=%s",
             kContentType, static_cast<unsigned>(multipart.size()),
             jpeg_magic ? 1 : 0, prefix_hex);

    ApplyAuthHeaders(http.get(), auth, session.upload_token.c_str());
    http->SetHeader("Content-Type", kContentType);
    http->SetPsramContent(std::move(multipart));
    task_diag::LogMemoryStage("face_enroll", "https_open_begin");
    task_diag::LogMemoryStage("face_enroll", "upload_begin");
    StageGuard upload_guard{"face_enroll", "upload_end"};
    if (!http->Open("POST", session.upload_url)) {
        task_diag::LogMemoryStage("face_enroll", "https_open_end");
        out->error_code = "network_error";
        out->retryable = true;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed "
                 "code=network_error reason=open");
        return false;
    }
    task_diag::LogMemoryStage("face_enroll", "https_open_end");
    out->http_status = http->GetStatusCode();
    const std::string body = http->ReadAll();
    http->Close();
    out->http_ok = (out->http_status == 200);
    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        if (out->http_ok) {
            out->error_code = "capability_invalid";
            out->retryable = false;
        } else if (out->http_status > 0) {
            // Got an HTTP response — not a transport failure.
            out->error_code = "upload_rejected";
            out->retryable = out->http_status >= 500;
        } else {
            out->error_code = "network_error";
            out->retryable = true;
        }
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed code=%s "
                 "http=%d",
                 out->error_code.c_str(), out->http_status);
        return false;
    }
    auto* ok = cJSON_GetObjectItem(root, "ok");
    out->ok = cJSON_IsTrue(ok);
    auto* session_id = cJSON_GetObjectItem(root, "session_id");
    if (cJSON_IsString(session_id) && session_id->valuestring) {
        out->session_id = session_id->valuestring;
    }
    auto* accepted = cJSON_GetObjectItem(root, "accepted_count");
    if (cJSON_IsNumber(accepted) &&
        std::floor(accepted->valuedouble) == accepted->valuedouble) {
        out->accepted_count = accepted->valueint;
    } else if (out->ok) {
        cJSON_Delete(root);
        out->ok = false;
        out->error_code = "capability_invalid";
        return false;
    }
    auto* required = cJSON_GetObjectItem(root, "required_frames");
    if (cJSON_IsNumber(required)) out->required_frames = required->valueint;
    auto* max_frames = cJSON_GetObjectItem(root, "max_frames");
    if (cJSON_IsNumber(max_frames)) out->max_frames = max_frames->valueint;
    auto* status = cJSON_GetObjectItem(root, "status");
    if (cJSON_IsString(status) && status->valuestring) {
        out->status = status->valuestring;
    }
    auto* draft = cJSON_GetObjectItem(root, "draft_ready");
    out->draft_ready = cJSON_IsTrue(draft);
    auto* error_code = cJSON_GetObjectItem(root, "error_code");
    if (cJSON_IsString(error_code) && error_code->valuestring) {
        out->error_code = error_code->valuestring;
    }
    auto* retryable = cJSON_GetObjectItem(root, "retryable");
    out->retryable = cJSON_IsTrue(retryable);
    auto* message = cJSON_GetObjectItem(root, "message");
    if (cJSON_IsString(message) && message->valuestring) {
        out->message = message->valuestring;
    }
    cJSON_Delete(root);

    if (!out->http_ok) {
        if (out->error_code.empty()) {
            out->error_code =
                out->http_status > 0 ? "upload_rejected" : "network_error";
        }
        if (!out->retryable) {
            out->retryable = out->http_status >= 500 ||
                             out->error_code == "network_error";
        }
        out->ok = false;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed code=%s "
                 "http=%d retryable=%d",
                 out->error_code.c_str(), out->http_status,
                 out->retryable ? 1 : 0);
        return false;
    }
    if (!out->ok) {
        if (out->error_code.empty()) out->error_code = "capability_invalid";
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed code=%s "
                 "retryable=%d",
                 out->error_code.c_str(), out->retryable ? 1 : 0);
        return false;
    }

    std::string reason;
    if (!ValidateUploadSuccessResponse(
            session, true, out->session_id, out->accepted_count,
            out->required_frames, out->max_frames, out->status,
            out->draft_ready, previous_accepted, &reason)) {
        out->ok = false;
        out->draft_ready = false;
        out->error_code = "capability_invalid";
        out->retryable = false;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=frame_upload status=failed "
                 "code=capability_invalid reason=%s",
                 reason.c_str());
        return false;
    }
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=frame_upload status=ok accepted=%d/%d "
             "draft=%d",
             out->accepted_count, out->required_frames,
             out->draft_ready ? 1 : 0);
    return true;
}

bool FaceEnrollmentClient::PostGuidedMultipart(
    const SessionInfo& session, const std::string& endpoint_url,
    CameraMultipartBody multipart_body, const char* content_type, GuidedResult* out) {
    if (!out) return false;
    *out = GuidedResult{};
    if (!session.guided_burst_v1 || endpoint_url.empty() ||
        session.upload_token.empty()) {
        out->error_code = "capability_invalid";
        return false;
    }
    const CapabilityConfig cfg = GetCapability();
    std::string endpoint_reason;
    if (!IsGuidedBurstConfig(cfg) ||
        !ValidateSamePublicHttpsUrl(cfg, endpoint_url, "bad_guided_url",
                                    &endpoint_reason)) {
        out->error_code = "capability_invalid";
        return false;
    }
    const std::string auth = LoadPairingToken();
    if (auth.empty()) {
        out->error_code = "auth_invalid";
        return false;
    }
    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) {
        out->error_code = "network_error";
        out->retryable = true;
        return false;
    }
    ApplyAuthHeaders(http.get(), auth, session.upload_token.c_str());
    http->SetHeader("Content-Type", content_type);
    http->SetPsramContent(std::move(multipart_body));
    task_diag::LogMemoryStage("face_enroll", "https_open_begin");
    task_diag::LogMemoryStage("face_enroll", "upload_begin");
    StageGuard upload_guard{"face_enroll", "upload_end"};
    if (!http->Open("POST", endpoint_url)) {
        task_diag::LogMemoryStage("face_enroll", "https_open_end");
        out->error_code = "network_error";
        out->retryable = true;
        return false;
    }
    task_diag::LogMemoryStage("face_enroll", "https_open_end");
    out->http_status = http->GetStatusCode();
    const std::string body = http->ReadAll();
    http->Close();
    out->http_ok = (out->http_status == 200);

    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        out->error_code = out->http_ok ? "capability_invalid"
                                       : "network_error";
        out->retryable = !out->http_ok;
        return false;
    }
    auto* error_code = cJSON_GetObjectItem(root, "error_code");
    if (cJSON_IsString(error_code) && error_code->valuestring) {
        out->error_code = error_code->valuestring;
    }
    auto* retryable = cJSON_GetObjectItem(root, "retryable");
    out->retryable = cJSON_IsTrue(retryable);
    if (!out->http_ok) {
        if (out->error_code.empty()) {
            out->error_code = out->http_status == 401 ||
                                      out->http_status == 403
                                  ? "auth_invalid"
                                  : "network_error";
        }
        out->retryable = out->retryable || out->http_status >= 500 ||
                         out->error_code == "network_error";
        cJSON_Delete(root);
        return false;
    }

    auto* ok = cJSON_GetObjectItem(root, "ok");
    auto* session_id = cJSON_GetObjectItem(root, "session_id");
    auto* guidance_code = cJSON_GetObjectItem(root, "guidance_code");
    auto* accepted_count = cJSON_GetObjectItem(root, "accepted_count");
    auto* draft_ready = cJSON_GetObjectItem(root, "draft_ready");
    const bool typed = cJSON_IsTrue(ok) && cJSON_IsString(session_id) &&
                       session_id->valuestring &&
                       cJSON_IsString(guidance_code) &&
                       guidance_code->valuestring &&
                       cJSON_IsNumber(accepted_count) &&
                       std::floor(accepted_count->valuedouble) ==
                           accepted_count->valuedouble &&
                       (cJSON_IsTrue(draft_ready) || cJSON_IsFalse(draft_ready));
    if (!typed) {
        cJSON_Delete(root);
        out->error_code = "capability_invalid";
        out->retryable = false;
        return false;
    }
    out->ok = true;
    out->session_id = session_id->valuestring;
    out->guidance_code = guidance_code->valuestring;
    out->accepted_count = accepted_count->valueint;
    out->draft_ready = cJSON_IsTrue(draft_ready);
    std::string reason;
    if (!ValidateGuidedResponse(session, true, out->session_id,
                                out->guidance_code, out->accepted_count,
                                out->draft_ready, &reason)) {
        out->ok = false;
        if (reason == "unknown_guidance_code" ||
            reason == "user_relative_not_negotiated" ||
            reason == "front_only_side_pose_forbidden" ||
            reason == "quota_full_continue_forbidden") {
            out->error_code = reason;
        } else {
            out->error_code = "capability_invalid";
        }
        out->retryable = false;
        ESP_LOGW(kTag,
                 "[FACE_ENROLL] event=guided_response status=rejected "
                 "reason=%s",
                 reason.c_str());
    }
    cJSON_Delete(root);
    return out->ok;
}

bool FaceEnrollmentClient::AssessFrame(
    const SessionInfo& session, const CameraJpegBuffer& jpeg,
    GuidedResult* out) {
    if (!out) return false;
    *out = GuidedResult{};
    const CapabilityConfig cfg = GetCapability();
    if (!session.guided_burst_v1 || session.assess_url.empty() ||
        jpeg.empty() || !IsJpeg(jpeg)) {
        out->error_code = "capability_invalid";
        return false;
    }
    if (static_cast<int>(jpeg.size()) > cfg.max_frame_bytes) {
        out->error_code = "payload_too_large";
        return false;
    }
    constexpr const char* kBoundary = "guidedassess";
    constexpr const char* kContentType =
        "multipart/form-data; boundary=guidedassess";
    CameraMultipartBody body;
    body.reserve(jpeg.size() + 192);
    AppendMultipartImage(&body, kBoundary, "image", jpeg);
    body.append("--guidedassess--\r\n");
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=guided_assess status=sending bytes=%u",
             static_cast<unsigned>(jpeg.size()));
    return PostGuidedMultipart(session, session.assess_url, std::move(body),
                               kContentType, out);
}

bool FaceEnrollmentClient::CapturePose(
    const SessionInfo& session, const char* pose, int round,
    const CameraJpegCandidates& candidates, GuidedResult* out) {
    if (!out) return false;
    *out = GuidedResult{};
    const CapabilityConfig cfg = GetCapability();
    if (!session.guided_burst_v1 || session.capture_url.empty() || !pose ||
        (std::strcmp(pose, "front") != 0 && std::strcmp(pose, "left") != 0 &&
         std::strcmp(pose, "right") != 0) ||
        round < 1 || round > 3 || candidates.size() < 2 ||
        candidates.size() > 3) {
        out->error_code = "capability_invalid";
        return false;
    }
    size_t image_bytes = 0;
    for (const auto& jpeg : candidates) {
        if (jpeg.empty() || !IsJpeg(jpeg) ||
            static_cast<int>(jpeg.size()) > cfg.max_frame_bytes) {
            out->error_code = "payload_too_large";
            return false;
        }
        image_bytes += jpeg.size();
    }
    constexpr const char* kBoundary = "guidedcapture";
    constexpr const char* kContentType =
        "multipart/form-data; boundary=guidedcapture";
    CameraMultipartBody body;
    body.reserve(image_bytes + 512);
    AppendMultipartText(&body, kBoundary, "pose", pose);
    AppendMultipartText(&body, kBoundary, "round", std::to_string(round));
    for (size_t i = 0; i < candidates.size(); ++i) {
        const std::string name = "candidate_" + std::to_string(i);
        AppendMultipartImage(&body, kBoundary, name.c_str(), candidates[i]);
    }
    body.append("--guidedcapture--\r\n");
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=guided_capture status=sending pose=%s "
             "round=%d candidates=%u bytes=%u",
             pose, round, static_cast<unsigned>(candidates.size()),
             static_cast<unsigned>(image_bytes));
    task_diag::LogMemoryStage("face_enroll", "candidate_upload_begin");
    const bool ok = PostGuidedMultipart(session, session.capture_url,
                                        std::move(body), kContentType, out);
    task_diag::LogMemoryStage("face_enroll", "candidate_upload_end");
    return ok;
}

bool FaceEnrollmentClient::CancelSession(const SessionInfo& session,
                                         std::string* error_code) {
    if (session.cancel_url.empty()) {
        if (error_code) *error_code = "session_cancelled";
        return false;
    }
    const std::string auth = LoadPairingToken();
    if (auth.empty()) {
        if (error_code) *error_code = "auth_invalid";
        return false;
    }
    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) {
        if (error_code) *error_code = "network_error";
        return false;
    }
    ApplyAuthHeaders(http.get(), auth, session.upload_token.c_str());
    task_diag::LogMemoryStage("face_enroll", "https_open_begin");
    if (!http->Open("DELETE", session.cancel_url)) {
        task_diag::LogMemoryStage("face_enroll", "https_open_end");
        if (error_code) *error_code = "network_error";
        return false;
    }
    task_diag::LogMemoryStage("face_enroll", "https_open_end");
    const int status = http->GetStatusCode();
    http->ReadAll();
    http->Close();
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=session_cancel http=%d session=%s",
             status, MaskSessionId(session.session_id).c_str());
    return status == 200 || status == 204 || status == 404;
}
#endif  // FACE_CONFIG_HOST_TEST

#ifdef FACE_CONFIG_HOST_TEST
void FaceEnrollmentClient::ResetForTest() {
    std::lock_guard<std::mutex> lock(mutex_);
    config_ = CapabilityConfig{};
    config_valid_ = false;
    loaded_persisted_ = false;
}
#endif
