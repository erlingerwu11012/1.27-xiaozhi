#ifndef _APPLICATION_H_
#define _APPLICATION_H_

#include <freertos/FreeRTOS.h>
#include <freertos/event_groups.h>
#include <freertos/task.h>
#include <esp_timer.h>

#include <string>
#include <mutex>
#include <condition_variable>
#include <chrono>
#include <deque>
#include <memory>
#include <vector>
#include <atomic>
#include <cstdint>
#include <ctime>

#include "protocol.h"
#include "ota.h"
#include "audio_service.h"
#include "device_state_event.h"
#include "main_ws_open_arbiter.h"
#include "main_ws_submit_policy.h"
#include "tts_request_gate.h"


#define MAIN_EVENT_SCHEDULE (1 << 0)
#define MAIN_EVENT_SEND_AUDIO (1 << 1)
#define MAIN_EVENT_WAKE_WORD_DETECTED (1 << 2)
#define MAIN_EVENT_VAD_CHANGE (1 << 3)
#define MAIN_EVENT_ERROR (1 << 4)
#define MAIN_EVENT_CHECK_NEW_VERSION_DONE (1 << 5)
#define MAIN_EVENT_CLOCK_TICK (1 << 6)
#define MAIN_EVENT_TTS_PLAYBACK (1 << 7)

// Ordinary dialogue and information/result cards: return to idle after
// 30 seconds with no user interaction. Reminder cards use a separate
// 180-second window (kReminderInteractionMaxSeconds /
// kCardInteractionWindowSeconds).
#define LISTENING_TIMEOUT_MS (30000)
#define CONNECTING_TIMEOUT_MS (10000)

enum AecMode {
    kAecOff,
    kAecOnDeviceSide,
    kAecOnServerSide,
};

/** 当前进入 Listening 的原因，用于区分唤醒词/触摸/系统等来源，决定超时后的 UX 行为 */
enum ListeningReason {
    kListeningReasonUnknown,
    kListeningReasonWakeWord,
    kListeningReasonTouch,
    kListeningReasonSystem,
    // A visible reminder card has its own voice-action window.  This is not
    // ordinary follow-up chat, so a generic server listen:stop must not tear
    // down the card or its interaction state.
    kListeningReasonReminder,
};

class Application {
public:
    static Application& GetInstance() {
        static Application instance;
        return instance;
    }
    // 删除拷贝构造函数和赋值运算符
    Application(const Application&) = delete;
    Application& operator=(const Application&) = delete;

    void Start();
    void RecoverAuthAfterTerminal();
    void MainEventLoop();
    DeviceState GetDeviceState() const { return device_state_; }
    bool IsVoiceDetected() const { return audio_service_.IsVoiceDetected(); }
    void Schedule(std::function<void()> callback);
    void SetDeviceState(DeviceState state);
    void Alert(const char* status, const char* message, const char* emotion = "", const std::string_view& sound = "");
    void DismissAlert();
    void AbortSpeaking(AbortReason reason);
    void ToggleChatState();
    void StartListening();
    void StopListening();
    // Stop mic uplink and current TTS without closing the WebSocket.
    // Face enrollment can then create a session immediately from Listening.
    void YieldConversationForFaceEnrollment();
    void Reboot();
    void WakeWordInvoke(const std::string& wake_word);
    bool UpgradeFirmware(Ota& ota, const std::string& url = "");
    /** Run signed Spine role OTA (update_spine). Returns after success/fail; success implies reboot. */
    void HandleUpdateSpine(const cJSON* root);
    bool IsSpineOtaRunning() const;
    /** Run signed wallpaper OTA (update_wallpaper). Success implies reboot. */
    void HandleUpdateWallpaper(const cJSON* root);
    bool IsWallpaperOtaRunning() const;
    /** 主动发起对话并注入文本（用于人体感知主动打招呼） */
    void StartChatWithText(const std::string& text);
    /** 人脸识别后触发主动播报（替代直接 StartChatWithText） */
    void OnPersonIdentified(const std::string& face_id, const std::string& base_greeting);
    /** Open primary conversation WebSocket if closed. Returns true when open. */
    bool EnsureMainAudioChannelOpen();
    /**
     * Sole arbitration entry that may call protocol_->OpenAudioChannel().
     * Serialized by main_ws_open_mutex_; never call protocol_->OpenAudioChannel elsewhere.
     */
    bool OpenMainAudioChannelExclusive();
    enum class PendingMainWsAction : uint8_t {
        kNone = 0,
        kToggleChatListening,
        kStartManualListening,
        kInjectChatText,
        kWakeWordFlow,
    };
    /** Non-blocking single-flight main WS open with optional pending action. */
    enum class MainWsOpenRequestResult : uint8_t {
        kAlreadyOpen = 0,
        kStarted,
        kJoined,
        kUpgradedManual,
        kRejectedLowerPriority,
        kFailedNoProtocol,
    };

