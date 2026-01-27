#ifndef AFE_AUDIO_PROCESSOR_H
#define AFE_AUDIO_PROCESSOR_H

#include <esp_afe_sr_models.h>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <freertos/event_groups.h>

#include <string>
#include <vector>
#include <functional>

// 包含这个头文件会自动引入 SpiramAllocator 的定义
// 必须确保你已经按照上一步修改了 audio_processor.h
#include "audio_processor.h"
#include "audio_codec.h"

class AfeAudioProcessor : public AudioProcessor {
public:
    AfeAudioProcessor();
    ~AfeAudioProcessor();

    void Initialize(AudioCodec* codec, int frame_duration_ms, srmodel_list_t* models_list) override;
    
    // Feed 保持标准 vector 不变，因为它通常来自 I2S (DMA 需要内部内存)
    void Feed(std::vector<int16_t>&& data) override;
    
    void Start() override;
    void Stop() override;
    bool IsRunning() override;

    // 【正确】这里直接使用 SpiramAllocator，编译器会从 audio_processor.h 中找到定义
    void OnOutput(std::function<void(std::vector<int16_t, SpiramAllocator<int16_t>>&& data)> callback) override;

    void OnVadStateChange(std::function<void(bool speaking)> callback) override;
    size_t GetFeedSize() override;
    void EnableDeviceAec(bool enable) override;

private:
    EventGroupHandle_t event_group_ = nullptr;
    const esp_afe_sr_iface_t* afe_iface_ = nullptr;
    esp_afe_sr_data_t* afe_data_ = nullptr;

    // 【正确】成员变量使用 SpiramAllocator
    std::function<void(std::vector<int16_t, SpiramAllocator<int16_t>>&& data)> output_callback_;
    
    std::function<void(bool speaking)> vad_state_change_callback_;
    AudioCodec* codec_ = nullptr;
    int frame_samples_ = 0;
    bool is_speaking_ = false;

    // 【正确】内部缓冲区使用 SpiramAllocator，确保长驻内存住在 PSRAM
    std::vector<int16_t, SpiramAllocator<int16_t>> output_buffer_;

    void AudioProcessorTask();
};

#endif // AFE_AUDIO_PROCESSOR_H