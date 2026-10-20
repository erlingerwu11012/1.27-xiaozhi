#ifndef DISPLAY_H
#define DISPLAY_H

#include "mcp_card.h"

#include <esp_timer.h>
#include <esp_log.h>
#include <esp_pm.h>

#include <string>
#include <chrono>
#include <functional>

class Theme {
public:
    Theme(const std::string& name) : name_(name) {}
    virtual ~Theme() = default;

    inline std::string name() const { return name_; }
private:
    std::string name_;
};

class Display {
public:
    Display();
    virtual ~Display();

    virtual void SetStatus(const char* status);
    virtual void ShowNotification(const char* notification, int duration_ms = 3000);
    virtual void ShowNotification(const std::string &notification, int duration_ms = 3000);
    virtual void SetEmotion(const char* emotion);
    // Local PCM playback only; independent of interaction/emotion state.
    virtual void SetTtsPlaybackActive(bool active) { (void)active; }
    virtual void SetChatMessage(const char* role, const char* content);
    virtual void SetTheme(Theme* theme);
    virtual Theme* GetTheme() { return current_theme_; }
    virtual void UpdateStatusBar(bool update_all = false);
    virtual void SetPowerSaveMode(bool on);
    // Screen-only standby; the application keeps its existing business state.
    virtual void TickStandbyClock(bool eligible, bool allow_entry = true) {
        (void)eligible; (void)allow_entry;
    }
    virtual bool IsStandbyClockActive() const { return false; }
    virtual void RecordDisplayActivity() {}
    virtual bool WakeFromStandbyClock() { return false; }

    // Optional product startup animation.  Implementations call on_started
    // when the first safe frame is on the panel; the callback may launch
    // audio asynchronously.  The default simply continues normal startup.
    virtual bool PlayStartupAnimation(std::function<void()> on_started = {}) {
        if (on_started) on_started();
        return false;
    }

    // 🟢 新增：显示配网二维码的虚函数接口
    virtual void ShowQrCode(const char* content);

    // 音量/亮度等级浮层（默认空实现，LcdDisplay 重写）
    virtual void ShowLevelOverlay(const char* type, int value, uint32_t duration_ms = 1500) {
        (void)type;
        (void)value;
        (void)duration_ms;
    }

    // Spine role OTA status (default no-op; LcdDisplay forwards to Home)
    virtual void ShowSpineOtaStatus(const char* title, const char* detail,
                                    int progress) {
        (void)title;
        (void)detail;
        (void)progress;
    }
    virtual void DismissSpineOtaStatus() {}

    // MCP display_hint 卡片接口（默认空实现，LcdDisplay 重写）
    virtual void ShowMcpCard(McpCardData* owned) {
        // 默认实现：释放数据后忽略（非 LCD 设备无卡片）
        if (owned) {
            free(owned->icon);
            free(owned->title);
            free(owned->status);
            for (int i = 0; i < 4; i++) free(owned->items[i]);
            for (int i = 0; i < 4; i++) free(owned->item_keys[i]);
            free(owned->action_key);
            free(owned->owner_user_id);
            free(owned->instance_id);
            free(owned->priority);
            free(owned->primary_label);
            free(owned->secondary_label);
            free(owned->tertiary_label);
            delete owned;
        }
    }
    virtual void DismissMcpCard() {}
    virtual bool DismissMcpCard(const std::string& instance_id,
                                uint32_t revision) {
        (void)instance_id;
        (void)revision;
        return false;
    }
    virtual bool HandleTouchGesture(int type, float x, float y) {
        (void)type;
        (void)x;
        (void)y;
        return false;
    }
    // 获取当前显示的卡片数据（只读），无卡片时返回 nullptr
    virtual const McpCardData* GetCurrentMcpCard() const { return nullptr; }
    virtual bool GetCurrentMcpCardIdentity(std::string& instance_id,
                                           uint32_t& revision) const {
        (void)instance_id;
        (void)revision;
        return false;
    }

    // ── 摄像头预览增强接口（基类空实现，LcdDisplay 重写）────────────────────
    virtual void SetBorderEffect(bool active) {}
    virtual void SetPreviewMode(bool enabled) {}
    virtual void ShowPrivacyOverlay() {}

    inline int width() const { return width_; }
    inline int height() const { return height_; }

protected:
    int width_ = 0;
    int height_ = 0;

    Theme* current_theme_ = nullptr;

    friend class DisplayLockGuard;
    virtual bool Lock(int timeout_ms = 0) = 0;
    virtual void Unlock() = 0;
};


class DisplayLockGuard {
public:
    DisplayLockGuard(Display *display) : display_(display) {
        if (!display_->Lock(30000)) {
            ESP_LOGE("Display", "Failed to lock display");
        }
    }
    ~DisplayLockGuard() {
        display_->Unlock();
    }

private:
    Display *display_;
};

class NoDisplay : public Display {
public:
    // 🟢 对新增接口的空实现
    virtual void ShowQrCode(const char* content) override {}
    virtual void ShowLevelOverlay(const char* type, int value, uint32_t duration_ms = 1500) override {
        (void)type; (void)value; (void)duration_ms;
    }

private:
    virtual bool Lock(int timeout_ms = 0) override {
        return true;
    }
    virtual void Unlock() override {}
};

#endif
