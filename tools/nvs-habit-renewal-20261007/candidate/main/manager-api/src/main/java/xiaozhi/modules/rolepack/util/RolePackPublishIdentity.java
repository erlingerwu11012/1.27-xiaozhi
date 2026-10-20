package xiaozhi.modules.rolepack.util;

import java.io.IOException;

import lombok.Value;

/**
 * 发布身份只信任 spine.bin 内 role.json；客户端 packId/version 仅用于一致性核对。
 */
public final class RolePackPublishIdentity {

    private RolePackPublishIdentity() {
    }

    @Value
    public static class Resolved {
        SpineBundleValidator.BundleInfo info;
        String packId;
        String version;
    }

    public static Resolved resolve(byte[] bin, String clientPackId, String clientVersion) throws IOException {
        SpineBundleValidator.BundleInfo info = SpineBundleValidator.inspectAndValidate(bin);
        if (clientPackId != null && !clientPackId.isBlank() && !clientPackId.trim().equals(info.getRoleId())) {
            throw new IllegalArgumentException("客户端 packId 与包内 role_id 不一致");
        }
        if (clientVersion != null && !clientVersion.isBlank() && !clientVersion.trim().equals(info.getVersion())) {
            throw new IllegalArgumentException("客户端 version 与包内 version 不一致");
        }
        return new Resolved(info, info.getRoleId(), info.getVersion());
    }
}
