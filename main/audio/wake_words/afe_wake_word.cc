#include "afe_wake_word.h"
#include "audio_service.h"

#include <esp_log.h>
#include <cstring>
#include <sstream>
#include <algorithm>

#define DETECTION_RUNNING_EVENT 1
#define TAG "AfeWakeWord"

// 定义环形缓冲区大小：16kHz * 2秒 = 32000 个采样点
// 占用 PSRAM 约 64KB
#define WAKE_BUFFER_SAMPLES_COUNT (16000 * 2)

AfeWakeWord::AfeWakeWord()
    : afe_data_(nullptr),
      wake_buffer_ptr_(nullptr),
      wake_buffer_len_(WAKE_BUFFER_SAMPLES_COUNT),
      wake_buffer_head_(0),
      wake_word_opus_() {

    event_group_ = xEventGroupCreate();
}

AfeWakeWord::~AfeWakeWord() {
    if (afe_data_ != nullptr) {
        afe_iface_->destroy(afe_data_);
    }
    if (wake_word_encode_task_stack_ != nullptr) heap_caps_free(wake_word_encode_task_stack_);
    if (wake_word_encode_task_buffer_ != nullptr) heap_caps_free(wake_word_encode_task_buffer_);
    if (detection_task_stack_ != nullptr) heap_caps_free(detection_task_stack_);
    if (detection_task_buffer_ != nullptr) heap_caps_free(detection_task_buffer_);
    if (wake_buffer_ptr_ != nullptr) heap_caps_free(wake_buffer_ptr_);
    if (models_ != nullptr) {
        esp_srmodel_deinit(models_);
    }
    vEventGroupDelete(event_group_);
}

bool AfeWakeWord::Initialize(AudioCodec* codec, srmodel_list_t* models_list) {
    codec_ = codec;
    int ref_num = codec_->input_reference() ? 1 : 0;

    if (models_list == nullptr) {
        models_ = esp_srmodel_init("model");
    } else {
        models_ = models_list;
    }

    if (models_ == nullptr || models_->num == -1) {
        ESP_LOGE(TAG, "Failed to initialize wakenet model");
        return false;
    }
    for (int i = 0; i < models_->num; i++) {
        ESP_LOGI(TAG, "Model %d: %s", i, models_->model_name[i]);
        if (strstr(models_->model_name[i], ESP_WN_PREFIX) != NULL) {
            wakenet_model_ = models_->model_name[i];
            char* words = esp_srmodel_get_wake_words(models_, wakenet_model_);
            if (words) {
                std::stringstream ss(words);
                std::string word;
                while (std::getline(ss, word, ';')) {
                    wake_words_.push_back(word);
                }
            }
        }
    }

    std::string input_format;
    for (int i = 0; i < codec_->input_channels() - ref_num; i++) {
        input_format.push_back('M');
    }
    for (int i = 0; i < ref_num; i++) {
        input_format.push_back('R');
    }
    
    afe_config_t* afe_config = afe_config_init(input_format.c_str(), models_, AFE_TYPE_SR, AFE_MODE_HIGH_PERF);
    afe_config->aec_init = codec_->input_reference();
    afe_config->aec_mode = AEC_MODE_SR_HIGH_PERF;
    afe_config->afe_perferred_core = 1;
    afe_config->afe_perferred_priority = 10; 
    afe_config->memory_alloc_mode = AFE_MEMORY_ALLOC_MORE_PSRAM;
    
    afe_iface_ = esp_afe_handle_from_config(afe_config);
    afe_data_ = afe_iface_->create_from_config(afe_config);

    wake_buffer_ptr_ = (int16_t*)heap_caps_malloc(wake_buffer_len_ * sizeof(int16_t), MALLOC_CAP_SPIRAM);
    if (wake_buffer_ptr_ == nullptr) {
        ESP_LOGE(TAG, "Failed to allocate wake buffer in PSRAM");
        return false;
    }
    memset(wake_buffer_ptr_, 0, wake_buffer_len_ * sizeof(int16_t));

    const uint32_t task_stack_size = 4096;
    detection_task_stack_ = (StackType_t*)heap_caps_malloc(task_stack_size, MALLOC_CAP_SPIRAM);
    detection_task_buffer_ = (StaticTask_t*)heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL);

    if (detection_task_stack_ && detection_task_buffer_) {
        xTaskCreateStatic([](void* arg) {
            auto this_ = (AfeWakeWord*)arg;
            this_->AudioDetectionTask();
            vTaskDelete(NULL);
        }, "audio_detection", task_stack_size, this, 10, detection_task_stack_, detection_task_buffer_);
    } else {
        ESP_LOGE(TAG, "Failed to allocate detection task stack");
        return false;
    }

    return true;
}

void AfeWakeWord::OnWakeWordDetected(std::function<void(const std::string& wake_word)> callback) {
    wake_word_detected_callback_ = callback;
}

void AfeWakeWord::Start() {
    xEventGroupSetBits(event_group_, DETECTION_RUNNING_EVENT);
}

void AfeWakeWord::Stop() {
    xEventGroupClearBits(event_group_, DETECTION_RUNNING_EVENT);
    if (afe_data_ != nullptr) {
        afe_iface_->reset_buffer(afe_data_);
    }
}

void AfeWakeWord::Feed(const std::vector<int16_t>& data) {
    if (afe_data_ == nullptr) return;
    afe_iface_->feed(afe_data_, data.data());
}

size_t AfeWakeWord::GetFeedSize() {
    if (afe_data_ == nullptr) return 0;
    return afe_iface_->get_feed_chunksize(afe_data_);
}

