#include "mcp_tools.h"
#include "mcp_server.h"
#include "habit_manager.h"
#include "behavior_logger.h"
#include "proactive_manager.h"
#include "presence_context.h"
#include "user_context.h"
#include "mcp_permission.h"
#include "reminder_coordinator.h"
#include <esp_log.h>
#include <ctime>

void RegisterHabitTools(McpServer& server) {
    server.AddUserOnlyTool("habit.learn",
        "记录用户的规律性习惯，用于定时主动提醒。仅在 habit.analyze 分析行为日志后调用，不用于响应用户的直接请求。"
        "recipient_person_id 可明确指定用户；未指定时优先当前声纹用户，"
        "声纹未知则为 all（所有用户）。",
        PropertyList({
            Property("intent",           kPropertyTypeString),
            Property("description",      kPropertyTypeString),
            Property("hour",             kPropertyTypeInteger, 0, 23),
            Property("minute",           kPropertyTypeInteger, 0, 59),
            Property("advance_minutes",  kPropertyTypeInteger, 0, 30),
            Property("source",           kPropertyTypeString),
            Property("repeat_days",      kPropertyTypeInteger, 127, 1, 127),
            Property("recipient_person_id", kPropertyTypeString,
                     std::string("")),
            Property("recipient_display_name", kPropertyTypeString,
                     std::string("")),
        }),
        [](const PropertyList& p) -> ReturnValue {
            if (!bound_person_turn || !bound_person_turn->Eligible()) return McpError{"本轮身份未确认", "identity_unconfirmed"};
            std::string intent = p["intent"].value<std::string>();
            std::string desc   = p["description"].value<std::string>();
            int h   = p["hour"].value<int>();
            int m   = p["minute"].value<int>();
            int adv = 2;
            std::string src = "auto";
            try { adv = p["advance_minutes"].value<int>(); } catch (...) {}
            try { src = p["source"].value<std::string>(); } catch (...) {}
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
            int id = HabitManager::GetInstance().Add(
                h, m, adv, intent, desc, src, creator, recipient,
                recipient_display, p["repeat_days"].value<int>());
            if (id < 0) return McpError{"习惯规则已满，最多20条"};
            char buf[96];
            snprintf(buf, sizeof(buf), "已记录习惯：%s，每天 %02d:%02d 前 %d 分钟提醒",
                     desc.c_str(), h, m, adv);
            return std::string(buf);
        });

    server.AddUserOnlyTool("habit.list",
        "查看所有已记录的习惯规则。", PropertyList(),
        [](const PropertyList& p) -> ReturnValue {
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kReadReminder, perm_err)) return McpError{perm_err};
            auto habits = HabitManager::GetInstance().GetAll(owner);
            if (habits.empty()) return std::string("暂无习惯规则");
            std::string result;
            int idx = 1;
            for (const auto& h : habits) {
                char buf[128];
                snprintf(buf, sizeof(buf), "%d. %02d:%02d %s [%s] 置信度:%d%s\n",
                         idx++, h.hour, h.minute, h.description.c_str(),
                         h.source.c_str(), h.confidence,
                         h.enabled ? "" : " (已禁用)");
                result += buf;
            }
            return result;
        });

    server.AddUserOnlyTool("habit.delete",
        "删除指定序号的习惯规则。当用户说不需要某个习惯、已经养成了不需要提醒、或明确要删除时调用。需先用 habit.list 查出序号再删除。",
        PropertyList({Property("index", kPropertyTypeInteger, 1, 20)}),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto habits = HabitManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)habits.size()) return McpError{"序号无效"};
            int id = habits[idx].id;
            HabitManager::GetInstance().Delete(id);
            return std::string("已删除");
        });

    server.AddUserOnlyTool("habit.confirm",
        "确认本次习惯提醒有效（用户接受了提醒）。",
        PropertyList({Property("index", kPropertyTypeInteger, 1, 20)}),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto habits = HabitManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)habits.size()) return McpError{"序号无效"};
            int id = habits[idx].id;
            const auto action = ReminderCoordinator::GetInstance().ActBySource(
                ReminderSourceType::kHabit, id, ReminderAction::kPrimary,
                0, owner);
            if (!action.handled) return McpError{action.message};
            return std::string("[HABIT_CONFIRMED] ") + habits[idx].description;
        });

    server.AddUserOnlyTool("habit.reject",
        "仅跳过今天这一次习惯提醒，不删除或禁用习惯规则。",
        PropertyList({Property("index", kPropertyTypeInteger, 1, 20)}),
        [](const PropertyList& p) -> ReturnValue {
            int idx = p["index"].value<int>() - 1;
            std::string owner = UserContext::GetInstance().GetEffectiveUserId();
            if (owner.empty()) owner = "default";
            std::string perm_err;
            if (!McpCheckPermission(owner, McpPermission::kWriteReminder, perm_err)) return McpError{perm_err};
            auto habits = HabitManager::GetInstance().GetAll(owner);
            if (idx < 0 || idx >= (int)habits.size()) return McpError{"序号无效"};
            int id = habits[idx].id;
            std::string desc = habits[idx].description;
            const auto action = ReminderCoordinator::GetInstance().ActBySource(
                ReminderSourceType::kHabit, id, ReminderAction::kTertiary,
                0, owner);
            if (!action.handled) return McpError{action.message};
            return std::string("[HABIT_SKIPPED_TODAY] ") + desc;
        });

    server.AddUserOnlyTool("behavior.log",
        "每次用户发出有意图的请求时调用，记录行为意图日志用于习惯学习分析。"
        "不需要用户主动要求，每次对话结束前自动调用一次。",
        PropertyList({
            Property("intent", kPropertyTypeString),
            Property("raw",    kPropertyTypeString),
            Property("outcome", kPropertyTypeString, std::string("conversation")),
        }),
        [](const PropertyList& p) -> ReturnValue {
            std::string intent = p["intent"].value<std::string>();
            std::string raw    = p["raw"].value<std::string>();
            time_t now = time(nullptr);
            struct tm t;
            localtime_r(&now, &t);
            std::string record;
            if (!BehaviorLogger::GetInstance().Log(intent, raw, t.tm_hour, t.tm_min,
                p["outcome"].value<std::string>(), &record)) return false;
            return record;
        });

    server.AddUserOnlyTool("habit.analyze",
        "分析最近7天的行为日志，识别规律性习惯并通过 habit.learn 记录。"
        "由系统定期触发（每7天或日志满时），不响应用户直接请求，不主动调用。",
        PropertyList(),
        [](const PropertyList& p) -> ReturnValue {
            if (!bound_person_turn || !bound_person_turn->Eligible()) return McpError{"本轮身份未确认", "identity_unconfirmed"};
            uint64_t watermark = 0;
            auto summaries = BehaviorLogger::GetInstance().Summarize(bound_person_turn->person_id, &watermark);
            if (summaries.empty()) {
                return std::string("暂无规律性行为数据");
            }
            cJSON* arr = cJSON_CreateArray();
            for (const auto& s : summaries) {
                cJSON* item = cJSON_CreateObject();
                cJSON_AddNumberToObject(item, "hour",        s.hour);
                cJSON_AddNumberToObject(item, "days_active", s.days_active);
                cJSON_AddNumberToObject(item, "total_count", s.total_count);
                cJSON* days_arr = cJSON_CreateArray();
                for (int d = 0; d < (int)s.samples.size(); d++) {
                    cJSON* day_obj = cJSON_CreateObject();
                    cJSON_AddNumberToObject(day_obj, "day", d + 1);
                    cJSON* texts = cJSON_CreateArray();
                    for (const auto& t : s.samples[d]) {
                        cJSON_AddItemToArray(texts, cJSON_CreateString(t.c_str()));
                    }
                    cJSON_AddItemToObject(day_obj, "texts", texts);
                    cJSON_AddItemToArray(days_arr, day_obj);
                }
                cJSON_AddItemToObject(item, "samples", days_arr);
                cJSON_AddItemToArray(arr, item);
            }
            cJSON* envelope = cJSON_CreateObject();
            cJSON_AddStringToObject(envelope, "person_id", bound_person_turn->person_id.c_str());
            cJSON_AddStringToObject(envelope, "watermark", std::to_string(watermark).c_str());
            cJSON_AddItemToObject(envelope, "summaries", arr);
            char* json_str = cJSON_PrintUnformatted(envelope);
            cJSON_Delete(envelope);
            std::string result = json_str ? json_str : "{}";
            if (json_str) free(json_str);
            return result;
        });

    server.AddUserOnlyTool("behavior.ack",
        "由服务端确认当前人物已成功分析的行为水位，保留其他人物和新增记录。",
        PropertyList({Property("watermark", kPropertyTypeString)}),
        [](const PropertyList& p) -> ReturnValue {
            if (!bound_person_turn || !bound_person_turn->Eligible()) return McpError{"本轮身份未确认", "identity_unconfirmed"};
            auto value = p["watermark"].value<std::string>();
            char* end = nullptr;
            auto mark = strtoull(value.c_str(), &end, 10);
            if (value.empty() || !end || *end || value[0] == '-') return McpError{"无效行为水位"};
            return BehaviorLogger::GetInstance().Acknowledge(bound_person_turn->person_id, mark);
        });
}
