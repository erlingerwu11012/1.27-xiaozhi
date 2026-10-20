#pragma once

#include <cstddef>
#include <cstdint>
#include <functional>


class BootAnimationPlayer {
public:
    using FrameSubmitter = std::function<bool(const uint16_t* pixels,
                                               int stride,
                                               int x1,
                                               int y1,
                                               int x2,
                                               int y2)>;

    // Plays a validated REBA v1 animation synchronously.  on_started is
    // invoked only after a complete black frame has reached panel GRAM.
    bool Play(const void* data,
              size_t size,
              int display_width,
              int display_height,
              FrameSubmitter submitter,
              std::function<void()> on_started);
};

