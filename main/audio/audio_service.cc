#include "audio_service.h"
#include "task_diagnostics.h"
#include <esp_log.h>
#include <esp_heap_caps.h>
#include <cstring>
#include <iterator>
#include <cstdlib>

#include "processors/no_audio_processor.h"

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32P4
#include "wake_words/afe_wake_word.h"
#include "wake_words/custom_wake_word.h"
#endif

#define RATE_CVT_CFG(_src_rate, _dest_rate, _channel)        \
    (esp_ae_rate_cvt_cfg_t)                                  \
    {                                                        \
        .src_rate        = (uint32_t)(_src_rate),            \
        .dest_rate       = (uint32_t)(_dest_rate),           \
        .channel         = (uint8_t)(_channel),              \
        .bits_per_sample = ESP_AE_BIT16,                  \
        .complexity      = 2,                                \
        .perf_type       = ESP_AE_RATE_CVT_PERF_TYPE_SPEED,  \
    }

#define TAG "AudioService"



AudioService::AudioService() {
    event_group_ = xEventGroupCreate();
}

AudioService::~AudioService() {
    if (event_group_ != nullptr) {
        vEventGroupDelete(event_group_);
    }
    if (input_rate_cvt_ != nullptr) {
        esp_ae_rate_cvt_close(input_rate_cvt_);
    }
}


void AudioService::Initialize(AudioCodec* codec) {
    codec_ = codec;
    codec_->Start();

    /* Setup the audio codec */
    opus_decoder_ = std::make_unique<OpusDecoderWrapper>(codec->output_sample_rate(), 1, OPUS_FRAME_DURATION_MS);
    opus_encoder_ = std::make_unique<OpusEncoderWrapper>(16000, 1, OPUS_FRAME_DURATION_MS);
    opus_encoder_->SetComplexity(0);

    if (codec->input_sample_rate() != 16000) {
        esp_ae_rate_cvt_cfg_t input_rate_cvt_cfg = RATE_CVT_CFG(
            codec->input_sample_rate(), 16000, codec->input_channels());
        auto rate_cvt_ret = esp_ae_rate_cvt_open(&input_rate_cvt_cfg, &input_rate_cvt_);
        if (input_rate_cvt_ == nullptr) {
            ESP_LOGE(TAG, "Failed to create input rate converter, error code: %d", rate_cvt_ret);
        } else {
            ESP_LOGD(TAG, "Input rate converter: %d -> 16000, channels=%d",
                     codec->input_sample_rate(), codec->input_channels());
        }
        input_resampler_.Configure(codec->input_sample_rate(), 16000);
        reference_resampler_.Configure(codec->input_sample_rate(), 16000);
    }

    audio_processor_ = std::make_unique<NoAudioProcessor>();
    ESP_LOGD(TAG, "Voice processor uses raw passthrough mode to avoid second AFE init");

    // 【云端接管断句】不再依赖本地 VAD 门控，Listening 状态下全量推流
    // 断句由云端 ASR 决定，设备仅负责持续上传直到收到服务端 stop 指令
    audio_processor_->OnOutput([this](std::vector<int16_t, SpiramAllocator<int16_t>>&& data) {
        std::vector<int16_t> standard_data(data.begin(), data.end());
        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(standard_data));
    });

    audio_processor_->OnVadStateChange([this](bool speaking) {
        voice_detected_ = speaking;
        if (!speaking) {
            vad_trailing_frames_ = VAD_TRAILING_FRAMES;
        } else {
            vad_trailing_frames_ = 0;
        }
        if (callbacks_.on_vad_change) {
            callbacks_.on_vad_change(speaking);
        }
    });

    audio_processor_->Initialize(codec_, OPUS_FRAME_DURATION_MS, models_list_);
    audio_processor_initialized_ = true;
    ESP_LOGD(TAG, "Raw voice processor pre-initialized");

    esp_timer_create_args_t audio_power_timer_args = {
        .callback = [](void* arg) {
            AudioService* audio_service = (AudioService*)arg;
            audio_service->CheckAndUpdateAudioPowerState();
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "audio_power_timer",
        .skip_unhandled_events = true,
    };
    esp_timer_create(&audio_power_timer_args, &audio_power_timer_);
}

void AudioService::Start() {
    static constexpr UBaseType_t kOpusCodecTaskPriority = 12;
    service_stopped_ = false;
    xEventGroupClearBits(event_group_, AS_EVENT_AUDIO_TESTING_RUNNING | AS_EVENT_WAKE_WORD_RUNNING | AS_EVENT_AUDIO_PROCESSOR_RUNNING);

    esp_timer_start_periodic(audio_power_timer_, 1000000);

#if CONFIG_USE_AUDIO_PROCESSOR
    /* Start the audio input task */
    xTaskCreatePinnedToCore([](void* arg) {
        task_diag::LogCurrentTask(TAG, "audio_input_start", 8, 0);
        AudioService* audio_service = (AudioService*)arg;
        audio_service->AudioInputTask();
        vTaskDelete(NULL);
    }, "audio_input", 2048 * 3, this, 8, &audio_input_task_handle_, 0);
    task_diag::LogTaskHandle(TAG, "audio_input_created", audio_input_task_handle_, 8, 0);

    /* Start the audio output task */
    xTaskCreate([](void* arg) {
        task_diag::LogCurrentTask(TAG, "audio_output_start", 4, -1);
        AudioService* audio_service = (AudioService*)arg;
        audio_service->AudioOutputTask();
        vTaskDelete(NULL);
    }, "audio_output", 2048 * 2, this, 4, &audio_output_task_handle_);
    task_diag::LogTaskHandle(TAG, "audio_output_created", audio_output_task_handle_, 4, -1);
#else
    /* Start the audio input task */
    xTaskCreate([](void* arg) {
        task_diag::LogCurrentTask(TAG, "audio_input_start", 8, -1);
        AudioService* audio_service = (AudioService*)arg;
        audio_service->AudioInputTask();
        vTaskDelete(NULL);
    }, "audio_input", 2048 * 2, this, 8, &audio_input_task_handle_);
    task_diag::LogTaskHandle(TAG, "audio_input_created", audio_input_task_handle_, 8, -1);

    /* Start the audio output task */
    xTaskCreate([](void* arg) {
        task_diag::LogCurrentTask(TAG, "audio_output_start", 4, -1);
        AudioService* audio_service = (AudioService*)arg;
        audio_service->AudioOutputTask();
        vTaskDelete(NULL);
    }, "audio_output", 2048, this, 4, &audio_output_task_handle_);
    task_diag::LogTaskHandle(TAG, "audio_output_created", audio_output_task_handle_, 4, -1);
#endif

    /* Start the opus codec task */
    xTaskCreate([](void* arg) {
        task_diag::LogCurrentTask(TAG, "opus_codec_start", kOpusCodecTaskPriority, -1);
        AudioService* audio_service = (AudioService*)arg;
        audio_service->OpusCodecTask();
        vTaskDelete(NULL);
    }, "opus_codec", CONFIG_OPUS_STACK_SIZE, this, kOpusCodecTaskPriority, &opus_codec_task_handle_);
    task_diag::LogTaskHandle(TAG, "opus_codec_created", opus_codec_task_handle_,
                             kOpusCodecTaskPriority, -1);
}

