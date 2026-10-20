#include "mcp_tools.h"
#include "mcp_server.h"
#include "board.h"
#include "application.h"
#include "boards/esp-box-3/camera_manager.h"
#include "boards/common/esp32_camera.h"
#include "boards/esp-box-3/config.h"
#include "face_enrollment_manager.h"
#include "vision_credentials.h"
#include <freertos/FreeRTOS.h>
#include <freertos/idf_additions.h>
#include <freertos/task.h>
#include <esp_log.h>
#include <atomic>
#include <cstdio>
#include <memory>
#include <functional>
#include <string>
#include <cJSON.h>
#include <esp_heap_caps.h>
#include <vector>

#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)
namespace {
struct IdentifyPersonTask {
    std::function<void(ReturnValue)> done;
};

std::atomic<uint32_t> g_identity_request_generation{0};

cJSON* IdentityJson(const IdentityResult& result, bool confirmed) {
    cJSON* json = cJSON_CreateObject();
    cJSON_AddStringToObject(json, "status", result.status.empty() ? "error" : result.status.c_str());
    cJSON_AddBoolToObject(json, "confirmed", confirmed);
    if (confirmed) {
        cJSON_AddStringToObject(json, "user_id", result.user_id.c_str());
        cJSON_AddStringToObject(json, "display_name", result.display_name.c_str());
        cJSON_AddNumberToObject(json, "confidence", result.confidence);
    }
    if (result.http_status > 0) {
        cJSON_AddNumberToObject(json, "http_status", result.http_status);
    }
    const std::string& reason = !result.server_reason.empty()
                                    ? result.server_reason
                                    : result.error_reason;
    if (!reason.empty()) {
        cJSON_AddStringToObject(json, "reason", reason.c_str());
    }
    return json;
}

void IdentifyPersonTaskEntry(void* arg) {
    std::unique_ptr<IdentifyPersonTask> task(static_cast<IdentifyPersonTask*>(arg));
    auto run = [&]() {
        auto finish = [&](ReturnValue value) { task->done(std::move(value)); };
        auto& manager = CameraManager::GetInstance();
        const uint32_t request_generation =
            g_identity_request_generation.fetch_add(1, std::memory_order_acq_rel) + 1;
        if (!IdentityClient::GetInstance().HasIdentityEndpoint()) {
            finish(McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"});
            return;
        }
        if (manager.IsPreviewActive() || !manager.TryAcquire()) {
            finish(McpError{"摄像头正忙，请稍后再试", "camera_busy"});
            return;
        }
        struct ReleaseGuard {
            CameraManager& manager;
            bool active = true;
            ~ReleaseGuard() { if (active) manager.Release(); }
        } release{manager};
        auto* camera = dynamic_cast<Esp32Camera*>(manager.GetCamera());
        if (!camera) {
            release.active = false;
            manager.Release();
            finish(McpError{"摄像头不可用", "camera_unavailable"});
            return;
        }

        IdentityResult first, second;
        bool first_captured = camera->Capture();
        if (first_captured) {
            first = camera->IdentifyFace(camera->GetLastJpeg(),
                                         request_generation);
        }
        vTaskDelay(pdMS_TO_TICKS(120));
        bool second_captured = camera->Capture();
        if (second_captured) {
            second = camera->IdentifyFace(camera->GetLastJpeg(),
                                          request_generation);
        }

        const IdentityResult* winner = nullptr;
        if (first.IsKnownPerson() && second.IsKnownPerson()) {
            if (first.user_id != second.user_id) {
                first.status = "ambiguous";
                first.error_reason = "different_users";
                release.active = false;
                manager.Release();
                finish(IdentityJson(first, false));
                return;
            }
            winner = first.confidence >= second.confidence ? &first : &second;
        } else if (first.IsKnownPerson()) {
            winner = &first;
        } else if (second.IsKnownPerson()) {
            winner = &second;
        }
        release.active = false;
        manager.Release();
        if (winner) {
            finish(IdentityJson(*winner, true));
        } else if (!first_captured && !second_captured) {
            finish(McpError{"拍照失败，请稍后再试", "capture_failed"});
        } else {
            const IdentityResult& observed = second.status.empty() ? first : second;
            if (observed.status == "error") {
                if (observed.error_reason == "vision_not_ready") {
                    finish(McpError{"视觉服务尚未就绪，请稍后再试",
                                    "vision_not_ready"});
                } else {
                const std::string code =
                    observed.http_status > 0
                        ? "identity_http_" + std::to_string(observed.http_status)
                        : (observed.error_reason.empty() ? "identity_error"
                                                         : observed.error_reason);
                const std::string message =
                    observed.http_status > 0
                        ? "人脸识别服务返回 HTTP " +
                              std::to_string(observed.http_status)
                        : "人脸识别失败，请稍后再试";
                finish(McpError{message, code});
                }
            } else if (observed.http_status > 0 && observed.http_status != 200) {
                finish(McpError{
                    "人脸识别服务返回 HTTP " + std::to_string(observed.http_status),
                    "identity_http_" + std::to_string(observed.http_status)});
            } else {
                finish(IdentityJson(observed, false));
            }
        }
    };
    try {
        run();
    } catch (const std::bad_alloc&) {
        ESP_LOGE("McpCamera", "[PHOTO_PSRAM] identification stopped: insufficient image memory");
        task->done(McpError{"照片内存不足，请稍后重试", "resource_exhausted"});
    }
    task.reset();
    vTaskDeleteWithCaps(nullptr);
}
}  // namespace
#endif

void RegisterCameraCommonTools(McpServer& server) {
    // 拍照识物
    server.AddTool("self.camera.take_photo",
        "仅在用户明确要求拍一张静态照片并识别画面内容时调用；当前不提供实时预览，此工具只拍摄一帧并上传识别。",
        PropertyList({Property("question", kPropertyTypeString)}),
        [](const PropertyList& p) -> ReturnValue {
            auto& mgr = CameraManager::GetInstance();
            std::string question = p["question"].value<std::string>();
            ESP_LOGI("CameraTools", "[CAMERA] Explicit user request: capturing a frame for VLM upload");

            if (!VisionCredentialStore::GetInstance().IsExplainReady()) {
                return McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"};
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
                        return McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"};
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
            TaskPriorityReset priority_reset(1);
            if (!mgr.GetCamera()->Capture()) throw std::runtime_error("拍照失败");
            try {
                return mgr.GetCamera()->Explain(question);
            } catch (const std::exception& e) {
                const std::string msg = e.what();
                if (msg.rfind("vision_not_ready", 0) == 0) {
                    return McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"};
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
        });

#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)
    server.AddAsyncTool(
        "self.camera.identify_person",
        "当用户问“我是谁”“认出我”“看看我是不是某某”时调用。拍摄两帧并分别与已录入人脸库比对；两帧中任一帧识别到用户即可确认。只返回本次认人结果，不设置当前用户，不替代声纹身份。普通识物请使用 self.camera.take_photo。",
        PropertyList(),
        [](const PropertyList&, std::function<void(ReturnValue)> done) {
            auto* task = new IdentifyPersonTask{done};
            const BaseType_t created = xTaskCreateWithCaps(
                IdentifyPersonTaskEntry, "mcp_identify", 12288, task, 3,
                nullptr, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            ESP_LOGI("CameraTools",
                     "[FACE_TASK] event=create task=mcp_identify stack_bytes=12288 "
                     "caps=psram|8bit result=%s internal_free=%u "
                     "internal_largest=%u psram_free=%u psram_largest=%u",
                     created == pdPASS ? "ok" : "failed",
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_INTERNAL),
                     (unsigned)heap_caps_get_free_size(MALLOC_CAP_SPIRAM),
                     (unsigned)heap_caps_get_largest_free_block(MALLOC_CAP_SPIRAM));
            if (created != pdPASS) {
                delete task;
                done(McpError{"无法启动认人任务", "resource_exhausted"});
            }
        });
#endif
}

void RegisterCameraUserTools(McpServer& server) {
#if defined(CONFIG_USE_USB_STREAM) || defined(CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE)

    server.AddUserOnlyTool(
        "camera.face.enroll.start",
        "当用户明确说“录入人脸 / 登记人脸 / 添加人脸”时调用。启动设备端人脸采集；"
        "不接收姓名参数，采集完成后提示用户到网页填写姓名。不要在雷达自动识别或提醒验证时调用。",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            const auto result = FaceEnrollmentManager::GetInstance().StartDetailed();
            if (!result.accepted) {
                return McpError{result.message,
                                result.code.empty() ? "enrollment_failed"
                                                    : result.code};
            }
            return result.message;
        });

    server.AddUserOnlyTool(
        "camera.face.enroll.cancel",
        "当用户说“取消录入人脸”或要求停止人脸采集时调用。可在创建、拍照、上传、等待状态中立即安全停止。",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            return FaceEnrollmentManager::GetInstance().Cancel();
        });

    server.AddUserOnlyTool(
        "camera.face.enroll.status",
        "查询当前人脸录入采集状态与有效帧数。不返回 session、token、图片或姓名。",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            auto snap = FaceEnrollmentManager::GetInstance().GetStatus();
            char buf[128];
            std::snprintf(
                buf, sizeof(buf),
                "{\"state\":\"%s\",\"accepted_count\":%d,\"required_frames\":%d}",
                FaceEnrollmentManager::StateName(snap.state),
                snap.accepted_count, snap.required_frames);
            return std::string(buf);
        });

#endif  // CONFIG_USE_USB_STREAM || CONFIG_ESP_VIDEO_ENABLE_USB_UVC_VIDEO_DEVICE
}
