#pragma once

#include <cstdint>
#include <functional>
#include <memory>
#include <string>

struct McpCardData;
class CubicatLvglOverlay;

class CubicatHomePlayer {
public:
    using FrameSubmitter = std::function<bool(const uint16_t* pixels,
                                               int stride,
                                               int x1,
                                               int y1,
                                               int x2,
                                               int y2,
                                               bool synchronous)>;
    using UiActionHandler =
        std::function<void(const char* instance_id,
                           uint32_t revision,
                           const char* action)>;

    enum class NetworkUiState {
        kConnected,
        kConfiguring,
        kDisconnected,
    };

    CubicatHomePlayer();
    ~CubicatHomePlayer();

    bool Start(int width,
               int height,
               FrameSubmitter frame_submitter,
               UiActionHandler action_handler);
    void Stop();
    void SetActive(bool active);
    bool IsActive() const;
    void Tick();
    // Only the render task calls ResumeAfterStandby; queries are thread-safe.
    void ResumeAfterStandby();
    bool HasForegroundUi() const;
    bool PresentFullFrame();
    void SetState(const char* state);
    void SetTtsPlaybackActive(bool active);
    void SetSubtitle(const char* role, const char* text);
    // Notifications share the bottom subtitle dock and scroll when needed.
    // Subtitles for active speech take priority; timing starts on display.
    void ShowNotification(const char* text, uint32_t duration_ms);
    void ShowMcpCard(const McpCardData* card);
    void DismissMcpCard();
    bool HandleTouch(float normalized_x, float normalized_y);
    void SetNetworkState(NetworkUiState state);
    void SetMuted(bool muted);
    void SetStatusText(const char* text);
    void SetBackground(const char* background_id);
    void ShowLevelOverlay(const char* type, int value, uint32_t duration_ms = 1500);

    // Remote role update status only (not a character shop).
    void ShowSpineOtaStatus(const char* title, const char* detail, int progress);
    void DismissSpineOtaStatus();

private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};
