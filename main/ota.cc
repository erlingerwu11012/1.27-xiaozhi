#include "ota.h"
#include "system_info.h"
#include "settings.h"
#include "assets/lang_config.h"
#include "auth_connection.h"
#include "ota_tls_diag.h"

#include <cJSON.h>
#include <esp_log.h>
#include <sdkconfig.h>
#include <esp_partition.h>
#include <esp_ota_ops.h>
#include <esp_app_format.h>
#include <esp_efuse.h>
#include <esp_efuse_table.h>
#include <esp_timer.h>
#include <esp_random.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#ifdef SOC_HMAC_SUPPORTED
#include <esp_hmac.h>
#endif

#include <cstring>
#include <cstdlib>
#include <cstdio>
#include <ctime>
#include <vector>
#include <sstream>
#include <algorithm>
#include <memory>
#include <sys/time.h>

#define TAG "Ota"

namespace {
constexpr const char* kWsCacheNs = "ws_vcache";
constexpr int32_t kWsCacheSchemaVersion = 1;

bool StartsWithIgnoreCase(const std::string& value, const char* prefix) {
    size_t n = strlen(prefix);
    if (value.size() < n) {
        return false;
    }
    for (size_t i = 0; i < n; ++i) {
        char a = value[i];
        char b = prefix[i];
        if (a >= 'A' && a <= 'Z') {
            a = static_cast<char>(a - 'A' + 'a');
        }
        if (b >= 'A' && b <= 'Z') {
            b = static_cast<char>(b - 'A' + 'a');
        }
        if (a != b) {
            return false;
        }
    }
    return true;
}

bool IsValidWssUrl(const std::string& url) {
    return StartsWithIgnoreCase(url, "wss://") && url.size() > 6;
}

std::string Base64UrlEncode(const uint8_t* data, size_t len) {
    static const char kTable[] =
        "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
    std::string out;
    out.reserve(((len + 2) / 3) * 4);
    for (size_t i = 0; i < len; i += 3) {
        const uint32_t n = (static_cast<uint32_t>(data[i]) << 16) |
                           ((i + 1 < len ? data[i + 1] : 0) << 8) |
                           (i + 2 < len ? data[i + 2] : 0);
        out.push_back(kTable[(n >> 18) & 63]);
        out.push_back(kTable[(n >> 12) & 63]);
        if (i + 1 < len) {
            out.push_back(kTable[(n >> 6) & 63]);
        }
        if (i + 2 < len) {
            out.push_back(kTable[n & 63]);
        }
    }
    return out;
}

std::string GeneratePairingSecret() {
    uint8_t raw[32];
    esp_fill_random(raw, sizeof(raw));
    return Base64UrlEncode(raw, sizeof(raw));
}

}  // namespace


Ota::Ota() {
#ifdef ESP_EFUSE_BLOCK_USR_DATA
    // Read Serial Number from efuse user_data
    uint8_t serial_number[33] = {0};
    if (esp_efuse_read_field_blob(ESP_EFUSE_USER_DATA, serial_number, 32 * 8) == ESP_OK) {
        if (serial_number[0] == 0) {
            has_serial_number_ = false;
        } else {
            serial_number_ = std::string(reinterpret_cast<char*>(serial_number), 32);
            has_serial_number_ = true;
        }
    }
#endif
}

Ota::~Ota() {
}

void Ota::SetLastCheckReason(const char* reason) {
    last_check_reason_ = reason ? reason : "unknown";
}

bool Ota::HasValidatedWebsocketSnapshot() const {
    Settings settings(kWsCacheNs, false);
    if (!settings.GetBool("valid", false)) {
        return false;
    }
    if (settings.GetInt("schema", 0) != kWsCacheSchemaVersion) {
        return false;
    }
    std::string url = settings.GetString("url");
    std::string token = settings.GetString("token");
    return IsValidWssUrl(url) && !token.empty();
}

