#ifndef SPINE_OTA_H
#define SPINE_OTA_H

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

#include <cJSON.h>
#include <esp_partition.h>

// The online role slot is 4 MiB. Keep the protocol limit equal to the slot so
// high-fidelity roles are not artificially capped by the old A/B layout.
constexpr size_t kSpineOtaMaxBytes = 4 * 1024 * 1024;

enum class SpineOtaError {
    kNone = 0,
    kBusy,
    kUrlDenied,
    kRoleUnknown,
    kSize,
    kSha,
    kSig,
    kMinFw,
    kFlash,
    kNetwork,
    kBundle,
    kRuntimeMismatch,
    kUnsupported,
    kNvs,
    kTaskMismatch,
};

enum class SpineOtaPhase {
    kIdle,
    kWaiting,
    kDownloading,
    kVerifying,
    kApplying,
    kSuccess,
    kFailed,
};

struct SpineOtaTask {
    std::string task_id;
    std::string pack_id;
    std::string role_id;
    std::string version;
    uint32_t size = 0;
    std::string sha256;
    std::string signature;
    std::string url;
    std::string min_fw;
};

using SpineOtaStatusCallback =
    std::function<void(SpineOtaPhase phase, int progress, SpineOtaError error,
                       const std::string& task_id, const std::string& pack_id)>;

const char* SpineOtaErrorToString(SpineOtaError err);
const char* SpineOtaPhaseToString(SpineOtaPhase phase);

// Parse https URL for update_spine. Rejects ports/IP/userinfo/fragment.
// On success: host_lower, path_no_query, signed_origin_path =
//   "https://<host_lower><path_no_query>"
bool SpineOtaParseHttpsUrl(const std::string& url,
                           std::string& host_lower,
                           std::string& path_no_query,
                           std::string& signed_origin_path);

bool SpineOtaRoleIdAllowed(const std::string& role_id, const char* allow_list);

class SpineOta {
public:
    static SpineOta& GetInstance() {
        static SpineOta instance;
        return instance;
    }

    // Atomically claim execution. Sets status callback only on success.
    // Must be called BEFORE stopping audio / changing device state.
    bool TryAcquire(SpineOtaStatusCallback cb);

    // Release running mark. Owned by Application after TryAcquire succeeds.
    // Safe to call multiple times. RunTask must NOT call this.
    void Release();

    static bool ParseTask(const cJSON* root, SpineOtaTask& out, SpineOtaError& err);
    static SpineOtaError Precheck(const SpineOtaTask& task, std::string* detail);

    // Caller must have successfully TryAcquire()'d. Does NOT touch audio or Release().
    // Returns true only after NVS commit of the single dynamic role succeeds; caller keeps the lock
    // until reboot (success) or audio/UI/state cleanup completes (failure).
    bool RunTask(const SpineOtaTask& task);

    bool IsRunning() const;

private:
    SpineOta() = default;

    void Report(SpineOtaPhase phase, int progress, SpineOtaError error,
                const std::string& task_id, const std::string& pack_id);

    bool DownloadToPartition(const SpineOtaTask& task,
                             const esp_partition_t* part,
                             SpineOtaError& err);

    mutable std::mutex mutex_;
    bool running_ = false;
    SpineOtaStatusCallback status_cb_;
    int last_reported_progress_ = -1;
    int64_t last_report_us_ = 0;
};

#endif
