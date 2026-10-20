#include "custom_wake_word.h"
#include "audio_service.h"
#include "task_diagnostics.h"
#include "system_info.h"
#include "assets.h"

#include <esp_log.h>
#include <esp_mn_iface.h>
#include <esp_mn_models.h>
#include <esp_mn_speech_commands.h>
#include <cJSON.h>
#include <chrono>
#include <cmath>


#define TAG "CustomWakeWord"

namespace {
constexpr EventBits_t kDetectionStopped = 1;
constexpr EventBits_t kEncoderStopped = 2;
constexpr uint32_t kDetectionStackSize = 8192;
// 512 samples at 16 kHz need 32 ms; allow the next AFE frame to arrive.
constexpr int kFetchTimeoutMs = 100;
}

CustomWakeWord::CustomWakeWord()
    : wake_word_pcm_(), wake_word_opus_() {
}

CustomWakeWord::~CustomWakeWord() {
    ReleaseResources();
}

void CustomWakeWord::ReleaseResources() {
    Stop();
    shutdown_ = true;
    if (detection_task_ != nullptr) {
        xEventGroupWaitBits(worker_events_, kDetectionStopped, pdFALSE, pdTRUE, portMAX_DELAY);
        vTaskDelete(detection_task_);
        detection_task_ = nullptr;
    }
    if (wake_word_encode_task_ != nullptr) {
        xEventGroupWaitBits(worker_events_, kEncoderStopped, pdFALSE, pdTRUE, portMAX_DELAY);
        vTaskDelete(wake_word_encode_task_);
        wake_word_encode_task_ = nullptr;
    }
    if (afe_data_ != nullptr) {
        afe_iface_->destroy(afe_data_);
        afe_data_ = nullptr;
    }
    if (multinet_model_data_ != nullptr && multinet_ != nullptr) {
        multinet_->destroy(multinet_model_data_);
        multinet_model_data_ = nullptr;
    }

    if (wake_word_encode_task_stack_ != nullptr) {
        heap_caps_free(wake_word_encode_task_stack_);
    }

    if (wake_word_encode_task_buffer_ != nullptr) {
        heap_caps_free(wake_word_encode_task_buffer_);
    }

    if (detection_task_stack_ != nullptr) heap_caps_free(detection_task_stack_);
    if (detection_task_buffer_ != nullptr) heap_caps_free(detection_task_buffer_);
    if (worker_events_ != nullptr) vEventGroupDelete(worker_events_);
    if (owns_models_ && models_ != nullptr) {
        esp_srmodel_deinit(models_);
    }
    models_ = nullptr;
    owns_models_ = false;
    wake_word_encode_task_stack_ = nullptr;
    wake_word_encode_task_buffer_ = nullptr;
    detection_task_stack_ = nullptr;
    detection_task_buffer_ = nullptr;
    worker_events_ = nullptr;
}

bool CustomWakeWord::ParseWakenetModelConfig() {
    // Read index.json
    auto& assets = Assets::GetInstance();
    void* ptr = nullptr;
    size_t size = 0;
    if (!assets.GetAssetData("index.json", ptr, size)) {
        ESP_LOGE(TAG, "Failed to read index.json");
        return false;
    }
    cJSON* root = cJSON_ParseWithLength(static_cast<char*>(ptr), size);
    if (root == nullptr) {
        ESP_LOGE(TAG, "Failed to parse index.json");
        return false;
    }
    cJSON* multinet_model = cJSON_GetObjectItem(root, "multinet_model");
    if (cJSON_IsObject(multinet_model)) {
        cJSON* language = cJSON_GetObjectItem(multinet_model, "language");
        cJSON* duration = cJSON_GetObjectItem(multinet_model, "duration");
        cJSON* threshold = cJSON_GetObjectItem(multinet_model, "threshold");
        cJSON* commands = cJSON_GetObjectItem(multinet_model, "commands");
        if (cJSON_IsString(language)) {
            language_ = language->valuestring;
        }
        if (cJSON_IsNumber(duration)) {
            duration_ = duration->valueint;
        }
        if (cJSON_IsNumber(threshold)) {
            threshold_ = threshold->valuedouble;
        }
        if (cJSON_IsArray(commands)) {
            for (int i = 0; i < cJSON_GetArraySize(commands); i++) {
                cJSON* command = cJSON_GetArrayItem(commands, i);
                if (cJSON_IsObject(command)) {
                    cJSON* command_name = cJSON_GetObjectItem(command, "command");
                    cJSON* text = cJSON_GetObjectItem(command, "text");
                    cJSON* action = cJSON_GetObjectItem(command, "action");
                    if (cJSON_IsString(command_name) && cJSON_IsString(text) && cJSON_IsString(action)) {
                        commands_.push_back({command_name->valuestring, text->valuestring, action->valuestring});
                        ESP_LOGI(TAG, "Command: %s, Text: %s, Action: %s", command_name->valuestring, text->valuestring, action->valuestring);
                    }
                }
            }
        }
    }
    cJSON_Delete(root);
    return !commands_.empty() && duration_ > 0 && std::isfinite(threshold_) &&
           threshold_ > 0.0f && threshold_ < 1.0f;
}