void AudioService::Stop() {
    esp_timer_stop(audio_power_timer_);
    service_stopped_ = true;
    xEventGroupSetBits(event_group_, AS_EVENT_AUDIO_TESTING_RUNNING |
        AS_EVENT_WAKE_WORD_RUNNING |
        AS_EVENT_AUDIO_PROCESSOR_RUNNING);

    /* 重置就绪门控，丢弃残留缓冲 */
    ready_gate_.Reset();

    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    audio_encode_queue_.clear();
    ++decoder_epoch_;
    tts_output_generation_ = 0;
    tts_last_output_us_ = 0;
    audio_decode_queue_.clear();
    audio_playback_queue_.clear();
    audio_testing_queue_.clear();
    audio_queue_cv_.notify_all();
}

bool AudioService::ReadAudioData(std::vector<int16_t>& data, int sample_rate, int samples) {
    if (!codec_->input_enabled()) {
        esp_timer_stop(audio_power_timer_);
        esp_timer_start_periodic(audio_power_timer_, AUDIO_POWER_CHECK_INTERVAL_MS * 1000);
        codec_->EnableInput(true);
    }

    if (codec_->input_sample_rate() != sample_rate) {
        data.resize(samples * codec_->input_sample_rate() / sample_rate * codec_->input_channels());
        if (!codec_->InputData(data)) {
            ESP_LOGE(TAG, "InputData failed before resample: target_rate=%d codec_rate=%d codec_ch=%d",
                     sample_rate, codec_->input_sample_rate(), codec_->input_channels());
            return false;
        }
        if (input_rate_cvt_ != nullptr) {
            std::lock_guard<std::mutex> lock(input_rate_cvt_mutex_);
            uint32_t in_sample_num = data.size() / codec_->input_channels();
            uint32_t output_samples = 0;
            esp_ae_err_t max_ret = esp_ae_rate_cvt_get_max_out_sample_num(input_rate_cvt_, in_sample_num, &output_samples);
            if (max_ret != ESP_AE_ERR_OK || output_samples == 0) {
                ESP_LOGE(TAG, "rate_cvt_get_max_out failed: ret=%d", (int)max_ret);
                return false;
            }
            auto resampled = std::vector<int16_t>(output_samples * codec_->input_channels());
            uint32_t actual_output = output_samples;
            esp_ae_err_t cvt_ret = esp_ae_rate_cvt_process(input_rate_cvt_, (esp_ae_sample_t)data.data(), in_sample_num,
                                    (esp_ae_sample_t)resampled.data(), &actual_output);
            if (cvt_ret != ESP_AE_ERR_OK) {
                ESP_LOGE(TAG, "rate_cvt_process failed: ret=%d", (int)cvt_ret);
                return false;
            }
            resampled.resize(actual_output * codec_->input_channels());
            data = std::move(resampled);
        } else if (codec_->input_channels() == 2) {
            auto mic_channel = std::vector<int16_t>(data.size() / 2);
            auto reference_channel = std::vector<int16_t>(data.size() / 2);
            for (size_t i = 0, j = 0; i < mic_channel.size(); ++i, j += 2) {
                mic_channel[i] = data[j];
                reference_channel[i] = data[j + 1];
            }
            auto resampled_mic = std::vector<int16_t>(input_resampler_.GetOutputSamples(mic_channel.size()));
            auto resampled_reference = std::vector<int16_t>(reference_resampler_.GetOutputSamples(reference_channel.size()));
            input_resampler_.Process(mic_channel.data(), mic_channel.size(), resampled_mic.data());
            reference_resampler_.Process(reference_channel.data(), reference_channel.size(), resampled_reference.data());
            data.resize(resampled_mic.size() + resampled_reference.size());
            for (size_t i = 0, j = 0; i < resampled_mic.size(); ++i, j += 2) {
                data[j] = resampled_mic[i];
                data[j + 1] = resampled_reference[i];
            }
        } else {
            auto resampled = std::vector<int16_t>(input_resampler_.GetOutputSamples(data.size()));
            input_resampler_.Process(data.data(), data.size(), resampled.data());
            data = std::move(resampled);
        }
    } else {
        data.resize(samples * codec_->input_channels());
        if (!codec_->InputData(data)) {
            ESP_LOGE(TAG, "InputData failed: rate=%d samples=%d ch=%d",
                     sample_rate, samples, codec_->input_channels());
            return false;
        }
    }

    /* Update the last input time */
    last_input_time_ = std::chrono::steady_clock::now();
    debug_statistics_.input_count++;

#if CONFIG_USE_AUDIO_DEBUGGER
    // 音频调试：发送原始音频数据
    if (audio_debugger_ == nullptr) {
        audio_debugger_ = std::make_unique<AudioDebugger>();
    }
    audio_debugger_->Feed(data);
#endif

    return true;
}

