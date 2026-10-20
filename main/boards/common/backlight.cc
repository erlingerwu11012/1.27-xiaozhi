#include "backlight.h"
#include "brightness_levels.h"
#include "settings.h"
#include <algorithm>

#include <esp_log.h>
#include <driver/ledc.h>

#define TAG "Backlight"


Backlight::Backlight() {
    // 创建背光渐变定时器
    const esp_timer_create_args_t timer_args = {
        .callback = [](void* arg) {
            auto self = static_cast<Backlight*>(arg);
            self->OnTransitionTimer();
        },
        .arg = this,
        .dispatch_method = ESP_TIMER_TASK,
        .name = "backlight_timer",
        .skip_unhandled_events = true,
    };
    ESP_ERROR_CHECK(esp_timer_create(&timer_args, &transition_timer_));
}

Backlight::~Backlight() {
    if (transition_timer_ != nullptr) {
        esp_timer_stop(transition_timer_);
        esp_timer_delete(transition_timer_);
    }
}

void Backlight::RestoreBrightness(bool gradual) {
    std::lock_guard<std::mutex> lock(brightness_mutex_);
    Settings settings("display");
    int level = settings.GetInt("brightness_lvl", 0);
    if (level < 1 || level > kBrightnessLevelCount) {
        int legacy = settings.GetInt("brightness", 100);
        if (legacy <= 0 || legacy > 100) legacy = 100;
        level = BrightnessLevelFromLegacyPercent(legacy);
        // A separate key identifies the new format without overwriting the
        // legacy value. Failed writes can safely retry migration next boot.
        Settings update("display", true);
        update.SetInt("brightness_lvl", level);
    }
    normal_brightness_ = BrightnessPercentForLevel(level);
    if (gradual) {
        ApplyTargetLocked();
    } else {
        esp_timer_stop(transition_timer_);
        target_brightness_ = temporary_enabled_ ? temporary_brightness_ : normal_brightness_;
        brightness_ = target_brightness_;
        SetBrightnessImpl(brightness_);
    }
    ESP_LOGI(TAG, "Restore brightness level=%d", level);
}

void Backlight::ApplyTargetLocked() {
    target_brightness_ = temporary_enabled_ ? temporary_brightness_ : normal_brightness_;
    // Stop first: reversing an in-progress fade must not start the same timer twice.
    esp_timer_stop(transition_timer_);
    if (brightness_ == target_brightness_) return;
    step_ = target_brightness_ > brightness_ ? 1 : -1;
    esp_timer_start_periodic(transition_timer_, 5 * 1000);
}

void Backlight::SetBrightness(uint8_t brightness, bool permanent) {
    std::lock_guard<std::mutex> lock(brightness_mutex_);
    if (brightness == 0) {
        // Hardware blackout, especially before the first boot frame. Do not
        // quantize zero or replace the saved/normal user target.
        esp_timer_stop(transition_timer_);
        target_brightness_ = 0;
        brightness_ = 0;
        SetBrightnessImpl(0);
        return;
    }
    brightness = BrightnessPercentForLevel(BrightnessLevelFromStored(brightness));
    if (permanent) {
        Settings settings("display", true);
        settings.SetInt("brightness_lvl", BrightnessLevelFromStored(brightness));
    }
    normal_brightness_ = brightness;
    ApplyTargetLocked();
    ESP_LOGI(TAG, "Set brightness to %d", brightness);
}

void Backlight::SetTemporaryBrightness(bool enabled, uint8_t brightness) {
    std::lock_guard<std::mutex> lock(brightness_mutex_);
    temporary_enabled_ = enabled;
    temporary_brightness_ = std::min<uint8_t>(brightness, 100);
    ApplyTargetLocked();
}

void Backlight::OnTransitionTimer() {
    std::lock_guard<std::mutex> lock(brightness_mutex_);
    if (brightness_ != target_brightness_) {
        brightness_ += step_;
        SetBrightnessImpl(brightness_);
    }
    if (brightness_ == target_brightness_) esp_timer_stop(transition_timer_);
}

PwmBacklight::PwmBacklight(gpio_num_t pin, bool output_invert, uint32_t freq_hz) : Backlight() {
    const ledc_timer_config_t backlight_timer = {
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .duty_resolution = LEDC_TIMER_10_BIT,
        .timer_num = LEDC_TIMER_0,
        .freq_hz = freq_hz, //背光pwm频率需要高一点，防止电感啸叫
        .clk_cfg = LEDC_AUTO_CLK,
        .deconfigure = false
    };
    ESP_ERROR_CHECK(ledc_timer_config(&backlight_timer));

    // Setup LEDC peripheral for PWM backlight control
    const ledc_channel_config_t backlight_channel = {
        .gpio_num = pin,
        .speed_mode = LEDC_LOW_SPEED_MODE,
        .channel = LEDC_CHANNEL_0,
        .intr_type = LEDC_INTR_DISABLE,
        .timer_sel = LEDC_TIMER_0,
        .duty = 0,
        .hpoint = 0,
        .flags = {
            .output_invert = output_invert,
        }
    };
    ESP_ERROR_CHECK(ledc_channel_config(&backlight_channel));
}

PwmBacklight::~PwmBacklight() {
    ledc_stop(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, 0);
}

void PwmBacklight::SetBrightnessImpl(uint8_t brightness) {
    // LEDC resolution set to 10bits, thus: 100% = 1023
    uint32_t duty_cycle = BrightnessDutyCount(brightness);
    ledc_set_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0, duty_cycle);
    ledc_update_duty(LEDC_LOW_SPEED_MODE, LEDC_CHANNEL_0);
}

GpioBacklight::GpioBacklight(gpio_num_t pin) : Backlight(), pin_(pin) {
    gpio_reset_pin(pin_);
    gpio_set_direction(pin_, GPIO_MODE_OUTPUT);
    gpio_set_level(pin_, 0);
}

GpioBacklight::~GpioBacklight() {
    gpio_set_level(pin_, 0);
}

void GpioBacklight::SetBrightnessImpl(uint8_t brightness) {
    gpio_set_level(pin_, brightness > 0 ? 1 : 0);
}

