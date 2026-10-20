#include "reminder_voice_service.h"

#include "application.h"
#include "assets/lang_config.h"
#include "board.h"
#include "device_state.h"
#include "http.h"
#include "network_interface.h"
#include "presence_context.h"
#include "reminder_coordinator.h"
#include "system_info.h"
#include "test_observability.h"
#include "user_context.h"

#include <cJSON.h>
#include <cmath>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <mbedtls/sha256.h>

#include <atomic>
#include <algorithm>
#include <cstdio>
#include <cstring>
#include <dirent.h>
#include <memory>
#include <mutex>
#include <sys/stat.h>
#include <vector>

namespace {

constexpr const char* kTag = "ReminderVoice";
constexpr uint32_t kMaxAssetBytes = 16 * 1024;
std::atomic<bool> g_download_active{false};

bool IsLowerHexSha256(const std::string& value) {
    if (value.size() != 64) return false;
    for (char ch : value) {
        if (!((ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'f'))) {
            return false;
        }
    }
    return true;
}

bool IsAllowedPhase(const std::string& phase) {
    return phase == "pre_alert" || phase == "due" || phase == "repeat" ||
           phase == "completion" || phase == "snooze" ||
           phase == "skip";
}

std::string DigestHex(const unsigned char digest[32]) {
    static const char kHex[] = "0123456789abcdef";
    std::string result(64, '0');
    for (size_t i = 0; i < 32; ++i) {
        result[i * 2] = kHex[digest[i] >> 4];
        result[i * 2 + 1] = kHex[digest[i] & 0x0f];
    }
    return result;
}

struct DownloadContext {
    std::string instance_id;
    uint32_t voice_revision = 0;
    ReminderVoiceAsset asset;
    ReminderVoiceService::Completion completion;
};

}  // namespace

ReminderVoiceService& ReminderVoiceService::GetInstance() {
    static ReminderVoiceService instance;
    return instance;
}

std::string ReminderVoiceService::BuildCachePath(
    const std::string& instance_id, uint32_t voice_revision,
    const std::string& phase, const std::string& sha256) {
    const std::string key =
        instance_id + "\x1f" + std::to_string(voice_revision) +
        "\x1f" + phase + "\x1f" + sha256;
    unsigned char digest[32] = {};
    mbedtls_sha256_context context;
    mbedtls_sha256_init(&context);
    mbedtls_sha256_starts(&context, 0);
    mbedtls_sha256_update(
        &context,
        reinterpret_cast<const unsigned char*>(key.data()),
        key.size());
    mbedtls_sha256_finish(&context, digest);
    mbedtls_sha256_free(&context);
    // CONFIG_SPIFFS_OBJ_NAME_LEN=32: "r" + 25 hex + ".ogg" is 30 bytes.
    return "/userdata/r" + DigestHex(digest).substr(0, 25) + ".ogg";
}

bool ReminderVoiceService::IsCurrentCachePath(
    const std::string& path) {
    constexpr size_t kPrefixLength = 11;  // "/userdata/r"
    if (path.size() != 40 ||
        path.rfind("/userdata/r", 0) != 0 ||
        path.compare(path.size() - 4, 4, ".ogg") != 0) {
        return false;
    }
    for (size_t index = kPrefixLength;
         index < path.size() - 4; ++index) {
        const char ch = path[index];
        if (!((ch >= '0' && ch <= '9') ||
              (ch >= 'a' && ch <= 'f'))) {
            return false;
        }
    }
    return true;
}

void ReminderVoiceService::CleanupLegacyCacheFiles() {
    DIR* directory = opendir("/userdata");
    if (!directory) return;
    while (dirent* entry = readdir(directory)) {
        const std::string name = entry->d_name;
        if (name.size() > 6 && name.rfind("rv", 0) == 0 &&
            name.compare(name.size() - 4, 4, ".ogg") == 0) {
            std::remove(("/userdata/" + name).c_str());
        }
    }
    closedir(directory);
}

