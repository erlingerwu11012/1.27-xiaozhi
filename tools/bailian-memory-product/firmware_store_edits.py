"""Apply the product's durable cleanup API to existing firmware managers."""
from pathlib import Path

root = Path(__file__).resolve().parents[2]
if 'bool HabitManager::RetirePerson' in (root/'main/habit_manager.cc').read_text(encoding='utf-8'):
    raise SystemExit('Firmware store edits already applied; refusing to apply twice.')
for name, collection, namespace in [("habit", "habits_", "habits"), ("note", "notes_", "notes"), ("alarm", "alarms_", "alarms")]:
    path = root / f"main/{name}_manager.cc"
    header = root / f"main/{name}_manager.h"
    cls = name.title() + "Manager"
    text = path.read_text(encoding="utf-8")
    text = text.replace(f"void {cls}::Save() {{", f"bool {cls}::Save() {{")
    start = text.index(f"bool {cls}::Save() {{")
    prefix, body = text[:start], text[start:]
    body = body.replace("if (!str) return;", "if (!str) return false;")
    body = body.replace('s.SetString("list", str);', 'bool okay = s.SetString("list", str) == ESP_OK;')
    body = body.replace('s.SetInt("next_id", next_id_);', 'okay = s.SetInt("next_id", next_id_) == ESP_OK && okay;')
    body = body.replace("free(str);\n}", "free(str);\n    return s.Commit() == ESP_OK && okay;\n}", 1)
    text = prefix + body
    retire = f'''
bool {cls}::RetirePerson(const std::string& person, bool legacy) {{
    std::lock_guard<std::mutex> lock(mutex_);
    const auto before = {collection};
    {collection}.erase(std::remove_if({collection}.begin(), {collection}.end(), [&](const auto& value) {{
        return value.owner_user_id == person || value.creator_person_id == person ||
            value.recipient_person_id == person || (legacy &&
            (value.owner_user_id.empty() || value.owner_user_id == "default"));
    }}), {collection}.end());
    if (!Save()) {{ {collection} = before; return false; }}
'''
    if name == "alarm":
        retire += '''    if (snoozed_alarm_.owner_user_id == person || (legacy && snoozed_alarm_.owner_user_id == "default")) snooze_target_minute_ = -1;
'''
    retire += "    return true;\n}\n"
    if f"{cls}::RetirePerson" not in text:
        text += retire
    if name == "alarm":
        if '#include "person_turn.h"' not in text:
            text = '#include "person_turn.h"\n' + text
        text = text.replace('return id.size() > 4 && id.compare(0, 4, "usr_") == 0;', 'return IsPersonId(id);')
        text = text.replace('a.owner_user_id == "default" || a.owner_user_id == owner ||', 'a.owner_user_id == owner ||')
    path.write_text(text, encoding="utf-8", newline="\n")
    text = header.read_text(encoding="utf-8").replace("void Save();", "bool Save();")
    if "RetirePerson" not in text:
        text = text.replace("bool Delete(int id);", "bool Delete(int id);\n    bool RetirePerson(const std::string& person, bool legacy = false);")
        # Alarm has an extra space between type and method.
        if "RetirePerson" not in text:
            text = text.replace("bool Delete(int id)", "bool RetirePerson(const std::string& person, bool legacy = false);\n    bool Delete(int id)")
    header.write_text(text, encoding="utf-8", newline="\n")

path = root / "main/identity_manager.h"
text = path.read_text(encoding="utf-8").replace("void Save();", "bool Save();")
text = text.replace("bool AddUser(const UserIdentity& user);", "bool AddUser(const UserIdentity& user);\n    bool ReplaceFromServer(const std::vector<UserIdentity>& users);")
path.write_text(text, encoding="utf-8", newline="\n")
path = root / "main/identity_manager.cc"
text = path.read_text(encoding="utf-8").replace("void IdentityManager::Save() {", "bool IdentityManager::Save() {")
text = text.replace("if (!str) return;\n    Settings s(\"identity\", true);", "if (!str) return false;\n    Settings s(\"identity\", true);")
text = text.replace('s.SetString("users", str);\n    free(str);', 'bool okay = s.SetString("users", str) == ESP_OK;\n    free(str);\n    if (s.Commit() != ESP_OK || !okay) return false;')
text = text.replace('ESP_LOGI(TAG, "Save: %zu users", users_.size());', 'ESP_LOGI(TAG, "Save: %zu users", users_.size());\n    return true;')
text += '''
bool IdentityManager::ReplaceFromServer(const std::vector<UserIdentity>& users) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (users.size() > kMaxUsers) return false;
    auto before = users_; users_ = users;
    if (!Save()) { users_ = before; return false; }
    face_identity_bindings_.erase(std::remove_if(face_identity_bindings_.begin(), face_identity_bindings_.end(), [&](const auto& binding) {
        return std::none_of(users_.begin(), users_.end(), [&](const auto& user) { return user.user_id == binding.user_id; });
    }), face_identity_bindings_.end());
    return true;
}
'''
path.write_text(text, encoding="utf-8", newline="\n")
