#include "mmap_asset_bundle.h"

#include <cstring>
#include <set>

#include <esp_log.h>
#include <mbedtls/sha256.h>
#include <spi_flash_mmap.h>

#define TAG "MmapBundle"

namespace {

struct mmap_assets_table {
    char asset_name[32];
    uint32_t asset_size;
    uint32_t asset_offset;
    uint16_t asset_width;
    uint16_t asset_height;
};

uint32_t CalculateChecksum16(const char* data, uint32_t length) {
    uint32_t checksum = 0;
    for (uint32_t i = 0; i < length; i++) {
        checksum += static_cast<uint8_t>(data[i]);
    }
    return checksum & 0xFFFF;
}

}  // namespace

MmapAssetBundle::~MmapAssetBundle() {
    Close();
}

void MmapAssetBundle::Close() {
    if (mmap_handle_ != 0) {
        esp_partition_munmap(mmap_handle_);
        mmap_handle_ = 0;
    }
    mmap_root_ = nullptr;
    partition_ = nullptr;
    valid_ = false;
    mapped_pages_64k_ = 0;
    assets_.clear();
    label_.clear();
}

bool MmapAssetBundle::Open(const char* label, bool require_role_json) {
    Close();
    if (label == nullptr || label[0] == '\0') {
        ESP_LOGE(TAG, "Empty partition label");
        return false;
    }
    label_ = label;

    partition_ = esp_partition_find_first(ESP_PARTITION_TYPE_ANY,
                                          ESP_PARTITION_SUBTYPE_ANY, label);
    if (partition_ == nullptr) {
        ESP_LOGE(TAG, "Partition '%s' not found", label);
        return false;
    }

    const int free_pages = spi_flash_mmap_get_free_pages(SPI_FLASH_MMAP_DATA);
    const uint32_t free_bytes = static_cast<uint32_t>(free_pages) * 64 * 1024;
    mapped_pages_64k_ = (partition_->size + 65535) / 65536;
    ESP_LOGI(TAG,
             "mmap plan label=%s partition=%lu KB need_pages=%u free_pages=%d free_KB=%lu",
             label, partition_->size / 1024, static_cast<unsigned>(mapped_pages_64k_),
             free_pages, free_bytes / 1024);

    if (free_bytes < partition_->size) {
        ESP_LOGE(TAG,
                 "mmap failed label=%s: free %lu KB < need %lu KB",
                 label, free_bytes / 1024, partition_->size / 1024);
        return false;
    }

    esp_err_t err = esp_partition_mmap(partition_, 0, partition_->size,
                                       ESP_PARTITION_MMAP_DATA,
                                       reinterpret_cast<const void**>(&mmap_root_),
                                       &mmap_handle_);
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "mmap failed label=%s: %s", label, esp_err_to_name(err));
        mmap_handle_ = 0;
        mmap_root_ = nullptr;
        return false;
    }

    if (!ValidateAndIndex(require_role_json)) {
        ESP_LOGE(TAG, "bundle validation failed label=%s", label);
        Close();
        return false;
    }

    valid_ = true;
    ESP_LOGI(TAG, "bundle OK label=%s files=%u", label,
             static_cast<unsigned>(assets_.size()));
    return true;
}

bool MmapAssetBundle::ValidateAndIndex(bool require_role_json) {
    assets_.clear();
    if (mmap_root_ == nullptr || partition_ == nullptr) {
        return false;
    }

    const uint32_t stored_files = *reinterpret_cast<const uint32_t*>(mmap_root_ + 0);
    const uint32_t stored_chksum = *reinterpret_cast<const uint32_t*>(mmap_root_ + 4);
    const uint32_t stored_len = *reinterpret_cast<const uint32_t*>(mmap_root_ + 8);

    if (stored_files == 0 || stored_files > 256) {
        ESP_LOGE(TAG, "invalid file count %lu", stored_files);
        return false;
    }
    if (stored_len > partition_->size - 12) {
        ESP_LOGE(TAG, "payload_len %lu exceeds partition", stored_len);
        return false;
    }

    const size_t table_bytes = static_cast<size_t>(stored_files) * sizeof(mmap_assets_table);
    if (12 + table_bytes > partition_->size || table_bytes > stored_len) {
        ESP_LOGE(TAG, "file table out of bounds");
        return false;
    }

    const uint32_t calculated = CalculateChecksum16(mmap_root_ + 12, stored_len);
    if (calculated != stored_chksum) {
        ESP_LOGE(TAG, "checksum mismatch calc=0x%lx stored=0x%lx", calculated, stored_chksum);
        return false;
    }

    std::set<std::string> seen;
    for (uint32_t i = 0; i < stored_files; i++) {
        const auto* item = reinterpret_cast<const mmap_assets_table*>(
            mmap_root_ + 12 + i * sizeof(mmap_assets_table));
        char name_buf[33] = {0};
        std::memcpy(name_buf, item->asset_name, 32);
        std::string name(name_buf);
        if (name.empty()) {
            ESP_LOGE(TAG, "empty asset name at index %lu", i);
            return false;
        }
        if (!seen.insert(name).second) {
            ESP_LOGE(TAG, "duplicate asset name: %s", name.c_str());
            return false;
        }

        const size_t data_base = 12 + table_bytes;
        const size_t absolute = data_base + item->asset_offset;
        // Each asset payload is 0x5A5A + file bytes; asset_size is file bytes.
        if (item->asset_offset > stored_len ||
            absolute + 2 < absolute ||
            absolute + 2 + item->asset_size > 12 + stored_len ||
            absolute + 2 + item->asset_size > partition_->size) {
            ESP_LOGE(TAG, "asset %s offset/size out of bounds", name.c_str());
            return false;
        }

        const auto* magic = reinterpret_cast<const uint8_t*>(mmap_root_ + absolute);
        if (magic[0] != 0x5A || magic[1] != 0x5A) {
            ESP_LOGE(TAG, "asset %s bad magic %02x%02x", name.c_str(), magic[0], magic[1]);
            return false;
        }

        assets_[name] = MmapAssetEntry{
            .size = static_cast<size_t>(item->asset_size),
            .offset = absolute + 2,
        };
    }

    if (require_role_json && assets_.find("role.json") == assets_.end()) {
        ESP_LOGE(TAG, "role.json missing");
        return false;
    }
    return true;
}

bool MmapAssetBundle::HasAsset(const std::string& name) const {
    return assets_.find(name) != assets_.end();
}

bool MmapAssetBundle::GetAssetData(const std::string& name, void*& ptr, size_t& size) const {
    auto it = assets_.find(name);
    if (!valid_ || it == assets_.end() || mmap_root_ == nullptr) {
        return false;
    }
    ptr = const_cast<char*>(mmap_root_ + it->second.offset);
    size = it->second.size;
    return true;
}

bool MmapAssetBundle::Sha256OfPrefix(size_t content_length, uint8_t out[32]) const {
    if (!valid_ || mmap_root_ == nullptr || out == nullptr) {
        return false;
    }
    if (content_length == 0 || content_length > partition_->size) {
        return false;
    }
    mbedtls_sha256_context ctx;
    mbedtls_sha256_init(&ctx);
    if (mbedtls_sha256_starts(&ctx, 0) != 0) {
        mbedtls_sha256_free(&ctx);
        return false;
    }
    if (mbedtls_sha256_update(&ctx, reinterpret_cast<const unsigned char*>(mmap_root_),
                              content_length) != 0) {
        mbedtls_sha256_free(&ctx);
        return false;
    }
    const int ret = mbedtls_sha256_finish(&ctx, out);
    mbedtls_sha256_free(&ctx);
    return ret == 0;
}
