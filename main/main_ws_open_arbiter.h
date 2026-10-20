#ifndef MAIN_WS_OPEN_ARBITER_H_
#define MAIN_WS_OPEN_ARBITER_H_

#include <cstdint>
#include <mutex>

/** Thread-safe single-flight state for primary WebSocket open requests. */
namespace main_ws_open {

enum class Source : uint8_t {
    kManual = 0,
    kRadar,
    kReminder,
    kGreeting,
};

enum class SubmitResult : uint8_t {
    kStarted = 0,
    kJoinInflight,
    kUpgradedManual,
    kRejectedLowerPriority,
};

const char* SourceName(Source source);

struct WorkerSnapshot {
    uint32_t request_id = 0;
    uint32_t presence_generation = 0;
    bool require_presence = true;
    Source source = Source::kRadar;
};

struct ArbiterState {
    mutable std::mutex mutex;
    uint32_t next_request_id = 1;
    uint32_t active_request_id = 0;
    bool inflight = false;
    /** Live flag; may be upgraded false while worker runs (manual priority). */
    bool require_presence = true;
    uint32_t presence_generation = 0;
    Source source = Source::kRadar;
};

/**
 * Begin or join an open request under the arbiter lock (short hold).
 * When kStarted, out_snapshot is filled for the worker task.
 */
SubmitResult SubmitRequest(ArbiterState& state, Source source,
                           bool require_presence, uint32_t presence_generation,
                           WorkerSnapshot* out_snapshot);

bool IsActiveRequest(const ArbiterState& state, uint32_t request_id);

/** True when a completed worker belongs to a superseded request. */
bool IsStaleRequest(const ArbiterState& state, uint32_t request_id);

/**
 * Discard when request_id is not active, or presence-bound open is stale.
 * Uses current require_presence (post-upgrade), not the worker snapshot flag.
 */
bool ShouldDiscardStale(const ArbiterState& state, uint32_t request_id,
                        uint32_t snapshot_generation, bool radar_present,
                        uint32_t current_generation);

void ClearInflight(ArbiterState& state, uint32_t request_id);

bool IsInflight(const ArbiterState& state);

uint32_t GetActiveRequestId(const ArbiterState& state);

bool GetRequirePresence(const ArbiterState& state);

/** Runs in-process unit tests; returns true when all pass. */
bool RunUnitTests();

}  // namespace main_ws_open

#endif  // MAIN_WS_OPEN_ARBITER_H_
