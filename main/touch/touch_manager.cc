/**
 * @file touch_manager.cc
 * @brief 触摸管理模块实现 - GT911 归一化坐标、去抖动、视线平滑
 *
 * BOX-3B 优先使用 0x5D，失败则尝试 0x14。GT911 地址由 INT 引脚在复位时电平决定。
 */

#include "touch/touch_manager.h"
#include "task_diagnostics.h"

#include <driver/gpio.h>
#include <driver/i2c_master.h>
#include <esp_err.h>
#include <esp_timer.h>
#include <esp_lcd_panel_io.h>
#include <esp_lcd_touch.h>
#include <esp_lcd_touch_gt911.h>
#include <esp_lcd_touch_ft5x06.h>
#include <esp_log.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include <freertos/task.h>

#include <algorithm>
#include <cmath>

static const char* TAG = "TouchManager";

namespace touch {

/* ========== FT6336U 寄存器定义（来自 Focaltech 官方寄存器表） ========== */
#define FT6336U_REG_DEVICE_MODE       0x00  // 模式切换（RW）
#define FT6336U_REG_TD_STATUS         0x02  // 触摸点数（RO）
#define FT6336U_REG_THGROUP           0x80  // 触摸阈值（RW）
#define FT6336U_REG_THDIFF            0x85  // 滤波阈值（RW）
#define FT6336U_REG_TIME_ENTER_MONITOR 0x87 // 进入监控延时（RW）
#define FT6336U_REG_PERIODACTIVE      0x88  // 报点率（RW），默认 12 ≈ 60Hz
#define FT6336U_REG_PERIODMONITOR     0x89  // 监控周期（RW）
#define FT6336U_REG_CHIP_ID           0xA3  // 芯片 ID（RO）
#define FT6336U_REG_MODE              0xA4  // 中断模式（RW）：0=轮询，1=触发
#define FT6336U_REG_POWER_MODE        0xA5  // 电源模式（RW）
#define FT6336U_REG_FOCALTECH_ID      0xA8  // Focaltech Vendor ID（RO），应为 0x11
/* 注意：0x81~0x84 在 FT6336U 中为 Reserved，不可写 */

/**
 * @brief FT6336U 后初始化：在 esp_lcd_touch_new_i2c_ft5x06() 之后调用，
 *        覆盖 ESP-IDF FT5x06 驱动写入的不兼容寄存器值，
 *        并配置 FT6336U 专属参数。
 *
 * 参考：Focaltech 官方 fts_wait_tp_to_valid() + FT6336GU 外部寄存器表
 */
static void ft6336u_post_init(esp_lcd_touch_handle_t tp) {
    uint8_t val = 0;

    /* 1. 等待芯片就绪：循环读 Chip ID (0xA3)，参考 fts_wait_tp_to_valid() */
    bool chip_ready = false;
    for (int retry = 0; retry < 30; retry++) {
        if (esp_lcd_panel_io_rx_param(tp->io, FT6336U_REG_CHIP_ID, &val, 1) == ESP_OK && val != 0x00 && val != 0xFF) {
            ESP_LOGI(TAG, "FT6336U Chip ID: 0x%02X (ready after %d ms)", val, retry * 10);
            chip_ready = true;
            break;
        }
        vTaskDelay(pdMS_TO_TICKS(10));
    }
    if (!chip_ready) {
        ESP_LOGW(TAG, "FT6336U Chip ID read timeout, continuing anyway");
    }

    /* 读 Focaltech Vendor ID 做二次验证 */
    if (esp_lcd_panel_io_rx_param(tp->io, FT6336U_REG_FOCALTECH_ID, &val, 1) == ESP_OK) {
        ESP_LOGI(TAG, "FT6336U Focaltech ID: 0x%02X %s", val, (val == 0x11) ? "(OK)" : "(unexpected)");
    }

    /* 2. 写 FT6336U 合法的 RW 寄存器，覆盖 ESP-IDF FT5x06 驱动的不兼容值 */

    /* 触摸阈值 (0x80)：值越小越灵敏。默认保持 22（Kconfig 可调，见
     * TOUCH_FT6336_THGROUP），不得未经真机验证直接改为驱动默认的 70。 */
    val = (uint8_t)CONFIG_TOUCH_FT6336_THGROUP;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_THGROUP, &val, 1);

