#pragma once
#include <cJSON.h>
#include <mutex>
#include <string>
#include <map>
#include <functional>
#include "person_turn.h"

// A server directory replaces local profiles. Never infer identity from a face.
class PersonDirectory {
public:
    static PersonDirectory& GetInstance();
    std::string Apply(const cJSON* state);
    bool Accepts(const PersonTurn& actor) const;
    bool Ready() const;
    bool AcceptsManagement(const std::string& account, uint64_t version,
                           const std::string& recipient) const;
    std::string WithManagement(const std::string& account, uint64_t version,
                              const std::string& recipient, const std::function<std::string()>& apply);
    void Invalidate();
private:
    struct Voice { std::string person; uint64_t version; };
    mutable std::mutex mutex_;
    std::string account_, mode_, default_id_;
    uint64_t version_ = 0, generation_ = 0;
    bool ready_ = false;
    std::map<std::string, Voice> voices_;
    std::map<std::string, std::string> members_;
};
