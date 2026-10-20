#ifndef WALLPAPER_ASSETS_H
#define WALLPAPER_ASSETS_H

#include <map>
#include <string>

#include "mmap_asset_bundle.h"

struct WallpaperMeta {
    int format = 0;
    std::string pack_id;
    std::string version;
    std::string default_id;
    std::map<std::string, std::string> files_by_id;
};

// Reads the optional online wallpaper package from the single "wallpaper"
// partition. Factory room.png remains in Assets and is selected by callers if
// this package is absent or invalid.
class WallpaperAssets {
public:
    static WallpaperAssets& GetInstance() {
        static WallpaperAssets instance;
        return instance;
    }

    bool Initialize();
    void Shutdown();
    bool ready() const { return ready_; }
    const WallpaperMeta& meta() const { return meta_; }

    bool GetSelectedAssetData(void*& ptr, size_t& size,
                              std::string* selected_id = nullptr);
    bool Select(const std::string& wallpaper_id);
    bool UseFactoryWallpaper();
    std::string SelectedId() const;

    static bool ParseAndValidateManifest(const char* json, size_t len,
                                         const MmapAssetBundle& bundle,
                                         WallpaperMeta& out,
                                         std::string* error);
    static bool ValidatePartition(const char* label, WallpaperMeta* out,
                                  std::string* error);

private:
    WallpaperAssets() = default;
    std::string ResolveSelectedId() const;

    MmapAssetBundle bundle_;
    WallpaperMeta meta_{};
    bool ready_ = false;
};

#endif