bool CustomWakeWord::Initialize(AudioCodec* codec, srmodel_list_t* models_list) {
    ReleaseResources();
    shutdown_ = false;
    codec_ = codec;
    commands_.clear();

    if (models_list == nullptr) {
        language_ = "cn";
        models_ = esp_srmodel_init("model");
        owns_models_ = true;
#ifdef CONFIG_CUSTOM_WAKE_WORD
        threshold_ = CONFIG_CUSTOM_WAKE_WORD_THRESHOLD / 100.0f;
        commands_.push_back({CONFIG_CUSTOM_WAKE_WORD, CONFIG_CUSTOM_WAKE_WORD_DISPLAY, "wake"});
#endif
    } else {
        models_ = models_list;
        if (!ParseWakenetModelConfig()) {
            ESP_LOGE(TAG, "Missing or invalid custom wake commands in assets/index.json");
            return false;
        }
    }

    if (models_ == nullptr || models_->num <= 0 || commands_.empty()) {
        ESP_LOGE(TAG, "Failed to initialize wakenet model");
        return false;
    }

    // 初始化 multinet (命令词识别)
    mn_name_ = esp_srmodel_filter(models_, ESP_MN_PREFIX, language_.c_str());
    if (mn_name_ == nullptr) {
        ESP_LOGE(TAG, "Failed to initialize multinet, mn_name is nullptr");
        ESP_LOGI(TAG, "Please refer to https://pcn7cs20v8cr.feishu.cn/wiki/CpQjwQsCJiQSWSkYEvrcxcbVnwh to add custom wake word");
        return false;
    }

    multinet_ = esp_mn_handle_from_name(mn_name_);
    if (multinet_ == nullptr) return false;
    multinet_model_data_ = multinet_->create(mn_name_, duration_);
    if (multinet_model_data_ == nullptr) return false;
    multinet_->set_det_threshold(multinet_model_data_, threshold_);
    if (esp_mn_commands_clear() != ESP_OK) return false;
    for (int i = 0; i < commands_.size(); i++) {
        if (esp_mn_commands_add(i + 1, commands_[i].command.c_str()) != ESP_OK) {
            ESP_LOGE(TAG, "Invalid custom wake command: %s", commands_[i].command.c_str());
            return false;
        }
    }
    if (esp_mn_commands_update() != nullptr) {
        ESP_LOGE(TAG, "MultiNet rejected custom wake commands");
        return false;
    }
    
    multinet_->print_active_speech_commands(multinet_model_data_);
    multinet_frame_samples_ = multinet_->get_samp_chunksize(multinet_model_data_);
    if (multinet_frame_samples_ == 0) return false;

    // Keep the microphone and playback-reference channels together until AEC.
    const int references = codec_->input_reference() ? 1 : 0;
    if (codec_->input_channels() <= references) return false;
    std::string input_format(codec_->input_channels() - references, 'M');
    input_format.append(references, 'R');
    afe_config_t* config = afe_config_init(input_format.c_str(), models_, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    if (config == nullptr) return false;
    config->aec_init = codec_->input_reference();
    config->aec_mode = AEC_MODE_SR_HIGH_PERF;
    config->wakenet_init = false;
    // Continuous command detection must not lose the start of a short wake phrase to VAD.
    config->vad_init = false;
    config->afe_perferred_core = 0;
    config->afe_perferred_priority = 1;
    config->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    afe_iface_ = esp_afe_handle_from_config(config);
    if (afe_iface_ != nullptr) afe_data_ = afe_iface_->create_from_config(config);
    afe_config_free(config);
    if (afe_data_ == nullptr) return false;

    worker_events_ = xEventGroupCreate();
    detection_task_stack_ = static_cast<StackType_t*>(heap_caps_malloc(kDetectionStackSize, MALLOC_CAP_SPIRAM));
    detection_task_buffer_ = static_cast<StaticTask_t*>(heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL));
    if (!worker_events_ || !detection_task_stack_ || !detection_task_buffer_) return false;
    detection_task_ = xTaskCreateStatic([](void* arg) {
        auto* self = static_cast<CustomWakeWord*>(arg);
        task_diag::LogCurrentTask(TAG, "custom_detection_start", 3, -1);
        self->AudioDetectionTask();
        xEventGroupSetBits(self->worker_events_, kDetectionStopped);
        vTaskSuspend(nullptr);
    }, "custom_detection", kDetectionStackSize, this, 3,
       detection_task_stack_, detection_task_buffer_);
    if (detection_task_ == nullptr) return false;
    ESP_LOGI(TAG, "[CUSTOM_WAKE] model=%s input=%s aec=%d threshold=%.2f commands=%u feed=%d mn_frame=%u",
             mn_name_, input_format.c_str(), references, threshold_, unsigned(commands_.size()),
             afe_iface_->get_feed_chunksize(afe_data_), unsigned(multinet_frame_samples_));
    return true;
}

