#include <cJSON.h>
#include "mcp_tools.h"
#include "mcp_server.h"
#include "application.h"
#include "alarm_manager.h"
#include "proactive_manager.h"
#include "presence_context.h"
#include "user_context.h"
#include "mcp_permission.h"
#include "board.h"
#include "display.h"
#include "reminder_coordinator.h"
#include <esp_log.h>

void RegisterAlarmTools(McpServer& server) {
    server.AddTool("alarm.set",
        "设置定时闹钟。repeat_days为重复规则位掩码：bit0=周日,bit1=周一,...,bit6=周六。"
        "常用值：127=每天,62=工作日(周一到周五),65=周末(周六周日),0=仅响一次。"
        "例如只在周一三五响=42(bit1+bit3+bit5=2+8+32)。"
        "recipient_person_id 可明确指定用户；未指定时优先当前声纹用户，"
        "声纹未知则为 all（所有用户）。",
        PropertyList({
            Property("hour",        kPropertyTypeInteger, 0, 23),
            Property("minute",      kPropertyTypeInteger, 0, 59),
            Property("label",       kPropertyTypeString),
            Property("repeat_days", kPropertyTypeInteger, 0, 127),
            Property("recipient_person_id", kPropertyTypeString,
                     std::string("")),
            Property("recipient_display_name", kPropertyTypeString,
                     std::string("")),
        }),
        [](const PropertyList& p) -> ReturnValue {
            int h = p["hour"].value<int>();
            int m = p["minute"].value<int>();
            std::string label = p["label"].value<std::string>();
            int rd = p["repeat_days"].value<int>();
            std::string creator = UserContext::GetInstance().GetEffectiveUserId();
            if (creator.empty()) creator = "default";
            std::string perm_err;
            if (!McpCheckPermission(creator, McpPermission::kWriteReminder, perm_err)) {
                return McpError{perm_err};
            }
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
            int id = AlarmManager::GetInstance().Add(
                h, m, label, (uint8_t)rd, creator, recipient,
                recipient_display);
            if (id < 0) return McpError{"闹钟保存失败或数量已满，请检查存储状态", "storage_write_failed"};
            ReminderCoordinator::GetInstance().InvalidateInformation("闹钟列表", creator);
            ESP_LOGI("MCP", "[ALARM] event=set id=%d %02d:%02d rd=%d",
                     id, h, m, rd);
            const char* repeat_desc = "仅一次";
            if (rd == 127) repeat_desc = "每天";
            else if (rd == 62) repeat_desc = "工作日";
            else if (rd == 65) repeat_desc = "周末";
            else if (rd != 0) repeat_desc = "自定义";
            char buf[96];
            snprintf(buf, sizeof(buf), "已设置 %02d:%02d %s [%s]",
                     h, m, label.c_str(), repeat_desc);
            return std::string(buf);
        });

    server.AddTool("alarm.list",
        "查看所有闹钟。", PropertyList(),
        [](const PropertyList& p) -> ReturnValue {
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kReadReminder, perm_err)) return McpError{perm_err};
            auto alarms = AlarmManager::GetInstance().GetAll(owner);
            if (alarms.empty()) return std::string("暂无闹钟");

            // 构造显示行
            std::vector<std::string> lines;
            static const char* day_names[] = {"日","一","二","三","四","五","六"};
            for (auto& a : alarms) {
                std::string repeat_str;
                if (a.repeat_days == 0x7F) repeat_str = "每天";
                else if (a.repeat_days == 0x3E) repeat_str = "工作日";
                else if (a.repeat_days == 0x41) repeat_str = "周末";
                else if (a.repeat_days == 0) repeat_str = "仅一次";
                else {
                    repeat_str = "每周";
                    for (int d = 0; d < 7; d++) {
                        if (a.repeat_days & (1 << d)) repeat_str += day_names[d];
                    }
                }
                char buf[96];
                snprintf(buf, sizeof(buf), "[%d] %02d:%02d %s [%s]%s",
                         a.id, a.hour, a.minute, a.label.c_str(),
                         repeat_str.c_str(), a.enabled ? "" : " (已关闭)");
                lines.push_back(buf);
            }

            auto* disp = Board::GetInstance().GetDisplay();
            if (disp) {
                int total = (int)lines.size();
                char title_buf[48];
                if (total <= 4) {
                    snprintf(title_buf, sizeof(title_buf), "闹钟列表（共%d个）", total);
                } else {
                    snprintf(title_buf, sizeof(title_buf), "闹钟列表（前4/%d）", total);
                }
                int show = total <= 4 ? total : 4;
                std::vector<std::string> shown_lines;
                for (int i = 0; i < show; i++) {
                    shown_lines.push_back(lines[i]);
                }
                ReminderCoordinator::GetInstance().EnqueueInformation(
                    title_buf, shown_lines, LISTENING_TIMEOUT_MS);
            }

            cJSON* root = cJSON_CreateObject();
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
            return result;
        });

    server.AddUserOnlyTool("alarm.delete",
        "删除指定序号的闹钟（从1开始）。",
        PropertyList({Property("index", kPropertyTypeInteger, 1, 8)}),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto alarms = AlarmManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)alarms.size()) return McpError{"序号无效"};
            int id = alarms[idx].id;
            if (!AlarmManager::GetInstance().Delete(id)) return McpError{"闹钟删除保存失败", "storage_failed"};
            ReminderCoordinator::GetInstance().InvalidateInformation("闹钟列表", owner);
            return std::string("已删除");
        });

    server.AddUserOnlyTool("alarm.dismiss",
        "关闭当前正在响的闹钟。用户说关掉、停、好了、知道了时调用。",
        PropertyList(),
        [](const PropertyList& p) -> ReturnValue {
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) {
                return McpError{perm_err};
            }
            ReminderInstance current;
            auto& coordinator = ReminderCoordinator::GetInstance();
            if (!coordinator.GetCurrent(current) || current.source_type != ReminderSourceType::kAlarm) {
                return McpError{"当前没有正在响的闹钟", "not_ringing"};
            }
            const auto result = coordinator.Act(current.instance_id, current.revision,
                ReminderAction::kPrimary, 0, owner, true);
            if (!result.handled) return McpError{result.message};
            return std::string("[ALARM_DISMISSED]");
        });

    server.AddUserOnlyTool("alarm.snooze",
        "贪睡当前闹钟。用户说再睡一会、5分钟后再叫我、贪睡时调用。",
        PropertyList({Property("minutes", kPropertyTypeInteger, 1, 30)}),
        [](const PropertyList& p) -> ReturnValue {
            int mins = p["minutes"].value<int>();
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) {
                return McpError{perm_err};
            }
            ReminderInstance current;
            auto& coordinator = ReminderCoordinator::GetInstance();
            if (!coordinator.GetCurrent(current) || current.source_type != ReminderSourceType::kAlarm) {
                return McpError{"当前没有正在响的闹钟", "not_ringing"};
            }
            const auto result = coordinator.Act(current.instance_id, current.revision,
                ReminderAction::kSecondary, mins, owner, true);
            if (!result.handled) return McpError{result.message};
            char buf[32];
            snprintf(buf, sizeof(buf), "[ALARM_SNOOZED] %d", mins);
            return std::string(buf);
        });
}
