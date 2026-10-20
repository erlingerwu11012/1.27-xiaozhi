/*
 * MCP Server Implementation
 * Reference: https://modelcontextprotocol.io/specification/2024-11-05
 */

#include "mcp_server.h"
#include "mcp_tools/mcp_tools.h"
#include <esp_log.h>
#include <esp_app_desc.h>
#include <algorithm>
#include <cstdint>
#include <cstring>

/**
 * 环境隔离
 */
enum wifi_mode_t : int;
extern "C" {
    int esp_wifi_get_mode(wifi_mode_t *mode);
}

#include "application.h"
#include "boards/esp-box-3/camera_manager.h"
#include "identity_client.h"
#include "vision_credentials.h"
#include "reminder_control_client.h"
#include "face_enrollment_client.h"
#include "face_enrollment_manager.h"
#include "face_roster.h"
#include "identity_manager.h"
#include "behavior_logger.h"
#include "user_context.h"
#include "person_directory.h"
#include "habit_manager.h"

#define TAG "MCP"

McpServer::McpServer() {}

McpServer::~McpServer() {
    for (auto tool : tools_) delete tool;
    tools_.clear();
}

static bool IsInConfigMode() {
    wifi_mode_t mode = static_cast<wifi_mode_t>(0);
    if (esp_wifi_get_mode(&mode) != 0) return false;
    int m = static_cast<int>(mode);
    bool in_ap = (m == 2 || m == 3);
    if (in_ap) {
        ESP_LOGD(TAG, "MCP logic paused: AP Mode active");
    }
    return in_ap;
}

static void SendMcpRpcResponse(const std::string& rpc_data) {
    cJSON* req = cJSON_CreateObject();
    cJSON* params = cJSON_CreateObject();
    cJSON_AddStringToObject(params, "toolName", "mcp_response_tool");

    cJSON* args = cJSON_CreateObject();
    cJSON_AddRawToObject(args, "mcp_data", rpc_data.c_str());
    cJSON_AddItemToObject(params, "arguments", args);
    cJSON_AddItemToObject(req, "params", params);

    char* req_str = cJSON_PrintUnformatted(req);
    if (!req_str) {
        cJSON_Delete(req);
        return;
    }

    std::string body(req_str);
    cJSON_free(req_str);
    cJSON_Delete(req);

    Application::GetInstance().SendMcpMessage(body);
}

void McpServer::AddCommonTools() {
    auto original_tools = std::move(tools_);

    RegisterDeviceCommonTools(*this);
    RegisterAlarmTools(*this);
    RegisterNoteTools(*this);
    RegisterCardTools(*this);
    RegisterCameraCommonTools(*this);

    tools_.insert(tools_.end(), original_tools.begin(), original_tools.end());
}

void McpServer::AddUserOnlyTools() {
    RegisterDeviceUserTools(*this);
    RegisterHabitTools(*this);
    RegisterCameraUserTools(*this);
}

void McpServer::ParseMessage(const std::string& message,
                             uint32_t connection_generation) {
    if (IsInConfigMode()) return;
    cJSON* json = cJSON_Parse(message.c_str());
    if (json) {
        ParseMessage(json, connection_generation);
        cJSON_Delete(json);
    }
}

