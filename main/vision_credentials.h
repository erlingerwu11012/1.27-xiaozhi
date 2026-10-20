#pragma once

#include <cstdint>
#include <mutex>
#include <string>

// Atomic vision credential snapshot for explain + identify HTTP uploads.
// URL / token / session_id / generation are replaced and read as one unit so a
// reconnect cannot pair a new Session-Id header with a prior connection's token.
struct VisionCredentialSnapshot {
    std::string explain_url;
    std::string identity_url;
    std::string token;
    std::string session_id;
    uint32_t connection_generation = 0;
    int64_t expires_at = 0;  // unix seconds; 0 = not provided
    bool explain_ready = false;
    bool identity_ready = false;
};

// True when a disconnect/close callback still owns the protocol object's
// current connection slot (stale closes must not clear the new session).
inline bool ConnectionGenerationOwnsSlot(uint32_t source_generation,
                                         uint32_t current_generation) {
    return source_generation != 0 && source_generation == current_generation;
}

class VisionCredentialStore {
public:
    static VisionCredentialStore& GetInstance();

    // Begin a new audio-channel attempt. Invalidates prior credentials and
    // opens the new generation for hello/initialize until EndConnection.
    uint32_t BeginConnection();

    // Close/disconnect for the generation that owned the socket. Clears
    // credentials and permanently seals that generation against further
    // publish until the next BeginConnection. Stale gens are ignored.
    void EndConnection(uint32_t generation);

    // hello / OnAudioChannelOpened: bind the audio session to this generation.
    // `generation` must be the value captured when that connection opened —
    // never re-read active_generation() at consume time.
    void ApplyHelloSession(uint32_t generation, const std::string& session_id);

    // MCP initialize capabilities.vision for this generation (source gen from
    // the connection that delivered the message).
    void ApplyInitializeVision(uint32_t generation,
                               const std::string& explain_url,
                               const std::string& identity_url,
                               const std::string& token,
                               const std::string& vision_session_id,
                               int64_t expires_at);

    uint32_t active_generation() const;
    bool IsGenerationAccepting(uint32_t generation) const;

    bool TryAcquireExplainSnapshot(VisionCredentialSnapshot* out) const;
    bool TryAcquireIdentitySnapshot(VisionCredentialSnapshot* out) const;

    bool IsExplainReady() const;
    std::string ExplainNotReadyReason() const;
    bool IsIdentityReady() const;
    std::string IdentityNotReadyReason() const;

    VisionCredentialSnapshot DebugCopy() const;

private:
    VisionCredentialStore() = default;

    bool AcceptsGenerationLocked(uint32_t generation) const;
    void ClearPendingLocked();
    void ClearPublishedLocked();
    void TryPublishLocked();
    bool IsExpiredLocked(int64_t expires_at) const;

    mutable std::mutex mutex_;
    uint32_t active_generation_ = 0;
    // After EndConnection for active_generation_, further hello/initialize for
    // that same number are rejected until BeginConnection advances it.
    bool generation_accepting_ = false;

    std::string pending_session_id_;
    std::string pending_explain_url_;
    std::string pending_identity_url_;
    std::string pending_token_;
    std::string pending_vision_session_id_;
    int64_t pending_expires_at_ = 0;
    bool pending_initialize_seen_ = false;
    bool pending_hello_seen_ = false;
    std::string last_reject_reason_;

    VisionCredentialSnapshot published_;
};
