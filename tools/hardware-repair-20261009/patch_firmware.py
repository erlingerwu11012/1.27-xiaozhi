from pathlib import Path
R=Path(r'E:/github/github_code/all/4.30')
def edit(f,old,new):
 p=R/f;s=p.read_text(encoding='utf-8');assert old in s,f;s=s.replace(old,new);p.write_text(s,encoding='utf-8')
# Scheduling is based on wall-clock minutes, independent of UI/audio state ticks.
edit('main/application.cc','            if (clock_ticks_ % 60 == 0) {\n                time_t now = time(nullptr);\n                if (now > 1000000000L) {','''            static time_t last_schedule_minute = 0;
            const time_t schedule_now = time(nullptr);
            const time_t current_minute = schedule_now / 60;
            if (schedule_now > 1000000000L && current_minute != last_schedule_minute) {
                // Catch short main-loop delays, but never replay hours of offline alarms.
                const time_t first_minute = last_schedule_minute > 0 &&
                    current_minute > last_schedule_minute && current_minute-last_schedule_minute <= 3
                    ? last_schedule_minute + 1 : current_minute;
                last_schedule_minute = current_minute;
                for (time_t tick_minute = first_minute; tick_minute <= current_minute; ++tick_minute) {
                    time_t now = tick_minute * 60;''')
edit('main/alarm_manager.h','    bool delivery_unbound = false;','    bool delivery_unbound = false;\n    int last_triggered_day = 0;\n    int64_t last_triggered_at = 0;')
edit('main/alarm_manager.cc','            fired->second == day_key)', '            fired->second == day_key)') if False else None
edit('main/alarm_manager.cc','        if (fired != last_fired_day_by_id_.end() &&\n            fired->second == day_key) {','        if (a.last_triggered_day == day_key || (fired != last_fired_day_by_id_.end() &&\n            fired->second == day_key)) {')
edit('main/alarm_manager.cc','        last_fired_minute_ = cur_min;\n        last_fired_day_by_id_[a.id] = day_key;','''        const Alarm before = a;
        a.last_triggered_day = day_key;
        a.last_triggered_at = static_cast<int64_t>(time(nullptr));
        if (a.repeat_days == 0) a.enabled = false;
        // Persist the claimed occurrence before delivery; reboot cannot ring it twice.
        if (!Save()) {
            a = before;
            ESP_LOGE(TAG, "Alarm occurrence persistence failed: id=%d", a.id);
            continue;
        }
        last_fired_minute_ = cur_min;
        last_fired_day_by_id_[a.id] = day_key;''')
edit('main/alarm_manager.cc','        a.delivery_unbound = junb ? junb->valueint != 0 : false;','''        a.delivery_unbound = junb ? junb->valueint != 0 : false;
        cJSON* last_day = cJSON_GetObjectItem(item, "fday");
        cJSON* last_time = cJSON_GetObjectItem(item, "fat");
        a.last_triggered_day = cJSON_IsNumber(last_day) ? last_day->valueint : 0;
        a.last_triggered_at = cJSON_IsNumber(last_time) ? static_cast<int64_t>(last_time->valuedouble) : 0;''')
edit('main/alarm_manager.cc','        cJSON_AddNumberToObject(item, "unb", a.delivery_unbound ? 1 : 0);','''        cJSON_AddNumberToObject(item, "unb", a.delivery_unbound ? 1 : 0);
        cJSON_AddNumberToObject(item, "fday", a.last_triggered_day);
        cJSON_AddNumberToObject(item, "fat", static_cast<double>(a.last_triggered_at));''')
