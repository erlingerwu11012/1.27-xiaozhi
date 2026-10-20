#pragma once

#include <cstdint>

// Five user brightness levels. Level 1 is an 82% PWM duty, level 5 is 100%.
// Internal fade values 87 and 96 represent 86.5% and 95.5% PWM duty.
// NVS stores the level (1-5) separately from the legacy brightness percent.
// Standby clock uses 85 and stays on the linear 10-bit formula (duty 869).
constexpr int kBrightnessLevelCount = 5;
constexpr uint8_t kBrightnessLevelPercent[kBrightnessLevelCount] = {82, 87, 91, 96, 100};
constexpr uint16_t kBrightnessLevelDuty[kBrightnessLevelCount] = {839, 885, 931, 977, 1023};

inline int BrightnessLevelFromLegacyPercent(int saved) {
    if (saved <= 64) return 1;
    if (saved <= 74) return 2;
    if (saved <= 84) return 3;
    if (saved <= 94) return 4;
    return 5;
}

// Resolve an internal fade value. Never use this to migrate legacy NVS/tool
// percents: values such as 82 and 87 have different meanings in that format.
inline int BrightnessLevelFromStored(int saved) {
    switch (saved) {
        case 82: return 1;
        case 87: return 2;
        case 91: return 3;
        case 96: return 4;
        case 100: return 5;
        default: break;
    }
    return BrightnessLevelFromLegacyPercent(saved);
}

inline uint8_t BrightnessPercentForLevel(int level) {
    if (level < 1) level = 1;
    if (level > kBrightnessLevelCount) level = kBrightnessLevelCount;
    return kBrightnessLevelPercent[level - 1];
}

inline int BrightnessLevelFromToolValue(int value) {
    if (value >= 1 && value <= kBrightnessLevelCount) return value;
    if (value >= 50 && value <= 100) return BrightnessLevelFromLegacyPercent(value);
    return 0;  // Invalid: neither a level nor a legacy percent.
}

inline uint16_t BrightnessDutyCount(uint8_t brightness) {
    switch (brightness) {
        case 82: return kBrightnessLevelDuty[0];
        case 87: return kBrightnessLevelDuty[1];
        case 91: return kBrightnessLevelDuty[2];
        case 96: return kBrightnessLevelDuty[3];
        case 100: return kBrightnessLevelDuty[4];
        default: return static_cast<uint16_t>((1023u * brightness) / 100u);
    }
}
