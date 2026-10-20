package xiaozhi.modules.visualota.util;

/**
 * 视觉 OTA 资源类型（Spine 角色包 / Wallpaper 壁纸包）。
 */
public enum VisualOtaResourceType {

    SPINE("spine"),
    WALLPAPER("wallpaper");

    private final String value;

    VisualOtaResourceType(String value) {
        this.value = value;
    }

    public String value() {
        return value;
    }
}
