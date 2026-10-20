#include <atomic>
#include <cassert>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <string>
#include <thread>
#include <vector>

#define TAG "CustomWakeWord"
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGD(...) ((void)0)
#define ESP_FAIL -1
#define pdMS_TO_TICKS(ms) (ms)
// @FETCH_TIMEOUT
void vTaskDelay(int ms) { std::this_thread::sleep_for(std::chrono::milliseconds(ms)); }
using EventGroupHandle_t = void*;
using TaskHandle_t = void*;
using StackType_t = uint8_t;
struct StaticTask_t {};
struct srmodel_list_t {};
struct model_iface_data_t {};
struct esp_afe_sr_data_t {};
enum esp_mn_state_t { ESP_MN_STATE_DETECTING, ESP_MN_STATE_DETECTED, ESP_MN_STATE_TIMEOUT };
struct esp_mn_results_t { int num = 1; int command_id[4]{1}; const char* string = "ni hao xiao nian"; float prob[4]{0.8f}; };
struct afe_fetch_result_t { int ret_value = 0; int16_t* data = nullptr; int data_size = 0; };
struct esp_mn_iface_t {
    esp_mn_state_t (*detect)(model_iface_data_t*, int16_t*);
    esp_mn_results_t* (*get_results)(model_iface_data_t*);
    void (*clean)(model_iface_data_t*);
};
struct esp_afe_sr_iface_t {
    int (*get_feed_chunksize)(esp_afe_sr_data_t*);
    void (*feed)(esp_afe_sr_data_t*, const int16_t*);
    afe_fetch_result_t* (*fetch_with_delay)(esp_afe_sr_data_t*, int);
    void (*reset_buffer)(esp_afe_sr_data_t*);
};
struct AudioCodec { int input_channels() const { return 2; } };

// @BASE
#define private public
// @CLASS
#undef private

std::vector<std::vector<int16_t>> detected_frames;
std::vector<int16_t> fed_interleaved;
esp_mn_state_t next_state = ESP_MN_STATE_DETECTING;
esp_mn_results_t results;
bool null_results = false;
int cleans = 0, resets = 0;
std::function<afe_fetch_result_t*()> fetch;
model_iface_data_t model;
esp_afe_sr_data_t afe;
AudioCodec codec;
esp_mn_iface_t mn_api{
    [](model_iface_data_t*, int16_t* data) {
        detected_frames.emplace_back(data, data + 4);
        return next_state;
    },
    [](model_iface_data_t*) -> esp_mn_results_t* { return null_results ? nullptr : &results; },
    [](model_iface_data_t*) { cleans++; }
};
esp_afe_sr_iface_t afe_api{
    [](esp_afe_sr_data_t*) { return 4; },
    [](esp_afe_sr_data_t*, const int16_t* data) { fed_interleaved.assign(data, data + 8); },
    [](esp_afe_sr_data_t*, int ticks) { assert(ticks >= 32); return fetch(); },
    [](esp_afe_sr_data_t*) { resets++; }
};
CustomWakeWord::CustomWakeWord() = default;
CustomWakeWord::~CustomWakeWord() = default;
bool CustomWakeWord::Initialize(AudioCodec*, srmodel_list_t*) { return false; }
void CustomWakeWord::EncodeWakeWordData() {}
bool CustomWakeWord::GetWakeWordOpus(std::vector<uint8_t>&) { return false; }
// @METHODS

void configure(CustomWakeWord& wake) {
    wake.codec_ = &codec;
    wake.afe_iface_ = &afe_api;
    wake.afe_data_ = &afe;
    wake.multinet_ = &mn_api;
    wake.multinet_model_data_ = &model;
    wake.multinet_frame_samples_ = 4;
    wake.commands_.push_back({"ni hao xiao nian", "你好，小念", "wake"});
    detected_frames.clear();
    fed_interleaved.clear();
    next_state = ESP_MN_STATE_DETECTING;
    null_results = false;
    results.command_id[0] = 1;
    wake.Start();
}