bool ReminderVoiceService::ValidateAsset(const ReminderVoiceAsset& asset,
                                         std::string& error) {
    if (!IsAllowedPhase(asset.phase)) {
        error = "unsupported voice phase";
        return false;
    }
    if (asset.script.empty() || asset.script.size() > 256) {
        error = "voice script must be between 1 and 256 bytes";
        return false;
    }
    if (asset.url.rfind("https://", 0) != 0 || asset.url.size() > 512) {
        error = "voice asset URL must be HTTPS and at most 512 bytes";
        return false;
    }
    if (!IsLowerHexSha256(asset.sha256)) {
        error = "voice asset sha256 must be 64 lowercase hex characters";
        return false;
    }
    if (asset.format != "ogg_opus") {
        error = "only ogg_opus voice assets are supported";
        return false;
    }
    if (asset.byte_count == 0 || asset.byte_count > kMaxAssetBytes) {
        error = "voice asset size must be between 1 and 16384 bytes";
        return false;
    }
    return true;
}

void ReminderVoiceService::RequestScripts(const ReminderInstance& instance,
                                          size_t pending_count,
                                          bool missed_occurrence) {
    if (instance.source_type == ReminderSourceType::kInformation) return;
    ESP_LOGI(kTag,
             "[REMINDER_VOICE] event=request instance=%s voice_rev=%u "
             "source=%s title=\"%s\"",
             instance.instance_id.c_str(),
             static_cast<unsigned>(instance.voice_revision),
             ReminderCoordinator::SourceTypeName(instance.source_type),
             instance.title.c_str());
    cJSON* root = cJSON_CreateObject();
    cJSON_AddStringToObject(root, "type", "reminder_voice_request");
    cJSON_AddStringToObject(root, "instance_id", instance.instance_id.c_str());
    cJSON_AddNumberToObject(root, "revision", instance.revision);
    cJSON_AddNumberToObject(
        root, "voice_revision", instance.voice_revision);
    cJSON_AddStringToObject(
        root, "recipient_person_id", instance.recipient_person_id.c_str());
    cJSON_AddNumberToObject(
        root, "presence_generation",
        instance.delivery_presence_generation);
    cJSON_AddStringToObject(
        root, "source_type",
        ReminderCoordinator::SourceTypeName(instance.source_type));
    cJSON_AddStringToObject(root, "title", instance.title.c_str());
    cJSON_AddStringToObject(root, "detail", instance.detail.c_str());
    cJSON_AddNumberToObject(root, "pending_count",
                            static_cast<double>(pending_count));
    cJSON_AddBoolToObject(root, "announce_pending_count",
                          pending_count > 1);
    cJSON_AddBoolToObject(root, "missed_occurrence",
                          missed_occurrence || instance.missed);
    cJSON_AddBoolToObject(root, "privacy_safe_required", false);
    cJSON_AddStringToObject(
        root, "constraints",
        "one_fact_only;one_sentence;no_invented_people_or_consequences;"
        "no_blame_no_anxiety;state_and_actions_are_device_authoritative;"
        "if_pending_count_gt_1_first_announce_multiple_pending_items;"
        "if_missed_occurrence_recap_without_alarm_sound");
    char* json = cJSON_PrintUnformatted(root);
    cJSON_Delete(root);
    if (!json) return;
    Application::GetInstance().SendReminderProtocolMessage(json);
    cJSON_free(json);
}

bool ReminderVoiceService::PlayDownloadedFile(
    const ReminderVoiceAsset& asset, const std::string& instance_id,
    uint32_t voice_revision, const std::string& phase) {
    if (!asset.cached || asset.cache_path.empty() ||
        !IsCurrentCachePath(asset.cache_path) ||
        asset.cache_path != BuildCachePath(instance_id, voice_revision,
                                           asset.phase, asset.sha256)) {
        return false;
    }
    FILE* file = std::fopen(asset.cache_path.c_str(), "rb");
    if (!file) return false;
    std::vector<char> bytes(asset.byte_count);
    const size_t read = std::fread(bytes.data(), 1, bytes.size(), file);
    std::fclose(file);
    if (read != bytes.size()) return false;
    Application::GetInstance().PlaySound(
        std::string_view(bytes.data(), bytes.size()));
    ESP_LOGI(kTag,
             "[REMINDER_VOICE] event=play instance=%s voice_rev=%u "
             "phase=%s source=downloaded",
             instance_id.c_str(), static_cast<unsigned>(voice_revision),
             phase.c_str());
    return true;
}

