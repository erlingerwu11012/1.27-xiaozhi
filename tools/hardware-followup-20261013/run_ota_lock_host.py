"""Compile actual firmware acquire/release and HandleUpdateSpine lock branches."""
from pathlib import Path
import sys,subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_ws_audio_send_host_test import ROOT,function
s=Path(__file__).parent
app=(ROOT/'main/application.cc').read_text(encoding='utf-8')
start=app.index('    // Atomic acquire BEFORE any security precheck')
end=app.index('    // Full security precheck',start)
gate=app[start:end]
start=app.index('    // Reject before acquire if another upgrade/activation path is active.')
end=app.index('    auto display = Board::GetInstance().GetDisplay();',start)
pre=app[start:end]
prefix=r'''
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
'''
body='\n'.join(function('main/spine_ota.cc',x) for x in ['bool SpineOta::TryAcquire(', 'void SpineOta::Release(', 'bool SpineOta::IsRunning('])+'\n'+function('main/application.cc','bool TryAcquireVisualOta(')+'\n'+function('main/application.cc','void ReleaseVisualOta(')
entry='void entry(bool fail_after_acquire=false){Task task;SpineOtaStatusCallback status_cb=[]{};\n'+pre+gate+'if(fail_after_acquire)return;reached=true;\n}\n'
tail=r'''
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
'''
out=s/'ota_lock_host_generated.cpp';out.write_text(prefix+body+entry+tail,encoding='utf-8');binary=s/'ota-lock-host'
subprocess.run(['g++','-std=c++17','-pthread','-fsanitize=address,undefined','-fno-sanitize-recover=all',str(out),'-o',str(binary)],check=True)
subprocess.run([str(binary)],check=True)
