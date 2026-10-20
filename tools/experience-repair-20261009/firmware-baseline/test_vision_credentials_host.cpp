// Host runtime tests for production vision_credentials.cc and http bounded read.
#include <algorithm>
#include <atomic>
#include <cstdio>
#include <cstring>
#include <string>
#include <thread>
#include <vector>

#include "http.h"
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

VisionCredentialStore& Store() { return VisionCredentialStore::GetInstance(); }

void ResetStore() {
    // Drive the singleton through public API to a clean not-ready state.
    const uint32_t gen = Store().BeginConnection();
    Store().EndConnection(gen);
}

void TestInitialConnectReady() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-A");
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-A", "", 0);
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(Store().TryAcquireIdentitySnapshot(&snap));
    CHECK(snap.session_id == "sess-A");
    CHECK(snap.token == "token-A");
    CHECK(snap.connection_generation == gen);
    CHECK(snap.explain_ready);
    CHECK(snap.identity_ready);
}

void TestReconnectInvalidatesUntilNewReady() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    Store().ApplyHelloSession(gen1, "sess-old");
    Store().ApplyInitializeVision(
        gen1, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-old", "", 0);
    VisionCredentialSnapshot snap;
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.token == "token-old");

    Store().EndConnection(gen1);
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    CHECK(!Store().IsIdentityReady());

    const uint32_t gen2 = Store().BeginConnection();
    Store().ApplyHelloSession(gen2, "sess-new");
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));  // hello only
    Store().ApplyInitializeVision(
        gen2, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-new", "", 0);
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.session_id == "sess-new");
    CHECK(snap.token == "token-new");
    CHECK(snap.connection_generation == gen2);
}

void TestHelloWithoutInitialize() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-A");
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    CHECK(!Store().TryAcquireIdentitySnapshot(&snap));
}

void TestInitializeBeforeHello() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-A", "", 0);
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    Store().ApplyHelloSession(gen, "sess-A");
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.session_id == "sess-A");
    CHECK(snap.token == "token-A");
}

void TestStaleInitializeIgnored() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    Store().ApplyHelloSession(gen1, "sess-1");
    Store().ApplyInitializeVision(
        gen1, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-1", "", 0);

    const uint32_t gen2 = Store().BeginConnection();
    Store().ApplyHelloSession(gen2, "sess-2");
    Store().ApplyInitializeVision(
        gen2, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-2", "", 0);

    // Late initialize from gen1 must not overwrite gen2.
    Store().ApplyInitializeVision(
        gen1, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-stale", "", 0);

    VisionCredentialSnapshot snap;
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.token == "token-2");
    CHECK(snap.session_id == "sess-2");
    CHECK(snap.connection_generation == gen2);
}

void TestStaleCloseIgnored() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    const uint32_t gen2 = Store().BeginConnection();
    Store().ApplyHelloSession(gen2, "sess-2");
    Store().ApplyInitializeVision(
        gen2, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-2", "", 0);
    Store().EndConnection(gen1);  // stale
    VisionCredentialSnapshot snap;
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.token == "token-2");
}

void TestConcurrentSnapshotAtomic() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-A");
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-A", "", 0);

    std::atomic<int> mixed{0};
    std::atomic<int> ok{0};
    std::thread reader([&]() {
        for (int i = 0; i < 2000; ++i) {
            VisionCredentialSnapshot snap;
            if (!Store().TryAcquireExplainSnapshot(&snap)) continue;
            const bool a = snap.token == "token-A" && snap.session_id == "sess-A";
            const bool b = snap.token == "token-B" && snap.session_id == "sess-B";
            if (a || b) {
                ++ok;
            } else {
                ++mixed;
            }
        }
    });
    std::thread writer([&]() {
        for (int i = 0; i < 200; ++i) {
            const uint32_t g = Store().BeginConnection();
            if (i % 2 == 0) {
                Store().ApplyHelloSession(g, "sess-A");
                Store().ApplyInitializeVision(
                    g, "https://v.example/mcp/vision/explain",
                    "https://v.example/mcp/vision/identify", "token-A", "", 0);
            } else {
                Store().ApplyInitializeVision(
                    g, "https://v.example/mcp/vision/explain",
                    "https://v.example/mcp/vision/identify", "token-B", "", 0);
                Store().ApplyHelloSession(g, "sess-B");
            }
        }
    });
    reader.join();
    writer.join();
    CHECK(mixed.load() == 0);
    CHECK(ok.load() > 0);
}

