from pathlib import Path
import shutil
R=Path(__file__).resolve().parents[2];backup=Path(__file__).parent/'firmware-baseline';backup.mkdir(exist_ok=True)
names=['main/vision_credentials.h','main/vision_credentials.cc','main/mcp_tools/mcp_tools_camera.cc','main/reminder_coordinator.cc']
for name in names:
    p=R/name;out=backup/Path(name).name
    if not out.exists():shutil.copy2(p,out)
p=R/'main/vision_credentials.h';s=p.read_text(encoding='utf-8-sig').replace('    bool IsExplainReady() const;','    bool IsExplainReady() const;\n    std::string ExplainNotReadyReason() const;');p.write_text(s,encoding='utf-8')
p=R/'main/vision_credentials.cc';s=p.read_text(encoding='utf-8-sig');needle='bool VisionCredentialStore::IsIdentityReady() const {'
s=s.replace(needle,'''std::string VisionCredentialStore::ExplainNotReadyReason() const {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!generation_accepting_) return "connection_closed";
    if (!last_reject_reason_.empty()) return last_reject_reason_;
    if (!pending_hello_seen_) return "awaiting_hello";
    if (!pending_initialize_seen_) return "awaiting_initialize";
    if (IsExpiredLocked(published_.expires_at)) return "expired";
    return published_.explain_ready ? "ready" : "incomplete_pending";
}

'''+needle);p.write_text(s,encoding='utf-8')
p=R/'main/mcp_tools/mcp_tools_camera.cc';s=p.read_text(encoding='utf-8-sig');s=s.replace('''            if (!VisionCredentialStore::GetInstance().IsExplainReady()) {
                return McpError''','''            if (!VisionCredentialStore::GetInstance().IsExplainReady()) {
                ESP_LOGW("CameraMCP", "event=explain_rejected reason=%s",
                         VisionCredentialStore::GetInstance().ExplainNotReadyReason().c_str());
                return McpError''');p.write_text(s,encoding='utf-8')
p=R/'main/reminder_coordinator.cc';s=p.read_text(encoding='utf-8-sig');needle='''        const bool can_read = CanReadDetails(instance, actor);
        cJSON_AddBoolToObject(root, "active", true);''';assert needle in s
s=s.replace(needle,'''        const bool can_read = CanReadDetails(instance, actor);
        // An authorized fresh read grants this exact visible version to the
        // current connection. Keep Act's session, actor and revision guards.
        const std::string session = Application::GetInstance().GetAudioSessionId();
        if (can_read && !session.empty()) {
            auto* self = const_cast<ReminderCoordinator*>(this);
            std::lock_guard<std::mutex> lock(self->mutex_);
            auto* live = self->FindLocked(instance.instance_id);
            if (live && live->revision == instance.revision &&
                self->current_instance_id_ == instance.instance_id &&
                IsActive(*live) && live->bound_session_id != session) {
                live->bound_session_id = session;
                ESP_LOGI(kTag, "[REMINDER_CARD] event=session_rebound reason=authorized_current_read revision=%u", static_cast<unsigned>(instance.revision));
            }
        }
        cJSON_AddBoolToObject(root, "active", true);''',1)
p.write_text(s,encoding='utf-8')
# Extend actual production-source host coverage, not a reimplementation.
p=R/'tools/test_vision_credentials_host.cpp';s=p.read_text(encoding='utf-8-sig');backupfile=backup/p.name
if not backupfile.exists():shutil.copy2(p,backupfile)
needle='    TestInitialConnectReady();';assert needle in s
s=s.replace(needle,'''    {
        auto& store = VisionCredentialStore::GetInstance();
        auto gen = store.BeginConnection();
        CHECK(store.ExplainNotReadyReason() == "awaiting_hello");
        store.ApplyHelloSession(gen, "experience-repair-session");
        CHECK(store.ExplainNotReadyReason() == "awaiting_initialize");
        store.EndConnection(gen);
        CHECK(store.ExplainNotReadyReason() == "connection_closed");
    }
'''+needle);p.write_text(s,encoding='utf-8')
print('firmware edits ready')
