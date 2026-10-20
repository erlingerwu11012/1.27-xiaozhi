#pragma once
#include <string>
#include <vector>
#include <functional>
#include <mutex>
#include <map>
#include <ctime>
#include <cJSON.h>

struct Habit {
    int         id;
    int         hour;
    int         minute;
    int         advance_minutes;    // 提前几分钟提醒（默认2）
    std::string intent;             // 意图标签（英文，用于去重）
    std::string description;        // 中文描述（用于播报）
    int         confidence;         // 置信度（确认+1，拒绝-1，初始为1）
    int         consecutive_reject; // 连续拒绝次数（>=3 时自动禁用）
    int         total_fires;        // 总触发次数（用于卡片显示）
    bool        enabled;
    std::string source;             // 来源："auto"（被动提取）/ "manual"（用户手动设定）
    std::string owner_user_id;      // creator / 管理归属："default"=公共
    std::string creator_person_id;
    std::string recipient_person_id;
    std::string recipient_display_name_snapshot;
    bool delivery_unbound = false;
    int repeat_days = 127;
    std::string timezone = "Asia/Shanghai";
    time_t last_occurrence = 0;
    time_t occurrence_at = 0; // copy passed to delivery; not the rule's next date
    std::string sync_id, sync_account, content_hash;
};

class HabitManager {
public:
    static HabitManager& GetInstance() {
        static HabitManager instance;
        return instance;
    }

    // 添加习惯规则，返回分配的 id，失败返回 -1（已满）
    int  Add(int hour, int minute, int advance_minutes,
             const std::string& intent, const std::string& description,
             const std::string& source = "auto");
    int  Add(int hour, int minute, int advance_minutes,
             const std::string& intent, const std::string& description,
             const std::string& source, const std::string& owner,
             const std::string& recipient_person_id = "",
             const std::string& recipient_display_name = "", int repeat_days = 127);
    bool Delete(int id);
    // Private management protocol. Identity validation is performed by caller.
    std::string Sync(const cJSON* params);
    bool RetirePerson(const std::string& person, bool legacy = false);

    // 用户拒绝的结果枚举
    enum class RejectResult {
        kNotFound,       // id 不存在
        kStorageError,
        kRejected,       // 正常拒绝，记录在案
        kAutoDisabled,   // 连续拒绝3次，已自动禁用
        kAutoDeleted,    // 置信度耗尽，已自动删除
    };

    // 用户确认：confidence+1，consecutive_reject 归零，total_fires+1
    bool Confirm(int id);

    // 用户跳过：confidence-1（不低于0），consecutive_reject+1。
    // 自动学习的习惯连续3次跳过后暂停；手动习惯永不自动暂停/删除。
    RejectResult Reject(int id);

    std::vector<Habit> GetAll();
    // 获取指定用户可见的习惯（owner_user_id 的私有 + "default" 公共）
    std::vector<Habit> GetAll(const std::string& owner_user_id);
    std::vector<std::string> GetListLines();

    // 每分钟调用一次，检查是否有习惯到点（提前 advance_minutes 分钟触发）
    void CheckAndFire(int hour, int minute, int day_key,
                      std::function<bool(const Habit&)> on_fire, time_t now = 0);

    static constexpr int kMaxHabits = 20;

private:
    HabitManager();
    void Load();
    bool Save(int* storage_error = nullptr);
    void DeleteById(int id); // 内部无锁删除

    std::vector<Habit> habits_;
    std::mutex mutex_;
    int next_id_ = 1;
    std::map<int, int> last_fired_day_by_id_;
};