void McpServer::ParseMessage(const cJSON* json, uint32_t connection_generation) {
    if (IsInConfigMode()) return;
    auto m_item = cJSON_GetObjectItem(json, "method");
    if (!m_item || !cJSON_IsString(m_item)) return;
    
    std::string m = m_item->valuestring;
    int id = cJSON_GetObjectItem(json, "id") ? cJSON_GetObjectItem(json, "id")->valueint : 0;

    if (m == "initialize") {
        // 解析服务端下发的 vision 配置（params.capabilities.vision）
        auto params = cJSON_GetObjectItem(json, "params");
        auto caps   = cJSON_GetObjectItem(params, "capabilities");
        auto vision = cJSON_GetObjectItem(caps, "vision");
        std::vector<FaceIdentityBinding> face_bindings;
        if (cJSON_IsObject(vision)) {
            auto url   = cJSON_GetObjectItem(vision, "url");
            auto token = cJSON_GetObjectItem(vision, "token");
            auto identity_url = cJSON_GetObjectItem(vision, "identity_url");
            auto vision_session = cJSON_GetObjectItem(vision, "session_id");
            auto expires_at_item = cJSON_GetObjectItem(vision, "expires_at");
            const char* explain = cJSON_IsString(url) ? url->valuestring : "";
            const char* tok =
                cJSON_IsString(token) ? token->valuestring : "";
            const char* identity =
                cJSON_IsString(identity_url) ? identity_url->valuestring : "";
            const char* vision_sid =
                cJSON_IsString(vision_session) && vision_session->valuestring
                    ? vision_session->valuestring
                    : "";
            const int64_t expires_at =
                cJSON_IsNumber(expires_at_item)
                    ? static_cast<int64_t>(expires_at_item->valuedouble)
                    : 0;
            // Use the connection generation captured when this MCP message was
            // received — never re-read active_generation() here.
            if (explain[0] != '\0' && tok[0] != '\0') {
                VisionCredentialStore::GetInstance().ApplyInitializeVision(
                    connection_generation, explain, identity, tok, vision_sid,
                    expires_at);
                // Mirror URL/token onto CameraManager for persistent camera
                // rebuild bookkeeping only; HTTP uploads use the store snapshot.
                CameraManager::GetInstance().SetExplainUrl(explain, tok);
                ESP_LOGI(TAG, "Vision URL set: %s", explain);
            } else {
                ESP_LOGW(TAG,
                         "Vision initialize missing url/token; credentials "
                         "not published generation=%u",
                         static_cast<unsigned>(connection_generation));
            }
            // Keep IdentityClient validation/logging side effects in sync for
            // callers that still query HasIdentityEndpoint before snapshots.
            IdentityClient::GetInstance().SetVisionConfig(
                explain, identity, tok);
            auto* bindings =
                cJSON_GetObjectItem(vision, "face_identity_bindings");
            if (cJSON_IsArray(bindings)) {
                cJSON* item = nullptr;
                cJSON_ArrayForEach(item, bindings) {
                    if (face_bindings.size() >=
                        IdentityManager::kMaxFaceIdentityBindings) {
                        break;
                    }
                    if (!cJSON_IsObject(item)) continue;
                    auto* profile =
                        cJSON_GetObjectItem(item, "face_profile_id");
                    auto* user = cJSON_GetObjectItem(item, "user_id");
                    auto* name = cJSON_GetObjectItem(item, "display_name");
                    if (!cJSON_IsString(profile) || !profile->valuestring ||
                        !cJSON_IsString(user) || !user->valuestring ||
                        !cJSON_IsString(name) || !name->valuestring) {
                        continue;
                    }
                    face_bindings.push_back({profile->valuestring,
                                             user->valuestring,
                                             name->valuestring});
                }
            }
            if (identity[0] == '\0') {
                ESP_LOGW(TAG,
                         "[REMINDER_DELIVERY] event=vision_config "
                         "identity_url missing (server prerequisite)");
            }
        }
        // A missing or malformed snapshot means there are no current server
        // bindings.  This clears stale local mappings after an unbind.
        IdentityManager::GetInstance().ApplyFaceIdentityBindings(
            std::move(face_bindings));
        auto reminder_control =
            cJSON_GetObjectItem(caps, "reminder_control");
        if (cJSON_IsObject(reminder_control)) {
            auto* ctrl_url = cJSON_GetObjectItem(reminder_control, "url");
            auto* ctrl_ver =
                cJSON_GetObjectItem(reminder_control, "protocol_version");
            auto* ctrl_connect = cJSON_GetObjectItem(
                reminder_control, "connect_timeout_ms");
            auto* ctrl_asset = cJSON_GetObjectItem(
                reminder_control, "asset_wait_timeout_ms");
            const char* url =
                cJSON_IsString(ctrl_url) ? ctrl_url->valuestring : "";
            const int version =
                cJSON_IsNumber(ctrl_ver) ? ctrl_ver->valueint : 1;
            const int connect_ms = cJSON_IsNumber(ctrl_connect)
                                       ? ctrl_connect->valueint
                                       : 3000;
            const int asset_ms =
                cJSON_IsNumber(ctrl_asset) ? ctrl_asset->valueint : 8000;
            ReminderControlClient::GetInstance().SetConfig(
                url ? url : "", version, connect_ms, asset_ms);
        } else {
            // Missing / non-object capability must forget any stale URL.
            ReminderControlClient::GetInstance().ClearConfig(
                "capability_missing");
        }
        auto face_enrollment =
            cJSON_GetObjectItem(caps, "face_enrollment");
        if (cJSON_IsObject(face_enrollment)) {
            FaceEnrollmentClient::CapabilityConfig cfg;
            auto* session_url =
                cJSON_GetObjectItem(face_enrollment, "session_url");
            auto* ver =
                cJSON_GetObjectItem(face_enrollment, "protocol_version");
            auto* guided_burst = cJSON_GetObjectItem(
                face_enrollment, "guided_burst_v1");
            auto* timeout = cJSON_GetObjectItem(
                face_enrollment, "session_timeout_seconds");
            auto* required =
                cJSON_GetObjectItem(face_enrollment, "required_frames");
            auto* max_frames =
                cJSON_GetObjectItem(face_enrollment, "max_frames");
            auto* max_bytes =
                cJSON_GetObjectItem(face_enrollment, "max_frame_bytes");
            cfg.session_url = cJSON_IsString(session_url) &&
                                      session_url->valuestring
                                  ? session_url->valuestring
                                  : "";
            cfg.protocol_version =
                cJSON_IsNumber(ver) ? ver->valueint : 1;
            cfg.guided_burst_v1 = cJSON_IsTrue(guided_burst);
            cfg.session_timeout_seconds =
                cJSON_IsNumber(timeout) ? timeout->valueint : 120;
            cfg.required_frames =
                cJSON_IsNumber(required) ? required->valueint : 3;
            cfg.max_frames =
                cJSON_IsNumber(max_frames) ? max_frames->valueint : 5;
            cfg.max_frame_bytes =
                cJSON_IsNumber(max_bytes) ? max_bytes->valueint : 307200;
            auto string_list_contains = [](cJSON* arr,
                                           const char* needle) -> bool {
                if (!cJSON_IsArray(arr) || !needle) return false;
                const cJSON* item = nullptr;
                cJSON_ArrayForEach(item, arr) {
                    if (cJSON_IsString(item) && item->valuestring &&
                        std::strcmp(item->valuestring, needle) == 0) {
                        return true;
                    }
                }
                return false;
            };
            auto* capture_modes = cJSON_GetObjectItem(
                face_enrollment, "supported_capture_modes");
            auto* guidance_profiles = cJSON_GetObjectItem(
                face_enrollment, "supported_guidance_profiles");
            // Missing or non-array => unsupported. Never default-enable.
            cfg.supports_front_only_v1 =
                string_list_contains(capture_modes, "front_only_v1");
            cfg.supports_user_relative_v1 =
                string_list_contains(guidance_profiles, "user_relative_v1");
            auto* enrolled = cJSON_GetObjectItem(
                face_enrollment, "enrolled_count");
            if (!enrolled) {
                enrolled = cJSON_GetObjectItem(
                    face_enrollment, "face_template_count");
            }
            const bool count_present =
                cJSON_IsNumber(enrolled) &&
                enrolled->valuedouble == enrolled->valueint;
            const int count =
                count_present ? enrolled->valueint : -1;
            auto* default_owner = cJSON_GetObjectItem(
                face_enrollment, "default_owner_person_id");
            if (!default_owner) {
                default_owner = cJSON_GetObjectItem(
                    face_enrollment, "default_owner_id");
            }
            std::string default_owner_id;
            if (cJSON_IsString(default_owner) && default_owner->valuestring) {
                default_owner_id = default_owner->valuestring;
            }
            FaceRoster::GetInstance().ApplyInitialize(
                Application::GetInstance().GetAudioSessionId(),
                count_present, count, default_owner_id, "initialize");
            FaceEnrollmentClient::GetInstance().SetCapability(cfg);
            if (!FaceEnrollmentClient::GetInstance().HasValidCapability()) {
                FaceEnrollmentManager::GetInstance().OnCapabilityCleared();
            }
        } else {
            FaceRoster::GetInstance().ApplyInitialize(
                Application::GetInstance().GetAudioSessionId(),
                /*count_present=*/false, -1, "",
                "initialize_face_enrollment_missing");
            FaceEnrollmentManager::GetInstance().OnCapabilityCleared();
            FaceEnrollmentClient::GetInstance().ClearCapability(
                "capability_missing");
        }
        PersonDirectory::GetInstance().Invalidate();
        auto app_desc = esp_app_get_description();
        std::string res = "{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{\"tools\":{},\"experimental\":{\"personalIdentity\":2,\"identityCleanup\":2,\"personBehavior\":2,\"weeklySchedule\":2,\"habitSync\":1,\"visionStatus\":1}},\"serverInfo\":{\"name\":\"" BOARD_NAME "\",\"version\":\"" + std::string(app_desc->version) + "\"}}";
        ReplyResult(id, res);
    } else if (m == "vision/status" || m == "vision/refresh") {
        auto& store = VisionCredentialStore::GetInstance();
        auto params = cJSON_GetObjectItem(json, "params");
        auto sid = cJSON_GetObjectItem(params, "session_id");
        const auto session = Application::GetInstance().GetAudioSessionId();
        if (!store.IsGenerationAccepting(connection_generation) || session.empty() ||
            !cJSON_IsString(sid) || session != sid->valuestring) {
            ReplyError(id, "vision_session_mismatch"); return;
        }
        if (m == "vision/refresh") {
            auto cap = cJSON_GetObjectItem(params, "vision");
            auto url = cJSON_GetObjectItem(cap, "url");
            auto identity = cJSON_GetObjectItem(cap, "identity_url");
            auto token = cJSON_GetObjectItem(cap, "token");
            auto expires = cJSON_GetObjectItem(cap, "expires_at");
            auto cap_session = cJSON_GetObjectItem(cap, "session_id");
            if (!cJSON_IsString(url) || !cJSON_IsString(identity) || !cJSON_IsString(token) ||
                !cJSON_IsString(cap_session) || session != cap_session->valuestring || !cJSON_IsNumber(expires)) {
                ReplyError(id, "invalid_vision_capability"); return;
            }
            store.ApplyInitializeVision(connection_generation, url->valuestring, identity->valuestring,
                token->valuestring, session, static_cast<int64_t>(expires->valuedouble));
        }
        cJSON* result = cJSON_CreateObject();
        cJSON_AddStringToObject(result, "session_id", session.c_str());
        cJSON_AddNumberToObject(result, "generation", connection_generation);
        cJSON_AddBoolToObject(result, "explain_ready", store.IsExplainReady());
        cJSON_AddBoolToObject(result, "identity_ready", store.IsIdentityReady());
        cJSON_AddStringToObject(result, "explain_reason", store.ExplainNotReadyReason().c_str());
        cJSON_AddStringToObject(result, "identity_reason", store.IdentityNotReadyReason().c_str());
        char* encoded = cJSON_PrintUnformatted(result);
        ReplyResult(id, encoded ? encoded : "{}");
        cJSON_free(encoded); cJSON_Delete(result);
    } else if (m == "identity/sync") {
        auto params = cJSON_GetObjectItem(json, "params");
        ReplyResult(id, PersonDirectory::GetInstance().Apply(params));
    } else if (m == "habit/sync") {
        auto params = cJSON_GetObjectItem(json, "params");
        auto encoded = cJSON_PrintUnformatted(params);
        if (!encoded) { ReplyError(id,"invalid_config"); return; }
        const std::string payload(encoded); cJSON_free(encoded);
        const auto session = Application::GetInstance().GetAudioSessionId();
        Application::GetInstance().Schedule([this,id,payload,session]() {
            if (session.empty() || session != Application::GetInstance().GetAudioSessionId()) return;
            auto p = cJSON_Parse(payload.c_str());
            auto account = cJSON_GetObjectItem(p,"account_id"), recipient = cJSON_GetObjectItem(p,"recipient_person_id"), version = cJSON_GetObjectItem(p,"directory_version");
            if (!cJSON_IsString(account) || !cJSON_IsString(recipient) || !cJSON_IsNumber(version) || version->valuedouble < 1 || version->valuedouble > 9007199254740991.0 ||
                version->valuedouble != static_cast<uint64_t>(version->valuedouble))
                ReplyResult(id,"{\"ok\":false,\"persisted\":false,\"error\":\"identity_mismatch\"}");
            else ReplyResult(id,PersonDirectory::GetInstance().WithManagement(account->valuestring,static_cast<uint64_t>(version->valuedouble),recipient->valuestring,
                [p]() { return HabitManager::GetInstance().Sync(p); }));
            cJSON_Delete(p);
        });
    } else if (m == "behavior/export") {
        auto params = cJSON_GetObjectItem(json, "params");
        auto identity = cJSON_GetObjectItem(params, "actor");
        auto text = [identity](const char* key) -> std::string {
            auto item = cJSON_GetObjectItem(identity, key);
            return cJSON_IsString(item) ? item->valuestring : "";
        };
        auto number = [identity](const char* key) -> uint64_t {
            auto item = cJSON_GetObjectItem(identity, key);
            return cJSON_IsNumber(item) && item->valuedouble >= 0 ? item->valuedouble : 0;
        };
        PersonTurn actor;
        actor.account_id = text("account_id"); actor.person_id = text("person_id");
        actor.turn_id = text("turn_id"); actor.status = text("status");
        actor.voiceprint_id = text("voiceprint_id"); actor.template_version = number("template_version");
        actor.directory_version = number("directory_version"); actor.generation = number("generation");
        auto cursor = cJSON_GetObjectItem(params, "after"); char* end = nullptr;
        uint64_t after = cJSON_IsString(cursor) ? strtoull(cursor->valuestring, &end, 10) : 0;
        if (!PersonDirectory::GetInstance().Accepts(actor) || !end || *end || cursor->valuestring[0] == '-')
            ReplyError(id, "invalid_behavior_export");
        else ReplyResult(id, BehaviorLogger::GetInstance().Export(actor.person_id, after));
    } else if (m == "tools/list") {
        std::string cursor;
        auto params = cJSON_GetObjectItem(json, "params");
        auto cursor_item = params
            ? cJSON_GetObjectItem(params, "cursor") : nullptr;
        if (cJSON_IsString(cursor_item) && cursor_item->valuestring) {
            cursor = cursor_item->valuestring;
        }
        GetToolsList(
            id, cursor,
            UserContext::GetInstance().GetEffectiveUserId() != "guest");
    } else if (m == "tools/call") {
        auto p = cJSON_GetObjectItem(json, "params");
        if (p) {
            auto name_item = cJSON_GetObjectItem(p, "name");
            PersonTurn actor;
            auto meta = cJSON_GetObjectItem(p, "_meta");
            auto identity = meta ? cJSON_GetObjectItem(meta, "person_turn") : nullptr;
            if (cJSON_IsObject(identity)) {
                auto text = [identity](const char* key) -> std::string {
                    auto value = cJSON_GetObjectItem(identity, key);
                    return cJSON_IsString(value) && value->valuestring ? value->valuestring : "";
                };
                auto number = [identity](const char* key) -> uint64_t {
                    auto value = cJSON_GetObjectItem(identity, key);
                    return cJSON_IsNumber(value) && value->valuedouble >= 0
                        ? static_cast<uint64_t>(value->valuedouble) : 0;
                };
                actor.person_id = text("person_id"); actor.turn_id = text("turn_id");
                actor.status = text("status"); actor.display_name = text("display_name");
                actor.account_id = text("account_id"); actor.voiceprint_id = text("voiceprint_id");
                actor.template_version = number("template_version");
                actor.directory_version = number("directory_version");
                actor.generation = number("generation"); actor.listen_epoch = number("listen_epoch");
                if (!IsPersonId(actor.person_id) || actor.turn_id.size() > 64) actor = {};
            }
            if (cJSON_IsString(name_item)) DoToolCall(id, name_item->valuestring,
                cJSON_GetObjectItem(p, "arguments"), actor);
        }
    }
}

