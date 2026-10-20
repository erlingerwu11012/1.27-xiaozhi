#include "proactive_wake_coordinator.h"

#include "application.h"
#include "board.h"
#include "display.h"
#include "face_roster.h"
#include "presence_context.h"
#include "reminder_coordinator.h"
#include "user_context.h"
#include "test_observability.h"
#include "device_state.h"

#include <esp_log.h>
#include <esp_timer.h>
#include <cJSON.h>

namespace {
constexpr const char* kTag = "ProactiveWake";
constexpr int64_t kGreetingCooldownUs = 5LL * 60 * 1000000;  // 5 minutes
constexpr int64_t kLongAbsenceUs = 15LL * 60 * 1000000;
constexpr uint64_t kInitializeTimeoutUs = 5ULL * 1000 * 1000;
constexpr uint64_t kNetworkWaitTimeoutUs = 10ULL * 1000 * 1000;

esp_timer_handle_t g_init_timer = nullptr;
esp_timer_handle_t g_network_timer = nullptr;

void InitTimeoutCb(void* /*arg*/) {
    Application::GetInstance().Schedule([]() {
        ProactiveWakeCoordinator::GetInstance().OnFaceRosterInitialized(
            "__timeout__", FaceEnrollmentState::kUnknown);
    });
}

void NetworkWaitTimeoutCb(void* /*arg*/) {
    Application::GetInstance().Schedule([]() {
        ProactiveWakeCoordinator::GetInstance().OnNetworkWaitTimeout();
    });
}
}  // namespace

ProactiveWakeCoordinator& ProactiveWakeCoordinator::GetInstance() {
    static ProactiveWakeCoordinator instance;
    return instance;
}

const char* ProactiveWakeCoordinator::StateName(State state) {
    switch (state) {
        case State::kIdle: return "Idle";
        case State::kConnectingForIdentity: return "ConnectingForIdentity";
        case State::kWaitingForInitialize: return "WaitingForInitialize";
        case State::kVerifyingFace: return "VerifyingFace";
        case State::kRequestingAiGreeting: return "RequestingAiGreeting";
        case State::kDeliveringReminder: return "DeliveringReminder";
        case State::kCancelledByAbsence: return "CancelledByAbsence";
        default: return "Unknown";
    }
}

void ProactiveWakeCoordinator::SetFaceCaptureHandlers(
    FaceCaptureStarter starter, FaceCaptureCanceller canceller) {
    face_capture_starter_ = std::move(starter);
    face_capture_canceller_ = std::move(canceller);
}

bool ProactiveWakeCoordinator::IsGreetingRateLimited() const {
    if (last_greeting_sent_us_ <= 0) return false;
    return (esp_timer_get_time() - last_greeting_sent_us_) < kGreetingCooldownUs;
}

bool ProactiveWakeCoordinator::IsGenerationLive(uint32_t generation) const {
    if (!PresenceContext::GetInstance().IsRadarPresent()) return false;
    if (generation == 0) return false;
    if (active_generation_ != 0 && generation != active_generation_) return false;
    if (PresenceContext::GetInstance().PresenceGeneration() != generation) {
        return false;
    }
    return true;
}

bool ProactiveWakeCoordinator::IsSessionLive(
    const std::string& session_id) const {
    if (session_id.empty()) return false;
    const std::string current = Application::GetInstance().GetAudioSessionId();
    if (current.empty()) return false;
    return session_id == current;
}

void ProactiveWakeCoordinator::CancelInitializeTimeout() {
    if (g_init_timer) {
        esp_timer_stop(g_init_timer);
    }
}

void ProactiveWakeCoordinator::CancelNetworkWaitTimeout() {
    if (g_network_timer) {
        esp_timer_stop(g_network_timer);
    }
}

void ProactiveWakeCoordinator::ArmInitializeTimeout() {
    if (!g_init_timer) {
        esp_timer_create_args_t args = {};
        args.callback = InitTimeoutCb;
        args.name = "wake_init_to";
        esp_timer_create(&args, &g_init_timer);
    }
    esp_timer_stop(g_init_timer);
    esp_timer_start_once(g_init_timer, kInitializeTimeoutUs);
}