void CustomWakeWord::OnWakeWordDetected(std::function<void(const std::string& wake_word)> callback) {
    wake_word_detected_callback_ = callback;
}

void CustomWakeWord::Start() {
    std::lock_guard<std::mutex> feed_lock(feed_mutex_);
    std::lock_guard<std::mutex> lock(detection_mutex_);
    generation_++;
    processed_pcm_.clear();
    fed_samples_ = 0;
    fetched_samples_ = 0;
    if (afe_data_) afe_iface_->reset_buffer(afe_data_);
    if (multinet_model_data_) multinet_->clean(multinet_model_data_);
    {
        std::lock_guard<std::mutex> pcm_lock(wake_word_mutex_);
        wake_word_pcm_.clear();
    }
    running_ = true;
    ESP_LOGI(TAG, "[CUSTOM_WAKE] detection_started generation=%lu", (unsigned long)generation_.load());
}

void CustomWakeWord::Stop() {
    std::lock_guard<std::mutex> feed_lock(feed_mutex_);
    running_ = false;
    generation_++;
    // Invalidate first, then wait for a fetch already in flight before reset.
    std::lock_guard<std::mutex> lock(detection_mutex_);
    processed_pcm_.clear();
    if (afe_data_) afe_iface_->reset_buffer(afe_data_);
    if (multinet_model_data_) multinet_->clean(multinet_model_data_);
}

void CustomWakeWord::Feed(const std::vector<int16_t>& data) {
    // AFE feed may block; the fetch/detect worker must remain free to drain it.
    std::lock_guard<std::mutex> lock(feed_mutex_);
    if (afe_data_ == nullptr || !running_) {
        return;
    }
    const size_t expected = GetFeedSize() * codec_->input_channels();
    if (data.size() != expected) {
        ESP_LOGW(TAG, "Unexpected AFE feed size: %u != %u", unsigned(data.size()), unsigned(expected));
        return;
    }
    afe_iface_->feed(afe_data_, data.data());
    fed_samples_.fetch_add(data.size() / codec_->input_channels());
}