void TestInFlightKeepsOldSnapshot() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    Store().ApplyHelloSession(gen1, "sess-1");
    Store().ApplyInitializeVision(
        gen1, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-1", "", 0);
    VisionCredentialSnapshot in_flight;
    CHECK(Store().TryAcquireExplainSnapshot(&in_flight));

    const uint32_t gen2 = Store().BeginConnection();
    Store().ApplyHelloSession(gen2, "sess-2");
    Store().ApplyInitializeVision(
        gen2, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-2", "", 0);

    CHECK(in_flight.token == "token-1");
    CHECK(in_flight.session_id == "sess-1");
    CHECK(in_flight.connection_generation == gen1);
    VisionCredentialSnapshot now;
    CHECK(Store().TryAcquireExplainSnapshot(&now));
    CHECK(now.token == "token-2");
}

void TestVisionSessionMismatchRejected() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-hello");
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-X", "sess-other", 0);
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    CHECK(!Store().IsIdentityReady());
}

void TestSameConnectionWakeDoesNotClear() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-A");
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-A", "", 0);
    // Same generation hello again (wake, not reconnect).
    Store().ApplyHelloSession(gen, "sess-A");
    VisionCredentialSnapshot snap;
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.token == "token-A");
}

void TestExplainAndIdentifyShareLifecycle() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().ApplyHelloSession(gen, "sess-A");
    Store().ApplyInitializeVision(
        gen, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", "token-A", "sess-A", 0);
    VisionCredentialSnapshot explain;
    VisionCredentialSnapshot identity;
    CHECK(Store().TryAcquireExplainSnapshot(&explain));
    CHECK(Store().TryAcquireIdentitySnapshot(&identity));
    CHECK(explain.token == identity.token);
    CHECK(explain.session_id == identity.session_id);
    CHECK(explain.connection_generation == identity.connection_generation);
    Store().EndConnection(gen);
    CHECK(!Store().TryAcquireExplainSnapshot(&explain));
    CHECK(!Store().TryAcquireIdentitySnapshot(&identity));
}

// Simulates production: WS OnData captures source_gen, Application passes it to
// McpServer::ParseMessage → ApplyInitializeVision(source_gen). Never reads
// active_generation() at consume time.
void DeliverInitializeLikeProductionCallChain(uint32_t source_generation,
                                              const char* token) {
    Store().ApplyInitializeVision(
        source_generation, "https://v.example/mcp/vision/explain",
        "https://v.example/mcp/vision/identify", token, "", 0);
}

void TestLateInitializeCannotAdoptNewGeneration() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    // Message received on gen1 — capture at entry (production OnData).
    const uint32_t source_gen = gen1;

    const uint32_t gen2 = Store().BeginConnection();
    Store().ApplyHelloSession(gen2, "sess-new");
    // Late initialize still carries source_gen=gen1 (not active_generation()).
    DeliverInitializeLikeProductionCallChain(source_gen, "token-old");
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    CHECK(Store().IsGenerationAccepting(gen2));
    CHECK(!Store().IsGenerationAccepting(gen1));

    // Contrast: wrongly using active_generation() would publish mismatch.
    // Correct path waits for gen2's own initialize.
    DeliverInitializeLikeProductionCallChain(gen2, "token-new");
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.token == "token-new");
    CHECK(snap.session_id == "sess-new");
    CHECK(snap.connection_generation == gen2);
}