void ProactiveWakeCoordinator::ArmNetworkWaitTimeout() {
    if (!g_network_timer) {
        esp_timer_create_args_t args = {};
        args.callback = NetworkWaitTimeoutCb;
        args.name = "wake_net_to";
        esp_timer_create(&args, &g_network_timer);
    }
    esp_timer_stop(g_network_timer);
    esp_timer_start_once(g_network_timer, kNetworkWaitTimeoutUs);
}

void ProactiveWakeCoordinator::OnNetworkWaitTimeout() {
    if (state_ != State::kConnectingForIdentity &&
        state_ != State::kWaitingForInitialize &&
        state_ != State::kVerifyingFace &&
        state_ != State::kRequestingAiGreeting) {
        return;
    }
    ESP_LOGW(kTag, "network/verify timeout -> idle from=%s gen=%u",
             StateName(state_), static_cast<unsigned>(active_generation_));
    CancelActiveFlow("network_wait_timeout");
}

void ProactiveWakeCoordinator::ResetToIdle(const char* reason) {
    CancelInitializeTimeout();
    CancelNetworkWaitTimeout();
    pending_greeting_.active = false;
    ESP_LOGI(kTag, "ResetToIdle from=%s reason=%s gen=%u",
             StateName(state_), reason ? reason : "-",
             static_cast<unsigned>(active_generation_));
    state_ = State::kIdle;
    initialize_received_ = false;
    pending_reminder_after_identity_ = false;
    enrollment_state_ = FaceEnrollmentState::kUnknown;
}

void ProactiveWakeCoordinator::DiscardPendingGreeting(const char* reason,
                                                        uint32_t ws_request_id) {
    if (!pending_greeting_.active) {
        return;
    }
    if (ws_request_id != 0 && pending_greeting_.ws_request_id != 0 &&
        pending_greeting_.ws_request_id != ws_request_id) {
        return;
    }
    ESP_LOGI(kTag,
             "DiscardPendingGreeting reason=%s gen=%u ws_req=%u",
             reason ? reason : "-",
             static_cast<unsigned>(pending_greeting_.presence_generation),
             static_cast<unsigned>(pending_greeting_.ws_request_id));
    pending_greeting_.active = false;
    if (state_ == State::kRequestingAiGreeting) {
        ResetToIdle(reason ? reason : "greeting_discarded");
    }
}

bool ProactiveWakeCoordinator::HasPendingGreeting() const {
    return pending_greeting_.active;
}

bool ProactiveWakeCoordinator::IsIdentityOrGreetingInFlight() const {
    if (pending_greeting_.active) {
        return true;
    }
    switch (state_) {
        case State::kConnectingForIdentity:
        case State::kWaitingForInitialize:
        case State::kVerifyingFace:
        case State::kRequestingAiGreeting:
        case State::kDeliveringReminder:
            return true;
        default:
            return false;
    }
}

bool ProactiveWakeCoordinator::IsProactiveGreetingPayload(
    const std::string& text) {
    return text.rfind("[PROACTIVE_RETURN]", 0) == 0 ||
           text.rfind("[PROACTIVE_GREETING]", 0) == 0;
}

void ProactiveWakeCoordinator::ArmPendingGreeting(
    uint32_t generation, uint32_t ws_request_id,
    const std::string& session_id, bool verified_face) {
    pending_greeting_.presence_generation = generation;
    pending_greeting_.session_id = session_id;
    pending_greeting_.ws_request_id = ws_request_id;
    pending_greeting_.verified_face = verified_face;
    pending_greeting_.active = true;
    state_ = State::kRequestingAiGreeting;
    ESP_LOGI(kTag,
             "ArmPendingGreeting gen=%u ws_req=%u session_len=%u mode=%s",
             static_cast<unsigned>(generation),
             static_cast<unsigned>(ws_request_id),
             static_cast<unsigned>(session_id.size()),
             verified_face ? "verified_face" : "no_face");
}

