
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
struct PhotoTask { std::string question; std::function<void(ReturnValue)> done; };
std::atomic<bool> photo_task_busy{false};
void PhotoTaskEntry(void* arg) {
    std::unique_ptr<PhotoTask> task(static_cast<PhotoTask*>(arg));
    const auto started = xTaskGetTickCount();
    try {
        const std::string question = task->question;
        auto run = [&]() -> ReturnValue {
            auto& mgr = CameraManager::GetInstance();

            ESP_LOGI("CameraTools", "[CAMERA] Explicit user request: capturing a frame for VLM upload");

            if (!VisionCredentialStore::GetInstance().IsExplainReady()) {
                ESP_LOGW("CameraMCP", "event=explain_rejected reason=%s",
                         VisionCredentialStore::GetInstance().ExplainNotReadyReason().c_str());
                return McpError{"视觉服务尚未就绪，请稍后再试", "vision_" + VisionCredentialStore::GetInstance().ExplainNotReadyReason()};
            }

            if (mgr.IsPreviewActive()) {
                auto jpeg = mgr.GetLastFrame();
                if (jpeg.empty()) {
                    throw std::runtime_error("暂无可用帧，请稍后再试");
                }
                Camera* cam = mgr.GetCamera();
                if (!cam) throw std::runtime_error("摄像头对象不可用");
                try {
                    return cam->Explain(question, jpeg);
                } catch (const std::exception& e) {
                    const std::string msg = e.what();
                    if (msg.rfind("vision_not_ready", 0) == 0) {
                        return McpError{"视觉服务尚未就绪，请稍后再试", "vision_" + VisionCredentialStore::GetInstance().ExplainNotReadyReason()};
                    }
                    if (msg.rfind("vision_http_", 0) == 0) {
                        const auto colon = msg.find(':');
                        const std::string code = colon == std::string::npos
                                                     ? "vision_http_error"
                                                     : msg.substr(0, colon);
                        const std::string text = colon == std::string::npos
                                                     ? msg
                                                     : msg.substr(colon + 2);
                        return McpError{text, code};
                    }
                    throw;
                }
            }

            if (!mgr.TryAcquire()) {
                throw std::runtime_error("摄像头正忙，请稍后再试");
            }
            struct CameraReleaseGuard {
                CameraManager& manager;
                ~CameraReleaseGuard() { manager.Release(); }
            } release_guard{mgr};

            if (!mgr.GetCamera()->Capture()) throw std::runtime_error("拍照失败");
            try {
                return mgr.GetCamera()->Explain(question);
            } catch (const std::exception& e) {
                const std::string msg = e.what();
                if (msg.rfind("vision_not_ready", 0) == 0) {
                    return McpError{"视觉服务尚未就绪，请稍后再试", "vision_" + VisionCredentialStore::GetInstance().ExplainNotReadyReason()};
                }
                if (msg.rfind("vision_http_", 0) == 0) {
                    const auto colon = msg.find(':');
                    const std::string code = colon == std::string::npos
                                                 ? "vision_http_error"
                                                 : msg.substr(0, colon);
                    const std::string text = colon == std::string::npos
                                                 ? msg
                                                 : msg.substr(colon + 2);
                    return McpError{text, code};
                }
                throw;
            }
        };
        task->done(run());
    } catch (const std::bad_alloc&) {
        task->done(McpError{"照片内存不足，请稍后重试", "resource_exhausted"});
    } catch (const std::exception& e) {
        ESP_LOGW("CameraTools", "event=photo_failed reason=%s", e.what());
        task->done(McpError{"拍照或上传失败，请再试一次", "capture_or_upload_failed"});
    }
    ESP_LOGI("CameraTools", "event=photo_finished elapsed_ms=%u",
        static_cast<unsigned>((xTaskGetTickCount()-started)*portTICK_PERIOD_MS));
    task.reset(); photo_task_busy.store(false);
    vTaskDeleteWithCaps(nullptr);
}
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
