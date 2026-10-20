#include "standby_clock.h"
#include "boards/common/brightness_levels.h"
#include <algorithm>
#include <atomic>
#include <cassert>
#include <cstdlib>
#include <cstring>
#include <cmath>
#include "gb2312font_20.h"
#include <fstream>
#include <iostream>
#include <mutex>
#include <string>
#include <vector>

static int64_t monotonic_us = 1000000;
int64_t esp_timer_get_time() { return monotonic_us; }
static bool fail_alloc = false;
static unsigned allocations = 0;
constexpr int MALLOC_CAP_SPIRAM = 1, MALLOC_CAP_8BIT = 2;
void* heap_caps_malloc(size_t bytes, int) { ++allocations; return fail_alloc ? nullptr : std::malloc(bytes); }
#define ESP_LOGE(...) ((void)0)
#define ESP_LOGI(...) ((void)0)

using TaskHandle_t = void*;
static unsigned notifications = 0;
void xTaskNotifyGive(TaskHandle_t) { ++notifications; }
struct FontData { const uint8_t* glyphData; uint8_t fontSize; uint16_t charCount; const char* charSet; };
static FontData DefaultFontData{GB2312_GlyphData_20,GB2312_FontSize_20,GB2312_CharCount_20,GB2312_CharSet_20};
// @GLYPH
static std::vector<std::string> events;
static int saved_brightness = 80;
static int saved_brightness_level = 0;
struct Settings {
    Settings(const char*,bool=false) {}
    int GetInt(const char* key,int fallback) {
        if (std::strcmp(key,"brightness")==0) return saved_brightness;
        if (std::strcmp(key,"brightness_lvl")==0) return saved_brightness_level;
        return fallback;
    }
    void SetInt(const char* key,int value) {
        if (std::strcmp(key,"brightness")==0) saved_brightness=value;
        if (std::strcmp(key,"brightness_lvl")==0) saved_brightness_level=value;
    }
};
using esp_timer_handle_t = void*;
int esp_timer_stop(esp_timer_handle_t) { return 0; }
int esp_timer_start_periodic(esp_timer_handle_t,int) { return 0; }
class Backlight {
public:
    void RestoreBrightness(bool);
    void ApplyTargetLocked();
    void SetBrightness(uint8_t,bool=false);
    void SetTemporaryBrightness(bool,uint8_t);
    void OnTransitionTimer();
    void SetBrightnessImpl(uint8_t b) { physical=b; }
    void CompleteFade() { for (int i=0;i<100;i++) OnTransitionTimer(); }
    std::mutex brightness_mutex_;
    uint8_t normal_brightness_=100,temporary_brightness_=10,brightness_=0,target_brightness_=0,physical=0;
    int8_t step_=1;
    bool temporary_enabled_=false;
    esp_timer_handle_t transition_timer_=nullptr;
};
// @BACKLIGHT
static Backlight backlight;
class Board {
public:
    static Board& GetInstance() { static Board b;return b; }
    Backlight* GetBacklight() { return &backlight; }
};
class CubicatHomePlayer {
public:
    bool active=true,foreground=false,fail_present=false;
    unsigned ticks=0,resumes=0;
    void SetActive(bool b) { active=b; }
    bool HasForegroundUi() const { return foreground; }
    void ResumeAfterStandby() { ++resumes;active=true; }
    void Tick() { assert(active);++ticks; }
    bool PresentFullFrame() { events.emplace_back("home");return !fail_present; }
};
class LcdDisplay {
public:
    std::recursive_mutex ui_mutex;
    int width_=320,height_=320;
    CubicatHomePlayer player;
    CubicatHomePlayer* cubicat_home_player_=&player;
    void* mcp_card_data_=nullptr;
    StandbyClockPolicy standby_policy_;
    StandbyClockText clock_text_;
    std::atomic<DisplayMode> requested_mode_{DisplayMode::Home},active_mode_{DisplayMode::Home};
    std::atomic<bool> clock_dirty_{false},clock_unavailable_{false},startup_revealed_{true},stop_render_task_{false};
    std::atomic<void*> render_task_{reinterpret_cast<void*>(1)};
    uint16_t* clock_pixels_=nullptr;
    unsigned clock_frames=0,drains=0;
    bool fail_transfer=false;
    ~LcdDisplay() { std::free(clock_pixels_); }
    void NotifyRenderTask();
    void RecordDisplayActivity();
    bool WakeFromStandbyClock();
    void TickStandbyClock(bool,bool=true);
    void RenderStandbyClock();
    bool RestoreHomeFromClock();
    void DrainNativeHomeFrames() { ++drains; }
    bool SubmitNativeHomeFrame(const uint16_t*,int,int,int,int,int,bool sync,bool) {
        assert(sync);++clock_frames;events.emplace_back("clock");return !fail_transfer;
    }
};
struct DisplayLockGuard {
    std::lock_guard<std::recursive_mutex> guard;
    explicit DisplayLockGuard(LcdDisplay* d):guard(d->ui_mutex) {}
};
static time_t wall_now=0;
time_t TestTime(time_t*) { return wall_now; }
#define time TestTime
// @DISPLAY
#undef time


