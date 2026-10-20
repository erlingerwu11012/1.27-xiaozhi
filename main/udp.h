#pragma once
#include <string>
#include <functional>

// UDP 客户端抽象接口
// 由 NetworkInterface::CreateUdp() 创建
class Udp {
public:
    virtual ~Udp() = default;

    // 连接到远端地址
    virtual bool Connect(const std::string& host, int port) = 0;

    // 发送数据，返回实际发送字节数，<0 表示错误
    virtual int Send(const std::string& data) = 0;

    // 注册数据接收回调
    virtual void OnMessage(std::function<void(const std::string& data)> callback) = 0;
};
