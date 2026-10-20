// Host runtime tests for production face_config_store.cc and
// FaceEnrollmentClient configuration I/O. Compiled against the real
// implementation with FreeRTOS/NVS stubs.

#include <atomic>
#include <chrono>
#include <cstdio>
#include <functional>
#include <string>
#include <thread>
#include <vector>

#include "face_config_host_hooks.h"
#include "face_config_store.h"
#include "face_enrollment_client.h"

namespace {

int g_failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond); \
            ++g_failures;                                                      \
        }                                                                      \
    } while (0)

void SleepMs(int ms) {
    std::this_thread::sleep_for(std::chrono::milliseconds(ms));
}

void WaitUntil(const std::function<bool()>& pred, int timeout_ms) {
    const auto deadline = std::chrono::steady_clock::now() +
                          std::chrono::milliseconds(timeout_ms);
    while (!pred() && std::chrono::steady_clock::now() < deadline) {
        SleepMs(2);
    }
}

FaceEnrollmentClient::CapabilityConfig ValidConfig() {
    FaceEnrollmentClient::CapabilityConfig cfg;
    cfg.session_url = "https://enroll.example.com/session";
    cfg.protocol_version = 1;
    cfg.guided_burst_v1 = false;
    cfg.session_timeout_seconds = 120;
    cfg.required_frames = 3;
    cfg.max_frames = 5;
    cfg.max_frame_bytes = 307200;
    cfg.supports_front_only_v1 = false;
    cfg.supports_user_relative_v1 = false;
    return cfg;
}

FaceEnrollmentClient::CapabilityConfig ValidV2Config() {
    FaceEnrollmentClient::CapabilityConfig cfg;
    cfg.session_url = "https://enroll.example.com/session";
    cfg.protocol_version = 2;
    cfg.guided_burst_v1 = true;
    cfg.session_timeout_seconds = 240;
    cfg.required_frames = 3;
    cfg.max_frames = 3;
    cfg.max_frame_bytes = 307200;
    cfg.supports_front_only_v1 = false;
    cfg.supports_user_relative_v1 = false;
    return cfg;
}

void SeedConfig(const FaceEnrollmentClient::CapabilityConfig& cfg) {
    face_config_host::HostSetString("websocket", "url",
                                    "wss://enroll.example.com/v1");
    face_config_host::HostSetString("websocket", "token", "pair-1");
    face_config_host::HostSetString("face_enrollment", "session_url",
                                    cfg.session_url.c_str());
    face_config_host::HostSetInt("face_enrollment", "proto_ver",
                                 cfg.protocol_version);
    face_config_host::HostSetBool("face_enrollment", "guided_burst",
                                  cfg.guided_burst_v1);
    face_config_host::HostSetInt("face_enrollment", "session_timeout",
                                 cfg.session_timeout_seconds);
    face_config_host::HostSetInt("face_enrollment", "required_frames",
                                 cfg.required_frames);
    face_config_host::HostSetInt("face_enrollment", "max_frames", cfg.max_frames);
    face_config_host::HostSetInt("face_enrollment", "max_frame_bytes",
                                 cfg.max_frame_bytes);
    face_config_host::HostSetBool("face_enrollment", "sup_front_only",
                                  cfg.supports_front_only_v1);
    face_config_host::HostSetBool("face_enrollment", "sup_user_rel",
                                  cfg.supports_user_relative_v1);
}

void SeedValidNvs() { SeedConfig(ValidConfig()); }

void SeedValidV2Nvs() { SeedConfig(ValidV2Config()); }

void CheckV2Persisted() {
    const auto cfg = ValidV2Config();
    CHECK(face_config_host::HostGetString("face_enrollment", "session_url") ==
          cfg.session_url);
    CHECK(face_config_host::HostGetInt("face_enrollment", "proto_ver") == 2);
    CHECK(face_config_host::HostGetBool("face_enrollment", "guided_burst") == true);
    CHECK(face_config_host::HostGetInt("face_enrollment", "session_timeout") ==
          240);
    CHECK(face_config_host::HostGetInt("face_enrollment", "required_frames") == 3);
    CHECK(face_config_host::HostGetInt("face_enrollment", "max_frames") == 3);
    CHECK(face_config_host::HostGetInt("face_enrollment", "max_frame_bytes") ==
          307200);
    CHECK(face_config_host::HostGetBool("face_enrollment", "sup_front_only") ==
          false);
    CHECK(face_config_host::HostGetBool("face_enrollment", "sup_user_rel") ==
          false);
}

