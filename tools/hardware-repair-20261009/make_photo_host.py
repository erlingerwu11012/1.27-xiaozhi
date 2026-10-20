from pathlib import Path
R=Path('tools/hardware-repair-20261009');src=Path('main/mcp_tools/mcp_tools_camera.cc').read_text(encoding='utf-8-sig');start=src.index('struct PhotoTask {');end=src.index('\n}\n\nvoid RegisterCameraCommonTools',start);worker=src[start:end]
prefix=r'''
#include <atomic>
#include <thread>
#include <chrono>
#include <string>
#include <vector>
#include <variant>
#include <memory>
#include <functional>
#include <cassert>
#include <iostream>
#include <stdexcept>
struct McpError {std::string message,code;};
using ReturnValue=std::variant<std::string,McpError>;
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define portTICK_PERIOD_MS 1
inline unsigned xTaskGetTickCount(){return 1;}
inline void vTaskDeleteWithCaps(void*){}
struct Camera {bool capture=true;std::string error;bool Capture(){return capture;}std::string Explain(const std::string&,const std::vector<unsigned char>& ={}){std::this_thread::sleep_for(std::chrono::milliseconds(180));if(!error.empty())throw std::runtime_error(error);return "blue cup";}};
struct CameraManager {Camera camera;bool preview=false,acquire=true,released=false;static CameraManager& GetInstance(){static CameraManager x;return x;}bool IsPreviewActive(){return preview;}bool TryAcquire(){return acquire;}void Release(){released=true;}Camera* GetCamera(){return &camera;}std::vector<unsigned char> GetLastFrame(){return {1,2};}};
struct VisionCredentialStore {bool ready=true;static VisionCredentialStore& GetInstance(){static VisionCredentialStore x;return x;}bool IsExplainReady(){return ready;}std::string ExplainNotReadyReason(){return "awaiting_initialize";}};
'''
tail=r'''
int main(){
 auto& mgr=CameraManager::GetInstance();auto& cred=VisionCredentialStore::GetInstance();
 for(int scenario=0;scenario<6;scenario++){
 mgr=CameraManager{};cred.ready=true;photo_task_busy=true;std::atomic<bool> finished=false;int callbacks=0;ReturnValue result;
 if(scenario==1)cred.ready=false;
 if(scenario==2)mgr.camera.capture=false;
 if(scenario==3)mgr.camera.error="vision_http_401: unauthorized";
 if(scenario==4)mgr.preview=true;
 if(scenario==5)mgr.acquire=false;
 auto* task=new PhotoTask{"identify",[&](ReturnValue x){result=std::move(x);callbacks++;finished=true;}};
 std::thread worker([&]{PhotoTaskEntry(task);});int audio_ticks=0;
 while(!finished){std::this_thread::sleep_for(std::chrono::milliseconds(5));audio_ticks++;}
 worker.join();assert(callbacks==1 && !photo_task_busy.load());
 if(scenario==0 || scenario==4){assert(std::get<std::string>(result)=="blue cup");assert(audio_ticks>=20);}
 if(scenario==1)assert(std::get<McpError>(result).code=="vision_awaiting_initialize");
 if(scenario==2)assert(std::get<McpError>(result).code=="capture_or_upload_failed" && mgr.released);
 if(scenario==3)assert(std::get<McpError>(result).code=="vision_http_401" && mgr.released);
 if(scenario==5)assert(std::get<McpError>(result).code=="capture_or_upload_failed");
 std::cout<<"PASS "<<scenario<<" audio_ticks="<<audio_ticks<<"\n";
 }
}
'''
(R/'photo-worker-host.cpp').write_text(prefix+worker+tail,encoding='utf-8')
