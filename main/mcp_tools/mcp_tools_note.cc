#include "mcp_tools.h"
#include "mcp_server.h"
#include "note_manager.h"
#include "proactive_manager.h"
#include "presence_context.h"
#include "user_context.h"
#include "mcp_permission.h"
#include "reminder_coordinator.h"
#include <esp_log.h>
#include <ctime>

void RegisterNoteTools(McpServer& server) {
    server.AddTool("note.add",
        "添加一条待办。remind_at 为 Unix 时间戳，未指定时填 0。"
        "recipient_person_id 可明确指定用户；未指定时优先当前声纹用户，"
        "声纹未知则为 all（所有用户）。",
        PropertyList({
            Property("text",      kPropertyTypeString),
            Property("remind_at", kPropertyTypeInteger, 0, 2147483647),
            Property("repeat_days", kPropertyTypeInteger, 0, 0, 127),
            Property("timezone", kPropertyTypeString, std::string("Asia/Shanghai")),
            Property("priority", kPropertyTypeString, std::string("normal")),
            Property("attention_policy", kPropertyTypeString,
                     std::string("general")),
            Property("pre_alert_minutes", kPropertyTypeInteger, 0, 0, 30),
            Property("recipient_person_id", kPropertyTypeString,
                     std::string("")),
            Property("recipient_display_name", kPropertyTypeString,
                     std::string("")),
        }),
        [](const PropertyList& p) -> ReturnValue {
            std::string text = p["text"].value<std::string>();
            uint32_t remind_at = 0;
            if (p["timezone"].value<std::string>() != "Asia/Shanghai") return McpError{"仅支持 Asia/Shanghai 时区"};
            try { remind_at = (uint32_t)p["remind_at"].value<int>(); } catch (...) {}
            std::string creator = UserContext::GetInstance().GetEffectiveUserId();
            if (creator.empty()) creator = "default";
            std::string perm_err;
            if (!McpCheckPermission(creator, McpPermission::kWriteReminder, perm_err)) {
                return McpError{perm_err};
            }
            const std::string priority =
                p["priority"].value<std::string>();
            const std::string attention_policy =
                p["attention_policy"].value<std::string>();
            const int pre_alert_minutes =
                p["pre_alert_minutes"].value<int>();
            std::string recipient =
                p["recipient_person_id"].value<std::string>();
            const std::string recipient_display =
                p["recipient_display_name"].value<std::string>();
            if (recipient.empty()) {
                const std::string speaker =
                    UserContext::GetInstance().GetCurrentSpeakerUserId();
                recipient = PresenceContext::IsStableUserId(speaker)
                    ? speaker : "all";
            }
            if (priority != "normal" && priority != "high") {
                return McpError{"priority must be normal or high"};
            }
            if (attention_policy != "general" &&
                attention_policy != "pickup" &&
                attention_policy != "medication") {
                return McpError{
                    "attention_policy must be general, pickup or medication"};
            }
            if (priority != "high" &&
                (attention_policy != "general" ||
                 pre_alert_minutes != 0)) {
                return McpError{
                    "attention policy and pre-alert require high priority"};
            }
            std::string add_error;
            int id = NoteManager::GetInstance().Add(
                text, remind_at, creator, priority, attention_policy,
                pre_alert_minutes, recipient, recipient_display, p["repeat_days"].value<int>(), &add_error);
            if (id < 0) {
                const std::string message = add_error == "note_limit_reached"
                    ? "备忘录已满，最多20条" : add_error == "storage_full"
                    ? "NVS存储空间不足，提醒未保存" : add_error == "invalid_repeat_days"
                    ? "重复提醒日期参数不正确" : "提醒保存失败，未保存";
                return McpError{message, add_error};
            }
            ESP_LOGI("MCP", "[NOTE] event=add id=%d remind_at=%u text_len=%u",
                     id, (unsigned)remind_at, (unsigned)text.size());
            if (remind_at > 0) {
                for (const auto& rule : NoteManager::GetInstance().GetAll(creator))
                    if (rule.id == id) remind_at = rule.remind_at;
                const bool queued = ReminderCoordinator::GetInstance().EnqueueNote(
                    id, creator, text, static_cast<time_t>(remind_at),
                    std::to_string(remind_at), priority, attention_policy,
                    pre_alert_minutes, recipient, creator, recipient_display);
                if (!queued) {
                    // Do not claim a reminder was configured when its
                    // durable coordinator row could not be committed.
                    NoteManager::GetInstance().Delete(id);
                    return McpError{"提醒未能持久化，未保存该备忘录", "persist_failed"};
                }
                time_t t = (time_t)remind_at;
                struct tm tm_info;
                localtime_r(&t, &tm_info);
                char time_buf[32];
                strftime(time_buf, sizeof(time_buf), "%m/%d %H:%M", &tm_info);
                return std::string("已记录：") + text + "，将于 " + time_buf + " 提醒";
            }
            return std::string("已记录：") + text;
        });

    server.AddUserOnlyTool("note.snooze",
        "将指定备忘录的提醒时间延后（贪睡，最多3次）。",
        PropertyList({
            Property("index",         kPropertyTypeInteger, 1, 20),
            Property("delay_minutes", kPropertyTypeInteger, 1, 60),
        }),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            int delay_min = p["delay_minutes"].value<int>();
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto notes = NoteManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)notes.size()) return McpError{"序号无效"};
            int id = notes[idx].id;
            const auto action = ReminderCoordinator::GetInstance().ActBySource(
                ReminderSourceType::kNote, id, ReminderAction::kSecondary,
                delay_min, owner);
            if (!action.handled) return McpError{action.message};
            char buf[32];
            snprintf(buf, sizeof(buf), "[NOTE_SNOOZED] %d", delay_min);
            return std::string(buf);
        });

    server.AddTool("note.list",
        "查看所有备忘录，包含状态标注（待办/已提醒/已过期）。", PropertyList(),
        [](const PropertyList& p) -> ReturnValue {
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kReadReminder, perm_err)) return McpError{perm_err};
            auto notes = NoteManager::GetInstance().GetAll(owner);
            if (notes.empty()) return std::string("暂无备忘录");
            std::string result;
            int i = 1;
            uint32_t now_ts = (uint32_t)time(nullptr);
            for (const auto& n : notes) {
                std::string line = n.text;
                if (n.remind_at > 0) {
                    if (n.fired) {
                        uint32_t elapsed = now_ts > n.remind_at ? now_ts - n.remind_at : 0;
                        char buf[32];
                        if (elapsed < 3600)
                            snprintf(buf, sizeof(buf), " [已提醒，%lu分钟前]", (unsigned long)(elapsed / 60));
                        else
                            snprintf(buf, sizeof(buf), " [已提醒，%lu小时前]", (unsigned long)(elapsed / 3600));
                        line += buf;
                    } else if (now_ts > n.remind_at) {
                        line += " [已过时间，待提醒]";
                    } else {
                        time_t t = (time_t)n.remind_at;
                        struct tm tm_info;
                        localtime_r(&t, &tm_info);
                        char time_buf[32];
                        strftime(time_buf, sizeof(time_buf), " [提醒:%m/%d %H:%M]", &tm_info);
                        line += time_buf;
                    }
                } else {
                    line += " [待办]";
                }
                result += std::to_string(i++) + ". " + line + "\n";
                if (i > 8) break;
            }
            return result;
        });

    server.AddUserOnlyTool("note.delete",
        "删除指定序号的备忘录（从1开始，最新的排第1）。",
        PropertyList({Property("index", kPropertyTypeInteger, 1, 20)}),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto notes = NoteManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)notes.size()) return McpError{"序号无效"};
            int id = notes[idx].id;
            const auto action = ReminderCoordinator::GetInstance().ActBySource(
                ReminderSourceType::kNote, id, ReminderAction::kCancel,
                0, owner);
            if (!action.handled) return McpError{action.message};
            return std::string("[NOTE_DELETED]");
        });
}