void Ota::ClearPersistedWebsocketCredentials() {
    // Explicit terminal revocation only.  Transport failures never call this.
    // The vault refuses a stale epoch, and a newer pairing session is left
    // intact.  Secrets are not written to the log.
    const uint32_t epoch = authconn::CurrentPersistedEpoch();
    const authconn::Outcome outcome =
        authconn::ApplyPersistedTerminal("credential_revoked", epoch);
    ESP_LOGW(TAG, "[OTA_BOOT] event=websocket_credentials_cleared reason=%s epoch=%u",
             authconn::StatusName(outcome.status), static_cast<unsigned>(epoch));
}

bool Ota::RestoreValidatedWebsocketSnapshot() {
    if (!authconn::MayRestorePersistedCache()) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=cache_reject reason=revoked_or_session");
        return false;
    }
    const authconn::ConnectableCredential current = authconn::LoadPersistedConnectable();
    if (current.present && authconn::MirrorPersistedCredential(current)) {
        has_websocket_config_ = true;
        last_auth_action_ = authconn::AuthAction::kConnect;
        last_auth_status_ = authconn::AuthStatus::kOk;
        ESP_LOGI(TAG, "[OTA_BOOT] event=config_fallback source=validated_cache");
        return true;
    }
    Settings cache(kWsCacheNs, false);
    if (!cache.GetBool("valid", false)) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=cache_reject reason=not_valid");
        return false;
    }
    if (cache.GetInt("schema", 0) != kWsCacheSchemaVersion) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=cache_reject reason=schema");
        return false;
    }
    std::string url = cache.GetString("url");
    std::string token = cache.GetString("token");
    int version = cache.GetInt("version", 1);
    if (!IsValidWssUrl(url) || token.empty()) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=cache_reject reason=fields");
        return false;
    }
    if (version <= 0) {
        version = 1;
    }
    {
        Settings settings("websocket", true);
        if (!settings.IsValid() || settings.SetString("url", url) != ESP_OK ||
            settings.SetString("token", token) != ESP_OK ||
            settings.SetInt("version", version) != ESP_OK || settings.Commit() != ESP_OK) {
            ESP_LOGW(TAG, "[OTA_BOOT] event=persist_failed target=cache_restore");
            return false;
        }
    }
    has_websocket_config_ = true;
    ESP_LOGI(TAG, "[OTA_BOOT] event=config_fallback source=validated_cache");
    return true;
}

std::string Ota::GetCheckVersionUrl() {
    Settings settings("wifi", false);
    std::string url = settings.GetString("ota_url");
    if (url.empty()) {
        url = CONFIG_OTA_URL;
    }
    return url;
}

std::unique_ptr<Http> Ota::SetupHttp() {
    auto& board = Board::GetInstance();
    auto network = board.GetNetwork();
    auto http = network->CreateHttp(0);
    auto user_agent = SystemInfo::GetUserAgent();
    http->SetHeader("Activation-Version", has_serial_number_ ? "2" : "1");
    http->SetHeader("Device-Id", SystemInfo::GetMacAddress().c_str());
    http->SetHeader("Client-Id", board.GetUuid().c_str());
    if (has_serial_number_) {
        http->SetHeader("Serial-Number", serial_number_.c_str());
        ESP_LOGI(TAG, "Setup HTTP, User-Agent: %s, Serial-Number: %s", user_agent.c_str(), serial_number_.c_str());
    }
    http->SetHeader("User-Agent", user_agent.c_str());
    http->SetHeader("Accept-Language", Lang::CODE);
    http->SetHeader("Content-Type", "application/json");

    // Device key, pairing secret and confirm may be sent together.  A WSS token
    // is never placed in Authorization or X-Pairing-Secret.
    const authconn::HeaderChoice choice = authconn::SelectPersistedHeader();
    if (!choice.device_key.empty()) {
        const std::string authorization = "Bearer " + choice.device_key;
        http->SetHeader("Authorization", authorization.c_str());
    }
    if (!choice.pairing_secret.empty()) {
        http->SetHeader("X-Pairing-Secret", choice.pairing_secret.c_str());
    }
    if (!choice.activation_code.empty()) {
        http->SetHeader("X-Activation-Code", choice.activation_code.c_str());
    }
    if (!choice.session_id.empty()) {
        http->SetHeader("X-Session-Id", choice.session_id.c_str());
    }
    if (choice.confirm) {
        http->SetHeader("X-Auth-Confirm", "1");
    }
    ESP_LOGI(TAG,
             "[OTA_BOOT] event=auth_header kind=%d key=%d pairing=%d activation=%d confirm=%d session=%d epoch=%u",
             static_cast<int>(choice.kind), choice.device_key.empty() ? 0 : 1,
             choice.pairing_secret.empty() ? 0 : 1, choice.activation_code.empty() ? 0 : 1,
             choice.confirm ? 1 : 0, choice.session_id.empty() ? 0 : 1,
             static_cast<unsigned>(choice.credential_epoch));

    return http;
}

