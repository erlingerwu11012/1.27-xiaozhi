#pragma once

#include <functional>
#include <atomic>
#include <cstdint>
#include <freertos/FreeRTOS.h>
#include <freertos/task.h>
#include <esp_timer.h>

/**
 * PresenceSensor — HLK-LD2410D-B 检测
 *
 * OUT 引脚（GPIO12）：上升沿 ISR → 触发回调
 * UART1（GPIO38=RX, GPIO39=TX）：读取传感器距离数据，用于驻留时间过滤
 *
 * OUT 高电平 = 有人，低电平 = 无人。
 * 稳定有人：OUT 连续高电平超过 kDwellMs 后 confirmed_present=true，并递增 generation。
 * 稳定离场：仅在曾经 confirmed_present=true 后，OUT 连续低电平超过 kAbsenceMs 才离场。
 * RequestStableRecheck：复用同一 dwell 检查（Idle / UVC ready 等场景），禁止直接读 GPIO 触发。
 */
class PresenceSensor {
public:
    // generation is the presence_generation after false→true (or current if already confirmed).
    using PresenceCallback = std::function<void(uint32_t generation)>;
    using AbsenceCallback = std::function<void(uint32_t generation)>;

    explicit PresenceSensor(PresenceCallback on_stable_presence,
                            AbsenceCallback on_stable_absence = nullptr);
    ~PresenceSensor();

    void ResetCooldown();
    void SetCooldown();
    bool IsCooldownActive() const { return cooldown_active_.load(); }

    bool IsConfirmedPresent() const { return confirmed_present_.load(); }
    uint32_t PresenceGeneration() const { return presence_generation_.load(); }

    // Re-run the 1s dwell check (must not skip dwell / call presence handlers directly).
    void RequestStableRecheck();

private:
    PresenceCallback on_stable_presence_;
    AbsenceCallback on_stable_absence_;
    std::atomic<bool>     cooldown_active_{false};
    std::atomic<bool>     confirmed_present_{false};
    std::atomic<uint32_t> presence_generation_{0};
    std::atomic<bool>     recheck_requested_{false};
    esp_timer_handle_t    cooldown_timer_  = nullptr;
    TaskHandle_t          notify_task_     = nullptr;
    TaskHandle_t          absence_task_    = nullptr;

    void InitUart();
    void ConfigureSensor();
    void StartNotifyTask();
    void StartAbsenceTask();
    void ConfirmPresentAndFire();
    void ConfirmAbsentAndFire();
    static void IRAM_ATTR OutPinIsrHandler(void* arg);
    static void NotifyTaskEntry(void* arg);
    static void AbsenceTaskEntry(void* arg);
};
