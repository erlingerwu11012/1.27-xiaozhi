#pragma once

#include <cstdint>

// Local output facts, never network receipt or subtitle state.
struct TtsPlaybackSnapshot {
    uint32_t generation = 0;
    int64_t last_output_us = 0;
    int64_t tail_until_us = 0;
    bool pending = false;
};

class TtsPlaybackState {
public:
    static constexpr int64_t kGapPauseUs = 200000;
    void Reset(uint32_t generation = 0) {
        generation_ = generation;
        observed_output_us_ = 0;
        active_ = false;
    }
    bool active() const { return active_; }
    bool Update(const TtsPlaybackSnapshot& output, int64_t now_us, bool stopped) {
        if (generation_ == 0) return active_ = false;
        if (output.generation != generation_) {
            // Decoder reset clears output ownership. A stale nonzero turn
            // cannot start this turn, while explicit reset also closes it.
            if (output.generation == 0) active_ = false;
            return active_;
        }
        // Pending packets alone must not open the mouth, including after a gap.
        if (output.last_output_us > observed_output_us_) {
            observed_output_us_ = output.last_output_us;
            active_ = true;
        }
        if (active_ && !output.pending && now_us >= output.tail_until_us &&
            (stopped || now_us - output.tail_until_us >= kGapPauseUs)) {
            active_ = false;
        }
        return active_;
    }
private:
    uint32_t generation_ = 0;
    int64_t observed_output_us_ = 0;
    bool active_ = false;
};
