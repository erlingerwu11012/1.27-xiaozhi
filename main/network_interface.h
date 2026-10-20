#pragma once
#include <memory>
#include "http.h"
#include "web_socket.h"
#include "mqtt.h"
#include "udp.h"

// 网络抽象接口：工厂类，负责创建各种网络连接对象
// WifiBoard::GetNetwork() 返回此接口的实现（EspNetwork）
class NetworkInterface {
public:
    virtual ~NetworkInterface() = default;

    // 创建 HTTP 客户端（index 用于区分多个并发连接）
    virtual std::unique_ptr<Http> CreateHttp(int index) = 0;

    // 创建 WebSocket 客户端
    virtual std::unique_ptr<WebSocket> CreateWebSocket(int index) = 0;

    // 创建 MQTT 客户端
    virtual std::unique_ptr<Mqtt> CreateMqtt(int index) = 0;

    // 创建 UDP 客户端
    virtual std::unique_ptr<Udp> CreateUdp(int index) = 0;
};
