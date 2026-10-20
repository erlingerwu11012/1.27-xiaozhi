#ifndef MMAP_ASSET_BUNDLE_H
#define MMAP_ASSET_BUNDLE_H

#include <cstddef>
#include <cstdint>
#include <map>
#include <string>

#include <esp_partition.h>

struct MmapAssetEntry {
    size_t size = 0;
    size_t offset = 0;
};

// Read-only mmap view of an esp_mmap_assets-style bundle on a named partition.
class MmapAssetBundle {
public:
    MmapAssetBundle() = default;
    ~MmapAssetBundle();

    MmapAssetBundle(const MmapAssetBundle&) = delete;
    MmapAssetBundle& operator=(const MmapAssetBundle&) = delete;

    // Maps partition `label` (full size) and validates structure.
    // require_role_json: when true, "role.json" must exist in the table.
    bool Open(const char* label, bool require_role_json);
    void Close();

    bool valid() const { return valid_; }
    const char* label() const { return label_.c_str(); }
    size_t partition_size() const { return partition_ ? partition_->size : 0; }
    size_t mapped_pages_64k() const { return mapped_pages_64k_; }

    bool GetAssetData(const std::string& name, void*& ptr, size_t& size) const;
    bool HasAsset(const std::string& name) const;
    const std::map<std::string, MmapAssetEntry>& assets() const { return assets_; }

    // SHA-256 over the entire mapped partition payload actually written is not
    // known here; callers that need hash of the downloaded blob should hash
    // the flash range they wrote. This helper hashes [0, content_length).
    bool Sha256OfPrefix(size_t content_length, uint8_t out[32]) const;

private:
    bool ValidateAndIndex(bool require_role_json);

    const esp_partition_t* partition_ = nullptr;
    esp_partition_mmap_handle_t mmap_handle_ = 0;
    const char* mmap_root_ = nullptr;
    bool valid_ = false;
    size_t mapped_pages_64k_ = 0;
    std::string label_;
    std::map<std::string, MmapAssetEntry> assets_;
};

#endif
