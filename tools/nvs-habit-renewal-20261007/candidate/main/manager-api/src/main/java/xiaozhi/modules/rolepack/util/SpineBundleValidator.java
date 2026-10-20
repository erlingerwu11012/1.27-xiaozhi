package xiaozhi.modules.rolepack.util;

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

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import lombok.Data;

/**
 * 客户端 mmap Spine Bundle（与固件 pack_spine.py / generated_spine.bin 同格式）。
 * <pre>
 * [u32 file_count][u32 checksum16][u32 payload_len]
 * [N * {name[32], size[u32], offset[u32], width[u16], height[u16]}]
 * [每个文件：0x5A 0x5A + 原始字节]
 * </pre>
 * little-endian；checksum = 目录表+数据区无符号字节累加的低 16 位
 * （与 ESP32 uint8_t / sum += (b & 0xFF) 一致）。禁止 signed byte 直接累加。
 * 禁止 ZIP：不得将 ZIP 重命名为 spine.bin。
 */
public final class SpineBundleValidator {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final int HEADER_SIZE = 12;
    private static final int DIR_ENTRY_SIZE = 44;
    private static final int NAME_FIELD_SIZE = 32;
    private static final byte ZZ0 = 0x5A;
    private static final byte ZZ1 = 0x5A;

    private SpineBundleValidator() {
    }

    /** 与固件一致：无符号字节累加后取低 16 位 */
    public static int checksum16Unsigned(byte[] data, int off, int len) {
        int sum = 0;
        for (int i = off; i < off + len; i++) {
            sum += (data[i] & 0xFF);
        }
        return sum & 0xFFFF;
    }

    public static int checksum16Unsigned(byte[] a, byte[] b) {
        int sum = 0;
        for (byte v : a) {
            sum += (v & 0xFF);
        }
        for (byte v : b) {
            sum += (v & 0xFF);
        }
        return sum & 0xFFFF;
    }

    /** 旧版错误算法（有符号），仅用于测试证明会与客户端不一致 */
    public static int checksum16SignedBroken(byte[] data, int off, int len) {
        int sum = 0;
        for (int i = off; i < off + len; i++) {
            sum += data[i];
        }
        return sum & 0xFFFF;
    }

    @Data
    public static class BundleFile {
        private String name;
        private byte[] data;
        private int size;
        private int offset;
        private int width;
        private int height;
    }

    @Data
    public static class BundleInfo {
        private String roleId;
        private String version;
        private String format;
        private String spineRuntimeVersion;
        private String skel;
        private String atlas;
        private String png;
        private int fileCount;
        private int checksum16;
        private int packSize;
        private List<BundleFile> files = new ArrayList<>();
    }

    /**
     * 从包内 role.json 读取 pack_id/version 后做完整 mmap 校验。
     */
    public static BundleInfo inspectAndValidate(byte[] bin) throws IOException {
        return validate(bin, null, null);
    }

