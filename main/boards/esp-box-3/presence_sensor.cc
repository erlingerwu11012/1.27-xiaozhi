#include "presence_sensor.h"
#include "config.h"
#include "task_diagnostics.h"
#include "test_observability.h"

#include <driver/gpio.h>
#include <driver/uart.h>
#include <esp_log.h>

#define TAG "PresenceSensor"

static const uint64_t kCooldownUs = 30ULL * 1000 * 1000;

// 驻留时间过滤：OUT 持续高电平超过此时间才触发回调，防止路过误触发
static const int kDwellMs    = 1000;   // 1 秒
static const int kPollMs     = 200;    // 每 200ms 轮询一次
static const int kDwellTicks = kDwellMs / kPollMs;  // = 5 次

// 离场检测：OUT 持续低电平超过此时间才触发 on_stable_absence_ 回调
static const int kAbsenceMs    = 5000;  // 5 秒
static const int kAbsencePollMs = 500;
static const int kAbsenceTicks = kAbsenceMs / kAbsencePollMs;  // = 10 次

PresenceSensor::PresenceSensor(PresenceCallback on_stable_presence,
                               AbsenceCallback on_stable_absence)
    : on_stable_presence_(std::move(on_stable_presence)),
      on_stable_absence_(std::move(on_stable_absence)) {

    esp_timer_create_args_t targs = {};
    targs.callback = [](void* arg) {
        static_cast<PresenceSensor*>(arg)->cooldown_active_ = false;
        ESP_LOGI(TAG, "Cooldown cleared");
    };
    targs.arg             = this;
    targs.dispatch_method = ESP_TIMER_TASK;
    targs.name            = "presence_cd";
    if (esp_timer_create(&targs, &cooldown_timer_) != ESP_OK) {
        ESP_LOGE(TAG, "esp_timer_create failed");
        return;
    }

    gpio_config_t io = {};
    io.pin_bit_mask = (1ULL << PRESENCE_SENSOR_OUT_PIN);
    io.mode         = GPIO_MODE_INPUT;
    io.pull_up_en   = GPIO_PULLUP_DISABLE;
    io.pull_down_en = GPIO_PULLDOWN_ENABLE;
    io.intr_type    = GPIO_INTR_POSEDGE;
    if (gpio_config(&io) != ESP_OK) {
        ESP_LOGE(TAG, "gpio_config failed for IO%d", PRESENCE_SENSOR_OUT_PIN);
        return;
    }

    InitUart();
    ConfigureSensor();
    StartNotifyTask();

    if (on_stable_absence_) {
        StartAbsenceTask();
    }

    esp_err_t isr_ret = gpio_install_isr_service(0);
    if (isr_ret != ESP_OK && isr_ret != ESP_ERR_INVALID_STATE) {
        ESP_LOGE(TAG, "gpio_install_isr_service failed: %s", esp_err_to_name(isr_ret));
        return;
    }
    if (gpio_isr_handler_add((gpio_num_t)PRESENCE_SENSOR_OUT_PIN,
                              OutPinIsrHandler, this) != ESP_OK) {
        ESP_LOGE(TAG, "gpio_isr_handler_add failed");
        return;
    }

    ESP_LOGI(TAG, "PresenceSensor initialized: OUT=IO%d, UART1 RX=IO%d TX=IO%d",
             PRESENCE_SENSOR_OUT_PIN,
             PRESENCE_SENSOR_UART_RX_PIN,
             PRESENCE_SENSOR_UART_TX_PIN);
}

PresenceSensor::~PresenceSensor() {
    gpio_isr_handler_remove((gpio_num_t)PRESENCE_SENSOR_OUT_PIN);
    if (notify_task_) {
        vTaskDelete(notify_task_);
        notify_task_ = nullptr;
    }
    if (absence_task_) {
        vTaskDelete(absence_task_);
        absence_task_ = nullptr;
    }
    if (cooldown_timer_) {
        esp_timer_stop(cooldown_timer_);
        esp_timer_delete(cooldown_timer_);
    }
    uart_driver_delete((uart_port_t)PRESENCE_SENSOR_UART_NUM);
}

