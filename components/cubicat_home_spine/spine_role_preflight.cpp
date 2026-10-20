#include "spine_role_preflight.h"

#include <spine/Atlas.h>
#include <spine/AtlasAttachmentLoader.h>
#include <spine/Attachment.h>
#include <spine/BlendMode.h>
#include <spine/ClippingAttachment.h>
#include <spine/MeshAttachment.h>
#include <spine/RegionAttachment.h>
#include <spine/SkeletonBinary.h>
#include <spine/SkeletonData.h>
#include <spine/Skin.h>
#include <spine/SlotData.h>
#include <spine/TextureLoader.h>

#include "cubicat-port/spine_extension.h"
#include "utils/logger.h"

namespace spine_role_preflight {

namespace {

const char* kTag = "SpinePreflight";

// Matches SkeletonBinary::readVarint(input, true) in the 4.2 runtime.
int ReadVarint(const unsigned char*& p, const unsigned char* end, bool& ok) {
    if (p >= end) {
        ok = false;
        return 0;
    }
    unsigned char b = *p++;
    int value = b & 0x7F;
    if (b & 0x80) {
        if (p >= end) { ok = false; return 0; }
        b = *p++;
        value |= (b & 0x7F) << 7;
        if (b & 0x80) {
            if (p >= end) { ok = false; return 0; }
            b = *p++;
            value |= (b & 0x7F) << 14;
            if (b & 0x80) {
                if (p >= end) { ok = false; return 0; }
                b = *p++;
                value |= (b & 0x7F) << 21;
                if (b & 0x80) {
                    if (p >= end) { ok = false; return 0; }
                    value |= (*p++ & 0x7F) << 28;
                }
            }
        }
    }
    return value;
}

// 4.x binary header: readInt(lowHash) + readInt(highHash) + string(version).
bool ReadVersionHeader(const unsigned char* data, size_t size, std::string& version) {
    if (data == nullptr || size < 8) return false;
    const unsigned char* p = data + 8;  // two 4-byte big-endian hash ints
    const unsigned char* end = data + size;
    bool ok = true;
    int len = ReadVarint(p, end, ok);
    if (!ok || len <= 0) return false;
    if (static_cast<size_t>(len - 1) > static_cast<size_t>(end - p)) return false;
    version.assign(reinterpret_cast<const char*>(p), static_cast<size_t>(len - 1));
    return true;
}

bool IsVersion42(const std::string& version) {
    return version.size() >= 3 && version.compare(0, 3, "4.2") == 0 &&
           (version.size() == 3 || version[3] == '.');
}

// The preflight never renders, so textures just need to "bind" without decoding.
class NoopTextureLoader : public spine::TextureLoader {
public:
    void load(spine::AtlasPage& page, const spine::String& path) override {
        (void)path;
        page.texture = reinterpret_cast<void*>(1);  // non-null marker
    }
    void unload(void* texture) override {
        (void)texture;
    }
};

std::string SlotName(spine::SlotData* slotData) {
    return slotData == nullptr ? std::string("?") : std::string(slotData->getName().buffer());
}

}  // namespace

const char* ErrorToString(ErrorCode code) {
    switch (code) {
        case ErrorCode::kOk: return "ok";
        case ErrorCode::kRuntimeMismatch: return "runtime_mismatch";
        case ErrorCode::kAtlasInvalid: return "atlas_invalid";
        case ErrorCode::kSkeletonInvalid: return "skeleton_invalid";
        case ErrorCode::kSkinMissing: return "skin_missing";
        case ErrorCode::kIdleMissing: return "idle_missing";
        case ErrorCode::kUnsupportedFeature: return "unsupported_feature";
    }
    return "unknown";
}

Result Check(const void* skel_data, size_t skel_size,
             const void* atlas_data, size_t atlas_size,
             const char* skin_name) {
    Result result;

    const auto* skel = static_cast<const unsigned char*>(skel_data);
    const auto* atlas = static_cast<const char*>(atlas_data);

    if (skel == nullptr || skel_size == 0) {
        result.code = ErrorCode::kSkeletonInvalid;
        result.detail = "empty skeleton data";
        return result;
    }

    // 1. Read the raw skeleton version header and require 4.2.*.
    std::string version;
    if (!ReadVersionHeader(skel, skel_size, version)) {
        result.code = ErrorCode::kSkeletonInvalid;
        result.detail = "unable to read skeleton version header";
        return result;
    }
    result.runtime_version = version;
    if (!IsVersion42(version)) {
        result.code = ErrorCode::kRuntimeMismatch;
        result.detail = "skeleton version " + version + " is not a Spine 4.2 export";
        ESP_LOGE(kTag, "%s (%s)", ErrorToString(result.code), result.detail.c_str());
        return result;
    }
    ESP_LOGI(kTag, "skeleton version header=%s", version.c_str());

    // 2. Ensure the PSRAM allocator is installed (idempotent).
    CubicatSpineExtension::init();

    // 3. Trial-load the atlas from the raw buffer.
    if (atlas == nullptr || atlas_size == 0) {
        result.code = ErrorCode::kAtlasInvalid;
        result.detail = "empty atlas data";
        return result;
    }
    NoopTextureLoader textureLoader;
    spine::Atlas atlasObject(atlas, static_cast<int>(atlas_size), "", &textureLoader, true);
    if (atlasObject.getPages().size() == 0 || atlasObject.getRegions().size() == 0) {
        result.code = ErrorCode::kAtlasInvalid;
        result.detail = "atlas produced no pages/regions";
        return result;
    }

    // 4. Trial-load the skeleton binary.
    spine::AtlasAttachmentLoader attachmentLoader(&atlasObject);
    spine::SkeletonBinary binary(&attachmentLoader);
    spine::SkeletonData* skeletonData =
        binary.readSkeletonData(skel, static_cast<int>(skel_size));
    if (skeletonData == nullptr) {
        result.code = ErrorCode::kSkeletonInvalid;
        result.detail = binary.getError().isEmpty() ? "skeleton parse failed"
                                                    : binary.getError().buffer();
        return result;
    }

    auto fail = [&](ErrorCode code, std::string detail) {
        result.code = code;
        result.detail = std::move(detail);
        delete skeletonData;
        return result;
    };

    // 5. The configured skin must exist.
    if (skin_name != nullptr && skin_name[0] != '\0') {
        if (skeletonData->findSkin(spine::String(skin_name)) == nullptr) {
            return fail(ErrorCode::kSkinMissing,
                        std::string("skin not found: ") + skin_name);
        }
    }

    // 6. The idle animation must exist.
    if (skeletonData->findAnimation("idle") == nullptr) {
        return fail(ErrorCode::kIdleMissing, "idle animation not found");
    }

    // 7. Reject unsupported features.
    // 7a. Blend modes: Normal/Additive/Multiply only (Screen is unsupported).
    for (size_t i = 0; i < skeletonData->getSlots().size(); ++i) {
        spine::SlotData* slotData = skeletonData->getSlots()[i];
        spine::BlendMode bm = slotData->getBlendMode();
        if (bm != spine::BlendMode_Normal && bm != spine::BlendMode_Additive &&
            bm != spine::BlendMode_Multiply) {
            return fail(ErrorCode::kUnsupportedFeature,
                        "unsupported blend mode on slot " + SlotName(slotData));
        }
    }

    // 7b. Dark tint (RGBA2 / two-color).
    for (size_t i = 0; i < skeletonData->getSlots().size(); ++i) {
        spine::SlotData* slotData = skeletonData->getSlots()[i];
        if (slotData->hasDarkColor()) {
            return fail(ErrorCode::kUnsupportedFeature,
                        "dark tint (RGBA2) on slot " + SlotName(slotData));
        }
    }

    // 7c. Physics constraints are supported by Spine 4.2. SpineNode advances
    // skeleton time and applies Physics_Update each frame.

    // 7d. Clipping attachments are unsupported. Sequences are allowed: the 4.2
    // runtime drives them via SequenceTimeline, and the renderer resolves the
    // current frame's region through attachment->getRegion(). A not-yet-resolved
    // (NULL) region is safely skipped by the renderer until a frame is applied.
    for (size_t i = 0; i < skeletonData->getSkins().size(); ++i) {
        spine::Skin* skin = skeletonData->getSkins()[i];
        auto entries = skin->getAttachments();
        while (entries.hasNext()) {
            auto& entry = entries.next();
            spine::Attachment* attachment = entry._attachment;
            if (attachment == nullptr) continue;

            const auto& rtti = attachment->getRTTI();
            if (rtti.isExactly(spine::ClippingAttachment::rtti)) {
                return fail(ErrorCode::kUnsupportedFeature, "clipping attachment present");
            }
            if (rtti.isExactly(spine::RegionAttachment::rtti)) {
                if (static_cast<spine::RegionAttachment*>(attachment)->getSequence() != nullptr) {
                    ESP_LOGW(kTag, "sequence on region attachment (allowed, rendered frame-by-frame)");
                }
            } else if (rtti.isExactly(spine::MeshAttachment::rtti)) {
                if (static_cast<spine::MeshAttachment*>(attachment)->getSequence() != nullptr) {
                    ESP_LOGW(kTag, "sequence on mesh attachment (allowed, rendered frame-by-frame)");
                }
            }
        }
    }

    result.code = ErrorCode::kOk;
    delete skeletonData;
    return result;
}

}  // namespace spine_role_preflight
