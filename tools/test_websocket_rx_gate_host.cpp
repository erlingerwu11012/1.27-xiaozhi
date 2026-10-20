// Host tests for production websocket_connection_gate.cc text dispatch path.
#include <atomic>
#include <chrono>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>

#include "websocket_connection_gate.h"
#include "vision_credentials.h"

namespace {

int g_failures = 0;

#define CHECK(cond)                                                            \
    do {                                                                       \
        if (!(cond)) {                                                         \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__,       \
                         #cond);                                               \
            ++g_failures;                                                      \
        }                                                                      \
    } while (0)

std::string MakeHello(const char* session_id) {
    return std::string("{\"type\":\"hello\",\"transport\":\"websocket\","
                       "\"session_id\":\"") +
           session_id + "\"}";
}

WebsocketTextDispatchHandlers MakeHandlers(
    std::function<void(const cJSON*)> on_hello,
    std::function<void(const cJSON*, uint32_t)> on_other = nullptr) {
    WebsocketTextDispatchHandlers h;
    h.on_hello = std::move(on_hello);
    h.on_terminal_auth = nullptr;
    h.on_other = std::move(on_other);
    return h;
}

void TestStaleHelloCannotRewriteNewSessionOrSignalReady() {
    WebsocketConnectionGate gate;
    std::string session_id;
    int hello_ready_events = 0;
    int other_forwarded = 0;
    VisionCredentialStore& store = VisionCredentialStore::GetInstance();
    const uint32_t gen1 = store.BeginConnection();
    gate.Begin(gen1, &session_id);

    {
        const std::string hello = MakeHello("sess-new");
        const auto result = DispatchWebsocketTextFrame(
            gate, gen1, hello.data(), hello.size(),
            MakeHandlers(
                [&](const cJSON* root) {
                    auto* sid = cJSON_GetObjectItem(root, "session_id");
                    if (cJSON_IsString(sid) && sid->valuestring) {
                        session_id = sid->valuestring;
                    }
                    ++hello_ready_events;
                    store.ApplyHelloSession(gen1, session_id);
                },
                [&](const cJSON*, uint32_t) { ++other_forwarded; }));
        CHECK(result == WebsocketTextDispatchResult::kHelloApplied);
        CHECK(session_id == "sess-new");
        CHECK(hello_ready_events == 1);
    }

    const uint32_t gen2 = store.BeginConnection();
    gate.Begin(gen2, &session_id);
    CHECK(session_id.empty());
    CHECK(hello_ready_events == 1);

    store.ApplyHelloSession(gen2, "sess-live");
    session_id = "sess-live";
    store.ApplyInitializeVision(
        gen2, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-live", "", 0);

    {
        const std::string stale = MakeHello("sess-stale");
        const auto result = DispatchWebsocketTextFrame(
            gate, gen1, stale.data(), stale.size(),
            MakeHandlers(
                [&](const cJSON* root) {
                    auto* sid = cJSON_GetObjectItem(root, "session_id");
                    if (cJSON_IsString(sid) && sid->valuestring) {
                        session_id = sid->valuestring;
                    }
                    ++hello_ready_events;
                },
                [&](const cJSON*, uint32_t) { ++other_forwarded; }));
        CHECK(result == WebsocketTextDispatchResult::kDiscardedStale);
    }

    CHECK(session_id == "sess-live");
    CHECK(hello_ready_events == 1);
    CHECK(other_forwarded == 0);
    VisionCredentialSnapshot snap;
    CHECK(store.TryAcquireExplainSnapshot(&snap));
    CHECK(snap.session_id == "sess-live");
    CHECK(snap.token == "token-live");
    CHECK(snap.connection_generation == gen2);
}

void TestEndedGenerationDropsHello() {
    WebsocketConnectionGate gate;
    std::string session_id = "keep";
    int hello_ready_events = 0;
    gate.Begin(7, &session_id);
    CHECK(session_id.empty());
    session_id = "open";
    CHECK(gate.End(7, &session_id));
    CHECK(session_id.empty());

    const std::string hello = MakeHello("after-end");
    const auto result = DispatchWebsocketTextFrame(
        gate, 7, hello.data(), hello.size(),
        MakeHandlers([&](const cJSON*) {
            session_id = "rewritten";
            ++hello_ready_events;
        }));
    CHECK(result == WebsocketTextDispatchResult::kDiscardedStale);
    CHECK(session_id.empty());
    CHECK(hello_ready_events == 0);
}

void TestBeginWaitsForInFlightAdmissionThenClearsSession() {
    WebsocketConnectionGate gate;
    std::string session_id;
    gate.Begin(1, &session_id);

    std::atomic<bool> holding{false};
    std::thread rx([&]() {
        auto admission = gate.TryAdmit(1);
        CHECK(static_cast<bool>(admission));
        holding.store(true);
        std::this_thread::sleep_for(std::chrono::milliseconds(80));
        session_id = "from-old-admission";
    });

    while (!holding.load()) {
        std::this_thread::yield();
    }
    const auto started = std::chrono::steady_clock::now();
    gate.Begin(2, &session_id);
    const auto elapsed = std::chrono::steady_clock::now() - started;
    rx.join();
    CHECK(elapsed > std::chrono::milliseconds(40));
    CHECK(session_id.empty());
    CHECK(gate.IsAccepting(2));
    CHECK(!gate.IsAccepting(1));
}

// on_other must not keep the gate locked: Begin/End / SendText must proceed.
void TestOtherCallbackReleasesGateBeforeHandler() {
    WebsocketConnectionGate gate;
    std::string session_id;
    gate.Begin(1, &session_id);

    std::atomic<bool> in_other{false};
    std::atomic<bool> begin_done{false};
    std::thread rx([&]() {
        const std::string mcp =
            "{\"type\":\"mcp\",\"payload\":{\"method\":\"initialize\"}}";
        const auto result = DispatchWebsocketTextFrame(
            gate, 1, mcp.data(), mcp.size(),
            MakeHandlers(
                nullptr,
                [&](const cJSON*, uint32_t gen) {
                    CHECK(gen == 1);
                    in_other.store(true);
                    // If the gate were still held, Begin(2) below would block
                    // until this handler returns — hang the test.
                    while (!begin_done.load()) {
                        std::this_thread::yield();
                    }
                }));
        CHECK(result == WebsocketTextDispatchResult::kForwarded);
    });

    while (!in_other.load()) {
        std::this_thread::yield();
    }
    gate.Begin(2, &session_id);
    CHECK(session_id.empty());
    CHECK(gate.IsAccepting(2));
    begin_done.store(true);
    rx.join();
}

}  // namespace

int main() {
    TestStaleHelloCannotRewriteNewSessionOrSignalReady();
    TestEndedGenerationDropsHello();
    TestBeginWaitsForInFlightAdmissionThenClearsSession();
    TestOtherCallbackReleasesGateBeforeHandler();
    if (g_failures) {
        std::fprintf(stderr, "%d checks failed\n", g_failures);
        return 1;
    }
    std::puts("PASS: websocket rx gate / stale hello dispatch host tests");
    return 0;
}
