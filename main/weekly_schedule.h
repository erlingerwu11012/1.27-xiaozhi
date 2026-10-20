#pragma once
#include <cstdint>
#include <ctime>

// Product v1 uses Asia/Shanghai and Monday-Friday, not holiday calendars.
inline constexpr int64_t kScheduleUtcOffset = 8 * 3600;
inline int64_t ScheduleDay(time_t timestamp) {
    return (static_cast<int64_t>(timestamp) + kScheduleUtcOffset) / 86400;
}
inline int ScheduleWeekday(int64_t day) { return static_cast<int>((day + 4) % 7); }
inline time_t WeeklyDueOnDay(int64_t day, int hour, int minute) {
    return static_cast<time_t>(day * 86400 - kScheduleUtcOffset + hour * 3600 + minute * 60);
}
inline bool WeekdayAllowed(int mask, int64_t day) {
    return mask > 0 && mask <= 127 && (mask & (1 << ScheduleWeekday(day)));
}
inline time_t NextWeeklyDue(time_t after, int hour, int minute, int mask) {
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || mask <= 0 || mask > 127) return 0;
    const auto start = ScheduleDay(after);
    for (int offset = 0; offset <= 7; ++offset) {
        const auto day = start + offset;
        const auto due = WeeklyDueOnDay(day, hour, minute);
        if (due > after && WeekdayAllowed(mask, day)) return due;
    }
    return 0;
}
inline time_t HabitOccurrenceAt(time_t now, int hour, int minute, int advance, int mask) {
    if (hour < 0 || hour > 23 || minute < 0 || minute > 59 || advance < 0 || advance > 30) return 0;
    const int target_minute = hour * 60 + minute;
    const int trigger = target_minute - advance;
    const auto day = ScheduleDay(now) + (trigger < 0 ? 1 : 0);
    const auto due = WeeklyDueOnDay(day, hour, minute);
    return WeekdayAllowed(mask, day) && now >= due - advance * 60 && now < due - advance * 60 + 60 ? due : 0;
}
