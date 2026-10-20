#include "audio/tts_playback_state.h"
#include <atomic>
#include <cassert>
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <future>
#include <iostream>
#include <memory>
#include <mutex>
#include <thread>
#include <vector>
#define ESP_LOGI(...) ((void)0)
#define ESP_LOGW(...) ((void)0)
#define CONFIG_USE_SERVER_AEC 0
constexpr int AUDIO_POWER_CHECK_INTERVAL_MS=1000;
std::atomic<int64_t> now_us{1000000};
int64_t esp_timer_get_time() { return now_us; }
void esp_timer_stop(void*) {}
void esp_timer_start_periodic(void*,int) {}
struct AudioTask {
    std::vector<int16_t> pcm{1}; uint32_t timestamp=0;
    uint64_t playback_sequence=1; uint32_t playback_generation=0,decoder_epoch=1;
};
struct Codec {
    std::function<bool()> write;
    bool output_enabled() { return true; }
    void EnableOutput(bool) {}
    bool OutputData(std::vector<int16_t>&) { return write(); }
    int64_t OutputTailUs() { return 60000; }
};
struct Decoder { void ResetState() {} };
struct AudioService {
    Codec* codec_=nullptr; Decoder decoder;
    Decoder* opus_decoder_=&decoder;
    std::mutex audio_queue_mutex_, decoder_mutex_;
    std::condition_variable audio_queue_cv_;
    std::deque<std::unique_ptr<AudioTask>> audio_playback_queue_;
    std::deque<int> audio_decode_queue_,audio_testing_queue_,timestamp_queue_;
    bool service_stopped_=false,decode_active_=false;
    uint32_t decoder_epoch_=1,tts_output_generation_=0;
    int64_t tts_last_output_us_=0,output_tail_until_us_=0;
    std::atomic<bool> playback_active_{false};
    std::atomic<uint64_t> last_played_sequence_{0};
    struct { std::function<void()> on_playback_progress; } callbacks_;
    struct { int playback_count=0; } debug_statistics_;
    void* audio_power_timer_=nullptr;
    std::chrono::steady_clock::time_point last_output_time_;
    void AudioOutputTask(); bool IsPlaybackDrained();
    TtsPlaybackSnapshot GetTtsPlaybackSnapshot(); void ResetDecoder();
};
// @METHODS

int main() {
    for (const unsigned generation : {0U,7U}) {
        AudioService audio; Codec codec; audio.codec_=&codec;
        codec.write=[&] { audio.service_stopped_=true; return true; };
        auto task=std::make_unique<AudioTask>(); task->playback_generation=generation;
        audio.audio_playback_queue_.push_back(std::move(task));
        audio.AudioOutputTask();
        auto snap=audio.GetTtsPlaybackSnapshot();
        assert(snap.generation==generation && !snap.pending);
        assert(!audio.IsPlaybackDrained());
        now_us+=60000; assert(audio.IsPlaybackDrained());
        TtsPlaybackState mouth; mouth.Reset(7);
        assert(mouth.Update(snap,now_us-1,false)==(generation==7));
    }
    // A queue can be empty while OutputData is blocked. Reset cannot let its
    // old generation publish a successful TTS output after the reset.
    {
        AudioService audio; Codec codec; audio.codec_=&codec;
        std::promise<void> entered,release; auto released=release.get_future();
        codec.write=[&] { entered.set_value(); released.wait(); return true; };
        std::promise<void> finished;
        audio.callbacks_.on_playback_progress=[&] {
            std::lock_guard<std::mutex> lock(audio.audio_queue_mutex_);
            audio.service_stopped_=true; finished.set_value();
        };
        auto task=std::make_unique<AudioTask>(); task->playback_generation=9;
        audio.audio_playback_queue_.push_back(std::move(task));
        std::thread output([&]{audio.AudioOutputTask();});
        entered.get_future().wait();
        assert(audio.GetTtsPlaybackSnapshot().pending && !audio.IsPlaybackDrained());
        audio.ResetDecoder(); release.set_value(); finished.get_future().wait(); output.join();
        assert(audio.GetTtsPlaybackSnapshot().generation==0);
        assert(audio.last_played_sequence_==0 && !audio.IsPlaybackDrained());
        now_us+=60000; assert(audio.IsPlaybackDrained());
    }
    {
        AudioService audio; Codec codec; audio.codec_=&codec;
        codec.write=[&]{audio.service_stopped_=true;return false;};
        auto task=std::make_unique<AudioTask>(); task->playback_generation=10;
        audio.audio_playback_queue_.push_back(std::move(task)); audio.AudioOutputTask();
        assert(audio.GetTtsPlaybackSnapshot().generation==0 && audio.IsPlaybackDrained());
    }
    {
        AudioService audio;
        audio.decode_active_=true;
        assert(!audio.IsPlaybackDrained() && audio.GetTtsPlaybackSnapshot().pending);
        audio.ResetDecoder(); assert(!audio.IsPlaybackDrained());
        audio.decode_active_=false; assert(audio.IsPlaybackDrained());
    }
    std::cout<<"PASS: production PCM output, in-flight drain, DMA tail, reset race, local sound and write failure\n";
}
