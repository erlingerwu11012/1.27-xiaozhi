#ifndef AUDIO_SERVICE_H
#define AUDIO_SERVICE_H

#include <memory>
#include <deque>
#include <condition_variable>
#include <chrono>
#include <mutex>
#include <atomic>

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/event_groups.h>
#include <esp_timer.h>
#include <model_path.h>

#include <opus_encoder.h>
#include <opus_decoder.h>
#include <opus_resampler.h>
#include <esp_ae_rate_cvt.h>
#include <esp_ae_types.h>

#include "audio_codec.h"
#include "audio_processor.h"
#include "audio_ready_state.h"
#include "processors/audio_debugger.h"
#include "wake_word.h"
#include "protocol.h"


/*
 * There are two types of audio data flow:
 * 1. (MIC) -> [Processors] -> {Encode Queue} -> [Opus Encoder] -> {Send Queue} -> (Server)
 * 2. (Server) -> {Decode Queue} -> [Opus Decoder] -> {Playback Queue} -> (Speaker)
 *
 * We use one task for MIC / Speaker / Processors, and one task for Opus Encoder / Opus Decoder.
 * 
 * Decode Queue and Send Queue are the main queues, because Opus packets are quite smaller than PCM packets.
 * 
 */

#define OPUS_FRAME_DURATION_MS 60
#define MAX_ENCODE_TASKS_IN_QUEUE 24
#define MAX_PLAYBACK_TASKS_IN_QUEUE 2
#define MAX_DECODE_PACKETS_IN_QUEUE (2400 / OPUS_FRAME_DURATION_MS)
#define MAX_SEND_PACKETS_IN_QUEUE (2400 / OPUS_FRAME_DURATION_MS)
#define AUDIO_TESTING_MAX_DURATION_MS 10000
#define MAX_TIMESTAMPS_IN_QUEUE 3

#define AUDIO_POWER_TIMEOUT_MS 15000
#define AUDIO_POWER_CHECK_INTERVAL_MS 1000
/* VAD 尾音帧数：语音结束后继续上传约 300ms（云端接管后不再用于门控，保留供 VAD 回调） */
#define VAD_TRAILING_FRAMES 10
/* Pre-roll 缓冲：16kHz 下 300ms = 4800 samples，用于找回唤醒后首字 */
#define PRE_ROLL_MS 300
#define PRE_ROLL_SAMPLES (PRE_ROLL_MS * 16000 / 1000)


#define AS_EVENT_AUDIO_TESTING_RUNNING      (1 << 0)
#define AS_EVENT_WAKE_WORD_RUNNING          (1 << 1)
#define AS_EVENT_AUDIO_PROCESSOR_RUNNING    (1 << 2)
#define AS_EVENT_PLAYBACK_NOT_EMPTY         (1 << 3)

struct AudioServiceCallbacks {
    std::function<void(void)> on_send_queue_available;
    std::function<void(const std::string&)> on_wake_word_detected;
    std::function<void(bool)> on_vad_change;
    std::function<void(void)> on_audio_testing_queue_full;
};


enum AudioTaskType {
    kAudioTaskTypeEncodeToSendQueue,
    kAudioTaskTypeEncodeToTestingQueue,
    kAudioTaskTypeDecodeToPlaybackQueue,
};

struct AudioTask {
    AudioTaskType type;
    std::vector<int16_t> pcm;
    uint32_t timestamp;
    uint32_t upload_generation = 0;
    int64_t upload_created_us = 0;
    uint64_t playback_sequence = 0;
};

struct DebugStatistics {
    uint32_t input_count = 0;
    uint32_t decode_count = 0;
    uint32_t encode_count = 0;
    uint32_t playback_count = 0;
};

class AudioService {
public:
    AudioService();
    ~AudioService();

    void Initialize(AudioCodec* codec);
    void Start();
    void Stop();
    void EncodeWakeWord();
    std::unique_ptr<AudioStreamPacket> PopWakeWordPacket();
    const std::string& GetLastWakeWord() const;
    bool IsVoiceDetected() const { return voice_detected_; }
    bool IsIdle();
    bool IsWakeWordRunning() const { return xEventGroupGetBits(event_group_) & AS_EVENT_WAKE_WORD_RUNNING; }
    bool IsAudioProcessorRunning() const {
        return (xEventGroupGetBits(event_group_) & AS_EVENT_AUDIO_PROCESSOR_RUNNING) &&
               audio_processor_ && audio_processor_->IsRunning();
    }
    bool IsAfeWakeWord();

    /** 获取语音子系统就绪状态（线程安全） */
    AudioReadyState GetAudioReadyState() const { return ready_gate_.GetState(); }
    /** 语音子系统是否就绪（READY 或 DEGRADED） */
    bool IsAudioSubsystemReady() const { return ready_gate_.IsReady(); }

    void EnableWakeWordDetection(bool enable);
    void EnableVoiceProcessing(bool enable);
    void EnableAudioTesting(bool enable);
    void EnableDeviceAec(bool enable);

    void SetCallbacks(AudioServiceCallbacks& callbacks);