    /**
     * 解析并严格校验 mmap spine.bin。
     * expectedPackId / expectedVersion 为 null 时仅使用包内 metadata。
     */
    public static BundleInfo validate(byte[] bin, String expectedPackId, String expectedVersion)
            throws IOException {
        if (bin == null || bin.length == 0) {
            throw new IllegalArgumentException("角色包文件为空");
        }
        if (bin.length > RolePackConstants.MAX_PACK_SIZE) {
            throw new IllegalArgumentException("角色包超过大小上限 " + RolePackConstants.MAX_PACK_SIZE + " bytes");
        }
        // 明确拒绝 ZIP（含“ZIP 改名 spine.bin”）
        if (bin.length >= 4 && bin[0] == 'P' && bin[1] == 'K'
                && (bin[2] == 3 || bin[2] == 5 || bin[2] == 7)
                && (bin[3] == 4 || bin[3] == 6 || bin[3] == 8)) {
            throw new IllegalArgumentException("不支持 ZIP：请上传客户端 mmap 格式的 spine.bin（generated_spine.bin）");
        }
        if (bin.length < HEADER_SIZE) {
            throw new IllegalArgumentException("spine.bin 过短：缺少 header");
        }

        ByteBuffer header = ByteBuffer.wrap(bin, 0, HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN);
        int fileCount = header.getInt();
        int checksumField = header.getInt();
        int payloadLen = header.getInt();
        int checksum16 = checksumField & 0xFFFF;

        if (fileCount <= 0 || fileCount > 64) {
            throw new IllegalArgumentException("非法 file_count: " + fileCount);
        }
        if (fileCount != 4) {
            throw new IllegalArgumentException("角色包必须恰好包含 4 个文件，实际: " + fileCount);
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

        // 校验 checksum（无符号，与 ESP32 uint8_t 一致）
        int sum = checksum16Unsigned(bin, dirStart, payloadLen);
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
            int width = entry.getShort() & 0xFFFF;
            int height = entry.getShort() & 0xFFFF;

            if (name.isEmpty() || name.contains("..") || name.contains("/") || name.contains("\\")) {
                throw new IllegalArgumentException("非法文件名: " + name);
            }
            if (!RolePackConstants.BUNDLE_REQUIRED_FILES.contains(name)) {
                throw new IllegalArgumentException("不允许的额外文件: " + name);
            }
            if (!names.add(name)) {
                throw new IllegalArgumentException("重复文件: " + name);
            }
            if (size < 0 || offset < 0) {
                throw new IllegalArgumentException("文件表 size/offset 非法: " + name);
            }
            // offset 相对数据区起点；条目覆盖 0x5A5A + size
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
            bf.setWidth(width);
            bf.setHeight(height);
            files.add(bf);
            contentByName.put(name, content);
        }

        if (names.contains("wallpaper.json")) {
            throw new IllegalArgumentException("检测到 wallpaper.json：本校验器仅接受 Spine 角色包");
        }
        if (!names.equals(RolePackConstants.BUNDLE_REQUIRED_FILES)) {
            Set<String> missing = new HashSet<>(RolePackConstants.BUNDLE_REQUIRED_FILES);
            missing.removeAll(names);
            throw new IllegalArgumentException("缺少必需文件: " + missing);
        }

        byte[] roleJsonBytes = contentByName.get(RolePackConstants.BUNDLE_ROLE_JSON);
        if (roleJsonBytes == null || roleJsonBytes.length == 0) {
            throw new IllegalArgumentException("role.json 为空");
        }
        JsonNode root = MAPPER.readTree(roleJsonBytes);
        BundleInfo info = new BundleInfo();
        info.setRoleId(text(root, "role_id"));
        info.setVersion(text(root, "version"));
        info.setFormat(optionalTextOrNumber(root, "format"));
        info.setSpineRuntimeVersion(optionalTextOrNumber(root, "spine_runtime_version"));
        info.setSkel(text(root, "skel"));
        info.setAtlas(text(root, "atlas"));
        info.setPng(text(root, "png"));
        info.setFileCount(fileCount);
        info.setChecksum16(checksum16);
        info.setPackSize(bin.length);
        info.setFiles(files);

        if (expectedPackId != null && !expectedPackId.isBlank()
                && !expectedPackId.equals(info.getRoleId())) {
            throw new IllegalArgumentException("role.json.role_id 与 pack_id 不一致");
        }
        if (expectedVersion != null && !expectedVersion.isBlank()
                && !expectedVersion.equals(info.getVersion())) {
            throw new IllegalArgumentException("role.json.version 与发布版本不一致");
        }
        if (!RolePackConstants.BUNDLE_SKEL.equals(info.getSkel())
                || !RolePackConstants.BUNDLE_ATLAS.equals(info.getAtlas())
                || !RolePackConstants.BUNDLE_PNG.equals(info.getPng())) {
            throw new IllegalArgumentException("role.json 中 skel/atlas/png 名称必须为固定文件名");
        }
        return info;
    }