bool ReminderVoiceService::HasCachedVoice(const ReminderInstance& instance,
                                          const std::string& phase) const {
    for (const auto& asset : instance.voice_assets) {
        if (asset.phase != phase || !asset.cached ||
            asset.cache_path.empty() ||
            asset.voice_revision != instance.voice_revision ||
            !IsCurrentCachePath(asset.cache_path) ||
            asset.cache_path != BuildCachePath(
                instance.instance_id, instance.voice_revision,
                asset.phase, asset.sha256)) {
            continue;
        }
        FILE* file = std::fopen(asset.cache_path.c_str(), "rb");
        if (!file) continue;
        char magic[4] = {};
        const size_t read = std::fread(magic, 1, 4, file);
        std::fclose(file);
        if (read == 4 && magic[0] == 'O' && magic[1] == 'g' &&
            magic[2] == 'g' && magic[3] == 'S') {
            return true;
        }
    }
    return false;
}

bool ReminderVoiceService::PlayCached(const ReminderInstance& instance,
                                      const std::string& phase) {
    for (const auto& asset : instance.voice_assets) {
        if (asset.phase != phase || !asset.cached ||
            asset.cache_path.empty() ||
            asset.voice_revision != instance.voice_revision ||
            !IsCurrentCachePath(asset.cache_path) ||
            asset.cache_path != BuildCachePath(
                instance.instance_id, instance.voice_revision,
                asset.phase, asset.sha256)) {
            continue;
        }
        FILE* file = std::fopen(asset.cache_path.c_str(), "rb");
        if (!file) continue;
        std::vector<char> bytes(asset.byte_count);
        const size_t read = std::fread(bytes.data(), 1, bytes.size(), file);
        std::fclose(file);
        if (read != bytes.size() || read < 4) continue;
        if (bytes[0] != 'O' || bytes[1] != 'g' || bytes[2] != 'g' ||
            bytes[3] != 'S') {
            continue;
        }
        Application::GetInstance().PlaySound(
            std::string_view(bytes.data(), bytes.size()));
        ESP_LOGI(kTag,
                 "[REMINDER_VOICE] event=play instance=%s voice_rev=%u "
                 "phase=%s source=cache bytes=%u",
                 instance.instance_id.c_str(),
                 static_cast<unsigned>(instance.voice_revision), phase.c_str(),
                 static_cast<unsigned>(bytes.size()));
        return true;
    }
    return false;
}

bool ReminderVoiceService::PlayDueLocalOrChime(
    const ReminderInstance& instance, bool allow_chime) {
    if (PlayCached(instance, "due")) {
        return true;
    }
    if (allow_chime) {
        PlayAttention(instance, "due");
    }
    return false;
}

void ReminderVoiceService::PlayAttention(const ReminderInstance& instance,
                                         const std::string& phase) {
    // Local chime only. Due AI audio is the instance cache, not this helper.
    (void)phase;
    ESP_LOGI(kTag,
             "[REMINDER_VOICE] event=play instance=%s voice_rev=%u "
             "phase=%s source=local_fallback priority=%s",
             instance.instance_id.c_str(),
             static_cast<unsigned>(instance.voice_revision), phase.c_str(),
             instance.priority == ReminderPriority::kHigh ? "high" : "normal");
    test_observability::Event("reminder_audio", "local_chime",
                              instance.delivery_presence_generation,
                              "requested",
                              instance.priority == ReminderPriority::kHigh
                                  ? "exclamation" : "popup");
    if (instance.priority == ReminderPriority::kHigh) {
        Application::GetInstance().PlaySound(Lang::Sounds::OGG_EXCLAMATION);
    } else {
        Application::GetInstance().PlaySound(Lang::Sounds::OGG_POPUP);
    }
}