    struct MainWsPendingIntent {
        PendingMainWsAction action = PendingMainWsAction::kNone;
        std::string chat_text;
        std::string wake_word;
        bool wake_from_audio = false;
        bool has_intent = false;

        static MainWsPendingIntent None() { return {}; }
    };

    struct MainWsSubmitOutcome {
        MainWsOpenRequestResult result = MainWsOpenRequestResult::kFailedNoProtocol;
        bool pending_applied = false;
        uint32_t ws_request_id = 0;
    };

    MainWsSubmitOutcome SubmitMainWsOpenRequest(
        main_ws_open::Source source,
        bool require_presence,
        const MainWsPendingIntent& intent);

    /** @deprecated Prefer SubmitMainWsOpenRequest; open-only, no pending. */
    MainWsOpenRequestResult RequestMainAudioChannelOpenAsync(
        main_ws_open::Source source,
        bool require_presence = true);
    bool IsMainAudioChannelOpenInFlight() const;
    uint32_t GetMainWsOpenActiveRequestId() const;
    void SendMcpMessage(const std::string& payload);
    // Maps a face-api profile ID through the server-supplied binding snapshot,
    // then synchronizes only the canonical in-room user to the server.
    // Returns false for unknown or deliberately unbound face profiles.
    bool SetCurrentPresentUserFromFaceProfile(
        const std::string& face_profile_id,
        const std::string& fallback_display_name = "");
    void ClearCurrentPresentUserFromFaceProfile();
    // Session / queue helpers for WS diagnostics and MCP isolation.
    std::string GetAudioSessionId() const;
    void GetAudioQueueStats(size_t& encode_queue, size_t& send_queue);
    void OnAudioSessionClosed(const std::string& closed_session_id);
    void SendReminderProtocolMessage(const std::string& payload);
    // Keep the server's reminder-interaction guard in sync with the local
    // card lifetime.  `expires_at` is a Unix timestamp and is capped by the
    // server to the same 180-second interaction window as a defensive
    // backstop.
    void BeginReminderInteraction(const std::string& instance_id,
                                  uint32_t revision, time_t expires_at);
    void EndReminderInteraction(const std::string& instance_id,
                                uint32_t revision, const char* reason);
    /** Retry a durable card's voice interaction after presence/WS recovery. */
    void RefreshReminderInteraction();
    bool IsReminderInteractionActive() const;
    /** True when the primary conversation WebSocket audio channel is open. */
    bool IsMainAudioChannelOpened() const;
    void SetAecMode(AecMode mode);
    AecMode GetAecMode() const { return aec_mode_; }
    void PlaySound(const std::string_view& sound);
    AudioService& GetAudioService() { return audio_service_; }

    void SetListeningReason(ListeningReason reason) { listening_reason_ = reason; }
    ListeningReason GetListeningReason() const { return listening_reason_; }

    /** Record a user interaction. Voice is valid even when ASR later fails. */
    void NotifyUserInteraction(bool is_from_touch = false);
    /** Compatibility name used by existing audio paths. */
    void ResetListeningTimeout(bool is_from_touch);

private:
    Application();
    ~Application();

