#pragma once

#include <cstdint>
#include <cstddef>
#include <limits>
#include <memory>
#include <new>
#include <string>
#include <type_traits>
#include <vector>

#ifdef ESP_PLATFORM
#include <esp_heap_caps.h>
#include <esp_log.h>
#endif

// Image bytes must never consume the internal heap as a fallback. Metadata,
// network control structures and hardware DMA buffers keep their own policy.
template <class T>
class CameraPsramAllocator {
public:
    using value_type = T;
    using is_always_equal = std::true_type;
    using propagate_on_container_move_assignment = std::true_type;
    CameraPsramAllocator() noexcept = default;
    template <class U>
    CameraPsramAllocator(const CameraPsramAllocator<U>&) noexcept {}

    T* allocate(size_t count) {
        if (count > std::numeric_limits<size_t>::max() / sizeof(T)) {
            throw std::bad_alloc();
        }
#ifdef ESP_PLATFORM
        const size_t bytes = count * sizeof(T);
        void* ptr = heap_caps_aligned_alloc(
            alignof(T) < alignof(void*) ? alignof(void*) : alignof(T),
            bytes, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
        if (!ptr) {
            ESP_LOGE("CameraMemory", "[PHOTO_PSRAM] allocation failed bytes=%u; no internal fallback",
                     static_cast<unsigned>(bytes));
            throw std::bad_alloc();
        }
        return static_cast<T*>(ptr);
#else
        return std::allocator<T>{}.allocate(count);
#endif
    }
    void deallocate(T* ptr, size_t count) noexcept {
#ifdef ESP_PLATFORM
        (void)count;
        heap_caps_free(ptr);
#else
        std::allocator<T>{}.deallocate(ptr, count);
#endif
    }
};

template <class T, class U>
bool operator==(const CameraPsramAllocator<T>&, const CameraPsramAllocator<U>&) noexcept {
    return true;
}
template <class T, class U>
bool operator!=(const CameraPsramAllocator<T>&, const CameraPsramAllocator<U>&) noexcept {
    return false;
}

// Host-only consumers retain their existing STL types. Firmware uses the
// explicit allocator even when malloc's default PSRAM preference changes.
#ifdef ESP_PLATFORM
using CameraJpegBuffer = std::vector<uint8_t, CameraPsramAllocator<uint8_t>>;
using CameraJpegCandidates = std::vector<CameraJpegBuffer, CameraPsramAllocator<CameraJpegBuffer>>;
using CameraMultipartBody = std::basic_string<char, std::char_traits<char>, CameraPsramAllocator<char>>;
#else
using CameraJpegBuffer = std::vector<uint8_t>;
using CameraJpegCandidates = std::vector<CameraJpegBuffer>;
using CameraMultipartBody = std::string;
#endif
