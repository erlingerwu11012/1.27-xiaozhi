#pragma once

#include <cstdint>
#include <functional>
#include <mutex>

#include "brightness_levels.h"

#include <driver/gpio.h>
#include <esp_timer.h>


class Backlight {
public:
    Backlight();
    ~Backlight();

    // Restores the saved brightness immediately by default.  A gradual restore
    // is used after the display has committed its first boot frame so the
    // panel's power-on contents never become visible.
    void RestoreBrightness(bool gradual = false);
    // Nonzero values resolve to user levels. Zero immediately blacks out the
    // hardware without changing the normal target or persisted user setting.
    void SetBrightness(uint8_t brightness, bool permanent = false);
    uint8_t brightness() const {
        std::lock_guard<std::mutex> lock(brightness_mutex_);
        return brightness_;
    }
    // User target, independent of an in-progress fade or standby override.
    uint8_t normal_brightness() const {
        std::lock_guard<std::mutex> lock(brightness_mutex_);
        return normal_brightness_;
    }
    // Temporary screen mode override; SetBrightness still updates the normal
    // user target, and disabling the override restores that latest target.
    void SetTemporaryBrightness(bool enabled, uint8_t brightness);


protected:
    void OnTransitionTimer();
    virtual void SetBrightnessImpl(uint8_t brightness) = 0;

    void ApplyTargetLocked();
    mutable std::mutex brightness_mutex_;
    uint8_t normal_brightness_ = 100;
    uint8_t temporary_brightness_ = 10;
    bool temporary_enabled_ = false;
    esp_timer_handle_t transition_timer_ = nullptr;
    uint8_t brightness_ = 0;
    uint8_t target_brightness_ = 0;
    int8_t step_ = 1;
};


class PwmBacklight : public Backlight {
public:
    PwmBacklight(gpio_num_t pin, bool output_invert = false, uint32_t freq_hz = 25000);
    ~PwmBacklight();

    void SetBrightnessImpl(uint8_t brightness) override;
};


class GpioBacklight : public Backlight {
public:
    GpioBacklight(gpio_num_t pin);
    ~GpioBacklight();

    void SetBrightnessImpl(uint8_t brightness) override;

private:
    gpio_num_t pin_;
};