void ProactiveWakeCoordinator::OnProactiveGreetingDelivered(
    const std::string& session_id, uint32_t ws_request_id) {
    if (!pending_greeting_.active) {
        return;
    }
    if (pending_greeting_.ws_request_id != 0 && ws_request_id != 0 &&
        pending_greeting_.ws_request_id != ws_request_id) {
        ESP_LOGW(kTag,
                 "OnProactiveGreetingDelivered stale ws_req pending=%u got=%u",
                 static_cast<unsigned>(pending_greeting_.ws_request_id),
                 static_cast<unsigned>(ws_request_id));
        DiscardPendingGreeting("stale_ws_request");
        return;
    }
    if (!IsGenerationLive(pending_greeting_.presence_generation)) {
        DiscardPendingGreeting("stale_generation");
        return;
    }
    if (!IsSessionLive(session_id)) {
        DiscardPendingGreeting("stale_session");
        return;
    }
    if (!pending_greeting_.session_id.empty() &&
        pending_greeting_.session_id != session_id) {
        DiscardPendingGreeting("session_mismatch");
        return;
    }
    pending_greeting_.active = false;
    MarkGreetingSent();
    {
        const time_t now = time(nullptr);
        if (ReminderCoordinator::GetInstance().PendingBroadcastCount(now) >= 2) {
            ReminderCoordinator::GetInstance().MarkPendingBroadcastPrompted(now);
        }
    }
    ESP_LOGI(kTag, "PROACTIVE_GREETING delivered async gen=%u mode=%s",
             static_cast<unsigned>(pending_greeting_.presence_generation),
             pending_greeting_.verified_face ? "verified_face" : "no_face");
    test_observability::Event("proactive", "greeting",
                              pending_greeting_.presence_generation,
                              "requested", "async_delivered");
    ResetToIdle("greeting_sent");
}

void ProactiveWakeCoordinator::CancelActiveFlow(const char* reason) {
    CancelInitializeTimeout();
    CancelNetworkWaitTimeout();
    if (face_capture_canceller_) {
        face_capture_canceller_();
    }
    DiscardPendingGreeting("cancel_active_flow");
    state_ = State::kCancelledByAbsence;
    ESP_LOGI(kTag, "CancelActiveFlow reason=%s gen=%u",
             reason ? reason : "-",
             static_cast<unsigned>(active_generation_));
    active_generation_ = 0;
    active_session_id_.clear();
    initialize_received_ = false;
    pending_reminder_after_identity_ = false;
    enrollment_state_ = FaceEnrollmentState::kUnknown;
    state_ = State::kIdle;
}

void ProactiveWakeCoordinator::OnAudioChannelClosed() {
    CancelActiveFlow("channel_closed");
}

bool ProactiveWakeCoordinator::HasPendingReminderPriority() const {
    return ReminderCoordinator::GetInstance().HasDuePersonalReminder(
        time(nullptr));
}

void ProactiveWakeCoordinator::OnStablePresence(uint32_t generation) {
    const int64_t now_us = esp_timer_get_time();
    return_away_seconds_ = stable_absence_started_us_ > 0
        ? static_cast<time_t>((now_us - stable_absence_started_us_) / 1000000)
        : 0;
    long_return_ = stable_absence_started_us_ > 0 &&
        now_us - stable_absence_started_us_ >= kLongAbsenceUs;
    PresenceContext::GetInstance().ApplyStablePresence(generation);
    ReminderCoordinator::GetInstance().OnPresenceChanged(true);
    test_observability::Event("proactive", "stable_presence", generation,
                              long_return_ ? "begin_identity" : "pending_only",
                              "radar_confirmed");

    if (!long_return_) {
        // Returning sooner than 15 minutes does not trigger another proactive
        // greeting.  A single due to-do is presented locally; two or more
        // wait for an explicit LLM consult.
        const time_t now = time(nullptr);
        const size_t pending =
            ReminderCoordinator::GetInstance().PendingBroadcastCount(now);
        if (pending >= 2) {
            ReminderCoordinator::GetInstance().RequestPendingBroadcastPrompt(
                now, false, return_away_seconds_);
        } else {
            ReminderCoordinator::GetInstance().Tick(
                now, Application::GetInstance().GetDeviceState() ==
                         kDeviceStateIdle);
        }
        return;
    }

    if (state_ != State::kIdle && active_generation_ == generation) {
        ESP_LOGI(kTag,
                 "OnStablePresence ignored: already active gen=%u state=%s",
                 static_cast<unsigned>(generation), StateName(state_));
        if (state_ == State::kVerifyingFace && face_capture_starter_) {
            face_capture_starter_(generation);
        }
        return;
    }
    if (state_ != State::kIdle && active_generation_ != 0 &&
        active_generation_ != generation) {
        CancelActiveFlow("new_generation");
    }

    active_generation_ = generation;
    active_session_id_.clear();
    initialize_received_ = false;
    enrollment_state_ = FaceEnrollmentState::kUnknown;
    // Reminder delivery waits until FaceRoster initialize for this session.
    pending_reminder_after_identity_ = HasPendingReminderPriority();
    BeginIdentityFlow(generation);
}

