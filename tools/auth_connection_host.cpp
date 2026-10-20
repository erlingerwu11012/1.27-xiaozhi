#include "auth_connection.h"

#include <iostream>
#include <map>
#include <string>
#include <vector>

namespace {

int g_failed = 0;

void Expect(bool cond, const char* name) {
    if (!cond) {
        std::cerr << "FAIL " << name << "\n";
        ++g_failed;
    } else {
        std::cout << "PASS " << name << "\n";
    }
}

class MemoryKv final : public authconn::AuthKv {
public:
    bool GetString(const char* key, std::string* out) const override {
        const auto dirty = dirty_s.find(key);
        if (dirty != dirty_s.end()) {
            if (out) *out = dirty->second;
            return true;
        }
        const auto committed = committed_s.find(key);
        if (committed == committed_s.end()) return false;
        if (out) *out = committed->second;
        return true;
    }
    bool GetInt(const char* key, int32_t* out) const override {
        const auto dirty = dirty_i.find(key);
        if (dirty != dirty_i.end()) {
            if (out) *out = dirty->second;
            return true;
        }
        const auto committed = committed_i.find(key);
        if (committed == committed_i.end()) return false;
        if (out) *out = committed->second;
        return true;
    }
    bool SetString(const char* key, const std::string& value) override {
        dirty_s[key] = value;
        return true;
    }
    bool SetInt(const char* key, int32_t value) override {
        dirty_i[key] = value;
        return true;
    }
    bool Erase(const char* key) override {
        dirty_s.erase(key);
        dirty_i.erase(key);
        erased.push_back(key);
        return true;
    }
    bool Commit() override {
        ++commits;
        if (fail_commits || (fail_at > 0 && commits == fail_at)) {
            dirty_s.clear();
            dirty_i.clear();
            erased.clear();
            return false;
        }
        for (const auto& item : dirty_s) committed_s[item.first] = item.second;
        for (const auto& item : dirty_i) committed_i[item.first] = item.second;
        for (const auto& key : erased) {
            committed_s.erase(key);
            committed_i.erase(key);
        }
        dirty_s.clear();
        dirty_i.clear();
        erased.clear();
        return true;
    }
    void Crash() {
        dirty_s.clear();
        dirty_i.clear();
        erased.clear();
    }

    int commits = 0;
    bool fail_commits = false;
    int fail_at = 0;
    std::map<std::string, std::string> committed_s;
    std::map<std::string, int32_t> committed_i;

private:
    std::map<std::string, std::string> dirty_s;
    std::map<std::string, int32_t> dirty_i;
    std::vector<std::string> erased;
};

const std::string kUrl = "wss://www.realecho.cn/xiaozhi/v1/";
const std::string kToken = "v2.signature.10.20.3";
const std::string kKey = std::string(43, 'A');
const std::string kNewKey = std::string(43, 'B');
const std::string kRedeem = std::string(43, 'c');

authconn::HttpPayload OkPayload(const std::string& key) {
    authconn::HttpPayload payload;
    payload.url = kUrl;
    payload.token = kToken;
    payload.auth_key = key;
    payload.version = 2;
    return payload;
}

authconn::HttpObservation Gen(uint32_t gen) {
    authconn::HttpObservation obs;
    obs.body_parsed = true;
    obs.request_gen = gen;
    obs.has_ws_url = true;
    obs.has_ws_token = true;
    obs.has_auth_key = true;
    return obs;
}

void SeedKey(MemoryKv& kv) {
    const auto out = authconn::ApplyHttpResponse(kv, Gen(1), OkPayload(kKey), nullptr);
    Expect(out.action == authconn::AuthAction::kConnect && out.ready_for_connection, "seed_connects");
}

}  // namespace