    /* 滤波阈值 (0x85)：默认 20 */
    val = 20;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_THDIFF, &val, 1);

    /* 进入监控延时 (0x87)：默认 10（单位：秒） */
    val = 10;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_TIME_ENTER_MONITOR, &val, 1);

    /* 报点率 (0x88)：默认 12 ≈ 60Hz */
    val = 12;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_PERIODACTIVE, &val, 1);

    /* 监控周期 (0x89)：默认 40 */
    val = 40;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_PERIODMONITOR, &val, 1);

    /* 中断模式 (0xA4)：1 = 触发模式（有触摸时产生中断） */
    val = 1;
    esp_lcd_panel_io_tx_param(tp->io, FT6336U_REG_MODE, &val, 1);

    /* 不写 0x81~0x84（FT6336U Reserved），ESP-IDF 驱动写了这些但无效 */

    ESP_LOGI(TAG, "FT6336U post-init done (threshold=%d, rate=%dHz, int_mode=trigger)",
             (int)CONFIG_TOUCH_FT6336_THGROUP, 60);
}

/* 视线平滑系数 [0,1]，越大越平滑 */
static constexpr float kGazeSmooth = 0.3f;

/* 心跳间隔 10 秒 */
static constexpr uint32_t kHeartbeatIntervalMs = 10000;

TouchManager::TouchManager() = default;

TouchManager::~TouchManager() {
    Deinit();
}