void AudioService::AudioInputTask() {
    TickType_t last_wake_feed_log_tick = 0;
#if CONFIG_AUDIO_WAKE_DIAGNOSTICS
    TickType_t last_wake_diag_log_tick = 0;
#endif
    uint32_t wake_feed_count = 0;
    uint32_t vp_feed_count = 0;
    uint32_t input_retry_count = 0;
    while (true) {
        EventBits_t bits = xEventGroupWaitBits(event_group_, AS_EVENT_AUDIO_TESTING_RUNNING |
            AS_EVENT_WAKE_WORD_RUNNING | AS_EVENT_AUDIO_PROCESSOR_RUNNING,
            pdFALSE, pdFALSE, portMAX_DELAY);

        if (service_stopped_) {
            break;
        }
        if (audio_input_need_warmup_) {
            audio_input_need_warmup_ = false;
            vTaskDelay(pdMS_TO_TICKS(120));
            continue;
        }

        /* Used for audio testing in NetworkConfiguring mode by clicking the BOOT button */
        if (bits & AS_EVENT_AUDIO_TESTING_RUNNING) {
            if (audio_testing_queue_.size() >= AUDIO_TESTING_MAX_DURATION_MS / OPUS_FRAME_DURATION_MS) {
                ESP_LOGW(TAG, "Audio testing queue is full, stopping audio testing");
                EnableAudioTesting(false);
                continue;
            }
            std::vector<int16_t> data;
            int samples = OPUS_FRAME_DURATION_MS * 16000 / 1000;
            if (ReadAudioData(data, 16000, samples)) {
                input_retry_count = 0;
                // If input channels is 2, we need to fetch the left channel data
                if (codec_->input_channels() == 2) {
                    auto mono_data = std::vector<int16_t>(data.size() / 2);
                    for (size_t i = 0, j = 0; i < mono_data.size(); ++i, j += 2) {
                        mono_data[i] = data[j];
                    }
                    data = std::move(mono_data);
                }
                PushTaskToEncodeQueue(kAudioTaskTypeEncodeToTestingQueue, std::move(data));
                continue;
            }
        }

        /* Feed the wake word */
        if (bits & AS_EVENT_WAKE_WORD_RUNNING) {
            std::vector<int16_t> data;
            int samples = wake_word_->GetFeedSize();
            if (samples > 0) {
                if (ReadAudioData(data, 16000, samples)) {
                    input_retry_count = 0;
                    /* 同时写入 Pre-roll 缓冲，用于进入 Listening 时找回首字 */
                    int ch = codec_->input_channels();
                    size_t mono_samps = (ch == 2) ? (data.size() / 2) : data.size();
                    if (ch == 2) {
                        std::vector<int16_t> mono(mono_samps);
                        for (size_t i = 0, j = 0; i < mono_samps; ++i, j += 2) mono[i] = data[j];
                        FeedPreRollBuffer(mono.data(), mono_samps, 1);
                    } else {
                        FeedPreRollBuffer(data.data(), mono_samps, 1);
                    }
                    wake_word_->Feed(data);
                    wake_feed_count++;
                    TickType_t now = xTaskGetTickCount();

                    // Shared level computation, reused by both the 5s DEBUG
                    // heartbeat and the optional 1s [AUDIO_WAKE_DIAG] line.
                    auto compute_levels = [&](int& mic_avg, int& mic_peak, int& ref_avg, int& ref_peak) {
                        int64_t mic_abs_sum = 0;
                        int64_t ref_abs_sum = 0;
                        mic_peak = 0;
                        ref_peak = 0;
                        size_t frames = (ch == 2) ? data.size() / 2 : data.size();
                        for (size_t i = 0; i < frames; ++i) {
                            int mic = data[(ch == 2) ? i * 2 : i];
                            int mic_abs = std::abs(mic);
                            mic_abs_sum += mic_abs;
                            if (mic_abs > mic_peak) mic_peak = mic_abs;
                            if (ch == 2) {
                                int ref = data[i * 2 + 1];
                                int ref_abs = std::abs(ref);
                                ref_abs_sum += ref_abs;
                                if (ref_abs > ref_peak) ref_peak = ref_abs;
                            }
                        }
                        mic_avg = frames ? (int)(mic_abs_sum / frames) : 0;
                        ref_avg = (ch == 2 && frames) ? (int)(ref_abs_sum / frames) : 0;
                    };

                    if (now - last_wake_feed_log_tick >= pdMS_TO_TICKS(5000)) {
                        last_wake_feed_log_tick = now;
                        int mic_avg = 0, mic_peak = 0, ref_avg = 0, ref_peak = 0;
                        compute_levels(mic_avg, mic_peak, ref_avg, ref_peak);
                        ESP_LOGD(TAG, "wake feed alive, count=%lu samples=%d ch=%d mic_avg=%d mic_peak=%d ref_avg=%d ref_peak=%d bits=0x%lx",
                                 (unsigned long)wake_feed_count, samples, ch, mic_avg, mic_peak, ref_avg, ref_peak,
                                 (unsigned long)xEventGroupGetBits(event_group_));
                    }

#if CONFIG_AUDIO_WAKE_DIAGNOSTICS
                    if (now - last_wake_diag_log_tick >= pdMS_TO_TICKS(1000)) {
                        last_wake_diag_log_tick = now;
                        int mic_avg = 0, mic_peak = 0, ref_avg = 0, ref_peak = 0;
                        compute_levels(mic_avg, mic_peak, ref_avg, ref_peak);
                        ESP_LOGI(TAG, "[AUDIO_WAKE_DIAG] mic_avg=%d mic_peak=%d ref_avg=%d ref_peak=%d input_gain=%.1f input_format=%s aec=%d read_fail=%lu feed=%lu",
                                 mic_avg, mic_peak, ref_avg, ref_peak,
                                 codec_->input_gain(),
                                 (ch == 2) ? "MR" : "1CH",
                                 codec_->input_reference() ? 1 : 0,
                                 (unsigned long)wake_read_fail_count_,
                                 (unsigned long)wake_feed_count);
                    }
#endif
                    continue;
                } else {
                    wake_read_fail_count_++;
                }
            }
        }

        /* Feed the audio processor */
        if (bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING) {
            std::vector<int16_t> data;
            const uint32_t generation = upload_generation_.load(std::memory_order_acquire);
            int samples = audio_processor_->GetFeedSize();
            if (samples > 0) {
                if (ReadAudioData(data, 16000, samples)) {
                    input_retry_count = 0;
                    upload_read_ok_.fetch_add(1, std::memory_order_relaxed);
                    // Read without the mode lock, then validate before Feed.
                    // Stop clears the processor's PCM buffer, so it must not
                    // race Feed or accept a read from the previous listen.
                    std::lock_guard<std::mutex> mode_lock(audio_mode_mutex_);
                    if (!IsAudioProcessorRunning() ||
                        generation != upload_generation_.load(std::memory_order_acquire)) continue;
                    std::deque<std::vector<int16_t>> frames_to_process;
                    if (ready_gate_.Gate(data, frames_to_process)) {
                        for (auto& frame : frames_to_process) {
                            audio_processor_->Feed(std::move(frame));
                            vp_feed_count++;
                        }
                    }
                    continue;
                } else {
                    upload_read_fail_.fetch_add(1, std::memory_order_relaxed);
                }
            } else {
                ESP_LOGE(TAG, "Invalid VP feed size: %d", samples);
            }
        }

        // A transient codec read failure must not kill the only capture task.
        // Recheck the current mode after a bounded backoff, including after
        // a mode switch which invalidated the bits returned by WaitBits.
        ++input_retry_count;
        if (input_retry_count == 1 || input_retry_count % 20 == 0) {
            ESP_LOGW(TAG, "[WS_AUDIO_UP] event=input_retry count=%lu bits=0x%lx",
                     (unsigned long)input_retry_count, (unsigned long)bits);
        }
        vTaskDelay(pdMS_TO_TICKS(50));
    }

    ESP_LOGW(TAG, "Audio input task stopped");
}