    bool PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket> packet, bool wait = false);
    std::unique_ptr<AudioStreamPacket> PopPacketFromSendQueue();
    /** 获取编码队列与发送队列当前长度（用于 [WS_AUDIO] 限频诊断日志） */
    void GetQueueStats(size_t& encode_queue, size_t& send_queue);

    /** 下行链路统计（低噪声，供 [WS_DL] 限频日志使用；underrun 当前无精确判据） */
    struct DownlinkStats {
        uint32_t rx_frames = 0;       /* 收到音频帧数 */
        uint32_t decode_drop = 0;     /* PushPacketToDecodeQueue 满而丢包次数 */
        uint32_t decode_ok = 0;       /* 解码成功帧数 */
        uint32_t decode_fail = 0;     /* 解码失败帧数 */
        size_t decode_queue = 0;      /* 当前 decode 队列深度 */
        size_t playback_queue = 0;    /* 当前 playback 队列深度 */
        uint32_t underrun = 0;        /* 播放欠载/无包：0 表示 unavailable，不伪造 */
        uint64_t last_played_sequence = 0;  /* 已实际送入 codec 的最后一帧 */
        bool playback_active = false;       /* codec 正在输出一帧 */
    };

    /** 下行收到一帧音频（由协议层/应用层调用递增计数） */
    void RecordIncomingAudioFrame();
    /** 获取下行统计与当前队列深度（线程安全） */
    void GetDownlinkStats(DownlinkStats& out);
    // True only after all decoded audio has been handed to the codec.  This
    // deliberately includes the synchronous OutputData call in progress.
    bool IsPlaybackDrained();
    // The next accepted downlink packet receives this local sequence number.
    uint64_t NextPlaybackSequence() const;
    void PlaySound(const std::string_view& sound);
    bool ReadAudioData(std::vector<int16_t>& data, int sample_rate, int samples);
    void ResetDecoder();
    void ResetUploadQueues();
    void RecordUploadSendResult(bool sent);
    void LogUploadStats(const char* reason) const;
    void SetModelsList(srmodel_list_t* models_list);

private:
    AudioCodec* codec_ = nullptr;
    AudioServiceCallbacks callbacks_;
    std::unique_ptr<AudioProcessor> audio_processor_;
    std::unique_ptr<WakeWord> wake_word_;
    std::unique_ptr<AudioDebugger> audio_debugger_;
    std::unique_ptr<OpusEncoderWrapper> opus_encoder_;
    std::unique_ptr<OpusDecoderWrapper> opus_decoder_;
    OpusResampler input_resampler_;
    OpusResampler reference_resampler_;
    OpusResampler output_resampler_;
    std::mutex input_rate_cvt_mutex_;
    esp_ae_rate_cvt_handle_t input_rate_cvt_ = nullptr;
    DebugStatistics debug_statistics_;
    uint32_t wake_read_fail_count_ = 0;  /* 唤醒喂数据时音频读取失败次数（诊断用） */
    srmodel_list_t* models_list_ = nullptr;

    /* 下行链路统计（原子计数，供 [WS_DL] 限频日志使用） */
    std::atomic<uint32_t> rx_frames_{0};
    std::atomic<uint32_t> decode_drop_count_{0};
    std::atomic<uint32_t> decode_ok_count_{0};
    std::atomic<uint32_t> decode_fail_count_{0};
    std::atomic<uint64_t> next_playback_sequence_{1};
    std::atomic<uint64_t> last_played_sequence_{0};
    std::atomic<bool> playback_active_{false};
    std::atomic<uint32_t> upload_generation_{1};
    std::atomic<uint32_t> upload_read_ok_{0};
    std::atomic<uint32_t> upload_read_fail_{0};
    std::atomic<uint32_t> upload_pcm_frames_{0};
    std::atomic<uint32_t> upload_silent_frames_{0};
    std::atomic<uint32_t> upload_encode_ok_{0};
    std::atomic<uint32_t> upload_encode_fail_{0};
    std::atomic<uint32_t> upload_queue_drop_{0};
    std::atomic<uint32_t> upload_send_enqueued_{0};
    std::atomic<uint32_t> upload_send_ok_{0};
    std::atomic<uint32_t> upload_send_fail_{0};
    std::atomic<uint32_t> upload_stale_drop_{0};

    EventGroupHandle_t event_group_;

    // Audio encode / decode
    TaskHandle_t audio_input_task_handle_ = nullptr;
    TaskHandle_t audio_output_task_handle_ = nullptr;
    TaskHandle_t opus_codec_task_handle_ = nullptr;
    std::mutex audio_queue_mutex_;
    std::condition_variable audio_queue_cv_;
    std::deque<std::unique_ptr<AudioStreamPacket>> audio_decode_queue_;
    std::deque<std::unique_ptr<AudioStreamPacket>> audio_send_queue_;
    std::deque<std::unique_ptr<AudioStreamPacket>> audio_testing_queue_;
    std::deque<std::unique_ptr<AudioTask>> audio_encode_queue_;
    std::deque<std::unique_ptr<AudioTask>> audio_playback_queue_;
    /* Pre-roll：唤醒前最后 300ms 原始 PCM，进入 Listening 时先推入队列最前 */
    std::deque<int16_t> pre_roll_buffer_;
    std::mutex pre_roll_mutex_;
    // For server AEC
    std::deque<uint32_t> timestamp_queue_;

    bool wake_word_initialized_ = false;
    bool audio_processor_initialized_ = false;
    bool voice_detected_ = false;
    std::mutex audio_mode_mutex_;
    int vad_trailing_frames_ = 0;  /* VAD 结束后继续上传的剩余帧数 */
    bool service_stopped_ = true;
    bool audio_input_need_warmup_ = false;

    /** 语音子系统就绪门控（线程安全） */
    mutable AudioReadyGate ready_gate_;

    esp_timer_handle_t audio_power_timer_ = nullptr;
    std::chrono::steady_clock::time_point last_input_time_;
    std::chrono::steady_clock::time_point last_output_time_;

    void AudioInputTask();
    void AudioOutputTask();
    void OpusCodecTask();
    void PushTaskToEncodeQueue(AudioTaskType type, std::vector<int16_t>&& pcm);
    void SetDecodeSampleRate(int sample_rate, int frame_duration);
    void CheckAndUpdateAudioPowerState();
    void FeedPreRollBuffer(const int16_t* data, size_t samples, int channels);
    void FlushPreRollBuffer();
};

#endif