// Inject scene/render targets into the actual engine update/reset methods.
static uint32_t engine_now=1000,timer0=0,timer1=0;
static uint16_t counter=0;
static float fps=0;
uint32_t millis() { return engine_now; }
struct EngineTarget {
    std::vector<float> deltas;
    unsigned renders=0;
    void update(float d) { deltas.push_back(d); }
    void tick(float d) { update(d); }
    int getDrawables() { return 0; }
    void renderObjects(int) { ++renders; }
};
class EmbedGameEngine {
public:
    EngineTarget *m_pTickMgr=nullptr,*m_pSceneMgr=nullptr,*m_pScheduleMgr=nullptr,*m_pRenderer=nullptr;
    uint16_t m_FPS=60;
    bool m_ResumeFramePending=false;
    void update();
    void resetTiming();
};
// @ENGINE
static void EngineResumeTests() {
    EngineTarget target;
    EmbedGameEngine engine;
    engine.m_pTickMgr=engine.m_pSceneMgr=engine.m_pScheduleMgr=engine.m_pRenderer=&target;
    engine.update();engine_now+=20;engine.update();
    assert(target.renders==1 && std::abs(target.deltas.back()-0.020f)<0.001f);
    engine_now+=3600000; // an hour paused cannot produce a catch-up delta
    engine.resetTiming();engine.update();
    assert(target.renders==2 && target.deltas.back()==0.0f);
    engine.update();assert(target.renders==2);
    engine_now+=20;engine.update();
    assert(target.renders==3 && std::abs(target.deltas.back()-0.020f)<0.001f);
}

