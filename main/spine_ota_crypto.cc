#include "spine_ota_crypto.h"

#include <cstring>
#include <sstream>
#include <vector>

#include <esp_log.h>
#include <mbedtls/base64.h>
#include <mbedtls/error.h>
#include <mbedtls/md.h>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>

#define TAG "SpineOtaCrypto"

namespace {

// Server-test ES256 public key (SubjectPublicKeyInfo PEM).
// Matches main/certs/spine_ota_server_test_public.pem.
// SPKI SHA-256: 4936f22629bad05b7e488bfa676930bd115e322f302e7a951e463da6dba95d2f
// Paired with api.realecho.cn RolePackSigner for single-device OTA testing.
// NOT a production key — replace with an independently generated production
// key pair before any public release.
// Old dev key (spine_ota_dev_public.pem / SPKI 47b586a1...):  no longer used.
constexpr const char kSpineOtaPublicKeyPem[] =
    "-----BEGIN PUBLIC KEY-----\n"
    "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE2JAR2g/XmegUW/7PiAyF2fvpvsqN\n"
    "0/x/JEUK/Wi8InQszW5jeEWa4yffHSVz9F8+CCg+yhPIarA3GIUU2/vbvQ==\n"
    "-----END PUBLIC KEY-----\n";

int HexNibble(char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}

// Convert raw r||s (64 bytes) to DER ECDSA signature.
bool RawRsToDer(const unsigned char* rs, unsigned char* der, size_t* der_len) {
    auto encode_int = [](const unsigned char* in32, unsigned char* out, size_t* out_len) {
        size_t start = 0;
        while (start < 32 && in32[start] == 0) start++;
        if (start == 32) {
            out[0] = 0x02;
            out[1] = 0x01;
            out[2] = 0x00;
            *out_len = 3;
            return;
        }
        const bool pad = (in32[start] & 0x80) != 0;
        const size_t int_len = 32 - start + (pad ? 1 : 0);
        out[0] = 0x02;
        out[1] = static_cast<unsigned char>(int_len);
        size_t o = 2;
        if (pad) out[o++] = 0x00;
        std::memcpy(out + o, in32 + start, 32 - start);
        *out_len = o + (32 - start);
    };

    unsigned char rbuf[40];
    unsigned char sbuf[40];
    size_t rlen = 0, slen = 0;
    encode_int(rs, rbuf, &rlen);
    encode_int(rs + 32, sbuf, &slen);
    const size_t seq_len = rlen + slen;
    if (seq_len + 2 > *der_len) return false;
    der[0] = 0x30;
    der[1] = static_cast<unsigned char>(seq_len);
    std::memcpy(der + 2, rbuf, rlen);
    std::memcpy(der + 2 + rlen, sbuf, slen);
    *der_len = 2 + seq_len;
    return true;
}

}  // namespace

std::string SpineOtaBuildCanonical(const std::string& task_id,
                                   const std::string& pack_id,
                                   const std::string& role_id,
                                   const std::string& version,
                                   uint32_t size,
                                   const std::string& sha256_hex,
                                   const std::string& min_fw,
                                   const std::string& signed_origin_path) {
    std::ostringstream oss;
    oss << task_id << '\n'
        << pack_id << '\n'
        << role_id << '\n'
        << version << '\n'
        << size << '\n'
        << sha256_hex << '\n'
        << min_fw << '\n'
        << signed_origin_path << '\n';
    return oss.str();
}

bool SpineOtaDecodeHexSha256(const std::string& hex, uint8_t out[32]) {
    if (hex.size() != 64 || out == nullptr) {
        return false;
    }
    for (size_t i = 0; i < 32; i++) {
        const int hi = HexNibble(hex[i * 2]);
        const int lo = HexNibble(hex[i * 2 + 1]);
        if (hi < 0 || lo < 0) {
            return false;
        }
        out[i] = static_cast<uint8_t>((hi << 4) | lo);
    }
    return true;
}

bool SpineOtaSha256HexEq(const uint8_t digest[32], const std::string& hex_lower) {
    uint8_t expected[32];
    if (!SpineOtaDecodeHexSha256(hex_lower, expected)) {
        return false;
    }
    for (char c : hex_lower) {
        if (c >= 'A' && c <= 'F') {
            return false;
        }
    }
    return std::memcmp(digest, expected, 32) == 0;
}

bool SpineOtaVerifyEs256(const std::string& canonical, const std::string& signature_b64) {
    if (canonical.empty() || signature_b64.empty()) {
        return false;
    }

    size_t olen = 0;
    mbedtls_base64_decode(nullptr, 0, &olen,
                          reinterpret_cast<const unsigned char*>(signature_b64.data()),
                          signature_b64.size());
    if (olen == 0 || olen > 256) {
        ESP_LOGE(TAG, "bad signature b64 length");
        return false;
    }
    std::vector<unsigned char> sig(olen);
    if (mbedtls_base64_decode(sig.data(), sig.size(), &olen,
                              reinterpret_cast<const unsigned char*>(signature_b64.data()),
                              signature_b64.size()) != 0) {
        ESP_LOGE(TAG, "signature base64 decode failed");
        return false;
    }
    sig.resize(olen);

    if (sig.size() != 64) {
        ESP_LOGE(TAG, "signature must be raw 64-byte r||s; got %u bytes",
                 static_cast<unsigned>(sig.size()));
        return false;
    }

    std::vector<unsigned char> der(80);
    size_t der_len = der.size();
    if (!RawRsToDer(sig.data(), der.data(), &der_len)) {
        return false;
    }
    der.resize(der_len);

    uint8_t hash[32];
    if (mbedtls_sha256(reinterpret_cast<const unsigned char*>(canonical.data()),
                       canonical.size(), hash, 0) != 0) {
        return false;
    }

    mbedtls_pk_context pk;
    mbedtls_pk_init(&pk);
    int ret = mbedtls_pk_parse_public_key(
        &pk, reinterpret_cast<const unsigned char*>(kSpineOtaPublicKeyPem),
        sizeof(kSpineOtaPublicKeyPem));
    if (ret != 0) {
        ESP_LOGE(TAG, "parse public key failed %d", ret);
        mbedtls_pk_free(&pk);
        return false;
    }

    ret = mbedtls_pk_verify(&pk, MBEDTLS_MD_SHA256, hash, sizeof(hash), der.data(), der.size());
    mbedtls_pk_free(&pk);
    if (ret != 0) {
        ESP_LOGE(TAG, "ES256 verify failed %d", ret);
        return false;
    }
    return true;
}
