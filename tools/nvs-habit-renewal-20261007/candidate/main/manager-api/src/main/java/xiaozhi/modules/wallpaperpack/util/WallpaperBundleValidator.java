package xiaozhi.modules.wallpaperpack.util;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.Data;
import xiaozhi.modules.rolepack.util.SpineBundleValidator;

/**
 * 壁纸 mmap bundle 校验（与固件同格式 header/目录表/0x5A5A/checksum16）。
 */
public final class WallpaperBundleValidator {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final int HEADER_SIZE = 12;
    private static final int DIR_ENTRY_SIZE = 44;
    private static final int NAME_FIELD_SIZE = 32;
    private static final byte ZZ0 = 0x5A;
    private static final byte ZZ1 = 0x5A;

    private static final Pattern PACK_ID_PATTERN = Pattern.compile("^[A-Za-z0-9_-]{1,64}$");
    private static final Pattern ITEM_ID_PATTERN = Pattern.compile("^[A-Za-z0-9_-]{1,31}$");

    private WallpaperBundleValidator() {
    }

    @Data
    public static class BundleFile {
        private String name;
        private byte[] data;
        private int size;
        private int offset;
    }

    @Data
    public static class BundleInfo {
        private String packId;
        private String version;
        private String defaultId;
        private int format;
        private int itemCount;
        private int checksum16;
        private int packSize;
        private List<BundleFile> files = new ArrayList<>();
    }

    public static BundleInfo inspectAndValidate(byte[] bin) throws IOException {
        return validate(bin, null, null);
    }

