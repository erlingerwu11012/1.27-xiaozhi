#include "auth_connection.h"

#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstring>

#include "cJSON.h"

namespace authconn {
namespace {

constexpr int32_t kSlotEmpty = 0;
constexpr int32_t kSlotPending = 1;
constexpr int32_t kSlotCommitted = 2;
constexpr int32_t kSlotRevoked = 3;

constexpr int32_t kPhaseNone = 0;
constexpr int32_t kPhasePairing = 1;
constexpr int32_t kPhaseRecovery = 2;
constexpr int32_t kPhaseDisabled = 3;

constexpr int32_t kSessionNone = 0;
constexpr int32_t kSessionPending = 1;
constexpr int32_t kSessionCommitted = 2;

int32_t IntOf(const AuthKv& kv, const char* key) {
    int32_t value = 0;
    kv.GetInt(key, &value);
    return value;
}

std::string StrOf(const AuthKv& kv, const char* key) {
    std::string value;
    if (!kv.GetString(key, &value)) {
        return {};
    }
    return value;
}

bool ValidUrl(const std::string& url) {
    return url.size() > 6 && url.size() <= 256 &&
           (url.rfind("wss://", 0) == 0 || url.rfind("WSS://", 0) == 0);
}

bool ValidToken(const std::string& token) {
    if (token.empty() || token.size() > 512) {
        return false;
    }
    for (unsigned char ch : token) {
        if (ch <= 0x20 || ch == 0x7f) {
            return false;
        }
    }
    return true;
}

bool ValidUserCode(const std::string& code) {
    if (code.size() != 6) {
        return false;
    }
    for (unsigned char ch : code) {
        if (ch < '0' || ch > '9') {
            return false;
        }
    }
    return true;
}

const char* SlotKey(int slot, const char* suffix, char* buf, size_t buflen) {
    std::snprintf(buf, buflen, "%c_%s", slot == 1 ? 'a' : 'b', suffix);
    return buf;
}

struct SlotView {
    int index = 0;
    int32_t state = kSlotEmpty;
    int32_t epoch = 0;
    std::string url;
    std::string token;
    std::string auth_key;
    int32_t version = 1;
    std::string credential_version;
};

SlotView ReadSlot(const AuthKv& kv, int index) {
    char key[8];
    SlotView slot;
    slot.index = index;
    slot.state = IntOf(kv, SlotKey(index, "st", key, sizeof(key)));
    slot.epoch = IntOf(kv, SlotKey(index, "ep", key, sizeof(key)));
    slot.url = StrOf(kv, SlotKey(index, "url", key, sizeof(key)));
    slot.token = StrOf(kv, SlotKey(index, "tok", key, sizeof(key)));
    slot.auth_key = StrOf(kv, SlotKey(index, "key", key, sizeof(key)));
    slot.credential_version = StrOf(kv, SlotKey(index, "cv", key, sizeof(key)));
    slot.version = IntOf(kv, SlotKey(index, "ver", key, sizeof(key)));
    if (slot.version <= 0) {
        slot.version = 1;
    }
    return slot;
}

int32_t RevokedEpoch(const AuthKv& kv) { return IntOf(kv, "revoked"); }
int32_t HoldEpoch(const AuthKv& kv) { return IntOf(kv, "hold"); }
int32_t Phase(const AuthKv& kv) { return IntOf(kv, "phase"); }
int32_t AppliedGen(const AuthKv& kv) { return IntOf(kv, "applied"); }

bool SlotUsable(const SlotView& slot, int32_t revoked) {
    return slot.state == kSlotCommitted && slot.epoch > 0 && slot.epoch > revoked &&
           IsOpaqueDeviceCredential(slot.auth_key);
}

SlotView HighestUsable(const AuthKv& kv) {
    const int32_t revoked = RevokedEpoch(kv);
    SlotView best;
    for (int index = 1; index <= 2; ++index) {
        SlotView slot = ReadSlot(kv, index);
        if (!SlotUsable(slot, revoked)) {
            continue;
        }
        if (best.index == 0 || slot.epoch > best.epoch) {
            best = std::move(slot);
        }
    }
    return best;
}

bool SessionCommitted(const AuthKv& kv) {
    return IntOf(kv, "s_st") == kSessionCommitted &&
           IsOpaqueDeviceCredential(StrOf(kv, "s_code"));
}

bool Suspended(const AuthKv& kv, int32_t epoch) {
    const int32_t hold = HoldEpoch(kv);
    return hold > 0 && epoch > 0 && epoch <= hold;
}

bool NewerThanSession(const AuthKv& kv, int32_t epoch) {
    if (!SessionCommitted(kv)) {
        return true;
    }
    return epoch > IntOf(kv, "s_base");
}

bool RawConnectable(const AuthKv& kv, const SlotView& slot) {
    if (!SlotUsable(slot, RevokedEpoch(kv))) {
        return false;
    }
    if (Suspended(kv, slot.epoch) || !NewerThanSession(kv, slot.epoch)) {
        return false;
    }
    if (Phase(kv) == kPhaseDisabled) {
        return false;
    }
    return ValidUrl(slot.url) && ValidToken(slot.token);
}

AuthAction ActionFromPhase(const AuthKv& kv, bool connectable) {
    if (connectable) {
        return AuthAction::kConnect;
    }
    switch (Phase(kv)) {
        case kPhasePairing:
            return AuthAction::kWaitPairing;
        case kPhaseRecovery:
            return AuthAction::kWaitRecovery;
        case kPhaseDisabled:
            return AuthAction::kShowDisabled;
        default:
            if (SessionCommitted(kv)) {
                return IntOf(kv, "s_kind") == kPhaseRecovery ? AuthAction::kWaitRecovery
                                                             : AuthAction::kWaitPairing;
            }
            return AuthAction::kRetryIncomplete;
    }
}

Outcome CurrentOutcome(const AuthKv& kv, AuthStatus status) {
    Outcome out;
    out.status = status;
    const SlotView slot = HighestUsable(kv);
    out.ready_for_connection = RawConnectable(kv, slot);
    out.action = ActionFromPhase(kv, out.ready_for_connection);
    out.retry_after_ms = 0;
    return out;
}

bool WriteCommittedSlot(AuthKv& kv, int dest, int32_t epoch, const std::string& url,
                        const std::string& token, const std::string& key, int version,
                        const std::string& credential_version, uint32_t request_gen) {
    char name[8];
    if (!kv.SetInt(SlotKey(dest, "st", name, sizeof(name)), kSlotPending) || !kv.Commit()) {
        return false;
    }
    if (!kv.SetString(SlotKey(dest, "url", name, sizeof(name)), url) ||
        !kv.SetString(SlotKey(dest, "tok", name, sizeof(name)), token) ||
        !kv.SetString(SlotKey(dest, "key", name, sizeof(name)), key) ||
        !kv.SetString(SlotKey(dest, "cv", name, sizeof(name)), credential_version) ||
        !kv.SetInt(SlotKey(dest, "ver", name, sizeof(name)), version) ||
        !kv.SetInt(SlotKey(dest, "ep", name, sizeof(name)), epoch) || !kv.Commit()) {
        return false;
    }
    if (!kv.SetInt(SlotKey(dest, "st", name, sizeof(name)), kSlotCommitted) || !kv.Commit()) {
        return false;
    }
    if (request_gen > 0 && !kv.SetInt("applied", static_cast<int32_t>(request_gen))) {
        return false;
    }
    if (!kv.SetInt("active", dest) || !kv.Commit()) {
        return false;
    }
    return true;
}

bool WriteSession(AuthKv& kv, int32_t kind, int32_t base_epoch, const std::string& redeem,
                  const std::string& user_code, int32_t origin, const std::string& session_id,
                  const std::string& expires, uint32_t request_gen) {
    if (!kv.SetInt("s_st", kSessionPending) || !kv.Commit()) {
        return false;
    }
    if (!kv.SetInt("s_kind", kind) || !kv.SetInt("s_base", base_epoch) ||
        !kv.SetInt("s_origin", origin) || !kv.SetString("s_code", redeem) ||
        !kv.SetString("s_user", user_code) || !kv.SetString("s_sid", session_id) ||
        !kv.SetString("s_exp", expires) || !kv.Commit()) {
        return false;
    }
    if (!kv.SetInt("s_st", kSessionCommitted) || !kv.Commit()) {
        return false;
    }
    if (request_gen > 0 &&
        (!kv.SetInt("applied", static_cast<int32_t>(request_gen)) || !kv.Commit())) {
        return false;
    }
    return true;
}

bool SetPhase(AuthKv& kv, int32_t phase, uint32_t request_gen) {
    if (!kv.SetInt("phase", phase)) {
        return false;
    }
    if (request_gen > 0 && !kv.SetInt("applied", static_cast<int32_t>(request_gen))) {
        return false;
    }
    return kv.Commit();
}

bool SetHold(AuthKv& kv, int32_t hold) {
    return kv.SetInt("hold", hold) && kv.Commit();
}

void ImportLegacy(AuthKv& kv, const LegacyCredential* legacy) {
    if (legacy == nullptr || HighestUsable(kv).index != 0) {
        return;
    }
    if (RevokedEpoch(kv) > 0 || !IsOpaqueDeviceCredential(legacy->auth_key)) {
        return;
    }
    const int32_t epoch = RevokedEpoch(kv) + 1;
    const std::string url = ValidUrl(legacy->url) ? legacy->url : "";
    const std::string token = ValidToken(legacy->token) ? legacy->token : "";
    const int version = legacy->version > 0 ? legacy->version : 1;
    WriteCommittedSlot(kv, 1, epoch, url, token, legacy->auth_key, version, "", 0);
}

std::string FormatVersion(int64_t value) {
    char buf[32];
    std::snprintf(buf, sizeof(buf), "%lld", static_cast<long long>(value));
    return buf;
}

bool ClearSession(AuthKv& kv) {
    if (!kv.SetInt("s_st", kSessionNone)) {
        return false;
    }
    kv.Erase("s_code");
    kv.Erase("s_user");
    kv.Erase("s_sid");
    kv.Erase("s_exp");
    kv.Erase("s_origin");
    return kv.Commit();
}

bool UpdateSessionMeta(AuthKv& kv, int32_t kind, const HttpObservation& obs,
                       const HttpPayload& payload) {
    if (!kv.SetInt("s_kind", kind)) {
        return false;
    }
    if (obs.has_session_id && !obs.session_id.empty() && !kv.SetString("s_sid", obs.session_id)) {
        return false;
    }
    if (ValidUserCode(payload.user_code) && !kv.SetString("s_user", payload.user_code)) {
        return false;
    }
    if (obs.has_expires && obs.expires_at_ms > 0 &&
        !kv.SetString("s_exp", FormatVersion(obs.expires_at_ms))) {
        return false;
    }
    return kv.Commit();
}

int32_t NextEpoch(const AuthKv& kv) {
    int32_t highest = RevokedEpoch(kv);
    for (int index = 1; index <= 2; ++index) {
        const int32_t epoch = ReadSlot(kv, index).epoch;
        if (epoch > highest) {
            highest = epoch;
        }
    }
    if (highest < 0) {
        highest = 0;
    }
    return highest + 1;
}

int DestinationSlot(const AuthKv& kv) {
    const SlotView usable = HighestUsable(kv);
    if (usable.index == 1) {
        return 2;
    }
    return 1;
}

bool StaleRequest(const AuthKv& kv, uint32_t request_gen) {
    const int32_t applied = AppliedGen(kv);
    return request_gen > 0 && applied > 0 && request_gen < static_cast<uint32_t>(applied);
}

bool RememberApplied(AuthKv& kv, uint32_t request_gen) {
    if (request_gen == 0) {
        return true;
    }
    return kv.SetInt("applied", static_cast<int32_t>(request_gen)) && kv.Commit();
}

bool AcceptSession(AuthKv& kv, int32_t kind, const HttpObservation& obs, const HttpPayload& payload,
                   int32_t origin, const std::string& secret, uint32_t request_gen, Outcome* out) {
    const SlotView usable = HighestUsable(kv);
    const int32_t base = usable.index == 0 ? 0 : usable.epoch;
    const std::string session_id = obs.has_session_id ? obs.session_id : "";
    const std::string expires = obs.has_expires && obs.expires_at_ms > 0 ? FormatVersion(obs.expires_at_ms)
                                                                          : "";
    if (!IsOpaqueDeviceCredential(secret) ||
        !WriteSession(kv, kind, base, secret, ValidUserCode(payload.user_code) ? payload.user_code : "",
                      origin, session_id, expires, request_gen)) {
        out->status = AuthStatus::kPersistFailed;
        out->action = AuthAction::kRetryPersist;
        out->ready_for_connection = false;
        return false;
    }
    if (base > 0) {
        SetHold(kv, base);
    }
    SetPhase(kv, kind == kPhaseRecovery ? kPhaseRecovery : kPhasePairing, request_gen);
    *out = CurrentOutcome(kv, kind == kPhaseRecovery ? AuthStatus::kRecoveryRequired
                                                     : AuthStatus::kPairingRequired);
    out->mutated = true;
    out->ready_for_connection = false;
    out->action = kind == kPhaseRecovery ? AuthAction::kWaitRecovery : AuthAction::kWaitPairing;
    return true;
}

bool StoreOkCredential(AuthKv& kv, const HttpPayload& payload, uint32_t request_gen, Outcome* out) {
    if (!ValidUrl(payload.url) || !ValidToken(payload.token)) {
        *out = CurrentOutcome(kv, AuthStatus::kIncomplete);
        out->status = AuthStatus::kIncomplete;
        out->ready_for_connection = false;
        if (out->action == AuthAction::kConnect) {
            out->action = AuthAction::kRetryIncomplete;
        }
        RememberApplied(kv, request_gen);
        return false;
    }
    std::string key = payload.auth_key;
    const bool replacing_key = IsOpaqueDeviceCredential(key);
    if (!replacing_key || IsWebsocketAccessToken(key) || key == payload.token) {
        key = HighestUsable(kv).auth_key;
    }
    if (!replacing_key && !IsOpaqueDeviceCredential(key)) {
        key.clear();
    }
    const SlotView previous = HighestUsable(kv);
    const int32_t epoch = NextEpoch(kv);
    const int version = payload.version > 0 ? payload.version : 1;
    const std::string credential_version = payload.credential_version_present
                                               ? FormatVersion(payload.credential_version)
                                               : previous.credential_version;
    if (!WriteCommittedSlot(kv, DestinationSlot(kv), epoch, payload.url, payload.token, key,
                            version, credential_version, request_gen)) {
        const bool previous_ok = !replacing_key && RawConnectable(kv, previous);
        out->mutated = false;
        out->status = AuthStatus::kPersistFailed;
        out->ready_for_connection = previous_ok;
        out->action = previous_ok ? AuthAction::kConnect : AuthAction::kRetryPersist;
        return false;
    }
    if (HoldEpoch(kv) > 0 && epoch > HoldEpoch(kv)) {
        SetHold(kv, 0);
    }
    SetPhase(kv, kPhaseNone, 0);
    kv.SetInt("refresh", 0);
    kv.Commit();
    *out = CurrentOutcome(kv, AuthStatus::kOk);
    out->mutated = true;
    out->status = AuthStatus::kOk;
    out->action = AuthAction::kConnect;
    out->ready_for_connection = RawConnectable(kv, HighestUsable(kv));
    if (!out->ready_for_connection) {
        out->action = AuthAction::kRetryPersist;
        out->status = AuthStatus::kPersistFailed;
    }
    return out->ready_for_connection;
}

bool RevokeEpoch(AuthKv& kv, uint32_t credential_epoch, Outcome* out) {
    const SlotView usable = HighestUsable(kv);
    if (usable.index == 0) {
        return true;
    }
    if (credential_epoch != 0 && credential_epoch != static_cast<uint32_t>(usable.epoch)) {
        if (credential_epoch < static_cast<uint32_t>(usable.epoch)) {
            out->status = AuthStatus::kStale;
            out->action = ActionFromPhase(kv, RawConnectable(kv, usable));
            out->ready_for_connection = RawConnectable(kv, usable);
            return false;
        }
    }
    char name[8];
    const int32_t epoch = usable.epoch;
    if (!kv.SetInt(SlotKey(usable.index, "st", name, sizeof(name)), kSlotRevoked) ||
        !kv.SetInt("revoked", epoch) || !kv.Commit()) {
        out->status = AuthStatus::kPersistFailed;
        out->action = AuthAction::kRetryPersist;
        out->ready_for_connection = false;
        return false;
    }
    return true;
}

}  // namespace

bool IsHighEntropySecret(const std::string& value) {
    return IsOpaqueDeviceCredential(value, 43);
}

bool IsOpaqueDeviceCredential(const std::string& value, size_t min_length) {
    if (value.size() < min_length || value.size() > 128) {
        return false;
    }
    for (unsigned char ch : value) {
        const bool ok = (ch >= '0' && ch <= '9') || (ch >= 'a' && ch <= 'z') ||
                        (ch >= 'A' && ch <= 'Z') || ch == '-' || ch == '_';
        if (!ok) {
            return false;
        }
    }
    return true;
}

bool IsWebsocketAccessToken(const std::string& value) {
    if (value.rfind("v2.", 0) == 0) {
        return true;
    }
    int dots = 0;
    for (char ch : value) {
        if (ch == '.') {
            ++dots;
        }
    }
    return dots == 2 || dots == 4;
}

AuthStatus ParseAuthStatus(const char* status) {
    if (status == nullptr || status[0] == '\0') {
        return AuthStatus::kAbsent;
    }
    if (std::strcmp(status, "ok") == 0) {
        return AuthStatus::kOk;
    }
    if (std::strcmp(status, "pairing_required") == 0) {
        return AuthStatus::kPairingRequired;
    }
    if (std::strcmp(status, "recovery_required") == 0) {
        return AuthStatus::kRecoveryRequired;
    }
    if (std::strcmp(status, "disabled") == 0) {
        return AuthStatus::kDisabled;
    }
    if (std::strcmp(status, "rate_limited") == 0) {
        return AuthStatus::kRateLimited;
    }
    if (std::strcmp(status, "temporary_error") == 0) {
        return AuthStatus::kTemporaryError;
    }
    return AuthStatus::kUnrecognized;
}

const char* StatusName(AuthStatus status) {
    switch (status) {
        case AuthStatus::kOk:
            return "ok";
        case AuthStatus::kPairingRequired:
            return "pairing_required";
        case AuthStatus::kRecoveryRequired:
            return "recovery_required";
        case AuthStatus::kDisabled:
            return "disabled";
        case AuthStatus::kRateLimited:
            return "rate_limited";
        case AuthStatus::kTemporaryError:
            return "temporary_error";
        case AuthStatus::kIncomplete:
            return "incomplete";
        case AuthStatus::kPersistFailed:
            return "persist_failed";
        case AuthStatus::kStale:
            return "stale";
        case AuthStatus::kUnrecognized:
            return "unrecognized";
        case AuthStatus::kAbsent:
            return "absent";
    }
    return "absent";
}

const char* ActionName(AuthAction action) {
    switch (action) {
        case AuthAction::kConnect:
            return "connect";
        case AuthAction::kWaitPairing:
            return "pairing";
        case AuthAction::kWaitRecovery:
            return "recovery";
        case AuthAction::kShowDisabled:
            return "disabled";
        case AuthAction::kQuietBackoff:
            return "backoff";
        case AuthAction::kRetryTransport:
            return "transport_retry";
        case AuthAction::kRetryIncomplete:
            return "incomplete";
        case AuthAction::kRetryPersist:
            return "persist_retry";
        case AuthAction::kRefreshToken:
            return "refresh_token";
    }
    return "incomplete";
}

Outcome ApplyHttpResponse(AuthKv& kv, const HttpObservation& obs, const HttpPayload& payload,
                          const LegacyCredential* legacy) {
    ImportLegacy(kv, legacy);
    Outcome out = CurrentOutcome(kv, AuthStatus::kAbsent);
    if (StaleRequest(kv, obs.request_gen)) {
        out.status = AuthStatus::kStale;
        return out;
    }

    const bool known_envelope = obs.envelope_present && obs.schema == 1 &&
                                obs.envelope_status != AuthStatus::kAbsent &&
                                obs.envelope_status != AuthStatus::kUnrecognized;
    if (obs.envelope_present && !known_envelope) {
        out = CurrentOutcome(kv, AuthStatus::kTemporaryError);
        if (out.action == AuthAction::kRetryIncomplete) {
            out.action = AuthAction::kRetryTransport;
        }
        if (out.action != AuthAction::kConnect) {
            out.ready_for_connection = false;
        }
        RememberApplied(kv, obs.request_gen);
        return out;
    }

    if (known_envelope && obs.envelope_status == AuthStatus::kRateLimited) {
        out = CurrentOutcome(kv, AuthStatus::kRateLimited);
        if (out.action == AuthAction::kRetryIncomplete) {
            out.action = AuthAction::kQuietBackoff;
        }
        if (out.action != AuthAction::kConnect) {
            out.ready_for_connection = false;
        }
        out.retry_after_ms = obs.retry_after_ms > 0 ? obs.retry_after_ms : 15000;
        RememberApplied(kv, obs.request_gen);
        return out;
    }
    if (known_envelope && obs.envelope_status == AuthStatus::kTemporaryError) {
        out = CurrentOutcome(kv, AuthStatus::kTemporaryError);
        if (out.action == AuthAction::kRetryIncomplete) {
            out.action = AuthAction::kRetryTransport;
        }
        if (out.action != AuthAction::kConnect) {
            out.ready_for_connection = false;
        }
        out.retry_after_ms = obs.retry_after_ms > 0 ? obs.retry_after_ms : 0;
        RememberApplied(kv, obs.request_gen);
        return out;
    }
    if (known_envelope && obs.envelope_status == AuthStatus::kDisabled) {
        if (!RevokeEpoch(kv, 0, &out)) {
            return out;
        }
        if (!SetPhase(kv, kPhaseDisabled, obs.request_gen)) {
            out.status = AuthStatus::kPersistFailed;
            out.action = AuthAction::kRetryPersist;
            out.ready_for_connection = false;
            return out;
        }
        out = CurrentOutcome(kv, AuthStatus::kDisabled);
        out.mutated = true;
        out.ready_for_connection = false;
        out.action = AuthAction::kShowDisabled;
        return out;
    }
    if (known_envelope && (obs.envelope_status == AuthStatus::kPairingRequired ||
                           obs.envelope_status == AuthStatus::kRecoveryRequired)) {
        const int32_t kind = obs.envelope_status == AuthStatus::kRecoveryRequired ? kPhaseRecovery
                                                                                   : kPhasePairing;
        auto hold_and_wait = [&]() {
            const SlotView usable = HighestUsable(kv);
            if (usable.index != 0) {
                SetHold(kv, usable.epoch);
            }
            if (!SetPhase(kv, kind, obs.request_gen)) {
                out.status = AuthStatus::kPersistFailed;
                out.action = AuthAction::kRetryPersist;
                out.ready_for_connection = false;
                return;
            }
            out = CurrentOutcome(kv, obs.envelope_status);
            out.ready_for_connection = false;
            out.action = kind == kPhaseRecovery ? AuthAction::kWaitRecovery : AuthAction::kWaitPairing;
            out.mutated = true;
        };
        if (SessionCommitted(kv)) {
            // accepted=false must not replace the secret that already owns this session.
            if (!(obs.accepted_known && !obs.accepted)) {
                UpdateSessionMeta(kv, kind, obs, payload);
            }
            hold_and_wait();
            return out;
        }
        const bool rejected = obs.accepted_known && !obs.accepted &&
                              !(obs.secret_required_known && obs.secret_required);
        if (!rejected && IsHighEntropySecret(payload.pairing_secret)) {
            AcceptSession(kv, kind, obs, payload, 1, payload.pairing_secret, obs.request_gen, &out);
            return out;
        }
        if (!rejected && IsOpaqueDeviceCredential(payload.redeem)) {
            AcceptSession(kv, kind, obs, payload, 2, payload.redeem, obs.request_gen, &out);
            return out;
        }
        hold_and_wait();
        return out;
    }
    if (known_envelope && obs.envelope_status == AuthStatus::kOk) {
        if (!StoreOkCredential(kv, payload, obs.request_gen, &out)) {
            return out;
        }
        if (obs.confirm_sent && !obs.has_auth_key && SessionCommitted(kv)) {
            if (ClearSession(kv)) {
                SetPhase(kv, kPhaseNone, 0);
                out = CurrentOutcome(kv, AuthStatus::kOk);
                out.mutated = true;
                out.status = AuthStatus::kOk;
                out.action = out.ready_for_connection ? AuthAction::kConnect : AuthAction::kRetryPersist;
            }
        }
        return out;
    }

    const bool legacy_pairing = !obs.envelope_present && ValidUserCode(payload.user_code) &&
                                IsOpaqueDeviceCredential(payload.redeem);
    if (legacy_pairing) {
        AcceptSession(kv, kPhasePairing, obs, payload, 2, payload.redeem, obs.request_gen, &out);
        return out;
    }
    const bool legacy_migration = !obs.envelope_present && HighestUsable(kv).index == 0 &&
                                  IsOpaqueDeviceCredential(payload.redeem);
    if (legacy_migration) {
        AcceptSession(kv, kPhasePairing, obs, payload, 2, payload.redeem, obs.request_gen, &out);
        return out;
    }
    if (!obs.envelope_present && ValidUrl(payload.url) && ValidToken(payload.token)) {
        StoreOkCredential(kv, payload, obs.request_gen, &out);
        return out;
    }

    out = CurrentOutcome(kv, AuthStatus::kIncomplete);
    out.status = AuthStatus::kIncomplete;
    if (out.action != AuthAction::kConnect) {
        out.ready_for_connection = false;
    }
    RememberApplied(kv, obs.request_gen);
    return out;
}

Outcome ApplyTerminalAuth(AuthKv& kv, const char* code, uint32_t credential_epoch) {
    Outcome out = CurrentOutcome(kv, AuthStatus::kAbsent);
    if (code == nullptr) {
        return out;
    }
    if (std::strcmp(code, "token_expired") == 0) {
        return NoteTokenExpired(kv, credential_epoch);
    }
    int32_t phase = kPhaseNone;
    AuthStatus status = AuthStatus::kAbsent;
    AuthAction action = AuthAction::kRetryIncomplete;
    if (std::strcmp(code, "device_unbound") == 0) {
        phase = kPhasePairing;
        status = AuthStatus::kPairingRequired;
        action = AuthAction::kWaitPairing;
    } else if (std::strcmp(code, "credential_revoked") == 0) {
        phase = kPhaseRecovery;
        status = AuthStatus::kRecoveryRequired;
        action = AuthAction::kWaitRecovery;
    } else if (std::strcmp(code, "device_disabled") == 0) {
        phase = kPhaseDisabled;
        status = AuthStatus::kDisabled;
        action = AuthAction::kShowDisabled;
    } else {
        out.action = AuthAction::kRetryTransport;
        out.ready_for_connection = false;
        return out;
    }
    if (!RevokeEpoch(kv, credential_epoch, &out)) {
        return out;
    }
    if (!SetPhase(kv, phase, 0)) {
        out.status = AuthStatus::kPersistFailed;
        out.action = AuthAction::kRetryPersist;
        out.ready_for_connection = false;
        return out;
    }
    out.status = status;
    out.action = action;
    out.ready_for_connection = false;
    out.mutated = true;
    return out;
}

Outcome NoteTokenExpired(AuthKv& kv, uint32_t credential_epoch) {
    Outcome out = CurrentOutcome(kv, AuthStatus::kTemporaryError);
    const SlotView usable = HighestUsable(kv);
    if (credential_epoch != 0 && usable.index != 0 &&
        credential_epoch != static_cast<uint32_t>(usable.epoch) &&
        credential_epoch < static_cast<uint32_t>(usable.epoch)) {
        out.status = AuthStatus::kStale;
        return out;
    }
    if (!kv.SetInt("refresh", 1) || !kv.Commit()) {
        out.status = AuthStatus::kPersistFailed;
        out.action = AuthAction::kRetryPersist;
        out.ready_for_connection = false;
        return out;
    }
    out.status = AuthStatus::kTemporaryError;
    out.action = AuthAction::kRefreshToken;
    out.ready_for_connection = false;
    out.mutated = true;
    return out;
}

void AttachSessionSecret(const AuthKv& kv, HeaderChoice* choice, bool primary) {
    const std::string secret = StrOf(kv, "s_code");
    if (!IsOpaqueDeviceCredential(secret)) {
        return;
    }
    choice->session_id = StrOf(kv, "s_sid");
    choice->credential_epoch = static_cast<uint32_t>(IntOf(kv, "s_base"));
    if (IntOf(kv, "s_origin") == 1) {
        choice->pairing_secret = secret;
        if (primary) {
            choice->kind = HeaderKind::kPairingSecret;
            choice->secret = secret;
        }
    } else {
        choice->activation_code = secret;
        if (primary) {
            choice->kind = HeaderKind::kRedeemCode;
            choice->secret = secret;
        }
    }
}

HeaderChoice SelectHeader(AuthKv& kv, const LegacyCredential* legacy) {
    ImportLegacy(kv, legacy);
    HeaderChoice choice;
    const bool session = SessionCommitted(kv);
    const SlotView usable = HighestUsable(kv);
    const bool key_ok = usable.index != 0 && !Suspended(kv, usable.epoch) && Phase(kv) != kPhaseDisabled;
    if (session && key_ok && NewerThanSession(kv, usable.epoch)) {
        choice.kind = HeaderKind::kConfirm;
        choice.secret = usable.auth_key;
        choice.device_key = usable.auth_key;
        choice.confirm = true;
        choice.credential_epoch = static_cast<uint32_t>(usable.epoch);
        AttachSessionSecret(kv, &choice, false);
        return choice;
    }
    if (session) {
        const bool blocked = key_ok && NewerThanSession(kv, usable.epoch);
        if (!blocked) {
            AttachSessionSecret(kv, &choice, true);
            return choice;
        }
    }
    if (key_ok) {
        choice.kind = HeaderKind::kDeviceKey;
        choice.secret = usable.auth_key;
        choice.device_key = usable.auth_key;
        choice.credential_epoch = static_cast<uint32_t>(usable.epoch);
        return choice;
    }
    if (RevokedEpoch(kv) == 0 && HoldEpoch(kv) == 0 && Phase(kv) == kPhaseNone &&
        legacy != nullptr && IsOpaqueDeviceCredential(legacy->auth_key) &&
        HighestUsable(kv).index == 0) {
        choice.kind = HeaderKind::kDeviceKey;
        choice.secret = legacy->auth_key;
        choice.device_key = legacy->auth_key;
    }
    return choice;
}

ConnectableCredential LoadConnectable(AuthKv& kv) {
    ConnectableCredential out;
    const SlotView slot = HighestUsable(kv);
    if (!RawConnectable(kv, slot)) {
        return out;
    }
    out.present = true;
    out.epoch = static_cast<uint32_t>(slot.epoch);
    out.url = slot.url;
    out.token = slot.token;
    out.auth_key = slot.auth_key;
    out.version = slot.version;
    out.credential_version = slot.credential_version;
    return out;
}

uint32_t CurrentEpoch(AuthKv& kv) {
    const SlotView slot = HighestUsable(kv);
    return slot.index == 0 ? 0 : static_cast<uint32_t>(slot.epoch);
}

bool RefreshRequested(AuthKv& kv) { return IntOf(kv, "refresh") == 1; }

bool ClearRefreshRequest(AuthKv& kv) {
    return kv.SetInt("refresh", 0) && kv.Commit();
}

bool MayRestoreUnscopedCache(AuthKv& kv) {
    return RevokedEpoch(kv) <= 0 && Phase(kv) == kPhaseNone && !SessionCommitted(kv);
}

bool HasCommittedSession(AuthKv& kv) { return SessionCommitted(kv); }

bool ConfirmPending(AuthKv& kv) {
    if (!SessionCommitted(kv) || Phase(kv) == kPhaseDisabled) {
        return false;
    }
    const SlotView usable = HighestUsable(kv);
    return usable.index != 0 && !Suspended(kv, usable.epoch) && NewerThanSession(kv, usable.epoch);
}

AuthAction CurrentAction(AuthKv& kv) { return CurrentOutcome(kv, AuthStatus::kAbsent).action; }

std::string SessionDisplayCode(AuthKv& kv) {
    if (!SessionCommitted(kv)) {
        return {};
    }
    const std::string code = StrOf(kv, "s_user");
    return ValidUserCode(code) ? code : std::string();
}

std::string StoredCredentialVersion(AuthKv& kv) {
    const SlotView slot = HighestUsable(kv);
    return slot.index == 0 ? std::string() : slot.credential_version;
}

uint32_t NextRequestGen(AuthKv& kv) {
    int32_t current = IntOf(kv, "req");
    const int32_t applied = IntOf(kv, "applied");
    if (current < applied) {
        current = applied;
    }
    if (current < 0) {
        current = 0;
    }
    const int32_t next = current == INT32_MAX ? 1 : current + 1;
    if (!kv.SetInt("req", next) || !kv.Commit()) {
        return 0;
    }
    return static_cast<uint32_t>(next);
}

namespace {

bool ReadI64(const cJSON* item, int64_t* out) {
    if (!cJSON_IsNumber(item) || out == nullptr) {
        return false;
    }
    const double value = item->valuedouble;
    if (value < static_cast<double>(INT64_MIN) || value > static_cast<double>(INT64_MAX)) {
        return false;
    }
    *out = static_cast<int64_t>(value);
    return true;
}

const char* JsonString(const cJSON* object, const char* key) {
    if (!cJSON_IsObject(object)) {
        return nullptr;
    }
    const cJSON* item = cJSON_GetObjectItemCaseSensitive(object, key);
    if (!cJSON_IsString(item) || item->valuestring == nullptr) {
        return nullptr;
    }
    return item->valuestring;
}

}  // namespace

bool ParseOtaAuthJson(const char* json, HttpObservation* observation, HttpPayload* payload) {
    if (observation == nullptr || payload == nullptr) {
        return false;
    }
    *observation = HttpObservation{};
    *payload = HttpPayload{};
    if (json == nullptr) {
        return false;
    }
    cJSON* root = cJSON_Parse(json);
    if (root == nullptr) {
        return false;
    }
    observation->body_parsed = true;
    const cJSON* auth = cJSON_GetObjectItemCaseSensitive(root, "auth");
    const cJSON* envelope = cJSON_IsObject(auth) ? auth : root;
    const cJSON* schema = cJSON_GetObjectItemCaseSensitive(envelope, "schema");
    const cJSON* status = cJSON_GetObjectItemCaseSensitive(envelope, "status");
    if (cJSON_IsNumber(schema) && cJSON_IsString(status) && status->valuestring != nullptr) {
        observation->envelope_present = true;
        observation->schema = schema->valueint;
        observation->envelope_status = ParseAuthStatus(status->valuestring);
        const cJSON* retry = cJSON_GetObjectItemCaseSensitive(envelope, "retry_after_ms");
        int64_t retry_ms = 0;
        if (ReadI64(retry, &retry_ms) && retry_ms > 0 && retry_ms <= 86400000LL) {
            observation->retry_after_ms = static_cast<int>(retry_ms);
        }
        const cJSON* version = cJSON_GetObjectItemCaseSensitive(envelope, "credential_version");
        if (ReadI64(version, &observation->credential_version)) {
            observation->credential_version_present = true;
            payload->credential_version_present = true;
            payload->credential_version = observation->credential_version;
        }
    }
    const cJSON* pairing = cJSON_IsObject(auth) ? cJSON_GetObjectItemCaseSensitive(auth, "pairing") : nullptr;
    if (cJSON_IsObject(pairing)) {
        if (const char* session_id = JsonString(pairing, "session_id")) {
            observation->has_session_id = session_id[0] != '\0';
            observation->session_id = session_id;
        }
        if (const char* purpose = JsonString(pairing, "purpose")) {
            observation->purpose = purpose;
        }
        if (const char* display = JsonString(pairing, "display_code")) {
            if (ValidUserCode(display)) {
                payload->user_code = display;
                observation->has_user_code = true;
            }
        }
        int64_t expires = 0;
        if (ReadI64(cJSON_GetObjectItemCaseSensitive(pairing, "expires_at"), &expires) && expires > 0) {
            observation->has_expires = true;
            observation->expires_at_ms = expires;
        }
        const cJSON* secret_required = cJSON_GetObjectItemCaseSensitive(pairing, "secret_required");
        if (cJSON_IsBool(secret_required)) {
            observation->secret_required_known = true;
            observation->secret_required = cJSON_IsTrue(secret_required);
        }
        const cJSON* accepted = cJSON_GetObjectItemCaseSensitive(pairing, "accepted");
        if (cJSON_IsBool(accepted)) {
            observation->accepted_known = true;
            observation->accepted = cJSON_IsTrue(accepted);
        }
    }
    const cJSON* activation = cJSON_GetObjectItemCaseSensitive(root, "activation");
    if (cJSON_IsObject(activation)) {
        if (!observation->has_user_code) {
            if (const char* code = JsonString(activation, "code")) {
                if (ValidUserCode(code)) {
                    payload->user_code = code;
                    observation->has_user_code = true;
                }
            }
        }
        if (const char* redeem = JsonString(activation, "bootstrap_code")) {
            if (IsOpaqueDeviceCredential(redeem) && !IsWebsocketAccessToken(redeem)) {
                payload->redeem = redeem;
                observation->has_redeem = true;
            }
        }
    }
    const cJSON* websocket = cJSON_GetObjectItemCaseSensitive(root, "websocket");
    if (cJSON_IsObject(websocket)) {
        if (const char* url = JsonString(websocket, "url")) {
            if (ValidUrl(url)) {
                payload->url = url;
                observation->has_ws_url = true;
            }
        }
        if (const char* token = JsonString(websocket, "token")) {
            if (ValidToken(token)) {
                payload->token = token;
                observation->has_ws_token = true;
            }
        }
        if (const char* auth_key = JsonString(websocket, "auth_key")) {
            if (IsOpaqueDeviceCredential(auth_key) && !IsWebsocketAccessToken(auth_key)) {
                payload->auth_key = auth_key;
                observation->has_auth_key = true;
            }
        }
        const cJSON* version = cJSON_GetObjectItemCaseSensitive(websocket, "version");
        if (cJSON_IsNumber(version) && version->valueint > 0) {
            payload->version = version->valueint;
        }
    }
    cJSON_Delete(root);
    return true;
}

#ifndef AUTH_CONNECTION_HOST
}  // namespace authconn

