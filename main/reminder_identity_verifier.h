#pragma once

#include "identity_client.h"

#include <cstdint>
#include <functional>
#include <mutex>
#include <string>

struct ReminderIdentityRequest {
    std::string instance_id;
    uint32_t revision = 0;
    std::string recipient_person_id;
    uint32_t presence_generation = 0;
};

struct ReminderIdentityOutcome {
    ReminderIdentityRequest request;
    bool confirmed = false;
    std::string reason;
    IdentityResult first;
    IdentityResult second;
};

// Async worker: capture + identify twice off the coordinator mutex / UI thread.
class ReminderIdentityVerifier {
public:
    using Callback = std::function<void(const ReminderIdentityOutcome&)>;

    static ReminderIdentityVerifier& GetInstance();

    void Start();
    bool RequestVerification(const ReminderIdentityRequest& request,
                             Callback callback);
    bool IsBusy() const;

private:
    ReminderIdentityVerifier() = default;
    static void WorkerEntry(void* arg);
    void WorkerLoop();
    ReminderIdentityOutcome RunVerification(
        const ReminderIdentityRequest& request);

    mutable std::mutex mutex_;
    bool started_ = false;
    bool busy_ = false;
    bool has_pending_ = false;
    ReminderIdentityRequest pending_;
    Callback pending_callback_;
    void* worker_handle_ = nullptr;
};