    public static BundleInfo validate(byte[] bin, String expectedPackId, String expectedVersion)
            throws IOException {
        if (bin == null || bin.length == 0) {
            throw new IllegalArgumentException("壁纸包文件为空");
        }
        if (bin.length > WallpaperPackConstants.MAX_PACK_SIZE) {
            throw new IllegalArgumentException(
                    "壁纸包超过大小上限 " + WallpaperPackConstants.MAX_PACK_SIZE + " bytes");
        }
        if (bin.length >= 4 && bin[0] == 'P' && bin[1] == 'K') {
            throw new IllegalArgumentException("不支持 ZIP：请上传 mmap 格式的 wallpaper.bin");
        }
        if (bin.length < HEADER_SIZE) {
            throw new IllegalArgumentException("wallpaper.bin 过短：缺少 header");
        }

        ByteBuffer header = ByteBuffer.wrap(bin, 0, HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN);
        int fileCount = header.getInt();
        int checksumField = header.getInt();
        int payloadLen = header.getInt();
        int checksum16 = checksumField & 0xFFFF;

        if (fileCount <= 0 || fileCount > 64) {
            throw new IllegalArgumentException("非法 file_count: " + fileCount);
        }
        long dirBytes = (long) fileCount * DIR_ENTRY_SIZE;
        if (payloadLen < dirBytes) {
            throw new IllegalArgumentException("payload_len 小于目录表长度");
        }
        if (HEADER_SIZE + (long) payloadLen != bin.length) {
            throw new IllegalArgumentException("payload_len 与文件总长不一致");
        }

        int dirStart = HEADER_SIZE;
        int dataStart = HEADER_SIZE + (int) dirBytes;
        int dataLen = payloadLen - (int) dirBytes;

        int sum = SpineBundleValidator.checksum16Unsigned(bin, dirStart, payloadLen);
        if (sum != checksum16) {
            throw new IllegalArgumentException("bundle checksum16 校验失败");
        }

        Set<String> names = new HashSet<>();
        List<BundleFile> files = new ArrayList<>();
        Map<String, byte[]> contentByName = new HashMap<>();

        for (int i = 0; i < fileCount; i++) {
            int entryOff = dirStart + i * DIR_ENTRY_SIZE;
            ByteBuffer entry = ByteBuffer.wrap(bin, entryOff, DIR_ENTRY_SIZE).order(ByteOrder.LITTLE_ENDIAN);
            byte[] nameRaw = new byte[NAME_FIELD_SIZE];
            entry.get(nameRaw);
            String name = cString(nameRaw);
            int size = entry.getInt();
            int offset = entry.getInt();
            entry.getShort();
            entry.getShort();

            if (name.isEmpty() || name.contains("..") || name.contains("/") || name.contains("\\")) {
                throw new IllegalArgumentException("非法文件名: " + name);
            }
            if ("role.json".equals(name)) {
                throw new IllegalArgumentException("检测到 role.json：本校验器仅接受壁纸包");
            }
            if (!names.add(name)) {
                throw new IllegalArgumentException("重复文件: " + name);
            }
            if (size < 0 || offset < 0) {
                throw new IllegalArgumentException("文件表 size/offset 非法: " + name);
            }
            long end = (long) offset + 2 + size;
            if (end > dataLen) {
                throw new IllegalArgumentException("文件越界: " + name);
            }
            int abs = dataStart + offset;
            if (bin[abs] != ZZ0 || bin[abs + 1] != ZZ1) {
                throw new IllegalArgumentException("缺少 0x5A5A magic: " + name);
            }
            byte[] content = new byte[size];
            System.arraycopy(bin, abs + 2, content, 0, size);

            BundleFile bf = new BundleFile();
            bf.setName(name);
            bf.setData(content);
            bf.setSize(size);
            bf.setOffset(offset);
            files.add(bf);
            contentByName.put(name, content);
        }

        if (!names.contains(WallpaperPackConstants.BUNDLE_WALLPAPER_JSON)) {
            throw new IllegalArgumentException("缺少 wallpaper.json");
        }
        if (names.contains("role.json")) {
            throw new IllegalArgumentException("检测到 role.json：本校验器仅接受壁纸包");
        }

        byte[] metaBytes = contentByName.get(WallpaperPackConstants.BUNDLE_WALLPAPER_JSON);
        if (metaBytes == null || metaBytes.length == 0) {
            throw new IllegalArgumentException("wallpaper.json 为空");
        }
        JsonNode root = MAPPER.readTree(metaBytes);
        int format = root.has("format") ? root.get("format").asInt(-1) : -1;
        if (format != 1) {
            throw new IllegalArgumentException("wallpaper.json format 必须为 1");
        }
        String packId = text(root, "pack_id");
        String version = text(root, "version");
        String defaultId = text(root, "default_id");
        if (!PACK_ID_PATTERN.matcher(packId).matches()) {
            throw new IllegalArgumentException("pack_id 格式非法");
        }
        if (version.isEmpty() || version.length() > 31) {
            throw new IllegalArgumentException("version 长度非法");
        }
        if (!ITEM_ID_PATTERN.matcher(defaultId).matches()) {
            throw new IllegalArgumentException("default_id 格式非法");
        }

        JsonNode itemsNode = root.get("items");
        if (itemsNode == null || !itemsNode.isArray()) {
            throw new IllegalArgumentException("items 必须为数组");
        }
        int itemCount = itemsNode.size();
        if (itemCount < 1 || itemCount > WallpaperPackConstants.MAX_WALLPAPER_ITEMS) {
            throw new IllegalArgumentException("items 数量必须在 1..16");
        }

        Set<String> itemIds = new HashSet<>();
        Set<String> referencedFiles = new HashSet<>();
        boolean defaultFound = false;
        for (JsonNode item : itemsNode) {
            String id = text(item, "id");
            String file = text(item, "file");
            if (!ITEM_ID_PATTERN.matcher(id).matches()) {
                throw new IllegalArgumentException("items.id 格式非法: " + id);
            }
            if (!itemIds.add(id)) {
                throw new IllegalArgumentException("items.id 重复: " + id);
            }
            if (file.contains("/") || file.contains("\\") || file.contains("..")) {
                throw new IllegalArgumentException("items.file 非法: " + file);
            }
            if (file.getBytes(StandardCharsets.UTF_8).length > 31) {
                throw new IllegalArgumentException("items.file 过长: " + file);
            }
            if (!referencedFiles.add(file)) {
                throw new IllegalArgumentException("items.file 重复: " + file);
            }
            if (!isAllowedImageFile(file)) {
                throw new IllegalArgumentException("items.file 扩展名非法: " + file);
            }
            if (!contentByName.containsKey(file)) {
                throw new IllegalArgumentException("items 引用的图片不存在: " + file);
            }
            if (defaultId.equals(id)) {
                defaultFound = true;
            }
        }
        if (!defaultFound) {
            throw new IllegalArgumentException("default_id 不在 items 中");
        }

        Set<String> allowedNames = new HashSet<>();
        allowedNames.add(WallpaperPackConstants.BUNDLE_WALLPAPER_JSON);
        allowedNames.addAll(referencedFiles);
        if (!names.equals(allowedNames)) {
            Set<String> extra = new HashSet<>(names);
            extra.removeAll(allowedNames);
            throw new IllegalArgumentException("不允许的额外业务资源: " + extra);
        }
        if (fileCount != allowedNames.size()) {
            throw new IllegalArgumentException("文件数量与 wallpaper.json 声明不一致");
        }

        if (expectedPackId != null && !expectedPackId.isBlank() && !expectedPackId.equals(packId)) {
            throw new IllegalArgumentException("wallpaper.json.pack_id 与请求不一致");
        }
        if (expectedVersion != null && !expectedVersion.isBlank() && !expectedVersion.equals(version)) {
            throw new IllegalArgumentException("wallpaper.json.version 与发布版本不一致");
        }

        BundleInfo info = new BundleInfo();
        info.setPackId(packId);
        info.setVersion(version);
        info.setDefaultId(defaultId);
        info.setFormat(format);
        info.setItemCount(itemCount);
        info.setChecksum16(checksum16);
        info.setPackSize(bin.length);
        info.setFiles(files);
        return info;
    }

