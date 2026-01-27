/*
 * MCP Server Implementation
 * Reference: https://modelcontextprotocol.io/specification/2024-11-05
 */

#include "mcp_server.h"
#include <esp_log.h>
#include <esp_app_desc.h>
#include <algorithm>
#include <cstring>
#include <esp_pthread.h>

/**
 * 环境隔离
 */
enum wifi_mode_t : int;
extern "C" {
    int esp_wifi_get_mode(wifi_mode_t *mode);
}

#include "application.h"
#include "display.h"
#include "oled_display.h"
#include "board.h"
#include "settings.h"
#include "lvgl_theme.h"
#include "lvgl_display.h"

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

void McpServer::AddCommonTools() {
    auto original_tools = std::move(tools_);
    auto& board = Board::GetInstance();

    // 1. 获取设备状态
    AddTool("self.get_device_status", "获取设备的实时状态（音量、屏幕、电量等）。", PropertyList(),
        [&board](const PropertyList& p) -> ReturnValue { return board.GetDeviceStatusJson(); });

    // 2. 音量调节
    AddTool("self.audio_speaker.set_volume", "设置音量 (0-100)。", 
        PropertyList({Property("volume", kPropertyTypeInteger, 0, 100)}), 
        [&board](const PropertyList& p) -> ReturnValue {
            board.GetAudioCodec()->SetOutputVolume(p["volume"].value<int>());
            return true;
        });

#ifdef HAVE_LVGL
    auto display = board.GetDisplay();
    auto camera = board.GetCamera();

    if (display) {
        // 3. 亮度控制
        auto backlight = board.GetBacklight();
        AddTool("self.screen.set_brightness", "设置屏幕亮度 (0-100)。",
            PropertyList({Property("brightness", kPropertyTypeInteger, 0, 100)}),
            [backlight](const PropertyList& p) -> ReturnValue {
                if (backlight) backlight->SetBrightness(static_cast<uint8_t>(p["brightness"].value<int>()), true);
                return true;
            });

        // 4. 主题设置
        if (display->GetTheme() != nullptr) {
            AddTool("self.screen.set_theme", "设置屏幕主题 (light/dark)。",
                PropertyList({Property("theme", kPropertyTypeString)}),
                [display](const PropertyList& p) -> ReturnValue {
                    auto theme = LvglThemeManager::GetInstance().GetTheme(p["theme"].value<std::string>());
                    if (theme) { display->SetTheme(theme); return true; }
                    return false;
                });
        }
    }

    if (camera) {
        // 5. 拍照识物
        AddTool("self.camera.take_photo", "拍照并识别内容。", 
            PropertyList({Property("question", kPropertyTypeString)}),
            [camera](const PropertyList& p) -> ReturnValue {
                TaskPriorityReset priority_reset(1);
                if (!camera->Capture()) throw std::runtime_error("Capture failed");
                return camera->Explain(p["question"].value<std::string>());
            });
    }
#endif
    tools_.insert(tools_.end(), original_tools.begin(), original_tools.end());
}

void McpServer::AddUserOnlyTools() {
    AddUserOnlyTool("self.get_system_info", "获取硬件系统信息。", PropertyList(), 
        [](const PropertyList& p){ return Board::GetInstance().GetSystemInfoJson(); });

    AddUserOnlyTool("self.reboot", "重启设备。", PropertyList(), [](const PropertyList& p){
        Application::GetInstance().Schedule([](){ vTaskDelay(pdMS_TO_TICKS(1000)); Application::GetInstance().Reboot(); });
        return true;
    });

#ifdef HAVE_LVGL
    auto display = dynamic_cast<LvglDisplay*>(Board::GetInstance().GetDisplay());
    if (display) {
        AddUserOnlyTool("self.screen.get_info", "查询屏幕参数。", PropertyList(), [display](const PropertyList& p){
            cJSON *json = cJSON_CreateObject();
            cJSON_AddNumberToObject(json, "width", display->width());
            cJSON_AddNumberToObject(json, "height", display->height());
            return json;
        });
    }
#endif
}

void McpServer::ParseMessage(const std::string& message) {
    if (IsInConfigMode()) return;
    cJSON* json = cJSON_Parse(message.c_str());
    if (json) { ParseMessage(json); cJSON_Delete(json); }
}

