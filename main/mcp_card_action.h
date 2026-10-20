#pragma once

#include <cstdint>
#include <string>

enum class McpCardAction {
    kPrimary,
    kSecondary,
    kTertiary,
};

struct McpCardActionResult {
    bool handled;
    std::string message;
};

// Executes a local UI action against the exact immutable card snapshot.
McpCardActionResult ExecuteMcpCardAction(const std::string& instance_id,
                                         uint32_t revision,
                                         McpCardAction action);

// Compatibility entry point for cloud card.action. It snapshots the current
// card first, then delegates to the identity-bound entry point above.
McpCardActionResult ExecuteCurrentMcpCardAction(McpCardAction action);

// Returns a small JSON description for the cloud assistant, or {"active":false}.
std::string GetCurrentMcpCardContext();
