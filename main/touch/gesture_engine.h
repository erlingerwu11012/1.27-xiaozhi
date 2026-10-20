/**
 * @file gesture_engine.h
 * @brief 手势识别引擎 - 基于 TouchManager 归一化坐标
 *
 * 异步非阻塞状态机，识别 TAP/DOUBLE_TAP/LONG_PRESS/SWIPE/CIRCLE。
 */

#pragma once

#include "touch_manager.h"
#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/** 区域：y < 0.4 头部，0.4 <= y < 0.8 脸部，y >= 0.8 底部 */
typedef enum {
    GESTURE_ZONE_HEAD = 0,   /**< y < 0.4 */
    GESTURE_ZONE_FACE = 1,   /**< 0.4 <= y < 0.8 */
    GESTURE_ZONE_BOTTOM = 2, /**< y >= 0.8 */
} GestureZone;

/** 识别到的手势类型 */
typedef enum {
    GESTURE_NONE = 0,
    GESTURE_TAP,
    GESTURE_DOUBLE_TAP,
    GESTURE_LONG_PRESS,
    GESTURE_SWIPE_LEFT,
    GESTURE_SWIPE_RIGHT,
    GESTURE_SWIPE_UP,
    GESTURE_SWIPE_DOWN,
    GESTURE_CIRCLE,
} GestureType;

/** 手势事件（带发生区域） */
typedef struct {
    GestureType type;
    GestureZone zone;
    float x;  /**< 释放点归一化 x */
    float y;  /**< 释放点归一化 y */
    float start_x;  /**< 按下点归一化 x */
    float start_y;  /**< 按下点归一化 y */
} GestureEvent;

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus

#include <functional>

namespace touch {

class TouchManager;

/**
 * @brief 手势识别引擎
 *
 * 在 update 中消费 TouchManager 状态，通过状态机输出手势事件。
 * 非阻塞：严禁在 Update 中使用 delay()。
 */
class GestureEngine {
public:
    using GestureCallback = std::function<void(const GestureEvent&)>;

    GestureEngine();
    ~GestureEngine() = default;

    GestureEngine(const GestureEngine&) = delete;
    GestureEngine& operator=(const GestureEngine&) = delete;

    /**
     * @brief 绑定 TouchManager
     */
    void SetTouchManager(TouchManager* tm) { touch_manager_ = tm; }

    /**
     * @brief 设置手势回调（主循环或显示回调中调用 Update 后触发）
     */
    void SetCallback(GestureCallback cb) { callback_ = std::move(cb); }

    /**
     * @brief 每帧调用，非阻塞状态机更新
     * @param now_ms 当前时间戳（毫秒），可用 esp_timer_get_time()/1000
     */
    void Update(int64_t now_ms);

    /**
     * @brief 获取最近一次识别到的手势（未消费可重复读取）
     * @return 有则填 out 并返回 true，否则 false
     */
    bool PollGesture(GestureEvent* out);

private:
    static GestureZone GetZone(float y);
    void OnTouchDown(float x, float y, int64_t now_ms);
    void OnTouchMove(float x, float y, int64_t now_ms);
    void OnTouchUp(float x, float y, int64_t now_ms);
    void Emit(GestureType type, GestureZone zone, float x, float y);
    bool IsInFaceZone(float y) const { return y < 0.8f; }
    void ResetCircleTracker();

    TouchManager* touch_manager_ = nullptr;
    GestureCallback callback_;

    enum State {
        IDLE,
        PRESSED,
        MOVING,
    };
    State state_ = IDLE;
    float down_x_ = 0, down_y_ = 0;
    int64_t down_time_ms_ = 0;
    float last_x_ = 0, last_y_ = 0;
    float max_dx_ = 0, max_dy_ = 0;   /* 按下期间最大位移 */
    bool long_press_fired_ = false;

    /* 双击 */
    int64_t last_tap_time_ms_ = -10000;
    float last_tap_x_ = 0, last_tap_y_ = 0;
    static constexpr int64_t kDoubleTapWindowMs = 400;
    static constexpr float kDoubleTapMaxDist = 0.15f;

    /* 长按 */
    static constexpr int64_t kLongPressMs = 800;
    /* TAP 最小有效按压时长：去抖后仍要求 >=40ms，过滤极短接触毛刺 */
    static constexpr int64_t kTapMinDurationMs = 40;

    /* 滑动：最小位移比例（降低门槛以提升灵敏度） */
    static constexpr float kSwipeAxisDominance = 1.25f;
    static constexpr float kSwipeMinDist = 0.1f;   /* 0.2→0.1：约 32px/24px 即可触发 */
    static constexpr float kTapMaxMove = 0.04f;    /* 0.08→0.04：约 13px/10px 即进入 MOVING */

    /* 画圈 */
    static constexpr int kCircleMinPoints = 12;
    static constexpr float kCircleMinRadius = 0.15f;
    static constexpr float kCircleAngleThreshold = 5.0f;  /* ~2.5 圈 弧度 */
    float circle_center_x_ = 0, circle_center_y_ = 0;
    float circle_last_angle_ = 0;
    float circle_angle_sum_ = 0;
    int circle_point_count_ = 0;
    bool circle_clockwise_ = true;

    GestureEvent pending_ = {GESTURE_NONE, GESTURE_ZONE_BOTTOM, 0, 0, 0, 0};
    bool has_pending_ = false;
};

}  // namespace touch

#endif /* __cplusplus */
