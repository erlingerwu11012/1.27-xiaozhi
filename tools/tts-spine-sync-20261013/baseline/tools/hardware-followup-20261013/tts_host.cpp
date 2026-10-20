#include "tts_request_gate.h"
// Hardware/RTOS stubs only. Methods and ingress callbacks are extracted from production.
#include <atomic>
#include <cassert>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <condition_variable>
#include <cstring>
#include <ctime>
#include <deque>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define CONFIG_AUDIO_WAKE_DIAGNOSTICS 0
using TickType_t = unsigned long;
using EventBits_t = unsigned long;
constexpr int AS_EVENT_AUDIO_TESTING_RUNNING=1, AS_EVENT_WAKE_WORD_RUNNING=2,
              AS_EVENT_AUDIO_PROCESSOR_RUNNING=4, pdFALSE=0, portMAX_DELAY=-1;
constexpr int OPUS_FRAME_DURATION_MS=60, AUDIO_TESTING_MAX_DURATION_MS=1000,
              MAX_ENCODE_TASKS_IN_QUEUE=20, MAX_TIMESTAMPS_IN_QUEUE=20,
              MAX_DECODE_PACKETS_IN_QUEUE=40;
constexpr unsigned LISTENING_TIMEOUT_MS=30000;
unsigned retry_delays=0;
TickType_t pdMS_TO_TICKS(unsigned ms) { return ms; }
TickType_t xTaskGetTickCount() { return 1234; }
long long g_now_us = 1'000'000;
long long esp_timer_get_time() { return g_now_us; }
void vTaskDelay(unsigned ms) { if(ms==50) ++retry_delays; }
using EventGroup = std::atomic<unsigned long>;
EventBits_t xEventGroupGetBits(EventGroup* group) { return group->load(); }
EventBits_t xEventGroupWaitBits(EventGroup* group, int, int, int, int) { return group->load(); }
void xEventGroupSetBits(EventGroup* group, int bits) { group->fetch_or(bits); }
void xEventGroupClearBits(EventGroup* group, int bits) { group->fetch_and(~bits); }
enum DeviceState { kDeviceStateIdle, kDeviceStateListening, kDeviceStateSpeaking, kDeviceStateConnecting };
static const char* const STATE_STRINGS[] = {
    "idle", "listening", "speaking", "connecting"
};
enum ListeningMode { kListeningModeAutoStop, kListeningModeManualStop, kListeningModeRealtime };
enum ListeningReason { kListeningReasonUnknown, kListeningReasonSystem };
enum AbortReason { kAbortReasonNone, kAbortReasonWakeWordDetected };
enum AudioTaskType { kAudioTaskTypeEncodeToTestingQueue, kAudioTaskTypeEncodeToSendQueue };
constexpr int kAecOff=0;
struct AudioStreamPacket { int id=0; };
struct AudioTask {
    AudioTaskType type; std::vector<int16_t> pcm; unsigned upload_generation=0, timestamp=0;
    long long upload_created_us=0;
};
struct Codec { int input_channels() { return 1; } };
struct Processor {
    std::atomic<bool> running{false};
    unsigned fed=0;
    std::function<void()> on_feed;
    std::function<void()> on_stop;
    void Start() { running=true; }
    void Stop() { if(on_stop) on_stop(); running=false; }
    bool IsRunning() { return running; }
    void Initialize(Codec*, int, void*) {}
    int GetFeedSize() { return 4; }
    void Feed(std::vector<int16_t>) { ++fed; if(on_feed) on_feed(); }
};
// The production gate has the same API; this stub passes frames only when ready.
struct ReadyGate {
    bool ready=false;
    void MarkReady() { ready=true; }
    void Reset() { ready=false; }
    bool Gate(std::vector<int16_t>& data, std::deque<std::vector<int16_t>>& frames) {
        if(ready) frames.push_back(std::move(data)); return ready;
    }
};
struct AudioService {
    EventGroup events{AS_EVENT_AUDIO_PROCESSOR_RUNNING}; EventGroup* event_group_=&events;
    std::atomic<bool> service_stopped_{false}; bool audio_input_need_warmup_=false;
    bool audio_processor_initialized_=true; void* models_list_=nullptr;
    Codec codec; Codec* codec_=&codec;
    std::unique_ptr<Processor> audio_processor_=std::make_unique<Processor>();
    std::unique_ptr<Processor> wake_word_=std::make_unique<Processor>();
    ReadyGate ready_gate_;
    std::mutex audio_mode_mutex_, audio_queue_mutex_; std::condition_variable audio_queue_cv_;
    std::deque<std::unique_ptr<AudioTask>> audio_encode_queue_;
    std::deque<int> audio_testing_queue_, timestamp_queue_;
    std::atomic<unsigned> upload_generation_{1}, upload_read_ok_{0}, upload_read_fail_{0};
    std::atomic<unsigned> upload_pcm_frames_{0}, upload_silent_frames_{0}, upload_queue_drop_{0};
    unsigned wake_read_fail_count_=0, resets=0, accepted=0;
    bool drained=true;
    unsigned long rx_frames=0;
    std::function<bool(std::vector<int16_t>&)> reader;
    struct DownlinkStats {
        unsigned long long last_played_sequence=0;
        unsigned long rx_frames=0;
    };
    void AudioInputTask(); void EnableVoiceProcessing(bool);
    void PushTaskToEncodeQueue(AudioTaskType, std::vector<int16_t>&&);
    bool ReadAudioData(std::vector<int16_t>& data, int, int) { return reader(data); }
    void FeedPreRollBuffer(const int16_t*, size_t, int) {}
    void EnableAudioTesting(bool) { events=0; }
    void ResetDecoder() { ++resets; accepted=0; drained=true; }
    void ResetUploadQueues() { ++upload_generation_; }
    void LogUploadStats(const char*) const {}
    void EnableWakeWordDetection(bool enable) {
        if(enable) events.fetch_or(AS_EVENT_WAKE_WORD_RUNNING);
        else events.fetch_and(~AS_EVENT_WAKE_WORD_RUNNING);
    }
    bool IsAudioProcessorRunning() const {
        return (events & AS_EVENT_AUDIO_PROCESSOR_RUNNING) && audio_processor_->IsRunning();
    }
    bool IsAudioSubsystemReady() const { return ready_gate_.ready; }
    bool IsWakeWordRunning() const { return events & AS_EVENT_WAKE_WORD_RUNNING; }
    bool IsPlaybackDrained() const { return drained; }
    void GetDownlinkStats(DownlinkStats& stats) {
        stats.last_played_sequence=accepted;
        stats.rx_frames=rx_frames;
    }
    unsigned long long NextPlaybackSequence() { return accepted+1; }
    void RecordIncomingAudioFrame() { ++rx_frames; }
    void PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket>) { ++accepted; drained=false; }
};
struct Display {
    unsigned messages=0;
    std::string role, text;
    void SetChatMessage(const char* r, const char* t) {
        ++messages; role=r ? r : ""; text=t ? t : "";
    }
};
struct Board {
    static Board& GetInstance() { static Board board; return board; }
    Display* GetDisplay() { static Display display; return &display; }
};
struct FaceEnrollmentManager {
    bool active=false;
    static FaceEnrollmentManager& GetInstance() { static FaceEnrollmentManager manager; return manager; }
    bool IsActive() { return active; }
};
struct UserContext {
    static UserContext& GetInstance() { static UserContext context; return context; }
    void ClearCurrentSpeakerUser() {}
};
struct ReminderCoordinator {
    static ReminderCoordinator& GetInstance() { static ReminderCoordinator manager; return manager; }
    void Tick(time_t, bool) {}
};
struct Protocol {
    unsigned starts=0, aborts=0; bool open=true;
    std::function<void(std::unique_ptr<AudioStreamPacket>)> on_audio;
    void OnIncomingAudio(std::function<void(std::unique_ptr<AudioStreamPacket>)> f) { on_audio=std::move(f); }
    void SendStartListening(ListeningMode) { ++starts; }
    void SendAbortSpeaking(AbortReason) { ++aborts; }
    bool IsAudioChannelOpened() { return open; }
};
struct cJSON { const char* valuestring; int valueint=0; const char* request=nullptr; };
cJSON* cJSON_GetObjectItem(const cJSON* value, const char* key) {
    if(strcmp(key,"abort_epoch")==0)return nullptr;
    if(strcmp(key,"request_id")==0) { static cJSON owner{nullptr};owner.valuestring=value->request;return value->request ? &owner : nullptr; }
    return const_cast<cJSON*>(value);
}
bool cJSON_IsNumber(const cJSON*){return false;}
bool cJSON_IsString(const cJSON* value) { return value && value->valuestring; }
struct Application {
    TtsRequestGate tts_request_gate_;
    AudioService audio_service_; std::unique_ptr<Protocol> protocol_=std::make_unique<Protocol>();
    DeviceState device_state_=kDeviceStateIdle; ListeningMode listening_mode_=kListeningModeAutoStop;
    ListeningReason listening_reason_=kListeningReasonUnknown; int aec_mode_=kAecOff;
    std::atomic<unsigned> tts_generation_{0}; unsigned active_tts_generation_=0;
    std::atomic<unsigned> pending_tts_audio_{0};
    std::atomic<bool> tts_stream_active_{false}; bool tts_stop_received_=false, tts_received_audio_=false;
    int64_t tts_stream_started_us_=0, tts_last_rx_us_=0;
    unsigned tts_closed_generation_=0;
    static constexpr unsigned kTtsAbnormalIdleTimeoutMs=15000;
    bool aborted_=false, awaiting_server_reply_=false;
    unsigned listening_timeout_ms_=0; TickType_t listening_start_tick_=0;
    struct ReminderInteractionState { bool active=false; };
    ReminderInteractionState reminder_interaction_;
    struct SubtitleMarker { unsigned long long playback_sequence; std::string text; };
    std::deque<SubtitleMarker> pending_subtitle_markers_; std::string last_tts_sentence_;
    std::deque<std::function<void()>> tasks;
    void Schedule(std::function<void()> f) { tasks.push_back(std::move(f)); }
    void Run() { while(!tasks.empty()) { auto f=std::move(tasks.front()); tasks.pop_front(); f(); } }
    void RegisterAudio() { // @AUDIO_CALLBACK
    }
    void ReceiveTts(const char* event, const char* text="subtitle", const char* owner_request=nullptr) {
        cJSON state_value{event}, message{text,0,owner_request}; const cJSON* state=&state_value; const cJSON* root=&message;
        // @TTS_CALLBACK
    }
    void ReceiveStt(const char* recognized_text) {
        cJSON message{recognized_text}; const cJSON* root=&message;
        auto* display=Board::GetInstance().GetDisplay();
        // @STT_CALLBACK
    }
    void BeginTtsStream(unsigned); void HandleIncomingTtsAudio(unsigned, std::unique_ptr<AudioStreamPacket>);
    void HandleTtsStop(unsigned); void QueueTtsSubtitle(unsigned, uint64_t, const std::string&);
    void UpdateTtsPlayback(); void FinishTtsPlayback(const char*, bool);
    void ClearTtsStream(bool, bool=true); void AbortSpeaking(AbortReason);
    void ResumeListeningAfterUserInterrupt(ListeningReason);
    void SetListeningMode(ListeningMode); void ArmListeningAudio(); void EnsureListeningAudio();
    void ActivateReminderInteractionIfReady() {}
    void ResetListeningTimeout(bool) {}
    void RecoverFromFailedChannelOpen(const char*) { SetDeviceState(kDeviceStateIdle); }
    void SetDeviceState(DeviceState state) {
        if(device_state_==state) return;
        device_state_=state;
        if(state==kDeviceStateListening) ArmListeningAudio();
        else if(state==kDeviceStateSpeaking && listening_mode_!=kListeningModeRealtime)
            audio_service_.EnableVoiceProcessing(false);
    }
    Application() { RegisterAudio(); SetListeningMode(kListeningModeAutoStop); }
    void Audio() { protocol_->on_audio(std::make_unique<AudioStreamPacket>()); }
};

