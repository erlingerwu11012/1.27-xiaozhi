#include "main_ws_submit_policy.h"

namespace main_ws_submit {

PendingTier TierForAction(PendingActionKind action) {
    switch (action) {
        case PendingActionKind::kToggleChatListening:
        case PendingActionKind::kStartManualListening:
        case PendingActionKind::kWakeWordFlow:
            return PendingTier::kManual;
        case PendingActionKind::kInjectChatText:
            return PendingTier::kProactive;
        default:
            return PendingTier::kNone;
    }
}

PendingTier TierForSource(main_ws_open::Source source, bool require_presence) {
    if (!require_presence) {
        return PendingTier::kManual;
    }
    switch (source) {
        case main_ws_open::Source::kManual:
            return PendingTier::kManual;
        default:
            return PendingTier::kProactive;
    }
}

bool ShouldWritePending(const main_ws_open::SubmitResult submit,
                        const PendingTier incoming_tier,
                        const PendingTier existing_tier,
                        const bool has_incoming_intent) {
    if (!has_incoming_intent || incoming_tier == PendingTier::kNone) {
        return false;
    }
    switch (submit) {
        case main_ws_open::SubmitResult::kStarted:
        case main_ws_open::SubmitResult::kUpgradedManual:
            return true;
        case main_ws_open::SubmitResult::kRejectedLowerPriority:
            return false;
        case main_ws_open::SubmitResult::kJoinInflight:
            if (existing_tier == PendingTier::kManual &&
                incoming_tier != PendingTier::kManual) {
                return false;
            }
            if (existing_tier != PendingTier::kNone &&
                existing_tier == incoming_tier) {
                return false;
            }
            if (existing_tier != PendingTier::kNone &&
                incoming_tier < existing_tier) {
                return false;
            }
            return true;
        default:
            return false;
    }
}

bool RunUnitTests() {
    using SR = main_ws_open::SubmitResult;
    using PT = PendingTier;

    if (ShouldWritePending(SR::kRejectedLowerPriority, PT::kProactive, PT::kManual,
                           true)) {
        return false;
    }

    if (!ShouldWritePending(SR::kJoinInflight, PT::kManual, PT::kProactive, true)) {
        return false;
    }
    if (ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kManual, true)) {
        return false;
    }

    if (ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kProactive,
                           true)) {
        return false;
    }
    if (!ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kNone, true)) {
        return false;
    }

    if (!ShouldWritePending(SR::kUpgradedManual, PT::kManual, PT::kProactive,
                            true)) {
        return false;
    }

    if (!ShouldWritePending(SR::kStarted, PT::kManual, PT::kNone, true)) {
        return false;
    }

    if (TierForAction(PendingActionKind::kWakeWordFlow) != PT::kManual) {
        return false;
    }
    if (TierForAction(PendingActionKind::kInjectChatText) != PT::kProactive) {
        return false;
    }
    if (TierForSource(main_ws_open::Source::kManual, false) != PT::kManual) {
        return false;
    }
    if (TierForSource(main_ws_open::Source::kGreeting, true) != PT::kProactive) {
        return false;
    }

    // Scenario 1: manual inflight, greeting rejected — do not overwrite manual pending.
    if (ShouldWritePending(SR::kRejectedLowerPriority, PT::kProactive, PT::kManual,
                           true)) {
        return false;
    }

    // Scenario 2: greeting inflight, manual upgrade — manual pending wins.
    if (!ShouldWritePending(SR::kUpgradedManual, PT::kManual, PT::kProactive, true)) {
        return false;
    }

    // Scenario 3: reminder join while manual pending — no proactive overwrite.
    if (ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kManual, true)) {
        return false;
    }

    // Scenario 4: radar then greeting join same tier — keep first pending only.
    if (ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kProactive,
                           true)) {
        return false;
    }
    if (!ShouldWritePending(SR::kJoinInflight, PT::kProactive, PT::kNone, true)) {
        return false;
    }

    // Scenario 5: manual join while proactive pending — manual replaces.
    if (!ShouldWritePending(SR::kJoinInflight, PT::kManual, PT::kProactive, true)) {
        return false;
    }

    return true;
}

}  // namespace main_ws_submit
