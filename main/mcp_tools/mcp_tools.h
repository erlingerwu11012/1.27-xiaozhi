#pragma once

/**
 * MCP Tools - 模块化工具注册
 * 
 * 每个模块提供两个注册函数：
 *   RegisterXxxCommonTools()  - 云端+用户均可见的工具
 *   RegisterXxxUserTools()    - 仅用户可见的工具
 * 
 * 在 mcp_server.cc 的 AddCommonTools() / AddUserOnlyTools() 中调用。
 */

class McpServer;

// ── 设备工具（音量、亮度、主题、系统信息、重启）──
void RegisterDeviceCommonTools(McpServer& server);
void RegisterDeviceUserTools(McpServer& server);

// ── 闹钟工具（alarm.set/list/delete/dismiss/snooze）──
void RegisterAlarmTools(McpServer& server);

// ── 备忘录工具（note.add/list/delete/snooze）──
void RegisterNoteTools(McpServer& server);

// ── 习惯 + 行为日志工具 ──
void RegisterHabitTools(McpServer& server);

// ── 当前卡片操作工具（语音与触摸共用）──
void RegisterCardTools(McpServer& server);

// ── 摄像头工具（拍照、认人、预览、人脸注册）──
void RegisterCameraCommonTools(McpServer& server);
void RegisterCameraUserTools(McpServer& server);
