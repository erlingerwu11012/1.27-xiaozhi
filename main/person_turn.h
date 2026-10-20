#pragma once
#include <cstdint>
#include <string>
#include <algorithm>

struct PersonTurn {
    std::string account_id;
    std::string voiceprint_id;
    uint64_t template_version = 0;
    std::string person_id;
    std::string turn_id;
    std::string status;
    std::string display_name;
    uint64_t directory_version = 0;
    uint64_t generation = 0;
    uint64_t listen_epoch = 0;
    bool Eligible() const {
        return !person_id.empty() && !turn_id.empty() &&
            (status == "matched" || status == "default");
    }
};

// A tool runs with the actor of its original audio, even if another person has
// started speaking. The transport, rather than model arguments, supplies it.
inline thread_local const PersonTurn* bound_person_turn = nullptr;
class PersonTurnScope {
public:
    explicit PersonTurnScope(const PersonTurn& actor)
        : previous_(bound_person_turn) { bound_person_turn = &actor; }
    ~PersonTurnScope() { bound_person_turn = previous_; }
    PersonTurnScope(const PersonTurnScope&) = delete;
private:
    const PersonTurn* previous_;
};

inline std::string Utf8Prefix(const std::string& text, size_t bytes) {
    if (text.size() <= bytes) return text;
    size_t end = bytes;
    while (end && (static_cast<unsigned char>(text[end]) & 0xc0) == 0x80) --end;
    return text.substr(0, end);
}

inline bool IsPersonId(const std::string& value) {
    return !value.empty() && value.size() <= 64 && value != "all" &&
        value != "default" && value != "guest" &&
        std::all_of(value.begin(), value.end(), [](unsigned char c) {
            return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
                (c >= '0' && c <= '9') || c == '_' || c == '-';
        });
}
