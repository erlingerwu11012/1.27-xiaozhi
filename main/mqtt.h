#pragma once
#include <string>
#include <functional>
#include <memory>

// MQTT 客户端抽象接口
// 由 NetworkInterface::CreateMqtt() 创建
class Mqtt {
public:
    virtual ~Mqtt() = default;

    // 设置 KeepAlive 间隔（秒）
    virtual void SetKeepAlive(int seconds) = 0;

    // 连接到 MQTT broker
    virtual bool Connect(const std::string& host, int port,
                         const std::string& client_id,
                         const std::string& username,
                         const std::string& password) = 0;

    // 是否已连接
    virtual bool IsConnected() const = 0;

    // 获取最后一次错误码
    virtual int GetLastError() const = 0;

    // 订阅主题
    virtual bool Subscribe(const std::string& topic) = 0;

    // 发布消息
    virtual bool Publish(const std::string& topic, const std::string& payload) = 0;

    // 注册连接成功回调
    virtual void OnConnected(std::function<void()> callback) = 0;

    // 注册断开连接回调
    virtual void OnDisconnected(std::function<void()> callback) = 0;

    // 注册消息接收回调
    virtual void OnMessage(std::function<void(const std::string& topic,
                                              const std::string& payload)> callback) = 0;
};
