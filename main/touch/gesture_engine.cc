/**
 * @file gesture_engine.cc
 * @brief 手势识别引擎实现 - 异步状态机
 */

#include "touch/gesture_engine.h"

#include <cmath>
#include <algorithm>

#include "esp_log.h"

static const char* TAG = "GestureEngine";

namespace touch {

namespace {

constexpr float kPi = 3.14159265358979323846f;
constexpr float kTwoPi = 6.28318530717958647692f;

float Atan2Approx(float dy, float dx) {
    if (dx == 0 && dy == 0) return 0;
    return atan2f(dy, dx);
}

/** 角度差 [-pi, pi] */
float AngleDiff(float a, float b) {
    float d = a - b;
    while (d > kPi) d -= kTwoPi;
    while (d < -kPi) d += kTwoPi;
    return d;
}

const char* GestureTypeStr(GestureType t) {
    switch (t) {
        case GESTURE_TAP: return "TAP";
        case GESTURE_DOUBLE_TAP: return "DOUBLE_TAP";
        case GESTURE_LONG_PRESS: return "LONG_PRESS";
        case GESTURE_SWIPE_LEFT: return "SWIPE_LEFT";
        case GESTURE_SWIPE_RIGHT: return "SWIPE_RIGHT";
        case GESTURE_SWIPE_UP: return "SWIPE_UP";
        case GESTURE_SWIPE_DOWN: return "SWIPE_DOWN";
        case GESTURE_CIRCLE: return "CIRCLE";
        default: return "?";
    }
}

}  // namespace

GestureZone GestureEngine::GetZone(float y) {
    if (y < 0.4f) return GESTURE_ZONE_HEAD;
    if (y < 0.8f) return GESTURE_ZONE_FACE;
    return GESTURE_ZONE_BOTTOM;
}

GestureEngine::GestureEngine() : touch_manager_(nullptr) {}

void GestureEngine::Update(int64_t now_ms) {
    if (touch_manager_ == nullptr) return;

    TouchPoint pt;
    if (!touch_manager_->GetState(&pt)) return;

    switch (state_) {
    case IDLE:
        if (pt.touched) {
            OnTouchDown(pt.x, pt.y, now_ms);
            state_ = PRESSED;
        }
        break;

    case PRESSED:
        if (!pt.touched) {
            OnTouchUp(last_x_, last_y_, now_ms);
            state_ = IDLE;
        } else {
            OnTouchMove(pt.x, pt.y, now_ms);
            if (std::abs(pt.x - down_x_) > kTapMaxMove || std::abs(pt.y - down_y_) > kTapMaxMove) {
                state_ = MOVING;
            }
            /* 长按检测：未进入 MOVING 且超时 */
            if (state_ == PRESSED && !long_press_fired_ && (now_ms - down_time_ms_ >= kLongPressMs)) {
                long_press_fired_ = true;
                Emit(GESTURE_LONG_PRESS, GetZone(down_y_), down_x_, down_y_);
            }
        }
        break;

    case MOVING:
        if (!pt.touched) {
            OnTouchUp(last_x_, last_y_, now_ms);
            state_ = IDLE;
        } else {
            OnTouchMove(pt.x, pt.y, now_ms);
        }
        break;
    }
}

void GestureEngine::OnTouchDown(float x, float y, int64_t now_ms) {
    ESP_LOGI(TAG, "[Gesture] touch DOWN (%.2f, %.2f) zone=%s", x, y,
             GetZone(y) == GESTURE_ZONE_HEAD ? "HEAD" : (GetZone(y) == GESTURE_ZONE_FACE ? "FACE" : "BOTTOM"));
    down_x_ = x;
    down_y_ = y;
    down_time_ms_ = now_ms;
    last_x_ = x;
    last_y_ = y;
    max_dx_ = 0;
    max_dy_ = 0;
    long_press_fired_ = false;
    ResetCircleTracker();
    circle_center_x_ = x;
    circle_center_y_ = y;
    circle_point_count_ = 0;
}

void GestureEngine::OnTouchMove(float x, float y, int64_t now_ms) {
    float dx = x - down_x_;
    float dy = y - down_y_;
    max_dx_ = std::max(max_dx_, std::abs(dx));
    max_dy_ = std::max(max_dy_, std::abs(dy));

    /* 画圈检测：仅 FaceZone */
    if (IsInFaceZone(down_y_)) {
        float cx = circle_center_x_;
        float cy = circle_center_y_;
        float rx = x - cx;
        float ry = y - cy;
        float r = std::sqrt(rx * rx + ry * ry);
        if (r >= kCircleMinRadius) {
            circle_point_count_++;
            float angle = Atan2Approx(ry, rx);
            if (circle_point_count_ >= 2) {
                float da = AngleDiff(angle, circle_last_angle_);
                circle_angle_sum_ += std::abs(da);
            }
            circle_last_angle_ = angle;
        }
    }

    last_x_ = x;
    last_y_ = y;
}

void GestureEngine::OnTouchUp(float x, float y, int64_t now_ms) {
    (void)x;
    (void)y;
    int64_t duration_ms = now_ms - down_time_ms_;
    GestureZone zone = GetZone(down_y_);

    /* 调试：滑动结束时的位移与状态（320×240 屏归一化→像素约值） */
    const char* state_str = (state_ == MOVING) ? "MOVING" : ((state_ == PRESSED) ? "PRESSED" : "IDLE");
    ESP_LOGI(TAG, "[Gesture] 滑动结束: state=%s max_dx=%.3f max_dy=%.3f duration=%lums (约%d,%d px)",
             state_str, max_dx_, max_dy_, (unsigned long)duration_ms,
             (int)(max_dx_ * 320.0f), (int)(max_dy_ * 240.0f));

    /* 双击：本次为短按，且与上次 TAP 在时间窗内且距离近 */
    if (state_ == PRESSED && !long_press_fired_ &&
        max_dx_ <= kTapMaxMove && max_dy_ <= kTapMaxMove &&
        duration_ms >= kTapMinDurationMs && duration_ms < 500) {
        float dist = std::sqrt((down_x_ - last_tap_x_) * (down_x_ - last_tap_x_) +
                            (down_y_ - last_tap_y_) * (down_y_ - last_tap_y_));
        if (now_ms - last_tap_time_ms_ <= kDoubleTapWindowMs && dist <= kDoubleTapMaxDist) {
            Emit(GESTURE_DOUBLE_TAP, zone, down_x_, down_y_);
            last_tap_time_ms_ = -10000;
            return;
        }
        last_tap_time_ms_ = now_ms;
        last_tap_x_ = down_x_;
        last_tap_y_ = down_y_;
        Emit(GESTURE_TAP, zone, down_x_, down_y_);
        return;
    }

    const float dx = last_x_ - down_x_;
    const float dy = last_y_ - down_y_;
    const float abs_dx = std::abs(dx), abs_dy = std::abs(dy);

    /* 画圈需要回到起点附近，避免曲折滑动抢占上下滑。 */
    if (IsInFaceZone(down_y_) && circle_point_count_ >= kCircleMinPoints &&
        circle_angle_sum_ >= kCircleAngleThreshold &&
        std::sqrt(dx * dx + dy * dy) < kSwipeMinDist) {
        Emit(GESTURE_CIRCLE, zone, last_x_, last_y_);
        return;
    }

    // Axis and direction must use the same final displacement. Historical
    // extrema can select a different axis after the finger corrects its path.
    // Ambiguous diagonal strokes and out-and-back strokes perform no action.
    if (state_ == MOVING && (abs_dx >= kSwipeMinDist || abs_dy >= kSwipeMinDist)) {
        if (abs_dx >= kSwipeMinDist && abs_dx >= abs_dy * kSwipeAxisDominance) {
            Emit(dx > 0 ? GESTURE_SWIPE_RIGHT : GESTURE_SWIPE_LEFT, zone, last_x_, last_y_);
        } else if (abs_dy >= kSwipeMinDist && abs_dy >= abs_dx * kSwipeAxisDominance) {
            Emit(dy > 0 ? GESTURE_SWIPE_DOWN : GESTURE_SWIPE_UP, zone, last_x_, last_y_);
        }
        return;
    }

    /* 未达滑动阈值时可能识别为 TAP */
    if (state_ == MOVING) {
        ESP_LOGI(TAG, "[Gesture] 判定结果=未达滑动阈值(max_dx=%.3f max_dy=%.3f < %.3f)，降级为TAP",
                 max_dx_, max_dy_, kSwipeMinDist);
    }

    /* 单次点击（按下期间有轻微移动但仍算 TAP） */
    if (!long_press_fired_ && max_dx_ <= kTapMaxMove && max_dy_ <= kTapMaxMove &&
        duration_ms >= kTapMinDurationMs && duration_ms < 500) {
        last_tap_time_ms_ = now_ms;
        last_tap_x_ = down_x_;
        last_tap_y_ = down_y_;
        Emit(GESTURE_TAP, zone, down_x_, down_y_);
    }
}

static const char* ZoneStr(GestureZone z) {
    return z == GESTURE_ZONE_HEAD ? "HEAD" : (z == GESTURE_ZONE_FACE ? "FACE" : "BOTTOM");
}

void GestureEngine::Emit(GestureType type, GestureZone zone, float x, float y) {
    ESP_LOGI(TAG, "[Gesture] EMIT %s zone=%s (%.2f, %.2f)", GestureTypeStr(type), ZoneStr(zone), x, y);
#if CONFIG_TOUCH_DIAGNOSTICS
    ESP_LOGI(TAG, "[TOUCH_DIAG] gesture=%s zone=%s", GestureTypeStr(type), ZoneStr(zone));
#endif
    pending_ = {type, zone, x, y, down_x_, down_y_};
    has_pending_ = true;
    if (callback_) {
        callback_(pending_);
    }
}

bool GestureEngine::PollGesture(GestureEvent* out) {
    if (out == nullptr || !has_pending_) return false;
    *out = pending_;
    has_pending_ = false;
    return true;
}

void GestureEngine::ResetCircleTracker() {
    circle_angle_sum_ = 0;
    circle_last_angle_ = 0;
    circle_point_count_ = 0;
}

}  // namespace touch
