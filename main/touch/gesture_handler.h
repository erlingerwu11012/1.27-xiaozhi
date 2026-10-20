/**
 * @file gesture_handler.h
 * @brief 将 GestureEngine 事件映射到 Stack-chan / Display / 系统行为
 *
 * - 单击唤醒 AI，双击停止当前任务
 * - 卡片左右滑处理完成/延后
 * - 左右区域上下滑分别调节亮度/音量
 * - 长按保留为无操作（触摸诊断由配置项单独控制）
 */
#pragma once

#include "gesture_engine.h"
#include "touch_manager.h"
#include <functional>
#include <cstdint>

class Board;
class Display;
class AudioCodec;

namespace touch {

class GestureEngine;
class TouchManager;

class GestureHandler {
public:
    GestureHandler();
    ~GestureHandler();

    GestureHandler(const GestureHandler&) = delete;
    GestureHandler& operator=(const GestureHandler&) = delete;

    /**
     * @brief 绑定 Board（用于 Display、AudioCodec）
     */
    void SetBoard(Board* board) { board_ = board; }

    /**
     * @brief 绑定 GestureEngine，注册回调
     */
    void Attach(GestureEngine* engine);

private:
    void OnGesture(const GestureEvent& e);
    void ScheduleVisual(std::function<void()> fn);

    Board* board_ = nullptr;
    GestureEngine* engine_ = nullptr;
    /* 播报期间被忽略单击的日志限频（毫秒） */
    int64_t last_tap_ignored_ms_ = 0;

};

}  // namespace touch