/* 
 * Specification: https://ccnphfhqs21z.feishu.cn/wiki/FjW6wZmisimNBBkov6OcmfvknVd
 */
bool Ota::IngestAuthResponse(const std::string& body, int status_code, bool confirm_sent) {
    if (status_code != 200 && status_code != 429 && status_code != 503) {
        SetLastCheckReason("http_status");
        last_auth_action_ = authconn::AuthAction::kRetryTransport;
        last_auth_status_ = authconn::AuthStatus::kTemporaryError;
        return false;
    }
    authconn::HttpObservation observation;
    authconn::HttpPayload payload;
    if (!authconn::ParseOtaAuthJson(body.c_str(), &observation, &payload)) {
        if (status_code == 429) {
            SetLastCheckReason("http_429");
            last_auth_action_ = authconn::AuthAction::kQuietBackoff;
            last_auth_status_ = authconn::AuthStatus::kRateLimited;
            auth_retry_after_ms_ = 15000;
        } else {
            SetLastCheckReason(status_code == 200 ? "bad_json" : "http_status");
            last_auth_action_ = authconn::AuthAction::kRetryTransport;
            last_auth_status_ = authconn::AuthStatus::kTemporaryError;
            if (status_code == 503) {
                auth_retry_after_ms_ = 5000;
            }
        }
        return false;
    }
    observation.request_gen = authconn::NextPersistedRequestGen();
    observation.confirm_sent = confirm_sent;
    const bool needs_secret =
        observation.envelope_present && observation.schema == 1 &&
        (observation.envelope_status == authconn::AuthStatus::kPairingRequired ||
         observation.envelope_status == authconn::AuthStatus::kRecoveryRequired) &&
        observation.secret_required_known && observation.secret_required &&
        !authconn::HasPersistedPairingSession();
    if (needs_secret) {
        payload.pairing_secret = GeneratePairingSecret();
        if (!authconn::IsHighEntropySecret(payload.pairing_secret)) {
            last_auth_action_ = authconn::AuthAction::kRetryPersist;
            last_auth_status_ = authconn::AuthStatus::kPersistFailed;
            SetLastCheckReason("persist_failed");
            return true;
        }
    }
    if (observation.has_user_code) {
        activation_code_ = payload.user_code;
        has_activation_code_ = true;
    }
    const authconn::Outcome outcome = authconn::ApplyPersistedHttp(observation, payload);
    last_auth_action_ = outcome.action;
    last_auth_status_ = outcome.status;
    auth_retry_after_ms_ = outcome.retry_after_ms;
    if (status_code == 429 && auth_retry_after_ms_ <= 0) {
        auth_retry_after_ms_ = 15000;
        if (last_auth_action_ == authconn::AuthAction::kRetryIncomplete) {
            last_auth_action_ = authconn::AuthAction::kQuietBackoff;
        }
    }
    if (outcome.action == authconn::AuthAction::kConnect) {
        const authconn::ConnectableCredential credential = authconn::LoadPersistedConnectable();
        if (credential.present) {
            has_websocket_config_ = authconn::MirrorPersistedCredential(credential);
            if (!has_websocket_config_) {
                Settings existing("websocket", false);
                has_websocket_config_ = existing.GetString("url") == credential.url &&
                                        existing.GetString("token") == credential.token &&
                                        !credential.token.empty();
            }
        }
        if (!has_websocket_config_) {
            last_auth_action_ = authconn::AuthAction::kRetryPersist;
            last_auth_status_ = authconn::AuthStatus::kPersistFailed;
            SetLastCheckReason("persist_failed");
        }
    } else {
        has_websocket_config_ = false;
        if (last_auth_action_ == authconn::AuthAction::kRetryIncomplete &&
            authconn::MayRestorePersistedCache()) {
            Settings existing("websocket", false);
            const std::string existing_url = existing.GetString("url");
            const std::string existing_token = existing.GetString("token");
            const std::string existing_key = existing.GetString("auth_key");
            if (IsValidWssUrl(existing_url) && !existing_token.empty() &&
                authconn::IsOpaqueDeviceCredential(existing_key)) {
                has_websocket_config_ = true;
                last_auth_action_ = authconn::AuthAction::kConnect;
                last_auth_status_ = authconn::AuthStatus::kOk;
            }
        }
    }
    if (outcome.action == authconn::AuthAction::kWaitPairing ||
        outcome.action == authconn::AuthAction::kWaitRecovery) {
        ESP_LOGI(TAG, "[OTA_BOOT] event=session_committed status=%s code=%d",
                 authconn::StatusName(outcome.status), has_activation_code_ ? 1 : 0);
    }
    if (observation.credential_version_present) {
        ESP_LOGI(TAG, "[OTA_BOOT] event=credential_version value=%lld",
                 static_cast<long long>(observation.credential_version));
    }
    return true;
}