void McpServer::ParseMessage(const cJSON* json) {
    if (IsInConfigMode()) return;
    auto m_item = cJSON_GetObjectItem(json, "method");
    if (!m_item || !cJSON_IsString(m_item)) return;
    
    std::string m = m_item->valuestring;
    int id = cJSON_GetObjectItem(json, "id") ? cJSON_GetObjectItem(json, "id")->valueint : 0;

    if (m == "initialize") {
        auto app_desc = esp_app_get_description();
        std::string res = "{\"protocolVersion\":\"2024-11-05\",\"capabilities\":{\"tools\":{}},\"serverInfo\":{\"name\":\"" BOARD_NAME "\",\"version\":\"" + std::string(app_desc->version) + "\"}}";
        ReplyResult(id, res);
    } else if (m == "tools/list") {
        GetToolsList(id, "", false);
    } else if (m == "tools/call") {
        auto p = cJSON_GetObjectItem(json, "params");
        if (p) {
            auto name_item = cJSON_GetObjectItem(p, "name");
            if (name_item) DoToolCall(id, name_item->valuestring, cJSON_GetObjectItem(p, "arguments"));
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

    // 1. 构建标准的 JSON-RPC 响应包
    cJSON* req = cJSON_CreateObject();
    
    // 这里增加 toolName 字段，是为了让服务器区分这是 MCP 的回执
    // 你的服务器端代码需要能识别这个 toolName="mcp_response_tool"
    cJSON* params = cJSON_CreateObject();
    cJSON_AddStringToObject(params, "toolName", "mcp_response_tool"); 
    
    cJSON* args = cJSON_CreateObject();
    // 嵌套 JSON 结构，符合 MCP 协议
    std::string inner = "{\"jsonrpc\":\"2.0\",\"id\":" + std::to_string(id) + ",\"result\":" + result + "}";
    cJSON_AddRawToObject(args, "mcp_data", inner.c_str());
    
    cJSON_AddItemToObject(params, "arguments", args);
    cJSON_AddItemToObject(req, "params", params);
    
    // 2. 序列化为字符串
    char* req_str = cJSON_PrintUnformatted(req);
    if (!req_str) { cJSON_Delete(req); return; }
    
    std::string body(req_str);
    cJSON_free(req_str);
    cJSON_Delete(req);

    // 3. 走 WebSocket 高速通道发送
    ESP_LOGI(TAG, "Sending MCP Reply via WebSocket (ID=%d)", id);
    Application::GetInstance().SendMcpMessage(body);
}

void McpServer::ReplyError(int id, const std::string& message) {
    if (IsInConfigMode()) return;
    std::string err_json = "{\"jsonrpc\":\"2.0\",\"id\":" + std::to_string(id) + ",\"error\":{\"code\":-32000,\"message\":\"" + message + "\"}}";
    ReplyResult(id, err_json);
}

void McpServer::AddTool(McpTool* tool) {
    if (std::find_if(tools_.begin(), tools_.end(), [tool](const McpTool* t) { return t->name() == tool->name(); }) != tools_.end()) return;
    tools_.push_back(tool);
}

void McpServer::AddTool(const std::string& name, const std::string& description, const PropertyList& properties, std::function<ReturnValue(const PropertyList&)> callback) {
    AddTool(new McpTool(name, description, properties, callback));
}

void McpServer::AddUserOnlyTool(const std::string& name, const std::string& description, const PropertyList& properties, std::function<ReturnValue(const PropertyList&)> callback) {
    auto tool = new McpTool(name, description, properties, callback);
    tool->set_user_only(true);
    AddTool(tool);
}

void McpServer::GetToolsList(int id, const std::string& cursor, bool list_user_only_tools) {
    if (IsInConfigMode()) return;
    std::string json = "{\"tools\":[";
    bool first = true;
    for (auto tool : tools_) {
        if (!list_user_only_tools && tool->user_only()) continue;
        if (!first) json += ",";
        json += tool->to_json();
        first = false;
        // 限制长度，防止配网后内存碎片化
        if (json.length() > 7000) break; 
    }
    json += "]}";
    ReplyResult(id, json);
}

void McpServer::DoToolCall(int id, const std::string& tool_name, const cJSON* tool_arguments) {
    if (IsInConfigMode()) return;
    auto it = std::find_if(tools_.begin(), tools_.end(), [&](McpTool* t){ return t->name() == tool_name; });
    if (it == tools_.end()) {
        ReplyError(id, "Tool not found");
        return;
    }
    PropertyList args = (*it)->properties();
    Application::GetInstance().Schedule([this, id, it, args = std::move(args)]() {
        try { ReplyResult(id, (*it)->Call(args)); } 
        catch (const std::exception& e) { ReplyError(id, e.what()); }
    });
}