void AudioService::AudioOutputTask() {
    while (true) {
        std::unique_lock<std::mutex> lock(audio_queue_mutex_);
        audio_queue_cv_.wait(lock, [this]() { return !audio_playback_queue_.empty() || service_stopped_; });
        if (service_stopped_) {
            break;
        }

        auto task = std::move(audio_playback_queue_.front());
        audio_playback_queue_.pop_front();
        if (task->decoder_epoch != decoder_epoch_) continue;
        // Publish in-flight ownership before releasing the queue lock.
        playback_active_.store(true, std::memory_order_release);
        audio_queue_cv_.notify_all();
        lock.unlock();

        if (!codec_->output_enabled()) {
            esp_timer_stop(audio_power_timer_);
            esp_timer_start_periodic(audio_power_timer_, AUDIO_POWER_CHECK_INTERVAL_MS * 1000);
            codec_->EnableOutput(true);
        }
        const bool written = codec_->OutputData(task->pcm);
        const int64_t output_us = esp_timer_get_time();
        lock.lock();
        if (written) output_tail_until_us_ = output_us + codec_->OutputTailUs();
        if (written && task->decoder_epoch == decoder_epoch_ && task->playback_sequence != 0) {
            last_played_sequence_.store(task->playback_sequence,
                                        std::memory_order_release);
            if (task->playback_generation != 0) {
                const bool first = tts_output_generation_ != task->playback_generation;
                tts_output_generation_ = task->playback_generation;
                tts_last_output_us_ = output_us;
                if (first) ESP_LOGI(TAG, "[TTS_OUTPUT] event=first_pcm generation=%lu at_ms=%lu tail_ms=%lu",
                    static_cast<unsigned long>(tts_output_generation_),
                    static_cast<unsigned long>(output_us / 1000),
                    static_cast<unsigned long>(codec_->OutputTailUs() / 1000));
            }
        }
        playback_active_.store(false, std::memory_order_release);
        lock.unlock();
        if (callbacks_.on_playback_progress) callbacks_.on_playback_progress();

        /* Update the last output time */
        last_output_time_ = std::chrono::steady_clock::now();
        debug_statistics_.playback_count++;

#if CONFIG_USE_SERVER_AEC
        /* Record the timestamp for server AEC */
        if (task->timestamp > 0) {
            lock.lock();
            timestamp_queue_.push_back(task->timestamp);
        }
#endif
    }

    ESP_LOGW(TAG, "Audio output task stopped");
}

void AudioService::OpusCodecTask() {
    while (true) {
        std::unique_lock<std::mutex> lock(audio_queue_mutex_);
        audio_queue_cv_.wait(lock, [this]() {
            return service_stopped_ ||
                (!audio_encode_queue_.empty() && audio_send_queue_.size() < MAX_SEND_PACKETS_IN_QUEUE) ||
                (!audio_decode_queue_.empty() && audio_playback_queue_.size() < MAX_PLAYBACK_TASKS_IN_QUEUE);
        });
        if (service_stopped_) {
            break;
        }

        /* Decode the audio from decode queue */
        if (!audio_decode_queue_.empty() && audio_playback_queue_.size() < MAX_PLAYBACK_TASKS_IN_QUEUE) {
            auto packet = std::move(audio_decode_queue_.front());
            audio_decode_queue_.pop_front();
            const uint32_t decode_epoch = decoder_epoch_;
            decode_active_ = true;
            audio_queue_cv_.notify_all();
            lock.unlock();

            auto task = std::make_unique<AudioTask>();
            task->type = kAudioTaskTypeDecodeToPlaybackQueue;
            task->timestamp = packet->timestamp;
            task->playback_sequence = packet->playback_sequence;
            task->playback_generation = packet->playback_generation;
            task->decoder_epoch = decode_epoch;

            std::unique_lock<std::mutex> decoder_lock(decoder_mutex_);
            SetDecodeSampleRate(packet->sample_rate, packet->frame_duration);
            const bool decoded = opus_decoder_->Decode(std::move(packet->payload), task->pcm);
            if (decoded) {
                // Resample if the sample rate is different
                if (opus_decoder_->sample_rate() != codec_->output_sample_rate()) {
                    int target_size = output_resampler_.GetOutputSamples(task->pcm.size());
                    std::vector<int16_t> resampled(target_size);
                    output_resampler_.Process(task->pcm.data(), task->pcm.size(), resampled.data());
                    task->pcm = std::move(resampled);
                }

            } else {
                ESP_LOGE(TAG, "Failed to decode audio");
                decode_fail_count_.fetch_add(1, std::memory_order_relaxed);
            }
            decoder_lock.unlock();
            lock.lock();
            decode_active_ = false;
            if (decoded && decode_epoch == decoder_epoch_ && !service_stopped_) {
                audio_playback_queue_.push_back(std::move(task));
                audio_queue_cv_.notify_all();
                decode_ok_count_.fetch_add(1, std::memory_order_relaxed);
            }
            lock.unlock();
            if (callbacks_.on_playback_progress) callbacks_.on_playback_progress();
            lock.lock();
            debug_statistics_.decode_count++;
        }
        
        /* Encode the audio to send queue */
        if (!audio_encode_queue_.empty() && audio_send_queue_.size() < MAX_SEND_PACKETS_IN_QUEUE) {
            auto task = std::move(audio_encode_queue_.front());
            audio_encode_queue_.pop_front();
            audio_queue_cv_.notify_all();
            lock.unlock();

            auto packet = std::make_unique<AudioStreamPacket>();
            packet->frame_duration = OPUS_FRAME_DURATION_MS;
            packet->sample_rate = 16000;
            packet->timestamp = task->timestamp;
            packet->upload_generation = task->upload_generation;
            packet->upload_created_us = task->upload_created_us;
            if (task->type == kAudioTaskTypeEncodeToSendQueue &&
                task->upload_generation !=
                    upload_generation_.load(std::memory_order_acquire)) {
                upload_stale_drop_.fetch_add(1, std::memory_order_relaxed);
                continue;
            }
            const size_t expected_pcm_size = OPUS_FRAME_DURATION_MS * 16000 / 1000;
            if (task->pcm.size() != expected_pcm_size) {
                ESP_LOGE(TAG, "Drop invalid opus frame: pcm_size=%u expected=%u",
                         (unsigned)task->pcm.size(), (unsigned)expected_pcm_size);
                if (task->type == kAudioTaskTypeEncodeToSendQueue) {
                    upload_encode_fail_.fetch_add(1, std::memory_order_relaxed);
                }
                continue;
            }
            if (!opus_encoder_->Encode(std::move(task->pcm), packet->payload)) {
                ESP_LOGE(TAG, "Failed to encode audio");
                if (task->type == kAudioTaskTypeEncodeToSendQueue) {
                    upload_encode_fail_.fetch_add(1, std::memory_order_relaxed);
                }
                continue;
            }
            if (task->type == kAudioTaskTypeEncodeToSendQueue) {
                upload_encode_ok_.fetch_add(1, std::memory_order_relaxed);
            }

            if (task->type == kAudioTaskTypeEncodeToSendQueue) {
                {
                    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
                    if (packet->upload_generation != upload_generation_.load(std::memory_order_acquire)) {
                        upload_stale_drop_.fetch_add(1, std::memory_order_relaxed);
                        continue;
                    }
                    audio_send_queue_.push_back(std::move(packet));
                    upload_send_enqueued_.fetch_add(1, std::memory_order_relaxed);
                }
                if (callbacks_.on_send_queue_available) {
                    callbacks_.on_send_queue_available();
                }
            } else if (task->type == kAudioTaskTypeEncodeToTestingQueue) {
                std::lock_guard<std::mutex> lock(audio_queue_mutex_);
                audio_testing_queue_.push_back(std::move(packet));
            }
            debug_statistics_.encode_count++;
            lock.lock();
        }
    }

    ESP_LOGW(TAG, "Opus codec task stopped");
}