void ReminderVoiceService::PlayFeedback(const ReminderInstance& instance,
                                        const std::string& phase) {
    if (PlayCached(instance, phase)) return;
    Application::GetInstance().PlaySound(Lang::Sounds::OGG_SUCCESS);
}

bool ReminderVoiceService::CacheAssetAsync(
    const std::string& instance_id, uint32_t voice_revision,
    const ReminderVoiceAsset& asset, Completion completion) {
    std::string error;
    if (!ValidateAsset(asset, error)) {
        if (completion) completion(false, asset, error);
        return false;
    }
    static std::once_flag legacy_cleanup_once;
    std::call_once(legacy_cleanup_once, []() {
        CleanupLegacyCacheFiles();
    });
    if (!ReminderCoordinator::GetInstance().CanAcceptVoiceAsset(
            instance_id, voice_revision)) {
        if (completion) {
            completion(false, asset,
                       "voice asset does not match an active instance");
        }
        return false;
    }
    bool expected = false;
    if (!g_download_active.compare_exchange_strong(expected, true)) {
        if (completion) completion(false, asset, "voice cache downloader is busy");
        return false;
    }

    auto* context = new DownloadContext{
        instance_id, voice_revision, asset, std::move(completion)};
    const BaseType_t created = xTaskCreate(
        [](void* argument) {
            std::unique_ptr<DownloadContext> ctx(
                static_cast<DownloadContext*>(argument));
            ReminderVoiceAsset result = ctx->asset;
            bool success = false;
            std::string error_message;

            auto* network = Board::GetInstance().GetNetwork();
            auto http = network ? network->CreateHttp(0) : nullptr;
            if (http) {
                // Signed CDN URLs are device-bound; never log the URL query.
                http->SetHeader("Device-Id",
                                SystemInfo::GetMacAddress().c_str());
            }
            if (!http || !http->Open("GET", result.url)) {
                error_message = "failed to open voice asset URL";
            } else if (http->GetStatusCode() != 200) {
                error_message = "voice asset HTTP status is not 200";
            } else {
                const int body_length = http->GetBodyLength();
                if (body_length < 0 ||
                    static_cast<uint32_t>(body_length) != result.byte_count ||
                    result.byte_count > kMaxAssetBytes) {
                    error_message = "voice asset Content-Length mismatch";
                } else {
                    const std::string temp_path = "/userdata/rvdownload.tmp";
                    FILE* file = std::fopen(temp_path.c_str(), "wb");
                    if (!file) {
                        error_message = "cannot open voice cache file";
                    } else {
                        mbedtls_sha256_context sha;
                        mbedtls_sha256_init(&sha);
                        mbedtls_sha256_starts(&sha, 0);
                        uint32_t total = 0;
                        char buffer[1024];
                        while (total < result.byte_count) {
                            const size_t wanted = std::min<size_t>(
                                sizeof(buffer), result.byte_count - total);
                            const int read = http->Read(buffer, wanted);
                            if (read <= 0 ||
                                std::fwrite(buffer, 1, read, file) !=
                                    static_cast<size_t>(read)) {
                                error_message = "voice asset download failed";
                                break;
                            }
                            mbedtls_sha256_update(
                                &sha,
                                reinterpret_cast<const unsigned char*>(buffer),
                                static_cast<size_t>(read));
                            total += static_cast<uint32_t>(read);
                        }
                        unsigned char digest[32] = {};
                        mbedtls_sha256_finish(&sha, digest);
                        mbedtls_sha256_free(&sha);
                        std::fclose(file);
                        if (error_message.empty() &&
                            total == result.byte_count &&
                            DigestHex(digest) == result.sha256) {
                            FILE* magic_file =
                                std::fopen(temp_path.c_str(), "rb");
                            char ogg[4] = {};
                            const bool ogg_ok =
                                magic_file &&
                                std::fread(ogg, 1, 4, magic_file) == 4 &&
                                ogg[0] == 'O' && ogg[1] == 'g' &&
                                ogg[2] == 'g' && ogg[3] == 'S';
                            if (magic_file) std::fclose(magic_file);
                            if (!ogg_ok) {
                                error_message = "voice asset is not OggS";
                                std::remove(temp_path.c_str());
                            } else if (!ReminderCoordinator::GetInstance().
                                    CanAcceptVoiceAsset(
                                        ctx->instance_id,
                                        ctx->voice_revision)) {
                                error_message =
                                    "voice asset revision became stale";
                                std::remove(temp_path.c_str());
                            } else {
                                const std::string final_path =
                                    BuildCachePath(
                                        ctx->instance_id,
                                        ctx->voice_revision,
                                        result.phase,
                                        result.sha256);
                                struct stat existing = {};
                                const bool already_cached =
                                    stat(final_path.c_str(), &existing) == 0 &&
                                    existing.st_size ==
                                        static_cast<off_t>(
                                            result.byte_count);
                                if (already_cached) {
                                    std::remove(temp_path.c_str());
                                    result.cache_path = final_path;
                                    result.cached = true;
                                    result.voice_revision =
                                        ctx->voice_revision;
                                    success = true;
                                } else {
                                    std::remove(final_path.c_str());
                                    if (std::rename(
                                            temp_path.c_str(),
                                            final_path.c_str()) == 0) {
                                        result.cache_path = final_path;
                                        result.cached = true;
                                        result.voice_revision =
                                            ctx->voice_revision;
                                        success = true;
                                    } else {
                                        error_message =
                                            "cannot commit voice cache file";
                                    }
                                }
                            }
                        } else {
                            if (error_message.empty()) {
                                error_message = "voice asset SHA-256 mismatch";
                            }
                            std::remove(temp_path.c_str());
                        }
                    }
                }
                http->Close();
            }

            auto completion = std::move(ctx->completion);
            g_download_active.store(false);
            Application::GetInstance().Schedule(
                [completion = std::move(completion), success,
                 result = std::move(result),
                 error_message = std::move(error_message)]() mutable {
                    if (completion) {
                        completion(success, result, error_message);
                    }
                });
            vTaskDelete(nullptr);
        },
        "reminder_voice", 6144, context, 2, nullptr);
    if (created != pdPASS) {
        g_download_active.store(false);
        auto failed_completion = std::move(context->completion);
        delete context;
        if (failed_completion) {
            failed_completion(
                false, asset, "cannot create voice cache task");
        }
        return false;
    }
    return true;
}

