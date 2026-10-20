#pragma once
#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <cstdint>

struct Note {
    int         id;
    uint32_t    ts;           // 创建时间戳（Unix 秒），无 RTC 时为 0
    uint32_t    remind_at;    // 提醒时间戳（0 = 不提醒，视为待办）
    bool        fired;        // 是否已触发提醒
    int         snooze_count; // 已贪睡次数（最多 kMaxSnooze 次）
    std::string text;         // 最长 96 字节（约 32 个中文字）
    // owner_user_id = creator / management ownership ("default"=公共)
    std::string owner_user_id;
    std::string creator_person_id;
    std::string recipient_person_id;
    std::string recipient_display_name_snapshot;
    bool delivery_unbound = false;
    std::string priority;      // "normal" / "high"
    std::string attention_policy; // "general" / "pickup" / "medication"
    int pre_alert_minutes;
    int repeat_days = 0;
    int repeat_hour = 0;
    int repeat_minute = 0;
    std::string timezone = "Asia/Shanghai";
    uint32_t last_occurrence = 0;
};

class NoteManager {
public:
    static NoteManager& GetInstance() {
        static NoteManager instance;
        return instance;
    }

    // 添加备忘录，返回 id；失败返回 -1，可通过 error_code 区分上限与存储失败。
    // remind_at = 0 表示不设提醒（视为待办事项）
    int  Add(const std::string& text, uint32_t remind_at = 0);
    int  Add(const std::string& text, uint32_t remind_at,
             const std::string& owner,
             const std::string& priority = "normal",
             const std::string& attention_policy = "general",
             int pre_alert_minutes = 0,
             const std::string& recipient_person_id = "",
             const std::string& recipient_display_name = "", int repeat_days = 0,
             std::string* error_code = nullptr);
    bool Delete(int id);
    bool RetirePerson(const std::string& person, bool legacy = false);
    bool CompleteOccurrence(int id);

    // 贪睡：将 remind_at 推后 delay_sec 秒，fired 重置为 false
    // 超过 kMaxSnooze 次后返回 false
    bool Snooze(int id, int delay_sec);

    std::vector<Note> GetAll();
    // 获取指定用户可管理的备忘录（creator / owner 匹配 + default 公共）
    std::vector<Note> GetAll(const std::string& owner_user_id);
    std::vector<std::string> GetListLines();

    // 检查是否有到期提醒，对每条到期的 Note 调用 on_remind
    // 只有回调确认提醒实例已持久化后，才将 fired 置为 true 并保存
    void CheckAndRemind(uint32_t now_ts,
                        std::function<bool(const Note&)> on_remind);

    // 凌晨 3 点自动清理过期备忘录：
    //   - 有提醒时间且已触发（fired=true）超过 24 小时 → 删除
    //   - 无提醒时间（待办）超过 7 天未完成 → 删除
    void PruneExpired(uint32_t now_ts);

    static constexpr int      kMaxNotes      = 20;
    static constexpr int      kMaxSnooze     = 3;
    static constexpr int      kMaxTextBytes  = 96;
    static constexpr uint32_t kFiredExpirySec = 24 * 3600;       // 已触发 24h 后删除
    static constexpr uint32_t kTodoExpirySec  = 7 * 24 * 3600;   // 待办 7天 后删除

private:
    NoteManager();
    void Load();
    bool Save(int* storage_error = nullptr);
    static void MigrateIdentityFields(Note& n);

    std::vector<Note> notes_;
    std::mutex mutex_;
    int next_id_ = 1;
};
