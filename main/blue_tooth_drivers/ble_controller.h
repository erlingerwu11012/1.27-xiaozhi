#ifndef BLE_CONTROLLER_H
#define BLE_CONTROLLER_H

#include <stdint.h>
#include <string>

class BleController {
public:
    // 获取单例实例
    static BleController& GetInstance();

    // 初始化蓝牙HID服务（包含硬件控制器使能、NimBLE栈启动、HID注册）
    void Init();

    // 检查电脑是否已通过蓝牙连接
    bool IsConnected();

    // === 键盘功能 ===
    // 发送标准按键。modifier 参考：0x08 为 Left GUI (Win键), 0x02 为 Left Shift
    void SendKey(uint8_t key_code, uint8_t modifier = 0);
    // 锁定屏幕 (Win + L)
    void LockScreen();

    // === 媒体控制功能 ===
    void VolumeUp();
    void VolumeDown();
    void Mute();
    void PlayPause();
    void NextTrack();
    void PrevTrack();

    // === 鼠标控制 (保留接口) ===
    void MoveMouse(int8_t x, int8_t y);

private:
    // 禁止外部构造和拷贝（标准单例模式）
    BleController() = default;
    ~BleController() = default;
    BleController(const BleController&) = delete;
    BleController& operator=(const BleController&) = delete;
};

#endif // BLE_CONTROLLER_H