bool Ota::CheckVersion() {
    auto& board = Board::GetInstance();
    auto app_desc = esp_app_get_description();

    // Check if there is a new firmware version available
    current_version_ = app_desc->version;
    ESP_LOGI(TAG, "Current version: %s", current_version_.c_str());
    SetLastCheckReason("unknown");

    std::string url = GetCheckVersionUrl();
    if (url.length() < 10) {
        ESP_LOGE(TAG, "Check version URL is not properly set");
        SetLastCheckReason("bad_url");
        return false;
    }

    // Serialize OTA HTTP + optional pure-TLS probe: never overlap attempts.
    uint32_t attempt_id = 0;
    for (int wait = 0; wait < 50 && attempt_id == 0; ++wait) {
        attempt_id = OtaTlsDiag::BeginAttempt("ota_check_version");
        if (attempt_id == 0) {
            vTaskDelay(pdMS_TO_TICKS(100));
        }
    }
    if (attempt_id == 0) {
        ESP_LOGE(TAG, "[OTA_BOOT] event=gate_timeout");
        SetLastCheckReason("gate_busy");
        return false;
    }

    struct AttemptGuard {
        uint32_t id;
        ~AttemptGuard() { OtaTlsDiag::EndAttempt(id); }
    } guard{attempt_id};

#if CONFIG_REALECHO_OTA_TLS_PROBE
    bool pure_ok = OtaTlsDiag::RunPureTlsProbe(attempt_id);
    ESP_LOGI(TAG, "[OTA_BOOT] event=pure_tls_probe attempt=%u ok=%d",
             static_cast<unsigned>(attempt_id), pure_ok ? 1 : 0);
#endif

    auto http = SetupHttp();

    std::string data = board.GetSystemInfoJson();
    std::string method = data.length() > 0 ? "POST" : "GET";
    http->SetContent(std::move(data));

    ESP_LOGI(TAG, "[OTA_BOOT] event=http_begin attempt=%u method=%s",
             static_cast<unsigned>(attempt_id), method.c_str());
    if (!http->Open(method.c_str(), url)) {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        SetLastCheckReason("tls_open_failed");
        last_auth_action_ = authconn::AuthAction::kRetryTransport;
        last_auth_status_ = authconn::AuthStatus::kTemporaryError;
        return false;
    }

    auto status_code = http->GetStatusCode();
    if (status_code == 200 || status_code == 429 || status_code == 503) {
        data = http->ReadAll();
    }
    http->Close();
    if (status_code != 200 && status_code != 429 && status_code != 503) {
        ESP_LOGE(TAG, "Failed to check version, status code: %d", status_code);
        SetLastCheckReason("http_status");
        last_auth_action_ = authconn::AuthAction::kRetryTransport;
        last_auth_status_ = authconn::AuthStatus::kTemporaryError;
        return false;
    }
    ESP_LOGI(TAG, "[OTA_BOOT] event=http_done attempt=%u status=%d",
             static_cast<unsigned>(attempt_id), status_code);
    if (!IngestAuthResponse(data, status_code, false)) {
        return false;
    }
    for (int extra = 0; extra < 2; ++extra) {
        const bool want_code =
            (last_auth_action_ == authconn::AuthAction::kWaitPairing ||
             last_auth_action_ == authconn::AuthAction::kWaitRecovery) &&
            !has_activation_code_ && authconn::HasPersistedPairingSession();
        const bool want_confirm = last_auth_action_ == authconn::AuthAction::kConnect &&
                                  has_websocket_config_ && authconn::PersistedConfirmPending();
        if (!want_code && !want_confirm) {
            break;
        }
        auto follow = SetupHttp();
        follow->SetContent(board.GetSystemInfoJson());
        if (!follow->Open(method.c_str(), url)) {
            ESP_LOGW(TAG, "[OTA_BOOT] event=auth_followup_failed confirm=%d", want_confirm ? 1 : 0);
            break;
        }
        const int follow_status = follow->GetStatusCode();
        std::string follow_body;
        if (follow_status == 200 || follow_status == 429 || follow_status == 503) {
            follow_body = follow->ReadAll();
        }
        follow->Close();
        if (!IngestAuthResponse(follow_body, follow_status, want_confirm && !want_code)) {
            break;
        }
        data = std::move(follow_body);
    }

    // Response: { "firmware": { "version": "1.0.0", "url": "http://" } }
    // Parse the JSON response and check if the version is newer
    // If it is, set has_new_version_ to true and store the new version and URL
    
    cJSON *root = cJSON_Parse(data.c_str());
    if (root == NULL) {
        ESP_LOGE(TAG, "Failed to parse JSON response");
        return true;
    }

    has_activation_challenge_ = false;
    activation_challenge_.clear();
    activation_message_.clear();
    cJSON *activation = cJSON_GetObjectItem(root, "activation");
    if (cJSON_IsObject(activation)) {
        cJSON* message = cJSON_GetObjectItem(activation, "message");
        if (cJSON_IsString(message)) {
            activation_message_ = message->valuestring;
        }
        if (!has_activation_code_) {
            cJSON* code = cJSON_GetObjectItem(activation, "code");
            if (cJSON_IsNumber(code)) {
                int code_val = code->valueint;
                if (code_val < 0) code_val = 0;
                char buf[16];
                snprintf(buf, sizeof(buf), "%06d", code_val % 1000000);
                activation_code_ = buf;
                has_activation_code_ = true;
            }
        }
        cJSON* challenge = cJSON_GetObjectItem(activation, "challenge");
        if (cJSON_IsString(challenge)) {
            activation_challenge_ = challenge->valuestring;
            has_activation_challenge_ = true;
        }
        cJSON* timeout_ms = cJSON_GetObjectItem(activation, "timeout_ms");
        if (cJSON_IsNumber(timeout_ms)) {
            activation_timeout_ms_ = timeout_ms->valueint;
        }
    }

    has_mqtt_config_ = false;
    cJSON *mqtt = cJSON_GetObjectItem(root, "mqtt");
    if (cJSON_IsObject(mqtt)) {
        Settings settings("mqtt", true);
        cJSON *item = NULL;
        cJSON_ArrayForEach(item, mqtt) {
            if (cJSON_IsString(item)) {
                if (settings.GetString(item->string) != item->valuestring) {
                    settings.SetString(item->string, item->valuestring);
                }
            } else if (cJSON_IsNumber(item)) {
                if (settings.GetInt(item->string) != item->valueint) {
                    settings.SetInt(item->string, item->valueint);
                }
            }
        }
        has_mqtt_config_ = true;
    } else {
        ESP_LOGI(TAG, "No mqtt section found !");
    }

    ESP_LOGI(TAG, "[OTA_BOOT] event=config_parsed websocket=%d mqtt=%d source=network status=%s action=%s",
             has_websocket_config_ ? 1 : 0, has_mqtt_config_ ? 1 : 0,
             authconn::StatusName(last_auth_status_), authconn::ActionName(last_auth_action_));

    has_server_time_ = false;
    cJSON *server_time = cJSON_GetObjectItem(root, "server_time");
    if (cJSON_IsObject(server_time)) {
        cJSON *timestamp = cJSON_GetObjectItem(server_time, "timestamp");
        cJSON *timezone_offset = cJSON_GetObjectItem(server_time, "timezone_offset");

        if (cJSON_IsNumber(timestamp)) {
            // Unix epoch is absolute UTC time. Never add timezone_offset to
            // settimeofday — that would shift wall-clock epoch and break
            // expires_at checks (e.g. offset=480 => +28800s ahead).
            struct timeval tv;
            const double ts = timestamp->valuedouble;
            const int tz_offset_min =
                cJSON_IsNumber(timezone_offset) ? timezone_offset->valueint : 0;

            tv.tv_sec = (time_t)(ts / 1000);  // ms -> s
            tv.tv_usec =
                (suseconds_t)((long long)ts % 1000) * 1000;  // leftover ms -> us
            settimeofday(&tv, NULL);
            has_server_time_ = true;

            // timezone_offset (minutes east of UTC) is display-only via TZ.
            if (cJSON_IsNumber(timezone_offset)) {
                const int hours = tz_offset_min / 60;
                const int mins = tz_offset_min % 60;
                const int abs_mins = mins < 0 ? -mins : mins;
                char tz[24];
                // POSIX TZ offset is hours west of UTC (sign flipped).
                if (mins == 0) {
                    std::snprintf(tz, sizeof(tz), "UTC%+d", -hours);
                } else {
                    std::snprintf(tz, sizeof(tz), "UTC%+d:%02d", -hours,
                                  abs_mins);
                }
                setenv("TZ", tz, 1);
                tzset();
            }

            ESP_LOGI(TAG,
                     "[OTA_BOOT] event=server_time timestamp_ms=%.0f "
                     "timezone_offset=%d now_unix=%lld",
                     ts, tz_offset_min, (long long)time(nullptr));
        }
    } else {
        ESP_LOGW(TAG, "No server_time section found!");
    }

    has_new_version_ = false;
    cJSON *firmware = cJSON_GetObjectItem(root, "firmware");
    if (cJSON_IsObject(firmware)) {
        cJSON *version = cJSON_GetObjectItem(firmware, "version");
        if (cJSON_IsString(version)) {
            firmware_version_ = version->valuestring;
        }
        cJSON *url = cJSON_GetObjectItem(firmware, "url");
        if (cJSON_IsString(url)) {
            firmware_url_ = url->valuestring;
        }

        if (cJSON_IsString(version) && cJSON_IsString(url)) {
            // Check if the version is newer, for example, 0.1.0 is newer than 0.0.1
            has_new_version_ = IsNewVersionAvailable(current_version_, firmware_version_);
            if (has_new_version_) {
                ESP_LOGI(TAG, "New version available: %s", firmware_version_.c_str());
            } else {
                ESP_LOGI(TAG, "Current is the latest version");
            }
            // If the force flag is set to 1, the given version is forced to be installed
            cJSON *force = cJSON_GetObjectItem(firmware, "force");
            if (cJSON_IsNumber(force) && force->valueint == 1) {
                has_new_version_ = true;
            }
        }
    } else {
        ESP_LOGW(TAG, "No firmware section found!");
    }

    cJSON_Delete(root);
    return true;
}