    public static byte[] pack(Map<String, byte[]> filesByName) throws IOException {
        if (filesByName == null || filesByName.isEmpty()) {
            throw new IllegalArgumentException("无文件可打包");
        }
        List<Map.Entry<String, byte[]>> list = new ArrayList<>(filesByName.entrySet());
        list.sort(Comparator
                .comparing((Map.Entry<String, byte[]> e) -> extension(e.getKey()))
                .thenComparing(Map.Entry::getKey));

        ByteArrayOutputStream dataArea = new ByteArrayOutputStream();
        int[] offsets = new int[list.size()];
        int[] sizes = new int[list.size()];
        for (int i = 0; i < list.size(); i++) {
            offsets[i] = dataArea.size();
            byte[] content = list.get(i).getValue();
            sizes[i] = content.length;
            dataArea.write(ZZ0);
            dataArea.write(ZZ1);
            dataArea.write(content);
        }
        byte[] dataBytes = dataArea.toByteArray();

        ByteArrayOutputStream dirArea = new ByteArrayOutputStream();
        for (int i = 0; i < list.size(); i++) {
            ByteBuffer entry = ByteBuffer.allocate(DIR_ENTRY_SIZE).order(ByteOrder.LITTLE_ENDIAN);
            byte[] nameBytes = list.get(i).getKey().getBytes(StandardCharsets.UTF_8);
            byte[] namePadded = new byte[NAME_FIELD_SIZE];
            System.arraycopy(nameBytes, 0, namePadded, 0, Math.min(nameBytes.length, NAME_FIELD_SIZE - 1));
            entry.put(namePadded);
            entry.putInt(sizes[i]);
            entry.putInt(offsets[i]);
            entry.putShort((short) 0);
            entry.putShort((short) 0);
            dirArea.write(entry.array());
        }
        byte[] dirBytes = dirArea.toByteArray();
        int combinedLen = dirBytes.length + dataBytes.length;
        int checksum = SpineBundleValidator.checksum16Unsigned(dirBytes, dataBytes);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteBuffer header = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN);
        header.putInt(list.size());
        header.putInt(checksum);
        header.putInt(combinedLen);
        out.write(header.array());
        out.write(dirBytes);
        out.write(dataBytes);
        byte[] result = out.toByteArray();
        if (result.length > WallpaperPackConstants.MAX_PACK_SIZE) {
            throw new IllegalArgumentException("打包结果超过大小上限");
        }
        return result;
    }

    public static Map<String, byte[]> sampleFiles(String packId, String version, String defaultId, String imageName) {
        String json = "{\"format\":1,\"pack_id\":\"" + packId + "\",\"version\":\"" + version
                + "\",\"default_id\":\"" + defaultId + "\",\"items\":[{\"id\":\"" + defaultId
                + "\",\"file\":\"" + imageName + "\"}]}";
        Map<String, byte[]> m = new HashMap<>();
        m.put(WallpaperPackConstants.BUNDLE_WALLPAPER_JSON, json.getBytes(StandardCharsets.UTF_8));
        m.put(imageName, new byte[] {
                (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
                0x00, 0x00, 0x00, 0x00
        });
        return m;
    }

    private static boolean isAllowedImageFile(String file) {
        String lower = file.toLowerCase();
        for (String ext : WallpaperPackConstants.ALLOWED_IMAGE_EXTENSIONS) {
            if (lower.endsWith(ext)) {
                return true;
            }
        }
        return false;
    }

    private static String extension(String filename) {
        int dot = filename.lastIndexOf('.');
        if (dot < 0) {
            return "";
        }
        return filename.substring(dot + 1).toLowerCase();
    }

    private static String cString(byte[] raw) {
        int end = 0;
        while (end < raw.length && raw[end] != 0) {
            end++;
        }
        return new String(raw, 0, end, StandardCharsets.UTF_8).trim();
    }

    private static String text(JsonNode root, String field) {
        JsonNode n = root.get(field);
        if (n == null || !n.isTextual() || n.asText().isBlank()) {
            throw new IllegalArgumentException("wallpaper.json 缺少字段: " + field);
        }
        return n.asText().trim();
    }
}