void PresenceSensor::InitUart() {
    uart_config_t uart_cfg = {};
    uart_cfg.baud_rate  = PRESENCE_SENSOR_UART_BAUD;
    uart_cfg.data_bits  = UART_DATA_8_BITS;
    uart_cfg.parity     = UART_PARITY_DISABLE;
    uart_cfg.stop_bits  = UART_STOP_BITS_1;
    uart_cfg.flow_ctrl  = UART_HW_FLOWCTRL_DISABLE;
    uart_cfg.source_clk = UART_SCLK_DEFAULT;

    esp_err_t ret = uart_driver_install(
        (uart_port_t)PRESENCE_SENSOR_UART_NUM, 512, 0, 0, nullptr, 0);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_driver_install failed: %s", esp_err_to_name(ret));
        return;
    }
    ret = uart_param_config((uart_port_t)PRESENCE_SENSOR_UART_NUM, &uart_cfg);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_param_config failed: %s", esp_err_to_name(ret));
        return;
    }
    ret = uart_set_pin((uart_port_t)PRESENCE_SENSOR_UART_NUM,
                       PRESENCE_SENSOR_UART_TX_PIN,
                       PRESENCE_SENSOR_UART_RX_PIN,
                       UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE);
    if (ret != ESP_OK) {
        ESP_LOGE(TAG, "uart_set_pin failed: %s", esp_err_to_name(ret));
        return;
    }
    ESP_LOGI(TAG, "UART1 initialized: baud=%d RX=IO%d TX=IO%d",
             PRESENCE_SENSOR_UART_BAUD,
             PRESENCE_SENSOR_UART_RX_PIN,
             PRESENCE_SENSOR_UART_TX_PIN);
}

void PresenceSensor::ConfigureSensor() {
    uart_flush((uart_port_t)PRESENCE_SENSOR_UART_NUM);

    const uint8_t kEnterConfig[] = {
        0xFD, 0xFC, 0xFB, 0xFA,
        0x04, 0x00,
        0xFF, 0x00,
        0x01, 0x00,
        0x04, 0x03, 0x02, 0x01
    };
    uart_write_bytes((uart_port_t)PRESENCE_SENSOR_UART_NUM,
                     kEnterConfig, sizeof(kEnterConfig));
    vTaskDelay(pdMS_TO_TICKS(100));

    const uint8_t kSetRange[] = {
        0xFD, 0xFC, 0xFB, 0xFA,
        0x14, 0x00,
        0x60, 0x00,
        0x00, 0x00, 0x02, 0x00, 0x00, 0x00,
        0x01, 0x00, 0x02, 0x00, 0x00, 0x00,
        0x02, 0x00, 0x05, 0x00, 0x00, 0x00,
        0x04, 0x03, 0x02, 0x01
    };
    uart_write_bytes((uart_port_t)PRESENCE_SENSOR_UART_NUM,
                     kSetRange, sizeof(kSetRange));
    vTaskDelay(pdMS_TO_TICKS(100));

    const uint8_t kExitConfig[] = {
        0xFD, 0xFC, 0xFB, 0xFA,
        0x02, 0x00,
        0xFE, 0x00,
        0x04, 0x03, 0x02, 0x01
    };
    uart_write_bytes((uart_port_t)PRESENCE_SENSOR_UART_NUM,
                     kExitConfig, sizeof(kExitConfig));
    vTaskDelay(pdMS_TO_TICKS(100));

    ESP_LOGI(TAG, "Sensor configured: max range gate=2 (~1.5m), no-person timeout=5s");
}

void PresenceSensor::ResetCooldown() {
    esp_timer_stop(cooldown_timer_);
    cooldown_active_ = false;
    ESP_LOGI(TAG, "Cooldown reset");
}

void PresenceSensor::SetCooldown() {
    cooldown_active_ = true;
    esp_timer_stop(cooldown_timer_);
    esp_timer_start_once(cooldown_timer_, kCooldownUs);
}

void PresenceSensor::RequestStableRecheck() {
    if (cooldown_active_.load()) {
        ESP_LOGI(TAG, "RequestStableRecheck ignored: cooldown active");
        return;
    }
    if (gpio_get_level((gpio_num_t)PRESENCE_SENSOR_OUT_PIN) != 1) {
        ESP_LOGI(TAG, "RequestStableRecheck ignored: GPIO low");
        return;
    }
    if (!notify_task_) return;
    recheck_requested_.store(true);
    xTaskNotifyGive(notify_task_);
    ESP_LOGI(TAG, "RequestStableRecheck: dwell check queued");
}

void PresenceSensor::ConfirmPresentAndFire() {
    uint32_t gen = presence_generation_.load();
    bool was = confirmed_present_.load();
    if (!was) {
        gen = presence_generation_.fetch_add(1) + 1;
        confirmed_present_.store(true);
        ESP_LOGI(TAG,
                 "Stable presence confirmed gen=%u (dwell %dms)",
                 static_cast<unsigned>(gen), kDwellMs);
        test_observability::Event("radar", "stable_presence", gen,
                                  "present", "dwell_confirmed", kDwellMs);
    } else {
        ESP_LOGI(TAG,
                 "Stable presence recheck gen=%u (already confirmed)",
                 static_cast<unsigned>(gen));
    }
    if (on_stable_presence_) {
        on_stable_presence_(gen);
    }
}