void Ota::MarkCurrentVersionValid() {
    auto partition = esp_ota_get_running_partition();
    if (strcmp(partition->label, "factory") == 0) {
        ESP_LOGI(TAG, "Running from factory partition, skipping");
        return;
    }

    ESP_LOGI(TAG, "Running partition: %s", partition->label);
    esp_ota_img_states_t state;
    if (esp_ota_get_state_partition(partition, &state) != ESP_OK) {
        ESP_LOGE(TAG, "Failed to get state of partition");
        return;
    }

    if (state == ESP_OTA_IMG_PENDING_VERIFY) {
        ESP_LOGI(TAG, "Marking firmware as valid");
        esp_ota_mark_app_valid_cancel_rollback();
    }
}

bool Ota::Upgrade(const std::string& firmware_url) {
    ESP_LOGI(TAG, "Upgrading firmware from %s", firmware_url.c_str());
    esp_ota_handle_t update_handle = 0;
    auto update_partition = esp_ota_get_next_update_partition(NULL);
    if (update_partition == NULL) {
        ESP_LOGE(TAG, "Failed to get update partition");
        return false;
    }

    ESP_LOGI(TAG, "Writing to partition %s at offset 0x%lx", update_partition->label, update_partition->address);
    bool image_header_checked = false;
    std::string image_header;

    auto network = Board::GetInstance().GetNetwork();
    auto http = network->CreateHttp(0);
    if (!http->Open("GET", firmware_url)) {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        return false;
    }

    if (http->GetStatusCode() != 200) {
        ESP_LOGE(TAG, "Failed to get firmware, status code: %d", http->GetStatusCode());
        return false;
    }

    size_t content_length = http->GetBodyLength();
    if (content_length == 0) {
        ESP_LOGE(TAG, "Failed to get content length");
        return false;
    }

    char buffer[512];
    size_t total_read = 0, recent_read = 0;
    auto last_calc_time = esp_timer_get_time();
    while (true) {
        int ret = http->Read(buffer, sizeof(buffer));
        if (ret < 0) {
            ESP_LOGE(TAG, "Failed to read HTTP data: %s", esp_err_to_name(ret));
            return false;
        }

        // Calculate speed and progress every second
        recent_read += ret;
        total_read += ret;
        if (esp_timer_get_time() - last_calc_time >= 1000000 || ret == 0) {
            size_t progress = total_read * 100 / content_length;
            ESP_LOGI(TAG, "Progress: %u%% (%u/%u), Speed: %uB/s", progress, total_read, content_length, recent_read);
            if (upgrade_callback_) {
                upgrade_callback_(progress, recent_read);
            }
            last_calc_time = esp_timer_get_time();
            recent_read = 0;
        }

        if (ret == 0) {
            break;
        }

        if (!image_header_checked) {
            image_header.append(buffer, ret);
            if (image_header.size() >= sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t) + sizeof(esp_app_desc_t)) {
                esp_app_desc_t new_app_info;
                memcpy(&new_app_info, image_header.data() + sizeof(esp_image_header_t) + sizeof(esp_image_segment_header_t), sizeof(esp_app_desc_t));
                
                auto current_version = esp_app_get_description()->version;
                ESP_LOGI(TAG, "Current version: %s, New version: %s", current_version, new_app_info.version);

                if (esp_ota_begin(update_partition, OTA_WITH_SEQUENTIAL_WRITES, &update_handle)) {
                    esp_ota_abort(update_handle);
                    ESP_LOGE(TAG, "Failed to begin OTA");
                    return false;
                }

                image_header_checked = true;
                std::string().swap(image_header);
            }
        }
        auto err = esp_ota_write(update_handle, buffer, ret);
        if (err != ESP_OK) {
            ESP_LOGE(TAG, "Failed to write OTA data: %s", esp_err_to_name(err));
            esp_ota_abort(update_handle);
            return false;
        }
    }
    http->Close();

    esp_err_t err = esp_ota_end(update_handle);
    if (err != ESP_OK) {
        if (err == ESP_ERR_OTA_VALIDATE_FAILED) {
            ESP_LOGE(TAG, "Image validation failed, image is corrupted");
        } else {
            ESP_LOGE(TAG, "Failed to end OTA: %s", esp_err_to_name(err));
        }
        return false;
    }

    err = esp_ota_set_boot_partition(update_partition);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Failed to set boot partition: %s", esp_err_to_name(err));
        return false;
    }

    ESP_LOGI(TAG, "Firmware upgrade successful");
    return true;
}

