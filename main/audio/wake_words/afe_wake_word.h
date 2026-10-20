#ifndef AFE_WAKE_WORD_H
#define AFE_WAKE_WORD_H

#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/event_groups.h>

#include <esp_afe_sr_models.h>
#include <esp_nsn_models.h>
#include <model_path.h>

#include <deque>
#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <condition_variable>
#include <atomic>

#include "audio_codec.h"
#include "wake_word.h"

class AfeWakeWord : public WakeWord {
public:
    AfeWakeWord();
    ~AfeWakeWord();

    bool Initialize(AudioCodec* codec, srmodel_list_t* models_list);
    void Feed(const std::vector<int16_t>& data);
    void OnWakeWordDetected(std::function<void(const std::string& wake_word)> callback);
    void Start();
    void Stop();
    size_t GetFeedSize();
    void EncodeWakeWordData();
    bool GetWakeWordOpus(std::vector<uint8_t>& opus);
    const std::string& GetLastDetectedWakeWord() const { return last_detected_wake_word_; }
    bool UsesAfe() const override { return true; }

private:
    srmodel_list_t *models_ = nullptr;
    const esp_afe_sr_iface_t* afe_iface_ = nullptr;
    esp_afe_sr_data_t* afe_data_ = nullptr;
    char* wakenet_model_ = nullptr;
    std::vector<std::string> wake_words_;
    EventGroupHandle_t event_group_;
    std::function<void(const std::string& wake_word)> wake_word_detected_callback_;
    AudioCodec* codec_ = nullptr;
    std::string last_detected_wake_word_;
    std::atomic<bool> wake_detect_latched_{false};
    std::vector<int16_t> input_buffer_;
    std::mutex input_buffer_mutex_;

    // --- 编码任务资源 ---
    TaskHandle_t wake_word_encode_task_ = nullptr;
    StaticTask_t* wake_word_encode_task_buffer_ = nullptr;
    StackType_t* wake_word_encode_task_stack_ = nullptr;

    // --- 检测任务资源 (新增，用于移至 PSRAM) ---
    TaskHandle_t detection_task_ = nullptr;
    StaticTask_t* detection_task_buffer_ = nullptr;
    StackType_t* detection_task_stack_ = nullptr;

    // --- 唤醒词音频数据缓存 (修改为 PSRAM 环形缓冲区) ---
    // 替代原有的 std::deque<std::vector<int16_t>> wake_word_pcm_;
    int16_t* wake_buffer_ptr_ = nullptr;  // PSRAM 缓冲区指针
    size_t wake_buffer_len_ = 0;          // 缓冲区总长度 (samples)
    size_t wake_buffer_head_ = 0;         // 当前写入位置索引

    // --- Opus 编码输出队列 ---
    std::deque<std::vector<uint8_t>> wake_word_opus_;
    std::mutex wake_word_mutex_;
    std::condition_variable wake_word_cv_;

    void StoreWakeWordData(const int16_t* data, size_t size);
    void AudioDetectionTask();
};

#endif