// =================================================================================
// 【核心修改】ReplyResult 函数重构
// 1. 移除了所有 HTTP Client 代码（删除了对 8123 端口的连接）
// 2. 改为使用 Application::SendMcpMessage 通过 WebSocket 回传
// 3. 彻底解决了 AFE 因为等待 HTTP 响应而卡死的问题
// =================================================================================
void McpServer::ReplyResult(int id, const std::string& result) {
    if (IsInConfigMode()) return;
    std::string inner = "{\"jsonrpc\":\"2.0\",\"id\":" + std::to_string(id) + ",\"result\":" + result + "}";
    ESP_LOGI(TAG, "Sending MCP Reply via WebSocket (ID=%d)", id);
    SendMcpRpcResponse(inner);
}

void McpServer::ReplyError(int id, const std::string& message) {
    if (IsInConfigMode()) return;
    cJSON* error = cJSON_CreateObject();
    cJSON_AddStringToObject(error, "jsonrpc", "2.0");
    cJSON_AddNumberToObject(error, "id", id);
    cJSON* detail = cJSON_CreateObject();
    cJSON_AddNumberToObject(detail, "code", -32000);
    cJSON_AddStringToObject(detail, "message", message.c_str());
    cJSON_AddItemToObject(error, "error", detail);
    char* error_str = cJSON_PrintUnformatted(error);
    if (error_str) {
        ESP_LOGW(TAG, "Sending MCP error via WebSocket (ID=%d): %s", id, message.c_str());
        SendMcpRpcResponse(error_str);
        cJSON_free(error_str);
    }
    cJSON_Delete(error);
}