void ResetAll() {
    FaceEnrollmentClient::GetInstance().ResetForTest();
    face_config::ResetStoreForTest();
    face_config_host::ResetHooks();
    face_config_host::ClearNvs();
}

void TestConcurrentStartCreatesOneExecutor() {
    ResetAll();
    std::atomic<int> ok{0};
    std::vector<std::thread> threads;
    threads.reserve(8);
    for (int i = 0; i < 8; ++i) {
        threads.emplace_back([&] {
            if (face_config::Start()) ok.fetch_add(1);
        });
    }
    for (auto& t : threads) t.join();
    CHECK(ok.load() == 8);
    CHECK(face_config::IsStoreReadyForTest());
    CHECK(face_config_host::QueueCreateSuccesses() == 1);
    CHECK(face_config_host::TaskCreateSuccesses() == 1);
}

void TestCreateFailThenRetry() {
    ResetAll();
    face_config_host::SetFailNextQueueCreates(1);
    CHECK(!face_config::Start());
    CHECK(!face_config::IsStoreReadyForTest());
    CHECK(face_config_host::QueueCreateSuccesses() == 0);
    CHECK(face_config_host::TaskCreateSuccesses() == 0);

    CHECK(face_config::Start());
    CHECK(face_config::IsStoreReadyForTest());
    CHECK(face_config_host::QueueCreateSuccesses() == 1);
    CHECK(face_config_host::TaskCreateSuccesses() == 1);

    ResetAll();
    face_config_host::SetFailNextTaskCreates(1);
    CHECK(!face_config::Start());
    CHECK(face_config_host::QueueCreateSuccesses() == 1);
    CHECK(face_config_host::TaskCreateSuccesses() == 0);
    CHECK(!face_config::IsStoreReadyForTest());

    CHECK(face_config::Start());
    CHECK(face_config::IsStoreReadyForTest());
    CHECK(face_config_host::QueueCreateSuccesses() == 1);
    CHECK(face_config_host::TaskCreateSuccesses() == 1);
}

void TestValidConfigNotClearedOnTransient() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());

    face_config_host::SetSubmitTimeoutMs(40);
    face_config_host::BlockWorker(true);
    FaceEnrollmentClient::GetInstance().SetCapability(ValidConfig());
    face_config_host::BlockWorker(false);
    WaitUntil([] { return face_config_host::LiveRequestCount() <= 1; }, 500);

    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));
    CHECK(face_config_host::HostGetString("face_enrollment", "session_url") ==
          ValidConfig().session_url);

    FaceEnrollmentClient::GetInstance().ResetForTest();
    face_config_host::SetFailNextAllocs(1);
    FaceEnrollmentClient::GetInstance().SetCapability(ValidConfig());
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));

    FaceEnrollmentClient::GetInstance().ResetForTest();
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
    face_config_host::SetNvsGetError("websocket", "url", true);
    FaceEnrollmentClient::GetInstance().SetCapability(ValidConfig());
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
}

void TestQueueFullDoesNotClear() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());

    face_config_host::SetSubmitTimeoutMs(40);
    face_config_host::BlockWorker(true);
    std::vector<std::thread> blockers;
    std::atomic<int> started{0};
    for (int i = 0; i < 4; ++i) {
        blockers.emplace_back([&] {
            started.fetch_add(1);
            std::string token;
            face_config::LoadPairingToken(&token);
        });
    }
    WaitUntil([&] { return started.load() == 4 && face_config_host::QueueDepth() == 4; },
              500);
    CHECK(face_config_host::QueueDepth() == 4);

    FaceEnrollmentClient::GetInstance().SetCapability(ValidConfig());
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));

    std::string ignored;
    const auto fifth = face_config::LoadPairingToken(&ignored);
    CHECK(fifth == face_config::IoResult::Transient);

    face_config_host::BlockWorker(false);
    for (auto& t : blockers) t.join();
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
}