void AudioService::SetDecodeSampleRate(int sample_rate, int frame_duration) {
    if (opus_decoder_->sample_rate() == sample_rate && opus_decoder_->duration_ms() == frame_duration) {
        return;
    }

    opus_decoder_.reset();
    opus_decoder_ = std::make_unique<OpusDecoderWrapper>(sample_rate, 1, frame_duration);

    auto codec = Board::GetInstance().GetAudioCodec();
    if (opus_decoder_->sample_rate() != codec->output_sample_rate()) {
        ESP_LOGI(TAG, "Resampling audio from %d to %d", opus_decoder_->sample_rate(), codec->output_sample_rate());
        output_resampler_.Configure(opus_decoder_->sample_rate(), codec->output_sample_rate());
    }
}

void AudioService::PushTaskToEncodeQueue(AudioTaskType type, std::vector<int16_t>&& pcm) {
    if (type == kAudioTaskTypeEncodeToSendQueue && !pcm.empty()) {
        upload_pcm_frames_.fetch_add(1, std::memory_order_relaxed);
        bool all_zero = true;
        for (auto sample : pcm) {
            if (sample != 0) {
                all_zero = false;
                break;
            }
        }
        if (all_zero) {
            upload_silent_frames_.fetch_add(1, std::memory_order_relaxed);
        }
    }

    auto task = std::make_unique<AudioTask>();
    task->type = type;
    task->pcm = std::move(pcm);
    if (type == kAudioTaskTypeEncodeToSendQueue) {
        task->upload_generation =
            upload_generation_.load(std::memory_order_acquire);
        task->upload_created_us = esp_timer_get_time();
    }
    
    /* Push the task to the encode queue */
    std::unique_lock<std::mutex> lock(audio_queue_mutex_);

    /* If the task is to send queue, we need to set the timestamp */
    if (type == kAudioTaskTypeEncodeToSendQueue && !timestamp_queue_.empty()) {
        if (timestamp_queue_.size() <= MAX_TIMESTAMPS_IN_QUEUE) {
            task->timestamp = timestamp_queue_.front();
        } else {
            ESP_LOGW(TAG, "Timestamp queue (%u) is full, dropping timestamp", timestamp_queue_.size());
        }
        timestamp_queue_.pop_front();
    }

    if (audio_encode_queue_.size() >= MAX_ENCODE_TASKS_IN_QUEUE) {
        const int64_t oldest_us = audio_encode_queue_.empty() ? 0 : audio_encode_queue_.front()->upload_created_us;
        ESP_LOGW(TAG, "Encode queue full, dropping frame encode_q=%u send_q=%u oldest_ms=%lld generation=%lu",
            (unsigned)audio_encode_queue_.size(), (unsigned)audio_send_queue_.size(),
            (long long)(oldest_us > 0 ? (esp_timer_get_time()-oldest_us)/1000 : 0),
            (unsigned long)upload_generation_.load(std::memory_order_acquire));
        if (type == kAudioTaskTypeEncodeToSendQueue) {
            upload_queue_drop_.fetch_add(1, std::memory_order_relaxed);
        }
        return;
    }
    audio_encode_queue_.push_back(std::move(task));
    audio_queue_cv_.notify_all();
}

void AudioService::FeedPreRollBuffer(const int16_t* data, size_t samples, int channels) {
    std::lock_guard<std::mutex> lock(pre_roll_mutex_);
    size_t stride = (channels > 1) ? (size_t)channels : 1;
    for (size_t i = 0; i < samples; ++i) {
        int16_t s = data[i * stride];
        pre_roll_buffer_.push_back(s);
        if (pre_roll_buffer_.size() > PRE_ROLL_SAMPLES) {
            pre_roll_buffer_.pop_front();
        }
    }
}

void AudioService::FlushPreRollBuffer() {
    const size_t frame_samples = OPUS_FRAME_DURATION_MS * 16000 / 1000;  /* 960 */
    while (true) {
        std::vector<int16_t> chunk;
        {
            std::lock_guard<std::mutex> lock(pre_roll_mutex_);
            if (pre_roll_buffer_.size() < frame_samples) {
                pre_roll_buffer_.clear();
                break;
            }
            chunk.reserve(frame_samples);
            for (size_t i = 0; i < frame_samples; ++i) {
                chunk.push_back(pre_roll_buffer_.front());
                pre_roll_buffer_.pop_front();
            }
        }
        PushTaskToEncodeQueue(kAudioTaskTypeEncodeToSendQueue, std::move(chunk));
    }
}

