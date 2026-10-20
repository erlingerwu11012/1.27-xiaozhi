#pragma once
#include <string>
#include <functional>
#include <memory>
#include <cstdint>

// WebSocket 客户端抽象接口
// 由 NetworkInterface::CreateWebSocket() 创建
class WebSocket {
public:
    virtual ~WebSocket() = default;

    // 设置握手请求头（必须在 Connect 之前调用）
    virtual void SetHeader(const char* key, const char* value) = 0;

    // 连接到 WebSocket 服务器（默认最多等待约 10 秒）
    virtual bool Connect(const char* url) { return Connect(url, 10000); }

    // 连接到 WebSocket 服务器，timeout_ms 为等待握手完成的上限
    virtual bool Connect(const char* url, int timeout_ms) = 0;

    // 发送文本消息
    virtual bool Send(const std::string& text) = 0;

    // 发送二进制消息
    virtual bool Send(const void* data, size_t len, bool binary) = 0;

    // 是否已连接
    virtual bool IsConnected() const = 0;

    // 获取最后一次错误码
    virtual int GetLastError() const = 0;

    // True when the last failed Send was a recoverable timeout/jitter while
    // the socket still reports connected (do not tear down the control link).
    virtual bool WasLastSendTransient() const { return false; }

    // Classifies a transient not-started failure for diagnostics.
    // "tx_lock_timeout" | "socket_not_writable" | "" when N/A.
    virtual const char* LastSendTransientClass() const { return ""; }

    // Mark a successful application-level receive (JSON/audio) for diagnostics.
    virtual void NoteRxOk() {}

    // Emit a single [WS_DIAG] line. Never logs tokens/passwords/audio bodies.
    // send_queue_depth < 0 means "unknown / not provided".
    virtual void LogDiagnostics(const char* reason, int send_queue_depth = -1) {}

    // Connection age in milliseconds (0 if never connected).
    virtual int64_t ConnectionAgeMs() const { return 0; }

    // 注册数据接收回调（binary=true 表示二进制帧）
    virtual void OnData(std::function<void(const char* data, size_t len, bool binary)> callback) = 0;

    // 注册断开连接回调
    virtual void OnDisconnected(std::function<void()> callback) = 0;
};
