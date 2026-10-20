#include "identity_client.h"

#include "board.h"
#include "http.h"
#include "system_info.h"
#include "vision_credentials.h"

#include <cJSON.h>
#include <esp_log.h>

namespace {
constexpr const char* kTag = "IdentityClient";
constexpr size_t kMaxErrorBodyBytes = 512;

bool StartsWithHttps(const std::string& value) {
    return value.size() >= 8 && value.compare(0, 8, "https://") == 0;
}

// Extract host between scheme and first '/' or '?' or end.
std::string ExtractHost(const std::string& url) {
    if (!StartsWithHttps(url)) return {};
    const size_t host_begin = 8;
    size_t host_end = url.find_first_of("/?", host_begin);
    if (host_end == std::string::npos) host_end = url.size();
    if (host_end <= host_begin) return {};
    return url.substr(host_begin, host_end - host_begin);
}

bool HostsMatch(const std::string& left, const std::string& right) {
    if (left.empty() || right.empty()) return false;
    return left == right;
}

CameraMultipartBody BuildIdentityMultipart(const CameraJpegBuffer& jpeg) {
    const std::string head =
        "--identity\r\nContent-Disposition: form-data; name=\"image\"; "
        "filename=\"face.jpg\"\r\nContent-Type: image/jpeg\r\n\r\n";
    const std::string tail = "\r\n--identity--\r\n";
    CameraMultipartBody body;
    body.reserve(head.size() + jpeg.size() + tail.size());
    body.append(head);
    body.append(reinterpret_cast<const char*>(jpeg.data()), jpeg.size());
    body.append(tail);
    return body;
}
}  // namespace

IdentityClient& IdentityClient::GetInstance() {
    static IdentityClient instance;
    return instance;
}

void IdentityClient::SetVisionConfig(const std::string& explain_url,
                                     const std::string& identity_url,
                                     const std::string& token) {
    std::lock_guard<std::mutex> lock(mutex_);
    explain_url_.clear();
    identity_url_.clear();
    token_.clear();

    if (!identity_url.empty() && !StartsWithHttps(identity_url)) {
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=not_https");
    } else if (!explain_url.empty() && !StartsWithHttps(explain_url)) {
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=explain_not_https");
    } else if (!identity_url.empty() && !explain_url.empty() &&
               !HostsMatch(ExtractHost(identity_url),
                           ExtractHost(explain_url))) {
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=host_mismatch");
    } else if (identity_url.empty()) {
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=missing");
    } else if (token.empty()) {
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=token_missing");
    } else {
        explain_url_ = explain_url;
        identity_url_ = identity_url;
        token_ = token;
        ESP_LOGI(kTag,
                 "[REMINDER_DELIVERY] event=vision_config identity=set "
                 "explain=%s token=set",
                 explain_url_.empty() ? "missing" : "set");
        return;
    }

    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=vision_config identity=rejected "
             "explain=%s token=%s",
             explain_url.empty() ? "missing" : "present",
             token.empty() ? "missing" : "present");
}

bool IdentityClient::HasIdentityEndpoint() const {
    return VisionCredentialStore::GetInstance().IsIdentityReady();
}

