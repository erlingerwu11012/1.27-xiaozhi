package xiaozhi.modules.rolepack.util;

import java.nio.charset.StandardCharsets;
import java.util.Locale;
import java.util.Set;

/**
 * 预览图/视频：magic + MIME，拒绝伪装与路径穿越文件名。
 */
public final class PreviewMediaValidator {

    public static final long MAX_IMAGE_BYTES = 5L * 1024 * 1024;
    public static final long MAX_VIDEO_BYTES = 25L * 1024 * 1024;

    private static final Set<String> IMAGE_EXT = Set.of("jpg", "jpeg", "png", "webp");
    private static final Set<String> VIDEO_EXT = Set.of("mp4", "webm");

    private PreviewMediaValidator() {
    }

    public static Result requireImage(byte[] data, String declaredFilename, String declaredContentType) {
        if (data == null || data.length == 0) {
            throw new IllegalArgumentException("封面图片为空");
        }
        if (data.length > MAX_IMAGE_BYTES) {
            throw new IllegalArgumentException("封面图片超过 5 MiB");
        }
        rejectDangerousPayload(data);
        Kind kind = detectImage(data);
        if (kind == null) {
            throw new IllegalArgumentException("封面图片必须是 JPG/PNG/WebP，且与文件内容一致");
        }
        rejectMismatchedMime(declaredContentType, kind.mimePrefixes);
        rejectPathTraversalName(declaredFilename);
        String nameExt = extensionOf(declaredFilename);
        if (!nameExt.isEmpty() && !IMAGE_EXT.contains(nameExt)) {
            throw new IllegalArgumentException("封面图片扩展名不允许");
        }
        if (!nameExt.isEmpty() && !kind.ext.equals(nameExt) && !(kind.ext.equals("jpg") && nameExt.equals("jpeg"))
                && !(kind.ext.equals("jpeg") && nameExt.equals("jpg"))) {
            throw new IllegalArgumentException("封面图片扩展名与文件内容不一致");
        }
        return new Result(kind.storeExt, kind.contentType);
    }

    public static Result requireVideo(byte[] data, String declaredFilename, String declaredContentType) {
        if (data == null || data.length == 0) {
            throw new IllegalArgumentException("演示视频为空");
        }
        if (data.length > MAX_VIDEO_BYTES) {
            throw new IllegalArgumentException("演示视频超过 25 MiB");
        }
        rejectDangerousPayload(data);
        Kind kind = detectVideo(data);
        if (kind == null) {
            throw new IllegalArgumentException("演示视频必须是 MP4 或 WebM，且与文件内容一致");
        }
        rejectMismatchedMime(declaredContentType, kind.mimePrefixes);
        rejectPathTraversalName(declaredFilename);
        String nameExt = extensionOf(declaredFilename);
        if (!nameExt.isEmpty() && !VIDEO_EXT.contains(nameExt)) {
            throw new IllegalArgumentException("演示视频扩展名不允许");
        }
        if (!nameExt.isEmpty() && !kind.ext.equals(nameExt)) {
            throw new IllegalArgumentException("演示视频扩展名与文件内容不一致");
        }
        return new Result(kind.storeExt, kind.contentType);
    }

    public static void rejectPathTraversalName(String filename) {
        if (filename == null || filename.isBlank()) {
            return;
        }
        String n = filename.replace('\\', '/');
        if (n.contains("..") || n.contains("/") || n.contains("\0")) {
            throw new IllegalArgumentException("非法文件名");
        }
    }

    public static String previewObjectKey(String packId, String version, String kind, String ext) {
        if (packId == null || version == null || packId.contains("..") || version.contains("..")
                || packId.contains("/") || version.contains("/") || packId.contains("\\") || version.contains("\\")) {
            throw new IllegalArgumentException("非法 pack_id 或 version");
        }
        if (!"image".equals(kind) && !"video".equals(kind)) {
            throw new IllegalArgumentException("非法预览类型");
        }
        if (ext == null || ext.contains(".") || ext.contains("/") || ext.contains("\\")) {
            throw new IllegalArgumentException("非法扩展名");
        }
        return packId + "/" + version + "/preview/" + kind + "." + ext;
    }