#include "settings.h"

#include <esp_log.h>

namespace authconn {
namespace {

constexpr const char* kNs = "auth_state";
constexpr const char* TAG = "AuthState";

class SettingsKv final : public AuthKv {
public:
    explicit SettingsKv(Settings* settings) : settings_(settings) {}

    bool GetString(const char* key, std::string* out) const override {
        if (settings_ == nullptr || key == nullptr) {
            return false;
        }
        return settings_->TryGetString(key, out) == Settings::ReadStatus::Ok;
    }
    bool GetInt(const char* key, int32_t* out) const override {
        if (settings_ == nullptr || key == nullptr) {
            return false;
        }
        return settings_->TryGetInt(key, out) == Settings::ReadStatus::Ok;
    }
    bool SetString(const char* key, const std::string& value) override {
        return settings_ != nullptr && key != nullptr && settings_->SetString(key, value) == ESP_OK;
    }
    bool SetInt(const char* key, int32_t value) override {
        return settings_ != nullptr && key != nullptr && settings_->SetInt(key, value) == ESP_OK;
    }
    bool Erase(const char* key) override {
        return settings_ != nullptr && key != nullptr && settings_->EraseKey(key) == ESP_OK;
    }
    bool Commit() override {
        return settings_ != nullptr && settings_->Commit() == ESP_OK;
    }

private:
    Settings* settings_;
};

class Store {
public:
    Store() : settings_(kNs, true), kv_(&settings_) {}
    bool open() const { return settings_.IsValid(); }
    AuthKv& kv() { return kv_; }

private:
    Settings settings_;
    SettingsKv kv_;
};

LegacyCredential ReadLegacy() {
    LegacyCredential legacy;
    Settings ws("websocket", false);
    legacy.url = ws.GetString("url");
    legacy.token = ws.GetString("token");
    legacy.auth_key = ws.GetString("auth_key");
    legacy.version = ws.GetInt("version", 1);
    return legacy;
}

}  // namespace

bool EraseMirroredCredential();

HeaderChoice SelectPersistedHeader() {
    Store store;
    if (!store.open()) {
        HeaderChoice choice;
        const LegacyCredential legacy = ReadLegacy();
        if (IsOpaqueDeviceCredential(legacy.auth_key)) {
            choice.kind = HeaderKind::kDeviceKey;
            choice.secret = legacy.auth_key;
            choice.device_key = legacy.auth_key;
        }
        return choice;
    }
    const LegacyCredential legacy = ReadLegacy();
    return SelectHeader(store.kv(), &legacy);
}

Outcome ApplyPersistedHttp(const HttpObservation& obs, const HttpPayload& payload) {
    Store store;
    if (!store.open()) {
        Outcome out;
        out.status = AuthStatus::kPersistFailed;
        out.action = AuthAction::kRetryPersist;
        return out;
    }
    const LegacyCredential legacy = ReadLegacy();
    return ApplyHttpResponse(store.kv(), obs, payload, &legacy);
}

Outcome ApplyPersistedTerminal(const char* code, uint32_t credential_epoch) {
    Store store;
    if (!store.open()) {
        Outcome out;
        out.status = AuthStatus::kPersistFailed;
        out.action = AuthAction::kRetryPersist;
        return out;
    }
    const Outcome out = ApplyTerminalAuth(store.kv(), code, credential_epoch);
    if (out.mutated && out.status != AuthStatus::kStale &&
        out.action != AuthAction::kRefreshToken) {
        EraseMirroredCredential();
    }
    return out;
}

Outcome NotePersistedTokenExpired(uint32_t credential_epoch) {
    Store store;
    if (!store.open()) {
        Outcome out;
        out.status = AuthStatus::kPersistFailed;
        out.action = AuthAction::kRetryPersist;
        return out;
    }
    return NoteTokenExpired(store.kv(), credential_epoch);
}

ConnectableCredential LoadPersistedConnectable() {
    Store store;
    if (!store.open()) {
        return {};
    }
    const LegacyCredential legacy = ReadLegacy();
    ImportLegacy(store.kv(), &legacy);
    return LoadConnectable(store.kv());
}

uint32_t CurrentPersistedEpoch() {
    Store store;
    if (!store.open()) {
        return 0;
    }
    return CurrentEpoch(store.kv());
}

bool PersistedRefreshRequested() {
    Store store;
    return store.open() && RefreshRequested(store.kv());
}

bool ClearPersistedRefreshRequest() {
    Store store;
    return store.open() && ClearRefreshRequest(store.kv());
}

bool MayRestorePersistedCache() {
    Store store;
    if (!store.open()) {
        return true;
    }
    return MayRestoreUnscopedCache(store.kv());
}

bool HasPersistedPairingSession() {
    Store store;
    return store.open() && HasCommittedSession(store.kv());
}

bool PersistedConfirmPending() {
    Store store;
    return store.open() && ConfirmPending(store.kv());
}

AuthAction CurrentPersistedAction() {
    Store store;
    if (!store.open()) {
        return AuthAction::kRetryIncomplete;
    }
    return CurrentAction(store.kv());
}

std::string PersistedDisplayCode() {
    Store store;
    if (!store.open()) {
        return {};
    }
    return SessionDisplayCode(store.kv());
}

uint32_t NextPersistedRequestGen() {
    Store store;
    if (!store.open()) {
        return 0;
    }
    return NextRequestGen(store.kv());
}

bool MirrorPersistedCredential(const ConnectableCredential& credential) {
    if (!credential.present || !ValidUrl(credential.url) || !ValidToken(credential.token)) {
        return false;
    }
    {
        Settings ws("websocket", true);
        if (!ws.IsValid() || ws.SetString("url", credential.url) != ESP_OK ||
            ws.SetString("token", credential.token) != ESP_OK ||
            ws.SetInt("version", credential.version) != ESP_OK ||
            ws.SetInt("cred_epoch", static_cast<int32_t>(credential.epoch)) != ESP_OK) {
            return false;
        }
        if (IsOpaqueDeviceCredential(credential.auth_key) &&
            ws.SetString("auth_key", credential.auth_key) != ESP_OK) {
            return false;
        }
        if (ws.Commit() != ESP_OK) {
            return false;
        }
    }
    Settings cache("ws_vcache", true);
    if (!cache.IsValid() || cache.SetInt("schema", 1) != ESP_OK ||
        cache.SetString("url", credential.url) != ESP_OK ||
        cache.SetString("token", credential.token) != ESP_OK ||
        cache.SetInt("version", credential.version) != ESP_OK ||
        cache.SetInt("cred_epoch", static_cast<int32_t>(credential.epoch)) != ESP_OK ||
        cache.SetBool("valid", true) != ESP_OK || cache.Commit() != ESP_OK) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=persist_failed target=ws_cache");
        return false;
    }
    ESP_LOGI(TAG, "[OTA_BOOT] event=credential_committed epoch=%u token_len=%u key_len=%u",
             static_cast<unsigned>(credential.epoch),
             static_cast<unsigned>(credential.token.size()),
             static_cast<unsigned>(credential.auth_key.size()));
    return true;
}

bool EraseMirroredCredential() {
    bool ok = true;
    {
        Settings active("websocket", true);
        if (!active.IsValid()) {
            ok = false;
        } else {
            active.EraseKey("url");
            active.EraseKey("token");
            active.EraseKey("version");
            active.EraseKey("cred_epoch");
            active.EraseKey("auth_key");
            if (active.Commit() != ESP_OK) {
                ok = false;
            }
        }
    }
    {
        Settings cache("ws_vcache", true);
        if (!cache.IsValid() || cache.SetBool("valid", false) != ESP_OK ||
            cache.EraseKey("url") != ESP_OK || cache.EraseKey("token") != ESP_OK ||
            cache.Commit() != ESP_OK) {
            ok = false;
        }
    }
    {
        Settings activation("activation", true);
        if (activation.IsValid()) {
            activation.EraseKey("bootstrap_code");
            if (activation.Commit() != ESP_OK) {
                ok = false;
            }
        }
    }
    if (!ok) {
        ESP_LOGW(TAG, "[OTA_BOOT] event=persist_failed target=mirror_erase");
    }
    return ok;
}

#endif

}  // namespace authconn
