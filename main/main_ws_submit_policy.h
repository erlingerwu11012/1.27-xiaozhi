#ifndef MAIN_WS_SUBMIT_POLICY_H_
#define MAIN_WS_SUBMIT_POLICY_H_

#include "main_ws_open_arbiter.h"

#include <cstdint>

namespace main_ws_submit {

enum class PendingTier : uint8_t {
    kNone = 0,
    kProactive,
    kManual,
};

enum class PendingActionKind : uint8_t {
    kNone = 0,
    kInjectChatText,
    kToggleChatListening,
    kStartManualListening,
    kWakeWordFlow,
};

PendingTier TierForAction(PendingActionKind action);
PendingTier TierForSource(main_ws_open::Source source, bool require_presence);

/** True when caller may write pending fields after arbiter submit. */
bool ShouldWritePending(main_ws_open::SubmitResult submit,
                        PendingTier incoming_tier, PendingTier existing_tier,
                        bool has_incoming_intent);

/** Runs in-process unit tests; returns true when all pass. */
bool RunUnitTests();

}  // namespace main_ws_submit

#endif  // MAIN_WS_SUBMIT_POLICY_H_
