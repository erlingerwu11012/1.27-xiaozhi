#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <cstdint>
#include "person_turn.h"

// 单条时间段摘要，供 Summarize() 返回
struct HourSummary {
    int hour;
    int days_active;
    int total_count;
    // 每天最长的3条原话，外层 index = 天（0~6），内层 = 最多3条
    std::vector<std::vector<std::string>> samples;
};

class BehaviorLogger {
public:
    static BehaviorLogger& GetInstance() {
        static BehaviorLogger instance;
        return instance;
    }

    // 挂载 userdata SPIFFS 分区，在 Board 构造函数早期调用
    static bool Init();

    // 记录一条行为日志（JSON Lines 格式追加写入 SPIFFS）
    bool Log(const std::string& intent, const std::string& raw,
             int hour, int minute, const std::string& outcome = "conversation", std::string* record = nullptr);

    // 读取全部日志内容（供调试）
    std::string ReadAll();
    // Private server RPC; bounded page, never exposed to the language model.
    std::string Export(const std::string& person, uint64_t after, size_t limit = 10);

    // 删除超过 kRetentionDays 天的记录（每天凌晨调用一次）
    void Prune();

    // 本地时间聚类+取样聚合，返回规律时间段摘要
    // 规律判定：7天里至少 kMinActiveDays 天有记录 且 总次数 > kMinTotalCount
    // 每个时间段每天取最长的 kSamplesPerDay 条原话
    std::vector<HourSummary> Summarize(const std::string& person = "",
                                      uint64_t* watermark = nullptr);
    bool Acknowledge(const std::string& person, uint64_t watermark);
    bool RetirePerson(const std::string& person);

    static constexpr int kRetentionDays  = 30;
    static constexpr int kMinActiveDays  = 5;   // 至少5天有记录才算规律
    static constexpr int kMinTotalCount  = 10;  // 至少10条才算规律
    static constexpr int kSamplesPerDay  = 3;   // 每天取最长的3条
    static constexpr int kAnalysisDays   = 7;   // 分析最近7天
    // 文件大小上限：24KB。userdata 还需容纳两条语音缓存以及提醒状态
    // 原子写入时的新旧两份文件，剩余空间保留给 SPIFFS 元数据和碎片整理。
    // 超过后立即触发分析+清理，而不是静默丢弃
    static constexpr size_t kMaxLogSize  = 24 * 1024;

#ifdef PERSON_MEMORY_HOST_TEST
    static constexpr const char* kLogPath        = "./logs/behavior.jsonl";
    static constexpr const char* kLogDir         = "./logs";
    static constexpr const char* kMountPoint     = ".";
#else
    static constexpr const char* kLogPath        = "/userdata/logs/behavior.jsonl";
    static constexpr const char* kLogDir         = "/userdata/logs";
    static constexpr const char* kMountPoint     = "/userdata";
#endif
    static constexpr const char* kPartitionLabel = "userdata";

    // 清空日志文件（分析完成后调用，开始新一轮积累）
    void ClearLog();
    // 检查文件大小是否超限（超限时返回 true，调用方应触发分析+清理）
    bool IsLogFull() const;

private:
    BehaviorLogger() = default;
    mutable std::mutex mutex_;
};