    std::mutex mutex_;
    std::deque<std::function<void()>> main_tasks_;
    std::unique_ptr<Protocol> protocol_;
    EventGroupHandle_t event_group_ = nullptr;
    esp_timer_handle_t clock_timer_handle_ = nullptr;
    esp_timer_handle_t tts_playback_timer_handle_ = nullptr;
    TtsPlaybackState tts_playback_state_;
    esp_timer_handle_t connecting_timer_handle_ = nullptr;
    volatile DeviceState device_state_ = kDeviceStateUnknown;
    /** 进入 kDeviceStateListening 时的系统 tick，用于非阻塞超时检测；0 表示未在聆听 */
    uint32_t listening_start_tick_ = 0;
    /** 当前聆听会话使用的超时时间（毫秒），由进入 Listening 的入口决定 */
    uint32_t listening_timeout_ms_ = LISTENING_TIMEOUT_MS;
    /** Recent subtitle text is kept only for the display playback boundary. */
    std::string last_tts_sentence_;
    struct SubtitleMarker {
        uint64_t playback_sequence = 0;
        std::string text;
    };
    // tts.stop only closes the server stream.  These main-loop fields keep
    // the subtitle visible until local speaker playback has actually drained.
    // Normal end requires both a matching tts.stop and IsPlaybackDrained().
    // Brief RX gaps must not end playback; only a monotonic idle timeout can
    // recover from a missing stop / start-with-no-audio.
    //
    // Binary audio frames have no server round id (v1/v2/v3). Local generation
    // isolates events already stamped on the main-loop queue; it cannot prove
    // that a later network packet belongs to a newer server turn.
    std::deque<SubtitleMarker> pending_subtitle_markers_;
    std::atomic<bool> tts_stream_active_{false};
    bool tts_stop_received_ = false;
    bool tts_received_audio_ = false;
    // esp_timer_get_time() anchors for abnormal-stream recovery.
    int64_t tts_stream_started_us_ = 0;
    int64_t tts_last_rx_us_ = 0;
    // Generation whose playback finished (stop+drain or anomaly). Late audio
    // stamped with this id must not revive Speaking without a new tts.start.
    uint32_t tts_closed_generation_ = 0;
    // Abnormal idle timeout (PROVISIONAL — not measured on-device this cycle).
    // Anchor: tts_last_rx_us_ after any RX, else tts_stream_started_us_.
    // Refresh: every HandleIncomingTtsAudio updates tts_last_rx_us_.
    // Trigger only when: no tts.stop AND IsPlaybackDrained() AND
    // (now - anchor) >= timeout. Continuous RX or active playback (!drained)
    // cannot fire. After tts.stop, FinishTtsPlayback waits for drain only —
    // this timer is not consulted. Chosen above the prior 3×1s false-positive
    // heuristic and typical multi-second LLM/tool streaming gaps; confirm on
    // device logs before treating as a measured production constant.
    static constexpr uint32_t kTtsAbnormalIdleTimeoutMs = 15000;
    // Local TTS main-loop isolation only. Not a listen/ASR round id and not
    // sent to the server. Uplink isolation uses AudioService::upload_generation_.
    // Listen start dedup on the server is NOT implemented here; do not reuse
    // this field for protocol listen generation.
    std::atomic<uint32_t> tts_generation_{0};
    TtsRequestGate tts_request_gate_;
    uint32_t active_tts_generation_ = 0;  // Main-loop owned playback generation.
    std::atomic<uint32_t> pending_tts_audio_{0};
    // VAD starts a request/response expectation.  If no response arrives in
    // the unified interaction window, surface a clear local error instead of
    // silently leaving the device listening forever.
    bool awaiting_server_reply_ = false;
    bool face_enrollment_was_active_ = false;
    uint32_t last_reminder_window_renewal_tick_ = 0;
    struct ReminderInteractionState {
        std::string instance_id;
        uint32_t revision = 0;
        time_t expires_at = 0;
        bool active = false;
        // The server needs one opened event for each audio WebSocket session.
        // A reconnect retains the local card but requires a fresh event.
        bool opened_on_channel = false;
        std::string opened_session_id;
    };
    ReminderInteractionState reminder_interaction_;
    /** 本次 Listening 的来源：唤醒词 / 触摸 / 系统等，用于决定超时后的 UX */
    ListeningReason listening_reason_ = kListeningReasonUnknown;
    ListeningMode listening_mode_ = kListeningModeAutoStop;
    AecMode aec_mode_ = kAecOff;
    std::string last_error_message_;
    AudioService audio_service_;

    bool has_server_time_ = false;
    bool aborted_ = false;
    int clock_ticks_ = 0;
    int last_prune_day_ = -1;
    int last_analysis_week_ = -1;  // 上次习惯批量分析的周数，防止同周重复触发
    TaskHandle_t check_new_version_task_handle_ = nullptr;
    TaskHandle_t main_event_loop_task_handle_ = nullptr;
    main_ws_open::ArbiterState ws_open_arbiter_;
    /** Protects pending_main_ws_action_ / pending_chat_text_ / wake-word fields. */
    std::mutex main_ws_request_mutex_;
    std::mutex main_ws_open_mutex_;
    static main_ws_submit::PendingActionKind ToPolicyAction(PendingMainWsAction action);
    main_ws_submit::PendingTier CurrentPendingTierLocked() const;
    void ApplyPendingIntentLocked(const MainWsPendingIntent& intent);
    void ClearProactiveChatPendingLocked();
    MainWsSubmitOutcome SubmitMainWsOpenRequestLocked(
        main_ws_open::Source source,
        bool require_presence,
        const MainWsPendingIntent& intent);
    PendingMainWsAction pending_main_ws_action_ = PendingMainWsAction::kNone;
    std::string pending_chat_text_;
    std::string pending_wake_word_;
    bool pending_wake_word_from_audio_ = false;

