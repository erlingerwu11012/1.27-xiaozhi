#pragma once

#include <cstdint>
#include <esp_err.h>

/** Serial OTA/TLS attempt ownership + optional [OTA_TLS] diagnostics (dev-gated). */
namespace OtaTlsDiag {

/** Acquire exclusive ownership for one OTA/TLS attempt. Returns 0 if busy. */
uint32_t BeginAttempt(const char* owner);

/** Release only if attempt_id matches the active owner (stale ids ignored). */
void EndAttempt(uint32_t attempt_id);

bool IsBusy();
uint32_t ActiveAttemptId();

void NoteWifiGotIp();
uint32_t WifiGeneration();
int64_t MsSinceGotIp();

void LogStage(uint32_t attempt_id, const char* stage);
void LogHeapWifi(uint32_t attempt_id, const char* stage);
void LogClose(uint32_t attempt_id, const char* source);
void LogTlsError(uint32_t attempt_id, esp_err_t open_err, esp_err_t esp_tls_err,
                 int mbedtls_err, int tls_flags, int err_no);

/**
 * Dev-only pure TLS probe to api.realecho.cn:443 with crt_bundle.
 * Caller must already hold BeginAttempt ownership.
 * Returns true if TLS handshake completed.
 */
bool RunPureTlsProbe(uint32_t attempt_id);

}  // namespace OtaTlsDiag
