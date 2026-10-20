#ifndef _BOARD_CONFIG_H_
#define _BOARD_CONFIG_H_

#include <driver/gpio.h>

#define AUDIO_INPUT_SAMPLE_RATE  24000
#define AUDIO_OUTPUT_SAMPLE_RATE 24000

#define AUDIO_INPUT_REFERENCE    true

#define AUDIO_I2S_GPIO_MCLK GPIO_NUM_2
#define AUDIO_I2S_GPIO_WS GPIO_NUM_45
#define AUDIO_I2S_GPIO_BCLK GPIO_NUM_17
#define AUDIO_I2S_GPIO_DIN  GPIO_NUM_16
#define AUDIO_I2S_GPIO_DOUT GPIO_NUM_15

#define AUDIO_CODEC_PA_PIN       GPIO_NUM_46
#define AUDIO_CODEC_I2C_SDA_PIN  GPIO_NUM_8
#define AUDIO_CODEC_I2C_SCL_PIN  GPIO_NUM_18
#define AUDIO_CODEC_ES8311_ADDR  ES8311_CODEC_DEFAULT_ADDR
#define AUDIO_CODEC_ES7210_ADDR  ES7210_CODEC_DEFAULT_ADDR

#define BUILTIN_LED_GPIO        GPIO_NUM_NC
#define BOOT_BUTTON_GPIO        GPIO_NUM_0
#define VOLUME_UP_BUTTON_GPIO   GPIO_NUM_NC
#define VOLUME_DOWN_BUTTON_GPIO GPIO_NUM_NC

#define DISPLAY_WIDTH   320
#define DISPLAY_HEIGHT  320
// 180° from the previous (mirror_x=true, swap=false / MADCTL 0x48) orientation.
// Touch sensor axes are configured independently below; LCD MADCTL does not
// describe the origin of the FT6336U sensor.
#define DISPLAY_MIRROR_X false
#define DISPLAY_MIRROR_Y true
#define DISPLAY_SWAP_XY  false

#define DISPLAY_OFFSET_X  0
// ST7796 320x320 is windowed from 320x480 GRAM. MY=1 reverses gate scan,
// so the visible 320 rows start at 160 instead of 0. Without this gap the
// unused 160 lines show as snow/garbage on one edge.
#define DISPLAY_OFFSET_Y  160

#define DISPLAY_BACKLIGHT_PIN GPIO_NUM_47
#define DISPLAY_BACKLIGHT_OUTPUT_INVERT false
// Keep 1kHz: device testing at 5kHz made the backlight nearly invisible
// even at a 90% target. Check the external driver before trying another rate.
#define DISPLAY_BACKLIGHT_PWM_FREQ_HZ 1000

// ---------- 触摸屏 (FT6336U) 引脚配置 ----------
#define TOUCH_I2C_SDA_PIN   GPIO_NUM_8
#define TOUCH_I2C_SCL_PIN   GPIO_NUM_18
#define TOUCH_INT_PIN       GPIO_NUM_3
#define TOUCH_RST_PIN       GPIO_NUM_NC  /* 与 LCD 共用 GPIO48，不单独复位 */
#define TOUCH_RST_IS_NC     1

// FT6336U X runs opposite to the visible screen on this assembly: the old
// LCD flags made a physical right-side stroke adjust the left-side control.
#define TOUCH_SWAP_XY  false
#define TOUCH_MIRROR_X true
#define TOUCH_MIRROR_Y true

// ---------- 人体存在传感器 HLK-LD2410D-B ----------
#define PRESENCE_SENSOR_OUT_PIN         GPIO_NUM_12  // LD2410D-B OUT → ESP32（有人=高）
#define PRESENCE_SENSOR_UART_NUM        UART_NUM_1   // 使用 UART1，避开 UART0(GPIO43/44)
#define PRESENCE_SENSOR_UART_RX_PIN     GPIO_NUM_38  // 传感器 TX → ESP32 RX
#define PRESENCE_SENSOR_UART_TX_PIN     GPIO_NUM_39  // ESP32 TX → 传感器 RX
#define PRESENCE_SENSOR_UART_BAUD       115200       // LD2410D-B 默认波特率（手册 4.1/4.2 节）

// ---------- USB 摄像头电源控制 ----------
// IO11 controls the active-high VBUS load switch.  Power-cycle once before
// starting USB Host, then keep VBUS enabled for the lifetime of the firmware.
#define USB_ENABLE_PIN                  GPIO_NUM_11
#define USB_ENABLE_ACTIVE_LEVEL         1
#define USB_POWER_OFF_DELAY_MS          300
#define USB_POWER_STABILIZE_DELAY_MS    800

// Face identity uses short-lived MCP capabilities.vision.identity_url + token.
// Long-lived FACE_API_URL / FACE_API_TOKEN firmware knobs are retired.

#endif // _BOARD_CONFIG_H_
