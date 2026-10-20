#pragma once

#include "camera_image_buffer.h"
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

class Http;

// HTTPS client for the frozen face-enrollment device contract.
// Never logs tokens, JPEG bytes, full URL query, or server raw bodies.
class FaceEnrollmentClient {
public:
    struct CapabilityConfig {
        std::string session_url;
        int protocol_version = 1;
        // V2 is opt-in: version=2 alone is never enough to start guided
        // capture.  Existing servers stay on the frozen V1 path.
        bool guided_burst_v1 = false;
        int session_timeout_seconds = 120;
        int required_frames = 3;
        int max_frames = 5;
        int max_frame_bytes = 307200;
        // Derived from supported_* string lists. Missing/non-array => false.
        // Never default-enable from stale NVS.
        bool supports_front_only_v1 = false;
        bool supports_user_relative_v1 = false;
    };

    struct SessionInfo {
        std::string session_id;
        std::string upload_url;
        std::string assess_url;
        std::string capture_url;
        std::string cancel_url;
        std::string upload_token;
        int64_t expires_at = 0;
        int required_frames = 3;
        int max_frames = 5;
        bool guided_burst_v1 = false;
        // Frozen at create success; capability refresh must not mutate these.
        std::string capture_mode;
        std::string guidance_profile;

        bool IsFrontOnlyV1() const {
            return capture_mode == "front_only_v1";
        }
        bool IsUserRelativeV1() const {
            return guidance_profile == "user_relative_v1";
        }
    };

    struct UploadResult {
        bool ok = false;
        bool http_ok = false;
        std::string session_id;
        int accepted_count = 0;
        int required_frames = 0;
        int max_frames = 0;
        std::string status;
        bool draft_ready = false;
        std::string error_code;
        bool retryable = false;
        std::string message;
        int http_status = 0;
    };

    // V2 guided endpoints contain no user-visible text.  The firmware maps a
    // validated guidance_code to local subtitles and local Ogg/Opus assets.
    struct GuidedResult {
        bool ok = false;
        bool http_ok = false;
        std::string session_id;
        std::string guidance_code;
        int accepted_count = 0;
        bool draft_ready = false;
        std::string error_code;
        bool retryable = false;
        int http_status = 0;
    };

    static FaceEnrollmentClient& GetInstance();

    void SetCapability(const CapabilityConfig& config);
    void ClearCapability(const char* reason = "capability_missing");
    bool HasValidCapability() const;
    CapabilityConfig GetCapability() const;
    bool IsGuidedBurstV1() const;

    static bool ValidateCapability(const CapabilityConfig& config,
                                   std::string* reason);
    static bool ValidateCapability(const CapabilityConfig& config,
                                   const std::string& main_ws_url,
                                   std::string* reason);
    static bool IsForbiddenHost(const std::string& host);
    static std::string ExtractHost(const std::string& url);
    static std::string NormalizeHost(const std::string& host);

    // Pairing token comes from Settings("websocket").token — never persisted here.
    bool CreateSession(SessionInfo* out, std::string* error_code);
    // previous_accepted enforces monotonic accepted_count. Oversized local JPEG
    // maps to payload_too_large (not face_quality_low).
    bool UploadFrame(const SessionInfo& session,
                     const CameraJpegBuffer& jpeg, int previous_accepted,
                     UploadResult* out);
    // V2 only.  Both calls retain the V1 TLS, host, and token invariants.
    bool AssessFrame(const SessionInfo& session, const CameraJpegBuffer& jpeg,
                     GuidedResult* out);
    bool CapturePose(const SessionInfo& session, const char* pose, int round,
                     const CameraJpegCandidates& candidates,
                     GuidedResult* out);
    bool CancelSession(const SessionInfo& session, std::string* error_code);

    // Host-testable validators (no network).
    static bool ValidateCreateSessionResponse(
        const CapabilityConfig& cfg, bool ok_field, const std::string& session_id,
        const std::string& upload_url, const std::string& cancel_url,
        const std::string& upload_token, int64_t expires_at, int required_frames,
        int max_frames, int64_t now_unix, std::string* reason);
    // requested_* come from the create request body actually sent.
    // Echo strings must be exact; empty means the field was absent.
    static bool ValidateCreateSessionModes(
        bool requested_front_only, bool requested_user_relative,
        bool guided, const std::string& capture_mode,
        const std::string& guidance_profile, int required_frames,
        int max_frames, std::string* reason);
    static bool ValidateUploadSuccessResponse(
        const SessionInfo& session, bool ok_field,
        const std::string& response_session_id, int accepted_count,
        int required_frames, int max_frames, const std::string& status,
        bool draft_ready, int previous_accepted, std::string* reason);
    static bool ValidateGuidedResponse(const SessionInfo& session,
                                       bool ok_field,
                                       const std::string& response_session_id,
                                       const std::string& guidance_code,
                                       int accepted_count, bool draft_ready,
                                       std::string* reason);
    // Shared assess/capture completion gate.  Requires the triple used by the
    // worker after ValidateGuidedResponse has already passed.
    static bool IsGuidedEnrollmentComplete(const SessionInfo& session,
                                           const std::string& guidance_code,
                                           int accepted_count,
                                           bool draft_ready);

private:
    FaceEnrollmentClient() = default;

    bool EnsureCapabilityLoaded() const;
    static std::string LoadPairingToken();
    static void ApplyAuthHeaders(Http* http, const std::string& pairing_token,
                                 const char* upload_token);
    bool PostGuidedMultipart(const SessionInfo& session,
                             const std::string& endpoint_url,
                             CameraMultipartBody multipart_body,
                             const char* content_type, GuidedResult* out);

    mutable std::mutex mutex_;
    CapabilityConfig config_;
    bool config_valid_ = false;
    bool loaded_persisted_ = false;

#ifdef FACE_CONFIG_HOST_TEST
public:
    void ResetForTest();
#endif
};