int main() {
    using namespace authconn;
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpPayload stray = OkPayload(kKey);
        stray.redeem = kRedeem;
        HttpObservation obs = Gen(2);
        obs.has_redeem = true;
        obs.has_auth_key = false;
        stray.auth_key.clear();
        stray.token.clear();
        stray.url.clear();
        obs.has_ws_token = false;
        const Outcome out = ApplyHttpResponse(kv, obs, stray, nullptr);
        const HeaderChoice header = SelectHeader(kv, nullptr);
        Expect(out.action == AuthAction::kConnect, "lone_redeem_keeps_connection");
        Expect(header.kind == HeaderKind::kDeviceKey && header.secret == kKey, "lone_redeem_does_not_override_key");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 2;
        obs.envelope_present = true;
        obs.schema = 1;
        obs.envelope_status = AuthStatus::kRecoveryRequired;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.redeem = kRedeem;
        const Outcome out = ApplyHttpResponse(kv, obs, payload, nullptr);
        const HeaderChoice header = SelectHeader(kv, nullptr);
        Expect(out.action == AuthAction::kWaitRecovery && !out.ready_for_connection, "recovery_waits");
        Expect(header.kind == HeaderKind::kRedeemCode && header.secret == kRedeem, "recovery_session_outranks_old_key");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 2;
        obs.has_user_code = true;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.user_code = "123456";
        payload.redeem = kRedeem;
        const Outcome out = ApplyHttpResponse(kv, obs, payload, nullptr);
        const HeaderChoice header = SelectHeader(kv, nullptr);
        Expect(out.action == AuthAction::kWaitPairing, "legacy_pairing_with_old_key");
        Expect(header.kind == HeaderKind::kRedeemCode && header.secret == kRedeem, "offline_rebind_uses_redeem");
    }
    {
        MemoryKv kv;
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 1;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.redeem = kRedeem;
        const Outcome out = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(out.action == AuthAction::kWaitPairing, "migration_redeem_without_key");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kRedeemCode, "migration_header");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 2;
        obs.has_ws_url = true;
        const Outcome out = ApplyHttpResponse(kv, obs, HttpPayload{}, nullptr);
        Expect(out.status == AuthStatus::kIncomplete && out.action == AuthAction::kConnect, "url_only_keeps_credentials");
        Expect(SelectHeader(kv, nullptr).secret == kKey, "url_only_does_not_clear_key");
        Expect(MayRestoreUnscopedCache(kv), "url_only_cache_still_allowed");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        const uint32_t epoch = CurrentEpoch(kv);
        HttpObservation rate;
        rate.body_parsed = true;
        rate.request_gen = 2;
        rate.envelope_present = true;
        rate.schema = 1;
        rate.envelope_status = AuthStatus::kRateLimited;
        rate.retry_after_ms = 25000;
        const Outcome limited = ApplyHttpResponse(kv, rate, HttpPayload{}, nullptr);
        Expect(limited.action == AuthAction::kConnect && SelectHeader(kv, nullptr).secret == kKey, "rate_limit_keeps_key");
        HttpObservation bad_schema = rate;
        bad_schema.request_gen = 3;
        bad_schema.schema = 9;
        bad_schema.envelope_status = AuthStatus::kDisabled;
        const Outcome unknown = ApplyHttpResponse(kv, bad_schema, HttpPayload{}, nullptr);
        Expect(unknown.action == AuthAction::kConnect && CurrentEpoch(kv) == epoch, "unknown_schema_does_not_revoke");
        const Outcome expired = NoteTokenExpired(kv, epoch);
        Expect(expired.action == AuthAction::kRefreshToken && RefreshRequested(kv), "token_expired_refreshes");
        Expect(SelectHeader(kv, nullptr).secret == kKey, "token_expired_keeps_key");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        const uint32_t epoch = CurrentEpoch(kv);
        HttpPayload renewed = OkPayload(kNewKey);
        renewed.token = "v2.signature.11.21.4";
        const Outcome ok = ApplyHttpResponse(kv, Gen(2), renewed, nullptr);
        Expect(ok.ready_for_connection && SelectHeader(kv, nullptr).secret == kNewKey, "new_key_committed");
        const Outcome stale = ApplyTerminalAuth(kv, "credential_revoked", epoch);
        Expect(stale.status == AuthStatus::kStale && SelectHeader(kv, nullptr).secret == kNewKey, "stale_revoke_ignored");
        const Outcome revoked = ApplyTerminalAuth(kv, "credential_revoked", CurrentEpoch(kv));
        Expect(revoked.action == AuthAction::kWaitRecovery && !revoked.ready_for_connection, "current_revoke_needs_recovery");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kNone, "revoked_key_not_sent");
        Expect(!MayRestoreUnscopedCache(kv), "revoked_cache_not_restored");
        HttpObservation transport;
        transport.body_parsed = true;
        transport.request_gen = 3;
        transport.envelope_present = true;
        transport.schema = 1;
        transport.envelope_status = AuthStatus::kTemporaryError;
        const Outcome after = ApplyHttpResponse(kv, transport, OkPayload(kKey), nullptr);
        Expect(after.action == AuthAction::kWaitRecovery && SelectHeader(kv, nullptr).kind == HeaderKind::kNone,
               "transport_status_does_not_restore_revoked_key");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        const int commits_before = kv.commits;
        kv.fail_at = commits_before + 1;
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 4;
        obs.envelope_present = true;
        obs.schema = 1;
        obs.envelope_status = AuthStatus::kRecoveryRequired;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.redeem = kRedeem;
        const Outcome failed = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(failed.action == AuthAction::kRetryPersist, "session_commit_failure_is_not_success");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kDeviceKey, "failed_session_does_not_drop_key");
        kv.fail_at = 0;
        const Outcome stored = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(stored.action == AuthAction::kWaitRecovery, "session_retry_after_commit_failure");
        kv.fail_commits = true;
        HttpPayload redeemed = OkPayload(kNewKey);
        redeemed.token = "v2.signature.12.22.5";
        HttpObservation redeem = Gen(5);
        const Outcome lost = ApplyHttpResponse(kv, redeem, redeemed, nullptr);
        Expect(lost.action == AuthAction::kRetryPersist && !lost.ready_for_connection, "redeem_persist_failure");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kRedeemCode, "same_redeem_is_retried");
        kv.fail_commits = false;
        kv.Crash();
        const Outcome done = ApplyHttpResponse(kv, redeem, redeemed, nullptr);
        Expect(done.ready_for_connection && SelectHeader(kv, nullptr).secret == kNewKey, "redeem_succeeds_after_retry");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 2;
        obs.envelope_present = true;
        obs.schema = 1;
        obs.envelope_status = AuthStatus::kPairingRequired;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.redeem = kRedeem;
        Expect(ApplyHttpResponse(kv, obs, payload, nullptr).action == AuthAction::kWaitPairing, "pairing_session");
        kv.Crash();
        HttpObservation late = Gen(1);
        HttpPayload old = OkPayload(std::string(43, 'D'));
        old.token = "v2.signature.1.2.1";
        const Outcome stale = ApplyHttpResponse(kv, late, old, nullptr);
        Expect(stale.status == AuthStatus::kStale && SelectHeader(kv, nullptr).kind == HeaderKind::kRedeemCode,
               "old_generation_cannot_replace_session");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        HttpObservation obs;
        obs.body_parsed = true;
        obs.request_gen = 2;
        obs.envelope_present = true;
        obs.schema = 1;
        obs.envelope_status = AuthStatus::kDisabled;
        obs.has_redeem = true;
        HttpPayload payload;
        payload.redeem = kRedeem;
        const Outcome out = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(out.action == AuthAction::kShowDisabled, "disabled_shown");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kNone, "disabled_ignores_redeem_and_old_key");
    }
    {
        MemoryKv kv;
        HttpPayload payload = OkPayload(kToken);
        const Outcome out = ApplyHttpResponse(kv, Gen(1), payload, nullptr);
        Expect(!out.ready_for_connection, "wss_token_is_not_a_device_key");
        Expect(SelectHeader(kv, nullptr).kind == HeaderKind::kNone, "wss_token_not_sent_as_authorization");
    }
    {
        MemoryKv kv;
        SeedKey(kv);
        const int before = kv.commits;
        HttpPayload renewed = OkPayload(kNewKey);
        renewed.token = "v2.signature.30.40.6";
        kv.fail_at = before + 2;
        ApplyHttpResponse(kv, Gen(2), renewed, nullptr);
        kv.Crash();
        Expect(SelectHeader(kv, nullptr).secret == kKey, "power_loss_during_pending_keeps_old_key");
        kv.fail_at = 0;
        const int again = kv.commits;
        kv.fail_at = again + 4;
        ApplyHttpResponse(kv, Gen(3), renewed, nullptr);
        kv.Crash();
        Expect(SelectHeader(kv, nullptr).secret == kNewKey, "committed_slot_survives_later_power_loss");
    }
    {
        const std::string secret(43, 's');
        const std::string other(43, 't');
        const std::string issued_key(43, 'K');
        const char* initial = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","token":"v2.signature.10.20.41","version":2,"auth_key":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"},
          "auth": {"schema":1,"status":"ok","retry_after_ms":0,"credential_version":41}
        })";
        MemoryKv kv;
        HttpObservation obs;
        HttpPayload payload;
        Expect(ParseOtaAuthJson(initial, &obs, &payload), "parse_initial_ok");
        obs.request_gen = 1;
        Expect(ApplyHttpResponse(kv, obs, payload, nullptr).ready_for_connection, "parsed_ok_connects");
        Expect(StoredCredentialVersion(kv) == "41", "credential_version_from_server");
        Expect(!SelectHeader(kv, nullptr).confirm && SelectHeader(kv, nullptr).pairing_secret.empty(),
               "healthy_key_has_no_pairing_secret");

        const char* recovery = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","version":2},
          "auth": {"schema":1,"status":"recovery_required","retry_after_ms":0,"credential_version":41,
                   "pairing":{"purpose":"recovery","secret_required":true,"accepted":false}}
        })";
        Expect(ParseOtaAuthJson(recovery, &obs, &payload), "parse_recovery_secret_required");
        Expect(obs.secret_required && obs.accepted_known && !obs.accepted && obs.credential_version == 41,
               "recovery_fields");
        payload.pairing_secret = secret;
        obs.request_gen = 2;
        const Outcome opened = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(opened.action == AuthAction::kWaitRecovery && !opened.ready_for_connection, "recovery_waits_for_code");
        HeaderChoice header = SelectHeader(kv, nullptr);
        Expect(header.kind == HeaderKind::kPairingSecret && header.pairing_secret == secret &&
               header.device_key.empty() && !header.confirm, "pairing_secret_not_old_key");

        const char* accepted = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","version":2},
          "auth": {"schema":1,"status":"recovery_required","retry_after_ms":0,"credential_version":41,
                   "pairing":{"session_id":"session-1","display_code":"654321","purpose":"recovery",
                              "expires_at":1710000000000,"secret_required":false,"accepted":true}}
        })";
        Expect(ParseOtaAuthJson(accepted, &obs, &payload), "parse_accepted_session");
        Expect(obs.session_id == "session-1" && payload.user_code == "654321" && obs.expires_at_ms == 1710000000000LL,
               "pairing_object_fields");
        payload.pairing_secret = other;
        obs.request_gen = 3;
        Expect(ApplyHttpResponse(kv, obs, payload, nullptr).action == AuthAction::kWaitRecovery, "same_session_reused");
        header = SelectHeader(kv, nullptr);
        Expect(header.pairing_secret == secret && header.session_id == "session-1", "secret_not_regenerated");
        Expect(SessionDisplayCode(kv) == "654321", "display_code_stored");

        const char* rejected = R"({
          "auth": {"schema":1,"status":"recovery_required","retry_after_ms":0,"credential_version":41,
                   "pairing":{"purpose":"recovery","secret_required":false,"accepted":false}}
        })";
        Expect(ParseOtaAuthJson(rejected, &obs, &payload), "parse_rejected_secret");
        payload.pairing_secret = other;
        obs.request_gen = 4;
        ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(SelectHeader(kv, nullptr).pairing_secret == secret, "accepted_false_keeps_secret");

        const char* issued = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","token":"v2.signature.11.21.42","version":2,
                        "auth_key":"KKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKKK"},
          "auth": {"schema":1,"status":"ok","retry_after_ms":0,"credential_version":42}
        })";
        Expect(ParseOtaAuthJson(issued, &obs, &payload), "parse_issued_key");
        obs.request_gen = 5;
        obs.confirm_sent = false;
        const Outcome got = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(got.ready_for_connection && StoredCredentialVersion(kv) == "42", "issued_key_version_42");
        header = SelectHeader(kv, nullptr);
        Expect(header.confirm && header.device_key == issued_key && header.pairing_secret == secret &&
               header.session_id == "session-1", "confirm_header_combination");
        Expect(!header.activation_code.empty() == false, "device_secret_is_not_activation_code");

        kv.fail_commits = true;
        obs.request_gen = 6;
        const Outcome lost = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(!lost.ready_for_connection, "lost_issued_response_is_retried");
        Expect(SelectHeader(kv, nullptr).confirm && SelectHeader(kv, nullptr).pairing_secret == secret,
               "failed_confirm_write_keeps_session");
        kv.fail_commits = false;
        kv.Crash();

        const char* confirmed = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","token":"v2.signature.12.22.42","version":2},
          "auth": {"schema":1,"status":"ok","retry_after_ms":0,"credential_version":42}
        })";
        Expect(ParseOtaAuthJson(confirmed, &obs, &payload), "parse_confirm_response");
        Expect(!obs.has_auth_key, "confirm_response_has_no_auth_key");
        obs.request_gen = 7;
        obs.confirm_sent = true;
        const Outcome done = ApplyHttpResponse(kv, obs, payload, nullptr);
        Expect(done.ready_for_connection && !HasCommittedSession(kv), "confirm_clears_session");
        header = SelectHeader(kv, nullptr);
        Expect(header.kind == HeaderKind::kDeviceKey && header.device_key == issued_key &&
               header.pairing_secret.empty() && !header.confirm, "confirmed_key_only");
        Expect(SessionDisplayCode(kv).empty(), "display_code_cleared_after_confirm");

        const char* token_as_key = R"({
          "websocket": {"url":"wss://www.realecho.cn/xiaozhi/v1/","token":"v2.signature.1.2.3","version":2,
                        "auth_key":"v2.signature.1.2.3"},
          "auth": {"schema":1,"status":"ok","retry_after_ms":0,"credential_version":42}
        })";
        HttpPayload rejected_key;
        HttpObservation rejected_obs;
        Expect(ParseOtaAuthJson(token_as_key, &rejected_obs, &rejected_key), "parse_token_shaped_key");
        Expect(!rejected_obs.has_auth_key && rejected_key.auth_key.empty(), "wss_token_not_parsed_as_auth_key");
    }
    if (g_failed != 0) {
        std::cerr << g_failed << " failed\n";
        return 1;
    }
    std::cout << "auth connection host tests passed\n";
    return 0;
}
