#include "main_ws_open_arbiter.h"

namespace main_ws_open {

const char* SourceName(Source source) {
    switch (source) {
        case Source::kManual:
            return "manual";
        case Source::kRadar:
            return "radar";
        case Source::kReminder:
            return "reminder";
        case Source::kGreeting:
            return "greeting";
        default:
            return "unknown";
    }
}

SubmitResult SubmitRequest(ArbiterState& state, Source source,
                           bool require_presence, uint32_t presence_generation,
                           WorkerSnapshot* out_snapshot) {
    std::lock_guard<std::mutex> lock(state.mutex);

    if (state.inflight) {
        if (!require_presence) {
            if (state.require_presence) {
                state.require_presence = false;
                state.source = source;
                return SubmitResult::kUpgradedManual;
            }
            return SubmitResult::kJoinInflight;
        }
        if (!state.require_presence) {
            return SubmitResult::kRejectedLowerPriority;
        }
        return SubmitResult::kJoinInflight;
    }

    const uint32_t request_id = state.next_request_id++;
    state.active_request_id = request_id;
    state.inflight = true;
    state.require_presence = require_presence;
    state.presence_generation = presence_generation;
    state.source = source;

    if (out_snapshot != nullptr) {
        out_snapshot->request_id = request_id;
        out_snapshot->presence_generation = presence_generation;
        out_snapshot->require_presence = require_presence;
        out_snapshot->source = source;
    }
    return SubmitResult::kStarted;
}

bool IsActiveRequest(const ArbiterState& state, uint32_t request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.inflight && state.active_request_id == request_id;
}

bool IsStaleRequest(const ArbiterState& state, uint32_t request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return !state.inflight || state.active_request_id != request_id;
}

bool ShouldDiscardStale(const ArbiterState& state, uint32_t request_id,
                          uint32_t snapshot_generation, bool radar_present,
                          uint32_t current_generation) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (!state.inflight || state.active_request_id != request_id) {
        return true;
    }
    if (!state.require_presence) {
        return false;
    }
    if (!radar_present) {
        return true;
    }
    return snapshot_generation != current_generation;
}

void ClearInflight(ArbiterState& state, uint32_t request_id) {
    std::lock_guard<std::mutex> lock(state.mutex);
    if (state.active_request_id == request_id) {
        state.inflight = false;
        state.active_request_id = 0;
    }
}

bool IsInflight(const ArbiterState& state) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.inflight;
}

uint32_t GetActiveRequestId(const ArbiterState& state) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.active_request_id;
}

bool GetRequirePresence(const ArbiterState& state) {
    std::lock_guard<std::mutex> lock(state.mutex);
    return state.require_presence;
}

bool RunUnitTests() {
    {
        ArbiterState st;
        WorkerSnapshot snap{};
        int open_calls = 0;
        auto mark_open = [&]() { ++open_calls; };

        const SubmitResult r1 =
            SubmitRequest(st, Source::kManual, false, 1, &snap);
        if (r1 != SubmitResult::kStarted) return false;
        mark_open();

        const SubmitResult r2 =
            SubmitRequest(st, Source::kRadar, true, 1, &snap);
        if (r2 != SubmitResult::kJoinInflight) return false;

        const SubmitResult r3 =
            SubmitRequest(st, Source::kReminder, true, 1, &snap);
        if (r3 != SubmitResult::kJoinInflight) return false;
        if (open_calls != 1) return false;
        ClearInflight(st, snap.request_id);
    }

    {
        ArbiterState st;
        WorkerSnapshot radar_snap{};
        SubmitRequest(st, Source::kRadar, true, 5, &radar_snap);

        const SubmitResult up =
            SubmitRequest(st, Source::kManual, false, 5, &radar_snap);
        if (up != SubmitResult::kUpgradedManual) return false;
        if (GetRequirePresence(st)) return false;
        if (ShouldDiscardStale(st, radar_snap.request_id,
                               radar_snap.presence_generation,
                               /*radar_present=*/false,
                               /*current_generation=*/99)) {
            return false;
        }
        ClearInflight(st, radar_snap.request_id);
    }

    {
        ArbiterState st;
        WorkerSnapshot s1{};
        SubmitRequest(st, Source::kRadar, true, 2, &s1);
        ClearInflight(st, s1.request_id);

        WorkerSnapshot s2{};
        SubmitRequest(st, Source::kRadar, true, 3, &s2);
        if (!IsStaleRequest(st, s1.request_id)) return false;
        if (!IsActiveRequest(st, s2.request_id)) return false;
        ClearInflight(st, s2.request_id);
    }

    {
        ArbiterState st;
        WorkerSnapshot snap{};
        SubmitRequest(st, Source::kRadar, true, 7, &snap);
        if (!ShouldDiscardStale(st, snap.request_id, 7,
                                /*radar_present=*/false, 7)) {
            return false;
        }
        ClearInflight(st, snap.request_id);
    }

    {
        ArbiterState st;
        WorkerSnapshot snap{};
        SubmitRequest(st, Source::kManual, false, 1, &snap);
        const SubmitResult rej =
            SubmitRequest(st, Source::kRadar, true, 1, &snap);
        if (rej != SubmitResult::kRejectedLowerPriority) return false;
        ClearInflight(st, snap.request_id);
    }

    return true;
}

}  // namespace main_ws_open