void TestTransientThenRetrySucceeds() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    face_config_host::SetNvsGetError("face_enrollment", "session_url", true);
    CHECK(!FaceEnrollmentClient::GetInstance().HasValidCapability());
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));

    face_config_host::SetNvsGetError("face_enrollment", "session_url", false);
    CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
    CHECK(FaceEnrollmentClient::GetInstance().GetCapability().session_url ==
          ValidConfig().session_url);
}

void TestInvalidConfigIsErased() {
    ResetAll();
    face_config_host::HostSetString("websocket", "url",
                                    "wss://enroll.example.com/v1");
    face_config_host::HostSetString("face_enrollment", "session_url",
                                    "https://evil.example.com/session");
    face_config_host::HostSetInt("face_enrollment", "proto_ver", 1);
    face_config_host::HostSetInt("face_enrollment", "session_timeout", 120);
    face_config_host::HostSetInt("face_enrollment", "required_frames", 3);
    face_config_host::HostSetInt("face_enrollment", "max_frames", 5);
    face_config_host::HostSetInt("face_enrollment", "max_frame_bytes", 307200);
    CHECK(face_config::Start());
    face_config::CapabilitySnapshot snap;
    CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Invalid);
    CHECK(!snap.valid);
    CHECK(!face_config_host::HostHasKey("face_enrollment", "session_url"));
}

void TestTimeoutDoesNotWriteCallerOutput() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    face_config_host::SetSubmitTimeoutMs(40);
    face_config_host::BlockWorker(true);
    {
        std::string out = "sentinel";
        const auto result = face_config::LoadWebsocketUrl(&out);
        CHECK(result == face_config::IoResult::Transient);
        CHECK(out.empty());
    }
    face_config_host::BlockWorker(false);
    WaitUntil([] { return face_config_host::LiveRequestCount() <= 1; }, 500);
    CHECK(face_config_host::LiveRequestCount() <= 1);
}

void TestTokenAlwaysFresh() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    std::string token;
    CHECK(face_config::LoadPairingToken(&token) == face_config::IoResult::Ok);
    CHECK(token == "pair-1");
    face_config_host::HostSetString("websocket", "token", "pair-2");
    CHECK(face_config::LoadPairingToken(&token) == face_config::IoResult::Ok);
    CHECK(token == "pair-2");
}

void TestWsUrlReadErrorDoesNotEraseFaceConfig() {
    ResetAll();
    SeedValidNvs();
    CHECK(face_config::Start());
    face_config_host::SetNvsGetError("websocket", "url", true);
    face_config::CapabilitySnapshot snap;
    CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Transient);
    CHECK(!snap.valid);
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));
}

void TestV2IntBoolReadErrorIsTransient() {
    struct Field {
        const char* key;
        bool is_bool;
    };
    const Field fields[] = {
        {"proto_ver", false},
        {"guided_burst", true},
        {"session_timeout", false},
        {"required_frames", false},
        {"max_frames", false},
        {"max_frame_bytes", false},
        {"sup_front_only", true},
        {"sup_user_rel", true},
    };
    for (const auto& field : fields) {
        ResetAll();
        SeedValidV2Nvs();
        CHECK(face_config::Start());
        FaceEnrollmentClient::GetInstance().ResetForTest();
        face_config_host::SetNvsGetError("face_enrollment", field.key, true);
        CHECK(!FaceEnrollmentClient::GetInstance().HasValidCapability());
        face_config::CapabilitySnapshot snap;
        CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Transient);
        CHECK(!snap.valid);
        CheckV2Persisted();
        if (field.is_bool) {
            CHECK(face_config_host::HostNvsGetU8Calls("face_enrollment",
                                                     field.key) >= 1);
        } else {
            CHECK(face_config_host::HostNvsGetI32Calls("face_enrollment",
                                                      field.key) >= 1);
        }
        // Transient must not cache an invalid loaded config. Retry without
        // ResetForTest() so loaded_persisted_ is not cleared by the harness.
        face_config_host::SetNvsGetError("face_enrollment", field.key, false);
        CHECK(FaceEnrollmentClient::GetInstance().HasValidCapability());
        const auto loaded = FaceEnrollmentClient::GetInstance().GetCapability();
        CHECK(loaded.protocol_version == 2);
        CHECK(loaded.guided_burst_v1 == true);
        CHECK(loaded.session_timeout_seconds == 240);
        CHECK(loaded.required_frames == 3);
        CHECK(loaded.max_frames == 3);
        CheckV2Persisted();
    }
}