bool TouchManager::Init(const TouchManagerConfig& config, i2c_master_bus_handle_t i2c_bus) {
    if (initialized_) return true;

    config_ = config;
    i2c_bus_ = i2c_bus;
    owns_i2c_ = (i2c_bus == nullptr);

    if (owns_i2c_) {
        i2c_master_bus_config_t bus_cfg = {
            .i2c_port = (i2c_port_t)1,
            .sda_io_num = config_.sda,
            .scl_io_num = config_.scl,
            .clk_source = I2C_CLK_SRC_DEFAULT,
            .glitch_ignore_cnt = 7,
            .intr_priority = 0,
            .trans_queue_depth = 0,
            .flags = { .enable_internal_pullup = 1 },
        };
        if (i2c_new_master_bus(&bus_cfg, &i2c_bus_) != ESP_OK) {
            ESP_LOGE(TAG, "I2C bus init failed");
            return false;
        }
    }

    esp_lcd_touch_config_t tp_cfg = {
        .x_max = config_.display_width,
        .y_max = config_.display_height,
        .rst_gpio_num = config_.rst_pin,
        .int_gpio_num = config_.int_pin,
        .levels = { .reset = 0, .interrupt = 0 },
        .flags = {
            .swap_xy = config_.swap_xy,
            .mirror_x = config_.mirror_x,
            .mirror_y = config_.mirror_y,
        },
    };

    const uint8_t addr_list[] = {
        ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS,       /* 0x5D, BOX-3B 优先 */
        ESP_LCD_TOUCH_IO_I2C_GT911_ADDRESS_BACKUP /* 0x14 */
    };
    esp_lcd_panel_io_handle_t panel_io = nullptr;
    esp_lcd_touch_handle_t tp = nullptr;

    if (config_.chip_type == TouchChipType::FT6336) {
        /* ---------- FT6336U (FT5x06 兼容) ---------- */
        uint8_t ft_addr = config_.i2c_addr ? config_.i2c_addr : 0x48;
        esp_lcd_panel_io_i2c_config_t io_cfg = ESP_LCD_TOUCH_IO_I2C_FT5x06_CONFIG();
        io_cfg.dev_addr = ft_addr;
        io_cfg.scl_speed_hz = 400 * 1000;

        if (esp_lcd_new_panel_io_i2c(i2c_bus_, &io_cfg, &panel_io) != ESP_OK) {
            ESP_LOGE(TAG, "FT6336 Panel IO I2C init failed at 0x%02X", ft_addr);
            if (owns_i2c_) { i2c_del_master_bus(i2c_bus_); }
            return false;
        }

        if (esp_lcd_touch_new_i2c_ft5x06(panel_io, &tp_cfg, &tp) != ESP_OK) {
            ESP_LOGE(TAG, "FT6336 (FT5x06) init failed at 0x%02X", ft_addr);
            esp_lcd_panel_io_del(panel_io);
            if (owns_i2c_) { i2c_del_master_bus(i2c_bus_); }
            return false;
        }
        ESP_LOGI(TAG, "FT6336 init OK at 0x%02X", ft_addr);
        ft6336u_post_init(tp);  /* FT6336U 专属后初始化 */
    } else {
        /* ---------- GT911 ---------- */
        for (size_t i = 0; i < sizeof(addr_list) / sizeof(addr_list[0]); i++) {
            esp_lcd_panel_io_i2c_config_t io_cfg = {};
            io_cfg.dev_addr = addr_list[i];
            io_cfg.control_phase_bytes = 1;
            io_cfg.dc_bit_offset = 0;
            io_cfg.lcd_cmd_bits = 16;
            io_cfg.scl_speed_hz = 400 * 1000;
            io_cfg.flags.disable_control_phase = 1;

            if (esp_lcd_new_panel_io_i2c(i2c_bus_, &io_cfg, &panel_io) != ESP_OK) {
                ESP_LOGW(TAG, "Panel IO I2C init failed at 0x%02X", addr_list[i]);
                continue;
            }

            if (esp_lcd_touch_new_i2c_gt911(panel_io, &tp_cfg, &tp) == ESP_OK) {
                ESP_LOGI(TAG, "GT911 init OK at 0x%02X (probe #%d)", addr_list[i], (int)(i + 1));
                break;
            }

            esp_lcd_panel_io_del(panel_io);
            panel_io = nullptr;
            ESP_LOGW(TAG, "GT911 init failed at 0x%02X, try next", addr_list[i]);
        }
    }

    if (panel_io == nullptr || tp == nullptr) {
        ESP_LOGE(TAG, "Touch init failed (chip_type=%d)", (int)config_.chip_type);
        if (owns_i2c_) { i2c_del_master_bus(i2c_bus_); }
        return false;
    }

    panel_io_ = panel_io;
    touch_handle_ = tp;

    mutex_ = xSemaphoreCreateMutex();
    if (mutex_ == nullptr) {
        esp_lcd_touch_del(tp);
        esp_lcd_panel_io_del(panel_io);
        if (owns_i2c_) { i2c_del_master_bus(i2c_bus_); }
        return false;
    }

    /* 必须在 xTaskCreate 之前设置，否则任务启动时 initialized_ 仍为 false 会立即退出 */
    initialized_ = true;

    BaseType_t ok = xTaskCreate(TouchTask, "touch", 2048, this, 3, (TaskHandle_t*)&task_handle_);
    if (ok != pdPASS) {
        initialized_ = false;
        vSemaphoreDelete((SemaphoreHandle_t)mutex_);
        esp_lcd_touch_del(tp);
        esp_lcd_panel_io_del(panel_io);
        if (owns_i2c_) { i2c_del_master_bus(i2c_bus_); }
        return false;
    }
    task_diag::LogTaskHandle(TAG, "touch_created", (TaskHandle_t)task_handle_, 3, -1);

    return true;
}

void TouchManager::Deinit() {
    if (!initialized_) return;

    if (task_handle_ != nullptr) {
        vTaskDelete((TaskHandle_t)task_handle_);
        task_handle_ = nullptr;
    }
    if (touch_handle_ != nullptr) {
        esp_lcd_touch_del((esp_lcd_touch_handle_t)touch_handle_);
        touch_handle_ = nullptr;
    }
    if (panel_io_ != nullptr) {
        esp_lcd_panel_io_del((esp_lcd_panel_io_handle_t)panel_io_);
        panel_io_ = nullptr;
    }
    if (mutex_ != nullptr) {
        vSemaphoreDelete((SemaphoreHandle_t)mutex_);
        mutex_ = nullptr;
    }
    if (owns_i2c_ && i2c_bus_ != nullptr) {
        i2c_del_master_bus(i2c_bus_);
        i2c_bus_ = nullptr;
    }
    initialized_ = false;
}