void ReminderVoiceService::DiscardExpiredCache(
    const std::string& cache_path, const char* reason,
    const std::string& instance_id) {
    if (!cache_path.empty()) {
        std::remove(cache_path.c_str());
    }
    ESP_LOGW(kTag,
             "[REMINDER_VOICE] event=play_discard reason=%s instance=%s",
             reason ? reason : "gate", instance_id.c_str());
}

bool ReminderVoiceService::ClaimImmediatePlay(const ImmediatePlayKey& key) {
    std::lock_guard<std::mutex> lock(immediate_play_mutex_);
    if (has_immediate_play_key_ && last_immediate_play_.Matches(key)) {
        return false;
    }
    last_immediate_play_ = key;
    has_immediate_play_key_ = true;
    return true;
}

bool ReminderVoiceService::EvaluatePlayGate(
    const std::string& instance_id, uint32_t revision,
    uint32_t voice_revision, uint32_t presence_generation,
    const std::string& recipient_person_id, ReminderInstance* current_out,
    const char** reason) const {
    if (Application::GetInstance().GetDeviceState() != kDeviceStateIdle) {
        if (reason) *reason = "device_busy";
        return false;
    }
    ReminderInstance current;
    if (!ReminderCoordinator::GetInstance().GetCurrent(current)) {
        if (reason) *reason = "no_current_card";
        return false;
    }
    if (current.instance_id != instance_id) {
        if (reason) *reason = "card_replaced";
        return false;
    }
    if (current.status != ReminderStatus::kPresenting) {
        if (reason) *reason = "not_presenting";
        return false;
    }
    if (current.revision != revision) {
        if (reason) *reason = "revision_mismatch";
        return false;
    }
    if (current.voice_revision != voice_revision) {
        if (reason) *reason = "voice_revision_mismatch";
        return false;
    }
    if (current.delivery_presence_generation != presence_generation) {
        if (reason) *reason = "presence_generation_mismatch";
        return false;
    }
    if (current.recipient_person_id != recipient_person_id) {
        if (reason) *reason = "identity_mismatch";
        return false;
    }
    auto& presence = PresenceContext::GetInstance();
    if (!presence.IsRadarPresent()) {
        if (reason) *reason = "absence";
        return false;
    }
    if (presence.PresenceGeneration() != presence_generation) {
        if (reason) *reason = "stale_generation";
        return false;
    }
    const bool speaker_matches =
        UserContext::GetInstance().GetCurrentSpeakerUserId() ==
        recipient_person_id;
    if (recipient_person_id != "all" && !speaker_matches &&
        !presence.ConfirmedMatches(recipient_person_id,
                                   presence_generation)) {
        if (reason) *reason = "identity_mismatch";
        return false;
    }
    if (current_out) *current_out = std::move(current);
    if (reason) *reason = nullptr;
    return true;
}