bool Ota::StartUpgrade(std::function<void(int progress, size_t speed)> callback) {
    upgrade_callback_ = callback;
    return Upgrade(firmware_url_);
}

bool Ota::StartUpgradeFromUrl(const std::string& url, std::function<void(int progress, size_t speed)> callback) {
    upgrade_callback_ = callback;
    return Upgrade(url);
}

std::vector<int> Ota::ParseVersion(const std::string& version) {
    std::vector<int> versionNumbers;
    std::stringstream ss(version);
    std::string segment;
    
    while (std::getline(ss, segment, '.')) {
        versionNumbers.push_back(std::stoi(segment));
    }
    
    return versionNumbers;
}

bool Ota::IsNewVersionAvailable(const std::string& currentVersion, const std::string& newVersion) {
    std::vector<int> current = ParseVersion(currentVersion);
    std::vector<int> newer = ParseVersion(newVersion);
    
    for (size_t i = 0; i < std::min(current.size(), newer.size()); ++i) {
        if (newer[i] > current[i]) {
            return true;
        } else if (newer[i] < current[i]) {
            return false;
        }
    }
    
    return newer.size() > current.size();
}

std::string Ota::GetActivationPayload() {
    if (!has_serial_number_) {
        return "{}";
    }

    std::string hmac_hex;
#ifdef SOC_HMAC_SUPPORTED
    uint8_t hmac_result[32]; // SHA-256 输出为32字节
    
    // 使用Key0计算HMAC
    esp_err_t ret = esp_hmac_calculate(HMAC_KEY0, (uint8_t*)activation_challenge_.data(), activation_challenge_.size(), hmac_result);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "HMAC calculation failed: %s", esp_err_to_name(ret));
        return "{}";
    }

    for (size_t i = 0; i < sizeof(hmac_result); i++) {
        char buffer[3];
        sprintf(buffer, "%02x", hmac_result[i]);
        hmac_hex += buffer;
    }