bool AudioService::PushPacketToDecodeQueue(std::unique_ptr<AudioStreamPacket> packet, bool wait) {
    if (!packet) return false;
    std::unique_lock<std::mutex> lock(audio_queue_mutex_);
    if (audio_decode_queue_.size() >= MAX_DECODE_PACKETS_IN_QUEUE) {
        if (wait) {
            audio_queue_cv_.wait(lock, [this]() { return audio_decode_queue_.size() < MAX_DECODE_PACKETS_IN_QUEUE; });
        } else {
            decode_drop_count_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
    }
    packet->playback_sequence =
        next_playback_sequence_.fetch_add(1, std::memory_order_relaxed);
    audio_decode_queue_.push_back(std::move(packet));
    audio_queue_cv_.notify_all();
    return true;
}

std::unique_ptr<AudioStreamPacket> AudioService::PopPacketFromSendQueue() {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    // Bound latency after congestion. The timestamp includes time spent in the
    // PCM/encoder queue, so recovered links cannot replay seconds-old speech.
    constexpr int64_t kMaxUploadPacketAgeUs = 1500000;
    const int64_t now_us = esp_timer_get_time();
    while (!audio_send_queue_.empty()) {
        auto packet = std::move(audio_send_queue_.front());
        audio_send_queue_.pop_front();
        audio_queue_cv_.notify_all();
        if (packet && (packet->upload_generation !=
                           upload_generation_.load(std::memory_order_acquire) ||
                       (packet->upload_created_us > 0 &&
                        now_us - packet->upload_created_us > kMaxUploadPacketAgeUs))) {
            upload_stale_drop_.fetch_add(1, std::memory_order_relaxed);
            continue;
        }
        return packet;
    }
    return nullptr;
}

void AudioService::GetQueueStats(size_t& encode_queue, size_t& send_queue) {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    encode_queue = audio_encode_queue_.size();
    send_queue = audio_send_queue_.size();
}

void AudioService::RecordIncomingAudioFrame() {
    rx_frames_.fetch_add(1, std::memory_order_relaxed);
}

void AudioService::GetDownlinkStats(DownlinkStats& out) {
    out.rx_frames = rx_frames_.load(std::memory_order_relaxed);
    out.decode_drop = decode_drop_count_.load(std::memory_order_relaxed);
    out.decode_ok = decode_ok_count_.load(std::memory_order_relaxed);
    out.decode_fail = decode_fail_count_.load(std::memory_order_relaxed);
    out.last_played_sequence =
        last_played_sequence_.load(std::memory_order_acquire);
    out.playback_active = playback_active_.load(std::memory_order_acquire);
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    out.decode_queue = audio_decode_queue_.size();
    out.playback_queue = audio_playback_queue_.size();
    // 当前无精确欠载判据：明确记录为 unavailable（恒 0），不伪造 underrun。
    out.underrun = 0;
}

bool AudioService::IsPlaybackDrained() {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    return audio_decode_queue_.empty() && audio_playback_queue_.empty() &&
           !decode_active_ && !playback_active_.load(std::memory_order_acquire) &&
           esp_timer_get_time() >= output_tail_until_us_;
}

TtsPlaybackSnapshot AudioService::GetTtsPlaybackSnapshot() {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    return {tts_output_generation_, tts_last_output_us_, output_tail_until_us_,
        decode_active_ || playback_active_.load(std::memory_order_acquire) ||
        !audio_decode_queue_.empty() || !audio_playback_queue_.empty()};
}

uint64_t AudioService::NextPlaybackSequence() const {
    return next_playback_sequence_.load(std::memory_order_acquire);
}

void AudioService::EncodeWakeWord() {
    if (wake_word_) {
        wake_word_->EncodeWakeWordData();
    }
}

const std::string& AudioService::GetLastWakeWord() const {
    return wake_word_->GetLastDetectedWakeWord();
}

std::unique_ptr<AudioStreamPacket> AudioService::PopWakeWordPacket() {
    auto packet = std::make_unique<AudioStreamPacket>();
    if (wake_word_->GetWakeWordOpus(packet->payload)) {
        return packet;
    }
    return nullptr;
}

void AudioService::EnableWakeWordDetection(bool enable) {
    if (!wake_word_) {
        ESP_LOGW(TAG, "%s wake word ignored: wake_word_ is null", enable ? "Enable" : "Disable");
        return;
    }

    std::lock_guard<std::mutex> lock(audio_mode_mutex_);
    EventBits_t before_bits = xEventGroupGetBits(event_group_);
    ESP_LOGD(TAG, "%s wake word, bits_before=0x%lx initialized=%d",
             enable ? "Enable" : "Disable", (unsigned long)before_bits, wake_word_initialized_ ? 1 : 0);
    if (enable) {
        if (before_bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING) {
            ESP_LOGD(TAG, "Skip wake word detection while voice processing is running");
            return;
        }
        if (!wake_word_initialized_) {
            ESP_LOGD(TAG, "Initializing wake word detector");
            if (!wake_word_->Initialize(codec_, models_list_)) {
                ESP_LOGE(TAG, "Failed to initialize wake word");
                return;
            }
            wake_word_initialized_ = true;
        }
        wake_word_->Start();
        xEventGroupSetBits(event_group_, AS_EVENT_WAKE_WORD_RUNNING);
        ESP_LOGI(TAG, "Wake word running, bits_after=0x%lx", (unsigned long)xEventGroupGetBits(event_group_));
    } else {
        wake_word_->Stop();
        xEventGroupClearBits(event_group_, AS_EVENT_WAKE_WORD_RUNNING);
        ESP_LOGI(TAG, "Wake word stopped, bits_after=0x%lx", (unsigned long)xEventGroupGetBits(event_group_));
    }
}

void AudioService::EnableVoiceProcessing(bool enable) {
    std::lock_guard<std::mutex> lock(audio_mode_mutex_);
    EventBits_t before_bits = xEventGroupGetBits(event_group_);
    ESP_LOGD(TAG, "%s voice processing, bits_before=0x%lx initialized=%d",
             enable ? "Enable" : "Disable", (unsigned long)before_bits, audio_processor_initialized_ ? 1 : 0);
    if (enable) {
        if ((before_bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING) && audio_processor_->IsRunning()) {
            ready_gate_.MarkReady();
            ESP_LOGD(TAG, "Voice processing already running");
            return;
        }

        if (wake_word_ && (before_bits & AS_EVENT_WAKE_WORD_RUNNING)) {
            ESP_LOGD(TAG, "Switch audio mode: WakeWord -> VoiceProcessing");
            wake_word_->Stop();
            xEventGroupClearBits(event_group_, AS_EVENT_WAKE_WORD_RUNNING);
            vTaskDelay(pdMS_TO_TICKS(50));
        }

        ready_gate_.Reset();

        if (!audio_processor_initialized_) {
            ESP_LOGI(TAG, "Initializing voice processor");
            audio_processor_->Initialize(codec_, OPUS_FRAME_DURATION_MS, models_list_);
            audio_processor_initialized_ = true;
            ESP_LOGD(TAG, "Voice processor initialized");
        }

        /* We should make sure no audio is playing */
        ResetDecoder();
        audio_input_need_warmup_ = true;
        audio_processor_->Start();
        xEventGroupSetBits(event_group_, AS_EVENT_AUDIO_PROCESSOR_RUNNING);

        /* AudioProcessor 已 Start，标记为 READY（AFE 内部 task 已启动） */
        ready_gate_.MarkReady();
        ESP_LOGI(TAG, "Voice processing running, bits_after=0x%lx", (unsigned long)xEventGroupGetBits(event_group_));
    } else {
        if (!(before_bits & AS_EVENT_AUDIO_PROCESSOR_RUNNING)) {
            ready_gate_.Reset();
            ESP_LOGD(TAG, "Voice processing already stopped");
            return;
        }
        audio_processor_->Stop();
        upload_generation_.fetch_add(1, std::memory_order_acq_rel);
        xEventGroupClearBits(event_group_, AS_EVENT_AUDIO_PROCESSOR_RUNNING);
        /* 退出语音处理，重置门控状态 */
        ready_gate_.Reset();
        ESP_LOGI(TAG, "Voice processing stopped, bits_after=0x%lx", (unsigned long)xEventGroupGetBits(event_group_));
    }
}

void AudioService::EnableAudioTesting(bool enable) {
    ESP_LOGI(TAG, "%s audio testing", enable ? "Enabling" : "Disabling");
    if (enable) {
        xEventGroupSetBits(event_group_, AS_EVENT_AUDIO_TESTING_RUNNING);
    } else {
        xEventGroupClearBits(event_group_, AS_EVENT_AUDIO_TESTING_RUNNING);
        /* Copy audio_testing_queue_ to audio_decode_queue_ */
        std::lock_guard<std::mutex> lock(audio_queue_mutex_);
        audio_decode_queue_ = std::move(audio_testing_queue_);
        audio_queue_cv_.notify_all();
    }
}

void AudioService::EnableDeviceAec(bool enable) {
    ESP_LOGI(TAG, "%s device AEC", enable ? "Enabling" : "Disabling");
    if (!audio_processor_initialized_) {
        audio_processor_->Initialize(codec_, OPUS_FRAME_DURATION_MS, models_list_);
        audio_processor_initialized_ = true;
    }

    audio_processor_->EnableDeviceAec(enable);
}

void AudioService::SetCallbacks(AudioServiceCallbacks& callbacks) {
    callbacks_ = callbacks;
}

void AudioService::PlaySound(const std::string_view& ogg) {
    if (!codec_->output_enabled()) {
        esp_timer_stop(audio_power_timer_);
        esp_timer_start_periodic(audio_power_timer_, AUDIO_POWER_CHECK_INTERVAL_MS * 1000);
        codec_->EnableOutput(true);
    }

    const uint8_t* buf = reinterpret_cast<const uint8_t*>(ogg.data());
    size_t size = ogg.size();
    size_t offset = 0;

    auto find_page = [&](size_t start)->size_t {
        for (size_t i = start; i + 4 <= size; ++i) {
            if (buf[i] == 'O' && buf[i+1] == 'g' && buf[i+2] == 'g' && buf[i+3] == 'S') return i;
        }
        return static_cast<size_t>(-1);
    };

    bool seen_head = false;
    bool seen_tags = false;
    int sample_rate = 16000; // 默认值

    while (true) {
        size_t pos = find_page(offset);
        if (pos == static_cast<size_t>(-1)) break;
        offset = pos;
        if (offset + 27 > size) break;

        const uint8_t* page = buf + offset;
        uint8_t page_segments = page[26];
        size_t seg_table_off = offset + 27;
        if (seg_table_off + page_segments > size) break;

        size_t body_size = 0;
        for (size_t i = 0; i < page_segments; ++i) body_size += page[27 + i];

        size_t body_off = seg_table_off + page_segments;
        if (body_off + body_size > size) break;

        // Parse packets using lacing
        size_t cur = body_off;
        size_t seg_idx = 0;
        while (seg_idx < page_segments) {
            size_t pkt_len = 0;
            size_t pkt_start = cur;
            bool continued = false;
            do {
                uint8_t l = page[27 + seg_idx++];
                pkt_len += l;
                cur += l;
                continued = (l == 255);
            } while (continued && seg_idx < page_segments);

            if (pkt_len == 0) continue;
            const uint8_t* pkt_ptr = buf + pkt_start;

            if (!seen_head) {
                // 解析OpusHead包
                if (pkt_len >= 19 && std::memcmp(pkt_ptr, "OpusHead", 8) == 0) {
                    seen_head = true;
                    
                    // OpusHead结构：[0-7] "OpusHead", [8] version, [9] channel_count, [10-11] pre_skip
                    // [12-15] input_sample_rate, [16-17] output_gain, [18] mapping_family
                    if (pkt_len >= 12) {
                        uint8_t version = pkt_ptr[8];
                        uint8_t channel_count = pkt_ptr[9];
                        
                        if (pkt_len >= 16) {
                            // 读取输入采样率 (little-endian)
                            sample_rate = pkt_ptr[12] | (pkt_ptr[13] << 8) | 
                                        (pkt_ptr[14] << 16) | (pkt_ptr[15] << 24);
                            ESP_LOGI(TAG, "OpusHead: version=%d, channels=%d, sample_rate=%d", 
                                   version, channel_count, sample_rate);
                        }
                    }
                }
                continue;
            }
            if (!seen_tags) {
                // Expect OpusTags in second packet
                if (pkt_len >= 8 && std::memcmp(pkt_ptr, "OpusTags", 8) == 0) {
                    seen_tags = true;
                }
                continue;
            }

            // Audio packet (Opus)
            auto packet = std::make_unique<AudioStreamPacket>();
            packet->sample_rate = sample_rate;
            packet->frame_duration = 60;
            packet->payload.resize(pkt_len);
            std::memcpy(packet->payload.data(), pkt_ptr, pkt_len);
            PushPacketToDecodeQueue(std::move(packet), true);
        }

        offset = body_off + body_size;
    }
}

bool AudioService::IsIdle() {
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    return audio_encode_queue_.empty() && audio_decode_queue_.empty() && audio_playback_queue_.empty() && audio_testing_queue_.empty();
}

void AudioService::ResetDecoder() {
    std::lock_guard<std::mutex> decoder_lock(decoder_mutex_);
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    ++decoder_epoch_;
    tts_output_generation_ = 0;
    tts_last_output_us_ = 0;
    opus_decoder_->ResetState();
    timestamp_queue_.clear();
    audio_decode_queue_.clear();
    audio_playback_queue_.clear();
    audio_testing_queue_.clear();
    // A task already inside OutputData cannot be cancelled safely.  It is
    // marked inactive only when that call returns, so state transitions wait
    // for IsPlaybackDrained() rather than pretending it vanished.
    audio_queue_cv_.notify_all();
}

void AudioService::ResetUploadQueues() {
    // Same lock order as Feed -> encode queue: finish the previous PCM
    // callback before opening a new upload generation.
    std::lock_guard<std::mutex> mode_lock(audio_mode_mutex_);
    std::lock_guard<std::mutex> lock(audio_queue_mutex_);
    const uint32_t generation =
        upload_generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
    size_t encode_count = audio_encode_queue_.size();
    size_t send_count = audio_send_queue_.size();
    audio_encode_queue_.clear();
    audio_send_queue_.clear();
    timestamp_queue_.clear();
    upload_read_ok_.store(0, std::memory_order_relaxed);
    upload_read_fail_.store(0, std::memory_order_relaxed);
    upload_pcm_frames_.store(0, std::memory_order_relaxed);
    upload_silent_frames_.store(0, std::memory_order_relaxed);
    upload_encode_ok_.store(0, std::memory_order_relaxed);
    upload_encode_fail_.store(0, std::memory_order_relaxed);
    upload_queue_drop_.store(0, std::memory_order_relaxed);
    upload_send_enqueued_.store(0, std::memory_order_relaxed);
    upload_send_ok_.store(0, std::memory_order_relaxed);
    upload_send_fail_.store(0, std::memory_order_relaxed);
    upload_stale_drop_.store(0, std::memory_order_relaxed);
    audio_queue_cv_.notify_all();
    if (encode_count || send_count) {
        ESP_LOGI(TAG, "[WS_AUDIO_UP] event=reset generation=%u encode=%u send=%u",
                 (unsigned)generation, (unsigned)encode_count, (unsigned)send_count);
    }
}

void AudioService::RecordUploadSendResult(bool sent) {
    if (sent) {
        upload_send_ok_.fetch_add(1, std::memory_order_relaxed);
    } else {
        upload_send_fail_.fetch_add(1, std::memory_order_relaxed);
    }
}

void AudioService::LogUploadStats(const char* reason) const {
    ESP_LOGI(TAG,
             "[WS_AUDIO_UP] reason=%s generation=%u pcm_frames=%u silent=%u "
             "encode_ok=%u encode_fail=%u queue_drop=%u enqueued=%u "
             "send_ok=%u send_fail=%u stale_drop=%u read_ok=%u read_fail=%u processor=%d ready=%d wake=%d",
             reason ? reason : "-",
             (unsigned)upload_generation_.load(std::memory_order_relaxed),
             (unsigned)upload_pcm_frames_.load(std::memory_order_relaxed),
             (unsigned)upload_silent_frames_.load(std::memory_order_relaxed),
             (unsigned)upload_encode_ok_.load(std::memory_order_relaxed),
             (unsigned)upload_encode_fail_.load(std::memory_order_relaxed),
             (unsigned)upload_queue_drop_.load(std::memory_order_relaxed),
             (unsigned)upload_send_enqueued_.load(std::memory_order_relaxed),
             (unsigned)upload_send_ok_.load(std::memory_order_relaxed),
             (unsigned)upload_send_fail_.load(std::memory_order_relaxed),
             (unsigned)upload_stale_drop_.load(std::memory_order_relaxed),
             (unsigned)upload_read_ok_.load(std::memory_order_relaxed),
             (unsigned)upload_read_fail_.load(std::memory_order_relaxed),
             IsAudioProcessorRunning() ? 1 : 0, IsAudioSubsystemReady() ? 1 : 0,
             IsWakeWordRunning() ? 1 : 0);
}

void AudioService::CheckAndUpdateAudioPowerState() {
    auto now = std::chrono::steady_clock::now();
    auto input_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_input_time_).count();
    auto output_elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_output_time_).count();
    if (input_elapsed > AUDIO_POWER_TIMEOUT_MS && codec_->input_enabled()) {
        codec_->EnableInput(false);
    }
    // 双工 codec（如 ESP-BOX-3 的 BoxAudioCodec）在关闭 output 时可能影响 I2S 输入；
    // 若 input 仍在用（listening 中），则暂不关闭 output，避免麦克风失效
    if (output_elapsed > AUDIO_POWER_TIMEOUT_MS && codec_->output_enabled() && !codec_->input_enabled()) {
        codec_->EnableOutput(false);
    }
    if (!codec_->input_enabled() && !codec_->output_enabled()) {
        esp_timer_stop(audio_power_timer_);
    }
}

void AudioService::SetModelsList(srmodel_list_t* models_list) {
    models_list_ = models_list;

#if CONFIG_IDF_TARGET_ESP32S3 || CONFIG_IDF_TARGET_ESP32P4
    if (esp_srmodel_filter(models_list_, ESP_MN_PREFIX, NULL) != nullptr) {
        wake_word_ = std::make_unique<CustomWakeWord>();
    } else if (esp_srmodel_filter(models_list_, ESP_WN_PREFIX, NULL) != nullptr) {
        wake_word_ = std::make_unique<AfeWakeWord>();
    } else {
        wake_word_ = nullptr;
    }
#endif

    if (wake_word_) {
        wake_word_->OnWakeWordDetected([this](const std::string& wake_word) {
            if (callbacks_.on_wake_word_detected) {
                callbacks_.on_wake_word_detected(wake_word);
            }
        });
    }
}

bool AudioService::IsAfeWakeWord() {
    return wake_word_ != nullptr && wake_word_->UsesAfe();
}
