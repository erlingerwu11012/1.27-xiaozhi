#ifndef SPINE_ROLE_PREFLIGHT_H
#define SPINE_ROLE_PREFLIGHT_H

#include <string>

// Shared Spine 4.2 role compatibility gate. Used by both the startup path
// (spine_assets) and the character OTA path (spine_ota) so that a role is only
// accepted when it can actually be rendered by the local 4.2 runtime + port.
namespace spine_role_preflight {

enum class ErrorCode {
    kOk = 0,
    kRuntimeMismatch,
    kAtlasInvalid,
    kSkeletonInvalid,
    kSkinMissing,
    kIdleMissing,
    kUnsupportedFeature,
};

struct Result {
    ErrorCode code = ErrorCode::kOk;
    std::string detail;
    std::string runtime_version;

    bool ok() const { return code == ErrorCode::kOk; }
};

const char* ErrorToString(ErrorCode code);

// Validate a Spine 4.2 role from raw in-memory bytes.
//   skel_data / skel_size : raw .skel binary
//   atlas_data / atlas_size: raw .atlas text
//   skin_name             : the role skin that must exist; may be empty to skip.
// The PNG texture is intentionally not decoded here; only runtime version,
// structure and unsupported-feature checks are performed.
Result Check(const void* skel_data, size_t skel_size,
             const void* atlas_data, size_t atlas_size,
             const char* skin_name);

}  // namespace spine_role_preflight

#endif