static void PolicyTests() {
    StandbyClockPolicy p;
    assert(!p.Tick(0,true));
    assert(!p.Tick(59999,true));
    assert(p.Tick(60000,true));
    p.Activity(65000);
    assert(!p.Tick(124999,true));
    assert(p.Tick(125000,true));
    assert(!p.Tick(300000,false));
    assert(!p.Tick(330000,false));
    assert(!p.Tick(389999,true));
    assert(p.Tick(390000,true));
    assert(!p.Tick(1,true)); // monotonic clock reset must never underflow
}
static void TextAndPixels(const char* output) {
    std::tm t{};t.tm_year=126;t.tm_mon=9;t.tm_mday=6;t.tm_hour=11;t.tm_min=50;t.tm_sec=20;t.tm_isdst=-1;
    const time_t now=std::mktime(&t);
    const auto text=MakeStandbyClockText(now);
    assert(text.valid && std::string(text.time)=="11:50" && std::string(text.date)=="2026.10.06");
    assert(MakeStandbyClockText(now+39)==text);
    assert(!(MakeStandbyClockText(now+40)==text));
    assert(!MakeStandbyClockText(0).valid);
    t.tm_hour=23;t.tm_min=59;t.tm_sec=59;
    const auto next=MakeStandbyClockText(std::mktime(&t)+1);
    assert(std::string(next.time)=="00:00" && std::string(next.date)=="2026.10.07");
    std::vector<uint16_t> image(320*320+2,0x1234);
    DrawStandbyClock(image.data()+1,320,320,text);
    assert(image.front()==0x1234 && image.back()==0x1234);
    unsigned white=0;int longest=0;
    for(int y=0;y<320;y++) { int run=0;for(int x=0;x<320;x++) {
        auto c=image[1+y*320+x];assert(c==0 || c==0xFFFF);white+=(c!=0);
        run=c?run+1:0;longest=std::max(longest,run);
    }}
    assert(white>4000 && longest>=30); // solid strokes, not separated LED cells
    std::ofstream f(output,std::ios::binary);f<<"P6\n320 320\n255\n";
    for(size_t i=1;i<image.size()-1;i++) { const char c=image[i]?char(255):0;f.put(c);f.put(c);f.put(c); }
    for(char digit='0';digit<='9';digit++) {
        auto sample=text;for(int i: {0,1,3,4}) sample.time[i]=digit;
        DrawStandbyClock(image.data()+1,320,320,sample);
        assert(image.front()==0x1234 && image.back()==0x1234);
    }
}
static void DisplayTests() {
    assert(kStandbyClockBrightness == 85); // Clock duty stays 869/1023.
    backlight.RestoreBrightness(false);
    LcdDisplay d;monotonic_us=1000000;
    d.TickStandbyClock(true);
    monotonic_us+=59999000;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::Home);
    monotonic_us+=1000;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::StandbyClock);
    d.RenderStandbyClock();backlight.CompleteFade();
    assert(!d.player.active && d.clock_frames==1 && backlight.physical==85 && saved_brightness_level==3 && saved_brightness==80);
    // Actual production font must display all three uncalibrated glyphs.
    for (const char* ch: {"未","校","时"}) assert(getCharIndex(DefaultFontData.charSet,ch)>=0);
    unsigned label_pixels=0;
    for(int i=216*320;i<236*320;i++) label_pixels+=d.clock_pixels_[i]!=0;
    assert(label_pixels>100 && !d.clock_text_.valid);
    wall_now=1791258600; // calibration is a display event even within the same monotonic minute
    d.TickStandbyClock(true);assert(d.clock_dirty_ && d.clock_text_.valid);
    d.RenderStandbyClock();assert(d.clock_frames==2);
    wall_now+=60;d.TickStandbyClock(true);d.RenderStandbyClock();assert(d.clock_frames==3);
    const auto before=allocations;
    d.TickStandbyClock(true,false); // background camera cannot restore Home
    assert(d.requested_mode_==DisplayMode::StandbyClock);
    for(int i=0;i<100;i++) d.RenderStandbyClock();
    assert(d.player.ticks==0 && d.clock_frames==3 && allocations==before);
    backlight.SetBrightness(90,true);backlight.CompleteFade();
    assert(saved_brightness_level==4 && saved_brightness==80 && backlight.physical==85);
    assert(d.WakeFromStandbyClock());
    d.player.fail_present=true;
    assert(!d.RestoreHomeFromClock());backlight.CompleteFade();
    assert(d.active_mode_==DisplayMode::StandbyClock && backlight.physical==85);
    d.player.fail_present=false;
    assert(d.RestoreHomeFromClock());backlight.CompleteFade();
    assert(d.player.active && backlight.physical==96 && events.back()=="home");
    assert(!d.WakeFromStandbyClock());
    for(int i=0;i<100;i++) {
        monotonic_us+=60000000;d.TickStandbyClock(true);d.RenderStandbyClock();
        assert(!d.player.active);d.WakeFromStandbyClock();d.RestoreHomeFromClock();
    }
    assert(allocations==before); // no per-transition allocation
    monotonic_us+=60000000;d.TickStandbyClock(true,false);
    assert(d.requested_mode_==DisplayMode::Home); // camera work blocks initial entry
    monotonic_us+=60000000;d.TickStandbyClock(true);d.RenderStandbyClock();
    d.player.foreground=true;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::Home);d.RestoreHomeFromClock();
    d.player.foreground=true;monotonic_us+=60000000;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::Home);
    d.player.foreground=false;monotonic_us+=59999000;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::Home);
    d.mcp_card_data_=reinterpret_cast<void*>(1);monotonic_us+=60000000;d.TickStandbyClock(true);
    assert(d.requested_mode_==DisplayMode::Home);
    d.mcp_card_data_=nullptr;
    LcdDisplay failure;failure.TickStandbyClock(true);monotonic_us+=60000000;failure.TickStandbyClock(true);
    fail_alloc=true;failure.RenderStandbyClock();fail_alloc=false;
    assert(failure.clock_unavailable_ && failure.player.active && failure.requested_mode_==DisplayMode::Home);
    d.WakeFromStandbyClock();monotonic_us+=60000000;d.TickStandbyClock(true);
    d.fail_transfer=true;d.RenderStandbyClock();
    assert(d.requested_mode_==DisplayMode::Home && d.clock_unavailable_);
    d.RestoreHomeFromClock();assert(d.player.active);
}
int main(int argc,char**argv) {
    assert(argc==2);PolicyTests();TextAndPixels(argv[1]);EngineResumeTests();DisplayTests();
    std::cout<<"PASS: monotonic idle policy, date/minute boundaries, solid renderer, uncalibrated font/calibration, resume delta, foreground/background gates, 100 transitions, allocation/transfer fallback, temporary brightness\n";
}