void TouchManager::TouchTask(void* arg) {
    task_diag::LogCurrentTask(TAG, "touch_start", 3, -1);
    auto* self = static_cast<TouchManager*>(arg);
    self->TaskLoop();
}

void TouchManager::TaskLoop() {
    const uint32_t period_ms = 10;
    esp_lcd_touch_point_data_t pts[1] = {};
    uint8_t cnt = 0;

    uint32_t poll_count = 0;
    uint32_t touch_count = 0;
    uint32_t last_heartbeat_ms = 0;

    while (initialized_ && touch_handle_ != nullptr) {
        poll_count++;

        esp_err_t err = esp_lcd_touch_read_data((esp_lcd_touch_handle_t)touch_handle_);
        if (err != ESP_OK) {
            read_fail_total_++;
            if (read_fail_total_ <= 3 || (read_fail_total_ % 100 == 0)) {
                ESP_LOGW(TAG, "[Touch] read_data failed err=%d (total fails=%lu)", err, (unsigned long)read_fail_total_);
            }
            // I2C 读失败不是有效触摸样本：不得解释为新的 DOWN，也不得使用未初始化坐标。
            UpdateState(0, 0, 0, false, /*valid_sample=*/false);
        } else {
            esp_lcd_touch_get_data((esp_lcd_touch_handle_t)touch_handle_, pts, &cnt, 1);

            if (cnt > 0) {
                touch_count++;
                UpdateState(
                    (int16_t)pts[0].x,
                    (int16_t)pts[0].y,
                    (uint16_t)pts[0].strength,
                    /*touched=*/true, /*valid_sample=*/true);
            } else {
                UpdateState(0, 0, 0, false, /*valid_sample=*/true);
            }
        }

        uint32_t now_ms = (uint32_t)(esp_timer_get_time() / 1000);
        if (now_ms - last_heartbeat_ms >= kHeartbeatIntervalMs) {
            last_heartbeat_ms = now_ms;
            ESP_LOGD(TAG, "Touch heartbeat: poll=%lu touch=%lu read_fail=%lu (last 10s, fail is total)",
                     (unsigned long)poll_count, (unsigned long)touch_count, (unsigned long)read_fail_total_);
            poll_count = 0;
            touch_count = 0;
        }

        vTaskDelay(pdMS_TO_TICKS(period_ms));
    }
    ESP_LOGW(TAG, "[Touch] TaskLoop exited");
    vTaskDelete(nullptr);
}

float TouchManager::Clamp01(float v) const {
    return std::max(0.0f, std::min(1.0f, v));
}