    /**
     * 打包与客户端 Assets/Spine mmap 同构的 spine.bin（测试 fixture / 兼容 pack_spine.py）。
     * 排序规则与 AssetsBinaryPacker 一致：(扩展名, 文件名)。
     */
    public static byte[] pack(Map<String, byte[]> filesByName) throws IOException {
        if (filesByName == null || filesByName.isEmpty()) {
            throw new IllegalArgumentException("无文件可打包");
        }
        if (!filesByName.keySet().equals(RolePackConstants.BUNDLE_REQUIRED_FILES)) {
            throw new IllegalArgumentException("打包文件集合必须恰好为四个固定文件");
        }
        List<Map.Entry<String, byte[]>> list = new ArrayList<>(filesByName.entrySet());
        list.sort(Comparator
                .comparing((Map.Entry<String, byte[]> e) -> extension(e.getKey()))
                .thenComparing(Map.Entry::getKey));

        int totalFiles = list.size();
        ByteArrayOutputStream dataArea = new ByteArrayOutputStream();
        int[] offsets = new int[totalFiles];
        int[] sizes = new int[totalFiles];
        for (int i = 0; i < totalFiles; i++) {
            offsets[i] = dataArea.size();
            byte[] content = list.get(i).getValue();
            sizes[i] = content.length;
            dataArea.write(ZZ0);
            dataArea.write(ZZ1);
            dataArea.write(content);
        }
        byte[] dataBytes = dataArea.toByteArray();

        ByteArrayOutputStream dirArea = new ByteArrayOutputStream();
        for (int i = 0; i < totalFiles; i++) {
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

        int checksum = checksum16Unsigned(dirBytes, dataBytes);

        ByteArrayOutputStream out = new ByteArrayOutputStream();
        ByteBuffer header = ByteBuffer.allocate(HEADER_SIZE).order(ByteOrder.LITTLE_ENDIAN);
        header.putInt(totalFiles);
        header.putInt(checksum);
        header.putInt(combinedLen);
        out.write(header.array());
        out.write(dirBytes);
        out.write(dataBytes);
        byte[] result = out.toByteArray();
        if (result.length > RolePackConstants.MAX_PACK_SIZE) {
            throw new IllegalArgumentException("打包结果超过大小上限");
        }
        return result;
    }

    public static String roleJsonSample(String roleId, String version) {
        return "{\"role_id\":\"" + roleId + "\",\"version\":\"" + version
                + "\",\"format\":2,\"spine_runtime_version\":\"4.2\""
                + ",\"skel\":\"skeleton.skel\",\"atlas\":\"skeleton.atlas\",\"png\":\"texture.png\"}";
    }

    public static Map<String, byte[]> sampleFiles(String roleId, String version) {
        Map<String, byte[]> m = new HashMap<>();
        m.put(RolePackConstants.BUNDLE_ROLE_JSON, roleJsonSample(roleId, version).getBytes(StandardCharsets.UTF_8));
        m.put(RolePackConstants.BUNDLE_SKEL, "skel-bytes".getBytes(StandardCharsets.UTF_8));
        m.put(RolePackConstants.BUNDLE_ATLAS, "atlas-bytes".getBytes(StandardCharsets.UTF_8));
        m.put(RolePackConstants.BUNDLE_PNG, new byte[] {
                (byte) 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
                (byte) 0xFF, (byte) 0xFE, (byte) 0x80, 0x00
        });
        return m;
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
            throw new IllegalArgumentException("role.json 缺少字段: " + field);
        }
        return n.asText().trim();
    }

    private static String optionalTextOrNumber(JsonNode root, String field) {
        JsonNode n = root.get(field);
        if (n == null || n.isNull()) {
            return null;
        }
        if (n.isNumber()) {
            return n.asText();
        }
        if (n.isTextual() && !n.asText().isBlank()) {
            return n.asText().trim();
        }
        return null;
    }
}
