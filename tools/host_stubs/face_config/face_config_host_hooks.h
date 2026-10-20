#pragma once

#include <cstdint>
#include <string>

namespace face_config_host {

void ResetHooks();
bool ShouldFailAlloc();
void SetFailNextAllocs(int n);
void SetFailNextQueueCreates(int n);
void SetFailNextTaskCreates(int n);
int QueueCreateAttempts();
int QueueCreateSuccesses();
int TaskCreateAttempts();
int TaskCreateSuccesses();
void SetSubmitTimeoutMs(uint32_t ms);
uint32_t SubmitTimeoutMs();
void BlockWorker(bool block);
int QueueDepth();
int LiveRequestCount();
void OnRequestAllocated();
void OnRequestDeleted();
bool WorkerShouldStop();
void RequestWorkerStop();
void ClearWorkerStop();
void JoinWorker(void* task);

void SetNvsOpenError(const char* ns, bool error);
void SetNvsGetError(const char* ns, const char* key, bool error);
void ClearNvs();
void HostSetString(const char* ns, const char* key, const char* value);
void HostSetInt(const char* ns, const char* key, int32_t value);
void HostSetBool(const char* ns, const char* key, bool value);
std::string HostGetString(const char* ns, const char* key);
int32_t HostGetInt(const char* ns, const char* key, int32_t default_value = 0);
bool HostGetBool(const char* ns, const char* key, bool default_value = false);
bool HostHasKey(const char* ns, const char* key);
int HostNvsGetI32Calls(const char* ns, const char* key);
int HostNvsGetU8Calls(const char* ns, const char* key);
int HostNvsGetStrCalls(const char* ns, const char* key);

}  // namespace face_config_host

namespace face_config {
void ResetStoreForTest();
bool IsStoreReadyForTest();
}