void ProactiveWakeCoordinator::BeginIdentityFlow(uint32_t generation) {
    if (!IsGenerationLive(generation) &&
        PresenceContext::GetInstance().PresenceGeneration() != generation) {
        ResetToIdle("stale_begin");
        return;
    }

    auto& app = Application::GetInstance();
    if (app.GetDeviceState() != kDeviceStateIdle &&
        state_ != State::kDeliveringReminder &&
        state_ != State::kConnectingForIdentity) {
        ESP_LOGI(kTag, "BeginIdentityFlow deferred: not idle");
        ResetToIdle("not_idle");
        return;
    }

    if (esp_timer_get_time() < 10 * 1000 * 1000LL) {
        ESP_LOGI(kTag, "BeginIdentityFlow deferred: boot grace");
        ResetToIdle("boot_grace");
        return;
    }

    if (app.IsMainAudioChannelOpened()) {
        active_session_id_ = app.GetAudioSessionId();
        state_ = State::kWaitingForInitialize;
        ArmInitializeTimeout();
        ArmNetworkWaitTimeout();
        ESP_LOGI(kTag, "WaitingForInitialize session_len=%u gen=%u",
                 static_cast<unsigned>(active_session_id_.size()),
                 static_cast<unsigned>(generation));
        test_observability::Event("proactive", "identity_flow", generation,
                                  "waiting_initialize", "ws_already_open");

        auto& roster = FaceRoster::GetInstance();
        if (!roster.IsUnknown() &&
            roster.BoundSessionId() == active_session_id_) {
            CancelInitializeTimeout();
            initialize_received_ = true;
            enrollment_state_ = roster.State();
            BranchOnEnrollment(enrollment_state_);
        }
        return;
    }

    state_ = State::kConnectingForIdentity;
    ESP_LOGI(kTag, "ConnectingForIdentity async gen=%u",
             static_cast<unsigned>(generation));
    test_observability::Event("proactive", "identity_flow", generation,
                              "ws_open_requested", "radar_arrival");
    ArmNetworkWaitTimeout();
    app.RequestMainAudioChannelOpenAsync(main_ws_open::Source::kRadar, true);
}

void ProactiveWakeCoordinator::OnAudioChannelReady(
    const std::string& session_id) {
    if (state_ != State::kConnectingForIdentity &&
        state_ != State::kWaitingForInitialize &&
        state_ != State::kDeliveringReminder &&
        state_ != State::kRequestingAiGreeting) {
        return;
    }
    if (!IsGenerationLive(active_generation_)) {
        ResetToIdle("absent_on_ready");
        return;
    }
    CancelNetworkWaitTimeout();
    active_session_id_ = session_id;
    test_observability::Event("proactive", "ws_ready", active_generation_,
                              "connected", "await_initialize");
    if (state_ == State::kConnectingForIdentity ||
        state_ == State::kWaitingForInitialize) {
        state_ = State::kWaitingForInitialize;
        ArmInitializeTimeout();
        ArmNetworkWaitTimeout();
        ESP_LOGI(kTag, "OnAudioChannelReady → WaitingForInitialize");
        auto& roster = FaceRoster::GetInstance();
        if (!roster.IsUnknown() && roster.BoundSessionId() == session_id) {
            CancelInitializeTimeout();
            initialize_received_ = true;
            enrollment_state_ = roster.State();
            BranchOnEnrollment(enrollment_state_);
        }
    }
}

void ProactiveWakeCoordinator::OnMainAudioChannelOpenFailed(const char* reason) {
    if (pending_greeting_.active) {
        DiscardPendingGreeting(reason ? reason : "ws_open_failed");
    }
    if (state_ != State::kConnectingForIdentity &&
        state_ != State::kWaitingForInitialize &&
        state_ != State::kVerifyingFace &&
        state_ != State::kRequestingAiGreeting) {
        return;
    }
    ESP_LOGW(kTag, "OnMainAudioChannelOpenFailed reason=%s",
             reason ? reason : "-");
    test_observability::Event("proactive", "ws_open_failed", active_generation_,
                              "blocked", reason ? reason : "unknown");
    ResetToIdle(reason ? reason : "ws_open_failed");
}

