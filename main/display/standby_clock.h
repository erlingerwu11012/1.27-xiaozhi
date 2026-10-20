#pragma once

#include <cstdint>
#include <ctime>

enum class DisplayMode { Home, StandbyClock };

// Test firmware: change only this constant to 30 * 60 * 1000 after acceptance.
constexpr int64_t kStandbyClockTimeoutMs = 60 * 1000;
// Clock backlight stays at the accepted 85 setting. With the linear 10-bit map
// that is duty 869/1023 (84.95%), between user level 1 (82%) and level 2 (86.5%).
constexpr uint8_t kStandbyClockBrightness = 85;

// Callers serialize this policy; time is monotonic, never wall-clock time.
class StandbyClockPolicy {
public:
    void Activity(int64_t now_ms) { idle_since_ms_ = now_ms; armed_ = true; }
    bool Tick(int64_t now_ms, bool eligible) {
        if (!eligible || !armed_ || now_ms < idle_since_ms_) {
            Activity(now_ms);
            return false;
        }
        return now_ms - idle_since_ms_ >= kStandbyClockTimeoutMs;
    }
private:
    int64_t idle_since_ms_ = 0;
    bool armed_ = false;
};

struct StandbyClockText {
    char time[6] = "--:--";
    char date[11] = {};
    bool valid = false;
    bool operator==(const StandbyClockText& other) const;
};

StandbyClockText MakeStandbyClockText(time_t now);
// No heap allocation, scene update, or animation is performed here.
void DrawStandbyClock(uint16_t* pixels, int width, int height,
                      const StandbyClockText& text);