void McpServer::AddTool(McpTool* tool) {
    if (std::find_if(tools_.begin(), tools_.end(), [tool](const McpTool* t) { return t->name() == tool->name(); }) != tools_.end()) return;
    tools_.push_back(tool);
}

void McpServer::AddTool(const std::string& name, const std::string& description, const PropertyList& properties, std::function<ReturnValue(const PropertyList&)> callback) {
    AddTool(new McpTool(name, description, properties, callback));
}

void McpServer::AddAsyncTool(const std::string& name, const std::string& description,
                             const PropertyList& properties,
                             std::function<void(const PropertyList&, std::function<void(ReturnValue)>)> callback) {
    AddTool(new McpTool(name, description, properties, std::move(callback)));
}

void McpServer::AddUserOnlyTool(const std::string& name, const std::string& description, const PropertyList& properties, std::function<ReturnValue(const PropertyList&)> callback) {
    auto tool = new McpTool(name, description, properties, callback);
    tool->set_user_only(true);
    AddTool(tool);
}

void McpServer::GetToolsList(int id, const std::string& cursor, bool list_user_only_tools) {
    if (IsInConfigMode()) return;
    size_t start = 0;
    if (!cursor.empty()) {
        try {
            size_t consumed = 0;
            start = std::stoul(cursor, &consumed);
            if (consumed != cursor.size()) throw std::invalid_argument("cursor");
        } catch (...) {
            ReplyError(id, "Invalid tools/list cursor");
            return;
        }
    }
    std::string json = "{\"tools\":[";
    bool first = true;
    size_t visible_index = 0;
    size_t next_cursor = 0;
    bool has_more = false;
    constexpr size_t kMaxPageBytes = 6000;
    for (auto tool : tools_) {
        if (!list_user_only_tools && tool->user_only()) continue;
        if (visible_index++ < start) continue;
        const std::string serialized = tool->to_json();
        const size_t extra = serialized.size() + (first ? 0 : 1);
        if (!first && json.size() + extra + 64 > kMaxPageBytes) {
            has_more = true;
            next_cursor = visible_index - 1;
            break;
        }
        if (!first) json += ",";
        json += serialized;
        first = false;
    }
    json += "]";
    if (has_more) {
        json += ",\"nextCursor\":\"" + std::to_string(next_cursor) + "\"";
    }
    json += "}";
    ReplyResult(id, json);
}

