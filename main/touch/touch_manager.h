/**
 * @file touch_manager.h
 * @brief 触摸管理模块 - 归一化坐标、去抖动、视线平滑
 *
 * 适用于 ESP32-S3-BOX-3B (GT911) 及可切换屏幕尺寸的 0.0~1.0 坐标体系。
 * 驱动层使用 esp_lcd_touch_gt911；未来可迁移至 LovyanGFX (LGFX) 时接口保持不变。
 */

#pragma once

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/**
 * @brief 归一化触摸点（0.0 ~ 1.0）
 */
typedef struct {
    bool touched;       /**< 是否被触摸 */
    float x;            /**< 归一化 X 坐标 [0.0, 1.0] */
    float y;            /**< 归一化 Y 坐标 [0.0, 1.0] */
    uint16_t pressure;  /**< 触摸压力 (0~255，部分芯片支持) */
} TouchPoint;

/**
 * @brief 平滑后的视线坐标（用于眼睛跟手）
 */
typedef struct {
    float gaze_x;   /**< 视线 X [0.0, 1.0]，未触摸时为 0.5 中心 */
    float gaze_y;   /**< 视线 Y [0.0, 1.0]，未触摸时为 0.5 中心 */
} GazePoint;

#ifdef __cplusplus
}
#endif

#ifdef __cplusplus

#include <driver/gpio.h>
#include <driver/i2c_master.h>

namespace touch {

/**
 * @brief 触摸芯片类型
 */
enum class TouchChipType {
    GT911,
    FT6336,  // FT5x06 兼容
};

/**
 * @brief TouchManager 配置（由 config.h 或板级传入）
 */
struct TouchManagerConfig {
    gpio_num_t sda;             /**< I2C SDA (BOX-3B: 8) */
    gpio_num_t scl;             /**< I2C SCL (BOX-3B: 18) */
    gpio_num_t int_pin;         /**< 触摸中断 (BOX-3B: 3)，GPIO_NUM_NC 表示轮询 */
    gpio_num_t rst_pin;         /**< 触摸复位 (BOX-3B: 48)，GPIO_NUM_NC 表示共用 LCD RST */
    uint16_t display_width;     /**< 显示宽度，用于归一化 */
    uint16_t display_height;    /**< 显示高度，用于归一化 */
    bool swap_xy;               /**< 是否交换 XY */
    bool mirror_x;              /**< 是否 X 镜像 */
    bool mirror_y;              /**< 是否 Y 镜像 */
    TouchChipType chip_type = TouchChipType::GT911;  /**< 触摸芯片类型，默认 GT911 */
    uint8_t i2c_addr = 0;       /**< I2C 地址，0 表示使用默认地址 */
};

/**
 * @brief 触摸管理模块
 *
 * - 独立任务采样，信号量保护
 * - 坐标归一化 0.0~1.0
 * - 去抖动、视线平滑
 */
class TouchManager {
public:
    TouchManager();
    ~TouchManager();

    TouchManager(const TouchManager&) = delete;
    TouchManager& operator=(const TouchManager&) = delete;

    /**
     * @brief 初始化触摸（GT911），启动采样任务
     * @param config 配置（含引脚、分辨率）
     * @param i2c_bus 可选，传入已创建的 I2C 总线以复用；nullptr 则内部创建
     * @return true 成功
     */
    bool Init(const TouchManagerConfig& config, i2c_master_bus_handle_t i2c_bus = nullptr);

    /**
     * @brief 反初始化，停止任务
     */
    void Deinit();

    /**
     * @brief 获取当前触摸状态（线程安全）
     * @param out 输出 TouchPoint
     */
    // Returns false when the snapshot is unavailable; callers keep their state.
    bool GetState(TouchPoint* out) const;

    /**
     * @brief 获取平滑后的视线坐标（用于眼睛跟手）
     * @param out 输出 GazePoint
     */
    void GetGazePoint(GazePoint* out) const;

    /**
     * @brief 是否已初始化
     */
    bool IsInitialized() const { return initialized_; }

private:
    static void TouchTask(void* arg);
    void TaskLoop();
    void UpdateState(int16_t raw_x, int16_t raw_y, uint16_t pressure, bool touched, bool valid_sample);
    void WriteState(bool touched, float nx, float ny, uint16_t pressure);
    float Clamp01(float v) const;

    bool initialized_ = false;
    TouchManagerConfig config_ = {};
    i2c_master_bus_handle_t i2c_bus_ = nullptr;
    bool owns_i2c_ = false;
    void* touch_handle_ = nullptr;   /* esp_lcd_touch_handle_t */
    void* panel_io_ = nullptr;      /* esp_lcd_panel_io_handle_t */

    mutable void* mutex_ = nullptr;    /* SemaphoreHandle_t */
    volatile TouchPoint state_ = {};
    volatile GazePoint gaze_ = {0.5f, 0.5f};
    void* task_handle_ = nullptr;

    /* --- 去抖状态机（仅在 TouchTask 线程访问，无需额外锁） ---
     * 稳定按下需连续 kPressDebounceFrames 次有效触摸样本（10ms 周期 ≈ 30ms），
     * 稳定释放需连续 kReleaseDebounceFrames 次有效非触摸样本（≈ 20ms）。
     * 单次 I2C 毛刺不会再形成 DOWN→UP→TAP。 */
    // Owned by the sampling task. No-contact samples have no valid position.
    float last_contact_x_ = 0.5f, last_contact_y_ = 0.5f;
    uint16_t last_contact_pressure_ = 0;
    bool stable_pressed_ = false;
    uint8_t press_streak_ = 0;
    uint8_t release_streak_ = 0;
    uint8_t consecutive_fail_count_ = 0;
    bool last_debug_pressed_ = false;
    uint32_t read_fail_total_ = 0;
    static constexpr uint8_t kPressDebounceFrames = 3;
    static constexpr uint8_t kReleaseDebounceFrames = 2;
    /* 连续 I2C 读失败达到该阈值（10ms 周期 ≈ 100ms）后安全释放，避免状态永久卡在 pressed。 */
    static constexpr uint8_t kMaxConsecutiveFails = 10;
};

}  // namespace touch

#endif /* __cplusplus */