void CustomWakeWord::AudioDetectionTask() {
    while (!shutdown_) {
        // Voice processing owns the input while wake detection is stopped.
        // Do not fetch from an AFE which is deliberately no longer being fed.
        if (!running_) {
            vTaskDelay(pdMS_TO_TICKS(20));
            continue;
        }
        const uint32_t generation = generation_.load();
        const size_t chunk = afe_iface_->get_fetch_chunksize(afe_data_);
        bool waiting_for_feed = false;
        {
        std::lock_guard<std::mutex> lock(detection_mutex_);
        if (!running_ || generation != generation_.load()) continue;
        // Keep one input frame of lookahead. Fetching once more after the last
        // fed frame causes a false empty-ring warning at every mode switch.
        // Continuous microphone input advances this bounded 32 ms reserve.
        waiting_for_feed = chunk == 0 || fed_samples_.load() < fetched_samples_ + chunk + GetFeedSize();
        if (!waiting_for_feed) {
        auto* result = afe_iface_->fetch_with_delay(afe_data_, pdMS_TO_TICKS(kFetchTimeoutMs));
        if (!result || result->ret_value == ESP_FAIL || !result->data || result->data_size <= 0) continue;
        fetched_samples_ += result->data_size / sizeof(int16_t);
        // A frame fetched across Stop/Start belongs to the previous listening epoch.
        if (!running_ || generation != generation_.load()) continue;
        DetectProcessedAudio(result->data, result->data_size / sizeof(int16_t));
        }
        }
        if (waiting_for_feed) vTaskDelay(pdMS_TO_TICKS(5));
    }
}

void CustomWakeWord::DetectProcessedAudio(const int16_t* data, size_t samples) {
    processed_pcm_.insert(processed_pcm_.end(), data, data + samples);
    // AFE and MultiNet do not necessarily have the same frame length.
    while (running_ && processed_pcm_.size() >= multinet_frame_samples_) {
        std::vector<int16_t> frame(processed_pcm_.begin(), processed_pcm_.begin() + multinet_frame_samples_);
        processed_pcm_.erase(processed_pcm_.begin(), processed_pcm_.begin() + multinet_frame_samples_);
        StoreWakeWordData(frame);
        const auto mn_state = multinet_->detect(multinet_model_data_, frame.data());
        if (mn_state == ESP_MN_STATE_DETECTING) {
            continue;
        } else if (mn_state == ESP_MN_STATE_DETECTED) {
            esp_mn_results_t *mn_result = multinet_->get_results(multinet_model_data_);
            if (mn_result == nullptr) {
                multinet_->clean(multinet_model_data_);
                continue;
            }
            for (int i = 0; i < mn_result->num && running_; i++) {
                const int command_index = mn_result->command_id[i] - 1;
                if (command_index < 0 || command_index >= commands_.size()) continue;
                ESP_LOGI(TAG, "Custom wake word detected: command_id=%d, string=%s, prob=%f",
                         mn_result->command_id[i], mn_result->string, mn_result->prob[i]);
                auto& command = commands_[command_index];
                if (command.action == "wake") {
                    last_detected_wake_word_ = command.text;
                    running_ = false;
                    if (wake_word_detected_callback_) {
                        wake_word_detected_callback_(last_detected_wake_word_);
                    }
                }
            }
            multinet_->clean(multinet_model_data_);
        } else if (mn_state == ESP_MN_STATE_TIMEOUT) {
            ESP_LOGD(TAG, "Command word detection timeout, cleaning state");
            multinet_->clean(multinet_model_data_);
        }
    }
}

size_t CustomWakeWord::GetFeedSize() {
    if (afe_data_ == nullptr) {
        return 0;
    }
    return afe_iface_->get_feed_chunksize(afe_data_);
}

void CustomWakeWord::StoreWakeWordData(const std::vector<int16_t>& data) {
    std::lock_guard<std::mutex> lock(wake_word_mutex_);
    // store audio data to wake_word_pcm_
    wake_word_pcm_.push_back(data);
    // keep about 2 seconds of data, detect duration is 30ms (sample_rate == 16000, chunksize == 512)
    while (wake_word_pcm_.size() * multinet_frame_samples_ > 16000 * 2) {
        wake_word_pcm_.pop_front();
    }
}

