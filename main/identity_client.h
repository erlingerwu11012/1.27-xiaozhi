#pragma once

#include "camera_image_buffer.h"
#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

struct IdentityResult {
    std::string status;  // known / unknown / no_face / ambiguous / error
    std::string user_id;
    std::string display_name;
    float confidence = 0.0f;
    int http_status = 0;
    uint32_t request_generation = 0;
    std::string server_reason;
    std::string error_reason;

    bool IsKnownPerson() const {
        return status == "known" && !user_id.empty() &&
               user_id.compare(0, 4, "usr_") == 0;
    }
};

// Vision identity client. Uses short-lived token + identity_url from MCP
// initialize capabilities.vision via VisionCredentialStore. Never embeds
// long-lived face API secrets.
class IdentityClient {
public:
    static IdentityClient& GetInstance();

    // Legacy mirror used by MCP initialize for HTTPS validation/logging.
    // HTTP uploads read VisionCredentialStore snapshots, not these fields.
    void SetVisionConfig(const std::string& explain_url,
                         const std::string& identity_url,
                         const std::string& token);

    bool HasIdentityEndpoint() const;
    std::string IdentityUrl() const;

    IdentityResult IdentifyJpeg(const CameraJpegBuffer& jpeg,
                                uint32_t request_generation);

private:
    IdentityClient() = default;

    mutable std::mutex mutex_;
    std::string explain_url_;
    std::string identity_url_;
    std::string token_;
};