void ProactiveWakeCoordinator::OnStableAbsence(uint32_t generation) {
    stable_absence_started_us_ = esp_timer_get_time();
    return_away_seconds_ = 0;
    long_return_ = false;
    PresenceContext::GetInstance().ApplyStableAbsence();
    ReminderCoordinator::GetInstance().OnPresenceChanged(false);
    ESP_LOGI(kTag, "OnStableAbsence gen=%u (active=%u state=%s)",
             static_cast<unsigned>(generation),
             static_cast<unsigned>(active_generation_),
             StateName(state_));
    test_observability::Event("proactive", "stable_absence", generation,
                              "cancelled", "radar_absent");
    CancelActiveFlow("absence");
}

void ProactiveWakeCoordinator::OnFaceRosterInitialized(
    const std::string& session_id, FaceEnrollmentState enrollment_state) {
    if (session_id == "__timeout__") {
        if (state_ != State::kWaitingForInitialize &&
            state_ != State::kConnectingForIdentity) {
            return;
        }
        ESP_LOGW(kTag, "initialize timeout gen=%u → silent unknown",
                 static_cast<unsigned>(active_generation_));
        CancelInitializeTimeout();
        // Keep unknown: no greeting, no private reminder bypass.
        enrollment_state_ = FaceEnrollmentState::kUnknown;
        initialize_received_ = false;
        if (state_ == State::kDeliveringReminder) {
            // Reminder path already running; do not greet.
            return;
        }
        ResetToIdle("initialize_timeout");
        return;
    }

    if (state_ != State::kWaitingForInitialize &&
        state_ != State::kConnectingForIdentity &&
        state_ != State::kDeliveringReminder) {
        ESP_LOGI(kTag, "OnFaceRosterInitialized ignored state=%s",
                 StateName(state_));
        return;
    }
    if (!IsGenerationLive(active_generation_)) {
        ESP_LOGI(kTag, "OnFaceRosterInitialized discarded: generation");
        return;
    }
    if (!IsSessionLive(session_id)) {
        ESP_LOGW(kTag, "OnFaceRosterInitialized discarded: session mismatch");
        return;
    }

    CancelInitializeTimeout();
    initialize_received_ = true;
    enrollment_state_ = enrollment_state;
    active_session_id_ = session_id;
    ESP_LOGI(kTag, "OnFaceRosterInitialized state=%d gen=%u",
             static_cast<int>(enrollment_state),
             static_cast<unsigned>(active_generation_));
    const char* enrollment_outcome = enrollment_state == FaceEnrollmentState::kKnownZero
        ? "known_zero" : enrollment_state == FaceEnrollmentState::kKnownOneOrMore
        ? "known_one_or_more" : "unknown";
    test_observability::Event("proactive", "identity_ready", active_generation_,
                              enrollment_outcome, "initialize_received");
    BranchOnEnrollment(enrollment_state);
}

void ProactiveWakeCoordinator::BranchOnEnrollment(FaceEnrollmentState state) {
    switch (state) {
        case FaceEnrollmentState::kKnownZero:
            test_observability::Event("proactive", "arrival_decision",
                                      active_generation_, "greeting", "no_face");
            RequestNoFaceGreeting();
            break;
        case FaceEnrollmentState::kKnownOneOrMore:
            state_ = State::kVerifyingFace;
            ESP_LOGI(kTag, "VerifyingFace gen=%u",
                     static_cast<unsigned>(active_generation_));
            test_observability::Event("proactive", "arrival_decision",
                                      active_generation_, "verify_face",
                                      "face_templates_present");
            if (face_capture_starter_) {
                ArmNetworkWaitTimeout();
                face_capture_starter_(active_generation_);
            } else {
                ESP_LOGW(kTag, "No face capture starter; silent");
                ResetToIdle("no_capture");
            }
            break;
        case FaceEnrollmentState::kUnknown:
        default:
            ESP_LOGI(kTag, "enrollment unknown → generic return greeting");
            test_observability::Event("proactive", "arrival_decision",
                                      active_generation_, "greeting", "identity_unknown");
            RequestNoFaceGreeting();
            break;
    }
}

