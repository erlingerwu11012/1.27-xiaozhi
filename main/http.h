#pragma once
#include <string>
#include <memory>
#include <utility>
#include <stdexcept>
#include "camera_image_buffer.h"

// HTTP 客户端抽象接口
// 由 NetworkInterface::CreateHttp() 创建，底层实现基于 esp_http_client
class Http {
public:
    virtual ~Http() = default;

    // 设置请求头
    virtual void SetHeader(const char* key, const char* value) = 0;

    // 设置请求体（用于 POST/PUT）
    virtual void SetContent(std::string&& content) = 0;

#ifdef ESP_PLATFORM
    // Photo uploads transfer ownership without making an ordinary-heap copy.
    // Unsupported clients must fail explicitly rather than fall back to SRAM.
    virtual void SetPsramContent(CameraMultipartBody&& content) {
        (void)content;
        throw std::logic_error("HTTP client does not support PSRAM photo bodies");
    }
#else
    void SetPsramContent(CameraMultipartBody&& content) { SetContent(std::move(content)); }
#endif

    // 打开连接并发送请求（method: "GET"/"POST"/"PUT"/"DELETE" 等）
    virtual bool Open(const char* method, const std::string& url) = 0;

    // Legacy streaming hook. New POST/PUT callers must provide the complete
    // body with SetContent() before Open(); they must not use chunked framing
    // or an empty Write() terminator.
    virtual int Write(const char* data, size_t len) = 0;

    // 获取响应状态码
    virtual int GetStatusCode() = 0;

    // 获取响应体长度（Content-Length），未知时返回 -1
    virtual int GetBodyLength() = 0;

    // 流式读取响应体，返回实际读取字节数，0 表示结束，<0 表示错误
    virtual int Read(char* buffer, size_t len) = 0;

    // 读取全部响应体为字符串
    virtual std::string ReadAll() = 0;

    // 关闭连接
    virtual void Close() = 0;
};

// Read at most `limit` bytes via Http::Read. If more body remains, Close() the
// client and set *truncated. Never buffers the unbounded remainder.
inline std::string ReadHttpBodyBounded(Http* http, size_t limit,
                                       bool* truncated = nullptr) {
    if (truncated) *truncated = false;
    if (!http || limit == 0) return {};
    std::string out;
    char buf[256];
    size_t total = 0;
    while (total < limit) {
        const size_t want =
            sizeof(buf) < (limit - total) ? sizeof(buf) : (limit - total);
        const int n = http->Read(buf, want);
        if (n < 0) break;
        if (n == 0) return out;
        out.append(buf, static_cast<size_t>(n));
        total += static_cast<size_t>(n);
    }
    char probe = 0;
    const int extra = http->Read(&probe, 1);
    if (extra > 0) {
        if (truncated) *truncated = true;
        http->Close();
    }
    return out;
}