edit('main/alarm_manager.cc','#include <cstring>','#include <cstring>\n#include <ctime>')
# Return actual alarm data, not a display-only acknowledgement.
p=R/'main/mcp_tools/mcp_tools_alarm.cc';s=p.read_text();start=s.index('            int total = (int)lines.size();',s.index('ReminderCoordinator::GetInstance().EnqueueInformation'));end=s.index('\n        });',start)
s=s[:start]+'''            cJSON* root = cJSON_CreateObject();
            cJSON* items = cJSON_AddArrayToObject(root, "items");
            cJSON_AddBoolToObject(root, "ok", true);
            for (const auto& a : alarms) {
                cJSON* item = cJSON_CreateObject();
                cJSON_AddNumberToObject(item, "id", a.id);
                cJSON_AddNumberToObject(item, "hour", a.hour);
                cJSON_AddNumberToObject(item, "minute", a.minute);
                cJSON_AddNumberToObject(item, "repeat_days", a.repeat_days);
                cJSON_AddBoolToObject(item, "enabled", a.enabled);
                cJSON_AddStringToObject(item, "label", a.label.c_str());
                cJSON_AddNumberToObject(item, "last_triggered_at", static_cast<double>(a.last_triggered_at));
                cJSON_AddItemToArray(items, item);
            }
            char* json = cJSON_PrintUnformatted(root);
            std::string result = json ? json : "{}";
            cJSON_free(json); cJSON_Delete(root);
            return result;'''+s[end:];
if '#include <cJSON.h>' not in s:s='#include <cJSON.h>\n'+s
p.write_text(s)
# Diagnose both readiness paths without logging credentials.
edit('main/vision_credentials.h','    bool IsIdentityReady() const;','    bool IsIdentityReady() const;\n    std::string IdentityNotReadyReason() const;')
edit('main/vision_credentials.cc','bool VisionCredentialStore::IsIdentityReady() const {','''std::string VisionCredentialStore::IdentityNotReadyReason() const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!generation_accepting_) return "connection_closed";
    if (!last_reject_reason_.empty()) return last_reject_reason_;
    if (!pending_hello_seen_) return "awaiting_hello";
    if (!pending_initialize_seen_) return "awaiting_initialize";
    if (IsExpiredLocked(published_.expires_at)) return "expired";
    if (published_.identity_url.empty()) return "missing_identity_url";
    return published_.identity_ready ? "ready" : "incomplete_pending";
}

bool VisionCredentialStore::IsIdentityReady() const {''')
# Move photo capture, JPEG and HTTP out of the application/audio sender task.
p=R/'main/mcp_tools/mcp_tools_camera.cc';s=p.read_text();start=s.index('    server.AddTool("self.camera.take_photo",');cb=s.index('        [](const PropertyList& p) -> ReturnValue {',start);end=s.index('\n        });',cb)
body=s[cb+len('        [](const PropertyList& p) -> ReturnValue {'):end].rstrip();assert body.endswith('}');body=body[:-1]
body=body.replace('            std::string question = p["question"].value<std::string>();','')
body=body.replace('            TaskPriorityReset priority_reset(1);','')
body=body.replace('McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"}', 'McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready:" + VisionCredentialStore::GetInstance().ExplainNotReadyReason()}')
worker='''namespace {
struct PhotoTask { std::string question; std::function<void(ReturnValue)> done; };
std::atomic<bool> photo_task_busy{false};
void PhotoTaskEntry(void* arg) {
    std::unique_ptr<PhotoTask> task(static_cast<PhotoTask*>(arg));
    const auto started = xTaskGetTickCount();
    try {
        const std::string question = task->question;
        auto run = [&]() -> ReturnValue {'''+body+'''
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
}

'''
s=s[:start]+s[start:cb].replace('server.AddTool','server.AddAsyncTool')+'''        [](const PropertyList& p, std::function<void(ReturnValue)> done) {
            if (photo_task_busy.exchange(true)) { done(McpError{"摄像头正忙，请稍后再试", "camera_busy"}); return; }
            auto* task = new (std::nothrow) PhotoTask{p["question"].value<std::string>(), done};
            if (!task) { photo_task_busy.store(false); done(McpError{"照片内存不足", "resource_exhausted"}); return; }
            const auto created = xTaskCreateWithCaps(PhotoTaskEntry, "mcp_photo", 12288, task, 3,
                nullptr, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
            if (created != pdPASS) { delete task; photo_task_busy.store(false); done(McpError{"无法启动拍照任务", "resource_exhausted"}); }
        });'''+s[end+len('\n        });'):]
s=s.replace('void RegisterCameraCommonTools(McpServer& server) {',worker+'void RegisterCameraCommonTools(McpServer& server) {')
s=s.replace('finish(McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready"});','finish(McpError{"视觉服务尚未就绪，请稍后再试", "vision_not_ready:" + VisionCredentialStore::GetInstance().IdentityNotReadyReason()});')
p.write_text(s)
print('firmware scheduler/photo patch applied')
