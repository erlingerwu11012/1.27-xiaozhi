#ifndef AUDIO_READY_STATE_H
#define AUDIO_READY_STATE_H

/**
 * 语音子系统就绪状态机
 * 
 * 解决 VAD/ASR 未就绪阶段的音频丢失、竞态和日志刷屏问题。
 * 
 * 状态流转：
 *   INIT ──(EnableVoiceProcessing)──> WARMING ──(processor running + timeout)──> READY
 *                                        │                                         │
 *                                        └──(timeout expired)──> DEGRADED          │
 *                                                                    │             │
 *   <──────────(DisableVoiceProcessing / Reset)──────────────────────┴─────────────┘
 */

#include <atomic>
#include <mutex>
#include <deque>
#include <vector>
#include <chrono>
#include <cstdint>
#include <esp_log.h>

/* ── 可配置参数：优先使用 Kconfig (sdkconfig)，否则使用编译时 -D，最后用默认值 ── */
#ifdef CONFIG_AUDIO_READY_TIMEOUT_MS
#define AUDIO_READY_TIMEOUT_MS          CONFIG_AUDIO_READY_TIMEOUT_MS
#elif !defined(AUDIO_READY_TIMEOUT_MS)
#define AUDIO_READY_TIMEOUT_MS          3000    /* 等待就绪的最大时间 (ms) */
#endif

#ifdef CONFIG_AUDIO_PREBUFFER_FRAMES
#define AUDIO_PREBUFFER_FRAMES          CONFIG_AUDIO_PREBUFFER_FRAMES
#elif !defined(AUDIO_PREBUFFER_FRAMES)
#define AUDIO_PREBUFFER_FRAMES          50      /* 未就绪时最多缓冲帧数 */
#endif

#ifdef CONFIG_AUDIO_NOT_READY_LOG_INTERVAL_MS
#define AUDIO_NOT_READY_LOG_INTERVAL_MS CONFIG_AUDIO_NOT_READY_LOG_INTERVAL_MS
#elif !defined(AUDIO_NOT_READY_LOG_INTERVAL_MS)
#define AUDIO_NOT_READY_LOG_INTERVAL_MS 2000    /* "未就绪"日志最小间隔 (ms) */
#endif

/**
 * 语音子系统就绪状态
 */
enum class AudioReadyState : int {
    INIT     = 0,   // 初始/已停止
    WARMING  = 1,   // 正在初始化（AFE create_from_config / Start 中）
    READY    = 2,   // 就绪，可正常处理音频
    DEGRADED = 3,   // 超时降级：放弃缓冲，直通或丢弃
};

inline const char* AudioReadyStateToString(AudioReadyState s) {
    switch (s) {
        case AudioReadyState::INIT:     return "INIT";
        case AudioReadyState::WARMING:  return "WARMING";
        case AudioReadyState::READY:    return "READY";
        case AudioReadyState::DEGRADED: return "DEGRADED";
        default:                        return "UNKNOWN";
    }
}

/**
 * AudioReadyGate — 门控 + 缓冲 + 超时降级
 * 
 * 线程安全：内部使用 mutex 保护缓冲区，atomic 保护状态。
 * 使用方式：
 *   1. 进入 Listening 前调用 EnterWarming()
 *   2. AudioProcessor 确认 running 后调用 MarkReady()
 *   3. 音频帧入口调用 Gate(data) — 未就绪时缓冲，就绪后自动回放
 *   4. 退出 Listening / 重连时调用 Reset()
 */
class AudioReadyGate {
public:
    AudioReadyGate() = default;

    /* ── 状态转换 ── */

    /** 进入 WARMING 状态，开始计时 */
    void EnterWarming() {
        std::lock_guard<std::mutex> lock(buf_mutex_);
        state_.store(AudioReadyState::WARMING, std::memory_order_release);
        warming_start_ = std::chrono::steady_clock::now();
        prebuffer_.clear();
        not_ready_logged_ = false;
        degraded_logged_ = false;
        ready_logged_ = false;
        ESP_LOGI("AudioReadyGate", "State -> WARMING");
    }

    /** 标记为 READY，触发缓冲回放 */
    void MarkReady() {
        auto prev = state_.load(std::memory_order_acquire);
        if (prev == AudioReadyState::READY) return;
        state_.store(AudioReadyState::READY, std::memory_order_release);
        if (!ready_logged_) {
            ready_logged_ = true;
            ESP_LOGI("AudioReadyGate", "State -> READY (buffered %u frames)", (unsigned)GetBufferedCount());
        }
    }

