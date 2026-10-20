package xiaozhi.modules.wallpaperpack.util;

import xiaozhi.modules.wallpaperpack.entity.WallpaperPackEntity;

public final class WallpaperPackPreviewAccess {

    private WallpaperPackPreviewAccess() {
    }

    public static boolean canServe(WallpaperPackEntity pack, String kind) {
        if (pack == null || !WallpaperPackConstants.STATUS_PUBLISHED.equals(pack.getStatus())) {
            return false;
        }
        String key = "video".equals(kind) ? pack.getPreviewVideoObjectKey() : pack.getPreviewImageObjectKey();
        return key != null && !key.isBlank() && !key.contains("..") && !key.startsWith("/") && !key.startsWith("\\");
    }
}
