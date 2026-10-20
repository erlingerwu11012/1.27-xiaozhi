
#include <string>
#include <mutex>
#include <cassert>
#include <utility>
#define ESP_LOGI(...) ((void)0)
#define vTaskDelay(...) ((void)0)
#define pdMS_TO_TICKS(x) (x)
namespace task_diag {void LogMemoryStage(const char*,const char*){}}
struct FaceEnrollmentClient {struct SessionInfo {std::string session_id;};};
struct FaceEnrollmentManager {
 enum class State {kIdle,kFailed,kCancelled,kExpired,kPoseFailed,kDraftReady};
 struct StatusSnapshot {State state,terminal_state;int accepted_count,required_frames,attempted_frames;std::string last_error_code,operation_id;};
 struct FinishPlan {State terminal;bool keep_draft_ready=false,release_camera=false,need_cleanup=false;FaceEnrollmentClient::SessionInfo cleanup_session;const char* hint=nullptr;int hint_ms=0;};
 mutable std::mutex mutex_;State state_=State::kIdle,terminal_state_=State::kIdle;
 int accepted_count_=0,required_frames_=3,attempted_frames_=0;std::string last_error_code_,operation_id_="test-operation";
 bool camera_held_=true,cleanup_scheduled_=false,guided_v2_active_=true,stop_requested_=true;
 void* worker_=nullptr;FaceEnrollmentClient::SessionInfo session_{"test-session"};
 StatusSnapshot GetStatus()const;FinishPlan BuildFinishPlanLocked(State);void FinishOutsideLock(FinishPlan);
 void ClearSessionSecretsLocked(){session_.session_id.clear();}
 void ReleaseCameraOutsideLock(bool){} void ScheduleAsyncCleanup(FaceEnrollmentClient::SessionInfo){}
 void ShowHint(const char*,int){} const char* StateName(State)const{return "test";}
};
FaceEnrollmentManager::StatusSnapshot FaceEnrollmentManager::GetStatus()
    const {
    std::lock_guard<std::mutex> lock(mutex_);
    StatusSnapshot snap;
    snap.state = state_;
    snap.accepted_count = accepted_count_;
    snap.required_frames = required_frames_;
    snap.attempted_frames = attempted_frames_;
    snap.last_error_code = last_error_code_;
    snap.operation_id = operation_id_;
    snap.terminal_state = terminal_state_;
    return snap;
}
FaceEnrollmentManager::FinishPlan FaceEnrollmentManager::BuildFinishPlanLocked(
    State terminal) {
    FinishPlan plan;
    plan.terminal = terminal;
    terminal_state_ = terminal;
    plan.keep_draft_ready = (terminal == State::kDraftReady);
    plan.release_camera = camera_held_;
    camera_held_ = false;
    if (terminal != State::kDraftReady && !session_.session_id.empty() &&
        !cleanup_scheduled_) {
        plan.cleanup_session = session_;
        plan.need_cleanup = true;
    } else if (terminal != State::kDraftReady && cleanup_scheduled_) {
        // Cleanup already queued by Cancel()/capability clear.
        plan.need_cleanup = false;
    }
    ClearSessionSecretsLocked();
    guided_v2_active_ = false;
    if (state_ != State::kDraftReady) {
        state_ = terminal;
    }
    worker_ = nullptr;
    // Keep stop_requested_ true until idle transition so late callbacks drop.
    ESP_LOGI(kTag,
             "[FACE_ENROLL] event=session_end state=%s accepted=%d code=%s",
             StateName(state_), accepted_count_,
             last_error_code_.empty() ? "-" : last_error_code_.c_str());
    return plan;
}
void FaceEnrollmentManager::FinishOutsideLock(FinishPlan plan) {
    ReleaseCameraOutsideLock(plan.release_camera);
    if (plan.need_cleanup) {
        ScheduleAsyncCleanup(std::move(plan.cleanup_session));
    }
    if (plan.hint) ShowHint(plan.hint, plan.hint_ms);
    vTaskDelay(pdMS_TO_TICKS(50));
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!plan.keep_draft_ready &&
            (state_ == State::kCancelled || state_ == State::kExpired ||
             state_ == State::kFailed || state_ == State::kPoseFailed)) {
            state_ = State::kIdle;
            stop_requested_ = false;
        }
    }
    const char* phase = "session_end";
    if (plan.terminal == State::kCancelled) phase = "session_cancel_end";
    else if (plan.terminal == State::kFailed ||
             plan.terminal == State::kExpired ||
             plan.terminal == State::kPoseFailed) {
        phase = "session_fail_end";
    }
    task_diag::LogMemoryStage("face_enroll", phase);
}
int main(){
 using S=FaceEnrollmentManager::State;
 for(auto state:{S::kFailed,S::kCancelled,S::kExpired,S::kPoseFailed}) {
  FaceEnrollmentManager m;m.last_error_code_="injected_http_or_usb_failure";
  auto plan=m.BuildFinishPlanLocked(state);assert(plan.release_camera && plan.need_cleanup);
  m.FinishOutsideLock(plan);auto status=m.GetStatus();
  assert(status.state==S::kIdle && status.terminal_state==state);
  assert(status.last_error_code=="injected_http_or_usb_failure" && status.operation_id=="test-operation");
 }
 FaceEnrollmentManager draft;draft.state_=S::kDraftReady;
 auto plan=draft.BuildFinishPlanLocked(S::kDraftReady);draft.FinishOutsideLock(plan);
 assert(draft.GetStatus().state==S::kDraftReady && draft.GetStatus().terminal_state==S::kDraftReady);
}