void AfeWakeWord::AudioDetectionTask() {
    auto fetch_size = afe_iface_->get_fetch_chunksize(afe_data_);
    auto feed_size = afe_iface_->get_feed_chunksize(afe_data_);
    ESP_LOGI(TAG, "Audio detection task started, feed size: %d fetch size: %d", feed_size, fetch_size);

    while (true) {
        // 1. 始终 Fetch，防爆满
        auto res = afe_iface_->fetch_with_delay(afe_data_, portMAX_DELAY);
        if (res == nullptr || res->ret_value == ESP_FAIL) {
            continue;
        }

        // 2. 状态检查
        EventBits_t bits = xEventGroupGetBits(event_group_);
        bool is_running = (bits & DETECTION_RUNNING_EVENT);
        
        if (!is_running) {
            StoreWakeWordData(res->data, res->data_size / sizeof(int16_t));
            continue; 
        }

        // 3. 正常逻辑
        StoreWakeWordData(res->data, res->data_size / sizeof(int16_t));

        if (res->wakeup_state == WAKENET_DETECTED) {
            // 【重要】这里删除了 Stop()，让主程序接管控制流
            
            int idx = res->wakenet_model_index - 1;
            if (idx >= 0 && idx < wake_words_.size()) {
                last_detected_wake_word_ = wake_words_[idx];
            } else {
                last_detected_wake_word_ = "unknown";
            }

            ESP_LOGI(TAG, "Wake word detected: %s", last_detected_wake_word_.c_str());

            if (wake_word_detected_callback_) {
                wake_word_detected_callback_(last_detected_wake_word_);
            }
        }
    }
}

void AfeWakeWord::StoreWakeWordData(const int16_t* data, size_t samples) {
    if (samples > wake_buffer_len_) {
        data += (samples - wake_buffer_len_);
        samples = wake_buffer_len_;
    }

    size_t space_at_end = wake_buffer_len_ - wake_buffer_head_;
    
    if (samples <= space_at_end) {
        memcpy(wake_buffer_ptr_ + wake_buffer_head_, data, samples * sizeof(int16_t));
        wake_buffer_head_ += samples;
    } else {
        memcpy(wake_buffer_ptr_ + wake_buffer_head_, data, space_at_end * sizeof(int16_t));
        size_t remaining = samples - space_at_end;
        memcpy(wake_buffer_ptr_, data + space_at_end, remaining * sizeof(int16_t));
        wake_buffer_head_ = remaining;
    }

    if (wake_buffer_head_ >= wake_buffer_len_) {
        wake_buffer_head_ = 0;
    }
}

void AfeWakeWord::EncodeWakeWordData() {
    const size_t stack_size = 4096 * 7; 
    wake_word_opus_.clear();
    
    if (wake_word_encode_task_stack_ == nullptr) {
        wake_word_encode_task_stack_ = (StackType_t*)heap_caps_malloc(stack_size, MALLOC_CAP_SPIRAM);
    }
    if (wake_word_encode_task_buffer_ == nullptr) {
        wake_word_encode_task_buffer_ = (StaticTask_t*)heap_caps_malloc(sizeof(StaticTask_t), MALLOC_CAP_INTERNAL);
    }

    wake_word_encode_task_ = xTaskCreateStatic([](void* arg) {
        auto this_ = (AfeWakeWord*)arg;
        {
            auto start_time = esp_timer_get_time();
            int frame_size_ms = 20; 
            int frame_samples = 16000 * frame_size_ms / 1000; 

            auto encoder = std::make_unique<OpusEncoderWrapper>(16000, 1, frame_size_ms);
            encoder->SetComplexity(0); 

            int packets = 0;
            
            size_t read_cursor = this_->wake_buffer_head_;
            size_t samples_processed = 0;
            size_t total_samples = this_->wake_buffer_len_;
            
            std::vector<int16_t> pcm_chunk(frame_samples);

            while (samples_processed < total_samples) {
                for (int i = 0; i < frame_samples; i++) {
                    pcm_chunk[i] = this_->wake_buffer_ptr_[read_cursor];
                    read_cursor++;
                    if (read_cursor >= this_->wake_buffer_len_) {
                        read_cursor = 0;
                    }
                }
                samples_processed += frame_samples;

                std::vector<int16_t> temp_chunk = pcm_chunk; 
                encoder->Encode(std::move(temp_chunk), [this_](std::vector<uint8_t>&& opus) {
                    std::lock_guard<std::mutex> lock(this_->wake_word_mutex_);
                    this_->wake_word_opus_.emplace_back(std::move(opus));
                    this_->wake_word_cv_.notify_all();
                });
                packets++;
            }

            auto end_time = esp_timer_get_time();
            ESP_LOGI(TAG, "Encode wake word opus %d packets in %ld ms", packets, (long)((end_time - start_time) / 1000));

            std::lock_guard<std::mutex> lock(this_->wake_word_mutex_);
            this_->wake_word_opus_.push_back(std::vector<uint8_t>()); 
            this_->wake_word_cv_.notify_all();
        }
        vTaskDelete(NULL);
    }, "encode_wake_word", stack_size, this, 5, wake_word_encode_task_stack_, wake_word_encode_task_buffer_);
}

bool AfeWakeWord::GetWakeWordOpus(std::vector<uint8_t>& opus) {
    std::unique_lock<std::mutex> lock(wake_word_mutex_);
    wake_word_cv_.wait(lock, [this]() {
        return !wake_word_opus_.empty();
    });
    if (wake_word_opus_.empty()) return false;
    opus.swap(wake_word_opus_.front());
    wake_word_opus_.pop_front();
    return !opus.empty();
}