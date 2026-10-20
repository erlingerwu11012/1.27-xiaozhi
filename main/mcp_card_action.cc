#include "mcp_card_action.h"

#include "presence_context.h"
#include "reminder_coordinator.h"
#include "user_context.h"

#include <esp_log.h>

namespace {
constexpr const char* kTag = "McpCardAction";

const char* ActionName(McpCardAction action) {
    switch (action) {
        case McpCardAction::kPrimary: return "primary";
        case McpCardAction::kSecondary: return "secondary";
        case McpCardAction::kTertiary: return "tertiary";
    }
    return "unknown";
}

std::string UserFacingActionMessage(const ReminderActionResult& result) {
    if (result.code == "recipient_identity_missing" ||
        result.message.find("用户身份") != std::string::npos) {
        return "用户身份未同步";
    }
    if (result.code == "session_mismatch") {
        return "会话已更新，请查看当前卡片";
    }
    return result.message;
}
}  // namespace

McpCardActionResult ExecuteMcpCardAction(
    const std::string& instance_id, uint32_t revision,
    McpCardAction action) {
    ReminderInstance snapshot;
    if (!ReminderCoordinator::GetInstance().GetById(
            instance_id, snapshot) ||
        snapshot.revision != revision) {
        ESP_LOGW(kTag,
                 "[REMINDER_CARD] event=action_rejected instance=%s rev=%u "
                 "action=%s reason=stale_or_missing",
                 instance_id.c_str(), static_cast<unsigned>(revision),
                 ActionName(action));
        return {false, "提醒已更新，请查看当前卡片"};
    }
    ESP_LOGI(kTag,
             "[REMINDER_CARD] event=action_execute instance=%s rev=%u "
             "action=%s source=%d status=%d",
             instance_id.c_str(), static_cast<unsigned>(revision),
             ActionName(action), static_cast<int>(snapshot.source_type),
             static_cast<int>(snapshot.status));
    ReminderAction mapped = ReminderAction::kPrimary;
    if (snapshot.status == ReminderStatus::kAwaitingUndo &&
        action == McpCardAction::kPrimary) {
        mapped = ReminderAction::kUndo;
    } else if (action == McpCardAction::kSecondary) {
        mapped = ReminderAction::kSecondary;
    } else if (action == McpCardAction::kTertiary) {
        mapped = ReminderAction::kTertiary;
    }
    std::string actor = PresenceContext::GetInstance().ConfirmedPersonId();
    if (actor.empty()) {
        if (snapshot.no_face_owner_bypass &&
            !snapshot.recipient_person_id.empty()) {
            actor = snapshot.recipient_person_id;
        } else {
            actor = UserContext::GetInstance().GetEffectiveUserId();
        }
    }
    const auto result = ReminderCoordinator::GetInstance().Act(
        instance_id, revision, mapped, 0, actor, true,
        /*touch_action=*/true);
    ESP_LOGI(kTag,
             "[REMINDER_CARD] event=action_complete instance=%s rev=%u "
             "action=%s handled=%d code=%s message=\"%s\"",
             instance_id.c_str(), static_cast<unsigned>(revision),
             ActionName(action), result.handled ? 1 : 0,
             result.code.c_str(), result.message.c_str());
    return {result.handled, UserFacingActionMessage(result)};
}

McpCardActionResult ExecuteCurrentMcpCardAction(McpCardAction action) {
    ReminderInstance current;
    if (!ReminderCoordinator::GetInstance().GetCurrent(current)) {
        return {false, "当前没有可操作提醒"};
    }
    return ExecuteMcpCardAction(
        current.instance_id, current.revision, action);
}

std::string GetCurrentMcpCardContext() {
    return ReminderCoordinator::GetInstance().GetCurrentJson();
}
