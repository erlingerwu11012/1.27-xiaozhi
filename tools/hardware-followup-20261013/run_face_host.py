from pathlib import Path
import sys,subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_ws_audio_send_host_test import ROOT,function
s=Path(__file__).parent
out=s/'face_host_generated.cpp'
prefix=r'''
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
'''
body='\n'.join(function('main/face_enrollment_manager.cc',sig) for sig in ['FaceEnrollmentManager::StatusSnapshot FaceEnrollmentManager::GetStatus(', 'FaceEnrollmentManager::FinishPlan FaceEnrollmentManager::BuildFinishPlanLocked(', 'void FaceEnrollmentManager::FinishOutsideLock('])
tail=r'''
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
'''
out.write_text(prefix+body+tail)
subprocess.run(['g++','-std=c++17','-pthread','-fsanitize=address,undefined',str(out),'-o',str(s/'face_host')],check=True)
subprocess.run([str(s/'face_host')],check=True)
print('face_terminal_scenarios_passed 5')