bool ReminderVoiceService::TryPlayAcceptedAssetNow(
    const std::string& instance_id, uint32_t revision,
    uint32_t voice_revision, const std::string& phase,
    uint32_t presence_generation, const std::string& recipient_person_id) {
    const ImmediatePlayKey key{instance_id, revision, voice_revision, phase,
                               presence_generation};

    const char* reason = nullptr;
    ReminderInstance current;
    if (!EvaluatePlayGate(instance_id, revision, voice_revision,
                          presence_generation, recipient_person_id, &current,
                          &reason)) {
        // Presynthesized files must survive until due.  A failed play gate
        // means "not now", not "throw the Ogg away".
        ESP_LOGI(kTag,
                 "[REMINDER_VOICE] event=play_deferred reason=%s instance=%s",
                 reason ? reason : "gate", instance_id.c_str());
        test_observability::Event("reminder_audio", "ai_voice",
                                  presence_generation, "deferred",
                                  reason ? reason : "gate");
        return false;
    }

    const ReminderVoiceAsset* match = nullptr;
    for (const auto& asset : current.voice_assets) {
        if (asset.phase == phase && asset.cached &&
            asset.voice_revision == voice_revision) {
            match = &asset;
            break;
        }
    }
    if (!match) {
        DiscardExpiredCache("", "asset_missing", instance_id);
        return false;
    }

    // Claim after gate so a failed gate never blocks the peer channel.
    if (!ClaimImmediatePlay(key)) {
        ESP_LOGI(kTag,
                 "[REMINDER_VOICE] event=play_discard reason=already_played "
                 "instance=%s voice_rev=%u phase=%s",
                 instance_id.c_str(),
                 static_cast<unsigned>(voice_revision), phase.c_str());
        return false;
    }

    // Copy asset then play outside any coordinator lock (GetCurrent already
    // released its mutex). Application::PlaySound is main-thread safe.
    const ReminderVoiceAsset asset_copy = *match;
    if (!PlayDownloadedFile(asset_copy, instance_id, voice_revision, phase)) {
        {
            std::lock_guard<std::mutex> lock(immediate_play_mutex_);
            if (has_immediate_play_key_ &&
                last_immediate_play_.Matches(key)) {
                has_immediate_play_key_ = false;
            }
        }
        DiscardExpiredCache(asset_copy.cache_path, "play_failed",
                            instance_id);
        test_observability::Event("reminder_audio", "ai_voice",
                                  presence_generation, "failed", "play_failed");
        return false;
    }
    test_observability::Event("reminder_audio", "ai_voice", presence_generation,
                              "requested", "cached_asset");
    return true;
}