void ProactiveWakeCoordinator::RequestNoFaceGreeting() {
    if (!IsGenerationLive(active_generation_)) {
        ResetToIdle("absent_noface");
        return;
    }
    const time_t now = time(nullptr);
    ReminderInstance current_card;
    const bool have_card =
        ReminderCoordinator::GetInstance().GetCurrent(current_card);
    if (have_card ||
        ReminderCoordinator::GetInstance().PendingBroadcastCount(now) == 1) {
        ESP_LOGI(kTag, "skip greeting: single due plays locally");
        ResetToIdle("single_due_local");
        if (!have_card) {
            ReminderCoordinator::GetInstance().Tick(
                now, Application::GetInstance().GetDeviceState() ==
                         kDeviceStateIdle);
        }
        return;
    }
    if (IsGreetingRateLimited()) {
        ESP_LOGI(kTag, "No-face greeting rate-limited");
        ResetToIdle("rate_limited");
        return;
    }
    TrySendProactiveGreeting(false, "");
}

void ProactiveWakeCoordinator::RequestVerifiedFaceGreeting(
    const std::string& display_name) {
    const time_t now = time(nullptr);
    ReminderInstance current_card;
    const bool have_card =
        ReminderCoordinator::GetInstance().GetCurrent(current_card);
    if (have_card ||
        ReminderCoordinator::GetInstance().PendingBroadcastCount(now) == 1) {
        ESP_LOGI(kTag, "skip greeting: single due plays locally");
        ResetToIdle("single_due_local");
        if (!have_card) {
            ReminderCoordinator::GetInstance().Tick(
                now, Application::GetInstance().GetDeviceState() ==
                         kDeviceStateIdle);
        }
        return;
    }
    if (IsGreetingRateLimited()) {
        ESP_LOGI(kTag, "Verified greeting rate-limited");
        ResetToIdle("rate_limited");
        return;
    }
    TrySendProactiveGreeting(true, display_name);
}

bool ProactiveWakeCoordinator::TrySendProactiveGreeting(
    bool verified_face, const std::string& display_name) {
    auto& app = Application::GetInstance();
    const DeviceState device_state = app.GetDeviceState();
    if (device_state == kDeviceStateSpeaking ||
        device_state == kDeviceStateListening) {
        ESP_LOGI(kTag, "greeting skipped: conversation already active");
        ResetToIdle("already_in_conversation");
        return false;
    }

    state_ = State::kRequestingAiGreeting;
    auto* display = Board::GetInstance().GetDisplay();

    const time_t now = time(nullptr);
    const size_t pending_count =
        ReminderCoordinator::GetInstance().PendingBroadcastCount(now);
    std::string face_identity = "none";
    if (verified_face) {
        face_identity = display_name.empty() ? "unknown" : display_name;
        for (char& ch : face_identity) {
            if (ch == '\n' || ch == '\r') ch = ' ';
        }
        if (face_identity.size() > 64) {
            face_identity.resize(64);
        }
    }
    const size_t pending_clamped = pending_count > 10000 ? 10000 : pending_count;
    std::string text = "[PROACTIVE_RETURN]\n";
    text += "event=stable_user_return\n";
    text += "away_seconds=" + std::to_string(return_away_seconds_) + "\n";
    text += "face_identity=" + face_identity + "\n";
    text += "pending_reminder_count=" + std::to_string(pending_clamped) + "\n";

    if (!IsGenerationLive(active_generation_)) {
        ResetToIdle("absent_before_send");
        return false;
    }

    Application::MainWsPendingIntent intent;
    intent.has_intent = true;
    intent.action = Application::PendingMainWsAction::kInjectChatText;
    intent.chat_text = text;

    if (!app.IsMainAudioChannelOpened()) {
        app.SetDeviceState(kDeviceStateConnecting);
    }
    const auto outcome = app.SubmitMainWsOpenRequest(
        main_ws_open::Source::kGreeting, /*require_presence=*/true, intent);

    if (outcome.result ==
        Application::MainWsOpenRequestResult::kRejectedLowerPriority) {
        ESP_LOGI(kTag, "greeting rejected: manual inflight");
        test_observability::Event("proactive", "greeting", active_generation_,
                                  "skipped", "manual_priority");
        ResetToIdle("greeting_rejected_manual");
        return false;
    }

    if (display) {
        display->WakeFromStandbyClock();
        display->SetEmotion(verified_face ? "happy" : "neutral");
        display->SetChatMessage("assistant", "");
    }

    if (!app.IsMainAudioChannelOpened()) {
        if (outcome.pending_applied) {
            ArmPendingGreeting(active_generation_, outcome.ws_request_id,
                               active_session_id_, verified_face);
            ArmNetworkWaitTimeout();
            ESP_LOGI(kTag, "greeting pending async ws gen=%u ws_req=%u",
                     static_cast<unsigned>(active_generation_),
                     static_cast<unsigned>(outcome.ws_request_id));
            test_observability::Event("proactive", "greeting", active_generation_,
                                      "pending", "ws_connecting");
        } else {
            ESP_LOGI(kTag, "greeting not queued outcome=%d",
                     static_cast<int>(outcome.result));
            test_observability::Event("proactive", "greeting", active_generation_,
                                      "skipped", "not_queued");
            ResetToIdle("greeting_not_queued");
        }
        return false;
    }

    MarkGreetingSent();
    if (pending_count >= 2) {
        ReminderCoordinator::GetInstance().MarkPendingBroadcastPrompted(now);
    }
    ESP_LOGI(kTag, "PROACTIVE_RETURN sent mode=%s gen=%u away_s=%lld pending=%u",
             verified_face ? "verified_face" : "no_face",
             static_cast<unsigned>(active_generation_),
             static_cast<long long>(return_away_seconds_),
             static_cast<unsigned>(pending_count));
    test_observability::Event("proactive", "greeting", active_generation_,
                              "requested", verified_face ? "verified_face" : "no_face");
    ResetToIdle("greeting_sent");
    return true;
}

