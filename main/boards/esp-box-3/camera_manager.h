#pragma once

#include "camera_image_buffer.h"
#include "camera.h"
#include <mutex>
#include <atomic>
#include <cstdint>
#include <vector>
#include <functional>

class Esp32Camera;

/**
 * CameraManager — USB 摄像头资源管理器（单例）
 *
 * 管理常开 UVC 摄像头实例的生命周期；供电由外部 USB Host/DOCK 提供。
 * 单次拍照：TryAcquire/AcquireWithRetry → Capture → Explain → Release。
 * 旧预览接口仅作兼容，始终拒绝启动；不创建预览线程。
 *
 * 解耦设计：UI 更新全部通过 on_ui_cb 回调完成，本类不依赖任何 display 头文件。
 */
class CameraManager {
public:
    enum class StreamState {
        Idle,
        Opening,
        Ready,
        Failed,
    };

    // ── 存在状态机 ────────────────────────────────────────────────────────────
    enum class PresenceState {
        EMPTY,    // 无人
        PRESENT,  // 检测到人（防抖通过）
        ENGAGED,  // 用户正在对话，屏蔽自动打招呼
    };

    static CameraManager& GetInstance();

    // ── 模式一：单次拍照接口 ──────────────────────────────────────────────────

    /**
     * 尝试获取已经常驻的摄像头资源（非阻塞）：
     * - 成功：复用已就绪的 UVC stream，返回 true
     * - 失败（mutex 被占）：立即返回 false，不阻塞
     * - 失败（stream 未就绪）：保持 VBUS 和 USB Host 常开，返回 false
     *   此时 hardware_failed_ 被置为 true，AcquireWithRetry 可据此重试
     */
    bool TryAcquire(bool background = false);

    /**
     * 获取已经由 usb_cam_init 打开的持久 stream。
     * 本接口不会参与 UVC 枚举或重新打开设备，避免拍照任务与启动任务并发初始化。
     */
    bool AcquireWithRetry(int max_retries = 2, bool background = false);

    /**
     * 释放摄像头使用权；不析构持久实例，不停止 USB Host，不关闭 VBUS
     */
    void Release();

    /**
     * 兼容旧调用的空操作。常驻策略下不允许业务流程关闭 VBUS。
     */
    void EnsurePowerOff();

    /**
     * 返回当前摄像头实例，仅在 TryAcquire()/AcquireWithRetry() 成功后有效
     */
    Camera* GetCamera();

    /**
     * 返回上一次 TryAcquire 是否因硬件故障失败（而非 mutex 被占）
     */
    bool IsHardwareFailed() const { return hardware_failed_; }

    /**
     * 标记 esp_video_init 已完成（由外部早期初始化调用，防止重复初始化）
     */
    void MarkVideoInitDone() { video_init_done_ = true; }

    /**
     * 检查 UVC 设备是否已枚举（dev_addr 非零）
     * 用于启动时等待枚举完成，不做 open/close
     */
    bool IsUvcDeviceConnected();

    /**
     * 查询 esp_video_init 是否已完成
     */
    bool IsVideoInitDone() const { return video_init_done_; }

    /**
     * 启动后立即打开摄像头 stream 并保持常开（claim USB device，阻止 HCD 反复枚举）
     * 成功后 persistent_camera_ 非空，后续 TryAcquire 直接复用
     */
    bool OpenPersistentStream();

    bool IsStreamReady();
    bool IsOperationActive() const { return operation_active_.load(); }
    bool IsForegroundOperationActive() const { return foreground_operation_active_.load(); }

    bool IsStreamOpening() const {
        return stream_state_.load(std::memory_order_acquire) == StreamState::Opening;
    }

    StreamState GetStreamState() const {
        return stream_state_.load(std::memory_order_acquire);
    }

    /**
     * 轮询等待 UVC 设备节点可 open()（替代固定 800ms 盲等）
     * 供早期初始化和 TryAcquire 共用
     */
    bool WaitForUvcReady(int timeout_ms = 1500, int poll_interval_ms = 100);

    // ── 旧预览接口（保留 ABI，当前固件不启动预览） ────────────────────────────

    /**
     * 启动常开预览（持续抓帧推屏 + 人脸识别状态机）
     *
     * on_face_cb: 状态从 EMPTY→PRESENT 且防抖通过时触发，参数为人名
     *             （"unknown" 表示检测到人但未识别）
     * on_ui_cb:   UI 更新回调，参数为新的 PresenceState
     *             调用方负责在此回调中执行 SetBorderEffect / ShowPrivacyOverlay 等 UI 操作
     *
     * 当前固件固定返回 false，避免引入未验证的持续推流线程。
     */
    bool StartPreview(
        std::function<void(const std::string& name)> on_face_cb = nullptr,
        std::function<void(PresenceState state)>     on_ui_cb   = nullptr,
        std::function<void(uint32_t session_id, const CameraJpegBuffer& jpeg)> on_frame_cb = nullptr);

    /**
     * 停止常开预览。当前实现为空操作并返回 true。
     */
    // Returns false when an in-flight operation has not reached a safe stop
    // point yet.  The caller should leave the preview UI intact and retry.
    bool StopPreview();

    /** 当前是否处于预览模式 */
    bool IsPreviewActive() const;

    /**
     * Returns true only while the specified preview session is still active.
     * UI consumers use this to discard asynchronous frames queued before close.
     */
    bool IsPreviewSessionActive(uint32_t session_id) const;

    // The WebSocket session can be established before the persistent camera
    // has finished opening, so retain it here and apply it on creation.
    void SetSessionId(const std::string& session_id);

    // MCP initialize can also arrive before the persistent camera exists, and
    // GetCamera() is nullptr unless TryAcquire() is held.  Stash the vision
    // explain URL here and apply it immediately if the camera is ready.
    void SetExplainUrl(const std::string& url, const std::string& token);

    /** 返回最新预览帧；当前固件未启动预览，因此返回空 vector。 */
    CameraJpegBuffer GetLastFrame();

    /**
     * 获取当前存在状态
     */
    PresenceState GetPresenceState() const;

    /**
     * 外部通知：用户主动发起对话时调用，切换到 ENGAGED 状态屏蔽自动打招呼
     * 对话结束后调用 SetEngaged(false) 恢复 PRESENT 状态
     */
    void SetEngaged(bool engaged);

private:
    CameraManager() = default;
    ~CameraManager() = default;
    CameraManager(const CameraManager&) = delete;
    CameraManager& operator=(const CameraManager&) = delete;

    // ── 模式一私有辅助 ────────────────────────────────────────────────────────

    /**
     * 兼容旧设计保留；常驻策略下不执行运行期电源循环。
     */
    void PowerCycle();

    // ── 模式一成员 ────────────────────────────────────────────────────────────
    std::atomic<bool> operation_active_{false};
    std::atomic<bool> foreground_operation_active_{false};
    std::mutex mutex_;
    std::mutex open_mutex_;  // 序列化 OpenPersistentStream，防止并发重入（需求3）
    std::mutex session_mutex_;
    Camera*    camera_          = nullptr;
    bool       hardware_failed_ = false;
    static bool video_init_done_;  // 全局唯一，防止重复调用 esp_video_init

    // ── 常开 stream（启动后立即 open，永不 close）──────────────────────────────
    Esp32Camera* persistent_camera_ = nullptr;
    std::atomic<StreamState> stream_state_{StreamState::Idle};
    std::string session_id_;
    std::string explain_url_;
    std::string explain_token_;

    // Preview remains a public compatibility API, but the current firmware
    // intentionally rejects live preview and keeps no preview state.
};
