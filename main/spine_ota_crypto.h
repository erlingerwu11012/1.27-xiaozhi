#ifndef SPINE_OTA_CRYPTO_H
#define SPINE_OTA_CRYPTO_H

#include <cstddef>
#include <cstdint>
#include <string>

// Canonical payload for ES256 (ECDSA P-256 + SHA-256), each line ends with \n:
//   task_id
//   pack_id
//   role_id
//   version
//   size
//   sha256
//   min_fw
//   https://<lowercase-host><raw-path-without-query>
//
// signed_origin_path must already be the full "https://host/path" string (no query).
std::string SpineOtaBuildCanonical(const std::string& task_id,
                                   const std::string& pack_id,
                                   const std::string& role_id,
                                   const std::string& version,
                                   uint32_t size,
                                   const std::string& sha256_hex,
                                   const std::string& min_fw,
                                   const std::string& signed_origin_path);

bool SpineOtaSha256HexEq(const uint8_t digest[32], const std::string& hex_lower);

// signature_b64: standard base64 of raw r||s (64 bytes) or DER ECDSA signature.
bool SpineOtaVerifyEs256(const std::string& canonical, const std::string& signature_b64);

bool SpineOtaDecodeHexSha256(const std::string& hex, uint8_t out[32]);

#endif
