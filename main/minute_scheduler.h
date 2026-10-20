#pragma once
#include <ctime>
struct MinuteWindow { time_t first=0, last=-1; };
class MinuteScheduler {
public:
    MinuteWindow Advance(time_t now) {
        if (now <= 1000000000L) return {};
        const time_t minute=now/60;
        if (minute==last_) return {};
        const time_t first=last_>0 && minute>last_ && minute-last_<=3 ? last_+1 : minute;
        last_=minute; return {first,minute};
    }
private: time_t last_=0;
};
