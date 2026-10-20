#ifndef AUDIO_PROCESSOR_H
#define AUDIO_PROCESSOR_H

#include <string>
#include <vector>
#include <functional>
#include <new>              // 【必须】为了 std::bad_alloc
#include "esp_heap_caps.h"  // 【必须】为了 heap_caps_malloc 和 MALLOC_CAP_SPIRAM

#include <model_path.h>
#include "audio_codec.h"

// =================================================================================
// 【核心修改】将 SpiramAllocator 定义直接放在这里
// 这样所有包含此文件的派生类（如 AfeAudioProcessor）都能自动识别它，无需新建文件
// =================================================================================
template <typename T>
class SpiramAllocator {
public:
    using value_type = T;

    SpiramAllocator() = default;
    template <typename U> SpiramAllocator(const SpiramAllocator<U>&) {}

    T* allocate(std::size_t n) {
        if (n > std::size_t(-1) / sizeof(T)) throw std::bad_alloc();
        
        // 关键：指定申请 MALLOC_CAP_SPIRAM (外部 PSRAM)
        void* p = heap_caps_malloc(n * sizeof(T), MALLOC_CAP_SPIRAM);
        
        if (!p) throw std::bad_alloc();
        return static_cast<T*>(p);
    }

    void deallocate(T* p, std::size_t) noexcept {
        heap_caps_free(p);
    }
};

template <typename T, typename U>
bool operator==(const SpiramAllocator<T>&, const SpiramAllocator<U>&) { return true; }

template <typename T, typename U>
bool operator!=(const SpiramAllocator<T>&, const SpiramAllocator<U>&) { return false; }
// =================================================================================


class AudioProcessor {
public:
    virtual ~AudioProcessor() = default;
    
    // 初始化接口
    virtual void Initialize(AudioCodec* codec, int frame_duration_ms, srmodel_list_t* models_list) = 0;
    
    // 输入音频数据 (Feed 通常来自 DMA/SRAM，所以保持标准 vector)
    virtual void Feed(std::vector<int16_t>&& data) = 0;
    
    virtual void Start() = 0;
    virtual void Stop() = 0;
    virtual bool IsRunning() = 0;

    // 【修改点】输出回调现在使用带有 SpiramAllocator 的 vector
    virtual void OnOutput(std::function<void(std::vector<int16_t, SpiramAllocator<int16_t>>&& data)> callback) = 0;

    virtual void OnVadStateChange(std::function<void(bool speaking)> callback) = 0;
    virtual size_t GetFeedSize() = 0;
    virtual void EnableDeviceAec(bool enable) = 0;
};

#endif // AUDIO_PROCESSOR_H