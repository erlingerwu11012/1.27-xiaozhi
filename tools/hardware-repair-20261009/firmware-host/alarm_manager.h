#pragma once

#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <map>
#include <cstdint>

struct Alarm {
    int    id;
    int    hour;
    int    minute;
    std::string label;
    bool   enabled;
    // 重复规则：位掩码，bit0=周日, bit1=周一, ..., bit6=周六
    // 0x7F(127)=每天, 0x00=仅响一次（响完自动禁用）
    uint8_t repeat_days;
    std::string owner_user_id;  // creator / 管理归属："default"=公共
    std::string creator_person_id;
    std::string recipient_person_id;
    std::string recipient_display_name_snapshot;
    bool delivery_unbound = false;
    int last_triggered_day = 0;
    int64_t last_triggered_at = 0;
};

class AlarmManager {
public:
    static AlarmManager& GetInstance() {
        static AlarmManager instance;
        return instance;
    }

    // 添加闹钟，返回分配的 id，失败返回 -1（已满）
    // repeat_days: 位掩码 bit0=周日..bit6=周六, 0x7F=每天, 0=仅一次
    int  Add(int hour, int minute, const std::string& label, uint8_t repeat_days = 0x7F);
    int  Add(int hour, int minute, const std::string& label, uint8_t repeat_days,
             const std::string& owner,
             const std::string& recipient_person_id = "",
             const std::string& recipient_display_name = "");
    // 删除指定 id，返回是否成功
    bool Delete(int id);
    bool RetirePerson(const std::string& person, bool legacy = false);
    // 获取所有闹钟（用于 MCP list 工具）
    std::vector<std::string> GetListLines();
    // 获取所有闹钟原始数据（用于 UI 列表）
    std::vector<Alarm> GetAll();
    // 获取指定用户可见的闹钟（owner_user_id 的私有 + "default" 公共）
    std::vector<Alarm> GetAll(const std::string& owner_user_id);

    // 每秒调用一次，检查是否有闹钟到点
    // wday: 当前星期几（0=周日, 1=周一, ..., 6=周六，与 tm_wday 一致）
    // 到点时调用 on_fire(alarm)
    void CheckAndFire(int hour, int minute, int wday, int day_key,
                      std::function<void(const Alarm&)> on_fire);

    // 旧调用兼容：操作 Manager 的单一运行时贪睡槽。
    // ReminderCoordinator 的单件动作不得调用这两个全局接口。
    void Snooze(int delay_minutes = 5);

    // 旧调用兼容：只清除上述运行时贪睡槽，不代表关闭某个提醒实例。
    void DismissCurrent();

    static constexpr int kMaxAlarms = 8;

private:
    AlarmManager();
    void Load();
    bool Save();

    std::vector<Alarm> alarms_;
    std::mutex mutex_;
    int next_id_ = 1;
    int last_fired_minute_ = -1; // 仅保留给旧贪睡路径
    std::map<int, int> last_fired_day_by_id_;

    // 贪睡状态（运行时，不持久化）
    int snooze_target_minute_ = -1;  // 贪睡目标时间（hour*60+minute），-1=无贪睡
    Alarm snoozed_alarm_{};          // 贪睡中的闹钟副本
};
