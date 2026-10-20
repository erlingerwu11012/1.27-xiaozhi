from pathlib import Path
R=Path(r'E:/github/github_code/all/4.30')
p=R/'main/reminder_coordinator.h';s=p.read_text();s=s.replace('    bool OnVisualDismissed(','''    ReminderActionResult CloseCurrent(const std::string& instance_id, uint32_t revision,
                                      const std::string& actor);
    void InvalidateInformation(const std::string& title_prefix, const std::string& actor);
    bool OnVisualDismissed(''');p.write_text(s)
p=R/'main/reminder_coordinator.cc';s=p.read_text();s=s.replace('    instance.owner_user_id = "default";\n    instance.due_at = time(nullptr);','''    instance.owner_user_id = UserContext::GetInstance().GetEffectiveUserId();
    if (instance.owner_user_id.empty()) instance.owner_user_id = "default";
    instance.recipient_person_id = instance.owner_user_id;
    instance.due_at = time(nullptr);''')
pos=s.index('bool ReminderCoordinator::OnVisualDismissed(')
s=s[:pos]+'''ReminderActionResult ReminderCoordinator::CloseCurrent(
    const std::string& id, uint32_t revision, const std::string& actor) {
    Initialize();
    uint32_t next_revision = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        auto* card = FindLocked(id);
        std::string error;
        if (!McpCheckPermission(actor, McpPermission::kWriteReminder, error))
            return {false, "permission_denied", error, 0};
        if (!card || !CanReadDetails(*card, actor))
            return {false, "identity_mismatch", "当前身份无权关闭这张卡片", 0};
        const auto session = Application::GetInstance().GetAudioSessionId();
        if (session.empty() || card->bound_session_id != session)
            return {false, "session_mismatch", "会话已变化，请重新读取当前卡片", card->revision};
        if (card->last_action == "close" && card->revision == revision + 1)
            return {true, "already_closed", "卡片已关闭，事项保留", card->revision};
        if (current_instance_id_ != id || card->revision != revision ||
            card->status != ReminderStatus::kPresenting)
            return {false, "stale_revision", "当前卡片已变化", card->revision};
        const auto before = *card;
        // Close this presentation only. Do not touch Note/Alarm/Habit business rows.
        card->status = ReminderStatus::kDismissed;
        card->last_action = "close";
        card->updated_at = time(nullptr);
        AdvanceRevisionLocked(*card);
        current_instance_id_.clear();
        SaveLocked();
        if (store_dirty_) { *card = before; current_instance_id_ = id;
            return {false, "storage_failed", "卡片关闭状态保存失败", revision}; }
        next_revision = card->revision;
    }
    ReminderControlClient::GetInstance().Cancel("card_closed");
    DismissVisual(id, next_revision, "card_closed");
    return {true, "closed", "卡片已关闭，事项保留", next_revision};
}

void ReminderCoordinator::InvalidateInformation(const std::string& prefix,
                                                const std::string& actor) {
    Initialize();
    std::string dismissed; uint32_t revision = 0;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        const auto before = instances_; const auto current = current_instance_id_;
        for (auto& card : instances_) {
            if (card.source_type != ReminderSourceType::kInformation || !IsActive(card) ||
                card.owner_user_id != actor || card.title.rfind(prefix, 0) != 0) continue;
            card.status = ReminderStatus::kExpired; card.updated_at = time(nullptr);
            AdvanceRevisionLocked(card);
            if (card.instance_id == current_instance_id_) {
                dismissed = card.instance_id; revision = card.revision; current_instance_id_.clear();
            }
        }
        SaveLocked();
        if (store_dirty_) { instances_ = before; current_instance_id_ = current; return; }
    }
    if (!dismissed.empty()) {
        ReminderControlClient::GetInstance().Cancel("source_updated");
        DismissVisual(dismissed, revision, "source_updated");
    }
}

'''+s[pos:];p.write_text(s)
p=R/'main/mcp_tools/mcp_tools_card.cc';s=p.read_text();pos=s.index('    server.AddTool(\n        "reminder.action"')
s=s[:pos]+'''    server.AddTool("reminder.close_current",
        "Close only the current visible card without completing or deleting its business item. Read reminder.get_current first; pass the exact instance_id and revision.",
        PropertyList({Property("instance_id", kPropertyTypeString),
                      Property("revision", kPropertyTypeInteger, 1, 2147483647)}),
        [](const PropertyList& properties) -> ReturnValue {
            const auto id = properties["instance_id"].value<std::string>();
            const int revision = properties["revision"].value<int>();
            const auto result = ReminderCoordinator::GetInstance().CloseCurrent(
                id, revision, UserContext::GetInstance().GetEffectiveUserId());
            if (!result.handled) return McpError{result.message, result.code};
            cJSON* root = cJSON_CreateObject();
            cJSON_AddBoolToObject(root, "ok", true);
            cJSON_AddBoolToObject(root, "closed", true);
            cJSON_AddBoolToObject(root, "business_unchanged", true);
            cJSON_AddStringToObject(root, "instance_id", id.c_str());
            cJSON_AddNumberToObject(root, "revision", revision);
            cJSON_AddNumberToObject(root, "current_revision", result.revision);
            return root;
        });

'''+s[pos:];p.write_text(s)
# Do not call coordinator while holding the alarm mutex (it reads source rows).
p=R/'main/alarm_manager.cc';s=p.read_text();start=s.index('void AlarmManager::CheckAndFire(');end=s.index('\nvoid AlarmManager::Snooze',start);section=s[start:end]
section=section.replace('    int cur_min = hour * 60 + minute;','    int cur_min = hour * 60 + minute;\n    std::vector<Alarm> deliveries;')
section=section.replace('            on_fire(snoozed_alarm_);','            deliveries.push_back(snoozed_alarm_);').replace('    std::lock_guard<std::mutex> lock(mutex_);\n    bool need_save', '    {\n    std::lock_guard<std::mutex> lock(mutex_);\n    bool need_save').replace('        on_fire(a);','        deliveries.push_back(a);').replace('    if (need_save) Save();\n}', '    if (need_save) Save();\n    }\n    for (const auto& alarm : deliveries) on_fire(alarm);\n}')
s=s[:start]+section+s[end:];p.write_text(s)
print('card close and alarm lock patch applied')