void McpServer::DoToolCall(int id, const std::string& tool_name, const cJSON* tool_arguments,
                           const PersonTurn& actor) {
    if (IsInConfigMode()) return;
    auto it = std::find_if(tools_.begin(), tools_.end(), [&](McpTool* t){ return t->name() == tool_name; });
    if (it == tools_.end()) {
        ReplyError(id, "Tool not found");
        return;
    }
    PropertyList args = (*it)->properties();
    try {
        args.ApplyJsonArguments(tool_arguments);
    } catch (const std::exception& e) {
        ReplyError(id, e.what());
        return;
    }

    McpTool* tool = *it;
    const bool session_independent = tool->session_independent();
    if (tool->user_only() &&
        UserContext::GetInstance().GetEffectiveUserId() == "guest") {
        ReplyError(id, "User authorization is required for this tool");
        return;
    }
    Application::GetInstance().Schedule([this, id, tool, actor, args = std::move(args),
                                         session_independent,
                                         session_at_request =
                                             Application::GetInstance()
                                                 .GetAudioSessionId()]() {
        if (!session_independent &&
            session_at_request !=
                Application::GetInstance().GetAudioSessionId()) {
            ESP_LOGW(TAG,
                     "Dropping MCP tool reply id=%d reason=session_mismatch",
                     id);
            ReplyError(id, "session_mismatch: audio session changed");
            return;
        }
        try {
        PersonTurn checked = actor;
        if (!PersonDirectory::GetInstance().Accepts(actor)) checked = {};
        PersonTurnScope actor_scope(checked);
        if (tool->is_async()) {
            tool->CallAsync(args, [this, id, session_at_request,
                                   session_independent](ReturnValue value) {
                // Completion runs on the worker task.  Marshal the WebSocket
                // reply back to the application event loop and drop stale
                // replies after a session rollover.
                Application::GetInstance().Schedule([this, id, session_at_request,
                                                      session_independent,
                                                      value = std::move(value)]() mutable {
                    if (!session_independent &&
                        session_at_request != Application::GetInstance().GetAudioSessionId()) {
                        ESP_LOGW(TAG, "Dropping async MCP reply id=%d reason=session_mismatch", id);
                        ReplyError(id, "session_mismatch: audio session changed");
                        return;
                    }
                    ReplyResult(id, McpTool::Serialize(value));
                });
            });
        } else {
            ReplyResult(id, tool->Call(args));
        }
        } catch (const std::exception& e) { ReplyError(id, e.what()); }
    });
}
