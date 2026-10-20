
#include <cassert>
#include <string>
#include <mutex>
#include <functional>
#include <iostream>
#include <utility>
#define ESP_LOGW(...) ((void)0)
using SpineOtaStatusCallback=std::function<void()>;
class SpineOta {public:
 mutable std::mutex mutex_;bool running_=false;int last_reported_progress_=0;long last_report_us_=0;SpineOtaStatusCallback status_cb_;
 static SpineOta& GetInstance(){static SpineOta s;return s;}
 bool TryAcquire(SpineOtaStatusCallback);void Release();bool IsRunning()const;
};
std::mutex g_visual_ota_mutex;bool g_visual_ota_running=false;
enum {kDeviceStateIdle,kDeviceStateUpgrading,kDeviceStateActivating,kDeviceStateStarting,kDeviceStateWifiConfiguring};
struct Task{std::string task_id="task",pack_id="pack";};
std::string failure;bool reached=false;int device_state_=kDeviceStateIdle;
void send_status(const std::string&,const std::string&,const char*,int,const char*,bool,const char* reason){failure=reason;}
bool SpineOta::TryAcquire(SpineOtaStatusCallback cb) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        return false;
    }
    running_ = true;
    last_reported_progress_ = -1;
    last_report_us_ = 0;
    status_cb_ = std::move(cb);
    return true;
}
void SpineOta::Release() {
    std::lock_guard<std::mutex> lock(mutex_);
    running_ = false;
    status_cb_ = nullptr;
    last_reported_progress_ = -1;
}
bool SpineOta::IsRunning() const {
    std::lock_guard<std::mutex> lock(mutex_);
    return running_;
}
bool TryAcquireVisualOta() {
    std::lock_guard<std::mutex> lock(g_visual_ota_mutex);
    if (g_visual_ota_running) return false;
    g_visual_ota_running = true;
    return true;
}
void ReleaseVisualOta() {
    std::lock_guard<std::mutex> lock(g_visual_ota_mutex);
    g_visual_ota_running = false;
}void entry(bool fail_after_acquire=false){Task task;SpineOtaStatusCallback status_cb=[]{};
    // Reject before acquire if another upgrade/activation path is active.
    if (device_state_ == kDeviceStateUpgrading ||
        device_state_ == kDeviceStateActivating ||
        device_state_ == kDeviceStateStarting ||
        device_state_ == kDeviceStateWifiConfiguring) {
        ESP_LOGW(TAG, "update_spine rejected pre-acquire: E_BUSY state=%d",
                 static_cast<int>(device_state_));
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "device_state_ineligible");
        return;
    }

    // Atomic acquire BEFORE any security precheck / audio stop / UI / state changes.
    if (!SpineOta::GetInstance().TryAcquire(status_cb)) {
        ESP_LOGW(TAG, "update_spine rejected: E_BUSY (running)");
        // Do not touch audio, UI, callback, or device state of the in-flight task.
        // E_BUSY did not acquire — must not Release.
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "spine_task_running");
        return;
    }
    if (!TryAcquireVisualOta()) {
        // The per-feature lock succeeded, but wallpaper holds the shared flash
        // writer. Undo this partial acquire before reporting E_BUSY.
        SpineOta::GetInstance().Release();
        ESP_LOGW(TAG, "update_spine rejected: E_BUSY (wallpaper OTA running)");
        send_status(task.task_id, task.pack_id, "failed", 0, "E_BUSY", false, "wallpaper_resource_lock");
        return;
    }

    // Hold running=true until success reboot or failure cleanup finishes.
    // RunTask must not Release. If Reboot() unexpectedly returns, destructor frees the lock.
    struct SpineOtaRunGuard {
        bool armed = true;
        ~SpineOtaRunGuard() {
            if (armed) {
                SpineOta::GetInstance().Release();
                ReleaseVisualOta();
            }
        }
    } run_guard;

if(fail_after_acquire)return;reached=true;
}

void reset(){SpineOta::GetInstance().Release();ReleaseVisualOta();failure.clear();reached=false;device_state_=kDeviceStateIdle;}
int main(){
 reset();assert(SpineOta::GetInstance().TryAcquire([]{}));entry();assert(failure=="spine_task_running" && SpineOta::GetInstance().IsRunning());
 reset();assert(TryAcquireVisualOta());entry();assert(failure=="wallpaper_resource_lock" && !SpineOta::GetInstance().IsRunning() && g_visual_ota_running);
 reset();entry();assert(reached && !SpineOta::GetInstance().IsRunning() && !g_visual_ota_running);
 reset();entry(true);assert(!reached && !SpineOta::GetInstance().IsRunning() && !g_visual_ota_running);
 for(int state:{kDeviceStateUpgrading,kDeviceStateActivating,kDeviceStateStarting,kDeviceStateWifiConfiguring}){reset();device_state_=state;entry();assert(failure=="device_state_ineligible" && !SpineOta::GetInstance().IsRunning() && !g_visual_ota_running);}
 reset();assert(SpineOta::GetInstance().TryAcquire([]{}));assert(!SpineOta::GetInstance().TryAcquire([]{}));SpineOta::GetInstance().Release();assert(SpineOta::GetInstance().TryAcquire([]{}));reset();
 std::cout<<"OTA production lock branches: 9 scenarios passed\n";
}
