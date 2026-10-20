#include "mcp_tools.h"

#include "mcp_card_action.h"
#include "mcp_server.h"
#include "mcp_permission.h"
#include "user_context.h"
#include "reminder_coordinator.h"

namespace {

bool CheckReminderWritePermission(std::string& error) {
    std::string user = UserContext::GetInstance().GetEffectiveUserId();
    if (user.empty()) user = "default";
    return McpCheckPermission(user, McpPermission::kWriteReminder, error);
}

}  // namespace

void RegisterCardTools(McpServer& server) {
    server.AddTool("card.get_current",
        "Get the actionable reminder card currently visible on the device. Use before resolving words such as 'this' or 'it'.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            return GetCurrentMcpCardContext();
        });

    server.AddTool("card.action",
        "Act on the reminder card currently visible on the device. primary completes/confirms/closes, secondary delays or snoozes, and tertiary means note not-needed or habit skip-today.",
        PropertyList({Property("action", kPropertyTypeString)}),
        [](const PropertyList& properties) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};

            const std::string action = properties["action"].value<std::string>();
            McpCardActionResult result;
            if (action == "primary") {
                result = ExecuteCurrentMcpCardAction(McpCardAction::kPrimary);
            } else if (action == "secondary") {
                result = ExecuteCurrentMcpCardAction(McpCardAction::kSecondary);
            } else if (action == "tertiary") {
                result = ExecuteCurrentMcpCardAction(McpCardAction::kTertiary);
            } else {
                return McpError{
                    "Argument 'action' must be 'primary', 'secondary', or 'tertiary'"};
            }
            if (!result.handled) return McpError{result.message};
            return result.message;
        });

    server.AddTool(
        "reminder.get_current",
        "Get the current reminder instance including instance_id, revision, "
        "status and exact actions.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            return ReminderCoordinator::GetInstance().GetCurrentJson();
        });

    server.AddUserOnlyTool(
        "reminder.list_pending",
        "List pending reminder instances visible to the current user.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            const std::string actor =
                UserContext::GetInstance().GetEffectiveUserId();
            return ReminderCoordinator::GetInstance().ListPendingJson(actor);
        });

    server.AddUserOnlyTool(
        "reminder.begin_broadcast",
        "Only call after the user explicitly agrees to hear pending to-dos. "
        "Shows and reads exactly one item; later items advance only after an "
        "action on the current item.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            if (!ReminderCoordinator::GetInstance().BeginPendingBroadcast()) {
                return McpError{"没有可播报的待办，或当前无人"};
            }
            return std::string("已开始逐项播报待办");
        });

    server.AddUserOnlyTool(
        "reminder.next",
        "For the user's voice command '下一个'. Skips only the current "
        "broadcast item for this visit; it remains unhandled and will be "
        "reminded later.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            if (!ReminderCoordinator::GetInstance().SkipCurrentBroadcast()) {
                return McpError{"当前没有可跳过的待办"};
            }
            return std::string("已切换到下一项，当前事项仍会保留");
        });

    server.AddUserOnlyTool(
        "reminder.stop_broadcast",
        "Stop the current to-do broadcast without completing, cancelling or "
        "snoozing the unhandled item.",
        PropertyList(),
        [](const PropertyList&) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            ReminderCoordinator::GetInstance().StopPendingBroadcast();
            return std::string("已停止播报，未处理待办会保留");
        });

    server.AddTool("reminder.close_current",
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

    server.AddTool(
        "reminder.action",
        "Apply an action to a reminder instance. Actions: primary, secondary, "
        "tertiary, silence, undo. Use minutes for a relative secondary/silence "
        "delay, or snooze_at (Unix seconds) for a user-requested clock time.",
        PropertyList({
            Property("instance_id", kPropertyTypeString),
            Property("revision", kPropertyTypeInteger, 1, 2147483647),
            Property("action", kPropertyTypeString),
            Property("minutes", kPropertyTypeInteger, 0, 0, 120),
            Property("snooze_at", kPropertyTypeInteger, 0, 0, 2147483647),
        }),
        [](const PropertyList& properties) -> ReturnValue {
            std::string error;
            if (!CheckReminderWritePermission(error)) return McpError{error};
            ReminderAction action;
            const std::string action_text =
                properties["action"].value<std::string>();
            if (!ReminderCoordinator::ParseAction(action_text, action)) {
                return McpError{"unsupported reminder action"};
            }
            const auto result = ReminderCoordinator::GetInstance().Act(
                properties["instance_id"].value<std::string>(),
                static_cast<uint32_t>(properties["revision"].value<int>()),
                action, properties["minutes"].value<int>(),
                UserContext::GetInstance().GetEffectiveUserId(),
                /*require_presented=*/false, /*touch_action=*/false,
                static_cast<time_t>(properties["snooze_at"].value<int>()));
            if (!result.handled) {
                return McpError{result.code + ": " + result.message};
            }
            return result.message;
        });
}