void CustomWakeWord::EncodeWakeWordData() {
    const size_t stack_size = 4096 * 7;
    if (wake_word_encode_task_ != nullptr) {
        xEventGroupWaitBits(worker_events_, kEncoderStopped, pdFALSE, pdTRUE, portMAX_DELAY);
        vTaskDelete(wake_word_encode_task_);
        wake_word_encode_task_ = nullptr;
    }
    xEventGroupClearBits(worker_events_, kEncoderStopped);
    {
        std::lock_guard<std::mutex> lock(wake_word_mutex_);
        wake_word_opus_.clear();
        encoding_pcm_ = std::move(wake_word_pcm_);
        wake_word_pcm_.clear();
    }
    if (wake_word_encode_task_stack_ == nullptr) {
        wake_word_encode_task_stack_ = (StackType_t*)heap_caps_malloc(stack_size, MALLOC_CAP_SPIRAM);
    }
    if (wake_word_encode_task_buffer_ == nullptr) {
        wake_word_encode_task_buffer_ = (StaticTask_t*)heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL);
    }

    if (!wake_word_encode_task_stack_ || !wake_word_encode_task_buffer_) {
        ESP_LOGE(TAG, "Could not allocate custom wake encoder task");
        std::lock_guard<std::mutex> lock(wake_word_mutex_);
        wake_word_opus_.emplace_back();
        wake_word_cv_.notify_all();
        return;
    }

    wake_word_encode_task_ = xTaskCreateStatic([](void* arg) {
        task_diag::LogCurrentTask("CustomWakeWord", "encode_wake_word_start", 2, -1);
        auto this_ = (CustomWakeWord*)arg;
        {
            auto start_time = esp_timer_get_time();
            auto encoder = std::make_unique<OpusEncoderWrapper>(16000, 1, OPUS_FRAME_DURATION_MS);
            encoder->SetComplexity(0); // 0 is the fastest

            int packets = 0;
            for (auto& pcm: this_->encoding_pcm_) {
                encoder->Encode(std::move(pcm), [this_](std::vector<uint8_t>&& opus) {
                    std::lock_guard<std::mutex> lock(this_->wake_word_mutex_);
                    this_->wake_word_opus_.emplace_back(std::move(opus));
                    this_->wake_word_cv_.notify_all();
                });
                packets++;
            }
            this_->encoding_pcm_.clear();

            auto end_time = esp_timer_get_time();
            ESP_LOGI(TAG, "Encode wake word opus %d packets in %ld ms", packets, (long)((end_time - start_time) / 1000));

            std::lock_guard<std::mutex> lock(this_->wake_word_mutex_);
            this_->wake_word_opus_.push_back(std::vector<uint8_t>());
            this_->wake_word_cv_.notify_all();
        }
        xEventGroupSetBits(this_->worker_events_, kEncoderStopped);
        vTaskSuspend(nullptr);
    }, "encode_wake_word", stack_size, this, 2, wake_word_encode_task_stack_, wake_word_encode_task_buffer_);
    task_diag::LogTaskHandle("CustomWakeWord", "encode_wake_word_created",
                             wake_word_encode_task_, 2, -1);
    if (wake_word_encode_task_ == nullptr) {
        ESP_LOGE(TAG, "Could not start custom wake encoder task");
        std::lock_guard<std::mutex> lock(wake_word_mutex_);
        wake_word_opus_.emplace_back();
        wake_word_cv_.notify_all();
    }
}

bool CustomWakeWord::GetWakeWordOpus(std::vector<uint8_t>& opus) {
    std::unique_lock<std::mutex> lock(wake_word_mutex_);
    if (!wake_word_cv_.wait_for(lock, std::chrono::milliseconds(3000), [this]() {
        return !wake_word_opus_.empty();
    })) {
        ESP_LOGE(TAG, "Timed out waiting for custom wake audio encoding");
        return false;
    }
    opus.swap(wake_word_opus_.front());
    wake_word_opus_.pop_front();
    return !opus.empty();
}
