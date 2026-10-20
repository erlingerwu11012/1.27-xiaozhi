#ifndef LCD_DISPLAY_H
#define LCD_DISPLAY_H

#include "display.h"
#include "mcp_card.h"
#include "standby_clock.h"

#include <esp_lcd_panel_io.h>
#include <esp_lcd_panel_ops.h>
#include <esp_timer.h>

#include <atomic>
#include <functional>
#include <memory>

class CubicatHomePlayer;
class HomeFramePipeline;
namespace cubicat { struct HomeLcdFramePerf; }

class LcdDisplay : public Display {
protected:
    enum class HomeState {
        kAbsent,
        kIdle,
        kPrewake,
        kListening,
        kThinking,
        kSpeaking,
        kReminder,
    };

    LcdDisplay(esp_lcd_panel_io_handle_t panel_io,
               esp_lcd_panel_handle_t panel,
               int width,
               int height);

    bool Lock(int timeout_ms = 0) override;
    void Unlock() override;
    virtual bool SubmitNativeHomeFrame(const uint16_t* pixels,
                                       int stride,
                                       int x1,
                                       int y1,
                                       int x2,
                                       int y2,
                                       bool synchronous = true,
                                       bool record_perf = false) = 0;
    virtual void DrainNativeHomeFrames() {}

    void StopCubicatHome();
    void UpdateHomeState(HomeState state);

    esp_lcd_panel_io_handle_t panel_io_ = nullptr;
    esp_lcd_panel_handle_t panel_ = nullptr;
    std::unique_ptr<CubicatHomePlayer> cubicat_home_player_;
    McpCardData* mcp_card_data_ = nullptr;
    esp_timer_handle_t mcp_dismiss_timer_ = nullptr;
    void* mcp_dismiss_context_ = nullptr;
    uint32_t mcp_card_generation_ = 0;
    void* ui_mutex_ = nullptr;
    std::atomic<bool> stop_render_task_{false};
    std::atomic<void*> render_task_{nullptr};
    std::atomic<bool> startup_frame_ready_{false};
    std::atomic<bool> startup_reveal_armed_{false};
    std::atomic<bool> startup_revealed_{false};
    std::function<void()> startup_reveal_callback_;
    HomeState current_home_state_ = HomeState::kIdle;
    bool hide_subtitle_ = false;

    // Called only after the first complete native frame has been committed to
    // panel GRAM.  Boards use this to reveal the backlight without exposing
    // the panel's reset contents or a partially transferred first frame.
    void NotifyStartupFrameReady();
    void ArmStartupReveal();
    void TryRevealStartup();

private:
    static void RenderTaskEntry(void* arg);
    void NotifyRenderTask();
    void RenderStandbyClock();
    bool RestoreHomeFromClock();
    // Policy/text are guarded by ui_mutex_; mode and dirty flags are atomic.
    StandbyClockPolicy standby_policy_;
    StandbyClockText clock_text_;
    std::atomic<DisplayMode> requested_mode_{DisplayMode::Home};
    std::atomic<DisplayMode> active_mode_{DisplayMode::Home};
    std::atomic<bool> clock_dirty_{false};
    std::atomic<bool> clock_unavailable_{false};
    uint16_t* clock_pixels_ = nullptr;  // allocated once; render-task owned

    bool StartRenderTask();
    void StopRenderTask();
    static void FreeMcpCard(McpCardData* card);
    static void McpDismissTimerCallback(void* arg);

public:
    ~LcdDisplay() override;

    void SetStartupRevealCallback(std::function<void()> callback);
    bool PlayStartupAnimation(std::function<void()> on_started = {}) override;
    void StartCubicatHome();
    void SetStatus(const char* status) override;
    void ShowNotification(const char* notification,
                          int duration_ms = 3000) override;
    void ShowNotification(const std::string& notification,
                          int duration_ms = 3000) override;
    void SetEmotion(const char* emotion) override;
    void SetTtsPlaybackActive(bool active) override;
    void SetChatMessage(const char* role, const char* content) override;
    void SetTheme(Theme* theme) override;
    void UpdateStatusBar(bool update_all = false) override;
    void SetPowerSaveMode(bool on) override;
    void TickStandbyClock(bool eligible, bool allow_entry = true) override;
    bool IsStandbyClockActive() const override {
        return requested_mode_.load() == DisplayMode::StandbyClock ||
               active_mode_.load() == DisplayMode::StandbyClock;
    }
    void RecordDisplayActivity() override;
    bool WakeFromStandbyClock() override;
    void ShowQrCode(const char* content) override;

    void SetHideSubtitle(bool hide);
    void ShowMcpCard(McpCardData* owned) override;
    void ShowLevelOverlay(const char* type, int value, uint32_t duration_ms = 1500) override;
    void ShowSpineOtaStatus(const char* title, const char* detail,
                            int progress) override;
    void DismissSpineOtaStatus() override;
    void DismissMcpCard() override;
    bool DismissMcpCard(const std::string& instance_id,
                        uint32_t revision) override;
    const McpCardData* GetCurrentMcpCard() const override {
        return mcp_card_data_;
    }
    bool GetCurrentMcpCardIdentity(std::string& instance_id,
                                   uint32_t& revision) const override;
    bool HandleTouchGesture(int type, float x, float y) override;
    void InvalidateHomeContext() {}

    // Camera preview is intentionally disabled in the Cubicat-only build.
    void SetBorderEffect(bool active) override { (void)active; }
    void SetPreviewMode(bool enabled) override { (void)enabled; }
    void ShowPrivacyOverlay() override {}
};

class SpiLcdDisplay final : public LcdDisplay {
public:
    SpiLcdDisplay(esp_lcd_panel_io_handle_t panel_io,
                  esp_lcd_panel_handle_t panel,
                  int width,
                  int height,
                  int offset_x,
                  int offset_y,
                  bool mirror_x,
                  bool mirror_y,
                  bool swap_xy);
    ~SpiLcdDisplay() override;

protected:
    bool SubmitNativeHomeFrame(const uint16_t* pixels,
                               int stride,
                               int x1,
                               int y1,
                               int x2,
                               int y2,
                               bool synchronous = true,
                               bool record_perf = false) override;
    void DrainNativeHomeFrames() override;

private:
    class NativeStreamTransport;
    int native_offset_x_ = 0, native_offset_y_ = 0;
    bool stream_enabled_ = false;
    static bool OnColorTransferDone(
        esp_lcd_panel_io_handle_t panel_io,
        esp_lcd_panel_io_event_data_t* event_data,
        void* user_ctx);
    bool TakeTransferSlot(int timeout_ms);
    bool WaitForAllTransfers(int timeout_ms);
    void ReleaseAllTransferSlots();
    bool QueueTransfer(int x1,
                       int y1,
                       int x2,
                       int y2,
                       const uint16_t* pixels);

    bool TransferNativeFrame(const uint16_t* pixels, int stride,
                             int x1, int y1, int x2, int y2,
                             cubicat::HomeLcdFramePerf& perf);
    std::unique_ptr<HomeFramePipeline> pipeline_;
    void* transfer_done_ = nullptr;
    uint16_t* dma_strips_[2] = {nullptr, nullptr};
    uint8_t next_strip_ = 0;
    std::atomic<bool> panel_ready_{false};
};

#endif  // LCD_DISPLAY_H