void TestEndSealsGenerationAgainstRepublish() {
    ResetStore();
    const uint32_t gen = Store().BeginConnection();
    Store().EndConnection(gen);
    CHECK(!Store().IsGenerationAccepting(gen));
    Store().ApplyHelloSession(gen, "sess-A");
    DeliverInitializeLikeProductionCallChain(gen, "token-A");
    VisionCredentialSnapshot snap;
    CHECK(!Store().TryAcquireExplainSnapshot(&snap));
    CHECK(!Store().IsExplainReady());
    CHECK(!Store().IsIdentityReady());
}

void TestStaleCloseCannotClearNewSessionSlot() {
    ResetStore();
    const uint32_t gen1 = Store().BeginConnection();
    std::string session_id = "sess-old";
    uint32_t connection_generation = gen1;

    const uint32_t gen2 = Store().BeginConnection();
    connection_generation = gen2;
    session_id = "sess-new";
    Store().ApplyHelloSession(gen2, session_id);
    DeliverInitializeLikeProductionCallChain(gen2, "token-new");

    // Stale disconnect from gen1 must not own the protocol slot.
    CHECK(!ConnectionGenerationOwnsSlot(gen1, connection_generation));
    if (ConnectionGenerationOwnsSlot(gen1, connection_generation)) {
        session_id.clear();  // would be the bug
    }
    CHECK(session_id == "sess-new");

    VisionCredentialStore::GetInstance().EndConnection(gen1);
    VisionCredentialSnapshot snap;
    CHECK(Store().TryAcquireExplainSnapshot(&snap));
    CHECK(snap.session_id == "sess-new");
    CHECK(snap.token == "token-new");
}

struct CountingHttp : Http {
    std::string payload;
    size_t offset = 0;
    int close_count = 0;
    size_t max_bytes_seen = 0;

    void SetHeader(const char*, const char*) override {}
    void SetContent(std::string&&) override {}
    bool Open(const char*, const std::string&) override { return true; }
    int Write(const char*, size_t) override { return 0; }
    int GetStatusCode() override { return 403; }
    int GetBodyLength() override { return static_cast<int>(payload.size()); }
    int Read(char* buffer, size_t len) override {
        if (offset >= payload.size()) return 0;
        const size_t n =
            std::min(len, payload.size() - offset);
        std::memcpy(buffer, payload.data() + offset, n);
        offset += n;
        max_bytes_seen = std::max(max_bytes_seen, offset);
        return static_cast<int>(n);
    }
    std::string ReadAll() override {
        // Production error path must not call this for bounded reads.
        std::string all = payload.substr(offset);
        offset = payload.size();
        max_bytes_seen = payload.size();
        return all;
    }
    void Close() override { ++close_count; }
};

void TestBoundedErrorBodyDoesNotBufferAll() {
    CountingHttp http;
    http.payload.assign(64 * 1024, 'X');
    bool truncated = false;
    const std::string got = ReadHttpBodyBounded(&http, 512, &truncated);
    CHECK(truncated);
    CHECK(got.size() == 512);
    // At most limit + 1 probe byte may be pulled from the transport.
    CHECK(http.max_bytes_seen <= 513);
    CHECK(http.close_count == 1);
    CHECK(http.offset < http.payload.size());  // remainder never fully read
}

}  // namespace

int main() {
    TestInitialConnectReady();
    TestReconnectInvalidatesUntilNewReady();
    TestHelloWithoutInitialize();
    TestInitializeBeforeHello();
    TestStaleInitializeIgnored();
    TestStaleCloseIgnored();
    TestConcurrentSnapshotAtomic();
    TestInFlightKeepsOldSnapshot();
    TestVisionSessionMismatchRejected();
    TestSameConnectionWakeDoesNotClear();
    TestExplainAndIdentifyShareLifecycle();
    TestLateInitializeCannotAdoptNewGeneration();
    TestEndSealsGenerationAgainstRepublish();
    TestStaleCloseCannotClearNewSessionSlot();
    TestBoundedErrorBodyDoesNotBufferAll();
    if (g_failures) {
        std::fprintf(stderr, "%d checks failed\n", g_failures);
        return 1;
    }
    std::puts("PASS: vision_credentials lifecycle host tests");
    return 0;
}