int main() {
    {
        CustomWakeWord wake;
        configure(wake);
        WakeWord& interface = wake;
        assert(interface.UsesAfe());
        const std::vector<int16_t> mic_ref{1, 91, 2, 92, 3, 93, 4, 94};
        wake.Feed(mic_ref);
        assert(fed_interleaved == mic_ref);
        assert(detected_frames.empty()); // MultiNet must never receive raw mic/reference samples.
        wake.Feed({9, 9});
        assert(fed_interleaved == mic_ref);
        std::vector<int16_t> first{11, 12, 13}, second{14, 15, 16};
        wake.DetectProcessedAudio(first.data(), first.size());
        assert(detected_frames.empty());
        wake.DetectProcessedAudio(second.data(), second.size());
        assert((detected_frames == std::vector<std::vector<int16_t>>{{11, 12, 13, 14}}));
        assert((wake.processed_pcm_ == std::vector<int16_t>{15, 16}));
        wake.Stop();
        wake.Start();
        assert(wake.processed_pcm_.empty());
        assert(wake.wake_word_pcm_.empty());
        std::cout << "PASS: preserve reference through AFE; reframe processed mono; reset partial audio\n";
    }
    {
        CustomWakeWord wake;
        configure(wake);
        int callbacks = 0;
        wake.OnWakeWordDetected([&](const std::string& name) { assert(name == "你好，小念"); callbacks++; });
        std::vector<int16_t> frame{1, 2, 3, 4};
        next_state = ESP_MN_STATE_DETECTED;
        results.command_id[0] = 0;
        wake.DetectProcessedAudio(frame.data(), frame.size());
        results.command_id[0] = 999;
        wake.DetectProcessedAudio(frame.data(), frame.size());
        assert(callbacks == 0 && wake.running_);
        null_results = true;
        wake.DetectProcessedAudio(frame.data(), frame.size());
        assert(callbacks == 0 && wake.running_);
        null_results = false;
        results.command_id[0] = 1;
        wake.DetectProcessedAudio(frame.data(), frame.size());
        assert(callbacks == 1 && !wake.running_);
        wake.DetectProcessedAudio(frame.data(), frame.size());
        assert(callbacks == 1);
        wake.Start();
        next_state = ESP_MN_STATE_TIMEOUT;
        int before = cleans;
        wake.DetectProcessedAudio(frame.data(), frame.size());
        assert(cleans == before + 1 && wake.running_);
        std::cout << "PASS: invalid/null results are safe; one callback per wake; timeout can recover\n";
    }
    {
        CustomWakeWord wake;
        configure(wake);
        std::promise<void> entered, release;
        auto released = release.get_future();
        std::vector<int16_t> old_audio{11, 12, 13, 14};
        afe_fetch_result_t result{0, old_audio.data(), int(old_audio.size() * sizeof(int16_t))};
        fetch = [&]() {
            entered.set_value();
            released.wait();
            wake.shutdown_ = true;
            return &result;
        };
        std::thread worker([&] { wake.AudioDetectionTask(); });
        entered.get_future().wait();
        wake.Stop();
        wake.Start();
        release.set_value();
        worker.join();
        assert(detected_frames.empty());
        std::cout << "PASS: frame fetched across Stop/Start cannot trigger a new wake\n";
    }
    {
        CustomWakeWord wake;
        configure(wake);
        wake.Stop();
        std::atomic<int> fetches{0};
        fetch = [&]() -> afe_fetch_result_t* {
            ++fetches;
            wake.shutdown_ = true;
            return nullptr;
        };
        std::thread worker([&] { wake.AudioDetectionTask(); });
        std::this_thread::sleep_for(std::chrono::milliseconds(55));
        assert(fetches == 0);
        wake.Start();
        worker.join();
        assert(fetches == 1);
        std::cout << "PASS: stopped wake detection does not fetch unfed AFE; Start resumes fetching\n";
    }
}
