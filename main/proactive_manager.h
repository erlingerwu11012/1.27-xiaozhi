#pragma once

#include <string>
#include <vector>
#include <map>
#include <set>
#include <mutex>
#include <ctime>

class ProactiveManager {
public:
    static ProactiveManager& GetInstance() {
        static ProactiveManager instance;
        return instance;
    }

    struct BriefItem {
        std::string type;   // "alarm" / "habit" / "note"
        int id;
        std::string text;   // LLM prompt 描述文本
    };

    // 主人不在场时触发的提醒记录，供主人回来后补报
    struct MissedReminder {
        std::string owner;     // 归属用户
        std::string type;      // "alarm" / "habit" / "note"
        int         id;
        std::string text;      // 播报描述
        time_t      fired_at;  // 触发时间戳
    };

    // 将未送达提醒加入该用户的 missed 队列
    void AddMissedReminder(const std::string& owner, const std::string& type,
                           int id, const std::string& text);

    // 取出并清空指定用户的 missed 队列（用于欢迎回来补报）
    std::vector<MissedReminder> PopMissedReminders(const std::string& face_id);

    // 检查是否有 missed 提醒（不消费）
    bool HasMissedReminders(const std::string& face_id);

    // 人脸识别降级接口（当前始终返回 "default"，接入人脸后替换）
    std::string ResolveFaceId(const std::string& recognition_result);

    // 根据 away_duration 返回未送达事项列表
    std::vector<BriefItem> GetPendingItems(const std::string& face_id, int away_seconds);

    // 标记已送达（防重复播报）
    void MarkDelivered(const std::string& face_id, const std::string& key);
    bool IsDelivered(const std::string& face_id, const std::string& key);

    // 标记事项已完成（触摸/语音确认后调用）
    void MarkCompleted(const std::string& face_id, const std::string& key);

    // 更新/查询人最后出现时间（UpdateLastSeen 会自动持久化到 NVS）
    void UpdateLastSeen(const std::string& face_id, time_t t);
    time_t GetLastSeen(const std::string& face_id);

    // 凌晨 3 点清空当日状态（delivered_ 清空，last_seen_ 保留）
    void ClearDailyState();

    // 传感器兜底（无人脸识别时使用）
    void SetSensorAbsentSince(time_t t);
    time_t GetSensorAbsentSince() const;

private:
    ProactiveManager();

    void SaveLastSeen();
    void LoadLastSeen();

    std::map<std::string, time_t>                        last_seen_;
    std::map<std::string, std::set<std::string>>         delivered_;
    std::map<std::string, std::vector<MissedReminder>>   missed_reminders_;
    std::mutex mutex_;
    time_t sensor_absent_since_ = 0;
};