    /** 重置到 INIT（退出 Listening / 重连 / 停止时调用） */
    void Reset() {
        std::lock_guard<std::mutex> lock(buf_mutex_);
        auto prev = state_.load(std::memory_order_acquire);
        state_.store(AudioReadyState::INIT, std::memory_order_release);
        size_t dropped = prebuffer_.size();
        prebuffer_.clear();
        if (prev != AudioReadyState::INIT && dropped > 0) {
            ESP_LOGW("AudioReadyGate", "Reset from %s, dropped %u buffered frames",
                     AudioReadyStateToString(prev), (unsigned)dropped);
        }
    }

    /* ── 查询 ── */

    AudioReadyState GetState() const {
        return state_.load(std::memory_order_acquire);
    }

    bool IsReady() const {
        auto s = GetState();
        return s == AudioReadyState::READY || s == AudioReadyState::DEGRADED;
    }

    /* ── 门控入口 ── */

    /**
     * 对一帧音频做门控判断。
     * 
     * @param data  输入音频帧（PCM samples）
     * @param out   输出：需要实际处理的帧列表（可能包含回放的缓冲帧 + 当前帧）
     * @return true  = out 中有数据需要处理
     *         false = 帧被缓冲或丢弃，调用者无需处理
     */
    bool Gate(std::vector<int16_t>& data, std::deque<std::vector<int16_t>>& out) {
        auto s = state_.load(std::memory_order_acquire);

        switch (s) {
        case AudioReadyState::INIT:
            // 不在语音处理模式，不应该收到帧，静默丢弃
            return false;

        case AudioReadyState::WARMING: {
            // 检查是否超时
            auto now = std::chrono::steady_clock::now();
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - warming_start_).count();
            
            if (elapsed >= AUDIO_READY_TIMEOUT_MS) {
                // 超时降级
                state_.store(AudioReadyState::DEGRADED, std::memory_order_release);
                if (!degraded_logged_) {
                    degraded_logged_ = true;
                    std::lock_guard<std::mutex> lock(buf_mutex_);
                    ESP_LOGW("AudioReadyGate", "State -> DEGRADED after %lld ms, discarding %u buffered frames",
                             (long long)elapsed, (unsigned)prebuffer_.size());
                    prebuffer_.clear();
                }
                // 降级后直通当前帧
                out.clear();
                out.push_back(std::move(data));
                return true;
            }

            // 缓冲当前帧
            {
                std::lock_guard<std::mutex> lock(buf_mutex_);
                if (prebuffer_.size() < AUDIO_PREBUFFER_FRAMES) {
                    prebuffer_.push_back(data);  // copy, 因为 data 可能还被调用者使用
                } else {
                    // 缓冲满，丢弃最旧帧
                    prebuffer_.pop_front();
                    prebuffer_.push_back(data);
                }
            }

            // 限频日志
            LogNotReady(now);
            return false;
        }

        case AudioReadyState::READY: {
            out.clear();
            // 先回放缓冲帧
            {
                std::lock_guard<std::mutex> lock(buf_mutex_);
                while (!prebuffer_.empty()) {
                    out.push_back(std::move(prebuffer_.front()));
                    prebuffer_.pop_front();
                }
            }
            // 再加入当前帧
            out.push_back(std::move(data));
            return true;
        }

        case AudioReadyState::DEGRADED:
            // 降级模式：直通
            out.clear();
            out.push_back(std::move(data));
            return true;

        default:
            return false;
        }
    }

    size_t GetBufferedCount() const {
        // 注意：不加锁的近似值，仅用于日志
        return prebuffer_.size();
    }

private:
    std::atomic<AudioReadyState> state_{AudioReadyState::INIT};
    std::mutex buf_mutex_;
    std::deque<std::vector<int16_t>> prebuffer_;

    std::chrono::steady_clock::time_point warming_start_;

    // 限频日志控制
    bool not_ready_logged_ = false;
    bool degraded_logged_ = false;
    bool ready_logged_ = false;
    std::chrono::steady_clock::time_point last_not_ready_log_;

    void LogNotReady(std::chrono::steady_clock::time_point now) {
        if (!not_ready_logged_) {
            not_ready_logged_ = true;
            last_not_ready_log_ = now;
            ESP_LOGW("AudioReadyGate", "Audio subsystem not ready, buffering frames...");
            return;
        }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - last_not_ready_log_).count();
        if (elapsed >= AUDIO_NOT_READY_LOG_INTERVAL_MS) {
            last_not_ready_log_ = now;
            ESP_LOGW("AudioReadyGate", "Still not ready, %u frames buffered", (unsigned)GetBufferedCount());
        }
    }
};

#endif // AUDIO_READY_STATE_H
