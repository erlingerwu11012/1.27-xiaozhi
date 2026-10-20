package xiaozhi.modules.wallpaperpack.util;

import java.io.IOException;

import lombok.Value;

public final class WallpaperPackPublishIdentity {

    private WallpaperPackPublishIdentity() {
    }

    @Value
    public static class Resolved {
        WallpaperBundleValidator.BundleInfo info;
        String packId;
        String version;
    }

    public static Resolved resolve(byte[] bin, String clientPackId, String clientVersion) throws IOException {
        WallpaperBundleValidator.BundleInfo info = WallpaperBundleValidator.inspectAndValidate(bin);
        if (clientPackId != null && !clientPackId.isBlank() && !clientPackId.trim().equals(info.getPackId())) {
            throw new IllegalArgumentException("客户端 packId 与包内 pack_id 不一致");
        }
        if (clientVersion != null && !clientVersion.isBlank() && !clientVersion.trim().equals(info.getVersion())) {
            throw new IllegalArgumentException("客户端 version 与包内 version 不一致");
        }
        return new Resolved(info, info.getPackId(), info.getVersion());
    }
}