    void OnWakeWordDetected();
    void DropWakeWord(const char* reason, bool reenable_latch);
    void RecoverWakeWordDetection(const char* reason);
    void QueueWakeWordChannelOpen();
    void ArmConnectingTimeout();
    void CancelConnectingTimeout();
    void OnConnectingTimeout();
    void RecoverFromFailedChannelOpen(const char* reason);
    void ResumeListeningAfterWakeInterrupt();
    void ResumeListeningAfterUserInterrupt(ListeningReason reason);
    static void MainWsOpenTask(void* arg);
    void CompletePendingMainWsAction(uint32_t ws_open_request_id = 0);
    void CompleteWakeWordFlow(const std::string& wake_word);
    void HandleMainWsOpenComplete(main_ws_open::WorkerSnapshot snapshot, bool ok);
    void LogMainWsOpenEvent(const char* event, const main_ws_open::WorkerSnapshot& snap,
                            const char* result) const;
    void ClearPendingMainWsActionLocked();
    void CheckNewVersion(Ota& ota);
    bool DriveAuthUntilReady(Ota& ota, bool allow_upgrade);
    void PresentAuthStatus(Ota& ota, bool announce);
    bool WaitForCredentialRelease(Ota& ota, bool recovery);
    bool auth_drive_active_ = false;
    TickType_t next_auth_announce_tick_ = 0;
    void CheckAssetsVersion();

    // Spine OTA server-ACK coordination. Signaled from the WebSocket receive task
    // when a `spine_ota_ack` frame arrives; waited on by the OTA worker task.
    void BeginSpineOtaAckWait(const std::string& task_id);
    bool FinishSpineOtaAckWait(int timeout_ms);
    void CancelSpineOtaAckWait();
    void OnSpineOtaAck(const cJSON* root);
    std::mutex ota_ack_mutex_;
    std::condition_variable ota_ack_cv_;
    bool ota_ack_pending_ = false;
    std::string ota_ack_task_id_;
    bool ota_ack_completed_ = false;
    void ShowActivationCode(const std::string& code, const char* status = nullptr,
                            const char* prefix = nullptr);
    bool WaitForActivation(Ota& ota);
    void SetListeningMode(ListeningMode mode);
    void ArmListeningAudio();
    void EnsureListeningAudio();
    void FlushPendingReminders();  // 回到 Idle 时触发积压的提醒
    void BeginTtsStream(uint32_t generation);
    void HandleIncomingTtsAudio(uint32_t generation, std::unique_ptr<AudioStreamPacket> packet);
    void HandleTtsStop(uint32_t generation);
    void QueueTtsSubtitle(uint32_t generation, uint64_t playback_sequence,
                          const std::string& text);
    void UpdateTtsPlayback();
    void FinishTtsPlayback(const char* reason, bool abnormal);
    void ClearTtsStream(bool clear_subtitle, bool invalidate_pending = true);
    void BeginReminderInteractionOnMain(const std::string& instance_id,
                                        uint32_t revision, time_t expires_at);
    void EndReminderInteractionOnMain(const std::string& instance_id,
                                      uint32_t revision, const char* reason);
    void ActivateReminderInteractionIfReady();
    bool SendReminderInteractionEvent(const char* event, const char* reason);
    void MarkReminderInteractionTransportClosed();
    void EnqueueOrSendReminderProtocolMessage(const std::string& payload);
    void FlushPendingReminderProtocolMessages();
    std::vector<std::string> pending_reminder_protocol_messages_;
};


class TaskPriorityReset {
public:
    TaskPriorityReset(BaseType_t priority) {
        original_priority_ = uxTaskPriorityGet(NULL);
        vTaskPrioritySet(NULL, priority);
    }
    ~TaskPriorityReset() {
        vTaskPrioritySet(NULL, original_priority_);
    }

private:
    BaseType_t original_priority_;
};

#endif // _APPLICATION_H_