#endif

    cJSON *payload = cJSON_CreateObject();
    cJSON_AddStringToObject(payload, "algorithm", "hmac-sha256");
    cJSON_AddStringToObject(payload, "serial_number", serial_number_.c_str());
    cJSON_AddStringToObject(payload, "challenge", activation_challenge_.c_str());
    cJSON_AddStringToObject(payload, "hmac", hmac_hex.c_str());
    auto json_str = cJSON_PrintUnformatted(payload);
    std::string json(json_str);
    cJSON_free(json_str);
    cJSON_Delete(payload);

    // The challenge/HMAC are authentication material.  Keep diagnostics
    // useful without ever writing them to a serial or cloud log.
    ESP_LOGI(TAG, "Activation payload prepared (serial=%d challenge=%d hmac=%d)",
             serial_number_.empty() ? 0 : 1,
             activation_challenge_.empty() ? 0 : 1,
             hmac_hex.empty() ? 0 : 1);
    return json;
}

esp_err_t Ota::Activate() {
    if (!has_activation_challenge_) {
        ESP_LOGW(TAG, "No activation challenge found");
        return ESP_FAIL;
    }

    std::string url = GetCheckVersionUrl();
    if (url.back() != '/') {
        url += "/activate";
    } else {
        url += "activate";
    }

    auto http = SetupHttp();

    std::string data = GetActivationPayload();
    http->SetContent(std::move(data));

    if (!http->Open("POST", url)) {
        ESP_LOGE(TAG, "Failed to open HTTP connection");
        return ESP_FAIL;
    }
    
    auto status_code = http->GetStatusCode();
    if (status_code == 202) {
        return ESP_ERR_TIMEOUT;
    }
    if (status_code != 200) {
        ESP_LOGE(TAG, "Failed to activate, code: %d, body: %s", status_code, http->ReadAll().c_str());
        return ESP_FAIL;
    }

    ESP_LOGI(TAG, "Activation successful");
    return ESP_OK;
}