bool ReminderVoiceService::AcceptCachedAssetAndMaybePlay(
    const std::string& instance_id, uint32_t revision,
    uint32_t voice_revision, uint32_t presence_generation,
    const std::string& recipient_person_id,
    const ReminderVoiceAsset& cached) {
    if (!ReminderCoordinator::GetInstance().UpdateVoiceAsset(
            instance_id, voice_revision, cached)) {
        DiscardExpiredCache(cached.cache_path, "update_rejected",
                            instance_id);
        return false;
    }
    ESP_LOGI(kTag,
             "[REMINDER_VOICE] event=asset_accepted instance=%s "
             "voice_rev=%u phase=%s",
             instance_id.c_str(), static_cast<unsigned>(voice_revision),
             cached.phase.c_str());
    TryPlayAcceptedAssetNow(instance_id, revision, voice_revision,
                            cached.phase, presence_generation,
                            recipient_person_id);
    return true;
}

bool ReminderVoiceService::HandleIncomingAssetMessage(const cJSON* root) {
    if (!root) return false;
    auto* instance = cJSON_GetObjectItem(root, "instance_id");
    auto* voice_revision = cJSON_GetObjectItem(root, "voice_revision");
    auto* phase = cJSON_GetObjectItem(root, "phase");
    auto* script = cJSON_GetObjectItem(root, "script");
    auto* url = cJSON_GetObjectItem(root, "url");
    auto* sha256 = cJSON_GetObjectItem(root, "sha256");
    auto* format = cJSON_GetObjectItem(root, "format");
    auto* bytes = cJSON_GetObjectItem(root, "bytes");
    if (!(cJSON_IsString(instance) && cJSON_IsNumber(voice_revision) &&
          cJSON_IsString(phase) && cJSON_IsString(script) &&
          script->valuestring && std::strlen(script->valuestring) <= 256 &&
          cJSON_IsString(url) && cJSON_IsString(sha256) &&
          cJSON_IsString(format) && cJSON_IsNumber(bytes) &&
          voice_revision->valuedouble >= 1 &&
          voice_revision->valuedouble <= UINT32_MAX &&
          std::floor(voice_revision->valuedouble) ==
              voice_revision->valuedouble &&
          bytes->valuedouble >= 1 && bytes->valuedouble <= UINT32_MAX &&
          std::floor(bytes->valuedouble) == bytes->valuedouble)) {
        ESP_LOGW(kTag, "Invalid reminder_voice_asset message");
        return false;
    }
    ReminderVoiceAsset asset;
    asset.phase = phase->valuestring;
    asset.script = script->valuestring;
    asset.url = url->valuestring;
    asset.sha256 = sha256->valuestring;
    asset.format = format->valuestring;
    asset.byte_count = static_cast<uint32_t>(bytes->valuedouble);
    const std::string instance_id = instance->valuestring;
    const uint32_t voice_rev =
        static_cast<uint32_t>(voice_revision->valuedouble);

    ReminderInstance live;
    if (!ReminderCoordinator::GetInstance().GetById(instance_id, live) ||
        live.voice_revision != voice_rev) {
        ESP_LOGW(kTag,
                 "[REMINDER_VOICE] event=play_discard "
                 "reason=instance_mismatch");
        return false;
    }
    const uint32_t revision = live.revision;
    const uint32_t presence_generation = live.delivery_presence_generation;
    const std::string recipient = live.recipient_person_id;

    return CacheAssetAsync(
        instance_id, voice_rev, asset,
        [instance_id, voice_rev, revision, presence_generation,
         recipient](bool ok, const ReminderVoiceAsset& cached,
                    const std::string& error) {
            if (!ok) {
                ESP_LOGW(kTag, "Reminder voice cache rejected: %s",
                         error.c_str());
                return;
            }
            ReminderVoiceService::GetInstance().AcceptCachedAssetAndMaybePlay(
                instance_id, revision, voice_rev, presence_generation,
                recipient, cached);
        });
}

void ReminderVoiceService::HandleIncomingErrorMessage(const cJSON* root) {
    if (!root) return;
    auto* code = cJSON_GetObjectItem(root, "code");
    const char* code_str =
        (cJSON_IsString(code) && code->valuestring) ? code->valuestring
                                                    : "error";
    ESP_LOGW(kTag, "[REMINDER_VOICE] event=voice_error code=%s", code_str);
}