void ProactiveWakeCoordinator::MarkGreetingSent() {
    last_greeting_sent_us_ = esp_timer_get_time();
}

void ProactiveWakeCoordinator::OnFaceVerified(
    uint32_t generation, const std::string& usr_id,
    const std::string& display_name) {
    if (!IsGenerationLive(generation)) {
        ESP_LOGI(kTag, "OnFaceVerified discarded gen=%u",
                 static_cast<unsigned>(generation));
        return;
    }
    if (state_ != State::kVerifyingFace && state_ != State::kIdle) {
        // Allow if we are still in verifying, or remapped after recheck.
        if (state_ != State::kVerifyingFace) {
            ESP_LOGI(kTag, "OnFaceVerified ignored state=%s", StateName(state_));
            return;
        }
    }
    auto& user_context = UserContext::GetInstance();
    // Some board camera paths resolve and publish the raw profile before they
    // enter this legacy greeting callback.  Preserve that canonical result
    // rather than treating a display label as a second face profile lookup.
    const bool already_bound_user =
        !user_context.GetCurrentPresentUserId().empty();
    const bool is_bound_user = already_bound_user ||
        Application::GetInstance().SetCurrentPresentUserFromFaceProfile(
            usr_id, display_name);
    const std::string present_user_id = is_bound_user
        ? user_context.GetCurrentPresentUserId() : usr_id;
    const std::string present_display_name = is_bound_user
        ? user_context.GetCurrentPresentDisplayName()
        : display_name;
    PresenceContext::GetInstance().SetConfirmedIdentity(
        present_user_id, present_display_name, 1.0f, "verified", generation);
    ESP_LOGI(kTag, "OnFaceVerified gen=%u name_len=%u",
             static_cast<unsigned>(generation),
             static_cast<unsigned>(display_name.size()));
    CancelNetworkWaitTimeout();
    RequestVerifiedFaceGreeting(present_display_name);
}

void ProactiveWakeCoordinator::OnFaceVerificationFailed(
    uint32_t generation, const char* reason) {
    if (generation != active_generation_) return;
    ESP_LOGI(kTag, "OnFaceVerificationFailed reason=%s → generic return greeting",
             reason ? reason : "-");
    CancelNetworkWaitTimeout();
    RequestNoFaceGreeting();
}

void ProactiveWakeCoordinator::RequestReminderDelivery(
    const std::string& instance_id, uint32_t generation) {
    if (!IsGenerationLive(generation)) return;
    ESP_LOGI(kTag, "RequestReminderDelivery id=%s gen=%u",
             instance_id.c_str(), static_cast<unsigned>(generation));
    // Never bypass identity: queue reminder and enter the same identity path.
    pending_reminder_after_identity_ = true;
    active_generation_ = generation;
    if (initialize_received_ &&
        enrollment_state_ != FaceEnrollmentState::kUnknown &&
        IsSessionLive(active_session_id_)) {
        BranchOnEnrollment(enrollment_state_);
        return;
    }
    BeginIdentityFlow(generation);
}
