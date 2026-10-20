#ifndef WALLPAPER_OTA_H
#define WALLPAPER_OTA_H

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

#include <cJSON.h>
#include <esp_partition.h>

constexpr size_t kWallpaperOtaMaxBytes = 2 * 1024 * 1024;

enum class WallpaperOtaError {
    kNone = 0,
    kBusy,
    kUrlDenied,
    kPackUnknown,
    kSize,
    kSha,
    kSig,
    kMinFw,
    kFlash,
    kNetwork,
    kBundle,
    kNvs,
};

enum class WallpaperOtaPhase {
    kIdle,
    kWaiting,
    kDownloading,
    kVerifying,
    kApplying,
    kSuccess,
    kFailed,
};

struct WallpaperOtaTask {
    std::string task_id;
    std::string pack_id;
    std::string version;
    uint32_t size = 0;
    std::string sha256;
    std::string signature;
    std::string url;
    std::string min_fw;
};

using WallpaperOtaStatusCallback =
    std::function<void(WallpaperOtaPhase phase, int progress, WallpaperOtaError error,
                       const std::string& task_id, const std::string& pack_id)>;

const char* WallpaperOtaErrorToString(WallpaperOtaError err);
const char* WallpaperOtaPhaseToString(WallpaperOtaPhase phase);

class WallpaperOta {
public:
    static WallpaperOta& GetInstance() {
        static WallpaperOta instance;
        return instance;
    }

    bool TryAcquire(WallpaperOtaStatusCallback cb);
    void Release();
    bool IsRunning() const;

    static bool ParseTask(const cJSON* root, WallpaperOtaTask& out,
                          WallpaperOtaError& error);
    static WallpaperOtaError Precheck(const WallpaperOtaTask& task,
                                      std::string* detail);

    // Caller owns TryAcquire/Release and performs the UI/audio lifecycle.
    bool RunTask(const WallpaperOtaTask& task);

private:
    WallpaperOta() = default;
    void Report(WallpaperOtaPhase phase, int progress, WallpaperOtaError error,
                const std::string& task_id, const std::string& pack_id);
    bool DownloadToPartition(const WallpaperOtaTask& task,
                             const esp_partition_t* partition,
                             WallpaperOtaError& error);
    static bool Commit(const WallpaperOtaTask& task, std::string* detail);

    mutable std::mutex mutex_;
    bool running_ = false;
    WallpaperOtaStatusCallback status_cb_;
    int last_reported_progress_ = -1;
    int64_t last_report_us_ = 0;
};

#endif