    private static void rejectDangerousPayload(byte[] data) {
        if (data.length >= 2 && data[0] == 'P' && data[1] == 'K') {
            throw new IllegalArgumentException("不允许 ZIP 作为预览媒体");
        }
        if (data.length >= 4 && data[0] == 0x7f && data[1] == 'E' && data[2] == 'L' && data[3] == 'F') {
            throw new IllegalArgumentException("不允许可执行文件");
        }
        if (data.length >= 2 && data[0] == '#' && data[1] == '!') {
            throw new IllegalArgumentException("不允许脚本文件");
        }
        String head = peekAscii(data, 256).toLowerCase(Locale.ROOT);
        if (head.contains("<svg") || head.startsWith("<?xml") && head.contains("svg")
                || head.contains("<html") || head.contains("<script") || head.contains("javascript:")) {
            throw new IllegalArgumentException("不允许 SVG/HTML/脚本作为预览媒体");
        }
    }

    private static Kind detectImage(byte[] data) {
        if (data.length >= 3 && (data[0] & 0xFF) == 0xFF && (data[1] & 0xFF) == 0xD8 && (data[2] & 0xFF) == 0xFF) {
            return new Kind("jpg", "jpg", "image/jpeg", new String[] { "image/jpeg", "image/jpg" });
        }
        if (data.length >= 8
                && (data[0] & 0xFF) == 0x89 && data[1] == 0x50 && data[2] == 0x4E && data[3] == 0x47
                && data[4] == 0x0D && data[5] == 0x0A && data[6] == 0x1A && data[7] == 0x0A) {
            return new Kind("png", "png", "image/png", new String[] { "image/png" });
        }
        if (data.length >= 12
                && data[0] == 'R' && data[1] == 'I' && data[2] == 'F' && data[3] == 'F'
                && data[8] == 'W' && data[9] == 'E' && data[10] == 'B' && data[11] == 'P') {
            return new Kind("webp", "webp", "image/webp", new String[] { "image/webp" });
        }
        return null;
    }

    private static Kind detectVideo(byte[] data) {
        if (data.length >= 12 && data[4] == 'f' && data[5] == 't' && data[6] == 'y' && data[7] == 'p') {
            return new Kind("mp4", "mp4", "video/mp4", new String[] { "video/mp4", "application/mp4" });
        }
        if (data.length >= 4
                && (data[0] & 0xFF) == 0x1A && (data[1] & 0xFF) == 0x45
                && (data[2] & 0xFF) == 0xDF && (data[3] & 0xFF) == 0xA3) {
            return new Kind("webm", "webm", "video/webm", new String[] { "video/webm" });
        }
        return null;
    }

    private static void rejectMismatchedMime(String declared, String[] allowed) {
        if (declared == null || declared.isBlank()) {
            return;
        }
        String mime = declared.split(";", 2)[0].trim().toLowerCase(Locale.ROOT);
        if (mime.isEmpty() || "application/octet-stream".equals(mime)) {
            return;
        }
        for (String a : allowed) {
            if (a.equals(mime)) {
                return;
            }
        }
        throw new IllegalArgumentException("声明的 MIME 与文件内容不一致");
    }

    private static String extensionOf(String filename) {
        if (filename == null) {
            return "";
        }
        String n = filename.replace('\\', '/');
        int slash = n.lastIndexOf('/');
        if (slash >= 0) {
            n = n.substring(slash + 1);
        }
        int dot = n.lastIndexOf('.');
        if (dot < 0 || dot == n.length() - 1) {
            return "";
        }
        return n.substring(dot + 1).toLowerCase(Locale.ROOT);
    }

    private static String peekAscii(byte[] data, int max) {
        int n = Math.min(data.length, max);
        return new String(data, 0, n, StandardCharsets.ISO_8859_1);
    }

    public record Result(String storeExt, String contentType) {
    }

    private record Kind(String ext, String storeExt, String contentType, String[] mimePrefixes) {
    }
}
