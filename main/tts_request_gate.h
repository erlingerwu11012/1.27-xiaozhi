#pragma once
#include <mutex>
#include <string>
#include <deque>

// Control frames carry an optional owner. Old servers remain compatible.
class TtsRequestGate {
public:
    bool Start(const std::string& owner) {
        std::lock_guard<std::mutex> lock(mutex_);
        if (owner.empty()) { current_.clear(); return true; }
        if (owner == current_) return false;
        for (const auto& old : retired_) if (old == owner) return false;
        if (!current_.empty()) {
            retired_.push_back(current_);
            if (retired_.size() > 32) retired_.pop_front();
        }
        current_ = owner;
        return true;
    }
    bool Matches(const std::string& owner) {
        std::lock_guard<std::mutex> lock(mutex_);
        return owner.empty() || owner == current_;
    }
    void Reset() {
        std::lock_guard<std::mutex> lock(mutex_);
        current_.clear(); retired_.clear();
    }
private:
    std::mutex mutex_;
    std::string current_;
    std::deque<std::string> retired_;
};