void TestV1MissingIntBoolKeysUseDefaults() {
    ResetAll();
    face_config_host::HostSetString("websocket", "url",
                                    "wss://enroll.example.com/v1");
    face_config_host::HostSetString("face_enrollment", "session_url",
                                    "https://enroll.example.com/session");
    CHECK(face_config::Start());
    face_config::CapabilitySnapshot snap;
    CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Ok);
    CHECK(snap.valid);
    CHECK(snap.config.protocol_version == 1);
    CHECK(snap.config.guided_burst_v1 == false);
    CHECK(snap.config.session_timeout_seconds == 120);
    CHECK(snap.config.required_frames == 3);
    CHECK(snap.config.max_frames == 5);
    CHECK(snap.config.max_frame_bytes == 307200);
    CHECK(snap.config.supports_front_only_v1 == false);
    CHECK(snap.config.supports_user_relative_v1 == false);
    CHECK(face_config_host::HostHasKey("face_enrollment", "session_url"));
}

void TestV2MissingMaxFramesStillValidates() {
    ResetAll();
    const auto cfg = ValidV2Config();
    face_config_host::HostSetString("websocket", "url",
                                    "wss://enroll.example.com/v1");
    face_config_host::HostSetString("face_enrollment", "session_url",
                                    cfg.session_url.c_str());
    face_config_host::HostSetInt("face_enrollment", "proto_ver", 2);
    face_config_host::HostSetBool("face_enrollment", "guided_burst", true);
    face_config_host::HostSetInt("face_enrollment", "session_timeout", 240);
    face_config_host::HostSetInt("face_enrollment", "required_frames", 3);
    face_config_host::HostSetInt("face_enrollment", "max_frame_bytes", 307200);
    CHECK(face_config::Start());
    face_config::CapabilitySnapshot snap;
    CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Invalid);
    CHECK(!snap.valid);
    CHECK(!face_config_host::HostHasKey("face_enrollment", "session_url"));
}

void TestV2InvalidMaxFramesIsErased() {
    ResetAll();
    SeedValidV2Nvs();
    face_config_host::HostSetInt("face_enrollment", "max_frames", 5);
    CHECK(face_config::Start());
    face_config::CapabilitySnapshot snap;
    CHECK(face_config::LoadCapability(&snap) == face_config::IoResult::Invalid);
    CHECK(!snap.valid);
    CHECK(!face_config_host::HostHasKey("face_enrollment", "session_url"));
}

FaceEnrollmentClient::SessionInfo MakeGuidedSession(int required_frames,
                                                    bool front_only,
                                                    bool user_relative) {
    FaceEnrollmentClient::SessionInfo session;
    session.session_id = "sess-1";
    session.guided_burst_v1 = true;
    session.required_frames = required_frames;
    session.max_frames = required_frames;
    if (front_only) session.capture_mode = "front_only_v1";
    if (user_relative) session.guidance_profile = "user_relative_v1";
    return session;
}

void ExpectGuided(bool expect_ok, const FaceEnrollmentClient::SessionInfo& session,
                  const char* code, int accepted, bool draft,
                  const char* expect_reason = nullptr) {
    std::string reason;
    const bool ok = FaceEnrollmentClient::ValidateGuidedResponse(
        session, true, session.session_id, code, accepted, draft, &reason);
    CHECK(ok == expect_ok);
    if (!expect_ok && expect_reason) {
        CHECK(reason == expect_reason);
    }
    if (expect_ok) {
        CHECK(FaceEnrollmentClient::IsGuidedEnrollmentComplete(
                  session, code, accepted, draft) ==
              (draft && std::string(code) == "DRAFT_READY" &&
               accepted == session.required_frames));
    }
}

