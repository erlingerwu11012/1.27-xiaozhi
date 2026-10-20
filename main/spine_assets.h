#ifndef SPINE_ASSETS_H
#define SPINE_ASSETS_H

#include <string>

#include "mmap_asset_bundle.h"

class Assets;

struct SpineRoleMeta {
    int format = 0;
    std::string role_id;
    std::string version;
    std::string spine_runtime_version;
    std::string skel;
    std::string atlas;
    std::string png;
    std::string skin;
    float scale = 0.0f;
};

// Kept for source compatibility with old callers. The product layout is now
// single-slot: the only online role partition is "spine".
enum class SpineSlot : char {
    kA = 'a',
    kB = 'b',
};

class SpineAssets {
public:
    static SpineAssets& GetInstance() {
        static SpineAssets instance;
        return instance;
    }

    // Prefer a validated online role in the single "spine" partition. If it
    // is blank, interrupted, or invalid, use the factory role stored in the
    // immutable "assets" partition instead.
    bool Initialize();
    void Shutdown();

    bool ready() const { return ready_; }
    bool uses_dynamic_partition() const { return uses_dynamic_partition_; }
    SpineSlot active_slot() const { return SpineSlot::kA; }
    const SpineRoleMeta& meta() const { return meta_; }
    const char* active_label() const;

    bool GetAssetData(const std::string& name, void*& ptr, size_t& size);

    // Legacy helpers now describe the single dynamic partition. They avoid
    // breaking OTA clients compiled against the previous A/B API.
    static SpineSlot ReadActiveSlotFromNvs();
    static bool CommitActiveSpineSlot(SpineSlot ignored_slot,
                                      const std::string& role_id,
                                      const std::string& version,
                                      const std::string& task_id,
                                      const std::string& sha256,
                                      std::string* error_detail);
    static const char* SlotLabel(SpineSlot ignored_slot);
    static SpineSlot OtherSlot(SpineSlot slot);

    static bool ParseAndValidateRoleJson(const char* json,
                                         size_t len,
                                         const MmapAssetBundle& bundle,
                                         SpineRoleMeta& out,
                                         std::string* error);
    static bool ParseAndValidateRoleJson(const char* json,
                                         size_t len,
                                         const Assets& assets,
                                         SpineRoleMeta& out,
                                         std::string* error);

private:
    SpineAssets() = default;
    bool TryOpenDynamic();
    bool TryOpenFactoryAssets();
    bool ValidateRoleData(bool dynamic_bundle, const char* source_label);

    MmapAssetBundle dynamic_bundle_;
    SpineRoleMeta meta_{};
    bool ready_ = false;
    bool uses_dynamic_partition_ = false;
};

#endif