void TouchManager::UpdateState(int16_t raw_x, int16_t raw_y, uint16_t pressure, bool touched, bool valid_sample) {
    float nx = config_.display_width > 0
        ? Clamp01((float)raw_x / (float)config_.display_width)
        : 0.5f;
    float ny = config_.display_height > 0
        ? Clamp01((float)raw_y / (float)config_.display_height)
        : 0.5f;

    if (valid_sample && touched) {
        last_contact_x_ = nx;
        last_contact_y_ = ny;
        last_contact_pressure_ = pressure;
    } else {
        // During release debounce we still report pressed. Preserve the last
        // real contact instead of publishing a phantom move to (0,0).
        nx = last_contact_x_;
        ny = last_contact_y_;
        pressure = last_contact_pressure_;
    }

    if (!valid_sample) {
        // I2C read 失败：不是有效触摸样本，不改变 press/release 去抖计数。
        // 累计连续失败次数，达到阈值后安全释放，避免状态永久卡在 pressed。
        consecutive_fail_count_++;
        if (consecutive_fail_count_ >= kMaxConsecutiveFails) {
            consecutive_fail_count_ = 0;
            if (stable_pressed_) {
                stable_pressed_ = false;
                press_streak_ = 0;
                release_streak_ = 0;
                WriteState(false, nx, ny, pressure);
#if CONFIG_TOUCH_DIAGNOSTICS
                ESP_LOGW(TAG, "[TOUCH_DIAG] i2c_fail_release i2c_fail=%lu",
                         (unsigned long)read_fail_total_);
#endif
            }
        }
        return;
    }
    consecutive_fail_count_ = 0;

    // 稳定状态去抖：连续 kPressDebounceFrames 次有效按下才判定 DOWN，
    // 连续 kReleaseDebounceFrames 次有效非触摸才判定 UP。单次毛刺不会形成 TAP。
    if (touched) {
        if (press_streak_ < kPressDebounceFrames) ++press_streak_;
        release_streak_ = 0;
        if (press_streak_ >= kPressDebounceFrames && !stable_pressed_) {
            stable_pressed_ = true;
#if CONFIG_TOUCH_DIAGNOSTICS
            ESP_LOGI(TAG, "[TOUCH_DIAG] press_stable raw=(%d,%d) norm=(%.2f,%.2f) samples=%u i2c_fail=%lu",
                     raw_x, raw_y, nx, ny, (unsigned)press_streak_, (unsigned long)read_fail_total_);
#endif
        }
    } else {
        if (release_streak_ < kReleaseDebounceFrames) ++release_streak_;
        press_streak_ = 0;
        if (release_streak_ >= kReleaseDebounceFrames && stable_pressed_) {
            stable_pressed_ = false;
#if CONFIG_TOUCH_DIAGNOSTICS
            ESP_LOGI(TAG, "[TOUCH_DIAG] release_stable norm=(%.2f,%.2f) samples=%u i2c_fail=%lu",
                     nx, ny, (unsigned)release_streak_, (unsigned long)read_fail_total_);
#endif
        }
    }

    /* 调试：稳定 down/up 边界打日志（DEBUG 级别，默认关闭） */
    if (stable_pressed_ != last_debug_pressed_) {
        last_debug_pressed_ = stable_pressed_;
        if (stable_pressed_) {
            ESP_LOGD(TAG, "Touch DOWN raw=(%d,%d) norm=(%.2f,%.2f)", raw_x, raw_y, nx, ny);
        } else {
            ESP_LOGD(TAG, "Touch UP");
        }
    }

    WriteState(stable_pressed_, nx, ny, pressure);
}

void TouchManager::WriteState(bool touched, float nx, float ny, uint16_t pressure) {
    if (xSemaphoreTake((SemaphoreHandle_t)mutex_, pdMS_TO_TICKS(10)) == pdTRUE) {
        state_.touched = touched;
        state_.x = nx;
        state_.y = ny;
        state_.pressure = pressure;

        if (touched) {
            gaze_.gaze_x += kGazeSmooth * (nx - gaze_.gaze_x);
            gaze_.gaze_y += kGazeSmooth * (ny - gaze_.gaze_y);
        } else {
            gaze_.gaze_x += kGazeSmooth * (0.5f - gaze_.gaze_x);
            gaze_.gaze_y += kGazeSmooth * (0.5f - gaze_.gaze_y);
        }
        gaze_.gaze_x = Clamp01(gaze_.gaze_x);
        gaze_.gaze_y = Clamp01(gaze_.gaze_y);

        xSemaphoreGive((SemaphoreHandle_t)mutex_);
    }
}

bool TouchManager::GetState(TouchPoint* out) const {
    if (out == nullptr) return false;
    // Gesture polling runs in ESP_TIMER_TASK. Never block it or fabricate UP
    // when the producer is briefly writing a snapshot.
    if (xSemaphoreTake((SemaphoreHandle_t)mutex_, 0) == pdTRUE) {
        out->touched = state_.touched;
        out->x = state_.x;
        out->y = state_.y;
        out->pressure = state_.pressure;
        xSemaphoreGive((SemaphoreHandle_t)mutex_);
        return true;
    }
    return false;
}

void TouchManager::GetGazePoint(GazePoint* out) const {
    if (out == nullptr) return;
    if (xSemaphoreTake((SemaphoreHandle_t)mutex_, pdMS_TO_TICKS(20)) == pdTRUE) {
        out->gaze_x = gaze_.gaze_x;
        out->gaze_y = gaze_.gaze_y;
        xSemaphoreGive((SemaphoreHandle_t)mutex_);
    } else {
        out->gaze_x = 0.5f;
        out->gaze_y = 0.5f;
    }
}

}  // namespace touch
