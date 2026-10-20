#pragma once

#include <cstdint>
#include <functional>

/**
 * @brief MCP display_hint 卡片数据结构
 *
 * 所有 char* 字段由 strdup() 分配，所有权由 ShowMcpCard() 接管。
 * 必须在 DismissMcpCard() 或 LcdDisplay 析构时逐一 free()。
 * 未使用的 items[] 槽置 nullptr。
 */
struct McpCardData {
    char*    icon;           // Font Awesome Unicode 字符，可为 nullptr
    char*    title;          // 卡片标题，可为 nullptr
    char*    items[4];       // 最多 4 行内容，未用槽为 nullptr
    int      item_count;     // 有效 items 数量，范围 [0, 4]
    char*    status;         // "ok" / "error" / "loading" / "alarm" / "remind" / "habit"
    uint32_t auto_dismiss_ms; // 0 = 不自动关闭

    // 主动播报系统扩展：条目完成回调
    // key 格式: "alarm:1" / "habit:2" / "note:3"
    char*    item_keys[4];   // 每个条目对应的 key，未用槽为 nullptr
    std::function<void(const char* key)> on_item_complete;  // 条目点击完成回调

    // 当前提醒卡片的唯一身份。触摸和语音均通过此键操作同一条本地数据。
    char*    action_key;     // "alarm:1" / "habit:2" / "note:3"，无操作时为 nullptr
    char*    owner_user_id;  // 提醒所属用户，公共提醒为 "default"

    // 统一提醒实例快照。UI 只能回传 instance_id + revision，不持有业务对象指针。
    char*    instance_id;
    uint32_t revision;
    char*    priority;       // "high" / "normal" / "low"
    char*    primary_label;
    char*    secondary_label;
    char*    tertiary_label;
    int      queue_count;
    bool     privacy_mode;
};