// @METHODS

int main() {
    {
        Application app;
        // All receive callbacks happen before the main loop gets CPU time.
        app.ReceiveTts("start"); app.Audio(); app.ReceiveTts("sentence_start"); app.ReceiveTts("stop");
        app.Run();
        assert(app.tts_stop_received_ && app.audio_service_.accepted==1);
        assert(app.device_state_==kDeviceStateSpeaking);
        app.audio_service_.drained=true; app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening && app.audio_service_.IsAudioProcessorRunning());
    }
    {
        Application app; app.ReceiveTts("start"); app.Run();
        app.Audio(); app.ReceiveTts("stop"); // Already queued when the user interrupts.
        app.AbortSpeaking(kAbortReasonNone); app.ResumeListeningAfterUserInterrupt(kListeningReasonSystem);
        app.Run(); app.Audio(); app.ReceiveTts("stop"); app.Run(); // Also arrive after abort, no new start.
        assert(app.device_state_==kDeviceStateListening && app.audio_service_.IsAudioProcessorRunning());
        assert(app.audio_service_.accepted==0 && !app.tts_stream_active_);
        app.ReceiveTts("start"); app.Audio(); app.ReceiveTts("stop"); app.Run();
        assert(app.audio_service_.accepted==1 && app.tts_stop_received_);
    }
    {
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.ReceiveTts("stop");
        app.ReceiveTts("start"); app.Audio(); app.Run();
        assert(app.audio_service_.accepted==1 && !app.tts_stop_received_);
        assert(app.active_tts_generation_==app.tts_generation_);
    }
    {
        Application app;
        const auto starts=app.protocol_->starts;
        app.EnsureListeningAudio(); assert(app.protocol_->starts==starts);
        app.audio_service_.audio_processor_->Stop(); // Flags still say running.
        app.EnsureListeningAudio();
        assert(app.protocol_->starts==starts+1 && app.audio_service_.IsAudioProcessorRunning());
        app.audio_service_.ready_gate_.Reset(); app.EnsureListeningAudio();
        assert(app.audio_service_.IsAudioSubsystemReady());
        app.SetListeningMode(kListeningModeRealtime);
        app.ReceiveTts("start"); app.Run(); app.AbortSpeaking(kAbortReasonWakeWordDetected);
        app.SetListeningMode(kListeningModeRealtime);
        assert(app.device_state_==kDeviceStateListening && app.audio_service_.IsAudioProcessorRunning());
    }
    {
        Application app; app.ReceiveTts("start");
        FaceEnrollmentManager::GetInstance().active=true; app.Run();
        assert(!app.tts_stream_active_ && app.device_state_==kDeviceStateListening);
        FaceEnrollmentManager::GetInstance().active=false;
        app.ReceiveTts("start"); app.ClearTtsStream(true); app.Run();
        assert(!app.tts_stream_active_);
    }
    {
        AudioService audio; audio.EnableVoiceProcessing(true); unsigned reads=0;
        audio.reader=[&](auto& data) { ++reads; if(reads<4) return false; data={1,2,3,4}; return true; };
        audio.audio_processor_->on_feed=[&] { audio.service_stopped_=true; };
        audio.AudioInputTask();
        assert(reads==4 && audio.upload_read_fail_==3 && audio.audio_processor_->fed==1);
        assert(retry_delays>=3);
    }
    {
        AudioService audio; audio.EnableVoiceProcessing(true); unsigned reads=0;
        audio.reader=[&](auto& data) {
            data={1,2,3,4}; ++reads;
            if(reads==1) { audio.EnableVoiceProcessing(false); audio.EnableVoiceProcessing(true); }
            return true;
        };
        audio.audio_processor_->on_feed=[&] { audio.service_stopped_=true; };
        audio.AudioInputTask();
        assert(reads==2 && audio.audio_processor_->fed==1); // Old read was discarded.
    }
    {
        AudioService audio; audio.EnableVoiceProcessing(true);
        std::promise<void> entered, release; auto released=release.get_future();
        std::atomic<bool> in_feed{false}, stop_raced{false};
        audio.reader=[](auto& data) { data={1,2,3,4}; return true; };
        audio.audio_processor_->on_feed=[&] {
            in_feed=true; entered.set_value(); released.wait(); in_feed=false; audio.service_stopped_=true;
        };
        audio.audio_processor_->on_stop=[&] { stop_raced=in_feed.load(); };
        std::thread capture([&] { audio.AudioInputTask(); }); entered.get_future().wait();
        auto stop=std::async(std::launch::async, [&] { audio.EnableVoiceProcessing(false); });
        assert(stop.wait_for(std::chrono::milliseconds(20))==std::future_status::timeout);
        release.set_value(); capture.join(); stop.get(); assert(!stop_raced);
    }
    {
        AudioService audio;
        audio.PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::vector<int16_t>(4,0));
        assert(audio.upload_silent_frames_==1 && audio.audio_encode_queue_.size()==1);
    }
    {
        Application app; app.ReceiveTts("start");
        for(int i=0; i<1000; ++i) app.Audio();
        assert(app.pending_tts_audio_==MAX_DECODE_PACKETS_IN_QUEUE);
        assert(app.tasks.size()==MAX_DECODE_PACKETS_IN_QUEUE+1);
        app.Run(); assert(app.pending_tts_audio_==0);
    }
    // Mid-stream RX gaps while drained must not end Speaking without tts.stop.
    {
        g_now_us = 1'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.Run();
        app.audio_service_.drained = true;
        g_now_us += 8'000'000; // 8s gap < 15s anomaly timeout
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking && app.tts_stream_active_);
        assert(!app.tts_stop_received_);
        // Subtitle-only updates also must not end playback.
        for (int i = 0; i < 5; ++i) app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking);
        // Stop arrives while local playback is still busy.
        app.audio_service_.drained = false;
        app.ReceiveTts("stop"); app.Run();
        assert(app.tts_stop_received_ && app.device_state_==kDeviceStateSpeaking);
        app.audio_service_.drained = true;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening);
        assert(app.tts_closed_generation_ != 0);
        // Late audio for the closed generation must not revive Speaking.
        const unsigned closed = app.tts_closed_generation_;
        app.HandleIncomingTtsAudio(closed, std::make_unique<AudioStreamPacket>());
        assert(app.device_state_==kDeviceStateListening && !app.tts_stream_active_);
    }
    // stop received but local playback still busy: wait for drain.
    {
        g_now_us = 1'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.ReceiveTts("stop"); app.Run();
        assert(app.tts_stop_received_);
        app.audio_service_.drained = false;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking);
        app.audio_service_.drained = true;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening);
    }
    // Missing stop after real idle timeout recovers without permanent Speaking.
    {
        g_now_us = 2'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.Run();
        app.audio_service_.drained = true;
        g_now_us += 16'000'000; // > kTtsAbnormalIdleTimeoutMs
        const unsigned resets_before = app.audio_service_.resets;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening);
        assert(!app.tts_stream_active_);
        assert(app.audio_service_.resets > resets_before); // anomaly resets decoder
        assert(app.tts_closed_generation_ != 0);
    }
    // start with no audio: anomaly timeout after drain.
    {
        g_now_us = 3'000'000;
        Application app;
        app.ReceiveTts("start"); app.Run();
        assert(app.device_state_==kDeviceStateSpeaking);
        app.audio_service_.drained = true;
        g_now_us += 16'000'000;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening && !app.tts_stream_active_);
    }
    // Active playback must not hit the idle timer even past 15s without stop.
    {
        g_now_us = 4'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.Run();
        app.audio_service_.drained = false;
        g_now_us += 20'000'000;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking && app.tts_stream_active_);
        assert(!app.tts_stop_received_);
    }
    // Fresh RX refreshes the idle anchor: two 10s drained gaps stay under timeout.
    {
        g_now_us = 5'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.Run();
        app.audio_service_.drained = true;
        g_now_us += 10'000'000;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking);
        app.Audio(); app.Run(); // refreshes tts_last_rx_us_
        app.audio_service_.drained = true;
        g_now_us += 10'000'000;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateSpeaking && app.tts_stream_active_);
    }
    // >15s anomaly then late audio for the closed generation must not revive;
    // a real new tts.start may begin a fresh turn.
    {
        g_now_us = 6'000'000;
        Application app;
        app.ReceiveTts("start"); app.Audio(); app.Run();
        app.audio_service_.drained = true;
        g_now_us += 16'000'000;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening);
        const unsigned closed = app.tts_closed_generation_;
        assert(closed != 0);
        app.HandleIncomingTtsAudio(closed, std::make_unique<AudioStreamPacket>());
        assert(app.device_state_==kDeviceStateListening && !app.tts_stream_active_);
        app.ReceiveTts("start"); app.Audio(); app.ReceiveTts("stop"); app.Run();
        assert(app.tts_stream_active_ && app.tts_stop_received_);
        assert(app.active_tts_generation_ != closed);
        app.audio_service_.drained = true;
        app.UpdateTtsPlayback();
        assert(app.device_state_==kDeviceStateListening);
    }
    // Recognition echoes never replace an existing assistant subtitle.
    {
        Application app;
        auto* display=Board::GetInstance().GetDisplay();
        display->SetChatMessage("assistant", "previous reply");
        const auto before=display->messages;
        app.ReceiveStt("recognized user speech"); app.Run();
        assert(display->messages==before);
        assert(display->role=="assistant" && display->text=="previous reply");
        assert(app.pending_subtitle_markers_.empty());
    }
    // Empty/malformed STT cannot clear subtitles or enqueue UI work either.
    {
        Application app;
        auto* display=Board::GetInstance().GetDisplay();
        const auto before=display->messages;
        app.ReceiveStt(""); app.ReceiveStt(nullptr); app.Run();
        assert(display->messages==before && app.tasks.empty());
    }
    // Multiple assistant captions still follow playback, even with interleaved STT.
    {
        Application app;
        auto* display=Board::GetInstance().GetDisplay();
        app.ReceiveTts("start");
        app.ReceiveTts("sentence_start", "first reply"); app.Audio(); app.Run();
        app.UpdateTtsPlayback();
        assert(display->role=="assistant" && display->text=="first reply");
        const auto before=display->messages;
        app.ReceiveStt("do not show this"); app.Run();
        assert(display->messages==before && display->text=="first reply");
        app.ReceiveTts("sentence_start", "second reply"); app.Audio(); app.Run();
        app.UpdateTtsPlayback();
        assert(display->role=="assistant" && display->text=="second reply");
    }
    // Duplicate start retains queued audio; a late stop from another owner drops.
    {
        Application app;
        app.ReceiveTts("start","","request-a"); app.Audio(); app.Run();
        auto generation=app.active_tts_generation_;
        app.ReceiveTts("start","","request-a"); app.Run();
        assert(app.active_tts_generation_==generation && app.tts_received_audio_);
        app.ReceiveTts("start","","request-b"); app.Audio(); app.Run();
        assert(app.active_tts_generation_!=generation);
        app.ReceiveTts("stop","","request-a");app.Run();
        assert(!app.tts_stop_received_);
        app.ReceiveTts("start","","request-a");app.Run();
        app.ReceiveTts("stop","","request-b");app.Run();
        assert(app.tts_stop_received_);
    }
    std::cout << "PASS: 24 production TTS/STT/capture scenarios (ASan/UBSan)\n";
}
