#pragma once

#include <cstdint>
#include <string>

// Device-side connection recovery.  The decision functions are host-testable.
//
// Deployed OTA responses use auth.schema, auth.status, auth.retry_after_ms and,
// when known, auth.credential_version.  Pairing and recovery sessions arrive in
// auth.pairing: session_id, display_code, purpose, expires_at, secret_required,
// accepted.  Epochs below are device-local write generations.  The server's
// credential_version is stored as delivered and is never hardcoded.

namespace authconn {

enum class AuthStatus : int {
    kAbsent = 0,
    kOk,
    kPairingRequired,
    kRecoveryRequired,
    kDisabled,
    kRateLimited,
    kTemporaryError,
    kIncomplete,
    kPersistFailed,
    kStale,
    kUnrecognized,
};

enum class AuthAction : int {
    kConnect = 0,
    kWaitPairing,
    kWaitRecovery,
    kShowDisabled,
    kQuietBackoff,
    kRetryTransport,
    kRetryIncomplete,
    kRetryPersist,
    kRefreshToken,
};

enum class HeaderKind : int {
    kNone = 0,
    kDeviceKey,
    kRedeemCode,
    kPairingSecret,
    kConfirm,
};

struct HeaderChoice {
    HeaderKind kind = HeaderKind::kNone;
    std::string secret;
    std::string device_key;
    std::string pairing_secret;
    std::string activation_code;
    std::string session_id;
    bool confirm = false;
    uint32_t credential_epoch = 0;
};

struct HttpObservation {
    bool body_parsed = false;
    bool envelope_present = false;
    int schema = 0;
    AuthStatus envelope_status = AuthStatus::kAbsent;
    int retry_after_ms = 0;
    bool has_user_code = false;
    bool has_redeem = false;
    bool has_ws_url = false;
    bool has_ws_token = false;
    bool has_auth_key = false;
    bool secret_required = false;
    bool secret_required_known = false;
    bool accepted = false;
    bool accepted_known = false;
    bool has_session_id = false;
    bool has_expires = false;
    bool credential_version_present = false;
    bool confirm_sent = false;
    int64_t credential_version = 0;
    int64_t expires_at_ms = 0;
    std::string session_id;
    std::string purpose;
    uint32_t request_gen = 0;
};

struct HttpPayload {
    std::string url;
    std::string token;
    std::string auth_key;
    int version = 1;
    std::string redeem;
    std::string user_code;
    std::string pairing_secret;
    bool credential_version_present = false;
    int64_t credential_version = 0;
};

struct LegacyCredential {
    std::string url;
    std::string token;
    std::string auth_key;
    int version = 1;
};

struct Outcome {
    AuthStatus status = AuthStatus::kAbsent;
    AuthAction action = AuthAction::kRetryIncomplete;
    int retry_after_ms = 0;
    bool ready_for_connection = false;
    bool mutated = false;
};

struct ConnectableCredential {
    bool present = false;
    uint32_t epoch = 0;
    std::string url;
    std::string token;
    std::string auth_key;
    int version = 1;
    std::string credential_version;
};

class AuthKv {
public:
    virtual ~AuthKv() = default;
    virtual bool GetString(const char* key, std::string* out) const = 0;
    virtual bool GetInt(const char* key, int32_t* out) const = 0;
    virtual bool SetString(const char* key, const std::string& value) = 0;
    virtual bool SetInt(const char* key, int32_t value) = 0;
    virtual bool Erase(const char* key) = 0;
    virtual bool Commit() = 0;
};

bool IsOpaqueDeviceCredential(const std::string& value, size_t min_length = 40);
bool IsHighEntropySecret(const std::string& value);
bool IsWebsocketAccessToken(const std::string& value);
AuthStatus ParseAuthStatus(const char* status);
bool ParseOtaAuthJson(const char* json, HttpObservation* observation, HttpPayload* payload);

const char* StatusName(AuthStatus status);
const char* ActionName(AuthAction action);

Outcome ApplyHttpResponse(AuthKv& kv, const HttpObservation& obs, const HttpPayload& payload,
                          const LegacyCredential* legacy);
Outcome ApplyTerminalAuth(AuthKv& kv, const char* code, uint32_t credential_epoch);
Outcome NoteTokenExpired(AuthKv& kv, uint32_t credential_epoch);
HeaderChoice SelectHeader(AuthKv& kv, const LegacyCredential* legacy);
ConnectableCredential LoadConnectable(AuthKv& kv);
uint32_t CurrentEpoch(AuthKv& kv);
bool RefreshRequested(AuthKv& kv);
bool ClearRefreshRequest(AuthKv& kv);
bool MayRestoreUnscopedCache(AuthKv& kv);
bool HasCommittedSession(AuthKv& kv);
bool ConfirmPending(AuthKv& kv);
AuthAction CurrentAction(AuthKv& kv);
std::string SessionDisplayCode(AuthKv& kv);
std::string StoredCredentialVersion(AuthKv& kv);
uint32_t NextRequestGen(AuthKv& kv);

#ifndef AUTH_CONNECTION_HOST
HeaderChoice SelectPersistedHeader();
Outcome ApplyPersistedHttp(const HttpObservation& obs, const HttpPayload& payload);
Outcome ApplyPersistedTerminal(const char* code, uint32_t credential_epoch);
Outcome NotePersistedTokenExpired(uint32_t credential_epoch);
ConnectableCredential LoadPersistedConnectable();
uint32_t CurrentPersistedEpoch();
bool PersistedRefreshRequested();
bool ClearPersistedRefreshRequest();
bool MayRestorePersistedCache();
bool HasPersistedPairingSession();
bool PersistedConfirmPending();
AuthAction CurrentPersistedAction();
std::string PersistedDisplayCode();
uint32_t NextPersistedRequestGen();
bool MirrorPersistedCredential(const ConnectableCredential& credential);
bool EraseMirroredCredential();
#endif

}  // namespace authconn