void PresenceSensor::ConfirmAbsentAndFire() {
    if (!confirmed_present_.load()) {
        return;
    }
    const uint32_t gen = presence_generation_.load();
    confirmed_present_.store(false);
    ESP_LOGI(TAG, "Stable absence confirmed gen=%u (LOW for %dms)",
             static_cast<unsigned>(gen), kAbsenceMs);
    test_observability::Event("radar", "stable_absence", gen,
                              "absent", "absence_confirmed", kAbsenceMs);
    if (on_stable_absence_) {
        on_stable_absence_(gen);
    }
}

void PresenceSensor::StartNotifyTask() {
    xTaskCreate(NotifyTaskEntry, "presence_notify", 2048, this, 3, &notify_task_);
    task_diag::LogTaskHandle(TAG, "presence_notify_created", notify_task_, 3, -1);
}

void IRAM_ATTR PresenceSensor::OutPinIsrHandler(void* arg) {
    auto* self = static_cast<PresenceSensor*>(arg);
    if (self->cooldown_active_.load()) return;
    if (!self->notify_task_) return;
    BaseType_t woken = pdFALSE;
    vTaskNotifyGiveFromISR(self->notify_task_, &woken);
    portYIELD_FROM_ISR(woken);
}

void PresenceSensor::NotifyTaskEntry(void* arg) {
    task_diag::LogCurrentTask(TAG, "presence_notify_start", 3, -1);
    auto* self = static_cast<PresenceSensor*>(arg);
    while (true) {
        ulTaskNotifyTake(pdTRUE, portMAX_DELAY);
        self->recheck_requested_.store(false);

        if (self->cooldown_active_.load()) {
            ESP_LOGI(TAG, "Cooldown active, ignored");
            continue;
        }

        ESP_LOGI(TAG, "Start dwell check on IO%d (%dms)",
                 PRESENCE_SENSOR_OUT_PIN, kDwellMs);

        int dwell_count = 0;
        bool triggered  = false;
        while (dwell_count < kDwellTicks) {
            vTaskDelay(pdMS_TO_TICKS(kPollMs));

            if (self->cooldown_active_.load()) {
                ESP_LOGI(TAG, "Cooldown set during dwell, abort");
                break;
            }

            if (gpio_get_level((gpio_num_t)PRESENCE_SENSOR_OUT_PIN) == 1) {
                dwell_count++;
                ESP_LOGD(TAG, "Dwell %d/%d", dwell_count, kDwellTicks);
            } else {
                ESP_LOGI(TAG, "OUT went low at dwell %d/%d, reset",
                         dwell_count, kDwellTicks);
                dwell_count = 0;
                break;
            }
        }

        if (dwell_count >= kDwellTicks) {
            triggered = true;
        }
        if (!triggered) continue;

        self->ConfirmPresentAndFire();
    }
}

void PresenceSensor::StartAbsenceTask() {
    xTaskCreate(AbsenceTaskEntry, "presence_absence", 2048, this, 2, &absence_task_);
    task_diag::LogTaskHandle(TAG, "presence_absence_created", absence_task_, 2, -1);
}

void PresenceSensor::AbsenceTaskEntry(void* arg) {
    task_diag::LogCurrentTask(TAG, "presence_absence_start", 2, -1);
    auto* self = static_cast<PresenceSensor*>(arg);

    while (true) {
        vTaskDelay(pdMS_TO_TICKS(kAbsencePollMs));

        // Absence only applies after a confirmed stable presence.
        if (!self->confirmed_present_.load()) {
            continue;
        }

        int level = gpio_get_level((gpio_num_t)PRESENCE_SENSOR_OUT_PIN);
        if (level == 1) {
            continue;
        }

        int absence_count = 1;
        bool confirmed_absent = false;
        while (absence_count < kAbsenceTicks) {
            vTaskDelay(pdMS_TO_TICKS(kAbsencePollMs));
            if (gpio_get_level((gpio_num_t)PRESENCE_SENSOR_OUT_PIN) == 1) {
                break;
            }
            absence_count++;
        }

        if (absence_count >= kAbsenceTicks) {
            confirmed_absent = true;
        }

        if (confirmed_absent) {
            self->ConfirmAbsentAndFire();
        }
    }
}
