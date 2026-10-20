package xiaozhi.modules.rolepack.util;

import xiaozhi.modules.rolepack.entity.RolePackEntity;

public final class RolePackPreviewAccess {

    private RolePackPreviewAccess() {
    }

    public static boolean canServe(RolePackEntity pack, String kind) {
        if (pack == null || !RolePackConstants.STATUS_PUBLISHED.equals(pack.getStatus())) {
            return false;
        }
        String key = "video".equals(kind) ? pack.getPreviewVideoObjectKey() : pack.getPreviewImageObjectKey();
        return key != null && !key.isBlank() && !key.contains("..") && !key.startsWith("/") && !key.startsWith("\\");
    }
}