void TestValidateGuidedResponseCompletionAndQuota() {
    // A/B: legal completion for front_only and three-pose.
    ExpectGuided(true, MakeGuidedSession(1, true, true), "DRAFT_READY", 1, true);
    ExpectGuided(true, MakeGuidedSession(3, false, false), "DRAFT_READY", 3,
                 true);

    // C: contradictory continue-after-full for front_only.
    ExpectGuided(false, MakeGuidedSession(1, true, true), "CAPTURE_FRONT", 1,
                 false, "quota_full_continue_forbidden");
    ExpectGuided(false, MakeGuidedSession(1, true, true), "RECAPTURE_FRONT", 1,
                 false, "quota_full_continue_forbidden");
    ExpectGuided(false, MakeGuidedSession(1, true, true), "DRAFT_READY", 0, true,
                 "draft_inconsistent");
    ExpectGuided(false, MakeGuidedSession(1, true, true), "DRAFT_READY", 1,
                 false, "draft_inconsistent");
    ExpectGuided(false, MakeGuidedSession(1, true, true), "CAPTURE_FRONT", 1,
                 true, "draft_inconsistent");
    ExpectGuided(false, MakeGuidedSession(1, true, true), "NO_FACE", 2, false,
                 "accepted_count_oob");

    // Terminal codes remain allowed when quota is full but draft is false.
    ExpectGuided(true, MakeGuidedSession(1, true, true), "POSE_FAILED", 1,
                 false);
    ExpectGuided(true, MakeGuidedSession(1, true, true), "TIMEOUT", 1, false);
    ExpectGuided(true, MakeGuidedSession(3, false, false), "SERVICE_ERROR", 3,
                 false);

    // D: three-pose mid-progress and side poses still legal.
    ExpectGuided(true, MakeGuidedSession(3, false, false), "CAPTURE_LEFT", 1,
                 false);
    ExpectGuided(true, MakeGuidedSession(3, false, false), "RECAPTURE_RIGHT", 2,
                 false);
    ExpectGuided(true, MakeGuidedSession(3, false, false), "MOVE_SCREEN_LEFT", 0,
                 false);

    // front_only rejects side pose; unnegotiated MOVE_USER rejected.
    ExpectGuided(false, MakeGuidedSession(1, true, true), "CAPTURE_LEFT", 0,
                 false, "front_only_side_pose_forbidden");
    ExpectGuided(false, MakeGuidedSession(1, true, false), "MOVE_USER_LEFT", 0,
                 false, "user_relative_not_negotiated");
    ExpectGuided(true, MakeGuidedSession(1, true, true), "MOVE_USER_RIGHT", 0,
                 false);

    // Completion helper must require the exact triple.
    auto front = MakeGuidedSession(1, true, false);
    CHECK(FaceEnrollmentClient::IsGuidedEnrollmentComplete(
        front, "DRAFT_READY", 1, true));
    CHECK(!FaceEnrollmentClient::IsGuidedEnrollmentComplete(
        front, "DRAFT_READY", 1, false));
    CHECK(!FaceEnrollmentClient::IsGuidedEnrollmentComplete(
        front, "CAPTURE_FRONT", 1, true));
    CHECK(!FaceEnrollmentClient::IsGuidedEnrollmentComplete(
        front, "DRAFT_READY", 0, true));
}

}  // namespace

int main() {
    TestConcurrentStartCreatesOneExecutor();
    TestCreateFailThenRetry();
    TestValidConfigNotClearedOnTransient();
    TestQueueFullDoesNotClear();
    TestTransientThenRetrySucceeds();
    TestInvalidConfigIsErased();
    TestTimeoutDoesNotWriteCallerOutput();
    TestTokenAlwaysFresh();
    TestWsUrlReadErrorDoesNotEraseFaceConfig();
    TestV2IntBoolReadErrorIsTransient();
    TestV1MissingIntBoolKeysUseDefaults();
    TestV2MissingMaxFramesStillValidates();
    TestV2InvalidMaxFramesIsErased();
    TestValidateGuidedResponseCompletionAndQuota();
    ResetAll();
    if (g_failures != 0) {
        std::fprintf(stderr, "%d host checks failed\n", g_failures);
        return 1;
    }
    std::printf("ALL HOST TESTS PASSED\n");
    return 0;
}
