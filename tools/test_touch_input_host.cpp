#include <algorithm>
#include <cassert>
#include <cmath>
#include <cstring>
#include <functional>
#include <iostream>
#include <mutex>
#include <vector>
#define private public
#include "touch/touch_manager.h"
#undef private
#include "touch/gesture_engine.h"
#include "boards/common/backlight.h"
#include "boards/esp-box-3/config.h"
#include <esp_log.h>
using SemaphoreHandle_t = void*;
static bool snapshot_busy = false;
constexpr int pdTRUE = 1;
#define pdMS_TO_TICKS(x) (x)
int xSemaphoreTake(SemaphoreHandle_t, int) { return snapshot_busy ? 0 : pdTRUE; }
void xSemaphoreGive(SemaphoreHandle_t) {}
static constexpr float kGazeSmooth = 0.3f;
static const char* TAG = "test";
namespace touch {
TouchManager::TouchManager() = default;
TouchManager::~TouchManager() = default;
// @TOUCH
}
// Exercise the actual managed driver's transform with the board touch flags.
using esp_err_t = int;
constexpr int ESP_OK = 0, ESP_ERR_INVALID_ARG = -1;
#define ESP_RETURN_ON_FALSE(c,ret,...) do { if (!(c)) return ret; } while(0)
#define ESP_RETURN_ON_ERROR(expr,...) do { auto e=(expr); if(e!=ESP_OK) return e; } while(0)
struct esp_lcd_touch_point_data_t { uint16_t x,y,strength; uint8_t track_id; };
struct FakeTouch;
using esp_lcd_touch_handle_t = FakeTouch*;
struct FakeTouch {
    struct {
        uint16_t x_max=320,y_max=320;
        struct { bool mirror_x=TOUCH_MIRROR_X, mirror_y=TOUCH_MIRROR_Y, swap_xy=TOUCH_SWAP_XY; } flags;
        void (*process_coordinates)(FakeTouch*,uint16_t*,uint16_t*,uint16_t*,uint8_t*,uint8_t)=nullptr;
    } config;
    bool (*get_xy)(FakeTouch*,uint16_t*,uint16_t*,uint16_t*,uint8_t*,uint8_t)=nullptr;
    void* set_mirror_x=nullptr; void* set_mirror_y=nullptr; void* set_swap_xy=nullptr;
    int (*get_track_id)(FakeTouch*,uint8_t*,uint8_t)=nullptr;
    uint16_t raw_x=0,raw_y=0;
};
// @DRIVER
static bool timer_running = false;
int esp_timer_stop(esp_timer_handle_t) { timer_running = false; return 0; }
int esp_timer_start_periodic(esp_timer_handle_t, int) { timer_running = true; return 0; }
static int saved_brightness = 100;
static int saved_brightness_level = 0;
static bool fail_brightness_write = false;
struct Settings {
    Settings(const char*, bool = false) {}
    int GetInt(const char* key, int fallback) {
        if (std::strcmp(key, "brightness") == 0) return saved_brightness;
        if (std::strcmp(key, "brightness_lvl") == 0) return saved_brightness_level;
        return fallback;
    }
    void SetInt(const char* key, int value) {
        if (fail_brightness_write) return;
        if (std::strcmp(key, "brightness") == 0) saved_brightness = value;
        if (std::strcmp(key, "brightness_lvl") == 0) saved_brightness_level = value;
    }
};
Backlight::Backlight() = default;
Backlight::~Backlight() = default;
// @BACKLIGHT
struct TestLight : Backlight {
    std::vector<int> writes;
    void SetBrightnessImpl(uint8_t value) override { writes.push_back(value); }
    void Tick() { OnTransitionTimer(); }
    void Settle() { for (int i = 0; i < 100; ++i) Tick(); }
};
struct Rig {
    touch::TouchManager tm;
    touch::GestureEngine engine;
    std::vector<GestureEvent> events;
    int64_t now = 1000;
    Rig() {
        tm.config_.display_width = tm.config_.display_height = 320;
        engine.SetTouchManager(&tm);
        engine.SetCallback([this](const GestureEvent& e) { events.push_back(e); });
    }
    void Sample(int x, int y, bool down, bool valid = true, int elapsed = 10) {
        now += elapsed;
        tm.UpdateState(x, y, 7, down, valid);
        engine.Update(now);
    }
    void Down(int x, int y) { for (int i = 0; i < 3; ++i) Sample(x, y, true); }
    void Up() { Sample(0, 0, false); Sample(0, 0, false); }
};
static bool Near(float a, float b) { return std::abs(a-b) < 0.00001f; }
int main() {
    // Reproduce the false (0,0) movement at the first release-debounce sample.
    for (int x : {40, 280}) {
        Rig r; r.Down(x, 80);
        r.Sample(x, 140, true); r.Sample(x, 200, true);
        r.Sample(0, 0, false);
        TouchPoint point{}; assert(r.tm.GetState(&point));
        assert(point.touched && Near(point.x, x/320.f) && Near(point.y, 200/320.f));
        assert(r.events.empty());
        r.Sample(0, 0, false);
        assert(r.events.size() == 1 && r.events[0].type == GESTURE_SWIPE_DOWN);
        assert(Near(r.events[0].start_x, x/320.f));
    }
    { Rig r; r.Down(200, 200); r.Sample(0,0,false); r.Sample(200,200,true);
      r.Sample(200,200,true); r.Sample(200,200,true); r.Up();
      assert(r.events.size()==1 && r.events[0].type==GESTURE_TAP); }
    { Rig r; r.Down(220,220); for(int i=0;i<1000;++i) r.Sample(220,220,true);
      assert(r.tm.press_streak_ == 3); r.Up(); assert(!r.tm.stable_pressed_);
      assert(r.events.size()==1 && r.events[0].type==GESTURE_LONG_PRESS); }
    { Rig r; r.Down(200,100); for(int i=0;i<9;++i) r.Sample(0,0,false,false);
      assert(r.tm.stable_pressed_ && r.events.empty()); r.Sample(0,0,false,false);
      assert(!r.tm.stable_pressed_); assert(Near(r.tm.state_.x,200/320.f)); }
    { Rig r; r.Down(200,200); snapshot_busy=true;
      r.engine.Update(r.now+100); snapshot_busy=false; assert(r.events.empty());
      r.Sample(200,200,true); r.Sample(200,200,true); r.Up();
      assert(r.events.size()==1 && r.events[0].type==GESTURE_TAP); }
    // Final direction wins over an earlier sideways excursion.
    { Rig r; r.Down(80,80); r.Sample(220,80,true); r.Sample(100,160,true); r.Sample(100,200,true); r.Up();
      assert(r.events.size()==1 && r.events[0].type==GESTURE_SWIPE_DOWN); }
    { Rig r; r.Down(80,80); r.Sample(220,220,true); r.Up(); assert(r.events.empty()); }
    { Rig r; r.Down(80,80); r.Sample(220,80,true); r.Sample(82,80,true); r.Up(); assert(r.events.empty()); }
    { Rig r; r.Down(80,80); r.Sample(80,180,true,true,800);
      assert(r.events.empty()); r.Up(); assert(r.events.size()==1 && r.events[0].type==GESTURE_SWIPE_DOWN); }
    { Rig r; r.Down(120,120); for(int i=0;i<5;++i) r.Sample(120,120,true); r.Up();
      r.Down(122,122); for(int i=0;i<5;++i) r.Sample(122,122,true); r.Up();
      assert(r.events.size()==2 && r.events[0].type==GESTURE_TAP && r.events[1].type==GESTURE_DOUBLE_TAP); }
    { Rig r; r.Down(120,120); r.Up(); assert(r.events.empty()); }
    for (auto type : {GESTURE_SWIPE_LEFT, GESTURE_SWIPE_RIGHT, GESTURE_SWIPE_UP, GESTURE_SWIPE_DOWN}) {
        Rig r; r.Down(160,160);
        r.Sample(type==GESTURE_SWIPE_LEFT ? 80 : type==GESTURE_SWIPE_RIGHT ? 240 : 160,
                 type==GESTURE_SWIPE_UP ? 80 : type==GESTURE_SWIPE_DOWN ? 240 : 160, true);
        r.Up(); assert(r.events.size()==1 && r.events[0].type==type);
    }
    FakeTouch driver;
    driver.get_xy=[](FakeTouch* tp,uint16_t* x,uint16_t* y,uint16_t* strength,uint8_t* count,uint8_t) {
        *x=tp->raw_x; *y=tp->raw_y; *strength=0; *count=1; return true;
    };
    for (int raw_x : {40,280}) {
        driver.raw_x=raw_x; driver.raw_y=80;
        esp_lcd_touch_point_data_t point{}; uint8_t count=0;
        assert(esp_lcd_touch_get_data(&driver,&point,&count,1)==ESP_OK && count==1);
        assert(point.x==320-raw_x && point.y==240);
    }
    // Every old percent must migrate independently of the new fade markers.
    struct LegacyCase { int percent, level; };
    const LegacyCase legacy_cases[] = {{50,1}, {60,1}, {64,1}, {65,2},
                                       {70,2}, {74,2}, {75,3}, {80,3}, {82,3}, {84,3},
                                       {85,4}, {87,4}, {90,4}, {91,4}, {94,4}, {95,5},
                                       {96,5}, {100,5}};
    for (const auto sample : legacy_cases) {
        saved_brightness = sample.percent;
        saved_brightness_level = 0;
        TestLight migrated; migrated.RestoreBrightness(false);
        assert(saved_brightness == sample.percent && saved_brightness_level == sample.level);
        assert(migrated.brightness() == BrightnessPercentForLevel(sample.level));
        assert(BrightnessLevelFromToolValue(sample.percent) == sample.level);
        // A subsequent boot uses the new level, even if the legacy key differs.
        saved_brightness = 50;
        TestLight rebooted; rebooted.RestoreBrightness(false);
        assert(rebooted.brightness() == BrightnessPercentForLevel(sample.level));
    }
    // Failed migration leaves the old percent intact for a safe next-boot retry.
    saved_brightness = 82; saved_brightness_level = 0; fail_brightness_write = true;
    { TestLight failed; failed.RestoreBrightness(false);
      assert(failed.brightness() == 91 && saved_brightness == 82 && saved_brightness_level == 0); }
    fail_brightness_write = false;
    { TestLight retried; retried.RestoreBrightness(false);
      assert(retried.brightness() == 91 && saved_brightness_level == 3); }
    for (int value = -1; value <= 101; ++value) {
        const int level = BrightnessLevelFromToolValue(value);
        if (value >= 1 && value <= 5) assert(level == value);
        else if (value >= 50 && value <= 100) assert(level >= 1 && level <= 5);
        else assert(level == 0);
    }
    const uint16_t expected_duty[] = {839, 885, 931, 977, 1023};
    for (int level = 1; level <= 5; ++level)
        assert(BrightnessDutyCount(BrightnessPercentForLevel(level)) == expected_duty[level-1]);
    assert(BrightnessDutyCount(85) == 869 && BrightnessDutyCount(0) == 0);

    saved_brightness = 100; saved_brightness_level = 0;
    TestLight light;
    light.SetBrightness(0); light.Settle();
    assert(light.brightness() == 0 && !timer_running && saved_brightness_level == 0);
    light.RestoreBrightness(true);
    assert(light.brightness() == 0 && timer_running);
    light.Settle(); assert(light.brightness() == 100);
    light.SetBrightness(91,true); assert(light.brightness()==100 && light.normal_brightness()==91);
    // Blackout must cancel an active fade without overwriting the user setting.
    light.SetBrightness(0,true); light.Settle();
    assert(light.brightness()==0 && light.normal_brightness()==91 && !timer_running);
    assert(saved_brightness_level==3 && saved_brightness==100);
    light.RestoreBrightness(true);
    light.Settle();
    assert(light.brightness()==91 && saved_brightness_level==3 && !timer_running);
    light.SetTemporaryBrightness(true,85); light.Settle();
    assert(light.brightness()==85 && light.normal_brightness()==91);
    light.SetBrightness(96,true); light.SetTemporaryBrightness(false,85); light.Settle();
    assert(light.brightness()==96 && saved_brightness_level==4 && saved_brightness==100 && !timer_running);
    auto count=light.writes.size(); for(int i=0;i<100;++i) light.Tick();
    assert(light.writes.size()==count); // Stable brightness never keeps rewriting PWM.
    std::cout << "PASS: production touch release/bounce/read-failure/lock contention, gesture directions/diagonals/double tap/long press, brightness migration/reboot/retry/tool validation/PWM/boot blackout/fade/standby targets\n";
}