std::string IdentityClient::IdentityUrl() const {
    VisionCredentialSnapshot snap;
    if (VisionCredentialStore::GetInstance().TryAcquireIdentitySnapshot(&snap)) {
        return snap.identity_url;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    return identity_url_;
}

IdentityResult IdentityClient::IdentifyJpeg(
    const CameraJpegBuffer& jpeg, uint32_t request_generation) try {
    IdentityResult result;
    result.request_generation = request_generation;
    result.status = "error";

    VisionCredentialSnapshot snap;
    if (!VisionCredentialStore::GetInstance().TryAcquireIdentitySnapshot(
            &snap)) {
        result.error_reason = "vision_not_ready";
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_endpoint_rejected "
                 "reason=vision_not_ready gen=%u",
                 static_cast<unsigned>(request_generation));
        return result;
    }

    if (jpeg.empty()) {
        result.error_reason = "empty_jpeg";
        return result;
    }

    auto http = Board::GetInstance().GetNetwork()->CreateHttp(3);
    if (!http) {
        result.error_reason = "http_create_failed";
        return result;
    }

    const std::string auth = "Bearer " + snap.token;
    http->SetHeader("Authorization", auth.c_str());
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", Board::GetInstance().GetUuid().c_str());
    if (!snap.session_id.empty()) {
        http->SetHeader("Session-Id", snap.session_id.c_str());
    }
    http->SetHeader("Content-Type",
                    "multipart/form-data; boundary=identity");
    http->SetPsramContent(BuildIdentityMultipart(jpeg));
    if (!http->Open("POST", snap.identity_url)) {
        result.error_reason = "connect_failed";
        return result;
    }
    result.http_status = http->GetStatusCode();
    if (result.http_status != 200) {
        bool truncated = false;
        const std::string err_body =
            ReadHttpBodyBounded(http.get(), kMaxErrorBodyBytes, &truncated);
        if (!truncated) {
            http->Close();
        }
        result.error_reason = truncated ? "http_status_truncated"
                                        : "http_status";
        ESP_LOGW(kTag,
                 "[REMINDER_DELIVERY] event=identity_http_error status=%d "
                 "gen=%u snap_gen=%u body_len=%u truncated=%d",
                 result.http_status,
                 static_cast<unsigned>(request_generation),
                 static_cast<unsigned>(snap.connection_generation),
                 static_cast<unsigned>(err_body.size()),
                 truncated ? 1 : 0);
        (void)err_body;
        return result;
    }
    const std::string body = http->ReadAll();
    http->Close();

    cJSON* root = cJSON_Parse(body.c_str());
    if (!root) {
        result.error_reason = "bad_json";
        return result;
    }
    auto* status = cJSON_GetObjectItem(root, "status");
    auto* user_id = cJSON_GetObjectItem(root, "user_id");
    auto* display_name = cJSON_GetObjectItem(root, "display_name");
    auto* name = cJSON_GetObjectItem(root, "name");
    auto* confidence = cJSON_GetObjectItem(root, "confidence");
    auto* reason = cJSON_GetObjectItem(root, "reason");
    if (cJSON_IsString(status) && status->valuestring) {
        result.status = status->valuestring;
    }
    if (cJSON_IsString(user_id) && user_id->valuestring) {
        result.user_id = user_id->valuestring;
    }
    if (cJSON_IsString(display_name) && display_name->valuestring) {
        result.display_name = display_name->valuestring;
    } else if (cJSON_IsString(name) && name->valuestring) {
        result.display_name = name->valuestring;
    }
    if (cJSON_IsNumber(confidence)) {
        result.confidence = static_cast<float>(confidence->valuedouble);
    }
    if (cJSON_IsString(reason) && reason->valuestring) {
        result.server_reason = reason->valuestring;
    }
    cJSON_Delete(root);

    if (result.status.empty()) {
        result.status = "error";
        result.error_reason = "missing_status";
    }
    if (result.status == "known" && !result.IsKnownPerson()) {
        result.status = "error";
        result.error_reason = "invalid_user_id";
        result.user_id.clear();
    }
    ESP_LOGI(kTag,
             "[REMINDER_DELIVERY] event=verify_result status=%s user=%s "
             "http_status=%d reason=%s gen=%u snap_gen=%u",
             result.status.c_str(),
             result.user_id.empty() ? "-" : result.user_id.c_str(),
             result.http_status,
             result.server_reason.empty() ? "-" : result.server_reason.c_str(),
             static_cast<unsigned>(request_generation),
             static_cast<unsigned>(snap.connection_generation));
    return result;
} catch (const std::bad_alloc&) {
    ESP_LOGE(kTag, "[PHOTO_PSRAM] identity upload stopped: insufficient image memory");
    IdentityResult result;
    result.status = "error";
    result.request_generation = request_generation;
    result.error_reason = "resource_exhausted";
    return result;
}
