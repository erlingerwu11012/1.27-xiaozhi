#pragma once

#include <string>

enum class McpPermission {
    kReadReminder,   // 查看提醒/习惯/备忘录列表
    kWriteReminder,  // 创建/删除/修改提醒
    kReadMemory,     // 查看用户记忆（未来）
    kWriteMemory,    // 写入用户记忆（未来）
    kGeneralChat     // 通用聊天（天气/时间/闲聊）
};

// 检查指定用户是否拥有指定权限
// 返回 true = 允许；false = 拒绝，out_error 填充拒绝原因（可直接返回给 LLM）
bool McpCheckPermission(const std::string& uid, McpPermission perm, std::string& out_error);
