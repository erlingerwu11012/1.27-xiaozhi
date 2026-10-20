#pragma once

#include <string>
#include <vector>
#include <mutex>

struct UserIdentity {
    std::string user_id;
    std::string display_name;
    // Legacy primary bindings are retained for stored configurations and for
    // older services.  New profiles may bind multiple face and voice templates
    // to the same stable user_id.
    std::string face_id;
    std::string voice_id;
    std::vector<std::string> face_ids;
    std::vector<std::string> voice_ids;
    bool enabled = true;
};

// A server-authoritative link between the face-api profile ID (usr_*) and the
// product-level user ID.  It is refreshed from MCP initialize and deliberately
// not persisted: an old device cache must never outlive a server-side unbind.
struct FaceIdentityBinding {
    std::string face_profile_id;
    std::string user_id;
    std::string display_name;
};

class IdentityManager {
public:
    static IdentityManager& GetInstance() {
        static IdentityManager instance;
        return instance;
    }

    bool AddUser(const UserIdentity& user);
    bool ReplaceFromServer(const std::vector<UserIdentity>& users);
    bool RemoveUser(const std::string& user_id);
    bool UpdateUser(const UserIdentity& user);

    // Results are copies so callers never retain a pointer into the protected
    // profile vector after the mutex is released.
    bool FindByUserId(const std::string& user_id, UserIdentity* out) const;
    bool FindByFaceId(const std::string& face_id, UserIdentity* out) const;
    bool FindByVoiceId(const std::string& voice_id, UserIdentity* out) const;

    // Replaces the volatile mapping delivered by the server for the active
    // connection.  It must not be saved to NVS because binding ownership is
    // managed by the account-scoped server profile.
    void ApplyFaceIdentityBindings(std::vector<FaceIdentityBinding> bindings);
    bool ResolveFaceIdentity(const std::string& face_profile_id,
                             FaceIdentityBinding* out) const;

    std::vector<UserIdentity> GetAll();

    static constexpr int kMaxUsers = 64;
    static constexpr int kMaxFaceIdentityBindings = 32;

private:
    IdentityManager();
    void Load();
    bool Save();

    std::vector<UserIdentity> users_;
    std::vector<FaceIdentityBinding> face_identity_bindings_;
    mutable std::mutex mutex_;
};
