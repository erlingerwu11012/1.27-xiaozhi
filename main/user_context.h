#pragma once

#include <string>
#include <mutex>
#include <esp_timer.h>
#include "person_turn.h"

class UserContext {
public:
    static UserContext& GetInstance() {
        static UserContext instance;
        return instance;
    }

    static constexpr uint64_t kSessionTimeoutMs = 120000;  // 120s 异常兜底

    // ── 在场用户（摄像头识别结果，只用于问候和陪伴体验）──
    void SetPresenceFace(const std::string& face_id) {
        std::lock_guard<std::mutex> lock(mutex_);
        presence_face_ = face_id;
    }

    std::string GetPresenceFace() {
        std::lock_guard<std::mutex> lock(mutex_);
        return presence_face_;
    }

    void ClearPresenceFace() {
        std::lock_guard<std::mutex> lock(mutex_);
        presence_face_.clear();
    }

    void SetCurrentPresentUser(const std::string& user_id,
                               const std::string& display_name = "") {
        std::lock_guard<std::mutex> lock(mutex_);
        current_present_user_id_ = user_id;
        current_present_display_name_ = display_name;
    }

    std::string GetCurrentPresentUserId() {
        std::lock_guard<std::mutex> lock(mutex_);
        return current_present_user_id_;
    }

    std::string GetCurrentPresentDisplayName() {
        std::lock_guard<std::mutex> lock(mutex_);
        return current_present_display_name_;
    }

    void ClearCurrentPresentUser() {
        std::lock_guard<std::mutex> lock(mutex_);
        current_present_user_id_.clear();
        current_present_display_name_.clear();
    }

    // ── 当前说话用户（由服务端声纹结果同步，只用于对话和默认接收人）──
    void SetCurrentSpeakerUser(const std::string& user_id,
                               const std::string& display_name = "") {
        std::lock_guard<std::mutex> lock(mutex_);
        current_speaker_user_id_ = user_id;
        current_speaker_display_name_ = display_name;
        speaker_updated_ms_ = static_cast<uint64_t>(esp_timer_get_time() / 1000);
    }

    std::string GetCurrentSpeakerUserId() {
        if (bound_person_turn) return bound_person_turn->Eligible() ? bound_person_turn->person_id : "";
        std::lock_guard<std::mutex> lock(mutex_);
        return current_speaker_user_id_;
    }

    std::string GetCurrentSpeakerDisplayName() {
        if (bound_person_turn) return bound_person_turn->display_name;
        std::lock_guard<std::mutex> lock(mutex_);
        return current_speaker_display_name_;
    }

    void ClearCurrentSpeakerUser() {
        std::lock_guard<std::mutex> lock(mutex_);
        current_speaker_user_id_.clear();
        current_speaker_display_name_.clear();
        speaker_updated_ms_ = 0;
    }

    // ── 兼容字段：历史人脸链路仍会写入 active_user_id ──
    void SetActiveUserId(const std::string& user_id) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!user_id.empty() && user_id != "all" && user_id != "default" &&
            user_id != "guest") {
            active_user_id_ = user_id;
        }
    }

    std::string GetActiveUserId() {
        std::lock_guard<std::mutex> lock(mutex_);
        return active_user_id_;
    }

    void ClearActiveUserId() {
        std::lock_guard<std::mutex> lock(mutex_);
        active_user_id_.clear();
    }

    // ── Session User ID（会话绑定的用户，唤醒时锁定，会话结束时清除）──
    void SetSessionUserId(const std::string& user_id) {
        std::lock_guard<std::mutex> lock(mutex_);
        session_user_id_   = user_id;
        session_start_ms_  = (uint64_t)(esp_timer_get_time() / 1000);
    }

    // 纯读取，无副作用，不做 TTL 判断
    std::string GetSessionUserId() {
        std::lock_guard<std::mutex> lock(mutex_);
        return session_user_id_;
    }

    void ClearSessionUserId() {
        std::lock_guard<std::mutex> lock(mutex_);
        session_user_id_.clear();
    }

    // 工具使用冻结声纹身份；人脸唤醒的 session 不代表发言人。
    // 在场人脸绝不能成为“提醒我”的默认接收人；脸与声纹上下文独立。
    // 纯读取，无副作用
    std::string GetEffectiveUserId() {
        if (bound_person_turn) return bound_person_turn->Eligible() ? bound_person_turn->person_id : "all";
        std::lock_guard<std::mutex> lock(mutex_);
        if (!current_speaker_user_id_.empty()) return current_speaker_user_id_;
        return "all";
    }

    // TTL 兜底清理（由主循环每秒 tick 调用，不在 Getter 里做）
    void TickSessionCleanup() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!session_user_id_.empty()) {
            uint64_t now = (uint64_t)(esp_timer_get_time() / 1000);
            if ((now - session_start_ms_) > kSessionTimeoutMs) {
                session_user_id_.clear();
            }
        }
    }

    // 查询 session 是否已超时（不清空，仅查询）
    bool IsSessionExpired() {
        std::lock_guard<std::mutex> lock(mutex_);
        if (session_user_id_.empty()) return false;
        uint64_t now = (uint64_t)(esp_timer_get_time() / 1000);
        return (now - session_start_ms_) > kSessionTimeoutMs;
    }

private:
    UserContext() = default;
    std::string  presence_face_;
    std::string  current_present_user_id_;
    std::string  current_present_display_name_;
    std::string  current_speaker_user_id_;
    std::string  current_speaker_display_name_;
    std::string  active_user_id_;
    std::string  session_user_id_;
    uint64_t     session_start_ms_ = 0;
    uint64_t     speaker_updated_ms_ = 0;
    std::mutex   mutex_;
};
