#pragma once

#include "face_enrollment_client.h"

#include <cstdint>
#include <string>

// Face-enrollment NVS/Flash I/O executed on an internal-SRAM task stack.
// Callers may run on PSRAM stacks; this module never opens an NVS handle on
// the caller's stack or returns a live handle to the caller.
namespace face_config {

enum class IoResult : uint8_t {
    Ok = 0,       // read succeeded and the value is usable
    NotFound,     // confirmed missing (namespace/key does not exist)
    Invalid,      // persisted content failed validation (and was erased)
    Transient,    // timeout, queue full, alloc failure, or NVS I/O error
};

struct CapabilitySnapshot {
    FaceEnrollmentClient::CapabilityConfig config;
    bool valid = false;
    IoResult result = IoResult::Transient;
};

// Creates the internal-SRAM worker. Safe to call more than once.
// At most one queue and one face_cfg task exist. Failed Start() leaves a
// consistent state that a later call may retry.
bool Start();
bool EnsureReady();

// Each call reads the latest websocket pairing token. Never caches the value.
// Transient leaves *out empty. NotFound also leaves *out empty.
IoResult LoadPairingToken(std::string* out);

// Latest websocket URL. Used to keep host-match checks off PSRAM stacks.
IoResult LoadWebsocketUrl(std::string* out);

// Reads persisted capability. Invalid persisted values are erased here.
// Transient I/O (including websocket URL read errors) never erases.
IoResult LoadCapability(CapabilitySnapshot* out);

// Persist/clear return false on executor or NVS-open failure. Callers keep
// in-memory state (existing nvs_unavailable semantics).
bool SaveCapability(const FaceEnrollmentClient::CapabilityConfig& config);
bool ClearCapability();

}  // namespace face_config
